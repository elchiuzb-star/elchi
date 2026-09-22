"""API v2 tracking router (K1-K9). Mounted by the integrator (``app/api/v2/router.py``).

Every HTTP endpoint declares ``response_model``. K1/K3/K5 go through the shared idempotent runner; K2 has no
Idempotency-Key (``(session, seq)`` dedup) and returns its ACK only after the commit; GETs that write an audit row
(staff K4, K9) commit through ``run_versioned``. K8 is the WebSocket in ``ws.py``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v2.web import ERROR_RESPONSES, current_user_id, get_session, run_command, run_versioned
from app.contracts.dto import BookingTrackingDTO, Envelope, PointsBatchAck, PointsBatchIn, PublicTrackingDTO
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.idempotency import IDEMPOTENT_REPLAY_HEADER
from app.modules.platform.service import domain_error_body
from app.modules.tracking import service as tracking_service
from app.modules.tracking.config import public_tracking_url
from app.modules.tracking.schemas import (
    EmptyDTO,
    TrackingGrantCreate,
    TrackingGrantDTO,
    TrackingSessionCreate,
    TrackingSessionDTO,
    TripTrackingAdminDTO,
)
from app.modules.tracking.ws import tracking_websocket

router = APIRouter(tags=["v2 Tracking"])

NO_STORE_HEADERS = {"Cache-Control": "no-store"}
PUBLIC_HEADERS = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "X-Robots-Tag": "noindex"}


@router.post("/tracking/sessions", response_model=Envelope[TrackingSessionDTO], status_code=201, responses=ERROR_RESPONSES)
def create_tracking_session(
    body: TrackingSessionCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> TrackingSessionDTO:
        row = tracking_service.create_session(
            session, actor_user_id=user_id, trip_public_id=body.trip_id, device_id=body.device_id,
            platform=body.platform, app_version=body.app_version,
        )
        return tracking_service.session_dto(row)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       success_status=201, resource_type="tracking_session")


@router.post("/tracking/sessions/{session_id}/points:batch", response_model=Envelope[PointsBatchAck], responses=ERROR_RESPONSES)
def ingest_tracking_points(
    session_id: str,
    body: PointsBatchIn,
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[PointsBatchAck]:
    ack = run_versioned(
        session,
        lambda: tracking_service.ingest_points(session, actor_user_id=user_id, session_public_id_value=session_id, batch=body),
    )
    return Envelope[PointsBatchAck](data=ack)  # built before the commit, returned after it (§10.4)


@router.post("/tracking/sessions/{session_id}/close", response_model=Envelope[TrackingSessionDTO], responses=ERROR_RESPONSES)
def close_tracking_session(
    session_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> TrackingSessionDTO:
        row = tracking_service.close_session(session, actor_user_id=user_id, session_public_id_value=session_id)
        return tracking_service.session_dto(row)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=None, handler=handler,
                       resource_type="tracking_session")


@router.get("/bookings/{booking_id}/tracking", response_model=Envelope[BookingTrackingDTO], responses=ERROR_RESPONSES)
def get_booking_tracking(
    booking_id: str,
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    dto = run_versioned(
        session,
        lambda: tracking_service.booking_tracking(session, booking_public_id_value=booking_id, viewer_user_id=user_id),
    )
    return JSONResponse(Envelope[BookingTrackingDTO](data=dto).model_dump(mode="json"), headers=NO_STORE_HEADERS)


@router.post("/bookings/{booking_id}/tracking-grants", response_model=Envelope[TrackingGrantDTO], status_code=201,
             responses=ERROR_RESPONSES)
def create_tracking_grant(
    booking_id: str,
    body: TrackingGrantCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    issued: dict[str, str] = {}

    def handler() -> TrackingGrantDTO:
        grant, token = tracking_service.create_grant(
            session, actor_user_id=user_id, booking_public_id_value=booking_id, scope=body.scope, ttl_minutes=body.ttl_minutes,
        )
        issued["token"] = token  # a deadlock retry overwrites it with the attempt that commits
        return tracking_service.grant_dto(grant, url=None)  # the stored idempotent response never carries the token

    response = run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                           handler=handler, success_status=201, resource_type="tracking_grant")
    if response.status_code == 201 and IDEMPOTENT_REPLAY_HEADER not in response.headers and "token" in issued:
        payload = json.loads(response.body)
        payload["data"]["url"] = public_tracking_url(issued["token"])
        return JSONResponse(status_code=201, content=payload, headers=NO_STORE_HEADERS)
    return response


@router.delete("/bookings/{booking_id}/tracking-grants/{grant_id}", response_model=Envelope[EmptyDTO], responses=ERROR_RESPONSES)
def revoke_tracking_grant(
    booking_id: str,
    grant_id: str,
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[EmptyDTO]:
    run_versioned(
        session,
        lambda: tracking_service.revoke_grant(session, actor_user_id=user_id, booking_public_id_value=booking_id,
                                              grant_public_id_value=grant_id),
    )
    return Envelope[EmptyDTO](data=EmptyDTO())


@router.get("/public/tracking/{token}", response_model=Envelope[PublicTrackingDTO], responses=ERROR_RESPONSES)
def get_public_tracking(token: str, request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    """K7: no auth; every failure is the same 404; no referrer, no caching, no analytics."""
    try:
        dto = tracking_service.public_tracking(session, token=token)
    except DomainError as exc:
        session.rollback()
        error = exc if exc.code is not ErrorCode.NOT_FOUND else DomainError(ErrorCode.NOT_FOUND)
        return JSONResponse(status_code=error.http_status, content=domain_error_body(error, request.headers.get("X-Request-ID")),
                            headers=PUBLIC_HEADERS)
    session.rollback()
    return JSONResponse(Envelope[PublicTrackingDTO](data=dto).model_dump(mode="json"), headers=PUBLIC_HEADERS)


@router.get("/admin/trips/{trip_id}/tracking", response_model=Envelope[TripTrackingAdminDTO], responses=ERROR_RESPONSES)
def get_admin_trip_tracking(
    trip_id: str,
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    dto = run_versioned(session, lambda: tracking_service.admin_trip_tracking(session, actor_user_id=user_id, trip_public_id=trip_id))
    return JSONResponse(Envelope[TripTrackingAdminDTO](data=dto).model_dump(mode="json"), headers=NO_STORE_HEADERS)


router.add_api_websocket_route("/ws", tracking_websocket)
