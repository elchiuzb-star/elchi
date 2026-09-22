"""Worker functions, partitions (Q71), retention, ORM drift and migration idempotency."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import EventType
from app.contracts.timeutil import utc_now
from app.modules.tracking import jobs
from tests.pg.conftest import PgDatabase, run_alembic, script_heads
from tests.pg.tracking.conftest import BW, passenger_booking, point, rows, run_trip_action, scalar, send, start_session

pytestmark = pytest.mark.pg


def _run(bw: BW, fn, **kwargs) -> int:  # noqa: ANN001
    with bw.db.session() as s:
        result = fn(s, **kwargs)
        s.commit()
        return result


def test_stale_signal_once_per_episode_without_coordinates(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01J100AA")
    t0 = tw.base - timedelta(minutes=20)
    sid = start_session(tw, trip_public, now=t0 - timedelta(seconds=10))
    assert _run(tw, jobs.emit_stale_signals, now=t0 + timedelta(minutes=3)) == 1  # started, never delivered a point
    send(tw, sid, [point(0, t0 + timedelta(minutes=3))], now=t0 + timedelta(minutes=3, seconds=1))
    assert _run(tw, jobs.emit_stale_signals, now=t0 + timedelta(minutes=3, seconds=30)) == 0  # fresh
    assert _run(tw, jobs.emit_stale_signals, now=t0 + timedelta(minutes=6)) == 1  # lost
    assert _run(tw, jobs.emit_stale_signals, now=t0 + timedelta(minutes=7)) == 0  # same episode
    send(tw, sid, [point(1, t0 + timedelta(minutes=8))], now=t0 + timedelta(minutes=8))
    assert _run(tw, jobs.emit_stale_signals, now=t0 + timedelta(minutes=11)) == 1  # new episode
    events = rows(tw.db, "SELECT payload FROM outbox_events WHERE event_type = :e ORDER BY id", e=EventType.TRACKING_STALE.value)
    assert [e.payload["freshness"] for e in events] == ["no_data", "lost", "lost"]
    assert all(set(e.payload) == {"trip_id", "freshness", "last_captured_at"} for e in events)


def test_window_opened_signal_once_per_booking(tw: BW) -> None:
    _, _, booking = passenger_booking(tw, "01J101AA")
    assert _run(tw, jobs.emit_window_opened_signals, now=tw.base - timedelta(hours=2)) == 0
    assert _run(tw, jobs.emit_window_opened_signals, now=tw.base - timedelta(minutes=29)) == 1
    assert _run(tw, jobs.emit_window_opened_signals, now=tw.base - timedelta(minutes=20)) == 0
    payload = scalar(tw.db, "SELECT payload FROM outbox_events WHERE event_type = :e", e=EventType.TRACKING_WINDOW_OPENED.value)
    assert set(payload) == {"booking_id", "trip_id", "service_type", "opens_at"} and payload["service_type"] == "passenger"


def test_partition_function_runs_as_app_role_which_owns_nothing(pg_db: PgDatabase) -> None:
    role = f"elchi_app_t{uuid.uuid4().hex[:8]}"
    day_sql = "(now() AT TIME ZONE 'UTC')::date + 10"
    with pg_db.engine.begin() as conn:
        conn.execute(text(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS'))
        conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
    try:
        with pytest.raises(DBAPIError, match="permission denied"):  # EXECUTE revoked from PUBLIC
            with pg_db.engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{role}"'))
                conn.execute(text(f"SELECT public.tracking_ensure_point_partition({day_sql})"))
        with pg_db.engine.begin() as conn:
            conn.execute(text(f'GRANT EXECUTE ON FUNCTION public.tracking_ensure_point_partition(DATE), '
                              f'public.tracking_ensure_point_partitions(), public.tracking_drop_expired_point_partitions() TO "{role}"'))
        with pg_db.engine.begin() as conn:
            conn.execute(text(f'SET LOCAL ROLE "{role}"'))
            assert conn.execute(text(f"SELECT public.tracking_ensure_point_partition({day_sql})")).scalar_one() is True
            assert conn.execute(text(f"SELECT public.tracking_ensure_point_partition({day_sql})")).scalar_one() is False
            conn.execute(text("SELECT public.tracking_ensure_point_partitions()"))
            conn.execute(text("SELECT public.tracking_drop_expired_point_partitions()"))
            with pytest.raises(DBAPIError, match="outside the allowed range"):
                with conn.begin_nested():
                    conn.execute(text("SELECT public.tracking_ensure_point_partition((now() AT TIME ZONE 'UTC')::date + 400)"))
        with pg_db.engine.connect() as conn:
            owned = conn.execute(text("SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner WHERE r.rolname = :r"),
                                 {"r": role}).scalar_one()
            assert owned == 0
            assert conn.execute(text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'tracking_points'::regclass")).scalar_one() >= 6
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


def test_default_partition_rows_move_and_expired_partitions_drop(tw: BW) -> None:
    _, trip_public, _ = passenger_booking(tw, "01J102AA")
    sid = start_session(tw, trip_public)
    far = utc_now().replace(microsecond=0) + timedelta(days=6)
    send(tw, sid, [point(0, far), point(1, far + timedelta(seconds=10))], now=far + timedelta(seconds=11))
    assert {r[0] for r in rows(tw.db, "SELECT tableoid::regclass::text FROM tracking_points")} == {"tracking_points_default"}
    day = far.date()
    with tw.db.engine.begin() as conn:
        assert conn.execute(text("SELECT public.tracking_ensure_point_partition(:d)"), {"d": day}).scalar_one() is True
    assert {r[0] for r in rows(tw.db, "SELECT tableoid::regclass::text FROM tracking_points")} == {f"tracking_points_p{day:%Y%m%d}"}
    old = (utc_now() - timedelta(days=9)).date()
    with tw.db.engine.begin() as conn:  # an old partition (as if created 9 days ago)
        conn.execute(text(f"CREATE TABLE tracking_points_p{old:%Y%m%d} PARTITION OF tracking_points "
                          f"FOR VALUES FROM ('{old}') TO ('{old + timedelta(days=1)}')"))
    with tw.db.session() as s:
        assert jobs.run_retention(s) >= 1
        s.commit()
    assert scalar(tw.db, "SELECT to_regclass(:n)", n=f"public.tracking_points_p{old:%Y%m%d}") is None
    assert scalar(tw.db, "SELECT count(*) FROM tracking_points") == 2


def test_retention_builds_simplified_track_from_trusted_points_and_purges_receipts(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01J103AA")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    send(tw, sid, [point(0, now, lat=41.3000), point(1, now + timedelta(seconds=10), lat=41.3020),
                   point(2, now + timedelta(seconds=20), lat=41.3040), point(3, now + timedelta(seconds=25), lat=45.0, mock=True)],
         now=now + timedelta(seconds=30))
    run_trip_action(tw, trip_id, tw.w.driver_id, "cancel", now=now + timedelta(minutes=1), reason="test")
    assert _run(tw, jobs.build_simplified_tracks, now=now + timedelta(hours=1)) == 1
    assert _run(tw, jobs.build_simplified_tracks, now=now + timedelta(hours=1)) == 0
    track = rows(tw.db, "SELECT point_count, ST_YMax(geometry) AS ymax FROM tracking_track_simplified WHERE trip_id = :t", t=trip_id)[0]
    assert track.point_count == 3 and track.ymax < 41.31  # the mock point is not in the track
    assert _run(tw, jobs.purge_expired_rows, now=now + timedelta(days=9)) == 4
    assert _run(tw, jobs.purge_expired_rows, now=now + timedelta(days=31)) == 1


def test_tracking_models_match_migrated_schema(pg_db: PgDatabase) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from sqlalchemy.types import UserDefinedType

    import app.models  # noqa: F401
    import app.modules.tracking.models  # noqa: F401
    from app.db.base import Base
    from app.modules.tracking.models import TRACKING_TABLES

    def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
        if type_ == "table" and reflected and compare_to is None:
            return name in Base.metadata.tables
        return True

    # Same technique as tests/pg/test_migrations_smoke.py::_compare_with_postgis_types, but geometry columns of
    # partitioned tables (relkind 'p', tracking_points) are included - the shared helper reads relkind 'r' only.
    class _ReflectedPostgis(UserDefinedType):
        cache_ok = True

        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            super().__init__()

        def get_col_spec(self, **_kw) -> str:  # noqa: ANN003
            return "postgis"

    def normalize(spec: str) -> str:
        return spec.replace(" ", "").replace('"', "").lower()

    with pg_db.engine.connect() as conn:
        actual = {
            (table, column): normalize(spec)
            for table, column, spec in conn.execute(text(
                "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_type t ON t.oid = a.atttypid WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                "AND a.attnum > 0 AND NOT a.attisdropped AND t.typname IN ('geometry', 'geography')"
            ))
        }

        def compare_type(_ctx, inspected_column, metadata_column, inspected_type, metadata_type):  # noqa: ANN001, ANN202
            key = (metadata_column.table.name, metadata_column.name)
            expected = normalize(metadata_type.compile(dialect=conn.dialect))
            if key in actual or expected.startswith(("geometry", "geography")):
                return actual.get(key) != expected
            return None

        names = conn.dialect.ischema_names
        saved = {name: names.get(name) for name in ("geometry", "geography")}
        names.update({"geometry": _ReflectedPostgis, "geography": _ReflectedPostgis})
        try:
            context = MigrationContext.configure(
                conn, opts={"include_object": include_object, "compare_type": compare_type, "compare_server_default": False}
            )
            diffs = compare_metadata(context, Base.metadata)
        finally:
            for name, value in saved.items():
                if value is None:
                    names.pop(name, None)
                else:
                    names[name] = value

    def touches(diff: object) -> bool:
        for item in diff if isinstance(diff, list) else [diff]:
            for part in item:
                table = getattr(part, "table", None)
                name = getattr(table, "name", None) or getattr(part, "name", None)
                if name in TRACKING_TABLES or part in TRACKING_TABLES:
                    return True
        return False

    ours = [diff for diff in diffs if touches(diff)]
    assert ours == [], "\n".join(map(repr, ours))


def test_0058_upgrade_is_idempotent(pg_db: PgDatabase) -> None:
    heads = script_heads()
    assert len(heads) == 1

    def snapshot() -> tuple:
        with pg_db.engine.connect() as conn:
            return (
                conn.execute(text("SELECT table_name, column_name, data_type FROM information_schema.columns "
                                  "WHERE table_schema = 'public' AND table_name LIKE 'tracking%' ORDER BY 1, 2")).all(),
                conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename LIKE 'tracking%' ORDER BY 1")).all(),
                conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1")).all(),
                conn.execute(text("SELECT conname FROM pg_constraint ORDER BY 1")).all(),
                conn.execute(text("SELECT proname, prosecdef FROM pg_proc WHERE proname LIKE 'tracking%' ORDER BY 1")).all(),
            )

    before = snapshot()
    # 0058: 3 SECURITY DEFINER partition functions + 3 guards; 0063 (wave 3.1): the ACL helper + the evidence guard
    assert [r for r in before[4] if r.prosecdef] and len(before[4]) == 8
    for args in (("stamp", "20260915_0057"), ("upgrade", "20260916_0058"), ("stamp", heads[0])):
        result = run_alembic(pg_db.url, *args)
        assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot() == before
