from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import Order, User
from app.schemas.dispute import DisputeCreate, DisputeUpdate
from app.services.dispute_service import (
    get_admin_dispute_detail,
    list_disputes,
    open_dispute,
    update_dispute,
)
from app.utils.api_response import error_response

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)
ADMIN_ROLES = {"operator", "admin", "super_admin"}
DISPUTE_ROLES = {"client", "driver", *ADMIN_ROLES}


def get_current_dispute_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | JSONResponse:
    if credentials is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    payload = verify_token(credentials.credentials)
    if payload is None or payload.get("type") != "access" or payload.get("sub") is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    if user.status != "active":
        return error_response(403, "FORBIDDEN", "User account is not active")
    if user.role not in DISPUTE_ROLES:
        return error_response(403, "FORBIDDEN", "Insufficient permissions")
    return user


def get_current_admin_dispute_user(
    current_user: User | JSONResponse = Depends(get_current_dispute_user),
) -> User | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    if current_user.role not in ADMIN_ROLES:
        return error_response(403, "FORBIDDEN", "Insufficient permissions")
    return current_user


@router.post("/orders/{order_id}/disputes", response_model=None)
def open_dispute_endpoint(
    order_id: int,
    payload: DisputeCreate,
    current_user: User | JSONResponse = Depends(get_current_dispute_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    dispute = open_dispute(db, current_user, order_id, payload)
    if isinstance(dispute, JSONResponse):
        return dispute
    order = db.get(Order, dispute.order_id)
    return {
        "success": True,
        "data": {
            "dispute_id": dispute.id,
            "order_id": dispute.order_id,
            "order_number": order.order_number if order else None,
            "reason": dispute.reason,
            "status": dispute.status,
            "previous_order_status": dispute.previous_order_status,
            "order_status": order.status if order else None,
            "created_at": dispute.created_at,
        },
        "message": "Dispute opened",
    }


@router.get("/disputes", response_model=None)
def get_my_disputes(
    status: str | None = None,
    reason: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User | JSONResponse = Depends(get_current_dispute_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = list_disputes(db, current_user, status, reason, page, limit)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "OK"}


@router.get("/admin/disputes", response_model=None)
def get_admin_disputes(
    status: str | None = None,
    reason: str | None = None,
    order_id: int | None = None,
    opened_by: int | None = None,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User | JSONResponse = Depends(get_current_admin_dispute_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = list_disputes(
        db,
        current_user,
        status,
        reason,
        page,
        limit,
        admin=True,
        order_id=order_id,
        opened_by=opened_by,
        from_city_id=from_city_id,
        to_city_id=to_city_id,
    )
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "OK"}


@router.get("/admin/disputes/{dispute_id}", response_model=None)
def get_admin_dispute_detail_endpoint(
    dispute_id: int,
    current_user: User | JSONResponse = Depends(get_current_admin_dispute_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = get_admin_dispute_detail(db, dispute_id)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "OK"}


@router.patch("/admin/disputes/{dispute_id}", response_model=None)
def update_admin_dispute_endpoint(
    dispute_id: int,
    payload: DisputeUpdate,
    current_user: User | JSONResponse = Depends(get_current_admin_dispute_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = update_dispute(db, current_user, dispute_id, payload)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "Dispute updated"}
