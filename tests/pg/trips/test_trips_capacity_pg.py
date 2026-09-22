"""Trips on real PostgreSQL 16: overlap exclusion (AC13), segment capacity (AC10/AC11), CHECKs, races."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity import service as identity_service
from app.modules.trips import service as trips_service
from app.modules.trips.rules import Resource, ResourceDemand
from app.modules.trips.schemas import TripPatch
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import World, make_trip, make_vehicle, trip_create, unchecked_segment_counters  # noqa: F401

pytestmark = pytest.mark.pg

A, B, C, D = 1, 2, 3, 4


def seats(world: World, trip_id: int) -> list[int]:
    with world.db.session() as s:
        return [load.seats_used for load in trips_service.get_segment_loads(s, trip_id)]


def test_ac13_parallel_overlapping_trips_only_one_is_created(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A100AA")
    body = trip_create(world, vehicle, start=world.base_time)

    def create(worker: int, session: Session) -> str:
        trip = trips_service.create_trip(session, driver_user_id=world.driver_id, data=body)
        session.commit()
        return trips_service.trip_public_id(trip)

    report = run_concurrently(12, create, engine=world.db.engine)
    assert len(report.successes) == 1, [r.error for r in report.failures]
    assert all(isinstance(r.error, DomainError) and r.error.code is ErrorCode.SCHEDULE_CONFLICT for r in report.failures)
    with world.db.session() as s:
        assert s.execute(text("SELECT count(*) FROM trips")).scalar_one() == 1


def test_ac13_driver_and_vehicle_overlap_rejected_by_constraint(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A101AA")
    other_vehicle = make_vehicle(world, world.driver_id, "01A102AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)

    # Same driver, other vehicle, overlapping by the turnaround buffer.
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.create_trip(
            s, driver_user_id=world.driver_id, data=trip_create(world, other_vehicle, start=world.base_time + timedelta(hours=4, minutes=10))
        )
    assert info.value.code is ErrorCode.SCHEDULE_CONFLICT and info.value.details == {"conflict": "driver"}

    # Same vehicle under another driver, written directly: the vehicle exclusion still holds.
    with world.db.session() as s:
        with pytest.raises(IntegrityError, match="ex_trips_vehicle_overlap"):
            s.execute(
                text(
                    "INSERT INTO trips (public_id, driver_user_id, vehicle_id, route_version_id, planned_start_at, planned_end_at, "
                    "blocked_period, booking_cutoff_at, seat_capacity, max_detour_minutes, max_detour_m) "
                    "SELECT gen_random_uuid(), :d, vehicle_id, route_version_id, planned_start_at, planned_end_at, blocked_period, "
                    "booking_cutoff_at, 1, 0, 0 FROM trips WHERE id = :t"
                ),
                {"d": world.driver2_id, "t": trip_id},
            )


@pytest.mark.parametrize("terminal_status", ["cancelled", "completed"])
def test_terminal_trip_leaves_the_overlap_constraint(world: World, terminal_status: str) -> None:
    vehicle = make_vehicle(world, world.driver_id, f"01A1{len(terminal_status)}3AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    with world.db.session() as s:
        s.execute(text("UPDATE trips SET status = :st WHERE id = :t"), {"st": terminal_status, "t": trip_id})
        s.commit()
    make_trip(world, world.driver_id, vehicle, start=world.base_time)  # same slot is free again


def test_ac10_ac11_reserve_follows_the_segment_example(world: World, unchecked_segment_counters: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A104AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    with world.db.session() as s:
        assert trips_service.reserve(s, trip_id, A, C, ResourceDemand(seats=2)) == [A, B]
        trips_service.reserve(s, trip_id, B, D, ResourceDemand(seats=1))
        s.commit()
    assert seats(world, trip_id) == [2, 3, 1]

    with world.db.session() as s:
        remaining_b_c = trips_service.get_segment_loads(s, trip_id)[1].remaining(Resource.SEATS)
        assert remaining_b_c == 1  # AC10
        with pytest.raises(DomainError) as info:
            trips_service.reserve(s, trip_id, A, D, ResourceDemand(seats=2))
        assert info.value.code is ErrorCode.CAPACITY_UNAVAILABLE
        s.rollback()
    assert seats(world, trip_id) == [2, 3, 1]  # rejected reserve wrote nothing

    with world.db.session() as s:
        trips_service.reserve(s, trip_id, C, D, ResourceDemand(seats=3))  # AC11
        s.commit()
    assert seats(world, trip_id) == [2, 3, 4]

    with world.db.session() as s:
        trips_service.release(s, trip_id, A, C, ResourceDemand(seats=2))
        s.commit()
    assert seats(world, trip_id) == [0, 1, 4]


def test_ac12_baggage_and_cargo_limits(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A105AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time, baggage_ml=50_000, cargo_g=10_000)
    with world.db.session() as s:
        trips_service.reserve(s, trip_id, A, D, ResourceDemand(seats=1, baggage_ml=40_000))
        with pytest.raises(DomainError) as info:
            trips_service.reserve(s, trip_id, B, C, ResourceDemand(baggage_ml=20_000, cargo_weight_g=5_000))
        assert info.value.code is ErrorCode.CARGO_LIMIT_EXCEEDED
        assert info.value.details["segments"][0]["resource"] == "baggage_ml"


def test_used_never_exceeds_capacity_check_constraint(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A106AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    for column, constraint in (
        ("seats_used = seat_capacity + 1", "ck_trip_segment_resources_seats"),
        ("seats_used = -1", "ck_trip_segment_resources_seats"),
        ("cargo_used_weight_g = cargo_capacity_weight_g + 1", "ck_trip_segment_resources_cargo_weight"),
        ("baggage_used_ml = baggage_capacity_ml + 1", "ck_trip_segment_resources_baggage"),
    ):
        with world.db.session() as s, pytest.raises(IntegrityError, match=constraint):
            s.execute(text(f"UPDATE trip_segment_resources SET {column} WHERE trip_id = :t"), {"t": trip_id})
    assert seats(world, trip_id) == [0, 0, 0]


def test_parallel_reserve_of_the_last_seat_has_one_winner(world: World, unchecked_segment_counters: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A107AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time, seats=1)

    def take(worker: int, session: Session) -> list[int]:
        taken = trips_service.reserve(session, trip_id, A, D, ResourceDemand(seats=1))
        session.commit()
        return taken

    report = run_concurrently(20, take, engine=world.db.engine)
    assert len(report.successes) == 1
    assert len(report.failures) == 19
    assert all(isinstance(r.error, DomainError) and r.error.code is ErrorCode.CAPACITY_UNAVAILABLE for r in report.failures)
    assert seats(world, trip_id) == [1, 1, 1]


def test_release_beyond_reserved_is_a_bookkeeping_error(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A108AA")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    with world.db.session() as s, pytest.raises(trips_service.CapacityAccountingError):
        trips_service.release(s, trip_id, A, B, ResourceDemand(seats=1))


def test_trip_create_guards(world: World) -> None:
    pending = make_vehicle(world, world.driver_id, "01A109AA", approve=False)
    approved = make_vehicle(world, world.driver_id, "01A110AA", seats=3)
    with world.db.session() as s:
        for body, code in (
            (trip_create(world, pending, start=world.base_time), ErrorCode.VEHICLE_NOT_ELIGIBLE),
            (trip_create(world, approved, start=world.base_time, seats=4), ErrorCode.VEHICLE_NOT_ELIGIBLE),
            (trip_create(world, approved, start=world.base_time, seats=3, stops=("D", "C")), ErrorCode.ROUTE_CHANGED),
        ):
            with pytest.raises(DomainError) as info:
                trips_service.create_trip(s, driver_user_id=world.driver_id, data=body)
            assert info.value.code is code
            s.rollback()
        with pytest.raises(DomainError) as info:
            trips_service.create_trip(s, driver_user_id=world.driver2_id, data=trip_create(world, approved, start=world.base_time, seats=3))
        assert info.value.code is ErrorCode.NOT_FOUND  # someone else's vehicle is invisible


def test_blocked_driver_cannot_create_trip(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A111AA")
    with world.db.session() as s:
        identity_service.block_driver_eligibility(
            s, driver_user_id=world.driver_id, actor_user_id=world.admin_id, expected_version=1, reason="document review"
        )
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.create_trip(s, driver_user_id=world.driver_id, data=trip_create(world, vehicle, start=world.base_time))
    assert info.value.code is ErrorCode.DRIVER_NOT_ELIGIBLE


def test_patch_trip_schedule_frozen_once_capacity_is_reserved(world: World, unchecked_segment_counters: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01A112AA")
    trip_id, trip_public_id = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    with world.db.session() as s:
        trip = trips_service.patch_trip(
            s, trip_public_id_value=trip_public_id, actor_user_id=world.driver_id, data=TripPatch(expected_version=1, max_detour_minutes=20)
        )
        assert trip.version == 2
        trips_service.reserve(s, trip_id, A, B, ResourceDemand(seats=1))
        s.commit()
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.patch_trip(
            s,
            trip_public_id_value=trip_public_id,
            actor_user_id=world.driver_id,
            data=TripPatch(expected_version=2, planned_end_at=world.base_time + timedelta(hours=6)),
        )
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION
    with world.db.session() as s, pytest.raises(DomainError) as info:
        trips_service.patch_trip(
            s, trip_public_id_value=trip_public_id, actor_user_id=world.driver_id, data=TripPatch(expected_version=1, max_detour_m=10)
        )
    assert info.value.code is ErrorCode.VERSION_CONFLICT
