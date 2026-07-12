from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.geo import (
    GeoGeocodeRequest,
    GeoReverseGeocodeRequest,
    GeoValidateLocationRequest,
)
from app.services import google_maps_service
from app.services.geo_service import nearest_district, validate_location_payload
from app.utils.api_response import error_response

router = APIRouter(prefix="/geo")


@router.post("/validate-location", response_model=None)
def validate_location(payload: GeoValidateLocationRequest, db: Session = Depends(get_db)) -> dict:
    data = validate_location_payload(
        db,
        lat=payload.lat,
        lng=payload.lng,
        region_id=payload.region_id,
        district_id=payload.district_id,
        label="marker",
    )
    return {"success": True, "data": data, "message": data["message"]}


@router.post("/reverse-geocode", response_model=None)
def reverse_geocode(payload: GeoReverseGeocodeRequest, db: Session = Depends(get_db)) -> dict:
    """Resolve a map marker (lat/lng) to a human-readable address via Google Maps.

    Falls back to the nearest known district when Google is not configured/available.
    """
    lat = float(payload.lat)
    lng = float(payload.lng)
    google_result = google_maps_service.reverse_geocode(lat, lng, language=payload.language)
    detected, _distance = nearest_district(db, lat, lng)
    if google_result is not None:
        data = {
            **google_result,
            "provider": "google",
            "detected_region_id": detected.city_id if detected else None,
            "detected_district_id": detected.id if detected else None,
        }
        return {"success": True, "data": data, "message": "OK"}

    fallback_address = detected.name_uz if detected else f"{lat:.6f}, {lng:.6f}"
    data = {
        "formatted_address": fallback_address,
        "lat": lat,
        "lng": lng,
        "region": None,
        "district": detected.name_uz if detected else None,
        "place_id": None,
        "provider": "local",
        "detected_region_id": detected.city_id if detected else None,
        "detected_district_id": detected.id if detected else None,
    }
    return {"success": True, "data": data, "message": "OK"}


@router.post("/geocode", response_model=None)
def geocode(payload: GeoGeocodeRequest):
    """Resolve a typed address to coordinates via Google Maps."""
    result = google_maps_service.geocode(payload.address, language=payload.language)
    if result is None:
        return error_response(404, "GEOCODE_FAILED", "Manzil bo'yicha koordinata topilmadi")
    return {"success": True, "data": {**result, "provider": "google"}, "message": "OK"}
