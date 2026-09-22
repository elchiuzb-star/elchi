"""A13 pure rules: share text, money formatting, KPI ratios (spec §20.2, §20.4). No database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.contracts.enums import KpiMetric, ShareLinkChannel
from app.contracts.operations import KPI_SMALL_SAMPLE_BELOW, SHARE_LINK_PUBLIC_PATH
from app.modules.operations import rules

DEPARTURE_START = datetime(2026, 9, 18, 4, 0, tzinfo=UTC)  # 09:00 in Asia/Tashkent
DEPARTURE_END = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)


def test_money_text_uses_integer_minor_units() -> None:
    assert rules.money_text(40_000_000, "UZS") == "400 000 UZS"
    assert rules.money_text(0, "UZS") == "0 UZS"
    assert rules.money_text(12_345, "UZS") == "123,45 UZS"


def test_share_text_carries_route_time_price_and_link_only() -> None:
    text = rules.share_text(
        channel=ShareLinkChannel.TELEGRAM.value, kind="request", service_type="passenger",
        origin="Toshkent", destination="Samarqand", departure_start=DEPARTURE_START, departure_end=DEPARTURE_END,
        total_minor=40_000_000, currency="UZS", url="https://elchi.uz/t/abc",
    )
    assert "Toshkent - Samarqand" in text
    assert "18.09.2026 09:00-11:00" in text  # displayed in Asia/Tashkent (AGENTS §6)
    assert "400 000 UZS" in text and "https://elchi.uz/t/abc" in text
    lowered = text.lower()
    for forbidden in ("+998", "telefon", "24/7", "kafolat"):
        assert forbidden not in lowered, forbidden


def test_public_url_falls_back_to_the_api_path_when_the_template_is_wrong() -> None:
    assert rules.public_url("abc", "https://elchi.uz/t/{token}") == "https://elchi.uz/t/abc"
    assert rules.public_url("abc", "https://elchi.uz/t/") == SHARE_LINK_PUBLIC_PATH.replace("{token}", "abc")
    assert rules.public_url("abc", None) == SHARE_LINK_PUBLIC_PATH.replace("{token}", "abc")


@pytest.mark.parametrize(
    ("status", "expired", "cta"),
    [("published", False, "open_app_to_offer"), ("published", True, "closed"), ("paused", False, "closed")],
)
def test_page_cta(status: str, expired: bool, cta: str) -> None:
    assert rules.page_cta(status=status, expired=expired) == cta


def test_ratio_never_invents_a_percentage() -> None:
    assert rules.Ratio(0, 0).value is None, "nothing measured is not 0 %"
    assert rules.Ratio(0, 5).value == 0.0
    assert rules.Ratio(3, 4).value == 0.75
    assert rules.Ratio(3, 4).small_sample is True
    assert rules.Ratio(30, KPI_SMALL_SAMPLE_BELOW + 10).small_sample is False
    assert rules.Ratio(0, 0).small_sample is False


def test_only_ratio_metrics_get_a_value() -> None:
    assert rules.metric_is_ratio(KpiMetric.LISTINGS_PUBLISHED.value) is False
    assert rules.metric_is_ratio(KpiMetric.BOOKING_COMPLETION.value) is True
    assert rules.kpi_target(KpiMetric.BOOKING_COMPLETION.value) == 0.90
    assert rules.kpi_target(KpiMetric.LISTINGS_PUBLISHED.value) is None
