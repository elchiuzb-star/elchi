"""Booking lifecycle on real PostgreSQL 16 (spec §9.5, §11; AC20-AC22, AC26, AC42; Q7, Q17, Q19, Q44, N3, N5, D10)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.contracts.errors import DomainError, ErrorCode
from app.core.config import settings
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking, BookingAllocation, BookingProof
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from tests.pg.bookings.conftest import (
    BW,
    accept,
    act,
    auth,
    booking_version,
    codes_for,
    domain_error,
    driver_trip,
    operator,
    parcel_request_body,
    passenger_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    rows,
    run_trip_action,
    scalar,
    seats_used,
    view,
    wallet,
)
from tests.pg.identity.a1_world import passenger_offer

pytestmark = pytest.mark.pg

CLIENT_PHONE, DRIVER_PHONE, RECEIVER_PHONE = "+998900000201", "+998900000301", "+998977777777"


def boarded_passenger(bw: BW, *, plate: str = "01B100AA"):  # noqa: ANN201
    listing, trip_id, _, ref = request_with_driver_proposal(bw, plate=plate)
    booking = accept(bw, ref, bw.w.client_id)
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30)) == "boarding"
    return listing, trip_id, booking


# --- passenger happy path, Q44 timeline, AC20 --------------------------------------------------------------------------------


def test_passenger_lifecycle_phone_timeline_and_single_capture(bw: BW) -> None:
    listing, trip_id, booking = boarded_passenger(bw)
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "awaiting_pickup"
    before = view(bw, booking.id, "driver", now=bw.base)
    assert before["client"]["contact_phone"] is None and before["contact"]["phones_visible"] is False  # Q44: accepted, not started
    assert view(bw, booking.id, "client", now=bw.base)["driver"]["vehicle"]["plate_number"] == "01B100AA"  # plate from awaiting_pickup

    assert domain_error(lambda: codes_for(bw, booking.id, bw.w.driver_id)).code is ErrorCode.FORBIDDEN  # the driver never sees codes
    code = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    act(bw, booking.id, bw.w.driver_id, "board", code=code, now=bw.base + timedelta(minutes=5))
    started = view(bw, booking.id, "driver", now=bw.base + timedelta(minutes=6))
    assert started["client"]["contact_phone"] == CLIENT_PHONE and started["contact"]["phones_visible"] is True
    assert view(bw, booking.id, "client", now=bw.base + timedelta(minutes=6))["driver"]["contact_phone"] == DRIVER_PHONE

    act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    completed = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    # Q74: without an A12 dispute probe the completion keeps the hold for finance review.
    assert (completed.service_status, completed.commission_status, completed.finance_review_reason) == (
        "completed", "held", "dispute_module_unavailable")
    again = domain_error(lambda: act(bw, booking.id, bw.w.client_id, "complete"))
    assert again.code is ErrorCode.INVALID_STATE_TRANSITION  # AC20: completion is not repeated
    finalized = operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="no dispute")
    assert finalized.commission_status == "captured" and wallet(bw, bw.w.driver_id) == (100_000_000 - 5_700_000, 0)
    assert domain_error(lambda: operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture")).code \
        is ErrorCode.INVALID_STATE_TRANSITION
    assert scalar(bw.db, "SELECT count(*) FROM ledger_transactions WHERE reference_kind = 'commission_capture'") == 1

    terminal = scalar(bw.db, "SELECT service_terminal_at FROM bookings WHERE id = :b", b=booking.id)
    still = view(bw, booking.id, "driver", now=terminal + timedelta(hours=23, minutes=59))
    hidden = view(bw, booking.id, "driver", now=terminal + timedelta(hours=24))
    assert still["client"]["contact_phone"] == CLIENT_PHONE
    assert hidden["client"]["contact_phone"] is None and hidden["contact"]["phones_visible"] is False  # Q44: re-hidden after 24 h
    events = [r.event_type for r in rows(bw.db, "SELECT event_type FROM outbox_events WHERE aggregate_type = 'booking' ORDER BY id")]
    assert "booking.started" in events and "booking.completed" in events


# --- proofs: attempt limit through HTTP (failures persist after the 4xx rollback), N5 rotation ------------------------------


def test_proof_attempt_limit_persists_through_the_idempotent_runner(bw: BW, client) -> None:  # noqa: ANN001
    _, _, booking = boarded_passenger(bw, plate="01B101AA")
    public = bookings_service.booking_public_id(booking)
    right = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    wrong = "000000" if right != "000000" else "111111"
    url = f"/api/v2/bookings/{public}/actions/board"
    version = booking_version(bw, booking.id)
    for attempt in range(5):
        response = client.post(url, json={"expected_version": version, "code": wrong}, headers=auth(bw.w.driver_id, "driver", f"board-wrong-{attempt:04d}"))
        assert response.status_code == 409 and response.json()["error"]["code"] == "PROOF_INVALID", response.text
    replay = client.post(url, json={"expected_version": version, "code": wrong}, headers=auth(bw.w.driver_id, "driver", "board-wrong-0000"))
    assert replay.headers.get("Idempotent-Replayed") == "true"  # a replay does not count again
    assert scalar(bw.db, "SELECT failed_attempts FROM booking_proofs WHERE booking_id = :b", b=booking.id) == 5
    blocked = client.post(url, json={"expected_version": version, "code": right}, headers=auth(bw.w.driver_id, "driver", "board-right-0001"))
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "PROOF_ATTEMPTS_EXCEEDED"
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "awaiting_pickup"
    assert scalar(bw.db, "SELECT count(*) FROM booking_proof_attempts WHERE booking_id = :b AND NOT succeeded", b=booking.id) == 5


def test_n5_code_issued_before_key_rotation_is_accepted_in_the_window(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, booking = boarded_passenger(bw, plate="01B102AA")
    monkeypatch.setattr(settings, "proof_code_key", None)
    old_master = settings.secret_key
    code = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    monkeypatch.setattr(settings, "secret_key", "rotated-" + "x" * 48)
    monkeypatch.setattr(settings, "previous_secret_keys", [])
    failures: list = []
    assert domain_error(lambda: act(bw, booking.id, bw.w.driver_id, "board", code=code, failures=failures)).code is ErrorCode.PROOF_INVALID
    monkeypatch.setattr(settings, "previous_secret_keys", [old_master])  # rotation window (KEY_ROTATION_VERIFICATION_WINDOW)
    assert act(bw, booking.id, bw.w.driver_id, "board", code=code).service_status == "onboard"
    with bw.db.session() as s:
        proof = s.execute(select(BookingProof).where(BookingProof.booking_id == booking.id)).scalar_one()
        assert proof.accepted_at is not None and len(proof.code_hash) == 64 and proof.actor_user_id == bw.w.driver_id


# --- AC21 cancellation, Q19 reopen, release contract --------------------------------------------------------------------------


def test_ac21_client_cancel_releases_allocation_and_hold_atomically(bw: BW) -> None:
    listing, trip_id, _, ref = request_with_driver_proposal(bw, plate="01B110AA")
    booking = accept(bw, ref, bw.w.client_id)
    with bw.db.session() as s:
        cancelled = bookings_service.cancel_booking(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=1, reason_code="plans_changed",
        )
        s.commit()
        assert (cancelled.service_status, cancelled.commission_status, cancelled.fault_side, cancelled.cancelled_by_side) == (
            "cancelled", "released", "client", "client")
    assert seats_used(bw, trip_id) == [0, 0, 0] and wallet(bw, bw.w.driver_id) == (100_000_000, 0)
    assert scalar(bw.db, "SELECT count(*) FROM booking_allocations WHERE booking_id = :b AND active", b=booking.id) == 0
    assert scalar(bw.db, "SELECT status FROM wallet_holds WHERE booking_id = :b", b=booking.id) == "released"
    with bw.db.session() as s:
        assert marketplace_service.get_listing_by_public_id(s, listing).status == "cancelled"  # the client closed its demand
        booking_row = s.get(Booking, booking.id)
        assert bookings_service._release_allocations(s, booking_row, trip_id, bw.base) is False  # noqa: SLF001 - release contract
        s.rollback()
    again = domain_error(lambda: act(bw, booking.id, bw.w.client_id, "complete"))
    assert again.code is ErrorCode.INVALID_STATE_TRANSITION


def test_q19_driver_cancel_reopens_the_request_and_notifies(bw: BW) -> None:
    listing, trip_id, _, ref = request_with_driver_proposal(bw, plate="01B111AA")
    booking = accept(bw, ref, bw.w.client_id)
    with bw.db.session() as s:
        result = bookings_service.cancel_booking(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.driver_id,
            expected_version=1, reason_code="vehicle_problem",
        )
        s.commit()
        assert (result.fault_side, result.commission_status) == ("driver", "released")
        assert marketplace_service.get_listing_by_public_id(s, listing).status == "published"
    events = [r.event_type for r in rows(bw.db, "SELECT event_type FROM outbox_events ORDER BY id")]
    assert events[-3:].count("listing.published") == 1 and "booking.cancelled" in events
    # The reopened demand can be booked again (the binding index ignores cancelled bookings).
    _, trip2 = driver_trip(bw, bw.w.driver2_id, "01B112AA")
    second = accept(bw, propose(bw, listing, bw.w.driver2_id, trip_public_id=trip2), bw.w.client_id)
    assert second.service_status == "confirmed" and seats_used(bw, trip_id) == [0, 0, 0]


# --- Q7 no-show, N3 ------------------------------------------------------------------------------------------------------------


def _report_no_show(bw: BW, booking_id: int) -> None:
    act(bw, booking_id, bw.w.driver_id, "arrive_at_pickup", now=bw.base, observed_at=bw.base)
    act(bw, booking_id, bw.w.driver_id, "report_no_show", now=bw.base + timedelta(minutes=11),
        contact_attempts=({"at": bw.base.isoformat(), "channel": "chat"},))


def test_q7_no_show_report_review_and_operator_confirmation(bw: BW) -> None:
    _, trip_id, booking = boarded_passenger(bw, plate="01B120AA")
    early = domain_error(lambda: act(bw, booking.id, bw.w.driver_id, "report_no_show", now=bw.base + timedelta(minutes=11)))
    assert early.code is ErrorCode.NO_SHOW_NOT_ALLOWED  # no "arrived" signal yet
    _report_no_show(bw, booking.id)
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "awaiting_pickup"
    assert scalar(bw.db, "SELECT status FROM no_show_reviews WHERE booking_id = :b", b=booking.id) == "pending"
    with bw.db.session() as s:
        blocked = domain_error(lambda: bookings_service.cancel_booking(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=booking_version(bw, booking.id), reason_code="late"))
        assert blocked.code is ErrorCode.NO_SHOW_REVIEW_PENDING
    assert domain_error(lambda: operator(bw, booking.id, bw.finance_id, "confirm_no_show")).code is ErrorCode.FORBIDDEN
    confirmed = operator(bw, booking.id, bw.operator_id, "confirm_no_show", now=bw.base + timedelta(minutes=20))
    assert (confirmed.service_status, confirmed.commission_status) == ("no_show", "released")
    assert seats_used(bw, trip_id) == [0, 0, 0] and wallet(bw, bw.w.driver_id)[1] == 0
    assert scalar(bw.db, "SELECT decided_by FROM no_show_reviews WHERE booking_id = :b", b=booking.id) == bw.operator_id


def test_n3_reject_no_show_after_trip_completion_cancels_with_driver_fault(bw: BW) -> None:
    _, trip_id, booking = boarded_passenger(bw, plate="01B121AA")
    _report_no_show(bw, booking.id)
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "depart", now=bw.base + timedelta(minutes=15)) == "in_progress"
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "complete", now=bw.base + timedelta(hours=4)) == "completed"  # review does not block
    rejected = operator(bw, booking.id, bw.operator_id, "reject_no_show", now=bw.base + timedelta(hours=5))
    assert (rejected.service_status, rejected.fault_side, rejected.cancelled_by_side, rejected.commission_status) == (
        "cancelled", "driver", "operator", "released")
    assert scalar(bw.db, "SELECT status FROM no_show_reviews WHERE booking_id = :b", b=booking.id) == "rejected"
    assert scalar(bw.db, "SELECT count(*) FROM booking_allocations WHERE booking_id = :b AND active", b=booking.id) == 0


def test_reject_no_show_while_trip_runs_keeps_awaiting_pickup(bw: BW) -> None:
    _, _, booking = boarded_passenger(bw, plate="01B122AA")
    _report_no_show(bw, booking.id)
    result = operator(bw, booking.id, bw.operator_id, "reject_no_show", now=bw.base + timedelta(minutes=30))
    assert result.service_status == "awaiting_pickup" and result.cancelled_at is None


# --- parcel: AC22, receiver phone, AC42, custody, finalize fee (Q17) ------------------------------------------------------------


def test_parcel_custody_trip_completion_return_and_fee_finalization(bw: BW) -> None:
    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01B130AA")
    ref = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000, dropoff="C", price_basis="total")
    booking = accept(bw, ref, bw.w.client_id)
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    before = view(bw, booking.id, "driver", now=bw.base)
    assert before["parcel_contacts"] == {"receiver_name": None, "receiver_phone": None} and before["client"]["contact_phone"] is None

    codes = codes_for(bw, booking.id, bw.w.client_id)
    assert set(codes) == {"pickup_code", "delivery_code"} and codes["pickup_code"] != codes["delivery_code"]
    wrong_kind = domain_error(lambda: act(bw, booking.id, bw.w.driver_id, "pick_up", code=codes["delivery_code"], failures=[]))
    assert wrong_kind.code is ErrorCode.PROOF_INVALID  # a delivery code never proves a pickup
    act(bw, booking.id, bw.w.driver_id, "pick_up", code=codes["pickup_code"], now=bw.base + timedelta(minutes=5))
    after = view(bw, booking.id, "driver", now=bw.base + timedelta(minutes=6))
    assert after["parcel_contacts"]["receiver_phone"] == RECEIVER_PHONE  # Q44: receiver phone after pickup
    assert after["client"]["contact_phone"] is None  # Q44: the sender's phone never reaches the driver

    with bw.db.session() as s:
        custody = domain_error(lambda: bookings_service.cancel_booking(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=booking_version(bw, booking.id), reason_code="changed_mind"))
    assert custody.code is ErrorCode.CUSTODY_REQUIRES_RETURN_FLOW  # AC22

    act(bw, booking.id, bw.w.driver_id, "start_transit", now=bw.base + timedelta(minutes=10))
    act(bw, booking.id, bw.w.driver_id, "report_delivery_failed", now=bw.base + timedelta(hours=2), note="nobody at the stop")
    assert scalar(bw.db, "SELECT status FROM custody_cases WHERE booking_id = :b", b=booking.id) == "open"
    run_trip_action(bw, trip_id, bw.w.driver_id, "depart", now=bw.base + timedelta(minutes=12))
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "complete", now=bw.base + timedelta(hours=4)) == "completed"  # AC42
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "delivery_failed"  # unchanged

    operator(bw, booking.id, bw.operator_id, "require_return", now=bw.base + timedelta(hours=5))
    return_code = codes_for(bw, booking.id, bw.w.client_id)["return_code"]
    returned = act(bw, booking.id, bw.w.driver_id, "return_to_sender", code=return_code, now=bw.base + timedelta(hours=6))
    assert (returned.service_status, returned.commission_status) == ("returned", "held")  # no automatic fee decision
    assert scalar(bw.db, "SELECT status FROM custody_cases WHERE booking_id = :b", b=booking.id) == "resolved"
    assert domain_error(lambda: operator(bw, booking.id, bw.operator_id, "finalize_fee", fee_mode="capture")).code is ErrorCode.FORBIDDEN
    finalized = operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture")  # Q17: finance.fee_finalize
    assert finalized.commission_status == "captured"


def test_trip_completion_is_refused_while_a_parcel_is_in_transit(bw: BW) -> None:
    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01B131AA")
    booking = accept(bw, propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000, dropoff="C",
                                 price_basis="total"), bw.w.client_id)
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    act(bw, booking.id, bw.w.driver_id, "pick_up", code=codes_for(bw, booking.id, bw.w.client_id)["pickup_code"], now=bw.base)
    run_trip_action(bw, trip_id, bw.w.driver_id, "depart", now=bw.base + timedelta(minutes=5))
    act(bw, booking.id, bw.w.driver_id, "start_transit", now=bw.base + timedelta(minutes=6))
    error = domain_error(lambda: run_trip_action(bw, trip_id, bw.w.driver_id, "complete", now=bw.base + timedelta(hours=4)))
    assert error.code is ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS and error.details["bookings"] == [bookings_service.booking_public_id(booking)]
    delivery = codes_for(bw, booking.id, bw.w.client_id)["delivery_code"]
    done = act(bw, booking.id, bw.w.driver_id, "deliver", code=delivery, now=bw.base + timedelta(hours=2))
    assert (done.service_status, done.commission_status) == ("delivered", "held")  # Q65: delivery no longer completes
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "complete", now=bw.base + timedelta(hours=4)) == "completed"


# --- AC26 cash ----------------------------------------------------------------------------------------------------------------


def test_ac26_contested_cash_keeps_service_status(bw: BW) -> None:
    _, _, booking = boarded_passenger(bw, plate="01B140AA")
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    with bw.db.session() as s:
        b = s.get(Booking, booking.id)
        _, receipt = bookings_service.report_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=bw.w.driver_id,
            expected_version=b.version, amount_minor=b.total_minor, reported_at=bw.base,
        )
        from app.contracts.ids import PublicIdPrefix, format_public_id

        receipt_public = format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id)
        s.commit()
    with bw.db.session() as s:
        same_side = domain_error(lambda: bookings_service.acknowledge_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), receipt_public_id=receipt_public,
            actor_user_id=bw.w.driver_id, expected_version=1))
        assert same_side.code is ErrorCode.FORBIDDEN
    with bw.db.session() as s:
        b, receipt = bookings_service.contest_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), receipt_public_id=receipt_public,
            actor_user_id=bw.w.client_id, expected_version=1, comment="I paid only half",
        )
        s.commit()
        assert (b.cash_status, b.service_status, receipt.status) == ("contested", "onboard", "contested")
    act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    done = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3))
    assert (done.service_status, done.cash_status) == ("completed", "contested")


# --- amendments (D10) ---------------------------------------------------------------------------------------------------------


def test_d10_amendment_changes_quantity_reserves_again_and_adjusts_the_single_hold(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01B150AA", seats=3)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    booking = accept(bw, propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000), bw.w.driver_id)
    assert wallet(bw, bw.w.driver_id)[1] == 3_000_000
    with bw.db.session() as s:
        amendment = bookings_service.create_amendment(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=booking.version, changes={"quantity": 2}, reason="friend joins",
        )
        s.commit()
        from app.contracts.ids import PublicIdPrefix, format_public_id

        amendment_public = format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id)
    with bw.db.session() as s:
        own = domain_error(lambda: bookings_service.accept_amendment(
            s, amendment_public_id=amendment_public, actor_user_id=bw.w.client_id, expected_version=1))
        assert own.code is ErrorCode.FORBIDDEN
    with bw.db.session() as s:
        updated = bookings_service.accept_amendment(s, amendment_public_id=amendment_public, actor_user_id=bw.w.driver_id, expected_version=1)
        s.commit()
        assert (updated.quantity, updated.total_minor, updated.commission_minor, updated.fee_bps) == (2, 40_000_000, 6_000_000, 1500)
    assert seats_used(bw, trip_id) == [2, 2, 2]
    assert wallet(bw, bw.w.driver_id)[1] == 6_000_000 and scalar(bw.db, "SELECT count(*) FROM wallet_holds") == 1
    assert scalar(bw.db, "SELECT count(*) FROM booking_allocations WHERE booking_id = :b AND NOT active", b=booking.id) == 3

    listing, _, _, ref = request_with_driver_proposal(bw, plate="01B151AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    request_booking = accept(bw, ref, bw.w.client2_id)
    with bw.db.session() as s:
        split = domain_error(lambda: bookings_service.create_amendment(
            s, booking_public_id_value=bookings_service.booking_public_id(request_booking), actor_user_id=bw.w.driver2_id,
            expected_version=1, changes={"quantity": 1}, reason="one seat only"))
        assert split.code is ErrorCode.QUANTITY_MISMATCH  # D9: a request is never split


def test_booking_amendments_are_listed_for_participants_only(bw: BW) -> None:
    """B9 read side: the counterpart must be able to find the amendment it is expected to answer."""
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01B152AA", seats=3)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    booking = accept(bw, propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000), bw.w.driver_id)
    public_id = bookings_service.booking_public_id(booking)
    with bw.db.session() as s:
        assert bookings_service.list_booking_amendments(
            s, booking_public_id_value=public_id, actor_user_id=bw.w.driver_id
        )[1] == []
        bookings_service.create_amendment(
            s, booking_public_id_value=public_id, actor_user_id=bw.w.client_id,
            expected_version=booking.version, changes={"quantity": 2}, reason="friend joins",
        )
        s.commit()
    with bw.db.session() as s:
        # the driver did not propose it, and is the side that has to answer it
        _, rows = bookings_service.list_booking_amendments(s, booking_public_id_value=public_id, actor_user_id=bw.w.driver_id)
        assert [(row.status, row.author_side, row.new_quantity) for row in rows] == [("proposed", "client", 2)]
        # a stranger is not told the booking exists at all
        outsider = domain_error(lambda: bookings_service.list_booking_amendments(
            s, booking_public_id_value=public_id, actor_user_id=bw.w.client2_id))
        assert outsider.code is ErrorCode.NOT_FOUND


# --- read-side hooks (N4, Q15, A1 N6) --------------------------------------------------------------------------------------------


def test_read_side_hooks_for_other_owners(bw: BW) -> None:
    _, trip_id, _, ref = request_with_driver_proposal(bw, plate="01B160AA")
    booking = accept(bw, ref, bw.w.client_id)
    with bw.db.session() as s:
        client_state = bookings_service.blocking_state_for_user(s, bw.w.client_id, lock=True)
        driver_state = bookings_service.blocking_state_for_user(s, bw.w.driver_id)
        assert client_state.blocks_deletion and client_state.as_details()["active_bookings_as_client"] == 1
        assert driver_state.blocks_deletion and driver_state.held_commission_bookings == 1
        obligations = bookings_service.driver_v2_obligations(s, bw.w.driver_id)
        assert obligations.has_active_v2_business and obligations.active_booking_count == 1
        assert bookings_service.trip_has_active_allocations(s, trip_id) and bookings_service.trip_has_allocations(s, trip_id)
        s.rollback()
    with bw.db.session() as s:
        bookings_service.cancel_booking(s, booking_public_id_value=bookings_service.booking_public_id(booking),
                                        actor_user_id=bw.w.client_id, expected_version=1, reason_code="x")
        s.commit()
    with bw.db.session() as s:
        assert not bookings_service.blocking_state_for_user(s, bw.w.client_id).blocks_deletion
        assert not bookings_service.trip_has_active_allocations(s, trip_id) and bookings_service.trip_has_allocations(s, trip_id)
        assert bookings_service.booking_public_id_for_proposal_version(s, s.get(Booking, booking.id).accepted_proposal_version_id)


def test_blocked_driver_keeps_obligations_on_an_existing_booking(bw: BW) -> None:
    """D16: an eligibility block stops new business, not the booked trip (trip.operate stays)."""
    _, _, booking = boarded_passenger(bw, plate="01B170AA")
    with bw.db.session() as s:
        identity_service.block_driver_eligibility(
            s, driver_user_id=bw.w.driver_id, actor_user_id=bw.w.admin_id,
            expected_version=identity_service.eligibility_version(s, bw.w.driver_id), reason="documents")
        s.commit()
    code = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    assert act(bw, booking.id, bw.w.driver_id, "board", code=code, now=bw.base).service_status == "onboard"
