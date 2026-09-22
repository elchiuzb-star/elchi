"""Small geometry helpers that do not need PostGIS.

Metre-accurate filtering and distances on stored data are done in PostgreSQL with
``geography`` (``ST_DWithin(geography, geography, metres)``); these helpers are only
for choosing which route legs to probe with the router and for encoding output.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.modules.geo.types import LatLng

EARTH_MEAN_RADIUS_M = 6_371_008.8


def haversine_m(a: LatLng, b: LatLng) -> float:
    """Great-circle distance in metres (spherical Earth; ~0.5% error, fine for leg selection)."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = phi2 - phi1
    dlmb = math.radians(b.lng - a.lng)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_MEAN_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def encode_polyline(points: Sequence[LatLng], precision: int = 5) -> str:
    """Google encoded polyline (lat, lng order), the ``RouteVersionDTO.geometry_polyline`` format."""
    if not 1 <= precision <= 7:
        raise ValueError("precision must be between 1 and 7")
    factor = 10**precision
    out: list[str] = []
    prev_lat = prev_lng = 0
    for point in points:
        lat = _round_half_up(point.lat * factor)
        lng = _round_half_up(point.lng * factor)
        for delta in (lat - prev_lat, lng - prev_lng):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lng = lat, lng
    return "".join(out)


def point_ewkt(point: LatLng) -> str:
    """EWKT for ``geometry(Point,4326)``; PostGIS axis order is (lng lat)."""
    return f"SRID=4326;POINT({point.lng!r} {point.lat!r})"


def linestring_ewkt(points: Sequence[LatLng]) -> str:
    if len(points) < 2:
        raise ValueError("a linestring needs at least two points")
    coords = ", ".join(f"{p.lng!r} {p.lat!r}" for p in points)
    return f"SRID=4326;LINESTRING({coords})"
