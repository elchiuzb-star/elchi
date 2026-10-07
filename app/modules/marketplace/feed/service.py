"""Feed (M1), saved searches (M3-M5) and the saved-search matcher (A5, wave 3).

Spec §6.3-§6.6, §8.1-§8.4; AC18, AC35, AC36; Q21, Q40, Q43, Q46; ADR-0026 (Q138: drivers browse client requests only);
ADR-0028 / Q160 (no stops: a request is two places, an end of a search is a district or a region).

Boundaries (AGENTS §4, WAVE1_CARDS "Wave 3"):
* marketplace / trips / geo data is read through their service functions and ports or read-only queries; this module
  writes only ``saved_searches`` / ``saved_search_notifications`` and outbox events (``platform.service``).
* Matching never calls a router and never inserts detours: a request matches when both its places lie on a confirmed
  road between the two areas, pickup before dropoff (``exact``/``on_route``, plus the separate time ``alternative``
  group). Production never shows ``detour`` (Q46); elsewhere the page is marked ``ROUTING_UNAVAILABLE`` because
  detours were not measured (AC35: no fake match).
* AC18: no online/last-seen filter.
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
    FeedSide,
    FeedSort,
    ListingKind,
    ListingStatus,
    MatchGroup,
    MatchReason,
    MatchType,
    ServiceType,
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
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.feed import rules
from app.modules.marketplace.feed.models import SavedSearch, SavedSearchNotification
from app.modules.marketplace.feed.schemas import MATCH_SCOPE_CONFIRMED_ROADS, SavedSearchCreate
from app.modules.marketplace.models import Listing
from app.modules.marketplace.ports import get_ports
from app.modules.platform import service as platform_service

logger = logging.getLogger(__name__)

__all__ = [
    "FeedCriteria",
    "FeedPage",
    "RankedItem",
    "create_saved_search",
    "delete_saved_search",
    "expire_saved_searches",
    "feed",
    "list_saved_searches",
    "load_reputations",
    "match_saved_searches_for_listing",
    "region_public_ids",
    "saved_search_match_still_relevant",
    "saved_search_public_id",
]

SAVED_SEARCH_LIMIT_CONSTRAINT = "saved_search_limit"
NOTIFICATION_UNIQUE = "uq_saved_search_notifications_search_listing"
PUBLISHED = ListingStatus.PUBLISHED.value


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


# --- ends (district or region) ------------------------------------------------------------------------------------------


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


def _area(session: Session, *, region_pk: int | None, district_pk: int | None):  # noqa: ANN202
    """One end of a search as an *area* (a region, optionally narrowed to a district; ADR-0028)."""
    from app.modules.geo.service import districts_by_ids
    from app.modules.trips import directions as trip_directions

    if district_pk is not None:
        info = districts_by_ids(session, [district_pk]).get(district_pk)
        if info is None:
            return None
        return trip_directions.stored_end(session, info.region_id, district_pk)
    return trip_directions.stored_end(session, region_pk, None)


def criteria_area(session: Session, *, region_id: str | None, district_id: str | None, field_name: str):  # noqa: ANN201
    """A feed criteria end (a district or a region - exactly one) as an area; 404 for an unknown id."""
    if (region_id is None) == (district_id is None):
        raise _validation(f"{field_name}_district_id", "exactly_one_of_district_or_region")
    if district_id is not None:
        area = _area(session, region_pk=None, district_pk=_district_pk(session, district_id, f"{field_name}_district_id"))
    else:
        area = _area(session, region_pk=_region_pk(session, region_id, f"{field_name}_region_id"), district_pk=None)
    if area is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": f"{field_name}_district_id"})
    return area


def roads_between(session: Session, origin, destination) -> dict[int, list]:  # noqa: ANN001
    """Open corridors whose confirmed roads run from the origin area to the destination area, with those roads."""
    from app.modules.geo.service import list_public_corridors
    from app.modules.trips import directions as trip_directions

    result: dict[int, list] = {}
    for corridor, _services in sorted(list_public_corridors(session), key=lambda row: row[0].id):
        routes = trip_directions._routes_for(session, corridor, origin, destination)  # noqa: SLF001 - same placement rule
        if routes:
            result[corridor.id] = routes
    return result


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


class _Reads:
    """Read-only lookups with per-call caches (one feed request / one consumer call)."""

    def __init__(self, session: Session, now: datetime) -> None:
        self.session = session
        self.now = now
        self._capable: dict[int, bool] = {}
        self._visible: dict[tuple[int, str], bool] = {}
        self._bands: dict[tuple[int, str], object] = {}

    def can_offer_as_driver(self, user_id: int) -> bool:
        """P9/Q40: only a user who could make a driver offer may see or be notified about client requests."""
        if user_id not in self._capable:
            caps = identity_service.get_capabilities(self.session, user_id, now=self.now)
            self._capable[user_id] = caps.has(Capability.PROPOSAL_SUBMIT_AS_DRIVER)
        return self._capable[user_id]

    def listing_visible(self, listing: Listing) -> bool:
        """Service flag (Q5, AC38) and an open corridor, as for publishing (A1 ports)."""
        key = (listing.corridor_id, listing.service_type)
        if key not in self._visible:
            ports = get_ports()
            flag = marketplace_service.SERVICE_FLAG[ServiceType(listing.service_type)]
            corridor = ports.geo.corridors_by_ids(self.session, [listing.corridor_id]).get(listing.corridor_id)
            self._visible[key] = (
                corridor is not None
                and corridor.is_open
                and ports.flags.is_enabled(self.session, flag, corridor_id=listing.corridor_id)
            )
        return self._visible[key]

    def band(self, corridor_id: int, service_type: ServiceType):  # noqa: ANN201
        """Q42 price *reference* for the ranking score: the corridor's band (ADR-0028)."""
        key = (corridor_id, service_type.value)
        if key not in self._bands:
            from app.modules.geo.service import resolve_price_band

            self._bands[key] = resolve_price_band(self.session, corridor_id=corridor_id, service_type=service_type)
        return self._bands[key]


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
    key: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class FeedPage:
    items: list[RankedItem]
    next_key: tuple[int, int, int] | None
    limit: int
    ranking_version: str = RANKING_VERSION
    match_scope: str = MATCH_SCOPE_CONFIRMED_ROADS
    degraded: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedCriteria:
    service_type: ServiceType
    side: FeedSide
    date_from: datetime
    date_to: datetime
    origin_region_id: str | None = None
    origin_district_id: str | None = None
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
    ready: bool
    when: datetime
    fit: float = NEUTRAL_FIT_SCORE


def _paginate(items: list[RankedItem], after_key: tuple[int, int, int] | None, limit: int) -> tuple[list[RankedItem], tuple[int, int, int] | None]:
    ordered = sorted(items, key=lambda item: item.key)
    if after_key is not None:
        ordered = [item for item in ordered if item.key > tuple(after_key)]
    page = ordered[:limit]
    return page, (page[-1].key if len(ordered) > limit and page else None)


def _page_markers(session: Session) -> tuple[str, ...]:
    # Q46: production offers confirmed roads only by policy. Elsewhere detours would be allowed but the feed does not
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
    service_type: ServiceType,
    corridor_ids: Iterable[int],
    window_from: datetime,
    window_to: datetime,
    exclude_owner_id: int,
    now: datetime,
    blocked_owner_ids: Collection[int] = (),
) -> list[Listing]:
    """Published client requests of these corridors whose window meets ``[window_from, window_to)`` (Q138)."""
    corridors = sorted(set(corridor_ids))
    if not corridors:
        return []
    stmt = select(Listing).where(
        Listing.kind == ListingKind.REQUEST.value,
        Listing.service_type == service_type.value,
        Listing.status == PUBLISHED,
        Listing.expires_at > now,
        Listing.departure_window_end > now,
        Listing.corridor_id.in_(corridors),
        Listing.owner_user_id != exclude_owner_id,
        Listing.departure_window_start < window_to,
        Listing.departure_window_end > window_from,
    )
    if blocked_owner_ids:
        # §8.1: a block hides the pair from each other before anything is scored or pushed.
        stmt = stmt.where(Listing.owner_user_id.notin_(sorted(blocked_owner_ids)))
    return list(
        session.execute(stmt.order_by(Listing.departure_window_start, Listing.id).limit(rules.FEED_CANDIDATE_LIMIT)).scalars()
    )


def _evaluate_request_on_road(
    reads: _Reads,
    listing: Listing,
    *,
    roads: dict[int, list],
    origin,  # noqa: ANN001 - trips DirectionEnd
    destination,  # noqa: ANN001 - trips DirectionEnd
    window_start: datetime,
    window_end: datetime,
    seats: int | None,
    include_alternatives: bool,
    max_total_minor: int | None,
    amenities: Sequence[str],
) -> _Eval | None:
    """A client request for a driver (ADR-0028): both places on a confirmed road of the listing's corridor, inside the
    stretch between the driver's two areas, pickup before dropoff - plus time. A near-miss in time is the only
    ``alternative`` (every place on the road is on the road).
    """
    if not reads.listing_visible(listing):
        return None
    routes = roads.get(listing.corridor_id)
    if not routes:
        return None
    from app.modules.marketplace import directions as market_directions

    base = market_directions.road_match(reads.session, listing, routes, origin, destination)
    if base is None:
        return None
    gap = rules.window_gap(listing.departure_window_start, listing.departure_window_end, window_start, window_end)
    reasons: list[MatchReason]
    if gap == timedelta(0):
        match_type = base
        reasons = [MatchReason.FULL_ROUTE if base is MatchType.EXACT else MatchReason.INTERMEDIATE_SEGMENT]
    elif include_alternatives and gap <= rules.ALTERNATIVE_TIME_TOLERANCE:
        match_type = MatchType.ALTERNATIVE
        reasons = [MatchReason.TIME_DIFFERS]
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
        ready=listing.status == PUBLISHED and ensure_aware_utc(listing.expires_at) > reads.now,
        when=ensure_aware_utc(listing.departure_window_start),
        fit=fit,
    )


def _driver_components(
    reads: _Reads, listing: Listing, ev: _Eval, summary: ReputationSummary, *, window: tuple[datetime, datetime]
) -> dict[str, float]:
    service = ServiceType(listing.service_type)
    group = rules.group_for(ev.match_type)
    band = reads.band(listing.corridor_id, service)
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
    """§20.4: count one feed search and whether it found anything. No user id, no places, no filters.

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
    """M1 ``requests``: client requests for a driver (§8.4 score). ``offers`` is retired (Q138).

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
    # P9 visibility (Q40): only drivers who could make an offer see client requests.
    identity_service.require_capability(
        identity_service.get_capabilities(session, viewer_user_id, now=now), Capability.PROPOSAL_SUBMIT_AS_DRIVER
    )
    # ADR-0028: the two ends are areas; the roads between them decide which corridors are searched.
    origin = criteria_area(
        session, region_id=criteria.origin_region_id, district_id=criteria.origin_district_id, field_name="origin"
    )
    destination = criteria_area(
        session, region_id=criteria.destination_region_id, district_id=criteria.destination_district_id,
        field_name="destination",
    )
    roads = roads_between(session, origin, destination)
    markers = _page_markers(session)
    extend = rules.ALTERNATIVE_TIME_TOLERANCE if criteria.include_alternatives else timedelta(0)
    candidates = _candidates(
        session,
        service_type=service,
        corridor_ids=roads.keys(),
        window_from=window[0] - extend,
        window_to=window[1] + extend,
        exclude_owner_id=viewer_user_id,
        now=now,
        blocked_owner_ids=_blocked_ids(session, viewer_user_id),
    )
    reads = _Reads(session, now)
    evaluated: list[tuple[Listing, _Eval]] = []
    for listing in candidates:
        ev = _evaluate_request_on_road(
            reads,
            listing,
            roads=roads,
            origin=origin,
            destination=destination,
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
        components = _driver_components(reads, listing, ev, summary, window=window)
        items.append(_ranked(listing, ev, components, rules.driver_score(**components), summary, FeedSort(criteria.sort)))
    page, next_key = _paginate(items, after_key, limit)
    return FeedPage(items=page, next_key=next_key, limit=limit, degraded=markers)


# --- M3-M5 saved searches --------------------------------------------------------------------------------------------


def saved_search_public_id(row: SavedSearch) -> str:
    return format_public_id(PublicIdPrefix.SAVED_SEARCH, row.public_id)


def _limit_reached() -> DomainError:
    return DomainError(ErrorCode.SAVED_SEARCH_LIMIT_REACHED, details={"limit": SAVED_SEARCH_MAX_PER_USER})


def _end_refs(
    session: Session, *, region_id: str | None, district_id: str | None, field_name: str
) -> tuple[int | None, int | None]:
    """``(region_id, district_id)`` - exactly one is set, as the DB CHECK demands."""
    if district_id is not None:
        return None, _district_pk(session, district_id, f"{field_name}_district_id")
    return _region_pk(session, region_id, f"{field_name}_region_id"), None


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
    origin_region, origin_district = _end_refs(
        session, region_id=data.origin_region_id, district_id=data.origin_district_id, field_name="origin"
    )
    destination_region, destination_district = _end_refs(
        session, region_id=data.destination_region_id, district_id=data.destination_district_id, field_name="destination"
    )
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
        origin_region_id=origin_region,
        origin_district_id=origin_district,
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


def _search_matches(reads: _Reads, search: SavedSearch, listing: Listing) -> bool:
    """ADR-0028: the request's two places on a road of its corridor, between the search's two areas - the same rule
    as the feed - with the windows meeting and the seats fitting."""
    origin = _area(reads.session, region_pk=search.origin_region_id, district_pk=search.origin_district_id)
    destination = _area(reads.session, region_pk=search.destination_region_id, district_pk=search.destination_district_id)
    if origin is None or destination is None:
        return False
    from app.modules.geo.service import get_corridor
    from app.modules.marketplace import directions as market_directions
    from app.modules.trips import directions as trip_directions

    corridor = get_corridor(reads.session, listing.corridor_id)
    routes = trip_directions._routes_for(reads.session, corridor, origin, destination)  # noqa: SLF001
    if not routes or market_directions.road_match(reads.session, listing, routes, origin, destination) is None:
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

    Matching: same service; a client request (Q138) whose two places lie on a confirmed road between the search's two
    areas (district or region), in order, with the windows meeting; quantity fits; not the owner's own listing.
    Hidden listings (flags, closed corridor) notify nobody. Several matching searches of one user give one notification (§6.6). A
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
    if listing.kind != ListingKind.REQUEST.value or not reads.listing_visible(listing):
        return 0  # Q138: a retired driver listing notifies nobody
    stmt = select(SavedSearch).where(
        SavedSearch.service_type == listing.service_type,
        SavedSearch.side == FeedSide.REQUESTS.value,
        SavedSearch.deleted_at.is_(None),
        SavedSearch.notify.is_(True),
        SavedSearch.time_window_end > now,
        SavedSearch.user_id != listing.owner_user_id,
        SavedSearch.time_window_start < listing.departure_window_end,
        SavedSearch.time_window_end > listing.departure_window_start,
    )
    chosen: dict[int, SavedSearch] = {}
    for search in session.execute(stmt.order_by(SavedSearch.id)).scalars():
        if search.user_id in chosen:
            continue
        # Eligibility may change after the search was saved: requests go only to users who can still offer (P9/Q40).
        if not reads.can_offer_as_driver(search.user_id):
            continue
        if _search_matches(reads, search, listing):
            chosen[search.user_id] = search
    listing_ref = marketplace_service.listing_public_id(listing)
    side = FeedSide.REQUESTS.value
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
