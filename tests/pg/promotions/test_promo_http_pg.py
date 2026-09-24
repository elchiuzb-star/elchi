"""The promotions HTTP surface on PostgreSQL (referral stage 5, ADR-0023 §16, §19).

Real FastAPI routers over the real services: authentication from the bearer token only, object ownership, server
capabilities, a real TOTP step-up for staff decisions, two different staff for a large budget change, abuse limits,
the client consent before an offer, the driver's view before accepting, idempotent retries. SYNTHETIC values only.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.contracts.enums import PromoInstrument
from app.contracts.money import TWO_PERSON_APPROVAL_THRESHOLD_MINOR
from app.db.session import get_db
from app.modules.identity import mfa
from tests.pg.bookings.conftest import BW, auth, bw, listing_version  # noqa: F401  (fixtures)
from tests.pg.identity.a1_world import add_user
from tests.pg.promotions.booking_world import BPS, FARE, H_LOT, P_LOT, PW, use_policy
from tests.pg.promotions.referral_world import Ref, enable_promotions, new_phone

pytestmark = pytest.mark.pg

FEATURES = {"X-Elchi-Client-Features": "promo_cash_v1"}


@pytest.fixture
def pw(bw: BW, promo) -> PW:  # noqa: ANN001, F811
    enable_promotions(promo.pg_db)
    use_policy(bw, BPS)
    return PW(bw, Ref(promo))


_WORLD: list[PW] = []


@pytest.fixture
def api(pw: PW) -> Iterator[TestClient]:
    from app.api.v2.web import db_error_handler
    from app.contracts.errors import DomainError as _DomainError
    from app.modules.bookings.api import router as bookings_router
    from app.modules.identity.api import router as identity_router
    from app.modules.identity.web import domain_error_handler
    from app.modules.marketplace.api import router as marketplace_router
    from app.modules.promotions.api import router as promotions_router
    from app.modules.trips.api import router as trips_router
    from sqlalchemy.exc import DBAPIError

    app = FastAPI()
    for router in (identity_router, trips_router, marketplace_router, bookings_router, promotions_router):
        app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(_DomainError, domain_error_handler)
    app.add_exception_handler(DBAPIError, db_error_handler)

    async def server_error(request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "SERVER_ERROR"}})

    app.add_exception_handler(Exception, server_error)

    def override_db() -> Iterator[Session]:
        session = pw.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    _WORLD[:] = [pw]
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    _WORLD.clear()


def _h(user_id: int, role: str, *, key: bool = True, features: bool = True, **extra: str) -> dict[str, str]:
    """A bearer token naming a real live login session (``sid``, Q126), like one the login flow issues."""
    from app.core.security import create_access_token

    claims = {"role": role, **({"sid": _WORLD[0].sid(user_id)} if _WORLD else {})}
    headers = {"Authorization": f"Bearer {create_access_token(str(user_id), extra_claims=claims)}"}
    if key:
        headers["Idempotency-Key"] = uuid.uuid4().hex
    if features:
        headers.update(FEATURES)
    headers.update(extra)
    return headers


def _err(response) -> str:  # noqa: ANN001
    return response.json()["error"]["code"]


# --- staff with a real second factor --------------------------------------------------------------------------------


def _code(session: Session, user_id: int, *, step: int = 0) -> str:
    from app.core.config import settings
    from app.core.secret_box import open_sealed

    row = session.execute(text("SELECT secret_cipher, public_id, secret_key_version FROM staff_mfa_factors "
                               "WHERE user_id = :u ORDER BY id DESC LIMIT 1"), {"u": user_id}).one()
    secret = open_sealed(settings.secret_key, mfa.SECRET_PURPOSE, row[0], aad=str(row[1]), key_version=row[2])
    return pyotp.TOTP(secret, interval=mfa.TOTP_INTERVAL_SECONDS).at(int(time.time()) + step * mfa.TOTP_INTERVAL_SECONDS)


def _staff(pw: PW, role: str) -> int:
    with pw.db.session() as s:
        user_id = add_user(s, new_phone(), role)
        s.commit()
        return user_id


def _with_factor(pw: PW, user_id: int) -> None:
    """Enroll, activated by a *different* super_admin, then step up - the same path the admin panel uses."""
    approver = _staff(pw, "super_admin")
    with pw.db.session() as s:
        mfa.enroll(s, user_id=user_id, account_name="synthetic@elchi")
        s.commit()
    with pw.db.session() as s:
        mfa.activate(s, actor_user_id=approver, subject_user_id=user_id, code=_code(s, user_id))
        s.commit()
    with pw.db.session() as s:
        assert mfa.step_up(s, user_id=user_id, code=_code(s, user_id, step=1)) or \
            mfa.step_up(s, user_id=user_id, code=_code(s, user_id))
        s.commit()


# --- the client consents before sending, the driver sees the terms before accepting (end to end) ----------------------


def _counter_payload(ref, unit: int, consent: tuple[int, int] | None) -> dict:  # noqa: ANN001
    body = {"expected_revision": ref.revision, "unit_price_minor": unit}
    if consent is not None:
        body["promo_consent"] = {"passenger_bonus_minor": consent[0], "cash_due_minor": consent[1]}
    return body


def test_consent_before_counter_driver_sees_terms_then_cash_and_capture(pw: PW, api: TestClient) -> None:
    client = pw.ref.client()
    driver = pw.bw.w.driver_id
    pw.combine(pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT), pw.lot(driver, PromoInstrument.DRIVER_CREDIT, H_LOT))
    trip, ref = pw.offer(client, driver, unit=FARE + 1_000_000)  # the driver asks 210 000

    preview = api.get(f"/api/v2/listings/{ref.listing_id}/promo-preview", params={"unit_price_minor": FARE},
                      headers=_h(client, "client", key=False))
    assert preview.status_code == 200, preview.text
    shown = preview.json()["data"]
    assert shown == {"quote": {"view": "client", "fare_minor": FARE, "passenger_discount_minor": P_LOT,
                               "cash_due_minor": FARE - P_LOT, "currency": "UZS"},  # no commission key at all (Q16)
                     "no_discount_reason": None}

    countered = api.post(f"/api/v2/proposals/{ref.thread_id}/counter", headers=_h(client, "client"),
                         json=_counter_payload(ref, FARE, (P_LOT, FARE - P_LOT)))
    assert countered.status_code == 200, countered.text
    assert pw.scalar("SELECT count(*) FROM promo_consents WHERE status = 'active'") == 1

    seen = api.get(f"/api/v2/proposals/{ref.thread_id}", headers=_h(driver, "driver", key=False)).json()["data"]
    version = seen["current_version"]
    assert version["promo_quote"] == {
        "view": "driver", "fare_minor": FARE, "passenger_discount_minor": P_LOT, "cash_to_collect_minor": FARE - P_LOT,
        "base_commission_minor": 2_000_000, "passenger_discount_covered_minor": P_LOT, "driver_credit_minor": H_LOT,
        "commission_charged_minor": 1_200_000, "driver_keeps_minor": 18_300_000, "currency": "UZS"}

    accepted = api.post(f"/api/v2/proposals/{ref.thread_id}/accept", headers=_h(driver, "driver"),
                        json={"proposal_version_id": version["id"],
                              "expected_listing_version": listing_version(pw.bw, ref.listing_id)})
    assert accepted.status_code == 201, accepted.text
    booking_id = pw.scalar("SELECT id FROM bookings ORDER BY id DESC LIMIT 1")
    assert pw.hold(booking_id)[:2] == (1_200_000, "active")
    client_view = api.get(f"/api/v2/bookings/{accepted.json()['data']['id']}", headers=_h(client, "client", key=False))
    assert client_view.json()["data"]["promo"]["cash_due_minor"] == FARE - P_LOT
    assert "commission" not in client_view.text and "driver_credit" not in client_view.text

    pw.board_and_depart(trip[0], driver, [(booking_id, client)])
    pw.acknowledge_cash(booking_id, client, pw.report_cash(booking_id, driver, FARE - P_LOT))
    pw.finish(trip[0], driver, booking_id, client)
    assert pw.hold(booking_id) == (1_200_000, "captured", 1_200_000)


def test_stale_or_hidden_consent_is_refused_and_nothing_is_sent(pw: PW, api: TestClient) -> None:
    client = pw.ref.client()
    driver = pw.bw.w.driver_id
    pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    pw.declare(driver)
    trip, ref = pw.offer(client, driver, unit=FARE + 1_000_000)
    revision = pw.scalar("SELECT max(revision) FROM proposal_versions")

    wrong = api.post(f"/api/v2/proposals/{ref.thread_id}/counter", headers=_h(client, "client"),
                     json=_counter_payload(ref, FARE, (P_LOT + 1, FARE - P_LOT - 1)))
    assert wrong.status_code == 409 and _err(wrong) == "PROMO_QUOTE_STALE"
    assert pw.scalar("SELECT max(revision) FROM proposal_versions") == revision  # the counter itself was undone
    old_app = api.post(f"/api/v2/proposals/{ref.thread_id}/counter", headers=_h(client, "client", features=False),
                       json=_counter_payload(ref, FARE, (P_LOT, FARE - P_LOT)))
    assert _err(old_app) == "CLIENT_UPGRADE_REQUIRED"
    plain = api.post(f"/api/v2/proposals/{ref.thread_id}/counter", headers=_h(client, "client"),
                     json=_counter_payload(ref, FARE, None))  # no consent field: no bonus, nothing pre-filled
    assert plain.status_code == 200 and pw.scalar("SELECT count(*) FROM promo_consents") == 0


def test_retry_with_the_same_key_returns_the_first_booking(pw: PW, api: TestClient) -> None:
    client = pw.ref.client()
    pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    pw.declare(pw.bw.w.driver_id)
    trip, ref = pw.offer(client, pw.bw.w.driver_id)
    headers = _h(client, "client")
    body = {"proposal_version_id": ref.version_id, "expected_listing_version": listing_version(pw.bw, ref.listing_id),
            "promo_consent": {"passenger_bonus_minor": P_LOT, "cash_due_minor": FARE - P_LOT}}
    first = api.post(f"/api/v2/proposals/{ref.thread_id}/accept", headers=headers, json=body)
    again = api.post(f"/api/v2/proposals/{ref.thread_id}/accept", headers=headers, json=body)  # timeout -> retry
    assert first.status_code == 201 and again.status_code == 201
    assert again.headers.get("Idempotent-Replayed") == "true" and again.json() == first.json()
    assert pw.scalar("SELECT count(*) FROM bookings") == 1
    assert pw.scalar("SELECT count(*) FROM promo_redemptions") == 1
    double = api.post(f"/api/v2/proposals/{ref.thread_id}/accept", headers=_h(client, "client"), json=body)
    assert double.status_code == 409 and pw.scalar("SELECT count(*) FROM bookings") == 1  # a new key is a new attempt


# --- actor, ownership, capabilities ---------------------------------------------------------------------------------


def test_actor_comes_from_the_session_and_foreign_objects_answer_404(pw: PW, api: TestClient) -> None:
    ref = pw.ref
    owner, stranger = ref.client(), ref.client()
    attribution = api.post("/api/v2/referrals/attribution", headers=_h(owner, "client"),
                           json={"code": ref.code(ref.client()), "audience": "client"})
    assert attribution.status_code == 201, attribution.text
    campaign = ref.campaign()
    offer = api.get("/api/v2/referrals/offers", params={"audience": "client"},
                    headers=_h(owner, "client", key=False)).json()["data"]
    assert [o["campaign_id"] for o in offer]
    body = {"attribution_id": attribution.json()["data"]["id"], "campaign_id": offer[0]["campaign_id"],
            "version_no": offer[0]["version_no"], "terms_fingerprint": offer[0]["terms_fingerprint"]}
    foreign = api.post("/api/v2/referrals/enrollments", headers=_h(stranger, "client"), json=body)
    assert foreign.status_code == 404  # someone else's attribution looks unknown
    forged = api.post("/api/v2/referrals/enrollments", headers=_h(stranger, "client"),
                      json={**body, "user_id": owner, "role": "super_admin"})
    assert forged.status_code == 422  # no body field can name a user or a role
    assert pw.scalar("SELECT count(*) FROM promo_enrollments") == 0

    as_client = api.get("/api/v2/admin/promo/campaigns", headers=_h(owner, "super_admin", key=False))
    assert as_client.status_code == 403  # a role claim in a token is not a capability; the server decides
    assert campaign  # the campaign exists; the client just may not see the admin view

    listing = pw.offer(owner, pw.bw.w.driver_id)[1].listing_id
    peek = api.get(f"/api/v2/listings/{listing}/promo-preview", params={"unit_price_minor": FARE},
                   headers=_h(stranger, "client", key=False))
    assert peek.status_code == 404  # another client's request: not a place to probe bonuses


def test_balance_shows_only_my_discount_rights_by_state(pw: PW, api: TestClient) -> None:
    me, other = pw.ref.client(), pw.ref.client()
    pw.lot(me, PromoInstrument.PASSENGER_BONUS, P_LOT)
    pw.lot(other, PromoInstrument.PASSENGER_BONUS, 999_000)
    data = api.get("/api/v2/me/promo-balance", headers=_h(me, "client", key=False)).json()["data"]
    assert data["buckets"] == [{
        "instrument": "passenger_bonus", "service_type": "passenger", "available_minor": P_LOT, "reserved_minor": 0,
        "under_review_minor": 0, "consumed_minor": 0, "expired_minor": 0, "reversed_minor": 0,
        "next_expiry_at": data["buckets"][0]["next_expiry_at"], "currency": "UZS"}]
    assert [lot["amount_minor"] for lot in data["lots"]] == [P_LOT]  # never another user's lot


# --- staff: real MFA step-up and two different people ---------------------------------------------------------------


def test_budget_and_review_decisions_need_a_real_step_up(pw: PW, api: TestClient) -> None:
    finance = _staff(pw, "finance")
    campaign = pw.ref.campaign()
    campaign_public = api.get("/api/v2/admin/promo/campaigns",
                              headers=_h(pw.ref.promo.super_id, "super_admin", key=False)).json()["data"][0]["id"]
    body = {"kind": "allocate", "amount_minor": 1_000, "reason": "synthetic top up"}
    no_factor = api.post(f"/api/v2/admin/promo/campaigns/{campaign_public}/budget-requests",
                         headers=_h(finance, "finance", **{"X-MFA-Verified": "true"}), json=body)
    assert no_factor.status_code == 403, no_factor.text
    assert no_factor.json()["error"]["details"]["reason"] == "step_up_required"  # a header is not a second factor
    _with_factor(pw, finance)
    posted = api.post(f"/api/v2/admin/promo/campaigns/{campaign_public}/budget-requests", headers=_h(finance, "finance"),
                      json=body)
    assert posted.status_code == 201, posted.text
    assert posted.json()["data"]["status"] == "posted"
    assert campaign


def test_a_large_budget_change_needs_a_second_different_person(pw: PW, api: TestClient) -> None:
    first, second = _staff(pw, "finance"), _staff(pw, "finance")
    _with_factor(pw, first)
    _with_factor(pw, second)
    pw.ref.campaign()
    campaign_public = api.get("/api/v2/admin/promo/campaigns",
                              headers=_h(first, "finance", key=False)).json()["data"][0]["id"]
    large = api.post(f"/api/v2/admin/promo/campaigns/{campaign_public}/budget-requests", headers=_h(first, "finance"),
                     json={"kind": "allocate", "amount_minor": TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1,
                           "reason": "synthetic large allocation"})
    assert large.status_code == 201 and large.json()["data"]["status"] == "pending"
    request = large.json()["data"]
    self_approve = api.post(f"/api/v2/admin/promo/budget-requests/{request['id']}/approve",
                            headers=_h(first, "finance"), json={"expected_version": request["version"]})
    assert self_approve.status_code == 409 and _err(self_approve) == "SECOND_APPROVER_REQUIRED"
    approved = api.post(f"/api/v2/admin/promo/budget-requests/{request['id']}/approve",
                        headers=_h(second, "finance"), json={"expected_version": request["version"]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "posted"


# --- abuse limits and the production switch ----------------------------------------------------------------------------


def test_code_check_is_rate_limited_and_says_nothing_about_owners(pw: PW, api: TestClient, monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings

    monkeypatch.setattr(settings, "referral_code_checks_per_ip_per_minute", 3)
    good = pw.ref.code(pw.ref.client())
    answers = [api.get(f"/api/v2/public/referral-codes/{code}").json()["data"] for code in (good, "ZZZZZZZZ")]
    assert answers == [{"valid": True}, {"valid": False}]
    assert api.get(f"/api/v2/public/referral-codes/{good}").status_code == 200
    limited = api.get(f"/api/v2/public/referral-codes/{good}")
    assert limited.status_code == 429 and _err(limited) == "RATE_LIMITED"
    other_source = api.get(f"/api/v2/public/referral-codes/{good}", headers={"X-Forwarded-For": "203.0.113.9"})
    assert other_source.status_code == 200  # one source's limit does not block everyone
    assert pw.scalar("SELECT count(*) FROM promo_rate_events WHERE key_hash LIKE '203.0.113%'") == 0  # hashed


def test_attribution_attempts_are_limited_per_user(pw: PW, api: TestClient, monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings

    monkeypatch.setattr(settings, "referral_attributions_per_user_per_hour", 2)
    user = pw.ref.client()
    codes = ["ZZZZZZZZ", "YYYYYYYY", "XXXXXXXX"]
    status = [api.post("/api/v2/referrals/attribution", headers=_h(user, "client"),
                       json={"code": code, "audience": "client"}).status_code for code in codes]
    assert status == [404, 404, 429]


def test_with_promotions_off_no_new_promo_obligation_can_be_made(pw: PW, api: TestClient) -> None:
    from tests.pg.bookings.conftest import _mark_flag_change_source

    user = pw.ref.client()
    code = pw.ref.code(pw.ref.client())
    with pw.db.engine.begin() as conn:
        _mark_flag_change_source(conn)
        conn.execute(text("UPDATE feature_flag_values SET enabled = false, version = version + 1 "
                          "WHERE flag_key = 'promotions_enabled'"))
    for response in (
        api.post("/api/v2/referrals/attribution", headers=_h(user, "client"), json={"code": code, "audience": "client"}),
        api.post("/api/v2/me/referral-code", headers=_h(user, "client")),
        api.get(f"/api/v2/public/referral-codes/{code}"),
    ):
        assert response.status_code == 403 and _err(response) == "FEATURE_DISABLED"
    assert pw.scalar("SELECT count(*) FROM referral_attributions") == 0
    assert pw.scalar("SELECT count(*) FROM promo_enrollments") == 0
    assert pw.scalar("SELECT count(*) FROM promo_obligations WHERE enrollment_id IS NOT NULL") == 0


def test_referral_code_endpoint_is_idempotent_and_link_is_not_claimed_ready(pw: PW, api: TestClient) -> None:
    user = pw.ref.client()
    headers = _h(user, "client")
    first = api.post("/api/v2/me/referral-code", headers=headers).json()["data"]
    again = api.post("/api/v2/me/referral-code", headers=_h(user, "client")).json()["data"]
    assert first["code"] == again["code"] and first["link_status"] == "not_configured" and first["share_url"] is None



def test_operator_notes_a_review_and_only_an_admin_with_a_factor_decides(pw: PW, api: TestClient) -> None:
    from app.contracts.timeutil import utc_now
    from app.modules.promotions import qualification

    operator, admin = _staff(pw, "operator"), _staff(pw, "admin")
    campaign = pw.ref.campaign()
    with pw.db.session() as s:
        qualification.open_review(s, kind="qualification_risk", dedup_key=f"http:{uuid.uuid4().hex}",
                                  reasons=["synthetic"], evidence=[{"table": "promo_campaigns", "id": campaign}],
                                  now=utc_now(), campaign_id=campaign)
        s.commit()
    [review] = api.get("/api/v2/admin/promo/reviews", headers=_h(operator, "operator", key=False)).json()["data"]
    started = api.post(f"/api/v2/admin/promo/reviews/{review['id']}/start", headers=_h(operator, "operator"),
                       json={"note": "looked at the trips"})
    assert started.status_code == 200 and started.json()["data"]["assigned_to_me"] is True
    version = started.json()["data"]["version"]
    decision = {"decision": "approve", "note": "fine", "expected_version": version}
    by_operator = api.post(f"/api/v2/admin/promo/reviews/{review['id']}/decide", headers=_h(operator, "operator"),
                           json=decision)
    assert by_operator.status_code == 403  # operator: note only (Q78 pattern)
    no_factor = api.post(f"/api/v2/admin/promo/reviews/{review['id']}/decide", headers=_h(admin, "admin"),
                         json=decision)
    assert no_factor.status_code == 403 and no_factor.json()["error"]["details"]["reason"] == "step_up_required"
    _with_factor(pw, admin)
    lots_before = pw.scalar("SELECT count(*) FROM promo_lots")
    decided = api.post(f"/api/v2/admin/promo/reviews/{review['id']}/decide", headers=_h(admin, "admin"), json=decision)
    assert decided.status_code == 200, decided.text
    assert decided.json()["data"]["status"] == "approved"
    assert pw.scalar("SELECT count(*) FROM promo_lots") == lots_before  # an approval creates no reward (Q122)


def test_enrollment_over_http_then_a_real_service_qualifies(pw: PW, api: TestClient, monkeypatch) -> None:  # noqa: ANN001
    """Enrollment needs the identity key (Q108/Q118, no fallback): the test configures a synthetic long secret."""
    from datetime import timedelta

    from app.core.config import settings
    from app.modules.promotions import qualification
    from tests.pg.promotions.lifecycle import completed_passenger
    from tests.pg.promotions.referral_world import SYNTH_SECRET

    monkeypatch.setattr(settings, "secret_key", SYNTH_SECRET)

    referee = pw.ref.client()
    campaign = pw.ref.campaign()
    attributed = api.post("/api/v2/referrals/attribution", headers=_h(referee, "client"),
                          json={"code": pw.ref.code(pw.ref.client()), "audience": "client"})
    assert attributed.status_code == 201, attributed.text
    [offer] = api.get("/api/v2/referrals/offers", params={"audience": "client"},
                      headers=_h(referee, "client", key=False)).json()["data"]
    codes = {item["code"] for item in offer["disclosures"]}
    assert {"not_cash", "referrer_service_excluded", "qualification_deadline", "required_services", "risk_check"} <= codes
    enrolled = api.post("/api/v2/referrals/enrollments", headers=_h(referee, "client"), json={
        "attribution_id": attributed.json()["data"]["id"], "campaign_id": offer["campaign_id"],
        "version_no": offer["version_no"], "terms_fingerprint": offer["terms_fingerprint"]})
    assert enrolled.status_code == 201, enrolled.text
    booking = completed_passenger(pw.bw, referee)
    progress = api.get("/api/v2/me/referrals", headers=_h(referee, "client", key=False)).json()["data"]
    # stage 5 milestone view: the finished trip is still inside its 48 h check - shown as "being checked", never done
    assert progress["enrollments"][0]["progress"] == {"unit": "service", "required": 1, "done": 0, "in_review": 1,
                                                      "remaining": 0, "milestones": []}
    with pw.db.session() as s:
        evidence = qualification.read_evidence(s, booking)
    enrollment = pw.scalar("SELECT id FROM promo_enrollments WHERE referee_user_id = :u", u=referee)
    with pw.db.session() as s:
        assert qualification.process_enrollment(
            s, enrollment_id=enrollment, now=evidence.conditions_met_at + timedelta(hours=48)) == "granted"
        s.commit()
    mine = api.get("/api/v2/me/referrals", headers=_h(referee, "client", key=False)).json()["data"]
    assert mine["enrollments"][0]["status"] == "granted" and mine["enrollments"][0]["side"] == "referee"
    balance = api.get("/api/v2/me/promo-balance", headers=_h(referee, "client", key=False)).json()["data"]
    assert balance["buckets"][0]["available_minor"] > 0
    assert campaign


# --- T4 over HTTP (Q123, Q126, Q129, stage-5 "why no discount") ------------------------------------------------------


def test_q126_a_stale_client_confirmation_is_renewed_over_http_without_a_new_offer(pw: PW, api: TestClient) -> None:
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    trip, ref = pw.offer(client, driver, unit=FARE + 1_000_000)
    countered = api.post(f"/api/v2/proposals/{ref.thread_id}/counter", headers=_h(client, "client"),
                         json=_counter_payload(ref, FARE, (P_LOT, FARE - P_LOT)))
    assert countered.status_code == 200, countered.text
    version = countered.json()["data"]["current_version"]
    assert version["promo_confirmation"] == "valid"  # the author sees its own confirmation holds
    pw.end_session(client)  # the client logged out on that phone
    accept = {"proposal_version_id": version["id"], "expected_listing_version": listing_version(pw.bw, ref.listing_id)}
    refused = api.post(f"/api/v2/proposals/{ref.thread_id}/accept", headers=_h(driver, "driver"), json=accept)
    assert refused.status_code == 409 and refused.json()["error"]["details"]["reasons"] == [
        "counterparty_confirmation_stale"]
    pw._sids.pop(client)  # the client logs in again
    shown = api.get(f"/api/v2/proposals/{ref.thread_id}", headers=_h(client, "client", key=False)).json()["data"]
    assert shown["current_version"]["promo_confirmation"] == "stale"
    renewed = api.post(f"/api/v2/proposals/{ref.thread_id}/promo-confirmation", headers=_h(client, "client"),
                       json={"proposal_version_id": version["id"],
                             "promo_consent": {"passenger_bonus_minor": P_LOT, "cash_due_minor": FARE - P_LOT}})
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["data"]["current_version"]["id"] == version["id"]  # the offer itself did not change
    accepted = api.post(f"/api/v2/proposals/{ref.thread_id}/accept", headers=_h(driver, "driver"), json=accept)
    assert accepted.status_code == 201, accepted.text


def test_stage5_the_preview_says_why_there_is_no_discount_in_plain_words(pw: PW, api: TestClient) -> None:
    client = pw.ref.client()
    _, ref = pw.offer(client, pw.bw.w.driver_id)
    none = api.get(f"/api/v2/listings/{ref.listing_id}/promo-preview", params={"unit_price_minor": FARE},
                   headers=_h(client, "client", key=False)).json()["data"]
    assert none == {"quote": None, "no_discount_reason": "no_campaign"}
    old_app = api.get(f"/api/v2/listings/{ref.listing_id}/promo-preview", params={"unit_price_minor": FARE},
                      headers=_h(client, "client", key=False, features=False)).json()["data"]
    assert old_app["no_discount_reason"] == "client_update_required"
    lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, P_LOT)
    with pw.db.engine.begin() as conn:
        conn.execute(text("UPDATE promo_lots SET expires_at = now() - interval '1 minute' WHERE id = :l"), {"l": lot})
    expired = api.get(f"/api/v2/listings/{ref.listing_id}/promo-preview", params={"unit_price_minor": FARE},
                      headers=_h(client, "client", key=False)).json()["data"]
    assert expired == {"quote": None, "no_discount_reason": "bonus_expired"}  # a category, never a rate or a rule


def test_q123_a_campaign_pairing_is_approved_only_with_a_real_step_up(pw: PW, api: TestClient) -> None:
    from app.contracts.enums import PromoCampaignKind

    pw.ref.campaign()
    pw.ref.campaign(kind=PromoCampaignKind.REFERRAL_DRIVER_CLIENT)
    boss = _staff(pw, "super_admin")
    listed = api.get("/api/v2/admin/promo/campaigns", headers=_h(boss, "super_admin", key=False)).json()["data"]
    a, b = listed[0]["id"], listed[1]["id"]
    body = {"other_campaign_id": b, "cost_basis": "additive", "reason": "synthetic pairing"}
    no_factor = api.post(f"/api/v2/admin/promo/campaigns/{a}/combinations", headers=_h(boss, "super_admin"), json=body)
    assert no_factor.status_code == 403 and no_factor.json()["error"]["details"]["reason"] == "step_up_required"
    no_basis = api.post(f"/api/v2/admin/promo/campaigns/{a}/combinations", headers=_h(boss, "super_admin"),
                        json={"other_campaign_id": b, "reason": "x"})
    assert no_basis.status_code == 422  # the cost basis is chosen explicitly - there is no default
    _with_factor(pw, boss)
    made = api.post(f"/api/v2/admin/promo/campaigns/{a}/combinations", headers=_h(boss, "super_admin"), json=body)
    assert made.status_code == 201, made.text
    [pairing] = made.json()["data"]["combinations"]
    assert (sorted(pairing["campaign_ids"]), pairing["cost_basis"], pairing["status"]) == (
        sorted([a, b]), "additive", "active")
    revoked = api.post(f"/api/v2/admin/promo/combinations/{pairing['id']}/revoke", headers=_h(boss, "super_admin"),
                       json={"expected_version": pairing["version"], "reason": "synthetic stop"})
    assert revoked.status_code == 200 and revoked.json()["data"]["status"] == "revoked"
