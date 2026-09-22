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


def _geo_objects(body: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        members = body["response"]["GeoObjectCollection"]["featureMember"]
    except (KeyError, TypeError):
        return []
    return [member["GeoObject"] for member in members if isinstance(member, dict) and "GeoObject" in member]


def geocode(
    address: str,
    language: str = "uz",
    *,
    near: tuple[float, float] | None = None,
    span_deg: float | None = None,
) -> dict[str, Any] | None:
    """Resolve a typed address to coordinates. Returns None when unavailable.

    ``near`` + ``span_deg`` bias the search towards an area (Yandex ``ll``/``spn``): a search run from
    inside a chosen district answers with that district first. The bias is a **preference, not a
    filter** - ``rspn`` is deliberately not set, so a place outside the window is still found rather
    than the search coming back empty. When several results come back, the first one that actually
    falls inside the window wins; otherwise the provider's own best answer is used unchanged.
    """
    if not is_configured() or not address.strip():
        return None
    params = {
        "apikey": settings.yandex_geocoder_api_key,
        "format": "json",
        "geocode": address,
        "lang": _yandex_lang(language),
        "results": 1,
    }
    window: tuple[float, float, float, float] | None = None
    if near is not None and span_deg:
        near_lat, near_lng = near
        params["ll"] = f"{near_lng},{near_lat}"
        params["spn"] = f"{span_deg},{span_deg}"
        # Ranking only helps if there is more than one candidate to rank.
        params["results"] = 5
        window = (near_lat - span_deg, near_lat + span_deg, near_lng - span_deg, near_lng + span_deg)
    try:
        response = httpx.get(GEOCODE_URL, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    candidates = _geo_objects(body)
    if not candidates:
        return None
    geo_object = candidates[0]
    if window is not None:
        min_lat, max_lat, min_lng, max_lng = window
        for candidate in candidates:
            lat, lng = _point_lat_lng(candidate, 0.0, 0.0)
            if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                geo_object = candidate
                break
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


# --- place suggestions (Yandex Geosuggest) ---------------------------------------------------------------
#
# The geocoder answers *addresses*. People type *places*: "10-sonli maktab", "tuman hokimligi", a bazaar.
# Geosuggest is the Yandex product that answers those, and it is a separate key (ELCHI_YANDEX_SUGGEST_API_KEY).
# It returns no coordinates, only a `uri`, which the geocoder resolves - so a search is two calls, and only
# the place the person actually picks costs the second one.

SUGGEST_URL = "https://suggest-maps.yandex.ru/v1/suggest"

# Yandex address component kinds, from its own vocabulary.
_AREA_KINDS = {"AREA", "SUBADMINISTRATIVE_AREA"}
_PROVINCE_KINDS = {"PROVINCE"}
_LOCALITY_KINDS = {"LOCALITY"}


def suggest_is_configured() -> bool:
    return bool(settings.yandex_suggest_api_key)


def _suggest_components(item: dict[str, Any]) -> dict[str, str | None]:
    """Pull province/area/locality names out of a suggest result."""
    province: str | None = None
    area: str | None = None
    locality: str | None = None
    for component in (item.get("address") or {}).get("component") or []:
        kinds = set(component.get("kind") or [])
        name = component.get("name")
        if kinds & _PROVINCE_KINDS and not province:
            province = name
        if kinds & _AREA_KINDS and not area:
            area = name
        if kinds & _LOCALITY_KINDS and not locality:
            locality = name
    return {"region": province, "district": area, "locality": locality}


def suggest_places(
    text: str,
    *,
    language: str = "uz",
    near: tuple[float, float] | None = None,
    span_deg: float | None = None,
    limit: int = 10,
) -> list[dict[str, Any]] | None:
    """Place suggestions for typed text. Returns None when the product is not configured/available.

    ``near`` + ``span_deg`` are passed to Yandex as ``ll``/``spn``. As with the geocoder this is a
    preference and not a filter: a place just outside the chosen district is still offered, it simply
    ranks below the ones inside it. The caller gets `district`/`region` names and the distance from the
    bias point, which is what the ordering in the client is built on.
    """
    if not suggest_is_configured() or not text.strip():
        return None
    params: dict[str, Any] = {
        "apikey": settings.yandex_suggest_api_key,
        "text": text,
        "lang": _yandex_lang(language),
        "results": max(1, min(limit, 20)),
        "attrs": "uri",
        "print_address": 1,
        "types": "biz,geo",
    }
    if near is not None:
        near_lat, near_lng = near
        params["ll"] = f"{near_lng},{near_lat}"
        if span_deg:
            params["spn"] = f"{span_deg},{span_deg}"
    try:
        response = httpx.get(SUGGEST_URL, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    out: list[dict[str, Any]] = []
    for item in body.get("results") or []:
        uri = item.get("uri")
        if not uri:
            # Without a uri there is no way to turn this row into a coordinate, so offering it would be
            # offering a dead end.
            continue
        names = _suggest_components(item)
        distance = item.get("distance") or {}
        out.append(
            {
                "title": (item.get("title") or {}).get("text"),
                "subtitle": (item.get("subtitle") or {}).get("text"),
                "formatted_address": (item.get("address") or {}).get("formatted_address"),
                "region": names["region"],
                "district": names["district"],
                "locality": names["locality"],
                "distance_m": int(distance["value"]) if isinstance(distance.get("value"), (int, float)) else None,
                "uri": uri,
            }
        )
    return out


def geocode_uri(uri: str, language: str = "uz") -> dict[str, Any] | None:
    """Turn a suggest result's `uri` into coordinates. Returns None when unavailable."""
    if not is_configured() or not uri.strip():
        return None
    params = {
        "apikey": settings.yandex_geocoder_api_key,
        "format": "json",
        "uri": uri,
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


def _district_matches(candidate: str | None, wanted: str) -> bool:
    """Is this suggestion in the district the person chose?

    Yandex writes "Kasbi tumani" where the catalogue says "Kasbi", and casing/apostrophes vary between
    the two spellings of Uzbek, so the comparison is deliberately loose - and it only ever decides an
    *order*, never whether a result is shown.
    """
    if not candidate:
        return False
    def normalise(value: str) -> str:
        lowered = value.lower().replace("ʻ", "'").replace("‘", "'").replace("’", "'")
        for suffix in (" tumani", " shahri", " tuman", " district"):
            if lowered.endswith(suffix):
                lowered = lowered[: -len(suffix)]
        return lowered.strip()
    return normalise(candidate) == normalise(wanted)


def rank_suggestions(results: list[dict[str, Any]], *, district: str | None) -> list[dict[str, Any]]:
    """Chosen district first, then by distance from the search centre. Stable and total."""
    def key(item: dict[str, Any]) -> tuple[int, float]:
        inside = 0 if district and _district_matches(item.get("district"), district) else 1
        distance = item.get("distance_m")
        return (inside, float(distance) if isinstance(distance, (int, float)) else float("inf"))
    return sorted(results, key=key)
