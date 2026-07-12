from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import User
from app.services.admin_audit_log_service import get_audit_log_detail, list_audit_logs
from app.utils.api_response import error_response

router = APIRouter(prefix="/admin/audit-logs")
bearer_scheme = HTTPBearer(auto_error=False)
AUDIT_LOG_ROLES = {"admin", "super_admin"}


def get_current_audit_admin(
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
    if user.role not in AUDIT_LOG_ROLES:
        return error_response(403, "FORBIDDEN", "Admin or super admin role required")
    return user


@router.get("", response_model=None)
def get_admin_audit_logs(
    actor_id: int | None = None,
    actor_role: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    search: str | None = None,
    page: int = 1,
    limit: int = 20,
    current_user: User | JSONResponse = Depends(get_current_audit_admin),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = list_audit_logs(
        db,
        actor_id,
        actor_role,
        entity_type,
        entity_id,
        action,
        created_from,
        created_to,
        search,
        page,
        limit,
    )
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}


@router.get("/{audit_log_id}", response_model=None)
def get_admin_audit_log(
    audit_log_id: int,
    current_user: User | JSONResponse = Depends(get_current_audit_admin),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    result = get_audit_log_detail(db, audit_log_id)
    if isinstance(result, JSONResponse):
        return result
    return {"success": True, "data": result, "message": "OK"}
