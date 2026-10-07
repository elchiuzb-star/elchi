"""PostGIS tests for the geo catalogue, confirmed roads, rollout guards and 0043 DB guards
(AC35; spec §6.3; STATE_MACHINES §10; wave 1.5 BR #5, #6, #8, #17; ADR-0028 / Q160: no stops - a road is its geometry).

Fixture geography is synthetic (tests/fixtures/geo/corridor_fixture.json).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import new_public_uuid
from app.modules.geo import service
from app.modules.geo.routing import FakeRoutingProvider
from app.modules.geo.types import LatLng
from app.modules.platform import service as platform_service
from tests.fixtures.geo.loader import build_route, load_geo_fixture
from tests.pg.conftest import PgDatabase, run_alembic, script_heads
from tests.pg.geo.geo_pg_helpers import create_user, set_q48_gate

pytestmark = pytest.mark.pg


@pytest.fixture
def geo(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fixture = load_geo_fixture(db, actor_user_id=admin)
    return pg_db, fixture, admin


def mark_production(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))


def _point_sql(place: LatLng) -> str:
    return f"ST_SetSRID(ST_MakePoint({place.lng}, {place.lat}), 4326)"


def test_geography_distance_is_metres_and_geometry_distance_is_not(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    chiroqchi = _point_sql(fx.places["chiroqchi"])
    with pg_db.engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT ST_Distance(rv.geometry::geography, {chiroqchi}::geography) AS metres, "
                f"ST_Distance(rv.geometry, {chiroqchi}) AS degrees, "
                f"ST_DWithin(rv.geometry, {chiroqchi}, 3000) AS geometry_dwithin_3000, "
                f"ST_DWithin(rv.geometry::geography, {chiroqchi}::geography, 3000) AS geography_dwithin_3000 "
                "FROM route_versions rv WHERE rv.id = :rv"
            ),
            {"rv": fx.routes["via_kattaqorgon"].id},
        ).one()
        on_route = conn.scalar(
            text(f"SELECT ST_Distance(rv.geometry::geography, {chiroqchi}::geography) FROM route_versions rv WHERE rv.id = :rv"),
            {"rv": fx.routes["via_chiroqchi"].id},
        )
    assert row.metres > 50_000 and row.degrees < 1.0
    assert row.geometry_dwithin_3000 is True and row.geography_dwithin_3000 is False
    assert on_route < 1.0


def test_a_place_off_the_road_does_not_project_and_order_is_along_the_road(geo) -> None:  # noqa: ANN001
    """AC14 / AC16 on the road model: Chiroqchi is on one fixture road and not the other; along a road the places come
    in their travel order (pickup before dropoff is a position comparison)."""
    pg_db, fx, _ = geo
    with pg_db.session() as db:
        off = service.project_point_on_route(db, route_version_id=fx.routes["via_kattaqorgon"].id, point=fx.places["chiroqchi"],
                                             max_offset_m=3000)
        road = fx.routes["via_chiroqchi"].id
        chiroqchi = service.route_position_m(db, route_version_id=road, point=fx.places["chiroqchi"])
        qarshi = service.route_position_m(db, route_version_id=road, point=fx.places["qarshi"])
    assert off is None
    assert 0 < chiroqchi < qarshi


def test_gist_index_serves_the_road_proximity_query(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    with pg_db.engine.begin() as conn:
        conn.execute(text("ANALYZE route_versions"))
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            r[0]
            for r in conn.execute(
                text(
                    "EXPLAIN SELECT id FROM route_versions WHERE status = 'confirmed' AND "
                    f"ST_DWithin(geometry::geography, {_point_sql(fx.places['chiroqchi'])}::geography, 3000)"
                )
            )
        )
    assert "ix_route_versions_geography_gist" in plan, plan


def test_confirmed_route_version_is_immutable(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    route_id = fx.routes["via_chiroqchi"].id
    for statement in (
        "UPDATE route_versions SET distance_m = distance_m + 1 WHERE id = :id",
        "UPDATE route_versions SET status = 'draft', confirmed_at = NULL WHERE id = :id",
        "DELETE FROM route_versions WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"id": route_id})


def test_a_draft_road_has_its_attribution_and_immutable_content(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    with pg_db.session() as db:
        draft = build_route(db, FakeRoutingProvider(), actor_user_id=admin, corridor=fx.corridor,
                            through=[fx.places["toshkent"], fx.places["qarshi"]], confirm=False)
    assert draft.attribution == "Synthetic route from the Elchi test router (not a real road)"
    with pytest.raises(DBAPIError, match="content is immutable"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE route_versions SET duration_s = duration_s + 1 WHERE id = :id"), {"id": draft.id})


def test_catalogue_constraints(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    for statement, message in (
        ("UPDATE corridor_config_versions SET search_radius_m = 1 WHERE corridor_id = :id", "immutable"),
        ("UPDATE service_corridors SET rollout_state = 'launched' WHERE id = :id", "ck_service_corridors_rollout_state"),
    ):
        with pytest.raises(DBAPIError, match=message):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"id": fx.corridor.id})


def test_ac35_router_outage_writes_nothing_generic_error_and_cache_is_reused(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    origin, destination = fx.places["toshkent"], fx.places["qarshi"]
    departure = datetime.now(timezone.utc) + timedelta(days=1)
    with pg_db.engine.connect() as conn:
        before = conn.scalar(text("SELECT count(*) FROM route_versions"))

    down = FakeRoutingProvider(outage=True)
    db = pg_db.session()
    try:
        plan = service.prepare_road_preview(db, down, corridor_api_id=fx.corridor.api_id, origin=origin, destination=destination,
                                            departure_at=departure)
        with pytest.raises(RuntimeError, match="transaction"):
            service.fetch_route_outside_transaction(db, down, plan)
        db.rollback()
        with pytest.raises(DomainError) as info:
            service.fetch_route_outside_transaction(db, down, plan)
        assert info.value.code is ErrorCode.ROUTING_UNAVAILABLE and info.value.http_status == 503
        assert info.value.details == {"retryable": True}  # provider/reason stay in server logs (BR #12)
    finally:
        db.close()
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM route_versions")) == before

    up = FakeRoutingProvider()
    with pg_db.session() as db:
        first = build_route(db, up, actor_user_id=admin, corridor=fx.corridor, through=[origin, destination], confirm=False)
        calls = len(up.calls)
        second = build_route(db, up, actor_user_id=admin, corridor=fx.corridor, through=[origin, destination], confirm=False)
    assert len(up.calls) == calls == 1
    assert first.id != second.id and first.distance_m == second.distance_m


def test_legacy_cities_are_mapped_unverified_never_guessed(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        city_id = conn.scalar(
            text("INSERT INTO cities (name, name_uz, type, requires_district, display_order, is_active) VALUES ('Qashqadaryo', 'Qashqadaryo', 'region', true, 1, true) RETURNING id")
        )
    assert run_alembic(pg_db.url, "stamp", "20260913_0033").returncode == 0
    assert run_alembic(pg_db.url, "upgrade", "20260913_0034").returncode == 0
    assert run_alembic(pg_db.url, "stamp", script_heads()[0]).returncode == 0
    with pg_db.engine.connect() as conn:
        rows = conn.execute(text("SELECT mapping_status, region_id, settlement_id FROM legacy_city_mappings WHERE legacy_city_id = :id"), {"id": city_id}).all()
    assert rows == [("unverified", None, None)]
    with pytest.raises(DBAPIError, match="ck_legacy_city_mappings_verified"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE legacy_city_mappings SET mapping_status = 'verified' WHERE legacy_city_id = :id"), {"id": city_id})


# --- rollout (STATE_MACHINES §10, BR #8, decision 27) ---------------------------------------------------


def _rollout(db, admin: int, corridor: service.CorridorInfo, state: str) -> service.CorridorInfo:  # noqa: ANN001
    return service.patch_corridor(db, actor_user_id=admin, corridor_api_id=corridor.api_id, expected_version=corridor.version, reason="test", changes={"rollout_state": state})


def _guard_reason(fn) -> str | None:  # noqa: ANN001
    try:
        fn()
    except DomainError as exc:
        assert exc.code is ErrorCode.INVALID_STATE_TRANSITION, exc.code
        return (exc.details or {}).get("reason", "not_allowed")
    return None


def test_corridor_rollout_guards(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    region_tk, region_sa = fx.regions["toshkent"].api_id, fx.regions["samarqand"].api_id
    with pg_db.session() as db:
        corridor = service.create_corridor(
            db, actor_user_id=admin, name="Rollout test", origin_region_api_id=region_tk, destination_region_api_id=region_sa,
            search_radius_m=3000, default_max_detour_minutes=10, default_max_detour_m=3000,
        )
        db.commit()
        assert _guard_reason(lambda: _rollout(db, admin, corridor, "active")) == "not_allowed"  # not in CORRIDOR_ROLLOUT
        db.rollback()

        corridor = _rollout(db, admin, corridor, "internal")
        db.commit()
        assert _guard_reason(lambda: _rollout(db, admin, corridor, "pilot")) == "needs_confirmed_road"
        db.rollback()
        # ADR-0028: only the confirmed road from A to B makes a corridor public
        build_route(db, FakeRoutingProvider(), actor_user_id=admin, corridor=corridor,
                    through=[LatLng(39.65, 66.96), LatLng(39.66, 66.97)])
        corridor = _rollout(db, admin, service.get_corridor(db, corridor.id), "pilot")
        db.commit()
        assert corridor.rollout_state.value == "pilot"
        corridor = _rollout(db, admin, corridor, "internal")
        db.commit()

        # internal -> draft: A4's booking counter hook (bookings do not exist yet).
        service.set_active_booking_counter(lambda _db, corridor_id: 2)
        try:
            assert _guard_reason(lambda: _rollout(db, admin, corridor, "draft")) == "active_bookings"
            db.rollback()
        finally:
            service.set_active_booking_counter(None)
        if platform_service.table_exists(db, "bookings"):
            with pytest.raises(DomainError) as unwired:
                _rollout(db, admin, corridor, "draft")
            assert unwired.value.code is ErrorCode.SERVICE_UNAVAILABLE
            db.rollback()
            service.set_active_booking_counter(lambda _db, corridor_id: 0)
        try:
            corridor = _rollout(db, admin, corridor, "draft")
            db.commit()
        finally:
            service.set_active_booking_counter(None)
        assert corridor.rollout_state.value == "draft" and corridor.version == 5
        closed = _rollout(db, admin, corridor, "closed")
        db.commit()
        assert _guard_reason(lambda: _rollout(db, admin, closed, "draft")) == "not_allowed"


# --- 0043 DB guards under the production marker (BR #5, #6) --------------------------------------------


def test_production_marker_db_guards(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    mark_production(pg_db)
    set_q48_gate(pg_db, passed=True)  # SQL side only; Q56 has its own tests
    insert_flag = text(
        "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, approval_reference, reason, updated_by) "
        "VALUES (:p, :k, 'country', 'UZ', :e, :a, 'r', :u)"
    )
    for key, enabled, approval, message in (
        ("passenger_enabled", True, None, "requires approval_reference"),
        ("card_payments_enabled", True, "  ", "requires approval_reference"),
        ("wallet_required", False, None, "wallet_required"),  # A3's guard (0042); geo does not duplicate it
    ):
        with pytest.raises(DBAPIError, match=message):
            with pg_db.engine.begin() as conn:
                service.mark_flag_change_source(conn)  # Q72 marker: exercise the 0043 production rules
                conn.execute(insert_flag, {"p": new_public_uuid(), "k": key, "e": enabled, "a": approval, "u": admin})
    with pg_db.engine.begin() as conn:
        service.mark_flag_change_source(conn)
        conn.execute(insert_flag, {"p": new_public_uuid(), "k": "passenger_enabled", "e": True, "a": "LEGAL-1", "u": admin})
        conn.execute(insert_flag, {"p": new_public_uuid(), "k": "card_payments_enabled", "e": False, "a": None, "u": admin})
    with pytest.raises(DBAPIError, match="requires approval_reference"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE feature_flag_values SET approval_reference = NULL, version = version + 1 WHERE flag_key = 'passenger_enabled'"))

    with pytest.raises(DBAPIError, match="fixture is forbidden in production"):
        with pg_db.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO route_versions (public_id, corridor_id, created_by_user_id, source, provider, provider_version, request_hash, geometry, distance_m, duration_s, is_estimate) "
                    "SELECT :p, corridor_id, created_by_user_id, 'fixture', provider, provider_version, request_hash, geometry, distance_m, duration_s, is_estimate "
                    "FROM route_versions WHERE id = :id"
                ),
                {"p": new_public_uuid(), "id": fx.routes["via_chiroqchi"].id},
            )
    with pg_db.session() as db:
        assert platform_service.is_production(db)
        assert service.production_flag_violations(db) == []


def test_missing_marker_counts_as_production_for_db_guards(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        assert conn.scalar(text("SELECT geo_production_guard_active()")) is False
        conn.execute(text("ALTER TABLE platform_environment DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM platform_environment"))
        conn.execute(text("ALTER TABLE platform_environment ENABLE TRIGGER USER"))
        assert conn.scalar(text("SELECT geo_production_guard_active()")) is True
