from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models import City, RouteTariff, User
from app.schemas.city import RouteTariffCreate, RouteTariffUpdate
from app.services.city_service import create_tariff, list_tariffs, tariff_to_dict, update_tariff
from app.utils.api_response import error_response

router = APIRouter(prefix="/admin/route-tariffs")


@router.post("", response_model=None)
def create_route_tariff_endpoint(
    payload: RouteTariffCreate,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    tariff = create_tariff(db, payload, current_user)
    if isinstance(tariff, JSONResponse):
        return tariff
    from_city = db.get(City, tariff.from_city_id)
    to_city = db.get(City, tariff.to_city_id)
    return {"success": True, "data": tariff_to_dict(tariff, from_city, to_city), "message": "OK"}


@router.get("", response_model=None)
def get_admin_route_tariffs(
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_roles("operator", "admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    data = list_tariffs(db, from_city_id=from_city_id, to_city_id=to_city_id, is_active=is_active, page=page, limit=limit)
    return {"success": True, "data": data, "message": "OK"}


@router.get("/{tariff_id}", response_model=None)
def get_admin_route_tariff(
    tariff_id: int,
    current_user: User = Depends(require_roles("operator", "admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    tariff = db.get(RouteTariff, tariff_id)
    if tariff is None:
        return error_response(status.HTTP_404_NOT_FOUND, "ROUTE_TARIFF_NOT_FOUND", "Route tariff not found")
    from_city = db.get(City, tariff.from_city_id)
    to_city = db.get(City, tariff.to_city_id)
    return {"success": True, "data": tariff_to_dict(tariff, from_city, to_city), "message": "OK"}


@router.patch("/{tariff_id}", response_model=None)
def update_route_tariff_endpoint(
    tariff_id: int,
    payload: RouteTariffUpdate,
    current_user: User = Depends(require_roles("admin", "super_admin")),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    tariff = update_tariff(db, tariff_id, payload, current_user)
    if isinstance(tariff, JSONResponse):
        return tariff
    from_city = db.get(City, tariff.from_city_id)
    to_city = db.get(City, tariff.to_city_id)
    return {"success": True, "data": tariff_to_dict(tariff, from_city, to_city), "message": "OK"}
