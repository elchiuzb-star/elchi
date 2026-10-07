"""Unit tests: road-interval capacity math, schedule and plate rules (spec §7; AC10-AC12; ADR-0028 / Q160).

The spec §7 example is the same as ever - A-B-C-D, capacity 4 - but the places are positions on the road (metres),
not stops: a booking occupies the half-open interval ``[pickup_m, dropoff_m)`` of the trip's road.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.route_position import Claim, Resources, interval_shortfalls
from app.modules.trips.rules import (
    TRIP_TURNAROUND_BUFFER,
    ResourceDemand,
    blocked_period,
    claim_shortfall_error,
    mask_plate,
    normalize_plate,
    validate_schedule,
)

NOW = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)

# Spec §7: A-B-C-D (100 km apart), capacity 4; A-C holds 2 seats, B-D holds 1 seat.
A, B, C, D = 0, 100_000, 200_000, 300_000
SEATS_4 = Resources(seats=4)
SPEC_EXAMPLE = [Claim(A, C, Resources(seats=2)), Claim(B, D, Resources(seats=1))]


def test_ac10_two_seats_a_to_d_rejected_on_b_c() -> None:
    shortfalls = interval_shortfalls(SEATS_4, SPEC_EXAMPLE, A, D, Resources(seats=2))
    assert [(s.at_m, s.resource, s.remaining) for s in shortfalls] == [(B, "seats", 1)]
    error = claim_shortfall_error(shortfalls)
    assert error.code is ErrorCode.CAPACITY_UNAVAILABLE
    assert error.details["positions"] == [{"at_m": B, "resource": "seats", "remaining": 1, "requested": 2}]


def test_ac10_one_seat_b_to_c_still_fits() -> None:
    assert interval_shortfalls(SEATS_4, SPEC_EXAMPLE, B, C, Resources(seats=1)) == []


def test_ac11_three_seats_c_to_d_allowed() -> None:
    assert interval_shortfalls(SEATS_4, SPEC_EXAMPLE, C, D, Resources(seats=3)) == []


def test_ac12_baggage_over_capacity_is_cargo_limit() -> None:
    capacity = Resources(seats=4, baggage_ml=50_000)
    claims = [Claim(A, B, Resources(seats=1, baggage_ml=40_000))]
    shortfalls = interval_shortfalls(capacity, claims, A, B, Resources(seats=1, baggage_ml=20_000))
    assert [s.resource for s in shortfalls] == ["baggage_ml"]
    assert claim_shortfall_error(shortfalls).code is ErrorCode.CARGO_LIMIT_EXCEEDED


@pytest.mark.parametrize("bad", [-1, 1.5, "2", True])
def test_resource_demand_rejects_non_integers_and_negatives(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ResourceDemand(seats=bad)  # type: ignore[arg-type]


def test_plate_normalisation_and_masking() -> None:
    assert normalize_plate(" 01 a-123 bc ") == "01A123BC"
    assert mask_plate("01A123BC") == "01****BC"
    with pytest.raises(DomainError):
        normalize_plate("-")


def test_blocked_period_adds_turnaround_buffer() -> None:
    start, end = NOW + timedelta(hours=1), NOW + timedelta(hours=5)
    assert blocked_period(start, end) == (start, end + TRIP_TURNAROUND_BUFFER)


def test_schedule_defaults_cutoff_to_departure_and_validates_the_plan() -> None:
    start, end = NOW + timedelta(hours=2), NOW + timedelta(hours=6)
    assert validate_schedule(now=NOW, planned_start_at=start, planned_end_at=end, booking_cutoff_at=None) == start
    with pytest.raises(DomainError):
        validate_schedule(now=NOW, planned_start_at=end, planned_end_at=start, booking_cutoff_at=None)
    with pytest.raises(DomainError):
        validate_schedule(now=NOW, planned_start_at=start, planned_end_at=end, booking_cutoff_at=start + timedelta(minutes=1))
    with pytest.raises(DomainError):
        validate_schedule(now=start, planned_start_at=start, planned_end_at=end, booking_cutoff_at=None)
