from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.db.session import get_db
from app.models import ClientProfile, User
from app.schemas.client import ClientProfileUpdate
from app.utils.api_response import error_response

router = APIRouter(prefix="/client/profile")
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_client(
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
    if user.role != "client":
        return error_response(403, "FORBIDDEN", "Client role required")
    return user


def get_or_create_client_profile(db: Session, user: User) -> ClientProfile:
    profile = db.scalar(select(ClientProfile).where(ClientProfile.user_id == user.id))
    if profile is None:
        profile = ClientProfile(user_id=user.id, full_name=user.full_name)
        db.add(profile)
        db.flush()
    return profile


def profile_to_dict(user: User, profile: ClientProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "user_id": user.id,
        "phone": user.phone,
        "full_name": profile.full_name or user.full_name,
        "role": user.role,
        "status": user.status,
        "is_phone_verified": user.is_phone_verified,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


@router.get("", response_model=None)
def get_client_profile(
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_client_profile(db, current_user)
    db.commit()
    db.refresh(profile)
    return {"success": True, "data": profile_to_dict(current_user, profile), "message": "OK"}


@router.patch("", response_model=None)
def update_client_profile(
    payload: ClientProfileUpdate,
    current_user: User | JSONResponse = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    if isinstance(current_user, JSONResponse):
        return current_user
    profile = get_or_create_client_profile(db, current_user)
    clean_name = payload.full_name.strip()
    if not clean_name:
        return error_response(400, "VALIDATION_ERROR", "full_name is required")
    profile.full_name = clean_name
    current_user.full_name = clean_name
    db.add_all([profile, current_user])
    db.commit()
    db.refresh(profile)
    db.refresh(current_user)
    return {"success": True, "data": profile_to_dict(current_user, profile), "message": "Client profile updated"}
