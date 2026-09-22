"""Wave 1.6 BR re-review on PostgreSQL: N1 balance forgery, N2 search_path, N3/Q49 withdraw,
N5 obligations without a global standard, N6 requester re-check, N7 backfill, marker flag guard,
read-only idempotency lookup, Q28 notice."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.platform.service import CommandResult, lookup_idempotent_response, run_idempotent
from app.modules.wallet import service
from tests.pg.wallet.conftest import FINANCE_CAPS, SUPER_CAPS, fund_wallet, make_user, mark_flag_change_source, wallet_row

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[3]
B = 10_000_000
BIG = service.TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1


def _migration_0047():
    path = REPO_ROOT / "alembic" / "versions" / "20260914_0047_wallet_balance_guard_withdraw.py"
    spec = importlib.util.spec_from_file_location("a3_migration_0047", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _funded(pg_db, people, amount=B):
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], amount, people["super"])
        s.commit()
        return wallet_row(s, people["driver"])


def _forge_pair(conn, wallet_id):
    conn.execute(text("UPDATE ledger_account_balances SET balance_minor = balance_minor + 1 "
                      "WHERE account_id = (SELECT ledger_account_id FROM wallet_accounts WHERE id = :w)"), {"w": wallet_id})
    conn.execute(text("UPDATE wallet_accounts SET posted_balance_minor = posted_balance_minor + 1 WHERE id = :w"),
                 {"w": wallet_id})


# --- N1 ---------------------------------------------------------------------------------------------


def test_n1_session_setting_does_not_open_the_balance_guard(pg_db, people):
    row = _funded(pg_db, people)
    with pytest.raises(DBAPIError, match="maintained by trigger"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("SET LOCAL elchi.ledger_balance_writer = 'on'"))
            _forge_pair(conn, row["id"])


def test_n1_two_table_forgery_detected_at_commit_even_without_the_guard(pg_db, people):
    row = _funded(pg_db, people)
    with pytest.raises(DBAPIError, match="differs from latest ledger entry"):
        with pg_db.engine.begin() as conn:  # guard removed, every deferred constraint trigger still on
            conn.execute(text("ALTER TABLE ledger_account_balances DISABLE TRIGGER trg_ledger_account_balances_guard"))
            _forge_pair(conn, row["id"])
    with pg_db.session() as s:
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == B


def test_n1_forgery_refused_for_an_app_role(pg_db, people):
    row = _funded(pg_db, people)
    role = f"elchi_app_t{uuid.uuid4().hex[:8]}"
    with pg_db.engine.begin() as conn:
        conn.execute(text(f'CREATE ROLE "{role}"'))
        conn.execute(text(f'GRANT SELECT, UPDATE ON wallet_accounts, ledger_account_balances, ledger_accounts, '
                          f'ledger_entries, wallet_holds TO "{role}"'))
    try:
        with pytest.raises(DBAPIError, match="maintained by trigger|permission denied"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{role}"'))
                conn.execute(text("SET LOCAL elchi.ledger_balance_writer = 'on'"))
                _forge_pair(conn, row["id"])
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


def test_n1_entries_carry_immutable_database_assigned_running_totals(pg_db, people, bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        service.hold_fee(s, booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                         total_minor=40_000_000, fee_bps=1500, wallet_required=True)
        service.capture_fee(s, booking_id=booking)
        fund_wallet(s, people["driver"], 1_000, people["super"])
        s.commit()
        account = wallet_row(s, people["driver"])
    with pg_db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT e.account_seq, e.running_balance_minor FROM ledger_entries e "
            "JOIN wallet_accounts w ON w.ledger_account_id = e.account_id WHERE w.id = :w ORDER BY e.account_seq"),
            {"w": account["id"]}).all()
        system = conn.execute(text(
            "SELECT count(*) FROM ledger_entries e JOIN ledger_accounts a ON a.id = e.account_id "
            "WHERE a.kind <> 'liability' AND e.account_seq IS NOT NULL")).scalar()
        balance = conn.execute(text(
            "SELECT balance_minor, last_account_seq FROM ledger_account_balances b "
            "JOIN wallet_accounts w ON w.ledger_account_id = b.account_id WHERE w.id = :w"), {"w": account["id"]}).one()
    assert [tuple(r) for r in rows] == [(1, B), (2, B - 6_000_000), (3, B - 6_000_000 + 1_000)]
    assert system == 0 and tuple(balance) == (B - 6_000_000 + 1_000, 3)
    with pytest.raises(DBAPIError, match="assigned by the database"):
        with pg_db.engine.begin() as conn:
            tx = conn.execute(text(
                "INSERT INTO ledger_transactions (public_id, reference_kind, reference_key, description) "
                "VALUES (:p, 'adjustment', 'forged-seq', 'x') RETURNING id"), {"p": uuid.uuid4()}).scalar()
            conn.execute(text(
                "INSERT INTO ledger_entries (transaction_id, account_id, direction, amount_minor, account_seq, "
                "running_balance_minor) SELECT :t, ledger_account_id, 'credit', 5, 99, 999999 FROM wallet_accounts "
                "WHERE id = :w"), {"t": tx, "w": account["id"]})
    with pytest.raises(DBAPIError, match="immutable"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE ledger_entries SET running_balance_minor = running_balance_minor + 1"))


def test_n7_backfill_restores_running_totals_and_is_idempotent(pg_db, people):
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        fund_wallet(s, people["driver"], 2_000, people["super"])
        s.commit()
    with pg_db.engine.connect() as conn:
        expected = conn.execute(text("SELECT id, account_seq, running_balance_minor FROM ledger_entries "
                                     "WHERE account_seq IS NOT NULL ORDER BY id")).all()
    with pg_db.engine.begin() as conn:  # simulate pre-0047 rows (superuser bypass)
        conn.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE ledger_entries SET account_seq = NULL, running_balance_minor = NULL"))
        conn.execute(text("ALTER TABLE ledger_entries ENABLE TRIGGER USER"))
        conn.execute(text("ALTER TABLE ledger_account_balances DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE ledger_account_balances SET last_account_seq = 0"))
        conn.execute(text("ALTER TABLE ledger_account_balances ENABLE TRIGGER USER"))
    module = _migration_0047()
    for _ in range(2):
        with pg_db.engine.begin() as conn:
            module.backfill_running_balances(conn)
    with pg_db.engine.connect() as conn:
        restored = conn.execute(text("SELECT id, account_seq, running_balance_minor FROM ledger_entries "
                                     "WHERE account_seq IS NOT NULL ORDER BY id")).all()
        balance = conn.execute(text("SELECT balance_minor, last_account_seq FROM ledger_account_balances")).one()
    assert restored == expected and tuple(balance) == (B + 2_000, 2)
    with pg_db.session() as s:  # new postings continue the sequence
        fund_wallet(s, people["driver"], 3_000, people["super"])
        s.commit()
        assert service.run_reconciliation(s).mismatch_count == 0
    with pg_db.engine.begin() as conn:  # L2 (wave 1.7): a drifted balance row stops the backfill, never overwritten
        conn.execute(text("ALTER TABLE ledger_account_balances DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE ledger_account_balances SET balance_minor = balance_minor + 7"))
        conn.execute(text("ALTER TABLE ledger_account_balances ENABLE TRIGGER USER"))
    with pytest.raises(RuntimeError, match="drift detected"):
        with pg_db.engine.begin() as conn:
            module.backfill_running_balances(conn)
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT balance_minor FROM ledger_account_balances")).scalar() == B + 5_007


# --- N2 ---------------------------------------------------------------------------------------------


def test_n2_security_definer_functions_pin_pg_temp_last(pg_db):
    with pg_db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT p.proname, p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.prosecdef "
            "AND p.proname IN ('ledger_entries_running_balance', 'platform_environment_record_history')")).all()
        legacy = conn.execute(text("SELECT count(*) FROM pg_proc WHERE proname = 'ledger_entries_apply_balance'")).scalar()
    assert {name for name, _ in rows} == {"ledger_entries_running_balance", "platform_environment_record_history"}
    for _, config in rows:
        assert "search_path=pg_catalog, public, pg_temp" in (config or []), config
    assert legacy == 0


# --- N3 / Q49 -----------------------------------------------------------------------------------------


def test_q49_requester_withdraws_only_others_reject(pg_db, people):
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, people["driver2"])
        pending = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                             wallet_id=wallet.id, direction="credit", amount_minor=BIG, reason="bank fix")
        s.commit()
        request_id = pending.request.id
        with pytest.raises(DomainError) as exc:
            service.reject_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                      adjustment_request_id=request_id, expected_version=1, reason="mine")
        assert exc.value.code is ErrorCode.FORBIDDEN and exc.value.details == {"reason": "requester_must_withdraw"}
        s.rollback()
        with pytest.raises(DomainError) as exc:
            service.withdraw_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                        adjustment_request_id=request_id, expected_version=1)
        assert exc.value.code is ErrorCode.FORBIDDEN
        s.rollback()
        assert service.blocking_state_for_user(s, people["driver2"]).blocks_deletion
        withdrawn = service.withdraw_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                                adjustment_request_id=request_id, expected_version=1, reason="typo")
        s.commit()
        assert (withdrawn.status, withdrawn.version, withdrawn.rejected_by) == ("withdrawn", 2, None)
        assert not service.blocking_state_for_user(s, people["driver2"]).blocks_deletion
        with pytest.raises(DomainError) as exc:
            service.approve_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                       adjustment_request_id=request_id, expected_version=2)
        assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
        s.rollback()
        other = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                           wallet_id=wallet.id, direction="credit", amount_minor=BIG, reason="second")
        s.commit()
        other_id = other.request.id
    with pytest.raises(DBAPIError, match="ck_ledger_adjustment_requests_rejecter"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE ledger_adjustment_requests SET status = 'rejected', rejected_by = requested_by, "
                              "reject_reason = 'self', decided_at = now() WHERE id = :id"), {"id": other_id})


# --- N5 / N6 ------------------------------------------------------------------------------------------


def _open_gap_in_global_standard(pg_db):
    with pg_db.engine.begin() as conn:  # superuser bypass to simulate a gap (the trigger forbids it)
        conn.execute(text("ALTER TABLE commission_policies DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE commission_policies SET effective_to = now() - interval '1 second', "
                          "ended_by = NULL, ended_reason = NULL WHERE kind = 'standard' AND scope_key = '*:*'"))
        conn.execute(text("ALTER TABLE commission_policies ENABLE TRIGGER USER"))


def test_n5_obligations_work_without_an_active_global_standard(pg_db, people, bookings):
    b1, b2, b3 = bookings.ids(3, driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        for booking in (b1, b2):
            service.hold_fee(s, booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                             total_minor=10_000_000, fee_bps=1500, wallet_required=True)
        s.commit()
        wallet_id = wallet_row(s, people["driver"])["id"]
    _open_gap_in_global_standard(pg_db)
    with pg_db.session() as s:
        report = service.assert_production_invariants(s)
        assert not report.ok and report.failed == ["global_standard_active_now"]
        service.capture_fee(s, booking_id=b1)
        service.release_fee(s, booking_id=b2)
        service.reverse_fee(s, booking_id=b1, amount_minor=1, actor_user_id=people["super"],
                            actor_capabilities=SUPER_CAPS, reason="dispute")
        service.request_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                   wallet_id=wallet_id, direction="credit", amount_minor=5, reason="goodwill")
        s.commit()
        with pytest.raises(DomainError) as exc:
            service.hold_fee(s, booking_id=b3, booking_public_id=f"bkg_{b3}", driver_user_id=people["driver"],
                             total_minor=1_000_000, fee_bps=1500, wallet_required=True)
        assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED
        assert exc.value.details == {"failed": ["global_standard_active_now"]}


def test_n6_approval_rechecks_requester_capability_for_plain_adjustments(pg_db, people):
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, people["driver2"])
        pending = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=FINANCE_CAPS,
                                             wallet_id=wallet.id, direction="credit", amount_minor=BIG, reason="bank")
        s.execute(text("UPDATE users SET role = 'operator' WHERE id = :id"), {"id": people["finance"]})
        s.commit()
        with pytest.raises(DomainError) as exc:
            service.approve_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                       adjustment_request_id=pending.request.id, expected_version=1)
        assert exc.value.code is ErrorCode.FORBIDDEN
        s.rollback()
        assert wallet_row(s, people["driver2"])["posted_balance_minor"] == 0


# --- marker flag guard, Q28 notice, idempotency lookup ----------------------------------------------


def test_marker_refuses_production_with_unapproved_passenger_flag(pg_db, people):
    with pg_db.engine.connect() as conn:
        columns = conn.execute(text(
            "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'feature_flag_values'")).all()
    if not columns:
        pytest.skip("feature_flag_values (A2) not present")
    values = {}
    for name, data_type, nullable, default in columns:
        if name == "id" or default is not None or nullable == "YES":
            continue
        values[name] = {"uuid": "gen_random_uuid()", "boolean": "false", "integer": str(people["super"]),
                        "bigint": str(people["super"]), "smallint": "1", "timestamp with time zone": "now()"}.get(data_type, "'x'")
    values.update({"flag_key": "'passenger_enabled'", "enabled": "true", "scope_type": "'country'", "scope_ref": "'UZ'"})
    with pg_db.engine.begin() as conn:
        mark_flag_change_source(conn)  # Q72: switching a v2 service flag on needs the admin-API marker
        conn.execute(text(f"INSERT INTO feature_flag_values ({', '.join(values)}) VALUES ({', '.join(values.values())})"))
    with pytest.raises(DBAPIError, match="without an approval reference"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 't' WHERE id = 1"))


def test_q28_unconfirmed_seed_is_an_informational_notice(pg_db):
    with pg_db.session() as s:
        report = service.assert_production_invariants(s)
    assert report.ok
    assert [n.name for n in report.notices] == ["unconfirmed_seed_policy_active"]
    assert report.as_dict()["notices"][0]["detail"] == {"blocks_production_quotes_and_holds": False}


def test_lookup_idempotent_response_is_read_only(pg_db):
    with pg_db.session() as s:
        uid = make_user(s, "driver")
        s.commit()
    args = dict(actor_user_id=uid, method="POST", route_template="/api/v2/routes/preview",
                idempotency_key="lookup-key-00001", body={"a": 1})
    with pg_db.session() as s:
        assert lookup_idempotent_response(s, **args) is None
        run_idempotent(s, handler=lambda: CommandResult(201, {"stored": True}), **args)
        s.commit()
    with pg_db.session() as s:
        replay = lookup_idempotent_response(s, **args)
        assert (replay.status_code, replay.body, replay.replayed) == (201, {"stored": True}, True)
        with pytest.raises(DomainError) as exc:
            lookup_idempotent_response(s, **{**args, "body": {"a": 2}})
        assert exc.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED
        assert lookup_idempotent_response(s, **args, now=utc_now() + timedelta(hours=25)) is None
        assert not s.new and not s.dirty
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM idempotency_records")).scalar() == 1
