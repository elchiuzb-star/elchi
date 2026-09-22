"""Outbound port from ``trips`` to the geo module (A2).

Trips code depends only on this Protocol. By default it is served by
``app.modules.trips.adapters.GeoServiceAdapter`` over ``app.modules.geo.service``;
tests may register a narrow fake with :func:`set_geo_port`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

ROUTE_VERSION_CONFIRMED = "confirmed"


class GeoIntegrationNotReady(RuntimeError):
    """No geo adapter registered (A2 service not wired yet)."""


@dataclass(frozen=True, slots=True)
class StopRef:
    id: int
    public_id: str  # stp_...
    corridor_id: int
    name_uz: str
    name_ru: str | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class RouteStopRef:
    seq: int
    stop_id: int
    cumulative_distance_m: int
    cumulative_duration_s: int


@dataclass(frozen=True, slots=True)
class RouteVersionRef:
    id: int
    public_id: str  # rtv_...
    status: str
    stops: tuple[RouteStopRef, ...]

    @property
    def is_confirmed(self) -> bool:
        return self.status == ROUTE_VERSION_CONFIRMED


class TripsGeoPort(Protocol):
    def stops_by_public_ids(self, session: Session, public_ids: Sequence[str]) -> dict[str, StopRef]: ...

    def stops_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, StopRef]: ...

    def route_version_by_public_id(self, session: Session, public_id: str) -> RouteVersionRef | None: ...

    def route_versions_by_ids(self, session: Session, ids: Sequence[int]) -> dict[int, RouteVersionRef]: ...


_geo_port: TripsGeoPort | None = None


def set_geo_port(port: TripsGeoPort | None) -> None:
    global _geo_port
    _geo_port = port


def get_geo_port() -> TripsGeoPort:
    if _geo_port is None:
        try:
            from app.modules.trips.adapters import GeoServiceAdapter
        except ImportError as exc:  # pragma: no cover - geo module absent
            raise GeoIntegrationNotReady("app.modules.geo.service is not available") from exc
        return GeoServiceAdapter()
    return _geo_port
