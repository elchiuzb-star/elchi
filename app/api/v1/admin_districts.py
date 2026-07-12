from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.schemas.district import DistrictCreate, DistrictUpdate
from app.services.city_service import create_district, district_to_dict, list_districts, update_district

router = APIRouter(prefix="/admin/districts")


@router.post("", response_model=None)
def create_district_endpoint(
    payload: DistrictCreate,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    district = create_district(db, payload, current_user)
    if isinstance(district, JSONResponse):
        return district
    return {"success": True, "data": district_to_dict(district), "message": "OK"}


@router.get("", response_model=None)
def get_admin_districts(
    city_id: int | None = None,
    search: str | None = None,
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_roles("operator", "admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "success": True,
        "data": list_districts(db, city_id=city_id, search=search, is_active=is_active, page=page, limit=limit),
        "message": "OK",
    }


@router.patch("/{district_id}", response_model=None)
def update_district_endpoint(
    district_id: int,
    payload: DistrictUpdate,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    district = update_district(db, district_id, payload, current_user)
    if isinstance(district, JSONResponse):
        return district
    return {"success": True, "data": district_to_dict(district), "message": "OK"}
