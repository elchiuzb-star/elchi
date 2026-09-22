"""Accept orchestrator on real PostgreSQL 16 (spec §15; AC02-AC12, AC19, AC41, AC43; Q16, Q21, Q54; D3)."""

from __future__ import annotations

import json
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking, BookingAllocation
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.platform.service import CommandResult, run_idempotent
from app.modules.trips import service as trips_service
from tests.pg.bookings.conftest import (
    BW,
    STAGGER_S,
    USERS_LOCK,
    accept,
    add_user,
    auth,
    counter,
    domain_error,
    driver_trip,
    fund,
    hold_inside,
    listing_version,
    parcel_request_body,
    passenger_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    rows,
    scalar,
    seats_used,
    set_flag,
    wallet,
)
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import passenger_offer

pytestmark = pytest.mark.pg

# --- AC03 / AC02: accept from both listing kinds --------------------------------------------------------------------------


def test_ac03_client_accepts_driver_proposal_on_request(bw: BW) -> None:
    listing, trip_id, trip_public, ref = request_with_driver_proposal(bw)
    booking = accept(bw, ref, bw.w.client_id)

    with bw.db.session() as s:
        b = s.get(Booking, booking.id)
        assert (b.service_status, b.cash_status, b.commission_status, b.version) == ("confirmed", "unpaid", "held", 1)
        assert (b.quantity, b.unit_price_minor, b.total_minor, b.fee_bps, b.commission_minor) == (2, 19_000_000, 38_000_000, 1500, 5_700_000)
        assert (b.pickup_occurrence_seq, b.dropoff_occurrence_seq, b.seats) == (1, 4, 2)
        assert b.terms_snapshot["flags"]["passenger_enabled"] is True and b.terms_snapshot["fee"]["fee_bps"] == 1500
        allocations = s.query(BookingAllocation).filter_by(booking_id=b.id).order_by(BookingAllocation.segment_from_seq).all()
        assert [(a.segment_from_seq, a.seats, a.active) for a in allocations] == [(1, 2, True), (2, 2, True), (3, 2, True)]
        thread = marketplace_service.get_thread_by_public_id(s, ref.thread_id)
        assert thread.state == "accepted" and marketplace_service.current_version(s, thread).status == "accepted"
        assert marketplace_service.get_listing_by_public_id(s, listing).status == "fulfilled"
    assert seats_used(bw, trip_id) == [2, 2, 2]
    assert wallet(bw, bw.w.driver_id) == (100_000_000, 5_700_000)
    assert rows(bw.db, "SELECT amount_minor, status, fee_bps FROM wallet_holds WHERE booking_id = :b", b=booking.id) == [(5_700_000, "active", 1500)]
    events = [r.event_type for r in rows(bw.db, "SELECT event_type FROM outbox_events ORDER BY id")]
    assert events[-2:] == ["wallet.hold.created", "booking.accepted"] or events[-2:] == ["booking.accepted", "wallet.hold.created"]
    history = rows(bw.db, "SELECT machine, from_status, to_status, command FROM booking_status_history WHERE booking_id = :b ORDER BY id", b=booking.id)
    assert [tuple(r) for r in history] == [("service", None, "confirmed", "accept"), ("cash", None, "unpaid", "accept"), ("commission", None, "held", "hold_fee")]


def test_ac02_driver_accepts_client_proposal_on_trip_offer(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A101AA", seats=3)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    ref = propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000, pickup="B", dropoff="D")
    booking = accept(bw, ref, bw.w.driver_id)
    with bw.db.session() as s:
        b = s.get(Booking, booking.id)
        assert (b.request_listing_id, b.supply_listing_id is not None, b.pickup_occurrence_seq, b.dropoff_occurrence_seq) == (None, True, 2, 4)
        assert marketplace_service.get_listing_by_public_id(s, offer).status == "published"  # seats remain: the offer stays open
    assert seats_used(bw, trip_id) == [0, 1, 1]


def test_trip_offer_is_fulfilled_when_its_last_seat_is_taken_and_other_threads_expire(bw: BW) -> None:
    _, trip_public = driver_trip(bw, bw.w.driver_id, "01A102AA", seats=1)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    first = propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000)
    second = propose(bw, offer, bw.w.client2_id, trip_public_id=None, quantity=1, unit=20_000_000)
    accept(bw, first, bw.w.driver_id)
    with bw.db.session() as s:
        assert marketplace_service.get_listing_by_public_id(s, offer).status == "fulfilled"
        other = marketplace_service.get_thread_by_public_id(s, second.thread_id)
        assert (other.state, marketplace_service.current_version(s, other).status_reason) == ("closed", "capacity_gone")


# --- AC04 / AC05 / Q54 / listing version ----------------------------------------------------------------------------------


def test_ac04_stale_version_after_counter_is_rejected_without_booking(bw: BW) -> None:
    _, trip_id, _, ref = request_with_driver_proposal(bw)
    countered = counter(bw, ref, bw.w.client_id, unit=18_000_000)
    error = domain_error(lambda: accept(bw, ref, bw.w.client_id))  # the old revision the client saw
    assert error.code is ErrorCode.PROPOSAL_CHANGED and error.http_status == 409
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0 and seats_used(bw, trip_id) == [0, 0, 0]
    assert countered.revision == 2


def test_ac05_author_cannot_accept_own_version(bw: BW) -> None:
    _, _, _, ref = request_with_driver_proposal(bw)
    error = domain_error(lambda: accept(bw, ref, bw.w.driver_id))
    assert error.code is ErrorCode.NOT_PROPOSAL_RECIPIENT and error.http_status == 403
    stranger = domain_error(lambda: accept(bw, ref, bw.w.client2_id))
    assert stranger.code is ErrorCode.NOT_FOUND


def test_q54_listing_terms_changed_and_listing_version_mismatch(bw: BW) -> None:
    listing, _, _, ref = request_with_driver_proposal(bw)
    wrong = domain_error(lambda: accept(bw, ref, bw.w.client_id, expected_listing_version=listing_version(bw, listing) + 1))
    assert wrong.code is ErrorCode.PROPOSAL_CHANGED and wrong.details["reason"] == "listing_terms_version_mismatch"
    with bw.db.engine.begin() as conn:  # a non-material edit bumps listings.version only: accept still works later (Q54)
        conn.execute(text("UPDATE listings SET version = version + 1 WHERE kind = 'request'"))
    with bw.db.engine.begin() as conn:  # a proposal-invalidating edit that A1 did not expire (defence in depth)
        conn.execute(text("UPDATE listings SET terms_version = terms_version + 1, version = version + 1 WHERE public_id IN "
                          "(SELECT public_id FROM listings WHERE kind = 'request')"))
    error = domain_error(lambda: accept(bw, ref, bw.w.client_id))
    assert error.code is ErrorCode.PROPOSAL_CHANGED and error.details["reason"] == "listing_terms_changed"
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0


def test_expired_version_cutoff_route_and_flags(bw: BW) -> None:
    _, trip_id, _, ref = request_with_driver_proposal(bw)
    late = domain_error(lambda: accept(bw, ref, bw.w.client_id, now=utc_now() + timedelta(hours=3)))
    assert late.code is ErrorCode.PROPOSAL_EXPIRED
    set_flag(bw.db, "passenger_enabled", False)
    assert domain_error(lambda: accept(bw, ref, bw.w.client_id)).code is ErrorCode.FEATURE_DISABLED
    set_flag(bw.db, "passenger_enabled", True)
    with bw.db.engine.begin() as conn:  # the pickup occurrence moved 3 h later: the agreed window no longer meets it
        conn.execute(text("UPDATE trip_stop_occurrences SET planned_arrival_at = planned_arrival_at + interval '3 hours' "
                          "WHERE trip_id = :t"), {"t": trip_id})
    route = domain_error(lambda: accept(bw, ref, bw.w.client_id))
    assert route.code is ErrorCode.ROUTE_CHANGED and route.details["reason"] == "schedule_changed"
    with bw.db.engine.begin() as conn:
        conn.execute(text("UPDATE trip_stop_occurrences SET planned_arrival_at = planned_arrival_at - interval '3 hours' WHERE trip_id = :t"),
                     {"t": trip_id})
        conn.execute(text("UPDATE trips SET version = version + 1 WHERE id = :t"), {"t": trip_id})  # raw version alone never blocks
        conn.execute(text("UPDATE trips SET booking_cutoff_at = now() - interval '1 minute' WHERE id = :t"), {"t": trip_id})
    assert domain_error(lambda: accept(bw, ref, bw.w.client_id)).code is ErrorCode.BOOKING_CUTOFF_PASSED
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0


# --- AC06 / AC07 / AC08 / AC09 --------------------------------------------------------------------------------------------


def test_ac06_two_drivers_accept_the_same_demand_in_parallel(bw: BW) -> None:
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=2))
    _, trip1 = driver_trip(bw, bw.w.driver_id, "01A110AA")
    _, trip2 = driver_trip(bw, bw.w.driver2_id, "01A111AA")
    ref1 = counter(bw, propose(bw, listing, bw.w.driver_id, trip_public_id=trip1), bw.w.client_id, unit=18_500_000)
    ref2 = counter(bw, propose(bw, listing, bw.w.driver2_id, trip_public_id=trip2), bw.w.client_id, unit=18_400_000)
    expected = listing_version(bw, listing)

    def work(index: int, session: Session) -> str:
        ref, driver = (ref1, bw.w.driver_id) if index == 0 else (ref2, bw.w.driver2_id)
        return bookings_service.booking_public_id(accept(bw, ref, driver, session=session, expected_listing_version=expected))

    for _ in range(1):
        report = run_concurrently(2, work, engine=bw.db.engine)
        assert len(report.successes) == 1, report.results
        assert all(isinstance(r.error, DomainError) and r.error.code in (ErrorCode.PROPOSAL_CHANGED, ErrorCode.LISTING_NOT_OPEN)
                   for r in report.failures), report.failures
    assert scalar(bw.db, "SELECT count(*) FROM bookings WHERE service_status <> 'cancelled'") == 1
    assert scalar(bw.db, "SELECT count(*) FROM wallet_holds") == 1


def test_ac07_twenty_parallel_accepts_for_the_last_seat(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A120AA", seats=1)
    refs = []
    with bw.db.session() as s:
        clients = [add_user(s, f"+99890100{i:04d}", "client", full_name=f"Client {i}") for i in range(20)]
        s.commit()
    for client_id in clients:
        listing = publish_listing(bw, client_id, passenger_request_body(bw, seats=1))
        refs.append((client_id, propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1)))

    def work(index: int, session: Session) -> int:
        client_id, ref = refs[index]
        return accept(bw, ref, client_id, session=session).id

    report = run_concurrently(20, work, engine=bw.db.engine)
    assert len(report.successes) == 1, [r.error for r in report.failures][:3]
    assert {r.error.code for r in report.failures} == {ErrorCode.CAPACITY_UNAVAILABLE}
    assert seats_used(bw, trip_id) == [1, 1, 1]
    assert scalar(bw.db, "SELECT count(*) FROM booking_allocations WHERE active") == 3
    assert wallet(bw, bw.w.driver_id)[1] == 2_850_000  # exactly one hold (19 000 000 x 15%)


def _accept_idempotent(bw: BW, session: Session, ref, actor_id: int, key: str, body: dict):  # noqa: ANN001, ANN202
    def handler() -> CommandResult:
        booking = bookings_service.accept_proposal(
            session, thread_public_id=ref.thread_id, actor_user_id=actor_id, proposal_version_public_id=body["proposal_version_id"],
            expected_listing_version=body["expected_listing_version"],
        )
        return CommandResult(201, {"success": True, "data": {"id": bookings_service.booking_public_id(booking), "version": booking.version}})

    result = run_idempotent(
        session, actor_user_id=actor_id, method="POST", route_template="/api/v2/proposals/{thread_id}/accept",
        idempotency_key=key, body=body, handler=handler, path_params={"thread_id": ref.thread_id},
    )
    session.commit()
    return result


def test_ac08_same_key_five_times_in_parallel_one_booking_one_hold_same_response(bw: BW) -> None:
    listing, _, _, ref = request_with_driver_proposal(bw)
    body = {"proposal_version_id": ref.version_id, "expected_listing_version": listing_version(bw, listing)}
    report = run_concurrently(5, lambda i, s: _accept_idempotent(bw, s, ref, bw.w.client_id, "accept-key-ac08", body), engine=bw.db.engine)
    assert report.failures == []
    bodies = {json.dumps(r.value.body, sort_keys=True) for r in report.successes}
    assert len(bodies) == 1 and {r.value.status_code for r in report.successes} == {201}
    assert sum(1 for r in report.successes if r.value.replayed) == 4
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1 and scalar(bw.db, "SELECT count(*) FROM wallet_holds") == 1


def test_ac08_ac09_http_replay_and_key_reuse(bw: BW, client) -> None:  # noqa: ANN001
    listing, _, _, ref = request_with_driver_proposal(bw)
    body = {"proposal_version_id": ref.version_id, "expected_listing_version": listing_version(bw, listing)}
    url = f"/api/v2/proposals/{ref.thread_id}/accept"
    first = client.post(url, json=body, headers=auth(bw.w.client_id, "client", "accept-http-0001"))
    assert first.status_code == 201, first.text
    data = first.json()["data"]
    assert data["id"].startswith("bkg_") and data["viewer_side"] == "client"
    assert "commission_status" not in data and "fee" not in data  # Q16: no commission keys for the client
    assert data["driver"]["contact_phone"] is None and data["contact"]["phones_visible"] is False  # Q44
    replay = client.post(url, json=body, headers=auth(bw.w.client_id, "client", "accept-http-0001"))
    assert replay.status_code == 201 and replay.headers.get("Idempotent-Replayed") == "true" and replay.json() == first.json()
    reused = client.post(url, json={**body, "expected_listing_version": body["expected_listing_version"] + 7},
                         headers=auth(bw.w.client_id, "client", "accept-http-0001"))
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1
    driver_view = client.get(f"/api/v2/bookings/{data['id']}", headers=auth(bw.w.driver_id, "driver")).json()["data"]
    assert driver_view["commission_status"] == "held" and driver_view["fee"]["commission_minor"] == 5_700_000
    assert driver_view["client"]["contact_phone"] is None and driver_view["client"]["display_name"] == "Aziza"
    stale = client.post(url, json=body, headers=auth(bw.w.client_id, "client", "accept-http-0002"))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "PROPOSAL_CHANGED"


# --- AC10 / AC11 / AC12 capacity through accept ----------------------------------------------------------------------------


def test_ac10_ac11_segment_capacity_through_accept(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A130AA", seats=4)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    with bw.db.session() as s:
        c3 = add_user(s, "+998901200003", "client", full_name="Uchinchi Mijoz")
        c4 = add_user(s, "+998901200004", "client", full_name="Tortinchi Mijoz")
        s.commit()
    a_c = propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=2, unit=15_000_000, pickup="A", dropoff="C")
    b_d = propose(bw, offer, bw.w.client2_id, trip_public_id=None, quantity=1, unit=15_000_000, pickup="B", dropoff="D")
    a_d = propose(bw, offer, c3, trip_public_id=None, quantity=2, unit=15_000_000, pickup="A", dropoff="D")
    c_d = propose(bw, offer, c4, trip_public_id=None, quantity=3, unit=15_000_000, pickup="C", dropoff="D")
    accept(bw, a_c, bw.w.driver_id)
    accept(bw, b_d, bw.w.driver_id)
    assert seats_used(bw, trip_id) == [2, 3, 1]  # A-B 2, B-C 3 (remaining 1), C-D 1
    error = domain_error(lambda: accept(bw, a_d, bw.w.driver_id))
    assert error.code is ErrorCode.CAPACITY_UNAVAILABLE and {seg["from_seq"] for seg in error.details["segments"]} == {2}  # AC10
    accept(bw, c_d, bw.w.driver_id)  # AC11: C-D for 3 fits
    assert seats_used(bw, trip_id) == [2, 3, 4]


def test_ac12_baggage_over_capacity_is_cargo_limit_exceeded(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A140AA", seats=4, baggage_ml=200_000)
    first = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=1, baggage_ml=150_000))
    second = publish_listing(bw, bw.w.client2_id, passenger_request_body(bw, seats=1, baggage_ml=150_000))
    ref1 = propose(bw, first, bw.w.driver_id, trip_public_id=trip_public, quantity=1)
    ref2 = propose(bw, second, bw.w.driver_id, trip_public_id=trip_public, quantity=1)
    accept(bw, ref1, bw.w.client_id)
    error = domain_error(lambda: accept(bw, ref2, bw.w.client2_id))
    assert error.code is ErrorCode.CARGO_LIMIT_EXCEEDED
    assert [load.baggage_used_ml for load in trips_service.get_segment_loads(bw.db.session(), trip_id)] == [150_000] * 3


# --- AC19 balance / AC43 frozen quote / D3 exempt ------------------------------------------------------------------------


def test_ac19_insufficient_commission_balance_rolls_back_everything(bw: BW) -> None:
    with bw.db.session() as s:
        poor = add_user(s, "+998900000399", "driver", full_name="Kambag'al Haydovchi", driver_status="approved")
        s.commit()
    fund(bw, poor, 10_000_000, bw.super_id)  # 100 000 so'm
    listing1 = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=2, unit=20_000_000))
    listing2 = publish_listing(bw, bw.w.client2_id, passenger_request_body(bw, seats=1, unit=20_000_000, origin="B",
                                                                         start=bw.base + timedelta(hours=1)))
    trip_id, trip_public = driver_trip(bw, poor, "01A150AA", seats=4)
    ref1 = propose(bw, listing1, poor, trip_public_id=trip_public, quantity=2, unit=20_000_000)  # 400 000 -> hold 60 000
    ref2 = propose(bw, listing2, poor, trip_public_id=trip_public, quantity=1, unit=33_333_300, pickup="B")  # hold ~50 000
    accept(bw, ref1, bw.w.client_id)
    assert wallet(bw, poor) == (10_000_000, 6_000_000)  # available 40 000 so'm
    error = domain_error(lambda: accept(bw, ref2, bw.w.client2_id))
    assert error.code is ErrorCode.INSUFFICIENT_COMMISSION_BALANCE and error.details in (None, {})  # no balance figures (Q16)
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1 and seats_used(bw, trip_id) == [2, 2, 2]
    with bw.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, ref2.thread_id)
        assert thread.state == "open" and marketplace_service.get_listing_by_public_id(s, listing2).status == "published"


def test_ac43_frozen_fee_quote_and_d3_exempt_campaign(bw: BW) -> None:
    listing, _, trip_public, ref = request_with_driver_proposal(bw)  # quoted at 1500 bps
    with bw.db.engine.begin() as conn:
        campaign = conn.execute(
            text("INSERT INTO commission_policies (public_id, kind, scope_corridor_id, fee_bps, effective_from, effective_to, campaign_name, "
                 "reason, created_by) VALUES (gen_random_uuid(), 'campaign', :c, 0, now(), now() + interval '30 days', 'Pilot 0%', 'A4', :a) "
                 "RETURNING id, public_id"),
            {"c": bw.w.corridor_id, "a": bw.super_id},
        ).one()
    booking = accept(bw, ref, bw.w.client_id)  # AC43: the frozen 1500 bps quote is used, not today's 0%
    assert (booking.fee_bps, booking.commission_status, booking.commission_minor) == (1500, "held", 5_700_000)

    bw.w.fees.policy_id, bw.w.fees.fee_bps, bw.w.fees.policy_kind = campaign.id, 0, "campaign"  # new quotes see the campaign
    other = publish_listing(bw, bw.w.client2_id, passenger_request_body(bw, seats=1, origin="B", start=bw.base + timedelta(hours=1)))
    exempt_ref = propose(bw, other, bw.w.driver_id, trip_public_id=trip_public, quantity=1, pickup="B")
    exempt = accept(bw, exempt_ref, bw.w.client2_id)
    assert (exempt.fee_bps, exempt.commission_status, exempt.commission_minor) == (0, "exempt", 0)
    assert scalar(bw.db, "SELECT count(*) FROM wallet_holds WHERE booking_id = :b", b=exempt.id) == 0  # D3: no hold row
    with pytest.raises(DBAPIError, match="exempt is terminal"), bw.db.engine.begin() as conn:  # exempt never becomes held
        conn.execute(text("UPDATE bookings SET commission_status = 'held', version = version + 1 WHERE id = :b"), {"b": exempt.id})
    with pytest.raises(IntegrityError, match="ck_bookings_exempt_iff_zero_bps"), bw.db.engine.begin() as conn:  # D3
        conn.execute(text("UPDATE bookings SET commission_status = 'exempt', version = version + 1 WHERE id = :b"), {"b": booking.id})


# --- AC41 eligibility block vs accept ---------------------------------------------------------------------------------------


def _eligibility_version(bw: BW) -> int:
    with bw.db.session() as s:
        return identity_service.eligibility_version(s, bw.w.driver_id)


def _block(bw: BW, session: Session, expected_version: int) -> None:
    # expected_version is read before the race, so a hook on eligibility_version fires only inside the users lock.
    identity_service.block_driver_eligibility(
        session, driver_user_id=bw.w.driver_id, actor_user_id=bw.w.admin_id, expected_version=expected_version, reason="AC41 test",
    )
    session.commit()


def test_ac41_block_before_accept_denies_after_accept_keeps_booking(bw: BW, lock_clock, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    clock = lock_clock(USERS_LOCK)
    _, _, _, ref = request_with_driver_proposal(bw, plate="01A160AA")
    expected = _eligibility_version(bw)
    early_thread: dict[str, int] = {}

    # (1) block first: the block holds the users lock; accept waits on it and then sees the block.
    hold_inside(monkeypatch, identity_service, "eligibility_version", only_thread=lambda: threading.get_ident() == early_thread.get("block"))

    def work(index: int, session: Session) -> str:
        clock.bind(index)
        if index == 0:
            early_thread["block"] = threading.get_ident()
            _block(bw, session, expected)
            return "blocked"
        time.sleep(STAGGER_S)
        accept(bw, ref, bw.w.client_id, session=session)
        return "booked"

    report = run_concurrently(2, work, engine=bw.db.engine)
    assert report.results[0].value == "blocked"
    assert isinstance(report.results[1].error, DomainError) and report.results[1].error.code is ErrorCode.DRIVER_NOT_ELIGIBLE
    clock.assert_waited(early=0, late=1)
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0


def test_ac41_accept_before_block_is_a_legal_booking(bw: BW, lock_clock, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    clock = lock_clock(USERS_LOCK)
    _, _, _, ref = request_with_driver_proposal(bw, plate="01A161AA")
    expected = _eligibility_version(bw)
    early: dict[str, int] = {}
    hold_inside(monkeypatch, marketplace_service, "version_demand", only_thread=lambda: threading.get_ident() == early.get("accept"))

    def work(index: int, session: Session) -> str:
        clock.bind(index)
        if index == 0:
            early["accept"] = threading.get_ident()
            accept(bw, ref, bw.w.client_id, session=session)
            return "booked"
        time.sleep(STAGGER_S)
        _block(bw, session, expected)
        return "blocked"

    report = run_concurrently(2, work, engine=bw.db.engine)
    assert [r.value for r in report.results] == ["booked", "blocked"], report.results
    clock.assert_waited(early=0, late=1)
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1  # booked before the block: D16 keeps the obligation


def test_ac41_negative_control_without_users_lock_books_a_blocked_driver(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: skipping the users lock lets the block commit inside accept, which then books anyway."""
    seen_illegal = False
    for round_no in range(3):
        _, _, _, ref = request_with_driver_proposal(bw, plate=f"01A17{round_no}AA")
        expected = _eligibility_version(bw)
        early: dict[str, int] = {}
        monkeypatch.setattr(identity_service, "lock_user_eligibility", lambda session, user_ids, mode="update": list(user_ids))
        hold_inside(monkeypatch, marketplace_service, "version_demand", only_thread=lambda: threading.get_ident() == early.get("accept"))
        order: list[str] = []

        def work(index: int, session: Session) -> str:
            if index == 0:
                early["accept"] = threading.get_ident()
                accept(bw, ref, bw.w.client_id, session=session)
                order.append("accept")
                return "booked"
            time.sleep(STAGGER_S)
            _block(bw, session, expected)
            order.append("block")
            return "blocked"

        report = run_concurrently(2, work, engine=bw.db.engine)
        monkeypatch.undo()
        if [r.value for r in report.results] == ["booked", "blocked"] and order == ["block", "accept"]:
            seen_illegal = True  # the block committed first, yet the booking exists
            break
        with bw.db.engine.begin() as conn:  # lift the block for the next round
            conn.execute(text("UPDATE driver_eligibility_blocks SET lifted_at = now(), lifted_by = :a, lift_reason = 'next round' "
                              "WHERE lifted_at IS NULL"), {"a": bw.w.admin_id})
    assert seen_illegal, "negative control did not reproduce the race; the lock test would not detect a missing lock"


# --- DB invariants and failure at COMMIT -------------------------------------------------------------------------------------


def test_db_invariants_snapshot_release_contract_and_capacity_consistency(bw: BW) -> None:
    _, trip_id, _, ref = request_with_driver_proposal(bw)
    booking = accept(bw, ref, bw.w.client_id)
    for statement, match in (
        # Q60 (0056): amounts change only with an accepted amendment - the freeze trigger fires before the CHECK.
        ("UPDATE bookings SET total_minor = 1, unit_price_minor = 1, version = version + 1 WHERE id = :b", r"accepted amendment \(Q60\)"),
        ("UPDATE bookings SET fee_bps = 1000 WHERE id = :b", "immutable"),
        ("UPDATE bookings SET driver_user_id = client_user_id WHERE id = :b", "immutable"),
        ("DELETE FROM bookings WHERE id = :b", "cannot be deleted"),
        ("DELETE FROM booking_allocations WHERE booking_id = :b", "cannot be deleted"),
        ("UPDATE booking_allocations SET seats = 9 WHERE booking_id = :b", "immutable"),
        ("UPDATE booking_status_history SET command = 'x' WHERE booking_id = :b", "append-only"),
    ):
        with pytest.raises(DBAPIError, match=match), bw.db.engine.begin() as conn:
            conn.execute(text(statement), {"b": booking.id})
    # Counters and allocations disagree -> the deferred trigger refuses at COMMIT (release without counter update).
    with pytest.raises(DBAPIError, match="does not equal its active booking allocations"), bw.db.engine.begin() as conn:
        conn.execute(text("UPDATE booking_allocations SET active = false, released_at = now() WHERE booking_id = :b AND segment_from_seq = 1"), {"b": booking.id})
    assert seats_used(bw, trip_id) == [2, 2, 2]
    # Release contract at the DB: a consistent release commits, but a released allocation never re-activates.
    with bw.db.engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("UPDATE booking_allocations SET active = false, released_at = now() WHERE booking_id = :b"), {"b": booking.id})
        conn.execute(text("UPDATE trip_segment_resources SET seats_used = seats_used - 2 WHERE trip_id = :t"), {"t": trip_id})
        with pytest.raises(DBAPIError, match="cannot be re-activated"):
            with conn.begin_nested():
                conn.execute(text("UPDATE booking_allocations SET active = true, released_at = NULL WHERE booking_id = :b"), {"b": booking.id})
        tx.rollback()
    with pytest.raises(IntegrityError, match="uq_bookings_accepted_proposal_version"), bw.db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bookings (public_id, service_type, service_status, commission_status, client_user_id, driver_user_id, trip_id, "
                "corridor_id, request_listing_id, supply_listing_id, proposal_thread_id, accepted_proposal_version_id, route_version_id, "
                "trip_version, pickup_stop_id, dropoff_stop_id, pickup_occurrence_seq, dropoff_occurrence_seq, pickup_window_start, "
                "pickup_window_end, quantity, seats, price_basis, unit_price_minor, total_minor, fee_policy_id, fee_bps, commission_minor, "
                "listing_version, listing_terms_version, terms_snapshot) SELECT gen_random_uuid(), service_type, 'confirmed', "
                "commission_status, client_user_id, driver_user_id, trip_id, corridor_id, NULL, request_listing_id, proposal_thread_id, "
                "accepted_proposal_version_id, route_version_id, trip_version, pickup_stop_id, dropoff_stop_id, pickup_occurrence_seq, "
                "dropoff_occurrence_seq, pickup_window_start, pickup_window_end, quantity, seats, price_basis, unit_price_minor, "
                "total_minor, fee_policy_id, fee_bps, commission_minor, listing_version, listing_terms_version, terms_snapshot "
                "FROM bookings WHERE id = :b"
            ),
            {"b": booking.id},
        )


def test_deferred_trigger_failure_at_commit_is_mapped_envelope_and_nothing_is_stored(bw: BW, client, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    listing, trip_id, _, ref = request_with_driver_proposal(bw)
    monkeypatch.setattr(trips_service, "reserve", lambda *args, **kwargs: [])  # a bookkeeping bug: allocations without usage
    body = {"proposal_version_id": ref.version_id, "expected_listing_version": listing_version(bw, listing)}
    response = client.post(f"/api/v2/proposals/{ref.thread_id}/accept", json=body, headers=auth(bw.w.client_id, "client", "accept-500-0001"))
    # Wave 2.1 (db_errors): the deferred check_violation is a 409 INTEGRITY_CONFLICT envelope, not a bare 500.
    assert response.status_code == 409 and response.json()["error"]["code"] == "INTEGRITY_CONFLICT", response.text
    assert response.json()["error"]["details"] == {"reason": "check_violation"}
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0
    assert scalar(bw.db, "SELECT count(*) FROM idempotency_records WHERE idem_key = 'accept-500-0001'") == 0
    assert scalar(bw.db, "SELECT count(*) FROM wallet_holds") == 0 and seats_used(bw, trip_id) == [0, 0, 0]
    with bw.db.session() as s:
        assert marketplace_service.get_thread_by_public_id(s, ref.thread_id).state == "open"


def test_parcel_request_accept_and_geo_counter_hook(bw: BW) -> None:
    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A180AA")
    ref = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000, dropoff="C", price_basis="total")
    booking = accept(bw, ref, bw.w.client_id)
    assert (booking.service_type, booking.cargo_weight_g, booking.cargo_volume_ml, booking.seats) == ("parcel", 2_000, 8_000, 0)
    from app.modules.geo import service as geo_service

    bookings_service.register_geo_hooks()
    try:
        with bw.db.session() as s:
            assert geo_service._active_bookings_on_corridor(s, bw.w.corridor_id) == 1  # noqa: SLF001
    finally:
        geo_service.set_active_booking_counter(None)


def test_q28_unconfirmed_seed_policy_blocks_the_production_hold(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    """Production + only the migration seed standard applies -> 503 COMMISSION_POLICY_UNCONFIRMED; nothing is booked."""
    from app.modules.wallet import service as wallet_service

    seed = rows(bw.db, "SELECT id, public_id, fee_bps FROM commission_policies WHERE created_by IS NULL AND scope_corridor_id IS NULL "
                       "AND kind = 'standard' ORDER BY id LIMIT 1")[0]
    bw.w.fees.policy_id, bw.w.fees.fee_bps = seed.id, seed.fee_bps
    listing, trip_id, _, ref = request_with_driver_proposal(bw, plate="01A190AA")
    real = wallet_service.assert_production_invariants

    def production_report(session, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        report = real(session)
        return type(report)(ok=True, is_production=True, app_environment="production", db_environment="production", checks=())

    monkeypatch.setattr(wallet_service, "require_money_invariants", production_report)
    error = domain_error(lambda: accept(bw, ref, bw.w.client_id))
    assert error.code is ErrorCode.COMMISSION_POLICY_UNCONFIRMED and error.http_status == 503
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0 and seats_used(bw, trip_id) == [0, 0, 0]


def test_openapi_declares_response_models_for_every_booking_route(client) -> None:  # noqa: ANN001
    spec = client.app.openapi()
    booking_paths = [p for p in spec["paths"] if p.startswith(("/api/v2/bookings", "/api/v2/me/bookings", "/api/v2/admin/bookings",
                                                                  "/api/v2/amendments")) or p.endswith(("/accept", "/manifest"))
                     or "/actions/" in p]
    assert len(booking_paths) >= 15
    for path in booking_paths:
        for method, op in spec["paths"][path].items():
            success = [code for code in op["responses"] if code.startswith("2")]
            assert success and "content" in op["responses"][success[0]], (method, path)
