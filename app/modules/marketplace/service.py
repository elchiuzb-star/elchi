"""Marketplace domain API (A1): listings (L1-L8) and proposal threads/versions (P1-P7).

Accept/booking is A4. Public functions take the caller's ``Session`` and never commit
(ADR-0001, AGENTS §4) - the worker entry points ``expire_due_proposals`` / ``expire_due_listings`` included:
the worker commits each ``limit``-sized batch (wave 2.1).

Lock order (ADR-0017): users -> trips -> listings -> proposal_threads. Exclusive row locks are
``FOR NO KEY UPDATE`` so foreign-key inserts (``FOR KEY SHARE``) never deadlock against them.

Signatures other modules may rely on:

* ``lock_listing(session, listing_id) -> Listing`` / ``lock_listings(session, ids) -> list[Listing]``
* ``lock_thread(session, thread_id) -> ProposalThread``
* ``current_version(session, thread, *, for_update=False) -> ProposalVersion | None``
* ``version_demand(version) -> ResourceDemand``  (what A4 reserves; seats = quantity for passenger)
* ``get_listing_by_public_id``, ``get_thread_by_public_id``, ``get_version_by_public_id``
* ``create_listing``, ``patch_listing``, ``publish_listing``, ``pause_listing``, ``resume_listing``, ``cancel_listing``
* ``submit_proposal``, ``counter_proposal``, ``reject_proposal``, ``withdraw_proposal``
* ``listings_for_trip``, ``has_published_trip_offer``
* ``expire_threads_for_trip(session, trip_id, *, reason, now)``, ``assert_trip_offers_on_trip(session, trip_id)``
* ``expire_due_proposals(session, *, now=None, limit=200)``, ``expire_due_listings(...)`` (worker jobs)

A proposal never reserves seats, cargo or balance (spec §5.3): capacity is only checked.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.contracts.enums import (
    ActorSide,
    Capability,
    EventType,
    FeatureFlagKey,
    ListingKind,
    ListingStatus,
    PriceBasis,
    ProposalStatus,
    ServiceType,
    TripStatus,
)
from app.contracts import contact_filter
from app.contracts.errors import DomainError, ErrorCode, WarningCode
from app.contracts.events import EventEnvelope
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.marketplace import (
    LISTING_PUBLISH_RATE_LIMIT,
    LISTING_PUBLISH_RATE_WINDOW_S,
    PARCEL_PILOT_MAX_DIMENSION_CM,
    PARCEL_PILOT_MAX_VOLUME_ML,
    PARCEL_PILOT_MAX_WEIGHT_G,
)
from app.contracts.money import commission_minor
from app.contracts.state_machines import LISTING, PROPOSAL_VERSION
from app.contracts.timeutil import ensure_aware_utc, to_iso_utc, utc_now
from app.models import AuditLog
from app.modules.geo.types import MatchRequest, OccurrenceTiming, TripRouteContext
from app.modules.identity import service as identity_service
from app.modules.marketplace.models import (
    Listing,
    ListingOfferLabel,
    ListingView,
    ParcelListingDetails,
    ParcelPolicyItem,
    ParcelPolicyVersion,
    PassengerListingDetails,
    ProposalThread,
    ProposalVersion,
)
from app.modules.marketplace.ports import CorridorRef, FeeQuote, get_ports
from app.modules.platform import service as platform_service
from app.modules.marketplace.rules import (
    LISTING_TIMEZONE,
    check_proposal_quantity,
    compute_total_minor,
    ensure_price_basis_allowed,
    listing_quantity,
    next_price_revision_count,
    parcel_volume_ml,
    proposal_expires_at,
    proposer_side,
)
from app.modules.marketplace.schemas import (
    ListingCreate,
    ListingPatch,
    ParcelDetails,
    PassengerDetails,
    PointEndInput,
    ProposalBaggage,
    ProposalCounter,
    ProposalCreate,
    ProposalParcel,
)
from app.modules.platform.service import constraint_name_of, enqueue_event
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip
from app.modules.trips.ports import StopRef
from app.modules.trips.rules import ResourceDemand, shortfall_error

__all__ = [
    "THREAD_ACCEPTED",
    "THREAD_CLOSED",
    "THREAD_OPEN",
    "accept_version",
    "actor_side",
    "cancel_listing_for_booking",
    "close_open_threads",
    "fulfil_listing",
    "reopen_listing",
    "assert_trip_offers_on_trip",
    "cancel_listing",
    "counter_proposal",
    "create_listing",
    "current_version",
    "driver_offer_label",
    "offer_labels",
    "parcel_receiver",
    "ContactFilterHit",
    "filter_free_text",
    "record_contact_filter_hits",
    "record_staff_listing_contact_view",
    "list_listing_offers",
    "ListingOffer",
    "expire_due_listings",
    "expire_due_proposals",
    "expire_threads_for_trip",
    "get_listing",
    "get_listing_by_public_id",
    "get_parcel_details",
    "get_passenger_details",
    "get_thread_by_public_id",
    "get_thread_for_party",
    "get_version_by_public_id",
    "has_published_trip_offer",
    "list_listing_threads",
    "list_owner_listings",
    "list_user_threads",
    "listing_public_id",
    "listings_for_trip",
    "lock_listing",
    "lock_listings",
    "lock_thread",
    "patch_listing",
    "pause_listing",
    "publish_listing",
    "reject_proposal",
    "resolve_listing_id",
    "resume_listing",
    "submit_proposal",
    "thread_public_id",
    "thread_versions",
    "version_demand",
    "version_public_id",
    "withdraw_proposal",
    "point_segment_for_trip",
    "preview_point_direction",
]

OPEN_TRIP_OFFER_INDEX = "uq_listings_open_trip_offer"
OPEN_THREAD_INDEX = "uq_proposal_threads_open_context"
ACTIVE_VERSION_INDEX = "uq_proposal_versions_active"

THREAD_OPEN = "open"
THREAD_ACCEPTED = "accepted"
THREAD_CLOSED = "closed"

LISTING_CREATE_CAPABILITY: dict[ListingKind, Capability] = {
    ListingKind.REQUEST: Capability.LISTING_CREATE_REQUEST,
    ListingKind.TRIP_OFFER: Capability.LISTING_CREATE_TRIP_OFFER,
}
PROPOSAL_CAPABILITY: dict[ActorSide, Capability] = {
    ActorSide.CLIENT: Capability.PROPOSAL_SUBMIT_AS_CLIENT,
    ActorSide.DRIVER: Capability.PROPOSAL_SUBMIT_AS_DRIVER,
}
SERVICE_FLAG: dict[ServiceType, FeatureFlagKey] = {
    ServiceType.PASSENGER: FeatureFlagKey.PASSENGER_ENABLED,
    ServiceType.PARCEL: FeatureFlagKey.PARCEL_ENABLED,
}
DUPLICATE_CHECK_STATUSES = (ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value)
EDITABLE_STATUSES = (ListingStatus.DRAFT.value, ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value)
LIVE_STATUSES = (ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value)
EXPIRABLE_STATUSES = (ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value, ListingStatus.FULFILLED.value)
CLOSED_OFFER_STATUSES = (ListingStatus.CANCELLED.value, ListingStatus.EXPIRED.value)
REQUEST_PARCEL_REQUIRED = (
    "parcel_type",
    "weight_g",
    "length_cm",
    "width_cm",
    "height_cm",
    "payer",
    "sender_name",
    "sender_phone",
    "receiver_name",
    "receiver_phone",
)
OFFER_PARCEL_REQUIRED = ("max_weight_g", "max_volume_ml", "max_dimension_cm")


# --- helpers ----------------------------------------------------------------------------------


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


def _check_version(current: int, expected: int) -> None:
    if current != expected:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": current})


def _duplicate_listing() -> DomainError:
    return DomainError(ErrorCode.DUPLICATE_LISTING, details={"reason": "open_trip_offer_exists"})


def listing_public_id(listing: Listing) -> str:
    return format_public_id(PublicIdPrefix.LISTING, listing.public_id)


def thread_public_id(thread: ProposalThread) -> str:
    return format_public_id(PublicIdPrefix.PROPOSAL_THREAD, thread.public_id)


def version_public_id(version: ProposalVersion) -> str:
    return format_public_id(PublicIdPrefix.PROPOSAL_VERSION, version.public_id)


def _emit(
    session: Session,
    event_type: EventType,
    *,
    aggregate_type: str,
    aggregate_public_id: str,
    aggregate_version: int,
    aggregate_id: int,
    payload: dict,
    now: datetime,
) -> None:
    enqueue_event(
        session,
        EventEnvelope(event_type, aggregate_type, aggregate_public_id, aggregate_version, now, payload),
        aggregate_id=aggregate_id,
    )


# --- free-text contact filter (R2, ADR-0020, Q43-Q44) -------------------------------------------

@dataclass(frozen=True, slots=True)
class ContactFilterHit:
    """One contact-filter match summary (no raw text) for audit and the Q45 strike signal."""

    actor_user_id: int
    field: str
    subject_type: str
    categories: dict[str, int]
    match_count: int
    filter_version: str


def filter_free_text(
    session: Session,
    *,
    actor_user_id: int,
    field: str,
    text: str | None,
    warnings: list[dict] | None,
    filter_hits: list[ContactFilterHit] | None = None,
) -> str | None:
    """Mask contact info in user free text before it is stored; only the masked text is persisted.

    On a hit a ``CONTACT_INFO_MASKED`` warning is appended to ``warnings`` and a
    :class:`ContactFilterHit` to ``filter_hits``. The API persists ``filter_hits`` with
    :func:`record_contact_filter_hits` in its own committed transaction after the command, so a later
    4xx cannot erase the record (R2-b, Q45). Without a sink the hit is recorded in the caller's transaction.
    """
    if text is None:
        return None
    result = contact_filter.scan(text)
    if not result.has_contact:
        return text
    hit = ContactFilterHit(
        actor_user_id=actor_user_id,
        field=field,
        subject_type="proposal" if field == "message" or field.startswith("proposal.") else "listing",
        categories=dict(sorted(Counter(match.category.value for match in result.matches).items())),
        match_count=len(result.matches),
        filter_version=result.filter_version,
    )
    if filter_hits is None:
        record_contact_filter_hits(session, [hit])
    else:
        filter_hits.append(hit)
    if warnings is not None:
        warnings.append({"code": WarningCode.CONTACT_INFO_MASKED.value, "field": field, **result.warning_details()})
    return result.masked_text


def record_contact_filter_hits(session: Session, hits: Sequence[ContactFilterHit]) -> None:
    """Audit row (category counts only) + staff-only ``CONTACT_FILTER_HIT`` event per hit. Never commits."""
    now = utc_now()
    for hit in hits:
        actor_public_id = identity_service.user_public_id(session, hit.actor_user_id)
        session.add(
            AuditLog(
                actor_id=hit.actor_user_id,
                entity_type="contact_filter",
                entity_id=None,
                action="contact_filter_hit",
                details={
                    "field": hit.field,
                    "subject_type": hit.subject_type,
                    "categories": hit.categories,
                    "match_count": hit.match_count,
                    "filter_version": hit.filter_version,
                },
            )
        )
        _emit(
            session,
            EventType.CONTACT_FILTER_HIT,  # staff-only audience (events.EVENT_AUDIENCES)
            aggregate_type="user",
            aggregate_public_id=actor_public_id,
            aggregate_version=1,
            aggregate_id=hit.actor_user_id,
            payload={
                "actor_id": actor_public_id,
                "subject_type": hit.subject_type,
                "field": hit.field,
                "categories": sorted(hit.categories),
                "match_count": hit.match_count,
                "filter_version": hit.filter_version,
            },
            now=now,
        )
    session.flush()


def record_staff_listing_contact_view(
    session: Session, *, actor_user_id: int, listing_ids: Sequence[str], surface: str, fields: Sequence[str]
) -> None:
    """``audit_logs`` row ``listing_contacts_viewed`` when a staff response shows phones (BR M2, Q44).

    Only public listing ids, the surface and field names are stored - never a phone value. No commit.
    """
    if not listing_ids or not fields:
        return
    session.add(
        AuditLog(
            actor_id=actor_user_id,
            entity_type="listing",
            entity_id=None,  # audit_logs.entity_id is INTEGER; public ids go into details
            action="listing_contacts_viewed",
            details={"listing_ids": list(listing_ids), "surface": surface, "fields": sorted(set(fields))},
        )
    )
    session.flush()


def _filtered_passenger(
    session: Session,
    actor_user_id: int,
    passenger: PassengerDetails | None,
    warnings: list[dict] | None,
    filter_hits: list | None = None,
) -> PassengerDetails | None:
    """R2-a: special assistance is free text. Amenities, parcel types and accepted parcel types are strict
    contract enums since Q68 (validated by the schema, 400 ``VALIDATION_ERROR``), so they are not filtered."""
    if passenger is None:
        return None
    return passenger.model_copy(
        update={
            "special_assistance": filter_free_text(
                session,
                actor_user_id=actor_user_id,
                field="passenger.special_assistance",
                text=passenger.special_assistance,
                warnings=warnings,
                filter_hits=filter_hits,
            ),
        }
    )


def _enum_values(items: Sequence) -> list[str]:  # noqa: ANN001
    """Enum members -> plain strings for TEXT[] columns, first occurrence kept (Q68)."""
    return list(dict.fromkeys(str(getattr(item, "value", item)) for item in items))


# --- listings: reads and locks ------------------------------------------------------------------


def resolve_listing_id(session: Session, public_id: str) -> int:
    value = parse_public_id(public_id, PublicIdPrefix.LISTING)
    listing_id = session.execute(select(Listing.id).where(Listing.public_id == value)).scalar_one_or_none()
    if listing_id is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return listing_id


def get_listing(session: Session, listing_id: int) -> Listing:
    listing = session.get(Listing, listing_id)
    if listing is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return listing


def get_listing_by_public_id(session: Session, public_id: str) -> Listing:
    return get_listing(session, resolve_listing_id(session, public_id))


def lock_listing(session: Session, listing_id: int) -> Listing:
    listing = session.execute(
        select(Listing)
        .where(Listing.id == listing_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if listing is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return listing


def _try_lock_listing(session: Session, listing_id: int) -> Listing | None:
    """Worker variant: skip a listing a user command is holding right now."""
    return session.execute(
        select(Listing)
        .where(Listing.id == listing_id)
        .with_for_update(key_share=True, skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def lock_listings(session: Session, listing_ids: Sequence[int]) -> list[Listing]:
    ids = sorted(set(listing_ids))
    if not ids:
        return []
    return list(
        session.execute(
            select(Listing)
            .where(Listing.id.in_(ids))
            .order_by(Listing.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).scalars()
    )


def get_passenger_details(session: Session, listing_id: int) -> PassengerListingDetails | None:
    return session.get(PassengerListingDetails, listing_id)


def get_parcel_details(session: Session, listing_id: int) -> ParcelListingDetails | None:
    return session.get(ParcelListingDetails, listing_id)


def listings_for_trip(session: Session, trip_id: int) -> list[Listing]:
    return list(session.execute(select(Listing).where(Listing.trip_id == trip_id).order_by(Listing.id)).scalars())


def has_published_trip_offer(session: Session, trip_id: int) -> bool:
    return (
        session.execute(
            select(Listing.id).where(
                Listing.trip_id == trip_id,
                Listing.kind == ListingKind.TRIP_OFFER.value,
                Listing.status == ListingStatus.PUBLISHED.value,
            )
        ).first()
        is not None
    )


def list_owner_listings(
    session: Session,
    owner_user_id: int,
    *,
    status: str | None = None,
    kind: str | None = None,
    service_type: str | None = None,
    before: tuple[datetime, int] | None = None,
    limit: int = 20,
) -> list[Listing]:
    stmt = select(Listing).where(Listing.owner_user_id == owner_user_id)
    if status:
        stmt = stmt.where(Listing.status == status)
    if kind:
        stmt = stmt.where(Listing.kind == kind)
    if service_type:
        stmt = stmt.where(Listing.service_type == service_type)
    if before is not None:
        created_at, listing_id = before
        stmt = stmt.where(
            (Listing.created_at < created_at) | ((Listing.created_at == created_at) & (Listing.id < listing_id))
        )
    return list(session.execute(stmt.order_by(Listing.created_at.desc(), Listing.id.desc()).limit(limit)).scalars())


# --- listings: validation helpers ------------------------------------------------------------------


def _stop_refs_by_public_ids(session: Session, public_ids: Sequence[str], field: str) -> list[StopRef]:
    for public_id in public_ids:
        parse_public_id(public_id, PublicIdPrefix.STOP)
    refs = get_ports().geo.stops_by_public_ids(session, list(public_ids))
    resolved = []
    for public_id in public_ids:
        ref = refs.get(public_id)
        if ref is None:
            raise DomainError(ErrorCode.NOT_FOUND, details={"field": field})
        resolved.append(ref)
    return resolved


def _open_corridor(session: Session, origin: StopRef, destination: StopRef) -> CorridorRef:
    if origin.corridor_id != destination.corridor_id:
        raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"reason": "stops_in_different_corridors"})
    if not (origin.is_active and destination.is_active):
        raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"reason": "stop_not_active"})
    corridor = get_ports().geo.corridors_by_ids(session, [origin.corridor_id]).get(origin.corridor_id)
    if corridor is None or not corridor.is_open:
        raise DomainError(
            ErrorCode.CORRIDOR_NOT_ACTIVE,
            details={"reason": "corridor_not_open", "rollout_state": corridor.rollout_state if corridor else None},
        )
    return corridor


def _assert_listing_corridor_open(session: Session, listing: Listing) -> CorridorRef:
    """The listing's corridor must still be open, whichever kind of ends it has (Q88).

    For a stop-ended listing this is the same question :func:`_open_corridor` asks, plus the stops being
    active. For a point-ended one there are no stops to consult and the corridor recorded on the listing is
    the answer.
    """
    if listing.origin_stop_id is not None and listing.destination_stop_id is not None:
        stops = get_ports().geo.stops_by_ids(session, [listing.origin_stop_id, listing.destination_stop_id])
        return _open_corridor(session, stops[listing.origin_stop_id], stops[listing.destination_stop_id])
    corridor = get_ports().geo.corridors_by_ids(session, [listing.corridor_id]).get(listing.corridor_id)
    if corridor is None or not corridor.is_open:
        raise DomainError(
            ErrorCode.CORRIDOR_NOT_ACTIVE,
            details={"reason": "corridor_not_open", "rollout_state": corridor.rollout_state if corridor else None},
        )
    return corridor


@dataclass(frozen=True, slots=True)
class EndPlacement:
    """Where one end of a direction sits on a corridor's confirmed road (Q88).

    A stop end takes its position from ``route_version_stops.line_fraction``; a point end is projected onto the
    line. Either way the placement answers the two questions the rest of the engine needs: *how far along the
    road* (so pickup can be proved to come before dropoff) and *which segment* (so capacity is still counted
    per segment, AC12).
    """

    stop: StopRef | None
    point: PointEndInput | None
    district_id: int | None
    fraction: float
    offset_m: int | None
    seq_before: int
    seq_after: int
    #: Interpolated from the projection - what an ETA for a place between two stops has to be built on.
    cumulative_distance_m: int = 0
    cumulative_duration_s: int = 0
    #: Position inside the segment (0..1), used to interpolate the trip's own arrival times.
    segment_ratio: float = 0.0

    @property
    def is_point(self) -> bool:
        return self.point is not None


def _district_pk(session: Session, public_id: str) -> int:
    """Advisory only (Q88): it files the booking, it never decides whether the ride is possible."""
    from app.modules.geo.service import get_district_by_api_id

    try:
        return get_district_by_api_id(session, public_id).id
    except DomainError:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "district_id"}) from None


def _place_on_route(
    session: Session, route, end, *, max_offset_m: int, district_id: int | None = None
):  # noqa: ANN001, ANN202 - RouteVersionInfo / point-or-stop
    """Place one end on one confirmed route, or ``None`` when it does not belong to it.

    ``district_id`` is already resolved by the caller: this function is also used to *re-*validate stored rows,
    where the district is a pk we wrote earlier rather than a public id a client just sent.
    """
    from app.modules.geo.service import project_point_on_route
    from app.modules.geo.geometry import LatLng

    stop, point = end
    if stop is not None:
        for index, route_stop in enumerate(route.stops):
            if route_stop.stop_id == stop.id:
                after = route.stops[min(index + 1, len(route.stops) - 1)]
                return EndPlacement(
                    stop=stop, point=None, district_id=None,
                    fraction=float(route_stop.line_fraction), offset_m=0,
                    seq_before=route_stop.seq, seq_after=after.seq,
                    cumulative_distance_m=route_stop.cumulative_distance_m,
                    cumulative_duration_s=route_stop.cumulative_duration_s,
                )
        return None
    projection = project_point_on_route(
        session, route_version_id=route.id, point=LatLng(lat=point.lat, lng=point.lng), max_offset_m=max_offset_m
    )
    if projection is None:
        return None
    return EndPlacement(
        stop=None, point=point, district_id=district_id,
        fraction=projection.fraction, offset_m=projection.offset_m,
        seq_before=projection.seq_before, seq_after=projection.seq_after,
        cumulative_distance_m=projection.cumulative_distance_m,
        cumulative_duration_s=projection.cumulative_duration_s,
        segment_ratio=projection.segment_ratio,
    )


def _apply_point_ends(row, origin_place, destination_place) -> None:  # noqa: ANN001
    """Write the map-point columns of a listing/proposal/booking row (Q88).

    The geometry goes in as EWKT through ``ST_GeomFromEWKT`` exactly like every other point in the geo module,
    so the column keeps its SRID and the GiST index stays usable.
    """
    from sqlalchemy import func

    from app.modules.geo.geometry import LatLng, point_ewkt

    prefixes = ("origin", "destination") if hasattr(row, "origin_stop_id") else ("pickup", "dropoff")
    for prefix, place in zip(prefixes, (origin_place, destination_place)):
        if place is None or not place.is_point:
            continue
        setattr(row, f"{prefix}_point", func.ST_GeomFromEWKT(point_ewkt(LatLng(lat=place.point.lat, lng=place.point.lng))))
        setattr(row, f"{prefix}_district_id", place.district_id)
        setattr(row, f"{prefix}_address", place.point.address)
        setattr(row, f"{prefix}_route_offset_m", place.offset_m)


def _resolve_point_direction(session: Session, data: ListingCreate):  # noqa: ANN202
    """Q88: find the corridor whose confirmed road actually serves both ends, in the right order.

    The client is not the source of truth here. It sends two places; the server decides which corridor - if any
    - can carry them, by projecting both onto each candidate's confirmed route. A corridor qualifies only when
    both ends land within *its* configured radius (migration 0077) and the origin lies before the destination
    along the line. When several qualify, the one the places sit closest to wins, and ties break on corridor id
    so the same request always resolves the same way.
    """
    from app.modules.geo.service import corridor_point_offset_m, get_route_version, list_corridor_routes

    ends = ((data.origin_stop_id, data.origin_point), (data.destination_stop_id, data.destination_point))
    stops_by_field = {}
    for field, (stop_public_id, _point) in zip(("origin_stop_id", "destination_stop_id"), ends):
        if stop_public_id is not None:
            stops_by_field[field] = _stop_refs_by_public_ids(session, [stop_public_id], field)[0]

    geo = get_ports().geo
    if stops_by_field:
        candidate_ids = {ref.corridor_id for ref in stops_by_field.values()}
        if len(candidate_ids) > 1:
            raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"reason": "stops_in_different_corridors"})
    else:
        candidate_ids = set(_open_corridor_ids(session))

    best = None
    for corridor_id in sorted(candidate_ids):
        corridor = geo.corridors_by_ids(session, [corridor_id]).get(corridor_id)
        if corridor is None or not corridor.is_open:
            continue
        radius = corridor_point_offset_m(session, corridor_id)
        for route_ref in list_corridor_routes(session, _corridor_info(session, corridor_id), limit=5):
            route = get_route_version(session, route_ref.id)
            placements = [
                _place_on_route(
                    session,
                    route,
                    (stops_by_field.get(field), point),
                    max_offset_m=radius,
                    district_id=_district_pk(session, point.district_id) if point is not None else None,
                )
                for field, (_stop, point) in zip(("origin_stop_id", "destination_stop_id"), ends)
            ]
            if any(placement is None for placement in placements):
                continue
            origin, destination = placements
            if origin.fraction >= destination.fraction:
                # The road runs the other way; a listing must not be publishable "backwards".
                continue
            cost = (origin.offset_m or 0) + (destination.offset_m or 0)
            if best is None or cost < best[0]:
                best = (cost, corridor, route, origin, destination)
    if best is None:
        raise DomainError(
            ErrorCode.ROUTE_MISMATCH,
            details={"reason": "no_confirmed_route_serves_both_points"},
        )
    _cost, corridor, route, origin, destination = best
    return corridor, route, origin, destination


def _open_corridor_ids(session: Session) -> list[int]:
    """Every corridor a listing may open on today (G2's public list: operable and service-enabled)."""
    from app.modules.geo.service import list_public_corridors

    return [corridor.id for corridor, _services, _stops in list_public_corridors(session)]


def _corridor_info(session: Session, corridor_id: int):  # noqa: ANN202
    from app.modules.geo.service import get_corridor

    return get_corridor(session, corridor_id)


def _require_service_flags(session: Session, listing: Listing, *, include_driver_listing: bool) -> None:
    flags = [SERVICE_FLAG[ServiceType(listing.service_type)]]
    if include_driver_listing and listing.kind == ListingKind.TRIP_OFFER.value:
        flags.append(FeatureFlagKey.DRIVER_LISTING_ENABLED)
    port = get_ports().flags
    for flag in flags:
        if not port.is_enabled(session, flag, corridor_id=listing.corridor_id):
            raise DomainError(ErrorCode.FEATURE_DISABLED, details={"flag": flag.value})


CARGO_PHOTO_UPLOAD_TYPE = "cargo_photo"


def _resolve_cargo_photo(value: str | None, *, uploader_user_id: int, current_stored: str | None) -> str | None:
    """Normalise a client-supplied cargo photo reference to a storage key bound to its uploader.

    What arrives from the app is whatever ``POST /api/v1/files/upload`` handed back - a *signed URL*. Storing
    that string would be wrong twice: the signature expires, and a signed URL in a DB column is a credential at
    rest. So the reference is resolved the way H0 resolves every other attachment: it must point into our
    upload store, it must be an image, and it must belong to the person attaching it. An unchanged value is
    kept as it is, so an edit by the same owner never has to re-upload.
    """
    if value is None:
        return None
    from app.utils import file_access, file_validation

    def invalid(reason: str) -> DomainError:
        return DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel.photo_file_id", "reason": reason})

    if CARGO_PHOTO_UPLOAD_TYPE not in file_validation.ALLOWED_UPLOAD_TYPES:
        raise invalid("cargo_photo_upload_type_unavailable")
    try:
        stored = file_access.resolve_attachment(
            value, user_id=uploader_user_id, expected_upload_type=CARGO_PHOTO_UPLOAD_TYPE, current_stored=current_stored
        )
    except file_access.FileReferenceError:
        raise invalid("invalid_file_reference") from None
    if stored is None:
        return None
    key = file_access.normalize_storage_key(stored)
    if key is None or file_access.key_extension(key) not in file_validation.ALLOWED_IMAGE_EXTENSIONS:
        raise invalid("not_an_image")
    return file_access.stored_value_for_key(key)


def _write_details(
    session: Session,
    listing: Listing,
    passenger: PassengerDetails | None,
    parcel: ParcelDetails | None,
    *,
    uploader_user_id: int,
) -> None:
    if passenger is not None:
        row = session.get(PassengerListingDetails, listing.id)
        if row is None:
            row = PassengerListingDetails(listing_id=listing.id)
            session.add(row)
        row.seat_count = passenger.seat_count
        row.adults = passenger.adults
        row.children = passenger.children
        row.child_seat_required = passenger.child_seat_required
        row.baggage_pieces = passenger.baggage.pieces
        row.baggage_total_weight_g = passenger.baggage.total_weight_g
        row.baggage_total_volume_ml = passenger.baggage.total_volume_ml
        row.special_assistance = passenger.special_assistance
        row.amenities = _enum_values(passenger.amenities)
    if parcel is not None:
        row = session.get(ParcelListingDetails, listing.id)
        if row is None:
            row = ParcelListingDetails(listing_id=listing.id)
            session.add(row)
        row.parcel_type = parcel.parcel_type.value if parcel.parcel_type is not None else None
        row.weight_g = parcel.weight_g
        row.length_cm = parcel.length_cm
        row.width_cm = parcel.width_cm
        row.height_cm = parcel.height_cm
        row.fragile = parcel.fragile
        row.declared_value_minor = parcel.declared_value_minor
        row.photo_file_id = _resolve_cargo_photo(
            parcel.photo_file_id, uploader_user_id=uploader_user_id, current_stored=row.photo_file_id
        )
        row.payer = parcel.payer.value if parcel.payer else None
        row.sender_name = parcel.sender.name if parcel.sender else None
        row.sender_phone = parcel.sender.phone if parcel.sender else None
        row.receiver_name = parcel.receiver.name if parcel.receiver else None
        row.receiver_phone = parcel.receiver.phone if parcel.receiver else None
        row.pickup_window_start = parcel.pickup_window_start
        row.pickup_window_end = parcel.pickup_window_end
        row.dropoff_window_start = parcel.dropoff_window_start
        row.dropoff_window_end = parcel.dropoff_window_end
        row.max_weight_g = parcel.max_weight_g
        row.max_volume_ml = parcel.max_volume_ml
        row.max_dimension_cm = parcel.max_dimension_cm
        row.accepted_parcel_types = _enum_values(parcel.accepted_parcel_types)


def _missing_fields(session: Session, listing: Listing) -> list[str]:
    kind, service = ListingKind(listing.kind), ServiceType(listing.service_type)
    if service is ServiceType.PASSENGER:
        if kind is ListingKind.REQUEST and get_passenger_details(session, listing.id) is None:
            return ["passenger"]
        return []
    parcel = get_parcel_details(session, listing.id)
    if parcel is None:
        return ["parcel"]
    required = REQUEST_PARCEL_REQUIRED if kind is ListingKind.REQUEST else OFFER_PARCEL_REQUIRED
    return [f"parcel.{name}" for name in required if getattr(parcel, name) is None]


def _trip_for_offer(session: Session, trip_public_id: str, owner_user_id: int) -> Trip:
    trip = trips_service.get_trip_by_public_id(session, trip_public_id)
    if trip.driver_user_id != owner_user_id:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": "trip_id"})
    if trip.status != TripStatus.PLANNED.value:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "trip", "from": trip.status})
    return trip


# --- listings: commands ---------------------------------------------------------------------------


def preview_point_direction(session: Session, *, origin: PointEndInput, destination: PointEndInput):  # noqa: ANN202
    """Q88: resolve two marked places to a corridor and its confirmed road, without creating anything.

    Same resolution the create path uses, so a preview that succeeds and a create that fails would be a bug,
    not a race. Raises ``ROUTE_MISMATCH`` when nothing serves them - which is the product's "these two places
    are not on an ELCHI route yet" state, not an error to hide.
    """
    from app.modules.geo.service import corridor_districts, corridor_point_offset_m

    data = ListingCreate.model_construct(
        kind=ListingKind.REQUEST,
        origin_stop_id=None,
        destination_stop_id=None,
        origin_point=origin,
        destination_point=destination,
    )
    corridor, route, origin_place, destination_place = _resolve_point_direction(session, data)
    districts = [
        item.district.name_uz
        for item in corridor_districts(session, _corridor_info(session, corridor.id))
        if item.on_confirmed_route
    ]
    return {
        "corridor": corridor,
        "route": route,
        "origin": origin_place,
        "destination": destination_place,
        "max_point_offset_m": corridor_point_offset_m(session, corridor.id),
        "districts_on_route": districts,
    }


def create_listing(
    session: Session,
    *,
    owner_user_id: int,
    data: ListingCreate,
    now: datetime | None = None,
    created_by_operator_id: int | None = None,
    consent_reference: str | None = None,
    warnings: list[dict] | None = None,
    filter_hits: list[ContactFilterHit] | None = None,
) -> Listing:
    """L1: a draft; the server computes quantity and total (AC01: 2 x 20 000 000 = 40 000 000)."""
    now = _now(now)
    comment = filter_free_text(  # first, so a rejected create still records the hit (R2-b)
        session, actor_user_id=owner_user_id, field="comment", text=data.comment, warnings=warnings, filter_hits=filter_hits
    )
    kind, service = ListingKind(data.kind), ServiceType(data.service_type)
    identity_service.require_capability(
        identity_service.get_capabilities(session, owner_user_id, now=now), LISTING_CREATE_CAPABILITY[kind]
    )
    ensure_price_basis_allowed(kind, service, data.price_basis)
    # Q88: two shapes. The stop-only path is untouched - legacy listings keep resolving exactly as before -
    # and a direction with any map point goes through the projection instead.
    origin = destination = None
    origin_place = destination_place = None
    if data.origin_point is None and data.destination_point is None:
        origin, destination = _stop_refs_by_public_ids(
            session, [data.origin_stop_id, data.destination_stop_id], "origin_stop_id/destination_stop_id"
        )
        corridor = _open_corridor(session, origin, destination)
    else:
        corridor, _route, origin_place, destination_place = _resolve_point_direction(session, data)
        origin, destination = origin_place.stop, destination_place.stop

    trip: Trip | None = None
    if kind is ListingKind.TRIP_OFFER:
        trip = _trip_for_offer(session, data.trip_id or "", owner_user_id)
        if origin is None or destination is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "trip_id", "reason": "offer_needs_stops"})
        if trips_service.occurrence_seqs_for_stops(session, trip.id, origin.id, destination.id) is None:
            raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "stops_not_on_trip"})
        if service is ServiceType.PARCEL and not (trip.cargo_capacity_weight_g or trip.cargo_capacity_volume_ml):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "trip has no cargo capacity", details={"field": "trip_id"})

    quantity = listing_quantity(
        kind,
        service,
        seat_count=data.passenger.seat_count if data.passenger else None,
        trip_seat_capacity=trip.seat_capacity if trip else None,
    )
    total = compute_total_minor(data.price_basis, data.unit_price_minor, quantity)
    window_start = ensure_aware_utc(data.departure_window_start)
    window_end = ensure_aware_utc(data.departure_window_end)
    if window_end <= now:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "departure_window_end"})
    expires_at = ensure_aware_utc(data.expires_at) if data.expires_at else window_end
    if expires_at > window_end or expires_at <= now:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "expires_at"})

    listing = Listing(
        public_id=new_public_uuid(),
        owner_user_id=owner_user_id,
        kind=kind.value,
        service_type=service.value,
        status=ListingStatus.DRAFT.value,
        trip_id=trip.id if trip else None,
        corridor_id=corridor.id,
        origin_stop_id=origin.id if origin else None,
        destination_stop_id=destination.id if destination else None,
        departure_window_start=window_start,
        departure_window_end=window_end,
        timezone=LISTING_TIMEZONE,
        price_basis=PriceBasis(data.price_basis).value,
        unit_price_minor=data.unit_price_minor,
        quantity=quantity,
        total_minor=total,
        currency=data.currency.value,
        payment_method=data.payment_method.value,
        expires_at=expires_at,
        comment=comment,
        created_by_operator_id=created_by_operator_id,
        consent_reference=consent_reference,
        version=1,
    )
    _apply_point_ends(listing, origin_place, destination_place)
    session.add(listing)
    _flush_or_translate(session, {OPEN_TRIP_OFFER_INDEX: _duplicate_listing})
    _write_details(
        session,
        listing,
        _filtered_passenger(session, owner_user_id, data.passenger, warnings, filter_hits),
        data.parcel,
        uploader_user_id=owner_user_id,
    )
    session.flush()
    return listing


def _owner_listing(session: Session, listing_public_id: str, actor_user_id: int) -> Listing:
    listing = get_listing_by_public_id(session, listing_public_id)
    if listing.owner_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    return listing


def _assert_pilot_parcel_limits(session: Session, listing: Listing) -> None:
    """§5.2: the pilot's declared size limits. Above them the answer is an explicit refusal, never a silent cut.

    The prohibited-items list is a product decision and is not enforced here; what this guard does is keep a
    50 kg pilot from accepting a "900 kg" post that no driver can load.
    """
    if listing.service_type != ServiceType.PARCEL.value:
        return
    details = session.execute(
        select(ParcelListingDetails).where(ParcelListingDetails.listing_id == listing.id)
    ).scalar_one_or_none()
    if details is None:
        return
    over: dict[str, int] = {}
    if (details.weight_g or 0) > PARCEL_PILOT_MAX_WEIGHT_G:
        over["weight_g"] = PARCEL_PILOT_MAX_WEIGHT_G
    sides = [int(value) for value in (details.length_cm, details.width_cm, details.height_cm) if value]
    if sides and max(sides) > PARCEL_PILOT_MAX_DIMENSION_CM:
        over["dimension_cm"] = PARCEL_PILOT_MAX_DIMENSION_CM
    if len(sides) == 3 and (sides[0] * sides[1] * sides[2]) > PARCEL_PILOT_MAX_VOLUME_ML:
        # 1 cm3 = 1 ml (AGENTS §6 units); only a fully described box can be measured this way.
        over["volume_ml"] = PARCEL_PILOT_MAX_VOLUME_ML
    if over:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "pilot_parcel_limit", "limits": over})


def _assert_publish_rate(session: Session, listing: Listing, now: datetime) -> None:
    """§5.4: a quantitative limit on new publishes per author, so re-posting cannot be used to look fresh."""
    window_start = now - timedelta(seconds=LISTING_PUBLISH_RATE_WINDOW_S)
    recent = session.execute(
        select(func.count(Listing.id)).where(
            Listing.owner_user_id == listing.owner_user_id,
            Listing.id != listing.id,
            Listing.published_at.is_not(None),
            Listing.published_at >= window_start,
        )
    ).scalar_one()
    if recent >= LISTING_PUBLISH_RATE_LIMIT:
        raise DomainError(
            ErrorCode.RATE_LIMITED,
            details={"limit": LISTING_PUBLISH_RATE_LIMIT, "window_s": LISTING_PUBLISH_RATE_WINDOW_S},
        )


def _place_listing_ends_on_corridor(session: Session, listing: Listing):  # noqa: ANN202
    """Do the listing's own ends still sit on a confirmed route of its corridor? (Q88)"""
    from app.modules.geo.service import corridor_point_offset_m, get_route_version, list_corridor_routes

    row = _listing_point_ends(session, listing)
    if row is None:
        return None
    radius = corridor_point_offset_m(session, listing.corridor_id)
    for route_ref in list_corridor_routes(session, _corridor_info(session, listing.corridor_id), limit=5):
        route = get_route_version(session, route_ref.id)
        ends = (
            (listing.origin_stop_id, row.o_lat, row.o_lng),
            (listing.destination_stop_id, row.d_lat, row.d_lng),
        )
        placements = []
        for stop_id, lat, lng in ends:
            if lat is None:
                stop_ref = get_ports().geo.stops_by_ids(session, [stop_id]).get(stop_id)
                placements.append(None if stop_ref is None else _place_on_route(session, route, (stop_ref, None), max_offset_m=radius))
            else:
                placements.append(
                    _place_on_route(
                        session, route, (None, PointEndInput(lat=lat, lng=lng, district_id="dst_ignored", address=None)),
                        max_offset_m=radius,
                    )
                )
        if any(place is None for place in placements):
            continue
        if placements[0].fraction < placements[1].fraction:
            return route, placements[0], placements[1]
    return None


def _assert_publishable(session: Session, listing: Listing, now: datetime) -> None:
    """STATE_MACHINES §1 publish/resume guards, in contract order (also re-run on material edits)."""
    kind = ListingKind(listing.kind)
    identity_service.require_capability(
        identity_service.get_capabilities(session, listing.owner_user_id, now=now), LISTING_CREATE_CAPABILITY[kind]
    )
    _require_service_flags(session, listing, include_driver_listing=True)
    geo = get_ports().geo
    if listing.origin_point is not None or listing.destination_point is not None:
        # Q88: a point end has no stop to re-check, so publish re-asks the question that made the listing
        # possible in the first place - does a confirmed route of an open corridor still serve both places?
        # A superseded route or a closed corridor must stop the listing here, not at accept time.
        corridor = geo.corridors_by_ids(session, [listing.corridor_id]).get(listing.corridor_id)
        if corridor is None or not corridor.is_open:
            raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"reason": "corridor_not_open"})
        if _place_listing_ends_on_corridor(session, listing) is None:
            raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "no_confirmed_route_serves_both_points"})
    else:
        stops = geo.stops_by_ids(session, [listing.origin_stop_id, listing.destination_stop_id])
        origin, destination = stops.get(listing.origin_stop_id), stops.get(listing.destination_stop_id)
        if origin is None or destination is None:
            raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"reason": "stop_missing"})
        _open_corridor(session, origin, destination)
    missing = _missing_fields(session, listing)
    if missing:
        raise DomainError(ErrorCode.LISTING_INCOMPLETE, details={"missing": missing})
    if ensure_aware_utc(listing.departure_window_end) <= now or ensure_aware_utc(listing.expires_at) <= now:
        raise DomainError(ErrorCode.LISTING_EXPIRED)
    if kind is ListingKind.TRIP_OFFER:
        trip = trips_service.get_trip(session, listing.trip_id)
        if trip.driver_user_id != listing.owner_user_id or trip.status != TripStatus.PLANNED.value:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "trip", "from": trip.status})
        if ensure_aware_utc(trip.booking_cutoff_at) <= now:
            raise DomainError(ErrorCode.LISTING_EXPIRED, details={"reason": "booking_cutoff_passed"})
        loads = trips_service.get_segment_loads(session, trip.id)
        if listing.service_type == ServiceType.PASSENGER.value:
            has_resource = any(load.seat_capacity - load.seats_used > 0 for load in loads)
        else:
            has_resource = any(
                load.cargo_capacity_weight_g - load.cargo_used_weight_g > 0
                or load.cargo_capacity_volume_ml - load.cargo_used_volume_ml > 0
                for load in loads
            )
        if not has_resource:
            raise DomainError(ErrorCode.CAPACITY_UNAVAILABLE, details={"reason": "trip_has_no_remaining_capacity"})
    duplicate = session.execute(
        select(Listing.public_id)
        .where(
            Listing.id != listing.id,
            Listing.owner_user_id == listing.owner_user_id,
            Listing.kind == listing.kind,
            Listing.service_type == listing.service_type,
            Listing.origin_stop_id == listing.origin_stop_id,
            Listing.destination_stop_id == listing.destination_stop_id,
            Listing.status.in_(DUPLICATE_CHECK_STATUSES),
            Listing.departure_window_start < listing.departure_window_end,
            Listing.departure_window_end > listing.departure_window_start,
        )
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise DomainError(
            ErrorCode.DUPLICATE_LISTING,
            details={"existing_listing_id": format_public_id(PublicIdPrefix.LISTING, duplicate)},
        )


def record_listing_view(session: Session, listing: Listing, *, viewer_user_id: int | None) -> bool:
    """Q98: remember that this person has seen this listing, and count them once.

    Returns whether this call was the first time - the caller commits either way, but only a true here has
    changed anything.

    The count is of **people**, so the row is the count: `(listing_id, viewer_user_id)` is the primary key and
    the counter is bumped only on the insert that actually created one. Everything that could turn the number
    into noise is refused here rather than in the UI, because the owner reads it as a decision ("nobody is
    looking - the window is wrong" vs "people look and pass - the price is wrong"):

    * the owner's own opens, which would make every check of one's own listing read as interest;
    * staff, who are working a queue, not shopping (Q3 keeps the two account kinds apart, so this is exact);
    * anonymous readers, including the public share page - with no identity there is nothing to deduplicate
      by, and a number a reload can raise is an invented signal (§9).

    Deliberately does not touch `version`, `terms_version` or `updated_at`: looking at a listing is not an
    edit. Bumping the aggregate version would expire every open proposal on it (Q54) - a listing would lose
    its offers because somebody read it.
    """
    if viewer_user_id is None or viewer_user_id == listing.owner_user_id:
        return False
    first = session.execute(
        pg_insert(ListingView)
        .values(listing_id=listing.id, viewer_user_id=viewer_user_id)
        .on_conflict_do_nothing(index_elements=["listing_id", "viewer_user_id"])
        .returning(ListingView.listing_id)
    ).scalar_one_or_none()
    if first is None:
        return False
    # One statement, read-modify-write inside the database: two people opening the listing at the same instant
    # both increment, because each waits for the other's row lock rather than overwriting a value read earlier.
    session.execute(
        update(Listing).where(Listing.id == listing.id).values(view_count=Listing.view_count + 1)
    )
    return True


def _emit_listing_published(session: Session, listing: Listing, now: datetime) -> None:
    geo = get_ports().geo
    stops = geo.stops_by_ids(session, [listing.origin_stop_id, listing.destination_stop_id])
    corridor = geo.corridors_by_ids(session, [listing.corridor_id]).get(listing.corridor_id)
    _emit(
        session,
        EventType.LISTING_PUBLISHED,
        aggregate_type="listing",
        aggregate_public_id=listing_public_id(listing),
        aggregate_version=listing.version,
        aggregate_id=listing.id,
        payload={
            "kind": listing.kind,
            "service_type": listing.service_type,
            "corridor_id": corridor.public_id if corridor else None,
            "origin_stop_id": stops[listing.origin_stop_id].public_id if listing.origin_stop_id in stops else None,
            "destination_stop_id": (
                stops[listing.destination_stop_id].public_id if listing.destination_stop_id in stops else None
            ),
            "departure_window_start": to_iso_utc(listing.departure_window_start),
            "departure_window_end": to_iso_utc(listing.departure_window_end),
            "listing_version": listing.version,
        },
        now=now,
    )


def _publish_like(
    session: Session, *, listing_public_id: str, actor_user_id: int, expected_version: int, command: str, now: datetime | None
) -> Listing:
    now = _now(now)
    listing = _owner_listing(session, listing_public_id, actor_user_id)
    # users first (AC41): FOR NO KEY UPDATE serialises with an eligibility block and with this
    # owner's other publishes, without blocking FK inserts that reference the user.
    identity_service.lock_user_eligibility(session, [listing.owner_user_id])
    listing = lock_listing(session, listing.id)
    _check_version(listing.version, expected_version)
    LISTING.assert_transition(listing.status, ListingStatus.PUBLISHED.value, command)
    _assert_publishable(session, listing, now)
    if listing.service_type == ServiceType.PARCEL.value:
        # §5.2: no approved prohibited-items policy -> no NEW parcel listing in production (fail-closed).
        assert_parcel_policy_ready(session)
    _assert_pilot_parcel_limits(session, listing)
    if command == "publish" and listing.published_at is None:
        # Only a genuinely new publish counts against the §5.4 limit; resuming a paused post is not a new post.
        _assert_publish_rate(session, listing, now)
    listing.status = ListingStatus.PUBLISHED.value
    if listing.published_at is None:
        listing.published_at = now
    listing.version += 1
    listing.updated_at = now
    _flush_or_translate(session, {OPEN_TRIP_OFFER_INDEX: _duplicate_listing})
    _emit_listing_published(session, listing, now)
    return listing


def publish_listing(
    session: Session, *, listing_public_id: str, actor_user_id: int, expected_version: int, now: datetime | None = None
) -> Listing:
    return _publish_like(
        session,
        listing_public_id=listing_public_id,
        actor_user_id=actor_user_id,
        expected_version=expected_version,
        command="publish",
        now=now,
    )


def resume_listing(
    session: Session, *, listing_public_id: str, actor_user_id: int, expected_version: int, now: datetime | None = None
) -> Listing:
    return _publish_like(
        session,
        listing_public_id=listing_public_id,
        actor_user_id=actor_user_id,
        expected_version=expected_version,
        command="resume",
        now=now,
    )


def pause_listing(
    session: Session, *, listing_public_id: str, actor_user_id: int, expected_version: int, now: datetime | None = None
) -> Listing:
    now = _now(now)
    listing = lock_listing(session, _owner_listing(session, listing_public_id, actor_user_id).id)
    _check_version(listing.version, expected_version)
    LISTING.assert_transition(listing.status, ListingStatus.PAUSED.value, "pause")
    listing.status = ListingStatus.PAUSED.value
    listing.version += 1
    listing.updated_at = now
    session.flush()
    return listing


def cancel_listing(
    session: Session,
    *,
    listing_public_id: str,
    actor_user_id: int,
    expected_version: int,
    reason_code: str,
    comment: str | None = None,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
    filter_hits: list[ContactFilterHit] | None = None,
) -> Listing:
    """L7: owner or operator. Open negotiations expire; bookings are never cancelled here (A4).

    Operators (``ops.booking_command``) cannot cancel drafts and every operator cancel is audited
    (decision 23).
    """
    now = _now(now)
    listing = get_listing_by_public_id(session, listing_public_id)
    by_operator = listing.owner_user_id != actor_user_id
    if by_operator:
        caps = identity_service.get_capabilities(session, actor_user_id, now=now)
        if not caps.has(Capability.OPS_BOOKING_COMMAND):
            raise DomainError(ErrorCode.NOT_FOUND)
    listing = lock_listing(session, listing.id)
    _check_version(listing.version, expected_version)
    if by_operator and listing.status == ListingStatus.DRAFT.value:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "operator_cannot_cancel_draft", "from": listing.status}
        )
    LISTING.assert_transition(listing.status, ListingStatus.CANCELLED.value, "cancel")
    previous_status = listing.status
    comment = filter_free_text(
        session, actor_user_id=actor_user_id, field="comment", text=comment, warnings=warnings, filter_hits=filter_hits
    )
    _close_open_threads(session, listing, reason="listing_closed", now=now)
    listing.status = ListingStatus.CANCELLED.value
    listing.cancelled_at = now
    listing.cancelled_by_user_id = actor_user_id
    listing.cancelled_reason = reason_code
    listing.cancel_comment = comment
    listing.version += 1
    listing.updated_at = now
    if by_operator:
        session.add(
            AuditLog(
                actor_id=actor_user_id,
                entity_type="listing",
                entity_id=None,  # audit_logs.entity_id is INTEGER; BIGINT ids go into details
                action="listing_cancel_by_operator",
                details={
                    "listing_id": format_public_id(PublicIdPrefix.LISTING, listing.public_id),
                    "from_status": previous_status,
                    "reason_code": reason_code,
                    "comment": comment,
                    "version": listing.version,
                },
            )
        )
    session.flush()
    _emit(
        session,
        EventType.LISTING_CANCELLED,
        aggregate_type="listing",
        aggregate_public_id=format_public_id(PublicIdPrefix.LISTING, listing.public_id),
        aggregate_version=listing.version,
        aggregate_id=listing.id,
        payload={"kind": listing.kind, "service_type": listing.service_type, "reason_code": reason_code},
        now=now,
    )
    return listing


def patch_listing(
    session: Session,
    *,
    listing_public_id: str,
    actor_user_id: int,
    data: ListingPatch,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
    filter_hits: list[ContactFilterHit] | None = None,
) -> Listing:
    """L3: versioned edit.

    Decision 20: only route, departure window, quantity/seat_count or price-basis changes are
    material. On a published/paused listing a material edit re-runs the publish guards (BR #8)
    and expires open negotiations; unit price, comment, expiry, amenities or assistance edits don't.
    A published/paused listing may only be edited while the owner keeps the new-business capability.
    """
    now = _now(now)
    listing = _owner_listing(session, listing_public_id, actor_user_id)
    identity_service.lock_user_eligibility(session, [listing.owner_user_id])
    listing = lock_listing(session, listing.id)
    _check_version(listing.version, data.expected_version)
    if listing.status not in EDITABLE_STATUSES:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "listing", "from": listing.status, "command": "patch"}
        )
    kind, service = ListingKind(listing.kind), ServiceType(listing.service_type)
    live = listing.status in LIVE_STATUSES
    if live:
        identity_service.require_capability(
            identity_service.get_capabilities(session, listing.owner_user_id, now=now), LISTING_CREATE_CAPABILITY[kind]
        )
    fields_set = data.model_fields_set
    material = False

    origin_id, destination_id = listing.origin_stop_id, listing.destination_stop_id
    if data.origin_stop_id is not None or data.destination_stop_id is not None:
        if data.origin_stop_id is not None:
            origin_id = _stop_refs_by_public_ids(session, [data.origin_stop_id], "origin_stop_id")[0].id
        if data.destination_stop_id is not None:
            destination_id = _stop_refs_by_public_ids(session, [data.destination_stop_id], "destination_stop_id")[0].id
        if origin_id == destination_id:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "destination_stop_id"})
        refs = get_ports().geo.stops_by_ids(session, [origin_id, destination_id])
        corridor = _open_corridor(session, refs[origin_id], refs[destination_id])
        if kind is ListingKind.TRIP_OFFER and (
            trips_service.occurrence_seqs_for_stops(session, listing.trip_id, origin_id, destination_id) is None
        ):
            raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "stops_not_on_trip"})
        material |= (origin_id, destination_id) != (listing.origin_stop_id, listing.destination_stop_id)
        listing.origin_stop_id, listing.destination_stop_id, listing.corridor_id = origin_id, destination_id, corridor.id

    window_start = ensure_aware_utc(data.departure_window_start or listing.departure_window_start)
    window_end = ensure_aware_utc(data.departure_window_end or listing.departure_window_end)
    if window_end <= window_start or window_end <= now:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "departure_window_end"})
    material |= (window_start, window_end) != (
        ensure_aware_utc(listing.departure_window_start),
        ensure_aware_utc(listing.departure_window_end),
    )

    price_basis = PriceBasis(data.price_basis or listing.price_basis)
    ensure_price_basis_allowed(kind, service, price_basis)
    material |= price_basis.value != listing.price_basis
    unit_price = data.unit_price_minor if data.unit_price_minor is not None else listing.unit_price_minor

    if data.passenger is not None and not (service is ServiceType.PASSENGER and kind is ListingKind.REQUEST):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "passenger"})
    if data.parcel is not None and service is not ServiceType.PARCEL:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel"})
    demand_before = _demand_fingerprint(session, listing)
    _write_details(
        session,
        listing,
        _filtered_passenger(session, actor_user_id, data.passenger, warnings, filter_hits),
        data.parcel,
        uploader_user_id=actor_user_id,
    )
    session.flush()
    # BR N1: demand fields feed proposal capacity snapshots, so they are material (Q20 "quantity").
    material |= _demand_fingerprint(session, listing) != demand_before

    seat_count = None
    if service is ServiceType.PASSENGER and kind is ListingKind.REQUEST:
        details = get_passenger_details(session, listing.id)
        seat_count = details.seat_count if details else None
    trip_seats = trips_service.get_trip(session, listing.trip_id).seat_capacity if listing.trip_id else None
    quantity = listing_quantity(kind, service, seat_count=seat_count, trip_seat_capacity=trip_seats)
    material |= quantity != listing.quantity

    if "expires_at" in fields_set and data.expires_at is not None:
        expires_at = ensure_aware_utc(data.expires_at)
        if expires_at > window_end:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "expires_at"})
    else:
        expires_at = min(ensure_aware_utc(listing.expires_at), window_end)
    if expires_at <= now:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "expires_at"})

    listing.departure_window_start, listing.departure_window_end = window_start, window_end
    listing.price_basis = price_basis.value
    listing.unit_price_minor = unit_price
    listing.quantity = quantity
    listing.total_minor = compute_total_minor(price_basis, unit_price, quantity)
    listing.expires_at = expires_at
    if "comment" in fields_set:
        listing.comment = filter_free_text(
            session, actor_user_id=actor_user_id, field="comment", text=data.comment, warnings=warnings, filter_hits=filter_hits
        )
    listing.version += 1  # every edit: optimistic concurrency (expected_version)
    listing.updated_at = now
    if material:
        listing.terms_version += 1  # proposal-invalidating edits only; A4 compares it at accept (BR N1)
    if live and material:
        _assert_publishable(session, listing, now)
        _close_open_threads(session, listing, reason="listing_changed", now=now)
    session.flush()
    return listing


def _demand_fingerprint(session: Session, listing: Listing) -> tuple:
    """Detail fields that change a proposal's quantity or capacity snapshot (BR N1)."""
    passenger = get_passenger_details(session, listing.id)
    parcel = get_parcel_details(session, listing.id)
    return (
        (passenger.seat_count, passenger.baggage_total_volume_ml) if passenger else None,
        (parcel.weight_g, parcel.length_cm, parcel.width_cm, parcel.height_cm) if parcel else None,
    )


# --- proposals: reads and locks --------------------------------------------------------------------


def lock_thread(session: Session, thread_id: int) -> ProposalThread:
    thread = session.execute(
        select(ProposalThread)
        .where(ProposalThread.id == thread_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if thread is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return thread


def get_thread_by_public_id(session: Session, public_id: str) -> ProposalThread:
    value = parse_public_id(public_id, PublicIdPrefix.PROPOSAL_THREAD)
    thread = session.execute(select(ProposalThread).where(ProposalThread.public_id == value)).scalar_one_or_none()
    if thread is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return thread


def get_version_by_public_id(session: Session, public_id: str) -> ProposalVersion:
    value = parse_public_id(public_id, PublicIdPrefix.PROPOSAL_VERSION)
    version = session.execute(select(ProposalVersion).where(ProposalVersion.public_id == value)).scalar_one_or_none()
    if version is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return version


def actor_side(thread: ProposalThread, user_id: int) -> ActorSide | None:
    if user_id == thread.client_user_id:
        return ActorSide.CLIENT
    if user_id == thread.driver_user_id:
        return ActorSide.DRIVER
    return None


def get_thread_for_party(session: Session, thread_public_id_value: str, user_id: int) -> ProposalThread:
    thread = get_thread_by_public_id(session, thread_public_id_value)
    if actor_side(thread, user_id) is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return thread


def current_version(session: Session, thread: ProposalThread, *, for_update: bool = False) -> ProposalVersion | None:
    if thread.current_version_id is None:
        return None
    stmt = select(ProposalVersion).where(ProposalVersion.id == thread.current_version_id)
    if for_update:
        stmt = stmt.with_for_update(key_share=True).execution_options(populate_existing=True)
    return session.execute(stmt).scalar_one_or_none()


def thread_versions(session: Session, thread_id: int) -> list[ProposalVersion]:
    return list(
        session.execute(
            select(ProposalVersion).where(ProposalVersion.thread_id == thread_id).order_by(ProposalVersion.revision)
        ).scalars()
    )


def version_demand(version: ProposalVersion, *, service_type: ServiceType | str) -> ResourceDemand:
    """Capacity a version needs on segments ``[pickup_occurrence_seq, dropoff_occurrence_seq)``."""
    seats = version.quantity if ServiceType(service_type) is ServiceType.PASSENGER else 0
    return ResourceDemand(
        seats=seats,
        baggage_ml=version.baggage_ml,
        cargo_weight_g=version.cargo_weight_g,
        cargo_volume_ml=version.cargo_volume_ml,
    )


def list_listing_threads(
    session: Session, listing_id: int, *, state: str | None = None, before_id: int | None = None, limit: int = 20
) -> list[ProposalThread]:
    stmt = select(ProposalThread).where(ProposalThread.listing_id == listing_id)
    if state:
        stmt = stmt.where(ProposalThread.state == state)
    if before_id is not None:
        stmt = stmt.where(ProposalThread.id < before_id)
    return list(session.execute(stmt.order_by(ProposalThread.id.desc()).limit(limit)).scalars())


def list_user_threads(
    session: Session, user_id: int, *, state: str | None = None, before_id: int | None = None, limit: int = 20
) -> list[ProposalThread]:
    stmt = select(ProposalThread).where(
        or_(ProposalThread.client_user_id == user_id, ProposalThread.driver_user_id == user_id)
    )
    if state:
        stmt = stmt.where(ProposalThread.state == state)
    if before_id is not None:
        stmt = stmt.where(ProposalThread.id < before_id)
    return list(session.execute(stmt.order_by(ProposalThread.id.desc()).limit(limit)).scalars())


# --- proposals: validation ------------------------------------------------------------------------


def _listing_open_for_proposals(listing: Listing, now: datetime) -> None:
    if listing.status != ListingStatus.PUBLISHED.value:
        raise DomainError(ErrorCode.LISTING_NOT_OPEN, details={"status": listing.status})
    if ensure_aware_utc(listing.expires_at) <= now or ensure_aware_utc(listing.departure_window_end) <= now:
        raise DomainError(ErrorCode.LISTING_NOT_OPEN, details={"reason": "listing_expired"})


def _trip_open_for_proposals(trip: Trip, now: datetime) -> None:
    if trip.status != TripStatus.PLANNED.value or ensure_aware_utc(trip.booking_cutoff_at) <= now:
        raise DomainError(ErrorCode.BOOKING_CUTOFF_PASSED, details={"trip_status": trip.status})


def _require_trip_driver_eligible(session: Session, trip: Trip, now: datetime) -> None:
    """Decision 21: a client cannot open or counter a deal on a blocked/ineligible driver's trip (read-only)."""
    caps = identity_service.get_capabilities(session, trip.driver_user_id, now=now)
    if not caps.driver_eligible:
        raise DomainError(ErrorCode.DRIVER_NOT_ELIGIBLE, details={"reason": "trip_driver_not_eligible"})


@dataclass(frozen=True, slots=True)
class _Demand:
    baggage_ml: int = 0
    cargo_weight_g: int = 0
    cargo_volume_ml: int = 0
    length_cm: int | None = None
    width_cm: int | None = None
    height_cm: int | None = None

    def resources(self, *, seats: int) -> ResourceDemand:
        return ResourceDemand(
            seats=seats,
            baggage_ml=self.baggage_ml,
            cargo_weight_g=self.cargo_weight_g,
            cargo_volume_ml=self.cargo_volume_ml,
        )


def _demand_for(
    session: Session,
    listing: Listing,
    *,
    baggage: ProposalBaggage | None,
    parcel: ProposalParcel | None,
    current: ProposalVersion | None,
) -> _Demand:
    """Demand snapshot: request proposals take the request details; trip-offer proposals the body (BR #3)."""
    kind, service = ListingKind(listing.kind), ServiceType(listing.service_type)
    if kind is ListingKind.REQUEST:
        if baggage is not None or parcel is not None:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                "demand of a request proposal comes from the request details",
                details={"field": "baggage" if baggage is not None else "parcel"},
            )
        if service is ServiceType.PASSENGER:
            details = get_passenger_details(session, listing.id)
            return _Demand(baggage_ml=(details.baggage_total_volume_ml or 0) if details else 0)
        request_parcel = get_parcel_details(session, listing.id)
        if request_parcel is None:
            return _Demand()
        dims = (request_parcel.length_cm, request_parcel.width_cm, request_parcel.height_cm)
        return _Demand(
            cargo_weight_g=request_parcel.weight_g or 0,
            cargo_volume_ml=parcel_volume_ml(*dims) if all(dims) else 0,
            length_cm=dims[0],
            width_cm=dims[1],
            height_cm=dims[2],
        )

    if service is ServiceType.PASSENGER:
        if parcel is not None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel"})
        if baggage is not None:
            return _Demand(baggage_ml=baggage.total_volume_ml)
        return _Demand(baggage_ml=current.baggage_ml if current else 0)

    if baggage is not None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "baggage"})
    if parcel is None:
        if current is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "a parcel proposal must describe the parcel", details={"field": "parcel"})
        return _Demand(
            cargo_weight_g=current.cargo_weight_g,
            cargo_volume_ml=current.cargo_volume_ml,
            length_cm=current.parcel_length_cm,
            width_cm=current.parcel_width_cm,
            height_cm=current.parcel_height_cm,
        )
    volume = parcel.volume_ml or parcel_volume_ml(parcel.length_cm, parcel.width_cm, parcel.height_cm)
    limits = get_parcel_details(session, listing.id)
    if limits is not None:
        exceeded = []
        if limits.max_weight_g is not None and parcel.weight_g > limits.max_weight_g:
            exceeded.append("weight_g")
        if limits.max_volume_ml is not None and volume > limits.max_volume_ml:
            exceeded.append("volume_ml")
        if limits.max_dimension_cm is not None and max(parcel.length_cm, parcel.width_cm, parcel.height_cm) > limits.max_dimension_cm:
            exceeded.append("dimension_cm")
        if exceeded:
            raise DomainError(ErrorCode.CARGO_LIMIT_EXCEEDED, details={"reason": "offer_limits", "fields": exceeded})
        # N7: when the offer restricts parcel types, an untyped parcel is not accepted either.
        if limits.accepted_parcel_types and parcel.parcel_type not in limits.accepted_parcel_types:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel.parcel_type"})
    return _Demand(
        cargo_weight_g=parcel.weight_g,
        cargo_volume_ml=volume,
        length_cm=parcel.length_cm,
        width_cm=parcel.width_cm,
        height_cm=parcel.height_cm,
    )


def _proposal_receiver(
    listing: Listing, parcel: ProposalParcel | None, *, current: ProposalVersion | None, side: ActorSide
) -> tuple[str, str] | None:
    """Receiver contact of a trip-offer parcel proposal (card item 7, Q43/Q44).

    Only the client (sender) sets it; a counter without a new receiver - or any driver counter - carries the
    current version's receiver. Request proposals take the receiver from the request details.
    """
    if listing.kind != ListingKind.TRIP_OFFER.value or listing.service_type != ServiceType.PARCEL.value:
        if parcel is not None and parcel.receiver is not None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel.receiver"})
        return None
    if side is ActorSide.CLIENT and parcel is not None and parcel.receiver is not None:
        return parcel.receiver.name, parcel.receiver.phone
    if side is ActorSide.DRIVER and parcel is not None and parcel.receiver is not None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel.receiver", "reason": "client_sets_receiver"})
    if current is not None and current.receiver_name and current.receiver_phone:
        return current.receiver_name, current.receiver_phone
    if side is ActorSide.CLIENT:
        # W21-4 (wave 3.1): a trip-offer parcel needs a receiver before pickup, and only the client can give one.
        # Asked for here, where the client can still fix it, instead of blocking the driver at `pick_up`.
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel.receiver", "reason": "receiver_required"})
    return None


def parcel_receiver(version: ProposalVersion) -> tuple[str, str] | None:
    """``(name, phone)`` stored on a trip-offer parcel version, else ``None`` (A4 snapshot; never to the driver pre-pickup)."""
    if version.receiver_name and version.receiver_phone:
        return version.receiver_name, version.receiver_phone
    return None


def _listing_point_ends(session: Session, listing: Listing):  # noqa: ANN202
    """The listing's own map-point ends, as placements on a given trip's route (Q88).

    A proposal never re-decides where the client wants to be met: it inherits the listing's places. What it
    *does* decide is where those places fall on **this driver's** route, which is what turns them into segments
    and an ETA.
    """
    if listing.origin_point is None and listing.destination_point is None:
        return None
    row = session.execute(
        text(
            "SELECT ST_Y(origin_point::geometry) AS o_lat, ST_X(origin_point::geometry) AS o_lng,"
            "       ST_Y(destination_point::geometry) AS d_lat, ST_X(destination_point::geometry) AS d_lng,"
            "       origin_district_id, destination_district_id, origin_address, destination_address"
            "  FROM listings WHERE id = :id"
        ),
        {"id": listing.id},
    ).one()
    return row


def _place_listing_ends_on_trip(session: Session, listing: Listing, trip: Trip):  # noqa: ANN202
    """Project the listing's ends onto the trip's confirmed route; ``None`` when this trip cannot serve them."""
    from app.modules.geo.geometry import LatLng
    from app.modules.geo.service import corridor_point_offset_m, get_route_version, project_point_on_route

    row = _listing_point_ends(session, listing)
    if row is None:
        return None
    radius = corridor_point_offset_m(session, listing.corridor_id)
    route = get_route_version(session, trip.route_version_id)

    def place(lat, lng, stop_id, district_id, address):  # noqa: ANN001, ANN202
        if lat is None:
            for index, route_stop in enumerate(route.stops):
                if route_stop.stop_id == stop_id:
                    after = route.stops[min(index + 1, len(route.stops) - 1)]
                    return EndPlacement(
                        stop=None, point=None, district_id=None, fraction=float(route_stop.line_fraction),
                        offset_m=0, seq_before=route_stop.seq, seq_after=after.seq,
                        cumulative_distance_m=route_stop.cumulative_distance_m,
                        cumulative_duration_s=route_stop.cumulative_duration_s,
                    )
            return None
        projection = project_point_on_route(
            session, route_version_id=route.id, point=LatLng(lat=lat, lng=lng), max_offset_m=radius
        )
        if projection is None:
            return None
        return EndPlacement(
            stop=None, point=PointEndInput(lat=lat, lng=lng, district_id="dst_inherited", address=address),
            district_id=district_id, fraction=projection.fraction, offset_m=projection.offset_m,
            seq_before=projection.seq_before, seq_after=projection.seq_after,
            cumulative_distance_m=projection.cumulative_distance_m,
            cumulative_duration_s=projection.cumulative_duration_s,
            segment_ratio=projection.segment_ratio,
        )

    pickup = place(row.o_lat, row.o_lng, listing.origin_stop_id, row.origin_district_id, row.origin_address)
    dropoff = place(row.d_lat, row.d_lng, listing.destination_stop_id, row.destination_district_id, row.destination_address)
    if pickup is None or dropoff is None or pickup.fraction >= dropoff.fraction:
        return None
    return pickup, dropoff


def _occurrence_seqs_for_placements(session: Session, trip: Trip, pickup, dropoff):  # noqa: ANN001, ANN202
    """Segments a point-ended booking consumes: board in the pickup's segment, ride through the dropoff's.

    The projection lands between two route stops. The passenger is aboard from the stop *before* the pickup
    projection until the stop *after* the dropoff projection, so the allocation covers every segment in
    between - conservative by one partial segment at each end, which is the safe direction for capacity.
    """
    from app.modules.geo.service import get_route_version

    route = get_route_version(session, trip.route_version_id)
    by_seq = {stop.seq: stop.stop_id for stop in route.stops}
    start_stop, end_stop = by_seq.get(pickup.seq_before), by_seq.get(dropoff.seq_after)
    if start_stop is None or end_stop is None:
        return None
    return trips_service.occurrence_seqs_for_stops(session, trip.id, start_stop, end_stop)


def point_segment_for_trip(session: Session, listing: Listing, trip: Trip) -> tuple[int, int] | None:
    """Public (A4): the segments a point-ended listing's places occupy on this trip *right now* (Q88).

    Accept re-asks this instead of comparing stop ids, because a point end has no stop id to compare. If the
    driver re-planned the route since the proposal, the places either still project to the same segments or
    they do not - and "do not" is exactly the ``ROUTE_CHANGED`` the stop path raises.
    """
    places = _place_listing_ends_on_trip(session, listing, trip)
    if places is None:
        return None
    return _occurrence_seqs_for_placements(session, trip, places[0], places[1])


def _point_eta(session: Session, trip: Trip, place) -> datetime:  # noqa: ANN001 - EndPlacement
    """When this trip reaches a place that sits between two of its stops (Q88).

    The trip's own occurrence times are the anchor, not the route's estimate: a driver may plan a slower or
    faster run than the road's default, and the person is waiting for *that* driver. Between the two
    surrounding stops the arrival is interpolated by how far along the segment the place sits.
    """
    occurrences = {o.seq: o for o in trips_service.list_occurrences(session, trip.id)}
    route_stop_ids = _route_stop_ids(session, trip)
    before = occurrences.get(_occurrence_seq_of(occurrences, route_stop_ids.get(place.seq_before)))
    after = occurrences.get(_occurrence_seq_of(occurrences, route_stop_ids.get(place.seq_after)))
    if before is None:
        return ensure_aware_utc(trip.planned_start_at) + timedelta(seconds=place.cumulative_duration_s)
    start = ensure_aware_utc(before.planned_arrival_at)
    if after is None:
        return start
    span = (ensure_aware_utc(after.planned_arrival_at) - start).total_seconds()
    return start + timedelta(seconds=span * place.segment_ratio)


def _route_stop_ids(session: Session, trip: Trip) -> dict[int, int]:
    from app.modules.geo.service import get_route_version

    return {stop.seq: stop.stop_id for stop in get_route_version(session, trip.route_version_id).stops}


def _occurrence_seq_of(occurrences: dict, stop_id: int | None) -> int | None:
    if stop_id is None:
        return None
    for seq, occurrence in sorted(occurrences.items()):
        if occurrence.stop_id == stop_id:
            return seq
    return None


def _validate_point_segment(
    session: Session,
    *,
    listing: Listing,
    trip: Trip,
    pickup,  # noqa: ANN001 - EndPlacement
    dropoff,  # noqa: ANN001 - EndPlacement
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> tuple[int, int]:
    """The point-ended twin of :func:`_validate_segment` (Q88).

    Same three questions, answered from the projection instead of from the stop catalogue: are the windows
    sane, does the trip reach the pickup place inside the window both sides asked for, and which segments does
    the ride consume. The ETA is interpolated from the projection's cumulative duration, which is the honest
    anchor for a place that sits between two stops (spec §6.3 step 5).
    """
    if ensure_aware_utc(window_end) <= ensure_aware_utc(window_start):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "pickup_window_end"})
    if ensure_aware_utc(window_end) <= now:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "pickup_window_end", "reason": "in_the_past"})

    match_start = max(ensure_aware_utc(listing.departure_window_start), ensure_aware_utc(window_start))
    match_end = min(ensure_aware_utc(listing.departure_window_end), ensure_aware_utc(window_end))
    if match_end <= match_start:
        raise DomainError(ErrorCode.TIME_WINDOW_CONFLICT, details={"reason": "proposal_window_outside_request_window"})

    eta = _point_eta(session, trip, pickup)
    wait = timedelta(minutes=trip.pickup_wait_minutes or 0)
    if not (match_start - wait <= eta <= match_end + wait):
        raise DomainError(
            ErrorCode.TIME_WINDOW_CONFLICT,
            details={"reason": "trip_reaches_the_pickup_outside_the_window", "eta": eta.isoformat()},
        )

    seqs = _occurrence_seqs_for_placements(session, trip, pickup, dropoff)
    if seqs is None:
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "points_not_on_trip_route"})
    return seqs


def _validate_segment(
    session: Session,
    *,
    listing: Listing,
    trip: Trip,
    pickup: StopRef,
    dropoff: StopRef,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> tuple[int, int]:
    """Segment and time checks (BR #4) through A2's pure ``evaluate_route_match`` on the trip occurrences.

    * request: stops in the request's corridor; the pickup ETA window must meet the request's
      departure window;
    * trip offer: pickup/dropoff inside the offer's origin->destination occurrences; the pickup ETA
      window must meet the proposal's pickup window.
    Only existing trip stops are accepted (no detour insertion without a trip change).
    """
    if ensure_aware_utc(window_end) <= ensure_aware_utc(window_start):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "pickup_window_end"})
    if ensure_aware_utc(window_end) <= now:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "pickup_window_end", "reason": "in_the_past"})
    offer_span: tuple[int, int] | None = None
    if listing.kind == ListingKind.REQUEST.value:
        if pickup.corridor_id != listing.corridor_id or dropoff.corridor_id != listing.corridor_id:
            raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "stop_outside_request_corridor"})
        # N3: the pickup must meet both the request's window and the proposal's own pickup window.
        match_start = max(ensure_aware_utc(listing.departure_window_start), ensure_aware_utc(window_start))
        match_end = min(ensure_aware_utc(listing.departure_window_end), ensure_aware_utc(window_end))
        if match_end <= match_start:
            raise DomainError(ErrorCode.TIME_WINDOW_CONFLICT, details={"reason": "proposal_window_outside_request_window"})
    else:
        offer_span = trips_service.occurrence_seqs_for_stops(
            session, trip.id, listing.origin_stop_id, listing.destination_stop_id
        )
        if offer_span is None:
            raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "offer_stops_not_on_trip"})
        match_start, match_end = window_start, window_end

    from app.modules.geo.service import evaluate_route_match  # A2 public API; lazy to keep imports acyclic

    occurrences = trips_service.list_occurrences(session, trip.id)
    context = TripRouteContext(
        route_version_id=trip.route_version_id,
        trip_version=trip.version,
        occurrences=tuple(
            OccurrenceTiming(o.seq, o.stop_id, ensure_aware_utc(o.planned_arrival_at), o.dwell_minutes) for o in occurrences
        ),
        max_detour_minutes=trip.max_detour_minutes,
        max_detour_m=trip.max_detour_m,
        detour_used_s=trip.detour_used_s,
        detour_used_m=trip.detour_used_m,
        pickup_wait_minutes=trip.pickup_wait_minutes,
        route_version_public_id=_route_version_public_id(session, trip.route_version_id),
    )
    result = evaluate_route_match(
        context,
        MatchRequest(
            pickup_stop_id=pickup.id,
            dropoff_stop_id=dropoff.id,
            pickup_window_start=ensure_aware_utc(match_start),
            pickup_window_end=ensure_aware_utc(match_end),
        ),
        now=now,
    )
    if not result.matched:
        raise DomainError(
            result.error_code or ErrorCode.ROUTE_MISMATCH,
            details={"reasons": [str(getattr(reason, "value", reason)) for reason in result.reasons]},
        )
    if (
        result.pickup is None
        or result.dropoff is None
        or result.pickup.occurrence_seq is None
        or result.dropoff.occurrence_seq is None
    ):
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "detour_stops_need_trip_change"})
    seqs = (result.pickup.occurrence_seq, result.dropoff.occurrence_seq)
    if offer_span is not None and (seqs[0] < offer_span[0] or seqs[1] > offer_span[1]):
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "outside_offer_segment"})
    return seqs


def _check_price_band(
    session: Session,
    *,
    listing: Listing,
    pickup_stop_id: int | None,
    dropoff_stop_id: int | None,
    price_basis: PriceBasis,
    unit_price_minor: int,
    quantity: int,
    warnings: list[dict] | None = None,
) -> None:
    """Q90: the band *advises* the auction - it does not decide it.

    Q88: a map-point end carries no stop id. That is not a reason to skip the reference - A2 then answers with
    the corridor-wide band, so a point-ended negotiation gets the same advice and the same ranking input a
    stop-ended one does.

    ELCHI's price is the one the two sides agree on (`300k → 350k → 320k → 330k → accept` must end at 330 000).
    A band outside which an offer simply cannot be made would turn that into a fixed fare, so an ordinary band
    now attaches a warning the person can see and argue with, and only an admin-imposed ``enforced`` band still
    refuses. No band at all -> nothing to say.
    """
    from app.modules.geo.pricing import assert_price_within_band, evaluate_price_band
    from app.modules.geo.service import resolve_price_band

    band = resolve_price_band(
        session,
        corridor_id=listing.corridor_id,
        service_type=ServiceType(listing.service_type),
        origin_stop_id=pickup_stop_id,
        destination_stop_id=dropoff_stop_id,
    )
    # A2 owns the PRICE_OUT_OF_BAND details shape; no band -> no check.
    details = evaluate_price_band(
        band, price_basis=price_basis, unit_price_minor=unit_price_minor, quantity=quantity
    )
    if details is not None and warnings is not None:
        warnings.append({"code": WarningCode.PRICE_OUTSIDE_REFERENCE.value, "field": "unit_price_minor", "details": details})
    # Only an admin-imposed abuse/safety limit refuses; everything else is the two sides' business (Q90).
    assert_price_within_band(band, price_basis=price_basis, unit_price_minor=unit_price_minor, quantity=quantity)

def _route_version_public_id(session: Session, route_version_id: int) -> str | None:
    route = get_ports().geo.route_versions_by_ids(session, [route_version_id]).get(route_version_id)
    return route.public_id if route else None


def driver_offer_label(session: Session, listing_id: int, driver_user_id: int) -> int:
    """Stable "Haydovchi #N" ordinal of a driver on a listing (R1, Q40). Call under the listing lock."""
    existing = session.execute(
        select(ListingOfferLabel.label_seq).where(
            ListingOfferLabel.listing_id == listing_id, ListingOfferLabel.driver_user_id == driver_user_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    next_seq = 1 + session.execute(
        select(func.coalesce(func.max(ListingOfferLabel.label_seq), 0)).where(ListingOfferLabel.listing_id == listing_id)
    ).scalar_one()
    session.add(ListingOfferLabel(listing_id=listing_id, driver_user_id=driver_user_id, label_seq=next_seq))
    session.flush()
    return next_seq


def offer_labels(session: Session, listing_id: int) -> dict[int, int]:
    """``{driver_user_id: label_seq}`` for one listing."""
    return dict(
        session.execute(
            select(ListingOfferLabel.driver_user_id, ListingOfferLabel.label_seq).where(
                ListingOfferLabel.listing_id == listing_id
            )
        ).all()
    )


def _check_terms_and_capacity(
    session: Session,
    *,
    listing: Listing,
    trip: Trip,
    seqs: tuple[int, int],
    quantity: int,
    price_basis: PriceBasis,
    demand: _Demand,
) -> None:
    ensure_price_basis_allowed(ListingKind(listing.kind), ServiceType(listing.service_type), price_basis)
    check_proposal_quantity(
        listing_kind=ListingKind(listing.kind),
        service_type=ServiceType(listing.service_type),
        listing_quantity=listing.quantity,
        quantity=quantity,
    )
    seats = quantity if listing.service_type == ServiceType.PASSENGER.value else 0
    resources = demand.resources(seats=seats)
    if not resources.is_empty:
        shortfalls = trips_service.check_capacity(session, trip.id, seqs[0], seqs[1], resources)
        if shortfalls:
            raise shortfall_error(shortfalls)


def _active_stops(session: Session, public_ids: Sequence[str]) -> list[StopRef]:
    refs = _stop_refs_by_public_ids(session, public_ids, "stops")
    for ref in refs:
        if not ref.is_active:
            raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE, details={"reason": "stop_not_active"})
    return refs


def _quote(session: Session, listing: Listing, total: int, now: datetime) -> FeeQuote:
    quote = get_ports().fees.quote(
        session, corridor_id=listing.corridor_id, service_type=ServiceType(listing.service_type), total_minor=total, at=now
    )
    commission_minor(total, quote.fee_bps)  # validates the bps returned by the port
    return quote


def _insert_version(
    session: Session,
    *,
    thread: ProposalThread,
    revision: int,
    author_side: ActorSide,
    author_user_id: int,
    listing: Listing,
    trip: Trip,
    pickup_stop_id: int | None,
    dropoff_stop_id: int | None,
    seqs: tuple[int, int],
    pickup_place=None,  # noqa: ANN001 - EndPlacement, Q88
    dropoff_place=None,  # noqa: ANN001 - EndPlacement, Q88
    window_start: datetime,
    window_end: datetime,
    quantity: int,
    price_basis: PriceBasis,
    unit_price_minor: int,
    total: int,
    expires_at: datetime,
    quote: FeeQuote,
    demand: _Demand,
    message: str | None,
    now: datetime,
    receiver: tuple[str, str] | None = None,
) -> ProposalVersion:
    version = ProposalVersion(
        public_id=new_public_uuid(),
        thread_id=thread.id,
        revision=revision,
        author_side=author_side.value,
        author_user_id=author_user_id,
        status=ProposalStatus.ACTIVE.value,
        pickup_stop_id=pickup_stop_id,
        dropoff_stop_id=dropoff_stop_id,
        pickup_occurrence_seq=seqs[0],
        dropoff_occurrence_seq=seqs[1],
        pickup_window_start=ensure_aware_utc(window_start),
        pickup_window_end=ensure_aware_utc(window_end),
        quantity=quantity,
        price_basis=price_basis.value,
        unit_price_minor=unit_price_minor,
        total_minor=total,
        currency="UZS",
        expires_at=expires_at,
        listing_version=listing.version,
        listing_terms_version=listing.terms_version,
        trip_version=trip.version,
        route_version_id=trip.route_version_id,
        fee_policy_id=quote.policy_id,
        fee_bps=quote.fee_bps,
        commission_minor=commission_minor(total, quote.fee_bps),
        message=message,
        created_at=now,
        baggage_ml=demand.baggage_ml,
        cargo_weight_g=demand.cargo_weight_g,
        cargo_volume_ml=demand.cargo_volume_ml,
        parcel_length_cm=demand.length_cm,
        parcel_width_cm=demand.width_cm,
        parcel_height_cm=demand.height_cm,
        receiver_name=receiver[0] if receiver else None,
        receiver_phone=receiver[1] if receiver else None,
    )
    _apply_point_ends(version, pickup_place, dropoff_place)  # Q88: the places travel with the terms
    session.add(version)
    _flush_or_translate(
        session,
        {ACTIVE_VERSION_INDEX: lambda: DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "concurrent_version"})},
    )
    return version


def _emit_proposal(
    session: Session, event_type: EventType, listing: Listing, thread: ProposalThread, version: ProposalVersion, now: datetime, **extra: str | None
) -> None:
    payload: dict = {"listing_id": listing_public_id(listing), "thread_id": thread_public_id(thread), "revision": version.revision}
    payload.update(extra)
    _emit(
        session,
        event_type,
        aggregate_type="proposal_thread",
        aggregate_public_id=thread_public_id(thread),
        aggregate_version=thread.version,
        aggregate_id=thread.id,
        payload=payload,
        now=now,
    )


# --- proposals: commands ---------------------------------------------------------------------------


def blocked_pair(session: Session, user_a: int, user_b: int) -> bool:
    """§8.1: the two users have blocked each other (either direction). Read-only; missing module -> no block."""
    try:
        from app.modules.trust_support import service as trust_service
    except Exception:  # noqa: BLE001 - marketplace works without the trust module installed
        return False
    return trust_service.blocked_between(session, user_a, user_b)


def submit_proposal(
    session: Session,
    *,
    listing_public_id: str,
    actor_user_id: int,
    data: ProposalCreate,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
    filter_hits: list[ContactFilterHit] | None = None,
) -> ProposalThread:
    """P1: open a negotiation with an immutable revision 1, a demand snapshot and a frozen fee quote (AC43)."""
    now = _now(now)
    # Filter first: the hit must be recorded even when a later guard rejects the command (R2-b, Q45).
    message = filter_free_text(
        session, actor_user_id=actor_user_id, field="message", text=data.message, warnings=warnings, filter_hits=filter_hits
    )
    listing = get_listing_by_public_id(session, listing_public_id)
    if listing.status == ListingStatus.DRAFT.value and listing.owner_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    if listing.owner_user_id == actor_user_id:
        raise DomainError(ErrorCode.SELF_DEALING_FORBIDDEN)
    if blocked_pair(session, listing.owner_user_id, actor_user_id):
        # §8.1: a blocked pair never meets again. 404, not 403: a block is not announced to the other side.
        raise DomainError(ErrorCode.NOT_FOUND)
    identity_service.lock_user_eligibility(session, [actor_user_id], mode="share")
    listing = lock_listing(session, listing.id)
    _listing_open_for_proposals(listing, now)
    kind = ListingKind(listing.kind)
    side = proposer_side(kind)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), PROPOSAL_CAPABILITY[side]
    )
    _require_service_flags(session, listing, include_driver_listing=False)

    if kind is ListingKind.REQUEST:
        if not data.trip_id:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "a driver proposal needs trip_id", details={"field": "trip_id"})
        trip = trips_service.get_trip_by_public_id(session, data.trip_id)
        if trip.driver_user_id != actor_user_id:
            raise DomainError(ErrorCode.NOT_FOUND, details={"field": "trip_id"})
    else:
        trip = trips_service.get_trip(session, listing.trip_id)
        if data.trip_id and trips_service.resolve_trip_id(session, data.trip_id) != trip.id:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "trip_id"})
        _require_trip_driver_eligible(session, trip, now)
    _trip_open_for_proposals(trip, now)

    # Q88: a point-ended listing hands its own places down to the proposal; only a stop-ended one asks the
    # driver which stops they mean.
    places = _place_listing_ends_on_trip(session, listing, trip)
    if places is not None:
        if data.pickup_stop_id is not None or data.dropoff_stop_id is not None:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                details={"field": "pickup_stop_id", "reason": "listing_ends_are_points"},
            )
        pickup_place, dropoff_place = places
        pickup = dropoff = None
        seqs = _validate_point_segment(
            session,
            listing=listing,
            trip=trip,
            pickup=pickup_place,
            dropoff=dropoff_place,
            window_start=data.pickup_window_start,
            window_end=data.pickup_window_end,
            now=now,
        )
    else:
        if data.pickup_stop_id is None or data.dropoff_stop_id is None:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, details={"field": "pickup_stop_id", "reason": "listing_ends_are_stops"}
            )
        pickup_place = dropoff_place = None
        pickup, dropoff = _active_stops(session, [data.pickup_stop_id, data.dropoff_stop_id])
        seqs = _validate_segment(
            session,
            listing=listing,
            trip=trip,
            pickup=pickup,
            dropoff=dropoff,
            window_start=data.pickup_window_start,
            window_end=data.pickup_window_end,
            now=now,
        )
    price_basis = PriceBasis(data.price_basis)
    demand = _demand_for(session, listing, baggage=data.baggage, parcel=data.parcel, current=None)
    receiver = _proposal_receiver(listing, data.parcel, current=None, side=side)
    _check_terms_and_capacity(
        session, listing=listing, trip=trip, seqs=seqs, quantity=data.quantity, price_basis=price_basis, demand=demand
    )
    # Q42 + Q88: a point-ended direction has no stop pair, so no *segment* band applies - but the corridor-wide
    # band describes the whole direction and is the right reference for it. Skipping the lookup entirely (what
    # wave 14 did) left every point listing without a price reference: no advisory warning, and a neutral price
    # score in the ranking forever. A2 picks the right scope; this just has to ask.
    _check_price_band(
        session,
        listing=listing,
        pickup_stop_id=pickup.id if pickup is not None else None,
        dropoff_stop_id=dropoff.id if dropoff is not None else None,
        price_basis=price_basis,
        unit_price_minor=data.unit_price_minor,
        quantity=data.quantity,
        warnings=warnings,
    )
    client_id, driver_id = (
        (listing.owner_user_id, actor_user_id) if side is ActorSide.DRIVER else (actor_user_id, trip.driver_user_id)
    )
    if client_id == driver_id:
        raise DomainError(ErrorCode.SELF_DEALING_FORBIDDEN)
    existing = session.execute(
        select(ProposalThread.public_id).where(
            ProposalThread.listing_id == listing.id,
            ProposalThread.client_user_id == client_id,
            ProposalThread.driver_user_id == driver_id,
            ProposalThread.trip_id == trip.id,
            ProposalThread.state == THREAD_OPEN,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            details={"reason": "open_thread_exists", "thread_id": format_public_id(PublicIdPrefix.PROPOSAL_THREAD, existing)},
        )
    total = compute_total_minor(price_basis, data.unit_price_minor, data.quantity)
    expires_at = proposal_expires_at(
        now=now,
        departure_at=trip.planned_start_at,
        booking_cutoff_at=trip.booking_cutoff_at,
        listing_expires_at=listing.expires_at,
    )
    quote = _quote(session, listing, total, now)

    driver_offer_label(session, listing.id, driver_id)
    thread = ProposalThread(
        public_id=new_public_uuid(),
        listing_id=listing.id,
        client_user_id=client_id,
        driver_user_id=driver_id,
        trip_id=trip.id,
        state=THREAD_OPEN,
        client_price_revisions=0,
        driver_price_revisions=0,
        version=1,
    )
    session.add(thread)
    _flush_or_translate(
        session,
        {OPEN_THREAD_INDEX: lambda: DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "open_thread_exists"})},
    )
    version = _insert_version(
        session,
        thread=thread,
        revision=1,
        author_side=side,
        author_user_id=actor_user_id,
        listing=listing,
        trip=trip,
        pickup_stop_id=pickup.id if pickup else None,
        dropoff_stop_id=dropoff.id if dropoff else None,
        seqs=seqs,
        pickup_place=pickup_place,
        dropoff_place=dropoff_place,
        window_start=data.pickup_window_start,
        window_end=data.pickup_window_end,
        quantity=data.quantity,
        price_basis=price_basis,
        unit_price_minor=data.unit_price_minor,
        total=total,
        expires_at=expires_at,
        quote=quote,
        demand=demand,
        message=message,
        now=now,
        receiver=receiver,
    )
    thread.current_version_id = version.id
    session.flush()
    _emit_proposal(session, EventType.PROPOSAL_CREATED, listing, thread, version, now, author_side=side.value)
    return thread


def counter_proposal(
    session: Session,
    *,
    thread_public_id_value: str,
    actor_user_id: int,
    data: ProposalCounter,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
    filter_hits: list[ContactFilterHit] | None = None,
) -> ProposalThread:
    """P5: only the recipient of the current version counters; the old version is superseded (AC04)."""
    now = _now(now)
    message = filter_free_text(  # first, see submit_proposal (R2-b)
        session, actor_user_id=actor_user_id, field="message", text=data.message, warnings=warnings, filter_hits=filter_hits
    )
    thread = get_thread_for_party(session, thread_public_id_value, actor_user_id)
    identity_service.lock_user_eligibility(session, [actor_user_id], mode="share")
    listing = lock_listing(session, thread.listing_id)
    thread = lock_thread(session, thread.id)
    if thread.state != THREAD_OPEN:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "proposal_thread", "from": thread.state})
    current = current_version(session, thread, for_update=True)
    if current is None or current.revision != data.expected_revision or current.status != ProposalStatus.ACTIVE.value:
        raise DomainError(
            ErrorCode.PROPOSAL_CHANGED, details={"current_revision": current.revision if current else None}
        )
    side = actor_side(thread, actor_user_id)
    if side is ActorSide(current.author_side):
        raise DomainError(ErrorCode.NOT_PROPOSAL_RECIPIENT)
    if ensure_aware_utc(current.expires_at) <= now:
        raise DomainError(ErrorCode.PROPOSAL_EXPIRED)
    _listing_open_for_proposals(listing, now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), PROPOSAL_CAPABILITY[side]
    )
    _require_service_flags(session, listing, include_driver_listing=False)
    trip = trips_service.get_trip(session, thread.trip_id)
    if side is ActorSide.CLIENT:
        _require_trip_driver_eligible(session, trip, now)
    _trip_open_for_proposals(trip, now)

    window_start = data.pickup_window_start or current.pickup_window_start
    window_end = data.pickup_window_end or current.pickup_window_end
    quantity = data.quantity if data.quantity is not None else current.quantity
    unit_price = data.unit_price_minor if data.unit_price_minor is not None else current.unit_price_minor
    price_basis = PriceBasis(current.price_basis)

    # Q88: a counteroffer inherits the listing's places exactly as the first proposal did. Without this branch
    # the stop lookup below was asked for `None` and raised - which meant the *counteroffer*, the half of the
    # two-sided auction that makes it an auction at all, was impossible on every map-point listing.
    places = _place_listing_ends_on_trip(session, listing, trip)
    if places is not None:
        if data.pickup_stop_id is not None or data.dropoff_stop_id is not None:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                details={"field": "pickup_stop_id", "reason": "listing_ends_are_points"},
            )
        pickup_place, dropoff_place = places
        pickup = dropoff = None
        seqs = _validate_point_segment(
            session,
            listing=listing,
            trip=trip,
            pickup=pickup_place,
            dropoff=dropoff_place,
            window_start=window_start,
            window_end=window_end,
            now=now,
        )
    else:
        pickup_place = dropoff_place = None
        stops = get_ports().geo.stops_by_ids(session, [current.pickup_stop_id, current.dropoff_stop_id])
        pickup, dropoff = stops[current.pickup_stop_id], stops[current.dropoff_stop_id]
        if data.pickup_stop_id is not None:
            pickup = _active_stops(session, [data.pickup_stop_id])[0]
        if data.dropoff_stop_id is not None:
            dropoff = _active_stops(session, [data.dropoff_stop_id])[0]
        if pickup.id == dropoff.id:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "dropoff_stop_id"})
        seqs = _validate_segment(
            session,
            listing=listing,
            trip=trip,
            pickup=pickup,
            dropoff=dropoff,
            window_start=window_start,
            window_end=window_end,
            now=now,
        )
    demand = _demand_for(session, listing, baggage=data.baggage, parcel=data.parcel, current=current)
    receiver = _proposal_receiver(listing, data.parcel, current=current, side=side)
    _check_terms_and_capacity(
        session, listing=listing, trip=trip, seqs=seqs, quantity=quantity, price_basis=price_basis, demand=demand
    )
    # Q53/Q67: the band is re-read when the price OR the pickup/dropoff stop changes (the segment band may
    # differ). A point-ended thread cannot change its ends at all, so only a price change re-reads it there.
    pickup_stop_id = pickup.id if pickup is not None else None
    dropoff_stop_id = dropoff.id if dropoff is not None else None
    if (
        unit_price != current.unit_price_minor
        or pickup_stop_id != current.pickup_stop_id
        or dropoff_stop_id != current.dropoff_stop_id
    ):
        _check_price_band(
            session,
            listing=listing,
            pickup_stop_id=pickup_stop_id,
            dropoff_stop_id=dropoff_stop_id,
            price_basis=price_basis,
            unit_price_minor=unit_price,
            quantity=quantity,
            warnings=warnings,
        )
    revisions_field = f"{side.value}_price_revisions"
    revisions = next_price_revision_count(
        getattr(thread, revisions_field), price_changed=unit_price != current.unit_price_minor
    )
    total = compute_total_minor(price_basis, unit_price, quantity)
    expires_at = proposal_expires_at(
        now=now, departure_at=trip.planned_start_at, booking_cutoff_at=trip.booking_cutoff_at, listing_expires_at=listing.expires_at
    )
    quote = _quote(session, listing, total, now)  # a counter gets a fresh quote (AC43)

    PROPOSAL_VERSION.assert_transition(current.status, ProposalStatus.SUPERSEDED.value, "counter")
    current.status = ProposalStatus.SUPERSEDED.value
    current.status_reason = "countered"
    current.closed_at = now
    session.flush()
    version = _insert_version(
        session,
        thread=thread,
        revision=current.revision + 1,
        author_side=side,
        author_user_id=actor_user_id,
        listing=listing,
        trip=trip,
        pickup_stop_id=pickup_stop_id,
        dropoff_stop_id=dropoff_stop_id,
        seqs=seqs,
        pickup_place=pickup_place,
        dropoff_place=dropoff_place,
        window_start=window_start,
        window_end=window_end,
        quantity=quantity,
        price_basis=price_basis,
        unit_price_minor=unit_price,
        total=total,
        expires_at=expires_at,
        quote=quote,
        demand=demand,
        message=message,
        now=now,
        receiver=receiver,
    )
    thread.current_version_id = version.id
    setattr(thread, revisions_field, revisions)
    thread.version += 1
    thread.updated_at = now
    session.flush()
    _emit_proposal(session, EventType.PROPOSAL_SUPERSEDED, listing, thread, version, now, author_side=side.value)
    return thread


def _close_thread_by_party(
    session: Session,
    *,
    thread_public_id_value: str,
    actor_user_id: int,
    expected_revision: int,
    reason_code: str | None,
    command: str,
    now: datetime | None,
) -> ProposalThread:
    """Reject (recipient) or withdraw (author). No capability needed: closing is not new business (D16)."""
    now = _now(now)
    thread = get_thread_for_party(session, thread_public_id_value, actor_user_id)
    listing = lock_listing(session, thread.listing_id)
    thread = lock_thread(session, thread.id)
    current = current_version(session, thread, for_update=True)
    if thread.state != THREAD_OPEN or current is None:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "proposal_thread", "from": thread.state})
    if current.revision != expected_revision:
        raise DomainError(ErrorCode.PROPOSAL_CHANGED, details={"current_revision": current.revision})
    side = actor_side(thread, actor_user_id)
    author = ActorSide(current.author_side)
    if command == "reject" and side is author:
        raise DomainError(ErrorCode.NOT_PROPOSAL_RECIPIENT)
    if command == "withdraw" and side is not author:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "only_the_author_can_withdraw"})
    target = ProposalStatus.REJECTED if command == "reject" else ProposalStatus.WITHDRAWN
    PROPOSAL_VERSION.assert_transition(current.status, target.value, command)
    current.status = target.value
    current.status_reason = reason_code or target.value
    current.closed_at = now
    thread.state = THREAD_CLOSED
    thread.closed_reason = reason_code or target.value
    thread.version += 1
    thread.updated_at = now
    session.flush()
    event = EventType.PROPOSAL_REJECTED if command == "reject" else EventType.PROPOSAL_WITHDRAWN
    _emit_proposal(session, event, listing, thread, current, now, reason_code=reason_code or target.value)
    return thread


def reject_proposal(
    session: Session,
    *,
    thread_public_id_value: str,
    actor_user_id: int,
    expected_revision: int,
    reason_code: str | None = None,
    now: datetime | None = None,
) -> ProposalThread:
    return _close_thread_by_party(
        session,
        thread_public_id_value=thread_public_id_value,
        actor_user_id=actor_user_id,
        expected_revision=expected_revision,
        reason_code=reason_code,
        command="reject",
        now=now,
    )


def withdraw_proposal(
    session: Session,
    *,
    thread_public_id_value: str,
    actor_user_id: int,
    expected_revision: int,
    reason_code: str | None = None,
    now: datetime | None = None,
) -> ProposalThread:
    return _close_thread_by_party(
        session,
        thread_public_id_value=thread_public_id_value,
        actor_user_id=actor_user_id,
        expected_revision=expected_revision,
        reason_code=reason_code,
        command="withdraw",
        now=now,
    )


# --- system expiry and trip changes ------------------------------------------------------------------


def _expire_thread(
    session: Session, listing: Listing, thread: ProposalThread, version: ProposalVersion | None, *, reason: str, now: datetime
) -> None:
    if version is not None and version.status == ProposalStatus.ACTIVE.value:
        PROPOSAL_VERSION.assert_transition(version.status, ProposalStatus.EXPIRED.value, "system_expire")
        version.status = ProposalStatus.EXPIRED.value
        version.status_reason = reason
        version.closed_at = now
    thread.state = THREAD_CLOSED
    thread.closed_reason = reason
    thread.version += 1
    thread.updated_at = now
    session.flush()
    if version is not None:
        _emit_proposal(session, EventType.PROPOSAL_EXPIRED, listing, thread, version, now, reason_code=reason)


def _close_open_threads(session: Session, listing: Listing, *, reason: str, now: datetime) -> int:
    """Caller holds the listing lock; threads are locked next in id order (ADR-0017)."""
    threads = list(
        session.execute(
            select(ProposalThread)
            .where(ProposalThread.listing_id == listing.id, ProposalThread.state == THREAD_OPEN)
            .order_by(ProposalThread.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).scalars()
    )
    for thread in threads:
        _expire_thread(session, listing, thread, current_version(session, thread, for_update=True), reason=reason, now=now)
    return len(threads)


# --- booking orchestrator commands (Q59; replace A4's temporary bridges) ----------------------------------
# The caller (A4 accept/cancel orchestrator) holds the ADR-0017 locks: trip -> listing -> proposal_threads.
# None of these commit; every status write goes through the contract state machine and bumps ``version``.


def accept_version(
    session: Session, *, listing: Listing, thread: ProposalThread, version: ProposalVersion, now: datetime
) -> None:
    """``active -> accepted`` for the version and ``open -> accepted`` for the thread (STATE_MACHINES §2)."""
    now = ensure_aware_utc(now)
    if thread.id != version.thread_id or thread.listing_id != listing.id:
        raise DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "version_not_in_thread"})
    if thread.state != THREAD_OPEN:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "proposal_thread", "from": thread.state, "command": "accept"}
        )
    PROPOSAL_VERSION.assert_transition(version.status, ProposalStatus.ACCEPTED.value, "accept")
    version.status = ProposalStatus.ACCEPTED.value
    version.status_reason = "accepted"
    version.closed_at = now
    thread.state = THREAD_ACCEPTED
    thread.closed_reason = "accepted"
    thread.version += 1
    thread.updated_at = now
    session.flush()


def close_open_threads(session: Session, *, listing: Listing, reason: str, now: datetime) -> int:
    """Expire every other open negotiation of the listing (``demand_fulfilled`` / ``capacity_gone`` ...).

    Returns the number of threads closed. The caller holds the listing lock; threads are locked in id order.
    """
    return _close_open_threads(session, listing, reason=reason[:64], now=ensure_aware_utc(now))


def fulfil_listing(session: Session, *, listing: Listing, now: datetime) -> None:
    """``system_fulfil``: the request's demand is booked (STATE_MACHINES §1)."""
    now = ensure_aware_utc(now)
    LISTING.assert_transition(listing.status, ListingStatus.FULFILLED.value, "system_fulfil")
    listing.status = ListingStatus.FULFILLED.value
    listing.version += 1
    listing.updated_at = now
    session.flush()


def reopen_listing(session: Session, *, listing: Listing, now: datetime) -> None:
    """``system_reopen`` after a driver/operator cancel inside a valid window (Q19); emits ``listing.published``."""
    now = ensure_aware_utc(now)
    LISTING.assert_transition(listing.status, ListingStatus.PUBLISHED.value, "system_reopen")
    listing.status = ListingStatus.PUBLISHED.value
    if listing.published_at is None:
        listing.published_at = now
    listing.version += 1
    listing.updated_at = now
    session.flush()
    _emit_listing_published(session, listing, now)


def cancel_listing_for_booking(
    session: Session, *, listing: Listing, actor_user_id: int | None, reason_code: str, now: datetime
) -> None:
    """Close a listing because of a booking-side event (client cancelled its request's booking, trip cancelled).

    Open threads expire first (listing -> threads), then ``cancel`` and ``listing.cancelled``.
    """
    now = ensure_aware_utc(now)
    LISTING.assert_transition(listing.status, ListingStatus.CANCELLED.value, "cancel")
    reason = reason_code[:64]
    _close_open_threads(session, listing, reason="listing_closed", now=now)
    listing.status = ListingStatus.CANCELLED.value
    listing.cancelled_at = now
    listing.cancelled_by_user_id = actor_user_id
    listing.cancelled_reason = reason
    listing.version += 1
    listing.updated_at = now
    session.flush()
    _emit(
        session,
        EventType.LISTING_CANCELLED,
        aggregate_type="listing",
        aggregate_public_id=listing_public_id(listing),
        aggregate_version=listing.version,
        aggregate_id=listing.id,
        payload={"kind": listing.kind, "service_type": listing.service_type, "reason_code": reason},
        now=now,
    )


def expire_threads_for_trip(session: Session, trip_id: int, *, reason: str, now: datetime | None = None) -> int:
    """Expire open negotiations on a trip whose stops/schedule changed (BR #5). Caller holds the trip lock."""
    now = _now(now)
    listing_ids = session.execute(
        select(ProposalThread.listing_id)
        .where(ProposalThread.trip_id == trip_id, ProposalThread.state == THREAD_OPEN)
        .distinct()
    ).scalars().all()
    listings = {listing.id: listing for listing in lock_listings(session, list(listing_ids))}
    threads = list(
        session.execute(
            select(ProposalThread)
            .where(ProposalThread.trip_id == trip_id, ProposalThread.state == THREAD_OPEN)
            .order_by(ProposalThread.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).scalars()
    )
    for thread in threads:
        _expire_thread(
            session,
            listings.get(thread.listing_id) or get_listing(session, thread.listing_id),
            thread,
            current_version(session, thread, for_update=True),
            reason=reason,
            now=now,
        )
    return len(threads)


def assert_trip_offers_on_trip(session: Session, trip_id: int) -> None:
    """Every open trip-offer listing of the trip must still start and end on its stops, in order (BR #5)."""
    offers = session.execute(
        select(Listing).where(
            Listing.trip_id == trip_id,
            Listing.kind == ListingKind.TRIP_OFFER.value,
            Listing.status.not_in(CLOSED_OFFER_STATUSES),
        )
    ).scalars()
    for offer in offers:
        if trips_service.occurrence_seqs_for_stops(session, trip_id, offer.origin_stop_id, offer.destination_stop_id) is None:
            raise DomainError(
                ErrorCode.ROUTE_MISMATCH,
                details={
                    "reason": "trip_offer_stops_not_on_trip",
                    "listing_id": format_public_id(PublicIdPrefix.LISTING, offer.public_id),
                },
            )


def expire_due_proposals(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """Worker entry point: expire active versions past their TTL (their fee quotes expire with them, AC43).

    Never commits (AGENTS §4): the worker wraps each batch of at most ``limit`` threads in one transaction and
    commits it. Listings are taken in id order (ADR-0017) with ``SKIP LOCKED``: a listing a user command holds
    right now is skipped and retried on the next run. Returns the number of threads expired.
    """
    now = _now(now)
    rows = session.execute(
        select(ProposalThread.listing_id, ProposalThread.id)
        .join(ProposalVersion, ProposalVersion.id == ProposalThread.current_version_id)
        .where(
            ProposalThread.state == THREAD_OPEN,
            ProposalVersion.status == ProposalStatus.ACTIVE.value,
            ProposalVersion.expires_at <= now,
        )
        .order_by(ProposalThread.listing_id, ProposalThread.id)
        .limit(limit)
    ).all()
    expired = 0
    skipped_listings: set[int] = set()
    for listing_id, thread_id in rows:
        if listing_id in skipped_listings:
            continue
        listing = _try_lock_listing(session, listing_id)
        if listing is None:
            skipped_listings.add(listing_id)
            continue
        thread = lock_thread(session, thread_id)
        version = current_version(session, thread, for_update=True)
        if (
            thread.state != THREAD_OPEN
            or version is None
            or version.status != ProposalStatus.ACTIVE.value
            or ensure_aware_utc(version.expires_at) > now
        ):
            continue
        _expire_thread(session, listing, thread, version, reason="ttl_expired", now=now)
        expired += 1
    return expired


def expire_due_listings(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """Worker entry point: ``system_expire`` of listings past validity/departure; bookings unaffected.

    Never commits (AGENTS §4): the worker commits each batch of at most ``limit`` listings. Locked listings
    are skipped (``SKIP LOCKED``) and retried on the next run. Returns the number of listings expired.
    """
    now = _now(now)
    ids = list(
        session.execute(
            select(Listing.id)
            .where(
                Listing.status.in_(EXPIRABLE_STATUSES),
                or_(Listing.expires_at <= now, Listing.departure_window_end <= now),
            )
            .order_by(Listing.id)
            .limit(limit)
        ).scalars()
    )
    expired = 0
    for listing_id in ids:
        listing = _try_lock_listing(session, listing_id)
        if listing is None:
            continue
        due = ensure_aware_utc(listing.expires_at) <= now or ensure_aware_utc(listing.departure_window_end) <= now
        if listing.status not in EXPIRABLE_STATUSES or not due:
            continue
        LISTING.assert_transition(listing.status, ListingStatus.EXPIRED.value, "system_expire")
        _close_open_threads(session, listing, reason="listing_expired", now=now)
        listing.status = ListingStatus.EXPIRED.value
        listing.version += 1
        listing.updated_at = now
        session.flush()
        _emit(
            session,
            EventType.LISTING_EXPIRED,
            aggregate_type="listing",
            aggregate_public_id=listing_public_id(listing),
            aggregate_version=listing.version,
            aggregate_id=listing.id,
            payload={"kind": listing.kind, "service_type": listing.service_type, "reason_code": "expired"},
            now=now,
        )
        expired += 1
    return expired


# --- open auction: anonymized offers on a request (R1, ADR-0019, Q40-Q41) --------------------------

AUCTION_VISIBLE_STATUSES = (ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value)


@dataclass(frozen=True, slots=True)
class ListingOffer:
    thread_id: int
    version: ProposalVersion
    label_seq: int
    trip: Trip
    is_mine: bool
    response_pending: bool = False
    #: U6: the reputation of the driver behind the anonymous label. The id never leaves the view layer - it is
    #: only used to look up the rating bucket, which carries no identity (R1/Q40 stays intact).
    driver_user_id: int = 0
    service_type: str = ""


def list_listing_offers(
    session: Session,
    *,
    listing_public_id: str,
    viewer_user_id: int,
    after_thread_id: int | None = None,
    limit: int = 20,
    now: datetime | None = None,
) -> list[ListingOffer]:
    """Driver view of competing offers on a client request (R1).

    Visible only to drivers who could submit on this listing (``proposal.submit_as_driver``, not the
    owner, listing published/paused); anyone else gets 404. Per open thread only the latest
    driver-authored version is shown: client counters stay private to the pair (Q41). No identity
    leaves this function: the caller renders an anonymous label and the vehicle class only.

    Also gated by the service flag and corridor rollout (R1-a, else 404). Threads whose current version
    is no longer active or has expired are skipped; when the client countered last, the driver's latest
    offer is still shown with ``response_pending=True`` (R1-b). Labels are per (listing, driver): one
    driver answering with two trips has two threads under the same label (R1-c).
    """
    now = _now(now)
    listing = get_listing_by_public_id(session, listing_public_id)
    if (
        listing.kind != ListingKind.REQUEST.value
        or listing.status not in AUCTION_VISIBLE_STATUSES
        or listing.owner_user_id == viewer_user_id
    ):
        raise DomainError(ErrorCode.NOT_FOUND)
    caps = identity_service.get_capabilities(session, viewer_user_id, now=now)
    if not caps.has(Capability.PROPOSAL_SUBMIT_AS_DRIVER):
        raise DomainError(ErrorCode.NOT_FOUND)
    try:
        _require_service_flags(session, listing, include_driver_listing=False)
        # Q88: a map-point end has no stop to read the corridor off, so the listing's own corridor is the
        # question - the same corridor publish already proved serves both places. Reading it through the stop
        # catalogue turned every point-ended request's competing-offer list into a 404, i.e. Q40 was closed on
        # exactly the listings the client app creates today.
        _assert_listing_corridor_open(session, listing)
    except (DomainError, KeyError):
        raise DomainError(ErrorCode.NOT_FOUND) from None
    # BR blocker 7: every visibility condition is in the keyset SQL, so expired/closed threads never eat the
    # page (the API asks for limit + 1 and a full page always means "there may be more").
    current_alias = aliased(ProposalVersion)
    driver_version = aliased(ProposalVersion)
    stmt = (
        select(ProposalThread, current_alias)
        .join(current_alias, current_alias.id == ProposalThread.current_version_id)
        .where(
            ProposalThread.listing_id == listing.id,
            ProposalThread.state == THREAD_OPEN,
            current_alias.status == ProposalStatus.ACTIVE.value,
            current_alias.expires_at > now,
            exists(
                select(driver_version.id).where(
                    driver_version.thread_id == ProposalThread.id, driver_version.author_side == ActorSide.DRIVER.value
                )
            ),
        )
    )
    if after_thread_id is not None:
        stmt = stmt.where(ProposalThread.id > after_thread_id)
    rows = session.execute(stmt.order_by(ProposalThread.id).limit(limit)).all()
    labels = offer_labels(session, listing.id)
    offers: list[ListingOffer] = []
    for thread, current in rows:
        version = session.execute(
            select(ProposalVersion)
            .where(ProposalVersion.thread_id == thread.id, ProposalVersion.author_side == ActorSide.DRIVER.value)
            .order_by(ProposalVersion.revision.desc())
            .limit(1)
        ).scalar_one_or_none()
        if version is None:
            continue
        offers.append(
            ListingOffer(
                thread_id=thread.id,
                version=version,
                label_seq=labels.get(thread.driver_user_id, 0),
                trip=trips_service.get_trip(session, thread.trip_id),
                is_mine=thread.driver_user_id == viewer_user_id,
                response_pending=current.author_side == ActorSide.CLIENT.value,
                driver_user_id=thread.driver_user_id,
                service_type=listing.service_type,
            )
        )
    return offers


# ==============================================================================================================
# §5.2 parcel policy: prohibited / restricted items (wave 7)
# ==============================================================================================================


@dataclass(frozen=True, slots=True)
class ParcelPolicyView:
    """What the reader gets: the approved version (if any) and its rules.

    ``approved`` is false when no confirmed version is active. That is **not** "everything may be sent": the
    marketplace then refuses new parcel business in production (``assert_parcel_policy_ready``), and the client
    is told the list is not published yet.
    """

    approved: bool
    label: str | None
    effective_from: datetime | None
    items: tuple[ParcelPolicyItem, ...]


def active_parcel_policy(session: Session) -> ParcelPolicyView:
    """The confirmed, active policy version with its items; ``approved=False`` when there is none."""
    version = session.execute(
        select(ParcelPolicyVersion).where(
            ParcelPolicyVersion.status == "active", ParcelPolicyVersion.confirmed_by.is_not(None)
        )
    ).scalar_one_or_none()
    if version is None:
        return ParcelPolicyView(approved=False, label=None, effective_from=None, items=())
    items = tuple(
        session.execute(
            select(ParcelPolicyItem)
            .where(ParcelPolicyItem.policy_version_id == version.id)
            .order_by(ParcelPolicyItem.display_order, ParcelPolicyItem.id)
        ).scalars()
    )
    return ParcelPolicyView(
        approved=True, label=version.label,
        effective_from=ensure_aware_utc(version.effective_from) if version.effective_from else None,
        items=items,
    )


def assert_parcel_policy_ready(session: Session) -> None:
    """§5.2 fail-closed gate for **new** parcel business.

    With no approved policy, production refuses to open a new parcel listing or booking - an unpublished list
    cannot silently mean "anything goes". Outside production the same state is allowed so development is not
    blocked; the reader still reports ``approved=false`` and the client shows that the list is not published.

    Deliberately not called from delivery, proof, cancellation or dispute paths: a parcel already accepted is an
    obligation and must finish safely (D16 obligation capabilities).
    """
    if active_parcel_policy(session).approved:
        return
    if platform_service.is_production(session):
        raise DomainError(ErrorCode.PARCEL_POLICY_UNCONFIRMED, details={"reason": "parcel_policy_unconfirmed"})


def create_parcel_policy_version(
    session: Session, *, actor_user_id: int, label: str, source_note: str | None, items: Sequence[Any],
    now: datetime | None = None,
) -> ParcelPolicyVersion:
    """Draft a policy version (``super_admin``). A draft never applies to anyone until it is confirmed."""
    now = _now(now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.PLATFORM_POLICY_MANAGE,
        session=session,  # ADR-0021 step-up: approving what may be carried is a privileged command
    )
    if not items:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "items", "reason": "empty_policy"})
    version = ParcelPolicyVersion(
        public_id=new_public_uuid(), label=label.strip(), status="draft", source_note=source_note,
        created_by=actor_user_id, created_at=now, updated_at=now, version=1,
    )
    session.add(version)
    _flush_or_translate(
        session,
        {"uq_parcel_policy_versions_label": lambda: DomainError(
            ErrorCode.INTEGRITY_CONFLICT, details={"field": "label", "reason": "label_exists"}
        )},
    )
    for order, item in enumerate(items, start=1):
        session.add(
            ParcelPolicyItem(
                policy_version_id=version.id, code=item.code, category=item.category.value if hasattr(item.category, "value") else item.category,
                applies_to=item.applies_to.value if hasattr(item.applies_to, "value") else item.applies_to,
                title_uz=item.title_uz, description_uz=item.description_uz, legal_basis=item.legal_basis,
                source_ref=item.source_ref, source_checked_on=item.source_checked_on,
                display_order=item.display_order or order * 10,
            )
        )
    _flush_or_translate(
        session,
        {"ck_parcel_policy_items_basis": lambda: DomainError(
            ErrorCode.VALIDATION_ERROR,
            details={"reason": "prohibited_item_needs_legal_basis_and_source"},
        )},
    )
    return version


def confirm_parcel_policy_version(
    session: Session, *, actor_user_id: int, policy_public_id: str, expected_version: int,
    now: datetime | None = None,
) -> ParcelPolicyVersion:
    """Approve a drafted policy (``super_admin``). The previous active version becomes ``superseded``.

    This is the human decision the code refuses to make on its own: what may and may not be carried is a legal
    and business question, so the platform will not activate a list that nobody approved.
    """
    now = _now(now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.PLATFORM_POLICY_MANAGE,
        session=session,  # ADR-0021 step-up: approving what may be carried is a privileged command
    )
    value = parse_public_id(policy_public_id, PublicIdPrefix.PARCEL_POLICY)
    version = session.execute(
        select(ParcelPolicyVersion).where(ParcelPolicyVersion.public_id == value).with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if version.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"expected_version": version.version})
    if version.status != "draft":
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "parcel_policy", "status": version.status})
    if version.created_by == actor_user_id:
        # Same spirit as Q17/Q49: the author of a policy is not its approver.
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "author_cannot_confirm_own_policy"})
    current = session.execute(
        select(ParcelPolicyVersion).where(ParcelPolicyVersion.status == "active").with_for_update()
    ).scalar_one_or_none()
    if current is not None:
        current.status = "superseded"
        current.updated_at = now
        current.version += 1
        session.flush()
    version.status = "active"
    version.confirmed_by = actor_user_id
    version.confirmed_at = now
    version.effective_from = now
    version.updated_at = now
    version.version += 1
    session.flush()
    return version


def list_parcel_policy_versions(session: Session, *, actor_user_id: int, now: datetime | None = None) -> list[ParcelPolicyVersion]:
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=_now(now)), Capability.OPS_VIEW
    )
    return list(
        session.execute(select(ParcelPolicyVersion).order_by(ParcelPolicyVersion.id.desc())).scalars()
    )


def parcel_policy_public_id(version: ParcelPolicyVersion) -> str:
    return format_public_id(PublicIdPrefix.PARCEL_POLICY, version.public_id)
