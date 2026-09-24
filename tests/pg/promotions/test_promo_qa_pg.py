"""QA #1-#24 gaps closed on PostgreSQL (referral stage 6, A6.3, ADR-0023 §20; docs/referral/QA_REPORT.md).

Each test names its QA item. Real services and HTTP routers; no sleep orders anything. SYNTHETIC values only.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import PromoInstrument
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.promotions import jobs, qualification
from tests.pg.bookings.conftest import BW, bw  # noqa: F401  (fixtures)
from tests.pg.promotions.booking_world import FARE, H_LOT, P_LOT, PW, use_policy
from tests.pg.promotions.referral_world import Ref, enable_promotions
from tests.pg.promotions.test_promo_booking_pg import _enrolled_client, _lots_of
from tests.pg.promotions.test_promo_http_pg import (  # noqa: F401  (fixtures)
    _err,
    _h,
    _staff,
    api,
    pw,
)
from tests.pg.promotions.test_promo_t4_pg import _operator_cancel

pytestmark = pytest.mark.pg


def _served(pw: PW, client: int, driver: int, *, consent: tuple[int, int] | None = None, capture: bool = True):  # noqa: F811, ANN202
    trip, ref = pw.offer(client, driver)
    booking = pw.accept(ref, client, consent=consent)
    cash = consent[1] if consent else FARE
    pw.board_and_depart(trip[0], driver, [(booking.id, client)])
    pw.acknowledge_cash(booking.id, client, pw.report_cash(booking.id, driver, cash))
    pw.finish(trip[0], driver, booking.id, client, capture=capture)
    return booking, trip, ref


def _process(pw: PW, enrollment: int, now) -> None:  # noqa: F811, ANN001
    """What the worker does for one enrollment: events, the enrollment itself, then the expiry sweep."""
    with pw.db.session() as s:
        qualification.process_qualification_events(s, now=now)
        qualification.process_enrollment(s, enrollment_id=enrollment, now=now)
        jobs.expire_enrollments(s, now=now)
        s.commit()


# --- QA #2: a replayed attribution over HTTP is the same attribution ---------------------------------------------------


def test_qa2_an_attribution_replayed_over_http_with_the_same_key_is_one_attribution(pw: PW, api: TestClient) -> None:  # noqa: F811
    referee, code = pw.ref.client(), pw.ref.code(pw.ref.client())
    headers = _h(referee, "client")
    first = api.post("/api/v2/referrals/attribution", headers=headers, json={"code": code, "audience": "client"})
    again = api.post("/api/v2/referrals/attribution", headers=headers, json={"code": code, "audience": "client"})
    assert (first.status_code, again.status_code) == (201, 201), again.text
    assert first.json()["data"]["id"] == again.json()["data"]["id"]
    assert pw.ref.count("referral_attributions", "referee_user_id = :u", u=referee) == 1


# --- QA #4: a real cancelled booking never qualifies ---------------------------------------------------------------------


def test_qa4_a_real_cancelled_booking_gives_no_reward_and_the_promise_is_released(pw: PW) -> None:  # noqa: F811
    referee, enrollment, campaign = _enrolled_client(pw)
    trip, ref = pw.offer(referee, pw.bw.w.driver_id)
    booking = pw.accept(ref, referee)
    _operator_cancel(pw, booking.id, "client")
    deadline = pw.scalar("SELECT qualification_deadline FROM promo_enrollments WHERE id = :e", e=enrollment)
    _process(pw, enrollment, deadline - timedelta(hours=1))
    assert _lots_of(pw, enrollment) == []  # nothing before the deadline
    _process(pw, enrollment, deadline + timedelta(days=3))
    assert _lots_of(pw, enrollment) == []  # and nothing after it
    assert pw.scalar("SELECT status FROM promo_enrollments WHERE id = :e", e=enrollment) == "released"
    assert pw.scalar("SELECT count(*) FROM promo_obligations WHERE enrollment_id = :e AND status = 'promised'",
                     e=enrollment) == 0  # the reserve went back to the budget
    assert pw.ref.promo.issues(campaign) == []


# --- QA #12: a commission above zero but below O + M gives no subsidy in the real flow --------------------------------


@pytest.fixture
def pw_low_fee(bw: BW, promo) -> PW:  # noqa: ANN001, F811
    """A world whose (only) campaign commission policy is 0.5 %: C = 1 000 so'm < O + M = 2 000 so'm (synthetic)."""
    enable_promotions(promo.pg_db)
    use_policy(bw, 50)
    return PW(bw, Ref(promo))


def test_qa12_a_small_commission_below_cost_plus_margin_gives_no_discount_in_the_real_flow(pw_low_fee: PW) -> None:
    pw = pw_low_fee  # noqa: F811 - this test runs in the low-fee world
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT)
    pw.combine(p_lot, h_lot)
    trip, ref = pw.offer(client, driver)
    with pytest.raises(DomainError) as exc:  # a consent to a discount that has no room is stale, never applied
        pw.accept(ref, client, consent=(P_LOT, FARE - P_LOT))
    assert exc.value.code is ErrorCode.PROMO_QUOTE_STALE
    booking = pw.accept(ref, client)
    terms = pw.terms(booking.id)
    assert terms == [] or (terms[0]["passenger_bonus_minor"], terms[0]["driver_credit_minor"]) == (0, 0)
    assert pw.hold(booking.id)[:2] == (100_000, "active")  # the full small commission, nothing subsidised
    assert (pw.lot_row(p_lot)["reserved_minor"], pw.lot_row(h_lot)["reserved_minor"]) == (0, 0)
    assert pw.ref.promo.issues() == []


# --- QA #19: the referrer's page shows no trip, route, phone or identity of the friend ----------------------------------


def test_qa19_the_referrers_page_never_shows_the_friends_trip_route_or_phone(pw: PW, api: TestClient) -> None:  # noqa: F811
    referrer = pw.ref.client()
    campaign = pw.ref.campaign()
    referee = pw.ref.client()
    attribution = pw.ref.attribute(referee, pw.ref.code(referrer))
    pw.ref.enroll(referee, attribution, campaign)
    booking, trip, ref = _served(pw, referee, pw.bw.w.driver_id)  # the friend travels
    page = api.get("/api/v2/me/referrals", headers=_h(referrer, "client", key=False))
    assert page.status_code == 200, page.text
    body = page.text
    secrets = [str(r[0]) for r in pw.rows("SELECT phone FROM users WHERE id IN (:a, :b, :c)",
                                            a=referee, b=referrer, c=pw.bw.w.driver_id)]
    secrets += [ref.listing_id, ref.thread_id, ref.version_id, str(trip[1])]
    secrets.append(format_public_id(PublicIdPrefix.BOOKING, pw.rows(
        "SELECT public_id FROM bookings WHERE id = :b", b=booking.id)[0][0]))
    secrets += [str(r[0]) for r in pw.rows("SELECT full_name FROM users WHERE id IN (:a, :c) AND full_name IS NOT NULL",
                                           a=referee, c=pw.bw.w.driver_id)]
    assert [s for s in secrets if s and s in body] == []
    for word in ("phone", "route", "trip", "stop", "corridor", "booking", "full_name", "plate"):
        assert word not in body.lower(), word
    data = page.json()["data"]
    assert [e["side"] for e in data["enrollments"]] == ["referrer"]
    assert all(e.get("progress") is None for e in data["enrollments"])  # the friend's progress is not the referrer's


# --- QA #20: a worker whose connection dies before COMMIT grants nothing; the rerun grants once -------------------------


def test_qa20_a_worker_whose_connection_dies_mid_job_grants_nothing_and_the_rerun_grants_once(pw: PW) -> None:  # noqa: F811
    referee, enrollment, campaign = _enrolled_client(pw)
    booking, _, _ = _served(pw, referee, pw.bw.w.driver_id)
    with pw.db.session() as s:
        ready = qualification.read_evidence(s, booking.id).conditions_met_at + timedelta(hours=48)
    crashed = pw.db.session()
    qualification.process_qualification_events(crashed, now=ready)
    qualification.process_enrollment(crashed, enrollment_id=enrollment, now=ready)
    assert crashed.execute(text("SELECT count(*) FROM promo_lots l JOIN promo_obligations o ON o.id = l.obligation_id "
                                "WHERE o.enrollment_id = :e"), {"e": enrollment}).scalar() == 2  # done, not committed
    pid = crashed.execute(text("SELECT pg_backend_pid()")).scalar()
    with pw.db.engine.begin() as killer:  # the worker's server connection is cut (process killed, network lost)
        assert killer.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar() is True
    with pytest.raises(DBAPIError):
        crashed.commit()
    crashed.close()
    assert _lots_of(pw, enrollment) == []  # nothing of the dead transaction survived
    for _ in range(2):  # the job runs again (and once more, as a lost acknowledgement would cause)
        _process(pw, enrollment, ready)
    assert len(_lots_of(pw, enrollment)) == 2
    assert pw.scalar("SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'grant' AND campaign_id = :c",
                     c=campaign) == 2
    assert pw.ref.promo.issues() == []


# --- QA #24: reconciliation over HTTP, including promo terms against the real commission money -------------------------


def test_qa24_reconciliation_over_http_matches_promo_terms_to_the_real_commission(pw: PW, api: TestClient) -> None:  # noqa: F811
    operator = _staff(pw, "operator")
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    pw.combine(pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT), pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT))
    booking, _, _ = _served(pw, client, driver, consent=(P_LOT, FARE - P_LOT))
    clean = api.get("/api/v2/admin/promo/reconciliation", headers=_h(operator, "operator", key=False))
    assert clean.status_code == 200 and clean.json()["data"] == []
    stranger = pw.ref.client()
    refused = api.get("/api/v2/admin/promo/reconciliation", headers=_h(stranger, "client", key=False))
    assert refused.status_code == 403 and _err(refused) == "FORBIDDEN"

    [(redemption_id, settled_at)] = pw.rows(
        "SELECT r.id, r.settled_at FROM promo_redemptions r JOIN promo_lots l ON l.id = r.lot_id "
        "WHERE r.booking_id = :b AND l.instrument = 'passenger_bonus'", b=booking.id)
    with pw.db.engine.begin() as conn:  # forged behind the triggers: C_net was captured but P no longer "consumed"
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("UPDATE promo_redemptions SET status = 'released', release_fault = 'platform' WHERE id = :r"),
                     {"r": redemption_id})
    try:
        found = api.get("/api/v2/admin/promo/reconciliation", headers=_h(operator, "operator", key=False)).json()["data"]
        mismatch = [i for i in found if i["kind"] == "booking_vs_commission"]
        assert [(i["detail"]["booking_id"], i["detail"]["consumed_passenger_bonus_minor"],
                 i["detail"]["passenger_bonus_minor"]) for i in mismatch] == [(booking.id, 0, P_LOT)]
    finally:
        with pw.db.engine.begin() as conn:
            conn.execute(text("SET LOCAL session_replication_role = replica"))
            conn.execute(text("UPDATE promo_redemptions SET status = 'consumed', release_fault = NULL, settled_at = :t "
                              "WHERE id = :r"), {"r": redemption_id, "t": settled_at})
    assert pw.ref.promo.issues() == []
