"""PostGIS tests for the geo catalogue, route versions, matching, rollout guards and 0043 DB guards
(AC14, AC16, AC35; spec §6.3; STATE_MACHINES §10; wave 1.5 BR #5, #6, #8, #17; decision 27).

Fixture geography is synthetic (tests/fixtures/geo/corridor_fixture.json).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import MatchType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import new_public_uuid
from app.modules.geo import service
from app.modules.geo.routing import FakeRoutingProvider
from app.modules.geo.types import LatLng, MatchReason, MatchRequest, TripRouteContext
from app.modules.platform import service as platform_service
from tests.fixtures.geo.loader import build_route, load_geo_fixture
from tests.pg.conftest import PgDatabase, run_alembic, script_heads
from tests.pg.geo.geo_pg_helpers import create_user, set_q48_gate

pytestmark = pytest.mark.pg

START = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)  # 06:00 Tashkent


@pytest.fixture
def geo(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fixture = load_geo_fixture(db, actor_user_id=admin)
    return pg_db, fixture, admin


def trip_context(route: service.RouteVersionInfo, **kw) -> TripRouteContext:  # noqa: ANN003
    params = dict(trip_version=1, max_detour_minutes=15, max_detour_m=5000)
    params.update(kw)
    return TripRouteContext(
        route_version_id=route.id,
        route_version_public_id=route.api_id,
        occurrences=service.planned_occurrences_from_route_version(route, planned_start_at=START, dwell_minutes=5),
        **params,
    )


def eta_request(route: service.RouteVersionInfo, pickup: int, dropoff: int) -> MatchRequest:
    occurrences = {o.stop_id: o for o in service.planned_occurrences_from_route_version(route, planned_start_at=START, dwell_minutes=5)}
    arrival = occurrences[pickup].planned_arrival_at if pickup in occurrences else START + timedelta(hours=4)
    return MatchRequest(pickup, dropoff, arrival - timedelta(minutes=30), arrival + timedelta(minutes=30))


def mark_production(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))


def test_geography_distance_is_metres_and_geometry_distance_is_not(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    with pg_db.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT ST_Distance(rv.geometry::geography, cs.point::geography) AS metres, "
                "ST_Distance(rv.geometry, cs.point) AS degrees, "
                "ST_DWithin(rv.geometry, cs.point, 3000) AS geometry_dwithin_3000, "
                "ST_DWithin(rv.geometry::geography, cs.point::geography, 3000) AS geography_dwithin_3000 "
                "FROM route_versions rv, corridor_stops cs WHERE rv.id = :rv AND cs.id = :stop"
            ),
            {"rv": fx.routes["via_kattaqorgon"].id, "stop": fx.stop_id("chiroqchi")},
        ).one()
        on_route = conn.scalar(
            text("SELECT ST_Distance(rv.geometry::geography, cs.point::geography) FROM route_versions rv, corridor_stops cs WHERE rv.id = :rv AND cs.id = :stop"),
            {"rv": fx.routes["via_chiroqchi"].id, "stop": fx.stop_id("chiroqchi")},
        )
    assert row.metres > 50_000 and row.degrees < 1.0
    assert row.geometry_dwithin_3000 is True and row.geography_dwithin_3000 is False
    assert on_route < 1.0


def test_ac14_chiroqchi_not_on_fixture_route_gives_no_on_route(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    chiroqchi, qarshi = fx.stop_id("chiroqchi"), fx.stop_id("qarshi")
    without, with_chiroqchi = fx.routes["via_kattaqorgon"], fx.routes["via_chiroqchi"]
    with pg_db.session() as db:
        candidates = service.find_candidates(db, pickup_stop_id=chiroqchi, dropoff_stop_id=qarshi)
        points = service.get_stop_points(db, [s.stop_id for s in without.stops] + [chiroqchi])
    assert [c.route_version_id for c in candidates] == [with_chiroqchi.id]

    request = eta_request(with_chiroqchi, chiroqchi, qarshi)
    ctx = trip_context(without)
    plain = service.evaluate_route_match(ctx, request)
    assert not plain.matched and plain.error_code is ErrorCode.ROUTE_MISMATCH
    assert MatchReason.PICKUP_NOT_ON_ROUTE in plain.reasons

    db = pg_db.session()
    try:
        measured = service.measure_detours_outside_transaction(db, FakeRoutingProvider(), ctx, request, points)
    finally:
        db.close()
    assert measured.quotes and not measured.unavailable_stop_ids
    assert all(q.route_version_id == without.api_id and q.trip_version == 1 for q in measured.quotes)
    with_detour = service.evaluate_route_match(ctx, request, detours=measured, include_alternatives=True)
    assert with_detour.match_type not in (MatchType.EXACT, MatchType.ON_ROUTE, MatchType.DETOUR)
    assert with_detour.error_code in (ErrorCode.DETOUR_LIMIT_EXCEEDED, ErrorCode.TIME_WINDOW_CONFLICT)

    ok = service.evaluate_route_match(trip_context(with_chiroqchi), request)
    assert ok.matched and ok.match_type is MatchType.ON_ROUTE and ok.pickup.occurrence_seq == 2


def test_ac16_reverse_direction_rejected_even_though_spatially_near(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    route = fx.routes["via_chiroqchi"]
    qarshi, chiroqchi = fx.stop_id("qarshi"), fx.stop_id("chiroqchi")
    with pg_db.session() as db:
        candidates = service.find_candidates(db, pickup_stop_id=qarshi, dropoff_stop_id=chiroqchi)
    assert [c.route_version_id for c in candidates] == [route.id]
    assert candidates[0].forward_by_line_fraction is False
    assert candidates[0].pickup_stop_seqs == (3,) and candidates[0].dropoff_stop_seqs == (2,)
    wide = MatchRequest(qarshi, chiroqchi, START, START + timedelta(hours=20))
    result = service.evaluate_route_match(trip_context(route), wide, include_alternatives=True)
    assert result.error_code is ErrorCode.ROUTE_MISMATCH and result.reasons == (MatchReason.REVERSE_DIRECTION,)


def test_find_candidates_orders_newest_confirmed_first(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    keys = ["toshkent", "samarqand", "qarshi"]
    with pg_db.session() as db:
        newer = build_route(db, FakeRoutingProvider(), actor_user_id=admin, stop_api_ids=[fx.stops[k].api_id for k in keys])
        candidates = service.find_candidates(db, pickup_stop_id=fx.stop_id("toshkent"), dropoff_stop_id=fx.stop_id("qarshi"))
    ids = [c.route_version_id for c in candidates]
    assert ids[0] == newer.id and set(ids) == {newer.id, fx.routes["via_kattaqorgon"].id, fx.routes["via_chiroqchi"].id}
    assert [c.confirmed_at for c in candidates] == sorted((c.confirmed_at for c in candidates), reverse=True)


def test_gist_indexes_serve_the_real_find_candidates_query(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    statement = text(service.FIND_CANDIDATES_SQL).bindparams(
        pickup=fx.stop_id("chiroqchi"), dropoff=fx.stop_id("qarshi"), radius=3000, corridor_id=None, limit=100
    )
    compiled = str(statement.compile(pg_db.engine, compile_kwargs={"literal_binds": True}))
    with pg_db.engine.begin() as conn:
        conn.execute(text("ANALYZE route_versions"))
        conn.execute(text("ANALYZE corridor_stops"))
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        route_plan = "\n".join(r[0] for r in conn.execute(text("EXPLAIN " + compiled)))
        stop_plan = "\n".join(
            r[0]
            for r in conn.execute(
                text(
                    "EXPLAIN SELECT id FROM corridor_stops "
                    "WHERE ST_DWithin(point::geography, ST_SetSRID(ST_MakePoint(66.57, 39.03), 4326)::geography, 3000)"
                )
            )
        )
    assert "ix_route_versions_geography_gist" in route_plan, route_plan
    assert "ix_corridor_stops_geography_gist" in stop_plan, stop_plan


def test_nearby_stop_ids_uses_metres(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    with pg_db.session() as db:
        assert service.nearby_stop_ids(db, fx.stop_id("chiroqchi"), radius_m=35_000) == [fx.stop_id("kitob")]
        assert service.nearby_stop_ids(db, fx.stop_id("chiroqchi"), radius_m=1_000) == []


def test_confirmed_route_version_and_its_stops_are_immutable(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    route_id = fx.routes["via_chiroqchi"].id
    statements = [
        "UPDATE route_versions SET distance_m = distance_m + 1 WHERE id = :id",
        "UPDATE route_versions SET status = 'draft', confirmed_at = NULL WHERE id = :id",
        "DELETE FROM route_versions WHERE id = :id",
        "UPDATE route_version_stops SET cumulative_distance_m = 1 WHERE route_version_id = :id",
        "DELETE FROM route_version_stops WHERE route_version_id = :id",
        "INSERT INTO route_version_stops (route_version_id, seq, stop_id, cumulative_distance_m, cumulative_duration_s, line_fraction) "
        "SELECT :id, 99, stop_id, 1, 1, 0.5 FROM route_version_stops WHERE route_version_id = :id LIMIT 1",
    ]
    for statement in statements:
        with pytest.raises(DBAPIError, match="immutable"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"id": route_id})


def test_draft_route_confirmation_checks_stops_and_content(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    with pg_db.session() as db:
        draft = build_route(db, FakeRoutingProvider(), actor_user_id=admin, stop_api_ids=[fx.stops["toshkent"].api_id, fx.stops["qarshi"].api_id], confirm=False)
    assert draft.attribution == "Synthetic route from the Elchi test router (not a real road)"
    with pytest.raises(DBAPIError, match="content is immutable"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE route_versions SET duration_s = duration_s + 1 WHERE id = :id"), {"id": draft.id})
    with pg_db.engine.begin() as conn:
        conn.execute(text("DELETE FROM route_version_stops WHERE route_version_id = :id AND seq = 1"), {"id": draft.id})
    with pytest.raises(DBAPIError, match="before confirmation"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE route_versions SET status = 'confirmed', confirmed_at = now() WHERE id = :id"), {"id": draft.id})


def test_catalogue_constraints(geo) -> None:  # noqa: ANN001
    pg_db, fx, _ = geo
    stop_id = fx.stop_id("qarshi")
    failing = [
        ("UPDATE corridor_stops SET verified_by = NULL WHERE id = :id", "ck_corridor_stops_active_verified"),
        ("UPDATE corridor_stops SET point = ST_SetSRID(ST_MakePoint(65.0, 95.0), 4326) WHERE id = :id", "ck_corridor_stops_point_valid"),
        ("UPDATE corridor_stops SET meeting_photo_file_id = '  ' WHERE id = :id", "ck_corridor_stops_meeting_photo_file_id"),
        ("UPDATE corridor_config_versions SET search_radius_m = 1 WHERE corridor_id = (SELECT corridor_id FROM corridor_stops WHERE id = :id)", "immutable"),
        ("UPDATE service_corridors SET rollout_state = 'launched' WHERE id = (SELECT corridor_id FROM corridor_stops WHERE id = :id)", "ck_service_corridors_rollout_state"),
    ]
    for statement, message in failing:
        with pytest.raises(DBAPIError, match=message):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"id": stop_id})


def test_stop_used_by_confirmed_route_cannot_move(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    stop = fx.stops["chiroqchi"]
    with pg_db.session() as db:
        with pytest.raises(DomainError) as info:
            service.patch_stop(db, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=stop.version, changes={"point": LatLng(39.5, 66.0)})
        assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION
        db.rollback()
        renamed = service.patch_stop(db, actor_user_id=admin, stop_api_id=stop.api_id, expected_version=stop.version, changes={"meeting_note": "Bozor oldida"})
        db.commit()
    assert renamed.version == stop.version + 1 and renamed.point == stop.point and renamed.meeting_note == "Bozor oldida"


def test_ac35_router_outage_writes_nothing_generic_error_and_cache_is_reused(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    stop_ids = [fx.stops["toshkent"].api_id, fx.stops["kitob"].api_id, fx.stops["qarshi"].api_id]
    departure = datetime.now(timezone.utc) + timedelta(days=1)
    with pg_db.engine.connect() as conn:
        before = conn.scalar(text("SELECT count(*) FROM route_versions"))

    down = FakeRoutingProvider(outage=True)
    db = pg_db.session()
    try:
        plan = service.prepare_route_preview(db, down, stop_api_ids=stop_ids, departure_at=departure)
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
        first = build_route(db, up, actor_user_id=admin, stop_api_ids=stop_ids, confirm=False)
        calls = len(up.calls)
        second = build_route(db, up, actor_user_id=admin, stop_api_ids=stop_ids, confirm=False)
    assert len(up.calls) == calls == 1
    assert first.id != second.id and first.distance_m == second.distance_m


def test_inactive_stop_blocks_route_preview(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    kitob = fx.stops["kitob"]
    with pg_db.session() as db:
        service.patch_stop(db, actor_user_id=admin, stop_api_id=kitob.api_id, expected_version=kitob.version, changes={"is_active": False})
        db.commit()
        with pytest.raises(DomainError) as info:
            service.prepare_route_preview(db, FakeRoutingProvider(), stop_api_ids=[fx.stops["toshkent"].api_id, kitob.api_id], departure_at=datetime.now(timezone.utc))
    assert info.value.code is ErrorCode.CORRIDOR_NOT_ACTIVE


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
    district = fx.district_api_ids["samarqand"]
    region_tk, region_sa = fx.regions["toshkent"].api_id, fx.regions["samarqand"].api_id
    with pg_db.session() as db:
        corridor = service.create_corridor(
            db, actor_user_id=admin, name="Rollout test", origin_region_api_id=region_tk, destination_region_api_id=region_sa,
            search_radius_m=3000, default_max_detour_minutes=10, default_max_detour_m=3000,
        )
        db.commit()
        assert _guard_reason(lambda: _rollout(db, admin, corridor, "active")) == "not_allowed"  # not in CORRIDOR_ROLLOUT
        db.rollback()
        assert _guard_reason(lambda: _rollout(db, admin, corridor, "internal")) == "needs_active_stop"
        db.rollback()

        def add_stop(name: str, **kw) -> service.StopInfo:  # noqa: ANN003
            params = dict(name_ru=None, district_api_id=district, point=LatLng(39.65, 66.96), meeting_note=None, sequence_hint=0, is_active=True)
            params.update(kw)
            stop = service.create_stop(db, actor_user_id=admin, corridor_api_id=corridor.api_id, name_uz=name, **params)
            db.commit()
            return stop

        first = add_stop("Bekat A")
        corridor = _rollout(db, admin, corridor, "internal")
        db.commit()
        assert _guard_reason(lambda: _rollout(db, admin, corridor, "pilot")) == "needs_two_active_stops"
        db.rollback()
        second = add_stop("Bekat B", point=LatLng(39.66, 66.97))
        with pytest.raises(DomainError) as missing:
            _rollout(db, admin, corridor, "pilot")
        assert missing.value.details["reason"] == "stops_missing_meeting_evidence"
        assert missing.value.details["stop_ids"] == [first.api_id, second.api_id]
        db.rollback()
        service.patch_stop(db, actor_user_id=admin, stop_api_id=first.api_id, expected_version=1, changes={"meeting_note": "Yoqilg'i shoxobchasi oldida"})
        service.patch_stop(db, actor_user_id=admin, stop_api_id=second.api_id, expected_version=1, changes={"meeting_note": "Avtobus bekati yonida"})
        db.commit()
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
