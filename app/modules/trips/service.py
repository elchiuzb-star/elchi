"""Trips domain API (A1): vehicles, trips and their capacity on the road.

Public functions take the caller's ``Session`` and never commit (ADR-0001).

A trip is a stretch ``[route_start_m, route_end_m]`` of one confirmed road (ADR-0028, Q160: no stop anywhere). Capacity
API for the bookings orchestrator (A4) - quantities are integers (seats, ml, g), positions are metres along the road,
a booking occupies ``[from_m, to_m)``:

* ``lock_trip(session, trip_id, *, share=False) -> Trip``  (``FOR NO KEY UPDATE``; call right after users locks)

* ``check_claim_capacity(session, trip_id, from_m, to_m, demand) -> list[ClaimShortfall]``  (read only)
* ``require_claim_capacity(session, trip_id, from_m, to_m, demand) -> None``  (the decision, under ``lock_trip``)
* ``claim(session, *, trip_id, booking_id, from_m, to_m, demand) -> TripCapacityClaim``  (re-locks the trip)
* ``release_claim(session, *, booking_id, now) -> bool``  (true -> false once; the release contract's twin)

A proposal only *checks* capacity; nothing is reserved before accept (spec §5.3).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import Capability, Role, TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import (
    PublicIdPrefix,
    format_public_id,
    new_public_uuid,
    parse_public_id,
    public_id_fragment_range,
)
from app.contracts.route_position import (
    Claim,
    ClaimShortfall,
    Resources,
    claim_span,
    eta_at,
    interval_shortfalls,
)
from app.contracts.state_machines import TRIP
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.models import AuditLog
from app.modules.identity import service as identity_service
from app.modules.platform.service import constraint_name_of
from app.modules.trips.models import Trip, TripCapacityClaim, Vehicle
from app.modules.trips.ports import RouteVersionRef, get_geo_port
from app.modules.trips.rules import (
    ACTIVE_TRIP_STATUSES,
    TERMINAL_TRIP_STATUSES,
    TRIP_TIMEZONE,
    VEHICLE_DECISIONS,
    ResourceDemand,
    VehicleVerificationStatus,
    blocked_period,
    claim_shortfall_error,
    normalize_plate,
    validate_schedule,
    validation_error,
)
from app.modules.trips.schemas import TripCreate, TripPatch, VehicleCreate

__all__ = [
    "active_trip_public_ids",
    "assert_vehicle_eligible_for_new_booking",
    "active_claims",
    "check_claim_capacity",
    "claim",
    "require_claim_capacity",
    "count_active_trips",
    "create_trip",
    "create_vehicle",
    "get_trip",
    "get_trip_by_public_id",
    "get_vehicle",
    "list_driver_trips",
    "list_driver_vehicles",
    "list_vehicles_for_review",
    "lock_trip",
    "patch_trip",
    "release_claim",
    "trip_eta_at",
    "trip_has_claims",
    "resolve_trip_id",
    "transition_trip",
    "trip_public_id",
    "vehicle_public_id",
    "verify_vehicle",
]

PLATE_UNIQUE = "uq_vehicles_plate_normalized"
DRIVER_OVERLAP = "ex_trips_driver_overlap"
VEHICLE_OVERLAP = "ex_trips_vehicle_overlap"


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
    """T1: a driver (even before approval) registers a vehicle; it starts ``pending``.

    Q94 ("the car is entered once") is not enforced by refusing a second row here. A registered vehicle is
    already immutable - there is no update path, only ``verify_vehicle`` - and a *new* row starts ``pending``,
    which ``_check_vehicle_capacity`` and ``assert_vehicle_eligible_for_new_booking`` both refuse. So staff
    already stand between any new car and a client, which is what the decision asks for, while a driver who
    genuinely runs two cars is not locked out. The single entry is enforced where the driver actually types
    it: the profile form registers one car, and v1 locks those fields after the first save.
    """
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


def list_vehicles_for_review(
    session: Session,
    *,
    actor_user_id: int,
    statuses: Sequence[str] | None = None,
    owner_user_public_id: str | None = None,
    after: tuple[datetime, int] | None = None,
    limit: int = 20,
    now: datetime | None = None,
) -> list[Vehicle]:
    """T3a: the staff verification queue, oldest first (``created_at``, ``id`` keyset).

    Gated with the same capability as ``verify_vehicle``: whoever may decide may see what waits for a decision.
    Read only - no lock, no audit row (reading the queue is not an action on a vehicle). ``owner_user_public_id``
    narrows it to one driver's cars (the admin driver card); the owner is resolved only after the capability check,
    so an unauthorised caller cannot probe which user ids exist.
    """
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=_now(now)),
        Capability.OPS_DRIVER_ELIGIBILITY_MANAGE,
    )
    stmt = select(Vehicle)
    if owner_user_public_id is not None:
        stmt = stmt.where(Vehicle.driver_user_id == identity_service.resolve_user_id(session, owner_user_public_id))
    if statuses:
        stmt = stmt.where(Vehicle.verification_status.in_(list(statuses)))
    if after is not None:
        created, vehicle_id = after
        stmt = stmt.where(
            (Vehicle.created_at > created) | ((Vehicle.created_at == created) & (Vehicle.id > vehicle_id))
        )
    return list(session.execute(stmt.order_by(Vehicle.created_at, Vehicle.id).limit(limit)).scalars())


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


def _confirmed_route(session: Session, route_version_public_id: str) -> RouteVersionRef:
    parse_public_id(route_version_public_id, PublicIdPrefix.ROUTE_VERSION)
    route = get_geo_port().route_version_by_public_id(session, route_version_public_id)
    if route is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": "route_version_id"})
    if not route.is_confirmed:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "route_version_not_confirmed"})
    return route


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


def create_trip(
    session: Session, *, driver_user_id: int, data: TripCreate, now: datetime | None = None, direction_id: int | None = None
) -> Trip:
    """T4. Overlap is decided by the EXCLUDE constraints, not by a racy pre-check (AC13).

    ``direction_id`` (ADR-0027): set when the system makes the trip from a driver direction (Q152).
    """
    now = _now(now)
    identity_service.lock_user_eligibility(session, [driver_user_id], mode="share")
    caps = identity_service.get_capabilities(session, driver_user_id, now=now)
    identity_service.require_capability(caps, Capability.TRIP_CREATE)

    vehicle = _vehicle_by_public_id(session, data.vehicle_id)
    if vehicle.driver_user_id != driver_user_id:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": "vehicle_id"})
    _check_vehicle_capacity(vehicle, data)

    route = _confirmed_route(session, data.route_version_id)
    span = _road_stretch(route, data.route_start_m, data.route_end_m)
    cutoff = validate_schedule(
        now=now,
        planned_start_at=data.planned_start_at,
        planned_end_at=data.planned_end_at,
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
        direction_id=direction_id,
        route_start_m=span[0],
        route_end_m=span[1],
    )
    session.add(trip)
    _flush_or_translate(session, SCHEDULE_TRANSLATIONS)
    return trip


def _road_stretch(route: RouteVersionRef, start_m: int | None, end_m: int | None) -> tuple[int, int]:
    """ADR-0028: the part of the road the trip drives - the whole road unless a stretch is given."""
    if route.distance_m is None:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "road_length_unknown"})
    start, end = (0, route.distance_m) if start_m is None else (start_m, end_m)
    if not 0 <= start < end <= route.distance_m:
        raise validation_error("the trip's stretch must lie on the road", field="route_end_m", road_m=route.distance_m)
    return start, end


def patch_trip(
    session: Session, *, trip_public_id_value: str, actor_user_id: int, data: TripPatch, now: datetime | None = None
) -> Trip:
    """T7: schedule/stretch/detour edits on a ``planned`` trip; the stretch and time are frozen once capacity is reserved."""
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
    stretch_change = data.route_start_m is not None
    if stretch_change and trip_has_claims(session, trip.id):
        # Q63 successor (ADR-0028): any booking ever on the trip, released ones included, freezes its stretch. Read
        # under the trip lock, which every claim insert also holds; DB backstop: 0097 trips_route_span_locked.
        raise DomainError(ErrorCode.TRIP_STOPS_LOCKED, details={"reason": "trip_has_bookings"})

    schedule_change = any(value is not None for value in (data.planned_start_at, data.planned_end_at, data.route_start_m))
    if schedule_change and trip_has_claims(session, trip.id, active_only=True):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "trip_has_reserved_capacity"})

    new_start = ensure_aware_utc(data.planned_start_at) if data.planned_start_at else ensure_aware_utc(trip.planned_start_at)
    new_end = ensure_aware_utc(data.planned_end_at) if data.planned_end_at else ensure_aware_utc(trip.planned_end_at)
    if schedule_change:
        old_start = ensure_aware_utc(trip.planned_start_at)
        old_cutoff = ensure_aware_utc(trip.booking_cutoff_at)
        requested_cutoff = new_start if old_cutoff == old_start else min(old_cutoff, new_start)
        trip.booking_cutoff_at = validate_schedule(
            now=now, planned_start_at=new_start, planned_end_at=new_end, booking_cutoff_at=requested_cutoff
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

    if stretch_change:
        route = get_geo_port().route_versions_by_ids(session, [trip.route_version_id]).get(trip.route_version_id)
        if route is None or not route.is_confirmed:
            raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "route_version_not_confirmed"})
        trip.route_start_m, trip.route_end_m = _road_stretch(route, data.route_start_m, data.route_end_m)
        session.flush()

    if schedule_change:
        # BR #5: open negotiations quoted against the old schedule expire (versions carry trip_version for A4 to
        # compare). Lock order: trip (held) -> listings -> threads.
        from app.modules.marketplace import (
            service as marketplace_service,  # marketplace imports trips
        )

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


# --- interval capacity (ADR-0028 phase 1, Q159) ----------------------------------------------------------------


def _resources(demand: ResourceDemand) -> Resources:
    return Resources(
        seats=demand.seats,
        baggage_ml=demand.baggage_ml,
        cargo_weight_g=demand.cargo_weight_g,
        cargo_volume_ml=demand.cargo_volume_ml,
    )


def _trip_capacity(trip: Trip) -> Resources:
    return Resources(
        seats=trip.seat_capacity,
        baggage_ml=trip.baggage_capacity_ml,
        cargo_weight_g=trip.cargo_capacity_weight_g,
        cargo_volume_ml=trip.cargo_capacity_volume_ml,
    )


def active_claims(session: Session, trip_id: int) -> list[Claim]:
    rows = session.execute(
        select(TripCapacityClaim)
        .where(TripCapacityClaim.trip_id == trip_id, TripCapacityClaim.active.is_(True))
        .order_by(TripCapacityClaim.from_m, TripCapacityClaim.id)
    ).scalars()
    return [
        Claim(
            row.from_m,
            row.to_m,
            Resources(
                seats=row.seats,
                baggage_ml=row.baggage_ml,
                cargo_weight_g=row.cargo_weight_g,
                cargo_volume_ml=row.cargo_volume_ml,
            ),
        )
        for row in rows
    ]


def check_claim_capacity(
    session: Session, trip_id: int, from_m: int, to_m: int, demand: ResourceDemand
) -> list[ClaimShortfall]:
    """Pure read. Only meaningful for a decision when the caller holds ``lock_trip``."""
    claim_span(from_m, to_m)
    trip = get_trip(session, trip_id)
    return interval_shortfalls(_trip_capacity(trip), active_claims(session, trip_id), from_m, to_m, _resources(demand))


def require_claim_capacity(session: Session, trip_id: int, from_m: int, to_m: int, demand: ResourceDemand) -> None:
    """ADR-0028 phase 2: the capacity decision - ``CAPACITY_UNAVAILABLE`` / ``CARGO_LIMIT_EXCEEDED`` with the road
    position where the trip is full. A decision only under ``lock_trip``; a proposal uses it as an early check."""
    if demand.is_empty:
        return
    shortfalls = check_claim_capacity(session, trip_id, from_m, to_m, demand)
    if shortfalls:
        raise claim_shortfall_error(shortfalls)


def claim(
    session: Session, *, trip_id: int, booking_id: int, from_m: int, to_m: int, demand: ResourceDemand
) -> TripCapacityClaim:
    """Occupy ``[from_m, to_m)`` of the trip's road for one booking (ADR-0028).

    Takes the trip row lock (re-entrant), checks every road position the claim covers and rejects with
    ``CAPACITY_UNAVAILABLE`` / ``CARGO_LIMIT_EXCEEDED`` before writing; the DB trigger is the backstop. Since phase 2
    this is the capacity decision; new bookings get no segment allocation.
    """
    if demand.is_empty:
        raise ValueError("claim needs a non-empty demand")
    claim_span(from_m, to_m)
    trip = lock_trip(session, trip_id)
    if trip.status in TERMINAL_TRIP_STATUSES:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "trip", "from": trip.status, "command": "claim"})
    shortfalls = interval_shortfalls(
        _trip_capacity(trip), active_claims(session, trip_id), from_m, to_m, _resources(demand)
    )
    if shortfalls:
        raise claim_shortfall_error(shortfalls)
    row = TripCapacityClaim(
        trip_id=trip_id,
        booking_id=booking_id,
        from_m=from_m,
        to_m=to_m,
        seats=demand.seats,
        baggage_ml=demand.baggage_ml,
        cargo_weight_g=demand.cargo_weight_g,
        cargo_volume_ml=demand.cargo_volume_ml,
        active=True,
    )
    session.add(row)
    session.flush()
    return row


def trip_eta_at(trip: Trip, position_m: int) -> datetime | None:
    """ADR-0028 phase 2: when the trip passes ``position_m`` of its road - linear between its planned start and end
    over its road span (``app.contracts.route_position.eta_at``). ``None`` for a trip without a road span."""
    if trip.route_start_m is None or trip.route_end_m is None:
        return None
    return eta_at(
        position_m, start_m=trip.route_start_m, end_m=trip.route_end_m,
        start_at=ensure_aware_utc(trip.planned_start_at), end_at=ensure_aware_utc(trip.planned_end_at),
    )


def trip_stretch(session: Session, trip: Trip) -> tuple[int, int]:
    """``(route_start_m, route_end_m)`` - the part of the road the trip drives; an unset stretch is the whole road."""
    if trip.route_start_m is not None and trip.route_end_m is not None:
        return trip.route_start_m, trip.route_end_m
    route = get_geo_port().route_versions_by_ids(session, [trip.route_version_id]).get(trip.route_version_id)
    return 0, route.distance_m if route is not None else 0


def trip_has_claims(session: Session, trip_id: int, *, active_only: bool = False) -> bool:
    """ADR-0028 (Q63 successor): has any booking ever claimed this trip's road (or holds one now)."""
    stmt = select(TripCapacityClaim.id).where(TripCapacityClaim.trip_id == trip_id)
    if active_only:
        stmt = stmt.where(TripCapacityClaim.active.is_(True))
    return session.execute(stmt.limit(1)).first() is not None


def release_claim(session: Session, *, booking_id: int, now: datetime) -> bool:
    """Flip the booking's active claim true -> false; ``False`` when it had none (release contract, ADR-0017 §11).

    Call it in the transaction - and under the trip lock - that releases the booking's allocations.
    """
    released = session.execute(
        update(TripCapacityClaim)
        .where(TripCapacityClaim.booking_id == booking_id, TripCapacityClaim.active.is_(True))
        .values(active=False, released_at=ensure_aware_utc(now))
        .returning(TripCapacityClaim.id)
        .execution_options(synchronize_session=False)
    ).all()
    return bool(released)


# --- staff lookup (admin panel) -------------------------------------------------------------------------------

ADMIN_TRIP_SEARCH_MAX_LIMIT = 50


def admin_search_trips(session: Session, *, actor_user_id: int, q: str, limit: int = 20) -> list[Trip]:
    """Staff lookup: a trip id or the start of its code (``trp_ab12`` / ``ab12``), or a driver's ``usr_...`` id
    (that driver's trips, newest departure first). ``ops.view``; read-only."""
    caps = identity_service.get_capabilities(session, actor_user_id)
    identity_service.require_capability(caps, Capability.OPS_VIEW)
    limit = max(1, min(limit, ADMIN_TRIP_SEARCH_MAX_LIMIT))
    text_value = (q or "").strip()
    if text_value.lower().startswith(f"{PublicIdPrefix.USER.value}_"):
        try:
            driver_user_id = identity_service.resolve_user_id(session, text_value)
        except DomainError:
            return []
        stmt = select(Trip).where(Trip.driver_user_id == driver_user_id)
    else:
        span = public_id_fragment_range(text_value, PublicIdPrefix.TRIP)
        if span is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "q", "reason": "not_a_trip_code"})
        stmt = select(Trip).where(Trip.public_id >= span[0], Trip.public_id <= span[1])
    stmt = stmt.order_by(Trip.planned_start_at.desc(), Trip.id.desc()).limit(limit)
    return list(session.execute(stmt).scalars())
