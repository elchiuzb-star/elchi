from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.contracts.enums import Currency
from app.contracts.money import (
    Money,
    bps_to_percent,
    commission_minor,
    legacy_rate_to_bps,
    major_to_minor,
    minor_to_major,
    net_after_commission_minor,
    percent_to_bps,
    round_half_up_div,
    total_minor,
)


def test_spec_example_two_seats_total() -> None:
    # spec §14.1: 2 x 200 000 so'm = 400 000 so'm = 40 000 000 tiyin
    assert total_minor(20_000_000, 2) == 40_000_000


def test_spec_example_fifteen_percent_commission() -> None:
    # spec §9.3: 15% of 400 000 so'm = 60 000 so'm
    assert commission_minor(40_000_000, 1500) == 6_000_000
    assert net_after_commission_minor(40_000_000, 1500) == 34_000_000


def test_zero_fee_campaign_is_zero_commission() -> None:
    assert commission_minor(40_000_000, 0) == 0


@pytest.mark.parametrize(
    ("total", "bps", "expected"),
    [
        (1, 5000, 1),  # 0.5 rounds up
        (1, 4999, 0),  # 0.4999 rounds down
        (3, 5000, 2),  # 1.5 rounds up
        (1, 1500, 0),  # 0.15
        (7, 1500, 1),  # 1.05
        (10, 1500, 2),  # 1.5
        (33_333, 1500, 5_000),  # 4999.95
        (1, 10_000, 1),
        (0, 1500, 0),
    ],
)
def test_commission_rounding_edges(total: int, bps: int, expected: int) -> None:
    assert commission_minor(total, bps) == expected


def test_round_half_up_matches_decimal_for_both_signs() -> None:
    for numerator in range(-2_000, 2_001, 7):
        for denominator in (1, 2, 3, 4, 10, 10_000):
            expected = int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            assert round_half_up_div(numerator, denominator) == expected


@pytest.mark.parametrize("bad", [1.0, True, "1"])
def test_money_functions_reject_non_int(bad: object) -> None:
    with pytest.raises(TypeError):
        commission_minor(bad, 1500)  # type: ignore[arg-type]


@pytest.mark.parametrize("bps", [-1, 10_001])
def test_fee_bps_bounds(bps: int) -> None:
    with pytest.raises(ValueError):
        commission_minor(100, bps)


def test_negative_total_rejected() -> None:
    with pytest.raises(ValueError):
        commission_minor(-1, 1500)


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        total_minor(20_000_000, 0)


def test_legacy_decimal_mapping_is_exact() -> None:
    assert major_to_minor(Decimal("60000.00")) == 6_000_000
    assert major_to_minor("400000") == 40_000_000
    assert minor_to_major(6_000_050) == Decimal("60000.5")
    with pytest.raises(ValueError):
        major_to_minor(Decimal("0.001"))
    with pytest.raises(TypeError):
        major_to_minor(600.5)  # type: ignore[arg-type]


def test_legacy_rate_and_percent_to_bps() -> None:
    assert legacy_rate_to_bps(Decimal("0.1500")) == 1500
    assert legacy_rate_to_bps("0.1") == 1000
    assert percent_to_bps("12.5") == 1250
    assert percent_to_bps(15) == 1500
    assert bps_to_percent(1250) == Decimal("12.5")
    with pytest.raises(ValueError):
        legacy_rate_to_bps(Decimal("0.12345"))
    with pytest.raises(ValueError):
        percent_to_bps("100.01")


def test_money_value_object() -> None:
    assert Money(100) + Money(50) == Money(150, Currency.UZS)
    assert (Money(100) - Money(150)).amount_minor == -50
    with pytest.raises(TypeError):
        Money(1.5)  # type: ignore[arg-type]
