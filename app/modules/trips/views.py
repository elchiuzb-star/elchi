"""DTO builders for trips (no writes). Stop names come from the geo port."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.contracts.enums import ListingKind, ListingStatus, Role, ServiceType, TripStatus
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.identity import service as identity_service
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip, Vehicle
from app.modules.trips.ports import StopRef, get_geo_port
from app.modules.trips.rules import Resource, mask_plate, vehicle_class
from app.modules.trips.schemas import (
    AdminVehicleDTO,
    AdminVehicleOwnerDTO,
    SegmentAvailabilityDTO,
    StopRefDTO,
    TripAvailabilityDTO,
    TripDTO,
    TripListingRefDTO,
    TripPublicDTO,
    TripPublicStopDTO,
    TripPublicVehicleDTO,
    TripStopDTO,
    TripVehicleDTO,
    VehicleDTO,
)


def stop_ref_dto(ref: StopRef | None) -> StopRefDTO:
    if ref is None:  # geo row missing: never invent a name
        return StopRefDTO(id="", name_uz="", name_ru=None)
    return StopRefDTO(id=ref.public_id, name_uz=ref.name_uz, name_ru=ref.name_ru)


def vehicle_dto(vehicle: Vehicle) -> VehicleDTO:
    return VehicleDTO(
        id=format_public_id(PublicIdPrefix.VEHICLE, vehicle.public_id),
        plate_number=vehicle.plate_number,
        plate_masked=mask_plate(vehicle.plate_normalized),
        make_model=vehicle.make_model,
        color=vehicle.color,
        seat_capacity=vehicle.seat_capacity,
        baggage_capacity_ml=vehicle.baggage_capacity_ml,
        cargo_max_weight_g=vehicle.cargo_max_weight_g,
        cargo_max_volume_ml=vehicle.cargo_max_volume_ml,
        document_file_ids=list(vehicle.document_file_ids or []),
        verification_status=vehicle.verification_status,
        version=vehicle.version,
        created_at=ensure_aware_utc(vehicle.created_at),
    )


def admin_vehicle_owner_dto(session: Session, driver_user_id: int) -> AdminVehicleOwnerDTO:
    """Eligibility of the vehicle's owner, recomputed on this read (no cache: a block applies at once)."""
    caps = identity_service.get_capabilities(session, driver_user_id)
    is_driver = Role.DRIVER in caps.roles
    return AdminVehicleOwnerDTO(
        user_id=identity_service.user_public_id(session, driver_user_id),
        is_driver=is_driver,
        account_active=caps.account_active,
        driver_verification_status=caps.driver.verification_status if caps.driver else None,
        eligible=caps.driver_eligible,
        reasons=list(caps.driver_reasons) if is_driver else [],
        blocked_reason=caps.driver.active_block_reason if caps.driver else None,
        eligibility_version=identity_service.eligibility_version(session, driver_user_id) if is_driver else None,
        active_trip_count=caps.driver.active_trip_count if caps.driver else 0,
    )


def admin_vehicle_dtos(session: Session, vehicles: list[Vehicle]) -> list[AdminVehicleDTO]:
    """Staff queue rows; one eligibility read per distinct owner on the page."""
    owners: dict[int, AdminVehicleOwnerDTO] = {}
    rows: list[AdminVehicleDTO] = []
    for vehicle in vehicles:
        owner = owners.get(vehicle.driver_user_id)
        if owner is None:
            owner = owners[vehicle.driver_user_id] = admin_vehicle_owner_dto(session, vehicle.driver_user_id)
        rows.append(
            AdminVehicleDTO(
                **vehicle_dto(vehicle).model_dump(),
                verification_reason=vehicle.verification_reason,
                verified_at=ensure_aware_utc(vehicle.verified_at) if vehicle.verified_at else None,
                updated_at=ensure_aware_utc(vehicle.updated_at),
                owner=owner,
            )
        )
    return rows


def _stops(session: Session, trip: Trip) -> tuple[list, dict[int, StopRef]]:
    occurrences = trips_service.list_occurrences(session, trip.id)
    refs = get_geo_port().stops_by_ids(session, sorted({o.stop_id for o in occurrences}))
    return occurrences, refs


def trip_dto(session: Session, trip: Trip) -> TripDTO:
    from app.modules.marketplace import service as marketplace_service  # marketplace imports trips

    vehicle = trips_service.get_vehicle(session, trip.vehicle_id)
    occurrences, refs = _stops(session, trip)
    route = get_geo_port().route_versions_by_ids(session, [trip.route_version_id]).get(trip.route_version_id)
    listings = marketplace_service.listings_for_trip(session, trip.id)
    return TripDTO(
        id=trips_service.trip_public_id(trip),
        status=TripStatus(trip.status),
        version=trip.version,
        vehicle=TripVehicleDTO(
            id=format_public_id(PublicIdPrefix.VEHICLE, vehicle.public_id),
            make_model=vehicle.make_model,
            color=vehicle.color,
            plate_masked=mask_plate(vehicle.plate_normalized),
            seat_capacity=vehicle.seat_capacity,
        ),
        route_version_id=route.public_id if route else "",
        stops=[
            TripStopDTO(
                seq=o.seq,
                stop=stop_ref_dto(refs.get(o.stop_id)),
                planned_arrival_at=ensure_aware_utc(o.planned_arrival_at),
                dwell_minutes=o.dwell_minutes,
                eta_arrival_at=ensure_aware_utc(o.eta_arrival_at) if o.eta_arrival_at else None,
            )
            for o in occurrences
        ],
        planned_start_at=ensure_aware_utc(trip.planned_start_at),
        planned_end_at=ensure_aware_utc(trip.planned_end_at),
        timezone=trip.timezone,
        seat_capacity=trip.seat_capacity,
        baggage_capacity_ml=trip.baggage_capacity_ml,
        cargo_capacity_weight_g=trip.cargo_capacity_weight_g,
        cargo_capacity_volume_ml=trip.cargo_capacity_volume_ml,
        max_detour_minutes=trip.max_detour_minutes,
        max_detour_m=trip.max_detour_m,
        detour_used_minutes=-(-trip.detour_used_s // 60),
        detour_used_s=trip.detour_used_s,
        detour_used_m=trip.detour_used_m,
        pickup_wait_minutes=trip.pickup_wait_minutes,
        booking_cutoff_at=ensure_aware_utc(trip.booking_cutoff_at),
        listings=[
            TripListingRefDTO(
                id=format_public_id(PublicIdPrefix.LISTING, listing.public_id),
                kind=ListingKind(listing.kind),
                service_type=ServiceType(listing.service_type),
                status=ListingStatus(listing.status),
            )
            for listing in listings
        ],
        open_cases=None,
        created_at=ensure_aware_utc(trip.created_at),
    )


def trip_public_dto(session: Session, trip: Trip) -> TripPublicDTO:
    vehicle = trips_service.get_vehicle(session, trip.vehicle_id)
    occurrences, refs = _stops(session, trip)
    return TripPublicDTO(
        id=trips_service.trip_public_id(trip),
        status=TripStatus(trip.status),
        vehicle=TripPublicVehicleDTO(vehicle_class=vehicle_class(trip.seat_capacity), seat_capacity=trip.seat_capacity),
        stops=[
            TripPublicStopDTO(
                seq=o.seq, stop=stop_ref_dto(refs.get(o.stop_id)), planned_arrival_at=ensure_aware_utc(o.planned_arrival_at)
            )
            for o in occurrences
        ],
        planned_start_at=ensure_aware_utc(trip.planned_start_at),
        planned_end_at=ensure_aware_utc(trip.planned_end_at),
        timezone=trip.timezone,
    )


def availability_dto(session: Session, trip: Trip, now: datetime | None = None) -> TripAvailabilityDTO:
    occurrences, refs = _stops(session, trip)
    stop_by_seq = {o.seq: refs.get(o.stop_id) for o in occurrences}
    loads = trips_service.get_segment_loads(session, trip.id)
    return TripAvailabilityDTO(
        trip_id=trips_service.trip_public_id(trip),
        trip_version=trip.version,
        computed_at=ensure_aware_utc(now) if now else utc_now(),
        segments=[
            SegmentAvailabilityDTO(
                from_seq=load.from_seq,
                to_seq=load.to_seq,
                from_stop_id=stop_ref_dto(stop_by_seq.get(load.from_seq)).id,
                to_stop_id=stop_ref_dto(stop_by_seq.get(load.to_seq)).id,
                seats_remaining=load.remaining(Resource.SEATS),
                baggage_remaining_ml=load.remaining(Resource.BAGGAGE_ML),
                cargo_remaining_weight_g=load.remaining(Resource.CARGO_WEIGHT_G),
                cargo_remaining_volume_ml=load.remaining(Resource.CARGO_VOLUME_ML),
            )
            for load in loads
        ],
    )
