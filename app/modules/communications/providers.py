"""Push provider port (ADR-0012 §9; U3 pending).

No real provider (Web Push VAPID / FCM / Expo) is wired and no dependency is added until the U3 decision, which
also decides how the raw token/subscription is stored (``device_tokens`` keeps only a SHA-256 hash today).
The default provider is :class:`DisabledPushProvider`: the dispatcher then creates no push deliveries and the in-app
inbox is the only channel. :class:`FakePushProvider` exists for tests and local demos.

A provider is called by ``communications.jobs`` OUTSIDE any DB transaction (claim -> commit -> send -> result tx).
A push is never proof of a transaction (spec §16) and its failure never touches bookings or money (AC34).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.contracts.communications import PUSH_PAYLOAD_KEYS
from app.contracts.enums import ClientPlatform, NotificationChannel


@dataclass(frozen=True, slots=True)
class PushMessage:
    delivery_id: str  # ntf_ public id
    user_id: int
    channel: NotificationChannel
    device_ids: tuple[str, ...]  # dev_ public ids (raw tokens are not stored until U3)
    payload: dict[str, Any]  # only communications.PUSH_PAYLOAD_KEYS


@dataclass(frozen=True, slots=True)
class PushResult:
    ok: bool
    error: str | None = None


class PushProvider(Protocol):
    name: str
    channel: NotificationChannel
    platforms: frozenset[ClientPlatform]
    enabled: bool

    def send(self, message: PushMessage) -> PushResult: ...


class DisabledPushProvider:
    """Default until U3: no push channel."""

    name = "disabled"
    channel = NotificationChannel.WEB_PUSH
    platforms: frozenset[ClientPlatform] = frozenset()
    enabled = False

    def send(self, message: PushMessage) -> PushResult:
        return PushResult(False, "push_provider_disabled")


@dataclass
class FakePushProvider:
    """Test/demo provider: records messages; ``fail`` makes every send fail, ``raise_error`` makes it raise."""

    name: str = "fake"
    channel: NotificationChannel = NotificationChannel.WEB_PUSH
    platforms: frozenset[ClientPlatform] = frozenset({ClientPlatform.WEB, ClientPlatform.ANDROID, ClientPlatform.IOS})
    enabled: bool = True
    fail: bool = False
    raise_error: bool = False
    sent: list[PushMessage] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def send(self, message: PushMessage) -> PushResult:
        if self.raise_error:
            raise RuntimeError("fake push provider exploded")
        if self.fail:
            return PushResult(False, "fake_provider_failure")
        with self._lock:
            self.sent.append(message)
        return PushResult(True)


_provider: PushProvider = DisabledPushProvider()


def get_push_provider() -> PushProvider:
    return _provider


def set_push_provider(provider: PushProvider | None) -> None:
    """Install a provider (tests, or the integrator after U3); ``None`` restores the disabled default."""
    global _provider
    _provider = DisabledPushProvider() if provider is None else provider


def push_payload(*, event_type: str, aggregate_id: str, title_key: str) -> dict[str, Any]:
    payload = {"event_type": event_type, "aggregate_id": aggregate_id, "title_key": title_key}
    assert set(payload) <= PUSH_PAYLOAD_KEYS
    return payload
