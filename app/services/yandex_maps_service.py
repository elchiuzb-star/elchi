"""Server-side Yandex Geocoder integration.

Wraps the Yandex Geocoder HTTP API so the backend can:
  * reverse-geocode a lat/lng marker into a human-readable address, and
  * forward-geocode a typed address into coordinates.

Both helpers degrade gracefully: if no API key is configured (or Yandex returns
an error / the request fails) they return ``None`` instead of raising, so the
rest of the app keeps working with the local heuristics in ``geo_service``.

Yandex Geocoder reference: https://yandex.com/dev/geocode/doc/en/
Note: Yandex uses "longitude,latitude" order in the ``geocode`` parameter.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings

GEOCODE_URL = "https://geocode-maps.yandex.ru/1.x/"
_REQUEST_TIMEOUT = 6.0

# Yandex "kind" values, coarse (region) → fine (district), used to pull the
# administrative pieces out of a geocode result's component list.
_REGION_KINDS = {"province", "area"}
_DISTRICT_KINDS = {"district", "locality"}

# Yandex language tags per app language.
_LANG = {"uz": "uz_UZ", "ru": "ru_RU", "en": "en_US"}


def is_configured() -> bool:
    return bool(settings.yandex_geocoder_api_key)


def _yandex_lang(language: str) -> str:
    return _LANG.get(language, "uz_UZ")


def _first_geo_object(body: dict[str, Any]) -> dict[str, Any] | None:
    try:
        members = body["response"]["GeoObjectCollection"]["featureMember"]
    except (KeyError, TypeError):
        return None
    if not members:
        return None
    return members[0].get("GeoObject")


def _extract_components(geo_object: dict[str, Any]) -> dict[str, str | None]:
    """Pull region/district labels from the address component list."""
    region: str | None = None
    district: str | None = None
    try:
        components = (
            geo_object["metaDataProperty"]["GeocoderMetaData"]["Address"]["Components"]
        )
    except (KeyError, TypeError):
        components = []
    for component in components:
        kind = component.get("kind")
        name = component.get("name")
        if kind in _REGION_KINDS and not region:
            region = name
        if kind in _DISTRICT_KINDS and not district:
            district = name
    return {"region": region, "district": district}


def _point_lat_lng(geo_object: dict[str, Any], fallback_lat: float, fallback_lng: float) -> tuple[float, float]:
    # Yandex Point.pos is "lon lat" (space-separated, longitude first).
    try:
        pos = geo_object["Point"]["pos"]
        lng_str, lat_str = pos.split()
        return float(lat_str), float(lng_str)
    except (KeyError, TypeError, ValueError):
        return fallback_lat, fallback_lng


def _formatted_address(geo_object: dict[str, Any]) -> str | None:
    try:
        return geo_object["metaDataProperty"]["GeocoderMetaData"]["text"]
    except (KeyError, TypeError):
        return geo_object.get("name")


def reverse_geocode(lat: float, lng: float, language: str = "uz") -> dict[str, Any] | None:
    """Resolve coordinates to an address. Returns None when unavailable."""
    if not is_configured():
        return None
    params = {
        "apikey": settings.yandex_geocoder_api_key,
        "format": "json",
        "geocode": f"{lng},{lat}",  # Yandex wants lon,lat
        "lang": _yandex_lang(language),
        "results": 1,
        "kind": "house",
    }
    try:
        response = httpx.get(GEOCODE_URL, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    geo_object = _first_geo_object(body)
    if geo_object is None:
        return None
    components = _extract_components(geo_object)
    out_lat, out_lng = _point_lat_lng(geo_object, lat, lng)
    return {
        "formatted_address": _formatted_address(geo_object),
        "lat": out_lat,
        "lng": out_lng,
        "region": components["region"],
        "district": components["district"],
        "place_id": None,
    }


def geocode(address: str, language: str = "uz") -> dict[str, Any] | None:
    """Resolve a typed address to coordinates. Returns None when unavailable."""
    if not is_configured() or not address.strip():
        return None
    params = {
        "apikey": settings.yandex_geocoder_api_key,
        "format": "json",
        "geocode": address,
        "lang": _yandex_lang(language),
        "results": 1,
    }
    try:
        response = httpx.get(GEOCODE_URL, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    geo_object = _first_geo_object(body)
    if geo_object is None:
        return None
    components = _extract_components(geo_object)
    out_lat, out_lng = _point_lat_lng(geo_object, 0.0, 0.0)
    if out_lat == 0.0 and out_lng == 0.0:
        return None
    return {
        "formatted_address": _formatted_address(geo_object),
        "lat": out_lat,
        "lng": out_lng,
        "region": components["region"],
        "district": components["district"],
        "place_id": None,
    }
