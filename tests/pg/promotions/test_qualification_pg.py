"""Qualification, grant, review queue, expiry/reinstate and jobs on PostgreSQL (referral stage 3, ADR-0023).

Evidence comes from real booking lifecycles (``lifecycle.py``: real accept/hold, proofs, cash receipts, finance
capture). The promotions hook inside the booking flow is stage 4: here the tests call the qualification functions and
jobs directly. SYNTHETIC people, amounts and campaign parameters only.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts.enums import PromoCampaignKind
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.promo import QUALIFICATION_RISK_WINDOW
from app.contracts.timeutil import utc_now
from app.modules.promotions import qualification, referral, service
from tests.pg.bookings.conftest import BW, bw  # noqa: F401  (fixture)
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import add_user
from tests.pg.promotions.conftest import ADMIN_CAPS, COMMITMENT, FINANCE_CAPS, OPERATOR_CAPS, REFEREE_REWARD, SUPER_CAPS
from tests.pg.promotions.lifecycle import (
    accepted_passenger,
    complete_passengers,
    completed_parcels_on_one_trip,
    completed_passenger,
    new_receiver,
    passenger_trip,
)
from tests.pg.promotions.referral_world import KEYS, Ref, enable_promotions
from tests.pg.ops.test_db_roles import roles  # noqa: F401  (fixture)

pytestmark = pytest.mark.pg


@pytest.fixture
def q(bw: BW, promo):  # noqa: ANN001, ANN201, F811
    enable_promotions(promo.pg_db)
    return bw, Ref(promo)


def _enrolled(ref: Ref, campaign: int, *, referrer: int | None = None, audience: str = "client") -> tuple[int, int]:
    referee = ref.client() if audience == "client" else ref.driver()
    referrer = referrer if referrer is not None else ref.client()
    attribution = ref.attribute(referee, ref.code(referrer), audience=audience)
    return referee, ref.enroll(referee, attribution, campaign)


def _process(ref: Ref, enrollment: int, now) -> str:  # noqa: ANN001
    with ref.pg_db.session() as s:
        result = qualification.process_enrollment(s, enrollment_id=enrollment, now=now)
        s.commit()
        return result


def _ready_at(ref: Ref, booking_id: int):  # noqa: ANN201
    with ref.pg_db.session() as s:
        evidence = qualification.read_evidence(s, booking_id)
    assert evidence is not None and evidence.conditions_met_at is not None
    return evidence.conditions_met_at + QUALIFICATION_RISK_WINDOW


def _lots(ref: Ref, enrollment: int) -> list[dict]:
    with ref.pg_db.engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "SELECT l.* FROM promo_lots l JOIN promo_obligations o ON o.id = l.obligation_id WHERE o.enrollment_id = :e "
            "ORDER BY l.id"), {"e": enrollment}).mappings()]


def _scalar(ref: Ref, sql: str, **params):  # noqa: ANN003, ANN201
    with ref.pg_db.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


# --- evidence and the 48 h window ----------------------------------------------------------------------------------


def test_evidence_is_read_from_the_source_records(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, _ = _enrolled(ref, campaign)
    booking = completed_passenger(bw, referee)
    with ref.pg_db.session() as s:
        evidence = qualification.read_evidence(s, booking)
    assert evidence.completed_at is not None and evidence.cash_confirmed_at is not None
    assert evidence.captured_at is not None and evidence.net_captured_minor > 0  # the capture of *this* booking
    capture_booking = _scalar(ref, "SELECT t.booking_id FROM wallet_holds h JOIN ledger_transactions t "
                                   "ON t.id = h.capture_transaction_id WHERE h.booking_id = :b", b=booking)
    assert capture_booking == booking
    # an event payload claiming "captured" is not evidence: without a real capture nothing is granted - Q120: the
    # service and cash were in time, so the enrollment waits for the platform's capture instead of being dropped
    uncaptured_referee, uncaptured = _enrolled(ref, campaign)
    trip = passenger_trip(bw, bw.w.driver_id)
    b2 = accepted_passenger(bw, uncaptured_referee, trip, bw.w.driver_id)
    complete_passengers(bw, trip[0], bw.w.driver_id, [(b2, uncaptured_referee)], capture=False)
    with ref.pg_db.session() as s:
        assert qualification.record_booking_event(s, booking_id=b2, kind="commission_captured", occurred_at=utc_now())
        s.commit()
    assert _process(ref, uncaptured, utc_now() + timedelta(days=5)) == "waiting"
    assert _lots(ref, uncaptured) == []


def test_48_hours_before_at_and_after_the_boundary(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    booking = completed_passenger(bw, referee)
    ready = _ready_at(ref, booking)
    assert _process(ref, enrollment, ready - timedelta(seconds=1)) == "waiting"
    assert _lots(ref, enrollment) == []
    assert _scalar(ref, "SELECT status FROM promo_qualifications WHERE enrollment_id = :e", e=enrollment) == "waiting"
    assert _process(ref, enrollment, ready) == "granted"  # at exactly 48 h the window has passed
    lots = _lots(ref, enrollment)
    assert len(lots) == 2 and all(l["status"] == "available" for l in lots)
    assert all(l["available_from"] == ready and l["expires_at"] == ready + timedelta(days=60) for l in lots)
    assert _process(ref, enrollment, ready + timedelta(hours=1)) == "settled"
    assert len(_lots(ref, enrollment)) == 2
    position = ref.promo.budget(campaign)
    assert (position.promised_minor, position.granted_minor) == (0, COMMITMENT)  # the reserve became the bonus
    assert _scalar(ref, "SELECT status FROM promo_enrollments WHERE id = :e", e=enrollment) == "granted"
    assert _scalar(ref, "SELECT count(*) FROM outbox_events WHERE event_type = 'promo.reward_granted'") == 2
    assert ref.promo.issues(campaign) == []


def test_service_in_time_counts_even_if_the_worker_was_late(q) -> None:  # noqa: ANN001
    """Deadline passed, worker ran weeks later: the service met every condition in time, so it still qualifies."""
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    completed_passenger(bw, referee)
    much_later = utc_now() + timedelta(days=45)  # the 30-day qualification window is long over
    with ref.pg_db.session() as s:
        assert qualification.expire_enrollments(s, now=much_later) == 0  # expiry processes first: nothing released
        s.commit()
    assert len(_lots(ref, enrollment)) == 2
    assert _scalar(ref, "SELECT status FROM promo_enrollments WHERE id = :e", e=enrollment) == "granted"


def test_expiry_releases_only_what_can_no_longer_be_earned(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    _, idle = _enrolled(ref, campaign)
    referee, reviewing = _enrolled(ref, campaign)
    completed_passenger(bw, referee)
    with ref.pg_db.engine.begin() as conn:  # the *reviewing* enrollment's referrer is blocked -> a person decides
        conn.execute(text("UPDATE users SET status = 'blocked' WHERE id = (SELECT referrer_user_id FROM promo_enrollments "
                          "WHERE id = :e)"), {"e": reviewing})
    later = utc_now() + timedelta(days=45)
    with ref.pg_db.session() as s:
        assert qualification.expire_enrollments(s, now=later) == 1
        s.commit()
    assert _scalar(ref, "SELECT status FROM promo_enrollments WHERE id = :e", e=idle) == "released"
    assert _scalar(ref, "SELECT a.status FROM referral_attributions a JOIN promo_enrollments e ON e.attribution_id = a.id "
                        "WHERE e.id = :e", e=idle) == "expired"
    assert _scalar(ref, "SELECT status FROM promo_enrollments WHERE id = :e", e=reviewing) == "promised"
    assert _scalar(ref, "SELECT count(*) FROM promo_reviews WHERE enrollment_id = :e AND kind = 'party_not_active'",
                   e=reviewing) == 1
    assert ref.promo.issues(campaign) == []


# --- concurrency and crash safety ----------------------------------------------------------------------------------


def test_parallel_processing_grants_one_reward(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    ready = _ready_at(ref, completed_passenger(bw, referee))

    def work(index: int, session) -> str:  # noqa: ANN001
        result = qualification.process_enrollment(session, enrollment_id=enrollment, now=ready)
        session.commit()
        return result

    report = run_concurrently(6, work, engine=ref.pg_db.engine)
    assert not report.failures, [r.error for r in report.failures]
    assert len(_lots(ref, enrollment)) == 2
    assert _scalar(ref, "SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'grant' AND campaign_id = :c", c=campaign) == 2
    assert _scalar(ref, "SELECT count(*) FROM outbox_events WHERE event_type = 'promo.reward_granted'") == 2


def test_worker_crash_before_commit_and_lost_ack_after_commit(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    booking = completed_passenger(bw, referee)
    ready = _ready_at(ref, booking)
    # stage 4: the booking flow itself recorded its events inside its own transactions (completion, cash, capture)
    flow_events = _scalar(ref, f"SELECT count(*) FROM promo_qualification_events WHERE booking_id = {booking}")
    assert flow_events >= 3
    with ref.pg_db.session() as s:
        qualification.record_booking_event(s, booking_id=booking, kind="booking_completed", occurred_at=utc_now())
        s.commit()
    with ref.pg_db.session() as s:  # the worker claims and processes ... and dies before COMMIT
        assert qualification.process_qualification_events(s, now=ready) >= 1
        s.rollback()
    assert _lots(ref, enrollment) == []
    assert _scalar(ref, "SELECT count(*) FROM promo_qualification_events WHERE processed_at IS NULL") == flow_events + 1
    for _ in range(2):  # the rerun commits; a second run (acknowledgement lost) must create nothing new
        with ref.pg_db.session() as s:
            qualification.process_qualification_events(s, now=ready)
            s.commit()
    assert len(_lots(ref, enrollment)) == 2
    assert _scalar(ref, "SELECT count(*) FROM promo_qualification_events WHERE processed_at IS NULL") == 0
    with ref.pg_db.session() as s:  # a redelivered event is a no-op
        assert not qualification.record_booking_event(s, booking_id=booking, kind="booking_completed", occurred_at=_scalar(
            ref, "SELECT max(occurred_at) FROM promo_qualification_events WHERE kind = 'booking_completed'"))
        s.commit()


def test_grant_racing_a_dispute_is_consistent(q) -> None:  # noqa: ANN001
    """Either the dispute is seen and nothing is granted, or the grant wins and the recheck opens a review."""
    from tests.pg.trust_support.conftest import open_dispute

    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    booking = completed_passenger(bw, referee)
    ready = _ready_at(ref, booking)

    def work(index: int, session) -> str:  # noqa: ANN001
        if index == 0:
            result = qualification.process_enrollment(session, enrollment_id=enrollment, now=ready)
            session.commit()
            return result
        session.close()
        open_dispute(bw, booking, referee, "service")
        return "dispute"

    report = run_concurrently(2, work, engine=ref.pg_db.engine)
    assert not report.failures, [r.error for r in report.failures]
    lots = _lots(ref, enrollment)
    with ref.pg_db.session() as s:
        qualification.recheck_granted(s, now=ready)
        s.commit()
    reviews = _scalar(ref, "SELECT count(*) FROM promo_reviews WHERE enrollment_id = :e AND kind = 'post_grant_recheck'", e=enrollment)
    assert (len(lots), reviews) in {(0, 0), (2, 1)}
    assert all(l["status"] == "available" for l in lots)  # nothing reversed automatically


def test_refund_after_grant_opens_a_review_and_reversal_is_no_debt(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    booking = completed_passenger(bw, referee)
    _process(ref, enrollment, _ready_at(ref, booking))
    from app.modules.wallet import service as wallet_service

    with ref.pg_db.session() as s:  # a real (small, single-approver) commission reversal by finance
        wallet_service.reverse_fee(s, booking_id=booking, amount_minor=100, actor_user_id=ref.promo.finance_id,
                                   actor_capabilities=FINANCE_CAPS, reason="refund after grant")
        s.commit()
    with ref.pg_db.session() as s:
        assert qualification.recheck_granted(s, now=utc_now()) == 1
        assert qualification.recheck_granted(s, now=utc_now()) == 0  # no duplicate review
        s.commit()
    review_id, version = ref.pg_db.engine.connect().execute(text(
        "SELECT id, version FROM promo_reviews WHERE kind = 'post_grant_recheck' AND enrollment_id = :e"), {"e": enrollment}).one()
    with ref.pg_db.engine.connect() as conn:
        balance_before = conn.execute(text("SELECT sum(posted_balance_minor) FROM wallet_accounts")).scalar()
    with ref.pg_db.session() as s:
        qualification.decide_review(s, review_id=review_id, decision="reject", actor_user_id=ref.promo.admin_id,
                                    actor_capabilities=ADMIN_CAPS, note="refund confirmed", expected_version=version)
        s.commit()
    assert {l["status"] for l in _lots(ref, enrollment)} == {"reversed"}
    with ref.pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT sum(posted_balance_minor) FROM wallet_accounts")).scalar() == balance_before
    assert ref.promo.issues(campaign) == []


# --- reviews ----------------------------------------------------------------------------------------------------------


def test_identity_review_survives_the_rollback_and_is_not_duplicated(q) -> None:  # noqa: ANN001
    from app.contracts.promo import IdentityRetentionPolicy
    from app.modules.promotions import identity as identity_service

    bw, ref = q
    campaign = ref.campaign()
    old = ref.client()
    ref.enroll(old, ref.attribute(old, ref.code(ref.client())), campaign)
    with ref.pg_db.session() as s:
        phone = s.execute(text("SELECT phone FROM users WHERE id = :u"), {"u": old}).scalar_one()
        identity_service.on_account_deleted(s, user_id=old, policy=IdentityRetentionPolicy(timedelta(days=30)))
        s.execute(text("UPDATE users SET phone = :p, status = 'deleted' WHERE id = :u"), {"p": f"deleted:{old}", "u": old})
        s.commit()
    with ref.pg_db.session() as s:  # the old account's unused promise has run out by now
        qualification.expire_enrollments(s, now=utc_now() + timedelta(days=31))
        newcomer = add_user(s, phone, "client")
        s.commit()
    attribution = ref.attribute(newcomer, ref.code(ref.client()))
    offer = ref.offer(campaign)
    for attempt in range(3):  # each command is refused and its transaction rolled back
        with ref.pg_db.session() as s:
            with pytest.raises(DomainError) as exc:
                referral.enroll(s, referee_user_id=newcomer, attribution_id=attribution, campaign_id=campaign,
                                accepted_campaign_version_id=offer.campaign_version_id,
                                accepted_terms_fingerprint=offer.terms_fingerprint, idempotency_key=f"k{attempt}", keys=KEYS)
            assert exc.value.details["reason"] == "identity_needs_review"
            s.rollback()
    reviews = ref.pg_db.engine.connect().execute(text(
        "SELECT id, version, status, reason_codes, evidence, risk_ruleset_version, due_at FROM promo_reviews "
        "WHERE attribution_id = :a"), {"a": attribution}).mappings().all()
    assert len(reviews) == 1 and reviews[0]["status"] == "open"
    assert reviews[0]["reason_codes"] == ["identity_key_match"] and reviews[0]["risk_ruleset_version"]
    assert all(set(item) == {"table", "id"} for item in reviews[0]["evidence"])  # references only, no personal data
    assert reviews[0]["due_at"] is not None
    with ref.pg_db.session() as s:
        with pytest.raises(DomainError) as exc:  # an operator may work the review, not decide it
            qualification.decide_review(s, review_id=reviews[0]["id"], decision="approve", actor_user_id=ref.promo.operator_id,
                                        actor_capabilities=OPERATOR_CAPS, note="x", expected_version=reviews[0]["version"])
        assert exc.value.code is ErrorCode.FORBIDDEN
    with ref.pg_db.session() as s:
        qualification.start_review(s, review_id=reviews[0]["id"], actor_user_id=ref.promo.operator_id,
                                   actor_capabilities=OPERATOR_CAPS, note="looking")
        s.commit()
    with ref.pg_db.session() as s:
        qualification.decide_review(s, review_id=reviews[0]["id"], decision="approve", actor_user_id=ref.promo.admin_id,
                                    actor_capabilities=ADMIN_CAPS, note="new owner of a recycled number",
                                    expected_version=reviews[0]["version"] + 1)
        s.commit()
    assert ref.count("promo_obligations", "beneficiary_user_id = :u", u=newcomer) == 0  # approval promised nothing
    ref.enroll(newcomer, attribution, campaign)  # a fresh attempt runs every check again and succeeds
    assert ref.count("promo_obligations", "beneficiary_user_id = :u", u=newcomer) == 1


def test_review_decision_racing_expiry_never_loses_the_right(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    ready = _ready_at(ref, completed_passenger(bw, referee))
    with ref.pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'blocked' WHERE id = (SELECT referrer_user_id FROM promo_enrollments "
                          "WHERE id = :e)"), {"e": enrollment})
    assert _process(ref, enrollment, ready) == "review"
    review_id, version = ref.pg_db.engine.connect().execute(text(
        "SELECT id, version FROM promo_reviews WHERE enrollment_id = :e"), {"e": enrollment}).one()
    later = utc_now() + timedelta(days=45)

    def work(index: int, session) -> str:  # noqa: ANN001
        if index == 0:
            qualification.decide_review(session, review_id=review_id, decision="approve", actor_user_id=ref.promo.admin_id,
                                        actor_capabilities=ADMIN_CAPS, note="checked", expected_version=version)
        else:
            qualification.expire_enrollments(session, now=later)
        session.commit()
        return "ok"

    report = run_concurrently(2, work, engine=ref.pg_db.engine)
    assert not report.failures, [r.error for r in report.failures]
    # the referrer is still blocked: the approval cleared the review but the live check still stops the grant,
    # and nothing that was earned in time is released while that is being decided
    assert _scalar(ref, "SELECT status FROM promo_enrollments WHERE id = :e", e=enrollment) == "promised"
    assert _lots(ref, enrollment) == []
    assert ref.promo.budget(campaign).promised_minor == COMMITMENT


def test_overdue_review_escalates_and_nothing_else_happens(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    ready = _ready_at(ref, completed_passenger(bw, referee))
    with ref.pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'blocked' WHERE id = (SELECT referrer_user_id FROM promo_enrollments "
                          "WHERE id = :e)"), {"e": enrollment})
    _process(ref, enrollment, ready)
    due = _scalar(ref, "SELECT due_at FROM promo_reviews WHERE enrollment_id = :e", e=enrollment)
    with ref.pg_db.session() as s:
        assert qualification.escalate_overdue_reviews(s, now=due - timedelta(seconds=1)) == 0
        assert qualification.escalate_overdue_reviews(s, now=due) == 1
        assert qualification.escalate_overdue_reviews(s, now=due + timedelta(days=1)) == 0
        s.commit()
    assert _scalar(ref, "SELECT status FROM promo_reviews WHERE enrollment_id = :e", e=enrollment) == "open"
    assert _scalar(ref, "SELECT escalated_at IS NOT NULL FROM promo_reviews WHERE enrollment_id = :e", e=enrollment)
    assert _lots(ref, enrollment) == [] and ref.promo.budget(campaign).promised_minor == COMMITMENT


def test_referrer_served_booking_does_not_close_the_enrollment(q) -> None:  # noqa: ANN001
    """Driver -> client: the inviting driver's own trip does not qualify; a later trip with another driver does."""
    bw, ref = q
    campaign = ref.campaign(kind=PromoCampaignKind.REFERRAL_DRIVER_CLIENT)
    referee, enrollment = _enrolled(ref, campaign, referrer=bw.w.driver_id)
    own = completed_passenger(bw, referee, driver_id=bw.w.driver_id)
    assert _process(ref, enrollment, _ready_at(ref, own)) == "pending"
    other = completed_passenger(bw, referee, driver_id=bw.w.driver2_id)
    assert _process(ref, enrollment, _ready_at(ref, other)) == "granted"


# --- parcels and driver milestones ------------------------------------------------------------------------------------


def test_staff_completed_parcels_never_qualify_by_themselves(q) -> None:  # noqa: ANN001
    """ADR-0026 (Q139, open decision D-1): a parcel has no handover/delivery proof and no in-app cash confirmation any
    more. Staff completion plus a real capture is *not* treated as the referee's qualifying evidence - nothing is
    granted automatically; the promise stays reserved until the enrollment's own deadline (no silent release)."""
    bw, ref = q
    campaign = ref.parcel_campaign()
    referee, enrollment = _enrolled(ref, campaign)
    bookings = completed_parcels_on_one_trip(bw, referee, [new_receiver(), new_receiver()])
    assert _scalar(ref, "SELECT count(*) FROM bookings WHERE id = ANY(:b) AND service_status = 'completed' "
                        "AND commission_status = 'captured'", b=bookings) == 2
    assert _process(ref, enrollment, utc_now() + timedelta(days=3)) != "granted"
    assert _lots(ref, enrollment) == []
    assert _scalar(ref, "SELECT count(*) FROM promo_qualifications WHERE enrollment_id = :e", e=enrollment) == 0
    assert ref.promo.budget(campaign).promised_minor == COMMITMENT


def _retired_reviews(ref: Ref, enrollment: int) -> list[int]:
    return [r[0] for r in ref.pg_db.engine.connect().execute(text(
        "SELECT id FROM promo_reviews WHERE kind = 'qualification_path_retired' AND enrollment_id = :e"), {"e": enrollment})]


def _enrollment_status(ref: Ref, enrollment: int) -> str:
    return _scalar(ref, "SELECT status FROM promo_enrollments WHERE id = :e", e=enrollment)


def test_a_promised_parcel_enrollment_waits_for_a_person_not_for_the_deadline(q) -> None:  # noqa: ANN001
    """Q147 (ADR-0026): the parcel proofs Q113 asks for were removed by the platform. Such a promise is neither granted
    without evidence nor released by the deadline, and the retired path is never a ground to reject it (D-4 open)."""
    bw, ref = q
    campaign = ref.parcel_campaign()
    _, rejected_one = _enrolled(ref, campaign)
    _, approved_one = _enrolled(ref, campaign)
    promised = ref.promo.budget(campaign).promised_minor
    with ref.pg_db.session() as s:
        assert qualification.review_retired_parcel_enrollments(s, now=utc_now()) == 2
        s.commit()
    with ref.pg_db.session() as s:
        assert qualification.review_retired_parcel_enrollments(s, now=utc_now()) == 0  # idempotent
        s.commit()
    assert len(_retired_reviews(ref, rejected_one)) == len(_retired_reviews(ref, approved_one)) == 1

    after_deadline = _scalar(ref, "SELECT max(qualification_deadline) FROM promo_enrollments") + timedelta(days=1)
    with ref.pg_db.session() as s:
        qualification.expire_enrollments(s, now=after_deadline)
        s.commit()
    assert _enrollment_status(ref, rejected_one) == _enrollment_status(ref, approved_one) == "promised"
    assert ref.promo.budget(campaign).promised_minor == promised  # the obligation is kept
    assert _lots(ref, rejected_one) == [] and _lots(ref, approved_one) == []  # and nothing is granted without evidence
    assert len(_retired_reviews(ref, rejected_one)) == 1  # the deadline pass opened no second review

    # the platform removing the proof is not the participant's breach: "reject" is refused and nothing is released
    refused = None
    with ref.pg_db.session() as s:
        try:
            qualification.decide_review(s, review_id=_retired_reviews(ref, rejected_one)[0], decision="reject",
                                        actor_user_id=ref.promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                        note="synthetic: trying to reject for the retired path", expected_version=1)
        except DomainError as exc:
            refused = exc
            s.rollback()
    assert refused is not None and refused.code is ErrorCode.INVALID_STATE_TRANSITION
    assert refused.details["reason"] == "retired_path_is_not_a_violation"
    assert _enrollment_status(ref, rejected_one) == "promised"
    # approval records that the promise is to be honoured; it grants nothing (D-4 open) and keeps the reserve
    with ref.pg_db.session() as s:
        qualification.decide_review(s, review_id=_retired_reviews(ref, approved_one)[0], decision="approve",
                                    actor_user_id=ref.promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                    note="synthetic: honour when D-4 is decided", expected_version=1)
        s.commit()
    assert _enrollment_status(ref, approved_one) == "promised" and _lots(ref, approved_one) == []
    with ref.pg_db.session() as s:
        qualification.expire_enrollments(s, now=after_deadline + timedelta(days=1))
        s.commit()
    assert _enrollment_status(ref, approved_one) == _enrollment_status(ref, rejected_one) == "promised"
    assert ref.promo.budget(campaign).promised_minor == promised  # every reserve kept


def test_driver_milestone_counts_distinct_trips(q) -> None:  # noqa: ANN001
    from tests.pg.bookings.conftest import fund

    bw, ref = q
    campaign = ref.campaign(kind=PromoCampaignKind.REFERRAL_DRIVER_DRIVER, milestone_thresholds=(1, 2),
                            min_distinct_clients=1)  # synthetic steps
    referee, enrollment = _enrolled(ref, campaign, referrer=bw.w.driver2_id, audience="driver")
    fund(bw, referee, 100_000_000, bw.super_id)
    trip = passenger_trip(bw, referee)
    clients = [ref.client(), ref.client()]
    first = [(accepted_passenger(bw, c, trip, referee), c) for c in clients]
    complete_passengers(bw, trip[0], referee, first)  # two bookings, one trip
    ready = max(_ready_at(ref, b) for b, _ in first)
    assert _process(ref, enrollment, ready) == "granted"
    assert _scalar(ref, "SELECT count(*) FROM promo_qualifications WHERE enrollment_id = :e", e=enrollment) == 1  # step 1 only
    second_trip = passenger_trip(bw, referee)
    b3 = accepted_passenger(bw, ref.client(), second_trip, referee)
    complete_passengers(bw, second_trip[0], referee, [(b3, _scalar(ref, "SELECT client_user_id FROM bookings WHERE id = :b", b=b3))])
    assert _process(ref, enrollment, _ready_at(ref, b3)) == "granted"
    assert _scalar(ref, "SELECT count(*) FROM promo_lots l JOIN promo_obligations o ON o.id = l.obligation_id "
                        "WHERE o.enrollment_id = :e", e=enrollment) == 4  # both sides x two steps, once each
    assert _scalar(ref, "SELECT status FROM promo_enrollments WHERE id = :e", e=enrollment) == "granted"


# --- expiry, reversal, reinstate ---------------------------------------------------------------------------------------


def _granted_lot(bw: BW, ref: Ref, campaign: int) -> tuple[int, int]:
    referee, enrollment = _enrolled(ref, campaign)
    booking = completed_passenger(bw, referee)
    _process(ref, enrollment, _ready_at(ref, booking))
    lot = next(l for l in _lots(ref, enrollment) if l["owner_user_id"] == referee)
    return lot["id"], enrollment


def test_repeated_reinstate_and_reversal_are_single(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    lot_id, _ = _granted_lot(bw, ref, campaign)
    expires = _scalar(ref, "SELECT expires_at FROM promo_lots WHERE id = :l", l=lot_id)
    with ref.pg_db.session() as s:
        service.expire_due_lots(s, now=expires)
        s.commit()
    release = _scalar(ref, "SELECT id FROM promo_ledger_transactions WHERE lot_id = :l AND kind = 'release_granted'", l=lot_id)

    def reinstate(index: int, session) -> int:  # noqa: ANN001
        lot = qualification.reinstate_expired_release(session, release_transaction_id=release,
                                                      actor_user_id=ref.promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                                      reason="platform outage", now=expires + timedelta(hours=1))
        session.commit()
        return lot.id

    report = run_concurrently(4, reinstate, engine=ref.pg_db.engine)
    for failure in report.failures:
        assert isinstance(failure.error, DomainError)
    assert _scalar(ref, "SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'reinstate' AND reinstates_id = :r", r=release) == 1
    assert _scalar(ref, "SELECT status FROM promo_lots WHERE id = :l", l=lot_id) == "available"

    def reverse(index: int, session) -> str:  # noqa: ANN001
        lot = service.reverse_lot(session, lot_id=lot_id, actor_user_id=ref.promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                  reason="confirmed abuse")
        session.commit()
        return lot.status

    report = run_concurrently(4, reverse, engine=ref.pg_db.engine)
    assert not report.failures, [r.error for r in report.failures]
    assert _scalar(ref, "SELECT count(*) FROM promo_ledger_transactions WHERE lot_id = :l AND reference_key LIKE "
                        "'release_granted:reversal%'", l=lot_id) == 1
    with ref.pg_db.session() as s:  # a reversal release is not reinstatable
        reversal = s.execute(text("SELECT id FROM promo_ledger_transactions WHERE lot_id = :l AND reference_key LIKE "
                                  "'release_granted:reversal%'"), {"l": lot_id}).scalar_one()
        with pytest.raises(DomainError):
            qualification.reinstate_expired_release(s, release_transaction_id=reversal, actor_user_id=ref.promo.admin_id,
                                                    actor_capabilities=ADMIN_CAPS, reason="x")
    assert ref.promo.issues(campaign) == []


def test_reinstate_without_budget_room_is_refused_without_a_negative(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign(allocate_minor=COMMITMENT)
    lot_id, _ = _granted_lot(bw, ref, campaign)
    expires = _scalar(ref, "SELECT expires_at FROM promo_lots WHERE id = :l", l=lot_id)
    with ref.pg_db.session() as s:
        service.expire_due_lots(s, now=expires)
        s.commit()
    with ref.pg_db.session() as s:  # the budget source shrank: exactly the room the expiry returned is taken (G14 floor)
        room = service.budget_position(s, campaign).reducible_minor(service.pending_reinstatements_minor(s, campaign))
        assert room >= REFEREE_REWARD  # at least the expired referee lot came back
        service.request_budget_change(s, actor_user_id=ref.promo.finance_id,
                                      actor_capabilities=FINANCE_CAPS,
                                      campaign_id=campaign, kind="reduce_allocation",
                                      amount_minor=room, reason="source refund")
        s.commit()
    release = _scalar(ref, "SELECT id FROM promo_ledger_transactions WHERE lot_id = :l AND kind = 'release_granted'", l=lot_id)
    with ref.pg_db.session() as s:
        with pytest.raises(DomainError) as exc:
            qualification.reinstate_expired_release(s, release_transaction_id=release, actor_user_id=ref.promo.admin_id,
                                                    actor_capabilities=ADMIN_CAPS, reason="outage")
        assert exc.value.code is ErrorCode.PROMO_BUDGET_EXHAUSTED
    position = ref.promo.budget(campaign)
    assert position.committed_minor <= position.allocated_minor + position.shortfall_minor
    assert _scalar(ref, "SELECT count(*) FROM promo_ledger_transactions WHERE kind = 'reinstate'") == 0


# --- pause, suspension, authority -----------------------------------------------------------------------------------


def test_pause_keeps_obligations_and_suspension_stops_processing_without_deleting(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    ready = _ready_at(ref, completed_passenger(bw, referee))
    with ref.pg_db.session() as s:
        version = s.execute(text("SELECT version FROM promo_campaigns WHERE id = :c"), {"c": campaign}).scalar_one()
        service.pause_campaign(s, actor_user_id=ref.promo.super_id, actor_capabilities=SUPER_CAPS, campaign_id=campaign,
                               expected_version=version, reason="new enrollments stop")
        qualification.suspend_processing(s, campaign_id=campaign, actor_user_id=ref.promo.super_id,
                                         actor_capabilities=SUPER_CAPS, reason="safety stop")
        s.commit()
    assert _process(ref, enrollment, ready) == "suspended"
    with ref.pg_db.session() as s:
        assert qualification.expire_enrollments(s, now=utc_now() + timedelta(days=90)) == 0
        s.commit()
    assert ref.count("promo_obligations", "enrollment_id = :e AND status = 'promised'", e=enrollment) == 2
    with ref.pg_db.session() as s:
        qualification.resume_processing(s, campaign_id=campaign, actor_user_id=ref.promo.super_id,
                                        actor_capabilities=SUPER_CAPS, reason="clear")
        s.commit()
    assert _process(ref, enrollment, ready) == "granted"  # paused for new people, still honoured for existing ones


def test_unauthorised_staff_cannot_grant_or_move_ledger_through_reviews(q) -> None:  # noqa: ANN001
    bw, ref = q
    campaign = ref.campaign()
    referee, enrollment = _enrolled(ref, campaign)
    ready = _ready_at(ref, completed_passenger(bw, referee))
    with ref.pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'blocked' WHERE id = (SELECT referrer_user_id FROM promo_enrollments "
                          "WHERE id = :e)"), {"e": enrollment})
    _process(ref, enrollment, ready)
    review_id, version = ref.pg_db.engine.connect().execute(text(
        "SELECT id, version FROM promo_reviews WHERE enrollment_id = :e"), {"e": enrollment}).one()
    ledger_before = _scalar(ref, "SELECT count(*) FROM promo_ledger_transactions")
    with ref.pg_db.session() as s:
        for caps in (OPERATOR_CAPS, frozenset()):
            with pytest.raises(DomainError) as exc:
                qualification.decide_review(s, review_id=review_id, decision="approve", actor_user_id=ref.promo.operator_id,
                                            actor_capabilities=caps, note="x", expected_version=version)
            assert exc.value.code is ErrorCode.FORBIDDEN
        with pytest.raises(DomainError):
            qualification.reinstate_expired_release(s, release_transaction_id=1, actor_user_id=ref.promo.operator_id,
                                                    actor_capabilities=OPERATOR_CAPS, reason="x")
    assert _scalar(ref, "SELECT count(*) FROM promo_ledger_transactions") == ledger_before
    assert _scalar(ref, "SELECT status FROM promo_reviews WHERE id = :r", r=review_id) == "open"


def test_the_retired_path_job_runs_under_the_application_role_once_and_keeps_the_reserve(roles, q) -> None:  # noqa: ANN001, F811
    """Q147 worker job under the real non-privileged application role (db_roles.bootstrap, as deploy does), on a real
    promised parcel enrollment: one review, a second run opens none, the reserve and the promise stay as they were."""
    from sqlalchemy import create_engine

    from app import worker
    from tests.pg.ops.test_db_roles import _as, _libpq_dsn, _plan, db_roles

    bw, ref = q
    campaign = ref.parcel_campaign()
    _, enrollment = _enrolled(ref, campaign)
    promised = ref.promo.budget(campaign).promised_minor
    db_roles.bootstrap(_libpq_dsn(ref.pg_db.url), _plan(ref.pg_db, roles))
    engine = create_engine(_as(ref.pg_db, roles.app, roles.app_password))
    job = next(j for j in worker.SERVICE_JOBS if j.name == "promotions.review_retired_parcel_enrollments")
    try:
        with engine.connect() as conn:
            who = conn.execute(text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert (who[0], who[1], who[2]) == (roles.app, False, False)
        first = worker.run_service_job(job, worker.resolve_service_function(job), engine=engine)
        second = worker.run_service_job(job, worker.resolve_service_function(job), engine=engine)
    finally:
        engine.dispose()
    assert first == (True, 1) and second == (True, 0)
    assert len(_retired_reviews(ref, enrollment)) == 1
    assert _enrollment_status(ref, enrollment) == "promised" and _lots(ref, enrollment) == []
    assert ref.promo.budget(campaign).promised_minor == promised
