"""ADR-0022 on real PostgreSQL: the registration token is sealed at rest, readable only for its own active row,
and a device FCM reports as gone is revoked instead of retried.

No network: the FCM provider runs with a fake transport and fake credentials, but with the *real* token lookup
(``push_setup.make_token_lookup``) reading the sealed column through its own short session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.contracts.enums import ClientPlatform, NotificationChannel
from app.core.secret_box import CURRENT_KEY_VERSION
from app.modules.communications import jobs
from app.modules.communications import service as comms
from app.modules.communications.fcm import FcmPushProvider
from app.modules.communications.providers import PushMessage, PushResult, set_push_provider
from app.modules.communications.push_setup import make_token_lookup
from tests.pg.communications.conftest import accepted_deal, dispatch_all, rows

pytestmark = pytest.mark.pg

TOKEN = "fcm-registration-token-0001:APA91bHUNIT"


def _register(bw, user_id: int, token: str = TOKEN, platform: str = "android") -> str:  # noqa: ANN001
    with bw.db.session() as s:
        device = comms.register_device(s, user_id=user_id, platform=platform, token=token, app_version="2.0.0")
        public_id = comms.device_public_id(device)
        s.commit()
    return public_id


def _lookup(bw, device_public_id: str) -> str | None:  # noqa: ANN001
    with bw.db.session() as s:
        return comms.device_push_token(s, device_public_id)


def test_register_seals_the_token_and_only_its_own_row_can_open_it(bw) -> None:  # noqa: ANN001
    device = _register(bw, bw.w.driver_id)
    row = rows(bw.db, "SELECT public_id, token_hash, token_cipher, token_key_version FROM device_tokens")[0]
    assert row.token_cipher is not None and row.token_key_version == CURRENT_KEY_VERSION
    assert TOKEN.encode() not in bytes(row.token_cipher), "the raw token is never stored"
    assert _lookup(bw, device) == TOKEN

    # A ciphertext copied onto another row does not authenticate (AAD = the row's public id).
    other = _register(bw, bw.w.client_id, token="another-device-token-0002", platform="ios")
    with bw.db.engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE device_tokens SET token_cipher = (SELECT token_cipher FROM device_tokens WHERE platform = 'android') "
            "WHERE platform = 'ios'"
        )
    assert _lookup(bw, other) is None
    assert _lookup(bw, "dev_not-a-real-id") is None


def test_re_register_reseals_and_a_legacy_row_fills_on_the_next_registration(bw) -> None:  # noqa: ANN001
    device = _register(bw, bw.w.driver_id)
    # Simulate a row registered before 0073: hash only, no cipher -> cannot push (a skip, not an error).
    with bw.db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE device_tokens SET token_cipher = NULL, token_key_version = NULL")
    assert _lookup(bw, device) is None

    again = _register(bw, bw.w.driver_id)  # same user, same token: same row, cipher written again
    assert again == device
    assert _lookup(bw, device) == TOKEN

    # The token moves to another account: new public id, re-sealed for it; the old id no longer resolves.
    moved = _register(bw, bw.w.client_id)
    assert moved != device
    assert _lookup(bw, moved) == TOKEN
    assert _lookup(bw, device) is None
    assert rows(bw.db, "SELECT count(*) AS n FROM device_tokens")[0].n == 1


def test_revoked_device_has_no_token(bw) -> None:  # noqa: ANN001
    device = _register(bw, bw.w.driver_id)
    with bw.db.session() as s:
        comms.revoke_device(s, device_public_id_value=device, user_id=bw.w.driver_id)
        s.commit()
    assert _lookup(bw, device) is None


@dataclass
class GoneProvider:
    """Reports every device as gone, the way the FCM adapter does for ``UNREGISTERED``."""

    name: str = "gone"
    channel: NotificationChannel = NotificationChannel.WEB_PUSH
    platforms: frozenset[ClientPlatform] = frozenset({ClientPlatform.ANDROID, ClientPlatform.IOS, ClientPlatform.WEB})
    enabled: bool = True
    sent: list[PushMessage] = field(default_factory=list)

    def send(self, message: PushMessage) -> PushResult:
        self.sent.append(message)
        return PushResult(False, "UNREGISTERED", gone_device_ids=message.device_ids, retryable=False)


def _push_rows(bw) -> list:  # noqa: ANN001
    return rows(bw.db, "SELECT status, attempts, last_error FROM notification_deliveries WHERE channel <> 'in_app' ORDER BY id")


def test_a_gone_device_is_revoked_and_the_delivery_is_not_retried(bw) -> None:  # noqa: ANN001
    provider = GoneProvider()
    set_push_provider(provider)
    _register(bw, bw.w.driver_id)
    accepted_deal(bw)
    dispatch_all(bw.db)
    assert jobs.deliver_push_batch(engine=bw.db.engine, provider=provider) > 0

    assert rows(bw.db, "SELECT revoked_at FROM device_tokens")[0].revoked_at is not None, "same effect as DELETE /devices/{id}"
    attempted = [r for r in _push_rows(bw) if r.attempts]
    assert attempted and all(r.status == "dead" and r.last_error == "UNREGISTERED" and r.attempts == 1 for r in attempted)
    # Nothing is left to send to: another round claims nothing and makes no call.
    before = len(provider.sent)
    jobs.deliver_push_batch(engine=bw.db.engine, provider=provider)
    assert len(provider.sent) == before


class _FakeTransport:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code, self.body = status_code, body
        self.tokens: list[str] = []

    def post(self, url: str, *, headers: dict, json: dict) -> tuple[int, dict]:
        self.tokens.append(json["message"]["token"])
        return self.status_code, self.body


class _FakeCredentials:
    project_id = "elchi-test"

    def access_token(self) -> str:
        return "ya29.fake"


def test_fcm_provider_reads_the_sealed_token_and_revokes_an_unregistered_device(bw) -> None:  # noqa: ANN001
    transport = _FakeTransport(404, {"error": {"status": "UNREGISTERED"}})
    provider = FcmPushProvider(credentials=_FakeCredentials(), transport=transport, token_lookup=make_token_lookup(bw.db.engine))
    set_push_provider(provider)
    _register(bw, bw.w.driver_id)
    accepted_deal(bw)
    dispatch_all(bw.db)
    assert jobs.deliver_push_batch(engine=bw.db.engine, provider=provider) > 0

    assert transport.tokens and set(transport.tokens) == {TOKEN}, "FCM receives the decrypted registration token"
    assert rows(bw.db, "SELECT revoked_at FROM device_tokens")[0].revoked_at is not None
    assert {r.status for r in _push_rows(bw) if r.attempts} == {"dead"}


def test_fcm_provider_delivers_with_the_decrypted_token(bw) -> None:  # noqa: ANN001
    transport = _FakeTransport(200, {"name": "projects/elchi-test/messages/1"})
    provider = FcmPushProvider(credentials=_FakeCredentials(), transport=transport, token_lookup=make_token_lookup(bw.db.engine))
    set_push_provider(provider)
    _register(bw, bw.w.driver_id)
    accepted_deal(bw)
    dispatch_all(bw.db)
    assert jobs.deliver_push_batch(engine=bw.db.engine, provider=provider) > 0
    assert set(transport.tokens) == {TOKEN}
    assert rows(bw.db, "SELECT revoked_at FROM device_tokens")[0].revoked_at is None
    assert {r.status for r in _push_rows(bw) if r.attempts} == {"sent"}
