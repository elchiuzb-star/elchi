"""Wave 2.1 booking hardening on real PostgreSQL 16 (Q59-Q66, BR blockers 1-5; AC20, AC26, AC42; T10, B12)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import ProofKind
from app.contracts.errors import ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.bookings.views import manifest_dto
from app.modules.platform import service as platform_service
from tests.pg.bookings.conftest import (
    BW,
    FUNDED_MINOR,
    accept,
    act,
    add_user,
    auth,
    booking_version,
    codes_for,
    domain_error,
    driver_trip,
    operator,
    parcel_request_body,
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

CLIENT_PHONE = "+998900000201"


def _public(booking: Booking) -> str:
    return bookings_service.booking_public_id(booking)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _captures(bw: BW) -> int:
    return int(scalar(bw.db, "SELECT count(*) FROM ledger_transactions WHERE reference_kind = 'commission_capture'"))


def _boarding_passenger(bw: BW, plate: str, *, client_id: int | None = None, driver_id: int | None = None):  # noqa: ANN202
    client_id, driver_id = client_id or bw.w.client_id, driver_id or bw.w.driver_id
    listing, trip_id, trip_public, ref = request_with_driver_proposal(bw, plate=plate, client_id=client_id, driver_id=driver_id)
    booking = accept(bw, ref, client_id)
    assert run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30)) == "boarding"
    return listing, trip_id, trip_public, booking


def _arrived_passenger(bw: BW, plate: str, *, client_id: int | None = None, driver_id: int | None = None):  # noqa: ANN202
    client_id, driver_id = client_id or bw.w.client_id, driver_id or bw.w.driver_id
    _, trip_id, _, booking = _boarding_passenger(bw, plate, client_id=client_id, driver_id=driver_id)
    act(bw, booking.id, driver_id, "board", code=codes_for(bw, booking.id, client_id)["boarding_code"], now=bw.base + timedelta(minutes=5))
    act(bw, booking.id, driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    return trip_id, booking


def _parcel_booking(bw: BW, plate: str, *, driver_id: int | None = None):  # noqa: ANN202
    driver_id = driver_id or bw.w.driver_id
    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    trip_id, trip_public = driver_trip(bw, driver_id, plate)
    ref = propose(bw, listing, driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000, dropoff="C", price_basis="total")
    return trip_id, accept(bw, ref, bw.w.client_id)


def _parcel_in_transit(bw: BW, plate: str, *, driver_id: int | None = None):  # noqa: ANN202
    driver_id = driver_id or bw.w.driver_id
    trip_id, booking = _parcel_booking(bw, plate, driver_id=driver_id)
    run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    codes = codes_for(bw, booking.id, bw.w.client_id)
    act(bw, booking.id, driver_id, "pick_up", code=codes["pickup_code"], now=bw.base)
    run_trip_action(bw, trip_id, driver_id, "depart", now=bw.base + timedelta(minutes=5))
    act(bw, booking.id, driver_id, "start_transit", now=bw.base + timedelta(minutes=6))
    return trip_id, booking, codes


def _report_no_show(bw: BW, booking_id: int) -> None:
    act(bw, booking_id, bw.w.driver_id, "arrive_at_pickup", now=bw.base, observed_at=bw.base)
    act(bw, booking_id, bw.w.driver_id, "report_no_show", now=bw.base + timedelta(minutes=11),
        contact_attempts=({"at": bw.base.isoformat(), "channel": "chat"},))


def _queue(bw: BW, actor_id: int, queue: str, *, now: datetime | None = None) -> list[int]:
    with bw.db.session() as s:
        return [b.id for b in bookings_service.admin_queue(s, actor_user_id=actor_id, queue=queue, corridor_id=None, after_id=None,
                                                           limit=50, now=now)]


# --- Q61 (BR blocker 1): vehicle status re-checked at accept, existing bookings continue --------------------------------------


def test_q61_unapproved_vehicle_blocks_new_bookings_only(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01C100AA", seats=3)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    first = propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000)
    second = propose(bw, offer, bw.w.client2_id, trip_public_id=None, quantity=1, unit=20_000_000)
    booking = accept(bw, first, bw.w.driver_id)
    for status in ("rejected", "blocked"):
        with bw.db.engine.begin() as conn:
            conn.execute(text("UPDATE vehicles SET verification_status = :s WHERE id = (SELECT vehicle_id FROM trips WHERE id = :t)"),
                         {"s": status, "t": trip_id})
        error = domain_error(lambda: accept(bw, second, bw.w.driver_id))
        assert error.code is ErrorCode.VEHICLE_NOT_ELIGIBLE and error.http_status == 409
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1 and seats_used(bw, trip_id) == [1, 1, 1]
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    code = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    assert act(bw, booking.id, bw.w.driver_id, "board", code=code, now=bw.base).service_status == "onboard"  # obligation continues


# --- Q60 (BR blocker 2): DB snapshot freeze; amendment path passes --------------------------------------------------------------


def test_q60_snapshot_columns_frozen_in_db_and_amendment_path_passes(bw: BW) -> None:
    _, _, _, ref = request_with_driver_proposal(bw, plate="01C101AA")
    booking = accept(bw, ref, bw.w.client_id)
    for statement in (
        "UPDATE bookings SET quantity = 3, seats = 3, total_minor = unit_price_minor * 3, version = version + 1 WHERE id = :b",
        "UPDATE bookings SET commission_minor = commission_minor + 1, version = version + 1 WHERE id = :b",
        "UPDATE bookings SET pickup_window_end = pickup_window_end + interval '1 hour', version = version + 1 WHERE id = :b",
        "UPDATE bookings SET price_basis = 'total', total_minor = unit_price_minor, version = version + 1 WHERE id = :b",
    ):
        with pytest.raises(DBAPIError) as info, bw.db.engine.begin() as conn:
            conn.execute(text(statement), {"b": booking.id})
        assert platform_service.constraint_name_of(info.value) == "booking_snapshot_frozen", statement
    with pytest.raises(DBAPIError) as forged, bw.db.engine.begin() as conn:  # a forged marker without an accepted amendment
        conn.execute(text("SELECT set_config('elchi.booking_amendments_accepted', ',1,2,3,', true)"))
        conn.execute(text("UPDATE bookings SET unit_price_minor = 1000, total_minor = 2000, version = version + 1 WHERE id = :b"),
                     {"b": booking.id})
    assert platform_service.constraint_name_of(forged.value) == "booking_snapshot_frozen"
    with bw.db.engine.begin() as conn:  # non-snapshot columns stay writable
        conn.execute(text("UPDATE bookings SET updated_at = now(), version = version + 1 WHERE id = :b"), {"b": booking.id})

    with bw.db.session() as s:
        amendment = bookings_service.create_amendment(
            s, booking_public_id_value=_public(booking), actor_user_id=bw.w.driver_id,
            expected_version=booking_version(bw, booking.id), changes={"unit_price_minor": 18_000_000}, reason="fuel is cheaper",
        )
        s.commit()
        amendment_public = format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id)
    with bw.db.session() as s:
        updated = bookings_service.accept_amendment(s, amendment_public_id=amendment_public, actor_user_id=bw.w.client_id, expected_version=1)
        s.commit()
        assert (updated.unit_price_minor, updated.total_minor, updated.commission_minor) == (18_000_000, 36_000_000, 5_400_000)
    assert wallet(bw, bw.w.driver_id)[1] == 5_400_000


# --- BR blocker 3: proof code reissue ---------------------------------------------------------------------------------------------


def test_br3_locked_code_reissued_old_code_dead_new_code_works(bw: BW, client) -> None:  # noqa: ANN001
    _, _, _, booking = _boarding_passenger(bw, "01C102AA")
    public = _public(booking)
    old = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    wrong = "000000" if old != "000000" else "111111"
    board_url = f"/api/v2/bookings/{public}/actions/board"
    version = booking_version(bw, booking.id)
    for attempt in range(5):
        response = client.post(board_url, json={"expected_version": version, "code": wrong},
                               headers=auth(bw.w.driver_id, "driver", f"w21-wrong-{attempt:04d}"))
        assert response.status_code == 409, response.text
    locked = client.post(board_url, json={"expected_version": version, "code": old}, headers=auth(bw.w.driver_id, "driver", "w21-locked-01"))
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "PROOF_ATTEMPTS_EXCEEDED"

    reissue_url = f"/api/v2/bookings/{public}/codes/boarding_code/reissue"
    driver_try = client.post(reissue_url, json={}, headers=auth(bw.w.driver_id, "driver", "w21-reissue-drv1"))
    assert driver_try.status_code == 403 and driver_try.json()["error"]["code"] == "FORBIDDEN"
    reissued = client.post(reissue_url, json={"reason": "locked out"}, headers=auth(bw.w.client_id, "client", "w21-reissue-0001"))
    assert reissued.status_code == 200, reissued.text
    new = reissued.json()["data"]["codes"]
    assert [c["kind"] for c in new] == ["boarding_code"] and new[0]["code"] != old
    replay = client.post(reissue_url, json={"reason": "locked out"}, headers=auth(bw.w.client_id, "client", "w21-reissue-0001"))
    assert replay.headers.get("Idempotent-Replayed") == "true" and replay.json() == reissued.json()
    assert rows(bw.db, "SELECT code_rotation, failed_attempts FROM booking_proofs WHERE booking_id = :b", b=booking.id) == [(1, 0)]

    stale = client.post(board_url, json={"expected_version": version, "code": old}, headers=auth(bw.w.driver_id, "driver", "w21-old-0001"))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "PROOF_INVALID"  # the old code no longer verifies
    ok = client.post(board_url, json={"expected_version": version, "code": new[0]["code"]}, headers=auth(bw.w.driver_id, "driver", "w21-new-0001"))
    assert ok.status_code == 200 and ok.json()["data"]["service_status"] == "onboard", ok.text

    with bw.db.session() as s:
        accepted = domain_error(lambda: bookings_service.reissue_proof_code(
            s, booking_public_id_value=public, actor_user_id=bw.w.client_id, proof_kind="boarding_code"))
    assert accepted.code is ErrorCode.INVALID_STATE_TRANSITION and accepted.details["reason"] == "proof_already_accepted"
    audit = rows(bw.db, "SELECT details::text AS d FROM audit_logs WHERE action = 'booking_proof_code_reissued'")
    assert len(audit) == 1 and new[0]["code"] not in audit[0].d and old not in audit[0].d
    events = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'booking.proof_code.reissued'")
    assert len(events) == 1 and events[0].payload == {"service_type": "passenger", "proof_kind": "boarding_code", "code_rotation": 1,
                                                      "requested_by_side": "client"}


def test_br3_self_service_reissue_is_rate_limited_operator_is_not(bw: BW) -> None:
    _, _, _, ref = request_with_driver_proposal(bw, plate="01C103AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    booking = accept(bw, ref, bw.w.client2_id)
    public = _public(booking)
    t0 = utc_now()

    def reissue(at: datetime):  # noqa: ANN202
        with bw.db.session() as s:
            result = bookings_service.reissue_proof_code(s, booking_public_id_value=public, actor_user_id=bw.w.client2_id,
                                                         proof_kind="boarding_code", now=at)
            s.commit()
            return result

    reissue(t0)
    too_soon = domain_error(lambda: reissue(t0 + timedelta(seconds=30)))
    assert too_soon.code is ErrorCode.PROOF_REISSUE_LIMITED and too_soon.http_status == 429
    assert too_soon.details == {"retry_after_s": 90, "reissues_left": 2}
    reissue(t0 + timedelta(minutes=3))
    reissue(t0 + timedelta(minutes=6))
    full = domain_error(lambda: reissue(t0 + timedelta(minutes=9)))
    assert full.code is ErrorCode.PROOF_REISSUE_LIMITED and full.details["reissues_left"] == 0
    with bw.db.session() as s:
        assert domain_error(lambda: bookings_service.reissue_proof_code(
            s, booking_public_id_value=public, actor_user_id=bw.w.driver2_id, proof_kind="boarding_code")).code is ErrorCode.FORBIDDEN
        assert domain_error(lambda: bookings_service.reissue_proof_code(
            s, booking_public_id_value=public, actor_user_id=bw.w.client_id, proof_kind="boarding_code")).code is ErrorCode.NOT_FOUND
        assert domain_error(lambda: bookings_service.reissue_proof_code(
            s, booking_public_id_value=public, actor_user_id=bw.w.client2_id, proof_kind="pickup_code")).code is ErrorCode.VALIDATION_ERROR

    with bw.db.session() as s:  # operator B13: not rate-limited, reason required, audited
        b = s.get(Booking, booking.id)
        no_kind = domain_error(lambda: bookings_service.operator_command(
            s, booking_public_id_value=public, actor_user_id=bw.operator_id, command="reissue_proof_code",
            expected_version=b.version, reason="client called support"))
        assert no_kind.code is ErrorCode.VALIDATION_ERROR
    with bw.db.session() as s:
        b = s.get(Booking, booking.id)
        bookings_service.operator_command(s, booking_public_id_value=public, actor_user_id=bw.operator_id, command="reissue_proof_code",
                                          expected_version=b.version, reason="client called support", proof_kind=ProofKind.BOARDING_CODE,
                                          now=t0 + timedelta(minutes=9, seconds=10))
        s.commit()
    assert scalar(bw.db, "SELECT code_rotation FROM booking_proofs WHERE booking_id = :b", b=booking.id) == 4
    assert rows(bw.db, "SELECT actor_side, self_service FROM booking_proof_reissues WHERE booking_id = :b ORDER BY id", b=booking.id) == [
        ("client", True), ("client", True), ("client", True), ("operator", False)]
    assert scalar(bw.db, "SELECT count(*) FROM audit_logs WHERE action = 'booking_proof_code_reissued'") == 4
    with pytest.raises(DBAPIError, match="append-only"), bw.db.engine.begin() as conn:
        conn.execute(text("DELETE FROM booking_proof_reissues WHERE booking_id = :b"), {"b": booking.id})


# --- BR blocker 4: service start needs a started trip; trip cancel guard ----------------------------------------------------------


def test_br4_board_and_pick_up_on_planned_trip_are_trip_not_started_without_attempts(bw: BW) -> None:
    _, trip_id, _, ref = request_with_driver_proposal(bw, plate="01C104AA")
    booking = accept(bw, ref, bw.w.client_id)
    act(bw, booking.id, bw.w.driver_id, "mark_awaiting_pickup", now=bw.base - timedelta(hours=2))
    failures: list = []
    code = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    error = domain_error(lambda: act(bw, booking.id, bw.w.driver_id, "board", code=code, failures=failures, now=bw.base - timedelta(hours=2)))
    assert error.code is ErrorCode.TRIP_NOT_STARTED and error.http_status == 409 and error.details["trip_status"] == "planned"
    assert failures == [] and scalar(bw.db, "SELECT count(*) FROM booking_proof_attempts") == 0
    assert scalar(bw.db, "SELECT count(*) FROM booking_proofs WHERE booking_id = :b", b=booking.id) == 0

    parcel_trip, parcel = _parcel_booking(bw, "01C105AA", driver_id=bw.w.driver2_id)
    act(bw, parcel.id, bw.w.driver2_id, "mark_awaiting_pickup", now=bw.base - timedelta(hours=2))
    pickup = codes_for(bw, parcel.id, bw.w.client_id)["pickup_code"]
    parcel_error = domain_error(lambda: act(bw, parcel.id, bw.w.driver2_id, "pick_up", code=pickup, failures=failures))
    assert parcel_error.code is ErrorCode.TRIP_NOT_STARTED and failures == []

    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    assert act(bw, booking.id, bw.w.driver_id, "board", code=code, now=bw.base).service_status == "onboard"
    run_trip_action(bw, parcel_trip, bw.w.driver2_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    assert act(bw, parcel.id, bw.w.driver2_id, "pick_up", code=pickup, now=bw.base).service_status == "picked_up"


def test_br4_trip_cancel_refused_with_people_or_parcels_inside_interrupt_resume(bw: BW) -> None:
    _, trip_id, _, booking = _boarding_passenger(bw, "01C106AA")
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    boarding = domain_error(lambda: run_trip_action(bw, trip_id, bw.w.driver_id, "cancel", reason="engine", now=bw.base))
    assert boarding.code is ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS and boarding.details["bookings"] == [_public(booking)]
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "interrupt", reason="flat tyre", now=bw.base + timedelta(minutes=20)) == "interrupted"
    interrupted = domain_error(lambda: run_trip_action(bw, trip_id, bw.super_id, "cancel", reason="engine", now=bw.base + timedelta(minutes=30)))
    assert interrupted.code is ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS  # also from interrupted, also for staff
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "onboard"  # interrupt keeps bookings
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "resume", reason="fixed", now=bw.base + timedelta(minutes=40)) == "in_progress"
    assert domain_error(lambda: run_trip_action(bw, trip_id, bw.w.driver_id, "resume", reason="x", now=bw.base)).code is ErrorCode.INVALID_STATE_TRANSITION

    parcel_trip, parcel = _parcel_booking(bw, "01C107AA", driver_id=bw.w.driver2_id)
    run_trip_action(bw, parcel_trip, bw.w.driver2_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    act(bw, parcel.id, bw.w.driver2_id, "pick_up", code=codes_for(bw, parcel.id, bw.w.client_id)["pickup_code"], now=bw.base)
    custody = domain_error(lambda: run_trip_action(bw, parcel_trip, bw.w.driver2_id, "cancel", reason="engine", now=bw.base))
    assert custody.code is ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS and custody.details["bookings"] == [_public(parcel)]
    assert scalar(bw.db, "SELECT status FROM trips WHERE id = :t", t=parcel_trip) == "boarding"


def test_trip_cancel_on_planned_trip_cancels_pre_service_bookings_and_releases(bw: BW) -> None:
    listing, trip_id, _, ref = request_with_driver_proposal(bw, plate="01C108AA")
    booking = accept(bw, ref, bw.w.client_id)
    assert domain_error(lambda: run_trip_action(bw, trip_id, bw.w.driver_id, "cancel", now=bw.base)).code is ErrorCode.VALIDATION_ERROR
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "cancel", reason="car broke", now=bw.base - timedelta(hours=3)) == "cancelled"
    row = rows(bw.db, "SELECT service_status, commission_status, fault_side, cancel_reason_code FROM bookings WHERE id = :b", b=booking.id)[0]
    assert tuple(row) == ("cancelled", "released", "driver", "trip_cancelled")
    assert seats_used(bw, trip_id) == [0, 0, 0] and wallet(bw, bw.w.driver_id) == (FUNDED_MINOR, 0)
    assert scalar(bw.db, "SELECT status FROM listings WHERE public_id = (SELECT public_id FROM listings WHERE kind = 'request' LIMIT 1)") \
        == "published"  # Q19: a driver-side cancel reopens the client's request
    events = [r.event_type for r in rows(bw.db, "SELECT event_type FROM outbox_events ORDER BY id")]
    assert "trip.status_changed" in events and "booking.cancelled" in events


# --- BR blocker 5 (Q19/Q7): trip cancel never decides a pending no-show review -----------------------------------------------------


def test_br5_pending_no_show_review_refuses_trip_cancel_until_operator_decides(bw: BW) -> None:
    _, trip_id, _, booking = _boarding_passenger(bw, "01C109AA")
    _report_no_show(bw, booking.id)
    error = domain_error(lambda: run_trip_action(bw, trip_id, bw.w.driver_id, "cancel", reason="nobody came", now=bw.base + timedelta(minutes=15)))
    assert error.code is ErrorCode.NO_SHOW_REVIEW_PENDING and error.details == {"bookings": [_public(booking)]}
    assert scalar(bw.db, "SELECT status FROM no_show_reviews WHERE booking_id = :b", b=booking.id) == "pending"
    assert scalar(bw.db, "SELECT status FROM trips WHERE id = :t", t=trip_id) == "boarding"
    operator(bw, booking.id, bw.operator_id, "reject_no_show", now=bw.base + timedelta(minutes=20))
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "cancel", reason="nobody came", now=bw.base + timedelta(minutes=25)) == "cancelled"
    review = rows(bw.db, "SELECT status, decision_command, decided_by FROM no_show_reviews WHERE booking_id = :b", b=booking.id)[0]
    assert tuple(review) == ("rejected", "reject_no_show", bw.operator_id)  # decided by the operator, not by the trip cancel
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "cancelled"


# --- Q62: detour quotes refused at accept in every environment ----------------------------------------------------------------------


def test_q62_detour_quote_is_refused_at_accept(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    _, trip_id, _, ref = request_with_driver_proposal(bw, plate="01C110AA")
    monkeypatch.setattr(bookings_service, "_version_detour_quotes", lambda version: ("measured-detour",))
    monkeypatch.setattr(platform_service, "is_production", lambda session=None: False)
    error = domain_error(lambda: accept(bw, ref, bw.w.client_id))
    assert error.code is ErrorCode.ROUTE_MISMATCH and error.details == {"reason": "detour_not_available"}
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0 and seats_used(bw, trip_id) == [0, 0, 0]


# --- Q64: masked plate after accept, full plate by time / boarding ------------------------------------------------------------------


def test_q64_plate_disclosure_by_time_boarding_and_cancellation(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01C111AA", seats=3)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    first = accept(bw, propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000), bw.w.driver_id)
    second = accept(bw, propose(bw, offer, bw.w.client2_id, trip_public_id=None, quantity=1, unit=20_000_000), bw.w.driver_id)
    pickup = scalar(bw.db, "SELECT pickup_window_start FROM bookings WHERE id = :b", b=first.id)

    early = view(bw, first.id, "client", now=pickup - timedelta(hours=2))["driver"]["vehicle"]
    assert early["plate_number"] is None and early["plate_masked"] == "01****AA" and early["make_model"] and early["color"]
    assert _parse(early["plate_number_visible_from"]) == pickup - timedelta(minutes=30)
    assert view(bw, first.id, "client", now=pickup - timedelta(minutes=31))["driver"]["vehicle"]["plate_number"] is None
    assert view(bw, first.id, "client", now=pickup - timedelta(minutes=30))["driver"]["vehicle"]["plate_number"] == "01C111AA"
    assert view(bw, first.id, "staff", now=pickup - timedelta(hours=2))["driver"]["vehicle"]["plate_number"] == "01C111AA"

    with bw.db.session() as s:
        bookings_service.cancel_booking(s, booking_public_id_value=_public(second), actor_user_id=bw.w.client2_id, expected_version=1,
                                        reason_code="plans_changed")
        s.commit()
    cancelled = view(bw, second.id, "client", now=pickup)["driver"]["vehicle"]
    assert cancelled["plate_number"] is None and cancelled["plate_number_visible_from"] is None  # never for a cancelled booking

    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=55))
    boarding = view(bw, first.id, "client", now=pickup - timedelta(minutes=50))["driver"]["vehicle"]
    assert boarding["plate_number"] == "01C111AA"  # trip boarding


# --- Q65 / AC20: delivered does not complete; sender confirms once; 24 h operator queue ---------------------------------------------


def test_q65_delivered_waits_for_sender_confirmation_and_captures_once(bw: BW, client) -> None:  # noqa: ANN001
    _, booking, codes = _parcel_in_transit(bw, "01C112AA")
    response = client.get(f"/api/v2/bookings/{_public(booking)}/codes", headers=auth(bw.w.client_id, "client"))
    assert response.status_code == 200 and [c["kind"] for c in response.json()["data"]["codes"]] == ["delivery_code"]
    assert response.json()["warnings"] == [{
        "code": "DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY", "field": "codes.delivery_code", "details": None,
        "message": response.json()["warnings"][0]["message"]}]
    version_before = booking_version(bw, booking.id)
    captures = _captures(bw)
    delivered = act(bw, booking.id, bw.w.driver_id, "deliver", code=codes["delivery_code"], now=bw.base + timedelta(hours=2))
    assert (delivered.service_status, delivered.commission_status, delivered.version) == ("delivered", "held", version_before + 1)
    assert _captures(bw) == captures and wallet(bw, bw.w.driver_id)[1] == 1_050_000
    assert domain_error(lambda: act(bw, booking.id, bw.w.driver_id, "complete")).code is ErrorCode.FORBIDDEN  # only the sender confirms
    done = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3))
    assert (done.service_status, done.commission_status) == ("completed", "held")  # Q74: no probe -> finance review
    assert domain_error(lambda: act(bw, booking.id, bw.w.client_id, "complete")).code is ErrorCode.INVALID_STATE_TRANSITION
    assert _captures(bw) == captures
    finalized = operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="delivery confirmed")
    assert finalized.commission_status == "captured" and _captures(bw) == captures + 1  # AC20: one capture


def test_q65_unconfirmed_delivery_enters_operator_queue_after_24h_signal_and_evidence_completion(bw: BW) -> None:
    _, booking, codes = _parcel_in_transit(bw, "01C113AA")
    delivered_at = bw.base + timedelta(hours=2)
    act(bw, booking.id, bw.w.driver_id, "deliver", code=codes["delivery_code"], now=delivered_at)
    assert _queue(bw, bw.operator_id, "awaiting_confirmation", now=delivered_at + timedelta(hours=23)) == []
    later = delivered_at + timedelta(hours=25)
    assert _queue(bw, bw.operator_id, "awaiting_confirmation", now=later) == [booking.id]
    with bw.db.session() as s:
        assert bookings_service.emit_confirmation_overdue_signals(s, now=later) == 1
        s.commit()
    with bw.db.session() as s:
        assert bookings_service.emit_confirmation_overdue_signals(s, now=later + timedelta(hours=1)) == 0  # dedup
        s.commit()
    payload = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'booking.confirmation_overdue'")[0].payload
    assert payload["booking_id"] == _public(booking) and payload["service_status"] == "delivered"
    assert _parse(payload["overdue_since"]) == delivered_at + timedelta(hours=24)
    done = operator(bw, booking.id, bw.operator_id, "complete_with_evidence", now=later, reason="receiver confirmed by phone")
    assert (done.service_status, done.commission_status) == ("completed", "held")  # Q74
    assert _queue(bw, bw.operator_id, "awaiting_confirmation", now=later) == []
    assert _queue(bw, bw.operator_id, "finance_review") == [booking.id]


def test_operator_complete_with_evidence_for_arrived_passenger_after_24h(bw: BW) -> None:
    _, booking = _arrived_passenger(bw, "01C114AA")
    ended = bw.base + timedelta(hours=3)
    assert _queue(bw, bw.operator_id, "awaiting_confirmation", now=ended + timedelta(hours=23)) == []
    assert _queue(bw, bw.operator_id, "awaiting_confirmation", now=ended + timedelta(hours=25)) == [booking.id]
    done = operator(bw, booking.id, bw.operator_id, "complete_with_evidence", now=ended + timedelta(hours=25), reason="trip log")
    assert (done.service_status, done.commission_status) == ("completed", "held")  # Q74
    assert scalar(bw.db, "SELECT count(*) FROM booking_proofs WHERE booking_id = :b AND proof_kind = 'operator_evidence' "
                         "AND accepted_at IS NOT NULL", b=booking.id) == 1


# --- Q66/Q74: no dispute probe -> completed, held, finance queue; with a probe: clear captures, open delays ---------------------


def test_q74_registered_probe_clear_captures_open_delays_without_finance_queue(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    _, clear = _arrived_passenger(bw, "01C140AA")
    _, disputed = _arrived_passenger(bw, "01C141AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    monkeypatch.setattr(bookings_service, "_blocking_dispute_probe", lambda session, booking_id: booking_id == disputed.id)
    captures = _captures(bw)
    done = act(bw, clear.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    assert (done.commission_status, done.finance_review_reason) == ("captured", None) and _captures(bw) == captures + 1
    held = act(bw, disputed.id, bw.w.client2_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    assert (held.service_status, held.commission_status, held.finance_review_reason) == ("completed", "held", None)
    assert _queue(bw, bw.finance_id, "finance_review") == []
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'commission.finance_review_required'") == 0


def test_q66_unavailable_dispute_check_completes_keeps_hold_and_queues_for_finance(bw: BW) -> None:
    _, booking = _arrived_passenger(bw, "01C115AA")  # Q74: no probe registered, whether or not disputes_v2 exists
    captures = _captures(bw)
    done = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    assert (done.service_status, done.commission_status, done.finance_review_reason) == ("completed", "held", "dispute_module_unavailable")
    assert _captures(bw) == captures and wallet(bw, bw.w.driver_id) == (FUNDED_MINOR, 5_700_000)
    events = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'commission.finance_review_required'")
    assert [e.payload for e in events] == [{"booking_id": _public(booking), "reason_code": "dispute_module_unavailable",
                                            "amount_minor": 5_700_000, "currency": "UZS"}]
    assert _queue(bw, bw.finance_id, "finance_review") == [booking.id]
    assert _queue(bw, bw.operator_id, "finance_review") == [booking.id]
    finalized = operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="no dispute reported")
    assert finalized.commission_status == "captured" and _captures(bw) == captures + 1
    assert _queue(bw, bw.finance_id, "finance_review") == []


# --- B12 queues, hold escalation signal, staff contact audit (HTTP) -------------------------------------------------------------------


def test_b12_queues_hold_escalation_signals_and_contact_audit(bw: BW, client) -> None:  # noqa: ANN001
    _, _, _, passenger = _boarding_passenger(bw, "01C116AA")
    _report_no_show(bw, passenger.id)
    _, parcel, _ = _parcel_in_transit(bw, "01C117AA", driver_id=bw.w.driver2_id)
    act(bw, parcel.id, bw.w.driver2_id, "report_delivery_failed", now=bw.base + timedelta(hours=2), note="nobody at the stop")

    assert _queue(bw, bw.operator_id, "no_show_review") == [passenger.id]
    assert _queue(bw, bw.operator_id, "custody_case") == [parcel.id]
    assert _queue(bw, bw.operator_id, "awaiting_confirmation", now=bw.base + timedelta(days=3)) == []
    assert _queue(bw, bw.operator_id, "finance_review") == []
    assert _queue(bw, bw.operator_id, "hold_escalation") == []
    escalated = utc_now() + timedelta(hours=49)
    assert _queue(bw, bw.operator_id, "hold_escalation", now=escalated) == [passenger.id, parcel.id]
    assert domain_error(lambda: _queue(bw, bw.w.driver_id, "no_show_review")).code is ErrorCode.FORBIDDEN
    with bw.db.session() as s:
        assert bookings_service.emit_hold_escalation_signals(s, now=escalated) == 2
        s.commit()
    with bw.db.session() as s:
        assert bookings_service.emit_hold_escalation_signals(s, now=escalated) == 0  # dedup per hold
    payloads = [r.payload for r in rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'wallet.hold.escalation_due' ORDER BY id")]
    assert {p["booking_id"] for p in payloads} == {_public(passenger), _public(parcel)} and all(p["currency"] == "UZS" for p in payloads)

    listed = client.get("/api/v2/admin/bookings?queue=no_show_review", headers=auth(bw.operator_id, "operator"))
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["client"]["contact_phone"] == CLIENT_PHONE  # staff see contacts ...
    detail = client.get(f"/api/v2/bookings/{_public(parcel)}", headers=auth(bw.operator_id, "operator"))
    assert detail.status_code == 200
    audit = rows(bw.db, "SELECT actor_id, details::text AS d FROM audit_logs WHERE action = 'booking_contacts_viewed' ORDER BY id")
    assert [a.actor_id for a in audit] == [bw.operator_id, bw.operator_id]  # ... and every such response is audited
    assert _public(passenger) in audit[0].d and "B12:no_show_review" in audit[0].d and "B1" in audit[1].d
    assert all("+998" not in a.d and "01C11" not in a.d for a in audit)  # no phone or plate value in the audit row
    bad = client.get("/api/v2/admin/bookings?queue=everything", headers=auth(bw.operator_id, "operator"))
    assert bad.status_code in (400, 422)


# --- amendment expiry (worker function) -----------------------------------------------------------------------------------------------


def test_expire_due_amendments_worker_function(bw: BW) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01C118AA", seats=3)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    booking = accept(bw, propose(bw, offer, bw.w.client_id, trip_public_id=None, quantity=1, unit=20_000_000), bw.w.driver_id)
    with bw.db.session() as s:
        bookings_service.create_amendment(s, booking_public_id_value=_public(booking), actor_user_id=bw.w.client_id,
                                          expected_version=booking.version, changes={"quantity": 2}, reason="friend joins")
        s.commit()
    with bw.db.session() as s:
        assert bookings_service.expire_due_amendments(s, now=utc_now() + timedelta(hours=1)) == 0
        assert bookings_service.expire_due_amendments(s, now=utc_now() + timedelta(hours=3)) == 1
        s.commit()
    assert rows(bw.db, "SELECT status, decided_at IS NOT NULL AS decided, version FROM booking_amendments WHERE booking_id = :b",
                b=booking.id) == [("expired", True, 2)]
    with bw.db.session() as s:
        assert bookings_service.expire_due_amendments(s, now=utc_now() + timedelta(hours=3)) == 0
        again = bookings_service.create_amendment(s, booking_public_id_value=_public(booking), actor_user_id=bw.w.client_id,
                                                  expected_version=booking.version, changes={"quantity": 2}, reason="friend joins")
        s.commit()
        assert again.status == "proposed"  # the single open amendment slot is free again
    assert seats_used(bw, trip_id) == [1, 1, 1]


# --- T10 manifest, AC26 HTTP cash acknowledge -----------------------------------------------------------------------------------------


def test_t10_manifest_phones_follow_q44_and_access(bw: BW, client) -> None:  # noqa: ANN001
    _, trip_id, trip_public, booking = _boarding_passenger(bw, "01C119AA")
    with bw.db.session() as s:
        trip, entries = bookings_service.trip_manifest(s, trip_public_id_value=trip_public, viewer_user_id=bw.w.driver_id, now=bw.base)
        assert [(e.booking.id, e.client_first_name, e.contact_phone) for e in entries] == [(booking.id, "Aziza", None)]
        dto = manifest_dto(s, trip, entries)
        assert [stop.seq for stop in dto.stops] == [1, 2, 3, 4]
        assert [i.booking_id for i in dto.stops[0].pickups] == [_public(booking)] and [i.booking_id for i in dto.stops[3].dropoffs] == [_public(booking)]
        assert domain_error(lambda: bookings_service.trip_manifest(s, trip_public_id_value=trip_public, viewer_user_id=bw.w.client2_id)).code \
            is ErrorCode.NOT_FOUND
        _, staff_entries = bookings_service.trip_manifest(s, trip_public_id_value=trip_public, viewer_user_id=bw.operator_id, now=bw.base)
        assert len(staff_entries) == 1
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    with bw.db.session() as s:
        _, started = bookings_service.trip_manifest(s, trip_public_id_value=trip_public, viewer_user_id=bw.w.driver_id,
                                                    now=bw.base + timedelta(minutes=10))
        assert [e.contact_phone for e in started] == [CLIENT_PHONE]  # Q44: phone from the service start
    response = client.get(f"/api/v2/trips/{trip_public}/manifest", headers=auth(bw.w.driver_id, "driver"))
    assert response.status_code == 200, response.text
    item = response.json()["data"]["stops"][0]["pickups"][0]
    assert (item["booking_id"], item["service_status"], item["seats"]) == (_public(booking), "onboard", 2)


def test_ac26_http_cash_report_and_acknowledge(bw: BW, client) -> None:  # noqa: ANN001
    _, _, _, booking = _boarding_passenger(bw, "01C120AA")
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    public = _public(booking)
    reported = client.post(
        f"/api/v2/bookings/{public}/cash-receipts",
        json={"expected_version": booking_version(bw, booking.id), "amount_minor": booking.total_minor, "reported_at": bw.base.isoformat()},
        headers=auth(bw.w.driver_id, "driver", "w21-cash-report-01"),
    )
    assert reported.status_code == 201, reported.text
    receipt = reported.json()["data"]
    assert receipt["status"] == "reported_paid" and receipt["id"].startswith("csh_")
    url = f"/api/v2/bookings/{public}/cash-receipts/{receipt['id']}/acknowledge"
    own = client.post(url, json={"expected_version": receipt["version"]}, headers=auth(bw.w.driver_id, "driver", "w21-cash-ack-drv1"))
    assert own.status_code == 403
    acknowledged = client.post(url, json={"expected_version": receipt["version"]}, headers=auth(bw.w.client_id, "client", "w21-cash-ack-0001"))
    assert acknowledged.status_code == 200 and acknowledged.json()["data"]["status"] == "acknowledged", acknowledged.text
    replay = client.post(url, json={"expected_version": receipt["version"]}, headers=auth(bw.w.client_id, "client", "w21-cash-ack-0001"))
    assert replay.headers.get("Idempotent-Replayed") == "true" and replay.json() == acknowledged.json()
    assert rows(bw.db, "SELECT cash_status, service_status FROM bookings WHERE id = :b", b=booking.id) == [("acknowledged", "onboard")]


# --- BR review fixes: M1 (resources follow the amendment), L3 (growth re-checks eligibility), L5 (HTTP B13 reissue) ---------------


def _offer_booking_with_amendment(bw: BW, plate: str, *, client_id: int, driver_id: int, quantity: int = 2):  # noqa: ANN202
    trip_id, trip_public = driver_trip(bw, driver_id, plate, seats=3)
    offer = publish_listing(bw, driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    booking = accept(bw, propose(bw, offer, client_id, trip_public_id=None, quantity=1, unit=20_000_000), driver_id)
    with bw.db.session() as s:
        amendment = bookings_service.create_amendment(s, booking_public_id_value=_public(booking), actor_user_id=client_id,
                                                      expected_version=booking.version, changes={"quantity": quantity}, reason="more seats")
        s.commit()
        return trip_id, booking, amendment.id, format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id)


def test_m1_accepted_amendment_marker_checks_resources_and_is_booking_scoped(bw: BW) -> None:
    _, a_booking, a_amendment_id, _ = _offer_booking_with_amendment(bw, "01C130AA", client_id=bw.w.client_id, driver_id=bw.w.driver_id)
    _, b_booking, _, _ = _offer_booking_with_amendment(bw, "01C131AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    accept_a = "UPDATE booking_amendments SET status = 'accepted', decided_at = now(), version = version + 1 WHERE id = :a"

    with pytest.raises(DBAPIError) as wrong_seats, bw.db.engine.begin() as conn:  # valid marker, seats != new quantity
        conn.execute(text(accept_a), {"a": a_amendment_id})
        conn.execute(text("UPDATE bookings SET quantity = 2, total_minor = unit_price_minor * 2, "
                          "commission_minor = commission_minor * 2, seats = 3, version = version + 1 WHERE id = :b"), {"b": a_booking.id})
    assert platform_service.constraint_name_of(wrong_seats.value) == "booking_snapshot_frozen"
    with pytest.raises(DBAPIError) as wrong_baggage, bw.db.engine.begin() as conn:
        conn.execute(text(accept_a), {"a": a_amendment_id})
        conn.execute(text("UPDATE bookings SET quantity = 2, total_minor = unit_price_minor * 2, commission_minor = commission_minor * 2, "
                          "seats = 2, baggage_ml = baggage_ml + 1, version = version + 1 WHERE id = :b"), {"b": a_booking.id})
    assert platform_service.constraint_name_of(wrong_baggage.value) == "booking_snapshot_frozen"
    with pytest.raises(DBAPIError) as other_booking, bw.db.engine.begin() as conn:  # A's marker never unlocks B
        conn.execute(text(accept_a), {"a": a_amendment_id})
        conn.execute(text("UPDATE bookings SET quantity = 2, total_minor = unit_price_minor * 2, commission_minor = commission_minor * 2, "
                          "seats = 2, version = version + 1 WHERE id = :b"), {"b": b_booking.id})
    assert platform_service.constraint_name_of(other_booking.value) == "booking_snapshot_frozen"
    assert rows(bw.db, "SELECT status FROM booking_amendments WHERE id = :a", a=a_amendment_id) == [("proposed",)]  # all rolled back


def test_l3_amendment_growth_rechecks_driver_and_vehicle_eligibility_decrease_does_not(bw: BW) -> None:
    from app.modules.identity import service as identity_service

    trip_id, booking, _, amendment_public = _offer_booking_with_amendment(bw, "01C132AA", client_id=bw.w.client_id, driver_id=bw.w.driver_id)
    with bw.db.engine.begin() as conn:
        conn.execute(text("UPDATE vehicles SET verification_status = 'rejected' WHERE id = (SELECT vehicle_id FROM trips WHERE id = :t)"),
                     {"t": trip_id})
    with bw.db.session() as s:
        vehicle = domain_error(lambda: bookings_service.accept_amendment(s, amendment_public_id=amendment_public,
                                                                         actor_user_id=bw.w.driver_id, expected_version=1))
    assert vehicle.code is ErrorCode.VEHICLE_NOT_ELIGIBLE
    with bw.db.engine.begin() as conn:
        conn.execute(text("UPDATE vehicles SET verification_status = 'approved' WHERE id = (SELECT vehicle_id FROM trips WHERE id = :t)"),
                     {"t": trip_id})
    with bw.db.session() as s:
        identity_service.block_driver_eligibility(s, driver_user_id=bw.w.driver_id, actor_user_id=bw.w.admin_id,
                                                  expected_version=identity_service.eligibility_version(s, bw.w.driver_id), reason="documents")
        s.commit()
    with bw.db.session() as s:
        driver = domain_error(lambda: bookings_service.accept_amendment(s, amendment_public_id=amendment_public,
                                                                        actor_user_id=bw.w.driver_id, expected_version=1))
    assert driver.code is ErrorCode.DRIVER_NOT_ELIGIBLE and seats_used(bw, trip_id) == [1, 1, 1]

    # A decrease (or price-only change) is an obligation, not new business: allowed for the blocked driver.
    with bw.db.session() as s:
        withdrawn = bookings_service.decide_amendment(s, amendment_public_id=amendment_public, actor_user_id=bw.w.client_id,
                                                      expected_version=1, decision="withdraw")
        s.commit()
        assert withdrawn.status == "withdrawn"
    with bw.db.session() as s:
        cheaper = bookings_service.create_amendment(s, booking_public_id_value=_public(booking), actor_user_id=bw.w.client_id,
                                                    expected_version=booking_version(bw, booking.id), changes={"unit_price_minor": 18_000_000},
                                                    reason="discount")
        s.commit()
        cheaper_public = format_public_id(PublicIdPrefix.AMENDMENT, cheaper.public_id)
    with bw.db.session() as s:
        updated = bookings_service.accept_amendment(s, amendment_public_id=cheaper_public, actor_user_id=bw.w.driver_id, expected_version=1)
        s.commit()
        assert (updated.unit_price_minor, updated.quantity) == (18_000_000, 1)


def test_l5_http_operator_reissue_command_requires_reason_and_never_returns_a_code(bw: BW, client) -> None:  # noqa: ANN001
    _, _, _, booking = _boarding_passenger(bw, "01C133AA")
    public = _public(booking)
    old = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    url = f"/api/v2/admin/bookings/{public}/commands/reissue_proof_code"
    version = booking_version(bw, booking.id)
    no_reason = client.post(url, json={"expected_version": version, "reason": "", "proof_kind": "boarding_code"},
                            headers=auth(bw.operator_id, "operator", "w21-op-reissue-01"))
    assert no_reason.status_code in (400, 422), no_reason.text
    driver = client.post(url, json={"expected_version": version, "reason": "x", "proof_kind": "boarding_code"},
                         headers=auth(bw.w.driver_id, "driver", "w21-op-reissue-02"))
    assert driver.status_code in (403, 404)
    ok = client.post(url, json={"expected_version": version, "reason": "client called support", "proof_kind": "boarding_code"},
                     headers=auth(bw.operator_id, "operator", "w21-op-reissue-03"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["id"] == public and ok.json()["data"]["version"] == version  # BookingDTO, booking unchanged
    new = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    assert new != old and new not in ok.text and old not in ok.text and "code" not in ok.json()["data"]
    audit = rows(bw.db, "SELECT actor_id, details::text AS d FROM audit_logs WHERE action = 'booking_proof_code_reissued'")
    assert [a.actor_id for a in audit] == [bw.operator_id] and new not in audit[0].d and "client called support" in audit[0].d
    events = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'booking.proof_code.reissued'")
    assert [e.payload for e in events] == [{"service_type": "passenger", "proof_kind": "boarding_code", "code_rotation": 1,
                                            "requested_by_side": "operator"}]


# --- Wave 3 (A4 small card): driver_arrived event, tracking close hook, finance review after a dispute (U8) -----------------------


def test_w3_arrive_at_pickup_emits_driver_arrived_once_with_allowlisted_payload(bw: BW) -> None:
    from app.contracts.enums import EventType
    from app.contracts.events import EVENT_PAYLOAD_ALLOWLIST

    _, _, trip_public, booking = _boarding_passenger(bw, "01C150AA")
    act(bw, booking.id, bw.w.driver_id, "arrive_at_pickup", now=bw.base, observed_at=bw.base)
    act(bw, booking.id, bw.w.driver_id, "arrive_at_pickup", now=bw.base + timedelta(minutes=1))  # repeat: no second event
    events = rows(bw.db, "SELECT aggregate_public_id, payload FROM outbox_events WHERE event_type = 'booking.driver_arrived'")
    assert len(events) == 1 and events[0].aggregate_public_id == _public(booking)
    payload = events[0].payload
    assert set(payload) == set(EVENT_PAYLOAD_ALLOWLIST[EventType.BOOKING_DRIVER_ARRIVED])
    assert (payload["service_type"], payload["trip_id"]) == ("passenger", trip_public) and _parse(payload["arrived_at"]) == bw.base


def test_w3_trip_terminal_transitions_close_tracking_sessions(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    calls: list[tuple[int, object]] = []
    fake = types.ModuleType("app.modules.tracking.service")
    fake.close_sessions_for_trip = lambda session, trip_id, *, now=None: calls.append((trip_id, now)) or 1  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.modules.tracking.service", fake)

    _, trip_id, _, booking = _boarding_passenger(bw, "01C151AA")
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    run_trip_action(bw, trip_id, bw.w.driver_id, "depart", now=bw.base + timedelta(minutes=5))
    run_trip_action(bw, trip_id, bw.w.driver_id, "interrupt", reason="tyre", now=bw.base + timedelta(minutes=30))
    run_trip_action(bw, trip_id, bw.w.driver_id, "resume", reason="fixed", now=bw.base + timedelta(minutes=40))
    assert calls == []  # interrupt/resume keep the sessions
    act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    run_trip_action(bw, trip_id, bw.w.driver_id, "complete", now=bw.base + timedelta(hours=4))
    assert calls == [(trip_id, bw.base + timedelta(hours=4))]

    _, planned_trip, _, _ = request_with_driver_proposal(bw, plate="01C152AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    run_trip_action(bw, planned_trip, bw.w.driver2_id, "cancel", reason="car broke", now=bw.base - timedelta(hours=3))
    assert calls[-1] == (planned_trip, bw.base - timedelta(hours=3))

    monkeypatch.delitem(sys.modules, "app.modules.tracking.service")  # A6 not importable yet: skipped, trip still cancels
    monkeypatch.setattr(bookings_service, "TRACKING_SERVICE_MODULE", "app.modules.tracking_absent_for_test.service")
    third_trip, _ = driver_trip(bw, bw.w.driver2_id, "01C153AA")
    assert run_trip_action(bw, third_trip, bw.w.driver2_id, "cancel", reason="x", now=bw.base - timedelta(hours=3)) == "cancelled"


def test_w3_mark_finance_review_after_dispute(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    _, disputed = _arrived_passenger(bw, "01C154AA")
    monkeypatch.setattr(bookings_service, "_blocking_dispute_probe", lambda session, booking_id: True)  # A12: dispute open
    done = act(bw, disputed.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    assert (done.commission_status, done.finance_review_reason) == ("held", None)
    assert _queue(bw, bw.finance_id, "finance_review") == []

    def mark(reason: str = "dispute resolved: driver delivered") -> None:
        with bw.db.session() as s:
            bookings_service.mark_finance_review_after_dispute(s, booking_id=disputed.id, reason=reason, now=bw.base + timedelta(days=1))
            s.commit()

    assert domain_error(lambda: mark("  ")).code is ErrorCode.VALIDATION_ERROR
    mark()
    mark()  # idempotent: no second event
    assert _queue(bw, bw.finance_id, "finance_review") == [disputed.id]
    # wave 3.1 (W3-6, 0062): the queued reason is dispute_resolved, not the Q74 module-unavailable one.
    assert scalar(bw.db, "SELECT finance_review_reason FROM bookings WHERE id = :b", b=disputed.id) == "dispute_resolved"
    events = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'commission.finance_review_required'")
    assert len(events) == 1 and events[0].payload["booking_id"] == _public(disputed)
    assert events[0].payload["reason_code"] == "dispute_resolved"
    assert scalar(bw.db, "SELECT count(*) FROM booking_status_history WHERE booking_id = :b AND command = 'finance_review_after_dispute'",
                  b=disputed.id) == 1
    open_capture = domain_error(lambda: operator(bw, disputed.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="early"))
    assert open_capture.details["reason"] == "blocking_dispute_open"  # BR M2: still open -> no money decision
    monkeypatch.setattr(bookings_service, "_blocking_dispute_probe", lambda session, booking_id: False)  # A12: dispute resolved
    operator(bw, disputed.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="dispute closed")
    assert _queue(bw, bw.finance_id, "finance_review") == []
    assert domain_error(lambda: mark()).code is ErrorCode.INVALID_STATE_TRANSITION  # no longer held

    _, _, _, open_booking = _boarding_passenger(bw, "01C155AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    with bw.db.session() as s:  # not finished yet: nothing to review
        assert domain_error(lambda: bookings_service.mark_finance_review_after_dispute(
            s, booking_id=open_booking.id, reason="x")).code is ErrorCode.INVALID_STATE_TRANSITION


@pytest.mark.parametrize(("outcome", "cash_status", "receipt_status"), [("paid", "acknowledged", "resolved_paid"),
                                                                        ("unpaid", "unpaid", "resolved_unpaid")])
def test_w3_resolve_contested_cash_receipt_after_payment_dispute(bw: BW, outcome: str, cash_status: str, receipt_status: str) -> None:
    _, _, _, booking = _boarding_passenger(bw, "01C160AA")
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    with bw.db.session() as s:
        b = s.get(Booking, booking.id)
        _, receipt = bookings_service.report_cash_receipt(s, booking_public_id_value=_public(b), actor_user_id=bw.w.driver_id,
                                                          expected_version=b.version, amount_minor=b.total_minor, reported_at=bw.base)
        receipt_public = format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id)
        s.commit()

    def resolve(actor_id: int, reason: str = "dispute decided") -> None:
        with bw.db.session() as s:
            bookings_service.resolve_contested_cash_receipt(s, booking_id=booking.id, outcome=outcome, actor_user_id=actor_id, reason=reason)
            s.commit()

    assert domain_error(lambda: resolve(bw.w.admin_id)).code is ErrorCode.INVALID_STATE_TRANSITION  # not contested yet
    with bw.db.session() as s:
        bookings_service.contest_cash_receipt(s, booking_public_id_value=_public(booking), receipt_public_id=receipt_public,
                                              actor_user_id=bw.w.client_id, expected_version=1, comment="I paid only half")
        s.commit()
    assert domain_error(lambda: resolve(bw.w.client_id)).code is ErrorCode.FORBIDDEN
    # wave 3.1: the cash outcome is part of the dispute decision, so it needs ops.dispute_decide (admin+)
    assert domain_error(lambda: resolve(bw.operator_id)).code is ErrorCode.FORBIDDEN
    assert domain_error(lambda: resolve(bw.w.admin_id, "  ")).code is ErrorCode.VALIDATION_ERROR
    resolve(bw.w.admin_id)
    assert rows(bw.db, "SELECT cash_status, service_status FROM bookings WHERE id = :b", b=booking.id) == [(cash_status, "onboard")]
    assert rows(bw.db, "SELECT status, decided_by_user_id FROM cash_receipts WHERE booking_id = :b", b=booking.id) == [
        (receipt_status, bw.w.admin_id)]
    assert scalar(bw.db, "SELECT count(*) FROM audit_logs WHERE action = :a", a=f"booking_cash_resolve_{outcome}") == 1
    assert domain_error(lambda: resolve(bw.w.admin_id)).code is ErrorCode.INVALID_STATE_TRANSITION  # decided once
    last = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'booking.status_changed' ORDER BY id DESC LIMIT 1")[0].payload
    assert (last["machine"], last["from_status"], last["to_status"]) == ("cash", "contested", cash_status)


def test_m2_finalize_fee_refused_while_a_blocking_dispute_is_open(bw: BW) -> None:
    from app.modules.trust_support import service as trust_service

    _, booking = _arrived_passenger(bw, "01C170AA")
    done = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    assert (done.commission_status, done.finance_review_reason) == ("held", "dispute_module_unavailable")  # Q74: no probe yet

    trust_service.register_booking_hooks()  # A12 wired (teardown: bw fixture resets the hooks; also reset below)
    try:
        with bw.db.session() as s:
            trust_service.open_dispute(s, booking_public_id_value=_public(booking), actor_user_id=bw.w.client_id,
                                       dispute_type="service", description="Haydovchi manzilga olib bormadi, boshqa joyda tushirdi")
            s.commit()
        assert _queue(bw, bw.finance_id, "finance_review") == [booking.id]
        for mode in ("capture", "release"):
            error = domain_error(lambda: operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode=mode, reason="finance"))
            assert error.code is ErrorCode.INVALID_STATE_TRANSITION and error.details["reason"] == "blocking_dispute_open", mode
        assert rows(bw.db, "SELECT commission_status FROM bookings WHERE id = :b", b=booking.id) == [("held",)]
        assert _captures(bw) == 0 and wallet(bw, bw.w.driver_id)[1] == 5_700_000
    finally:
        bookings_service.set_blocking_dispute_probe(None)
        bookings_service.set_payment_dispute_opener(None)
    finalized = operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="manual finance path")  # Q74
    assert finalized.commission_status == "captured" and _captures(bw) == 1


def test_signal_functions_never_starve_new_rows_behind_signalled_ones(bw: BW) -> None:
    """A10a review: with limit=1, more than limit*4 already-signalled due rows must not hide a new due row.
    The functions write outbox rows only and never commit (AGENTS §4): an uncommitted session leaves nothing behind."""
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01C121AA", seats=7)
    offer = publish_listing(bw, bw.w.driver_id, passenger_offer(bw.w, trip_public, start=bw.base))
    with bw.db.session() as s:
        clients = [add_user(s, f"+99890130{i:04d}", "client", full_name=f"Mijoz {i}") for i in range(6)]
        s.commit()
    bookings = [accept(bw, propose(bw, offer, c, trip_public_id=None, quantity=1, unit=20_000_000), bw.w.driver_id) for c in clients]
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    for client_id, booking in zip(clients, bookings, strict=True):
        act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, client_id)["boarding_code"], now=bw.base)
        act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    overdue, escalated = bw.base + timedelta(hours=28), utc_now() + timedelta(hours=49)

    with bw.db.session() as s:  # no commit inside the functions
        assert bookings_service.emit_confirmation_overdue_signals(s, now=overdue, limit=1) == 1
        s.rollback()
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'booking.confirmation_overdue'") == 0

    for emit, at in ((bookings_service.emit_confirmation_overdue_signals, overdue), (bookings_service.emit_hold_escalation_signals, escalated)):
        for _ in range(len(bookings)):  # the 6th call still finds the last row behind 5 (> limit*4) signalled ones
            with bw.db.session() as s:
                assert emit(s, now=at, limit=1) == 1
                s.commit()
        with bw.db.session() as s:
            assert emit(s, now=at, limit=1) == 0
    signalled = {r.payload["booking_id"] for r in rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'booking.confirmation_overdue'")}
    assert signalled == {_public(b) for b in bookings}
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'wallet.hold.escalation_due'") == len(bookings)
