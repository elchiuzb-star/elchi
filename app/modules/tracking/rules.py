"""Pure tracking rules (A6): point classification, payload hash, window rule, grant TTL, event payloads. No DB.

Contract constants and helpers live in ``app.contracts.tracking``; this module only combines them.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.contracts import tracking as contract
from app.contracts.enums import (
    ServiceType,
    TrackingFreshness,
    TrackingQualityFlag,
    TrackingWindowReason,
    TripStatus,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import UTC, ensure_aware_utc, to_iso_utc

# K1: a driver publishes GPS only for a trip that is actually running (§10.3 step 1: no two-day continuous GPS).
PUBLISHABLE_TRIP_STATUSES: frozenset[str] = frozenset(
    {TripStatus.BOARDING.value, TripStatus.IN_PROGRESS.value, TripStatus.INTERRUPTED.value}
)

# U1 (pending user decision, WAVE1_CARDS "Wave 3"): may a parcel sender see the vehicle's live location between accept
# and pickup? Q44 says "tracking window" from accept; spec §10.6 and the contract open the parcel window at pickup.
# Conservative contract default: NO. This is the single switch for that rule.
PARCEL_SENDER_SEES_LIVE_LOCATION_BEFORE_PICKUP = False

EARTH_RADIUS_M = 6_371_008.8


def booking_tracking_window(
    *,
    service_type: ServiceType | str,
    service_status: str,
    trip_status: TripStatus | str,
    pickup_window_start: datetime,
    now: datetime,
) -> contract.TrackingWindow:
    """Live-location window for booking participants and recipient links (``contract.tracking_window`` + U1 rule)."""
    window = contract.tracking_window(
        service_type=service_type,
        service_status=service_status,
        trip_status=trip_status,
        pickup_window_start=pickup_window_start,
        now=now,
    )
    if PARCEL_SENDER_SEES_LIVE_LOCATION_BEFORE_PICKUP and window.reason is TrackingWindowReason.PARCEL_NOT_PICKED_UP:
        return contract.TrackingWindow(True, TrackingWindowReason.OPEN)
    return window


def parcel_open_statuses() -> frozenset[str]:
    """Parcel statuses whose window is open (SQL pre-filter of the window-opened job; follows the U1 switch)."""
    if PARCEL_SENDER_SEES_LIVE_LOCATION_BEFORE_PICKUP:
        return contract.PARCEL_TRACKING_STATUSES | contract.PARCEL_BEFORE_PICKUP_STATUSES
    return contract.PARCEL_TRACKING_STATUSES


def grant_ttl(ttl_minutes: int) -> timedelta:
    """K5 TTL bounds (U4 pilot default 15 min - 24 h, ``contract.TRACKING_GRANT_MIN_TTL``/``MAX_TTL``)."""
    if isinstance(ttl_minutes, bool) or not isinstance(ttl_minutes, int):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "ttl_minutes"})
    ttl = timedelta(minutes=ttl_minutes)
    if ttl < contract.TRACKING_GRANT_MIN_TTL or ttl > contract.TRACKING_GRANT_MAX_TTL:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            details={
                "field": "ttl_minutes",
                "min": int(contract.TRACKING_GRANT_MIN_TTL.total_seconds() // 60),
                "max": int(contract.TRACKING_GRANT_MAX_TTL.total_seconds() // 60),
            },
        )
    return ttl


def grant_validity(
    *,
    window: contract.TrackingWindow,
    service_type: ServiceType | str,
    pickup_window_start: datetime,
    now: datetime,
    ttl: timedelta,
) -> tuple[datetime, datetime]:
    """K5 ``(valid_from, valid_until)``. A grant issued before the window opens starts at the window opening - passenger
    ``pickup - 30 min`` (``window.opens_at``), parcel the agreed ``pickup_window_start`` (the actual opening is the
    ``picked_up`` status, unknown in advance) - so it cannot expire before the window opens; ``ttl`` counts from
    ``valid_from``. It may be issued at most ``TRACKING_GRANT_MAX_TTL`` ahead of that start, otherwise
    ``400 VALIDATION_ERROR reason=grant_too_early {issuable_from}``. K7 still requires the window to be open."""
    now = ensure_aware_utc(now)
    anchor: datetime | None = None
    if not window.is_open:
        if window.opens_at is not None:
            anchor = ensure_aware_utc(window.opens_at)
        elif ServiceType(service_type) is ServiceType.PARCEL and window.reason is TrackingWindowReason.PARCEL_NOT_PICKED_UP:
            anchor = ensure_aware_utc(pickup_window_start)
    valid_from = anchor if anchor is not None and anchor > now else now
    if valid_from - now > contract.TRACKING_GRANT_MAX_TTL:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            details={
                "field": "ttl_minutes",
                "reason": "grant_too_early",
                "issuable_from": to_iso_utc(valid_from - contract.TRACKING_GRANT_MAX_TTL),
            },
        )
    return valid_from, valid_from + ttl


# --- points ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fix:
    """A stored position used as a reference (live marker or plausibility candidate)."""

    captured_at: datetime
    lat: float
    lng: float


@dataclass(frozen=True, slots=True)
class PointDecision:
    flags: tuple[TrackingQualityFlag, ...]
    moves_live: bool
    becomes_candidate: bool


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Great-circle (haversine) distance in whole metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return int(round(2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))))


def _implausible(reference: Fix, captured_at: datetime, lat: float, lng: float) -> bool:
    elapsed = (captured_at - reference.captured_at).total_seconds()
    return contract.is_implausible_speed(distance_m(reference.lat, reference.lng, lat, lng), elapsed)


def classify_point(
    *,
    captured_at: datetime,
    lat: float,
    lng: float,
    accuracy_m: int,
    is_mock: bool,
    live: Fix | None,
    candidate: Fix | None,
) -> PointDecision:
    """Quality flags of one accepted point (K2, §10.4, AC28). Points are processed in ``captured_at`` order.

    * ``low_accuracy``: accuracy worse than 100 m (still trusted, shown as low confidence);
    * ``mock_location``: never trusted, never a plausibility reference;
    * ``out_of_order``: older than the live marker - history only;
    * ``implausible_speed``: faster than ``MAX_PLAUSIBLE_SPEED_MPS`` from the live marker, unless it is plausible from a
      newer candidate (the newest in-order non-mock point, itself possibly flagged). The second consistent point after a
      jump is trusted again, so one wrong reference cannot freeze the marker forever; a single outlier never moves it.
    Only a trusted point strictly newer than the live marker moves it (``contract.is_trusted_for_live``).
    """
    captured_at = ensure_aware_utc(captured_at)
    flags: list[TrackingQualityFlag] = []
    if contract.is_low_accuracy(accuracy_m):
        flags.append(TrackingQualityFlag.LOW_ACCURACY)
    if is_mock:
        flags.append(TrackingQualityFlag.MOCK_LOCATION)
    in_order = live is None or captured_at >= live.captured_at
    if not in_order:
        flags.append(TrackingQualityFlag.OUT_OF_ORDER)
    elif not is_mock and live is not None and captured_at > live.captured_at and _implausible(live, captured_at, lat, lng):
        newer_candidate = candidate is not None and live.captured_at < candidate.captured_at < captured_at
        if not newer_candidate or _implausible(candidate, captured_at, lat, lng):
            flags.append(TrackingQualityFlag.IMPLAUSIBLE_SPEED)
    moves_live = contract.is_trusted_for_live(flags) and (live is None or captured_at > live.captured_at)
    becomes_candidate = (
        not is_mock and in_order and (candidate is None or captured_at > candidate.captured_at)
    )
    return PointDecision(tuple(flags), moves_live, becomes_candidate)


def point_payload_hash(
    *,
    seq: int,
    captured_at: datetime,
    lat: float,
    lng: float,
    accuracy_m: int,
    speed_mps: int | None,
    heading_deg: int | None,
    battery_pct: int | None,
    is_mock: bool,
) -> str:
    """SHA-256 of the canonical point payload: same retry -> duplicate, different payload -> ``payload_conflict``."""
    canonical = json.dumps(
        {
            "seq": seq,
            "captured_at": to_iso_utc(captured_at),
            "lat": repr(float(lat)),
            "lng": repr(float(lng)),
            "accuracy_m": accuracy_m,
            "speed_mps": speed_mps,
            "heading_deg": heading_deg,
            "battery_pct": battery_pct,
            "is_mock": bool(is_mock),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def captured_date(captured_at: datetime):  # noqa: ANN201 - date
    return ensure_aware_utc(captured_at).astimezone(UTC).date()


# --- event payloads (allowlist: no coordinates, phones, names, codes) ---------------------------------------------


def stale_payload(*, trip_public_id: str, last_captured_at: datetime | None) -> dict[str, Any]:
    freshness = TrackingFreshness.NO_DATA if last_captured_at is None else TrackingFreshness.LOST
    return {
        "trip_id": trip_public_id,
        "freshness": freshness.value,
        "last_captured_at": None if last_captured_at is None else to_iso_utc(last_captured_at),
    }


def window_opened_payload(
    *, booking_public_id: str, trip_public_id: str, service_type: str, opens_at: datetime | None
) -> dict[str, Any]:
    return {
        "booking_id": booking_public_id,
        "trip_id": trip_public_id,
        "service_type": service_type,
        "opens_at": None if opens_at is None else to_iso_utc(opens_at),
    }
