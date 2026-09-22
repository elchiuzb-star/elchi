"""Route matching core (spec §6.1-6.5; AC14-AC17, AC35; wave 1.5 BR #1-#4).

All functions except ``measure_detours`` are pure and deterministic. ``measure_detours``
calls the router and must run outside any DB transaction.

Rules:
* Both pickup and dropoff are checked; pickup must come strictly before dropoff in
  **occurrence order** (loops/repeated stops are separate occurrences), so the reverse
  direction is rejected (AC16).
* ETA window at an occurrence: ``[arrival, arrival + max(dwell, 1 min))``, for a pickup
  ``max(pickup_wait, dwell, 1 min)``. ``arrival`` is the occurrence's current planned arrival,
  which already contains accepted detours before it (``apply_insertions``); nothing is added
  to earlier occurrences or to the origin (AC15, BR #1).
* A new pickup detour delays the dropoff by its ``extra_s`` plus the inserted stop dwell.
* Detour budget is cumulative in seconds and metres:
  ``detour_used_s + pickup extra_s + dropoff extra_s <= max_detour_minutes * 60`` and the same
  for metres (AC17, BR #2).
* Two detours on the same leg are rejected (``DETOUR_ORDER_UNKNOWN``): their relative order is
  not measured. Pilot limitation (decision 25).
* Routing outage: stops that needed a router measurement are reported as
  ``ROUTING_UNAVAILABLE`` with ``degraded=True``; no detour is assumed (AC35).
* Production (Q46): no routing provider is enabled, so no quotes exist and results are never
  ``detour``; only verified-stop matches (exact/on_route/alternative) occur there.
* Detour measurements are ``DetourQuote`` snapshots bound to the trip version and route version;
  A4 re-validates them under lock with ``validate_detour_quote`` and checks existing bookings with
  ``verify_existing_windows``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.contracts.detour import detour_legs_conflict
from app.contracts.enums import MatchType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import ensure_aware_utc, utc_now, windows_intersect
from app.modules.geo.geometry import haversine_m
from app.modules.geo.routing.base import RoutingProvider, RoutingUnavailable
from app.modules.geo.types import (
    DETOUR_QUOTE_TTL,
    BookingWindow,
    DetourMeasurements,
    DetourQuote,
    LatLng,
    MatchReason,
    MatchRequest,
    OccurrenceTiming,
    RouteMatchResult,
    ServicePoint,
    TimelineChange,
    TripRouteContext,
)

ALTERNATIVE_TIME_TOLERANCE = timedelta(hours=3)
MIN_ETA_WINDOW = timedelta(minutes=1)

_RANK = {MatchType.EXACT: 0, MatchType.ON_ROUTE: 1, MatchType.DETOUR: 2, MatchType.ALTERNATIVE: 3}


def eta_window(arrival: datetime, dwell_minutes: int, *, pickup_wait_minutes: int | None = None) -> tuple[datetime, datetime]:
    """``[arrival, arrival + span)``; span = max(dwell, 1 min), for pickups also >= pickup wait."""
    span = max(timedelta(minutes=dwell_minutes), MIN_ETA_WINDOW)
    if pickup_wait_minutes is not None:
        span = max(span, timedelta(minutes=pickup_wait_minutes))
    start = ensure_aware_utc(arrival)
    return start, start + span


@dataclass(frozen=True, slots=True)
class _Point:
    kind: str  # "stop" | "detour"
    stop_id: int
    index: int  # occurrence index (stop) or index of the occurrence it follows (detour)
    arrival: datetime
    dwell_minutes: int
    extra_s: int
    extra_m: int
    alternative: bool
    quote: DetourQuote | None = None

    @property
    def order(self) -> tuple[int, int]:
        return (self.index, 0 if self.kind == "stop" else 1)


def _usable_quote(quote: DetourQuote, trip: TripRouteContext, now: datetime | None) -> bool:
    if not quote.matches_trip(trip):
        return False
    if now is None:
        return True
    return quote.is_valid_for(route_version_id=trip.route_version_public_id or "", trip_version=trip.trip_version, now=now)


def _points_for(
    stop_id: int,
    alternatives: Sequence[int],
    trip: TripRouteContext,
    detours: DetourMeasurements,
    include_alternatives: bool,
    now: datetime | None,
) -> list[_Point]:
    occ = trip.occurrences
    index_by_seq = {o.seq: i for i, o in enumerate(occ)}
    points: list[_Point] = []
    for i, o in enumerate(occ):
        if o.stop_id == stop_id:
            points.append(_Point("stop", stop_id, i, o.planned_arrival_at, o.dwell_minutes, 0, 0, False))
    for quote in detours.quotes:
        if quote.stop_id != stop_id or quote.after_seq not in index_by_seq or not _usable_quote(quote, trip, now):
            continue
        k = index_by_seq[quote.after_seq]
        if k >= len(occ) - 1:
            continue  # nothing after the last stop to insert before
        base = occ[k]
        arrival = base.planned_arrival_at + timedelta(minutes=base.dwell_minutes, seconds=quote.arrive_offset_s)
        points.append(
            _Point("detour", stop_id, k, arrival, trip.inserted_stop_dwell_minutes, quote.extra_s, quote.extra_m, False, quote)
        )
    if include_alternatives:
        for alt in dict.fromkeys(alternatives):
            if alt == stop_id:
                continue
            for i, o in enumerate(occ):
                if o.stop_id == alt:
                    points.append(_Point("stop", alt, i, o.planned_arrival_at, o.dwell_minutes, 0, 0, True))
    return points


def _gap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> timedelta:
    if windows_intersect(a0, a1, b0, b1):
        return timedelta(0)
    return b0 - a1 if a1 <= b0 else a0 - b1


def _service_point(p: _Point, trip: TripRouteContext, start: datetime, end: datetime) -> ServicePoint:
    seq = trip.occurrences[p.index].seq
    return ServicePoint(
        kind=p.kind,
        stop_id=p.stop_id,
        occurrence_seq=seq if p.kind == "stop" else None,
        after_seq=seq if p.kind == "detour" else None,
        eta_window_start=start,
        eta_window_end=end,
        is_alternative_stop=p.alternative,
    )


def evaluate_route_match(
    trip: TripRouteContext,
    request: MatchRequest,
    *,
    detours: DetourMeasurements | None = None,
    include_alternatives: bool = False,
    alternative_time_tolerance: timedelta = ALTERNATIVE_TIME_TOLERANCE,
    now: datetime | None = None,
) -> RouteMatchResult:
    """Classify how ``trip`` can serve ``request``. Quotes for another trip/route version, or
    expired at ``now`` (when given), are ignored."""
    measured = detours or DetourMeasurements()
    if measured.quotes and trip.route_version_public_id is None:
        # BR N3: never silently treat measured detours as off-route.
        raise ValueError("trip.route_version_public_id is required when detour quotes are supplied")
    rv = trip.route_version_id

    def failure(code: ErrorCode, *reasons: MatchReason, degraded: bool = False, **details: int | str | bool | None) -> RouteMatchResult:
        return RouteMatchResult(False, None, tuple(dict.fromkeys(reasons)), code, rv, degraded=degraded, details=dict(details))

    if request.pickup_stop_id == request.dropoff_stop_id:
        return failure(ErrorCode.ROUTE_MISMATCH, MatchReason.SAME_STOP)

    pickups = _points_for(request.pickup_stop_id, request.pickup_alternative_stop_ids, trip, measured, include_alternatives, now)
    dropoffs = _points_for(request.dropoff_stop_id, request.dropoff_alternative_stop_ids, trip, measured, include_alternatives, now)

    degraded_reasons: list[MatchReason] = []
    missing: list[MatchReason] = []
    for points, stop_id, missing_reason in (
        (pickups, request.pickup_stop_id, MatchReason.PICKUP_NOT_ON_ROUTE),
        (dropoffs, request.dropoff_stop_id, MatchReason.DROPOFF_NOT_ON_ROUTE),
    ):
        if not any(p.stop_id == stop_id for p in points):
            missing.append(missing_reason)
            if stop_id in measured.unavailable_stop_ids:
                degraded_reasons.append(MatchReason.ROUTING_UNAVAILABLE)
    degraded = bool(degraded_reasons)
    last_index = len(trip.occurrences) - 1

    best: tuple[tuple[int, int, int, tuple[int, int], tuple[int, int]], RouteMatchResult] | None = None
    reverse_seen = order_unknown = time_failed = detour_failed = False
    detour_fail_details: dict[str, int] = {}

    for p in pickups:
        for d in dropoffs:
            if p.order == d.order:
                order_unknown = True  # two detours on the same leg: relative order not measured (decision 25)
                continue
            if p.order > d.order:
                reverse_seen = True
                continue
            new_s = p.extra_s + d.extra_s
            new_m = p.extra_m + d.extra_m
            p_start, p_end = eta_window(p.arrival, p.dwell_minutes, pickup_wait_minutes=trip.pickup_wait_minutes)
            delay_s = p.extra_s + (p.dwell_minutes * 60 if p.kind == "detour" else 0)
            d_start, d_end = eta_window(d.arrival + timedelta(seconds=delay_s), d.dwell_minutes)
            gaps = [_gap(p_start, p_end, request.pickup_window_start, request.pickup_window_end)]
            if request.dropoff_window_start is not None and request.dropoff_window_end is not None:
                gaps.append(_gap(d_start, d_end, request.dropoff_window_start, request.dropoff_window_end))
            time_ok = all(g == timedelta(0) for g in gaps)
            uses_alt = p.alternative or d.alternative
            uses_detour = p.kind == "detour" or d.kind == "detour"

            if not time_ok and not (include_alternatives and max(gaps) <= alternative_time_tolerance):
                time_failed = True
                continue
            if not cumulative_detour_allowed(
                detour_used_s=trip.detour_used_s,
                detour_used_m=trip.detour_used_m,
                added_s=new_s,
                added_m=new_m,
                max_detour_minutes=trip.max_detour_minutes,
                max_detour_m=trip.max_detour_m,
            ):
                detour_failed = True
                detour_fail_details = {
                    "detour_used_s": trip.detour_used_s,
                    "detour_added_s": new_s,
                    "max_detour_s": trip.max_detour_s,
                    "detour_used_m": trip.detour_used_m,
                    "detour_added_m": new_m,
                    "max_detour_m": trip.max_detour_m,
                }
                continue

            reasons: list[MatchReason] = []
            if time_ok and not uses_alt:
                if uses_detour:
                    match_type = MatchType.DETOUR
                elif p.index == 0 and d.index == last_index:
                    match_type = MatchType.EXACT
                else:
                    match_type = MatchType.ON_ROUTE
            else:
                match_type = MatchType.ALTERNATIVE
                if uses_alt:
                    reasons.append(MatchReason.NEARBY_STOP)
                if not time_ok:
                    reasons.append(MatchReason.TIME_DIFFERS)
            if match_type is MatchType.EXACT:
                reasons.insert(0, MatchReason.FULL_ROUTE)
            elif not uses_detour:
                reasons.insert(0, MatchReason.INTERMEDIATE_SEGMENT)
            reasons.append(MatchReason.PICKUP_DETOUR if p.kind == "detour" else MatchReason.PICKUP_AT_STOP)
            reasons.append(MatchReason.DROPOFF_DETOUR if d.kind == "detour" else MatchReason.DROPOFF_AT_STOP)
            reasons.extend(degraded_reasons)

            result = RouteMatchResult(
                matched=True,
                match_type=match_type,
                reasons=tuple(dict.fromkeys(reasons)),
                error_code=None,
                route_version_id=rv,
                pickup=_service_point(p, trip, p_start, p_end),
                dropoff=_service_point(d, trip, d_start, d_end),
                detour_s=new_s,
                detour_m=new_m,
                detour_minutes=math.ceil(new_s / 60),
                is_estimate=uses_detour or trip.schedule_is_estimate,
                degraded=degraded,
                detour_quotes=tuple(q for q in (p.quote, d.quote) if q is not None),
            )
            key = (_RANK[match_type], new_s, new_m, p.order, d.order)
            if best is None or key < best[0]:
                best = (key, result)

    if best is not None:
        return best[1]
    if detour_failed:
        return failure(ErrorCode.DETOUR_LIMIT_EXCEEDED, MatchReason.DETOUR_LIMIT_EXCEEDED, *degraded_reasons, degraded=degraded, **detour_fail_details)
    if time_failed:
        return failure(ErrorCode.TIME_WINDOW_CONFLICT, MatchReason.TIME_WINDOW_MISMATCH, *degraded_reasons, degraded=degraded)
    if reverse_seen:
        return failure(ErrorCode.ROUTE_MISMATCH, MatchReason.REVERSE_DIRECTION, degraded=degraded)
    if degraded:
        return failure(ErrorCode.ROUTING_UNAVAILABLE, *missing, *degraded_reasons, degraded=True)
    if order_unknown:
        return failure(ErrorCode.ROUTE_MISMATCH, MatchReason.DETOUR_ORDER_UNKNOWN)
    return failure(ErrorCode.ROUTE_MISMATCH, *missing)


def cumulative_detour_allowed(
    *,
    detour_used_s: int,
    detour_used_m: int,
    added_s: int,
    added_m: int,
    max_detour_minutes: int,
    max_detour_m: int,
) -> bool:
    """AC17: the sum of all detours (seconds, metres) must stay within the trip limit."""
    return detour_used_s + added_s <= max_detour_minutes * 60 and detour_used_m + added_m <= max_detour_m


# --- quotes, timeline and existing bookings (A4 accept, under lock, no router) ---------------------


def _route_changed(reason: str, **details: int | str) -> DomainError:
    return DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": reason, **details})


def validate_detour_quote(quote: DetourQuote, trip: TripRouteContext, *, now: datetime | None = None) -> None:
    """Freshness check of a stored quote against the locked trip. Raises ``409 ROUTE_CHANGED``."""
    current = ensure_aware_utc(now) if now is not None else utc_now()
    if trip.route_version_public_id is None:
        raise ValueError("trip.route_version_public_id is required to validate detour quotes")
    if quote.route_version_id != trip.route_version_public_id:
        raise _route_changed("route_version_changed")
    if quote.trip_version != trip.trip_version:
        raise _route_changed("trip_version_changed", quote_trip_version=quote.trip_version, trip_version=trip.trip_version)
    if not quote.is_valid_for(route_version_id=trip.route_version_public_id, trip_version=trip.trip_version, now=current):
        raise _route_changed("detour_quote_expired")
    seqs = [o.seq for o in trip.occurrences]
    if quote.after_seq not in seqs or quote.after_seq == seqs[-1]:
        raise _route_changed("after_seq_missing", after_seq=quote.after_seq)


def validate_detour_quotes(quotes: Sequence[DetourQuote], trip: TripRouteContext, *, now: datetime | None = None) -> None:
    for quote in quotes:
        validate_detour_quote(quote, trip, now=now)
    if detour_legs_conflict(tuple(quotes)):
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": MatchReason.DETOUR_ORDER_UNKNOWN.value})


def apply_insertions(
    occurrences: Sequence[OccurrenceTiming],
    quotes: Sequence[DetourQuote],
    *,
    inserted_dwell_minutes: int = 0,
) -> TimelineChange:
    """New trip timeline after inserting detour stops (pure).

    Inserted arrival = departure of ``after_seq`` + ``arrive_offset_s``; every later occurrence
    shifts by ``extra_s`` + inserted dwell. Earlier occurrences (and the origin) never move.
    Seqs after an insertion are renumbered; ``seq_map`` gives old -> new.
    """
    occ = tuple(occurrences)
    seqs = [o.seq for o in occ]
    ordered = sorted(quotes, key=lambda q: q.after_seq, reverse=True)
    if detour_legs_conflict(tuple(ordered)):
        raise ValueError("two detours on the same leg are not supported (decision 25)")
    # items: (old_seq | None, stop_id, arrival, dwell_minutes)
    items: list[tuple[int | None, int, datetime, int]] = [(o.seq, o.stop_id, o.planned_arrival_at, o.dwell_minutes) for o in occ]
    dwell_delay = timedelta(minutes=inserted_dwell_minutes)
    for quote in ordered:
        if quote.after_seq not in seqs or quote.after_seq == seqs[-1]:
            raise ValueError(f"after_seq {quote.after_seq} is not an inner leg of this timeline")
        k = next(i for i, item in enumerate(items) if item[0] == quote.after_seq)
        base = items[k]
        arrival = base[2] + timedelta(minutes=base[3], seconds=quote.arrive_offset_s)
        shift = timedelta(seconds=quote.extra_s) + dwell_delay
        items = items[: k + 1] + [(None, quote.stop_id, arrival, inserted_dwell_minutes)] + [
            (s, stop, at + shift, dwell) for s, stop, at, dwell in items[k + 1 :]
        ]
    new_occurrences: list[OccurrenceTiming] = []
    seq_map: dict[int, int] = {}
    inserted: dict[int, int] = {}
    inserted_count = 0
    previous_new = -1
    previous_old: int | None = None
    for old_seq, stop_id, arrival, dwell in items:
        if old_seq is None:
            inserted_count += 1
            new_seq = previous_new + 1
            inserted[previous_old if previous_old is not None else -1] = new_seq
        else:
            new_seq = old_seq + inserted_count
            seq_map[old_seq] = new_seq
            previous_old = old_seq
        new_occurrences.append(OccurrenceTiming(new_seq, stop_id, arrival, dwell))
        previous_new = new_seq
    inserted_seqs = tuple(inserted[q.after_seq] for q in sorted(quotes, key=lambda q: q.after_seq))
    return TimelineChange(tuple(new_occurrences), seq_map, inserted_seqs)


def verify_existing_windows(
    trip: TripRouteContext,
    existing_booking_windows: Sequence[BookingWindow],
    insertion: DetourQuote | Sequence[DetourQuote],
) -> TimelineChange:
    """Reject an insertion that breaks an existing booking's agreed window (spec §6.4). Pure.

    A window counts as broken if the occurrence's ETA window intersected the agreed window before
    the insertion and no longer does after it. Raises ``409 TIME_WINDOW_CONFLICT`` with
    ``details.bookings``; returns the new timeline otherwise.
    """
    quotes = (insertion,) if isinstance(insertion, DetourQuote) else tuple(insertion)
    change = apply_insertions(trip.occurrences, quotes, inserted_dwell_minutes=trip.inserted_stop_dwell_minutes)
    before = {o.seq: o for o in trip.occurrences}
    after = {o.seq: o for o in change.occurrences}
    broken: list[str] = []
    for window in existing_booking_windows:
        if window.occurrence_seq not in before:
            raise ValueError(f"booking {window.booking_ref} references unknown occurrence {window.occurrence_seq}")
        wait = trip.pickup_wait_minutes if window.kind == "pickup" else None
        old = before[window.occurrence_seq]
        new = after[change.seq_map[window.occurrence_seq]]
        old_eta = eta_window(old.planned_arrival_at, old.dwell_minutes, pickup_wait_minutes=wait)
        new_eta = eta_window(new.planned_arrival_at, new.dwell_minutes, pickup_wait_minutes=wait)
        ok_before = windows_intersect(*old_eta, window.window_start, window.window_end)
        ok_after = windows_intersect(*new_eta, window.window_start, window.window_end)
        if ok_before and not ok_after:
            broken.append(window.booking_ref)
    if broken:
        raise DomainError(
            ErrorCode.TIME_WINDOW_CONFLICT,
            details={"reason": "breaks_existing_booking_windows", "bookings": sorted(set(broken))},
        )
    return change


# --- router probes (outside transactions) ------------------------------------------------------


def measure_detours(
    provider: RoutingProvider,
    trip: TripRouteContext,
    request: MatchRequest,
    stop_points: Mapping[int, LatLng],
    *,
    now: datetime | None = None,
    ttl: timedelta = DETOUR_QUOTE_TTL,
) -> DetourMeasurements:
    """Measure detours for request stops that are not trip occurrences. No DB access.

    For each such stop the two legs adjacent to the nearest occurrence are probed (via-route and
    direct leg, same provider). If any probe fails, that stop is reported unavailable and none of
    its partial measurements are used. Each measurement becomes a ``DetourQuote``.
    """
    measured_at = ensure_aware_utc(now) if now is not None else utc_now()
    if trip.route_version_public_id is None:
        raise ValueError("trip.route_version_public_id is required to produce detour quotes")
    occ = trip.occurrences
    on_route = {o.stop_id for o in occ}
    needed = [sid for sid in dict.fromkeys((request.pickup_stop_id, request.dropoff_stop_id)) if sid not in on_route]
    quotes: list[DetourQuote] = []
    unavailable: set[int] = set()
    for stop_id in needed:
        try:
            target = stop_points[stop_id]
            occ_points = [stop_points[o.stop_id] for o in occ]
        except KeyError as exc:
            raise ValueError(f"missing coordinates for stop {exc.args[0]}") from None
        nearest = min(range(len(occ)), key=lambda i: (haversine_m(occ_points[i], target), i))
        legs = sorted({j for j in (nearest - 1, nearest) if 0 <= j < len(occ) - 1})
        found: list[DetourQuote] = []
        try:
            for j in legs:
                a, b = occ_points[j], occ_points[j + 1]
                via = provider.route([a, target, b])
                direct = provider.route([a, b])
                found.append(
                    DetourQuote(
                        route_version_id=trip.route_version_public_id,
                        trip_version=trip.trip_version,
                        stop_id=stop_id,
                        after_seq=occ[j].seq,
                        arrive_offset_s=via.legs[0].duration_s,
                        extra_s=max(0, via.duration_s - direct.duration_s),
                        extra_m=max(0, via.distance_m - direct.distance_m),
                        measured_at=measured_at,
                        expires_at=measured_at + ttl,
                        provider=provider.name,
                        provider_version=provider.version,
                    )
                )
        except RoutingUnavailable:
            unavailable.add(stop_id)
            continue
        quotes.extend(found)
    return DetourMeasurements(tuple(quotes), frozenset(unavailable), provider=getattr(provider, "name", None))
