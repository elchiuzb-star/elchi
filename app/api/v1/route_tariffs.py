from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import RouteTariff, User
from app.services.city_service import get_active_city_pair, tariff_to_dict

router = APIRouter(prefix="/route-tariffs")


@router.get("/suggested-price", response_model=None)
def get_suggested_price(
    from_city_id: int = Query(...),
    to_city_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    cities = get_active_city_pair(db, from_city_id, to_city_id)
    if isinstance(cities, JSONResponse):
        return cities

    tariff = db.scalar(
        select(RouteTariff).where(
            RouteTariff.from_city_id == from_city_id,
            RouteTariff.to_city_id == to_city_id,
            RouteTariff.is_active == True,  # noqa: E712
        )
    )
    from_city, to_city = cities
    if tariff is None:
        return {
            "success": True,
            "data": {
                "from_city_id": from_city_id,
                "to_city_id": to_city_id,
                "from_city": {
                    "id": from_city.id,
                    "name_uz": from_city.name_uz,
                    "name_ru": from_city.name_ru,
                    "region": from_city.region,
                },
                "to_city": {
                    "id": to_city.id,
                    "name_uz": to_city.name_uz,
                    "name_ru": to_city.name_ru,
                    "region": to_city.region,
                },
                "suggested_price": None,
                "min_price": None,
                "max_price": None,
                "currency": "UZS",
                "is_active": False,
            },
            "message": "No active tariff found for this route",
        }

    return {"success": True, "data": tariff_to_dict(tariff, from_city, to_city), "message": "OK"}
