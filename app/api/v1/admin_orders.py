from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import User
from app.schemas.admin_order import AdminAssignDriver, AdminOrderCancel, AdminOrderStatusUpdate
from app.services.admin_order_service import (
    assign_driver_manually,
    cancel_order_manually,
    get_admin_order_detail,
    list_admin_orders,
    update_admin_order_status,
)
from app.utils.api_response import error_response

router = APIRouter(prefix="/admin/orders")
bearer_scheme = HTTPBearer(auto_error=False)
ADMIN_ORDER_ROLES = {"operator", "admin", "super_admin"}


def get_current_admin_order_user(
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
    if user.role not in ADMIN_ORDER_ROLES:
        return error_response(403, "FORBIDDEN", "Operator or admin role required")
    return user


# Forcing a status, assigning a driver or cancelling changes money/state, so it
# is admin+ only. Operators keep read access to the list and detail endpoints.
ADMIN_ORDER_MUTATION_ROLES = {"admin", "super_admin"}


def get_current_admin_order_manager(
    current_user: User | JSONResponse = Depends(get_current_admin_order_user),
) -> User | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    if current_user.role not in ADMIN_ORDER_MUTATION_ROLES:
        return error_response(403, "FORBIDDEN", "Admin role required")
    return current_user


@router.get("", response_model=None)
def get_admin_orders(
    status: str | None = None,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    client_phone: str | None = None,
    driver_phone: str | None = None,
    order_number: str | None = None,
    payment_status: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User | JSONResponse = Depends(get_current_admin_order_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = list_admin_orders(
        db,
        status,
        from_city_id,
        to_city_id,
        client_phone,
        driver_phone,
        order_number,
        payment_status,
        created_from,
        created_to,
        page,
        limit,
    )
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "OK"}


@router.get("/{order_id}", response_model=None)
def get_admin_order(
    order_id: int,
    current_user: User | JSONResponse = Depends(get_current_admin_order_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = get_admin_order_detail(db, order_id)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "OK"}


@router.patch("/{order_id}/status", response_model=None)
def patch_admin_order_status(
    order_id: int,
    payload: AdminOrderStatusUpdate,
    current_user: User | JSONResponse = Depends(get_current_admin_order_manager),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = update_admin_order_status(db, current_user, order_id, payload)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "Order status updated"}


@router.post("/{order_id}/assign-driver", response_model=None)
def post_admin_assign_driver(
    order_id: int,
    payload: AdminAssignDriver,
    current_user: User | JSONResponse = Depends(get_current_admin_order_manager),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = assign_driver_manually(db, current_user, order_id, payload)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "Driver assigned"}


@router.post("/{order_id}/cancel", response_model=None)
def post_admin_cancel_order(
    order_id: int,
    payload: AdminOrderCancel,
    current_user: User | JSONResponse = Depends(get_current_admin_order_manager),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    data = cancel_order_manually(db, current_user, order_id, payload)
    if isinstance(data, JSONResponse):
        return data
    return {"success": True, "data": data, "message": "Order cancelled"}
