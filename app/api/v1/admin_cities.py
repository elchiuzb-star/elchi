from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import City, User
from app.schemas.city import CityCreate, CityUpdate
from app.services.city_service import city_to_dict, create_city, list_cities, update_city
from app.utils.api_response import error_response

router = APIRouter(prefix="/admin/cities")


@router.post("", response_model=None)
def create_city_endpoint(
    payload: CityCreate,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    city = create_city(db, payload, current_user)
    if isinstance(city, JSONResponse):
        return city
    return {"success": True, "data": city_to_dict(city), "message": "OK"}


@router.get("", response_model=None)
def get_admin_cities(
    search: str | None = None,
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_roles("operator", "admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    return {"success": True, "data": list_cities(db, search=search, is_active=is_active, page=page, limit=limit), "message": "OK"}


@router.get("/{city_id}", response_model=None)
def get_admin_city(
    city_id: int,
    current_user: User = Depends(require_roles("operator", "admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    city = db.get(City, city_id)
    if city is None:
        return error_response(status.HTTP_404_NOT_FOUND, "CITY_NOT_FOUND", "City not found")
    return {"success": True, "data": city_to_dict(city), "message": "OK"}


@router.patch("/{city_id}", response_model=None)
def update_city_endpoint(
    city_id: int,
    payload: CityUpdate,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    city = update_city(db, city_id, payload, current_user)
    if isinstance(city, JSONResponse):
        return city
    return {"success": True, "data": city_to_dict(city), "message": "OK"}
