"""Unit tests: §8.2-§8.4 ranking (incl. §8.3 example), total-price comparison, verified-stop order, contracts (A5)."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.enums import EventType, FeedSort, MatchGroup, MatchType, PriceBasis, ReputationLabel, ServiceType
from app.contracts.feed import NEUTRAL_PRICE_SCORE, SAVED_SEARCH_MAX_PER_USER
from app.contracts.trust import ReputationSummary
from app.modules.marketplace.feed import rules
from app.modules.marketplace.feed.schemas import SavedSearchCreate

NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    ("components", "expected"),
    [
        ({"M": 1.00, "T": 0.95, "R": 0.90, "P": 1 / 3, "E": 0.80}, 81.67),
        ({"M": 1.00, "T": 0.85, "R": 0.95, "P": 0.60, "E": 1.00}, 88.00),
        ({"M": 0.65, "T": 0.70, "R": 0.75, "P": 1.00, "E": 0.20}, 70.50),
    ],
)
def test_spec_8_3_example_scores(components: dict[str, float], expected: float) -> None:
    assert rules.client_score(**components) == pytest.approx(expected, abs=0.005)


def test_spec_8_3_price_component_from_band() -> None:
    # 2 people, L=300 000, U=450 000 (totals)
    assert rules.price_score(400_000, 300_000, 450_000) == pytest.approx(1 / 3)
    assert rules.price_score(360_000, 300_000, 450_000) == pytest.approx(0.60)
    assert rules.price_score(300_000, 300_000, 450_000) == 1.0
    assert rules.price_score(500_000, 300_000, 450_000) == 0.0
    assert rules.price_score(400_000, None, None) == NEUTRAL_PRICE_SCORE
    assert rules.price_score(400_000, 300_000, 300_000) == NEUTRAL_PRICE_SCORE  # U == L


def test_totals_are_compared_for_the_same_quantity() -> None:
    per_seat = rules.comparable_total_minor(
        price_basis=PriceBasis.PER_SEAT, unit_price_minor=20_000_000, total_minor=80_000_000, listing_quantity=4, wanted_quantity=2
    )
    total = rules.comparable_total_minor(
        price_basis=PriceBasis.TOTAL, unit_price_minor=39_000_000, total_minor=39_000_000, listing_quantity=2, wanted_quantity=2
    )
    assert (per_seat, total) == (40_000_000, 39_000_000)
    assert rules.comparable_total_minor(
        price_basis=PriceBasis.TOTAL, unit_price_minor=39_000_000, total_minor=39_000_000, listing_quantity=3, wanted_quantity=2
    ) is None  # per_seat and total never mix
    assert rules.band_totals(ServiceType.PASSENGER, 150_000, 225_000, 2) == (300_000, 450_000)
    assert rules.band_totals(ServiceType.PARCEL, 50_000, 90_000, 1) == (50_000, 90_000)


def test_driver_price_score_never_rewards_cheapness() -> None:
    reference = 400_000
    scores = [rules.driver_price_score(total, reference) for total in (200_000, 300_000, 400_000, 500_000, 700_000)]
    assert scores == sorted(scores)
    assert rules.driver_price_score(400_000, reference) == pytest.approx(0.5)
    assert rules.driver_price_score(100_000, None) == NEUTRAL_PRICE_SCORE
    low = rules.driver_score(M=1, T=1, Y=rules.driver_price_score(300_000, reference), C=0.9, F=0.5)
    high = rules.driver_score(M=1, T=1, Y=rules.driver_price_score(450_000, reference), C=0.9, F=0.5)
    assert low < high


def test_ac36_adjusted_rating_one_five_star_is_not_first() -> None:
    one = ReputationSummary(user_id=1, service_type=ServiceType.PASSENGER, rating_count=1, rating_sum=5)
    many = ReputationSummary(user_id=2, service_type=ServiceType.PASSENGER, rating_count=200, rating_sum=960)
    new = ReputationSummary(user_id=3, service_type=ServiceType.PASSENGER)
    assert rules.reliability(many) > rules.reliability(one)
    assert new.average_rating is None and new.label is ReputationLabel.NEW_VERIFIED  # no fake 4.5
    key_one = rules.sort_key(FeedSort.RATING, group=MatchGroup.PRIMARY, score=0, comparable_total=None, when=NOW,
                             adjusted_rating=one.adjusted_rating, rating_count=1, listing_id=1)
    key_many = rules.sort_key(FeedSort.RATING, group=MatchGroup.PRIMARY, score=0, comparable_total=None, when=NOW,
                              adjusted_rating=many.adjusted_rating, rating_count=200, listing_id=2)
    assert key_many < key_one


def test_time_experience_fit_and_groups() -> None:
    assert rules.time_score(NOW, NOW, 0) == 1.0
    assert rules.time_score(NOW + timedelta(minutes=1), NOW, 0) == 0.0
    assert rules.time_score(NOW + timedelta(minutes=30), NOW, 60) == pytest.approx(0.5)
    assert rules.experience(0) == 0.0 and rules.experience(100) == pytest.approx(1.0) and rules.experience(10_000) == 1.0
    assert rules.fit_score(2, 4) == 0.5 and rules.fit_score(5, 4) is None and rules.fit_score(1, None) == 0.5
    assert rules.group_for(MatchType.ALTERNATIVE) is MatchGroup.ALTERNATIVE and rules.group_for(MatchType.EXACT) is MatchGroup.PRIMARY
    primary = rules.sort_key(FeedSort.RECOMMENDED, group=MatchGroup.PRIMARY, score=10, comparable_total=1, when=NOW,
                             adjusted_rating=4.5, rating_count=0, listing_id=9)
    alternative = rules.sort_key(FeedSort.RECOMMENDED, group=MatchGroup.ALTERNATIVE, score=99, comparable_total=1, when=NOW,
                                 adjusted_rating=4.5, rating_count=0, listing_id=1)
    assert primary < alternative


def test_stop_segment_match_verified_order() -> None:
    order = [{1: [0], 2: [1], 3: [2], 4: [3]}]  # A=1 -> B=2 -> C=3 -> D=4
    assert rules.stop_segment_match(order, {1}, {4}, 1, 4) is MatchType.EXACT
    assert rules.stop_segment_match(order, {1}, {4}, 2, 3) is MatchType.ON_ROUTE
    assert rules.stop_segment_match(order, {1}, {4}, 3, 2) is None  # reverse (AC16)
    assert rules.stop_segment_match(order, {4}, {1}, 2, 3) is None  # wanted direction reversed
    assert rules.stop_segment_match(order, {2}, {3}, 1, 4) is None  # request longer than the wanted segment
    assert rules.stop_segment_match([], {1}, {4}, 2, 3) is None  # no confirmed route -> no guess


def test_migration_limit_literal_matches_contract() -> None:
    spec = importlib.util.spec_from_file_location(
        "migration_0061_unit", ROOT / "alembic" / "versions" / "20260916_0061_marketplace_saved_searches.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.SAVED_SEARCH_LIMIT == SAVED_SEARCH_MAX_PER_USER
    assert "CONSTRAINT = 'saved_search_limit'" in (ROOT / "alembic" / "versions" / "20260916_0061_marketplace_saved_searches.py").read_text(encoding="utf-8")


def test_saved_search_create_requires_exactly_one_reference_per_end() -> None:
    base = {
        "service_type": "passenger",
        "side": "offers",
        "time_window_start": "2026-09-20T05:00:00Z",
        "time_window_end": "2026-09-21T05:00:00+05:00",
    }
    SavedSearchCreate.model_validate({**base, "origin_stop_id": "stp_x", "destination_region_id": "reg_y"})
    for bad in (
        {"destination_stop_id": "stp_y"},
        {"origin_stop_id": "stp_x", "origin_region_id": "reg_x", "destination_stop_id": "stp_y"},
        {"origin_stop_id": "stp_x", "destination_stop_id": "stp_y", "time_window_end": "2026-09-20T04:00:00Z"},
        {"origin_stop_id": "stp_x", "destination_stop_id": "stp_y", "time_window_start": "2026-09-20T05:00:00"},
    ):
        with pytest.raises(ValidationError):
            SavedSearchCreate.model_validate({**base, **bad})


def test_consumer_exports_and_missing_reputation_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.marketplace.feed import consumers
    from app.modules.marketplace.feed import service as feed_service

    assert [c.name for c in consumers.CONSUMERS] == ["saved_search_matcher"]
    assert consumers.CONSUMERS[0].event_types == frozenset({EventType.LISTING_PUBLISHED})
    assert consumers.RELEVANCE_CHECKS == {EventType.SAVED_SEARCH_MATCHED: feed_service.saved_search_match_still_relevant}

    import app.modules.trust_support.service as trust_service

    monkeypatch.delattr(trust_service, "reputation_summaries")
    summaries = feed_service.load_reputations(None, [7, 3], service_type=ServiceType.PASSENGER)  # type: ignore[arg-type]
    assert summaries == {
        3: ReputationSummary(user_id=3, service_type=ServiceType.PASSENGER),
        7: ReputationSummary(user_id=7, service_type=ServiceType.PASSENGER),
    }
