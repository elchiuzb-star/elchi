"""ADR-0028 (Q159): road positions and interval capacity - pure arithmetic, no database."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.contracts.route_position import (
    Claim,
    ClaimShortfall,
    Resources,
    claim_span,
    interval_shortfalls,
    peak_load,
    position_m,
    travel_s,
)


def seats(n: int) -> Resources:
    return Resources(seats=n)


def test_position_is_the_fraction_of_the_road_in_whole_metres() -> None:
    assert position_m(0, 510_000) == 0
    assert position_m(1, 510_000) == 510_000
    assert position_m(Decimal("0.3333333"), 510_000) == 170_000  # 169_999.983 rounds half-up like SQL round()
    assert position_m(0.5, 3) == 2
    with pytest.raises(ValueError):
        position_m(1.01, 100)
    with pytest.raises(ValueError):
        position_m(0.5, 0)


def test_travel_time_is_linear_along_the_road() -> None:
    assert travel_s(0, 170_000, distance_m=510_000, duration_s=25_200) == 8_400
    assert travel_s(100, 100, distance_m=510_000, duration_s=25_200) == 0
    with pytest.raises(ValueError):
        travel_s(200, 100, distance_m=510_000, duration_s=25_200)


def test_pickup_must_come_before_dropoff() -> None:
    assert claim_span(0, 1) == (0, 1)
    for bad in ((5, 5), (6, 5), (-1, 5)):
        with pytest.raises(ValueError):
            claim_span(*bad)
    with pytest.raises(TypeError):
        claim_span(1.0, 2)  # type: ignore[arg-type]


def test_intervals_are_half_open_so_a_seat_freed_at_b_is_free_at_b() -> None:
    held = [Claim(0, 100, seats(1))]
    assert interval_shortfalls(seats(1), held, 100, 200, seats(1)) == []
    assert interval_shortfalls(seats(1), held, 99, 200, seats(1)) == [
        ClaimShortfall(at_m=99, resource="seats", remaining=0, requested=1)
    ]


def test_the_peak_is_found_at_a_claim_start_inside_the_interval() -> None:
    held = [Claim(0, 50, seats(1)), Claim(40, 90, seats(2)), Claim(80, 120, seats(1))]
    peaks = peak_load(held, 30, 100)
    assert peaks["seats"] == (3, 40) and peaks["baggage_ml"] == (0, 30)
    # three seats on the road: [30, 100) peaks at 3 between 40 and 50 and again between 80 and 90
    assert interval_shortfalls(seats(3), held, 30, 100, seats(1)) == [
        ClaimShortfall(at_m=40, resource="seats", remaining=0, requested=1)
    ]
    assert interval_shortfalls(seats(3), held, 50, 80, seats(1)) == []  # only the middle claim is there


def test_each_resource_is_checked_on_its_own() -> None:
    held = [Claim(0, 100, Resources(seats=1, cargo_weight_g=40_000))]
    capacity = Resources(seats=4, cargo_weight_g=50_000)
    shortfalls = interval_shortfalls(capacity, held, 50, 150, Resources(cargo_weight_g=20_000))
    assert shortfalls == [ClaimShortfall(at_m=50, resource="cargo_weight_g", remaining=10_000, requested=20_000)]
    with pytest.raises(ValueError):
        interval_shortfalls(capacity, held, 50, 150, Resources())
