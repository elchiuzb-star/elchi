"""U6 rating bucket (user decision 17.09.2026, option A) - spec §8.2, AC36.

The bucket is the short trust signal a client sees on an anonymous competing offer. These tests pin the two
things the spec is most insistent about: a new driver is never handed a score, and a single rating never buys
the badge that two hundred ratings earn.
"""

from __future__ import annotations

import pytest

from app.contracts import trust
from app.contracts.enums import RatingBucket, ServiceType


def summary(count: int, total: int) -> trust.ReputationSummary:
    return trust.ReputationSummary(
        user_id=1, service_type=ServiceType.PASSENGER, rating_count=count, rating_sum=total
    )


def test_a_driver_without_ratings_is_new_not_average_and_not_zero() -> None:
    fresh = summary(0, 0)
    assert fresh.rating_bucket is RatingBucket.NEW_VERIFIED
    assert fresh.average_rating is None, "no ratings means no number at all (S2)"


@pytest.mark.parametrize("count", [1, 2])
def test_one_or_two_five_star_ratings_do_not_earn_the_good_badge(count: int) -> None:
    """§8.2: 1 x 5.0 and 200 x 4.8 must not look the same. Below the minimum there is no judgement."""
    assert summary(count, 5 * count).rating_bucket is RatingBucket.NEW_VERIFIED


def test_the_bucket_starts_at_the_minimum_count() -> None:
    assert trust.RATING_BUCKET_MIN_COUNT == 3
    assert summary(3, 15).rating_bucket is RatingBucket.GOOD


@pytest.mark.parametrize(
    ("count", "total", "expected"),
    [
        (10, 48, RatingBucket.GOOD),    # 4.8
        (10, 40, RatingBucket.GOOD),    # exactly 4.0 - the boundary belongs to the better group
        (10, 39, RatingBucket.MIXED),   # 3.9
        (10, 30, RatingBucket.MIXED),   # exactly 3.0
        (10, 29, RatingBucket.LOW),     # 2.9
        (4, 4, RatingBucket.LOW),       # 1.0 - a bad record is not hidden behind "new"
    ],
)
def test_thresholds(count: int, total: int, expected: RatingBucket) -> None:
    assert summary(count, total).rating_bucket is expected


def test_the_bucket_never_uses_the_internal_ranking_prior() -> None:
    """``adjusted_rating`` carries the 4.5 prior for sorting; reading it as a display value would hand a brand
    new driver a "good" badge (§8.2 forbids exactly that)."""
    fresh = summary(0, 0)
    assert fresh.adjusted_rating == pytest.approx(4.5)
    assert fresh.rating_bucket is RatingBucket.NEW_VERIFIED

    poor = summary(3, 3)  # average 1.0, but the prior drags the internal value up
    assert poor.adjusted_rating > 3.0
    assert poor.rating_bucket is RatingBucket.LOW, "the displayed group follows the real average, not the prior"


def test_bucket_values_are_the_four_agreed_groups() -> None:
    assert {b.value for b in RatingBucket} == {"new_verified", "good", "mixed", "low"}
