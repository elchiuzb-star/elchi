"""K1-K3 on PostgreSQL: AC27, AC28, AC29, AC38, D16, DB guards, A4 trip-terminal hook."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import TrackingFreshness
from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity import service as identity_service
from app.modules.platform.service import run_with_db_retry
from app.modules.tracking import service as tracking_service
from app.modules.tracking.models import TrackingSession
from tests.pg.harness import run_concurrently
from tests.pg.tracking.conftest import (
    BW,
    db_constraint,
    domain_error,
    passenger_booking,
    point,
    rows,
    run_trip_action,
    scalar,
    send,
    set_flag,
    start_session,
)

pytestmark = pytest.mark.pg


def _sid(bw: BW, public: str) -> int:
    with bw.db.session() as s:
        return tracking_service._session_by_public_id(s, public).id


def test_ac29_new_session_supersedes_and_old_writer_gets_409(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01T100AA")
    now = tw.base - timedelta(minutes=10)
    old = start_session(tw, trip_public, now=now - timedelta(minutes=5))
    assert send(tw, old, [point(0, now - timedelta(seconds=5))], now=now).accepted_seqs == [0]
    new = start_session(tw, trip_public, now=now, device="dev-2")
    statuses = dict(rows(tw.db, "SELECT public_id::text, status FROM tracking_sessions WHERE trip_id = :t", t=trip_id))
    assert sorted(statuses.values()) == ["active", "superseded"]
    err = domain_error(lambda: send(tw, old, [point(1, now)], now=now))
    assert err.code is ErrorCode.TRACKING_SESSION_SUPERSEDED and err.http_status == 409
    assert send(tw, new, [point(0, now)], now=now).session_status.value == "active"
    # DB guard: a raw insert for the superseded session is refused with the contract constraint name
    with pytest.raises(DBAPIError) as info:
        with tw.db.engine.begin() as conn:
            conn.execute(text("INSERT INTO tracking_point_receipts (session_id, seq, captured_date, payload_hash, received_at) "
                              "VALUES (:s, 99, current_date, repeat('a', 64), now())"), {"s": _sid(tw, old)})
    assert db_constraint(info.value) == "tracking_session_superseded"


def test_concurrent_session_creation_leaves_exactly_one_active(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01T101AA")
    now = tw.base - timedelta(minutes=10)

    def worker(index: int, s) -> str:  # noqa: ANN001
        def attempt() -> str:  # same retry wrapper as the v2 runner (run_command)
            row = tracking_service.create_session(s, actor_user_id=tw.w.driver_id, trip_public_id=trip_public,
                                                  device_id=f"d{index}", platform="android", app_version="2", now=now)
            public = tracking_service.session_public_id(row)
            s.commit()
            return public

        return run_with_db_retry(s, attempt)

    report = run_concurrently(6, worker, engine=tw.db.engine)
    assert not report.failures, [r.error for r in report.failures]
    assert scalar(tw.db, "SELECT count(*) FROM tracking_sessions WHERE trip_id = :t AND status = 'active'", t=trip_id) == 1
    assert scalar(tw.db, "SELECT count(*) FROM tracking_sessions WHERE trip_id = :t", t=trip_id) == 6


def test_ac28_old_and_mock_points_never_move_the_marker(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01T102AA")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    send(tw, sid, [point(5, now, lat=41.3010)], now=now)
    ack = send(tw, sid, [point(3, now - timedelta(seconds=40), lat=41.2000), point(6, now + timedelta(seconds=10), lat=41.5, mock=True)],
               now=now + timedelta(seconds=11))
    assert ack.accepted_seqs == [3, 6]
    flags = dict(rows(tw.db, "SELECT seq, quality_flags FROM tracking_points WHERE session_id = :s", s=_sid(tw, sid)))
    assert flags[3] == ["out_of_order"] and flags[6] == ["mock_location"] and flags[5] == []
    with tw.db.session() as s:
        live = tracking_service._trip_live_point(s, trip_id)
    assert live.captured_at == now and abs(live.lat - 41.3010) < 1e-9  # marker neither went back nor to the mock point
    assert scalar(tw.db, "SELECT last_seq FROM tracking_sessions WHERE public_id IS NOT NULL AND trip_id = :t", t=trip_id) == 6
    with pytest.raises(DBAPIError):  # DB: live point cannot move backwards
        with tw.db.engine.begin() as conn:
            conn.execute(text("UPDATE tracking_sessions SET last_captured_at = last_captured_at - interval '1 minute' WHERE trip_id = :t"),
                         {"t": trip_id})


def test_duplicate_seq_is_one_row_and_changed_payload_conflicts(tw: BW) -> None:
    _, trip_public, _ = passenger_booking(tw, "01T103AA")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    first = send(tw, sid, [point(1, now), point(1, now)], now=now)
    assert first.accepted_seqs == [1] and first.duplicate_seqs == [1]
    retry = send(tw, sid, [point(1, now), point(1, now, lat=41.9)], now=now + timedelta(seconds=5))
    assert retry.accepted_seqs == [] and retry.duplicate_seqs == [1]
    assert [(r.seq, r.reason.value) for r in retry.rejected] == [(1, "payload_conflict")]
    assert scalar(tw.db, "SELECT count(*) FROM tracking_points WHERE session_id = :s", s=_sid(tw, sid)) == 1
    assert scalar(tw.db, "SELECT count(*) FROM tracking_point_receipts WHERE session_id = :s", s=_sid(tw, sid)) == 1


def test_ac27_gap_turns_lost_then_new_batch_is_fresh_in_order(tw: BW) -> None:
    trip_id, trip_public, booking = passenger_booking(tw, "01T104AA")
    t0 = tw.base - timedelta(minutes=25)
    sid = start_session(tw, trip_public, now=t0 - timedelta(minutes=1))
    send(tw, sid, [point(0, t0), point(1, t0 + timedelta(seconds=10), lat=41.3005)], now=t0 + timedelta(seconds=11))
    with tw.db.session() as s:
        assert tracking_service.trip_tracking_summary(s, trip_id, now=t0 + timedelta(seconds=20)).freshness is TrackingFreshness.FRESH
        assert tracking_service.trip_tracking_summary(s, trip_id, now=t0 + timedelta(seconds=90)).freshness is TrackingFreshness.DELAYED
        gap = tracking_service.booking_live_state(s, booking.id, now=t0 + timedelta(minutes=5, seconds=10))
        assert gap.freshness is TrackingFreshness.LOST and gap.window.is_open
    later = t0 + timedelta(minutes=5, seconds=10)
    # the phone queued points during the gap and sends them with a new one
    queued = [point(4, later - timedelta(seconds=2), lat=41.3040), point(2, later - timedelta(minutes=4), lat=41.3010),
              point(3, later - timedelta(minutes=2), lat=41.3025)]
    assert send(tw, sid, queued, now=later).accepted_seqs == [2, 3, 4]
    with tw.db.session() as s:
        summary = tracking_service.trip_tracking_summary(s, trip_id, now=later)
    assert summary.freshness is TrackingFreshness.FRESH and summary.active_session
    ordered = [r.seq for r in rows(tw.db, "SELECT seq FROM tracking_points WHERE session_id = :s ORDER BY captured_at", s=_sid(tw, sid))]
    assert ordered == [0, 1, 2, 3, 4]
    assert not any(r.quality_flags for r in rows(tw.db, "SELECT quality_flags FROM tracking_points WHERE session_id = :s", s=_sid(tw, sid)))


def test_rejections_batch_limit_and_ownership(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01T105AA")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    ack = send(tw, sid, [point(1, now - timedelta(hours=25)), point(2, now + timedelta(seconds=120)), point(3, now)], now=now)
    assert ack.accepted_seqs == [3] and {(r.seq, r.reason.value) for r in ack.rejected} == {(1, "too_old"), (2, "future_timestamp")}
    too_many = [point(i, now) for i in range(101)]
    err = domain_error(lambda: send(tw, sid, too_many, now=now))
    assert err.code is ErrorCode.TRACKING_BATCH_TOO_LARGE and err.http_status == 400
    assert domain_error(lambda: send(tw, sid, [point(9, now)], now=now, driver_id=tw.w.driver2_id)).code is ErrorCode.NOT_FOUND
    assert domain_error(lambda: start_session(tw, trip_public, driver_id=tw.w.driver2_id)).code is ErrorCode.NOT_FOUND


def test_session_needs_running_trip(tw: BW) -> None:
    _, trip_public, _ = passenger_booking(tw, "01T106AA", boarding=False)
    err = domain_error(lambda: start_session(tw, trip_public))
    assert err.code is ErrorCode.INVALID_STATE_TRANSITION and err.details["trip_status"] == "planned"


def test_d16_blocked_driver_still_publishes_on_active_trip(tw: BW) -> None:
    _, trip_public, _ = passenger_booking(tw, "01T107AA")
    with tw.db.session() as s:
        version = identity_service.eligibility_version(s, tw.w.driver_id)
        identity_service.block_driver_eligibility(s, driver_user_id=tw.w.driver_id, actor_user_id=tw.w.admin_id,
                                                  expected_version=version, reason="document check")
        s.commit()
        assert not identity_service.get_capabilities(s, tw.w.driver_id).driver_eligible
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    assert send(tw, sid, [point(0, now)], now=now).accepted_seqs == [0]


def test_ac38_flag_off_refuses_only_trips_without_a_session(tw: BW) -> None:
    _, first_trip, _ = passenger_booking(tw, "01T108AA")
    now = tw.base - timedelta(minutes=10)
    started = start_session(tw, first_trip)
    set_flag(tw.db, "tracking_enabled", False)
    _, fresh_trip, _ = passenger_booking(tw, "01T109AA", client_id=tw.w.client2_id, driver_id=tw.w.driver2_id)
    err = domain_error(lambda: start_session(tw, fresh_trip, driver_id=tw.w.driver2_id))
    assert err.code is ErrorCode.FEATURE_DISABLED and err.http_status == 403
    assert send(tw, started, [point(0, now)], now=now).accepted_seqs == [0]  # the running trip continues
    restarted = start_session(tw, first_trip, device="rebooted")  # app restart on a started trip
    assert send(tw, restarted, [point(1, now + timedelta(seconds=5))], now=now + timedelta(seconds=6)).accepted_seqs == [1]


def test_trip_cancel_closes_sessions_via_a4_hook_and_k2_409(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01T110AA")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    send(tw, sid, [point(0, now)], now=now)
    run_trip_action(tw, trip_id, tw.w.driver_id, "cancel", now=now + timedelta(minutes=1), reason="car broke down")
    assert scalar(tw.db, "SELECT status FROM tracking_sessions WHERE trip_id = :t", t=trip_id) == "closed"
    err = domain_error(lambda: send(tw, sid, [point(1, now + timedelta(minutes=2))], now=now + timedelta(minutes=2)))
    assert err.code is ErrorCode.TRACKING_SESSION_CLOSED and err.http_status == 409
    assert domain_error(lambda: start_session(tw, trip_public)).code is ErrorCode.INVALID_STATE_TRANSITION
    with pytest.raises(DBAPIError) as info:
        with tw.db.engine.begin() as conn:
            conn.execute(text("INSERT INTO tracking_point_receipts (session_id, seq, captured_date, payload_hash, received_at) "
                              "VALUES (:s, 50, current_date, repeat('b', 64), now())"), {"s": _sid(tw, sid)})
    assert db_constraint(info.value) == "tracking_session_closed"


def test_close_sessions_for_trip_export_and_k3(tw: BW) -> None:
    trip_id, trip_public, _ = passenger_booking(tw, "01T111AA")
    sid = start_session(tw, trip_public)
    with tw.db.session() as s:
        closed = tracking_service.close_session(s, actor_user_id=tw.w.driver_id, session_public_id_value=sid)
        assert closed.status == "closed" and closed.ended_at is not None
        s.commit()
        again = tracking_service.close_session(s, actor_user_id=tw.w.driver_id, session_public_id_value=sid)
        assert again.status == "closed"
        s.commit()
    start_session(tw, trip_public, device="dev-3")
    with tw.db.session() as s:
        assert tracking_service.close_sessions_for_trip(s, trip_id, now=tw.base) == 1
        assert tracking_service.close_sessions_for_trip(s, trip_id, now=tw.base) == 0
        s.commit()
    with pytest.raises(DBAPIError) as info:  # closed session is frozen
        with tw.db.engine.begin() as conn:
            conn.execute(text("UPDATE tracking_sessions SET status = 'active', ended_at = NULL WHERE trip_id = :t"), {"t": trip_id})
    assert db_constraint(info.value) == "tracking_session_closed"


def test_history_rows_are_append_only(tw: BW) -> None:
    _, trip_public, _ = passenger_booking(tw, "01T112AA")
    now = tw.base - timedelta(minutes=10)
    sid = start_session(tw, trip_public)
    send(tw, sid, [point(0, now)], now=now)
    for statement in ("UPDATE tracking_point_receipts SET payload_hash = repeat('c', 64)",
                      "UPDATE tracking_points SET accuracy_m = 1",
                      "DELETE FROM tracking_sessions"):
        with pytest.raises(DBAPIError) as info:
            with tw.db.engine.begin() as conn:
                conn.execute(text(statement))
        assert db_constraint(info.value) == "append_only_violation", statement
    with tw.db.session() as s:
        assert s.query(TrackingSession).count() == 1
