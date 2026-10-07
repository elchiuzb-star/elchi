"""Geo value objects shared with other modules.

Plain frozen dataclasses: no DB, no settings, no I/O. Coordinates are WGS84 degrees (floats are fine here; money never
is). ADR-0028 / Q160: the stop-occurrence matching and detour types are gone with the stops - a place is a position on
a confirmed road (``app.contracts.route_position``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["LatLng"]


@dataclass(frozen=True, slots=True)
class LatLng:
    lat: float
    lng: float

    def __post_init__(self) -> None:
        for name, value, limit in (("lat", self.lat, 90.0), ("lng", self.lng, 180.0)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not math.isfinite(value) or not -limit <= value <= limit:
                raise ValueError(f"{name} out of range: {value!r}")
        object.__setattr__(self, "lat", float(self.lat))
        object.__setattr__(self, "lng", float(self.lng))
