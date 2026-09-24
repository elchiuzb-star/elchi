"""The operational promo report on PostgreSQL (referral stage 6, A6.2, ADR-0023 §20).

Real rows through the real services, read over HTTP: who may read it, what it counts in which grouping, that it
changes nothing (campaigns, budgets, lots, bookings, outbox), and that a budget shortfall is shown as an alert while
old obligations stay. SYNTHETIC values only.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.contracts.enums import PromoInstrument, PromoLedgerKind
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import utc_now
from app.modules.promotions import service as promo_service
from tests.pg.bookings.conftest import BW, bw  # noqa: F401  (fixtures)
from tests.pg.promotions.booking_world import FARE, H_LOT, P_LOT, PW
from tests.pg.promotions.conftest import COMMITMENT, FINANCE_CAPS
from tests.pg.promotions.test_promo_http_pg import (  # noqa: F401  (fixtures)
    _err,
    _h,
    _staff,
    api,
    pw,
)

pytestmark = pytest.mark.pg

TABLES = ("promo_campaigns", "promo_campaign_versions", "promo_budgets", "promo_budget_requests", "promo_obligations",
          "promo_lots", "promo_redemptions", "promo_ledger_transactions", "promo_enrollments", "promo_booking_terms",
          "bookings", "wallet_holds", "outbox_events")


def _period() -> dict[str, str]:
    today = utc_now().date()
    return {"from": (today - timedelta(days=1)).isoformat(), "to": (today + timedelta(days=1)).isoformat()}


def _report(api: TestClient, reader: int, group_by: str) -> dict:  # noqa: F811
    response = api.get("/api/v2/admin/promo/report", params={**_period(), "group_by": group_by},
                       headers=_h(reader, "finance", key=False, features=False))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _fingerprint(pw: PW) -> dict[str, tuple]:  # noqa: F811
    """Row count and a hash of every row of every table the report reads - it must change none of them."""
    return {table: tuple(pw.rows(f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t.id), '')) "
                                 f"FROM {table} t")[0]) for table in TABLES}


def test_report_needs_campaign_view_and_finance_reports_and_a_bounded_period(pw: PW, api: TestClient) -> None:  # noqa: F811
    operator, finance = _staff(pw, "operator"), _staff(pw, "finance")
    refused = api.get("/api/v2/admin/promo/report", params=_period(), headers=_h(operator, "operator", key=False))
    assert refused.status_code == 403 and _err(refused) == "FORBIDDEN"  # campaign view alone does not show money
    client = pw.ref.client()
    assert api.get("/api/v2/admin/promo/report", params=_period(),
                   headers=_h(client, "client", key=False)).status_code == 403
    today = utc_now().date()
    too_long = api.get("/api/v2/admin/promo/report", headers=_h(finance, "finance", key=False),
                       params={"from": (today - timedelta(days=366)).isoformat(), "to": today.isoformat()})
    assert too_long.status_code == 400 and _err(too_long) == "VALIDATION_ERROR"
    data = _report(api, finance, "service")
    assert (data["data_source"], data["currency"], data["amount_unit"], data["period"]["day_bounds"]) == (
        "operational", "UZS", "minor", "UTC")


def test_report_counts_a_real_promo_booking_in_every_grouping_and_writes_nothing(pw: PW, api: TestClient) -> None:  # noqa: F811
    finance = _staff(pw, "finance")
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    pw.combine(p_lot, h_lot)
    trip, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, FARE - P_LOT))
    pw.finish(trip[0], driver, booking.id, client)
    c_net = 2_000_000 - P_LOT - H_LOT

    before = _fingerprint(pw)
    by_service = _report(api, finance, "service")
    by_corridor = _report(api, finance, "corridor")
    by_version = _report(api, finance, "campaign_version")
    by_cohort = _report(api, finance, "cohort")
    assert _fingerprint(pw) == before  # read-only: no campaign, budget, lot, booking or outbox row touched

    [passenger] = [r["values"] for r in by_service["rows"] if r["key"] == "passenger"]
    assert (passenger["promo_bookings"], passenger["passenger_bonus_minor"], passenger["driver_credit_minor"],
            passenger["net_commission_agreed_minor"], passenger["net_commission_captured_minor"],
            passenger["net_commission_kept_minor"]) == (1, P_LOT, H_LOT, c_net, c_net, c_net)
    assert (passenger["spent_passenger_bonus_minor"], passenger["spent_driver_credit_minor"]) == (P_LOT, H_LOT)
    assert passenger["granted_passenger_bonus_minor"] == P_LOT and passenger["granted_driver_credit_minor"] == H_LOT

    [corridor] = by_corridor["rows"]
    assert corridor["key"].startswith("cor_")
    assert corridor["values"]["promo_bookings"] == 1 and corridor["values"]["net_commission_kept_minor"] == c_net
    assert corridor["values"]["enrollments"] is None  # not applicable to a corridor, never 0
    assert corridor["values"]["outstanding_liability_minor"] is None

    keys = {r["key"] for r in by_version["rows"]}
    assert len(keys) == 2 and all(k.startswith("pcm_") and k.endswith("/v1") for k in keys)
    assert all(r["values"]["promo_bookings"] is None for r in by_version["rows"])  # a booking can mix two campaigns

    # the test lots were granted without an enrollment: shown apart, never folded into a week
    assert [r["key"] for r in by_cohort["rows"]] == ["no_enrollment"]
    budgets = {b["campaign_id"]: b for b in by_service["budgets"]}
    assert all(b["alerts"] == [] and b["shortfall_minor"] == 0 for b in budgets.values())
    assert sum(b["consumed_minor"] for b in budgets.values()) == P_LOT + H_LOT


def test_report_cohort_is_the_enrollment_week_with_its_maturity(pw: PW, api: TestClient) -> None:  # noqa: F811
    finance = _staff(pw, "finance")
    campaign = pw.ref.campaign()
    referrer, referee = pw.ref.client(), pw.ref.client()
    attribution = pw.ref.attribute(referee, pw.ref.code(referrer))
    pw.ref.enroll(referee, attribution, campaign)
    data = _report(api, finance, "cohort")
    [row] = [r for r in data["rows"] if r["key"] != "no_enrollment"]
    assert row["cohort"]["anchor"] == "enrollment_week_asia_tashkent"
    assert (row["cohort"]["matured_d30"], row["cohort"]["matured_d60"]) == (False, False)  # just enrolled: immature
    assert (row["values"]["enrollments"], row["values"]["enrollments_open"], row["values"]["promised_open_minor"],
            row["values"]["outstanding_liability_minor"]) == (1, 1, COMMITMENT, COMMITMENT)


def test_report_shows_a_shortfall_as_an_alert_and_keeps_old_obligations(pw: PW, api: TestClient) -> None:  # noqa: F811
    finance = _staff(pw, "finance")
    campaign = pw.ref.campaign(allocate_minor=COMMITMENT * 2)
    pw.ref.promo.promise(campaign)
    pw.ref.promo.promise(campaign)
    with pw.db.session() as s:  # external funding really lost: recorded with evidence (G14), pauses the campaign
        promo_service.request_budget_change(s, actor_user_id=pw.ref.promo.finance_id, actor_capabilities=FINANCE_CAPS,
                                            campaign_id=campaign, kind=PromoLedgerKind.FUNDING_LOSS,
                                            amount_minor=COMMITMENT, reason="synthetic source refund",
                                            evidence_reference="SYNTHETIC-NOTICE")
        s.commit()
    public = pw.rows("SELECT public_id FROM promo_campaigns WHERE id = :c", c=campaign)[0][0]
    [row] = [b for b in _report(api, finance, "service")["budgets"]
             if b["campaign_id"] == format_public_id(PublicIdPrefix.PROMO_CAMPAIGN, public)]
    assert (row["allocated_minor"], row["promised_minor"], row["committed_minor"], row["shortfall_minor"],
            row["funded_commitment_minor"], row["available_for_new_minor"], row["reducible_minor"], row["alerts"]) == (
        COMMITMENT, COMMITMENT * 2, COMMITMENT * 2, COMMITMENT, COMMITMENT, 0, 0, ["budget_shortfall"])
    with pytest.raises(DomainError) as exc:  # no new promise while in shortfall ...
        pw.ref.promo.promise(campaign)
    assert exc.value.code in (ErrorCode.PROMO_BUDGET_EXHAUSTED, ErrorCode.FEATURE_DISABLED)
    with pw.db.session() as s:  # ... the funding loss already paused it; the old promises are still honoured
        assert promo_service.pause_exhausted_campaigns(s) == []
        s.commit()
    assert pw.scalar("SELECT count(*) FROM promo_obligations WHERE campaign_id = :c AND status = 'promised'",
                     c=campaign) == 4  # two enrollments x two sides, none cancelled
    assert pw.ref.promo.issues(campaign) == []
    assert pw.scalar("SELECT status FROM promo_campaigns WHERE id = :c", c=campaign) == "paused"
