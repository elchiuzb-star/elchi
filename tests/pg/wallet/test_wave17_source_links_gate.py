"""Wave 1.7 on PostgreSQL: Q55 ledger source links, Q56 Q48 gate, L1 marker split, Q57 notices JSON."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.platform import service as platform_service
from app.modules.platform.service import DeploymentEnvironment, q48_gate_status
from app.modules.wallet import service
from tests.pg.wallet.conftest import FINANCE_CAPS, SUPER_CAPS, as_role, fund_wallet, wallet_row

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[3]
B = 10_000_000
BIG = service.TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1


@pytest.fixture
def app_env(monkeypatch):
    def set_env(env: DeploymentEnvironment):
        monkeypatch.setattr(service, "app_environment", lambda: env)
        monkeypatch.setattr(platform_service, "app_environment", lambda: env)

    return set_env


def _migration_0052():
    path = REPO_ROOT / "alembic" / "versions" / "20260915_0052_wallet_ledger_source_links.py"
    spec = importlib.util.spec_from_file_location("a3_migration_0052", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_topup_posting(conn, wallet_id, amount, *, source_type=None, source_id=None, key=None):
    """A balanced cash -> driver credit that also moves the wallet cache (passes every pre-Q55 check)."""
    tx = conn.execute(text(
        "INSERT INTO ledger_transactions (public_id, reference_kind, reference_key, description, wallet_id, "
        "source_type, source_id) VALUES (:p, 'topup', :k, 'forged', :w, :st, :sid) RETURNING id"),
        {"p": uuid.uuid4(), "k": key or f"forged-{uuid.uuid4().hex}", "w": wallet_id, "st": source_type,
         "sid": source_id}).scalar()
    conn.execute(text(
        "INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_minor) "
        "SELECT :t, (SELECT id FROM ledger_accounts WHERE code = 'cash_bank'), 'debit', :a "
        "UNION ALL SELECT :t, ledger_account_id, 'credit', :a FROM wallet_accounts WHERE id = :w"),
        {"t": tx, "a": amount, "w": wallet_id})
    conn.execute(text("UPDATE wallet_accounts SET posted_balance_minor = posted_balance_minor + :a WHERE id = :w"),
                 {"a": amount, "w": wallet_id})
    return tx


def _wallet_id(pg_db, driver):
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, driver)
        s.commit()
        return wallet.id


# --- Q55 forgeries ------------------------------------------------------------------------------------


def test_q55_owner_raw_posting_without_source_is_refused_at_commit(pg_db, people):
    wallet_id = _wallet_id(pg_db, people["driver"])
    with pytest.raises(DBAPIError, match="LEDGER_SOURCE_INVALID.*source_missing"):
        with pg_db.engine.begin() as conn:
            _raw_topup_posting(conn, wallet_id, 5_000_000)
    with pg_db.session() as s:
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == 0


def test_q55_app_role_raw_posting_without_source_is_refused_at_commit(pg_db, people, app_role):
    wallet_id = _wallet_id(pg_db, people["driver"])
    with pytest.raises(DBAPIError, match="LEDGER_SOURCE_INVALID"):
        with pg_db.engine.begin() as conn:
            as_role(conn, app_role)
            _raw_topup_posting(conn, wallet_id, 5_000_000)


def test_q55_pending_topup_or_inserted_approved_topup_is_not_a_source(pg_db, people, app_role):
    with pg_db.session() as s:
        topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=B, method="bank_transfer")
        s.commit()
        wallet_id, topup_id = topup.wallet_id, topup.id
    with pytest.raises(DBAPIError, match="topup_not_approved_for_transaction"):
        with pg_db.engine.begin() as conn:
            _raw_topup_posting(conn, wallet_id, B, source_type="topup_request", source_id=topup_id)
    with pytest.raises(DBAPIError, match="must be created pending"):
        with pg_db.engine.begin() as conn:
            as_role(conn, app_role)
            conn.execute(text(
                "INSERT INTO topup_requests (public_id, driver_user_id, wallet_id, amount_minor, method, status, "
                "source_type, source_reference, received_amount_minor, first_approver_id) "
                "VALUES (:p, :d, :w, 1, 'bank_transfer', 'approved', 'bank_statement', 'X', 1, :a)"),
                {"p": uuid.uuid4(), "d": people["driver"], "w": wallet_id, "a": people["super"]})


def test_q55_mismatched_amount_forgery_is_refused(pg_db, people):
    with pg_db.session() as s:
        topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=1_000, method="bank_transfer")
        s.commit()
        wallet_id, topup_id = topup.wallet_id, topup.id
    with pytest.raises(DBAPIError, match="amount_mismatch"):
        with pg_db.engine.begin() as conn:
            tx = _raw_topup_posting(conn, wallet_id, 5_000_000, source_type="topup_request", source_id=topup_id)
            conn.execute(text(
                "UPDATE topup_requests SET status = 'approved', source_type = 'bank_statement', source_reference = :r, "
                "received_amount_minor = 1000, received_at = now(), first_approver_id = :a, ledger_transaction_id = :t, "
                "decided_at = now(), version = version + 1 WHERE id = :id"),
                {"r": f"STMT-{uuid.uuid4().hex}", "a": people["super"], "t": tx, "id": topup_id})


def test_q55_entries_appended_to_a_legitimate_posting_are_refused(pg_db, people):
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        s.commit()
        row = wallet_row(s, people["driver"])
        tx_id = s.execute(text("SELECT id FROM ledger_transactions WHERE reference_kind = 'topup'")).scalar()
    with pytest.raises(DBAPIError, match="amount_mismatch"):
        with pg_db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_minor) "
                "SELECT :t, (SELECT id FROM ledger_accounts WHERE code = 'cash_bank'), 'debit', 1000 "
                "UNION ALL SELECT :t, ledger_account_id, 'credit', 1000 FROM wallet_accounts WHERE id = :w"),
                {"t": tx_id, "w": row["id"]})
            conn.execute(text("UPDATE wallet_accounts SET posted_balance_minor = posted_balance_minor + 1000 WHERE id = :w"),
                         {"w": row["id"]})


# --- Q55 legitimate flows, reconciliation, backfill -----------------------------------------------------


def _legit_flows(pg_db, people, bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        service.hold_fee(s, booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                         total_minor=40_000_000, fee_bps=1500, wallet_required=True)
        service.capture_fee(s, booking_id=booking)
        service.reverse_fee(s, booking_id=booking, amount_minor=100, actor_user_id=people["super"],
                            actor_capabilities=SUPER_CAPS, reason="dispute")
        wallet = service.get_or_create_wallet(s, people["driver"])
        service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                   wallet_id=wallet.id, direction="credit", amount_minor=50, reason="goodwill")
        big = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                         wallet_id=wallet.id, direction="credit", amount_minor=BIG, reason="bank fix")
        s.commit()
        service.approve_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                   adjustment_request_id=big.request.id, expected_version=1)
        s.commit()


def test_q55_legitimate_flows_post_with_sources_and_reconcile_clean(pg_db, people, bookings):
    _legit_flows(pg_db, people, bookings)
    with pg_db.session() as s:
        sources = s.execute(text("SELECT reference_kind, source_type FROM ledger_transactions ORDER BY id")).all()
        report = service.run_reconciliation(s)
        s.commit()
    assert [tuple(r) for r in sources] == [
        ("topup", "topup_request"), ("commission_capture", "wallet_hold"), ("commission_reversal", "wallet_hold"),
        ("adjustment", "ledger_adjustment_request"), ("adjustment", "ledger_adjustment_request"),
    ]
    assert report.orphan_postings == [] and report.mismatch_count == 0


def test_q55_backfill_links_existing_postings_and_fails_loudly_on_orphans(pg_db, people, bookings):
    _legit_flows(pg_db, people, bookings)
    with pg_db.engine.connect() as conn:
        expected = conn.execute(text("SELECT id, source_type, source_id FROM ledger_transactions ORDER BY id")).all()
    with pg_db.engine.begin() as conn:  # simulate pre-0052 rows
        conn.execute(text("ALTER TABLE ledger_transactions DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE ledger_transactions SET source_type = NULL, source_id = NULL"))
        conn.execute(text("ALTER TABLE ledger_transactions ENABLE TRIGGER USER"))
    module = _migration_0052()
    for _ in range(2):
        with pg_db.engine.begin() as conn:
            module.backfill_source_links(conn)
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT id, source_type, source_id FROM ledger_transactions ORDER BY id")).all() == expected
    with pg_db.engine.begin() as conn:  # an orphan posting between system accounts slipped in with the link off
        conn.execute(text("ALTER TABLE ledger_transactions DISABLE TRIGGER trg_ledger_transactions_source_link"))
        conn.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER trg_ledger_entries_source_link"))
        tx = conn.execute(text(
            "INSERT INTO ledger_transactions (public_id, reference_kind, reference_key, description) "
            "VALUES (:p, 'adjustment', 'orphan-1', 'orphan') RETURNING id"), {"p": uuid.uuid4()}).scalar()
        conn.execute(text(
            "INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_minor) "
            "SELECT :t, (SELECT id FROM ledger_accounts WHERE code = 'cash_bank'), 'debit', 7 "
            "UNION ALL SELECT :t, (SELECT id FROM ledger_accounts WHERE code = 'manual_adjustments'), 'credit', 7"),
            {"t": tx})
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))  # flush pending balance checks before ALTER TABLE
        conn.execute(text("ALTER TABLE ledger_entries ENABLE TRIGGER trg_ledger_entries_source_link"))
        conn.execute(text("ALTER TABLE ledger_transactions ENABLE TRIGGER trg_ledger_transactions_source_link"))
    with pg_db.session() as s:
        report = service.run_reconciliation(s)
        s.commit()
        assert [o["problem"] for o in report.orphan_postings] == ["source_missing"] and report.mismatch_count == 1
    with pytest.raises(RuntimeError, match="cannot be linked"):
        with pg_db.engine.begin() as conn:
            module.backfill_source_links(conn)


# --- Q56 gate -----------------------------------------------------------------------------------------


def test_q56_gate_checks_role_guard_links_and_seed(pg_db, people, app_role):
    with pg_db.session() as s:
        superuser = q48_gate_status(s)
        assert not superuser.ok
        # The superuser test login also owns every object (Q71).
        assert set(superuser.failed) == {"app_role_not_superuser", "app_role_cannot_write_balances", "seed_rate_confirmed",
                                         "app_role_owns_no_objects"}
        seed = service.current_global_standard(s)
        service.confirm_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=seed.id,
                               expected_version=seed.version, reason="rate reviewed")
        s.commit()
        as_role(s, app_role)
        gate = q48_gate_status(s)
        assert gate.ok, gate.as_dict()
        assert [c.name for c in gate.checks] == ["app_role_not_superuser", "app_role_cannot_write_balances",
                                                 "balance_guard_uses_trigger_depth", "ledger_source_links_enforced",
                                                 "seed_rate_confirmed", "approver_guard_enforced",
                                                 "app_role_owns_no_objects"]
        assert s.execute(text("SELECT public.q48_gate_ok(), public.platform_q48_gate_passed()")).one() == (True, True)
        json.dumps(gate.as_dict())
    with pg_db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER trg_ledger_entries_source_link"))
    try:
        with pg_db.session() as s:
            as_role(s, app_role)
            assert q48_gate_status(s).failed == ["ledger_source_links_enforced"]
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE ledger_entries ENABLE TRIGGER trg_ledger_entries_source_link"))


def test_q56_production_gate_blocks_new_holds_but_not_obligations(pg_db, people, app_env, app_role, bookings):
    held, refused = bookings.ids(2, driver_user_id=people["driver"])
    with pg_db.session() as s:  # non-production: an existing hold
        fund_wallet(s, people["driver"], B, people["super"])
        service.hold_fee(s, booking_id=held, booking_public_id=f"bkg_{held}", driver_user_id=people["driver"],
                         total_minor=10_000_000, fee_bps=1500, wallet_required=True)
        s.commit()
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 't' WHERE id = 1"))
    app_env(DeploymentEnvironment.PRODUCTION)
    with pg_db.session() as s:
        as_role(s, app_role)  # seed unconfirmed -> gate fails
        report = service.assert_production_invariants(s)
        assert report.failed == ["q48_money_gate"]
        gate_check = next(c for c in report.as_dict()["checks"] if c["name"] == "q48_money_gate")
        assert gate_check["detail"] == {"failed": ["seed_rate_confirmed"]}
        seed = service.current_global_standard(s)
        with pytest.raises(DomainError) as exc:
            service.hold_fee(s, booking_id=refused, booking_public_id=f"bkg_{refused}", driver_user_id=people["driver"],
                             total_minor=1_000_000, fee_bps=1500, wallet_required=True, fee_policy_id=seed.id)
        assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED
        assert exc.value.details == {"failed": ["q48_money_gate"]}
        s.rollback()
        as_role(s, app_role)
        assert not service.capture_fee(s, booking_id=held).already_captured  # obligation still works
        s.commit()


# --- L1, Q57 --------------------------------------------------------------------------------------------


def test_l1_marker_switch_refuses_when_flag_columns_cannot_be_verified(pg_db):
    with pg_db.engine.connect() as conn:
        present = conn.execute(text("SELECT to_regclass('public.feature_flag_values') IS NOT NULL")).scalar()
    if not present:
        pytest.skip("feature_flag_values (A2) not present")
    with pg_db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE feature_flag_values RENAME COLUMN approval_reference TO approval_reference_tmp"))
    try:
        with pytest.raises(DBAPIError, match="cannot verify passenger/card approval references"):
            with pg_db.engine.begin() as conn:
                conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 't' WHERE id = 1"))
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE feature_flag_values RENAME COLUMN approval_reference_tmp TO approval_reference"))


def test_q57_invariant_report_with_notices_is_json_serialisable(pg_db):
    with pg_db.session() as s:
        report = service.assert_production_invariants(s)
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["notices"] == [{"name": "unconfirmed_seed_policy_active",
                                   "detail": {"blocks_production_quotes_and_holds": False}}]
    assert json.dumps([n.as_dict() for n in report.notices])
    assert report.ok and utc_now()
