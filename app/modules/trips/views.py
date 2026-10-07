"""DTO builders for trips (no writes). A trip is a stretch of one confirmed road (ADR-0028, Q160)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.contracts.enums import (
    ListingKind,
    ListingStatus,
    Role,
    ServiceType,
    TripStatus,
)
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.route_position import peak_load
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.identity import service as identity_service
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip, Vehicle
from app.modules.trips.ports import get_geo_port
from app.modules.trips.rules import mask_plate, vehicle_class
from app.modules.trips.schemas import (
    AdminVehicleDTO,
    AdminVehicleOwnerDTO,
    StretchAvailabilityDTO,
    TripAvailabilityDTO,
    TripDTO,
    TripListingRefDTO,
    TripPublicDTO,
    TripPublicVehicleDTO,
    TripVehicleDTO,
    VehicleDTO,
)


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


def trip_dto(session: Session, trip: Trip) -> TripDTO:
    from app.modules.marketplace import (
        service as marketplace_service,  # marketplace imports trips
    )

    vehicle = trips_service.get_vehicle(session, trip.vehicle_id)
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
        route_start_m=trip.route_start_m,
        route_end_m=trip.route_end_m,
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


def trip_public_dto(session: Session, trip: Trip) -> TripPublicDTO:  # noqa: ARG001 - the session is the builders' contract
    return TripPublicDTO(
        id=trips_service.trip_public_id(trip),
        status=TripStatus(trip.status),
        vehicle=TripPublicVehicleDTO(vehicle_class=vehicle_class(trip.seat_capacity), seat_capacity=trip.seat_capacity),
        planned_start_at=ensure_aware_utc(trip.planned_start_at),
        planned_end_at=ensure_aware_utc(trip.planned_end_at),
        timezone=trip.timezone,
    )


def availability_dto(session: Session, trip: Trip, now: datetime | None = None) -> TripAvailabilityDTO:
    """ADR-0028: the trip's stretch cut at every booking's place; each piece with what is still free on it."""
    claims = trips_service.active_claims(session, trip.id)
    start = trip.route_start_m or 0
    end = trip.route_end_m or start
    cuts = sorted({start, end, *(c.from_m for c in claims if start < c.from_m < end), *(c.to_m for c in claims if start < c.to_m < end)})
    pieces = []
    for from_m, to_m in zip(cuts, cuts[1:], strict=False):
        used = peak_load(claims, from_m, to_m)
        pieces.append(
            StretchAvailabilityDTO(
                from_m=from_m,
                to_m=to_m,
                seats_remaining=trip.seat_capacity - used["seats"][0],
                baggage_remaining_ml=trip.baggage_capacity_ml - used["baggage_ml"][0],
                cargo_remaining_weight_g=trip.cargo_capacity_weight_g - used["cargo_weight_g"][0],
                cargo_remaining_volume_ml=trip.cargo_capacity_volume_ml - used["cargo_volume_ml"][0],
            )
        )
    return TripAvailabilityDTO(
        trip_id=trips_service.trip_public_id(trip),
        trip_version=trip.version,
        computed_at=ensure_aware_utc(now) if now else utc_now(),
        stretches=pieces,
    )


# --- driver directions (ADR-0027) -------------------------------------------------------------------------------


def direction_trip_ref(session: Session, trip: Trip | None):  # noqa: ANN201 - DirectionTripRefDTO | None
    from app.modules.trips import directions as trip_directions
    from app.modules.trips.schemas import DirectionTripRefDTO

    if trip is None:
        return None
    return DirectionTripRefDTO(
        id=trips_service.trip_public_id(trip),
        status=TripStatus(trip.status),
        planned_start_at=ensure_aware_utc(trip.planned_start_at),
        planned_end_at=ensure_aware_utc(trip.planned_end_at),
        seats_booked=trip_directions.seats_booked(session, trip),
    )


def direction_dto(session: Session, direction, *, admin: bool = False):  # noqa: ANN001, ANN201
    """DriverDirectionDTO (or the admin variant): names of both ends, the road's districts between them, the car,
    the capacity and the trip the system made from the direction."""
    from app.modules.trips import directions as trip_directions
    from app.modules.trips.schemas import (
        AdminDriverDirectionDTO,
        DirectionEndDTO,
        DriverDirectionDTO,
    )

    origin, destination = trip_directions.direction_ends(session, direction)

    def end(value) -> DirectionEndDTO:  # noqa: ANN001
        return DirectionEndDTO(
            region_id=value.region_api_id, region_name_uz=value.region_name_uz, region_name_ru=value.region_name_ru,
            district_id=value.district_api_id, district_name_uz=value.district_name_uz, district_name_ru=value.district_name_ru,
        )

    routes = trip_directions.direction_routes(session, direction) if direction.status != trip_directions.STATUS_ARCHIVED else []
    via = trip_directions.via_district_names(session, routes[0]) if routes else []
    vehicle = trips_service.get_vehicle(session, direction.vehicle_id)
    fields = dict(
        id=trip_directions.direction_public_id(direction),
        origin=end(origin),
        destination=end(destination),
        via_district_names=via,
        vehicle_id=trips_service.vehicle_public_id(vehicle),
        seat_capacity=direction.seat_capacity,
        cargo_capacity_weight_g=direction.cargo_capacity_weight_g,
        cargo_capacity_volume_ml=direction.cargo_capacity_volume_ml,
        status=direction.status,
        version=direction.version,
        active_trip=direction_trip_ref(session, trip_directions.active_trip(session, direction)),
        created_at=ensure_aware_utc(direction.created_at),
        updated_at=ensure_aware_utc(direction.updated_at),
    )
    if not admin:
        return DriverDirectionDTO(**fields)
    from app.modules.bookings.rules import first_name

    refs = identity_service.user_refs(session, [direction.driver_user_id])
    driver_api_id, full_name = refs[direction.driver_user_id]
    return AdminDriverDirectionDTO(**fields, driver_id=driver_api_id, driver_display_name=first_name(full_name, "Haydovchi"))
