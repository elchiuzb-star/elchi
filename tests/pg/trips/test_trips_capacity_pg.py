"""Trips on real PostgreSQL 16: overlap exclusion (AC13), create guards, races.

Capacity (AC10-AC12) is the road-interval claim model (ADR-0028): its arithmetic is unit-tested in
``tests/modules/trips/test_trip_rules.py`` and proved through accept in ``tests/pg/bookings``."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity import service as identity_service
from app.modules.trips import service as trips_service
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import World, make_trip, make_vehicle, trip_create

pytestmark = pytest.mark.pg



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
            s, driver_user_id=world.driver_id, data=trip_create(world, other_vehicle, start=world.base_time + timedelta(hours=3, minutes=10))  # the plan ends at D (+3 h)
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


def test_trip_create_guards(world: World) -> None:
    pending = make_vehicle(world, world.driver_id, "01A109AA", approve=False)
    approved = make_vehicle(world, world.driver_id, "01A110AA", seats=3)
    with world.db.session() as s:
        for body, code in (
            (trip_create(world, pending, start=world.base_time), ErrorCode.VEHICLE_NOT_ELIGIBLE),
            (trip_create(world, approved, start=world.base_time, seats=4), ErrorCode.VEHICLE_NOT_ELIGIBLE),
            # ADR-0028: the trip's stretch must lie on the road
            (trip_create(world, approved, start=world.base_time, seats=3).model_copy(update={"route_end_m": 10_000_000}),
             ErrorCode.VALIDATION_ERROR),
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

