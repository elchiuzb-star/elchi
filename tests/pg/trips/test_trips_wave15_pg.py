"""Wave 1.5 trips fixes on PostgreSQL: the NO KEY UPDATE trip lock.

The release contract (one release per booking) is the road claim's (ADR-0028): ``tests/pg/bookings/test_route_positions_pg.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.modules.trips import service as trips_service
from tests.pg.identity.a1_world import World, make_trip, make_vehicle, run_in_thread

pytestmark = pytest.mark.pg


def test_trip_lock_allows_foreign_key_inserts_referencing_the_trip(world: World) -> None:
    vehicle = make_vehicle(world, world.driver_id, "01K200KK")
    trip_id, _ = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    holder = world.db.session()
    try:
        trips_service.lock_trip(holder, trip_id)

        def take_the_fk_check_lock() -> None:
            with world.db.session() as s:  # an FK insert referencing trips(id) takes exactly this FOR KEY SHARE lock
                s.execute(text("SELECT 1 FROM trips WHERE id = :t FOR KEY SHARE"), {"t": trip_id})
                s.rollback()

        thread, outcome = run_in_thread(take_the_fk_check_lock)
        thread.join(timeout=10)
        assert not thread.is_alive() and "error" not in outcome, outcome
    finally:
        holder.rollback()
        holder.close()
