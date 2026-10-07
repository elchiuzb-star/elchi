"""ADR-0028 / Q160: ELCHI has no stops.

* a public corridor needs a confirmed road (0099) - the service and the deferred DB guard both refuse otherwise;
* the stop-era tables are frozen history (0101): any INSERT / UPDATE / DELETE is refused with ``stops_retired``;
* no row may gain a stop id (an old row keeps its own as history), and every listing / proposal version / booking end
  is a point;
* the v2 API has no stop endpoints and no stop field.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.db_errors import map_db_error
from app.contracts.enums import ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.geo import service
from tests.fixtures.geo.loader import load_geo_fixture
from tests.pg.conftest import PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user

pytestmark = pytest.mark.pg

FROZEN = ("corridor_stops", "route_version_stops", "trip_stop_occurrences", "trip_segment_resources", "booking_allocations")


@pytest.fixture
def geo(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fixture = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
    return pg_db, fixture, admin


def _historic_stop(pg_db: PgDatabase, fx, admin: int) -> int:  # noqa: ANN001
    """A stop row as the stop era left it (written with the freeze guard off, test-only)."""
    guard = "trg_corridor_stops_stops_retired"
    with pg_db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE corridor_stops DISABLE TRIGGER {guard}"))
    try:
        with pg_db.engine.begin() as conn:
            stop_id = conn.scalar(
                text(
                    "INSERT INTO corridor_stops (public_id, corridor_id, geo_district_id, name_uz, point, is_active, verified_by, "
                    "verified_at) SELECT gen_random_uuid(), :c, d.id, 'Tarixiy bekat', ST_SetSRID(ST_MakePoint(69.2, 41.3), 4326), "
                    "true, :a, now() FROM geo_districts d ORDER BY d.id LIMIT 1 RETURNING id"
                ),
                {"c": fx.corridor.id, "a": admin},
            )
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE corridor_stops ENABLE TRIGGER {guard}"))
    return stop_id


def _refusal(pg_db: PgDatabase, sql: str, **params: object) -> DBAPIError:
    with pytest.raises(DBAPIError) as info, pg_db.engine.begin() as conn:
        conn.execute(text(sql), params)
    return info.value


def _rule(error: DBAPIError) -> str | None:
    return getattr(getattr(getattr(error, "orig", None), "diag", None), "constraint_name", None)


def test_a_public_corridor_needs_a_confirmed_road(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    with pg_db.session() as db:
        corridor = service.create_corridor(
            db, actor_user_id=admin, name="Yo'lsiz koridor", origin_region_api_id=fx.regions["toshkent"].api_id,
            destination_region_api_id=fx.regions["samarqand"].api_id, search_radius_m=3000, default_max_detour_minutes=10,
            default_max_detour_m=1000,
        )
        corridor = service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id,
                                          expected_version=corridor.version, reason="internal", changes={"rollout_state": "internal"})
        db.commit()
        with pytest.raises(DomainError) as info:
            service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id, expected_version=corridor.version,
                                   reason="pilot", changes={"rollout_state": "pilot"})
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION and info.value.details["reason"] == "needs_confirmed_road"
    error = _refusal(pg_db, "UPDATE service_corridors SET rollout_state = 'pilot', version = version + 1 WHERE id = :id",
                     id=corridor.id)
    assert "need a confirmed road" in str(error)


@pytest.mark.parametrize("table", FROZEN)
def test_nothing_new_is_written_to_a_stop_table(geo, table: str) -> None:  # noqa: ANN001
    pg_db, _fx, _admin = geo
    error = _refusal(pg_db, f"INSERT INTO {table} DEFAULT VALUES")  # BEFORE ROW guard fires before any NOT NULL check
    assert _rule(error) == "stops_retired", str(error)
    rule = map_db_error(sqlstate=getattr(error.orig, "sqlstate", None), constraint="stops_retired")
    assert (rule.code, rule.reason) == (ErrorCode.INTEGRITY_CONFLICT, "stops_retired")


def test_a_historic_stop_can_neither_change_nor_go_and_nothing_may_point_at_it(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    stop_id = _historic_stop(pg_db, fx, admin)
    assert _rule(_refusal(pg_db, "UPDATE corridor_stops SET name_uz = 'x' WHERE id = :s", s=stop_id)) == "stops_retired"
    assert _rule(_refusal(pg_db, "DELETE FROM corridor_stops WHERE id = :s", s=stop_id)) == "stops_retired"

    with pg_db.session() as db:
        band = service.set_price_band(db, actor_user_id=admin, corridor_api_id=fx.corridor.api_id,
                                      service_type=ServiceType.PASSENGER, floor_minor=1_000, ceiling_minor=9_000,
                                      is_active=True, reason="corridor band")
        db.commit()
    refused = _refusal(pg_db, "UPDATE corridor_price_bands SET origin_stop_id = :s, destination_stop_id = :s WHERE id = :b",
                       s=stop_id, b=band.id)
    # refused either way: the band's scope was already immutable (0046), and no row may gain a stop (0101)
    assert _rule(refused) == "stops_retired" or "scope columns are immutable" in str(refused)


def test_every_end_is_a_point_and_no_row_may_gain_a_stop(pg_db: PgDatabase) -> None:
    with pg_db.engine.connect() as conn:
        checks = set(conn.execute(text("SELECT conname FROM pg_constraint WHERE conname LIKE '%point_required'")).scalars())
        triggers = set(conn.execute(text("SELECT tgname FROM pg_trigger WHERE tgname LIKE '%no_new_stop'")).scalars())
    assert checks == {
        f"ck_{table}_{end}_point_required"
        for table, ends in (("listings", ("origin", "destination")), ("proposal_versions", ("pickup", "dropoff")),
                            ("bookings", ("pickup", "dropoff")))
        for end in ends
    }
    assert triggers == {f"trg_{t}_no_new_stop" for t in
                        ("listings", "proposal_versions", "bookings", "corridor_price_bands", "trip_intent_versions")}


def test_the_v2_api_has_no_stop_endpoint_or_field() -> None:
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert not [path for path in paths if path.startswith("/api/v2") and "stop" in path]
    schema = app.openapi()
    text_schema = str(schema)
    for name in ("origin_stop_id", "pickup_stop_id", "stop_ids", "stops_count", "StopRefDTO", "occurrence_seq", "'stops'"):
        assert name not in text_schema, name
