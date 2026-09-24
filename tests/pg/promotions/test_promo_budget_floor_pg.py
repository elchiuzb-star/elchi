"""G14 budget floor on PostgreSQL (referral stage 6, ADR-0023 §20.2, migration 0090).

A plain ``reduce_allocation`` never takes the budget below spent + outstanding obligations: ``B >= S + L``, reducible
``max(0, B - S - L)``; L = promised + granted (reserved-on-bookings inside granted, counted once) + approved
reinstatements waiting for room. A real loss of external funding is a separate ``funding_loss`` with evidence: it may
leave a shortfall, cancels nothing, pauses the campaign. Service and database both enforce it. SYNTHETIC values only.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import PromoLedgerKind
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.money import TWO_PERSON_APPROVAL_THRESHOLD_MINOR
from app.contracts.timeutil import utc_now
from app.modules.promotions import qualification, reporting, service
from tests.pg.harness import run_concurrently
from tests.pg.promotions.conftest import (
    ADMIN_CAPS,
    COMMITMENT,
    FINANCE_CAPS,
    REFEREE_REWARD,
    SUPER_CAPS,
)

pytestmark = pytest.mark.pg

REDUCE, LOSS = PromoLedgerKind.REDUCE_ALLOCATION, PromoLedgerKind.FUNDING_LOSS


def _change(promo, campaign: int, kind: PromoLedgerKind, amount: int, *, actor: int | None = None,  # noqa: ANN001
            caps=FINANCE_CAPS, evidence: str | None = None, session=None):  # noqa: ANN001, ANN202
    own = session is None
    s = session or promo.session()
    try:
        row = service.request_budget_change(s, actor_user_id=actor or promo.finance_id, actor_capabilities=caps,
                                            campaign_id=campaign, kind=kind, amount_minor=amount,
                                            reason="synthetic budget change", evidence_reference=evidence)
        s.commit()
        return row
    except BaseException:
        s.rollback()
        raise
    finally:
        if own:
            s.close()


def _state(promo, campaign: int) -> tuple:  # noqa: ANN001
    """Everything a refused change must leave untouched: the budget row, the ledger and the requests."""
    with promo.pg_db.engine.connect() as conn:
        budget = tuple(conn.execute(text("SELECT allocated_minor, promised_minor, granted_minor, consumed_minor, "
                                         "released_minor, last_ledger_seq FROM promo_budgets WHERE campaign_id = :c"),
                                    {"c": campaign}).one())
        ledger = conn.execute(text("SELECT count(*) FROM promo_ledger_transactions WHERE campaign_id = :c"),
                              {"c": campaign}).scalar()
        requests = conn.execute(text("SELECT count(*) FROM promo_budget_requests WHERE campaign_id = :c"),
                                {"c": campaign}).scalar()
    return budget, ledger, requests


def _floor_holds(promo, campaign: int) -> bool:  # noqa: ANN001
    with promo.session() as s:
        position = service.budget_position(s, campaign)
        return position.allocated_minor >= position.committed_minor


def _expired_lot(promo, campaign: int) -> tuple[int, int]:  # noqa: ANN001
    """A referee lot (REFEREE_REWARD) that expired unspent: (lot id, its expiry release ledger id)."""
    lot_id = promo.granted_lot(campaign)
    with promo.session() as s:
        expires = s.execute(text("SELECT expires_at FROM promo_lots WHERE id = :l"), {"l": lot_id}).scalar_one()
        service.expire_due_lots(s, now=expires)
        s.commit()
        release = s.execute(text("SELECT id FROM promo_ledger_transactions WHERE lot_id = :l AND kind = 'release_granted'"),
                            {"l": lot_id}).scalar_one()
    return lot_id, release


def _reinstate(promo, release: int, session=None):  # noqa: ANN001, ANN202
    own = session is None
    s = session or promo.session()
    try:
        lot = qualification.reinstate_expired_release(s, release_transaction_id=release, actor_user_id=promo.admin_id,
                                                      actor_capabilities=ADMIN_CAPS, reason="synthetic outage")
        s.commit()
        return lot.id
    except BaseException:
        s.rollback()
        raise
    finally:
        if own:
            s.close()


def test_g14_reduction_reaches_exactly_spent_plus_obligations_and_one_tiyin_more_changes_nothing(promo, bookings) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT * 4)  # B = 2 000 000
    promo.promise(campaign)  # promised 500 000
    lot_id = promo.granted_lot(campaign)  # + promised 300 000 (referrer) and granted 200 000 (referee)
    booking, other = (bookings.new(driver_user_id=bookings.world.driver_id) for _ in range(2))
    with promo.session() as s:
        spent = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=100_000)
        service.consume_redemption(s, redemption_id=spent.id)
        service.reserve_lot(s, lot_id=lot_id, booking_id=other, amount_minor=50_000)  # reserved: inside granted
        s.commit()
    # S = 100 000; L = promised 800 000 + granted 100 000 (of which 50 000 reserved) -> reducible 1 000 000
    with promo.session() as s:
        assert service.budget_position(s, campaign).reducible_minor() == 1_000_000
    before = _state(promo, campaign)
    with pytest.raises(DomainError) as exc:
        _change(promo, campaign, REDUCE, 1_000_001)
    assert exc.value.code is ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT
    assert exc.value.details["reducible_minor"] == 1_000_000
    assert _state(promo, campaign) == before  # refused: budget, ledger and requests untouched

    _change(promo, campaign, REDUCE, 1_000_000)  # exactly to the floor
    position = promo.budget(campaign)
    assert position.allocated_minor == position.committed_minor == 1_000_000 and position.shortfall_minor == 0
    at_floor = _state(promo, campaign)
    with pytest.raises(DomainError) as exc:
        _change(promo, campaign, REDUCE, 1)
    assert exc.value.code is ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT
    assert _state(promo, campaign) == at_floor
    assert promo.issues(campaign) == []


def test_g14_no_authority_and_no_raw_posting_can_go_below_the_floor_or_lower_the_spend(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT * 2)
    promo.promise(campaign)  # room = COMMITMENT
    before = _state(promo, campaign)
    with pytest.raises(DomainError) as exc:  # the super_admin has the budget capability - and still cannot
        _change(promo, campaign, REDUCE, COMMITMENT + 1, actor=promo.super_id, caps=SUPER_CAPS)
    assert exc.value.code is ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT
    with pytest.raises(DBAPIError) as db_exc, promo.pg_db.engine.begin() as conn:  # the service bypassed: DB refuses
        conn.execute(text("INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, "
                          "reference_key, actor_user_id, reason) VALUES (gen_random_uuid(), :c, 'reduce_allocation', "
                          ":a, 'raw:below-floor', :u, 'raw posting')"), {"c": campaign, "a": COMMITMENT + 1,
                                                                            "u": promo.super_id})
    assert db_exc.value.orig.diag.constraint_name == "promo_budget_below_commitment"
    with pytest.raises(DBAPIError) as db_exc, promo.pg_db.engine.begin() as conn:  # S cannot be edited down either
        conn.execute(text("UPDATE promo_budgets SET consumed_minor = 0 WHERE campaign_id = :c"), {"c": campaign})
    assert db_exc.value.orig.diag.constraint_name == "promo_budget_writer_refused"
    with pytest.raises(DBAPIError), promo.pg_db.engine.begin() as conn:  # no negative movement exists
        conn.execute(text("INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, "
                          "reference_key, actor_user_id, reason) VALUES (gen_random_uuid(), :c, 'allocate', -1, "
                          "'raw:negative', :u, 'raw')"), {"c": campaign, "u": promo.super_id})
    with pytest.raises(DBAPIError) as db_exc, promo.pg_db.engine.begin() as conn:  # a loss needs its own evidence
        conn.execute(text("INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, "
                          "reference_key, actor_user_id, reason) VALUES (gen_random_uuid(), :c, 'funding_loss', 1, "
                          "'raw:loss', :u, 'raw')"), {"c": campaign, "u": promo.super_id})
    assert db_exc.value.orig.diag.constraint_name == "promo_funding_loss_evidence"  # the trigger runs first
    assert _state(promo, campaign) == before
    assert promo.issues(campaign) == []


def test_g14_a_reduction_racing_an_enrollment_cannot_both_take_the_last_room(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT * 2)
    promo.promise(campaign)  # room = COMMITMENT: either one more promise or one reduction of it

    def work(index: int, session) -> str:  # noqa: ANN001
        if index == 0:
            _change(promo, campaign, REDUCE, COMMITMENT, session=session)
            return "reduced"
        service.promise_rewards(session, campaign_id=campaign, rewards=promo.specs(), source_type="synthetic_test",
                                source_id=2)
        session.commit()
        return "promised"

    report = run_concurrently(2, work, engine=promo.pg_db.engine)
    winners = [r.value for r in report.results if r.error is None]
    assert len(winners) == 1, [r.error for r in report.results]
    loser = next(r for r in report.results if r.error is not None)
    assert isinstance(loser.error, DomainError) and loser.error.code in (
        ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT, ErrorCode.PROMO_BUDGET_EXHAUSTED)
    assert _floor_holds(promo, campaign) and promo.budget(campaign).shortfall_minor == 0
    assert promo.issues(campaign) == []


def test_g14_a_reduction_racing_an_approved_reinstatement_keeps_the_floor(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT)
    _, release = _expired_lot(promo, campaign)  # the expiry freed REFEREE_REWARD of room

    def work(index: int, session) -> str:  # noqa: ANN001
        if index == 0:
            _change(promo, campaign, REDUCE, REFEREE_REWARD, session=session)
            return "reduced"
        _reinstate(promo, release, session=session)
        return "reinstated"

    report = run_concurrently(2, work, engine=promo.pg_db.engine)
    winners = [r.value for r in report.results if r.error is None]
    assert len(winners) == 1, [r.error for r in report.results]
    assert _floor_holds(promo, campaign)
    with promo.session() as s:  # an approved reinstatement that lost the race waits as L: nothing more to reduce
        position = service.budget_position(s, campaign)
        pending = service.pending_reinstatements_minor(s, campaign)
        assert pending == (REFEREE_REWARD if winners == ["reduced"] else 0)
        assert position.reducible_minor(pending) == 0
    with pytest.raises(DomainError) as exc:
        _change(promo, campaign, REDUCE, 1)
    assert exc.value.code is ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT
    assert promo.issues(campaign) == []


def test_g14_an_approved_reinstatement_waiting_for_room_is_an_obligation_in_the_floor(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT)
    _, release = _expired_lot(promo, campaign)
    _change(promo, campaign, REDUCE, REFEREE_REWARD)  # exactly the room the expiry freed
    with pytest.raises(DomainError) as exc:  # approved, but no room: stays as an unfulfilled, escalated review
        _reinstate(promo, release)
    assert exc.value.code is ErrorCode.PROMO_BUDGET_EXHAUSTED
    with promo.session() as s:
        assert service.pending_reinstatements_minor(s, campaign) == REFEREE_REWARD
    _change(promo, campaign, PromoLedgerKind.ALLOCATE, 300_000)  # room in the buckets: 300 000 ...
    with pytest.raises(DomainError) as exc:  # ... but 200 000 of it belongs to the waiting reinstatement
        _change(promo, campaign, REDUCE, 100_001)
    assert exc.value.details["reducible_minor"] == 100_000
    _change(promo, campaign, REDUCE, 100_000)
    _reinstate(promo, release)  # the waiting reinstatement still fits
    with promo.session() as s:
        assert service.pending_reinstatements_minor(s, campaign) == 0
    assert _floor_holds(promo, campaign) and promo.issues(campaign) == []


def test_g14_a_funding_loss_is_apart_needs_evidence_leaves_a_shortfall_and_cancels_nothing(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT * 2)
    first = promo.promise(campaign)
    promo.promise(campaign)  # B = S + L exactly
    with pytest.raises(DomainError) as exc:
        _change(promo, campaign, LOSS, COMMITMENT)  # no evidence reference
    assert exc.value.code is ErrorCode.VALIDATION_ERROR
    _change(promo, campaign, LOSS, COMMITMENT, evidence="SYNTHETIC-BANK-NOTICE-1")
    position = promo.budget(campaign)
    assert (position.allocated_minor, position.promised_minor, position.shortfall_minor) == (
        COMMITMENT, COMMITMENT * 2, COMMITMENT)  # nothing cancelled; a real shortfall
    with promo.session() as s:
        assert s.execute(text("SELECT status FROM promo_campaigns WHERE id = :c"), {"c": campaign}).scalar() == "paused"
        assert s.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'funding_loss_escalated' "
                              "AND entity_id = :c"), {"c": campaign}).scalar() == 1
        version = s.execute(text("SELECT version FROM promo_campaigns WHERE id = :c"), {"c": campaign}).scalar()
        with pytest.raises(DomainError) as exc:  # it cannot be resumed into new promises while short
            service.resume_campaign(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS,
                                    campaign_id=campaign, expected_version=version, reason="t")
        assert exc.value.code is ErrorCode.PROMO_BUDGET_EXHAUSTED
    with pytest.raises(DomainError):
        promo.promise(campaign)
    with promo.session() as s:  # an old promise is still honoured
        assert service.grant_obligation(s, obligation_id=first[1]).amount_minor == REFEREE_REWARD
        s.commit()
    assert promo.ledger_count(campaign, "funding_loss") == 1
    assert promo.issues(campaign) == []


def test_g14_a_large_funding_loss_needs_a_second_different_finance_approver(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=TWO_PERSON_APPROVAL_THRESHOLD_MINOR)
    _change(promo, campaign, PromoLedgerKind.ALLOCATE, TWO_PERSON_APPROVAL_THRESHOLD_MINOR)
    request = _change(promo, campaign, LOSS, TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1, evidence="SYNTHETIC-NOTICE-2")
    assert promo.ledger_count(campaign, "funding_loss") == 0  # waits for the second person
    with promo.session() as s:
        with pytest.raises(DomainError) as exc:
            service.approve_budget_request(s, actor_user_id=promo.finance_id, actor_capabilities=FINANCE_CAPS,
                                           request_id=request.id, expected_version=request.version)
        assert exc.value.code is ErrorCode.SECOND_APPROVER_REQUIRED
    with promo.session() as s:
        service.approve_budget_request(s, actor_user_id=promo.finance2_id, actor_capabilities=FINANCE_CAPS,
                                       request_id=request.id, expected_version=request.version)
        s.commit()
    assert promo.ledger_count(campaign, "funding_loss") == 1 and promo.issues(campaign) == []


def test_g14_a_new_report_period_never_erases_old_spend_or_obligations(promo, bookings) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT * 2)
    lot_id = promo.granted_lot(campaign)
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    with promo.session() as s:
        service.consume_redemption(s, redemption_id=service.reserve_lot(
            s, lot_id=lot_id, booking_id=booking, amount_minor=100_000).id)
        s.commit()
    later = utc_now() + timedelta(days=400)  # a report period that starts long after all of it
    with promo.session() as s:
        start, end = reporting.day_bounds(later.date(), later.date())
        data = reporting.build_report(s, group_by="service", start=start, end=end, now=utc_now())
        s.rollback()
    [row] = [b for b in data["budgets"] if b["consumed_minor"] == 100_000]
    assert row["committed_minor"] == COMMITMENT and row["reducible_minor"] == COMMITMENT  # budgets are all-time state
    assert data["rows"] == [] or all(r["values"]["spent_passenger_bonus_minor"] in (0, None) for r in data["rows"])
