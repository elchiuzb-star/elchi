"""Pure policy resolution (Q19) and legacy Decimal -> minor/bps conversion (ADR-0003)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.contracts.enums import CommissionPolicyKind as K
from app.contracts.enums import ServiceType
from app.contracts.money import legacy_rate_to_bps, major_to_minor
from app.modules.wallet.policy import PolicyCandidate, fee_percent_text, scope_specificity, select_policy
from app.services.system_settings_service import bps_to_rate, calculate_order_income, percent_to_rate

T0 = datetime(2026, 9, 13, 7, 0, tzinfo=timezone.utc)


def c(id_, kind, bps, corridor=None, service=None, start=T0, end=None):
    return PolicyCandidate(id_, kind, corridor, service, bps, start, end)


GLOBAL = c(1, K.STANDARD, 1500)
PARCEL = c(2, K.STANDARD, 1200, service=ServiceType.PARCEL)
CORRIDOR = c(3, K.STANDARD, 1100, corridor=7)
CORRIDOR_PARCEL = c(4, K.STANDARD, 1000, corridor=7, service=ServiceType.PARCEL)
CAMPAIGN = c(5, K.CAMPAIGN, 0, start=T0 + timedelta(hours=1), end=T0 + timedelta(hours=2))


@pytest.mark.parametrize(
    ("corridor", "service", "at", "expected"),
    [
        (7, "parcel", T0, 4),
        (7, "passenger", T0, 3),
        (8, "parcel", T0, 2),
        (8, "passenger", T0, 1),
        (None, None, T0, 1),
        (7, "parcel", T0 + timedelta(minutes=90), 5),  # a global campaign beats the most specific standard
        (7, "parcel", T0 + timedelta(hours=2), 4),  # [from, to) half-open
    ],
)
def test_select_policy_precedence(corridor, service, at, expected):
    chosen = select_policy([GLOBAL, PARCEL, CORRIDOR, CORRIDOR_PARCEL, CAMPAIGN], corridor_id=corridor,
                           service_type=service, at=at)
    assert chosen.id == expected


def test_specific_campaign_beats_global_campaign_and_none_when_nothing_applies():
    specific = c(6, K.CAMPAIGN, 500, service=ServiceType.PASSENGER, start=CAMPAIGN.effective_from, end=CAMPAIGN.effective_to)
    at = T0 + timedelta(minutes=90)
    assert select_policy([CAMPAIGN, specific], corridor_id=None, service_type="passenger", at=at).id == 6
    assert select_policy([CAMPAIGN, specific], corridor_id=None, service_type="parcel", at=at).id == 5
    assert select_policy([PARCEL], corridor_id=None, service_type="passenger", at=T0) is None
    assert [scope_specificity(x) for x in (GLOBAL, PARCEL, CORRIDOR, CORRIDOR_PARCEL)] == [0, 1, 2, 3]


def test_naive_resolution_time_rejected():
    with pytest.raises(ValueError):
        select_policy([GLOBAL], corridor_id=None, service_type=None, at=datetime(2026, 9, 13))


def test_legacy_conversion_is_exact():
    assert legacy_rate_to_bps(Decimal("0.1500")) == 1500
    assert legacy_rate_to_bps(percent_to_rate(Decimal("12.5"))) == 1250
    assert legacy_rate_to_bps(percent_to_rate(Decimal("12.345"))) == 1235  # v1 quantizes to 4 dp first
    assert bps_to_rate(1500) == Decimal("0.1500")
    assert major_to_minor(Decimal("60000.00")) == 6_000_000
    with pytest.raises(ValueError):
        major_to_minor(Decimal("0.001"))
    assert fee_percent_text(1500) == "15.00" and fee_percent_text(1250) == "12.50" and fee_percent_text(0) == "0.00"


def test_legacy_fee_stays_decimal_report_value():
    income = calculate_order_income(Decimal("400000"), Decimal("0.15"))
    assert income["system_fee"] == Decimal("60000.00")
    assert major_to_minor(income["system_fee"]) == 6_000_000  # legacy_calculated_fee_minor view value, never a ledger row
