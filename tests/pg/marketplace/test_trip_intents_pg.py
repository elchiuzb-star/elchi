"""Saved trip/parcel requests (trip intents, ADR-0025) on PostgreSQL.

One request, offers to several drivers, at most one booking - enforced in the accept transaction under the intent lock
and by ``uq_bookings_trip_intent_binding``. Parallel tests are staged by database conditions (a transaction is seen
waiting on a lock), never by sleeps. SYNTHETIC people, prices and places only.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.marketplace import intents
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import (
    ProposalCounter,
    ProposalCreate,
    TripIntentCreate,
    TripIntentUpdate,
)
from app.modules.marketplace.views import thread_dto
from tests.pg.bookings.conftest import (  # noqa: F401  (fixtures)
    BW,
    FUNDED_MINOR,
    ThreadRef,
    _ref,
    accept,
    auth,
    bw,
    client,
    domain_error,
    driver_trip,
    fund,
    listing_version,
    occurrence_window,
    publish_listing,
    rows,
    scalar,
    seats_used,
    wallet,
)
from tests.pg.identity.a1_world import add_user, passenger_offer, wait_for_lock_waiters

pytestmark = pytest.mark.pg

UNIT = 19_000_000  # 190 000 so'm per person (synthetic)


# --- builders ---------------------------------------------------------------------------------------------------------


def _intent_body(bw: BW, *, quantity: int = 3, service: str = "passenger", start_h: float = -0.5, hours: float = 2,
                 price: int | None = UNIT, parcel: dict | None = None) -> dict[str, Any]:
    start = bw.base + timedelta(hours=start_h)
    body: dict[str, Any] = {
        "service_type": service,
        "origin": {"stop_id": bw.w.stop_public_ids["A"]},
        "destination": {"stop_id": bw.w.stop_public_ids["D"]},
        "window_start": start.isoformat(), "window_end": (start + timedelta(hours=hours)).isoformat(),
        "quantity": quantity,
    }
    if price is not None:
        body.update(price_basis="per_seat" if service == "passenger" else "total", unit_price_minor=price)
    if parcel is not None:
        body["parcel"] = parcel
    return body


def _update_body(bw: BW, version: int, *, acknowledge: bool = False, **kw: Any) -> TripIntentUpdate:
    body = {k: v for k, v in _intent_body(bw, **kw).items() if k != "service_type"}  # the service is frozen
    return TripIntentUpdate.model_validate({**body, "expected_version": version, "acknowledge_open_offers": acknowledge})


def _create(bw: BW, owner: int, **kw: Any) -> tuple[str, int]:
    with bw.db.session() as s:
        intent = intents.create_intent(s, owner_user_id=owner, data=TripIntentCreate.model_validate(_intent_body(bw, **kw)))
        s.commit()
        return intents.intent_public_id(intent), intent.current_version_no


def _intent_row(bw: BW, public_id: str) -> dict:
    with bw.db.session() as s:
        intent = intents._by_public_id(s, public_id)
        return {"id": intent.id, "status": intent.status, "version": intent.version, "terms": intent.terms_version,
                "booking_id": intent.booking_id, "version_no": intent.current_version_no}


def _driver(bw: BW, phone: str) -> int:
    with bw.db.session() as s:
        driver = add_user(s, phone, "driver", full_name="Synthetic Driver", driver_status="approved")
        s.commit()
    fund(bw, driver, FUNDED_MINOR, bw.super_id)
    return driver


def _offer(bw: BW, driver: int, plate: str, *, seats: int = 4, unit: int = 20_000_000) -> tuple[str, int]:
    trip_id, trip_public = driver_trip(bw, driver, plate, seats=seats)
    return publish_listing(bw, driver, passenger_offer(bw.w, trip_public, start=bw.base, unit_price_minor=unit)), trip_id


def _proposal(bw: BW, intent_id: str, version_no: int, *, quantity: int = 3, unit: int = UNIT, parcel: dict | None = None,
              basis: str = "per_seat") -> ProposalCreate:
    window = occurrence_window(bw, "A")
    body: dict[str, Any] = {
        "pickup_stop_id": bw.w.stop_public_ids["A"], "dropoff_stop_id": bw.w.stop_public_ids["D"],
        "pickup_window_start": window[0].isoformat(), "pickup_window_end": window[1].isoformat(),
        "quantity": quantity, "price_basis": basis, "unit_price_minor": unit,
        "trip_intent": {"id": intent_id, "version_no": version_no},
    }
    if parcel is not None:
        body["parcel"] = parcel
    return ProposalCreate.model_validate(body)


def _propose(bw: BW, listing: str, owner: int, data: ProposalCreate) -> ThreadRef:
    with bw.db.session() as s:
        thread = marketplace_service.submit_proposal(s, listing_public_id=listing, actor_user_id=owner, data=data)
        ref = _ref(s, listing, thread)
        s.commit()
        return ref


def _accept_in(bw: BW, ref: ThreadRef, driver: int) -> Callable[[Session], Booking]:
    def run(session: Session) -> Booking:
        return bookings_service.accept_proposal(
            session, thread_public_id=ref.thread_id, actor_user_id=driver, proposal_version_public_id=ref.version_id,
            expected_listing_version=listing_version(bw, ref.listing_id))
    return run


def _staged(bw: BW, first: Callable[[Session], Any], second: Callable[[Session], Any]) -> tuple[Any, Any]:
    """``first`` does its work and keeps its transaction (and locks) open; ``second`` starts only then; ``first``
    commits only once the database shows ``second`` waiting on a lock. The order is a DB condition, not a sleep."""
    results: dict[str, Any] = {}
    first_done, release = threading.Event(), threading.Event()

    def run_first() -> None:
        s = bw.db.session()
        try:
            results["first"] = first(s)
            first_done.set()
            assert release.wait(30), "never released"
            s.commit()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            results["first"] = exc
            first_done.set()
            s.rollback()
        finally:
            s.close()

    def run_second() -> None:
        s = bw.db.session()
        try:
            results["second"] = second(s)
            s.commit()
        except BaseException as exc:  # noqa: BLE001
            results["second"] = exc
            s.rollback()
        finally:
            s.close()

    one = threading.Thread(target=run_first)
    one.start()
    assert first_done.wait(30), "first never reached its locked point"
    if isinstance(results.get("first"), BaseException):
        release.set()
        one.join(30)
        raise results["first"]
    two = threading.Thread(target=run_second)
    two.start()
    try:
        wait_for_lock_waiters(bw.w, 1)  # the second transaction is now blocked behind the first
    finally:
        release.set()
    one.join(30)
    two.join(30)
    return results["first"], results["second"]


def _thread_state(bw: BW, thread_public_id: str) -> tuple[str, str | None]:
    with bw.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        return thread.state, thread.closed_reason


def _sweep(bw: BW) -> int:
    with bw.db.session() as s:
        closed = intents.close_stale_intent_threads(s)
        s.commit()
        return closed


# --- one request, several drivers --------------------------------------------------------------------------------------


def test_offers_to_three_drivers_carry_the_request_and_their_own_price(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    driver3 = _driver(bw, "+998900000931")
    refs = []
    for driver, plate, unit in ((bw.w.driver_id, "01T100TA", 18_000_000), (bw.w.driver2_id, "01T101TA", 19_000_000),
                                (driver3, "01T102TA", 20_000_000)):
        listing, _ = _offer(bw, driver, plate)
        refs.append(_propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no, unit=unit)))
    row = _intent_row(bw, intent_id)
    with bw.db.session() as s:
        threads = [marketplace_service.get_thread_by_public_id(s, ref.thread_id) for ref in refs]
        assert {(t.trip_intent_id, t.trip_intent_terms_version) for t in threads} == {(row["id"], row["terms"])}
        totals = sorted(marketplace_service.current_version(s, t).total_minor for t in threads)
        assert totals == [3 * 18_000_000, 3 * 19_000_000, 3 * 20_000_000]  # each driver its own price, 3 people each
        client_view = thread_dto(s, threads[0], viewer_user_id=bw.w.client_id)
        driver_view = thread_dto(s, threads[0], viewer_user_id=bw.w.driver_id)
        assert client_view.trip_intent_id == intent_id and driver_view.trip_intent_id is None  # private to the client
        dto = intents.intent_dto(s, intents._by_public_id(s, intent_id))
    assert dto["open_offers"] == 3 and all(o["terms_current"] for o in dto["offers"])
    assert dto["current_version"]["total_minor"] == 3 * UNIT  # 3 kishi x 190 000 = 570 000 so'm
    assert scalar(bw.db, "SELECT count(*) FROM listings WHERE owner_user_id = :c", c=bw.w.client_id) == 0  # not public


def test_the_request_decides_quantity_and_passenger_and_parcel_never_mix(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing, _ = _offer(bw, bw.w.driver_id, "01T110TA")
    error = domain_error(lambda: _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no, quantity=2)))
    assert error.code is ErrorCode.VALIDATION_ERROR and error.details["reason"] == "trip_intent_quantity_mismatch"
    parcel = {"parcel_type": "box", "weight_g": 2_000, "length_cm": 20, "width_cm": 20, "height_cm": 20,
              "receiver": {"name": "Olim", "phone": "+998900000999"}}
    error = domain_error(lambda: _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no, parcel=parcel)))
    assert error.code is ErrorCode.VALIDATION_ERROR and error.details["reason"] == "passenger_request_has_no_parcel"
    with bw.db.session() as s:  # a passenger request cannot hold parcel data; a parcel request is one shipment (D9)
        for body, code in ((_intent_body(bw, parcel=parcel), ErrorCode.VALIDATION_ERROR),
                           (_intent_body(bw, service="parcel", quantity=2, price=None, parcel=parcel), ErrorCode.QUANTITY_MISMATCH)):
            with pytest.raises(DomainError) as exc:
                intents.create_intent(s, owner_user_id=bw.w.client_id, data=TripIntentCreate.model_validate(body))
            assert exc.value.code is code
    parcel_id, parcel_no = _create(bw, bw.w.client_id, service="parcel", quantity=1, price=None, parcel=parcel)
    error = domain_error(lambda: _propose(bw, listing, bw.w.client_id,
                                          _proposal(bw, parcel_id, parcel_no, quantity=1, parcel=parcel, basis="total")))
    assert error.details["reason"] == "trip_intent_service_mismatch"  # a parcel request on a passenger offer
    ref = _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no))
    countered = ThreadRef(ref.listing_id, ref.thread_id, ref.version_id, ref.revision)
    with bw.db.session() as s, pytest.raises(DomainError) as exc:  # the driver cannot shrink what the client asked for
        marketplace_service.counter_proposal(s, thread_public_id_value=countered.thread_id, actor_user_id=bw.w.driver_id,
                                             data=ProposalCounter(expected_revision=ref.revision, quantity=2))
    assert exc.value.details["reason"] == "trip_intent_quantity_fixed"


def test_an_expired_window_is_refused_and_never_moved_and_the_offer_fit_is_shown(bw: BW) -> None:
    past = utc_now() - timedelta(hours=5)  # a window that is really over
    with bw.db.session() as s, pytest.raises(DomainError) as exc:
        intents.create_intent(s, owner_user_id=bw.w.client_id, data=TripIntentCreate.model_validate(
            {**_intent_body(bw), "window_start": past.isoformat(), "window_end": (past + timedelta(hours=1)).isoformat()}))
    assert exc.value.code is ErrorCode.TRIP_INTENT_EXPIRED
    intent_id, version_no = _create(bw, bw.w.client_id, start_h=3, hours=1)  # the offer leaves at base..base+1h
    listing, _ = _offer(bw, bw.w.driver_id, "01T120TA", seats=2)
    with bw.db.session() as s:
        intent = intents._by_public_id(s, intent_id)
        fit = intents.fit(s, intent, marketplace_service.get_listing_by_public_id(s, listing))
        later = intents.intent_dto(s, intent, now=bw.base + timedelta(hours=5))
    assert fit["time"] == {"status": "outside", "minutes_outside": 120}  # shown, the request is not adapted
    assert fit["availability"] == {"status": "insufficient", "requested": 3, "available": 2}
    assert (fit["origin"]["status"], fit["destination"]["status"]) == ("same_stop", "same_stop")
    assert fit["price"]["listing_total_minor"] == 3 * 20_000_000 and fit["price"]["intent_total_minor"] == 3 * UNIT
    assert "capacity_insufficient" in fit["blockers"]
    assert later["expired"] is True and later["current_version"]["window_start"] == bw.base + timedelta(hours=3)
    with bw.db.session() as s, pytest.raises(DomainError) as exc:  # after the window: asked to update, never moved
        intents.prepare_for_proposal(s, ref=_proposal(bw, intent_id, version_no).trip_intent,
                                     owner_user_id=bw.w.client_id, listing=marketplace_service.get_listing_by_public_id(s, listing),
                                     data=_proposal(bw, intent_id, version_no), now=bw.base + timedelta(hours=5))
    assert exc.value.code is ErrorCode.TRIP_INTENT_EXPIRED
    error = domain_error(lambda: _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no)))
    assert error.code is ErrorCode.CAPACITY_UNAVAILABLE  # 3 people never fit 2 seats, also at submit


def test_two_drivers_accepting_in_parallel_make_exactly_one_booking_and_the_loser_leaves_nothing(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing1, trip1 = _offer(bw, bw.w.driver_id, "01T130TA")
    listing2, trip2 = _offer(bw, bw.w.driver2_id, "01T131TA")
    ref1 = _propose(bw, listing1, bw.w.client_id, _proposal(bw, intent_id, version_no))
    ref2 = _propose(bw, listing2, bw.w.client_id, _proposal(bw, intent_id, version_no))
    held2_before = wallet(bw, bw.w.driver2_id)

    won, lost = _staged(bw, _accept_in(bw, ref1, bw.w.driver_id), _accept_in(bw, ref2, bw.w.driver2_id))
    assert isinstance(won, Booking)
    # the loser waited (on the shared client row or on the request) and is refused: either the request is booked, or
    # the winner already closed its thread in the same transaction - both before any capacity, lot or hold
    assert isinstance(lost, DomainError) and lost.code in (ErrorCode.TRIP_INTENT_BOOKED, ErrorCode.PROPOSAL_CHANGED)
    assert scalar(bw.db, "SELECT count(*) FROM bookings WHERE trip_intent_id IS NOT NULL") == 1
    assert scalar(bw.db, "SELECT count(*) FROM wallet_holds") == 1
    assert wallet(bw, bw.w.driver2_id) == held2_before and seats_used(bw, trip2) == [0, 0, 0]  # nothing left behind
    assert seats_used(bw, trip1) == [3, 3, 3]
    row = _intent_row(bw, intent_id)
    assert (row["status"], row["booking_id"]) == ("booked", won.id)
    # closed by the winner, or - if the loser held its thread lock at that moment (SKIP LOCKED) - by the sweep
    _sweep(bw)
    assert _thread_state(bw, ref2.thread_id) == ("closed", intents.REASON_BOOKED)
    events = rows(bw.db, "SELECT event_type, payload FROM outbox_events WHERE aggregate_type = 'proposal_thread' "
                         "ORDER BY id DESC LIMIT 1")
    assert events[0].event_type == "proposal.expired" and events[0].payload["reason_code"] == intents.REASON_BOOKED
    error = domain_error(lambda: accept(bw, ref2, bw.w.driver2_id))  # and it can never be accepted again
    assert error.code in (ErrorCode.TRIP_INTENT_BOOKED, ErrorCode.PROPOSAL_CHANGED)


def test_the_other_offers_close_in_the_accept_transaction_when_nobody_holds_them(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing1, _ = _offer(bw, bw.w.driver_id, "01T140TA")
    listing2, _ = _offer(bw, bw.w.driver2_id, "01T141TA")
    ref1 = _propose(bw, listing1, bw.w.client_id, _proposal(bw, intent_id, version_no))
    ref2 = _propose(bw, listing2, bw.w.client_id, _proposal(bw, intent_id, version_no))
    accept(bw, ref1, bw.w.driver_id)
    assert _thread_state(bw, ref2.thread_id) == ("closed", intents.REASON_BOOKED)  # a system expiry, no client fault
    with bw.db.session() as s:
        version = marketplace_service.current_version(s, marketplace_service.get_thread_by_public_id(s, ref2.thread_id))
        assert (version.status, version.status_reason) == ("expired", intents.REASON_BOOKED)
    assert scalar(bw.db, "SELECT count(*) FROM bookings WHERE service_status = 'cancelled'") == 0
    with bw.db.session() as s, pytest.raises(DomainError) as exc:  # nothing new can be sent from a booked request
        marketplace_service.submit_proposal(s, listing_public_id=listing2, actor_user_id=bw.w.client_id,
                                            data=_proposal(bw, intent_id, version_no))
    assert exc.value.code is ErrorCode.TRIP_INTENT_BOOKED


@pytest.mark.parametrize("first", ["accept", "edit"])
def test_an_edit_racing_an_accept_has_one_consistent_outcome(bw: BW, first: str) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing, trip_id = _offer(bw, bw.w.driver_id, "01T150TA" if first == "accept" else "01T151TA")
    ref = _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no))
    version = _intent_row(bw, intent_id)["version"]

    def edit(session: Session) -> Any:
        body = _update_body(bw, version, acknowledge=True, quantity=2)
        return intents.edit_intent(session, intent_public_id=intent_id, owner_user_id=bw.w.client_id, data=body)

    if first == "accept":
        done, refused = _staged(bw, _accept_in(bw, ref, bw.w.driver_id), edit)
        assert isinstance(done, Booking)
        assert isinstance(refused, DomainError) and refused.code is ErrorCode.TRIP_INTENT_BOOKED
        assert _intent_row(bw, intent_id)["status"] == "booked" and seats_used(bw, trip_id) == [3, 3, 3]
    else:
        done, refused = _staged(bw, edit, _accept_in(bw, ref, bw.w.driver_id))
        assert isinstance(refused, DomainError) and refused.code in (ErrorCode.TRIP_INTENT_CHANGED,
                                                                      ErrorCode.PROPOSAL_CHANGED)
        assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0 and seats_used(bw, trip_id) == [0, 0, 0]
        row = _intent_row(bw, intent_id)
        assert (row["status"], row["terms"]) == ("active", 2)
        _sweep(bw)
        assert _thread_state(bw, ref.thread_id) == ("closed", intents.REASON_CHANGED)


def test_a_material_edit_shows_what_happens_to_open_offers_before_closing_them(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing, _ = _offer(bw, bw.w.driver_id, "01T160TA")
    ref = _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no))
    version = _intent_row(bw, intent_id)["version"]
    with bw.db.session() as s:  # only the price hint: nothing happens to the offer
        body = _update_body(bw, version, price=21_000_000)
        intents.edit_intent(s, intent_public_id=intent_id, owner_user_id=bw.w.client_id, data=body)
        s.commit()
    assert _thread_state(bw, ref.thread_id) == ("open", None) and _intent_row(bw, intent_id)["terms"] == 1
    version = _intent_row(bw, intent_id)["version"]
    with bw.db.session() as s, pytest.raises(DomainError) as exc:
        body = _update_body(bw, version, quantity=2)
        intents.edit_intent(s, intent_public_id=intent_id, owner_user_id=bw.w.client_id, data=body)
    assert exc.value.code is ErrorCode.TRIP_INTENT_OFFERS_AFFECTED and exc.value.details == {"open_offers": 1}
    with bw.db.session() as s:
        body = _update_body(bw, version, acknowledge=True, quantity=2)
        intents.edit_intent(s, intent_public_id=intent_id, owner_user_id=bw.w.client_id, data=body)
        s.commit()
    assert _thread_state(bw, ref.thread_id) == ("closed", intents.REASON_CHANGED)
    error = domain_error(lambda: accept(bw, ref, bw.w.driver_id))
    assert error.code in (ErrorCode.PROPOSAL_CHANGED, ErrorCode.TRIP_INTENT_CHANGED)
    stale = _proposal(bw, intent_id, version_no, quantity=2)  # the old version the screen still showed
    error = domain_error(lambda: _propose(bw, listing, bw.w.client_id, stale))
    assert error.code is ErrorCode.TRIP_INTENT_CHANGED


def test_a_failed_accept_rolls_back_everything_and_the_request_stays_open(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    with bw.db.session() as s:
        poor = add_user(s, "+998900000941", "driver", full_name="Synthetic Driver", driver_status="approved")
        s.commit()  # no commission balance
    listing, trip_id = _offer(bw, poor, "01T170TA")
    ref = _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no))
    error = domain_error(lambda: accept(bw, ref, poor))
    assert error.code is ErrorCode.INSUFFICIENT_COMMISSION_BALANCE
    assert _intent_row(bw, intent_id)["status"] == "active" and _thread_state(bw, ref.thread_id) == ("open", None)
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0 and seats_used(bw, trip_id) == [0, 0, 0]
    fund(bw, poor, FUNDED_MINOR, bw.super_id)
    assert accept(bw, ref, poor).trip_intent_id == _intent_row(bw, intent_id)["id"]


def test_two_independent_requests_of_one_client_book_separately(bw: BW) -> None:
    first_id, first_no = _create(bw, bw.w.client_id)
    second_id, second_no = _create(bw, bw.w.client_id, quantity=1)
    listing1, _ = _offer(bw, bw.w.driver_id, "01T180TA")
    listing2, _ = _offer(bw, bw.w.driver2_id, "01T181TA")
    one = accept(bw, _propose(bw, listing1, bw.w.client_id, _proposal(bw, first_id, first_no)), bw.w.driver_id)
    two = accept(bw, _propose(bw, listing2, bw.w.client_id, _proposal(bw, second_id, second_no, quantity=1)), bw.w.driver2_id)
    assert one.id != two.id and {_intent_row(bw, first_id)["status"], _intent_row(bw, second_id)["status"]} == {"booked"}


def test_a_foreign_request_is_unknown_and_the_link_cannot_be_removed(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing, _ = _offer(bw, bw.w.driver_id, "01T190TA")
    error = domain_error(lambda: _propose(bw, listing, bw.w.client2_id, _proposal(bw, intent_id, version_no)))
    assert error.code is ErrorCode.NOT_FOUND  # another person's request is not revealed
    with bw.db.session() as s:
        for call in (lambda: intents.get_own_intent(s, intent_id, bw.w.client2_id),
                     lambda: intents.close_intent(s, intent_public_id=intent_id, owner_user_id=bw.w.client2_id,
                                                  expected_version=1)):
            with pytest.raises(DomainError) as exc:
                call()
            assert exc.value.code is ErrorCode.NOT_FOUND
    ref = _propose(bw, listing, bw.w.client_id, _proposal(bw, intent_id, version_no))
    with pytest.raises(DBAPIError) as db_exc, bw.db.engine.begin() as conn:  # the offer stays in its request
        conn.execute(text("UPDATE proposal_threads SET trip_intent_id = NULL, trip_intent_terms_version = NULL "
                          "WHERE trip_intent_id IS NOT NULL"))
    assert db_exc.value.orig.diag.constraint_name == "trip_intent_link_frozen"
    booking = accept(bw, ref, bw.w.driver_id)
    with pytest.raises(DBAPIError) as db_exc, bw.db.engine.begin() as conn:
        conn.execute(text("UPDATE bookings SET trip_intent_id = NULL WHERE id = :b"), {"b": booking.id})
    assert db_exc.value.orig.diag.constraint_name == "trip_intent_link_frozen"


def test_the_database_keeps_one_live_booking_even_if_the_service_check_were_bypassed(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing1, _ = _offer(bw, bw.w.driver_id, "01T200TA")
    listing2, _ = _offer(bw, bw.w.driver2_id, "01T201TA")
    ref1 = _propose(bw, listing1, bw.w.client_id, _proposal(bw, intent_id, version_no))
    ref2 = _propose(bw, listing2, bw.w.client_id, _proposal(bw, intent_id, version_no))
    accept(bw, ref1, bw.w.driver_id)
    with bw.db.engine.begin() as conn:  # forge: the request looks active again while its booking is live
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("UPDATE trip_intents SET status = 'active', booking_id = NULL WHERE public_id IS NOT NULL"))
        conn.execute(text("UPDATE proposal_threads SET state = 'open', closed_reason = NULL "
                          "WHERE trip_intent_id IS NOT NULL AND state = 'closed'"))
        conn.execute(text("UPDATE proposal_versions SET status = 'active', status_reason = NULL, closed_at = NULL "
                          "WHERE status = 'expired'"))
    error = domain_error(lambda: accept(bw, ref2, bw.w.driver2_id))
    assert error.code is ErrorCode.TRIP_INTENT_BOOKED  # uq_bookings_trip_intent_binding
    assert scalar(bw.db, "SELECT count(*) FROM bookings WHERE trip_intent_id IS NOT NULL") == 1


def test_a_cancelled_booking_reopens_nothing_by_itself_and_search_again_is_explicit(bw: BW) -> None:
    intent_id, version_no = _create(bw, bw.w.client_id)
    listing1, _ = _offer(bw, bw.w.driver_id, "01T210TA")
    listing2, _ = _offer(bw, bw.w.driver2_id, "01T211TA")
    ref1 = _propose(bw, listing1, bw.w.client_id, _proposal(bw, intent_id, version_no))
    ref2 = _propose(bw, listing2, bw.w.client_id, _proposal(bw, intent_id, version_no))
    booking = accept(bw, ref1, bw.w.driver_id)
    with bw.db.session() as s:
        b = s.get(Booking, booking.id)
        bookings_service.operator_command(
            s, booking_public_id_value=bookings_service.booking_public_id(b), actor_user_id=bw.super_id,
            command="cancel", expected_version=b.version, reason="synthetic operator cancel", cancel_fault_side="driver")
        s.commit()
    with bw.db.session() as s:
        dto = intents.intent_dto(s, intents._by_public_id(s, intent_id))
    assert (dto["status"], dto["booking_cancelled"], dto["can_reopen"]) == ("booked", True, True)
    assert _thread_state(bw, ref2.thread_id) == ("closed", intents.REASON_BOOKED)  # stays closed
    assert _sweep(bw) == 0
    row = _intent_row(bw, intent_id)
    with bw.db.session() as s:
        intents.reopen_intent(s, intent_public_id=intent_id, owner_user_id=bw.w.client_id, expected_version=row["version"])
        s.commit()
    row = _intent_row(bw, intent_id)
    assert (row["status"], row["booking_id"], row["terms"]) == ("active", None, 2)
    assert _thread_state(bw, ref2.thread_id) == ("closed", intents.REASON_BOOKED)  # old offers never come back
    fresh = _propose(bw, listing2, bw.w.client_id, _proposal(bw, intent_id, row["version_no"]))
    assert accept(bw, fresh, bw.w.driver2_id).trip_intent_id == row["id"]  # an explicit new offer books again


# --- HTTP: session owner, idempotent retry, timeout replay -------------------------------------------------------------


def test_http_owner_from_session_and_retries_with_the_same_key_make_one_offer_and_one_booking(bw: BW, client: TestClient) -> None:  # noqa: F811
    body = _intent_body(bw)
    created = client.post("/api/v2/me/trip-intents", json=body, headers=auth(bw.w.client_id, "client", "intent-key-1"))
    again = client.post("/api/v2/me/trip-intents", json=body, headers=auth(bw.w.client_id, "client", "intent-key-1"))
    assert created.status_code == again.status_code == 201, created.text
    intent = created.json()["data"]
    assert again.json()["data"]["id"] == intent["id"]
    assert scalar(bw.db, "SELECT count(*) FROM trip_intents") == 1  # the replay made nothing new
    assert client.get(f"/api/v2/me/trip-intents/{intent['id']}", headers=auth(bw.w.client2_id, "client")).status_code == 404
    listing, _ = _offer(bw, bw.w.driver_id, "01T220TA")
    fit = client.get(f"/api/v2/me/trip-intents/{intent['id']}/fit", params={"listing_id": listing},
                     headers=auth(bw.w.client_id, "client"))
    assert fit.status_code == 200 and fit.json()["data"]["availability"]["status"] == "ok"
    proposal = _proposal(bw, intent["id"], intent["current_version"]["version_no"]).model_dump(mode="json")
    sent = [client.post(f"/api/v2/listings/{listing}/proposals", json=proposal,
                        headers=auth(bw.w.client_id, "client", "offer-key-1")) for _ in range(2)]  # a timeout retry
    assert [r.status_code for r in sent] == [201, 201], sent[0].text
    assert sent[0].json()["data"]["id"] == sent[1].json()["data"]["id"]
    assert sent[0].json()["data"]["trip_intent_id"] == intent["id"]
    thread = sent[0].json()["data"]
    accept_body = {"proposal_version_id": thread["current_version"]["id"],
                   "expected_listing_version": listing_version(bw, listing)}
    accepted = [client.post(f"/api/v2/proposals/{thread['id']}/accept", json=accept_body,
                            headers=auth(bw.w.driver_id, "driver", "accept-key-1")) for _ in range(2)]
    assert [r.status_code for r in accepted] == [201, 201], accepted[0].text
    assert accepted[0].json()["data"]["id"] == accepted[1].json()["data"]["id"]
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1 and scalar(bw.db, "SELECT count(*) FROM wallet_holds") == 1
    edited = client.patch(f"/api/v2/me/trip-intents/{intent['id']}", headers=auth(bw.w.client_id, "client", "edit-key-1"),
                          json=_update_body(bw, intent["version"] + 1, quantity=2).model_dump(mode="json"))
    assert edited.status_code == 409 and edited.json()["error"]["code"] == "TRIP_INTENT_BOOKED"
