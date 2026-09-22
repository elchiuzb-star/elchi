"""Wallet money invariants on PostgreSQL: AC19, AC20, AC23, AC24, AC25, D4, D10."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.contracts.enums import CommissionStatus
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.wallet import service
from tests.pg.harness import run_concurrently
from tests.pg.wallet.conftest import ADMIN_CAPS, FINANCE_CAPS, SUPER_CAPS, error_code, fund_wallet, wallet_row

pytestmark = pytest.mark.pg

B = 10_000_000  # 100 000 so'm in tiyin


def _hold(session, driver, booking_id, total, bps=1500, **kw):
    return service.hold_fee(
        session, booking_id=booking_id, booking_public_id=f"bkg_test{booking_id}", driver_user_id=driver,
        total_minor=total, fee_bps=bps, wallet_required=True, **kw,
    )


def test_ac19_hold_reduces_available_and_second_hold_rejected(pg_db, people, bookings):
    b1, b2 = bookings.ids(2, driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        result = _hold(s, people["driver"], b1, 40_000_000)  # 15% of 400 000 so'm = 60 000 so'm
        s.commit()
        assert result.amount_minor == 6_000_000
        snap = service.get_wallet(s, people["driver"])
        assert (snap.posted_balance_minor, snap.held_minor, snap.available_minor) == (B, 6_000_000, 4_000_000)
        with pytest.raises(DomainError) as exc:
            _hold(s, people["driver"], b2, 50_000_000, bps=1000)  # 50 000 so'm
        assert exc.value.code is ErrorCode.INSUFFICIENT_COMMISSION_BALANCE
        assert exc.value.details is None  # no balance figures leak to a client caller (Q16)
        s.rollback()
        assert wallet_row(s, people["driver"])["held_minor"] == 6_000_000


def test_ac19_parallel_holds_never_make_available_negative(pg_db, people, bookings):
    booking_ids = bookings.ids(20, driver_user_id=people["driver"])  # created before the workers start
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        s.commit()
    amounts = [6_000_000] + [5_000_000] * 19  # totals at 1000 bps

    def worker(i, session):
        res = _hold(session, people["driver"], booking_ids[i], amounts[i] * 10, bps=1000)
        session.commit()
        return res.amount_minor

    report = run_concurrently(20, worker, engine=pg_db.engine)
    assert all(error_code(r) is ErrorCode.INSUFFICIENT_COMMISSION_BALANCE for r in report.failures), report.failures
    won = sum(report.values())
    with pg_db.session() as s:
        row = wallet_row(s, people["driver"])
        holds = s.execute(text("SELECT count(*), coalesce(sum(amount_minor),0) FROM wallet_holds WHERE status='active'")).one()
    assert won <= B and row["held_minor"] == won == holds[1]
    assert row["posted_balance_minor"] - row["held_minor"] >= 0
    assert holds[0] == len(report.successes) >= 1
    # Greedy bound: any accepted set leaves no room for another 5 000 000 hold.
    assert B - won < 5_000_000 or len(report.successes) == 20


def test_ac20_parallel_capture_debits_once(pg_db, people, bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], booking, 40_000_000)
        s.commit()

    def worker(i, session):
        res = service.capture_fee(session, booking_id=booking)
        session.commit()
        return res.already_captured

    report = run_concurrently(10, worker, engine=pg_db.engine)
    assert not report.failures, report.failures
    assert sorted(report.values()) == [False] + [True] * 9
    with pg_db.session() as s:
        row = wallet_row(s, people["driver"])
        captures = s.execute(text("SELECT count(*) FROM ledger_transactions WHERE reference_kind='commission_capture'")).scalar()
        hold = s.execute(text("SELECT status, captured_minor FROM wallet_holds WHERE booking_id=:b"), {"b": booking}).one()
    assert captures == 1
    assert (row["posted_balance_minor"], row["held_minor"]) == (B - 6_000_000, 0)
    assert tuple(hold) == ("captured", 6_000_000)


def test_capture_after_release_is_invalid_and_release_is_idempotent(pg_db, people, bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], booking, 40_000_000)
        assert service.release_fee(s, booking_id=booking).changed
        assert not service.release_fee(s, booking_id=booking).changed
        with pytest.raises(DomainError) as exc:
            service.capture_fee(s, booking_id=booking)
        assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
        s.commit()
        assert wallet_row(s, people["driver"])["held_minor"] == 0


def test_ac23_parallel_approve_same_topup_credits_once(pg_db, people):
    with pg_db.session() as s:
        topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=B, method="bank_transfer")
        s.commit()
        topup_id = topup.id

    def worker(i, session):
        service.approve_topup(
            session, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, topup_id=topup_id,
            expected_version=1, source_type="bank_statement", source_reference="STMT-2026-0001",
            received_amount_minor=B, received_at=utc_now(),
        )
        session.commit()

    report = run_concurrently(10, worker, engine=pg_db.engine)
    assert len(report.successes) == 1
    assert {error_code(r) for r in report.failures} == {ErrorCode.VERSION_CONFLICT}
    with pg_db.session() as s:
        assert s.execute(text("SELECT count(*) FROM ledger_transactions WHERE reference_kind='topup'")).scalar() == 1
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == B


def test_ac23_same_source_reference_on_two_topups_credits_once(pg_db, people):
    with pg_db.session() as s:
        ids = [
            service.create_topup(s, driver_user_id=people[d], amount_minor=B, method="bank_transfer").id
            for d in ("driver", "driver2")
        ]
        s.commit()

    def worker(i, session):
        service.approve_topup(
            session, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, topup_id=ids[i],
            expected_version=1, source_type="bank_statement", source_reference="STMT-SHARED",
            received_amount_minor=B, received_at=utc_now(),
        )
        session.commit()

    report = run_concurrently(2, worker, engine=pg_db.engine)
    assert len(report.successes) == 1
    assert [error_code(r) for r in report.failures] == [ErrorCode.TOPUP_REFERENCE_DUPLICATE]
    with pg_db.session() as s:
        assert s.execute(text("SELECT count(*) FROM ledger_transactions WHERE reference_kind='topup'")).scalar() == 1
        total = s.execute(text("SELECT sum(posted_balance_minor) FROM wallet_accounts")).scalar()
    assert total == B


def test_ac24_pending_topup_does_not_change_balance(pg_db, people):
    with pg_db.session() as s:
        service.create_topup(s, driver_user_id=people["driver"], amount_minor=B, method="bank_transfer",
                             evidence_file_id="screenshot-1")
        s.commit()
        snap = service.get_wallet(s, people["driver"])
        assert (snap.posted_balance_minor, snap.held_minor, snap.available_minor) == (0, 0, 0)
        assert snap.pending_topups_minor == B
        assert s.execute(text("SELECT count(*) FROM ledger_entries")).scalar() == 0


def test_large_topup_needs_two_different_approvers(pg_db, people):
    big = service.LARGE_AMOUNT_THRESHOLD_MINOR + 1
    with pg_db.session() as s:
        topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=big, method="cash_desk")
        kwargs = dict(actor_capabilities=SUPER_CAPS, topup_id=topup.id, source_type="cashier_receipt",
                      source_reference="RCPT-9", received_amount_minor=big, received_at=utc_now())
        first = service.approve_topup(s, actor_user_id=people["super"], expected_version=1, **kwargs)
        assert first.status == "awaiting_second_approval"
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == 0
        with pytest.raises(DomainError) as exc:
            service.approve_topup(s, actor_user_id=people["super"], expected_version=2, **kwargs)
        assert exc.value.code is ErrorCode.SECOND_APPROVER_REQUIRED
        done = service.approve_topup(s, actor_user_id=people["super2"], expected_version=2, **kwargs)
        s.commit()
        assert done.status == "approved" and done.second_approver_id == people["super2"]
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == big


def test_ac25_unbalanced_posting_rolls_back(pg_db, people):
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        s.commit()
        with pytest.raises(DomainError) as exc:
            service._post_transaction(s, reference_kind="adjustment", reference_key="x", description="bad",
                                      entries=[(1, "debit", 5), (2, "credit", 4)], wallet_id=None,
                                      source_type="ledger_adjustment_request", source_id=1)
        assert exc.value.code is ErrorCode.LEDGER_UNBALANCED
    with pytest.raises(DBAPIError, match="LEDGER_UNBALANCED"):
        with pg_db.engine.begin() as conn:
            tx = conn.execute(text(
                "INSERT INTO ledger_transactions (public_id, reference_kind, reference_key, description) "
                "VALUES (:p, 'adjustment', 'raw-1', 'raw') RETURNING id"), {"p": uuid.uuid4()}).scalar()
            conn.execute(text("INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_minor) "
                              "VALUES (:t, 1, 'debit', 100), (:t, 3, 'credit', 99)"), {"t": tx})
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM ledger_transactions WHERE reference_key='raw-1'")).scalar() == 0


def test_ac25_ledger_is_immutable_and_cache_cannot_drift(pg_db, people):
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        s.commit()
    for statement in ("UPDATE ledger_entries SET amount_minor = amount_minor + 1",
                      "DELETE FROM ledger_entries",
                      "UPDATE ledger_transactions SET description = 'tampered'",
                      "DELETE FROM ledger_transactions",
                      "TRUNCATE ledger_entries CASCADE"):
        with pytest.raises(DBAPIError, match="immutable"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement))
    with pytest.raises(DBAPIError, match="differs from ledger"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE wallet_accounts SET posted_balance_minor = posted_balance_minor + 1"))
    with pg_db.session() as s:
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == B


def test_ac25_d4_partial_reversals_create_new_entries_and_cap_at_captured(pg_db, people, bookings):
    b = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], b, 40_000_000)
        capture = service.capture_fee(s, booking_id=b)
        s.commit()
        capture_entries = s.execute(text("SELECT id, amount_minor FROM ledger_entries WHERE transaction_id=:t ORDER BY id"),
                                    {"t": capture.transaction_id}).all()
        r1 = service.reverse_fee(s, booking_id=b, amount_minor=2_000_000, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, reason="dispute 1")
        r2 = service.reverse_fee(s, booking_id=b, amount_minor=3_000_000, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, reason="dispute 2")
        s.commit()
        assert r1.commission_status is CommissionStatus.PARTIALLY_REVERSED
        assert (r2.reversed_minor, r2.remaining_minor) == (5_000_000, 1_000_000)
        with pytest.raises(DomainError) as exc:
            service.reverse_fee(s, booking_id=b, amount_minor=2_000_000, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, reason="too much")
        assert exc.value.code is ErrorCode.REVERSAL_EXCEEDS_CAPTURED
        s.rollback()
        r3 = service.reverse_fee(s, booking_id=b, amount_minor=1_000_000, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, reason="rest")
        s.commit()
        assert r3.commission_status is CommissionStatus.REVERSED
        links = s.execute(text("SELECT reference_key FROM ledger_transactions WHERE reversal_of_id=:t ORDER BY id"),
                          {"t": capture.transaction_id}).scalars().all()
        assert links == [f"commission:reversal:{b}:{n}" for n in (1, 2, 3)]
        assert s.execute(text("SELECT id, amount_minor FROM ledger_entries WHERE transaction_id=:t ORDER BY id"),
                         {"t": capture.transaction_id}).all() == capture_entries
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == B


def test_d4_concurrent_partial_reversals_never_exceed_captured(pg_db, people, bookings):
    b = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], b, 40_000_000)
        service.capture_fee(s, booking_id=b)
        s.commit()

    def worker(i, session):
        service.reverse_fee(session, booking_id=b, amount_minor=1_000_000, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, reason=f"r{i}")
        session.commit()

    report = run_concurrently(10, worker, engine=pg_db.engine)
    assert len(report.successes) == 6
    assert {error_code(r) for r in report.failures} == {ErrorCode.REVERSAL_EXCEEDS_CAPTURED}
    with pg_db.session() as s:
        hold = s.execute(text("SELECT captured_minor, reversed_minor FROM wallet_holds WHERE booking_id=:b"), {"b": b}).one()
        assert tuple(hold) == (6_000_000, 6_000_000)
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == B


@pytest.mark.parametrize("round_", range(3))
def test_d10_adjust_hold_concurrent_with_other_hold_same_wallet(pg_db, people, round_, bookings):
    amended, other = bookings.ids(2, driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], amended, 40_000_000)  # 6 000 000 held, 4 000 000 available
        s.commit()

    def worker(i, session):
        if i == 0:
            res = service.adjust_hold(session, booking_id=amended, new_total_minor=60_000_000, fee_bps=1500, wallet_required=True)
        else:
            res = _hold(session, people["driver"], other, 20_000_000)  # 3 000 000
        session.commit()
        return (i, res.delta_minor)

    report = run_concurrently(2, worker, engine=pg_db.engine)
    assert len(report.successes) == 1
    assert [error_code(r) for r in report.failures] == [ErrorCode.INSUFFICIENT_COMMISSION_BALANCE]
    with pg_db.session() as s:
        row = wallet_row(s, people["driver"])
        assert row["held_minor"] == 9_000_000
        assert row["posted_balance_minor"] - row["held_minor"] >= 0
        assert s.execute(text("SELECT count(*) FROM wallet_holds WHERE booking_id=:b"), {"b": amended}).scalar() == 1


def test_d10_adjust_hold_keeps_snapshot_bps_and_single_hold(pg_db, people, bookings):
    b = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], b, 40_000_000)
        down = service.adjust_hold(s, booking_id=b, new_total_minor=20_000_000, fee_bps=1500)
        s.commit()
        assert (down.amount_minor, down.delta_minor) == (3_000_000, -3_000_000)
        with pytest.raises(DomainError) as exc:
            service.adjust_hold(s, booking_id=b, new_total_minor=20_000_000, fee_bps=1000)
        assert exc.value.code is ErrorCode.AMENDMENT_CONFLICT
        s.rollback()
        with pytest.raises(DomainError) as exc:
            _hold(s, people["driver"], b, 80_000_000)
        assert exc.value.code is ErrorCode.AMENDMENT_CONFLICT
        s.rollback()
    with pytest.raises(DBAPIError, match="uq_wallet_holds_booking_charge"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("INSERT INTO wallet_holds (wallet_id, booking_id, charge_kind, fee_bps, amount_minor, status) "
                              "SELECT id, :b, 'commission', 1500, 1, 'active' FROM wallet_accounts LIMIT 1"), {"b": b})


def test_exempt_snapshot_never_creates_hold(pg_db, people, bookings):
    b = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        with pytest.raises(ValueError):
            _hold(s, people["driver"], b, 40_000_000, bps=0)
        assert s.execute(text("SELECT count(*) FROM wallet_holds")).scalar() == 0


def test_non_production_wallet_required_false_still_holds_real_fee(pg_db, people, bookings):
    b1 = bookings.new(driver_user_id=people["driver"])
    b2 = bookings.new(driver_user_id=people["driver2"])
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, people["driver"])
        service.set_test_overdraft_allowed(s, wallet.id, True, actor_user_id=people["super"])
        res = service.hold_fee(s, booking_id=b1, booking_public_id=f"bkg_t{b1}", driver_user_id=people["driver"],
                               total_minor=40_000_000, fee_bps=1500, wallet_required=False)
        s.commit()
        assert res.amount_minor == 6_000_000
        row = wallet_row(s, people["driver"])
        assert (row["posted_balance_minor"], row["held_minor"]) == (0, 6_000_000)
    with pg_db.session() as s:
        with pytest.raises(DomainError) as exc:  # overdraft flag missing -> still refused
            service.hold_fee(s, booking_id=b2, booking_public_id=f"bkg_t{b2}", driver_user_id=people["driver2"],
                             total_minor=40_000_000, fee_bps=1500, wallet_required=False)
        assert exc.value.code is ErrorCode.INSUFFICIENT_COMMISSION_BALANCE


def test_large_adjustment_two_person_rule_and_reversal_via_request(pg_db, people):
    big = service.LARGE_AMOUNT_THRESHOLD_MINOR + 100
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        wallet = service.get_or_create_wallet(s, people["driver"])
        small = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                           wallet_id=wallet.id, direction="credit", amount_minor=100, reason="goodwill")
        assert small.status == "posted" and small.transaction is not None
        pending = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                             wallet_id=wallet.id, direction="credit", amount_minor=big, reason="bank fix")
        assert pending.status == "pending_second_approval" and pending.transaction is None
        s.commit()
        with pytest.raises(DomainError) as exc:
            service.approve_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                       adjustment_request_id=pending.request.id, expected_version=1)
        assert exc.value.code is ErrorCode.SECOND_APPROVER_REQUIRED
        s.rollback()
        done = service.approve_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                          adjustment_request_id=pending.request.id, expected_version=1)
        s.commit()
        assert done.transaction.second_approver_id == people["super"]
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == B + 100 + big


def test_reconcile_clean_after_operations(pg_db, people, bookings):
    b = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], b, 40_000_000)
        service.capture_fee(s, booking_id=b)
        service.reverse_fee(s, booking_id=b, amount_minor=1, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, reason="rounding")
        report = service.reconcile(s)
        again = service.reconcile(s)
        s.commit()
        assert report.mismatches == [] and report.unbalanced_transactions == [] and report.mismatch_count == 0
        assert again.wallets_checked == report.wallets_checked == 1
        assert s.execute(text("SELECT count(*) FROM reconciliation_runs")).scalar() == 1


# --- wave 1.5 ---------------------------------------------------------------------------------------------

THRESHOLD = service.TWO_PERSON_APPROVAL_THRESHOLD_MINOR


def _fund_large(s, driver, approver, total):
    """Real top-ups in threshold-sized chunks (each needs a single approval)."""
    remaining = total
    while remaining > 0:
        chunk = min(remaining, THRESHOLD)
        fund_wallet(s, driver, chunk, approver)
        remaining -= chunk


def test_br5_reverse_fee_requires_finance_capability_and_eligible_second_approver(pg_db, people, bookings):
    b = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        _fund_large(s, people["driver"], people["super"], 200_000_000)
        _hold(s, people["driver"], b, 1_000_000_000)  # 150 000 000 commission
        service.capture_fee(s, booking_id=b)
        s.commit()
        big = THRESHOLD + 1
        refused = [
            (dict(actor_capabilities=ADMIN_CAPS, amount_minor=1), ErrorCode.FORBIDDEN),
            (dict(actor_capabilities=SUPER_CAPS, amount_minor=big), ErrorCode.SECOND_APPROVER_REQUIRED),
            (dict(actor_capabilities=SUPER_CAPS, amount_minor=big, second_approver_id=people["super"]),
             ErrorCode.SECOND_APPROVER_REQUIRED),  # same person
            (dict(actor_capabilities=SUPER_CAPS, amount_minor=big, second_approver_id=people["admin"]),
             ErrorCode.SECOND_APPROVER_REQUIRED),  # admin lacks finance.adjustment_approve
            (dict(actor_capabilities=SUPER_CAPS, amount_minor=1, second_approver_id=people["admin"]),
             ErrorCode.SECOND_APPROVER_REQUIRED),  # a given approver is always validated
        ]
        for kwargs, code in refused:
            with pytest.raises(DomainError) as exc:
                service.reverse_fee(s, booking_id=b, actor_user_id=people["super"], reason="dispute", **kwargs)
            assert exc.value.code is code, kwargs
            s.rollback()
        done = service.reverse_fee(s, booking_id=b, amount_minor=big, actor_user_id=people["super"],
                                   actor_capabilities=SUPER_CAPS, reason="dispute", second_approver_id=people["super2"])
        s.commit()
        assert done.transaction.second_approver_id == people["super2"]
        assert s.execute(text("SELECT count(*) FROM ledger_transactions WHERE reference_kind='commission_reversal'")).scalar() == 1


def test_br4_reject_adjustment_closes_pending_request_and_stops_blocking_deletion(pg_db, people):
    big = THRESHOLD + 1
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, people["driver2"])
        pending = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                             wallet_id=wallet.id, direction="credit", amount_minor=big, reason="bank fix")
        s.commit()
        assert service.blocking_state_for_user(s, people["driver2"]).blocks_deletion
        with pytest.raises(DomainError) as exc:
            service.reject_adjustment(s, actor_user_id=people["admin"], actor_capabilities=ADMIN_CAPS,
                                      adjustment_request_id=pending.request.id, expected_version=1, reason="no")
        assert exc.value.code is ErrorCode.FORBIDDEN
        s.rollback()
        rejected = service.reject_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                             adjustment_request_id=pending.request.id, expected_version=1,
                                             reason="duplicate request")
        s.commit()
        assert (rejected.status, rejected.rejected_by, rejected.version) == ("rejected", people["super"], 2)
        assert rejected.decided_at is not None
        assert not service.blocking_state_for_user(s, people["driver2"]).blocks_deletion
        for call in (
            lambda: service.approve_adjustment(s, actor_user_id=people["super2"], actor_capabilities=SUPER_CAPS,
                                               adjustment_request_id=pending.request.id, expected_version=2),
            lambda: service.reject_adjustment(s, actor_user_id=people["super2"], actor_capabilities=SUPER_CAPS,
                                              adjustment_request_id=pending.request.id, expected_version=2, reason="again"),
        ):
            with pytest.raises(DomainError) as exc:
                call()
            assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
            s.rollback()
        assert wallet_row(s, people["driver2"])["posted_balance_minor"] == 0
    with pytest.raises(DBAPIError, match="terminal"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE ledger_adjustment_requests SET status = 'pending_second_approval'"))


def test_br10_approve_topup_refuses_deleted_driver(pg_db, people):
    with pg_db.session() as s:
        topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=B, method="bank_transfer")
        s.commit()
        s.execute(text("UPDATE users SET status = 'deleted' WHERE id = :id"), {"id": people["driver"]})
        s.commit()
        with pytest.raises(DomainError) as exc:
            service.approve_topup(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, topup_id=topup.id,
                                  expected_version=1, source_type="bank_statement", source_reference="STMT-DEL",
                                  received_amount_minor=B, received_at=utc_now())
        assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
        assert exc.value.details == {"reason": "driver_account_deleted"}
        s.rollback()
        assert s.execute(text("SELECT count(*) FROM ledger_transactions")).scalar() == 0


def test_br10_blocking_state_lock_serializes_with_topup_approval(pg_db, people):
    with pg_db.session() as s:
        topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=B, method="bank_transfer")
        s.commit()
        topup_id = topup.id
    holder = pg_db.session()
    try:
        state = service.blocking_state_for_user(holder, people["driver"], lock=True)
        assert state.blocks_deletion and state.pending_topups_count == 1
        with pg_db.session() as other:
            other.execute(text("SET LOCAL lock_timeout = '300ms'"))
            with pytest.raises(OperationalError):
                service.approve_topup(other, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                      topup_id=topup_id, expected_version=1, source_type="bank_statement",
                                      source_reference="STMT-LOCK", received_amount_minor=B, received_at=utc_now())
            other.rollback()
    finally:
        holder.rollback()
        holder.close()


def test_br8_running_balance_is_trigger_maintained_and_cannot_drift(pg_db, people, bookings):
    b = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        _hold(s, people["driver"], b, 40_000_000)
        service.capture_fee(s, booking_id=b)
        s.commit()
    driver_balance_sql = (
        "SELECT b.balance_minor FROM ledger_account_balances b "
        "JOIN wallet_accounts w ON w.ledger_account_id = b.account_id WHERE w.driver_user_id = :d"
    )
    with pg_db.engine.connect() as conn:
        assert conn.execute(text(driver_balance_sql), {"d": people["driver"]}).scalar() == B - 6_000_000
        system_rows = conn.execute(text(
            "SELECT count(*) FROM ledger_account_balances b JOIN ledger_accounts a ON a.id = b.account_id "
            "WHERE a.kind <> 'liability'")).scalar()
        assert system_rows == 0  # no hot balance row for commission_revenue / cash accounts
    with pytest.raises(DBAPIError, match="maintained by trigger"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE ledger_account_balances SET balance_minor = balance_minor + 1"))
    with pytest.raises(DBAPIError, match="maintained by trigger"):
        with pg_db.engine.begin() as conn:  # wave 1.6 N1: a session setting no longer opens the guard
            conn.execute(text("SET LOCAL elchi.ledger_balance_writer = 'on'"))
            conn.execute(text("UPDATE ledger_account_balances SET balance_minor = balance_minor + 1"))
    with pg_db.engine.begin() as conn:  # superuser tampering of both caches: only reconciliation can see it
        conn.execute(text("ALTER TABLE wallet_accounts DISABLE TRIGGER ALL"))
        conn.execute(text("ALTER TABLE ledger_account_balances DISABLE TRIGGER ALL"))
        conn.execute(text("UPDATE ledger_account_balances SET balance_minor = balance_minor + 1"))
        conn.execute(text("UPDATE wallet_accounts SET posted_balance_minor = posted_balance_minor + 1"))
        conn.execute(text("ALTER TABLE wallet_accounts ENABLE TRIGGER ALL"))
        conn.execute(text("ALTER TABLE ledger_account_balances ENABLE TRIGGER ALL"))
    with pg_db.session() as s:
        report = service.run_reconciliation(s)
        s.commit()
        assert report.mismatch_count == 1
        assert report.mismatches[0]["running_balance_minor"] == report.mismatches[0]["ledger_minor"] + 1


def test_decision30_split_adjustment_signals(pg_db, people):
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        wallet = service.get_or_create_wallet(s, people["driver"])
        for _ in range(3):
            service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                       wallet_id=wallet.id, direction="credit", amount_minor=40_000_000, reason="split")
        service.request_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                   wallet_id=wallet.id, direction="credit", amount_minor=1_000_000, reason="single")
        s.commit()
        signals = service.split_adjustment_signals(s, since=utc_now() - timedelta(hours=1),
                                                   until=utc_now() + timedelta(minutes=1))
        assert [(x.requested_by, x.count, x.amount_minor) for x in signals] == [(people["finance"], 3, 120_000_000)]
