from __future__ import annotations

from decimal import Decimal
from math import asin, cos, radians, sin, sqrt
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import District
from app.utils.api_response import error_response

DISTRICT_CENTER_MAX_KM = 75.0


def _as_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))


def nearest_district(db: Session, lat: float, lng: float) -> tuple[District | None, float | None]:
    districts = db.scalars(
        select(District).where(
            District.is_active == True,  # noqa: E712
            District.center_lat.is_not(None),
            District.center_lng.is_not(None),
        )
    )
    best: tuple[District | None, float | None] = (None, None)
    for district in districts:
        center_lat = _as_float(district.center_lat)
        center_lng = _as_float(district.center_lng)
        if center_lat is None or center_lng is None:
            continue
        distance = distance_km(lat, lng, center_lat, center_lng)
        if best[1] is None or distance < best[1]:
            best = (district, distance)
    return best


def validate_location_payload(
    db: Session,
    *,
    lat: Decimal | float,
    lng: Decimal | float,
    region_id: int,
    district_id: int | None,
    label: str,
) -> dict[str, Any]:
    lat_float = float(lat)
    lng_float = float(lng)
    detected, _detected_distance = nearest_district(db, lat_float, lng_float)
    selected = db.get(District, district_id) if district_id is not None else None

    if district_id is None:
        return {
            "valid": True,
            "detected_region_id": detected.city_id if detected else None,
            "detected_district_id": detected.id if detected else None,
            "message": "OK",
        }

    if selected is None or selected.city_id != region_id:
        return {
            "valid": False,
            "detected_region_id": detected.city_id if detected else None,
            "detected_district_id": detected.id if detected else None,
            "message": "Tuman tanlangan shaharga tegishli emas",
        }

    selected_lat = _as_float(selected.center_lat)
    selected_lng = _as_float(selected.center_lng)
    if selected_lat is None or selected_lng is None:
        return {
            "valid": False,
            "detected_region_id": detected.city_id if detected else None,
            "detected_district_id": detected.id if detected else None,
            "message": "Bu tuman uchun default koordinata topilmadi",
        }

    distance_to_selected = distance_km(lat_float, lng_float, selected_lat, selected_lng)
    if distance_to_selected > DISTRICT_CENTER_MAX_KM:
        message = (
            "Pickup marker tanlangan tumandan tashqarida. Iltimos, tumanni o'zgartiring yoki marker joyini to'g'rilang."
            if label == "pickup"
            else "Delivery marker tanlangan tumandan tashqarida. Iltimos, tumanni o'zgartiring yoki marker joyini to'g'rilang."
        )
        if detected is not None and detected.city_id != region_id:
            message = f"Tanlangan {label} koordinata tanlangan viloyatga tegishli emas."
        return {
            "valid": False,
            "detected_region_id": detected.city_id if detected else None,
            "detected_district_id": detected.id if detected else None,
            "message": message,
        }

    return {
        "valid": True,
        "detected_region_id": detected.city_id if detected else None,
        "detected_district_id": detected.id if detected else None,
        "message": "OK",
    }


def validate_order_location_or_error(
    db: Session,
    *,
    lat: Decimal | None,
    lng: Decimal | None,
    region_id: int,
    district_id: int | None,
    label: str,
) -> JSONResponse | None:
    if lat is None and lng is None:
        return None
    if lat is None or lng is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Coordinate pair is incomplete")
    result = validate_location_payload(db, lat=lat, lng=lng, region_id=region_id, district_id=district_id, label=label)
    if result["valid"]:
        return None
    return error_response(status.HTTP_400_BAD_REQUEST, "LOCATION_MISMATCH", result["message"], result)
