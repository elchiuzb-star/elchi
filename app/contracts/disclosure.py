"""Vehicle plate disclosure after accept (wave 2.1, Q64; Q43/Q44, ADR-0020).

* Before accept: no plate at all (``TripPublicDTO.vehicle`` = class + seats).
* After accept: :func:`mask_plate_number` + make/model + colour (``dto.BookingVehicleDisclosureDTO``).
* Full plate: when the trip is ``boarding`` or at most :data:`FULL_PLATE_LEAD_BEFORE_PICKUP` before the pickup
  time of this booking (:func:`full_plate_visible`). The caller passes the agreed pickup time; A4 uses the
  booking's ``pickup_window_start`` (earliest agreed pickup moment).
* Not for bookings that ended before the service started (``cancelled`` / ``no_show``): the owner module does
  not call the helper for them. Staff views may show the full plate (audited).
Pure: stdlib only.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.contracts.enums import TripStatus
from app.contracts.timeutil import ensure_aware_utc

FULL_PLATE_LEAD_BEFORE_PICKUP = timedelta(minutes=30)
FULL_PLATE_TRIP_STATUSES: frozenset[str] = frozenset({TripStatus.BOARDING.value})


def normalize_plate_number(plate: str) -> str:
    """Upper-case alphanumerics only (same normalisation as ``vehicles.plate_normalized``)."""
    return "".join(ch for ch in plate.upper() if ch.isalnum())


def mask_plate_number(plate: str) -> str:
    """``01 A 123 BC`` -> ``01****BC``; four characters or fewer -> all masked.

    Identical to ``app.modules.trips.rules.mask_plate`` (contract test keeps them equal).
    """
    normalized = normalize_plate_number(plate)
    if len(normalized) <= 4:
        return "*" * len(normalized)
    return normalized[:2] + "*" * (len(normalized) - 4) + normalized[-2:]


def full_plate_visible_from(pickup_at: datetime) -> datetime:
    return ensure_aware_utc(pickup_at, field="pickup_at") - FULL_PLATE_LEAD_BEFORE_PICKUP


def full_plate_visible(*, trip_status: TripStatus | str, pickup_at: datetime, now: datetime) -> bool:
    """Q64: trip ``boarding`` or ``now >= pickup_at - 30 min`` (also after the pickup time has passed)."""
    if TripStatus(trip_status).value in FULL_PLATE_TRIP_STATUSES:
        return True
    return ensure_aware_utc(now, field="now") >= full_plate_visible_from(pickup_at)
