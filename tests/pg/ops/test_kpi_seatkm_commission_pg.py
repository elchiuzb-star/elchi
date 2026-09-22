"""Wave 7 / §20.4: the last two KPIs, measured from stored data and reconciled against their sources.

``booked_seat_km_ratio`` uses the distance a human confirmed with the route version - never a straight line and
never a live routing call - and excludes trips whose route has no usable distance from *both* sides, reporting
that exclusion as ``seat_km_route_coverage``.

``net_commission_per_corridor`` is what the ledger credited to ``commission_revenue`` minus what was reversed.
Holds, top-ups and the legacy calculated fee cannot appear there by construction, and the value is revenue, not
profit: the report shows the amount with the number of bookings behind it and never as a ratio.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.contracts.enums import KpiMetric
from app.modules.operations import rules as ops_rules
from app.modules.operations import service as operations_service
from app.modules.wallet import service as wallet_service
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    accept,
    auth,
    bw,
    driver_trip,
    fund,
    parcel_request_body,
    passenger_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def _collect(bw: BW, day: date | None = None) -> dict[str, tuple[int, int]]:  # noqa: F811
    target = day or date.today()
    with bw.db.session() as session:
        operations_service.collect_kpi_daily(session, day=target)
        session.commit()
    return {
        metric: (int(numerator), int(denominator))
        for metric, numerator, denominator in rows(
            bw.db,
            "SELECT metric, numerator, denominator FROM kpi_daily WHERE day = :d AND corridor_id IS NULL",
            d=target,
        )
    }


def _trip_day(bw: BW) -> date:  # noqa: F811
    """The local day the fixture trip departs on (the collector works in the display timezone)."""
    value = scalar(bw.db, "SELECT (planned_start_at AT TIME ZONE 'Asia/Tashkent')::date FROM trips ORDER BY id LIMIT 1")
    return value


def test_seat_km_ratio_uses_the_confirmed_route_distance(bw: BW) -> None:  # noqa: F811
    _listing, trip_id, _trip_public, ref = request_with_driver_proposal(bw, seats=2, trip_seats=4)
    booking = accept(bw, ref, bw.w.client_id)

    metrics = _collect(bw, _trip_day(bw))
    numerator, denominator = metrics[KpiMetric.BOOKED_SEAT_KM_RATIO.value]

    # reconcile against the source rows: seats x (dropoff - pickup) cumulative distance, capacity x route length
    expected_booked = scalar(
        bw.db,
        """
        SELECT b.seats * (ds.cumulative_distance_m - ps.cumulative_distance_m)
          FROM bookings b
          JOIN trip_stop_occurrences po ON po.trip_id = b.trip_id AND po.seq = b.pickup_occurrence_seq
          JOIN trip_stop_occurrences do_ ON do_.trip_id = b.trip_id AND do_.seq = b.dropoff_occurrence_seq
          JOIN route_version_stops ps ON ps.route_version_id = b.route_version_id AND ps.seq = po.route_version_stop_seq
          JOIN route_version_stops ds ON ds.route_version_id = b.route_version_id AND ds.seq = do_.route_version_stop_seq
         WHERE b.id = :b
        """,
        b=booking.id,
    )
    expected_offered = scalar(
        bw.db,
        """
        SELECT t.seat_capacity * (SELECT max(cumulative_distance_m) FROM route_version_stops
                                   WHERE route_version_id = t.route_version_id)
          FROM trips t WHERE t.id = :t
        """,
        t=trip_id,
    )
    assert numerator == int(expected_booked)
    assert denominator == int(expected_offered)
    assert 0 < numerator <= denominator, "a booking can never fill more seat-metres than the trip offers"

    coverage = metrics[KpiMetric.SEAT_KM_ROUTE_COVERAGE.value]
    assert coverage == (1, 1), "the trip's route has a distance, so the ratio covers all of it"


def test_trip_without_a_route_distance_leaves_both_sides_and_is_reported(bw: BW) -> None:  # noqa: F811
    _listing, trip_id, _trip_public, ref = request_with_driver_proposal(bw, seats=2, trip_seats=4)
    accept(bw, ref, bw.w.client_id)
    day = _trip_day(bw)
    with_distance = _collect(bw, day)[KpiMetric.BOOKED_SEAT_KM_RATIO.value]

    # A second trip whose route version has no per-stop distances recorded. (A route version itself must carry a
    # positive distance - the DB refuses 0 - so the realistic gap is a version whose stop distances are missing.)
    second_trip, _second_public = driver_trip(bw, bw.w.driver2_id, "01A701AA")
    with bw.db.session() as session:
        session.execute(
            text(
                "INSERT INTO route_versions (public_id, corridor_id, created_by_user_id, source, provider, "
                "provider_version, request_hash, geometry, distance_m, duration_s, is_estimate, status, "
                "confirmed_at, created_at, updated_at) "
                "SELECT gen_random_uuid(), corridor_id, created_by_user_id, source, provider, provider_version, "
                "       'no-stop-distance-' || id, geometry, distance_m, duration_s, true, status, confirmed_at, "
                "       now(), now() "
                "  FROM route_versions ORDER BY id LIMIT 1"
            )
        )
        new_route = session.execute(text("SELECT max(id) FROM route_versions")).scalar_one()
        # the version exists, its stop distances do not
        session.execute(
            text("UPDATE trips SET route_version_id = :new WHERE id = :t"), {"new": new_route, "t": second_trip}
        )
        session.commit()

    metrics = _collect(bw, day)
    assert metrics[KpiMetric.BOOKED_SEAT_KM_RATIO.value] == with_distance, (
        "a trip without a confirmed distance changes neither side of the ratio"
    )
    assert metrics[KpiMetric.SEAT_KM_ROUTE_COVERAGE.value] == (1, 2), "the gap is reported, not hidden"


def test_cancelled_booking_and_parcel_do_not_count_as_booked_seat_km(bw: BW) -> None:  # noqa: F811
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw, seats=2, trip_seats=4)
    booking = accept(bw, ref, bw.w.client_id)
    day = _trip_day(bw)
    before = _collect(bw, day)[KpiMetric.BOOKED_SEAT_KM_RATIO.value]
    assert before[0] > 0

    with bw.db.session() as session:
        # the DB CHECK refuses a cancelled row without its reason and fault side - fill them like the real command
        session.execute(
            text(
                "UPDATE bookings SET service_status = 'cancelled', cancelled_at = now(), "
                "cancelled_by_side = 'client', cancel_reason_code = 'client_changed_plan', fault_side = 'client' "
                "WHERE id = :b"
            ),
            {"b": booking.id},
        )
        session.commit()

    after = _collect(bw, day)[KpiMetric.BOOKED_SEAT_KM_RATIO.value]
    assert after[0] == 0, "a seat that was never consumed is not booked seat-km"
    assert after[1] == before[1], "the offered side does not change when a booking is cancelled"


def test_net_commission_is_capture_minus_reversal_and_never_a_ratio(bw: BW) -> None:  # noqa: F811
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw, seats=2, trip_seats=4)
    fund(bw, bw.w.driver_id, 100_000_000, bw.finance_id)
    booking = accept(bw, ref, bw.w.client_id)

    with bw.db.session() as session:
        captured = wallet_service.capture_fee(session, booking_id=booking.id, actor_user_id=bw.finance_id)
        session.commit()
        captured_minor = captured.captured_minor

    today = date.today()
    metrics = _collect(bw, today)
    numerator, denominator = metrics[KpiMetric.NET_COMMISSION_PER_CORRIDOR.value]
    assert numerator == captured_minor
    assert denominator == 1, "the pair says how many bookings are behind the amount"

    # reconcile against the ledger itself
    ledger_total = scalar(
        bw.db,
        """
        SELECT COALESCE(sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor ELSE -e.amount_minor END), 0)
          FROM ledger_entries e
          JOIN ledger_accounts a ON a.id = e.account_id
         WHERE a.code = 'commission_revenue'
        """,
    )
    assert int(ledger_total) == numerator

    # a reversal reduces the day it is posted on; summing days over a range stays consistent
    with bw.db.session() as session:
        from app.contracts.enums import STAFF_ROLE_CAPABILITIES

        wallet_service.reverse_fee(
            session, booking_id=booking.id, amount_minor=captured_minor // 2, actor_user_id=bw.finance_id,
            actor_capabilities=STAFF_ROLE_CAPABILITIES["super_admin"], second_approver_id=bw.super_id,
            reason="mijoz shikoyati asosli",
        )
        session.commit()
    after = _collect(bw, today)[KpiMetric.NET_COMMISSION_PER_CORRIDOR.value]
    assert after[0] == captured_minor - captured_minor // 2

    with bw.db.session() as session:
        report = operations_service.kpi_report(session, actor_user_id=bw.operator_id)
    by_metric = {item.metric: item for item in report.metrics}
    money = by_metric[KpiMetric.NET_COMMISSION_PER_CORRIDOR.value]
    assert money.value is None, "an amount is never shown as a percentage"
    assert money.numerator == after[0]
    assert report.missing_metrics == [], "§20.4 has no unmeasurable metric left"
    assert ops_rules.metric_is_ratio(KpiMetric.NET_COMMISSION_PER_CORRIDOR.value) is False


def test_topups_and_holds_never_reach_the_commission_metric(bw: BW) -> None:  # noqa: F811
    """A hold is not a ledger row and a top-up credits the driver's prepaid liability, not revenue (§9.1)."""
    _listing, _trip_id, _trip_public, ref = request_with_driver_proposal(bw, seats=2, trip_seats=4)
    fund(bw, bw.w.driver_id, 100_000_000, bw.finance_id)  # approved top-up -> ledger, but not revenue
    accept(bw, ref, bw.w.client_id)  # creates a hold, no capture yet

    metrics = _collect(bw, date.today())
    assert metrics[KpiMetric.NET_COMMISSION_PER_CORRIDOR.value] == (0, 0), "held commission is not revenue"
    assert scalar(bw.db, "SELECT count(*) FROM wallet_holds WHERE status = 'active'") >= 1
