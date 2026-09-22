"""Booking command races on real PostgreSQL 16 (ADR-0017 lock order; AC20, AC21; release contract).

Forced overlap: a hook sleeps inside the first worker's locked section and the second worker starts later; LockClock
proves the second worker really waited on the trip row lock. Every pair runs in both orders; no deadlock is allowed.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.marketplace import service as marketplace_service
from tests.pg.bookings.conftest import (
    BW,
    STAGGER_S,
    TRIPS_LOCK,
    accept,
    act,
    codes_for,
    driver_trip,
    hold_inside,
    passenger_request_body,
    propose,
    publish_listing,
    rows,
    run_trip_action,
    scalar,
    seats_used,
    wallet,
)
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import passenger_offer

pytestmark = pytest.mark.pg


def _is_deadlock(error: BaseException | None) -> bool:
    return isinstance(error, OperationalError) and "deadlock" in str(error).lower()


@pytest.mark.parametrize("cancel_first", [True, False])
def test_accept_vs_cancel_on_the_same_trip_serialize_without_deadlock(
    bw: BW, lock_clock, monkeypatch: pytest.MonkeyPatch, cancel_first: bool  # noqa: ANN001
) -> None:
    clock = lock_clock(TRIPS_LOCK)
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01C100AA", seats=2)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    first = accept(bw, propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000), bw.w.driver_id)
    second_ref = propose(bw, offer, bw.w.client2_id, trip_public_id=None, quantity=1, unit=20_000_000)
    early = 0 if cancel_first else 1
    early_ident: dict[str, int] = {}
    hold_inside(monkeypatch, marketplace_service, "lock_listings", only_thread=lambda: threading.get_ident() == early_ident.get("t"))

    def work(index: int, session: Session) -> str:
        clock.bind(index)
        if index == early:
            early_ident["t"] = threading.get_ident()
        else:
            time.sleep(STAGGER_S)
        if index == 0:
            bookings_service.cancel_booking(session, booking_public_id_value=bookings_service.booking_public_id(first),
                                            actor_user_id=bw.w.client_id, expected_version=first.version, reason_code="race")
            session.commit()
            return "cancelled"
        accept(bw, second_ref, bw.w.driver_id, session=session)
        return "accepted"

    report = run_concurrently(2, work, engine=bw.db.engine)
    assert not any(_is_deadlock(r.error) for r in report.results), report.results
    assert [r.value for r in report.results] == ["cancelled", "accepted"], report.results
    clock.assert_waited(early=early, late=1 - early)
    assert seats_used(bw, trip_id) == [1, 1, 1]  # the deferred capacity trigger also checked this at COMMIT
    assert wallet(bw, bw.w.driver_id)[1] == 3_000_000


def test_parallel_cancels_release_once(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01C101AA", seats=2)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    booking = accept(bw, propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=2, unit=20_000_000), bw.w.driver_id)

    def work(index: int, session: Session) -> str:
        actor = bw.w.client_id if index % 2 == 0 else bw.w.driver_id
        bookings_service.cancel_booking(session, booking_public_id_value=bookings_service.booking_public_id(booking),
                                        actor_user_id=actor, expected_version=1, reason_code=f"race-{index}")
        session.commit()
        return "cancelled"

    report = run_concurrently(6, work, engine=bw.db.engine)
    assert len(report.successes) == 1
    assert {r.error.code for r in report.failures if isinstance(r.error, DomainError)} <= {ErrorCode.VERSION_CONFLICT}
    assert len(report.failures) == 5 and all(isinstance(r.error, DomainError) for r in report.failures)
    assert seats_used(bw, trip_id) == [0, 0, 0] and wallet(bw, bw.w.driver_id)[1] == 0
    assert scalar(bw.db, "SELECT count(*) FROM booking_status_history WHERE booking_id = :b AND to_status = 'cancelled'", b=booking.id) == 1


def test_ac20_parallel_completion_captures_once(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01C102AA", seats=2)
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=1))
    booking = accept(bw, propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1), bw.w.client_id)
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    arrived = act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))

    def work(index: int, session: Session) -> str:
        bookings_service.perform_action(
            session, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            action="complete", data=bookings_service.ActionInput(expected_version=arrived.version),
        )
        session.commit()
        return "completed"

    report = run_concurrently(5, work, engine=bw.db.engine)
    assert len(report.successes) == 1, report.results
    assert all(isinstance(r.error, DomainError) and r.error.code is ErrorCode.VERSION_CONFLICT for r in report.failures)
    # Q74: no A12 probe -> completion keeps the hold (finance_review); finance captures with finalize_fee.
    assert scalar(bw.db, "SELECT count(*) FROM ledger_transactions WHERE reference_kind = 'commission_capture'") == 0
    with bw.db.session() as s:
        completed = s.get(Booking, booking.id)
        assert (completed.commission_status, completed.finance_review_reason) == ("held", "dispute_module_unavailable")
        completed_version = completed.version

    def finalize(index: int, session: Session) -> str:
        bookings_service.operator_command(
            session, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.finance_id,
            command="finalize_fee", expected_version=completed_version, reason=f"finance-{index}", fee_mode="capture",
        )
        session.commit()
        return "captured"

    finalized = run_concurrently(5, finalize, engine=bw.db.engine)
    assert len(finalized.successes) == 1, finalized.results
    assert all(isinstance(r.error, DomainError) and r.error.code is ErrorCode.VERSION_CONFLICT for r in finalized.failures)
    assert scalar(bw.db, "SELECT count(*) FROM ledger_transactions WHERE reference_kind = 'commission_capture'") == 1  # AC20
    assert rows(bw.db, "SELECT status, captured_minor FROM wallet_holds WHERE booking_id = :b", b=booking.id) == [("captured", 2_850_000)]
    with bw.db.session() as s:
        assert s.get(Booking, booking.id).commission_status == "captured"
