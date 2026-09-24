"""Promotions budget and immutable promo ledger on PostgreSQL (referral stage 1, ADR-0023, Q105/Q111/Q114/Q115).

SYNTHETIC amounts only. Covers QA #6, #7, #8, #22, #24 (budget half) and the stage-1 acceptance criteria A1.x.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import PromoCampaignKind, PromoInstrument, PromoLedgerKind
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.money import TWO_PERSON_APPROVAL_THRESHOLD_MINOR
from app.modules.promotions import service
from tests.pg.harness import run_concurrently
from tests.pg.promotions.conftest import (
    ADMIN_CAPS,
    COMMITMENT,
    FINANCE_CAPS,
    OPERATOR_CAPS,
    REFEREE_REWARD,
    SUPER_CAPS,
    SYNTH_POLICY,
    synthetic_terms,
)

pytestmark = pytest.mark.pg


def _code(result) -> ErrorCode | None:  # noqa: ANN001
    return result.error.code if isinstance(result.error, DomainError) else None


# --- two-sided promise and the last remainder -----------------------------------------------------------------


def test_both_sides_are_reserved_before_anything_is_promised(promo) -> None:  # noqa: ANN001
    """QA #6: an enrollment reserves referrer + referee in one step; a budget for one side only refuses both."""
    campaign = promo.campaign(allocate_minor=COMMITMENT)
    promo.promise(campaign)
    position = promo.budget(campaign)
    assert (position.promised_minor, position.available_for_new_minor) == (COMMITMENT, 0)

    small = promo.campaign(allocate_minor=COMMITMENT - 1, activate=False)
    with promo.session() as s:
        with pytest.raises(DomainError):  # cannot even be activated: not one maximum promise fits
            version_id = s.execute(text("SELECT id FROM promo_campaign_versions WHERE campaign_id = :c"), {"c": small}).scalar_one()
            service.activate_campaign(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS,
                                      campaign_id=small, version_id=version_id, expected_version=1, reason="t")


def test_partial_enrollment_leaves_nothing_behind(promo) -> None:  # noqa: ANN001
    """A failure half-way (second side does not fit) rolls back the first side too - no partial reserve."""
    campaign = promo.campaign(allocate_minor=COMMITMENT)
    with promo.session() as s:
        with pytest.raises(DomainError) as exc:
            service.promise_rewards(s, campaign_id=campaign, source_type="synthetic_test", source_id=1,
                                    rewards=promo.specs(referee_amount=REFEREE_REWARD + 1))
        assert exc.value.code is ErrorCode.PROMO_BUDGET_EXHAUSTED
        s.commit()
    assert promo.budget(campaign).committed_minor == 0
    assert promo.ledger_count(campaign, "promise") == 0
    with promo.pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM promo_obligations WHERE campaign_id = :c"), {"c": campaign}).scalar_one() == 0


def test_two_operations_cannot_take_the_last_remainder(promo) -> None:  # noqa: ANN001
    """The budget holds exactly one more enrollment; two race for it; exactly one wins."""
    campaign = promo.campaign(allocate_minor=COMMITMENT * 3)
    promo.promise(campaign)
    promo.promise(campaign)
    specs = [promo.specs() for _ in range(2)]

    def enroll(index: int, session) -> int:  # noqa: ANN001
        rows = service.promise_rewards(session, campaign_id=campaign, rewards=specs[index],
                                       source_type="synthetic_test", source_id=index)
        session.commit()
        return len(rows)

    report = run_concurrently(2, enroll, engine=promo.pg_db.engine)
    assert len(report.successes) == 1
    assert [_code(r) for r in report.failures] == [ErrorCode.PROMO_BUDGET_EXHAUSTED]
    position = promo.budget(campaign)
    assert position.committed_minor == position.allocated_minor == COMMITMENT * 3
    assert promo.issues(campaign) == []


def test_parallel_enrollments_never_exceed_the_budget(promo) -> None:  # noqa: ANN001
    """QA #7: 20 concurrent enrollments against room for 5."""
    campaign = promo.campaign(allocate_minor=COMMITMENT * 5)
    specs = [promo.specs() for _ in range(20)]

    def enroll(index: int, session) -> None:  # noqa: ANN001
        service.promise_rewards(session, campaign_id=campaign, rewards=specs[index],
                                source_type="synthetic_test", source_id=index)
        session.commit()

    report = run_concurrently(20, enroll, engine=promo.pg_db.engine)
    assert len(report.successes) == 5
    assert {_code(r) for r in report.failures} == {ErrorCode.PROMO_BUDGET_EXHAUSTED}
    position = promo.budget(campaign)
    assert position.committed_minor == position.allocated_minor
    assert promo.ledger_count(campaign, "promise") == 10
    assert promo.issues(campaign) == []


# --- idempotency: repeated request / worker event -------------------------------------------------------------


def test_replayed_enrollment_creates_nothing_new(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    specs = promo.specs(key="replay")
    first = promo.promise(campaign, specs)
    second = promo.promise(campaign, specs)
    assert first == second
    assert promo.ledger_count(campaign, "promise") == 2


def test_parallel_duplicate_enrollment_and_grant_make_one_reward(promo) -> None:  # noqa: ANN001
    """QA #5/#20: the same event processed by several workers at once -> one obligation set, one lot."""
    campaign = promo.campaign()
    specs = promo.specs(key="dup")

    def enroll(index: int, session) -> list[int]:  # noqa: ANN001
        rows = service.promise_rewards(session, campaign_id=campaign, rewards=specs,
                                       source_type="synthetic_test", source_id=1)
        session.commit()
        return [row.id for row in rows]

    report = run_concurrently(6, enroll, engine=promo.pg_db.engine)
    assert not report.failures, [r.error for r in report.failures]
    assert len({tuple(v) for v in report.values()}) == 1
    obligation_id = report.values()[0][1]

    def grant(index: int, session) -> int:  # noqa: ANN001
        lot = service.grant_obligation(session, obligation_id=obligation_id)
        session.commit()
        return lot.id

    grants = run_concurrently(6, grant, engine=promo.pg_db.engine)
    assert not grants.failures, [r.error for r in grants.failures]
    assert len(set(grants.values())) == 1
    assert promo.ledger_count(campaign, "grant") == 1
    assert promo.budget(campaign).promised_minor == COMMITMENT - REFEREE_REWARD
    assert promo.budget(campaign).granted_minor == REFEREE_REWARD
    assert promo.issues(campaign) == []


# --- stages of one obligation are counted once (Q115) ---------------------------------------------------------


def test_promise_grant_consume_are_stages_of_one_obligation(promo, bookings) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    obligation_ids = promo.promise(campaign)
    committed = promo.budget(campaign).committed_minor
    with promo.session() as s:
        lot = service.grant_obligation(s, obligation_id=obligation_ids[1], granted_minor=REFEREE_REWARD - 50_000)
        s.commit()
        lot_id = lot.id
    after_grant = promo.budget(campaign)
    assert after_grant.committed_minor == committed - 50_000  # the unused part went back, nothing double-counted
    with promo.session() as s:
        redemption = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=100_000)
        service.consume_redemption(s, redemption_id=redemption.id)
        s.commit()
    after_consume = promo.budget(campaign)
    assert after_consume.committed_minor == after_grant.committed_minor
    assert (after_consume.consumed_minor, after_consume.granted_minor) == (100_000, REFEREE_REWARD - 50_000 - 100_000)
    assert promo.issues(campaign) == []


# --- pause, shortfall, commitments (QA #8, task §8) ------------------------------------------------------------


def test_pause_keeps_every_existing_commitment(promo, bookings) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    promised = promo.promise(campaign)
    lot_id = promo.granted_lot(campaign)
    with promo.session() as s:
        service.pause_campaign(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS, campaign_id=campaign,
                               expected_version=2, reason="synthetic pause")
        s.commit()
    with promo.session() as s:
        with pytest.raises(DomainError) as exc:
            service.promise_rewards(s, campaign_id=campaign, rewards=promo.specs(), source_type="synthetic_test", source_id=9)
        assert exc.value.code is ErrorCode.FEATURE_DISABLED
    with promo.session() as s:  # an earlier promise can still be granted, and a granted bonus still spends
        service.grant_obligation(s, obligation_id=promised[0])
        redemption = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=REFEREE_REWARD)
        service.consume_redemption(s, redemption_id=redemption.id)
        s.commit()
    assert promo.issues(campaign) == []


def test_budget_shortfall_stops_new_enrollments_but_honours_old_ones(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(allocate_minor=COMMITMENT * 2)
    obligations = promo.promise(campaign)
    promo.promise(campaign)
    with promo.session() as s:  # external funding really lost (G14: a plain reduction cannot go this low)
        service.request_budget_change(s, actor_user_id=promo.finance_id, actor_capabilities=FINANCE_CAPS,
                                      campaign_id=campaign, kind=PromoLedgerKind.FUNDING_LOSS,
                                      amount_minor=COMMITMENT, reason="synthetic source refund",
                                      evidence_reference="SYNTHETIC-NOTICE")
        s.commit()
    position = promo.budget(campaign)
    assert position.shortfall_minor == COMMITMENT
    assert position.promised_minor == COMMITMENT * 2  # nothing cancelled
    with promo.session() as s:  # paused by the funding loss itself; the sweep finds nothing left to pause
        assert s.execute(text("SELECT status FROM promo_campaigns WHERE id = :c"), {"c": campaign}).scalar() == "paused"
        assert service.pause_exhausted_campaigns(s) == []
        s.commit()
    with promo.session() as s:
        lot = service.grant_obligation(s, obligation_id=obligations[0])  # still honoured
        s.commit()
        assert lot.amount_minor > 0
    assert promo.issues(campaign) == []


# --- authority (Q105, Q114) -----------------------------------------------------------------------------------


def test_operator_cannot_change_budget_or_campaign(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    with promo.session() as s:
        for call in (
            lambda: service.request_budget_change(s, actor_user_id=promo.operator_id, actor_capabilities=OPERATOR_CAPS,
                                                  campaign_id=campaign, kind="allocate", amount_minor=1, reason="x"),
            lambda: service.pause_campaign(s, actor_user_id=promo.operator_id, actor_capabilities=OPERATOR_CAPS,
                                           campaign_id=campaign, expected_version=2, reason="x"),
            lambda: service.request_budget_change(s, actor_user_id=promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                                  campaign_id=campaign, kind="allocate", amount_minor=1, reason="x"),
        ):
            with pytest.raises(DomainError) as exc:
                call()
            assert exc.value.code is ErrorCode.FORBIDDEN


def test_database_refuses_budget_changes_by_non_finance_staff(promo) -> None:  # noqa: ANN001
    """Even a direct INSERT by the app role cannot allocate on an operator's authority."""
    campaign = promo.campaign()
    with pytest.raises(DBAPIError) as info:
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, reference_key, "
                "actor_user_id, reason) VALUES (gen_random_uuid(), :c, 'allocate', 1, 'raw-operator', :u, 'raw')"),
                {"c": campaign, "u": promo.operator_id})
    assert info.value.orig.diag.constraint_name == "approver_not_finance_staff"


def test_budget_and_ledger_cannot_be_edited_directly(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign()
    for statement, rule in (
        ("UPDATE promo_budgets SET allocated_minor = allocated_minor + 1 WHERE campaign_id = :c", "promo_budget_writer_refused"),
        ("DELETE FROM promo_budgets WHERE campaign_id = :c", "promo_budget_writer_refused"),
        ("UPDATE promo_ledger_transactions SET amount_minor = 1 WHERE campaign_id = :c", "append_only_violation"),
        ("DELETE FROM promo_ledger_transactions WHERE campaign_id = :c", "append_only_violation"),
        ("UPDATE promo_campaign_versions SET referee_reward_minor = 1 WHERE campaign_id = :c", "append_only_violation"),
    ):
        with pytest.raises(DBAPIError) as info:
            with promo.pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"c": campaign})
        assert info.value.orig.diag.constraint_name == rule, statement
    for table in ("promo_ledger_transactions", "promo_budgets"):
        with pytest.raises(DBAPIError):
            with promo.pg_db.engine.begin() as conn:
                conn.execute(text(f"TRUNCATE {table} CASCADE"))


def test_large_budget_change_needs_a_different_finance_approver(promo) -> None:  # noqa: ANN001
    """Q114: the wallet's threshold and rule, reused - strictly above needs a second, different person."""
    campaign = promo.campaign()
    before = promo.budget(campaign).allocated_minor
    with promo.session() as s:  # exactly the threshold posts at once
        request = service.request_budget_change(s, actor_user_id=promo.finance_id, actor_capabilities=FINANCE_CAPS,
                                                campaign_id=campaign, kind="allocate",
                                                amount_minor=TWO_PERSON_APPROVAL_THRESHOLD_MINOR, reason="at threshold")
        s.commit()
        assert request.status == "posted"
    with promo.session() as s:
        request = service.request_budget_change(s, actor_user_id=promo.finance_id, actor_capabilities=FINANCE_CAPS,
                                                campaign_id=campaign, kind="allocate",
                                                amount_minor=TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1, reason="large")
        s.commit()
        request_id, version = request.id, request.version
        assert request.status == "pending"
    assert promo.budget(campaign).allocated_minor == before + TWO_PERSON_APPROVAL_THRESHOLD_MINOR
    with promo.session() as s:
        with pytest.raises(DomainError) as exc:
            service.approve_budget_request(s, actor_user_id=promo.finance_id, actor_capabilities=FINANCE_CAPS,
                                           request_id=request_id, expected_version=version)
        assert exc.value.code is ErrorCode.SECOND_APPROVER_REQUIRED
    with promo.session() as s:
        with pytest.raises(DomainError) as exc:
            service.approve_budget_request(s, actor_user_id=promo.admin_id, actor_capabilities=ADMIN_CAPS,
                                           request_id=request_id, expected_version=version)
        assert exc.value.code is ErrorCode.FORBIDDEN
    with promo.session() as s:
        service.approve_budget_request(s, actor_user_id=promo.finance2_id, actor_capabilities=FINANCE_CAPS,
                                       request_id=request_id, expected_version=version)
        s.commit()
    assert promo.budget(campaign).allocated_minor == before + 2 * TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1
    # the DB refuses a raw large posting without an approved request
    with pytest.raises(DBAPIError) as info:
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, reference_key, "
                "actor_user_id, reason) VALUES (gen_random_uuid(), :c, 'allocate', :a, 'raw-large', :u, 'raw')"),
                {"c": campaign, "a": TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1, "u": promo.finance_id})
    assert info.value.orig.diag.constraint_name == "promo_second_approver_required"
    with pytest.raises(DBAPIError) as info:  # and a request row approved by its own requester
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE promo_budget_requests SET approved_by = requested_by WHERE campaign_id = :c"),
                         {"c": campaign})
    assert info.value.orig.diag.constraint_name == "ck_promo_budget_requests_approver"


# --- activation and versions (Q105, Q111, QA #22) --------------------------------------------------------------


def test_activation_refuses_unset_parameters_in_service_and_database(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(activate=False, terms=synthetic_terms(margin_policy=None, approval_reference=None))
    with promo.session() as s:
        version_id = s.execute(text("SELECT id FROM promo_campaign_versions WHERE campaign_id = :c"), {"c": campaign}).scalar_one()
        with pytest.raises(DomainError) as exc:
            service.activate_campaign(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS,
                                      campaign_id=campaign, version_id=version_id, expected_version=1, reason="t")
        assert exc.value.code is ErrorCode.PROMO_PARAMETERS_UNSET
    with pytest.raises(DBAPIError) as info:
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE promo_campaigns SET status = 'active', active_version_id = :v WHERE id = :c"),
                         {"v": version_id, "c": campaign})
    assert info.value.orig.diag.constraint_name == "promo_activation_incomplete"


def test_zero_margin_is_never_stored(promo) -> None:  # noqa: ANN001
    from dataclasses import replace

    campaign = promo.campaign(activate=False)
    with promo.session() as s:
        with pytest.raises(DBAPIError) as info:
            service.add_campaign_version(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS, campaign_id=campaign,
                                         terms=synthetic_terms(margin_policy=replace(SYNTH_POLICY, min_margin_minor=0)))
        assert info.value.orig.diag.constraint_name == "ck_promo_campaign_versions_min_margin"


def test_new_version_never_changes_existing_promises(promo) -> None:  # noqa: ANN001
    """QA #22: terms are versioned; an enrollment keeps the version and amounts it joined under."""
    campaign = promo.campaign()
    obligations = promo.promise(campaign)
    with promo.session() as s:
        worse = service.add_campaign_version(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS,
                                             campaign_id=campaign, terms=synthetic_terms(referee_reward_minor=1))
        c = s.execute(text("SELECT version FROM promo_campaigns WHERE id = :c"), {"c": campaign}).scalar_one()
        service.activate_campaign(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS, campaign_id=campaign,
                                  version_id=worse.id, expected_version=c, reason="synthetic new terms")
        s.commit()
    with promo.pg_db.engine.connect() as conn:
        rows = conn.execute(text("SELECT o.amount_minor, v.version_no FROM promo_obligations o "
                                 "JOIN promo_campaign_versions v ON v.id = o.campaign_version_id WHERE o.id = ANY(:ids) "
                                 "ORDER BY o.id"), {"ids": obligations}).all()
    assert [tuple(r) for r in rows] == [(300_000, 1), (REFEREE_REWARD, 1)]
    with pytest.raises(DBAPIError) as info:
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE promo_obligations SET amount_minor = 1 WHERE id = :o"), {"o": obligations[1]})
    assert info.value.orig.diag.constraint_name == "promo_invalid_transition"


def test_driver_referral_campaign_only_with_credit_both_sides(promo) -> None:  # noqa: ANN001
    campaign = promo.campaign(kind=PromoCampaignKind.REFERRAL_DRIVER_DRIVER, activate=False,
                              terms=synthetic_terms(milestone_thresholds=(5, 10), min_distinct_clients=3))
    with promo.session() as s:
        version_id = s.execute(text("SELECT id FROM promo_campaign_versions WHERE campaign_id = :c"), {"c": campaign}).scalar_one()
        with pytest.raises(DomainError) as exc:  # passenger bonus is not the driver->driver instrument
            service.activate_campaign(s, actor_user_id=promo.super_id, actor_capabilities=SUPER_CAPS,
                                      campaign_id=campaign, version_id=version_id, expected_version=1, reason="t")
        assert exc.value.code is ErrorCode.VALIDATION_ERROR
    ok = promo.campaign(kind=PromoCampaignKind.REFERRAL_DRIVER_DRIVER, terms=synthetic_terms(
        milestone_thresholds=(5, 10), min_distinct_clients=3,
        referrer_instrument=PromoInstrument.DRIVER_CREDIT, referee_instrument=PromoInstrument.DRIVER_CREDIT))
    assert promo.budget(ok).allocated_minor > 0


# --- reconciliation and the real money ledger ------------------------------------------------------------------


def test_promotions_never_touch_the_real_money_ledger(promo, bookings) -> None:  # noqa: ANN001
    """A1.9 / Q55: promo work writes no ledger_transactions, wallet_holds or ledger_account_balances rows."""
    with promo.pg_db.engine.connect() as conn:
        before = conn.execute(text(
            "SELECT (SELECT count(*) FROM ledger_transactions), (SELECT count(*) FROM wallet_holds), "
            "(SELECT count(*) FROM ledger_account_balances)")).one()
    campaign = promo.campaign()
    booking = bookings.new(driver_user_id=bookings.world.driver_id)
    lot_id = promo.granted_lot(campaign)
    with promo.session() as s:
        redemption = service.reserve_lot(s, lot_id=lot_id, booking_id=booking, amount_minor=REFEREE_REWARD)
        service.consume_redemption(s, redemption_id=redemption.id)
        s.commit()
    with promo.pg_db.engine.connect() as conn:
        after = conn.execute(text(
            "SELECT (SELECT count(*) FROM ledger_transactions), (SELECT count(*) FROM wallet_holds), "
            "(SELECT count(*) FROM ledger_account_balances)")).one()
    assert tuple(before) == tuple(after)
    assert promo.issues() == []


def test_forged_budget_cache_is_detected_at_commit(promo) -> None:  # noqa: ANN001
    """Even with the writer guard bypassed (session_replication_role), the deferred check refuses the commit."""
    campaign = promo.campaign()
    with pytest.raises(DBAPIError) as info:
        with promo.pg_db.engine.begin() as conn:
            conn.execute(text("SET LOCAL session_replication_role = replica"))
            conn.execute(text("UPDATE promo_budgets SET allocated_minor = allocated_minor + 1 WHERE campaign_id = :c"),
                         {"c": campaign})
            conn.execute(text("SET LOCAL session_replication_role = origin"))
            conn.execute(text(
                "INSERT INTO promo_ledger_transactions (public_id, campaign_id, kind, amount_minor, reference_key, "
                "actor_user_id, reason) VALUES (gen_random_uuid(), :c, 'allocate', 1, 'forge-check', :u, 'raw')"),
                {"c": campaign, "u": promo.finance_id})
    assert info.value.orig.diag.constraint_name == "promo_budget_cache_mismatch"
