"""Pure booking rules (Q44 contact timeline, Q7 no-show guard, Q19 reopen, AC22, proofs, fees). No DB."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.enums import ActorSide, BookingAction, FaultSide, ProofKind, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.bookings import rules

T0 = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)


# --- Q44 phone reveal timeline ------------------------------------------------------------------------------------


def test_q44_no_phones_before_service_start() -> None:
    visibility = rules.contact_visibility(service_started_at=None, service_terminal_at=None, now=T0)
    assert visibility == rules.ContactVisibility(False, None, None)
    for service in ServiceType:
        disclosure = rules.phone_disclosure(service, visibility)
        assert not (disclosure.driver_phone_to_client or disclosure.client_phone_to_driver or disclosure.receiver_phone_to_driver)


def test_q44_phones_revealed_at_start_and_hidden_24h_after_terminal() -> None:
    started, terminal = T0, T0 + timedelta(hours=3)
    during = rules.contact_visibility(service_started_at=started, service_terminal_at=None, now=T0 + timedelta(hours=1))
    assert during.phones_visible and during.visible_from == started and during.visible_until is None
    just_before = rules.contact_visibility(
        service_started_at=started, service_terminal_at=terminal, now=terminal + timedelta(hours=24) - timedelta(seconds=1)
    )
    assert just_before.phones_visible and just_before.visible_until == terminal + timedelta(hours=24)
    after = rules.contact_visibility(service_started_at=started, service_terminal_at=terminal, now=terminal + timedelta(hours=24))
    assert not after.phones_visible


def test_q44_parcel_sender_phone_never_to_driver_receiver_only_after_pickup() -> None:
    before = rules.contact_visibility(service_started_at=None, service_terminal_at=None, now=T0)
    after_pickup = rules.contact_visibility(service_started_at=T0, service_terminal_at=None, now=T0 + timedelta(minutes=5))
    assert rules.phone_disclosure(ServiceType.PARCEL, before).receiver_phone_to_driver is False
    disclosure = rules.phone_disclosure(ServiceType.PARCEL, after_pickup)
    assert disclosure.receiver_phone_to_driver and disclosure.driver_phone_to_client
    assert disclosure.client_phone_to_driver is False  # the sender is the client: never shown to the driver
    passenger = rules.phone_disclosure(ServiceType.PASSENGER, after_pickup)
    assert passenger.client_phone_to_driver and passenger.driver_phone_to_client and not passenger.receiver_phone_to_driver


def test_started_statuses_match_q44_start_points() -> None:
    assert rules.has_started(ServiceType.PASSENGER, "onboard") and not rules.has_started(ServiceType.PASSENGER, "awaiting_pickup")
    assert rules.has_started(ServiceType.PARCEL, "picked_up") and not rules.has_started(ServiceType.PARCEL, "awaiting_pickup")


def test_first_name_only() -> None:
    assert rules.first_name("Dilshod Rahimov", "Haydovchi") == "Dilshod"
    assert rules.first_name(None, "Mijoz") == "Mijoz"


# --- cancellation (AC22, Q19) ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["picked_up", "in_transit", "delivery_failed", "return_required"])
def test_ac22_parcel_in_custody_cannot_be_cancelled(status: str) -> None:
    with pytest.raises(DomainError) as info:
        rules.ensure_cancellable(ServiceType.PARCEL, status)
    assert info.value.code is ErrorCode.CUSTODY_REQUIRES_RETURN_FLOW


def test_pre_service_cancel_allowed_and_post_start_refused() -> None:
    rules.ensure_cancellable(ServiceType.PASSENGER, "confirmed")
    rules.ensure_cancellable(ServiceType.PARCEL, "awaiting_pickup")
    with pytest.raises(DomainError) as info:
        rules.ensure_cancellable(ServiceType.PASSENGER, "onboard")
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION


def test_q19_request_reopens_only_after_driver_or_operator_cancel_in_window() -> None:
    kwargs = dict(listing_expires_at=T0 + timedelta(hours=2), departure_window_end=T0 + timedelta(hours=3), now=T0)
    assert rules.request_listing_reopens(cancelled_by=ActorSide.DRIVER, **kwargs)
    assert rules.request_listing_reopens(cancelled_by=ActorSide.OPERATOR, **kwargs)
    assert not rules.request_listing_reopens(cancelled_by=ActorSide.CLIENT, **kwargs)
    assert not rules.request_listing_reopens(
        cancelled_by=ActorSide.DRIVER, listing_expires_at=T0, departure_window_end=T0 + timedelta(hours=3), now=T0
    )


def test_fault_side_of_plain_cancel() -> None:
    assert rules.fault_side_for_cancel(ActorSide.CLIENT) is FaultSide.CLIENT
    assert rules.fault_side_for_cancel(ActorSide.DRIVER) is FaultSide.DRIVER
    assert rules.fault_side_for_cancel(ActorSide.OPERATOR) is FaultSide.NONE


# --- no-show guard (Q7) --------------------------------------------------------------------------------------------


def _no_show(**overrides):  # noqa: ANN003, ANN202
    values = dict(
        arrived_at_pickup_at=T0,
        pickup_window_start=T0,
        pickup_window_end=T0 + timedelta(minutes=30),
        wait_minutes=10,
        contact_attempts=1,
        now=T0 + timedelta(minutes=11),
    )
    values.update(overrides)
    return rules.check_no_show_report(**values)


def test_q7_no_show_guard_accepts_a_waiting_driver() -> None:
    assert _no_show() == T0 + timedelta(minutes=10)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"arrived_at_pickup_at": None}, "arrival_not_recorded"),
        ({"arrived_at_pickup_at": T0 + timedelta(minutes=31)}, "driver_arrived_late"),
        ({"now": T0 + timedelta(minutes=9)}, "wait_time_not_elapsed"),
        ({"contact_attempts": 0}, "no_contact_attempt"),
    ],
)
def test_q7_no_show_guard_rejections(overrides: dict, reason: str) -> None:
    with pytest.raises(DomainError) as info:
        _no_show(**overrides)
    assert info.value.code is ErrorCode.NO_SHOW_NOT_ALLOWED and info.value.details["reason"] == reason


def test_wait_is_counted_from_window_start_for_an_early_driver() -> None:
    with pytest.raises(DomainError):
        _no_show(arrived_at_pickup_at=T0 - timedelta(minutes=30), now=T0 + timedelta(minutes=5))


# --- actions, proofs, fees -------------------------------------------------------------------------------------------


def test_actions_of_the_other_service_are_invalid() -> None:
    with pytest.raises(DomainError) as info:
        rules.action_target(ServiceType.PARCEL, BookingAction.BOARD, "awaiting_pickup")
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert rules.action_target(ServiceType.PARCEL, BookingAction.PICK_UP, "awaiting_pickup") == "picked_up"
    assert rules.action_target(ServiceType.PASSENGER, BookingAction.REPORT_NO_SHOW, "awaiting_pickup") is None


def test_separate_codes_per_action_and_driver_sees_none() -> None:
    assert rules.ACTION_PROOF_KIND[BookingAction.PICK_UP] is ProofKind.PICKUP_CODE
    assert rules.ACTION_PROOF_KIND[BookingAction.DELIVER] is ProofKind.DELIVERY_CODE
    assert ProofKind.DELIVERY_CODE in rules.CLIENT_CODE_KINDS[ServiceType.PARCEL]
    assert all(ActorSide.DRIVER in rules.ACTION_SIDES[action] for action in rules.ACTION_PROOF_KIND)


def test_proof_attempt_limit() -> None:
    rules.ensure_proof_attempts_left(4)
    with pytest.raises(DomainError) as info:
        rules.ensure_proof_attempts_left(5)
    assert info.value.code is ErrorCode.PROOF_ATTEMPTS_EXCEEDED and info.value.http_status == 429


def test_capture_only_for_a_hold_without_blocking_dispute() -> None:
    assert rules.capture_on_completion(commission_status="held", blocking_dispute_open=False)
    assert not rules.capture_on_completion(commission_status="held", blocking_dispute_open=True)
    assert not rules.capture_on_completion(commission_status="exempt", blocking_dispute_open=False)


def test_fee_finalizable_only_after_a_service_outcome() -> None:
    rules.ensure_fee_finalizable("returned")
    with pytest.raises(DomainError):
        rules.ensure_fee_finalizable("confirmed")


def test_boarding_window_is_60_minutes() -> None:
    assert rules.boarding_opens_at(T0) == T0 - timedelta(minutes=60)
