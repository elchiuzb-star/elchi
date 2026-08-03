from math import ceil

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_, select

from app.api.deps import get_current_user, require_operator_or_admin, require_super_admin
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    AdminUserCreate,
    AuthProfileUpdate,
    AuthRequestOtp,
    AuthUser,
    AuthVerifyOtp,
    LogoutRequest,
    LogoutResponse,
    OtpRequestedResponse,
    RefreshTokenRequest,
    StaffLogin,
    TokenResponse,
)
from app.services.auth_service import (
    build_token_response,
    create_admin_user,
    login_staff_with_password,
    logout_refresh_session,
    request_otp,
    verify_otp,
)
from app.utils.api_response import error_response

router = APIRouter(prefix="/auth")
admin_router = APIRouter(prefix="/admin/users")


def client_ip(request: Request) -> str | None:
    """Real client IP. Behind a reverse proxy the direct peer is the proxy, so
    prefer the left-most X-Forwarded-For entry it sets."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/request-otp", response_model=OtpRequestedResponse)
def request_otp_endpoint(payload: AuthRequestOtp, request: Request, db: Session = Depends(get_db)) -> OtpRequestedResponse:
    result = request_otp(db, phone=payload.phone, role=payload.role, ip_address=client_ip(request))
    if hasattr(result, "status_code"):
        return result
    return OtpRequestedResponse(
        success=True,
        message="OTP sent",
        dev_otp=result.get("dev_otp"),
        data=result,
    )


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp_endpoint(payload: AuthVerifyOtp, db: Session = Depends(get_db)) -> dict:
    user = verify_otp(db, phone=payload.phone, otp=payload.otp_value, role=payload.role)
    if hasattr(user, "status_code"):
        return user
    return build_token_response(db, user)


@router.post("/staff-login", response_model=TokenResponse)
def staff_login_endpoint(payload: StaffLogin, db: Session = Depends(get_db)) -> dict:
    """Username + password sign-in for operator/admin/super_admin."""
    user = login_staff_with_password(db, username=payload.username, password=payload.password)
    if hasattr(user, "status_code"):
        return user
    return build_token_response(db, user)


@router.post("/refresh", response_model=TokenResponse)
def refresh_endpoint(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> dict:
    from app.services.auth_service import refresh_tokens

    result = refresh_tokens(db, refresh_token=payload.refresh_token)
    return result


@router.post("/logout", response_model=LogoutResponse)
def logout_endpoint(
    payload: LogoutRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogoutResponse:
    result = logout_refresh_session(db, payload.refresh_token if payload else None)
    if hasattr(result, "status_code"):
        return result
    return LogoutResponse(success=True, message="Logged out.")


@router.get("/me", response_model=AuthUser)
def me_endpoint(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=None)
def update_me_endpoint(
    payload: AuthProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if current_user.role not in {"operator", "admin", "super_admin"}:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Only staff users can update profile here")
    full_name = payload.full_name.strip() if payload.full_name else None
    current_user.full_name = full_name or None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return {"success": True, "data": current_user, "message": "Profile updated"}


@admin_router.post("", response_model=AuthUser)
def create_admin_user_endpoint(
    payload: AdminUserCreate,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> User:
    user = create_admin_user(db, current_user, payload)
    if hasattr(user, "status_code"):
        return user
    return user


def staff_user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "phone": user.phone,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
        "is_phone_verified": user.is_phone_verified,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


@admin_router.get("", response_model=None)
def list_admin_users_endpoint(
    search: str | None = None,
    role: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    is_phone_verified: bool | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(User).where(User.role.in_(["operator", "admin", "super_admin"]))
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.phone.ilike(q), User.full_name.ilike(q)))
    if role:
        stmt = stmt.where(User.role == role)
    if status_filter:
        stmt = stmt.where(User.status == status_filter)
    if is_phone_verified is not None:
        stmt = stmt.where(User.is_phone_verified == is_phone_verified)
    if created_from:
        stmt = stmt.where(func.date(User.created_at) >= created_from)
    if created_to:
        stmt = stmt.where(func.date(User.created_at) <= created_to)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    safe_limit = max(1, min(limit, 100))
    offset = (page - 1) * safe_limit
    users = list(db.scalars(stmt.order_by(User.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "success": True,
        "data": {
            "items": [staff_user_to_dict(item) for item in users],
            "pagination": {
                "page": page,
                "limit": safe_limit,
                "total": total,
                "total_pages": ceil(total / safe_limit) if total else 0,
            },
        },
        "message": "OK",
    }


@admin_router.get("/{user_id}", response_model=None)
def get_admin_user_endpoint(
    user_id: int,
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    user = db.get(User, user_id)
    if user is None or user.role not in {"operator", "admin", "super_admin"}:
        return error_response(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Staff user not found")
    return {"success": True, "data": staff_user_to_dict(user), "message": "OK"}


@admin_router.patch("/{user_id}", response_model=None)
def update_admin_user_endpoint(
    user_id: int,
    payload: dict,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    user = db.get(User, user_id)
    if user is None or user.role not in {"operator", "admin", "super_admin"}:
        return error_response(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Staff user not found")
    if user.role == "super_admin" and user.id != current_user.id:
        return error_response(status.HTTP_400_BAD_REQUEST, "ROLE_NOT_ALLOWED", "Super admin users cannot be edited here")
    if "role" in payload and payload["role"] is not None:
        if payload["role"] not in {"operator", "admin"}:
            return error_response(status.HTTP_400_BAD_REQUEST, "ROLE_NOT_ALLOWED", "Only admin or operator role is allowed")
        if user.role != "super_admin":
            user.role = payload["role"]
    if "status" in payload and payload["status"] is not None:
        if payload["status"] not in {"active", "blocked", "inactive"}:
            return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid user status")
        user.status = payload["status"]
    if "full_name" in payload:
        user.full_name = payload["full_name"] or None
    db.commit()
    db.refresh(user)
    return {"success": True, "data": staff_user_to_dict(user), "message": "Staff user updated"}


@admin_router.post("/{user_id}/block", response_model=None)
def block_admin_user_endpoint(
    user_id: int,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    user = db.get(User, user_id)
    if user is None or user.role not in {"operator", "admin"}:
        return error_response(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Staff user not found")
    user.status = "blocked"
    db.commit()
    db.refresh(user)
    return {"success": True, "data": staff_user_to_dict(user), "message": "Staff user blocked"}


@admin_router.post("/{user_id}/unblock", response_model=None)
def unblock_admin_user_endpoint(
    user_id: int,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    user = db.get(User, user_id)
    if user is None or user.role not in {"operator", "admin"}:
        return error_response(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Staff user not found")
    user.status = "active"
    db.commit()
    db.refresh(user)
    return {"success": True, "data": staff_user_to_dict(user), "message": "Staff user unblocked"}
