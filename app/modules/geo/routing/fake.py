"""Deterministic fake router for dev/test (never selectable in production, see ``config``)."""

from __future__ import annotations

from collections.abc import Sequence

from app.modules.geo.geometry import haversine_m
from app.modules.geo.routing.base import RouteLeg, RouteResult, RoutingUnavailable, validate_waypoints
from app.modules.geo.types import LatLng


class FakeRoutingProvider:
    """Great-circle distance x road factor at a constant speed; optional outage.

    Integer arithmetic after rounding the great-circle metres, so results are stable
    across platforms. ``calls`` records waypoints for assertions.
    """

    name = "fake"
    version = "fake-1"
    attribution = "Synthetic route from the Elchi test router (not a real road)"

    def __init__(self, *, road_factor_permille: int = 1250, speed_kmh: int = 60, outage: bool = False) -> None:
        if road_factor_permille < 1000 or speed_kmh <= 0:
            raise ValueError("road factor must be >= 1000 permille and speed positive")
        self.road_factor_permille = road_factor_permille
        self.speed_kmh = speed_kmh
        self.outage = outage
        self.calls: list[tuple[LatLng, ...]] = []

    def leg(self, a: LatLng, b: LatLng) -> RouteLeg:
        distance_m = (round(haversine_m(a, b)) * self.road_factor_permille + 500) // 1000
        duration_s = (distance_m * 3600 + self.speed_kmh * 500) // (self.speed_kmh * 1000)
        return RouteLeg(distance_m=distance_m, duration_s=duration_s)

    def route(self, waypoints: Sequence[LatLng]) -> RouteResult:
        points = validate_waypoints(waypoints)
        self.calls.append(points)
        if self.outage:
            raise RoutingUnavailable("fake_outage", self.name)
        legs = tuple(self.leg(a, b) for a, b in zip(points, points[1:]))
        return RouteResult(
            provider=self.name,
            provider_version=self.version,
            distance_m=sum(leg.distance_m for leg in legs),
            duration_s=sum(leg.duration_s for leg in legs),
            legs=legs,
            geometry=points,
            is_estimate=True,
        )
