"""Q42 corridor price bands on PostgreSQL, and the N4 routing cache cleanup job (wave 1.6)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.contracts.enums import ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import new_public_uuid
from app.modules.geo import service
from app.modules.geo.jobs import ROUTING_CACHE_CLEANUP_LOCK_KEY, cleanup_routing_cache, routing_cache_cleanup_task
from app.modules.geo.types import LatLng
from tests.fixtures.geo.loader import load_geo_fixture
from tests.pg.conftest import PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg


@pytest.fixture
def geo(pg_db: PgDatabase):  # noqa: ANN201
    admin = create_user(pg_db, "admin")
    with pg_db.session() as db:
        fx = load_geo_fixture(db, actor_user_id=admin, with_routes=False)
    return pg_db, fx, admin


def set_band(db, fx, admin, *, service_type=ServiceType.PASSENGER, origin=None, dest=None, floor=10_000, ceiling=50_000, active=True, version=None, reason="pilot pricing"):  # noqa: ANN001, ANN201
    return service.set_price_band(
        db,
        actor_user_id=admin,
        corridor_api_id=fx.corridor.api_id,
        service_type=service_type,
        origin_stop_api_id=fx.stops[origin].api_id if origin else None,
        destination_stop_api_id=fx.stops[dest].api_id if dest else None,
        floor_minor=floor,
        ceiling_minor=ceiling,
        is_active=active,
        reason=reason,
        expected_version=version,
    )


def resolve(db, fx, origin: str, dest: str, service_type=ServiceType.PASSENGER):  # noqa: ANN001, ANN201
    return service.resolve_price_band(
        db, corridor_id=fx.corridor.id, service_type=service_type, origin_stop_id=fx.stop_id(origin), destination_stop_id=fx.stop_id(dest)
    )


def test_resolution_precedence_versioning_and_history(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    with pg_db.session() as db:
        assert resolve(db, fx, "toshkent", "qarshi") is None  # no band configured -> no limit
        corridor_band = set_band(db, fx, admin)
        segment = set_band(db, fx, admin, origin="toshkent", dest="qarshi", floor=20_000, ceiling=30_000)
        db.commit()
        assert (corridor_band.version, segment.version) == (1, 1)
        picked = resolve(db, fx, "toshkent", "qarshi")
        assert picked.scope == "segment" and (picked.floor_minor, picked.ceiling_minor) == (20_000, 30_000)
        assert resolve(db, fx, "samarqand", "qarshi").scope == "corridor"
        assert resolve(db, fx, "qarshi", "toshkent").scope == "corridor"  # reverse is another segment
        assert resolve(db, fx, "toshkent", "qarshi", ServiceType.PARCEL) is None

        updated = set_band(db, fx, admin, origin="toshkent", dest="qarshi", floor=20_000, ceiling=30_000, active=False, version=1, reason="retire")
        db.commit()
        assert updated.version == 2 and not updated.is_active
        assert resolve(db, fx, "toshkent", "qarshi").scope == "corridor"
        parcel = set_band(db, fx, admin, service_type=ServiceType.PARCEL, floor=40_000, ceiling=90_000)
        db.commit()
        assert parcel.price_basis.value == "total"
        assert [(b.service_type.value, b.origin_stop_id is not None) for b in service.list_price_bands(db, fx.corridor)] == [
            ("parcel", False), ("passenger", False), ("passenger", True)
        ]
        history, _ = service.list_price_band_history(db, corridor=fx.corridor, after_id=None, limit=10)
    assert [(h.service_type.value, h.band_version, h.old_is_active, h.new_is_active, h.reason) for h in history] == [
        ("parcel", 1, None, True, "pilot pricing"),
        ("passenger", 2, True, False, "retire"),
        ("passenger", 1, None, True, "pilot pricing"),
        ("passenger", 1, None, True, "pilot pricing"),
    ]
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM audit_logs WHERE entity_type = 'corridor_price_band'")) == 4


def test_validation_and_version_conflicts(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    with pg_db.session() as db:
        other = service.create_corridor(
            db, actor_user_id=admin, name="Boshqa koridor", origin_region_api_id=fx.regions["toshkent"].api_id,
            destination_region_api_id=fx.regions["samarqand"].api_id, search_radius_m=3000, default_max_detour_minutes=10, default_max_detour_m=1000,
        )
        foreign = service.create_stop(
            db, actor_user_id=admin, corridor_api_id=other.api_id, name_uz="Begona", name_ru=None,
            district_api_id=fx.district_api_ids["samarqand"], point=LatLng(39.6, 66.9), meeting_note="x", sequence_hint=0, is_active=True,
        )
        db.commit()

        def invalid(**kw) -> tuple[str, str]:  # noqa: ANN003
            params = dict(
                actor_user_id=admin, corridor_api_id=fx.corridor.api_id, service_type=ServiceType.PASSENGER, origin_stop_api_id=None,
                destination_stop_api_id=None, floor_minor=10, ceiling_minor=20, is_active=True, reason="r",
            )
            params.update(kw)
            with pytest.raises(DomainError) as info:
                service.set_price_band(db, **params)
            db.rollback()
            return info.value.code.value, (info.value.details or {}).get("reason")

        assert invalid(floor_minor=21) == ("VALIDATION_ERROR", "floor_above_ceiling")
        assert invalid(floor_minor=0) == ("VALIDATION_ERROR", "positive_integer_required")
        assert invalid(origin_stop_api_id=fx.stops["toshkent"].api_id) == ("VALIDATION_ERROR", "segment_needs_both_stops")
        assert invalid(origin_stop_api_id=fx.stops["toshkent"].api_id, destination_stop_api_id=fx.stops["toshkent"].api_id) == ("VALIDATION_ERROR", "same_stop")
        assert invalid(origin_stop_api_id=fx.stops["toshkent"].api_id, destination_stop_api_id=foreign.api_id) == ("VALIDATION_ERROR", "stop_not_in_corridor")
        assert invalid(expected_version=1) == ("VERSION_CONFLICT", None)
        set_band(db, fx, admin)
        db.commit()
        assert invalid() == ("VERSION_CONFLICT", None)
        assert invalid(expected_version=2) == ("VERSION_CONFLICT", None)


def test_db_constraints_immutability_and_append_only(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo
    insert = text(
        "INSERT INTO corridor_price_bands (public_id, corridor_id, service_type, price_basis, origin_stop_id, destination_stop_id, floor_minor, ceiling_minor, reason, updated_by) "
        "VALUES (:p, :c, :s, :b, :o, :d, :f, :ce, 'r', :u)"
    )
    base = {"c": fx.corridor.id, "s": "passenger", "b": "per_seat", "o": None, "d": None, "f": 10, "ce": 20, "u": admin}
    for overrides, message in (
        ({"f": 30}, "ck_corridor_price_bands_amounts"),
        ({"f": 0}, "ck_corridor_price_bands_amounts"),
        ({"b": "total"}, "ck_corridor_price_bands_price_basis"),
        ({"o": fx.stop_id("toshkent")}, "ck_corridor_price_bands_segment"),
    ):
        with pytest.raises(IntegrityError, match=message):
            with pg_db.engine.begin() as conn:
                conn.execute(insert, {**base, **overrides, "p": new_public_uuid()})
    with pg_db.session() as db:
        other = service.create_corridor(
            db, actor_user_id=admin, name="Begona koridor", origin_region_api_id=fx.regions["toshkent"].api_id,
            destination_region_api_id=fx.regions["samarqand"].api_id, search_radius_m=3000, default_max_detour_minutes=10, default_max_detour_m=1000,
        )
        foreign = service.create_stop(
            db, actor_user_id=admin, corridor_api_id=other.api_id, name_uz="Begona", name_ru=None,
            district_api_id=fx.district_api_ids["samarqand"], point=LatLng(39.6, 66.9), meeting_note="x", sequence_hint=0, is_active=True,
        )
        db.commit()
    with pytest.raises(DBAPIError, match="must belong to the corridor"):
        with pg_db.engine.begin() as conn:
            conn.execute(insert, {**base, "o": fx.stop_id("toshkent"), "d": foreign.id, "p": new_public_uuid()})
    with pg_db.engine.begin() as conn:
        conn.execute(insert, {**base, "p": new_public_uuid()})
        band_id = conn.scalar(text("SELECT id FROM corridor_price_bands WHERE corridor_id = :c"), {"c": fx.corridor.id})
    with pytest.raises(IntegrityError, match="ix_corridor_price_bands_corridor_scope"):
        with pg_db.engine.begin() as conn:
            conn.execute(insert, {**base, "p": new_public_uuid()})
    for statement, message in (
        ("UPDATE corridor_price_bands SET floor_minor = 11 WHERE id = :id", "exactly 1"),
        ("UPDATE corridor_price_bands SET service_type = 'parcel', price_basis = 'total', version = version + 1 WHERE id = :id", "immutable"),
        ("DELETE FROM corridor_price_bands WHERE id = :id", "cannot be deleted"),
        ("UPDATE corridor_price_band_changes SET reason = 'x' WHERE band_id = :id", "append-only"),
        ("DELETE FROM corridor_price_band_changes WHERE band_id = :id", "append-only"),
    ):
        with pytest.raises(DBAPIError, match=message):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"id": band_id})


def test_concurrent_first_write_and_concurrent_edits(geo) -> None:  # noqa: ANN001
    pg_db, fx, admin = geo

    def create(worker: int, session) -> int:  # noqa: ANN001
        info = set_band(session, fx, admin, origin="samarqand", dest="qarshi", floor=10_000 + worker, ceiling=60_000)
        session.commit()
        return info.id

    report = run_concurrently(8, create, engine=pg_db.engine)
    assert len(report.successes) == 1
    assert len(report.errors_of(DomainError)) == 7 and all(r.error.code is ErrorCode.VERSION_CONFLICT for r in report.errors_of(DomainError))

    def edit(worker: int, session) -> int:  # noqa: ANN001
        info = set_band(session, fx, admin, origin="samarqand", dest="qarshi", floor=20_000 + worker, ceiling=60_000, version=1, reason=f"edit {worker}")
        session.commit()
        return info.version

    edits = run_concurrently(8, edit, engine=pg_db.engine)
    assert edits.values() == [2]
    assert len(edits.errors_of(DomainError)) == 7
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT version FROM corridor_price_bands WHERE corridor_id = :c"), {"c": fx.corridor.id}) == 2
        assert conn.scalar(text("SELECT count(*) FROM corridor_price_band_changes WHERE corridor_id = :c"), {"c": fx.corridor.id}) == 2


# --- N4: routing cache cleanup ------------------------------------------------------------------------


def _insert_cache(pg_db: PgDatabase, *, expired: int, fresh: int) -> None:
    with pg_db.engine.begin() as conn:
        for i in range(expired):
            conn.execute(
                text("INSERT INTO routing_cache (provider, request_hash, response, created_at, expires_at) VALUES ('fake', :h, '{}'::jsonb, now() - interval '2 hours', now() - interval '1 hour')"),
                {"h": f"e{i:063d}"},
            )
        for i in range(fresh):
            conn.execute(
                text("INSERT INTO routing_cache (provider, request_hash, response, expires_at) VALUES ('fake', :h, '{}'::jsonb, now() + interval '1 hour')"),
                {"h": f"f{i:063d}"},
            )


def _cache_rows(pg_db: PgDatabase) -> int:
    with pg_db.engine.connect() as conn:
        return conn.scalar(text("SELECT count(*) FROM routing_cache"))


def test_routing_cache_cleanup_deletes_expired_rows_in_batches(pg_db: PgDatabase) -> None:
    _insert_cache(pg_db, expired=7, fresh=2)
    assert cleanup_routing_cache(engine=pg_db.engine, batch_size=3) == 7
    assert _cache_rows(pg_db) == 2
    assert cleanup_routing_cache(engine=pg_db.engine, batch_size=3) == 0
    assert cleanup_routing_cache(engine=pg_db.engine, batch_size=2, max_batches=1) == 0


def test_routing_cache_cleanup_task_runs_under_worker_lock(pg_db: PgDatabase) -> None:
    from app.worker import advisory_lock_key

    _insert_cache(pg_db, expired=3, fresh=0)
    with pg_db.engine.connect() as holder:
        assert holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": advisory_lock_key(ROUTING_CACHE_CLEANUP_LOCK_KEY)}).scalar()
        holder.commit()
        assert routing_cache_cleanup_task(engine=pg_db.engine) == 0  # another replica holds the lock
        assert _cache_rows(pg_db) == 3
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": advisory_lock_key(ROUTING_CACHE_CLEANUP_LOCK_KEY)})
        holder.commit()
    assert routing_cache_cleanup_task(engine=pg_db.engine) == 3
    assert _cache_rows(pg_db) == 0
