import pytest

from app.contracts.enums import BookingAction
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.state_machines import (
    ALL_MACHINES,
    CASH_COLLECTION,
    COMMISSION,
    CUSTODY_CASE,
    DISPUTE,
    LISTING,
    NO_SHOW_REVIEW,
    PARCEL_BOOKING,
    PASSENGER_BOOKING,
    PROPOSAL_VERSION,
    TRIP,
    StateMachine,
    booking_blocks_trip_completion,
)


def _reachable(machine: StateMachine) -> set[str]:
    seen = set(machine.initial)
    frontier = list(machine.initial)
    while frontier:
        state = frontier.pop()
        for transition in machine.transitions:
            if transition.source == state and transition.target not in seen:
                seen.add(transition.target)
                frontier.append(transition.target)
    return seen


@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_every_state_is_reachable(machine: StateMachine) -> None:
    assert _reachable(machine) == {state.value for state in machine.states}


def test_terminal_states() -> None:
    assert LISTING.terminal == {"expired", "cancelled"}
    assert PROPOSAL_VERSION.terminal == {"superseded", "accepted", "rejected", "withdrawn", "expired"}
    assert TRIP.terminal == {"completed", "cancelled"}
    assert PASSENGER_BOOKING.terminal == {"completed", "cancelled", "no_show"}
    assert NO_SHOW_REVIEW.terminal == {"confirmed", "rejected"}
    assert PARCEL_BOOKING.terminal == {"completed", "cancelled", "returned"}
    assert CUSTODY_CASE.terminal == {"resolved"}
    assert CASH_COLLECTION.terminal == {"acknowledged"}
    assert COMMISSION.terminal == {"exempt", "released", "reversed"}
    assert DISPUTE.terminal == {"resolved", "rejected"}


@pytest.mark.parametrize("custody_state", ["picked_up", "in_transit", "delivery_failed", "return_required"])
def test_parcel_in_custody_cannot_be_cancelled_ac22(custody_state: str) -> None:
    assert not PARCEL_BOOKING.is_allowed(custody_state, "cancelled")
    with pytest.raises(DomainError) as exc:
        PARCEL_BOOKING.assert_transition(custody_state, "cancelled")
    assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION


def test_pickup_cannot_complete_delivery_directly() -> None:
    assert not PARCEL_BOOKING.is_allowed("awaiting_pickup", "delivered")
    assert not PARCEL_BOOKING.is_allowed("picked_up", "completed")


def test_no_show_only_via_operator_confirm_decision_7() -> None:
    to_no_show = [t for t in PASSENGER_BOOKING.transitions if t.target == "no_show"]
    assert [(t.source, t.command) for t in to_no_show] == [("awaiting_pickup", "confirm_no_show")]
    # The driver's report is not a service-status transition.
    assert all(t.command != BookingAction.REPORT_NO_SHOW.value for t in PASSENGER_BOOKING.transitions)
    with pytest.raises(DomainError):
        PASSENGER_BOOKING.assert_transition("awaiting_pickup", "no_show", command="report_no_show")
    PASSENGER_BOOKING.assert_transition("awaiting_pickup", "no_show", command="confirm_no_show")


def test_no_show_review_paths_d2() -> None:
    assert NO_SHOW_REVIEW.commands_from("pending") == {"confirm_no_show", "reject_no_show", "system_close_boarded"}
    # After a rejected review the booking is still awaiting_pickup and can board or be cancelled.
    assert PASSENGER_BOOKING.commands_from("awaiting_pickup") >= {"board", "cancel"}


def test_passenger_cannot_cancel_once_onboard() -> None:
    assert not PASSENGER_BOOKING.is_allowed("onboard", "cancelled")
    assert not PASSENGER_BOOKING.is_allowed("arrived", "cancelled")


def test_commission_rules() -> None:
    assert not COMMISSION.is_allowed("captured", "released")
    assert not COMMISSION.is_allowed("released", "captured")
    assert not COMMISSION.is_allowed("exempt", "held")
    # D10: amendments adjust the one existing hold; D4: repeated partial reversals.
    assert COMMISSION.is_allowed_by("held", "held", "adjust_hold")
    assert COMMISSION.is_allowed_by("partially_reversed", "partially_reversed", "reverse_partial")


def test_dispute_machine_has_no_reopen_or_restore() -> None:
    assert not DISPUTE.is_allowed("resolved", "open")
    assert not DISPUTE.is_allowed("rejected", "under_review")
    assert all(t.command != "restore_previous_status" for m in ALL_MACHINES for t in m.transitions)


def test_trip_completion_is_only_from_running_states() -> None:
    sources = {t.source for t in TRIP.transitions if t.target == "completed"}
    assert sources == {"in_progress", "interrupted"}


@pytest.mark.parametrize(
    ("service", "status", "custody", "review", "blocks"),
    [
        ("parcel", "delivered", False, False, False),
        ("parcel", "returned", False, False, False),
        ("parcel", "in_transit", False, False, True),
        ("parcel", "picked_up", True, False, True),
        ("parcel", "delivery_failed", False, False, True),
        ("parcel", "delivery_failed", True, False, False),  # D1
        ("parcel", "return_required", True, False, False),  # D1
        ("passenger", "arrived", False, False, False),
        ("passenger", "no_show", False, False, False),
        ("passenger", "onboard", False, False, True),
        ("passenger", "awaiting_pickup", False, False, True),
        ("passenger", "awaiting_pickup", False, True, False),
        ("passenger", "confirmed", False, True, True),
    ],
)
def test_trip_completion_guard_ac42_d1(service: str, status: str, custody: bool, review: bool, blocks: bool) -> None:
    assert (
        booking_blocks_trip_completion(service, status, has_open_custody_case=custody, has_pending_no_show_review=review)
        is blocks
    )


def test_cash_status_is_independent_of_service() -> None:
    assert CASH_COLLECTION.commands_from("contested") == {"resolve_paid", "resolve_unpaid"}
