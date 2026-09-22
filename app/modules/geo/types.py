"""Geo value objects shared with other modules (A1 trips/marketplace, A4 accept, A5 feed).

Plain frozen dataclasses: no DB, no settings, no I/O. Units follow the contracts:
distances in integer metres (``*_m``), durations in integer seconds (``*_s``) or
minutes (``*_minutes``), datetimes timezone-aware (``app.contracts.timeutil``).
Coordinates are WGS84 degrees (floats are fine here; money never is).

Timeline rule (wave 1.5, BR #1/#2): ``OccurrenceTiming.planned_arrival_at`` is the
trip's *current* arrival at that occurrence, i.e. planned start + preceding legs +
dwell + every accepted detour located BEFORE it. A4 maintains it on accept with
``matching.apply_insertions``. There is no blanket slack. The detour budget is tracked
in seconds and metres (``detour_used_s``/``detour_used_m``) against
``max_detour_minutes * 60`` and ``max_detour_m``; minutes are only rounded up for display.

``DetourQuote`` extends ``app.contracts.detour.DetourQuote``. Contract request (A0a): promote
``BookingWindow``/``TimelineChange`` and the geo quote extension fields if other modules need them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.contracts.detour import DEFAULT_DETOUR_QUOTE_TTL
from app.contracts.detour import DetourQuote as ContractDetourQuote
from app.contracts.enums import MatchReason, MatchType
from app.contracts.errors import ErrorCode
from app.contracts.timeutil import ensure_aware_utc

__all__ = [
    "DETOUR_QUOTE_TTL",
    "BookingWindow",
    "DetourMeasurements",
    "DetourQuote",
    "LatLng",
    "MatchReason",
    "MatchRequest",
    "OccurrenceTiming",
    "RouteMatchResult",
    "ServicePoint",
    "TimelineChange",
    "TripRouteContext",
]

# A router measurement is trusted for this long (contract default); after it A4 re-measures outside the transaction.
DETOUR_QUOTE_TTL = DEFAULT_DETOUR_QUOTE_TTL


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


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


@dataclass(frozen=True, slots=True)
class OccurrenceTiming:
    """One stop occurrence of a trip (A1 ``trip_stop_occurrences``), in trip order.

    A repeated physical stop (loop route) appears as separate occurrences with
    different ``seq``; matching uses this order, never only ``ST_LineLocatePoint``.
    ``planned_arrival_at`` already includes accepted detours before this occurrence.
    """

    seq: int
    stop_id: int
    planned_arrival_at: datetime
    dwell_minutes: int = 0

    def __post_init__(self) -> None:
        _require_int(self.seq, "seq")
        _require_int(self.stop_id, "stop_id", minimum=1)
        _require_int(self.dwell_minutes, "dwell_minutes")
        object.__setattr__(self, "planned_arrival_at", ensure_aware_utc(self.planned_arrival_at, field="planned_arrival_at"))


@dataclass(frozen=True, slots=True)
class TripRouteContext:
    """Everything route matching needs about one trip. Built by the trips module (A1) under its lock."""

    route_version_id: int
    trip_version: int
    occurrences: tuple[OccurrenceTiming, ...]
    max_detour_minutes: int
    max_detour_m: int
    detour_used_s: int = 0
    detour_used_m: int = 0
    pickup_wait_minutes: int = 10
    # Stop time assumed at a newly inserted (detour) stop; delays every later occurrence.
    inserted_stop_dwell_minutes: int = 0
    schedule_is_estimate: bool = True
    # ``rtv_...`` public id; required to measure or use detour quotes (contract quotes carry the public id).
    route_version_public_id: str | None = None

    def __post_init__(self) -> None:
        _require_int(self.route_version_id, "route_version_id", minimum=1)
        _require_int(self.trip_version, "trip_version", minimum=1)
        for name in (
            "max_detour_minutes",
            "max_detour_m",
            "detour_used_s",
            "detour_used_m",
            "pickup_wait_minutes",
            "inserted_stop_dwell_minutes",
        ):
            _require_int(getattr(self, name), name)
        if self.detour_used_s > self.max_detour_s or self.detour_used_m > self.max_detour_m:
            raise ValueError("detour already used exceeds the trip limit")
        occurrences = tuple(self.occurrences)
        if len(occurrences) < 2:
            raise ValueError("a trip needs at least two stop occurrences")
        for previous, current in zip(occurrences, occurrences[1:]):
            if current.seq <= previous.seq:
                raise ValueError("occurrence seq must be strictly increasing")
            if current.planned_arrival_at < previous.planned_arrival_at:
                raise ValueError("planned arrivals must not go back in time")
        object.__setattr__(self, "occurrences", occurrences)

    @property
    def max_detour_s(self) -> int:
        return self.max_detour_minutes * 60


@dataclass(frozen=True, slots=True)
class MatchRequest:
    """A demand to serve: pickup/dropoff corridor stops and the client's windows ``[start, end)``."""

    pickup_stop_id: int
    dropoff_stop_id: int
    pickup_window_start: datetime
    pickup_window_end: datetime
    dropoff_window_start: datetime | None = None
    dropoff_window_end: datetime | None = None
    # Other active stops near the requested ones (from ``service.nearby_stop_ids``);
    # used only for ``alternative`` results.
    pickup_alternative_stop_ids: tuple[int, ...] = ()
    dropoff_alternative_stop_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _require_int(self.pickup_stop_id, "pickup_stop_id", minimum=1)
        _require_int(self.dropoff_stop_id, "dropoff_stop_id", minimum=1)
        start = ensure_aware_utc(self.pickup_window_start, field="pickup_window_start")
        end = ensure_aware_utc(self.pickup_window_end, field="pickup_window_end")
        if end <= start:
            raise ValueError("pickup window end must be after start")
        object.__setattr__(self, "pickup_window_start", start)
        object.__setattr__(self, "pickup_window_end", end)
        if (self.dropoff_window_start is None) != (self.dropoff_window_end is None):
            raise ValueError("dropoff window needs both start and end")
        if self.dropoff_window_start is not None:
            d_start = ensure_aware_utc(self.dropoff_window_start, field="dropoff_window_start")
            d_end = ensure_aware_utc(self.dropoff_window_end, field="dropoff_window_end")  # type: ignore[arg-type]
            if d_end <= d_start:
                raise ValueError("dropoff window end must be after start")
            object.__setattr__(self, "dropoff_window_start", d_start)
            object.__setattr__(self, "dropoff_window_end", d_end)
        object.__setattr__(self, "pickup_alternative_stop_ids", tuple(self.pickup_alternative_stop_ids))
        object.__setattr__(self, "dropoff_alternative_stop_ids", tuple(self.dropoff_alternative_stop_ids))


@dataclass(frozen=True, slots=True)
class DetourQuote(ContractDetourQuote):
    """Geo extension of ``app.contracts.detour.DetourQuote`` (A0a).

    Contract fields: ``route_version_id`` (``rtv_...`` public id), ``trip_version``, ``after_seq``,
    ``extra_s``, ``extra_m``, ``measured_at``, ``expires_at``. Geo adds what is needed to rebuild the
    timeline: the served ``stop_id``, ``arrive_offset_s`` (driving time from leaving ``after_seq``
    to the stop) and the measuring provider. Instances are valid contract quotes
    (``is_valid_for``, ``detour_legs_conflict``, ``total_detour_seconds``).
    A4 validates it under the trip lock with ``matching.validate_detour_quote`` (no router call).
    """

    stop_id: int
    arrive_offset_s: int
    provider: str
    provider_version: str

    def __post_init__(self) -> None:
        ContractDetourQuote.__post_init__(self)
        _require_int(self.stop_id, "stop_id", minimum=1)
        _require_int(self.arrive_offset_s, "arrive_offset_s")
        if not self.provider:
            raise ValueError("provider is required")

    def matches_trip(self, trip: TripRouteContext) -> bool:
        return (
            trip.route_version_public_id is not None
            and self.route_version_id == trip.route_version_public_id
            and self.trip_version == trip.trip_version
        )


@dataclass(frozen=True, slots=True)
class DetourMeasurements:
    quotes: tuple[DetourQuote, ...] = ()
    # Stops whose detour could not be measured because the router failed (AC35).
    unavailable_stop_ids: frozenset[int] = frozenset()
    provider: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quotes", tuple(self.quotes))
        object.__setattr__(self, "unavailable_stop_ids", frozenset(self.unavailable_stop_ids))


@dataclass(frozen=True, slots=True)
class BookingWindow:
    """An existing booking's agreed window at one occurrence (input to ``verify_existing_windows``)."""

    booking_ref: str
    occurrence_seq: int
    kind: Literal["pickup", "dropoff"]
    window_start: datetime
    window_end: datetime

    def __post_init__(self) -> None:
        _require_int(self.occurrence_seq, "occurrence_seq")
        if self.kind not in ("pickup", "dropoff"):
            raise ValueError("kind must be pickup or dropoff")
        start = ensure_aware_utc(self.window_start, field="window_start")
        end = ensure_aware_utc(self.window_end, field="window_end")
        if end <= start:
            raise ValueError("window end must be after start")
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)


@dataclass(frozen=True, slots=True)
class TimelineChange:
    """Result of ``apply_insertions``: the new occurrence timeline.

    ``seq_map`` maps every old seq to its new seq (insertions renumber later occurrences,
    so A4 must remap booking/segment references); ``inserted_seqs`` are the new stops' seqs
    in ascending ``after_seq`` order of the quotes.
    """

    occurrences: tuple[OccurrenceTiming, ...]
    seq_map: dict[int, int]
    inserted_seqs: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ServicePoint:
    """Where and when a pickup or dropoff happens in a match result."""

    kind: str  # "stop" (existing occurrence) or "detour" (new stop inserted after ``after_seq``)
    stop_id: int
    occurrence_seq: int | None
    after_seq: int | None
    eta_window_start: datetime
    eta_window_end: datetime
    is_alternative_stop: bool = False


@dataclass(frozen=True, slots=True)
class RouteMatchResult:
    """Deterministic outcome of :func:`app.modules.geo.matching.evaluate_route_match`.

    ``matched=False`` always carries ``error_code`` (``ROUTE_MISMATCH``,
    ``DETOUR_LIMIT_EXCEEDED``, ``TIME_WINDOW_CONFLICT`` or ``ROUTING_UNAVAILABLE``).
    ``degraded=True`` means a routing outage prevented part of the evaluation;
    the result never claims a match the data does not support (AC35).
    ``detour_quotes`` are the measurements the match relies on (snapshot them with the proposal).
    """

    matched: bool
    match_type: MatchType | None
    reasons: tuple[MatchReason, ...]
    error_code: ErrorCode | None
    route_version_id: int
    pickup: ServicePoint | None = None
    dropoff: ServicePoint | None = None
    detour_s: int = 0
    detour_m: int = 0
    detour_minutes: int = 0
    is_estimate: bool = True
    degraded: bool = False
    detour_quotes: tuple[DetourQuote, ...] = ()
    details: dict[str, int | str | bool | None] = field(default_factory=dict)

    @property
    def pickup_eta_window_start(self) -> datetime | None:
        return self.pickup.eta_window_start if self.pickup else None

    @property
    def pickup_eta_window_end(self) -> datetime | None:
        return self.pickup.eta_window_end if self.pickup else None
