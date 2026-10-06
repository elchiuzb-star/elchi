"""Driver directions (ADR-0027): a driver names "where from -> where to", the system does the rest.

Q150: the driver gives two ends - a region and, unless the region is a city without districts, a district - and the
car. No time, coordinate, stop, corridor or route is asked. This module resolves the ends onto the confirmed roads
of an open corridor (the same projection Q88 uses for a client's map point) and keeps the direction.

Q152: when the driver makes an offer from a direction, the marketplace asks this module for the direction's trip -
the active one, or a new one planned around the client's pickup time (``plan_trip_create``). Trips stay the internal
model they always were (Q93, Q138): the direction is never shown to a client.

Placement rules (one end on one confirmed route):

* every active stop of the corridor that sits in the end's district (or region, for a region-only end) and is on
  the route is a candidate at its own position on the line;
* the district (or region) centre is a candidate when it projects onto the route within the corridor's radius;
* the origin takes the earliest candidate along the road, the destination the latest - the stretch of road the
  driver covers is as long as the two areas allow, never longer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import Capability, TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.identity import service as identity_service
from app.modules.platform.service import constraint_name_of
from app.modules.trips import service as trips_service
from app.modules.trips.models import DriverDirection, Trip, Vehicle
from app.modules.trips.rules import DEFAULT_PICKUP_WAIT_MINUTES, VehicleVerificationStatus
from app.modules.trips.schemas import (
    DirectionEndInput,
    DriverDirectionCreate,
    DriverDirectionPatch,
    TripCreate,
    TripPatch,
    TripStopInput,
)

LIVE_ENDS_INDEX = "uq_driver_directions_live_ends"
STATUS_ACTIVE, STATUS_PAUSED, STATUS_ARCHIVED = "active", "paused", "archived"
#: Trips a direction keeps using for new offers (Q152, Q154). Interrupted trips take no new business.
DIRECTION_TRIP_STATUSES = (TripStatus.PLANNED.value, TripStatus.BOARDING.value, TripStatus.IN_PROGRESS.value)

# The same defaults the native trip form sends (android-app TripRules: dwell 5 min, 15 min / 5 km detour budget,
# 10 min pickup wait) - a system-made trip must not behave differently from one a driver typed in.
DWELL_MINUTES = 5
MAX_DETOUR_MINUTES = 15
MAX_DETOUR_M = 5_000
#: A system-made trip never departs sooner than this, so the driver has time to see it and start boarding.
MIN_DEPARTURE_LEAD = timedelta(minutes=15)
#: How many confirmed roads of one corridor are considered (same bound as the Q88 resolver).
ROUTES_PER_CORRIDOR = 5


def _now(now: datetime | None) -> datetime:
    return ensure_aware_utc(now) if now is not None else utc_now()


def direction_public_id(direction: DriverDirection) -> str:
    return format_public_id(PublicIdPrefix.DRIVER_DIRECTION, direction.public_id)


# --- ends ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectionEnd:
    """A region and an optional district. ``covers`` answers "is this district inside this end"."""

    region_id: int
    region_api_id: str
    region_name_uz: str
    region_name_ru: str | None
    region_center: tuple[float, float] | None
    district_id: int | None
    district_api_id: str | None
    district_name_uz: str | None
    district_name_ru: str | None
    district_center: tuple[float, float] | None

    def covers(self, *, district_id: int | None, region_id: int | None) -> bool:
        if self.district_id is not None:
            return district_id == self.district_id
        return region_id == self.region_id

    @property
    def center(self) -> tuple[float, float] | None:
        return self.district_center if self.district_id is not None else self.region_center


def _regions_by_id(session: Session) -> dict[int, object]:
    from app.modules.geo.service import list_regions

    return {region.id: region for region in list_regions(session, active_only=False)}


def _end(region, district) -> DirectionEnd:  # noqa: ANN001 - geo RegionInfo / DistrictInfo
    region_center = (region.center_lat, region.center_lng) if region.center_lat is not None else None
    district_center = (
        (district.center_lat, district.center_lng) if district is not None and district.center_lat is not None else None
    )
    return DirectionEnd(
        region_id=region.id,
        region_api_id=region.api_id,
        region_name_uz=region.name_uz,
        region_name_ru=region.name_ru,
        region_center=region_center,
        district_id=district.id if district is not None else None,
        district_api_id=district.api_id if district is not None else None,
        district_name_uz=district.name_uz if district is not None else None,
        district_name_ru=district.name_ru if district is not None else None,
        district_center=district_center,
    )


def resolve_end(session: Session, data: DirectionEndInput, field: str) -> DirectionEnd:
    from app.modules.geo.service import get_district_by_api_id, get_region_by_api_id

    try:
        region = get_region_by_api_id(session, data.region_id)
    except DomainError:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": f"{field}.region_id"}) from None
    district = None
    if data.district_id:
        try:
            district = get_district_by_api_id(session, data.district_id)
        except DomainError:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": f"{field}.district_id"}) from None
        if district.region_id != region.id:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, details={"field": f"{field}.district_id", "reason": "district_outside_region"}
            )
    elif region.requires_district:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": f"{field}.district_id", "reason": "district_required"})
    return _end(region, district)


def stored_end(session: Session, region_id: int, district_id: int | None, *, regions: dict | None = None) -> DirectionEnd:
    from app.modules.geo.service import districts_by_ids

    regions = regions if regions is not None else _regions_by_id(session)
    district = districts_by_ids(session, [district_id]).get(district_id) if district_id else None
    return _end(regions[region_id], district)


# --- placing ends on a road -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutePlace:
    """Where an area meets a confirmed road: position on the line and the segment it falls in."""

    fraction: float
    seq_before: int
    seq_after: int
    cumulative_duration_s: int
    offset_m: int


@dataclass(frozen=True)
class DirectionRoute:
    """One confirmed road of the direction's corridor with both ends placed on it, origin before destination."""

    route: object  # geo RouteVersionInfo
    origin: RoutePlace
    destination: RoutePlace


def _stop_place(route, stop_id: int) -> RoutePlace | None:  # noqa: ANN001
    stops = list(route.stops)
    for index, stop in enumerate(stops):
        if stop.stop_id == stop_id:
            after = stops[min(index + 1, len(stops) - 1)]
            return RoutePlace(
                fraction=float(stop.line_fraction), seq_before=stop.seq, seq_after=after.seq,
                cumulative_duration_s=stop.cumulative_duration_s, offset_m=0,
            )
    return None


def _point_place(session: Session, route, point: tuple[float, float], radius_m: int) -> RoutePlace | None:  # noqa: ANN001
    from app.modules.geo.geometry import LatLng
    from app.modules.geo.service import project_point_on_route

    projection = project_point_on_route(
        session, route_version_id=route.id, point=LatLng(lat=point[0], lng=point[1]), max_offset_m=radius_m
    )
    if projection is None:
        return None
    return RoutePlace(
        fraction=projection.fraction, seq_before=projection.seq_before, seq_after=projection.seq_after,
        cumulative_duration_s=projection.cumulative_duration_s, offset_m=projection.offset_m,
    )


def _place_end(
    session: Session,
    route,  # noqa: ANN001 - geo RouteVersionInfo
    end: DirectionEnd,
    *,
    stops: list,
    district_regions: dict[int, int],
    radius_m: int,
    first: bool,
) -> RoutePlace | None:
    candidates: list[RoutePlace] = []
    for stop in stops:
        if end.covers(district_id=stop.district_id, region_id=district_regions.get(stop.district_id)):
            place = _stop_place(route, stop.id)
            if place is not None:
                candidates.append(place)
    if end.center is not None:
        place = _point_place(session, route, end.center, radius_m)
        if place is not None:
            candidates.append(place)
    if not candidates:
        return None
    return (min if first else max)(candidates, key=lambda place: place.fraction)


def _routes_for(session: Session, corridor, origin: DirectionEnd, destination: DirectionEnd) -> list[DirectionRoute]:  # noqa: ANN001
    from app.modules.geo.service import (
        corridor_point_offset_m,
        districts_by_ids,
        get_route_version,
        list_corridor_routes,
        list_corridor_stops,
    )

    stops = list_corridor_stops(session, corridor)
    district_regions = {did: info.region_id for did, info in districts_by_ids(session, {s.district_id for s in stops}).items()}
    radius = corridor_point_offset_m(session, corridor.id)
    result: list[DirectionRoute] = []
    for ref in list_corridor_routes(session, corridor, limit=ROUTES_PER_CORRIDOR):
        route = get_route_version(session, ref.id)
        o = _place_end(session, route, origin, stops=stops, district_regions=district_regions, radius_m=radius, first=True)
        d = _place_end(session, route, destination, stops=stops, district_regions=district_regions, radius_m=radius, first=False)
        if o is not None and d is not None and o.fraction < d.fraction:
            result.append(DirectionRoute(route=route, origin=o, destination=d))
    return result


def resolve_corridor(session: Session, origin: DirectionEnd, destination: DirectionEnd):  # noqa: ANN201
    """The open corridor whose confirmed roads carry this direction; ``ROUTE_MISMATCH`` when none does.

    Several may qualify (a long road and a branch): the one whose roads the two areas sit closest to wins, ties on
    corridor id, so the same two ends always resolve the same way.
    """
    from app.modules.geo.service import list_public_corridors

    best = None
    for corridor, _services, _stops in sorted(list_public_corridors(session), key=lambda row: row[0].id):
        routes = _routes_for(session, corridor, origin, destination)
        if not routes:
            continue
        cost = min(r.origin.offset_m + r.destination.offset_m for r in routes)
        if best is None or cost < best[0]:
            best = (cost, corridor, routes)
    if best is None:
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "no_corridor_serves_direction"})
    return best[1], best[2]


def direction_ends(session: Session, direction: DriverDirection, *, regions: dict | None = None) -> tuple[DirectionEnd, DirectionEnd]:
    regions = regions if regions is not None else _regions_by_id(session)
    return (
        stored_end(session, direction.origin_region_id, direction.origin_district_id, regions=regions),
        stored_end(session, direction.destination_region_id, direction.destination_district_id, regions=regions),
    )


def direction_routes(session: Session, direction: DriverDirection) -> list[DirectionRoute]:
    """The direction's roads as they stand now (a route confirmed later is picked up; a closed corridor gives none)."""
    from app.modules.geo.service import get_corridor

    origin, destination = direction_ends(session, direction)
    corridor = get_corridor(session, direction.corridor_id)
    if not corridor.is_operable:
        return []
    return _routes_for(session, corridor, origin, destination)


def via_district_names(session: Session, direction_route: DirectionRoute) -> list[str]:
    """Districts of the road's stops strictly between the two ends - "Samarqand, Chiroqchi orqali"."""
    from app.modules.geo.service import get_stops

    route = direction_route.route
    inner = [s for s in route.stops if direction_route.origin.fraction < float(s.line_fraction) < direction_route.destination.fraction]
    infos = get_stops(session, [s.stop_id for s in inner])
    names: list[str] = []
    for stop in inner:
        info = infos.get(stop.stop_id)
        if info is not None and info.district_name_uz not in names:
            names.append(info.district_name_uz)
    return names


# --- commands ---------------------------------------------------------------------------------------------------------


def _approved_vehicle(session: Session, driver_user_id: int, vehicle_public_id: str | None) -> Vehicle:
    vehicles = trips_service.list_driver_vehicles(session, driver_user_id)
    if vehicle_public_id is not None:
        parse_public_id(vehicle_public_id, PublicIdPrefix.VEHICLE)
        chosen = next((v for v in vehicles if trips_service.vehicle_public_id(v) == vehicle_public_id), None)
        if chosen is None:
            raise DomainError(ErrorCode.NOT_FOUND, details={"field": "vehicle_id"})
    else:
        approved = [v for v in vehicles if v.verification_status == VehicleVerificationStatus.APPROVED.value]
        if len(approved) != 1:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                details={"field": "vehicle_id", "reason": "no_approved_vehicle" if not approved else "choose_vehicle"},
            )
        chosen = approved[0]
    if chosen.verification_status != VehicleVerificationStatus.APPROVED.value:
        raise DomainError(ErrorCode.VEHICLE_NOT_ELIGIBLE, details={"verification_status": chosen.verification_status})
    return chosen


def _capacity(vehicle: Vehicle, seats: int | None, weight_g: int | None, volume_ml: int | None) -> tuple[int, int, int]:
    values = (
        ("seat_capacity", vehicle.seat_capacity if seats is None else seats, vehicle.seat_capacity),
        ("cargo_capacity_weight_g", (vehicle.cargo_max_weight_g or 0) if weight_g is None else weight_g, vehicle.cargo_max_weight_g or 0),
        ("cargo_capacity_volume_ml", (vehicle.cargo_max_volume_ml or 0) if volume_ml is None else volume_ml, vehicle.cargo_max_volume_ml or 0),
    )
    for field, requested, limit in values:
        if requested > limit:
            raise DomainError(ErrorCode.VEHICLE_NOT_ELIGIBLE, details={"field": field, "requested": requested, "vehicle_limit": limit})
    seats_v, weight_v, volume_v = (value for _f, value, _l in values)
    if seats_v <= 0 and weight_v <= 0 and volume_v <= 0:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "seat_capacity", "reason": "no_capacity"})
    return seats_v, weight_v, volume_v


def _duplicate(session: Session, driver_user_id: int, origin: DirectionEnd, destination: DirectionEnd) -> DomainError:
    existing = session.execute(
        select(DriverDirection.public_id).where(
            DriverDirection.driver_user_id == driver_user_id,
            DriverDirection.origin_region_id == origin.region_id,
            DriverDirection.origin_district_id.is_not_distinct_from(origin.district_id),
            DriverDirection.destination_region_id == destination.region_id,
            DriverDirection.destination_district_id.is_not_distinct_from(destination.district_id),
            DriverDirection.status != STATUS_ARCHIVED,
        )
    ).scalar_one_or_none()
    details: dict = {"reason": "direction_exists"}
    if existing is not None:
        details["direction_id"] = format_public_id(PublicIdPrefix.DRIVER_DIRECTION, existing)
    return DomainError(ErrorCode.VALIDATION_ERROR, details=details)


def create_direction(session: Session, *, driver_user_id: int, data: DriverDirectionCreate, now: datetime | None = None) -> DriverDirection:
    """Q150. Users row first (ADR-0017): serialises two creates of the same driver; the unique index is the backstop."""
    now = _now(now)
    identity_service.lock_user_eligibility(session, [driver_user_id], mode="update")
    identity_service.require_capability(identity_service.get_capabilities(session, driver_user_id, now=now), Capability.TRIP_CREATE)
    origin = resolve_end(session, data.origin, "origin")
    destination = resolve_end(session, data.destination, "destination")
    if origin.region_id == destination.region_id and origin.district_id == destination.district_id:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "destination", "reason": "same_as_origin"})
    vehicle = _approved_vehicle(session, driver_user_id, data.vehicle_id)
    seats, weight, volume = _capacity(vehicle, data.seat_capacity, data.cargo_capacity_weight_g, data.cargo_capacity_volume_ml)
    corridor, _routes = resolve_corridor(session, origin, destination)
    duplicate = _duplicate(session, driver_user_id, origin, destination)
    if "direction_id" in (duplicate.details or {}):
        raise duplicate
    direction = DriverDirection(
        public_id=new_public_uuid(),
        driver_user_id=driver_user_id,
        vehicle_id=vehicle.id,
        corridor_id=corridor.id,
        origin_region_id=origin.region_id,
        origin_district_id=origin.district_id,
        destination_region_id=destination.region_id,
        destination_district_id=destination.district_id,
        seat_capacity=seats,
        cargo_capacity_weight_g=weight,
        cargo_capacity_volume_ml=volume,
        status=STATUS_ACTIVE,
        version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(direction)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if constraint_name_of(exc) == LIVE_ENDS_INDEX:
            raise _duplicate(session, driver_user_id, origin, destination) from None
        raise
    return direction


def list_directions(session: Session, driver_user_id: int, *, include_archived: bool = False) -> list[DriverDirection]:
    stmt = select(DriverDirection).where(DriverDirection.driver_user_id == driver_user_id)
    if not include_archived:
        stmt = stmt.where(DriverDirection.status != STATUS_ARCHIVED)
    return list(session.execute(stmt.order_by(DriverDirection.id.desc())).scalars())


def list_directions_for_admin(session: Session, *, driver_user_id: int | None, limit: int = 50) -> list[DriverDirection]:
    stmt = select(DriverDirection)
    if driver_user_id is not None:
        stmt = stmt.where(DriverDirection.driver_user_id == driver_user_id)
    return list(session.execute(stmt.order_by(DriverDirection.id.desc()).limit(limit)).scalars())


def get_owned_direction(
    session: Session, public_id: str, driver_user_id: int, *, mode: Literal["read", "lock"] = "read"
) -> DriverDirection:
    uuid_value = parse_public_id(public_id, PublicIdPrefix.DRIVER_DIRECTION)
    stmt = select(DriverDirection).where(DriverDirection.public_id == uuid_value)
    if mode == "lock":
        stmt = stmt.with_for_update(key_share=True)
    direction = session.execute(stmt).scalar_one_or_none()
    if direction is None or direction.driver_user_id != driver_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    return direction


def patch_direction(
    session: Session, *, direction_public_id_value: str, actor_user_id: int, data: DriverDirectionPatch, now: datetime | None = None
) -> DriverDirection:
    now = _now(now)
    identity_service.lock_user_eligibility(session, [actor_user_id], mode="share")
    direction = get_owned_direction(session, direction_public_id_value, actor_user_id, mode="lock")
    if direction.version != data.expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": direction.version})
    if direction.status == STATUS_ARCHIVED:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "driver_direction", "from": STATUS_ARCHIVED})
    if any(v is not None for v in (data.seat_capacity, data.cargo_capacity_weight_g, data.cargo_capacity_volume_ml)):
        vehicle = trips_service.get_vehicle(session, direction.vehicle_id)
        seats, weight, volume = _capacity(
            vehicle,
            data.seat_capacity if data.seat_capacity is not None else direction.seat_capacity,
            data.cargo_capacity_weight_g if data.cargo_capacity_weight_g is not None else direction.cargo_capacity_weight_g,
            data.cargo_capacity_volume_ml if data.cargo_capacity_volume_ml is not None else direction.cargo_capacity_volume_ml,
        )
        direction.seat_capacity, direction.cargo_capacity_weight_g, direction.cargo_capacity_volume_ml = seats, weight, volume
    if data.status is not None and data.status != direction.status:
        if data.status == STATUS_ACTIVE:
            # Re-activating a paused direction is new business: the same checks as creating it.
            identity_service.require_capability(
                identity_service.get_capabilities(session, actor_user_id, now=now), Capability.TRIP_CREATE
            )
        direction.status = data.status
    direction.version += 1
    direction.updated_at = now
    session.flush()
    return direction


# --- the direction's trip -----------------------------------------------------------------------------------------------


def direction_trips(session: Session, direction: DriverDirection) -> list[Trip]:
    """Trips made from this direction that still take new business, soonest first (Q152, Q154)."""
    return list(
        session.execute(
            select(Trip)
            .where(Trip.direction_id == direction.id, Trip.status.in_(DIRECTION_TRIP_STATUSES))
            .order_by(Trip.planned_start_at, Trip.id)
        ).scalars()
    )


def active_trip(session: Session, direction: DriverDirection) -> Trip | None:
    trips = direction_trips(session, direction)
    return trips[0] if trips else None


def seats_booked(session: Session, trip: Trip) -> int:
    loads = trips_service.get_segment_loads(session, trip.id)
    return max((load.seats_used for load in loads), default=0)


def _arrival_offsets(route, from_seq: int, to_seq: int) -> list[tuple[object, timedelta]]:  # noqa: ANN001
    """Each included route stop with its arrival offset from the departure (driving time + dwell at earlier stops).

    The same rule as ``geo.planned_occurrences_from_route_version``: no dwell before the first stop, one dwell
    per intermediate stop already passed.
    """
    included = [s for s in route.stops if from_seq <= s.seq <= to_seq]
    base = included[0].cumulative_duration_s
    return [
        (stop, timedelta(seconds=stop.cumulative_duration_s - base, minutes=DWELL_MINUTES * max(0, index - 1)))
        for index, stop in enumerate(included)
    ]


def pickup_offset(route, *, from_seq: int, to_seq: int, place_seq_before: int, place_cumulative_s: int) -> timedelta:  # noqa: ANN001
    """Time from the trip's departure to a place on the road, interpolated inside its segment."""
    offsets = _arrival_offsets(route, from_seq, to_seq)
    by_seq = {stop.seq: (stop, offset) for stop, offset in offsets}
    before = by_seq.get(place_seq_before)
    if before is None:
        return offsets[0][1]
    stop, offset = before
    extra = max(0, place_cumulative_s - stop.cumulative_duration_s)
    dwell = timedelta(minutes=DWELL_MINUTES) if offsets[0][0].seq != stop.seq else timedelta(0)
    return offset + (dwell if extra else timedelta(0)) + timedelta(seconds=extra)


def departure_for(pickup_at: datetime, offset: timedelta, now: datetime) -> datetime:
    """When to leave so the car is at the place at ``pickup_at``; never sooner than MIN_DEPARTURE_LEAD from now."""
    departure = ensure_aware_utc(pickup_at) - offset
    earliest = now + MIN_DEPARTURE_LEAD
    departure = max(departure, earliest)
    return departure.replace(second=0, microsecond=0) + (timedelta(minutes=1) if departure.second or departure.microsecond else timedelta(0))


def plan_trip_create(
    direction: DriverDirection, route, *, vehicle_public_id: str, from_seq: int, to_seq: int, departure: datetime  # noqa: ANN001
) -> TripCreate:
    from app.modules.geo.service import stop_api_id

    offsets = _arrival_offsets(route, from_seq, to_seq)
    stops = [
        TripStopInput(
            stop_id=stop_api_id(stop.stop_public_id), seq=index + 1, planned_arrival_at=departure + offset,
            dwell_minutes=DWELL_MINUTES if 0 < index < len(offsets) - 1 else 0,
        )
        for index, (stop, offset) in enumerate(offsets)
    ]
    end = departure + offsets[-1][1]
    if end <= departure:
        end = departure + timedelta(minutes=1)
    return TripCreate(
        vehicle_id=vehicle_public_id,
        route_version_id=route.api_id,
        stops=stops,
        planned_start_at=departure,
        planned_end_at=end,
        seat_capacity=direction.seat_capacity,
        cargo_capacity_weight_g=direction.cargo_capacity_weight_g or None,
        cargo_capacity_volume_ml=direction.cargo_capacity_volume_ml or None,
        max_detour_minutes=MAX_DETOUR_MINUTES,
        max_detour_m=MAX_DETOUR_M,
        pickup_wait_minutes=DEFAULT_PICKUP_WAIT_MINUTES,
    )


def create_trip_for_direction(
    session: Session, direction: DriverDirection, route, *, from_seq: int, to_seq: int, departure: datetime, now: datetime  # noqa: ANN001
) -> Trip:
    vehicle = trips_service.get_vehicle(session, direction.vehicle_id)
    data = plan_trip_create(
        direction, route, vehicle_public_id=trips_service.vehicle_public_id(vehicle), from_seq=from_seq, to_seq=to_seq,
        departure=departure,
    )
    return trips_service.create_trip(session, driver_user_id=direction.driver_user_id, data=data, now=now, direction_id=direction.id)


def retime_trip(
    session: Session, direction: DriverDirection, trip: Trip, route, *, from_seq: int, to_seq: int, departure: datetime, now: datetime  # noqa: ANN001
) -> Trip:
    """Move an empty planned trip (no booking, no open offer) to a new time and stretch - the driver's plan follows the
    client they are now answering. ``patch_trip`` refuses it the moment any capacity is reserved (Q63)."""
    vehicle = trips_service.get_vehicle(session, direction.vehicle_id)
    plan = plan_trip_create(
        direction, route, vehicle_public_id=trips_service.vehicle_public_id(vehicle), from_seq=from_seq, to_seq=to_seq,
        departure=departure,
    )
    return trips_service.patch_trip(
        session,
        trip_public_id_value=trips_service.trip_public_id(trip),
        actor_user_id=direction.driver_user_id,
        data=TripPatch(
            expected_version=trip.version, planned_start_at=plan.planned_start_at, planned_end_at=plan.planned_end_at,
            stops=plan.stops,
        ),
        now=now,
    )
