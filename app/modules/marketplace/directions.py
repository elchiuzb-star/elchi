"""Requests along a driver direction, and offers made from it (ADR-0027 Q151-Q153).

The driver named only "where from -> where to" (``trips.directions``). This module answers the two questions the
driver's screen asks:

* **which client requests can I serve?** - every open request of the direction's corridor whose two ends fall on one
  of the direction's confirmed roads, inside the stretch the direction covers. With an active trip the answer also
  says whether the trip reaches the pickup in the client's window (``fits_trip``) or at another time
  (``time_differs``, with the ETA); without one, when the driver would leave to be there on time (``no_trip``).
* **make this offer** - the system takes the direction's active trip, re-times an empty one, or plans a new one
  around the client's pickup time, then submits an ordinary proposal through ``service.submit_proposal`` (every
  existing rule - flags, eligibility, capacity, price band, fee quote, contact filter - applies unchanged).

Nothing here is visible to a client as a "direction": the client sees an offer from "Haydovchi #N" as before (Q138).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.enums import ListingKind, ListingStatus, MatchType, PriceBasis, ServiceType, TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.route_position import position_m
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.models import Listing, ProposalThread
from app.modules.marketplace.schemas import ProposalCreate
from app.modules.trips import directions as trip_directions
from app.modules.trips import service as trips_service
from app.modules.trips.models import DriverDirection, Trip
from app.modules.trips.rules import ResourceDemand

FIT_NO_TRIP, FIT_TRIP, FIT_TIME_DIFFERS = "no_trip", "fits_trip", "time_differs"
#: The offered pickup window around the trip's ETA - the same half-width the native offer form uses (OfferRules).
OFFER_HALF_WINDOW = timedelta(minutes=30)
#: A time proposal is a quarter of an hour either side of the time the driver names (Q153).
TIME_PROPOSAL_HALF_WINDOW = timedelta(minutes=15)
#: An explicit time on an existing trip must be the trip's own ETA, give or take this.
TRIP_TIME_TOLERANCE = timedelta(minutes=30)
FEED_LIMIT = 100


def _now(now: datetime | None) -> datetime:
    return ensure_aware_utc(now) if now is not None else utc_now()


@dataclass(frozen=True)
class DirectionRequest:
    listing: Listing
    match_type: MatchType
    fit: str
    pickup_eta: datetime | None
    suggested_departure_at: datetime | None
    my_thread: ProposalThread | None


@dataclass(frozen=True)
class _Fit:
    """One request on one road of the direction."""

    direction_route: trip_directions.DirectionRoute
    pickup: object  # marketplace EndPlacement
    dropoff: object
    match_type: MatchType


# --- where a request falls on the direction -----------------------------------------------------------------------


def _end_area(session: Session, listing: Listing, which: str) -> tuple[int | None, int | None]:
    """(district id, region id) of a request place."""
    from app.modules.geo.service import districts_by_ids

    district_id = listing.origin_district_id if which == "origin" else listing.destination_district_id
    if district_id is None:
        return None, None
    info = districts_by_ids(session, [district_id]).get(district_id)
    return district_id, (info.region_id if info is not None else None)


def _fit_on_route(
    session: Session, listing: Listing, direction_route: trip_directions.DirectionRoute,
    origin: trip_directions.DirectionEnd, destination: trip_directions.DirectionEnd,
) -> _Fit | None:
    """The request rides inside the direction's stretch of this road: the pickup in the origin area or after it, the
    dropoff in the destination area or before it (Q151)."""
    places = marketplace_service.place_listing_on_route(session, listing, direction_route.route)
    if places is None:
        return None
    pickup, dropoff = places
    o_district, o_region = _end_area(session, listing, "origin")
    d_district, d_region = _end_area(session, listing, "destination")
    pickup_in_origin = origin.covers(district_id=o_district, region_id=o_region)
    dropoff_in_destination = destination.covers(district_id=d_district, region_id=d_region)
    if not (pickup_in_origin or pickup.fraction >= direction_route.origin.fraction):
        return None
    if not (dropoff_in_destination or dropoff.fraction <= direction_route.destination.fraction):
        return None
    match_type = MatchType.EXACT if pickup_in_origin and dropoff_in_destination else MatchType.ON_ROUTE
    return _Fit(direction_route=direction_route, pickup=pickup, dropoff=dropoff, match_type=match_type)


def _best_fit(session: Session, listing: Listing, routes, origin, destination, *, prefer_route_id: int | None) -> _Fit | None:  # noqa: ANN001
    fits = [f for f in (_fit_on_route(session, listing, r, origin, destination) for r in routes) if f is not None]
    if not fits:
        return None
    if prefer_route_id is not None:
        preferred = [f for f in fits if f.direction_route.route.id == prefer_route_id]
        if preferred:
            return preferred[0]
    return fits[0]


def road_match(session: Session, listing: Listing, routes, origin, destination) -> MatchType | None:  # noqa: ANN001
    """Public (ADR-0028 phase 2, the old ``/feed`` and saved searches): does the request ride inside the stretch of a
    road between these two areas, pickup before dropoff - ``exact`` when both its places lie in the areas themselves,
    ``on_route`` when they lie in between. Positions along the road decide."""
    fit = _best_fit(session, listing, routes, origin, destination, prefer_route_id=None)
    return None if fit is None else fit.match_type


def _positions(fit: _Fit) -> tuple[int, int]:
    """ADR-0028: the request's two places as metres along the road of the fit."""
    route = fit.direction_route.route
    return position_m(fit.pickup.fraction, route.distance_m), position_m(fit.dropoff.fraction, route.distance_m)


def _trip_serves(session: Session, trip: Trip, fit: _Fit) -> bool:
    """The trip drives the road the request is on, over both places (ADR-0028: its road span, not its stops)."""
    if trip.route_version_id != fit.direction_route.route.id:
        return False
    pickup_m, dropoff_m = _positions(fit)
    start_m, end_m = trips_service.trip_stretch(session, trip)
    return start_m <= pickup_m and dropoff_m <= end_m


def _trip_eta(session: Session, trip: Trip, fit: _Fit) -> datetime:
    return ensure_aware_utc(marketplace_service._point_eta(session, trip, fit.pickup))  # noqa: SLF001 - same module family


def _span_for(fit: _Fit) -> tuple[int, int]:
    """The road a new trip drives (ADR-0028, metres): the direction's stretch, widened to the request's own
    places when they lie beyond it."""
    dr = fit.direction_route
    distance = dr.route.distance_m
    pickup_m, dropoff_m = _positions(fit)
    start = min(position_m(dr.origin.fraction, distance), pickup_m)
    end = max(position_m(dr.destination.fraction, distance), dropoff_m)
    return start, max(end, start + 1)


def _offset_for(fit: _Fit) -> timedelta:
    start_m, _end_m = _span_for(fit)
    return trip_directions.pickup_offset(fit.direction_route.route, start_m=start_m, place_position_m=_positions(fit)[0])


def _wait(trip: Trip | None) -> timedelta:
    return timedelta(minutes=(trip.pickup_wait_minutes if trip is not None else 10) or 0)


def _in_window(listing: Listing, eta: datetime, wait: timedelta) -> bool:
    start, end = ensure_aware_utc(listing.departure_window_start), ensure_aware_utc(listing.departure_window_end)
    return start - wait <= eta <= end + wait


def _has_room(session: Session, listing: Listing, *, trip: Trip | None, direction: DriverDirection, fit: _Fit) -> bool:
    """Capacity is a hard filter (§8.4): a request the car cannot carry is not shown."""
    if listing.service_type == ServiceType.PASSENGER.value:
        if trip is None:
            return listing.quantity <= direction.seat_capacity
    elif trip is None:
        return direction.cargo_capacity_weight_g > 0 or direction.cargo_capacity_volume_ml > 0
    # ADR-0028 phase 2: the exact road interval the request rides, against the trip's claims.
    pickup_m, dropoff_m = _positions(fit)
    to_m = max(dropoff_m, pickup_m + 1)
    if listing.service_type == ServiceType.PASSENGER.value:
        return not trips_service.check_claim_capacity(session, trip.id, pickup_m, to_m, ResourceDemand(seats=listing.quantity))
    return not trips_service.check_claim_capacity(session, trip.id, pickup_m, to_m, ResourceDemand(cargo_weight_g=1)) or not (
        trips_service.check_claim_capacity(session, trip.id, pickup_m, to_m, ResourceDemand(cargo_volume_ml=1))
    )


def _my_open_thread(session: Session, listing: Listing, driver_user_id: int) -> ProposalThread | None:
    return session.execute(
        select(ProposalThread).where(
            ProposalThread.listing_id == listing.id,
            ProposalThread.driver_user_id == driver_user_id,
            ProposalThread.state == marketplace_service.THREAD_OPEN,
        )
    ).scalars().first()


# --- Q151: the requests along a direction ---------------------------------------------------------------------------


def direction_requests(
    session: Session,
    *,
    driver_user_id: int,
    direction_public_id_value: str,
    service_type: ServiceType,
    date_from: datetime,
    date_to: datetime,
    now: datetime | None = None,
) -> tuple[DriverDirection, Trip | None, list[DirectionRequest]]:
    now = _now(now)
    direction = trip_directions.get_owned_direction(session, direction_public_id_value, driver_user_id)
    trip = trip_directions.active_trip(session, direction)
    if direction.status != trip_directions.STATUS_ACTIVE:
        return direction, trip, []
    routes = trip_directions.direction_routes(session, direction)
    if not routes:
        return direction, trip, []
    origin, destination = trip_directions.direction_ends(session, direction)
    from app.modules.marketplace.feed.service import _blocked_ids  # noqa: PLC0415 - the feed's own block rule

    blocked = _blocked_ids(session, driver_user_id)
    stmt = select(Listing).where(
        Listing.kind == ListingKind.REQUEST.value,
        Listing.service_type == ServiceType(service_type).value,
        Listing.status == ListingStatus.PUBLISHED.value,
        Listing.corridor_id == direction.corridor_id,
        Listing.owner_user_id != driver_user_id,
        Listing.expires_at > now,
        Listing.departure_window_end > now,
        Listing.departure_window_start < ensure_aware_utc(date_to),
        Listing.departure_window_end > ensure_aware_utc(date_from),
    )
    if blocked:
        stmt = stmt.where(Listing.owner_user_id.notin_(sorted(blocked)))
    candidates = list(session.execute(stmt.order_by(Listing.departure_window_start, Listing.id).limit(FEED_LIMIT)).scalars())
    moving = trip is not None and marketplace_service.trip_is_moving(trip)

    items: list[DirectionRequest] = []
    for listing in candidates:
        fit = _best_fit(session, listing, routes, origin, destination, prefer_route_id=trip.route_version_id if trip else None)
        if fit is None:
            continue
        thread = _my_open_thread(session, listing, driver_user_id)
        if trip is not None and _trip_serves(session, trip, fit):
            if not _has_room(session, listing, trip=trip, direction=direction, fit=fit):
                continue
            if moving:
                try:
                    eta = marketplace_service.assert_pickup_ahead(
                        session, listing=listing, trip=trip, pickup_place=fit.pickup, now=now
                    )
                except DomainError:
                    continue  # Q154: the car is already past this pickup
            else:
                eta = _trip_eta(session, trip, fit)
            on_time = _in_window(listing, eta, _wait(trip))
            if not on_time and not marketplace_service.time_proposal_possible(listing, eta):
                continue  # Q157: too far from what the client asked to be offered even as a time proposal
            items.append(DirectionRequest(
                listing=listing, match_type=fit.match_type, fit=FIT_TRIP if on_time else FIT_TIME_DIFFERS,
                pickup_eta=eta, suggested_departure_at=None, my_thread=thread,
            ))
            continue
        if trip is not None and not _retimable(session, trip):
            continue  # the busy trip cannot reach it; the next trip is planned once this one is done
        if not _has_room(session, listing, trip=None, direction=direction, fit=fit):
            continue
        offset = _offset_for(fit)
        departure = trip_directions.departure_for(ensure_aware_utc(listing.departure_window_start), offset, now)
        eta = departure + offset
        if not _in_window(listing, eta, _wait(None)) and not marketplace_service.time_proposal_possible(listing, eta):
            continue  # Q157
        items.append(DirectionRequest(
            listing=listing, match_type=fit.match_type,
            fit=FIT_NO_TRIP if _in_window(listing, eta, _wait(None)) else FIT_TIME_DIFFERS,
            pickup_eta=eta, suggested_departure_at=departure, my_thread=thread,
        ))
    order = {FIT_TRIP: 0, FIT_NO_TRIP: 1, FIT_TIME_DIFFERS: 2}
    items.sort(key=lambda item: (order[item.fit], item.pickup_eta or ensure_aware_utc(item.listing.departure_window_start), item.listing.id))
    return direction, trip, items


# --- Q152/Q153: an offer from a direction ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectionOffer:
    thread: ProposalThread
    trip: Trip
    trip_created: bool
    trip_retimed: bool
    time_proposal: bool


def _retimable(session: Session, trip: Trip) -> bool:
    """An empty planned trip: no capacity reserved and no open negotiation quoted against its time."""
    if trip.status != TripStatus.PLANNED.value:
        return False
    if trips_service.trip_has_claims(session, trip.id):  # ADR-0028: any booking ever - its road stretch is locked
        return False
    open_thread = session.execute(
        select(ProposalThread.id).where(
            ProposalThread.trip_id == trip.id, ProposalThread.state == marketplace_service.THREAD_OPEN
        ).limit(1)
    ).scalar_one_or_none()
    return open_thread is None


def _offer_window(listing: Listing, eta: datetime, pickup_at: datetime | None) -> tuple[datetime, datetime]:
    """The pickup window offered: around the trip's real ETA. A named time (Q153) only planned the trip; the window
    is still the time the car will actually be there."""
    if pickup_at is not None:
        return eta - TIME_PROPOSAL_HALF_WINDOW, eta + TIME_PROPOSAL_HALF_WINDOW
    start = max(ensure_aware_utc(listing.departure_window_start), eta - OFFER_HALF_WINDOW)
    end = min(ensure_aware_utc(listing.departure_window_end), eta + OFFER_HALF_WINDOW)
    if end <= start:
        raise DomainError(
            ErrorCode.TIME_WINDOW_CONFLICT,
            details={
                "reason": "trip_time_differs", "eta": eta.isoformat(),
                # Q157: whether resending with pickup_at = eta can work at all
                "time_proposal_possible": marketplace_service.time_proposal_possible(listing, eta),
            },
        )
    return start, end


def _windows_meet(listing: Listing, start: datetime, end: datetime) -> bool:
    return max(ensure_aware_utc(listing.departure_window_start), start) < min(ensure_aware_utc(listing.departure_window_end), end)


def offer_from_direction(
    session: Session,
    *,
    driver_user_id: int,
    direction_public_id_value: str,
    listing_public_id_value: str,
    unit_price_minor: int,
    message: str | None,
    pickup_at: datetime | None,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
    filter_hits: list | None = None,
) -> DirectionOffer:
    """Lock order (ADR-0017 + ADR-0027): users -> driver_directions -> trips -> listings -> threads."""
    now = _now(now)
    identity_service.lock_user_eligibility(session, [driver_user_id], mode="share")
    direction = trip_directions.get_owned_direction(session, direction_public_id_value, driver_user_id, mode="lock")
    if direction.status != trip_directions.STATUS_ACTIVE:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "driver_direction", "from": direction.status})
    listing = marketplace_service.get_listing_by_public_id(session, listing_public_id_value)
    if listing.kind != ListingKind.REQUEST.value or listing.corridor_id != direction.corridor_id:
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "request_not_on_direction"})
    if pickup_at is not None and ensure_aware_utc(pickup_at) <= now:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "pickup_at", "reason": "in_the_past"})
    if pickup_at is not None and not _in_window(listing, ensure_aware_utc(pickup_at), timedelta(0)):
        # Q157: refuse before any trip is planned or moved for a time the client could never be offered
        marketplace_service.assert_time_proposal_in_range(listing, ensure_aware_utc(pickup_at))
    routes = trip_directions.direction_routes(session, direction)
    origin, destination = trip_directions.direction_ends(session, direction)
    trip = trip_directions.active_trip(session, direction)
    fit = _best_fit(session, listing, routes, origin, destination, prefer_route_id=trip.route_version_id if trip else None)
    if fit is None:
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "request_not_on_direction"})

    created = retimed = False
    reuse = False
    if trip is not None and _trip_serves(session, trip, fit):
        eta = _trip_eta(session, trip, fit)
        wanted = ensure_aware_utc(pickup_at) if pickup_at is not None else None
        on_time = _in_window(listing, eta, _wait(trip)) if wanted is None else abs(wanted - eta) <= TRIP_TIME_TOLERANCE
        # An empty planned trip follows the client the driver is answering now; a trip with passengers keeps its
        # time, and a different time on it is a time proposal at the trip's own ETA (Q153).
        reuse = on_time or not _retimable(session, trip)
        if reuse and wanted is not None and not on_time:
            raise DomainError(ErrorCode.TIME_WINDOW_CONFLICT, details={
                "reason": "trip_time_differs", "eta": eta.isoformat(),
                "time_proposal_possible": marketplace_service.time_proposal_possible(listing, eta),
            })
    elif trip is not None and not _retimable(session, trip):
        raise DomainError(
            ErrorCode.SCHEDULE_CONFLICT,
            details={"reason": "active_trip_cannot_serve", "trip_id": trips_service.trip_public_id(trip)},
        )
    if reuse:
        trip = trips_service.lock_trip(session, trip.id)
        if marketplace_service.trip_is_moving(trip):
            # Q154: "the car has passed it" is the answer, before any window is built around a time already gone.
            marketplace_service.assert_pickup_ahead(session, listing=listing, trip=trip, pickup_place=fit.pickup, now=now)
    else:
        start_m, end_m = _span_for(fit)
        offset = _offset_for(fit)
        target = ensure_aware_utc(pickup_at) if pickup_at is not None else ensure_aware_utc(listing.departure_window_start)
        departure = trip_directions.departure_for(target, offset, now)
        if trip is None:
            trip = trip_directions.create_trip_for_direction(
                session, direction, fit.direction_route.route, start_m=start_m, end_m=end_m, departure=departure, now=now
            )
            created = True
        else:
            trip = trip_directions.retime_trip(
                session, direction, trips_service.lock_trip(session, trip.id), fit.direction_route.route,
                start_m=start_m, end_m=end_m, departure=departure, now=now,
            )
            retimed = True
    eta = _trip_eta(session, trip, fit)

    window_start, window_end = _offer_window(listing, eta, pickup_at)
    outside = not _windows_meet(listing, window_start, window_end)
    data = ProposalCreate(
        trip_id=trips_service.trip_public_id(trip),
        pickup_window_start=window_start,
        pickup_window_end=window_end,
        quantity=listing.quantity,
        price_basis=PriceBasis(listing.price_basis),
        unit_price_minor=unit_price_minor,
        message=message,
        outside_request_window=outside,
    )
    thread = marketplace_service.submit_proposal(
        session, listing_public_id=listing_public_id_value, actor_user_id=driver_user_id, data=data, now=now,
        warnings=warnings, filter_hits=filter_hits,
    )
    return DirectionOffer(thread=thread, trip=trip, trip_created=created, trip_retimed=retimed, time_proposal=outside)

