"""Wave 2 contract additions: operator signal events (§9.5), Q54 accept alias as implemented by A4."""

import pytest
from pydantic import ValidationError

from app.contracts.enums import EventType
from app.contracts.events import EVENT_AUDIENCES, EVENT_PAYLOAD_ALLOWLIST, EventAudience, payload_for_audience


@pytest.mark.parametrize(
    ("event_type", "value"),
    [
        (EventType.BOOKING_CONFIRMATION_OVERDUE, "booking.confirmation_overdue"),
        (EventType.WALLET_HOLD_ESCALATION_DUE, "wallet.hold.escalation_due"),
    ],
)
def test_signal_events_are_staff_only(event_type: EventType, value: str) -> None:
    assert event_type.value == value
    assert EVENT_AUDIENCES[event_type] == frozenset({EventAudience.STAFF})
    assert event_type in EVENT_PAYLOAD_ALLOWLIST
    assert payload_for_audience(event_type, {"booking_id": "bkg_x"}, EventAudience.CLIENT) is None
    assert payload_for_audience(event_type, {"booking_id": "bkg_x"}, EventAudience.DRIVER) is None


def test_accept_request_terms_version_alias_q54() -> None:
    from app.modules.bookings.schemas import AcceptRequest

    legacy = AcceptRequest(proposal_version_id="prv_x", expected_listing_version=3)
    alias = AcceptRequest(proposal_version_id="prv_x", expected_listing_terms_version=3)
    both = AcceptRequest(proposal_version_id="prv_x", expected_listing_version=3, expected_listing_terms_version=3)
    assert legacy.terms_version == alias.terms_version == both.terms_version == 3
    with pytest.raises(ValidationError):
        AcceptRequest(proposal_version_id="prv_x", expected_listing_version=3, expected_listing_terms_version=4)
    with pytest.raises(ValidationError):
        AcceptRequest(proposal_version_id="prv_x")
