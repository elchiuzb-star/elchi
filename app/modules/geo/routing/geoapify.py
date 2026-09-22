"""Hosted routing adapter: Geoapify Routing API (spec §10.2 candidate; ADR-0011 external data flow).

Request: ``GET {base_url}?waypoints=lat,lon|lat,lon&mode=drive&apiKey=...`` (GeoJSON response).
Response fields used: ``features[0].properties.distance`` (m), ``.time`` (s),
``.legs[i].distance/time``; ``features[0].geometry`` LineString or MultiLineString of
``[lon, lat]`` pairs.

Verification status: parsing is covered by a contract test against a response shaped
after the public documentation (``tests/fixtures/geo/geoapify_routing_response.json``).
It has NOT been verified against the real service/sandbox (no API key was available).

Data flow: stop coordinates (no user identity) leave the country to the provider;
listed for the legal review in ADR-0011. The API key is never logged or returned.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any

import httpx

from app.modules.geo.routing.base import RouteLeg, RouteResult, RoutingUnavailable, validate_waypoints
from app.modules.geo.types import LatLng

DEFAULT_BASE_URL = "https://api.geoapify.com/v1/routing"
ATTRIBUTION = "Powered by Geoapify | © OpenStreetMap contributors"

# httpx/httpcore log full request URLs at INFO, which would include ``apiKey`` (BR #11).
for _logger_name in ("httpx", "httpcore"):
    if logging.getLogger(_logger_name).getEffectiveLevel() < logging.WARNING:
        logging.getLogger(_logger_name).setLevel(logging.WARNING)


def _metres_or_seconds(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("expected a non-negative finite number")
    return int(math.floor(float(value) + 0.5))


def parse_geoapify_response(body: Any, *, waypoint_count: int, provider_version: str = "v1") -> RouteResult:
    """Strictly parse a Geoapify routing GeoJSON body; any deviation -> ``RoutingUnavailable``."""
    try:
        feature = body["features"][0]
        props = feature["properties"]
        distance_m = _metres_or_seconds(props["distance"])
        duration_s = _metres_or_seconds(props["time"])
        legs = tuple(
            RouteLeg(distance_m=_metres_or_seconds(leg["distance"]), duration_s=_metres_or_seconds(leg["time"]))
            for leg in props["legs"]
        )
        geometry = feature["geometry"]
        if geometry["type"] == "LineString":
            lines = [geometry["coordinates"]]
        elif geometry["type"] == "MultiLineString":
            lines = geometry["coordinates"]
        else:
            raise ValueError("unsupported geometry type")
        points: list[LatLng] = []
        for line in lines:
            for coord in line:
                point = LatLng(lat=float(coord[1]), lng=float(coord[0]))
                if not points or points[-1] != point:
                    points.append(point)
        if len(legs) != waypoint_count - 1:
            raise ValueError("leg count does not match waypoints")
        return RouteResult(
            provider="geoapify",
            provider_version=provider_version,
            distance_m=distance_m,
            duration_s=duration_s,
            legs=legs,
            geometry=tuple(points),
            # No live traffic in the request: durations are typical-speed estimates.
            is_estimate=True,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        raise RoutingUnavailable("bad_response", "geoapify") from None


class GeoapifyRoutingProvider:
    name = "geoapify"
    version = "v1"
    attribution = ATTRIBUTION

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        mode: str = "drive",
        timeout_s: float = 6.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not base_url.startswith("https://"):
            raise ValueError("base_url must use https")
        self._api_key = api_key
        self._base_url = base_url
        self._mode = mode
        self._timeout_s = timeout_s
        self._transport = transport

    def __repr__(self) -> str:  # never show the key
        return f"GeoapifyRoutingProvider(base_url={self._base_url!r}, mode={self._mode!r})"

    def route(self, waypoints: Sequence[LatLng]) -> RouteResult:
        points = validate_waypoints(waypoints)
        params = {
            "waypoints": "|".join(f"{p.lat:.6f},{p.lng:.6f}" for p in points),
            "mode": self._mode,
            "apiKey": self._api_key,
        }
        try:
            with httpx.Client(timeout=self._timeout_s, transport=self._transport, follow_redirects=False) as client:
                response = client.get(self._base_url, params=params)
        except httpx.TimeoutException:
            raise RoutingUnavailable("timeout", self.name) from None
        except httpx.HTTPError:
            raise RoutingUnavailable("network", self.name) from None
        if response.status_code == 429:
            raise RoutingUnavailable("quota", self.name)
        if response.status_code in (401, 403):
            raise RoutingUnavailable("auth", self.name)
        if response.status_code >= 500:
            raise RoutingUnavailable("upstream_error", self.name)
        if response.status_code != 200:
            raise RoutingUnavailable(f"http_{response.status_code}", self.name)
        try:
            body = response.json()
        except ValueError:
            raise RoutingUnavailable("bad_response", self.name) from None
        return parse_geoapify_response(body, waypoint_count=len(points), provider_version=self.version)
