"""GPS tracking constants and pure helpers (spec §10.3, §10.4, §10.6, §10.7, §13; D18).

Values are pilot defaults from the spec; field testing may change them through a
contract update. Retention values are *proposed* and subject to legal review
(spec §10.7, ADR-0011).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.contracts.enums import (
    ParcelBookingStatus,
    PassengerBookingStatus,
    ServiceType,
    TrackingFreshness,
    TrackingPointRejectReason,
    TrackingQualityFlag,
    TrackingWindowReason,
    TripStatus,
)
from app.contracts.timeutil import ensure_aware_utc

# §10.4 UI freshness: 0-30 s fresh, 31-120 s delayed, >120 s "aloqa uzilgan" (lost).
FRESH_MAX_AGE_SECONDS = 30
DELAYED_MAX_AGE_SECONDS = 120
# §10.4: accuracy worse than 100 m is low confidence.
LOW_ACCURACY_THRESHOLD_M = 100
# §10.4 pilot batch and queue limits.
MAX_POINTS_PER_BATCH = 100
MAX_POINT_AGE = timedelta(hours=24)  # older uploads are rejected from normal ingestion
LOCAL_QUEUE_MAX_AGE = timedelta(hours=24)
LOCAL_QUEUE_MAX_POINTS = 20_000
# §10.3 send-interval targets (app configuration, not an OS guarantee).
SEND_INTERVAL_MOVING_SECONDS = 10
SEND_INTERVAL_WAITING_SECONDS = (30, 60)
SEND_INTERVAL_APPROACHING_SECONDS = (5, 10)
# §10.6: passenger tracking opens 30 minutes before the agreed pickup.
PASSENGER_TRACKING_OPENS_BEFORE_PICKUP = timedelta(minutes=30)
# §10.7 / §13 proposed retention.
RAW_POINT_RETENTION = timedelta(days=7)
SIMPLIFIED_TRACK_RETENTION = timedelta(days=30)
POINT_RECEIPT_RETENTION = timedelta(days=8)
# M1 (wave 3.1): a disputed trip's raw points are copied into tracking_evidence_points while the hold is open, so
# they outlive RAW_POINT_RETENTION; the copy is deleted this long after the hold was released.
EVIDENCE_RETENTION_AFTER_RELEASE = timedelta(days=30)
# §10.6: share/tracking tokens carry at least 128 random bits from
# `secrets.token_bytes` (see app.contracts.crypto.new_secret_token); uuid4 is
# an identifier, not a secret, and must not be used as a token.
TRACKING_TOKEN_MIN_BYTES = 16
TRACKING_TOKEN_BYTES = 32


def freshness_for_age(age_seconds: float | int | None) -> TrackingFreshness:
    """Bucket the age of the last trusted point; ``None`` means no point yet."""
    if age_seconds is None:
        return TrackingFreshness.NO_DATA
    if isinstance(age_seconds, bool) or not isinstance(age_seconds, (int, float)):
        raise TypeError("age_seconds must be a number")
    if age_seconds < 0:
        raise ValueError("age_seconds must not be negative; reject future timestamps at ingestion")
    if age_seconds <= FRESH_MAX_AGE_SECONDS:
        return TrackingFreshness.FRESH
    if age_seconds <= DELAYED_MAX_AGE_SECONDS:
        return TrackingFreshness.DELAYED
    return TrackingFreshness.LOST


def freshness_at(last_captured_at: datetime | None, now: datetime) -> TrackingFreshness:
    if last_captured_at is None:
        return TrackingFreshness.NO_DATA
    age = (ensure_aware_utc(now) - ensure_aware_utc(last_captured_at)).total_seconds()
    return freshness_for_age(max(age, 0.0))


def is_low_accuracy(accuracy_m: float | int) -> bool:
    if isinstance(accuracy_m, bool) or not isinstance(accuracy_m, (int, float)) or accuracy_m < 0:
        raise ValueError("accuracy_m must be a non-negative number")
    return accuracy_m > LOW_ACCURACY_THRESHOLD_M


def is_too_old_for_ingestion(captured_at: datetime, received_at: datetime) -> bool:
    return ensure_aware_utc(received_at) - ensure_aware_utc(captured_at) > MAX_POINT_AGE


# --- wave 3 (16.09.2026, A6): ingestion limits, point quality, tracking window ------------------------------------

# Point payload units are integers (AGENTS §6): accuracy_m, speed_mps, heading_deg, battery_pct. lat/lng are WGS84
# degrees (JSON numbers) validated by app.contracts.dto.TrackingPointIn and stored as geometry(Point, 4326).
MAX_ACCURACY_M = 10_000  # a larger value is `invalid`
MAX_SPEED_MPS_INPUT = 100  # device-reported speed above this is `invalid`
MAX_FUTURE_SKEW = timedelta(seconds=60)  # same clock-skew tolerance as the wallet guards
# Pilot plausibility bound between two consecutive trusted points (252 km/h); a faster jump is flagged, not rejected.
MAX_PLAUSIBLE_SPEED_MPS = 70
RECOMMENDED_INTERVAL_SECONDS = SEND_INTERVAL_MOVING_SECONDS  # TrackingSessionDTO.recommended_interval_s
# §10.3 fallback for clients without a WebSocket: HTTP snapshot polling.
SNAPSHOT_POLL_INTERVAL_SECONDS = (10, 15)
WS_PUSH_INTERVAL_SECONDS = 5  # server-side snapshot push cadence of K8 (no pub/sub dependency in the pilot)
# K5 recipient link TTL bounds; the link also closes with the booking (§10.6).
TRACKING_GRANT_MIN_TTL = timedelta(minutes=15)
TRACKING_GRANT_MAX_TTL = timedelta(hours=24)
# Stable label key: GPS follows the driver's phone, never "the parcel's device" (§10.3).
TRACKING_SUBJECT_LABEL_KEY = "vehicle_carrying_your_booking"

UNTRUSTED_QUALITY_FLAGS: frozenset[TrackingQualityFlag] = frozenset(
    {TrackingQualityFlag.MOCK_LOCATION, TrackingQualityFlag.IMPLAUSIBLE_SPEED, TrackingQualityFlag.OUT_OF_ORDER}
)


def point_rejection(captured_at: datetime, received_at: datetime) -> TrackingPointRejectReason | None:
    """Time-based rejection of one ingested point (K2); ``None`` means acceptable."""
    captured = ensure_aware_utc(captured_at)
    received = ensure_aware_utc(received_at)
    if captured - received > MAX_FUTURE_SKEW:
        return TrackingPointRejectReason.FUTURE_TIMESTAMP
    if received - captured > MAX_POINT_AGE:
        return TrackingPointRejectReason.TOO_OLD
    return None


def is_implausible_speed(distance_m: int, elapsed_seconds: float) -> bool:
    """Distance between two trusted points against :data:`MAX_PLAUSIBLE_SPEED_MPS` (pure; A6 measures the distance)."""
    if isinstance(distance_m, bool) or not isinstance(distance_m, int) or distance_m < 0:
        raise ValueError("distance_m must be a non-negative int")
    if elapsed_seconds <= 0:
        return distance_m > MAX_PLAUSIBLE_SPEED_MPS
    return distance_m / elapsed_seconds > MAX_PLAUSIBLE_SPEED_MPS


def is_trusted_for_live(flags: Iterable[TrackingQualityFlag | str]) -> bool:
    """Only trusted points move the live marker and freshness (§10.4, AC28). Low accuracy stays trusted."""
    return not ({TrackingQualityFlag(flag) for flag in flags} & UNTRUSTED_QUALITY_FLAGS)


PASSENGER_TRACKING_STATUSES: frozenset[str] = frozenset(
    {PassengerBookingStatus.CONFIRMED.value, PassengerBookingStatus.AWAITING_PICKUP.value,
     PassengerBookingStatus.ONBOARD.value}
)
PARCEL_TRACKING_STATUSES: frozenset[str] = frozenset(
    {ParcelBookingStatus.PICKED_UP.value, ParcelBookingStatus.IN_TRANSIT.value,
     ParcelBookingStatus.DELIVERY_FAILED.value, ParcelBookingStatus.RETURN_REQUIRED.value}
)
PARCEL_BEFORE_PICKUP_STATUSES: frozenset[str] = frozenset(
    {ParcelBookingStatus.CONFIRMED.value, ParcelBookingStatus.AWAITING_PICKUP.value}
)
TRACKING_TRIP_TERMINAL_STATUSES: frozenset[str] = frozenset({TripStatus.COMPLETED.value, TripStatus.CANCELLED.value})


@dataclass(frozen=True, slots=True)
class TrackingWindow:
    is_open: bool
    reason: TrackingWindowReason
    opens_at: datetime | None = None


def tracking_window(
    *,
    service_type: ServiceType | str,
    service_status: str,
    trip_status: TripStatus | str,
    pickup_window_start: datetime,
    now: datetime,
) -> TrackingWindow:
    """Live-location visibility for a booking participant or its recipient link (§10.6, AC44, Q44).

    * trip completed/cancelled -> closed (the next ride of the vehicle is never visible, §10.3 step 6);
    * passenger: open from ``pickup_window_start - 30 min`` (or once ``onboard``) until ``arrived``/terminal;
    * parcel: open from ``picked_up`` until ``delivered``/terminal (custody states stay open); not before pickup.
    Computed at read time, so no revoke job is needed for correctness; grants add their own ``valid_until``.
    """
    if TripStatus(trip_status).value in TRACKING_TRIP_TERMINAL_STATUSES:
        return TrackingWindow(False, TrackingWindowReason.TRIP_FINISHED)
    if ServiceType(service_type) is ServiceType.PASSENGER:
        if service_status not in PASSENGER_TRACKING_STATUSES:
            return TrackingWindow(False, TrackingWindowReason.BOOKING_FINISHED)
        opens_at = ensure_aware_utc(pickup_window_start) - PASSENGER_TRACKING_OPENS_BEFORE_PICKUP
        if service_status == PassengerBookingStatus.ONBOARD.value or ensure_aware_utc(now) >= opens_at:
            return TrackingWindow(True, TrackingWindowReason.OPEN, opens_at)
        return TrackingWindow(False, TrackingWindowReason.NOT_YET_OPEN, opens_at)
    if service_status in PARCEL_TRACKING_STATUSES:
        return TrackingWindow(True, TrackingWindowReason.OPEN)
    if service_status in PARCEL_BEFORE_PICKUP_STATUSES:
        return TrackingWindow(False, TrackingWindowReason.PARCEL_NOT_PICKED_UP)
    return TrackingWindow(False, TrackingWindowReason.BOOKING_FINISHED)
