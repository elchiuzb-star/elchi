from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.city_service import list_cities, list_public_city_districts
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/cities")


@router.get("", response_model=None)
def get_cities(
    search: str | None = None,
    is_active: bool | None = True,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    return {"success": True, "data": list_cities(db, search=search, is_active=is_active, page=page, limit=limit), "message": "OK"}


@router.get("/{city_id}/districts", response_model=None)
def get_city_districts(
    city_id: int,
    search: str | None = None,
    is_active: bool | None = True,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    result = list_public_city_districts(db, city_id, search=search, is_active=is_active, page=page, limit=limit)
    if isinstance(result, JSONResponse):
        return result
    data, message = result
    return {"success": True, "data": data, "message": message or "OK"}
