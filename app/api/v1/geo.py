from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.geo import (
    GeoGeocodeRequest,
    GeoResolvePlaceRequest,
    GeoReverseGeocodeRequest,
    GeoSuggestRequest,
    GeoValidateLocationRequest,
)
from app.services import yandex_maps_service as maps_service
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
    """Resolve a map marker (lat/lng) to a human-readable address via Yandex Maps.

    Falls back to the nearest known district when Yandex is not configured/available.
    """
    lat = float(payload.lat)
    lng = float(payload.lng)
    geo_result = maps_service.reverse_geocode(lat, lng, language=payload.language)
    detected, _distance = nearest_district(db, lat, lng)
    if geo_result is not None:
        data = {
            **geo_result,
            "provider": "yandex",
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
    """Resolve a typed address to coordinates via Yandex Maps.

    When the caller says which area it is searching from (`near_lat`/`near_lng`/`span_deg`), results
    inside that area are preferred - a search made after choosing Kasbi answers with Kasbi first.
    Both fields are optional and a request without them is unchanged, so the v1 contract holds.
    """
    near = (
        (float(payload.near_lat), float(payload.near_lng))
        if payload.near_lat is not None and payload.near_lng is not None
        else None
    )
    result = maps_service.geocode(
        payload.address,
        language=payload.language,
        near=near,
        span_deg=float(payload.span_deg) if payload.span_deg is not None else None,
    )
    if result is None:
        return error_response(404, "GEOCODE_FAILED", "Manzil bo'yicha koordinata topilmadi")
    return {"success": True, "data": {**result, "provider": "yandex"}, "message": "OK"}


@router.post("/suggest", response_model=None)
def suggest(payload: GeoSuggestRequest):
    """Place suggestions for typed text, ranked towards the area the person is searching from.

    This is what makes "10-sonli maktab" findable: the geocoder answers addresses, and a school is not
    an address. A suggestion carries no coordinate - only a `uri` that `/geo/resolve-place` turns into
    one, so nothing is geocoded until a place is actually picked.

    An unconfigured or unreachable provider returns an empty list rather than an error: the map is
    still there and the pin can still be dragged, which is the honest fallback.
    """
    near = (
        (float(payload.near_lat), float(payload.near_lng))
        if payload.near_lat is not None and payload.near_lng is not None
        else None
    )
    results = maps_service.suggest_places(
        payload.text,
        language=payload.language,
        near=near,
        span_deg=float(payload.span_deg) if payload.span_deg is not None else None,
        limit=payload.limit,
    )
    ranked = maps_service.rank_suggestions(results or [], district=payload.district)
    return {"success": True, "data": {"results": ranked}, "message": "OK"}


@router.post("/resolve-place", response_model=None)
def resolve_place(payload: GeoResolvePlaceRequest):
    """Coordinates for a suggestion picked from `/geo/suggest`."""
    result = maps_service.geocode_uri(payload.uri, language=payload.language)
    if result is None:
        return error_response(404, "GEOCODE_FAILED", "Bu joy bo'yicha koordinata topilmadi")
    return {"success": True, "data": {**result, "provider": "yandex"}, "message": "OK"}
