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
from app.modules.trips import service as trips_service
from app.modules.trips.schemas import (
    AdminVehicleDTO,
    AdminVehicleStatus,
    TripAvailabilityDTO,
    TripCreate,
    TripDTO,
    TripPatch,
    TripPublicDTO,
    VehicleCreate,
    VehicleDTO,
    VehicleVerifyRequest,
)
from app.modules.trips.views import admin_vehicle_dtos, availability_dto, trip_dto, trip_public_dto, vehicle_dto

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
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[AdminVehicleDTO]]:
    """T3a: vehicles awaiting (or past) a staff decision, oldest first. Same capability as T3 verify."""
    scope = page_scope("GET /admin/vehicles", status=status)
    rows = trips_service.list_vehicles_for_review(
        session,
        actor_user_id=user_id,
        statuses=[status] if status else None,
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
