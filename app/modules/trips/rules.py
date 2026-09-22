"""Pure trip, vehicle and segment-capacity rules (spec §5.2, §7; AC10-AC13). No I/O.

Segments: a trip with stop occurrences ``1..n`` has atomic segments
``(1,2), (2,3), ... (n-1,n)`` identified by ``from_seq``. A booking picked up at
occurrence ``p`` and dropped at ``d`` uses the half-open interval ``[p, d)``,
i.e. segments ``from_seq in range(p, d)``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.contracts.enums import TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.state_machines import TRIP_TERMINAL_STATUSES
from app.contracts.timeutil import ensure_aware_utc

TRIP_TIMEZONE = "Asia/Tashkent"
# Pilot turnaround/preparation buffer appended to the planned interval before the
# overlap exclusion constraint is evaluated (spec §7). Operator-tunable later.
TRIP_TURNAROUND_BUFFER = timedelta(minutes=30)
DEFAULT_PICKUP_WAIT_MINUTES = 10

# Statuses that occupy the driver and the vehicle (exclusion constraint predicate).
ACTIVE_TRIP_STATUSES: frozenset[str] = frozenset(
    {TripStatus.PLANNED.value, TripStatus.BOARDING.value, TripStatus.IN_PROGRESS.value, TripStatus.INTERRUPTED.value}
)
TERMINAL_TRIP_STATUSES: frozenset[str] = TRIP_TERMINAL_STATUSES


class VehicleVerificationStatus(StrEnum):
    """Module-private vehicle status values (DB CHECK in migration 0037)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"


VEHICLE_DECISIONS: dict[str, tuple[frozenset[str], VehicleVerificationStatus]] = {
    "approve": (frozenset({"pending", "rejected"}), VehicleVerificationStatus.APPROVED),
    "reject": (frozenset({"pending", "approved"}), VehicleVerificationStatus.REJECTED),
}


def validation_error(message: str, **details: object) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_ERROR, message, details=details or None)


def vehicle_class(seat_capacity: int) -> str:
    """Coarse, non-identifying vehicle class for pre-accept views (R2, Q43); never make/model/plate."""
    if seat_capacity <= 4:
        return "car"
    if seat_capacity <= 7:
        return "minivan"
    return "minibus"


def normalize_plate(value: str) -> str:
    normalized = "".join(ch for ch in value.upper() if ch.isalnum())
    if len(normalized) < 2:
        raise validation_error("plate_number is too short", field="plate_number")
    return normalized


def mask_plate(plate_normalized: str) -> str:
    """``01A123BC`` -> ``01****BC``; used before a booking is confirmed (§10.6)."""
    if len(plate_normalized) <= 4:
        return "*" * len(plate_normalized)
    return plate_normalized[:2] + "*" * (len(plate_normalized) - 4) + plate_normalized[-2:]


def blocked_period(
    planned_start_at: datetime, planned_end_at: datetime, buffer: timedelta = TRIP_TURNAROUND_BUFFER
) -> tuple[datetime, datetime]:
    start = ensure_aware_utc(planned_start_at, field="planned_start_at")
    end = ensure_aware_utc(planned_end_at, field="planned_end_at")
    if end <= start:
        raise validation_error("planned_end_at must be after planned_start_at", field="planned_end_at")
    return start, end + buffer


class Resource(StrEnum):
    SEATS = "seats"
    BAGGAGE_ML = "baggage_ml"
    CARGO_WEIGHT_G = "cargo_weight_g"
    CARGO_VOLUME_ML = "cargo_volume_ml"


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class ResourceDemand:
    seats: int = 0
    baggage_ml: int = 0
    cargo_weight_g: int = 0
    cargo_volume_ml: int = 0

    def __post_init__(self) -> None:
        for resource in Resource:
            _non_negative_int(getattr(self, resource.value), resource.value)

    def amount(self, resource: Resource) -> int:
        return getattr(self, resource.value)

    @property
    def is_empty(self) -> bool:
        return all(self.amount(resource) == 0 for resource in Resource)


@dataclass(frozen=True, slots=True)
class SegmentLoad:
    from_seq: int
    to_seq: int
    seat_capacity: int
    seats_used: int
    baggage_capacity_ml: int
    baggage_used_ml: int
    cargo_capacity_weight_g: int
    cargo_used_weight_g: int
    cargo_capacity_volume_ml: int
    cargo_used_volume_ml: int

    def capacity(self, resource: Resource) -> int:
        return {
            Resource.SEATS: self.seat_capacity,
            Resource.BAGGAGE_ML: self.baggage_capacity_ml,
            Resource.CARGO_WEIGHT_G: self.cargo_capacity_weight_g,
            Resource.CARGO_VOLUME_ML: self.cargo_capacity_volume_ml,
        }[resource]

    def used(self, resource: Resource) -> int:
        return {
            Resource.SEATS: self.seats_used,
            Resource.BAGGAGE_ML: self.baggage_used_ml,
            Resource.CARGO_WEIGHT_G: self.cargo_used_weight_g,
            Resource.CARGO_VOLUME_ML: self.cargo_used_volume_ml,
        }[resource]

    def remaining(self, resource: Resource) -> int:
        return self.capacity(resource) - self.used(resource)


@dataclass(frozen=True, slots=True)
class Shortfall:
    from_seq: int
    resource: Resource
    remaining: int
    requested: int


def covered_from_seqs(from_seq: int, to_seq: int) -> range:
    """Segments used by ``[from_seq, to_seq)``."""
    for name, value in (("from_seq", from_seq), ("to_seq", to_seq)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be int")
    if from_seq < 1 or to_seq <= from_seq:
        raise validation_error("pickup occurrence must come before dropoff occurrence", from_seq=from_seq, to_seq=to_seq)
    return range(from_seq, to_seq)


def _covered_segments(segments: Iterable[SegmentLoad], from_seq: int, to_seq: int) -> list[SegmentLoad]:
    by_from = {segment.from_seq: segment for segment in segments}
    covered = []
    for seq in covered_from_seqs(from_seq, to_seq):
        segment = by_from.get(seq)
        if segment is None:
            raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"missing_segment_from_seq": seq})
        covered.append(segment)
    return covered


def find_shortfalls(segments: Iterable[SegmentLoad], from_seq: int, to_seq: int, demand: ResourceDemand) -> list[Shortfall]:
    shortfalls: list[Shortfall] = []
    for segment in _covered_segments(segments, from_seq, to_seq):
        for resource in Resource:
            requested = demand.amount(resource)
            if requested and requested > segment.remaining(resource):
                shortfalls.append(Shortfall(segment.from_seq, resource, segment.remaining(resource), requested))
    return shortfalls


def min_remaining(segments: Iterable[SegmentLoad], from_seq: int, to_seq: int, resource: Resource) -> int:
    return min(segment.remaining(resource) for segment in _covered_segments(segments, from_seq, to_seq))


def shortfall_error(shortfalls: Sequence[Shortfall]) -> DomainError:
    """Seats -> ``CAPACITY_UNAVAILABLE``; baggage/cargo only -> ``CARGO_LIMIT_EXCEEDED`` (AC12)."""
    if not shortfalls:
        raise ValueError("no shortfall")
    code = (
        ErrorCode.CAPACITY_UNAVAILABLE
        if any(item.resource is Resource.SEATS for item in shortfalls)
        else ErrorCode.CARGO_LIMIT_EXCEEDED
    )
    return DomainError(
        code,
        details={
            "segments": [
                {"from_seq": s.from_seq, "resource": s.resource.value, "remaining": s.remaining, "requested": s.requested}
                for s in shortfalls
            ]
        },
    )


def map_stops_onto_route(trip_stop_ids: Sequence[int], route_stops: Sequence[tuple[int, int]]) -> list[int] | None:
    """Map trip stops onto ``(route_seq, stop_id)`` pairs as an ordered subsequence.

    Returns the matched route seqs, or ``None`` when a stop is missing or out of
    order (reverse direction is never matched). Repeated stops (loops) map to
    successive occurrences.
    """
    ordered = sorted(route_stops)
    matched: list[int] = []
    position = 0
    for stop_id in trip_stop_ids:
        while position < len(ordered) and ordered[position][1] != stop_id:
            position += 1
        if position >= len(ordered):
            return None
        matched.append(ordered[position][0])
        position += 1
    return matched


def validate_schedule(
    *,
    now: datetime,
    planned_start_at: datetime,
    planned_end_at: datetime,
    arrivals: Sequence[datetime],
    booking_cutoff_at: datetime | None,
) -> datetime:
    """Validate a trip schedule and return the effective booking cutoff (UTC)."""
    now = ensure_aware_utc(now)
    start = ensure_aware_utc(planned_start_at, field="planned_start_at")
    end = ensure_aware_utc(planned_end_at, field="planned_end_at")
    if end <= start:
        raise validation_error("planned_end_at must be after planned_start_at", field="planned_end_at")
    if start <= now:
        raise validation_error("planned_start_at must be in the future", field="planned_start_at")
    if len(arrivals) < 2:
        raise validation_error("a trip needs at least two stops", field="stops")
    previous = None
    for index, arrival in enumerate(arrivals):
        value = ensure_aware_utc(arrival, field="planned_arrival_at")
        if value < start or value > end:
            raise validation_error("stop arrival must be within the planned interval", field="stops", index=index)
        if previous is not None and value < previous:
            raise validation_error("stop arrivals must not go back in time", field="stops", index=index)
        previous = value
    cutoff = start if booking_cutoff_at is None else ensure_aware_utc(booking_cutoff_at, field="booking_cutoff_at")
    if cutoff > start:
        # Pilot: new bookings close before departure (spec §7).
        raise validation_error("booking_cutoff_at must not be after planned_start_at", field="booking_cutoff_at")
    return cutoff
