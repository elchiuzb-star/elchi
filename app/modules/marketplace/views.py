"""DTO builders for listings and proposals (no writes).

Privacy (spec §10.6, Q6, Q16): the public listing view never carries phones,
addresses, GPS or photos; the fee quote is only shown to the driver side.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from app.contracts.enums import (
    ActorSide,
    Currency,
    ListingKind,
    ListingStatus,
    ParcelPayer,
    ParcelType,
    PaymentMethod,
    PriceBasis,
    ProposalStatus,
    RatingBucket,
    ServiceType,
)
from app.contracts.dto import MediaRefDTO
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import ensure_aware_utc
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.models import Listing, ParcelListingDetails, PassengerListingDetails, ProposalThread, ProposalVersion
from app.modules.geo.schemas import DistrictRefDTO
from app.modules.marketplace.ports import get_ports
from app.modules.marketplace.rules import MAX_PRICE_REVISIONS_PER_SIDE, display_name
from app.modules.marketplace.schemas import (
    ProposalDriverSummaryDTO,
    BaggageDetails,
    ContactDetails,
    FeeQuoteDTO,
    ListingDTO,
    ListingOfferDTO,
    ListingOwnerDTO,
    ListingPublicDTO,
    DirectionPreviewDTO,
    ParcelDetails,
    PointEndDTO,
    PassengerDetails,
    PriceRevisionsLeftDTO,
    ProposalDemandDTO,
    ProposalPartyDTO,
    ProposalPromoClientDTO,
    ProposalPromoDriverDTO,
    ProposalThreadDTO,
    ProposalVersionDTO,
)
from app.modules.trips.models import Trip
from app.modules.trips.rules import vehicle_class
from app.modules.trips.views import stop_ref_dto
from app.utils.file_access import media_ref


def _passenger(row: PassengerListingDetails | None) -> PassengerDetails | None:
    if row is None:
        return None
    return PassengerDetails(
        seat_count=row.seat_count,
        adults=row.adults,
        children=row.children,
        child_seat_required=row.child_seat_required,
        baggage=BaggageDetails(
            pieces=row.baggage_pieces,
            total_weight_g=row.baggage_total_weight_g,
            total_volume_ml=row.baggage_total_volume_ml,
        ),
        special_assistance=row.special_assistance,
        amenities=list(row.amenities or []),
    )


def point_end_dto(session: Session, row, prefix: str) -> PointEndDTO | None:  # noqa: ANN001
    """Read one map-point end back (Q88), or ``None`` when that end is a verified stop.

    The district travels with it because it is what an operator files and searches by; it is explicitly not a
    validity claim - `PointEndInput` says why.
    """
    if getattr(row, f"{prefix}_point", None) is None:
        return None
    coords = session.execute(
        text(
            f"SELECT ST_Y({prefix}_point::geometry) AS lat, ST_X({prefix}_point::geometry) AS lng "
            f"FROM {row.__table__.name} WHERE id = :id"
        ),
        {"id": row.id},
    ).one()
    from app.modules.geo.service import districts_by_ids  # A2 public API; lazy to keep imports acyclic

    district_id = getattr(row, f"{prefix}_district_id", None)
    district = None
    if district_id is not None:
        info = districts_by_ids(session, [district_id]).get(district_id)
        if info is not None:
            district = DistrictRefDTO(id=info.api_id, name_uz=info.name_uz)
    return PointEndDTO(
        lat=float(coords.lat),
        lng=float(coords.lng),
        district=district,
        address=getattr(row, f"{prefix}_address", None),
        route_offset_m=getattr(row, f"{prefix}_route_offset_m", None),
    )


def parcel_photo_ref(stored_value: str | None) -> MediaRefDTO | None:
    """A signed link for a cargo photo. The **caller** decides who may see it; this only mints the URL."""
    ref = media_ref(stored_value)
    return MediaRefDTO(**ref) if ref else None


def _parcel(row: ParcelListingDetails | None, *, photo_visible: bool) -> ParcelDetails | None:
    if row is None:
        return None

    def aware(value):  # noqa: ANN001, ANN202
        return ensure_aware_utc(value) if value is not None else None

    # Q6: the cargo photo is for the owner, the assigned driver and staff. Everyone else gets neither the link
    # nor the key - a stored reference is not a public identifier.
    photo = parcel_photo_ref(row.photo_file_id) if photo_visible else None

    category = None
    if row.parcel_category_item_id is not None:
        from app.modules.marketplace import parcel_catalog

        category = parcel_catalog.item_dto(parcel_catalog.get_item(object_session(row), row.parcel_category_item_id))
    return ParcelDetails(
        category_id=category["id"] if category else None,
        category=category,
        parcel_type=row.parcel_type,
        weight_g=row.weight_g,
        length_cm=row.length_cm,
        width_cm=row.width_cm,
        height_cm=row.height_cm,
        fragile=row.fragile,
        declared_value_minor=row.declared_value_minor,
        photo_file_id=photo.file_id if photo else None,
        photo=photo,
        payer=ParcelPayer(row.payer) if row.payer else None,
        sender=ContactDetails(name=row.sender_name, phone=row.sender_phone) if row.sender_name and row.sender_phone else None,
        receiver=(
            ContactDetails(name=row.receiver_name, phone=row.receiver_phone)
            if row.receiver_name and row.receiver_phone
            else None
        ),
        pickup_window_start=aware(row.pickup_window_start),
        pickup_window_end=aware(row.pickup_window_end),
        dropoff_window_start=aware(row.dropoff_window_start),
        dropoff_window_end=aware(row.dropoff_window_end),
        max_weight_g=row.max_weight_g,
        max_volume_ml=row.max_volume_ml,
        max_dimension_cm=row.max_dimension_cm,
        accepted_parcel_types=list(row.accepted_parcel_types or []),
    )


def _category_of(session: Session, parcel: ParcelListingDetails | None) -> dict | None:
    """Q140: the category and its limits, shown to the driver before proposing (no personal data in it)."""
    if parcel is None or parcel.parcel_category_item_id is None:
        return None
    from app.modules.marketplace import parcel_catalog

    return parcel_catalog.item_dto(parcel_catalog.get_item(session, parcel.parcel_category_item_id))


def _trip_public_id(session: Session, trip_id: int | None) -> str | None:
    if trip_id is None:
        return None
    trip = session.get(Trip, trip_id)
    return format_public_id(PublicIdPrefix.TRIP, trip.public_id) if trip else None


def direction_preview_dto(session: Session, preview: dict) -> DirectionPreviewDTO:
    """Render what `preview_point_direction` worked out, including the radius the screen has to explain."""
    from app.modules.geo.geometry import encode_polyline

    from app.modules.geo.service import get_corridor

    corridor, route = preview["corridor"], preview["route"]
    # CorridorRef is the marketplace port's narrow view (id + rollout); the human name lives in geo.
    corridor_name = get_corridor(session, corridor.id).name
    origin, destination = preview["origin"], preview["destination"]

    def end(place) -> PointEndDTO:  # noqa: ANN001 - EndPlacement
        return PointEndDTO(
            lat=place.point.lat,
            lng=place.point.lng,
            district=None,
            address=place.point.address,
            route_offset_m=place.offset_m,
        )

    return DirectionPreviewDTO(
        corridor_id=corridor.public_id,
        corridor_name=corridor_name,
        route_version_id=format_public_id(PublicIdPrefix.ROUTE_VERSION, route.public_id),
        route_polyline=encode_polyline(route.geometry),
        distance_m=route.distance_m,
        duration_s=route.duration_s,
        # Both ends carry an interpolated cumulative value, so the leg is their difference. `max(0, ...)`
        # because a placement is only ever ordered origin-before-destination by the resolver, and a zero
        # is a truer answer than a negative one if that ever stops holding.
        leg_distance_m=max(0, destination.cumulative_distance_m - origin.cumulative_distance_m),
        leg_duration_s=max(0, destination.cumulative_duration_s - origin.cumulative_duration_s),
        max_point_offset_m=preview["max_point_offset_m"],
        origin=end(origin),
        destination=end(destination),
        districts_on_route=preview["districts_on_route"],
    )


def listing_dto(session: Session, listing: Listing, *, viewer_user_id: int | None = None) -> ListingDTO:
    """The owner's (or staff's) view of a listing.

    `viewer_user_id` decides one thing only: whether the cargo photo is rendered (Q6). It defaults to None,
    which means "not the owner", so a caller that forgets to pass it leaks nothing.
    """
    geo = get_ports().geo
    stops = geo.stops_by_ids(session, [listing.origin_stop_id, listing.destination_stop_id])
    corridor = geo.corridors_by_ids(session, [listing.corridor_id]).get(listing.corridor_id)
    owner_public_id, owner_name = identity_service.user_refs(session, [listing.owner_user_id])[listing.owner_user_id]
    return ListingDTO(
        id=marketplace_service.listing_public_id(listing),
        kind=ListingKind(listing.kind),
        service_type=ServiceType(listing.service_type),
        status=ListingStatus(listing.status),
        version=listing.version,
        terms_version=listing.terms_version,
        owner=ListingOwnerDTO(id=owner_public_id, display_name=display_name(owner_name)),
        corridor_id=corridor.public_id if corridor else "",
        origin_stop=stop_ref_dto(stops.get(listing.origin_stop_id)) if listing.origin_stop_id else None,
        destination_stop=stop_ref_dto(stops.get(listing.destination_stop_id)) if listing.destination_stop_id else None,
        origin_point=point_end_dto(session, listing, "origin"),
        destination_point=point_end_dto(session, listing, "destination"),
        departure_window_start=ensure_aware_utc(listing.departure_window_start),
        departure_window_end=ensure_aware_utc(listing.departure_window_end),
        timezone=listing.timezone,
        price_basis=PriceBasis(listing.price_basis),
        unit_price_minor=listing.unit_price_minor,
        quantity=listing.quantity,
        total_minor=listing.total_minor,
        currency=Currency(listing.currency),
        payment_method=PaymentMethod(listing.payment_method),
        expires_at=ensure_aware_utc(listing.expires_at),
        trip_id=_trip_public_id(session, listing.trip_id),
        passenger=_passenger(marketplace_service.get_passenger_details(session, listing.id)),
        parcel=_parcel(
            marketplace_service.get_parcel_details(session, listing.id),
            photo_visible=viewer_user_id is not None,
        ),
        comment=listing.comment,
        view_count=listing.view_count,
        published_at=ensure_aware_utc(listing.published_at) if listing.published_at else None,
        created_at=ensure_aware_utc(listing.created_at),
    )


def listing_public_dto(session: Session, listing: Listing) -> ListingPublicDTO:
    stops = get_ports().geo.stops_by_ids(session, [listing.origin_stop_id, listing.destination_stop_id])
    parcel = marketplace_service.get_parcel_details(session, listing.id)
    return ListingPublicDTO(
        id=marketplace_service.listing_public_id(listing),
        kind=ListingKind(listing.kind),
        service_type=ServiceType(listing.service_type),
        status=ListingStatus(listing.status),
        origin_stop=stop_ref_dto(stops.get(listing.origin_stop_id)) if listing.origin_stop_id else None,
        destination_stop=stop_ref_dto(stops.get(listing.destination_stop_id)) if listing.destination_stop_id else None,
        origin_point=point_end_dto(session, listing, "origin"),
        destination_point=point_end_dto(session, listing, "destination"),
        departure_window_start=ensure_aware_utc(listing.departure_window_start),
        departure_window_end=ensure_aware_utc(listing.departure_window_end),
        timezone=listing.timezone,
        price_basis=PriceBasis(listing.price_basis),
        unit_price_minor=listing.unit_price_minor,
        quantity=listing.quantity,
        total_minor=listing.total_minor,
        currency=Currency(listing.currency),
        reputation=None,
        parcel_type=ParcelType(parcel.parcel_type) if parcel and parcel.parcel_type else None,
        parcel_category=_category_of(session, parcel),
        trip_id=_trip_public_id(session, listing.trip_id),
        view_count=listing.view_count,
        published_at=ensure_aware_utc(listing.published_at) if listing.published_at else None,
    )


def _version_dto(
    session: Session,
    thread: ProposalThread,
    version: ProposalVersion,
    viewer_side: ActorSide | None,
    stops: dict,
    policies: dict,
    promo: dict | None = None,
    promo_reason: str | None = None,
    viewer_user_id: int | None = None,
) -> ProposalVersionDTO:
    fee_quote = None
    if viewer_side is ActorSide.DRIVER:
        policy = policies.get(version.fee_policy_id)
        fee_quote = FeeQuoteDTO(
            policy_id=policy.public_id if policy else "",
            policy_kind=policy.kind if policy else "",
            fee_bps=version.fee_bps,
            commission_minor=version.commission_minor,
            net_minor=version.total_minor - version.commission_minor,
            valid_until=ensure_aware_utc(version.expires_at),
        )
    promo_quote = None
    if promo is not None:
        # one object per role (Q16, Q103): the client's has no commission keys at all, not merely nulls
        promo_quote = ProposalPromoClientDTO(**promo) if viewer_side is ActorSide.CLIENT else ProposalPromoDriverDTO(**promo)
    confirmation = None
    if viewer_user_id is not None and version.status == "active":
        from app.modules.promotions.booking import version_confirmation_state

        confirmation = version_confirmation_state(session, version=version, viewer_user_id=viewer_user_id)
    return ProposalVersionDTO(
        id=marketplace_service.version_public_id(version),
        revision=version.revision,
        author_side=ActorSide(version.author_side),
        status=ProposalStatus(version.status),
        status_reason=version.status_reason,
        pickup_stop=stop_ref_dto(stops.get(version.pickup_stop_id)) if version.pickup_stop_id else None,
        dropoff_stop=stop_ref_dto(stops.get(version.dropoff_stop_id)) if version.dropoff_stop_id else None,
        pickup_point=point_end_dto(session, version, "pickup"),
        dropoff_point=point_end_dto(session, version, "dropoff"),
        pickup_window_start=ensure_aware_utc(version.pickup_window_start),
        pickup_window_end=ensure_aware_utc(version.pickup_window_end),
        quantity=version.quantity,
        price_basis=PriceBasis(version.price_basis),
        unit_price_minor=version.unit_price_minor,
        total_minor=version.total_minor,
        currency=Currency(version.currency),
        expires_at=ensure_aware_utc(version.expires_at),
        created_at=ensure_aware_utc(version.created_at),
        message=version.message,
        demand=ProposalDemandDTO(
            baggage_ml=version.baggage_ml,
            cargo_weight_g=version.cargo_weight_g,
            cargo_volume_ml=version.cargo_volume_ml,
            parcel_length_cm=version.parcel_length_cm,
            parcel_width_cm=version.parcel_width_cm,
            parcel_height_cm=version.parcel_height_cm,
        ),
        fee_quote=fee_quote,
        promo_quote=promo_quote,
        promo_unavailable_reason=promo_reason,
        promo_confirmation=confirmation,
        price_revisions_left=PriceRevisionsLeftDTO(
            client=MAX_PRICE_REVISIONS_PER_SIDE - thread.client_price_revisions,
            driver=MAX_PRICE_REVISIONS_PER_SIDE - thread.driver_price_revisions,
        ),
        # Q43/Q44: the receiver contact is the sender's (client's) own data; the driver gets it only through the
        # booking after pickup (A4), never from the proposal.
        receiver=(
            ContactDetails(name=version.receiver_name, phone=version.receiver_phone)
            if viewer_side is ActorSide.CLIENT and version.receiver_name and version.receiver_phone
            else None
        ),
    )


def _promo_preview(session: Session, thread: ProposalThread, version: ProposalVersion, listing: Listing,
                   viewer_side: ActorSide | None) -> tuple[dict | None, str | None]:
    """Referral stages 4-5: the promotions module's read-only preview of an open version's money terms for the
    viewer, or - when the viewer holds a bonus/credit that does not apply - the plain reason why."""
    if thread.state != marketplace_service.THREAD_OPEN or version.status != "active" or version.total_minor <= 0:
        return None, None
    from app.modules.geo import service as geo_service
    from app.modules.promotions.booking import no_discount_reason, preview_version_quote

    payer = None
    if listing.service_type == ServiceType.PARCEL.value:
        details = marketplace_service.get_parcel_details(session, listing.id) if listing.kind == "request" else None
        payer = details.payer if details is not None and details.payer else "sender"
    flags = geo_service.snapshot_flags(session, corridor_id=listing.corridor_id)
    quote = preview_version_quote(
        session, flags=flags, viewer_side=viewer_side,
        service_type=listing.service_type, parcel_payer=payer, fare_minor=version.total_minor, fee_bps=version.fee_bps,
        proposal_version_id=version.id, client_user_id=thread.client_user_id, driver_user_id=thread.driver_user_id)
    if quote is not None or viewer_side not in (ActorSide.CLIENT, ActorSide.DRIVER):
        return quote, None
    holder = thread.client_user_id if viewer_side is ActorSide.CLIENT else thread.driver_user_id
    reason = no_discount_reason(session, flags=flags, user_id=holder,
                                instrument="passenger_bonus" if viewer_side is ActorSide.CLIENT else "driver_credit",
                                service_type=listing.service_type, parcel_payer=payer, client_features=None)
    return None, None if reason == "no_campaign" else reason  # holding nothing is not news on every offer


def thread_dto(
    session: Session, thread: ProposalThread, *, viewer_user_id: int, include_versions: bool = False
) -> ProposalThreadDTO:
    viewer_side = marketplace_service.actor_side(thread, viewer_user_id)
    versions = marketplace_service.thread_versions(session, thread.id)
    current = next((v for v in versions if v.id == thread.current_version_id), None)
    shown = versions if include_versions else ([current] if current else [])
    stop_ids = sorted({v.pickup_stop_id for v in shown} | {v.dropoff_stop_id for v in shown})
    ports = get_ports()
    stops = ports.geo.stops_by_ids(session, stop_ids) if stop_ids else {}
    policies = (
        ports.fees.policy_refs(session, sorted({v.fee_policy_id for v in shown}))
        if viewer_side is ActorSide.DRIVER and shown
        else {}
    )
    listing = marketplace_service.get_listing(session, thread.listing_id)
    labels = marketplace_service.offer_labels(session, listing.id)
    driver_label = labels.get(thread.driver_user_id)

    def party(side: ActorSide) -> ProposalPartyDTO:
        # Pre-accept (every state A1 produces): no id, name or reputation link (R2, Q43).
        if side is ActorSide.CLIENT:
            return ProposalPartyDTO(side=side, label="Mijoz")
        return ProposalPartyDTO(side=side, label=f"Haydovchi #{driver_label}" if driver_label else "Haydovchi")

    return ProposalThreadDTO(
        id=marketplace_service.thread_public_id(thread),
        listing_id=marketplace_service.listing_public_id(listing),
        trip_id=_trip_public_id(session, thread.trip_id),
        state=thread.state,
        client=party(ActorSide.CLIENT),
        driver=party(ActorSide.DRIVER),
        current_version=_version_dto(session, thread, current, viewer_side, stops, policies,
                                     *_promo_preview(session, thread, current, listing, viewer_side),
                                     viewer_user_id=viewer_user_id) if current else None,
        versions=[_version_dto(session, thread, v, viewer_side, stops, policies) for v in versions] if include_versions else None,
        booking_id=_booking_id(session, thread),
        trip_intent_id=_trip_intent_id(session, thread) if viewer_side is ActorSide.CLIENT else None,
        driver_summary=_driver_summary(session, thread, listing) if viewer_side is ActorSide.CLIENT else None,
    )


def _driver_summary(session: Session, thread: ProposalThread, listing: Listing) -> ProposalDriverSummaryDTO | None:
    """ADR-0026: with no driver listings left, the client compares the answers to its own request by this - vehicle
    class, seats and the rating bucket with its count (U6), exactly the anonymous Q40 set; nothing that identifies."""
    if thread.trip_id is None:
        return None
    trip = session.get(Trip, thread.trip_id)
    if trip is None:
        return None
    summary = None
    try:
        from app.modules.trust_support import service as trust_support_service

        summary = trust_support_service.reputation_summaries(
            session, [thread.driver_user_id], service_type=listing.service_type).get(thread.driver_user_id)
    except Exception:  # noqa: BLE001 - an unknown reputation is shown as unknown, never as a default (AC36)
        summary = None
    return ProposalDriverSummaryDTO(
        vehicle_class=vehicle_class(trip.seat_capacity), seat_capacity=trip.seat_capacity,
        rating_bucket=_bucket_of(summary), rating_count=summary.rating_count if summary is not None else 0,
        completed_bookings=summary.completed_bookings if summary is not None else None,
    )


def _trip_intent_id(session: Session, thread: ProposalThread) -> str | None:
    """ADR-0025: the client's private request - never shown to the driver side."""
    if thread.trip_intent_id is None:
        return None
    from app.modules.marketplace.models import TripIntent

    intent = session.get(TripIntent, thread.trip_intent_id)
    return format_public_id(PublicIdPrefix.TRIP_INTENT, intent.public_id) if intent is not None else None


def _booking_id(session: Session, thread: ProposalThread) -> str | None:
    """Public booking id of an accepted thread (A4 read API; lazy import: bookings imports marketplace)."""
    if thread.state != marketplace_service.THREAD_ACCEPTED or thread.current_version_id is None:
        return None
    from app.modules.bookings import service as bookings_service

    return bookings_service.booking_public_id_for_proposal_version(session, thread.current_version_id)


def listing_offer_dtos(session: Session, offers: list) -> list[ListingOfferDTO]:
    stop_ids = sorted({o.version.pickup_stop_id for o in offers} | {o.version.dropoff_stop_id for o in offers})
    stops = get_ports().geo.stops_by_ids(session, stop_ids) if stop_ids else {}
    reputations = _offer_reputations(session, offers)
    return [
        ListingOfferDTO(
            label=f"Haydovchi #{offer.label_seq}",
            is_mine=offer.is_mine,
            response_pending=offer.response_pending,
            revision=offer.version.revision,
            quantity=offer.version.quantity,
            price_basis=PriceBasis(offer.version.price_basis),
            unit_price_minor=offer.version.unit_price_minor,
            total_minor=offer.version.total_minor,
            currency=Currency(offer.version.currency),
            pickup_stop=stop_ref_dto(stops.get(offer.version.pickup_stop_id)),
            dropoff_stop=stop_ref_dto(stops.get(offer.version.dropoff_stop_id)),
            pickup_window_start=ensure_aware_utc(offer.version.pickup_window_start),
            pickup_window_end=ensure_aware_utc(offer.version.pickup_window_end),
            vehicle_class=vehicle_class(offer.trip.seat_capacity),
            seat_capacity=offer.trip.seat_capacity,
            rating_bucket=_bucket_of(reputations.get(offer.driver_user_id)),
            rating_count=reputations[offer.driver_user_id].rating_count if offer.driver_user_id in reputations else 0,
            completed_bookings=(
                reputations[offer.driver_user_id].completed_bookings if offer.driver_user_id in reputations else None
            ),
            updated_at=ensure_aware_utc(offer.version.created_at),
        )
        for offer in offers
    ]


def _offer_reputations(session: Session, offers: list) -> dict[int, Any]:
    """U6: reputation of each driver behind an anonymous offer label.

    Returns an empty mapping when trust_support cannot answer (module absent, snapshot table missing). An empty
    mapping means "unknown", and the DTO then carries ``rating_bucket=None`` - never a default bucket and never
    a zero rating (§8.2, AC36).
    """
    service_types = {o.service_type for o in offers if o.service_type}
    driver_ids = sorted({o.driver_user_id for o in offers if o.driver_user_id})
    if not driver_ids or len(service_types) != 1:
        return {}
    try:
        from app.modules.trust_support import service as trust_support_service

        return trust_support_service.reputation_summaries(
            session, driver_ids, service_type=next(iter(service_types))
        )
    except Exception:  # noqa: BLE001 - a missing trust module must not break the auction view (Q74 spirit)
        return {}


def _bucket_of(summary: Any) -> RatingBucket | None:
    return None if summary is None else summary.rating_bucket
