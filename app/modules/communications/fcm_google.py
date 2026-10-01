"""Google side of the FCM adapter (ADR-0022): service-account OAuth2 credentials and an httpx transport.

No ``google-auth`` dependency: the service-account flow is one RS256-signed JWT exchanged at Google's token
endpoint (RFC 7523), and both pieces already ship in pinned packages - ``cryptography`` signs, ``httpx`` posts.

* :class:`ServiceAccountCredentials` implements ``fcm.Credentials``. It signs a JWT assertion with the service
  account's private key, exchanges it at :data:`TOKEN_URI` for an access token and caches that token until
  :data:`REFRESH_MARGIN_S` before it expires. The HTTP call is injected (``fetch``), so tests never reach Google.
* :class:`HttpxTransport` implements ``fcm.Transport``. A network error becomes a synthetic ``503 UNAVAILABLE``
  so the batch continues and the outbox retries with its backoff instead of the worker catching an exception.

Nothing here logs a token, the assertion or the key. Neither class is created on import: only
``communications.push_setup`` builds them, and only when ``ELCHI_PUSH_PROVIDER=fcm`` and the config is complete.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)

#: Pinned rather than read from the key file: a tampered file must not be able to send our signed assertion
#: (and the private key id) somewhere else.
TOKEN_URI = "https://oauth2.googleapis.com/token"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ASSERTION_LIFETIME_S = 3600  # Google's maximum
REFRESH_MARGIN_S = 300  # refresh this long before the token expires
HTTP_TIMEOUT_S = 10.0

#: ``(url, form) -> (status_code, json_body)``
FormPost = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]


class ServiceAccountError(ValueError):
    """The service-account file is missing, unreadable or not an RSA service-account key."""


@dataclass(frozen=True)
class ServiceAccount:
    client_email: str
    private_key_id: str | None
    private_key: rsa.RSAPrivateKey = field(repr=False)
    project_id: str | None

    def __repr__(self) -> str:  # never print the key object
        return f"ServiceAccount(client_email={self.client_email!r}, project_id={self.project_id!r})"


def load_service_account(path: str | Path) -> ServiceAccount:
    """Parse a Google service-account JSON key file. Raises :class:`ServiceAccountError` with no key material."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServiceAccountError(f"service account file is not readable JSON ({type(exc).__name__})") from None
    if not isinstance(raw, dict) or raw.get("type") != "service_account":
        raise ServiceAccountError("file is not a service_account key")
    email, pem = raw.get("client_email"), raw.get("private_key")
    if not isinstance(email, str) or not email or not isinstance(pem, str) or not pem:
        raise ServiceAccountError("service account key lacks client_email or private_key")
    try:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except (ValueError, TypeError):
        raise ServiceAccountError("private_key is not a readable PEM key") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ServiceAccountError("private_key is not an RSA key (RS256 needs RSA)")
    project_id = raw.get("project_id") if isinstance(raw.get("project_id"), str) else None
    key_id = raw.get("private_key_id") if isinstance(raw.get("private_key_id"), str) else None
    return ServiceAccount(client_email=email, private_key_id=key_id, private_key=key, project_id=project_id)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_assertion(account: ServiceAccount, *, now: float, scope: str = FCM_SCOPE) -> str:
    """RS256 JWT for the OAuth2 JWT-bearer grant (``iss`` = the service account, ``aud`` = :data:`TOKEN_URI`)."""
    header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
    if account.private_key_id:
        header["kid"] = account.private_key_id
    issued = int(now)
    claims = {
        "iss": account.client_email,
        "scope": scope,
        "aud": TOKEN_URI,
        "iat": issued,
        "exp": issued + ASSERTION_LIFETIME_S,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    )
    signature = account.private_key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


def httpx_form_post(url: str, form: dict[str, str], *, timeout: float = HTTP_TIMEOUT_S) -> tuple[int, dict[str, Any]]:
    """Default ``fetch`` for :class:`ServiceAccountCredentials`."""
    response = httpx.post(url, data=form, timeout=timeout)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


@dataclass
class ServiceAccountCredentials:
    """``fcm.Credentials`` backed by a service account. Thread-safe; one token exchange per expiry window."""

    account: ServiceAccount
    project_id: str
    fetch: FormPost = httpx_form_post
    clock: Callable[[], float] = time.time
    _token: str | None = field(default=None, init=False, repr=False)
    _expires_at: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def access_token(self) -> str | None:
        with self._lock:
            now = self.clock()
            if self._token and now < self._expires_at - REFRESH_MARGIN_S:
                return self._token
            form = {"grant_type": JWT_BEARER_GRANT, "assertion": build_assertion(self.account, now=now)}
            try:
                status_code, body = self.fetch(TOKEN_URI, form)
            except httpx.HTTPError as exc:
                logger.warning("fcm_token_exchange_failed error=%s", type(exc).__name__)
                return None
            token, expires_in = body.get("access_token"), body.get("expires_in")
            if status_code != 200 or not isinstance(token, str) or not token:
                # Google's error code only ("invalid_grant" ...); the description can echo the account.
                logger.warning("fcm_token_exchange_refused status=%s error=%s", status_code, body.get("error"))
                self._token, self._expires_at = None, 0.0
                return None
            lifetime = expires_in if isinstance(expires_in, int) and expires_in > 0 else ASSERTION_LIFETIME_S
            self._token, self._expires_at = token, now + lifetime
            return token

    def invalidate(self) -> None:
        """Forget the cached token (FCM answered 401: it may have been revoked early)."""
        with self._lock:
            self._token, self._expires_at = None, 0.0


class HttpxTransport:
    """``fcm.Transport`` over a shared :class:`httpx.Client` (connection reuse across a batch)."""

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = HTTP_TIMEOUT_S) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            response = self._client.post(url, headers=headers, json=json)
        except httpx.HTTPError as exc:
            logger.warning("fcm_transport_error error=%s", type(exc).__name__)
            return 503, {"error": {"status": "UNAVAILABLE"}}
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.status_code, body if isinstance(body, dict) else {}

    def close(self) -> None:
        self._client.close()
