"""Routing provider protocol (spec §6.3 step 4, §10.1, §15).

Rules:
* Providers are called only outside a DB transaction (:func:`route_outside_transaction`).
* A failure is :class:`RoutingUnavailable`; callers turn it into ``ROUTING_UNAVAILABLE``
  or a degraded result, never into a guessed route (AC35).
* Provider credentials stay server-side; nothing here is serialised to clients.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.modules.geo.types import LatLng

MAX_WAYPOINTS = 25

# Attribution shown with a stored route version, by provider name (BR #16).
PROVIDER_ATTRIBUTIONS: dict[str, str] = {
    "fake": "Synthetic route from the Elchi test router (not a real road)",
    "geoapify": "Powered by Geoapify | © OpenStreetMap contributors",
    "osrm": "© OpenStreetMap contributors | routing by OSRM",
}


class RoutingUnavailable(Exception):
    """Router failed, timed out, is over quota, misconfigured or returned garbage."""

    def __init__(self, reason: str, provider: str) -> None:
        # Never include URLs or exception text: they may carry the API key.
        self.reason = reason
        self.provider = provider
        super().__init__(f"routing unavailable ({provider}: {reason})")


@dataclass(frozen=True, slots=True)
class RouteLeg:
    distance_m: int
    duration_s: int

    def __post_init__(self) -> None:
        for name in ("distance_m", "duration_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")


@dataclass(frozen=True, slots=True)
class RouteResult:
    provider: str
    provider_version: str
    distance_m: int
    duration_s: int
    legs: tuple[RouteLeg, ...]
    geometry: tuple[LatLng, ...]
    is_estimate: bool

    def __post_init__(self) -> None:
        RouteLeg(self.distance_m, self.duration_s)  # reuse validation
        legs = tuple(self.legs)
        geometry = tuple(self.geometry)
        if not legs:
            raise ValueError("a route has at least one leg")
        if len(geometry) < 2:
            raise ValueError("route geometry needs at least two points")
        object.__setattr__(self, "legs", legs)
        object.__setattr__(self, "geometry", geometry)

    def to_cache_json(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_version": self.provider_version,
            "distance_m": self.distance_m,
            "duration_s": self.duration_s,
            "legs": [[leg.distance_m, leg.duration_s] for leg in self.legs],
            "geometry": [[p.lat, p.lng] for p in self.geometry],
            "is_estimate": self.is_estimate,
        }

    @classmethod
    def from_cache_json(cls, data: dict[str, Any]) -> RouteResult:
        return cls(
            provider=str(data["provider"]),
            provider_version=str(data["provider_version"]),
            distance_m=int(data["distance_m"]),
            duration_s=int(data["duration_s"]),
            legs=tuple(RouteLeg(int(d), int(s)) for d, s in data["legs"]),
            geometry=tuple(LatLng(float(lat), float(lng)) for lat, lng in data["geometry"]),
            is_estimate=bool(data["is_estimate"]),
        )


@runtime_checkable
class RoutingProvider(Protocol):
    name: str
    version: str
    attribution: str

    def route(self, waypoints: Sequence[LatLng]) -> RouteResult:
        """Driving route through ``waypoints`` in order; raises :class:`RoutingUnavailable`."""
        ...


def validate_waypoints(waypoints: Sequence[LatLng]) -> tuple[LatLng, ...]:
    points = tuple(waypoints)
    if len(points) < 2:
        raise ValueError("at least two waypoints are required")
    if len(points) > MAX_WAYPOINTS:
        raise ValueError(f"at most {MAX_WAYPOINTS} waypoints are allowed")
    for point in points:
        if not isinstance(point, LatLng):
            raise TypeError("waypoints must be LatLng")
    return points


class DisabledRoutingProvider:
    """Used when no provider is configured, and always in production (decision 24)."""

    version = "none"
    attribution = ""

    def __init__(self, reason: str = "not_configured") -> None:
        self.name = "disabled"
        self.reason = reason

    def route(self, waypoints: Sequence[LatLng]) -> RouteResult:
        validate_waypoints(waypoints)
        raise RoutingUnavailable(self.reason, self.name)


def assert_outside_transaction(session: Any) -> None:
    """Spec §15: external map/routing APIs are never called inside a DB transaction."""
    if session is not None and session.in_transaction():
        raise RuntimeError("routing provider must not be called inside a DB transaction (spec §15)")


def route_outside_transaction(session: Any, provider: RoutingProvider, waypoints: Sequence[LatLng]) -> RouteResult:
    assert_outside_transaction(session)
    return provider.route(waypoints)
