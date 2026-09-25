"""Feed (M1), listing matches (M2), saved searches (M3-M5) and the saved-search matcher (A5, wave 3).

Spec §6.3-§6.6, §8.1-§8.4; AC18, AC35, AC36; Q21, Q40, Q43, Q46.

Boundaries (AGENTS §4, WAVE1_CARDS "Wave 3"):
* marketplace / trips / geo data is read through their service functions and ports or read-only queries; this module
  writes only ``saved_searches`` / ``saved_search_notifications`` and outbox events (``platform.service``).
* Matching never calls a router and never inserts detours: matches are verified stops only (``exact``/``on_route``,
  plus the separate ``alternative`` group). Production never shows ``detour`` (Q46); elsewhere the page is marked
  ``ROUTING_UNAVAILABLE`` because detours were not measured (AC35: no fake match).
* Q21: trip offers of drivers that are not eligible are not shown (nor pushed). AC18: no online/last-seen filter.
* Reputation comes from A12 ``trust_support.service.reputation_summaries`` (lazy); when it does not exist yet every
  summary is the zero ``ReputationSummary`` (label ``new_verified``) - never a default rating (§8.2, AC36).
* Domain functions never commit.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.contracts.communications import DispatchedEvent
from app.contracts.enums import (
    Capability,
    EventType,
    FeatureFlagKey,
    FeedSide,
    FeedSort,
    ListingKind,
    ListingStatus,
    MatchGroup,
    MatchReason,
    MatchType,
    ServiceType,
    TripStatus,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventEnvelope
from app.contracts.feed import (
    FEED_DEFAULT_LIMIT,
    FEED_MAX_LIMIT,
    NEUTRAL_FIT_SCORE,
    RANKING_VERSION,
    SAVED_SEARCH_MAX_PER_USER,
    SAVED_SEARCH_MAX_WINDOW_DAYS,
)
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.contracts.trust import ReputationSummary
from app.modules.geo.matching import ALTERNATIVE_TIME_TOLERANCE, evaluate_route_match
from app.modules.geo.types import MatchRequest, OccurrenceTiming, RouteMatchResult, TripRouteContext
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.feed import rules
from app.modules.marketplace.feed.models import SavedSearch, SavedSearchNotification
from app.modules.marketplace.feed.schemas import MATCH_SCOPE_CONFIRMED_STOPS, SavedSearchCreate
from app.modules.marketplace.models import Listing
from app.modules.marketplace.ports import get_ports
from app.modules.marketplace.rules import parcel_volume_ml
from app.modules.platform import service as platform_service
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip

logger = logging.getLogger(__name__)

__all__ = [
    "FeedCriteria",
    "FeedPage",
    "RankedItem",
    "SegmentAvailability",
    "create_saved_search",
    "delete_saved_search",
    "expire_saved_searches",
    "feed",
    "list_saved_searches",
    "listing_matches",
    "load_reputations",
    "match_saved_searches_for_listing",
    "region_public_ids",
    "saved_search_match_still_relevant",
    "saved_search_public_id",
]

SAVED_SEARCH_LIMIT_CONSTRAINT = "saved_search_limit"
NOTIFICATION_UNIQUE = "uq_saved_search_notifications_search_listing"
SIDE_KIND: dict[FeedSide, ListingKind] = {FeedSide.OFFERS: ListingKind.TRIP_OFFER, FeedSide.REQUESTS: ListingKind.REQUEST}
KIND_SIDE: dict[ListingKind, FeedSide] = {kind: side for side, kind in SIDE_KIND.items()}
PUBLISHED = ListingStatus.PUBLISHED.value
PLANNED = TripStatus.PLANNED.value
MATCHABLE_OWNER_STATUSES = (ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value)
CONSUMER_REGION_STOP_LIMIT = 200
_GEO_RANK = {MatchType.EXACT: 0, MatchType.ON_ROUTE: 1, MatchType.DETOUR: 2, MatchType.ALTERNATIVE: 3}


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _validation(field_name: str, reason: str, **details: object) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_ERROR, details={"field": field_name, "reason": reason, **details})


# --- reputation (A12, lazy) -----------------------------------------------------------------------------------------


def load_reputations(
    session: Session, user_ids: Iterable[int], *, service_type: ServiceType
) -> dict[int, ReputationSummary]:
    """A12 summaries; a zero summary (no rating, ``new_verified``) for every user A12 does not return or when the
    A12 function does not exist yet. Never an invented rating (§8.2, AC36)."""
    ids = sorted({int(user_id) for user_id in user_ids})
    if not ids:
        return {}
    service = ServiceType(service_type)
    try:
        from app.modules.trust_support import service as trust_service

        provider = trust_service.reputation_summaries
    except (ImportError, AttributeError):
        logger.info("trust_support.service.reputation_summaries unavailable; using zero reputation summaries")
        provider = None
    found = dict(provider(session, ids, service_type=service)) if provider is not None else {}
    return {user_id: found.get(user_id) or ReputationSummary(user_id=user_id, service_type=service) for user_id in ids}


# --- ends (stop or region) ------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class End:
    stop_ids: frozenset[int]
    corridor_ids: frozenset[int]


_REGION_STOPS_SQL = text(
    "SELECT cs.id, cs.corridor_id FROM corridor_stops cs JOIN geo_districts d ON d.id = cs.geo_district_id "
    "WHERE d.region_id = :region AND cs.is_active ORDER BY cs.id LIMIT :limit"
)


_DISTRICT_STOPS_SQL = text(
    "SELECT cs.id, cs.corridor_id FROM corridor_stops cs "
    "WHERE cs.geo_district_id = :district AND cs.is_active ORDER BY cs.id LIMIT :limit"
)


def _region_pk(session: Session, region_public_id: str, field_name: str) -> int:
    try:
        value = parse_public_id(region_public_id, PublicIdPrefix.REGION)
    except DomainError:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": field_name}) from None
    region_id = session.execute(
        text("SELECT id FROM regions WHERE public_id = :u AND is_active"), {"u": value}
    ).scalar_one_or_none()
    if region_id is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": field_name})
    return int(region_id)


def _region_end(session: Session, region_id: int, *, limit: int) -> End:
    rows = session.execute(_REGION_STOPS_SQL, {"region": region_id, "limit": limit}).all()
    return End(frozenset(row.id for row in rows), frozenset(row.corridor_id for row in rows))


def _district_pk(session: Session, district_public_id: str, field_name: str) -> int:
    try:
        value = parse_public_id(district_public_id, PublicIdPrefix.DISTRICT)
    except DomainError:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": field_name}) from None
    district_id = session.execute(
        text("SELECT id FROM geo_districts WHERE public_id = :u AND is_active"), {"u": value}
    ).scalar_one_or_none()
    if district_id is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": field_name})
    return int(district_id)


def _district_end(session: Session, district_id: int, *, limit: int) -> End:
    rows = session.execute(_DISTRICT_STOPS_SQL, {"district": district_id, "limit": limit}).all()
    return End(frozenset(row.id for row in rows), frozenset(row.corridor_id for row in rows))


def _stop_pk(session: Session, stop_public_id: str, field_name: str) -> tuple[int, int]:
    ref = get_ports().geo.stops_by_public_ids(session, [stop_public_id]).get(stop_public_id)
    if ref is None or not ref.is_active:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": field_name})
    return ref.id, ref.corridor_id


def resolve_end(
    session: Session,
    *,
    stop_id: str | None,
    region_id: str | None,
    district_id: str | None = None,
    field_name: str,
) -> End:
    """One end of a direction: a stop, a district or a whole region - exactly one of them.

    The district (wave 10) is the unit the picker uses everywhere except Tashkent city; it resolves to the
    active stops inside it, so everything downstream (order on the confirmed route, capacity, price band)
    keeps working on verified stops and nothing is matched by administrative proximity alone (spec 6.1).
    """
    given = [value for value in (stop_id, region_id, district_id) if value is not None]
    if len(given) != 1:
        raise _validation(f"{field_name}_stop_id", "exactly_one_of_stop_district_or_region")
    if stop_id is not None:
        pk, corridor_id = _stop_pk(session, stop_id, f"{field_name}_stop_id")
        return End(frozenset({pk}), frozenset({corridor_id}))
    if district_id is not None:
        return _district_end(
            session, _district_pk(session, district_id, f"{field_name}_district_id"), limit=rules.REGION_STOP_LIMIT
        )
    return _region_end(session, _region_pk(session, region_id, f"{field_name}_region_id"), limit=rules.REGION_STOP_LIMIT)


def district_public_ids(session: Session, district_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted({int(value) for value in district_ids})
    if not ids:
        return {}
    rows = session.execute(text("SELECT id, public_id FROM geo_districts WHERE id = ANY(:ids)"), {"ids": ids}).all()
    return {row.id: format_public_id(PublicIdPrefix.DISTRICT, row.public_id) for row in rows}


def region_public_ids(session: Session, region_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted({int(value) for value in region_ids})
    if not ids:
        return {}
    rows = session.execute(text("SELECT id, public_id FROM regions WHERE id = ANY(:ids)"), {"ids": ids}).all()
    return {row.id: format_public_id(PublicIdPrefix.REGION, row.public_id) for row in rows}


# --- per-request read cache -----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SegmentAvailability:
    seat_capacity: int
    min_remaining_seats: int
    min_remaining_cargo_weight_g: int
    min_remaining_cargo_volume_ml: int


@dataclass(frozen=True, slots=True)
class TripMatch:
    result: RouteMatchResult
    pickup_seq: int
    dropoff_seq: int


class _Reads:
    """Read-only lookups with per-call caches (one feed request / one consumer call)."""

    def __init__(self, session: Session, now: datetime) -> None:
        self.session = session
        self.now = now
        self._trips: dict[int, Trip] = {}
        self._contexts: dict[int, TripRouteContext | None] = {}
        self._eligible: dict[int, bool] = {}
        self._visible: dict[tuple[int, str, str], bool] = {}
        self._bands: dict[tuple[int, str, int, int], object] = {}
        self._orders: dict[int, list[dict[int, list[int]]]] = {}
        self._nearby: dict[int, tuple[int, ...]] = {}
        self._region_stops: dict[int, frozenset[int]] = {}
        self._district_stops: dict[int, frozenset[int]] = {}
        self._spans: dict[int, tuple[int, int] | None] = {}
        self._vehicles: dict[int, bool] = {}

    def trip(self, trip_id: int) -> Trip:
        if trip_id not in self._trips:
            self._trips[trip_id] = trips_service.get_trip(self.session, trip_id)
        return self._trips[trip_id]

    def trip_context(self, trip: Trip) -> TripRouteContext | None:
        if trip.id not in self._contexts:
            occurrences = trips_service.list_occurrences(self.session, trip.id)
            try:
                self._contexts[trip.id] = TripRouteContext(
                    route_version_id=trip.route_version_id,
                    trip_version=trip.version,
                    occurrences=tuple(
                        OccurrenceTiming(o.seq, o.stop_id, ensure_aware_utc(o.planned_arrival_at), o.dwell_minutes)
                        for o in occurrences
                    ),
                    max_detour_minutes=trip.max_detour_minutes,
                    max_detour_m=trip.max_detour_m,
                    detour_used_s=trip.detour_used_s,
                    detour_used_m=trip.detour_used_m,
                    pickup_wait_minutes=trip.pickup_wait_minutes,
                )
            except ValueError:  # malformed timeline: never guess a match
                logger.warning("trip %s has no usable route context", trip.id)
                self._contexts[trip.id] = None
        return self._contexts[trip.id]

    def offer_span(self, listing: Listing) -> tuple[int, int] | None:
        if listing.id not in self._spans:
            self._spans[listing.id] = (
                trips_service.occurrence_seqs_for_stops(
                    self.session, listing.trip_id, listing.origin_stop_id, listing.destination_stop_id
                )
                if listing.trip_id is not None
                else None
            )
        return self._spans[listing.id]

    def driver_eligible(self, user_id: int) -> bool:
        """Q21: new business only with a currently eligible driver (read-only capability computation)."""
        if user_id not in self._eligible:
            self._eligible[user_id] = identity_service.get_capabilities(self.session, user_id, now=self.now).driver_eligible
        return self._eligible[user_id]

    def can_offer_as_driver(self, user_id: int) -> bool:
        """P9/Q40: only a user who could make a driver offer may see or be notified about client requests."""
        key = -int(user_id)  # separate cache slot from driver_eligible
        if key not in self._eligible:
            caps = identity_service.get_capabilities(self.session, user_id, now=self.now)
            self._eligible[key] = caps.has(Capability.PROPOSAL_SUBMIT_AS_DRIVER)
        return self._eligible[key]

    def vehicle_eligible(self, vehicle_id: int) -> bool:
        """Q61: a new booking needs an approved vehicle (A1 read-only check, no lock)."""
        if vehicle_id not in self._vehicles:
            try:
                trips_service.assert_vehicle_eligible_for_new_booking(self.session, vehicle_id)
                self._vehicles[vehicle_id] = True
            except DomainError:
                self._vehicles[vehicle_id] = False
        return self._vehicles[vehicle_id]

    def listing_visible(self, listing: Listing) -> bool:
        """Service flags (Q5, AC38) and an open corridor, as for publishing (A1 ports)."""
        key = (listing.corridor_id, listing.kind, listing.service_type)
        if key not in self._visible:
            ports = get_ports()
            flags = [marketplace_service.SERVICE_FLAG[ServiceType(listing.service_type)]]
            if listing.kind == ListingKind.TRIP_OFFER.value:
                flags.append(FeatureFlagKey.DRIVER_LISTING_ENABLED)
            corridor = ports.geo.corridors_by_ids(self.session, [listing.corridor_id]).get(listing.corridor_id)
            self._visible[key] = (
                corridor is not None
                and corridor.is_open
                and all(ports.flags.is_enabled(self.session, flag, corridor_id=listing.corridor_id) for flag in flags)
            )
        return self._visible[key]

    def band(  # noqa: ANN201
        self,
        corridor_id: int,
        service_type: ServiceType,
        origin_stop_id: int | None,
        destination_stop_id: int | None,
    ):
        """Q42 price *reference* for the ranking score.

        Q88: either end may be a map point with no stop id; A2 then answers with the corridor-wide band, so a
        point-ended listing is scored on price like any other instead of falling back to the neutral 0.5
        because nobody could look a reference up for it.
        """
        key = (corridor_id, service_type.value, origin_stop_id, destination_stop_id)
        if key not in self._bands:
            try:
                from app.modules.geo.service import resolve_price_band
            except ImportError:  # pragma: no cover - A2 always ships it
                self._bands[key] = None
            else:
                self._bands[key] = resolve_price_band(
                    self.session,
                    corridor_id=corridor_id,
                    service_type=service_type,
                    origin_stop_id=origin_stop_id,
                    destination_stop_id=destination_stop_id,
                )
        return self._bands[key]

    def route_orders(self, corridor_id: int) -> list[dict[int, list[int]]]:
        """Stop order of every confirmed route version of the corridor (verified stops, spec §6.2)."""
        if corridor_id not in self._orders:
            rows = self.session.execute(
                text(
                    "SELECT rvs.route_version_id, rvs.seq, rvs.stop_id FROM route_version_stops rvs "
                    "JOIN route_versions rv ON rv.id = rvs.route_version_id "
                    "WHERE rv.status = 'confirmed' AND rv.corridor_id = :c ORDER BY rvs.route_version_id, rvs.seq"
                ),
                {"c": corridor_id},
            ).all()
            orders: dict[int, dict[int, list[int]]] = {}
            for row in rows:
                orders.setdefault(row.route_version_id, {}).setdefault(row.stop_id, []).append(row.seq)
            self._orders[corridor_id] = list(orders.values())
        return self._orders[corridor_id]

    def nearby(self, stop_id: int) -> tuple[int, ...]:
        if stop_id not in self._nearby:
            from app.modules.geo import service as geo_service

            ref = get_ports().geo.stops_by_ids(self.session, [stop_id]).get(stop_id)
            if ref is None:
                self._nearby[stop_id] = ()
            else:
                radius = geo_service.get_corridor(self.session, ref.corridor_id).config.search_radius_m
                self._nearby[stop_id] = tuple(geo_service.nearby_stop_ids(self.session, stop_id, radius_m=radius))
        return self._nearby[stop_id]

    def region_stops(self, region_id: int) -> frozenset[int]:
        if region_id not in self._region_stops:
            self._region_stops[region_id] = _region_end(self.session, region_id, limit=CONSUMER_REGION_STOP_LIMIT).stop_ids
        return self._region_stops[region_id]

    def district_stops(self, district_id: int) -> frozenset[int]:
        if district_id not in self._district_stops:
            self._district_stops[district_id] = _district_end(
                self.session, district_id, limit=CONSUMER_REGION_STOP_LIMIT
            ).stop_ids
        return self._district_stops[district_id]


def listing_end_candidates(reads: _Reads, listing: Listing) -> tuple[frozenset[int], frozenset[int]]:
    """The verified stops that can stand for this listing's two ends (Q88).

    A stop end stands for itself. A map-point end has no stop id, so the verified stops of the district it was
    marked in stand for it - the place itself was already proved to sit on a confirmed route when the listing
    was published, and this only answers "which of the catalogue's stops is it near".

    **This is the one place that answer is computed.** Every consumer of a listing's ends - the primary feed,
    `listing_matches`, saved searches - goes through it, because a consumer that reads `listing.origin_stop_id`
    directly silently drops every point-ended listing: `None` is not a stop, so nothing ever matches and the
    listing simply never appears. That is the marketplace loop breaking without a single error being raised.
    """
    if listing.origin_stop_id is not None:
        origin = frozenset({listing.origin_stop_id})
    else:
        origin = reads.district_stops(listing.origin_district_id) if listing.origin_district_id else frozenset()
    if listing.destination_stop_id is not None:
        destination = frozenset({listing.destination_stop_id})
    else:
        destination = (
            reads.district_stops(listing.destination_district_id) if listing.destination_district_id else frozenset()
        )
    return origin, destination


def _point_listing_match(
    reads: _Reads,
    listing: Listing,
    orders,  # noqa: ANN001 - per-route {stop_id: positions}
    origin_ids: frozenset[int] | set[int],
    destination_ids: frozenset[int] | set[int],
) -> MatchType | None:
    """Match a map-point listing through its districts' verified stops - never ``exact`` (Q88).

    A place marked on the map is, by construction, not one of the driver's chosen ends, so calling it an exact
    match would be a lie to both sides. The best it can honestly be is "on your way", and only when the
    district's stops fall inside the stretch the driver asked about.
    """
    pickup_candidates, dropoff_candidates = listing_end_candidates(reads, listing)
    for pickup in sorted(pickup_candidates):
        for dropoff in sorted(dropoff_candidates):
            if rules.stop_segment_match(orders, origin_ids, destination_ids, pickup, dropoff) is not None:
                return MatchType.ON_ROUTE
    return None


def best_trip_match(
    reads: _Reads,
    trip: Trip,
    *,
    offer_span: tuple[int, int] | None,
    origin_ids: Iterable[int],
    destination_ids: Iterable[int],
    window_start: datetime,
    window_end: datetime,
    include_alternatives: bool,
) -> TripMatch | None:
    """Best verified-stop match of ``trip`` for any (origin, destination) pair via A2 ``evaluate_route_match``.

    No detour measurements are passed, so a result is never ``detour`` (Q46); a pickup/dropoff that would need a new
    stop is never offered. ``offer_span`` restricts to the trip offer's own origin -> destination occurrences.
    """
    context = reads.trip_context(trip)
    if context is None:
        return None
    best: tuple[tuple[int, int, int], TripMatch] | None = None
    for origin in sorted(set(origin_ids)):
        for destination in sorted(set(destination_ids)):
            if origin == destination:
                continue
            request = MatchRequest(
                pickup_stop_id=origin,
                dropoff_stop_id=destination,
                pickup_window_start=window_start,
                pickup_window_end=window_end,
                pickup_alternative_stop_ids=reads.nearby(origin) if include_alternatives else (),
                dropoff_alternative_stop_ids=reads.nearby(destination) if include_alternatives else (),
            )
            result = evaluate_route_match(context, request, include_alternatives=include_alternatives, now=reads.now)
            if not result.matched or result.match_type is None or result.pickup is None or result.dropoff is None:
                continue
            pickup_seq, dropoff_seq = result.pickup.occurrence_seq, result.dropoff.occurrence_seq
            if pickup_seq is None or dropoff_seq is None or result.match_type is MatchType.DETOUR:
                continue
            if offer_span is not None and (pickup_seq < offer_span[0] or dropoff_seq > offer_span[1]):
                continue
            key = (_GEO_RANK[result.match_type], pickup_seq, dropoff_seq)
            if best is None or key < best[0]:
                best = (key, TripMatch(result, pickup_seq, dropoff_seq))
    return best[1] if best else None


def segment_availability(session: Session, trip: Trip, from_seq: int, to_seq: int) -> SegmentAvailability | None:
    loads = [load for load in trips_service.get_segment_loads(session, trip.id) if from_seq <= load.from_seq < to_seq]
    if not loads:
        return None
    return SegmentAvailability(
        seat_capacity=trip.seat_capacity,
        min_remaining_seats=min(load.seat_capacity - load.seats_used for load in loads),
        min_remaining_cargo_weight_g=min(load.cargo_capacity_weight_g - load.cargo_used_weight_g for load in loads),
        min_remaining_cargo_volume_ml=min(load.cargo_capacity_volume_ml - load.cargo_used_volume_ml for load in loads),
    )


def _parcel_fit(session: Session, listing: Listing, availability: SegmentAvailability | None) -> float | None:
    """§8.4 F for parcels: max used share of known weight/volume; ``None`` = does not fit (hard reject)."""
    details = marketplace_service.get_parcel_details(session, listing.id)
    if availability is None:
        return NEUTRAL_FIT_SCORE
    shares: list[float] = []
    weight_g, volume = (details.weight_g if details else None), None
    if details is not None and details.parcel_category_item_id is not None:
        # Q140 (ADR-0026): a category is measured by its limits - the same worst case the capacity check reserves.
        from app.modules.marketplace import parcel_catalog

        item = parcel_catalog.get_item(session, details.parcel_category_item_id)
        weight_g, volume = item.max_weight_g, item.max_volume_ml
    elif details is not None and details.length_cm and details.width_cm and details.height_cm:
        volume = parcel_volume_ml(details.length_cm, details.width_cm, details.height_cm)
    if weight_g:
        remaining = availability.min_remaining_cargo_weight_g
        if remaining <= 0 or weight_g > remaining:
            return None
        shares.append(weight_g / remaining)
    if volume:
        remaining = availability.min_remaining_cargo_volume_ml
        if remaining <= 0 or volume > remaining:
            return None
        shares.append(volume / remaining)
    if availability.min_remaining_cargo_weight_g <= 0 and availability.min_remaining_cargo_volume_ml <= 0:
        return None
    return rules.clip01(max(shares)) if shares else NEUTRAL_FIT_SCORE


def _has_amenities(session: Session, listing: Listing, wanted: Sequence[str]) -> bool:
    details = marketplace_service.get_passenger_details(session, listing.id)
    return details is not None and set(wanted) <= set(details.amenities or [])


# --- ranked items and pages ------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankedItem:
    listing: Listing
    group: MatchGroup
    match_type: MatchType
    reasons: tuple[MatchReason, ...]
    pickup_eta_window_start: datetime | None
    pickup_eta_window_end: datetime | None
    is_estimate: bool
    comparable_total_minor: int | None
    score: float
    components: dict[str, float]
    reputation: ReputationSummary
    ready_to_accept: bool
    availability: SegmentAvailability | None
    key: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class FeedPage:
    items: list[RankedItem]
    next_key: tuple[int, int, int] | None
    limit: int
    ranking_version: str = RANKING_VERSION
    match_scope: str = MATCH_SCOPE_CONFIRMED_STOPS
    degraded: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedCriteria:
    service_type: ServiceType
    side: FeedSide
    date_from: datetime
    date_to: datetime
    origin_stop_id: str | None = None
    origin_region_id: str | None = None
    origin_district_id: str | None = None
    destination_stop_id: str | None = None
    destination_region_id: str | None = None
    destination_district_id: str | None = None
    seats: int | None = None
    max_total_minor: int | None = None
    amenities: tuple[str, ...] = field(default_factory=tuple)
    sort: FeedSort = FeedSort.RECOMMENDED
    include_alternatives: bool = False


@dataclass(frozen=True, slots=True)
class _Eval:
    match_type: MatchType
    reasons: tuple[MatchReason, ...]
    eta_start: datetime | None
    eta_end: datetime | None
    is_estimate: bool
    total: int | None
    availability: SegmentAvailability | None
    ready: bool
    pickup_stop_id: int
    dropoff_stop_id: int
    when: datetime
    fit: float = NEUTRAL_FIT_SCORE


def _paginate(items: list[RankedItem], after_key: tuple[int, int, int] | None, limit: int) -> tuple[list[RankedItem], tuple[int, int, int] | None]:
    ordered = sorted(items, key=lambda item: item.key)
    if after_key is not None:
        ordered = [item for item in ordered if item.key > tuple(after_key)]
    page = ordered[:limit]
    return page, (page[-1].key if len(ordered) > limit and page else None)


def _page_markers(session: Session) -> tuple[str, ...]:
    # Q46: production offers verified stops only by policy. Elsewhere detours would be allowed but the feed does not
    # measure them (no router call in a read), so the page says so instead of implying completeness (AC35).
    return () if platform_service.is_production(session) else (ErrorCode.ROUTING_UNAVAILABLE.value,)


def _blocked_ids(session: Session, viewer_user_id: int) -> frozenset[int]:
    """§8.1: everyone hidden from this viewer by a block, in either direction.

    Read through A12's service function; when the trust module is not wired the feed simply has nothing to hide.
    """
    try:
        from app.modules.trust_support import service as trust_service
    except Exception:  # noqa: BLE001 - the feed must work even if trust_support is not installed
        return frozenset()
    return frozenset(trust_service.blocked_user_ids(session, viewer_user_id))


def _candidates(
    session: Session,
    *,
    kind: ListingKind,
    service_type: ServiceType,
    corridor_ids: Iterable[int],
    window_from: datetime,
    window_to: datetime,
    exclude_owner_id: int,
    now: datetime,
    blocked_owner_ids: Collection[int] = (),
) -> list[Listing]:
    corridors = sorted(set(corridor_ids))
    if not corridors:
        return []
    stmt = select(Listing).where(
        Listing.kind == kind.value,
        Listing.service_type == service_type.value,
        Listing.status == PUBLISHED,
        Listing.expires_at > now,
        Listing.departure_window_end > now,
        Listing.corridor_id.in_(corridors),
        Listing.owner_user_id != exclude_owner_id,
    )
    if blocked_owner_ids:
        # §8.1: a block hides the pair from each other before anything is scored or pushed.
        stmt = stmt.where(Listing.owner_user_id.notin_(sorted(blocked_owner_ids)))
    if kind is ListingKind.TRIP_OFFER:
        stmt = stmt.join(Trip, Trip.id == Listing.trip_id).where(
            Trip.status == PLANNED, Trip.planned_start_at < window_to, Trip.planned_end_at > window_from
        )
    else:
        stmt = stmt.where(Listing.departure_window_start < window_to, Listing.departure_window_end > window_from)
    return list(
        session.execute(stmt.order_by(Listing.departure_window_start, Listing.id).limit(rules.FEED_CANDIDATE_LIMIT)).scalars()
    )


def _evaluate_offer(
    reads: _Reads,
    listing: Listing,
    *,
    origin_ids: Iterable[int],
    destination_ids: Iterable[int],
    window_start: datetime,
    window_end: datetime,
    wanted_quantity: int,
    include_alternatives: bool,
    max_total_minor: int | None,
    amenities: Sequence[str],
) -> _Eval | None:
    """A trip offer for a client (§8.1 gates before ranking: visibility, eligibility, route/time, capacity)."""
    if listing.trip_id is None or not reads.listing_visible(listing):
        return None
    trip = reads.trip(listing.trip_id)
    if trip.status != PLANNED or not reads.driver_eligible(trip.driver_user_id):  # Q21
        return None
    span = reads.offer_span(listing)
    if span is None:
        return None
    match = best_trip_match(
        reads,
        trip,
        offer_span=span,
        origin_ids=origin_ids,
        destination_ids=destination_ids,
        window_start=window_start,
        window_end=window_end,
        include_alternatives=include_alternatives,
    )
    if match is None:
        return None
    availability = segment_availability(reads.session, trip, match.pickup_seq, match.dropoff_seq)
    service = ServiceType(listing.service_type)
    if service is ServiceType.PASSENGER:
        if availability is None or availability.min_remaining_seats < wanted_quantity:
            return None  # capacity is a hard reject, never a score (§8.4)
    elif availability is None or (
        availability.min_remaining_cargo_weight_g <= 0 and availability.min_remaining_cargo_volume_ml <= 0
    ):
        return None
    total = rules.comparable_total_minor(
        price_basis=listing.price_basis,
        unit_price_minor=listing.unit_price_minor,
        total_minor=listing.total_minor,
        listing_quantity=listing.quantity,
        wanted_quantity=wanted_quantity,
    )
    if max_total_minor is not None and (total is None or total > max_total_minor):
        return None
    if amenities and not _has_amenities(reads.session, listing, amenities):
        return None
    result = match.result
    return _Eval(
        match_type=result.match_type,
        reasons=tuple(result.reasons),
        eta_start=result.pickup_eta_window_start,
        eta_end=result.pickup_eta_window_end,
        is_estimate=result.is_estimate,
        total=total,
        availability=availability,
        ready=(
            ensure_aware_utc(trip.booking_cutoff_at) > reads.now
            and listing.status == PUBLISHED
            and reads.vehicle_eligible(trip.vehicle_id)  # Q61
        ),
        pickup_stop_id=result.pickup.stop_id,
        dropoff_stop_id=result.dropoff.stop_id,
        when=result.pickup_eta_window_start or ensure_aware_utc(listing.departure_window_start),
    )


def _evaluate_request_by_stops(
    reads: _Reads,
    listing: Listing,
    *,
    origin_ids: frozenset[int],
    destination_ids: frozenset[int],
    window_start: datetime,
    window_end: datetime,
    seats: int | None,
    include_alternatives: bool,
    max_total_minor: int | None,
    amenities: Sequence[str],
) -> _Eval | None:
    """A client request for a driver without a trip context: verified stop order on confirmed routes + time."""
    if not reads.listing_visible(listing):
        return None
    orders = reads.route_orders(listing.corridor_id)
    gap = rules.window_gap(listing.departure_window_start, listing.departure_window_end, window_start, window_end)
    point_ended = listing.origin_stop_id is None or listing.destination_stop_id is None
    if point_ended:
        # Q88: a marked place has no stop id to compare, so it is matched through the verified stops of the
        # district it was marked in. The place itself was already proved to sit on a confirmed route when the
        # listing was published; this only answers "is it on *this* driver's stretch of it".
        base = _point_listing_match(reads, listing, orders, origin_ids, destination_ids)
    else:
        base = rules.stop_segment_match(orders, origin_ids, destination_ids, listing.origin_stop_id, listing.destination_stop_id)
    reasons: list[MatchReason]
    if base is not None and gap == timedelta(0):
        match_type = base
        reasons = [MatchReason.FULL_ROUTE if base is MatchType.EXACT else MatchReason.INTERMEDIATE_SEGMENT]
        if not point_ended:
            reasons += [MatchReason.PICKUP_AT_STOP, MatchReason.DROPOFF_AT_STOP]
    elif include_alternatives and gap <= ALTERNATIVE_TIME_TOLERANCE:
        near_origin = origin_ids | {n for stop in origin_ids for n in reads.nearby(stop)}
        near_destination = destination_ids | {n for stop in destination_ids for n in reads.nearby(stop)}
        alternative = base or rules.stop_segment_match(
            orders, near_origin, near_destination, listing.origin_stop_id, listing.destination_stop_id
        )
        if alternative is None:
            return None
        match_type = MatchType.ALTERNATIVE
        reasons = ([] if base is not None else [MatchReason.NEARBY_STOP]) + ([MatchReason.TIME_DIFFERS] if gap else [])
    else:
        return None
    fit = NEUTRAL_FIT_SCORE
    if seats is not None and listing.service_type == ServiceType.PASSENGER.value:
        fitted = rules.fit_score(listing.quantity, seats)
        if fitted is None:
            return None
        fit = fitted
    total = listing.total_minor
    if max_total_minor is not None and total > max_total_minor:
        return None
    if amenities and not _has_amenities(reads.session, listing, amenities):
        return None
    return _Eval(
        match_type=match_type,
        reasons=tuple(reasons),
        eta_start=None,
        eta_end=None,
        is_estimate=True,
        total=total,
        availability=None,
        ready=listing.status == PUBLISHED and ensure_aware_utc(listing.expires_at) > reads.now,
        pickup_stop_id=listing.origin_stop_id,
        dropoff_stop_id=listing.destination_stop_id,
        when=ensure_aware_utc(listing.departure_window_start),
        fit=fit,
    )


def _evaluate_request_for_trip(
    reads: _Reads, listing: Listing, *, trip: Trip, offer_span: tuple[int, int], include_alternatives: bool
) -> _Eval | None:
    """M2 for a trip-offer owner: the owner's own trip against a client request (route, time, capacity)."""
    if not reads.listing_visible(listing):
        return None
    # Q88: a point-ended request is matched through its districts' verified stops, exactly as the primary feed
    # does it. Passing `listing.origin_stop_id` here (which is `None` for such a request) made every one of
    # them invisible to the driver whose trip could actually serve it.
    origin_ids, destination_ids = listing_end_candidates(reads, listing)
    if not origin_ids or not destination_ids:
        return None
    match = best_trip_match(
        reads,
        trip,
        offer_span=offer_span,
        origin_ids=origin_ids,
        destination_ids=destination_ids,
        window_start=ensure_aware_utc(listing.departure_window_start),
        window_end=ensure_aware_utc(listing.departure_window_end),
        include_alternatives=include_alternatives,
    )
    if match is None:
        return None
    availability = segment_availability(reads.session, trip, match.pickup_seq, match.dropoff_seq)
    if listing.service_type == ServiceType.PASSENGER.value:
        fit = rules.fit_score(listing.quantity, availability.min_remaining_seats if availability else 0)
    else:
        fit = _parcel_fit(reads.session, listing, availability)
    if fit is None:
        return None
    result = match.result
    return _Eval(
        match_type=result.match_type,
        reasons=tuple(result.reasons),
        eta_start=result.pickup_eta_window_start,
        eta_end=result.pickup_eta_window_end,
        is_estimate=result.is_estimate,
        total=listing.total_minor,
        availability=availability,
        ready=listing.status == PUBLISHED and ensure_aware_utc(listing.expires_at) > reads.now,
        pickup_stop_id=result.pickup.stop_id,
        dropoff_stop_id=result.dropoff.stop_id,
        when=result.pickup_eta_window_start or ensure_aware_utc(listing.departure_window_start),
        fit=fit,
    )


def _client_components(
    reads: _Reads, listing: Listing, ev: _Eval, summary: ReputationSummary, *, window: tuple[datetime, datetime], quantity: int
) -> dict[str, float]:
    service = ServiceType(listing.service_type)
    group = rules.group_for(ev.match_type)
    band = reads.band(listing.corridor_id, service, ev.pickup_stop_id, ev.dropoff_stop_id)
    low, high = rules.band_totals(service, band.floor_minor, band.ceiling_minor, quantity) if band else (None, None)
    return {
        "M": rules.match_score(ev.match_type) if group is MatchGroup.PRIMARY else 0.0,
        "T": rules.time_score(ev.when, rules.window_midpoint(*window), rules.window_minutes(*window)),
        "R": rules.reliability(summary),
        "P": rules.price_score(ev.total, low, high),
        "E": rules.experience(summary.completed_trips),
    }


def _driver_components(
    reads: _Reads, listing: Listing, ev: _Eval, summary: ReputationSummary, *, window: tuple[datetime, datetime]
) -> dict[str, float]:
    service = ServiceType(listing.service_type)
    group = rules.group_for(ev.match_type)
    band = reads.band(listing.corridor_id, service, listing.origin_stop_id, listing.destination_stop_id)
    reference = (
        rules.band_reference_total(service, band.floor_minor, band.ceiling_minor, listing.quantity) if band else None
    )
    return {
        "M": rules.match_score(ev.match_type) if group is MatchGroup.PRIMARY else 0.0,
        "T": rules.time_score(ev.when, rules.window_midpoint(*window), rules.window_minutes(*window)),
        "Y": rules.driver_price_score(ev.total, reference),
        "C": summary.completion_ratio,  # client keeping agreements; neutral prior for a new client
        "F": ev.fit,
    }


def _ranked(listing: Listing, ev: _Eval, components: dict[str, float], score: float, summary: ReputationSummary, sort: FeedSort) -> RankedItem:
    group = rules.group_for(ev.match_type)
    return RankedItem(
        listing=listing,
        group=group,
        match_type=ev.match_type,
        reasons=ev.reasons,
        pickup_eta_window_start=ev.eta_start,
        pickup_eta_window_end=ev.eta_end,
        is_estimate=ev.is_estimate,
        comparable_total_minor=ev.total,
        score=score,
        components=components,
        reputation=summary,
        ready_to_accept=ev.ready,
        availability=ev.availability,
        key=rules.sort_key(
            sort,
            group=group,
            score=score,
            comparable_total=ev.total,
            when=ev.when,
            adjusted_rating=summary.adjusted_rating,
            rating_count=summary.rating_count,
            listing_id=listing.id,
        ),
    )


def _check_window(start: datetime, end: datetime, *, field_name: str) -> tuple[datetime, datetime]:
    start, end = ensure_aware_utc(start), ensure_aware_utc(end)
    if end <= start:
        raise _validation(field_name, "window_end_before_start")
    if end - start > timedelta(days=SAVED_SEARCH_MAX_WINDOW_DAYS):
        raise _validation(field_name, "window_too_long", max_days=SAVED_SEARCH_MAX_WINDOW_DAYS)
    return start, end


# --- M1 feed ---------------------------------------------------------------------------------------------------------


def record_search(
    session: Session, *, criteria: FeedCriteria, page: FeedPage, corridor_id: int | None = None,
    now: datetime | None = None,
) -> None:
    """§20.4: count one feed search and whether it found anything. No user id, no stops, no filters.

    The row is what makes ``search_with_match_rate`` measurable at all; before wave 6 the metric was reported as
    "this system does not measure it". Failures are swallowed: a counter must never break a search.
    """
    from app.modules.marketplace.feed.models import FeedSearchEvent

    try:
        session.add(
            FeedSearchEvent(
                occurred_at=now or utc_now(), service_type=ServiceType(criteria.service_type).value,
                side=FeedSide(criteria.side).value, corridor_id=corridor_id,
                matched=bool(page.items), result_count=len(page.items),
            )
        )
        session.flush()
    except Exception:  # noqa: BLE001 - a KPI counter is never worth a failed request
        session.rollback()


def feed(
    session: Session,
    *,
    viewer_user_id: int,
    criteria: FeedCriteria,
    after_key: tuple[int, int, int] | None = None,
    limit: int = FEED_DEFAULT_LIMIT,
    now: datetime | None = None,
) -> FeedPage:
    """M1. ``offers``: trip offers for a client (§8.2 score); ``requests``: client requests for a driver (§8.4 score).

    The default is the chosen direction (both ends required, no country-wide mixed feed, §6.6). The primary group
    (``exact``/``on_route``) always precedes the ``alternative`` group, which is opt-in.
    """
    now = _now(now)
    limit = max(1, min(int(limit), FEED_MAX_LIMIT))
    side, service = FeedSide(criteria.side), ServiceType(criteria.service_type)
    if side is FeedSide.OFFERS:
        # Q138 (ADR-0026): there are no driver listings for a client to browse - clients publish requests.
        raise DomainError(ErrorCode.DRIVER_LISTING_RETIRED, details={"side": FeedSide.OFFERS.value})
    window = _check_window(criteria.date_from, criteria.date_to, field_name="date_to")
    if side is FeedSide.REQUESTS:
        # P9 visibility (Q40): only drivers who could make an offer see client requests.
        identity_service.require_capability(
            identity_service.get_capabilities(session, viewer_user_id, now=now), Capability.PROPOSAL_SUBMIT_AS_DRIVER
        )
    origin = resolve_end(
        session,
        stop_id=criteria.origin_stop_id,
        region_id=criteria.origin_region_id,
        district_id=criteria.origin_district_id,
        field_name="origin",
    )
    destination = resolve_end(
        session,
        stop_id=criteria.destination_stop_id,
        region_id=criteria.destination_region_id,
        district_id=criteria.destination_district_id,
        field_name="destination",
    )
    markers = _page_markers(session)
    quantity = 1 if service is ServiceType.PARCEL else (criteria.seats or 1)
    extend = ALTERNATIVE_TIME_TOLERANCE if criteria.include_alternatives else timedelta(0)
    candidates = _candidates(
        session,
        kind=SIDE_KIND[side],
        service_type=service,
        corridor_ids=origin.corridor_ids & destination.corridor_ids,
        window_from=window[0] - extend,
        window_to=window[1] + extend,
        exclude_owner_id=viewer_user_id,
        now=now,
        blocked_owner_ids=_blocked_ids(session, viewer_user_id),
    )
    reads = _Reads(session, now)
    evaluated: list[tuple[Listing, _Eval]] = []
    for listing in candidates:
        if side is FeedSide.OFFERS:
            ev = _evaluate_offer(
                reads,
                listing,
                origin_ids=origin.stop_ids,
                destination_ids=destination.stop_ids,
                window_start=window[0],
                window_end=window[1],
                wanted_quantity=quantity,
                include_alternatives=criteria.include_alternatives,
                max_total_minor=criteria.max_total_minor,
                amenities=criteria.amenities,
            )
        else:
            ev = _evaluate_request_by_stops(
                reads,
                listing,
                origin_ids=origin.stop_ids,
                destination_ids=destination.stop_ids,
                window_start=window[0],
                window_end=window[1],
                seats=criteria.seats,
                include_alternatives=criteria.include_alternatives,
                max_total_minor=criteria.max_total_minor,
                amenities=criteria.amenities,
            )
        if ev is not None and not (ev.match_type is MatchType.DETOUR and not markers):  # Q46 (defensive)
            evaluated.append((listing, ev))
    reputations = load_reputations(session, [listing.owner_user_id for listing, _ in evaluated], service_type=service)
    items: list[RankedItem] = []
    for listing, ev in evaluated:
        summary = reputations[listing.owner_user_id]
        if side is FeedSide.OFFERS:
            components = _client_components(reads, listing, ev, summary, window=window, quantity=quantity)
            score = rules.client_score(**components)
        else:
            components = _driver_components(reads, listing, ev, summary, window=window)
            score = rules.driver_score(**components)
        items.append(_ranked(listing, ev, components, score, summary, FeedSort(criteria.sort)))
    page, next_key = _paginate(items, after_key, limit)
    return FeedPage(items=page, next_key=next_key, limit=limit, degraded=markers)


# --- M2 listing matches ----------------------------------------------------------------------------------------------


def listing_matches(
    session: Session,
    *,
    listing_public_id: str,
    viewer_user_id: int,
    sort: FeedSort = FeedSort.RECOMMENDED,
    include_alternatives: bool = False,
    after_key: tuple[int, int, int] | None = None,
    limit: int = FEED_DEFAULT_LIMIT,
    now: datetime | None = None,
) -> FeedPage:
    """M2: matches for the owner of a listing; anyone else gets 404. Request -> trip offers; trip offer -> requests."""
    now = _now(now)
    limit = max(1, min(int(limit), FEED_MAX_LIMIT))
    listing = marketplace_service.get_listing_by_public_id(session, listing_public_id)
    if listing.owner_user_id != viewer_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    markers = _page_markers(session)
    if listing.status not in MATCHABLE_OWNER_STATUSES:
        return FeedPage(items=[], next_key=None, limit=limit, degraded=markers)
    service = ServiceType(listing.service_type)
    reads = _Reads(session, now)
    extend = ALTERNATIVE_TIME_TOLERANCE if include_alternatives else timedelta(0)
    evaluated: list[tuple[Listing, _Eval]] = []
    if listing.kind == ListingKind.REQUEST.value:
        window = (ensure_aware_utc(listing.departure_window_start), ensure_aware_utc(listing.departure_window_end))
        quantity = listing.quantity
        # Q88: the owner of a point-ended request asks "which trips can carry me" with the same ends the rest
        # of the engine uses; reading the (absent) stop ids returned an empty page and called it "no matches".
        own_origin_ids, own_destination_ids = listing_end_candidates(reads, listing)
        if not own_origin_ids or not own_destination_ids:
            return FeedPage(items=[], next_key=None, limit=limit, degraded=markers)
        for candidate in _candidates(
            session,
            kind=ListingKind.TRIP_OFFER,
            service_type=service,
            corridor_ids=[listing.corridor_id],
            window_from=window[0] - extend,
            window_to=window[1] + extend,
            exclude_owner_id=viewer_user_id,
            now=now,
            blocked_owner_ids=_blocked_ids(session, viewer_user_id),
        ):
            ev = _evaluate_offer(
                reads,
                candidate,
                origin_ids=own_origin_ids,
                destination_ids=own_destination_ids,
                window_start=window[0],
                window_end=window[1],
                wanted_quantity=quantity,
                include_alternatives=include_alternatives,
                max_total_minor=None,
                amenities=(),
            )
            if ev is not None:
                evaluated.append((candidate, ev))
        reputations = load_reputations(session, [c.owner_user_id for c, _ in evaluated], service_type=service)
        items = []
        for candidate, ev in evaluated:
            summary = reputations[candidate.owner_user_id]
            components = _client_components(reads, candidate, ev, summary, window=window, quantity=quantity)
            items.append(_ranked(candidate, ev, components, rules.client_score(**components), summary, FeedSort(sort)))
    else:
        if listing.trip_id is None:
            return FeedPage(items=[], next_key=None, limit=limit, degraded=markers)
        trip = reads.trip(listing.trip_id)
        span = reads.offer_span(listing)
        if span is None or trip.status != PLANNED:
            return FeedPage(items=[], next_key=None, limit=limit, degraded=markers)
        trip_window = (ensure_aware_utc(trip.planned_start_at), ensure_aware_utc(trip.planned_end_at))
        for candidate in _candidates(
            session,
            kind=ListingKind.REQUEST,
            service_type=service,
            corridor_ids=[listing.corridor_id],
            window_from=trip_window[0] - extend,
            window_to=trip_window[1] + extend,
            exclude_owner_id=viewer_user_id,
            now=now,
            blocked_owner_ids=_blocked_ids(session, viewer_user_id),
        ):
            ev = _evaluate_request_for_trip(
                reads, candidate, trip=trip, offer_span=span, include_alternatives=include_alternatives
            )
            if ev is not None:
                evaluated.append((candidate, ev))
        reputations = load_reputations(session, [c.owner_user_id for c, _ in evaluated], service_type=service)
        items = []
        for candidate, ev in evaluated:
            summary = reputations[candidate.owner_user_id]
            request_window = (
                ensure_aware_utc(candidate.departure_window_start),
                ensure_aware_utc(candidate.departure_window_end),
            )
            components = _driver_components(reads, candidate, ev, summary, window=request_window)
            items.append(_ranked(candidate, ev, components, rules.driver_score(**components), summary, FeedSort(sort)))
    page, next_key = _paginate(items, after_key, limit)
    return FeedPage(items=page, next_key=next_key, limit=limit, degraded=markers)


# --- M3-M5 saved searches --------------------------------------------------------------------------------------------


def saved_search_public_id(row: SavedSearch) -> str:
    return format_public_id(PublicIdPrefix.SAVED_SEARCH, row.public_id)


def _limit_reached() -> DomainError:
    return DomainError(ErrorCode.SAVED_SEARCH_LIMIT_REACHED, details={"limit": SAVED_SEARCH_MAX_PER_USER})


def _end_refs(
    session: Session, *, stop_id: str | None, region_id: str | None, district_id: str | None, field_name: str
) -> tuple[int | None, int | None, int | None]:
    """``(stop_id, region_id, district_id)`` - exactly one is set, as the DB CHECK demands."""
    if stop_id is not None:
        return _stop_pk(session, stop_id, f"{field_name}_stop_id")[0], None, None
    if district_id is not None:
        return None, None, _district_pk(session, district_id, f"{field_name}_district_id")
    return None, _region_pk(session, region_id, f"{field_name}_region_id"), None


def create_saved_search(session: Session, *, user_id: int, data: SavedSearchCreate, now: datetime | None = None) -> SavedSearch:
    """M3. Limit under the ``users`` row lock (FOR NO KEY UPDATE, first group of ADR-0017) + DB guard."""
    now = _now(now)
    start, end = _check_window(data.time_window_start, data.time_window_end, field_name="time_window_end")
    if end <= now:
        raise _validation("time_window_end", "in_the_past")
    service = ServiceType(data.service_type)
    if service is ServiceType.PARCEL and data.quantity != 1:
        raise _validation("quantity", "parcel_quantity_is_one")
    if FeedSide(data.side) is FeedSide.OFFERS:
        raise DomainError(ErrorCode.DRIVER_LISTING_RETIRED, details={"side": FeedSide.OFFERS.value})  # Q138: nothing to be told about
    if FeedSide(data.side) is FeedSide.REQUESTS:
        # Same P9/Q40 gate as the requests feed: 403 CAPABILITY_REQUIRED / DRIVER_NOT_ELIGIBLE.
        identity_service.require_capability(
            identity_service.get_capabilities(session, user_id, now=now), Capability.PROPOSAL_SUBMIT_AS_DRIVER
        )
    origin_stop, origin_region, origin_district = _end_refs(
        session,
        stop_id=data.origin_stop_id,
        region_id=data.origin_region_id,
        district_id=data.origin_district_id,
        field_name="origin",
    )
    destination_stop, destination_region, destination_district = _end_refs(
        session,
        stop_id=data.destination_stop_id,
        region_id=data.destination_region_id,
        district_id=data.destination_district_id,
        field_name="destination",
    )
    if origin_stop is not None and origin_stop == destination_stop:
        raise _validation("destination_stop_id", "same_stop")
    identity_service.lock_user_eligibility(session, [user_id])
    live = session.execute(
        select(func.count(SavedSearch.id)).where(
            SavedSearch.user_id == user_id, SavedSearch.deleted_at.is_(None), SavedSearch.time_window_end > now
        )
    ).scalar_one()
    if live >= SAVED_SEARCH_MAX_PER_USER:
        raise _limit_reached()
    row = SavedSearch(
        public_id=new_public_uuid(),
        user_id=user_id,
        service_type=service.value,
        side=FeedSide(data.side).value,
        origin_stop_id=origin_stop,
        origin_region_id=origin_region,
        origin_district_id=origin_district,
        destination_stop_id=destination_stop,
        destination_region_id=destination_region,
        destination_district_id=destination_district,
        time_window_start=start,
        time_window_end=end,
        quantity=data.quantity,
        notify=data.notify,
        created_at=now,
        updated_at=now,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except DBAPIError as exc:
        if platform_service.constraint_name_of(exc) == SAVED_SEARCH_LIMIT_CONSTRAINT:
            raise _limit_reached() from exc
        raise
    return row


def list_saved_searches(
    session: Session, *, user_id: int, after: tuple[datetime, int] | None = None, limit: int = 20
) -> list[SavedSearch]:
    """M4: the caller's searches that are not deleted, newest first (expired ones stay listed with notify=false)."""
    stmt = select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.deleted_at.is_(None))
    if after is not None:
        created, row_id = after
        stmt = stmt.where(
            (SavedSearch.created_at < created) | ((SavedSearch.created_at == created) & (SavedSearch.id < row_id))
        )
    return list(session.execute(stmt.order_by(SavedSearch.created_at.desc(), SavedSearch.id.desc()).limit(limit)).scalars())


def delete_saved_search(session: Session, *, user_id: int, saved_search_public_id: str, now: datetime | None = None) -> None:
    """M5: soft delete by the owner; another user's (or an already deleted) search is 404."""
    now = _now(now)
    value = parse_public_id(saved_search_public_id, PublicIdPrefix.SAVED_SEARCH)
    row = session.execute(
        select(SavedSearch).where(SavedSearch.public_id == value).with_for_update(key_share=True)
    ).scalar_one_or_none()
    if row is None or row.user_id != user_id or row.deleted_at is not None:
        raise DomainError(ErrorCode.NOT_FOUND)
    row.deleted_at = now
    row.updated_at = now
    session.flush()


# --- consumer: listing.published -> saved_search.matched --------------------------------------------------------------


def _search_ends(reads: _Reads, search: SavedSearch) -> tuple[frozenset[int], frozenset[int]]:
    def side(stop_id: int | None, region_id: int | None, district_id: int | None) -> frozenset[int]:
        if stop_id:
            return frozenset({stop_id})
        if district_id:
            return reads.district_stops(district_id)
        return reads.region_stops(region_id)

    return (
        side(search.origin_stop_id, search.origin_region_id, search.origin_district_id),
        side(search.destination_stop_id, search.destination_region_id, search.destination_district_id),
    )


def _search_matches(reads: _Reads, search: SavedSearch, listing: Listing) -> bool:
    origins, destinations = _search_ends(reads, search)
    if not origins or not destinations:
        return False
    if listing.kind == ListingKind.TRIP_OFFER.value:
        trip = reads.trip(listing.trip_id)
        span = reads.offer_span(listing)
        if span is None:
            return False
        match = best_trip_match(
            reads,
            trip,
            offer_span=span,
            origin_ids=origins,
            destination_ids=destinations,
            window_start=ensure_aware_utc(search.time_window_start),
            window_end=ensure_aware_utc(search.time_window_end),
            include_alternatives=False,
        )
        if match is None:
            return False
        if listing.service_type == ServiceType.PASSENGER.value:
            availability = segment_availability(reads.session, trip, match.pickup_seq, match.dropoff_seq)
            return availability is not None and availability.min_remaining_seats >= search.quantity
        return True
    # Q88: a request listing may be point-ended, and then it has no stop pair to compare. Its districts'
    # verified stops stand in for the ends here exactly as they do in the feed - otherwise a saved search
    # would never fire for the listings the client app actually publishes.
    orders = reads.route_orders(listing.corridor_id)
    pickup_candidates, dropoff_candidates = listing_end_candidates(reads, listing)
    if not pickup_candidates or not dropoff_candidates:
        return False
    matched = any(
        rules.stop_segment_match(orders, origins, destinations, pickup, dropoff) is not None
        for pickup in sorted(pickup_candidates)
        for dropoff in sorted(dropoff_candidates)
    )
    if not matched:
        return False
    if rules.window_gap(listing.departure_window_start, listing.departure_window_end, search.time_window_start, search.time_window_end):
        return False
    return not (listing.service_type == ServiceType.PASSENGER.value and listing.quantity > search.quantity)


def _listing_live(listing: Listing, now: datetime) -> bool:
    return (
        listing.status == PUBLISHED
        and ensure_aware_utc(listing.expires_at) > now
        and ensure_aware_utc(listing.departure_window_end) > now
    )


def match_saved_searches_for_listing(session: Session, listing_id: int, *, now: datetime | None = None) -> int:
    """Consumer body for ``listing.published``: one ``saved_search.matched`` per (user, listing).

    Matching: same service; side by listing kind; both ends (stop or region) on the listing's verified route in
    order (trip offers via the trip occurrences and ETA window, requests via confirmed route stop order and the
    departure window); quantity fits; not the owner's own listing. Hidden listings (flags, closed corridor, Q21
    ineligible driver) notify nobody. Several matching searches of one user give one notification (§6.6). A
    redelivered event finds the ``saved_search_notifications`` row and emits nothing. Returns the events enqueued.
    """
    now = _now(now)
    try:
        listing = marketplace_service.get_listing(session, listing_id)
    except DomainError:
        return 0
    if not _listing_live(listing, now):
        return 0
    reads = _Reads(session, now)
    kind = ListingKind(listing.kind)
    if not reads.listing_visible(listing):
        return 0
    stmt = select(SavedSearch).where(
        SavedSearch.service_type == listing.service_type,
        SavedSearch.side == KIND_SIDE[kind].value,
        SavedSearch.deleted_at.is_(None),
        SavedSearch.notify.is_(True),
        SavedSearch.time_window_end > now,
        SavedSearch.user_id != listing.owner_user_id,
    )
    if kind is ListingKind.TRIP_OFFER:
        if listing.trip_id is None:
            return 0
        trip = reads.trip(listing.trip_id)
        if trip.status != PLANNED or not reads.driver_eligible(trip.driver_user_id):
            return 0
        stmt = stmt.where(SavedSearch.time_window_start < trip.planned_end_at, SavedSearch.time_window_end > trip.planned_start_at)
    else:
        stmt = stmt.where(
            SavedSearch.time_window_start < listing.departure_window_end,
            SavedSearch.time_window_end > listing.departure_window_start,
        )
    chosen: dict[int, SavedSearch] = {}
    for search in session.execute(stmt.order_by(SavedSearch.id)).scalars():
        if search.user_id in chosen:
            continue
        # Eligibility may change after the search was saved: requests go only to users who can still offer (P9/Q40).
        if kind is ListingKind.REQUEST and not reads.can_offer_as_driver(search.user_id):
            continue
        if _search_matches(reads, search, listing):
            chosen[search.user_id] = search
    listing_ref = marketplace_service.listing_public_id(listing)
    side = KIND_SIDE[kind].value
    emitted = 0
    for search in sorted(chosen.values(), key=lambda row: row.id):
        already = session.execute(
            select(
                exists().where(
                    SavedSearchNotification.listing_id == listing.id,
                    SavedSearchNotification.saved_search_id == SavedSearch.id,
                    SavedSearch.user_id == search.user_id,
                )
            )
        ).scalar_one()
        if already:
            continue
        inserted = session.execute(
            pg_insert(SavedSearchNotification)
            .values(saved_search_id=search.id, listing_id=listing.id, notified_at=now)
            .on_conflict_do_nothing(constraint=NOTIFICATION_UNIQUE)
            .returning(SavedSearchNotification.id)
        ).scalar_one_or_none()
        if inserted is None:
            continue
        search.last_notified_at = now
        search.updated_at = now
        search_ref = saved_search_public_id(search)
        platform_service.enqueue_event(
            session,
            EventEnvelope(
                event_type=EventType.SAVED_SEARCH_MATCHED,
                aggregate_type="saved_search",
                aggregate_public_id=search_ref,
                aggregate_version=1,
                occurred_at=now,
                payload={
                    "saved_search_id": search_ref,
                    "listing_id": listing_ref,
                    "service_type": listing.service_type,
                    "side": side,
                },
            ),
            aggregate_id=search.id,
            dedup_key=f"saved_search:{search_ref}:{listing_ref}",
        )
        emitted += 1
    session.flush()
    return emitted


def saved_search_match_still_relevant(session: Session, event: DispatchedEvent) -> bool:
    """A7 relevance check before a push (§6.6): the listing is still published and not expired, the search is not
    deleted, still notifies and its window is not over."""
    payload = event.payload or {}
    try:
        search_uuid = parse_public_id(str(payload.get("saved_search_id")), PublicIdPrefix.SAVED_SEARCH)
        listing_uuid = parse_public_id(str(payload.get("listing_id")), PublicIdPrefix.LISTING)
    except DomainError:
        return False
    now = utc_now()
    search = session.execute(select(SavedSearch).where(SavedSearch.public_id == search_uuid)).scalar_one_or_none()
    if search is None or search.deleted_at is not None or not search.notify or ensure_aware_utc(search.time_window_end) <= now:
        return False
    if search.side == FeedSide.REQUESTS.value and not _Reads(session, now).can_offer_as_driver(search.user_id):
        return False  # P9/Q40 re-checked at push time
    listing = session.execute(select(Listing).where(Listing.public_id == listing_uuid)).scalar_one_or_none()
    return listing is not None and _listing_live(listing, now)


# --- worker ----------------------------------------------------------------------------------------------------------


def expire_saved_searches(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """ServiceJob: searches whose window has ended stop notifying (``notify=false``). No commit."""
    now = _now(now)
    ids = list(
        session.execute(
            select(SavedSearch.id)
            .where(SavedSearch.deleted_at.is_(None), SavedSearch.notify.is_(True), SavedSearch.time_window_end <= now)
            .order_by(SavedSearch.id)
            .limit(limit)
            .with_for_update(key_share=True, skip_locked=True)
        ).scalars()
    )
    if not ids:
        return 0
    session.execute(
        update(SavedSearch).where(SavedSearch.id.in_(ids)).values(notify=False, updated_at=now).execution_options(synchronize_session=False)
    )
    session.flush()
    return len(ids)


# §17.7 data minimisation: the counters answer a KPI, they are not a history to keep forever.
SEARCH_EVENT_RETENTION = timedelta(days=90)


def purge_search_events(session: Session, *, now: datetime | None = None, limit: int = 5000) -> int:
    """Delete feed search counters past the retention window (A10a worker). Returns the number removed."""
    from app.modules.marketplace.feed.models import FeedSearchEvent

    cutoff = (now or utc_now()) - SEARCH_EVENT_RETENTION
    ids = list(
        session.execute(
            select(FeedSearchEvent.id).where(FeedSearchEvent.occurred_at < cutoff).order_by(FeedSearchEvent.id).limit(limit)
        ).scalars()
    )
    if not ids:
        return 0
    session.execute(delete(FeedSearchEvent).where(FeedSearchEvent.id.in_(ids)))
    return len(ids)
