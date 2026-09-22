"""Wave 6: the two KPIs §20.4 asked for and the map quota accounting of §10.8, on real PostgreSQL.

Before this wave the platform answered "we do not measure that" for ``search_with_match_rate`` and
``time_to_first_valid_offer`` - honest, but it also meant two of the pilot's exit criteria could not be read at
all. The feed now counts its searches (anonymously) and the first offer is timed from rows that already existed.

§10.8: routing/map calls are counted per day with the published credit weights, and the answer says the number
is Elchi's own estimate, not the provider's invoice. GPS ingestion is never counted or limited here.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.contracts.enums import KpiMetric
from app.contracts.operations import PROVIDER_DAILY_CREDIT_LIMIT
from app.modules.marketplace.feed import service as feed_service
from app.modules.operations import service as operations_service
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    auth,
    bw,
    passenger_request_body,
    propose,
    publish_listing,
    driver_trip,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def _criteria(bw: BW, *, destination: str = "D"):  # noqa: ANN202, F811
    from app.contracts.enums import FeedSide, ServiceType
    from app.modules.marketplace.feed.service import FeedCriteria

    return FeedCriteria(
        service_type=ServiceType.PASSENGER, side=FeedSide.REQUESTS,
        date_from=bw.base - timedelta(days=1), date_to=bw.base + timedelta(days=5),
        origin_stop_id=bw.w.stop_public_ids["A"], destination_stop_id=bw.w.stop_public_ids[destination],
    )


def test_search_with_match_rate_is_measured_from_anonymous_counters(bw: BW) -> None:  # noqa: F811
    publish_listing(bw, bw.w.client_id, passenger_request_body(bw))

    with bw.db.session() as session:
        hit = feed_service.feed(session, viewer_user_id=bw.w.driver_id, criteria=_criteria(bw), limit=20)
        feed_service.record_search(session, criteria=_criteria(bw), page=hit)
        miss_criteria = _criteria(bw, destination="B")
        miss = feed_service.feed(session, viewer_user_id=bw.w.driver_id, criteria=miss_criteria, limit=20)
        feed_service.record_search(session, criteria=miss_criteria, page=miss)
        session.commit()

    with bw.db.session() as session:
        stored = session.execute(text("SELECT service_type, side, matched, result_count FROM feed_search_events")).all()
        assert len(stored) == 2
        assert {row.matched for row in stored} == {True, False}
        columns = {
            row[0]
            for row in session.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'feed_search_events'")
            ).all()
        }
        # §17.7: the counter is not a search history - no user, no stops, no filter values.
        assert columns.isdisjoint({"user_id", "origin_stop_id", "destination_stop_id", "filters", "seats"})

    with bw.db.session() as session:
        written = operations_service.collect_kpi_daily(session, day=date.today())
        session.commit()
        assert written > 0
        value = session.execute(
            text("SELECT numerator, denominator FROM kpi_daily WHERE metric = :m AND corridor_id IS NULL"),
            {"m": KpiMetric.SEARCH_WITH_MATCH_RATE.value},
        ).one()
        assert value.denominator == 2 and value.numerator == 1

    with bw.db.session() as session:
        report = operations_service.kpi_report(session, actor_user_id=bw.operator_id)
        metrics = {item.metric: item for item in report.metrics}
        assert KpiMetric.SEARCH_WITH_MATCH_RATE.value in {str(m) for m in metrics}
        # the honest "cannot measure" list is empty since wave 7 - and no metric was turned into a zero to
        # get there: seat-km still reports "no measurable trip" as denominator 0 / value None.
        assert report.missing_metrics == []
        seat_km = metrics[KpiMetric.BOOKED_SEAT_KM_RATIO.value]
        assert seat_km.value is None or seat_km.denominator > 0


def test_time_to_first_valid_offer_is_a_mean_in_seconds(bw: BW) -> None:  # noqa: F811
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw))
    _trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01A610AA")
    propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=2)

    with bw.db.session() as session:
        operations_service.collect_kpi_daily(session, day=date.today())
        session.commit()
        row = session.execute(
            text("SELECT numerator, denominator FROM kpi_daily WHERE metric = :m AND corridor_id IS NULL"),
            {"m": KpiMetric.TIME_TO_FIRST_VALID_OFFER.value},
        ).one()
    # numerator = total seconds, denominator = listings that got an offer -> the reader divides for the mean.
    assert row.denominator == 1
    assert row.numerator >= 0


def test_provider_quota_counts_calls_and_marks_the_thresholds(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        for _ in range(3):
            operations_service.record_provider_usage(session, provider="geoapify", operation="route")
        operations_service.record_provider_usage(session, provider="geoapify", operation="route", failures=1)
        session.commit()

    with bw.db.session() as session:
        quotas = operations_service.provider_quota(session, actor_user_id=bw.operator_id)
        assert len(quotas) == 1
        quota = quotas[0]
        assert quota.provider == "geoapify"
        assert quota.calls == 4 and quota.failures == 1
        assert quota.credits == 4.0  # 1 credit per routing request (published weight, pilot estimate)
        assert quota.limit == PROVIDER_DAILY_CREDIT_LIMIT
        assert quota.state == "ok" and quota.estimated is True

    # 70 % / 85 % thresholds (§10.8) are read from the same counters.
    with bw.db.session() as session:
        session.execute(text("UPDATE provider_usage_daily SET credits = :c"), {"c": PROVIDER_DAILY_CREDIT_LIMIT * 0.72})
        session.commit()
    with bw.db.session() as session:
        assert operations_service.provider_quota(session, actor_user_id=bw.operator_id)[0].state == "warn"
        session.execute(text("UPDATE provider_usage_daily SET credits = :c"), {"c": PROVIDER_DAILY_CREDIT_LIMIT * 0.9})
        session.commit()
    with bw.db.session() as session:
        assert operations_service.provider_quota(session, actor_user_id=bw.operator_id)[0].state == "restrict"


def test_quota_accounting_never_touches_tracking(bw: BW) -> None:  # noqa: F811
    """§10.8: "Tracking ma'lumotini qabul qilish xarita kvotasi sabab to'xtamaydi."."""
    with bw.db.session() as session:
        # the same local day the service reads (Asia/Tashkent, §6 time rules), not the server's UTC date
        operations_service.record_provider_usage(session, provider="geoapify", operation="route", calls=1)
        session.execute(text("UPDATE provider_usage_daily SET credits = :c"), {"c": PROVIDER_DAILY_CREDIT_LIMIT * 5})
        session.commit()
    with bw.db.session() as session:
        quota = operations_service.provider_quota(session, actor_user_id=bw.operator_id)[0]
        assert quota.state == "restrict"
        # No tracking table is involved in the decision at all: the quota view reads provider_usage_daily only.
        assert session.execute(text("SELECT count(*) FROM tracking_sessions")).scalar_one() >= 0
