"""Server-side Google Maps Geocoding integration.

Wraps the Google Maps Geocoding API so the backend can:
  * reverse-geocode a lat/lng marker into a human-readable address, and
  * forward-geocode a typed address into coordinates.

Both helpers degrade gracefully: if no API key is configured (or Google returns
an error / the request fails) they return ``None`` instead of raising, so the
rest of the app keeps working with the local heuristics in ``geo_service``.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_REQUEST_TIMEOUT = 6.0

# Google address-component types mapped onto the fields we care about.
_REGION_TYPES = {"administrative_area_level_1"}
_DISTRICT_TYPES = {"administrative_area_level_2", "administrative_area_level_3", "sublocality", "locality"}


def is_configured() -> bool:
    return bool(settings.google_maps_api_key)


def _extract_components(result: dict[str, Any]) -> dict[str, str | None]:
    region: str | None = None
    district: str | None = None
    for component in result.get("address_components", []):
        types = set(component.get("types", []))
        if types & _REGION_TYPES and not region:
            region = component.get("long_name")
        if types & _DISTRICT_TYPES and not district:
            district = component.get("long_name")
    return {"region": region, "district": district}


def reverse_geocode(lat: float, lng: float, language: str = "uz") -> dict[str, Any] | None:
    """Resolve coordinates to an address. Returns None when unavailable."""
    if not is_configured():
        return None
    params = {
        "latlng": f"{lat},{lng}",
        "key": settings.google_maps_api_key,
        "language": language,
        "region": settings.google_maps_country,
    }
    try:
        response = httpx.get(GEOCODE_URL, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if body.get("status") != "OK" or not body.get("results"):
        return None
    result = body["results"][0]
    components = _extract_components(result)
    location = result.get("geometry", {}).get("location", {})
    return {
        "formatted_address": result.get("formatted_address"),
        "lat": location.get("lat", lat),
        "lng": location.get("lng", lng),
        "region": components["region"],
        "district": components["district"],
        "place_id": result.get("place_id"),
    }


def geocode(address: str, language: str = "uz") -> dict[str, Any] | None:
    """Resolve a typed address to coordinates. Returns None when unavailable."""
    if not is_configured() or not address.strip():
        return None
    params = {
        "address": address,
        "key": settings.google_maps_api_key,
        "language": language,
        "region": settings.google_maps_country,
        "components": f"country:{settings.google_maps_country.upper()}",
    }
    try:
        response = httpx.get(GEOCODE_URL, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if body.get("status") != "OK" or not body.get("results"):
        return None
    result = body["results"][0]
    location = result.get("geometry", {}).get("location", {})
    components = _extract_components(result)
    return {
        "formatted_address": result.get("formatted_address"),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "region": components["region"],
        "district": components["district"],
        "place_id": result.get("place_id"),
    }
