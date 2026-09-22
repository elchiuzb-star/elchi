"""Trips domain API (A1): vehicles, trips, stop occurrences and segment capacity.

Public functions take the caller's ``Session`` and never commit (ADR-0001).

Capacity API for the bookings orchestrator (A4) - all quantities are integers
(seats, ml, g); a booking from occurrence ``p`` to ``d`` uses segments ``[p, d)``:

* ``lock_trip(session, trip_id, *, share=False) -> Trip``  (``FOR NO KEY UPDATE``; call right after users locks)
* ``check_capacity(session, trip_id, from_seq, to_seq, demand) -> list[Shortfall]``  (read only)
* ``require_capacity(...) -> None``  (CAPACITY_UNAVAILABLE / CARGO_LIMIT_EXCEEDED)
* ``reserve(session, trip_id, from_seq, to_seq, demand) -> list[int]``  (re-locks the trip; atomic)
* ``release(session, trip_id, from_seq, to_seq, demand) -> list[int]``
* ``occurrence_seqs_for_stops(session, trip_id, pickup_stop_id, dropoff_stop_id) -> tuple[int, int] | None``

A proposal only *checks* capacity; nothing is reserved before accept (spec §5.3).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import Capability, Role, TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.state_machines import TRIP
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.models import AuditLog
from app.modules.identity import service as identity_service
from app.modules.platform.service import constraint_name_of
from app.modules.trips.models import Trip, TripSegmentResource, TripStopOccurrence, Vehicle
from app.modules.trips.ports import RouteVersionRef, StopRef, get_geo_port
from app.modules.trips.rules import (
    ACTIVE_TRIP_STATUSES,
    TERMINAL_TRIP_STATUSES,
    TRIP_TIMEZONE,
    VEHICLE_DECISIONS,
    ResourceDemand,
    SegmentLoad,
    Shortfall,
    VehicleVerificationStatus,
    blocked_period,
    covered_from_seqs,
    find_shortfalls,
    map_stops_onto_route,
    normalize_plate,
    shortfall_error,
    validate_schedule,
    validation_error,
)
from app.modules.trips.schemas import TripCreate, TripPatch, TripStopInput, VehicleCreate

__all__ = [
    "CapacityAccountingError",
    "active_trip_public_ids",
    "assert_vehicle_eligible_for_new_booking",
    "check_capacity",
    "count_active_trips",
    "create_trip",
    "create_vehicle",
    "get_segment_loads",
    "get_trip",
    "get_trip_by_public_id",
    "get_vehicle",
    "list_driver_trips",
    "list_driver_vehicles",
    "list_occurrences",
    "lock_trip",
    "occurrence_seqs_for_stops",
    "patch_trip",
    "release",
    "require_capacity",
    "reserve",
    "resolve_trip_id",
    "transition_trip",
    "trip_public_id",
    "vehicle_public_id",
    "verify_vehicle",
]

PLATE_UNIQUE = "uq_vehicles_plate_normalized"
DRIVER_OVERLAP = "ex_trips_driver_overlap"
VEHICLE_OVERLAP = "ex_trips_vehicle_overlap"


class CapacityAccountingError(RuntimeError):
    """A release would drive a used counter below zero: caller bookkeeping bug (500)."""


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _flush_or_translate(session: Session, translations: dict[str, Callable[[], DomainError]]) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        factory = translations.get(constraint_name_of(exc) or "")
        if factory is None:
            raise
        raise factory() from exc


def _schedule_conflict(kind: str) -> Callable[[], DomainError]:
    return lambda: DomainError(ErrorCode.SCHEDULE_CONFLICT, details={"conflict": kind})


SCHEDULE_TRANSLATIONS = {DRIVER_OVERLAP: _schedule_conflict("driver"), VEHICLE_OVERLAP: _schedule_conflict("vehicle")}


def _check_version(current: int, expected: int) -> None:
    if current != expected:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": current})


def trip_public_id(trip: Trip) -> str:
    return format_public_id(PublicIdPrefix.TRIP, trip.public_id)


def vehicle_public_id(vehicle: Vehicle) -> str:
    return format_public_id(PublicIdPrefix.VEHICLE, vehicle.public_id)


# --- vehicles ------------------------------------------------------------------------------------


def _duplicate_plate() -> DomainError:
    return DomainError(ErrorCode.VALIDATION_ERROR, "plate_number is already registered", details={"field": "plate_number"})


def create_vehicle(
    session: Session, *, driver_user_id: int, data: VehicleCreate, now: datetime | None = None
) -> Vehicle:
    """T1: a driver (even before approval) registers a vehicle; it starts ``pending``."""
    caps = identity_service.get_capabilities(session, driver_user_id, now=now)
    if Role.DRIVER not in caps.roles or not caps.account_active:
        raise DomainError(ErrorCode.CAPABILITY_REQUIRED, details={"role": Role.DRIVER.value})
    plate_normalized = normalize_plate(data.plate_number)
    if session.execute(select(Vehicle.id).where(Vehicle.plate_normalized == plate_normalized)).first() is not None:
        raise _duplicate_plate()
    vehicle = Vehicle(
        public_id=new_public_uuid(),
        driver_user_id=driver_user_id,
        plate_number=data.plate_number.strip().upper(),
        plate_normalized=plate_normalized,
        make_model=data.make_model,
        color=data.color,
        seat_capacity=data.seat_capacity,
        baggage_capacity_ml=data.baggage_capacity_ml,
        cargo_max_weight_g=data.cargo_max_weight_g,
        cargo_max_volume_ml=data.cargo_max_volume_ml,
        document_file_ids=list(data.document_file_ids),
        verification_status=VehicleVerificationStatus.PENDING.value,
        version=1,
    )
    session.add(vehicle)
    _flush_or_translate(session, {PLATE_UNIQUE: _duplicate_plate})
    return vehicle


def get_vehicle(session: Session, vehicle_id: int) -> Vehicle:
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return vehicle


def _vehicle_by_public_id(session: Session, public_id: str, *, for_update: bool = False) -> Vehicle:
    value = parse_public_id(public_id, PublicIdPrefix.VEHICLE)
    stmt = select(Vehicle).where(Vehicle.public_id == value)
    if for_update:
        stmt = stmt.with_for_update(key_share=True).execution_options(populate_existing=True)
    vehicle = session.execute(stmt).scalar_one_or_none()
    if vehicle is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return vehicle


def list_driver_vehicles(session: Session, driver_user_id: int) -> list[Vehicle]:
    return list(
        session.execute(
            select(Vehicle).where(Vehicle.driver_user_id == driver_user_id).order_by(Vehicle.created_at, Vehicle.id)
        ).scalars()
    )


def verify_vehicle(
    session: Session,
    *,
    vehicle_public_id: str,
    actor_user_id: int,
    expected_version: int,
    decision: str,
    reason: str | None,
    now: datetime | None = None,
) -> Vehicle:
    """T3: staff approve/reject. Rejecting never cancels existing trips (D16 semantics)."""
    now = _now(now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.OPS_DRIVER_ELIGIBILITY_MANAGE
    )
    if decision not in VEHICLE_DECISIONS:
        raise validation_error("unknown decision", field="decision")
    vehicle = _vehicle_by_public_id(session, vehicle_public_id, for_update=True)
    _check_version(vehicle.version, expected_version)
    allowed_from, target = VEHICLE_DECISIONS[decision]
    if vehicle.verification_status not in allowed_from:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            details={"machine": "vehicle", "from": vehicle.verification_status, "to": target.value},
        )
    vehicle.verification_status = target.value
    vehicle.verification_reason = reason
    vehicle.verified_by = actor_user_id
    vehicle.verified_at = now
    vehicle.version += 1
    vehicle.updated_at = now
    session.add(
        AuditLog(
            actor_id=actor_user_id,
            entity_type="vehicle",
            entity_id=None,  # audit_logs.entity_id is INTEGER; BIGINT ids go into details
            action=f"vehicle_{decision}",
            details={
                "vehicle_id": format_public_id(PublicIdPrefix.VEHICLE, vehicle.public_id),
                "reason": reason,
                "version": vehicle.version,
            },
        )
    )
    session.flush()
    return vehicle


# --- trips: reads and locks ---------------------------------------------------------------------


def get_trip(session: Session, trip_id: int) -> Trip:
    trip = session.get(Trip, trip_id)
    if trip is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return trip


def resolve_trip_id(session: Session, public_id: str) -> int:
    value = parse_public_id(public_id, PublicIdPrefix.TRIP)
    trip_id = session.execute(select(Trip.id).where(Trip.public_id == value)).scalar_one_or_none()
    if trip_id is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return trip_id


def get_trip_by_public_id(session: Session, public_id: str) -> Trip:
    return get_trip(session, resolve_trip_id(session, public_id))


def lock_trip(session: Session, trip_id: int, *, share: bool = False) -> Trip:
    """Second group of the global lock order (ADR-0017): the physical capacity source.

    Exclusive mode is ``FOR NO KEY UPDATE`` so FK inserts referencing the trip (listings, threads,
    bookings, allocations) take their ``FOR KEY SHARE`` without deadlocking against it.
    """
    trip = session.execute(
        select(Trip)
        .where(Trip.id == trip_id)
        .with_for_update(read=share, key_share=not share)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if trip is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return trip


def list_occurrences(session: Session, trip_id: int) -> list[TripStopOccurrence]:
    return list(
        session.execute(
            select(TripStopOccurrence).where(TripStopOccurrence.trip_id == trip_id).order_by(TripStopOccurrence.seq)
        ).scalars()
    )


def occurrence_seqs_for_stops(
    session: Session, trip_id: int, pickup_stop_id: int, dropoff_stop_id: int
) -> tuple[int, int] | None:
    """First pickup occurrence and the first dropoff occurrence after it; ``None`` if absent or reversed."""
    occurrences = list_occurrences(session, trip_id)
    for pickup in occurrences:
        if pickup.stop_id != pickup_stop_id:
            continue
        for dropoff in occurrences:
            if dropoff.seq > pickup.seq and dropoff.stop_id == dropoff_stop_id:
                return pickup.seq, dropoff.seq
    return None


def count_active_trips(session: Session, driver_user_id: int) -> int:
    return int(
        session.execute(
            select(func.count(Trip.id)).where(
                Trip.driver_user_id == driver_user_id, Trip.status.in_(sorted(ACTIVE_TRIP_STATUSES))
            )
        ).scalar_one()
    )


def active_trip_public_ids(session: Session, driver_user_id: int) -> list[str]:
    rows = session.execute(
        select(Trip.public_id)
        .where(Trip.driver_user_id == driver_user_id, Trip.status.in_(sorted(ACTIVE_TRIP_STATUSES)))
        .order_by(Trip.planned_start_at, Trip.id)
    ).scalars()
    return [format_public_id(PublicIdPrefix.TRIP, value) for value in rows]


def list_driver_trips(
    session: Session,
    driver_user_id: int,
    *,
    statuses: Sequence[str] | None = None,
    after: tuple[datetime, int] | None = None,
    limit: int = 20,
) -> list[Trip]:
    stmt = select(Trip).where(Trip.driver_user_id == driver_user_id)
    if statuses:
        stmt = stmt.where(Trip.status.in_(list(statuses)))
    if after is not None:
        start, trip_id = after
        stmt = stmt.where(
            (Trip.planned_start_at > start) | ((Trip.planned_start_at == start) & (Trip.id > trip_id))
        )
    return list(session.execute(stmt.order_by(Trip.planned_start_at, Trip.id).limit(limit)).scalars())


# --- trips: commands ----------------------------------------------------------------------------


def _resolve_trip_stops(
    session: Session, route: RouteVersionRef, stops: Sequence[TripStopInput]
) -> tuple[list[StopRef], list[int]]:
    geo = get_geo_port()
    public_ids = [stop.stop_id for stop in stops]
    for public_id in public_ids:
        parse_public_id(public_id, PublicIdPrefix.STOP)
    refs = geo.stops_by_public_ids(session, public_ids)
    resolved: list[StopRef] = []
    for index, public_id in enumerate(public_ids):
        ref = refs.get(public_id)
        if ref is None:
            raise DomainError(ErrorCode.NOT_FOUND, details={"field": "stops", "index": index})
        if not ref.is_active:
            raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"field": "stops", "index": index})
        resolved.append(ref)
    route_seqs = map_stops_onto_route([ref.id for ref in resolved], [(s.seq, s.stop_id) for s in route.stops])
    if route_seqs is None:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "stops_not_on_route_version"})
    return resolved, route_seqs


def _confirmed_route(session: Session, route_version_public_id: str) -> RouteVersionRef:
    parse_public_id(route_version_public_id, PublicIdPrefix.ROUTE_VERSION)
    route = get_geo_port().route_version_by_public_id(session, route_version_public_id)
    if route is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": "route_version_id"})
    if not route.is_confirmed:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "route_version_not_confirmed"})
    return route


def _write_stops_and_segments(
    session: Session, trip: Trip, stops: Sequence[TripStopInput], refs: Sequence[StopRef], route_seqs: Sequence[int]
) -> None:
    for stop, ref, route_seq in zip(stops, refs, route_seqs, strict=True):
        session.add(
            TripStopOccurrence(
                trip_id=trip.id,
                seq=stop.seq,
                stop_id=ref.id,
                route_version_stop_seq=route_seq,
                planned_arrival_at=ensure_aware_utc(stop.planned_arrival_at),
                dwell_minutes=stop.dwell_minutes,
            )
        )
    for from_seq in range(1, len(stops)):
        session.add(
            TripSegmentResource(
                trip_id=trip.id,
                from_seq=from_seq,
                to_seq=from_seq + 1,
                seat_capacity=trip.seat_capacity,
                seats_used=0,
                baggage_capacity_ml=trip.baggage_capacity_ml,
                baggage_used_ml=0,
                cargo_capacity_weight_g=trip.cargo_capacity_weight_g,
                cargo_used_weight_g=0,
                cargo_capacity_volume_ml=trip.cargo_capacity_volume_ml,
                cargo_used_volume_ml=0,
            )
        )
    session.flush()


def _check_vehicle_capacity(vehicle: Vehicle, data: TripCreate) -> None:
    if vehicle.verification_status != VehicleVerificationStatus.APPROVED.value:
        raise DomainError(ErrorCode.VEHICLE_NOT_ELIGIBLE, details={"verification_status": vehicle.verification_status})
    limits = (
        ("seat_capacity", data.seat_capacity, vehicle.seat_capacity),
        ("baggage_capacity_ml", data.baggage_capacity_ml or 0, vehicle.baggage_capacity_ml or 0),
        ("cargo_capacity_weight_g", data.cargo_capacity_weight_g or 0, vehicle.cargo_max_weight_g or 0),
        ("cargo_capacity_volume_ml", data.cargo_capacity_volume_ml or 0, vehicle.cargo_max_volume_ml or 0),
    )
    for field, requested, available in limits:
        if requested > available:
            raise DomainError(
                ErrorCode.VEHICLE_NOT_ELIGIBLE, details={"field": field, "requested": requested, "vehicle_limit": available}
            )
    if not any(requested > 0 for _, requested, _ in limits):
        raise validation_error("a trip must offer seats, baggage or cargo capacity", field="seat_capacity")


def create_trip(session: Session, *, driver_user_id: int, data: TripCreate, now: datetime | None = None) -> Trip:
    """T4. Overlap is decided by the EXCLUDE constraints, not by a racy pre-check (AC13)."""
    now = _now(now)
    identity_service.lock_user_eligibility(session, [driver_user_id], mode="share")
    caps = identity_service.get_capabilities(session, driver_user_id, now=now)
    identity_service.require_capability(caps, Capability.TRIP_CREATE)

    vehicle = _vehicle_by_public_id(session, data.vehicle_id)
    if vehicle.driver_user_id != driver_user_id:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": "vehicle_id"})
    _check_vehicle_capacity(vehicle, data)

    route = _confirmed_route(session, data.route_version_id)
    refs, route_seqs = _resolve_trip_stops(session, route, data.stops)
    cutoff = validate_schedule(
        now=now,
        planned_start_at=data.planned_start_at,
        planned_end_at=data.planned_end_at,
        arrivals=[stop.planned_arrival_at for stop in data.stops],
        booking_cutoff_at=data.booking_cutoff_at,
    )
    start, blocked_end = blocked_period(data.planned_start_at, data.planned_end_at)
    trip = Trip(
        public_id=new_public_uuid(),
        driver_user_id=driver_user_id,
        vehicle_id=vehicle.id,
        route_version_id=route.id,
        status=TripStatus.PLANNED.value,
        planned_start_at=start,
        planned_end_at=ensure_aware_utc(data.planned_end_at),
        blocked_period=Range(start, blocked_end, bounds="[)"),
        booking_cutoff_at=cutoff,
        timezone=TRIP_TIMEZONE,
        seat_capacity=data.seat_capacity,
        baggage_capacity_ml=data.baggage_capacity_ml or 0,
        cargo_capacity_weight_g=data.cargo_capacity_weight_g or 0,
        cargo_capacity_volume_ml=data.cargo_capacity_volume_ml or 0,
        max_detour_minutes=data.max_detour_minutes,
        max_detour_m=data.max_detour_m,
        detour_used_minutes=0,
        detour_used_s=0,
        detour_used_m=0,
        pickup_wait_minutes=data.pickup_wait_minutes,
        version=1,
    )
    session.add(trip)
    _flush_or_translate(session, SCHEDULE_TRANSLATIONS)
    _write_stops_and_segments(session, trip, data.stops, refs, route_seqs)
    return trip


def patch_trip(
    session: Session, *, trip_public_id_value: str, actor_user_id: int, data: TripPatch, now: datetime | None = None
) -> Trip:
    """T7: schedule/stops/detour edits on a ``planned`` trip; route and time are frozen once capacity is reserved."""
    now = _now(now)
    trip_id = resolve_trip_id(session, trip_public_id_value)
    identity_service.lock_user_eligibility(session, [actor_user_id], mode="share")
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.TRIP_CREATE
    )
    trip = lock_trip(session, trip_id)
    if trip.driver_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    _check_version(trip.version, data.expected_version)
    if trip.status != TripStatus.PLANNED.value:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "trip", "from": trip.status, "command": "patch"})
    if data.stops is not None:
        # Q63: any allocation, released ones included, freezes the stops (bookings reference occurrence seqs).
        # Read under the trip lock, which every allocation insert also holds; DB backstop: 0054 trip_stops_locked.
        from app.modules.bookings import service as bookings_service  # bookings imports trips

        if bookings_service.trip_has_allocations(session, trip.id):
            raise DomainError(ErrorCode.TRIP_STOPS_LOCKED, details={"reason": "trip_has_allocations"})

    schedule_change = any(value is not None for value in (data.planned_start_at, data.planned_end_at, data.stops))
    if schedule_change and any(_has_usage(load) for load in get_segment_loads(session, trip.id)):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "trip_has_reserved_capacity"})

    new_start = ensure_aware_utc(data.planned_start_at) if data.planned_start_at else ensure_aware_utc(trip.planned_start_at)
    new_end = ensure_aware_utc(data.planned_end_at) if data.planned_end_at else ensure_aware_utc(trip.planned_end_at)
    if schedule_change:
        occurrences = list_occurrences(session, trip.id)
        arrivals = (
            [stop.planned_arrival_at for stop in data.stops]
            if data.stops
            else [ensure_aware_utc(o.planned_arrival_at) for o in occurrences]
        )
        old_start = ensure_aware_utc(trip.planned_start_at)
        old_cutoff = ensure_aware_utc(trip.booking_cutoff_at)
        requested_cutoff = new_start if old_cutoff == old_start else min(old_cutoff, new_start)
        trip.booking_cutoff_at = validate_schedule(
            now=now, planned_start_at=new_start, planned_end_at=new_end, arrivals=arrivals, booking_cutoff_at=requested_cutoff
        )
        _, blocked_end = blocked_period(new_start, new_end)
        trip.planned_start_at = new_start
        trip.planned_end_at = new_end
        trip.blocked_period = Range(new_start, blocked_end, bounds="[)")

    if data.max_detour_minutes is not None:
        if data.max_detour_minutes * 60 < trip.detour_used_s:
            raise validation_error("max_detour_minutes is below the detour already used", field="max_detour_minutes")
        trip.max_detour_minutes = data.max_detour_minutes
    if data.max_detour_m is not None:
        if data.max_detour_m < trip.detour_used_m:
            raise validation_error("max_detour_m is below the detour already used", field="max_detour_m")
        trip.max_detour_m = data.max_detour_m

    trip.version += 1
    trip.updated_at = now
    _flush_or_translate(session, SCHEDULE_TRANSLATIONS)

    if data.stops:
        routes = get_geo_port().route_versions_by_ids(session, [trip.route_version_id])
        route = routes.get(trip.route_version_id)
        if route is None or not route.is_confirmed:
            raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "route_version_not_confirmed"})
        refs, route_seqs = _resolve_trip_stops(session, route, data.stops)
        session.execute(delete(TripSegmentResource).where(TripSegmentResource.trip_id == trip.id))
        session.execute(delete(TripStopOccurrence).where(TripStopOccurrence.trip_id == trip.id))
        session.expire_all()
        trip = lock_trip(session, trip.id)
        _write_stops_and_segments(session, trip, data.stops, refs, route_seqs)

    if schedule_change:
        # BR #5: open trip-offer listings must still fit the new stops, and open negotiations quoted
        # against the old schedule expire (versions carry trip_version for A4 to compare).
        # Lock order: trip (held) -> listings -> threads.
        from app.modules.marketplace import service as marketplace_service  # marketplace imports trips

        marketplace_service.assert_trip_offers_on_trip(session, trip.id)
        marketplace_service.expire_threads_for_trip(session, trip.id, reason="trip_changed", now=now)
    return trip


# --- booking orchestrator commands (Q59, Q61; used by A4) ------------------------------------


def transition_trip(
    session: Session, *, trip: Trip, target: TripStatus | str, command: str, reason: str | None, now: datetime
) -> str:
    """Status write for the trip (STATE_MACHINES §3); returns the previous status. Never commits.

    Booking guards (``booking_blocks_trip_cancel``, pending no-show reviews) are A4's and run before this call,
    under the trip lock (``lock_trip``).
    """
    now = ensure_aware_utc(now)
    target_status = TripStatus(target)
    previous = trip.status
    TRIP.assert_transition(previous, target_status.value, command)
    trip.status = target_status.value
    if target_status is TripStatus.CANCELLED:
        trip.cancel_reason = reason
    elif target_status is TripStatus.INTERRUPTED:
        trip.interrupted_reason = reason
    trip.version += 1
    trip.updated_at = now
    session.flush()
    return previous


def assert_vehicle_eligible_for_new_booking(session: Session, vehicle_id: int) -> None:
    """Q61: a new booking needs an ``approved`` vehicle; existing bookings are obligations and never re-check.

    Plain read (no lock) - call it under the trip lock at accept. ``409 VEHICLE_NOT_ELIGIBLE``
    ``details {reason: "vehicle_not_approved", verification_status}`` (or ``reason: "vehicle_missing"``).
    """
    status = session.execute(select(Vehicle.verification_status).where(Vehicle.id == vehicle_id)).scalar_one_or_none()
    if status is None:
        raise DomainError(ErrorCode.VEHICLE_NOT_ELIGIBLE, details={"reason": "vehicle_missing"})
    if status != VehicleVerificationStatus.APPROVED.value:
        raise DomainError(
            ErrorCode.VEHICLE_NOT_ELIGIBLE, details={"reason": "vehicle_not_approved", "verification_status": status}
        )


# --- segment capacity (AC10, AC11, AC12; used by A4) ---------------------------------------


def _has_usage(load: SegmentLoad) -> bool:
    return bool(load.seats_used or load.baggage_used_ml or load.cargo_used_weight_g or load.cargo_used_volume_ml)


def _to_load(row: TripSegmentResource) -> SegmentLoad:
    return SegmentLoad(
        from_seq=row.from_seq,
        to_seq=row.to_seq,
        seat_capacity=row.seat_capacity,
        seats_used=row.seats_used,
        baggage_capacity_ml=row.baggage_capacity_ml,
        baggage_used_ml=row.baggage_used_ml,
        cargo_capacity_weight_g=row.cargo_capacity_weight_g,
        cargo_used_weight_g=row.cargo_used_weight_g,
        cargo_capacity_volume_ml=row.cargo_capacity_volume_ml,
        cargo_used_volume_ml=row.cargo_used_volume_ml,
    )


def _segment_rows(
    session: Session, trip_id: int, *, span: tuple[int, int] | None = None, for_update: bool = False
) -> list[TripSegmentResource]:
    stmt = select(TripSegmentResource).where(TripSegmentResource.trip_id == trip_id)
    if span is not None:
        stmt = stmt.where(TripSegmentResource.from_seq >= span[0], TripSegmentResource.from_seq < span[1])
    stmt = stmt.order_by(TripSegmentResource.from_seq).execution_options(populate_existing=True)
    if for_update:
        stmt = stmt.with_for_update(key_share=True)
    return list(session.execute(stmt).scalars())


def get_segment_loads(session: Session, trip_id: int) -> list[SegmentLoad]:
    return [_to_load(row) for row in _segment_rows(session, trip_id)]


def check_capacity(
    session: Session, trip_id: int, from_seq: int, to_seq: int, demand: ResourceDemand
) -> list[Shortfall]:
    """Pure read. Only meaningful for a decision when the caller holds ``lock_trip``."""
    covered_from_seqs(from_seq, to_seq)
    rows = _segment_rows(session, trip_id, span=(from_seq, to_seq))
    return find_shortfalls([_to_load(row) for row in rows], from_seq, to_seq, demand)


def require_capacity(session: Session, trip_id: int, from_seq: int, to_seq: int, demand: ResourceDemand) -> None:
    shortfalls = check_capacity(session, trip_id, from_seq, to_seq, demand)
    if shortfalls:
        raise shortfall_error(shortfalls)


def reserve(session: Session, trip_id: int, from_seq: int, to_seq: int, demand: ResourceDemand) -> list[int]:
    """Atomically consume capacity on segments ``[from_seq, to_seq)``; returns their ``from_seq``.

    Takes the trip row lock (re-entrant if the caller already holds it), re-reads the
    segments under ``FOR UPDATE`` and rejects with ``CAPACITY_UNAVAILABLE`` /
    ``CARGO_LIMIT_EXCEEDED`` before writing. The ``used <= capacity`` CHECK is the backstop.
    """
    if demand.is_empty:
        raise ValueError("reserve needs a non-empty demand")
    span = covered_from_seqs(from_seq, to_seq)
    trip = lock_trip(session, trip_id)
    if trip.status in TERMINAL_TRIP_STATUSES:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "trip", "from": trip.status, "command": "reserve"})
    rows = _segment_rows(session, trip_id, span=(from_seq, to_seq), for_update=True)
    shortfalls = find_shortfalls([_to_load(row) for row in rows], from_seq, to_seq, demand)
    if shortfalls:
        raise shortfall_error(shortfalls)
    for row in rows:
        row.seats_used += demand.seats
        row.baggage_used_ml += demand.baggage_ml
        row.cargo_used_weight_g += demand.cargo_weight_g
        row.cargo_used_volume_ml += demand.cargo_volume_ml
        row.updated_at = utc_now()
    session.flush()
    return list(span)


def release(session: Session, trip_id: int, from_seq: int, to_seq: int, demand: ResourceDemand) -> list[int]:
    """Return capacity taken by :func:`reserve` (cancel, no-show confirm, amendment).

    Contract for the bookings orchestrator (A4, owner of ``booking_allocations``):

    * call exactly once per allocation transition ``active -> inactive``, in the same transaction
      that flips ``booking_allocations.active``, while holding :func:`lock_trip` (taken here too);
    * pass the demand that was reserved for that allocation (the proposal version snapshot).

    Segment counters cannot tell which booking a unit belongs to, so a double release is only
    detectable when it would drive a counter below zero: that raises
    :class:`CapacityAccountingError` and nothing is written. A double release that another booking's
    usage hides is prevented only by A4's ``active`` flag transition, not here.
    """
    if demand.is_empty:
        raise ValueError("release needs a non-empty demand")
    span = covered_from_seqs(from_seq, to_seq)
    lock_trip(session, trip_id)
    rows = _segment_rows(session, trip_id, span=(from_seq, to_seq), for_update=True)
    if [row.from_seq for row in rows] != list(span):
        raise CapacityAccountingError(f"trip {trip_id} lacks segments {list(span)}")
    for row in rows:
        if (
            row.seats_used < demand.seats
            or row.baggage_used_ml < demand.baggage_ml
            or row.cargo_used_weight_g < demand.cargo_weight_g
            or row.cargo_used_volume_ml < demand.cargo_volume_ml
        ):
            raise CapacityAccountingError(f"release exceeds reserved capacity on trip {trip_id} segment {row.from_seq}")
    for row in rows:
        row.seats_used -= demand.seats
        row.baggage_used_ml -= demand.baggage_ml
        row.cargo_used_weight_g -= demand.cargo_weight_g
        row.cargo_used_volume_ml -= demand.cargo_volume_ml
        row.updated_at = utc_now()
    session.flush()
    return list(span)
