"""Unit tests for corridor price bands (Q42): precedence and comparisons."""

from __future__ import annotations

import pytest

from app.contracts.enums import PriceBasis, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.geo.pricing import (
    PRICE_BAND_BASIS,
    PriceBand,
    assert_price_within_band,
    evaluate_price_band,
    price_within_band,
    select_price_band,
)

CORRIDOR, OTHER = 1, 2
A, B, C = 10, 11, 12


def band(origin=None, dest=None, floor=10_000, ceiling=50_000, *, service=ServiceType.PASSENGER, active=True, version=1, corridor=CORRIDOR, enforced=False):  # noqa: ANN001, ANN201
    return PriceBand(corridor, service, origin, dest, floor, ceiling, active, version, "UZS", enforced)


def pick(bands, origin=A, dest=C, service=ServiceType.PASSENGER):  # noqa: ANN001, ANN201
    return select_price_band(bands, corridor_id=CORRIDOR, service_type=service, origin_stop_id=origin, destination_stop_id=dest)


def test_segment_band_wins_over_corridor_band() -> None:
    corridor_wide, segment = band(), band(A, C, 20_000, 30_000)
    assert pick([corridor_wide, segment]) is segment and segment.scope == "segment"
    assert pick([corridor_wide, segment], origin=B) is corridor_wide and corridor_wide.scope == "corridor"


def test_reverse_segment_is_a_different_segment() -> None:
    assert pick([band(C, A, 1, 2)]) is None


def test_no_band_returns_none_and_filters_apply() -> None:
    assert pick([]) is None
    assert pick([band(active=False)]) is None
    assert pick([band(corridor=OTHER)]) is None
    assert pick([band(service=ServiceType.PARCEL)]) is None
    assert pick([band(A, C, active=False), band(floor=5, ceiling=9)]).floor_minor == 5  # inactive segment falls back


def test_price_basis_per_service() -> None:
    assert PRICE_BAND_BASIS == {ServiceType.PASSENGER: PriceBasis.PER_SEAT, ServiceType.PARCEL: PriceBasis.TOTAL}
    assert band().price_basis is PriceBasis.PER_SEAT


def test_price_within_band_passenger_per_seat_and_total() -> None:
    b = band(floor=100, ceiling=300)
    assert price_within_band(b, price_basis=PriceBasis.PER_SEAT, unit_price_minor=100, quantity=3)
    assert price_within_band(b, price_basis=PriceBasis.PER_SEAT, unit_price_minor=300, quantity=3)
    assert not price_within_band(b, price_basis=PriceBasis.PER_SEAT, unit_price_minor=301, quantity=1)
    # a total price for 2 seats is compared with 2 x band, without rounding
    assert price_within_band(b, price_basis=PriceBasis.TOTAL, unit_price_minor=201, quantity=2)
    assert not price_within_band(b, price_basis=PriceBasis.TOTAL, unit_price_minor=199, quantity=2)
    assert not price_within_band(b, price_basis=PriceBasis.TOTAL, unit_price_minor=601, quantity=2)


def test_price_within_band_parcel_total() -> None:
    b = band(service=ServiceType.PARCEL, floor=50_000, ceiling=90_000)
    assert price_within_band(b, price_basis=PriceBasis.TOTAL, unit_price_minor=70_000, quantity=1)
    assert not price_within_band(b, price_basis=PriceBasis.TOTAL, unit_price_minor=40_000, quantity=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"floor": 0},
        {"floor": 10, "ceiling": 9},
        {"origin": A},
        {"origin": A, "dest": A},
        {"version": 0},
    ],
)
def test_invalid_bands_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        band(**kwargs)


def test_price_check_rejects_non_positive_inputs() -> None:
    with pytest.raises(ValueError):
        price_within_band(band(), price_basis=PriceBasis.PER_SEAT, unit_price_minor=0, quantity=1)
    with pytest.raises(ValueError):
        price_within_band(band(), price_basis=PriceBasis.PER_SEAT, unit_price_minor=1, quantity=0)


def test_an_ordinary_band_never_refuses_a_negotiated_price() -> None:
    """Q90: the band advises. ELCHI's price is the one the two sides agree on.

    This test used to assert the opposite - that a price outside the band raised. That was Q42's original
    reading, and it turned the two-sided auction into a fixed fare: a counteroffer at 330 000 on a band of
    100..300 could not be *made*, so the sequence the product exists for could not happen.
    """
    b = band(floor=100, ceiling=300)
    assert_price_within_band(b, price_basis=PriceBasis.TOTAL, unit_price_minor=700, quantity=2)
    assert_price_within_band(band(A, C, 100, 300), price_basis=PriceBasis.PER_SEAT, unit_price_minor=99, quantity=1)


def test_evaluate_returns_the_advice_the_caller_shows_as_a_warning() -> None:
    """The band still has something to say - it just says it instead of deciding."""
    b = band(floor=100, ceiling=300)
    assert evaluate_price_band(None, price_basis=PriceBasis.PER_SEAT, unit_price_minor=1, quantity=1) is None
    assert evaluate_price_band(b, price_basis=PriceBasis.PER_SEAT, unit_price_minor=200, quantity=1) is None
    details = evaluate_price_band(b, price_basis=PriceBasis.TOTAL, unit_price_minor=700, quantity=2)
    assert details == {"floor_minor": 100, "ceiling_minor": 300, "currency": "UZS", "price_basis": "per_seat", "scope": "corridor"}
    segment = evaluate_price_band(band(A, C, 100, 300), price_basis=PriceBasis.PER_SEAT, unit_price_minor=99, quantity=1)
    assert segment is not None and segment["scope"] == "segment"


def test_only_an_enforced_band_refuses_and_says_which_one() -> None:
    """Q90 keeps exactly one hard limit: an abuse/safety band an admin deliberately marked ``enforced``."""
    assert_price_within_band(None, price_basis=PriceBasis.PER_SEAT, unit_price_minor=1, quantity=1)  # no band, no check
    hard = band(floor=100, ceiling=300, enforced=True)
    assert_price_within_band(hard, price_basis=PriceBasis.PER_SEAT, unit_price_minor=200, quantity=1)  # inside: fine
    with pytest.raises(DomainError) as info:
        assert_price_within_band(hard, price_basis=PriceBasis.TOTAL, unit_price_minor=700, quantity=2)
    assert info.value.code is ErrorCode.PRICE_OUT_OF_BAND and info.value.http_status == 400
    assert info.value.details == {"floor_minor": 100, "ceiling_minor": 300, "currency": "UZS", "price_basis": "per_seat", "scope": "corridor"}
    with pytest.raises(DomainError) as segment:
        assert_price_within_band(
            band(A, C, 100, 300, enforced=True), price_basis=PriceBasis.PER_SEAT, unit_price_minor=99, quantity=1
        )
    assert segment.value.details["scope"] == "segment"


def test_a_point_ended_listing_still_gets_a_reference() -> None:
    """Q88 + Q42: no stop pair is not the same as no price reference.

    A map-point end has no stop id, so there is no segment to look up - but the corridor-wide band still
    describes the direction, and without it a point listing would score a neutral 0.5 on price forever.
    """
    corridor_wide, segment = band(), band(A, C, 20_000, 30_000)
    picked = select_price_band(
        [corridor_wide, segment],
        corridor_id=CORRIDOR,
        service_type=ServiceType.PASSENGER,
        origin_stop_id=None,
        destination_stop_id=None,
    )
    assert picked is corridor_wide and picked.scope == "corridor"
