"""Unit tests: segment capacity math, stop mapping, schedule and plate rules (spec §7; AC10-AC12)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.errors import DomainError, ErrorCode
from app.modules.trips.rules import (
    TRIP_TURNAROUND_BUFFER,
    Resource,
    ResourceDemand,
    SegmentLoad,
    blocked_period,
    covered_from_seqs,
    find_shortfalls,
    map_stops_onto_route,
    mask_plate,
    min_remaining,
    normalize_plate,
    shortfall_error,
    validate_schedule,
)

NOW = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)


def segment(from_seq: int, seats_used: int, *, capacity: int = 4, baggage: tuple[int, int] = (0, 0)) -> SegmentLoad:
    return SegmentLoad(
        from_seq=from_seq,
        to_seq=from_seq + 1,
        seat_capacity=capacity,
        seats_used=seats_used,
        baggage_capacity_ml=baggage[0],
        baggage_used_ml=baggage[1],
        cargo_capacity_weight_g=0,
        cargo_used_weight_g=0,
        cargo_capacity_volume_ml=0,
        cargo_used_volume_ml=0,
    )


# Spec §7: A-B-C-D, capacity 4; A-C holds 2 seats, B-D holds 1 seat.
A, B, C, D = 1, 2, 3, 4
SPEC_EXAMPLE = [segment(A, 2), segment(B, 3), segment(C, 1)]


def test_ac10_spec_example_remaining_per_segment() -> None:
    assert [s.remaining(Resource.SEATS) for s in SPEC_EXAMPLE] == [2, 1, 3]
    assert min_remaining(SPEC_EXAMPLE, B, C, Resource.SEATS) == 1


def test_ac10_two_seats_a_to_d_rejected_on_b_c() -> None:
    shortfalls = find_shortfalls(SPEC_EXAMPLE, A, D, ResourceDemand(seats=2))
    assert [(s.from_seq, s.remaining, s.requested) for s in shortfalls] == [(B, 1, 2)]
    assert shortfall_error(shortfalls).code is ErrorCode.CAPACITY_UNAVAILABLE


def test_ac11_three_seats_c_to_d_allowed() -> None:
    assert find_shortfalls(SPEC_EXAMPLE, C, D, ResourceDemand(seats=3)) == []


def test_ac12_baggage_over_capacity_is_cargo_limit() -> None:
    loads = [segment(1, 0, baggage=(50_000, 40_000))]
    shortfalls = find_shortfalls(loads, 1, 2, ResourceDemand(seats=1, baggage_ml=20_000))
    assert [s.resource for s in shortfalls] == [Resource.BAGGAGE_ML]
    assert shortfall_error(shortfalls).code is ErrorCode.CARGO_LIMIT_EXCEEDED


def test_missing_segment_is_route_mismatch() -> None:
    with pytest.raises(DomainError) as info:
        find_shortfalls([segment(1, 0)], 1, 3, ResourceDemand(seats=1))
    assert info.value.code is ErrorCode.ROUTE_MISMATCH


@pytest.mark.parametrize(("from_seq", "to_seq"), [(2, 2), (3, 1), (0, 1)])
def test_span_must_be_forward(from_seq: int, to_seq: int) -> None:
    with pytest.raises(DomainError):
        covered_from_seqs(from_seq, to_seq)


@pytest.mark.parametrize("bad", [-1, True, 1.0])
def test_resource_demand_rejects_non_integers_and_negatives(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ResourceDemand(seats=bad)  # type: ignore[arg-type]


def test_stop_mapping_accepts_ordered_subsequence_and_rejects_reverse() -> None:
    route = [(0, 10), (1, 20), (2, 30), (3, 40)]
    assert map_stops_onto_route([10, 30, 40], route) == [0, 2, 3]
    assert map_stops_onto_route([40, 10], route) is None
    assert map_stops_onto_route([10, 99], route) is None


def test_stop_mapping_handles_loops_as_distinct_occurrences() -> None:
    route = [(0, 10), (1, 20), (2, 10), (3, 30)]
    assert map_stops_onto_route([10, 20, 10, 30], route) == [0, 1, 2, 3]


def test_plate_normalisation_and_masking() -> None:
    assert normalize_plate(" 01 a-123 bc ") == "01A123BC"
    assert mask_plate("01A123BC") == "01****BC"
    with pytest.raises(DomainError):
        normalize_plate("-")


def test_blocked_period_adds_turnaround_buffer() -> None:
    start, end = NOW + timedelta(hours=1), NOW + timedelta(hours=5)
    assert blocked_period(start, end) == (start, end + TRIP_TURNAROUND_BUFFER)


def test_schedule_defaults_cutoff_to_departure_and_validates_arrivals() -> None:
    start, end = NOW + timedelta(hours=2), NOW + timedelta(hours=6)
    arrivals = [start, start + timedelta(hours=2), end]
    assert validate_schedule(now=NOW, planned_start_at=start, planned_end_at=end, arrivals=arrivals, booking_cutoff_at=None) == start
    with pytest.raises(DomainError):
        validate_schedule(now=NOW, planned_start_at=start, planned_end_at=end, arrivals=[start, end + timedelta(minutes=1)], booking_cutoff_at=None)
    with pytest.raises(DomainError):
        validate_schedule(now=NOW, planned_start_at=start, planned_end_at=end, arrivals=[end, start], booking_cutoff_at=None)
    with pytest.raises(DomainError):
        validate_schedule(now=NOW, planned_start_at=start, planned_end_at=end, arrivals=arrivals, booking_cutoff_at=start + timedelta(minutes=1))
    with pytest.raises(DomainError):
        validate_schedule(now=start, planned_start_at=start, planned_end_at=end, arrivals=arrivals, booking_cutoff_at=None)
