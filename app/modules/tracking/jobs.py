"""Tracking worker functions (A6; wired by A10a into ``app.worker``).

ServiceJob shape ``fn(session, *, now=None, limit=200) -> int`` (no commit; the worker commits per batch):

* :func:`emit_stale_signals`         - ``tracking.stale`` once per session + episode (the last trusted point it went
                                        stale from; ``no_data`` episode for a session that never delivered a point)
* :func:`emit_window_opened_signals` - ``tracking.window_opened`` once per booking

Own-session task (``geo.jobs`` pattern, under ``run_locked``):

* :func:`retention_task` - creates upcoming daily ``tracking_points`` partitions and drops expired ones through the
  SECURITY DEFINER functions of migrations 0058/0063 (Q71), builds simplified tracks of finished trips from trusted
  stored points, copies the raw points of trips under an evidence hold (M1, 0063) before their partition expires,
  deletes receipts older than ``POINT_RECEIPT_RETENTION``, simplified tracks older than
  ``SIMPLIFIED_TRACK_RETENTION`` and evidence whose hold was released over ``EVIDENCE_RETENTION_AFTER_RELEASE`` ago.

Events carry no coordinates (``events.EVENT_PAYLOAD_ALLOWLIST``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, literal, or_, select, text
from sqlalchemy.orm import Session

from app.contracts import tracking as contract
from app.contracts.enums import EventType, PassengerBookingStatus, ServiceType, TrackingSessionStatus
from app.contracts.events import EventEnvelope
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.platform import service as platform_service
from app.modules.platform.models import OutboxEvent
from app.modules.tracking import rules
from app.modules.tracking.models import TrackingSession
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SIGNAL_BATCH_LIMIT = 200
RETENTION_LOCK_KEY = "tracking.retention"
RETENTION_BATCH_LIMIT = 500
UNTRUSTED_FLAGS_SQL = "ARRAY[{}]::TEXT[]".format(
    ", ".join(f"'{flag.value}'" for flag in sorted(contract.UNTRUSTED_QUALITY_FLAGS, key=lambda flag: flag.value))
)
SIMPLIFY_TOLERANCE_DEG = 0.0001  # ~11 m


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _not_signalled(key_expression):  # noqa: ANN001, ANN202 - SQL expression
    return ~select(OutboxEvent.id).where(OutboxEvent.dedup_key == key_expression).exists()


def _stale_key_expression():  # noqa: ANN202 - SQL expression
    episode = func.coalesce(
        func.to_char(func.timezone("UTC", TrackingSession.last_captured_at), 'YYYYMMDD"T"HH24MISS.US'), literal("no_data")
    )
    return func.concat(f"{EventType.TRACKING_STALE.value}:", TrackingSession.id, ":", episode)


def emit_stale_signals(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """``tracking.stale`` for active sessions of running trips whose last trusted point is older than 120 s (``lost``) or
    that delivered no point for 120 s. One event per session + episode; a fresh point followed by a new gap is a new
    episode. Writes only outbox rows; no commit. Returns the number emitted."""
    now = _now(now)
    threshold = now - timedelta(seconds=contract.DELAYED_MAX_AGE_SECONDS)
    key = _stale_key_expression().label("dedup_key")
    rows = session.execute(
        select(TrackingSession.id, TrackingSession.trip_id, TrackingSession.last_captured_at, key)
        .join(Trip, Trip.id == TrackingSession.trip_id)
        .where(
            TrackingSession.status == TrackingSessionStatus.ACTIVE.value,
            Trip.status.in_(sorted(rules.PUBLISHABLE_TRIP_STATUSES)),
            func.coalesce(TrackingSession.last_captured_at, TrackingSession.started_at) < threshold,
            _not_signalled(_stale_key_expression()),
        )
        .order_by(TrackingSession.id)
        .limit(limit)
    ).all()
    for _session_id, trip_id, last_captured_at, dedup_key in rows:
        trip = trips_service.get_trip(session, trip_id)
        trip_public = trips_service.trip_public_id(trip)
        platform_service.enqueue_event(
            session,
            EventEnvelope(
                EventType.TRACKING_STALE, "trip", trip_public, trip.version, now,
                rules.stale_payload(trip_public_id=trip_public, last_captured_at=None if last_captured_at is None else ensure_aware_utc(last_captured_at)),
            ),
            aggregate_id=trip.id,
            dedup_key=dedup_key,
        )
    return len(rows)


def emit_window_opened_signals(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """``tracking.window_opened`` once per booking when its live-location window is open (AC44). No commit."""
    now = _now(now)
    key = func.concat(f"{EventType.TRACKING_WINDOW_OPENED.value}:", Booking.id)
    passenger_open = and_(
        Booking.service_type == ServiceType.PASSENGER.value,
        Booking.service_status.in_(sorted(contract.PASSENGER_TRACKING_STATUSES)),
        or_(
            Booking.service_status == PassengerBookingStatus.ONBOARD.value,
            Booking.pickup_window_start <= now + contract.PASSENGER_TRACKING_OPENS_BEFORE_PICKUP,
        ),
    )
    parcel_open = and_(
        Booking.service_type == ServiceType.PARCEL.value,
        Booking.service_status.in_(sorted(rules.parcel_open_statuses())),
    )
    candidates = session.execute(
        select(Booking, Trip)
        .join(Trip, Trip.id == Booking.trip_id)
        .where(
            Trip.status.not_in(sorted(contract.TRACKING_TRIP_TERMINAL_STATUSES)),
            or_(passenger_open, parcel_open),
            _not_signalled(key),
        )
        .order_by(Booking.id)
        .limit(limit)
    ).all()
    emitted = 0
    for booking, trip in candidates:
        window = rules.booking_tracking_window(
            service_type=booking.service_type, service_status=booking.service_status, trip_status=trip.status,
            pickup_window_start=booking.pickup_window_start, now=now,
        )
        if not window.is_open:
            continue
        opens_at = window.opens_at if booking.service_type == ServiceType.PASSENGER.value else booking.service_started_at
        booking_public = bookings_service.booking_public_id(booking)
        platform_service.enqueue_event(
            session,
            EventEnvelope(
                EventType.TRACKING_WINDOW_OPENED, "booking", booking_public, booking.version, now,
                rules.window_opened_payload(
                    booking_public_id=booking_public, trip_public_id=trips_service.trip_public_id(trip),
                    service_type=booking.service_type, opens_at=None if opens_at is None else ensure_aware_utc(opens_at),
                ),
            ),
            aggregate_id=booking.id,
            dedup_key=f"{EventType.TRACKING_WINDOW_OPENED.value}:{booking.id}",
        )
        emitted += 1
    return emitted


# --- retention -------------------------------------------------------------------------------------------------------------


def build_simplified_tracks(session: Session, *, now: datetime | None = None, limit: int = RETENTION_BATCH_LIMIT) -> int:
    """One simplified line per finished trip from its *trusted* stored points (no synthetic point is added). No commit."""
    now = _now(now)
    result = session.execute(
        text(
            f"""
            WITH candidates AS (
                SELECT s.trip_id
                  FROM tracking_sessions s
                  JOIN trips t ON t.id = s.trip_id
                 WHERE t.status IN ('completed', 'cancelled')
                   AND s.last_captured_at IS NOT NULL
                   AND s.last_captured_at > :raw_cutoff
                   AND NOT EXISTS (SELECT 1 FROM tracking_track_simplified x WHERE x.trip_id = s.trip_id)
                 GROUP BY s.trip_id
                 ORDER BY max(s.last_captured_at) DESC
                 LIMIT :limit
            ), lines AS (
                SELECT s.trip_id,
                       ST_Simplify(ST_MakeLine(p.point ORDER BY p.captured_at, p.seq), :tolerance, true) AS geometry,
                       count(*) AS point_count
                  FROM tracking_points p
                  JOIN tracking_sessions s ON s.id = p.session_id
                 WHERE s.trip_id IN (SELECT trip_id FROM candidates)
                   AND NOT (p.quality_flags && {UNTRUSTED_FLAGS_SQL})
                 GROUP BY s.trip_id
                HAVING count(*) >= 2
            )
            INSERT INTO tracking_track_simplified (trip_id, geometry, point_count, generated_at)
            SELECT trip_id, geometry, point_count, :now FROM lines
             WHERE geometry IS NOT NULL AND ST_NPoints(geometry) >= 2
            ON CONFLICT (trip_id) DO NOTHING
            """
        ),
        {"raw_cutoff": now - contract.RAW_POINT_RETENTION, "limit": limit, "tolerance": SIMPLIFY_TOLERANCE_DEG, "now": now},
    )
    return int(result.rowcount or 0)


def copy_evidence_points(session: Session, *, now: datetime | None = None, limit: int = RETENTION_BATCH_LIMIT) -> int:
    """M1: copy the raw points of trips under an active evidence hold out of the expiring daily partitions.

    Every stored point is copied, trusted or not (an ``implausible_speed`` point is evidence too). Runs before the
    partition drop; a partition whose held points are not copied yet is skipped by
    ``tracking_drop_expired_point_partitions`` (0063), so a failure here delays the drop instead of losing evidence.
    No commit; returns the number of points copied.
    """
    now = _now(now)
    result = session.execute(
        text(
            """
            INSERT INTO tracking_evidence_points (
                session_id, seq, trip_id, captured_date, captured_at, received_at, point, accuracy_m,
                speed_mps, heading_deg, battery_pct, is_mock, quality_flags, copied_at
            )
            SELECT p.session_id, p.seq, s.trip_id, p.captured_date, p.captured_at, p.received_at, p.point,
                   p.accuracy_m, p.speed_mps, p.heading_deg, p.battery_pct, p.is_mock, p.quality_flags, :now
              FROM tracking_points p
              JOIN tracking_sessions s ON s.id = p.session_id
             WHERE EXISTS (SELECT 1 FROM tracking_evidence_holds h
                            WHERE h.trip_id = s.trip_id AND h.released_at IS NULL)
               AND NOT EXISTS (SELECT 1 FROM tracking_evidence_points e
                                WHERE e.session_id = p.session_id AND e.seq = p.seq)
             ORDER BY p.captured_date, p.session_id, p.seq
             LIMIT :limit
            ON CONFLICT (session_id, seq) DO NOTHING
            """
        ),
        {"now": now, "limit": limit},
    )
    return int(result.rowcount or 0)


def purge_released_evidence(session: Session, *, now: datetime | None = None, limit: int = RETENTION_BATCH_LIMIT) -> int:
    """Evidence of trips whose every hold was released more than ``EVIDENCE_RETENTION_AFTER_RELEASE`` ago: the
    copied points go first, then the hold rows themselves. No commit; returns the number of rows removed."""
    now = _now(now)
    cutoff = now - contract.EVIDENCE_RETENTION_AFTER_RELEASE
    points = session.execute(
        text(
            """
            DELETE FROM tracking_evidence_points
             WHERE (session_id, seq) IN (
                SELECT x.session_id, x.seq
                  FROM tracking_evidence_points x
                 WHERE NOT EXISTS (
                     SELECT 1 FROM tracking_evidence_holds h
                      WHERE h.trip_id = x.trip_id AND (h.released_at IS NULL OR h.released_at >= :cutoff))
                 ORDER BY x.session_id, x.seq
                 LIMIT :limit
                 FOR UPDATE SKIP LOCKED)
            """
        ),
        {"cutoff": cutoff, "limit": limit},
    ).rowcount
    holds = session.execute(
        text(
            """
            DELETE FROM tracking_evidence_holds h
             WHERE h.released_at IS NOT NULL AND h.released_at < :cutoff
               AND NOT EXISTS (SELECT 1 FROM tracking_evidence_holds o
                                WHERE o.trip_id = h.trip_id AND (o.released_at IS NULL OR o.released_at >= :cutoff))
               AND NOT EXISTS (SELECT 1 FROM tracking_evidence_points e WHERE e.trip_id = h.trip_id)
            """
        ),
        {"cutoff": cutoff},
    ).rowcount
    return int(points or 0) + int(holds or 0)


def purge_expired_rows(session: Session, *, now: datetime | None = None, limit: int = RETENTION_BATCH_LIMIT) -> int:
    """Receipts older than 8 days and simplified tracks older than 30 days, in bounded batches. No commit."""
    now = _now(now)
    receipts = session.execute(
        text(
            "DELETE FROM tracking_point_receipts WHERE (session_id, seq) IN (SELECT session_id, seq FROM tracking_point_receipts "
            "WHERE received_at < :cutoff ORDER BY received_at LIMIT :limit FOR UPDATE SKIP LOCKED)"
        ),
        {"cutoff": now - contract.POINT_RECEIPT_RETENTION, "limit": limit},
    ).rowcount
    tracks = session.execute(
        text(
            "DELETE FROM tracking_track_simplified WHERE id IN (SELECT id FROM tracking_track_simplified "
            "WHERE generated_at < :cutoff ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED)"
        ),
        {"cutoff": now - contract.SIMPLIFIED_TRACK_RETENTION, "limit": limit},
    ).rowcount
    return int(receipts or 0) + int(tracks or 0)


def run_retention(session: Session, *, now: datetime | None = None, limit: int = RETENTION_BATCH_LIMIT) -> int:
    """Partitions (SECURITY DEFINER functions, DB clock) + simplified tracks + row purges. No commit; returns a count.

    Order matters: simplified tracks are built before raw partitions of their days are dropped on a later run.
    """
    created = session.execute(text("SELECT public.tracking_ensure_point_partitions()")).scalar_one()
    simplified = build_simplified_tracks(session, now=now, limit=limit)
    evidence = copy_evidence_points(session, now=now, limit=limit)
    dropped = session.execute(text("SELECT public.tracking_drop_expired_point_partitions()")).scalar_one()
    purged = purge_expired_rows(session, now=now, limit=limit) + purge_released_evidence(session, now=now, limit=limit)
    total = int(created) + simplified + evidence + int(dropped) + purged
    if total:
        logger.info(
            "tracking_retention partitions_created=%s simplified=%s evidence_copied=%s expired=%s purged=%s",
            created, simplified, evidence, dropped, purged,
        )
    return total


def run_retention_once(*, engine: Engine | None = None, now: datetime | None = None) -> int:
    if engine is None:
        from app.db.session import engine as default_engine

        engine = default_engine
    with Session(engine) as session:
        try:
            total = run_retention(session, now=now)
            session.commit()
            return total
        except BaseException:
            session.rollback()
            raise


def retention_task(*, engine: Engine | None = None) -> int:
    """Worker task (argument-free): ``run_retention_once`` under ``run_locked`` (one replica at a time); 0 when skipped."""
    from app.worker import run_locked

    ran, total = run_locked(RETENTION_LOCK_KEY, lambda: run_retention_once(engine=engine), engine=engine)
    return int(total or 0) if ran else 0
