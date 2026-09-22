"""Pure A7 units: consumer registry tolerance, push payload/provider port, dedup windows, DTO shapes (no DB)."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts.communications import NOTIFICATION_DEDUP_WINDOW, PUSH_PAYLOAD_KEYS
from app.contracts.enums import EventType
from app.modules.communications import dispatch
from app.modules.communications.providers import (
    DisabledPushProvider,
    FakePushProvider,
    PushMessage,
    get_push_provider,
    push_payload,
    set_push_provider,
)
from app.modules.communications.schemas import ChatMessageAdminDTO, NotificationDTO, PushTokenRegister
from app.modules.communications.service import _dedup_window_start


@pytest.fixture(autouse=True)
def _reset():  # noqa: ANN202
    dispatch.reset_registry()
    yield
    dispatch.reset_registry()
    set_push_provider(None)


def test_consumer_modules_contract_value() -> None:
    assert dispatch.CONSUMER_MODULES == ("app.modules.trust_support.consumers", "app.modules.marketplace.feed.consumers")


def test_registry_tolerates_missing_and_broken_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    good = types.ModuleType("elchi_test_good_consumers")

    class Consumer:
        name = "unit.good"
        event_types = frozenset({EventType.LISTING_PUBLISHED})

        def __call__(self, session, event) -> None:  # noqa: ANN001
            return None

    good.CONSUMERS = (Consumer(), object(), Consumer())  # invalid + duplicate name are skipped
    good.RELEVANCE_CHECKS = {EventType.SAVED_SEARCH_MATCHED: lambda s, e: True, "bad": lambda s, e: True}
    monkeypatch.setitem(sys.modules, "elchi_test_good_consumers", good)

    broken = types.ModuleType("elchi_test_broken_consumers")
    monkeypatch.setitem(sys.modules, "elchi_test_broken_consumers", None)  # import raises ImportError

    registry = dispatch.load_registry(("elchi_test_good_consumers", "elchi_test_missing_consumers", "elchi_test_broken_consumers"))
    assert [c.name for c in registry.consumers] == ["unit.good"]
    assert set(registry.relevance_checks) == {EventType.SAVED_SEARCH_MATCHED}
    assert registry.loaded_modules == ("elchi_test_good_consumers",)
    assert registry.failed_modules == ("elchi_test_missing_consumers", "elchi_test_broken_consumers")
    assert dispatch.load_registry(("elchi_test_good_consumers", "elchi_test_missing_consumers", "elchi_test_broken_consumers")) is registry
    assert broken is not None


def test_push_port_defaults_to_disabled_and_payload_is_allowlisted() -> None:
    assert isinstance(get_push_provider(), DisabledPushProvider) and not get_push_provider().enabled
    payload = push_payload(event_type="booking.accepted", aggregate_id="bkg_x", title_key="notification.booking.accepted.title")
    assert set(payload) == PUSH_PAYLOAD_KEYS
    fake = FakePushProvider()
    set_push_provider(fake)
    assert get_push_provider() is fake
    result = fake.send(PushMessage("ntf_x", 1, fake.channel, ("dev_x",), payload))
    assert result.ok and fake.sent
    assert not DisabledPushProvider().send(PushMessage("ntf_x", 1, fake.channel, (), payload)).ok
    set_push_provider(None)
    assert isinstance(get_push_provider(), DisabledPushProvider)


def test_dedup_window_buckets() -> None:
    window = NOTIFICATION_DEDUP_WINDOW
    start = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    assert _dedup_window_start(start) == start
    assert _dedup_window_start(start + window - timedelta(seconds=1)) == start
    assert _dedup_window_start(start + window) == start + window


def test_module_dtos_reject_unknown_fields_and_short_tokens() -> None:
    with pytest.raises(ValueError):
        PushTokenRegister(platform="web", token_or_subscription="short")
    with pytest.raises(ValueError):
        PushTokenRegister(platform="blackberry", token_or_subscription="x" * 32)
    with pytest.raises(ValueError):
        NotificationDTO(id="ntf_x", type="t", title_key="a", body_key="b", params={}, is_read=False,
                        created_at=datetime.now(UTC), link=None, phone="+998")
    assert "author_user_id" in ChatMessageAdminDTO.model_fields
