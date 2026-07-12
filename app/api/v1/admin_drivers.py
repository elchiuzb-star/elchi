from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import User
from app.schemas.admin_driver import (
    AdminDriverApprove,
    AdminDriverBlock,
    AdminDriverReject,
    AdminDriverVehicleUpdate,
)
from app.services.admin_driver_service import (
    ADMIN_DRIVER_MUTATION_ROLES,
    ADMIN_DRIVER_VIEW_ROLES,
    approve_driver,
    block_driver,
    get_admin_driver_detail,
    list_admin_drivers,
    reject_driver,
    update_driver_vehicle,
)
from app.utils.api_response import error_response

router = APIRouter(prefix="/admin/drivers")
bearer_scheme = HTTPBearer(auto_error=False)


def authenticated_user(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> User | JSONResponse:
    if credentials is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    payload = verify_token(credentials.credentials)
    if payload is None or payload.get("type") != "access" or payload.get("sub") is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        return error_response(401, "UNAUTHORIZED", "Authentication required")
    return user


def get_current_admin_driver_view_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | JSONResponse:
    user = authenticated_user(credentials, db)
    if isinstance(user, JSONResponse):
        return user
    if user.status != "active":
        return error_response(403, "FORBIDDEN", "User account is not active")
    if user.role not in ADMIN_DRIVER_VIEW_ROLES:
        return error_response(403, "FORBIDDEN", "Admin access required")
    return user


def get_current_admin_driver_mutation_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | JSONResponse:
    user = authenticated_user(credentials, db)
    if isinstance(user, JSONResponse):
        return user
    if user.status != "active":
        return error_response(403, "FORBIDDEN", "User account is not active")
    if user.role == "operator":
        return error_response(403, "FORBIDDEN", "Only admin or super_admin can perform driver verification actions")
    if user.role not in ADMIN_DRIVER_MUTATION_ROLES:
        return error_response(403, "FORBIDDEN", "Admin access required")
    return user


def get_current_admin_driver_vehicle_editor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | JSONResponse:
    """Vehicle edits are allowed for operators as well as admins/super_admins."""
    user = authenticated_user(credentials, db)
    if isinstance(user, JSONResponse):
        return user
    if user.status != "active":
        return error_response(403, "FORBIDDEN", "User account is not active")
    if user.role not in ADMIN_DRIVER_VIEW_ROLES:
        return error_response(403, "FORBIDDEN", "Admin or operator access required")
    return user


@router.get("", response_model=None)
def get_admin_drivers(
    verification_status: str | None = None,
    is_available: bool | None = None,
    search: str | None = None,
    phone: str | None = None,
    plate_number: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User | JSONResponse = Depends(get_current_admin_driver_view_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = list_admin_drivers(db, verification_status, is_available, search, phone, plate_number, page, limit)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.get("/{driver_id}", response_model=None)
def get_admin_driver(
    driver_id: int,
    current_user: User | JSONResponse = Depends(get_current_admin_driver_view_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = get_admin_driver_detail(db, driver_id)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.patch("/{driver_id}/vehicle", response_model=None)
def patch_admin_driver_vehicle(
    driver_id: int,
    payload: AdminDriverVehicleUpdate,
    current_user: User | JSONResponse = Depends(get_current_admin_driver_vehicle_editor),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = update_driver_vehicle(db, current_user, driver_id, payload)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "Driver vehicle updated"}


@router.post("/{driver_id}/approve", response_model=None)
def post_admin_driver_approve(
    driver_id: int,
    payload: AdminDriverApprove,
    current_user: User | JSONResponse = Depends(get_current_admin_driver_mutation_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = approve_driver(db, current_user, driver_id, payload)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "Driver approved"}


@router.post("/{driver_id}/reject", response_model=None)
def post_admin_driver_reject(
    driver_id: int,
    payload: AdminDriverReject,
    current_user: User | JSONResponse = Depends(get_current_admin_driver_mutation_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = reject_driver(db, current_user, driver_id, payload)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "Driver rejected"}


@router.post("/{driver_id}/block", response_model=None)
def post_admin_driver_block(
    driver_id: int,
    payload: AdminDriverBlock,
    current_user: User | JSONResponse = Depends(get_current_admin_driver_mutation_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = block_driver(db, current_user, driver_id, payload)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "Driver blocked"}
