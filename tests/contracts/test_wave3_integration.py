"""Wave 3 integration pass: contract copies of module DTOs stay identical, dispute audience rule, wiring names."""

import pytest

from app.contracts import dto
from app.contracts.enums import EventType
from app.contracts.events import EVENT_AUDIENCES, EventAudience, payload_for_audience


def _shape(model: type) -> dict[str, tuple[str, object]]:
    return {name: (repr(field.annotation), field.get_default()) for name, field in model.model_fields.items()}


@pytest.mark.parametrize("name", ["PushTokenRegister", "DeviceDTO", "NotificationDTO", "OutboxEventAdminDTO",
                                  "OutboxRetryRequest", "ChatMessageAdminDTO", "ChatHideRequest"])
def test_communications_dto_copies_match_module(name: str) -> None:
    from app.modules.communications import schemas

    module_model = getattr(schemas, name)
    assert module_model is getattr(dto, name) or _shape(module_model) == _shape(getattr(dto, name))


@pytest.mark.parametrize("name", ["FeedMatchDTO", "FeedReputationDTO", "TripAvailabilitySummaryDTO", "FeedPageMeta"])
def test_feed_dto_copies_match_module(name: str) -> None:
    from app.modules.marketplace.feed import schemas

    module_model = getattr(schemas, name)
    assert module_model is getattr(dto, name) or _shape(module_model) == _shape(getattr(dto, name))


def test_commission_dispute_never_reaches_clients_q16() -> None:
    payload = {"booking_id": "bkg_x", "dispute_type": "commission"}
    assert payload_for_audience(EventType.DISPUTE_OPENED, payload, EventAudience.CLIENT) is None
    assert payload_for_audience(EventType.DISPUTE_OPENED, payload, EventAudience.DRIVER) == payload
    service = {"booking_id": "bkg_x", "dispute_type": "service"}
    assert payload_for_audience(EventType.DISPUTE_OPENED, service, EventAudience.CLIENT) == service


def test_dispute_escalation_event_is_staff_only() -> None:
    assert EVENT_AUDIENCES[EventType.DISPUTE_ESCALATION_DUE] == frozenset({EventAudience.STAFF})


def test_wave3_models_are_wired() -> None:
    from app.modules import WIRED_MODEL_MODULES

    for name in ("tracking", "communications", "trust_support", "marketplace.feed"):
        assert f"app.modules.{name}.models" in WIRED_MODEL_MODULES
