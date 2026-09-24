"""DTO builders for bookings (no writes).

Viewer roles: the client gets ``BookingClientDTO`` (no commission/fee keys, Q16); the driver and staff get
``BookingDTO``. Contact data follows Q44 through ``rules.contact_visibility`` / ``rules.phone_disclosure``:
before the service starts nobody sees a phone; the parcel sender's phone never reaches the driver; the
receiver's phone only after pickup. Staff views show contacts; the API writes an audit row for them.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.dto import MediaRefDTO
from app.contracts.disclosure import full_plate_visible, full_plate_visible_from, mask_plate_number
from app.contracts.enums import ActorSide, CashCollectionStatus, CommissionStatus, Currency, PaymentMethod, PriceBasis, ServiceType
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.bookings import rules
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking, BookingAmendment, CashReceipt
from app.modules.bookings.schemas import (
    AmendmentDTO,
    BookingCancelledDTO,
    BookingClientDTO,
    BookingClientPartyDTO,
    BookingCodeDTO,
    BookingCodesDTO,
    BookingContactDTO,
    BookingDriverDTO,
    BookingDTO,
    BookingFeeDTO,
    BookingListingIdsDTO,
    BookingPromoClientDTO,
    BookingPromoDriverDTO,
    BookingPolicyVersionsDTO,
    BookingStopDTO,
    BookingVehicleDTO,
    CashReceiptDTO,
    CustodyCaseDTO,
    ManifestItemDTO,
    ManifestStopDTO,
    NoShowReviewDTO,
    ParcelContactsDTO,
    TripManifestDTO,
)
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace import views as marketplace_views
from app.utils.file_access import media_ref
from app.modules.marketplace.models import Listing, ProposalVersion
from app.modules.promotions import booking as promo_booking
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip
from app.modules.trips.ports import get_geo_port
from app.modules.trips.rules import vehicle_class
from app.modules.trips.views import stop_ref_dto

ViewerRole = bookings_service.ViewerRole
# Q64: bookings that ended before the service started never disclose the full plate.
NO_PLATE_STATUSES = frozenset({"cancelled", "no_show"})


def _vehicle_dto(booking: Booking, trip: Trip, vehicle, *, staff: bool, now: datetime) -> BookingVehicleDTO:  # noqa: ANN001
    ended_before_start = booking.service_status in NO_PLATE_STATUSES
    pickup_at = ensure_aware_utc(booking.pickup_window_start)
    visible = staff or (not ended_before_start and full_plate_visible(trip_status=trip.status, pickup_at=pickup_at, now=now))
    return BookingVehicleDTO(
        vehicle_class=vehicle_class(trip.seat_capacity),
        seat_capacity=trip.seat_capacity,
        make_model=vehicle.make_model,
        color=vehicle.color,
        plate_masked=mask_plate_number(vehicle.plate_normalized),
        plate_number=vehicle.plate_number if visible else None,
        plate_number_visible_from=None if (staff or ended_before_start) else full_plate_visible_from(pickup_at),
    )


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else ensure_aware_utc(value)


def _phone(session: Session, user_id: int) -> str:
    return identity_service.get_user_summary(session, user_id).phone


def _listing_public(session: Session, listing_id: int | None) -> str | None:
    if listing_id is None:
        return None
    listing = session.get(Listing, listing_id)
    return marketplace_service.listing_public_id(listing) if listing else None


def _fee_block(session: Session, booking: Booking) -> BookingFeeDTO:
    from app.modules.wallet.models import CommissionPolicy  # read-only immutable policy identity (A1 adapter pattern)

    row = session.execute(
        select(CommissionPolicy.public_id, CommissionPolicy.kind).where(CommissionPolicy.id == booking.fee_policy_id)
    ).one()
    return BookingFeeDTO(
        policy_id=format_public_id(PublicIdPrefix.COMMISSION_POLICY, row.public_id),
        policy_kind=row.kind,
        fee_bps=booking.fee_bps,
        commission_minor=booking.commission_minor,
        # what the driver keeps: F - C, plus the Driver Credit on a discounted booking (F - C + H)
        net_minor=promo_booking.terms_for_booking(session, booking).driver_keeps_minor,
    )


def booking_view(
    session: Session, booking: Booking, *, viewer_role: str, now: datetime | None = None
) -> BookingDTO | BookingClientDTO:
    now = ensure_aware_utc(now) if now is not None else utc_now()
    service = ServiceType(booking.service_type)
    trip = trips_service.get_trip(session, booking.trip_id)
    occurrences = {o.seq: o for o in trips_service.list_occurrences(session, trip.id)}
    stops = get_geo_port().stops_by_ids(session, [booking.pickup_stop_id, booking.dropoff_stop_id])
    pickup_occ, dropoff_occ = occurrences.get(booking.pickup_occurrence_seq), occurrences.get(booking.dropoff_occurrence_seq)
    visibility = rules.contact_visibility(
        service_started_at=booking.service_started_at, service_terminal_at=booking.service_terminal_at, now=now
    )
    disclosure = rules.phone_disclosure(service, visibility)
    staff = viewer_role == ViewerRole.STAFF
    refs = identity_service.user_refs(session, [booking.client_user_id, booking.driver_user_id])

    driver_block = client_block = parcel_contacts = None
    if viewer_role in (ViewerRole.CLIENT, ViewerRole.STAFF):
        vehicle = trips_service.get_vehicle(session, trip.vehicle_id)
        driver_id, driver_name = refs[booking.driver_user_id]
        driver_block = BookingDriverDTO(
            id=driver_id,
            display_name=rules.first_name(driver_name, "Haydovchi"),
            vehicle=_vehicle_dto(booking, trip, vehicle, staff=staff, now=now),
            contact_phone=_phone(session, booking.driver_user_id) if (staff or disclosure.driver_phone_to_client) else None,
        )
    if viewer_role in (ViewerRole.DRIVER, ViewerRole.STAFF):
        client_id, client_name = refs[booking.client_user_id]
        client_block = BookingClientPartyDTO(
            id=client_id,
            display_name=rules.first_name(client_name, "Mijoz"),
            contact_phone=_phone(session, booking.client_user_id) if (staff or disclosure.client_phone_to_driver) else None,
        )
        if service is ServiceType.PARCEL:
            # Request parcels: listing details; trip-offer parcels: A1 ``parcel_receiver(version)``. Q44: after pickup.
            receiver = bookings_service.parcel_receiver_for(session, booking)
            reveal = staff or disclosure.receiver_phone_to_driver
            parcel_contacts = ParcelContactsDTO(
                receiver_name=receiver[0] if (receiver is not None and reveal) else None,
                receiver_phone=receiver[1] if (receiver is not None and reveal) else None,
            )

    # Q6: the sender, the assigned driver and staff see the cargo photo; nobody else has a booking here at all.
    # The link is minted per response and expires on its own, so the driver client re-reads the booking to
    # refresh it rather than holding a long-lived URL.
    parcel_photo = None
    if service is ServiceType.PARCEL and booking.request_listing_id is not None:
        details = marketplace_service.get_parcel_details(session, booking.request_listing_id)
        ref = media_ref(details.photo_file_id) if details else None
        parcel_photo = MediaRefDTO(**ref) if ref else None

    receipt = bookings_service.latest_cash_receipt(session, booking.id)
    review = bookings_service.latest_no_show_review(session, booking.id)
    case = bookings_service.latest_custody_case(session, booking.id)
    version = session.get(ProposalVersion, booking.accepted_proposal_version_id)
    common = dict(
        id=bookings_service.booking_public_id(booking),
        viewer_side=viewer_role,
        service_type=service,
        service_status=booking.service_status,
        cash_status=CashCollectionStatus(booking.cash_status),
        version=booking.version,
        trip_id=trips_service.trip_public_id(trip),
        listing_ids=BookingListingIdsDTO(
            request=_listing_public(session, booking.request_listing_id), supply=_listing_public(session, booking.supply_listing_id)
        ),
        accepted_proposal_version_id=marketplace_service.version_public_id(version) if version else "",
        quantity=booking.quantity,
        price_basis=PriceBasis(booking.price_basis),
        unit_price_minor=booking.unit_price_minor,
        total_minor=booking.total_minor,
        currency=Currency(booking.currency),
        payment_method=PaymentMethod(booking.payment_method),
        pickup=BookingStopDTO(
            stop=stop_ref_dto(stops.get(booking.pickup_stop_id)) if booking.pickup_stop_id else None,
            point=marketplace_views.point_end_dto(session, booking, "pickup"),
            occurrence_seq=booking.pickup_occurrence_seq,
            planned_arrival_at=_aware(pickup_occ.planned_arrival_at) if pickup_occ else None,
            window_start=_aware(booking.pickup_window_start),
            window_end=_aware(booking.pickup_window_end),
        ),
        dropoff=BookingStopDTO(
            stop=stop_ref_dto(stops.get(booking.dropoff_stop_id)) if booking.dropoff_stop_id else None,
            point=marketplace_views.point_end_dto(session, booking, "dropoff"),
            occurrence_seq=booking.dropoff_occurrence_seq,
            planned_arrival_at=_aware(dropoff_occ.planned_arrival_at) if dropoff_occ else None,
            window_start=_aware(booking.dropoff_window_start),
            window_end=_aware(booking.dropoff_window_end),
        ),
        driver=driver_block,
        client=client_block,
        parcel_contacts=parcel_contacts,
        parcel_photo=parcel_photo,
        contact=BookingContactDTO(
            phones_visible=visibility.phones_visible, visible_from=visibility.visible_from,
            visible_until=visibility.visible_until,
            chat_thread_id=bookings_service.chat_thread_public_id(session, booking.id),
        ),
        no_show_review=(
            NoShowReviewDTO(status=review.status, reported_at=ensure_aware_utc(review.created_at), decided_at=_aware(review.decided_at))
            if review
            else None
        ),
        cash_receipt=cash_receipt_dto(receipt, booking) if receipt else None,
        custody_case=(
            CustodyCaseDTO(
                status=case.status, reason_code=case.opened_reason_code, opened_at=ensure_aware_utc(case.opened_at),
                resolved_at=_aware(case.resolved_at),
            )
            if case
            else None
        ),
        policy_versions=BookingPolicyVersionsDTO(
            listing_version=booking.listing_version,
            listing_terms_version=booking.listing_terms_version,
            cancellation_policy=str(booking.terms_snapshot.get("cancellation_policy", rules.CANCELLATION_POLICY)),
        ),
        cancellation_policy_summary=rules.CANCELLATION_POLICY_SUMMARY,
        cancelled=(
            BookingCancelledDTO(
                by_side=ActorSide(booking.cancelled_by_side), reason_code=booking.cancel_reason_code or "",
                fault_side=booking.fault_side, at=ensure_aware_utc(booking.cancelled_at),
            )
            if booking.cancelled_at is not None
            else None
        ),
        created_at=ensure_aware_utc(booking.created_at),
        updated_at=ensure_aware_utc(booking.updated_at),
    )
    if viewer_role == ViewerRole.CLIENT:
        client_promo = promo_booking.client_promo_view(session, booking)
        return BookingClientDTO(**common, promo=BookingPromoClientDTO(**client_promo) if client_promo else None)
    driver_promo = promo_booking.driver_promo_view(session, booking)
    return BookingDTO(**common, commission_status=CommissionStatus(booking.commission_status), fee=_fee_block(session, booking),
                      promo=BookingPromoDriverDTO(**driver_promo) if driver_promo else None)


def staff_contact_fields(dto: BookingDTO | BookingClientDTO) -> list[str]:
    """Which contact values a staff response actually shows (for the ``booking_contacts_viewed`` audit row)."""
    fields: list[str] = []
    if dto.driver is not None and dto.driver.contact_phone:
        fields.append("driver_phone")
    if dto.driver is not None and dto.driver.vehicle.plate_number:
        fields.append("plate_number")
    if dto.client is not None and dto.client.contact_phone:
        fields.append("client_phone")
    if dto.parcel_contacts is not None and dto.parcel_contacts.receiver_phone:
        fields.append("receiver_phone")
    return fields


def codes_dto(booking_public_id: str, codes: list) -> BookingCodesDTO:
    return BookingCodesDTO(booking_id=booking_public_id, codes=[BookingCodeDTO(kind=kind, code=code) for kind, code in codes])


def cash_receipt_dto(receipt: CashReceipt, booking: Booking) -> CashReceiptDTO:
    return CashReceiptDTO(
        id=format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id),
        booking_id=bookings_service.booking_public_id(booking),
        booking_version=booking.version,
        reported_by_side=receipt.reported_by_side,
        amount_minor=receipt.amount_minor,
        currency=Currency(receipt.currency),
        status=receipt.status,
        reported_at=ensure_aware_utc(receipt.reported_at),
        decided_at=_aware(receipt.decided_at),
        dispute_id=None if receipt.dispute_id is None else str(receipt.dispute_id),
        version=receipt.version,
    )


def amendment_dto(amendment: BookingAmendment, booking: Booking, *, viewer_role: str,
                  session: Session | None = None) -> AmendmentDTO:
    promo = None
    if session is not None:
        view = promo_booking.amendment_promo_view(session, booking, amendment, viewer_role=viewer_role)
        if view is not None:
            promo = BookingPromoClientDTO(**view) if viewer_role == ViewerRole.CLIENT else BookingPromoDriverDTO(**view)
    return AmendmentDTO(
        id=format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id),
        booking_id=bookings_service.booking_public_id(booking),
        status=amendment.status,
        author_side=amendment.author_side,
        changes=dict(amendment.changes),
        new_quantity=amendment.new_quantity,
        new_unit_price_minor=amendment.new_unit_price_minor,
        new_total_minor=amendment.new_total_minor,
        fee_delta_minor=None if viewer_role == ViewerRole.CLIENT else amendment.fee_delta_minor,
        promo=promo,
        expires_at=ensure_aware_utc(amendment.expires_at),
        version=amendment.version,
    )


def manifest_dto(session: Session, trip: Trip, entries: list) -> TripManifestDTO:
    occurrences = trips_service.list_occurrences(session, trip.id)
    stops = get_geo_port().stops_by_ids(session, sorted({o.stop_id for o in occurrences}))
    pickups: dict[int, list[ManifestItemDTO]] = {}
    dropoffs: dict[int, list[ManifestItemDTO]] = {}
    for entry in entries:
        booking = entry.booking
        item = ManifestItemDTO(
            booking_id=bookings_service.booking_public_id(booking),
            service_type=ServiceType(booking.service_type),
            service_status=booking.service_status,
            seats=booking.seats if booking.service_type == ServiceType.PASSENGER.value else None,
            parcel_summary=(
                f"{booking.cargo_weight_g} g, {booking.cargo_volume_ml} ml" if booking.service_type == ServiceType.PARCEL.value else None
            ),
            client_first_name=entry.client_first_name,
            contact_phone=entry.contact_phone,
        )
        pickups.setdefault(booking.pickup_occurrence_seq, []).append(item)
        dropoffs.setdefault(booking.dropoff_occurrence_seq, []).append(item)
    return TripManifestDTO(
        trip_id=trips_service.trip_public_id(trip),
        trip_version=trip.version,
        stops=[
            ManifestStopDTO(
                seq=o.seq,
                stop=stop_ref_dto(stops.get(o.stop_id)),
                planned_arrival_at=ensure_aware_utc(o.planned_arrival_at),
                pickups=pickups.get(o.seq, []),
                dropoffs=dropoffs.get(o.seq, []),
            )
            for o in occurrences
        ],
    )
