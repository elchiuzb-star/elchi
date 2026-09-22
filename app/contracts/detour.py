"""Detour quote snapshot (spec §6.3-§6.4, AC17; wave 1.5 BR review; decision Q25).

A2 (geo) measures the extra driving a pickup/dropoff detour adds after a given stop
occurrence; A4 (accept) re-checks the snapshot inside the locked transaction instead of
calling a routing provider under locks (§15). A quote is bound to the route version and
the trip version it was measured against and expires; a stale or mismatched quote must be
re-measured (``ROUTE_CHANGED`` / ``DETOUR_LIMIT_EXCEEDED`` are raised by the owners).

Units (AGENTS §6): seconds and metres, integers. Trip detour counters are kept in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.contracts.timeutil import ensure_aware_utc

# Pilot default validity of a detour measurement (owners may shorten; never lengthen past the
# proposal TTL).
DEFAULT_DETOUR_QUOTE_TTL = timedelta(minutes=10)


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return value


@dataclass(frozen=True, slots=True)
class DetourQuote:
    route_version_id: str  # rtv_... public id
    trip_version: int
    after_seq: int  # detour leaves the route after this stop occurrence (leg after_seq -> after_seq+1)
    extra_s: int
    extra_m: int
    measured_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.route_version_id, str) or not self.route_version_id:
            raise ValueError("route_version_id is required")
        if isinstance(self.trip_version, bool) or not isinstance(self.trip_version, int) or self.trip_version < 1:
            raise ValueError("trip_version must be a positive int")
        _non_negative_int(self.after_seq, "after_seq")
        _non_negative_int(self.extra_s, "extra_s")
        _non_negative_int(self.extra_m, "extra_m")
        measured = ensure_aware_utc(self.measured_at, field="measured_at")
        expires = ensure_aware_utc(self.expires_at, field="expires_at")
        if expires <= measured:
            raise ValueError("expires_at must be after measured_at")
        object.__setattr__(self, "measured_at", measured)
        object.__setattr__(self, "expires_at", expires)

    def is_valid_for(self, *, route_version_id: str, trip_version: int, now: datetime) -> bool:
        """Usable only for the same route/trip versions and before expiry."""
        return (
            route_version_id == self.route_version_id
            and trip_version == self.trip_version
            and ensure_aware_utc(now, field="now") < self.expires_at
        )


def detour_legs_conflict(quotes: list[DetourQuote] | tuple[DetourQuote, ...]) -> bool:
    """Q25 (pilot limitation): two detours on the same leg are rejected."""
    legs = [quote.after_seq for quote in quotes]
    return len(legs) != len(set(legs))


def total_detour_seconds(quotes: list[DetourQuote] | tuple[DetourQuote, ...]) -> int:
    return sum(quote.extra_s for quote in quotes)


# Q62 (wave 2.1): detour insertion and AC13 re-check are deferred in the pilot (Q46). Accept rejects a proposal
# version that carries detour quotes in EVERY environment with ``409 ROUTE_MISMATCH`` and
# ``details.reason = DETOUR_NOT_AVAILABLE_REASON`` (no new error code; ROUTE_MISMATCH is already on P8).
DETOUR_INSERTION_ENABLED = False
DETOUR_NOT_AVAILABLE_REASON = "detour_not_available"
