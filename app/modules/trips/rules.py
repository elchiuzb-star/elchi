"""Pure trip, vehicle and capacity rules (spec §5.2, §7; AC10-AC13). No I/O.

Capacity is counted on the road (ADR-0028, Q160): a booking occupies ``[pickup_m, dropoff_m)`` of the trip's stretch;
the arithmetic is ``app.contracts.route_position``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.contracts.enums import TripStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.route_position import ClaimShortfall
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


def claim_shortfall_error(shortfalls: Sequence[ClaimShortfall]) -> DomainError:
    """Seats -> ``CAPACITY_UNAVAILABLE``, otherwise ``CARGO_LIMIT_EXCEEDED`` (AC12); details name the road position
    where the trip is full (``positions[{at_m, resource, remaining, requested}]``)."""
    if not shortfalls:
        raise ValueError("no shortfall")
    code = (
        ErrorCode.CAPACITY_UNAVAILABLE
        if any(item.resource == Resource.SEATS.value for item in shortfalls)
        else ErrorCode.CARGO_LIMIT_EXCEEDED
    )
    return DomainError(
        code,
        details={
            "positions": [
                {"at_m": s.at_m, "resource": s.resource, "remaining": s.remaining, "requested": s.requested}
                for s in shortfalls
            ]
        },
    )


def validate_schedule(
    *,
    now: datetime,
    planned_start_at: datetime,
    planned_end_at: datetime,
    booking_cutoff_at: datetime | None,
) -> datetime:
    """Validate a trip's plan (start before end, in the future) and return the effective booking cutoff (UTC)."""
    now = ensure_aware_utc(now)
    start = ensure_aware_utc(planned_start_at, field="planned_start_at")
    end = ensure_aware_utc(planned_end_at, field="planned_end_at")
    if end <= start:
        raise validation_error("planned_end_at must be after planned_start_at", field="planned_end_at")
    if start <= now:
        raise validation_error("planned_start_at must be in the future", field="planned_start_at")
    cutoff = start if booking_cutoff_at is None else ensure_aware_utc(booking_cutoff_at, field="booking_cutoff_at")
    if cutoff > start:
        # Pilot: new bookings close before departure (spec §7).
        raise validation_error("booking_cutoff_at must not be after planned_start_at", field="booking_cutoff_at")
    return cutoff
