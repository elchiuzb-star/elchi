"""Contract additions requested during wave 1 (decisions Q16-Q17, BR N2, N3, N5)."""

import pytest

from app.contracts.crypto import (
    PURPOSE_BOOKING_PROOF_CODE,
    KeyRing,
    build_keyring,
    derive_proof_code,
    derive_subkey,
    verify_proof_code,
)
from app.contracts.enums import (
    OPERATOR_COMMAND_CAPABILITY,
    STAFF_ROLE_CAPABILITIES,
    STAFF_ROLES,
    Capability,
    EventType,
    FaultSide,
    OperatorBookingCommand,
    Role,
    role_combination_allowed,
)
from app.contracts.events import (
    CLIENT_REDACTED_PAYLOAD_KEYS,
    EVENT_AUDIENCES,
    EventAudience,
    EventEnvelope,
    payload_for_audience,
)
from app.contracts.state_machines import PASSENGER_BOOKING, reject_no_show_outcome

OLD_MASTER = "old-secret-key-value-123456"
NEW_MASTER = "new-secret-key-value-654321"


# --- Q17 finance role --------------------------------------------------------------

def test_finance_is_a_staff_role() -> None:
    assert Role.FINANCE in STAFF_ROLES
    assert role_combination_allowed([Role.FINANCE, Role.OPERATOR])
    assert not role_combination_allowed([Role.FINANCE, Role.DRIVER])
    assert not role_combination_allowed(["finance", "client"])


def test_finance_capabilities() -> None:
    finance = STAFF_ROLE_CAPABILITIES[Role.FINANCE]
    assert {
        Capability.FINANCE_TOPUP_APPROVE,
        Capability.FINANCE_ADJUSTMENT,
        Capability.FINANCE_ADJUSTMENT_APPROVE,
        Capability.FINANCE_FEE_FINALIZE,
        Capability.FINANCE_REPORTS,
    } <= finance
    assert Capability.FINANCE_COMMISSION_POLICY_MANAGE not in finance  # Q2 stays super_admin
    assert OPERATOR_COMMAND_CAPABILITY[OperatorBookingCommand.FINALIZE_FEE] is Capability.FINANCE_FEE_FINALIZE
    # super_admin acts for finance until the role is wired.
    assert finance <= STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]
    for role in (Role.OPERATOR, Role.ADMIN):
        assert Capability.FINANCE_FEE_FINALIZE not in STAFF_ROLE_CAPABILITIES[role]
        assert Capability.FINANCE_TOPUP_APPROVE not in STAFF_ROLE_CAPABILITIES[role]


# --- N2 / Q16 event audiences ------------------------------------------------------

def test_every_event_has_an_audience_and_money_events_skip_clients() -> None:
    assert set(EVENT_AUDIENCES) == set(EventType)
    for event_type, audiences in EVENT_AUDIENCES.items():
        assert EventAudience.STAFF in audiences
        if event_type.value.startswith(("wallet.", "commission.")):
            assert EventAudience.CLIENT not in audiences, event_type


def test_wallet_event_not_delivered_to_client() -> None:
    payload = {"booking_id": "bkg_x", "amount_minor": 6_000_000, "currency": "UZS"}
    assert payload_for_audience(EventType.WALLET_HOLD_CREATED, payload, EventAudience.CLIENT) is None
    assert payload_for_audience(EventType.WALLET_HOLD_CREATED, payload, EventAudience.DRIVER) == payload


def test_client_booking_copy_strips_commission() -> None:
    from datetime import datetime, timezone

    event = EventEnvelope(
        EventType.BOOKING_ACCEPTED,
        "booking",
        "bkg_x",
        1,
        datetime(2026, 9, 13, tzinfo=timezone.utc),
        {"service_type": "parcel", "service_status": "confirmed", "commission_status": "held"},
    )
    client_copy = event.payload_for(EventAudience.CLIENT)
    assert client_copy == {"service_type": "parcel", "service_status": "confirmed"}
    assert event.payload_for(EventAudience.DRIVER)["commission_status"] == "held"
    assert not (set(client_copy) & CLIENT_REDACTED_PAYLOAD_KEYS)


def test_commission_status_change_not_sent_to_client() -> None:
    payload = {"machine": "commission", "from_status": "held", "to_status": "captured"}
    assert payload_for_audience(EventType.BOOKING_STATUS_CHANGED, payload, EventAudience.CLIENT) is None
    service = {"machine": "service", "from_status": "onboard", "to_status": "arrived"}
    assert payload_for_audience(EventType.BOOKING_STATUS_CHANGED, service, EventAudience.CLIENT) == service


# --- N3 reject_no_show after terminal trip -----------------------------------------

@pytest.mark.parametrize("trip_status", ["completed", "cancelled"])
def test_reject_no_show_after_terminal_trip_cancels_with_driver_fault(trip_status: str) -> None:
    outcome = reject_no_show_outcome(trip_status)
    assert outcome.booking_status == "cancelled"
    assert outcome.fault_side == FaultSide.DRIVER.value
    PASSENGER_BOOKING.assert_transition("awaiting_pickup", "cancelled", command="reject_no_show")


@pytest.mark.parametrize("trip_status", ["planned", "boarding", "in_progress", "interrupted"])
def test_reject_no_show_while_trip_running_keeps_awaiting_pickup(trip_status: str) -> None:
    outcome = reject_no_show_outcome(trip_status)
    assert outcome.booking_status == "awaiting_pickup"
    assert outcome.fault_side is None


def test_reject_no_show_never_leads_to_no_show() -> None:
    assert not PASSENGER_BOOKING.is_allowed_by("awaiting_pickup", "no_show", "reject_no_show")


# --- N5 key rotation window ----------------------------------------------------------

def test_codes_from_previous_secret_verify_during_window() -> None:
    old_key = derive_subkey(OLD_MASTER, PURPOSE_BOOKING_PROOF_CODE)
    shown_before_rotation = derive_proof_code(old_key, "bkg_a", "pickup_code", 0)
    ring = build_keyring(PURPOSE_BOOKING_PROOF_CODE, NEW_MASTER, previous_masters=[OLD_MASTER])
    assert verify_proof_code(ring, "bkg_a", "pickup_code", 0, shown_before_rotation)
    new_code = derive_proof_code(ring.current, "bkg_a", "pickup_code", 0)
    assert verify_proof_code(ring, "bkg_a", "pickup_code", 0, new_code)


def test_codes_from_removed_secret_fail_after_window() -> None:
    old_key = derive_subkey(OLD_MASTER, PURPOSE_BOOKING_PROOF_CODE)
    shown_before_rotation = derive_proof_code(old_key, "bkg_a", "pickup_code", 0)
    ring_after_window = build_keyring(PURPOSE_BOOKING_PROOF_CODE, NEW_MASTER)
    if shown_before_rotation != derive_proof_code(ring_after_window.current, "bkg_a", "pickup_code", 0):
        assert not verify_proof_code(ring_after_window, "bkg_a", "pickup_code", 0, shown_before_rotation)


def test_subkey_version_bump_keeps_previous_version_verifiable() -> None:
    ring = build_keyring(PURPOSE_BOOKING_PROOF_CODE, NEW_MASTER, version=2, previous_versions=[1])
    assert ring.current == derive_subkey(NEW_MASTER, PURPOSE_BOOKING_PROOF_CODE, 2)
    assert ring.previous == (derive_subkey(NEW_MASTER, PURPOSE_BOOKING_PROOF_CODE, 1),)
    v1_code = derive_proof_code(ring.previous[0], "bkg_b", "delivery_code", 3)
    assert verify_proof_code(ring, "bkg_b", "delivery_code", 3, v1_code)


def test_keyring_drops_duplicates() -> None:
    ring = build_keyring(PURPOSE_BOOKING_PROOF_CODE, NEW_MASTER, previous_masters=[NEW_MASTER])
    assert ring == KeyRing(current=ring.current, previous=())
