"""ADR-0022: service-account credentials, the httpx transport and the start-up decision - all without a network.

The token endpoint is a fake ``fetch``; the transport runs on ``httpx.MockTransport``; the production check is
passed in. What is asserted is what a real rollout depends on: the JWT verifies with the account's public key,
the access token is cached and refreshed, a network error never escapes into the worker, and push stays off
unless it is explicitly and completely configured - and in production only with the separate K3 flag.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import Settings
from app.modules.communications import fcm_google, push_setup
from app.modules.communications.fcm import FcmPushProvider
from app.modules.communications.providers import DisabledPushProvider, get_push_provider, set_push_provider


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def key_file(tmp_path: Path, rsa_key: rsa.RSAPrivateKey) -> Path:
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    path = tmp_path / "sa.json"
    path.write_text(json.dumps({
        "type": "service_account", "project_id": "elchi-file", "private_key_id": "kid-1",
        "private_key": pem, "client_email": "push@elchi-file.iam.gserviceaccount.com",
        "token_uri": "https://evil.example/token",
    }))
    return path


@pytest.fixture(autouse=True)
def _restore_provider():
    yield
    set_push_provider(None)


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


# --- credentials --------------------------------------------------------------------------------------------------


def test_the_assertion_is_an_rs256_jwt_for_the_fcm_scope(key_file: Path, rsa_key: rsa.RSAPrivateKey) -> None:
    account = fcm_google.load_service_account(key_file)
    assert "BEGIN" not in repr(account), "the key never appears in a repr/log"
    jwt = fcm_google.build_assertion(account, now=1_700_000_000)
    header_b64, claims_b64, signature_b64 = jwt.split(".")
    header, claims = json.loads(_b64decode(header_b64)), json.loads(_b64decode(claims_b64))
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "kid-1"}
    assert claims == {
        "iss": "push@elchi-file.iam.gserviceaccount.com", "scope": fcm_google.FCM_SCOPE,
        "aud": "https://oauth2.googleapis.com/token", "iat": 1_700_000_000, "exp": 1_700_003_600,
    }
    rsa_key.public_key().verify(  # raises if the signature is wrong
        _b64decode(signature_b64), f"{header_b64}.{claims_b64}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_the_access_token_is_cached_until_shortly_before_expiry(key_file: Path) -> None:
    clock = {"now": 1_000.0}
    calls: list[tuple[str, dict]] = []

    def fetch(url: str, form: dict) -> tuple[int, dict]:
        calls.append((url, form))
        return 200, {"access_token": f"ya29.{len(calls)}", "expires_in": 3600, "token_type": "Bearer"}

    creds = fcm_google.ServiceAccountCredentials(
        account=fcm_google.load_service_account(key_file), project_id="p", fetch=fetch, clock=lambda: clock["now"]
    )
    assert creds.access_token() == "ya29.1"
    assert calls[0][0] == "https://oauth2.googleapis.com/token", "pinned; the key file's token_uri is ignored"
    assert calls[0][1]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    clock["now"] += 3600 - fcm_google.REFRESH_MARGIN_S - 1
    assert creds.access_token() == "ya29.1" and len(calls) == 1
    clock["now"] += 2
    assert creds.access_token() == "ya29.2" and len(calls) == 2
    creds.invalidate()
    assert creds.access_token() == "ya29.3"


def test_a_refused_or_failed_exchange_yields_no_token(key_file: Path) -> None:
    account = fcm_google.load_service_account(key_file)
    refused = fcm_google.ServiceAccountCredentials(account=account, project_id="p", fetch=lambda u, f: (400, {"error": "invalid_grant"}))
    assert refused.access_token() is None

    def boom(url: str, form: dict) -> tuple[int, dict]:
        raise httpx.ConnectError("no route")

    offline = fcm_google.ServiceAccountCredentials(account=account, project_id="p", fetch=boom)
    assert offline.access_token() is None


@pytest.mark.parametrize("content", ["not json", json.dumps({"type": "authorized_user"}),
                                     json.dumps({"type": "service_account", "client_email": "x", "private_key": "junk"})])
def test_an_unusable_key_file_is_refused_without_echoing_it(tmp_path: Path, content: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(fcm_google.ServiceAccountError) as info:
        fcm_google.load_service_account(path)
    assert "junk" not in str(info.value)


# --- transport ----------------------------------------------------------------------------------------------------


def test_transport_returns_status_and_body_and_turns_network_errors_into_unavailable() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404, json={"error": {"status": "UNREGISTERED"}})

    transport = fcm_google.HttpxTransport(httpx.Client(transport=httpx.MockTransport(handler)))
    status, body = transport.post("https://fcm.googleapis.com/v1/projects/p/messages:send",
                                  headers={"Authorization": "Bearer t"}, json={"message": {"token": "x"}})
    assert (status, body) == (404, {"error": {"status": "UNREGISTERED"}})
    assert json.loads(seen[0].content) == {"message": {"token": "x"}}

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    offline = fcm_google.HttpxTransport(httpx.Client(transport=httpx.MockTransport(down)))
    assert offline.post("https://x", headers={}, json={}) == (503, {"error": {"status": "UNAVAILABLE"}})


# --- start-up decision --------------------------------------------------------------------------------------------


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def test_push_is_disabled_by_default() -> None:
    config = _settings()
    assert config.push_provider == "disabled" and config.push_allow_production is False
    assert push_setup.install_push_provider(config=config, production=False) == "disabled"
    assert isinstance(get_push_provider(), DisabledPushProvider)


def test_fcm_without_a_key_file_stays_disabled() -> None:
    config = _settings(push_provider="fcm", push_fcm_project_id="p")
    assert push_setup.install_push_provider(config=config, production=False) == "disabled"
    assert not get_push_provider().enabled


def test_fcm_with_an_unreadable_key_file_stays_disabled(tmp_path: Path) -> None:
    config = _settings(push_provider="fcm", push_fcm_service_account_file=str(tmp_path / "missing.json"))
    assert push_setup.install_push_provider(config=config, production=False) == "disabled"


def test_fcm_is_installed_outside_production_when_complete(key_file: Path) -> None:
    config = _settings(push_provider="fcm", push_fcm_service_account_file=str(key_file))
    assert push_setup.install_push_provider(config=config, production=False) == "fcm"
    installed = get_push_provider()
    assert isinstance(installed, FcmPushProvider) and installed.enabled
    assert installed.credentials.project_id == "elchi-file", "falls back to the key file's project id"


def test_fcm_is_refused_in_production_without_the_k3_flag(key_file: Path) -> None:
    config = _settings(push_provider="fcm", push_fcm_project_id="p", push_fcm_service_account_file=str(key_file))
    assert push_setup.install_push_provider(config=config, production=True) == "disabled"
    assert not get_push_provider().enabled
    allowed = _settings(push_provider="fcm", push_fcm_project_id="p", push_fcm_service_account_file=str(key_file),
                        push_allow_production=True)
    assert push_setup.install_push_provider(config=allowed, production=True) == "fcm"
    assert get_push_provider().credentials.project_id == "p", "the configured project id wins"


def test_an_unknown_provider_value_is_refused_at_settings_load() -> None:
    with pytest.raises(ValueError, match="ELCHI_PUSH_PROVIDER"):
        _settings(push_provider="expo")
