"""FCM push adapter (ADR-0022, user decision 17.09.2026).

Deliberately split in two so the parts that carry rules can be tested without ever contacting Google:

* :func:`build_request` turns a :class:`PushMessage` into the FCM HTTP v1 body. It enforces the payload
  allowlist (§15) itself rather than trusting the caller, so a future change cannot leak a phone number or a
  proof code into a notification;
* :func:`classify` turns an FCM response into "retry", "give up" or "this device is gone", which is what the
  outbox needs to know;
* :class:`FcmPushProvider` wires them to a transport. The transport is injected, so tests use a fake and no
  test in this repository can make a network call.

**Not enabled.** Without credentials the provider reports ``enabled = False`` and ``send`` refuses, so
importing this module changes nothing. Turning it on needs a service account, the K3 legal review recorded in
ADR-0022, and the outbox flag - three things a coding agent does not get to do on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.contracts.communications import PUSH_PAYLOAD_KEYS
from app.contracts.enums import ClientPlatform, NotificationChannel
from app.modules.communications.providers import PushMessage, PushResult

FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

#: FCM answers with these when the registration token is no longer usable; the device row should be revoked
#: rather than retried forever (the outbox would otherwise keep a dead device in the queue).
GONE_ERRORS = frozenset({"UNREGISTERED", "INVALID_ARGUMENT", "SENDER_ID_MISMATCH"})
#: Transient: the outbox should retry with its existing backoff.
RETRY_ERRORS = frozenset({"UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED", "DEADLINE_EXCEEDED"})


class Transport(Protocol):
    """Minimal seam over the HTTP call: ``(url, headers, json) -> (status_code, body)``."""

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> tuple[int, dict[str, Any]]: ...


class Credentials(Protocol):
    """Supplies a Google OAuth2 access token for the service account. ``None`` means "not configured"."""

    project_id: str

    def access_token(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Verdict:
    retry: bool
    device_gone: bool
    error: str | None


def build_request(message: PushMessage, *, token: str) -> dict[str, Any]:
    """FCM HTTP v1 body for one device.

    The notification carries a *key*, not a sentence: the client renders the text, so no user data and no
    localized string ever leaves the platform. ``data`` is checked against the allowlist here, on the way out,
    because this is the last place the rule can still be enforced (§15, AC34).
    """
    leaked = set(message.payload) - PUSH_PAYLOAD_KEYS
    if leaked:
        raise ValueError(f"refusing to send keys outside the push allowlist: {sorted(leaked)}")
    return {
        "message": {
            "token": token,
            # No "notification" block: an OS-rendered title would have to contain real text. The client app
            # turns title_key into words it already ships, so the payload stays free of user data.
            "data": {key: str(value) for key, value in message.payload.items()},
            "android": {"priority": "high", "ttl": "3600s"},
        }
    }


def classify(status_code: int, body: dict[str, Any]) -> Verdict:
    """What the outbox should do with this response."""
    if 200 <= status_code < 300:
        return Verdict(retry=False, device_gone=False, error=None)
    status = str(((body or {}).get("error") or {}).get("status") or "")
    if status in GONE_ERRORS or status_code in {400, 404}:
        return Verdict(retry=False, device_gone=True, error=status or f"http_{status_code}")
    if status in RETRY_ERRORS or status_code == 429 or status_code >= 500:
        return Verdict(retry=True, device_gone=False, error=status or f"http_{status_code}")
    if status_code in {401, 403}:
        # Our own credentials are wrong: retrying will not fix it and the device is innocent.
        return Verdict(retry=False, device_gone=False, error=status or f"http_{status_code}")
    return Verdict(retry=True, device_gone=False, error=status or f"http_{status_code}")


@dataclass
class FcmPushProvider:
    """``PushProvider`` implementation. Inert until credentials and a transport are supplied."""

    credentials: Credentials | None = None
    transport: Transport | None = None
    token_lookup: Any = None  # Callable[[str], str | None]: device public id -> decrypted registration token
    name: str = "fcm"
    channel: NotificationChannel = NotificationChannel.WEB_PUSH
    platforms: frozenset[ClientPlatform] = field(
        default_factory=lambda: frozenset({ClientPlatform.ANDROID, ClientPlatform.IOS, ClientPlatform.WEB})
    )
    last_verdict: Verdict | None = None

    @property
    def enabled(self) -> bool:
        return self.credentials is not None and self.transport is not None and self.token_lookup is not None

    def send(self, message: PushMessage) -> PushResult:
        if not self.enabled:
            return PushResult(False, "fcm_not_configured")
        access_token = self.credentials.access_token()
        if not access_token:
            return PushResult(False, "fcm_no_access_token")
        url = FCM_ENDPOINT.format(project_id=self.credentials.project_id)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        failures: list[str] = []
        delivered = 0
        for device_id in message.device_ids:
            token = self.token_lookup(device_id)
            if not token:
                # Registered before 0073, or the ciphertext did not authenticate: nothing to send to.
                failures.append("device_token_unavailable")
                continue
            status_code, body = self.transport.post(url, headers=headers, json=build_request(message, token=token))
            verdict = classify(status_code, body)
            self.last_verdict = verdict
            if verdict.error is None:
                delivered += 1
            else:
                failures.append(verdict.error)
        if delivered:
            return PushResult(True)
        return PushResult(False, failures[0] if failures else "fcm_no_devices")
