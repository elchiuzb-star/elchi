"""Routing adapter: OSRM, run by us (spec §6.3 step 4; ADR-0011 external data flow).

Why this provider exists
------------------------
The other two adapters are a dead end for production. ``fake`` draws straight lines between stops -
honest about being synthetic, useless as a road. ``geoapify`` is a real router, but it is a third
party outside the country, so Q24 keeps it switched off until a legal and terms review that has not
happened.

OSRM is the same routing quality with neither problem, because **it is not an external service**:
the container runs next to the database, on an OpenStreetMap extract of Uzbekistan, and no request,
coordinate or booking ever leaves the machine. `docs/ops/EXTERNAL_DATA_FLOWS.md` already names this
as the thing that removes flow E9 rather than adding one.

What it talks to
----------------
`osrm-routed`'s HTTP API::

    GET {base}/route/v1/driving/{lng},{lat};{lng},{lat}...?overview=full&geometries=geojson

GeoJSON rather than an encoded polyline: the coordinates arrive as plain numbers, so there is no
decoder to get wrong, and over a local socket the extra bytes cost nothing.

Strictness
----------
Any deviation from the documented shape is :class:`RoutingUnavailable`, never a guessed route
(AC35). A router that answers ``NoRoute`` is telling us the truth - two places with no road between
them - and the caller turns that into the product's "not on an ELCHI route yet", not into a straight
line drawn over a desert.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.modules.geo.routing.base import (
    RouteLeg,
    RouteResult,
    RoutingUnavailable,
    validate_waypoints,
)
from app.modules.geo.types import LatLng

DEFAULT_BASE_URL = "http://127.0.0.1:5000"
ATTRIBUTION = "© OpenStreetMap contributors | routing by OSRM"

#: OSRM's own vocabulary for "there is no road", as opposed to "the router is broken".
_NO_ROUTE_CODES = {"NoRoute", "NoSegment", "NoTrips"}


def parse_osrm_response(body: Any, *, waypoint_count: int, provider_version: str = "v1") -> RouteResult:
    """Strictly parse an OSRM ``/route`` body; any deviation -> :class:`RoutingUnavailable`."""
    if not isinstance(body, dict):
        raise RoutingUnavailable("bad_response", "osrm")

    code = body.get("code")
    if code in _NO_ROUTE_CODES:
        raise RoutingUnavailable("no_route", "osrm")
    if code != "Ok":
        raise RoutingUnavailable("bad_response", "osrm")

    routes = body.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RoutingUnavailable("no_route", "osrm")
    route = routes[0]
    if not isinstance(route, dict):
        raise RoutingUnavailable("bad_response", "osrm")

    try:
        geometry_coordinates = route["geometry"]["coordinates"]
        raw_legs = route["legs"]
        total_distance = route["distance"]
        total_duration = route["duration"]
    except (KeyError, TypeError):
        raise RoutingUnavailable("bad_response", "osrm") from None

    if not isinstance(raw_legs, list) or len(raw_legs) != waypoint_count - 1:
        # A leg per gap between waypoints, or the caller cannot line legs up with stops.
        raise RoutingUnavailable("bad_response", "osrm")

    try:
        legs = tuple(
            RouteLeg(distance_m=round(float(leg["distance"])), duration_s=round(float(leg["duration"])))
            for leg in raw_legs
        )
        # OSRM speaks GeoJSON order: longitude first.
        geometry = tuple(
            LatLng(float(pair[1]), float(pair[0]))
            for pair in geometry_coordinates
            if isinstance(pair, (list, tuple)) and len(pair) >= 2
        )
        result = RouteResult(
            provider="osrm",
            provider_version=provider_version,
            distance_m=round(float(total_distance)),
            duration_s=round(float(total_duration)),
            legs=legs,
            geometry=geometry,
            # A real road network and real speed profiles: this is a routed answer, not an estimate.
            is_estimate=False,
        )
    except (KeyError, TypeError, ValueError):
        raise RoutingUnavailable("bad_response", "osrm") from None
    return result


class OsrmRoutingProvider:
    """Our own `osrm-routed`. No API key: there is no third party to authenticate to."""

    name = "osrm"
    version = "v1"
    attribution = ATTRIBUTION

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        profile: str = "driving",
        timeout_s: float = 6.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            # Plain http is expected and correct here: the socket is local, and requiring TLS for it
            # would mean terminating a certificate in front of our own container for no gain.
            raise ValueError("base_url must be http:// or https://")
        self._base_url = base_url.rstrip("/")
        self._profile = profile
        self._timeout_s = timeout_s
        self._transport = transport

    def __repr__(self) -> str:
        return f"OsrmRoutingProvider(base_url={self._base_url!r}, profile={self._profile!r})"

    def route(self, waypoints: Sequence[LatLng]) -> RouteResult:
        points = validate_waypoints(waypoints)
        path = ";".join(f"{point.lng:.6f},{point.lat:.6f}" for point in points)
        url = f"{self._base_url}/route/v1/{self._profile}/{path}"
        params = {"overview": "full", "geometries": "geojson", "steps": "false", "annotations": "false"}
        try:
            with httpx.Client(timeout=self._timeout_s, transport=self._transport, follow_redirects=False) as client:
                response = client.get(url, params=params)
        except httpx.TimeoutException:
            raise RoutingUnavailable("timeout", self.name) from None
        except httpx.HTTPError:
            # Almost always "the container is not running" during development, which is a
            # configuration fact and not something to paper over with a synthetic line.
            raise RoutingUnavailable("network", self.name) from None
        if response.status_code == 429:
            raise RoutingUnavailable("quota", self.name)
        if response.status_code >= 500:
            raise RoutingUnavailable("upstream_error", self.name)
        if response.status_code == 400:
            # OSRM answers 400 with a code like NoRoute; the body says which.
            try:
                return parse_osrm_response(response.json(), waypoint_count=len(points), provider_version=self.version)
            except ValueError:
                raise RoutingUnavailable("bad_response", self.name) from None
        if response.status_code != 200:
            raise RoutingUnavailable(f"http_{response.status_code}", self.name)
        try:
            body = response.json()
        except ValueError:
            raise RoutingUnavailable("bad_response", self.name) from None
        return parse_osrm_response(body, waypoint_count=len(points), provider_version=self.version)
