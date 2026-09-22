"""Pure ranking and matching rules for the feed (spec §6.4, §8.2-§8.4; AC36). No I/O.

Formulas (contract weights in ``app.contracts.feed``):

* client ``score = 100 * (0.30M + 0.20T + 0.20R + 0.20P + 0.10E)`` (§8.2)
* driver ``score = 100 * (0.35M + 0.20T + 0.20Y + 0.15C + 0.10F)`` (§8.4)
* ``M`` = ``MATCH_TYPE_SCORE`` (alternatives are a separate group, M = 0 inside it)
* ``T = max(0, 1 - |eta - desired| / tolerated_minutes)``; the feed uses the midpoint of the wanted window as
  ``desired`` and the window length as tolerance (tolerance 0 -> 1 only for an exact time)
* ``R = 0.60 * adjusted_rating/5 + 0.25 * C + 0.15 * O`` with the priors of ``app.contracts.trust``
* ``P = clip((U - total) / (U - L), 0, 1)`` on the **total** for the same quantity; no trusted band or U == L -> 0.5
* ``E = min(1, ln(1 + completed_trips) / ln(1 + EXPERIENCE_LOG_BASE_TRIPS))``
* ``Y = clip(net / reference_net - 0.5, 0, 1)``; a higher total never lowers Y (§8.4: cheapness is not rewarded);
  no reference -> 0.5
* ``F = requested / min_remaining`` on the segment (0-1); insufficient capacity is a hard reject, unknown -> 0.5
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta

from app.contracts.enums import FeedSort, MatchGroup, MatchType, PriceBasis, ServiceType
from app.contracts.feed import (
    CLIENT_SCORE_WEIGHTS,
    DRIVER_SCORE_WEIGHTS,
    EXPERIENCE_LOG_BASE_TRIPS,
    MATCH_TYPE_SCORE,
    NEUTRAL_FIT_SCORE,
    NEUTRAL_PRICE_SCORE,
    RELIABILITY_WEIGHTS,
)
from app.contracts.timeutil import ensure_aware_utc
from app.contracts.trust import ON_TIME_PRIOR, RATING_PRIOR_WEIGHT, ReputationSummary

# Module configuration (not contract): bounded work per feed request.
FEED_CANDIDATE_LIMIT = 500  # listings evaluated per request (pilot scale)
REGION_STOP_LIMIT = 20  # active stops taken from a region end
ON_TIME_PRIOR_WEIGHT = 10  # same prior weight as ReputationSummary.completion_ratio (§8.2)
_MISSING_SORT_VALUE = 2**62


def clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def match_score(match_type: MatchType) -> float:
    return MATCH_TYPE_SCORE.get(MatchType(match_type), 0.0)


def group_for(match_type: MatchType) -> MatchGroup:
    return MatchGroup.ALTERNATIVE if MatchType(match_type) is MatchType.ALTERNATIVE else MatchGroup.PRIMARY


def window_midpoint(start: datetime, end: datetime) -> datetime:
    start, end = ensure_aware_utc(start), ensure_aware_utc(end)
    return start + (end - start) / 2


def window_minutes(start: datetime, end: datetime) -> float:
    return max(0.0, (ensure_aware_utc(end) - ensure_aware_utc(start)).total_seconds() / 60)


def time_score(eta: datetime, desired: datetime, tolerated_minutes: float) -> float:
    diff = abs((ensure_aware_utc(eta) - ensure_aware_utc(desired)).total_seconds()) / 60
    if tolerated_minutes <= 0:
        return 1.0 if diff == 0 else 0.0
    return max(0.0, 1.0 - diff / tolerated_minutes)


def price_score(total_minor: int | None, low_minor: int | None, high_minor: int | None) -> float:
    if total_minor is None or low_minor is None or high_minor is None or high_minor == low_minor:
        return NEUTRAL_PRICE_SCORE
    return clip01((high_minor - total_minor) / (high_minor - low_minor))


def driver_price_score(total_minor: int | None, reference_total_minor: int | None) -> float:
    """§8.4 Y. The same commission rate applies to both totals, so ``net/reference_net == total/reference_total``."""
    if total_minor is None or not reference_total_minor or reference_total_minor <= 0:
        return NEUTRAL_PRICE_SCORE
    return clip01(total_minor / reference_total_minor - 0.5)


def on_time_ratio(summary: ReputationSummary) -> float:
    return (summary.on_time_count + ON_TIME_PRIOR_WEIGHT * ON_TIME_PRIOR) / (summary.eligible_resolved + ON_TIME_PRIOR_WEIGHT)


def reliability(summary: ReputationSummary) -> float:
    return clip01(
        RELIABILITY_WEIGHTS["rating"] * (summary.adjusted_rating / 5)
        + RELIABILITY_WEIGHTS["completion"] * summary.completion_ratio
        + RELIABILITY_WEIGHTS["on_time"] * on_time_ratio(summary)
    )


def experience(completed_trips: int) -> float:
    return min(1.0, math.log(1 + max(0, completed_trips)) / math.log(1 + EXPERIENCE_LOG_BASE_TRIPS))


def fit_score(requested: int, min_remaining: int | None) -> float | None:
    """§8.4 F. ``None`` means the demand does not fit (hard reject, never a low score)."""
    if min_remaining is None:
        return NEUTRAL_FIT_SCORE
    if requested > min_remaining or min_remaining <= 0:
        return None
    return clip01(requested / min_remaining)


def _weighted(weights: Mapping[str, float], components: Mapping[str, float]) -> float:
    if set(weights) != set(components):
        raise ValueError(f"components {sorted(components)} do not match weights {sorted(weights)}")
    return round(100 * sum(weights[key] * clip01(components[key]) for key in weights), 2)


def client_score(*, M: float, T: float, R: float, P: float, E: float) -> float:  # noqa: N803 - spec symbols
    return _weighted(CLIENT_SCORE_WEIGHTS, {"M": M, "T": T, "R": R, "P": P, "E": E})


def driver_score(*, M: float, T: float, Y: float, C: float, F: float) -> float:  # noqa: N803 - spec symbols
    return _weighted(DRIVER_SCORE_WEIGHTS, {"M": M, "T": T, "Y": Y, "C": C, "F": F})


def comparable_total_minor(
    *, price_basis: PriceBasis | str, unit_price_minor: int, total_minor: int, listing_quantity: int, wanted_quantity: int
) -> int | None:
    """Total price for ``wanted_quantity`` (§8.2 P compares totals; per_seat and total never mix).

    ``per_seat`` -> unit * wanted; ``total`` -> the listing total only when it is for the same quantity, else ``None``.
    """
    if PriceBasis(price_basis) is PriceBasis.PER_SEAT:
        return unit_price_minor * wanted_quantity
    return total_minor if listing_quantity == wanted_quantity else None


def band_totals(service_type: ServiceType | str, floor_minor: int, ceiling_minor: int, quantity: int) -> tuple[int, int]:
    """Q42 bands: passenger bands are per seat, parcel bands are totals."""
    if ServiceType(service_type) is ServiceType.PASSENGER:
        return floor_minor * quantity, ceiling_minor * quantity
    return floor_minor, ceiling_minor


def band_reference_total(service_type: ServiceType | str, floor_minor: int, ceiling_minor: int, quantity: int) -> int:
    low, high = band_totals(service_type, floor_minor, ceiling_minor, quantity)
    return (low + high) // 2


def stop_segment_match(
    route_orders: Iterable[Mapping[int, Sequence[int]]],
    origin_ids: Iterable[int],
    destination_ids: Iterable[int],
    pickup_stop_id: int,
    dropoff_stop_id: int,
) -> MatchType | None:
    """Verified-stop match of a request segment against a wanted direction (no trip, no router; Q46).

    ``route_orders``: per confirmed route version, ``{stop_id: [positions]}``. ``exact`` when both stops are the
    wanted ends; ``on_route`` when some confirmed route has ``origin <= pickup < dropoff <= destination`` in its stop
    order; otherwise ``None`` (reverse direction or off route, AC16).
    """
    origins, destinations = set(origin_ids), set(destination_ids)
    if pickup_stop_id == dropoff_stop_id:
        return None
    if pickup_stop_id in origins and dropoff_stop_id in destinations:
        return MatchType.EXACT
    for order in route_orders:
        pickups = order.get(pickup_stop_id, ())
        dropoffs = order.get(dropoff_stop_id, ())
        starts = [p for o in origins for p in order.get(o, ())]
        ends = [p for d in destinations for p in order.get(d, ())]
        for p in pickups:
            for d in dropoffs:
                if p >= d:
                    continue
                if any(s <= p for s in starts) and any(e >= d for e in ends):
                    return MatchType.ON_ROUTE
    return None


def window_gap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> timedelta:
    """Zero when the half-open windows intersect, else the distance between them."""
    a0, a1, b0, b1 = (ensure_aware_utc(v) for v in (a_start, a_end, b_start, b_end))
    if a0 < b1 and b0 < a1:
        return timedelta(0)
    return b0 - a1 if a1 <= b0 else a0 - b1


def sort_key(
    sort: FeedSort,
    *,
    group: MatchGroup,
    score: float,
    comparable_total: int | None,
    when: datetime,
    adjusted_rating: float,
    rating_count: int,
    listing_id: int,
) -> tuple[int, int, int]:
    """Integer keyset key ``(group, value, listing_id)``, ascending. Primary group always before alternatives."""
    group_rank = 0 if MatchGroup(group) is MatchGroup.PRIMARY else 1
    sort = FeedSort(sort)
    if sort is FeedSort.CHEAPEST:
        value = comparable_total if comparable_total is not None else _MISSING_SORT_VALUE
    elif sort is FeedSort.TIME:
        value = int(ensure_aware_utc(when).timestamp())
    elif sort is FeedSort.RATING:
        # adjusted rating (AC36: 1 x 5.0 is not blindly first), then more ratings first
        value = -(round(adjusted_rating * 10_000) * 1_000_000 + min(rating_count, 999_999))
    else:
        value = -round(score * 100)
    return group_rank, value, listing_id


__all__ = [
    "FEED_CANDIDATE_LIMIT",
    "ON_TIME_PRIOR_WEIGHT",
    "RATING_PRIOR_WEIGHT",
    "REGION_STOP_LIMIT",
    "band_reference_total",
    "band_totals",
    "client_score",
    "clip01",
    "comparable_total_minor",
    "driver_price_score",
    "driver_score",
    "experience",
    "fit_score",
    "group_for",
    "match_score",
    "on_time_ratio",
    "price_score",
    "reliability",
    "sort_key",
    "stop_segment_match",
    "time_score",
    "window_gap",
    "window_midpoint",
    "window_minutes",
]
