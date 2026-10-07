"""API v2 vehicles and trips router (T1-T8). Mounted by the integrator under ``/api/v2``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts.dto import MAX_PAGE_LIMIT, Envelope, PageMeta
from app.contracts.enums import Capability, Role, TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity import service as identity_service
from app.modules.identity.web import (
    ERROR_RESPONSES,
    current_user_id,
    decode_time_id_cursor,
    encode_page_cursor,
    get_session,
    optional_user_id,
    page_scope,
    run_command,
    run_versioned,
)
from app.modules.marketplace import service as marketplace_service
from app.modules.trips import directions as trip_directions
from app.modules.trips import service as trips_service
from app.modules.trips.schemas import (
    AdminDriverDirectionDTO,
    AdminTripSearchDTO,
    AdminVehicleDTO,
    AdminVehicleStatus,
    DriverDirectionCreate,
    DriverDirectionDTO,
    DriverDirectionPatch,
    TripAvailabilityDTO,
    TripCreate,
    TripDTO,
    TripPatch,
    TripPublicDTO,
    VehicleCreate,
    VehicleDTO,
    VehicleVerifyRequest,
)
from app.modules.trips.views import (
    admin_vehicle_dtos,
    availability_dto,
    direction_dto,
    trip_dto,
    trip_public_dto,
    vehicle_dto,
)

router = APIRouter(tags=["v2 Trips"])


@router.post("/vehicles", response_model=Envelope[VehicleDTO], status_code=201, responses=ERROR_RESPONSES)
def create_vehicle(
    body: VehicleCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: vehicle_dto(trips_service.create_vehicle(session, driver_user_id=user_id, data=body)),
        success_status=201,
        resource_type="vehicle",
    )


@router.get("/me/vehicles", response_model=Envelope[list[VehicleDTO]], responses=ERROR_RESPONSES)
def list_my_vehicles(
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[list[VehicleDTO]]:
    if Role.DRIVER not in identity_service.get_capabilities(session, user_id).roles:
        raise DomainError(ErrorCode.CAPABILITY_REQUIRED, details={"role": Role.DRIVER.value})
    return Envelope[list[VehicleDTO]](data=[vehicle_dto(v) for v in trips_service.list_driver_vehicles(session, user_id)])


@router.get("/admin/vehicles", response_model=Envelope[list[AdminVehicleDTO]], responses=ERROR_RESPONSES)
def list_vehicles_for_review(
    status: AdminVehicleStatus | None = Query(default=None, description="Omit for every status."),
    owner_user_id: str | None = Query(
        default=None, max_length=64, description="Only this driver's vehicles (usr_ public id); omit for everyone."
    ),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[AdminVehicleDTO]]:
    """T3a: vehicles awaiting (or past) a staff decision, oldest first. Same capability as T3 verify."""
    scope = page_scope("GET /admin/vehicles", status=status, owner=owner_user_id)
    rows = trips_service.list_vehicles_for_review(
        session,
        actor_user_id=user_id,
        statuses=[status] if status else None,
        owner_user_public_id=owner_user_id,
        after=decode_time_id_cursor(cursor, scope),
        limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].created_at, page[-1].id], scope) if more else None
    return Envelope[list[AdminVehicleDTO]](
        data=admin_vehicle_dtos(session, page), meta=PageMeta(next_cursor=next_cursor, limit=limit)
    )


@router.post("/admin/vehicles/{vehicle_id}/verify", response_model=Envelope[VehicleDTO], responses=ERROR_RESPONSES)
def verify_vehicle(
    vehicle_id: str,
    body: VehicleVerifyRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: vehicle_dto(
            trips_service.verify_vehicle(
                session,
                vehicle_public_id=vehicle_id,
                actor_user_id=user_id,
                expected_version=body.expected_version,
                decision=body.decision,
                reason=body.reason,
            )
        ),
        resource_type="vehicle",
    )


@router.post("/trips", response_model=Envelope[TripDTO], status_code=201, responses=ERROR_RESPONSES)
def create_trip(
    body: TripCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: trip_dto(session, trips_service.create_trip(session, driver_user_id=user_id, data=body)),
        success_status=201,
        resource_type="trip",
    )


def _can_see_full_trip(session: Session, trip_driver_id: int, user_id: int | None) -> bool:
    if user_id is None:
        return False
    if user_id == trip_driver_id:
        return True
    return identity_service.get_capabilities(session, user_id).has(Capability.OPS_VIEW)


@router.get("/admin/trips/search", response_model=Envelope[list[AdminTripSearchDTO]], responses=ERROR_RESPONSES)
def search_admin_trips(
    q: str = Query(min_length=4, max_length=40),
    limit: int = Query(default=20, ge=1, le=trips_service.ADMIN_TRIP_SEARCH_MAX_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[AdminTripSearchDTO]]:
    from app.contracts.ids import PublicIdPrefix, format_public_id
    from app.contracts.timeutil import ensure_aware_utc
    from app.modules.bookings.rules import first_name

    trips = trips_service.admin_search_trips(session, actor_user_id=user_id, q=q, limit=limit)
    refs = identity_service.user_refs(session, [trip.driver_user_id for trip in trips])
    vehicles = {trip.vehicle_id: trips_service.get_vehicle(session, trip.vehicle_id) for trip in trips}
    return Envelope[list[AdminTripSearchDTO]](
        data=[
            AdminTripSearchDTO(
                id=trips_service.trip_public_id(trip),
                status=TripStatus(trip.status),
                driver_id=refs[trip.driver_user_id][0],
                driver_display_name=first_name(refs[trip.driver_user_id][1], "Haydovchi"),
                vehicle_id=format_public_id(PublicIdPrefix.VEHICLE, vehicles[trip.vehicle_id].public_id),
                planned_start_at=ensure_aware_utc(trip.planned_start_at),
                planned_end_at=ensure_aware_utc(trip.planned_end_at),
                seat_capacity=trip.seat_capacity,
            )
            for trip in trips
        ]
    )


@router.get("/trips/{trip_id}", response_model=Envelope[TripDTO | TripPublicDTO], responses=ERROR_RESPONSES)
def get_trip(
    trip_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[TripDTO | TripPublicDTO]:
    trip = trips_service.get_trip_by_public_id(session, trip_id)
    if _can_see_full_trip(session, trip.driver_user_id, user_id):
        return Envelope[TripDTO | TripPublicDTO](data=trip_dto(session, trip))
    # Booking participants (A4) will also get the public view; until then an open offer is required.
    if marketplace_service.has_published_trip_offer(session, trip.id):
        return Envelope[TripDTO | TripPublicDTO](data=trip_public_dto(session, trip))
    raise DomainError(ErrorCode.NOT_FOUND)


@router.get("/me/trips", response_model=Envelope[list[TripDTO]], responses=ERROR_RESPONSES)
def list_my_trips(
    status: TripStatus | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[TripDTO]]:
    identity_service.require_capability(identity_service.get_capabilities(session, user_id), Capability.TRIP_OPERATE)
    scope = page_scope("GET /me/trips", status=status.value if status else None)
    rows = trips_service.list_driver_trips(
        session,
        user_id,
        statuses=[status.value] if status else None,
        after=decode_time_id_cursor(cursor, scope),
        limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].planned_start_at, page[-1].id], scope) if more else None
    return Envelope[list[TripDTO]](
        data=[trip_dto(session, trip) for trip in page], meta=PageMeta(next_cursor=next_cursor, limit=limit)
    )


@router.patch("/trips/{trip_id}", response_model=Envelope[TripDTO], responses=ERROR_RESPONSES)
def patch_trip(
    trip_id: str, body: TripPatch, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[TripDTO]:
    dto = run_versioned(
        session,
        lambda: trip_dto(
            session, trips_service.patch_trip(session, trip_public_id_value=trip_id, actor_user_id=user_id, data=body)
        ),
    )
    return Envelope[TripDTO](data=dto)


@router.get("/trips/{trip_id}/availability", response_model=Envelope[TripAvailabilityDTO], responses=ERROR_RESPONSES)
def get_trip_availability(
    trip_id: str, user_id: int | None = Depends(optional_user_id), session: Session = Depends(get_session)
) -> Envelope[TripAvailabilityDTO]:
    """Computed remaining capacity per segment (AC10/AC11); never a reservation."""
    trip = trips_service.get_trip_by_public_id(session, trip_id)
    if not (
        marketplace_service.has_published_trip_offer(session, trip.id)
        or _can_see_full_trip(session, trip.driver_user_id, user_id)
    ):
        raise DomainError(ErrorCode.NOT_FOUND)
    return Envelope[TripAvailabilityDTO](data=availability_dto(session, trip))


# --- driver directions (ADR-0027, Q150) -----------------------------------------------------------------------


@router.post("/driver-directions", response_model=Envelope[DriverDirectionDTO], status_code=201, responses=ERROR_RESPONSES)
def create_driver_direction(
    body: DriverDirectionCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Q150: the driver names only "where from -> where to"; the server finds the road and keeps the direction.

    ``409 ROUTE_MISMATCH`` (``no_corridor_serves_direction``) is the product's "no ELCHI road here yet" answer.
    """
    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: direction_dto(
            session, trip_directions.create_direction(session, driver_user_id=user_id, data=body)
        ),
        success_status=201,
        resource_type="driver_direction",
    )


@router.get("/me/driver-directions", response_model=Envelope[list[DriverDirectionDTO]], responses=ERROR_RESPONSES)
def list_my_driver_directions(
    include_archived: bool = Query(default=False),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[DriverDirectionDTO]]:
    if Role.DRIVER not in identity_service.get_capabilities(session, user_id).roles:
        raise DomainError(ErrorCode.CAPABILITY_REQUIRED, details={"role": Role.DRIVER.value})
    rows = trip_directions.list_directions(session, user_id, include_archived=include_archived)
    return Envelope[list[DriverDirectionDTO]](data=[direction_dto(session, row) for row in rows])


@router.get("/driver-directions/{direction_id}", response_model=Envelope[DriverDirectionDTO], responses=ERROR_RESPONSES)
def get_driver_direction(
    direction_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[DriverDirectionDTO]:
    return Envelope[DriverDirectionDTO](
        data=direction_dto(session, trip_directions.get_owned_direction(session, direction_id, user_id))
    )


@router.patch("/driver-directions/{direction_id}", response_model=Envelope[DriverDirectionDTO], responses=ERROR_RESPONSES)
def patch_driver_direction(
    direction_id: str, body: DriverDirectionPatch, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[DriverDirectionDTO]:
    dto = run_versioned(
        session,
        lambda: direction_dto(
            session,
            trip_directions.patch_direction(session, direction_public_id_value=direction_id, actor_user_id=user_id, data=body),
        ),
    )
    return Envelope[DriverDirectionDTO](data=dto)


@router.get("/admin/driver-directions", response_model=Envelope[list[AdminDriverDirectionDTO]], responses=ERROR_RESPONSES)
def list_admin_driver_directions(
    driver_id: str | None = Query(default=None, max_length=64, description="usr_... - one driver's directions."),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[AdminDriverDirectionDTO]]:
    """ADR-0027: what a driver said they drive, for staff (read-only; ``ops.view``)."""
    identity_service.require_capability(identity_service.get_capabilities(session, user_id), Capability.OPS_VIEW)
    driver_user_id = identity_service.resolve_user_id(session, driver_id) if driver_id else None
    rows = trip_directions.list_directions_for_admin(session, driver_user_id=driver_user_id, limit=limit)
    return Envelope[list[AdminDriverDirectionDTO]](data=[direction_dto(session, row, admin=True) for row in rows])
