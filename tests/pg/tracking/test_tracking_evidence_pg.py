"""M1 (wave 3.1): raw GPS of a disputed trip survives the 7-day raw retention.

Proves on real PostgreSQL: an evidence hold makes the retention job copy the raw points out of the expiring daily
partition; a partition whose held points are not copied yet is skipped instead of dropped; the copy is append-only
and is purged EVIDENCE_RETENTION_AFTER_RELEASE after the hold was released.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.timeutil import utc_now
from app.modules.tracking import jobs
from app.modules.tracking import service as tracking_service
from tests.pg.tracking.conftest import BW, db_constraint, passenger_booking, rows, scalar, start_session

pytestmark = pytest.mark.pg

OLD_DAYS = 9  # older than contracts.tracking.RAW_POINT_RETENTION (7 days)


def _run(bw: BW, fn, **kwargs) -> int:  # noqa: ANN001
    with bw.db.session() as s:
        result = fn(s, **kwargs)
        s.commit()
        return result


def _session_id(bw: BW, trip_id: int) -> int:
    return scalar(bw.db, "SELECT id FROM tracking_sessions WHERE trip_id = :t", t=trip_id)


def _old_partition_with_points(bw: BW, session_id: int, *, count: int = 3) -> str:
    """A partition of an already expired day plus ``count`` points in it (the ingestion API refuses old captures)."""
    day = (utc_now() - timedelta(days=OLD_DAYS)).date()
    name = f"tracking_points_p{day:%Y%m%d}"
    with bw.db.engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {name} PARTITION OF tracking_points "
                          f"FOR VALUES FROM ('{day}') TO ('{day + timedelta(days=1)}')"))
        for seq in range(count):
            conn.execute(
                text(
                    "INSERT INTO tracking_points (captured_date, session_id, seq, captured_at, received_at, point,"
                    " accuracy_m, battery_pct) VALUES (:d, :s, :q, :at, :at, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 10, 80)"
                ),
                {"d": day, "s": session_id, "q": 100 + seq, "at": utc_now() - timedelta(days=OLD_DAYS, seconds=60 - seq),
                 "lng": 69.24 + seq / 1000, "lat": 41.30},
            )
    return name


def _hold(bw: BW, trip_id: int, *, source_id: int = 4242) -> None:
    with bw.db.session() as s:
        tracking_service.hold_trip_evidence(s, trip_id=trip_id, source_id=source_id)
        s.commit()


def test_held_trip_points_are_copied_before_the_partition_is_dropped(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01J120AA")
    start_session(tw, trip_public)
    session_id = _session_id(tw, trip_id)
    partition = _old_partition_with_points(tw, session_id)

    _hold(tw, trip_id)
    assert tracking_service_hold_open(tw, trip_id) is True

    # 1. the hold alone stops the drop: nothing was copied yet, so the expired partition stays
    with tw.db.session() as s:
        assert s.execute(text("SELECT public.tracking_drop_expired_point_partitions()")).scalar_one() == 0
        s.commit()
    assert scalar(tw.db, "SELECT to_regclass(:n)", n=f"public.{partition}") is not None

    # 2. the retention job copies first, then drops
    with tw.db.session() as s:
        assert jobs.copy_evidence_points(s) == 3
        assert jobs.copy_evidence_points(s) == 0  # idempotent
        s.commit()
    with tw.db.session() as s:
        assert s.execute(text("SELECT public.tracking_drop_expired_point_partitions()")).scalar_one() >= 1
        s.commit()
    assert scalar(tw.db, "SELECT to_regclass(:n)", n=f"public.{partition}") is None
    kept = rows(tw.db, "SELECT seq, trip_id, ST_X(point) AS lng FROM tracking_evidence_points ORDER BY seq")
    assert [r.seq for r in kept] == [100, 101, 102] and {r.trip_id for r in kept} == {trip_id}
    assert scalar(tw.db, "SELECT count(*) FROM tracking_points") == 0


def tracking_service_hold_open(bw: BW, trip_id: int) -> bool:
    with bw.db.session() as s:
        return tracking_service.trip_evidence_hold_open(s, trip_id)


def test_evidence_is_append_only_and_purged_after_the_hold_is_released(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01J121AA")
    start_session(tw, trip_public)
    session_id = _session_id(tw, trip_id)
    _old_partition_with_points(tw, session_id, count=2)
    _hold(tw, trip_id)
    assert _run(tw, jobs.copy_evidence_points) == 2

    for statement in ("UPDATE tracking_evidence_points SET accuracy_m = 1", "TRUNCATE tracking_evidence_points"):
        with pytest.raises(DBAPIError) as info:
            with tw.db.engine.begin() as conn:
                conn.exec_driver_sql(statement)
        assert db_constraint(info.value) == "append_only_violation"

    released = utc_now()
    with tw.db.session() as s:
        assert tracking_service.release_trip_evidence(s, trip_id=trip_id, source_id=4242, now=released) is True
        assert tracking_service.release_trip_evidence(s, trip_id=trip_id, source_id=4242, now=released) is False
        s.commit()
    assert tracking_service_hold_open(tw, trip_id) is False

    # still inside the window: nothing is purged
    assert _run(tw, jobs.purge_released_evidence, now=released + timedelta(days=29)) == 0
    # after the window: the points go first and the now-empty hold row with them (2 points + 1 hold)
    assert _run(tw, jobs.purge_released_evidence, now=released + timedelta(days=31)) == 3
    assert _run(tw, jobs.purge_released_evidence, now=released + timedelta(days=31)) == 0
    assert scalar(tw.db, "SELECT count(*) FROM tracking_evidence_points") == 0
    assert scalar(tw.db, "SELECT count(*) FROM tracking_evidence_holds") == 0


def test_hold_is_idempotent_per_source_and_reopens_a_released_hold(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01J122AA")
    start_session(tw, trip_public)
    _hold(tw, trip_id, source_id=7)
    _hold(tw, trip_id, source_id=7)
    assert scalar(tw.db, "SELECT count(*) FROM tracking_evidence_holds WHERE trip_id = :t", t=trip_id) == 1
    with tw.db.session() as s:
        tracking_service.release_trip_evidence(s, trip_id=trip_id, source_id=7)
        s.commit()
    assert tracking_service_hold_open(tw, trip_id) is False
    _hold(tw, trip_id, source_id=7)  # a second dispute with the same id re-opens the same row
    assert scalar(tw.db, "SELECT count(*) FROM tracking_evidence_holds WHERE trip_id = :t", t=trip_id) == 1
    assert tracking_service_hold_open(tw, trip_id) is True
    # a different source is a separate hold: the trip stays held until both are released
    _hold(tw, trip_id, source_id=8)
    with tw.db.session() as s:
        tracking_service.release_trip_evidence(s, trip_id=trip_id, source_id=7)
        s.commit()
    assert tracking_service_hold_open(tw, trip_id) is True


def test_new_partition_inherits_the_parent_acl(tw: BW) -> None:
    """0063: a privilege revoked on tracking_points is revoked on every partition created afterwards."""
    day = (utc_now() + timedelta(days=5)).date()
    name = f"tracking_points_p{day:%Y%m%d}"
    role = "elchi_acl_probe"
    with tw.db.engine.begin() as conn:
        conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        conn.execute(text(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS'))
        conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON tracking_points TO "{role}"'))
        conn.execute(text(f'REVOKE UPDATE, DELETE ON tracking_points FROM "{role}"'))  # append-only class
    try:
        with tw.db.engine.begin() as conn:
            assert conn.execute(text("SELECT public.tracking_ensure_point_partition(:d)"), {"d": day}).scalar_one() is True
        privileges = rows(
            tw.db,
            "SELECT has_table_privilege(:r, :t, 'INSERT') AS can_insert, has_table_privilege(:r, :t, 'UPDATE') AS can_update,"
            " has_table_privilege(:r, :t, 'DELETE') AS can_delete, has_table_privilege(:r, :t, 'SELECT') AS can_select",
            r=role, t=f"public.{name}",
        )[0]
        assert (privileges.can_insert, privileges.can_update, privileges.can_delete) == (True, False, False)
        assert privileges.can_select is True
    finally:
        with tw.db.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
