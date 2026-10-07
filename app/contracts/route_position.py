"""ADR-0028 (Q159): places as positions along a confirmed road, and capacity as intervals of that road.

ELCHI works point A -> point B. There are no intermediate nodes - neither user/operator stops nor system-made ones -
so everything the engine needs is expressed in **metres along the confirmed road from its start**:

* a place's position: ``round(fraction * distance_m)`` where ``fraction`` is ``ST_LineLocatePoint`` (0..1);
* a trip drives ``[route_start_m, route_end_m]`` of the road;
* a booking occupies ``[pickup_m, dropoff_m)`` of it (a *claim*);
* driving time is linear along the road: ``duration_s * metres / distance_m``.

Capacity: at every point ``x`` of the road the sum of the active claims covering ``x`` must fit the trip. The sum of
half-open intervals only rises at an interval's start, so the peak over ``[from_m, to_m)`` is reached either at
``from_m`` or at the start of a claim inside it - those are the only points checked.

Pure and dependency-free (AGENTS §4: no DB, settings, clock or I/O). The lateral distance from the road is a different
quantity (``*_route_offset_m``, Q88) and never mixes with these positions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

__all__ = [
    "RESOURCES",
    "ROAD_POSITION_COMMENT",
    "Claim",
    "ClaimShortfall",
    "Resources",
    "claim_span",
    "eta_at",
    "interval_shortfalls",
    "peak_load",
    "position_m",
    "travel_s",
]

#: The column comment migration 0097 writes on every ``*_position_m`` / ``route_*_m`` column (the ORM repeats it).
ROAD_POSITION_COMMENT = (
    "ADR-0028 (Q159): metres along the confirmed road from its start (round(ST_LineLocatePoint * distance_m)). "
    "Not the *_route_offset_m lateral distance."
)

#: The resources a claim carries, in the order every tuple of amounts uses.
RESOURCES: tuple[str, ...] = ("seats", "baggage_ml", "cargo_weight_g", "cargo_volume_ml")


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int")
    return value


def position_m(fraction: float | Decimal, distance_m: int) -> int:
    """Metres along the road for a ``ST_LineLocatePoint`` fraction. Half-up rounding, like ``round()`` in SQL."""
    _int(distance_m, "distance_m")
    if distance_m <= 0:
        raise ValueError("distance_m must be positive")
    value = Decimal(str(fraction))
    if not Decimal(0) <= value <= Decimal(1):
        raise ValueError("fraction must be within 0..1")
    return int((value * distance_m).to_integral_value(rounding="ROUND_HALF_UP"))


def travel_s(from_m: int, to_m: int, *, distance_m: int, duration_s: int) -> int:
    """Driving time between two positions of one road, linear along it (no nodes, no dwell)."""
    for name, value in (("from_m", from_m), ("to_m", to_m), ("distance_m", distance_m), ("duration_s", duration_s)):
        _int(value, name)
    if distance_m <= 0 or duration_s < 0:
        raise ValueError("road distance must be positive and duration non-negative")
    if to_m < from_m:
        raise ValueError("to_m must not come before from_m")
    return (duration_s * (to_m - from_m) + distance_m // 2) // distance_m


def eta_at(position_m: int, *, start_m: int, end_m: int, start_at: datetime, end_at: datetime) -> datetime:
    """When a trip driving ``[start_m, end_m]`` from ``start_at`` to ``end_at`` passes ``position_m`` (ADR-0028).

    Linear in road metres between the trip's own two planned moments - the driver's plan, not the road's default
    estimate - with no node or dwell in between. A position before the start is reached at the start, one past the
    end at the end. Whole seconds.
    """
    for name, value in (("position_m", position_m), ("start_m", start_m), ("end_m", end_m)):
        _int(value, name)
    if end_m < start_m or end_at < start_at:
        raise ValueError("a trip ends after it starts")
    if end_m == start_m:
        return start_at
    x = min(max(position_m, start_m), end_m)
    total_s = int((end_at - start_at).total_seconds())
    return start_at + timedelta(seconds=(total_s * (x - start_m) + (end_m - start_m) // 2) // (end_m - start_m))


def claim_span(pickup_m: int, dropoff_m: int) -> tuple[int, int]:
    """The half-open interval a booking occupies. Pickup strictly before dropoff (Q88 rule 3)."""
    _int(pickup_m, "pickup_m")
    _int(dropoff_m, "dropoff_m")
    if pickup_m < 0 or dropoff_m <= pickup_m:
        raise ValueError("pickup must come before dropoff along the road")
    return pickup_m, dropoff_m


@dataclass(frozen=True, slots=True)
class Resources:
    seats: int = 0
    baggage_ml: int = 0
    cargo_weight_g: int = 0
    cargo_volume_ml: int = 0

    def __post_init__(self) -> None:
        for name in RESOURCES:
            if _int(getattr(self, name), name) < 0:
                raise ValueError(f"{name} must be non-negative")

    def amounts(self) -> tuple[int, ...]:
        return tuple(getattr(self, name) for name in RESOURCES)

    @property
    def is_empty(self) -> bool:
        return not any(self.amounts())


@dataclass(frozen=True, slots=True)
class Claim:
    from_m: int
    to_m: int
    resources: Resources

    def __post_init__(self) -> None:
        claim_span(self.from_m, self.to_m)

    def covers(self, at_m: int) -> bool:
        return self.from_m <= at_m < self.to_m


@dataclass(frozen=True, slots=True)
class ClaimShortfall:
    at_m: int
    resource: str
    remaining: int
    requested: int


def _breakpoints(claims: Sequence[Claim], from_m: int, to_m: int) -> list[int]:
    return sorted({from_m, *(c.from_m for c in claims if from_m < c.from_m < to_m)})


def _load_at(claims: Iterable[Claim], at_m: int) -> tuple[int, ...]:
    totals = [0] * len(RESOURCES)
    for claim in claims:
        if claim.covers(at_m):
            for index, amount in enumerate(claim.resources.amounts()):
                totals[index] += amount
    return tuple(totals)


def peak_load(claims: Iterable[Claim], from_m: int, to_m: int) -> dict[str, tuple[int, int]]:
    """Per resource: ``(peak amount, first position where it is reached)`` over ``[from_m, to_m)``."""
    claim_span(from_m, to_m)
    claims = list(claims)
    peaks: dict[str, tuple[int, int]] = {name: (0, from_m) for name in RESOURCES}
    for at_m in _breakpoints(claims, from_m, to_m):
        for name, amount in zip(RESOURCES, _load_at(claims, at_m), strict=True):
            if amount > peaks[name][0]:
                peaks[name] = (amount, at_m)
    return peaks


def interval_shortfalls(
    capacity: Resources, claims: Iterable[Claim], from_m: int, to_m: int, demand: Resources
) -> list[ClaimShortfall]:
    """What a new claim ``[from_m, to_m)`` of ``demand`` would overflow; empty when it fits everywhere."""
    if demand.is_empty:
        raise ValueError("demand must not be empty")
    peaks = peak_load(claims, from_m, to_m)
    shortfalls: list[ClaimShortfall] = []
    for name, limit, requested in zip(RESOURCES, capacity.amounts(), demand.amounts(), strict=True):
        if not requested:
            continue
        used, at_m = peaks[name]
        remaining = limit - used
        if requested > remaining:
            shortfalls.append(ClaimShortfall(at_m=at_m, resource=name, remaining=max(remaining, 0), requested=requested))
    return shortfalls
