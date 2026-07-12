from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import User
from app.services.notification_service import list_notifications, mark_all_notifications_read, mark_notification_read
from app.utils.api_response import error_response

router = APIRouter(prefix="/notifications")
bearer_scheme = HTTPBearer(auto_error=False)
ALLOWED_NOTIFICATION_ROLES = {"client", "driver", "operator", "admin", "super_admin"}


def get_current_notification_user(
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
    if user.role not in ALLOWED_NOTIFICATION_ROLES:
        return error_response(403, "FORBIDDEN", "Notification access requires an active user")
    return user


@router.get("", response_model=None)
def get_notifications(
    is_read: bool | None = None,
    type: str | None = None,  # noqa: A002
    order_id: int | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User | JSONResponse = Depends(get_current_notification_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = list_notifications(db, current_user, is_read, type, order_id, page, limit)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.patch("/read-all", response_model=None)
def patch_notifications_read_all(
    current_user: User | JSONResponse = Depends(get_current_notification_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = mark_all_notifications_read(db, current_user)
    return {"success": True, "data": result, "message": "All notifications marked as read"}


@router.patch("/{notification_id}/read", response_model=None)
def patch_notification_read(
    notification_id: int,
    current_user: User | JSONResponse = Depends(get_current_notification_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = mark_notification_read(db, current_user, notification_id)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "Notification marked as read"}
