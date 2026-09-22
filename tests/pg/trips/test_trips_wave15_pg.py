"""Wave 1.5 trips fixes on PostgreSQL: release contract (double release detection), NO KEY UPDATE trip lock."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.modules.trips import service as trips_service
from app.modules.trips.rules import ResourceDemand
from tests.pg.identity.a1_world import World, make_trip, make_vehicle, run_in_thread

pytestmark = pytest.mark.pg


def test_double_release_is_detected_and_writes_nothing(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01K100KK")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    demand = ResourceDemand(seats=2, baggage_ml=30_000)
    with world.db.session() as s:
        trips_service.reserve(s, trip_id, 1, 3, demand)
        trips_service.release(s, trip_id, 1, 3, demand)
        s.commit()
    with world.db.session() as s, pytest.raises(trips_service.CapacityAccountingError):
        trips_service.release(s, trip_id, 1, 3, demand)
    with world.db.session() as s:
        loads = trips_service.get_segment_loads(s, trip_id)
        assert [(load.seats_used, load.baggage_used_ml) for load in loads] == [(0, 0), (0, 0), (0, 0)]


def test_trip_lock_allows_foreign_key_inserts_referencing_the_trip(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01K200KK")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    holder = world.db.session()
    try:
        trips_service.lock_trip(holder, trip_id)

        def insert_occurrence_like_row() -> None:
            with world.db.session() as s:  # an FK insert referencing trips(id) takes FOR KEY SHARE
                s.execute(
                    text(
                        "INSERT INTO trip_stop_occurrences (trip_id, seq, stop_id, route_version_stop_seq, planned_arrival_at) "
                        "SELECT :t, 99, stop_id, route_version_stop_seq, planned_arrival_at FROM trip_stop_occurrences "
                        "WHERE trip_id = :t AND seq = 1"
                    ),
                    {"t": trip_id},
                )
                s.rollback()

        thread, outcome = run_in_thread(insert_occurrence_like_row)
        thread.join(timeout=10)
        assert not thread.is_alive() and "error" not in outcome, outcome
    finally:
        holder.rollback()
        holder.close()
