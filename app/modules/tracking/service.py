"""Tracking domain API (A6, wave 3; spec §10.3-§10.7, AC27-AC31, AC44, Q44, D16).

Public functions take the caller's ``Session`` and never commit (ADR-0001). GPS comes only from the trip driver's
phone; nothing here synthesises, interpolates or back-fills a point, and no DTO says "GPS active" - only the freshness
of the last *trusted* stored point (§6.6, §10.4-§10.5). "Keldim" is A4's ``arrive_at_pickup``
(``bookings.arrived_at_pickup_at``); it is only read here, never derived from GPS.

Lock order (ADR-0017): ``trips`` FOR SHARE -> ``tracking_sessions`` FOR NO KEY UPDATE (id ASC) -> receipts/points insert.
A trip transition (A4, ``trips`` FOR NO KEY UPDATE) therefore serialises with ingestion and session creation, and calls
:func:`close_sessions_for_trip` in its own transaction.

Exports other modules rely on (signatures fixed by WAVE1_CARDS "Wave 3"):

* ``booking_live_state(session, booking_id, *, now=None) -> BookingLiveState``            (A12 SOS staff view, A7)
* ``trip_tracking_summary(session, trip_id, *, now=None) -> TripTrackingSummary``          (K9, operator queue)
* ``close_sessions_for_trip(session, trip_id, *, now=None) -> int``                        (A4 trip complete/cancel)
* ``hold_trip_evidence`` / ``release_trip_evidence`` / ``trip_evidence_hold_open``          (A12 disputes, M1)

Worker functions: ``app.modules.tracking.jobs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import tracking as contract
from app.contracts.crypto import new_secret_token, secret_token_hash
from app.contracts.dto import (
    BookingTrackingDTO,
    PointRejectionDTO,
    PointsBatchAck,
    PointsBatchIn,
    PublicTrackingDTO,
    TrackingLastPointDTO,
    TrackingWindowDTO,
)
from app.contracts.enums import (
    Capability,
    ClientPlatform,
    FeatureFlagKey,
    TrackingFreshness,
    TrackingEvidenceReason,
    TrackingEvidenceSource,
    TrackingGrantScope,
    TrackingPointRejectReason,
    TrackingSessionStatus,
    TrackingWindowReason,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.state_machines import TRACKING_SESSION
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.models import AuditLog
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.identity import service as identity_service
from app.modules.platform.service import constraint_name_of
from app.modules.tracking import rules
from app.modules.tracking.models import (
    ACTIVE_SESSION_INDEX,
    TrackingEvidenceHold,
    TrackingGrant,
    TrackingPointReceipt,
    TrackingSession,
)
from app.modules.tracking.schemas import TrackingGrantDTO, TrackingSessionDTO, TripTrackingAdminDTO
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip

__all__ = [
    "BookingLiveState",
    "LivePoint",
    "PublicTrackingState",
    "TripTrackingSummary",
    "admin_trip_tracking",
    "booking_live_state",
    "booking_tracking",
    "close_session",
    "close_sessions_for_trip",
    "create_grant",
    "create_session",
    "grant_dto",
    "grant_public_id",
    "ingest_points",
    "public_tracking",
    "public_tracking_state",
    "revoke_grant",
    "session_dto",
    "session_public_id",
    "trip_tracking_summary",
]

ACTIVE = TrackingSessionStatus.ACTIVE.value
SUPERSEDED = TrackingSessionStatus.SUPERSEDED.value
CLOSED = TrackingSessionStatus.CLOSED.value
CREATE_ATTEMPTS = 3
MAX_PUBLIC_TOKEN_LENGTH = 256


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else ensure_aware_utc(value)


# --- exported read models ------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BookingLiveState:
    window: contract.TrackingWindow
    freshness: TrackingFreshness
    last_captured_at: datetime | None
    driver_arrived_at: datetime | None


@dataclass(frozen=True, slots=True)
class TripTrackingSummary:
    active_session: bool
    freshness: TrackingFreshness
    last_captured_at: datetime | None


@dataclass(frozen=True, slots=True)
class LivePoint:
    """The newest trusted stored point of a trip (live columns of its sessions)."""

    captured_at: datetime
    received_at: datetime
    lat: float
    lng: float
    accuracy_m: int

    def dto(self) -> TrackingLastPointDTO:
        return TrackingLastPointDTO(
            lat=self.lat,
            lng=self.lng,
            accuracy_m=self.accuracy_m,
            low_accuracy=contract.is_low_accuracy(self.accuracy_m),
            captured_at=self.captured_at,
            received_at=self.received_at,
        )


# --- ids and DTOs -------------------------------------------------------------------------------------------------------


def session_public_id(row: TrackingSession) -> str:
    return format_public_id(PublicIdPrefix.TRACKING_SESSION, row.public_id)


def grant_public_id(row: TrackingGrant) -> str:
    return format_public_id(PublicIdPrefix.TRACKING_GRANT, row.public_id)


def session_dto(row: TrackingSession) -> TrackingSessionDTO:
    return TrackingSessionDTO(
        id=session_public_id(row),
        status=TrackingSessionStatus(row.status),
        last_seq=row.last_seq,
        started_at=ensure_aware_utc(row.started_at),
        ended_at=_aware(row.ended_at),
        recommended_interval_s=contract.RECOMMENDED_INTERVAL_SECONDS,
    )


def grant_dto(row: TrackingGrant, *, url: str | None) -> TrackingGrantDTO:
    return TrackingGrantDTO(
        id=grant_public_id(row), url=url, valid_from=ensure_aware_utc(row.valid_from), expires_at=ensure_aware_utc(row.valid_until)
    )


def _window_dto(window: contract.TrackingWindow) -> TrackingWindowDTO:
    return TrackingWindowDTO(is_open=window.is_open, reason=window.reason, opens_at=_aware(window.opens_at))


# --- small readers ------------------------------------------------------------------------------------------------------


def _session_by_public_id(session: Session, public_id: str) -> TrackingSession:
    value = parse_public_id(public_id, PublicIdPrefix.TRACKING_SESSION)
    row = session.execute(select(TrackingSession).where(TrackingSession.public_id == value)).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


def _lock_session(session: Session, session_id: int) -> TrackingSession:
    row = session.execute(
        select(TrackingSession)
        .where(TrackingSession.id == session_id)
        .with_for_update(key_share=True)  # FOR NO KEY UPDATE: points/receipts insert FOR KEY SHARE on it
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


def _trip_live_point(session: Session, trip_id: int) -> LivePoint | None:
    row = session.execute(
        select(
            TrackingSession.last_captured_at,
            TrackingSession.last_received_at,
            TrackingSession.last_accuracy_m,
            func.ST_Y(TrackingSession.last_point),
            func.ST_X(TrackingSession.last_point),
        )
        .where(TrackingSession.trip_id == trip_id, TrackingSession.last_captured_at.is_not(None))
        .order_by(TrackingSession.last_captured_at.desc(), TrackingSession.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    captured_at, received_at, accuracy_m, lat, lng = row
    return LivePoint(ensure_aware_utc(captured_at), ensure_aware_utc(received_at), float(lat), float(lng), int(accuracy_m))


def _active_session(session: Session, trip_id: int) -> TrackingSession | None:
    return session.execute(
        select(TrackingSession).where(TrackingSession.trip_id == trip_id, TrackingSession.status == ACTIVE)
    ).scalar_one_or_none()


def _freshness(live: LivePoint | None, now: datetime) -> TrackingFreshness:
    return contract.freshness_at(None if live is None else live.captured_at, now)


def _window_for_booking(booking: Booking, trip: Trip, now: datetime) -> contract.TrackingWindow:
    return rules.booking_tracking_window(
        service_type=booking.service_type,
        service_status=booking.service_status,
        trip_status=trip.status,
        pickup_window_start=booking.pickup_window_start,
        now=now,
    )


def _audit_view(session: Session, *, actor_user_id: int, details: dict[str, Any]) -> None:
    """``audit_logs.action = tracking_viewed`` (§10.6): public ids and the surface only - never coordinates."""
    session.add(AuditLog(actor_id=actor_user_id, entity_type="tracking", entity_id=None, action="tracking_viewed", details=details))
    session.flush()


def _tracking_flag_enabled(session: Session, trip: Trip) -> bool:
    from app.modules.geo import service as geo_service
    from app.modules.geo.models import RouteVersion

    corridor_id = session.execute(select(RouteVersion.corridor_id).where(RouteVersion.id == trip.route_version_id)).scalar_one()
    return geo_service.is_flag_enabled(session, FeatureFlagKey.TRACKING_ENABLED, corridor_id=corridor_id)


# --- exports: read-only ---------------------------------------------------------------------------------------------


def booking_live_state(session: Session, booking_id: int, *, now: datetime | None = None) -> BookingLiveState:
    """Window, freshness and "Keldim" time of a booking for staff surfaces (no coordinates, no audit, read-only)."""
    now = _now(now)
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    trip = trips_service.get_trip(session, booking.trip_id)
    live = _trip_live_point(session, trip.id)
    return BookingLiveState(
        window=_window_for_booking(booking, trip, now),
        freshness=_freshness(live, now),
        last_captured_at=None if live is None else live.captured_at,
        driver_arrived_at=_aware(booking.arrived_at_pickup_at),
    )


def trip_tracking_summary(session: Session, trip_id: int, *, now: datetime | None = None) -> TripTrackingSummary:
    """Whether the trip has an active writer session and the freshness of its last trusted point (read-only)."""
    now = _now(now)
    live = _trip_live_point(session, trip_id)
    return TripTrackingSummary(
        active_session=_active_session(session, trip_id) is not None,
        freshness=_freshness(live, now),
        last_captured_at=None if live is None else live.captured_at,
    )


# --- K1 / K3 sessions -------------------------------------------------------------------------------------------------


def create_session(
    session: Session,
    *,
    actor_user_id: int,
    trip_public_id: str,
    device_id: str,
    platform: ClientPlatform | str,
    app_version: str,
    now: datetime | None = None,
) -> TrackingSession:
    """K1: the trip driver opens the single active writer session; a previous active one is superseded (AC29).

    ``tracking.publish`` is an obligation capability (kept under an eligibility block, D16). ``tracking_enabled`` off
    refuses only a trip that never had a session (AC38: a started trip continues).
    """
    now = _now(now)
    snapshot = trips_service.get_trip_by_public_id(session, trip_public_id)
    if snapshot.driver_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    if not caps.has(Capability.TRACKING_PUBLISH):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.TRACKING_PUBLISH.value})
    trip = trips_service.lock_trip(session, snapshot.id, share=True)
    if trip.status not in rules.PUBLISHABLE_TRIP_STATUSES:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "trip_not_running", "trip_status": trip.status}
        )
    # Several K1 for one trip (app restarts) serialise here; the trip row itself stays FOR SHARE (card K1), so trip
    # transitions and ingestion are not blocked by this lock.
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('tracking_session_trip:' || :trip_id, 0))"),
                    {"trip_id": str(trip.id)})
    had_session = session.execute(select(TrackingSession.id).where(TrackingSession.trip_id == trip.id).limit(1)).first() is not None
    if not had_session and not _tracking_flag_enabled(session, trip):
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"flag": FeatureFlagKey.TRACKING_ENABLED.value})
    platform_value = ClientPlatform(platform).value

    for _ in range(CREATE_ATTEMPTS):
        previous = session.execute(
            select(TrackingSession)
            .where(TrackingSession.trip_id == trip.id, TrackingSession.status == ACTIVE)
            .order_by(TrackingSession.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).scalars().all()
        for old in previous:
            TRACKING_SESSION.assert_transition(old.status, SUPERSEDED, "supersede")
            old.status = SUPERSEDED
            old.ended_at = now
            old.updated_at = now
        session.flush()
        try:
            with session.begin_nested():
                row = TrackingSession(
                    public_id=new_public_uuid(),
                    trip_id=trip.id,
                    driver_user_id=actor_user_id,
                    device_id=device_id,
                    platform=platform_value,
                    app_version=app_version,
                    status=ACTIVE,
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
            return row
        except IntegrityError as exc:
            # A concurrent K1 for the same trip committed its active session after our FOR UPDATE read (both hold the
            # trip FOR SHARE): supersede that one too and retry.
            if constraint_name_of(exc) != ACTIVE_SESSION_INDEX:
                raise
    raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "tracking_session_contention"})


def close_session(
    session: Session, *, actor_user_id: int, session_public_id_value: str, now: datetime | None = None
) -> TrackingSession:
    """K3: the session owner ends it. A superseded/closed session is returned unchanged (idempotent end state)."""
    now = _now(now)
    snapshot = _session_by_public_id(session, session_public_id_value)
    if snapshot.driver_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    trips_service.lock_trip(session, snapshot.trip_id, share=True)
    row = _lock_session(session, snapshot.id)
    if row.status == ACTIVE:
        TRACKING_SESSION.assert_transition(row.status, CLOSED, "close")
        row.status = CLOSED
        row.ended_at = now
        row.updated_at = now
        session.flush()
    return row


def close_sessions_for_trip(session: Session, trip_id: int, *, now: datetime | None = None) -> int:
    """A4 hook (trip ``complete``/``cancel``, same transaction, trip already locked): close active sessions. No commit."""
    now = _now(now)
    rows = session.execute(
        select(TrackingSession)
        .where(TrackingSession.trip_id == trip_id, TrackingSession.status == ACTIVE)
        .order_by(TrackingSession.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).scalars().all()
    for row in rows:
        TRACKING_SESSION.assert_transition(row.status, CLOSED, "close")
        row.status = CLOSED
        row.ended_at = now
        row.updated_at = now
    if rows:
        session.flush()
    return len(rows)


# --- M1 evidence holds ---------------------------------------------------------------------------------------------


def hold_trip_evidence(
    session: Session,
    *,
    trip_id: int,
    reason: str = TrackingEvidenceReason.DISPUTE.value,
    source_type: str = TrackingEvidenceSource.DISPUTE.value,
    source_id: int,
    now: datetime | None = None,
) -> bool:
    """M1: keep this trip's raw points past ``RAW_POINT_RETENTION`` while the source (a dispute) is open.

    Called by A12 when a dispute is opened. Idempotent per ``(trip_id, source_type, source_id)``: a second call
    re-opens a released hold instead of inserting a duplicate. Returns True when a hold is open after the call.
    The retention job copies the points; nothing is copied here. No commit.
    """
    now = _now(now)
    reason = TrackingEvidenceReason(reason).value
    source_type = TrackingEvidenceSource(source_type).value
    statement = (
        pg_insert(TrackingEvidenceHold)
        .values(trip_id=trip_id, reason=reason, source_type=source_type, source_id=source_id, created_at=now)
        .on_conflict_do_update(
            constraint="uq_tracking_evidence_holds_source",
            set_={"released_at": None},
        )
    )
    session.execute(statement)
    session.flush()
    return True


def release_trip_evidence(
    session: Session,
    *,
    trip_id: int,
    source_type: str = TrackingEvidenceSource.DISPUTE.value,
    source_id: int,
    now: datetime | None = None,
) -> bool:
    """M1: the source closed. The copied points stay for ``EVIDENCE_RETENTION_AFTER_RELEASE`` and are then purged.

    Returns True when a hold was released now (a second call is a no-op). No commit.
    """
    now = _now(now)
    result = session.execute(
        update(TrackingEvidenceHold)
        .where(
            TrackingEvidenceHold.trip_id == trip_id,
            TrackingEvidenceHold.source_type == TrackingEvidenceSource(source_type).value,
            TrackingEvidenceHold.source_id == source_id,
            TrackingEvidenceHold.released_at.is_(None),
        )
        .values(released_at=now)
    )
    session.flush()
    return bool(result.rowcount)


def trip_evidence_hold_open(session: Session, trip_id: int) -> bool:
    """True while any source still holds this trip's raw points (read-only, used by the retention job and tests)."""
    return bool(
        session.execute(
            select(TrackingEvidenceHold.id)
            .where(TrackingEvidenceHold.trip_id == trip_id, TrackingEvidenceHold.released_at.is_(None))
            .limit(1)
        ).scalar_one_or_none()
    )


# --- K2 ingestion ------------------------------------------------------------------------------------------------------


def _assert_writable(row: TrackingSession, trip: Trip) -> None:
    if row.status == SUPERSEDED:
        raise DomainError(ErrorCode.TRACKING_SESSION_SUPERSEDED)
    if row.status != ACTIVE or trip.status in contract.TRACKING_TRIP_TERMINAL_STATUSES:
        raise DomainError(ErrorCode.TRACKING_SESSION_CLOSED)


def _reference_fixes(session: Session, session_id: int) -> tuple[rules.Fix | None, rules.Fix | None]:
    row = session.execute(
        select(
            TrackingSession.last_captured_at,
            func.ST_Y(TrackingSession.last_point),
            func.ST_X(TrackingSession.last_point),
            TrackingSession.candidate_captured_at,
            func.ST_Y(TrackingSession.candidate_point),
            func.ST_X(TrackingSession.candidate_point),
        ).where(TrackingSession.id == session_id)
    ).one()
    live = None if row[0] is None else rules.Fix(ensure_aware_utc(row[0]), float(row[1]), float(row[2]))
    candidate = None if row[3] is None else rules.Fix(ensure_aware_utc(row[3]), float(row[4]), float(row[5]))
    return live, candidate


_INSERT_POINT_SQL = text(
    "INSERT INTO tracking_points (captured_date, session_id, seq, captured_at, received_at, point, accuracy_m, "
    "speed_mps, heading_deg, battery_pct, is_mock, quality_flags) VALUES (:captured_date, :session_id, :seq, "
    ":captured_at, :received_at, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :accuracy_m, :speed_mps, :heading_deg, "
    ":battery_pct, :is_mock, CAST(:quality_flags AS TEXT[]))"
)


def ingest_points(
    session: Session, *, actor_user_id: int, session_public_id_value: str, batch: PointsBatchIn, now: datetime | None = None
) -> PointsBatchAck:
    """K2 (AC27-AC29). Every accepted point is stored with its quality flags; only trusted, newer points move the live
    marker. The caller commits and only then returns the ACK (§10.4). No Idempotency-Key: ``(session, seq)`` dedups."""
    received_at = _now(now)
    snapshot = _session_by_public_id(session, session_public_id_value)
    if snapshot.driver_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    if len(batch.points) > contract.MAX_POINTS_PER_BATCH:
        raise DomainError(
            ErrorCode.TRACKING_BATCH_TOO_LARGE, details={"max_points": contract.MAX_POINTS_PER_BATCH, "points": len(batch.points)}
        )
    trip = trips_service.lock_trip(session, snapshot.trip_id, share=True)
    row = _lock_session(session, snapshot.id)
    _assert_writable(row, trip)

    seqs = sorted({point.seq for point in batch.points})
    stored_hashes = dict(
        session.execute(
            select(TrackingPointReceipt.seq, TrackingPointReceipt.payload_hash).where(
                TrackingPointReceipt.session_id == row.id, TrackingPointReceipt.seq.in_(seqs)
            )
        ).all()
    )
    duplicates: list[int] = []
    rejected: list[PointRejectionDTO] = []
    fresh: dict[int, tuple[Any, str]] = {}
    for point in batch.points:
        digest = rules.point_payload_hash(
            seq=point.seq, captured_at=point.captured_at, lat=point.lat, lng=point.lng, accuracy_m=point.accuracy_m,
            speed_mps=point.speed_mps, heading_deg=point.heading_deg, battery_pct=point.battery_pct, is_mock=point.is_mock,
        )
        known = stored_hashes.get(point.seq) or (fresh[point.seq][1] if point.seq in fresh else None)
        if known is not None:
            if known.strip() == digest:
                duplicates.append(point.seq)
            else:
                rejected.append(PointRejectionDTO(seq=point.seq, reason=TrackingPointRejectReason.PAYLOAD_CONFLICT))
            continue
        reason = contract.point_rejection(point.captured_at, received_at)
        if reason is not None:
            rejected.append(PointRejectionDTO(seq=point.seq, reason=reason))
            continue
        fresh[point.seq] = (point, digest)

    if fresh:
        live, candidate = _reference_fixes(session, row.id)
        live_before, candidate_before = live, candidate
        best_live_accuracy: int | None = None
        point_rows: list[dict[str, Any]] = []
        receipt_rows: list[dict[str, Any]] = []
        ordered = sorted(fresh.items(), key=lambda item: (ensure_aware_utc(item[1][0].captured_at), item[0]))
        for seq, (point, digest) in ordered:
            captured_at = ensure_aware_utc(point.captured_at)
            decision = rules.classify_point(
                captured_at=captured_at, lat=point.lat, lng=point.lng, accuracy_m=point.accuracy_m, is_mock=point.is_mock,
                live=live, candidate=candidate,
            )
            fix = rules.Fix(captured_at, point.lat, point.lng)
            if decision.moves_live:
                live = fix
                best_live_accuracy = point.accuracy_m
            if decision.becomes_candidate:
                candidate = fix
            day = rules.captured_date(captured_at)
            point_rows.append(
                {
                    "captured_date": day, "session_id": row.id, "seq": seq, "captured_at": captured_at, "received_at": received_at,
                    "lat": point.lat, "lng": point.lng, "accuracy_m": point.accuracy_m, "speed_mps": point.speed_mps,
                    "heading_deg": point.heading_deg, "battery_pct": point.battery_pct, "is_mock": point.is_mock,
                    "quality_flags": [flag.value for flag in decision.flags],
                }
            )
            receipt_rows.append(
                {"session_id": row.id, "seq": seq, "captured_date": day, "payload_hash": digest, "received_at": received_at}
            )
        session.execute(
            pg_insert(TrackingPointReceipt).values(receipt_rows).on_conflict_do_nothing(index_elements=["session_id", "seq"])
        )
        session.execute(_INSERT_POINT_SQL, point_rows)
        values: dict[str, Any] = {
            "last_seq": max([*fresh.keys(), *([row.last_seq] if row.last_seq is not None else [])]),
            "updated_at": received_at,
        }
        if live is not None and live != live_before:
            values.update(
                last_captured_at=live.captured_at,
                last_received_at=received_at,
                last_point=func.ST_SetSRID(func.ST_MakePoint(live.lng, live.lat), 4326),
                last_accuracy_m=best_live_accuracy,
            )
        if candidate is not None and candidate != candidate_before:
            values.update(
                candidate_captured_at=candidate.captured_at,
                candidate_point=func.ST_SetSRID(func.ST_MakePoint(candidate.lng, candidate.lat), 4326),
            )
        session.execute(update(TrackingSession).where(TrackingSession.id == row.id).values(**values))
        session.flush()

    return PointsBatchAck(
        accepted_seqs=sorted(fresh.keys()),
        duplicate_seqs=duplicates,
        rejected=rejected,
        session_status=TrackingSessionStatus(row.status),
    )


# --- K4 participant / staff view -------------------------------------------------------------------------------------


def _booking_tracking_dto(booking: Booking, window: contract.TrackingWindow, live: LivePoint | None, now: datetime) -> BookingTrackingDTO:
    return BookingTrackingDTO(
        booking_id=bookings_service.booking_public_id(booking),
        window=_window_dto(window),
        freshness=_freshness(live, now),
        last_point=None if live is None else live.dto(),
        driver_arrived_at=_aware(booking.arrived_at_pickup_at),
        eta_window_start=None,  # no routing/ETA provider in the pilot (Q46); never a guessed ETA
        eta_window_end=None,
        eta_is_estimate=True,
    )


def booking_tracking(
    session: Session, *, booking_public_id_value: str, viewer_user_id: int, now: datetime | None = None, audit: bool = True
) -> BookingTrackingDTO:
    """K4. Participants (client, driver) inside the window; staff with ``ops.view`` always (audited). Others -> 404.

    Only this booking's trip is read, so a later ride of the vehicle and other bookings stay invisible (§10.3 step 6).
    """
    now = _now(now)
    booking, role = bookings_service.get_booking_for_viewer(session, booking_public_id_value, viewer_user_id)
    trip = trips_service.get_trip(session, booking.trip_id)
    window = _window_for_booking(booking, trip, now)
    if role == bookings_service.ViewerRole.STAFF:
        if audit:
            _audit_view(session, actor_user_id=viewer_user_id,
                        details={"booking_id": bookings_service.booking_public_id(booking), "surface": "booking_tracking"})
    elif not window.is_open:
        details: dict[str, Any] = {"reason": window.reason.value}
        if window.opens_at is not None:
            details["opens_at"] = ensure_aware_utc(window.opens_at).isoformat()
        raise DomainError(ErrorCode.TRACKING_WINDOW_NOT_OPEN, details=details)
    return _booking_tracking_dto(booking, window, _trip_live_point(session, trip.id), now)


# --- K5-K7 recipient links -----------------------------------------------------------------------------------------------


def _owner_booking(session: Session, booking_public_id_value: str, actor_user_id: int) -> Booking:
    booking, role = bookings_service.get_booking_for_viewer(session, booking_public_id_value, actor_user_id)
    if role != bookings_service.ViewerRole.CLIENT:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "booking_owner_only"})
    return booking


def create_grant(
    session: Session,
    *,
    actor_user_id: int,
    booking_public_id_value: str,
    scope: TrackingGrantScope | str,
    ttl_minutes: int,
    now: datetime | None = None,
) -> tuple[TrackingGrant, str]:
    """K5: the booking owner (client / parcel sender) creates a recipient link. Returns ``(grant, token)``; the token is
    ``crypto.new_secret_token`` (``TRACKING_TOKEN_BYTES``) and only its SHA-256 is stored. The grant starts when the
    window opens (if that time is known) and never outlives ``ttl``; K7 re-checks the window on every read."""
    now = _now(now)
    booking = _owner_booking(session, booking_public_id_value, actor_user_id)
    scope_value = TrackingGrantScope(scope).value
    ttl = rules.grant_ttl(ttl_minutes)
    trip = trips_service.get_trip(session, booking.trip_id)
    window = _window_for_booking(booking, trip, now)
    if window.reason in (TrackingWindowReason.BOOKING_FINISHED, TrackingWindowReason.TRIP_FINISHED):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": window.reason.value})
    valid_from, valid_until = rules.grant_validity(
        window=window, service_type=booking.service_type, pickup_window_start=booking.pickup_window_start, now=now, ttl=ttl
    )
    token = new_secret_token(contract.TRACKING_TOKEN_BYTES)
    grant = TrackingGrant(
        public_id=new_public_uuid(),
        booking_id=booking.id,
        grantee_user_id=None,
        token_hash=secret_token_hash(token),
        scope=scope_value,
        valid_from=valid_from,
        valid_until=valid_until,
        created_by_user_id=actor_user_id,
        created_at=now,
    )
    session.add(grant)
    session.flush()
    return grant, token


def revoke_grant(
    session: Session, *, actor_user_id: int, booking_public_id_value: str, grant_public_id_value: str, now: datetime | None = None
) -> None:
    """K6: the owner revokes a link (idempotent); the link then returns 404 and its WebSocket closes (AC31)."""
    now = _now(now)
    booking = _owner_booking(session, booking_public_id_value, actor_user_id)
    value = parse_public_id(grant_public_id_value, PublicIdPrefix.TRACKING_GRANT)
    grant = session.execute(
        select(TrackingGrant)
        .where(TrackingGrant.public_id == value, TrackingGrant.booking_id == booking.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if grant is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if grant.revoked_at is None:
        grant.revoked_at = now
        session.flush()


@dataclass(frozen=True, slots=True)
class PublicTrackingState:
    """Result of a K7/K8 token lookup: ``grant_valid`` false -> unknown/revoked/expired; else the window decides."""

    grant_valid: bool
    window: contract.TrackingWindow | None = None
    dto: PublicTrackingDTO | None = None


def public_tracking_state(session: Session, *, token: str, now: datetime | None = None) -> PublicTrackingState:
    now = _now(now)
    if not isinstance(token, str) or not token or len(token) > MAX_PUBLIC_TOKEN_LENGTH:
        return PublicTrackingState(False)
    grant = session.execute(select(TrackingGrant).where(TrackingGrant.token_hash == secret_token_hash(token))).scalar_one_or_none()
    if (
        grant is None
        or grant.revoked_at is not None
        or now < ensure_aware_utc(grant.valid_from)
        or now >= ensure_aware_utc(grant.valid_until)
    ):
        return PublicTrackingState(False)
    booking = session.get(Booking, grant.booking_id)
    if booking is None:  # pragma: no cover - FK
        return PublicTrackingState(False)
    trip = trips_service.get_trip(session, booking.trip_id)
    window = _window_for_booking(booking, trip, now)
    if not window.is_open:
        return PublicTrackingState(True, window)
    live = _trip_live_point(session, trip.id)
    dto = PublicTrackingDTO(
        freshness=_freshness(live, now),
        last_point=None if live is None else live.dto(),
        status_label=f"{booking.service_type}.{booking.service_status}",
    )
    return PublicTrackingState(True, window, dto)


def public_tracking(session: Session, *, token: str, now: datetime | None = None) -> PublicTrackingDTO:
    """K7: unknown, revoked, expired token or closed window -> 404 (no difference is revealed)."""
    state = public_tracking_state(session, token=token, now=now)
    if state.dto is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return state.dto


# --- K9 operator ---------------------------------------------------------------------------------------------------------


def admin_trip_tracking(
    session: Session, *, actor_user_id: int, trip_public_id: str, now: datetime | None = None
) -> TripTrackingAdminDTO:
    now = _now(now)
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    if not caps.has(Capability.OPS_VIEW):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.OPS_VIEW.value})
    trip = trips_service.get_trip_by_public_id(session, trip_public_id)
    _audit_view(session, actor_user_id=actor_user_id,
                details={"trip_id": trips_service.trip_public_id(trip), "surface": "admin_trip_tracking"})
    active = _active_session(session, trip.id)
    live = _trip_live_point(session, trip.id)
    return TripTrackingAdminDTO(
        trip_id=trips_service.trip_public_id(trip),
        active_session=active is not None,
        session_started_at=None if active is None else ensure_aware_utc(active.started_at),
        freshness=_freshness(live, now),
        last_point=None if live is None else live.dto(),
    )
