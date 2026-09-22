"""Wave 2.1 trips on PostgreSQL: Q59 transition_trip, Q61 vehicle eligibility, Q63 stops lock, counter trigger."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.db_errors import map_db_error
from app.contracts.enums import TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.views import thread_dto
from app.modules.platform.service import constraint_name_of, sqlstate_of
from app.modules.trips import service as trips_service
from app.modules.trips.rules import ResourceDemand
from app.modules.trips.schemas import TripPatch
from tests.pg.bookings.conftest import BW, accept, bw, request_with_driver_proposal, trip_version  # noqa: F401
from tests.pg.identity.a1_world import World, make_trip, make_vehicle

pytestmark = pytest.mark.pg

COUNTER_MISMATCH = "changed without a matching booking allocation change"


def _seats(world: World, trip_id: int) -> list[int]:
    with world.db.session() as s:
        return [load.seats_used for load in trips_service.get_segment_loads(s, trip_id)]


# --- Q59 ----------------------------------------------------------------------------------------------


def test_q59_transition_trip_uses_the_state_machine_and_bumps_version(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01Q590AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    with world.db.session() as s:
        trip = trips_service.lock_trip(s, trip_id)
        with pytest.raises(DomainError) as info:
            trips_service.transition_trip(s, trip=trip, target=TripStatus.COMPLETED, command="complete", reason=None, now=utc_now())
        assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION
        previous = trips_service.transition_trip(
            s, trip=trip, target=TripStatus.CANCELLED, command="cancel", reason="mashina buzildi", now=utc_now()
        )
        assert previous == "planned"
        assert (trip.status, trip.cancel_reason, trip.version) == ("cancelled", "mashina buzildi", 2)
        s.commit()


# --- Q61 ----------------------------------------------------------------------------------------------


def test_q61_new_booking_needs_an_approved_vehicle(world: World) -> None:
    make_vehicle(world, world.driver_id, "01Q610AA", approve=False)
    make_vehicle(world, world.driver_id, "01Q611AA")
    with world.db.session() as s:
        pending_id, approved_id = s.execute(
            text("SELECT id FROM vehicles WHERE driver_user_id = :d ORDER BY id"), {"d": world.driver_id}
        ).scalars().all()
        with pytest.raises(DomainError) as info:
            trips_service.assert_vehicle_eligible_for_new_booking(s, pending_id)
        assert info.value.code is ErrorCode.VEHICLE_NOT_ELIGIBLE and info.value.http_status == 409
        assert info.value.details == {"reason": "vehicle_not_approved", "verification_status": "pending"}
        trips_service.assert_vehicle_eligible_for_new_booking(s, approved_id)  # approved -> no error
        public_id = trips_service.vehicle_public_id(trips_service.get_vehicle(s, approved_id))
    with world.db.session() as s:  # an approved vehicle that is later rejected blocks new bookings again
        vehicle = trips_service.get_vehicle(s, approved_id)
        s.execute(
            text("UPDATE vehicles SET verification_status = 'rejected', verification_reason = 'hujjat', version = version + 1 WHERE id = :v"),
            {"v": vehicle.id},
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.assert_vehicle_eligible_for_new_booking(s, approved_id)
    assert info.value.details["verification_status"] == "rejected" and public_id.startswith("veh_")
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.assert_vehicle_eligible_for_new_booking(s, 987_654_321)
    assert info.value.details == {"reason": "vehicle_missing"}


# --- capacity counter trigger (0054) ---------------------------------------------------------------------


def test_segment_counters_cannot_change_without_allocations(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01Q620AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    with pytest.raises(DBAPIError, match=COUNTER_MISMATCH) as info, world.db.engine.begin() as conn:
        conn.execute(text("UPDATE trip_segment_resources SET seats_used = 1 WHERE trip_id = :t AND from_seq = 1"), {"t": trip_id})
    assert sqlstate_of(info.value) == "23514"
    assert map_db_error(sqlstate="23514").code is ErrorCode.INTEGRITY_CONFLICT
    with world.db.session() as s:  # the service path is refused at COMMIT as well without an allocation
        trips_service.reserve(s, trip_id, 1, 3, ResourceDemand(seats=1))
        with pytest.raises(DBAPIError, match=COUNTER_MISMATCH):
            s.commit()
        s.rollback()
    assert _seats(world, trip_id) == [0, 0, 0]


# --- Q63 + booking_id ------------------------------------------------------------------------------------


def test_q63_any_allocation_locks_the_stops_and_booking_id_is_shown(bw: BW) -> None:
    listing_id, trip_id, trip_public_id, ref = request_with_driver_proposal(bw)
    booking = accept(bw, ref, bw.w.client_id)  # counters + allocations commit together (counter trigger positive path)

    with bw.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, ref.thread_id)
        assert thread_dto(s, thread, viewer_user_id=bw.w.client_id).booking_id == bookings_service.booking_public_id(booking)

    with bw.db.engine.begin() as conn:  # consistent release: the allocation is inactive but still exists
        conn.execute(text("UPDATE booking_allocations SET active = false, released_at = now() WHERE booking_id = :b"), {"b": booking.id})
        conn.execute(
            text(
                "UPDATE trip_segment_resources SET seats_used = 0, baggage_used_ml = 0, cargo_used_weight_g = 0, "
                "cargo_used_volume_ml = 0 WHERE trip_id = :t"
            ),
            {"t": trip_id},
        )

    stops = [
        {"stop_id": bw.w.stop_public_ids[name], "seq": index + 1, "planned_arrival_at": (bw.base + timedelta(hours=index)).isoformat()}
        for index, name in enumerate(("A", "B", "D"))
    ]
    with bw.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.patch_trip(
            s,
            trip_public_id_value=trip_public_id,
            actor_user_id=bw.w.driver_id,
            data=TripPatch.model_validate({"expected_version": trip_version(bw, trip_id), "stops": stops}),
        )
    assert info.value.code is ErrorCode.TRIP_STOPS_LOCKED and info.value.http_status == 409

    for statement in (
        "UPDATE trip_stop_occurrences SET stop_id = (SELECT stop_id FROM trip_stop_occurrences WHERE trip_id = :t AND seq = 2) "
        "WHERE trip_id = :t AND seq = 3",
        "DELETE FROM trip_segment_resources WHERE trip_id = :t AND from_seq = 3",
        "DELETE FROM trip_stop_occurrences WHERE trip_id = :t AND seq = 4",
        "INSERT INTO trip_stop_occurrences (trip_id, seq, stop_id, route_version_stop_seq, planned_arrival_at) "
        "SELECT trip_id, 9, stop_id, route_version_stop_seq, planned_arrival_at FROM trip_stop_occurrences WHERE trip_id = :t AND seq = 1",
    ):
        with pytest.raises(DBAPIError) as db_info, bw.db.engine.begin() as conn:
            conn.execute(text(statement), {"t": trip_id})
        assert sqlstate_of(db_info.value) == "23001" and constraint_name_of(db_info.value) == "trip_stops_locked", statement
        assert map_db_error(sqlstate="23001", constraint="trip_stops_locked").code is ErrorCode.TRIP_STOPS_LOCKED

    with bw.db.engine.begin() as conn:  # schedule/ETA columns are not stops
        conn.execute(text("UPDATE trip_stop_occurrences SET eta_arrival_at = now() WHERE trip_id = :t"), {"t": trip_id})
    assert listing_id


def test_q63_trip_without_allocations_can_still_change_stops(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01Q631AA")
    trip_id, trip_public_id = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    stops = [
        {"stop_id": world.stop_public_ids[name], "seq": index + 1, "planned_arrival_at": (world.base_time + timedelta(hours=index)).isoformat()}
        for index, name in enumerate(("A", "C", "D"))
    ]
    with world.db.session() as s:
        trip = trips_service.patch_trip(
            s, trip_public_id_value=trip_public_id, actor_user_id=world.driver_id, data=TripPatch.model_validate({"expected_version": 1, "stops": stops})
        )
        s.commit()
        assert [o.seq for o in trips_service.list_occurrences(s, trip.id)] == [1, 2, 3]
    assert _seats(world, trip_id) == [0, 0]
