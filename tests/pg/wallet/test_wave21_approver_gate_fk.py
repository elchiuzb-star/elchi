"""Wave 2.1 (A3, migration 0055) on PostgreSQL: wallet -> bookings FKs, Q69 approver guard, Q70 money-in gate,
Q71 object ownership gate check, amendment hold increase gate (AC19, D10)."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.db_errors import CONSTRAINT_RULES
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.platform import service as platform_service
from app.modules.platform.service import DeploymentEnvironment, constraint_name_of, q48_gate_status
from app.modules.wallet import service
from tests.pg.wallet.conftest import SUPER_CAPS, as_role, fund_wallet, make_user, wallet_row

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[3]
B = 10_000_000
THRESHOLD = service.TWO_PERSON_APPROVAL_THRESHOLD_MINOR
BIG = THRESHOLD + 1
GATE_FAILED = {"failed": ["q48_money_gate"]}


@pytest.fixture
def app_env(monkeypatch):
    def set_env(env: DeploymentEnvironment):
        monkeypatch.setattr(service, "app_environment", lambda: env)
        monkeypatch.setattr(platform_service, "app_environment", lambda: env)

    return set_env


def _migration_0055():
    path = REPO_ROOT / "alembic" / "versions" / "20260915_0055_wallet_booking_fk_approver_guard.py"
    spec = importlib.util.spec_from_file_location("a3_migration_0055", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mark_production(pg_db):
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 't' WHERE id = 1"))


def _pending_topup(pg_db, driver, amount=B):
    with pg_db.session() as s:
        topup = service.create_topup(s, driver_user_id=driver, amount_minor=amount, method="bank_transfer")
        s.commit()
        return topup.id


def _approve_topup_kwargs(topup_id, version=1, amount=B, reference=None):
    return dict(topup_id=topup_id, expected_version=version, source_type="bank_statement",
                source_reference=reference or f"STMT-{uuid.uuid4().hex}", received_amount_minor=amount,
                received_at=utc_now())


def _refused_by_db(pg_db, sql, params, *, rule, role=None):
    with pytest.raises(DBAPIError) as exc:
        with pg_db.engine.begin() as conn:
            if role:
                as_role(conn, role)
            conn.execute(text(sql), params)
    assert constraint_name_of(exc.value) == rule, exc.value
    return exc.value


# --- FKs ------------------------------------------------------------------------------------------------


def test_fk_wallet_holds_and_ledger_transactions_reference_real_bookings(pg_db, people, bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT conname, convalidated, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname IN ('fk_wallet_holds_booking_id', 'fk_ledger_transactions_booking_id') ORDER BY conname")).all()
    assert [(r[0], r[1]) for r in rows] == [("fk_ledger_transactions_booking_id", True),
                                            ("fk_wallet_holds_booking_id", True)]
    assert all("REFERENCES bookings(id)" in r[2] for r in rows)
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        service.hold_fee(s, booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                         total_minor=10_000_000, fee_bps=1500, wallet_required=True)
        capture = service.capture_fee(s, booking_id=booking)
        s.commit()
        assert s.execute(text("SELECT booking_id FROM ledger_transactions WHERE id = :t"),
                         {"t": capture.transaction_id}).scalar() == booking
    missing = booking + 1_000_000
    with pg_db.session() as s:
        with pytest.raises(DBAPIError) as exc:
            service.hold_fee(s, booking_id=missing, booking_public_id="bkg_missing", driver_user_id=people["driver"],
                             total_minor=1_000_000, fee_bps=1500, wallet_required=True)
        assert constraint_name_of(exc.value) == "fk_wallet_holds_booking_id"
    with pg_db.session() as s:
        wallet_id = wallet_row(s, people["driver"])["id"]
    _refused_by_db(
        pg_db,
        "INSERT INTO ledger_transactions (public_id, reference_kind, reference_key, description, wallet_id, booking_id) "
        "VALUES (:p, 'commission_capture', 'fk-probe', 'x', :w, :b)",
        {"p": uuid.uuid4(), "w": wallet_id, "b": missing},
        rule="fk_ledger_transactions_booking_id",
    )


def test_fk_migration_step_is_idempotent_and_reports_orphans(pg_db, people, bookings):
    module = _migration_0055()
    for _ in range(2):
        with pg_db.engine.begin() as conn:
            module.add_booking_foreign_keys(conn)
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        service.hold_fee(s, booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                         total_minor=10_000_000, fee_bps=1500, wallet_required=True)
        s.commit()
    with pg_db.engine.begin() as conn:  # simulate a pre-0055 orphan (superuser, constraint dropped)
        conn.execute(text("ALTER TABLE wallet_holds DROP CONSTRAINT fk_wallet_holds_booking_id"))
        conn.execute(text("ALTER TABLE wallet_holds DISABLE TRIGGER USER"))
        conn.execute(text("UPDATE wallet_holds SET booking_id = booking_id + 1000000 WHERE booking_id = :b"), {"b": booking})
        conn.execute(text("ALTER TABLE wallet_holds ENABLE TRIGGER USER"))
    with pytest.raises(RuntimeError, match="wallet_holds.booking_id references missing bookings"):
        with pg_db.engine.begin() as conn:
            module.add_booking_foreign_keys(conn)
    with pg_db.engine.connect() as conn:  # the failed step left nothing behind
        assert conn.execute(text("SELECT count(*) FROM pg_constraint WHERE conname = 'fk_wallet_holds_booking_id'")).scalar() == 0


# --- Q69 ------------------------------------------------------------------------------------------------


@pytest.fixture
def non_approvers(pg_db, people):
    """Staff/marketplace users who must never approve: operator, admin, driver, revoked finance, blocked finance."""
    with pg_db.session() as s:
        operator = make_user(s, "operator")
        revoked = make_user(s, "operator")
        s.execute(text("INSERT INTO user_roles (user_id, role, status) VALUES (:u, 'finance', 'active')"), {"u": revoked})
        s.execute(text("UPDATE user_roles SET status = 'revoked' WHERE user_id = :u AND role = 'finance'"), {"u": revoked})
        blocked = make_user(s, "finance")
        s.execute(text("UPDATE users SET status = 'blocked' WHERE id = :u"), {"u": blocked})
        s.commit()
    return {"operator": operator, "admin": people["admin"], "driver": people["driver2"],
            "revoked_finance": revoked, "blocked_finance": blocked}


def test_q69_db_refuses_non_finance_approvers_even_for_the_app_role(pg_db, people, app_role, non_approvers):
    topup_id = _pending_topup(pg_db, people["driver"])
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, people["driver2"])
        pending = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                             wallet_id=wallet.id, direction="credit", amount_minor=BIG, reason="bank")
        s.commit()
        adjustment_id = pending.request.id
    assert CONSTRAINT_RULES["approver_not_finance_staff"].code is ErrorCode.FORBIDDEN
    for name, user in non_approvers.items():
        for column in ("first_approver_id", "second_approver_id"):
            _refused_by_db(pg_db, f"UPDATE topup_requests SET {column} = :u WHERE id = :id",
                           {"u": user, "id": topup_id}, rule="approver_not_finance_staff", role=app_role)
        _refused_by_db(pg_db, "UPDATE ledger_adjustment_requests SET approved_by = :u WHERE id = :id",
                       {"u": user, "id": adjustment_id}, rule="approver_not_finance_staff", role=app_role)
        _refused_by_db(
            pg_db,
            "UPDATE ledger_adjustment_requests SET status = 'rejected', rejected_by = :u, reject_reason = 'x', "
            "decided_at = now(), version = version + 1 WHERE id = :id",
            {"u": user, "id": adjustment_id}, rule="approver_not_finance_staff", role=app_role,
        )
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT first_approver_id, status FROM topup_requests WHERE id = :id"),
                            {"id": topup_id}).one() == (None, "pending")


def test_q69_service_refuses_fabricated_capabilities(pg_db, people, non_approvers):
    topup_id = _pending_topup(pg_db, people["driver"])
    with pg_db.session() as s:
        wallet_id = service.get_or_create_wallet(s, people["driver2"]).id
        pending = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                             wallet_id=wallet_id, direction="credit", amount_minor=BIG, reason="bank")
        s.commit()
        for user in non_approvers.values():
            calls = (
                lambda: service.approve_topup(s, actor_user_id=user, actor_capabilities=SUPER_CAPS,
                                              **_approve_topup_kwargs(topup_id)),
                lambda: service.approve_adjustment(s, actor_user_id=user, actor_capabilities=SUPER_CAPS,
                                                   adjustment_request_id=pending.request.id, expected_version=1),
                lambda: service.reject_adjustment(s, actor_user_id=user, actor_capabilities=SUPER_CAPS,
                                                  adjustment_request_id=pending.request.id, expected_version=1, reason="no"),
                lambda: service.request_adjustment(s, actor_user_id=user, actor_capabilities=SUPER_CAPS, wallet_id=wallet_id,
                                                   direction="credit", amount_minor=100, reason="goodwill"),
            )
            for call in calls:
                with pytest.raises(DomainError) as exc:
                    call()
                assert exc.value.code is ErrorCode.FORBIDDEN
                assert exc.value.details == {"reason": "approver_not_finance_staff"}
                s.rollback()
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == 0


def test_q69_finance_via_user_roles_and_super_admin_approve(pg_db, people):
    with pg_db.session() as s:
        granted = make_user(s, "operator")  # staff family: operator + finance is allowed (Q3)
        s.execute(text("INSERT INTO user_roles (user_id, role, status) VALUES (:u, 'finance', 'active')"), {"u": granted})
        s.commit()
    big_topup = _pending_topup(pg_db, people["driver"], BIG)
    with pg_db.session() as s:
        kwargs = _approve_topup_kwargs(big_topup, amount=BIG, reference="STMT-Q69")
        first = service.approve_topup(s, actor_user_id=granted, actor_capabilities=SUPER_CAPS, **kwargs)
        s.commit()
        done = service.approve_topup(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                     **{**kwargs, "expected_version": first.version})
        s.commit()
        assert (done.status, done.first_approver_id, done.second_approver_id) == ("approved", granted, people["finance"])
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == BIG


# --- Q70 ------------------------------------------------------------------------------------------------


def test_q70_production_gate_refuses_money_in_but_not_debits(pg_db, people, app_env, app_role):
    wallet_id = None
    with pg_db.session() as s:  # non-production preparation
        for _ in range(3):
            fund_wallet(s, people["driver"], THRESHOLD, people["super"])
        wallet_id = service.get_or_create_wallet(s, people["driver"]).id
        small_topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=B, method="bank_transfer")
        raw_topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=B, method="bank_transfer")
        big_topup = service.create_topup(s, driver_user_id=people["driver"], amount_minor=BIG, method="bank_transfer")
        s.commit()
        big_kwargs = _approve_topup_kwargs(big_topup.id, amount=BIG, reference="STMT-BIG-Q70")
        first = service.approve_topup(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, **big_kwargs)
        big_credit = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                                wallet_id=wallet_id, direction="credit", amount_minor=BIG, reason="bank")
        big_debit = service.request_adjustment(s, actor_user_id=people["finance"], actor_capabilities=SUPER_CAPS,
                                               wallet_id=wallet_id, direction="debit", amount_minor=BIG, reason="Q31 refund")
        s.commit()
        posted_before = wallet_row(s, people["driver"])["posted_balance_minor"]
    _mark_production(pg_db)
    app_env(DeploymentEnvironment.PRODUCTION)
    with pg_db.session() as s:
        as_role(s, app_role)  # seed rate unconfirmed -> the Q48 gate fails
        assert q48_gate_status(s).failed == ["seed_rate_confirmed"]
        refused = (
            lambda: service.approve_topup(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                          **_approve_topup_kwargs(small_topup.id)),
            lambda: service.approve_topup(s, actor_user_id=people["super2"], actor_capabilities=SUPER_CAPS,
                                          **{**big_kwargs, "expected_version": first.version}),
            lambda: service.request_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                               wallet_id=wallet_id, direction="credit", amount_minor=100, reason="x"),
            lambda: service.approve_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                               adjustment_request_id=big_credit.request.id, expected_version=1),
        )
        for call in refused:
            with pytest.raises(DomainError) as exc:
                call()
            assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED and exc.value.http_status == 503
            assert exc.value.details == GATE_FAILED
            s.rollback()
            as_role(s, app_role)
        # Q31 refunds (debits) keep working while the gate fails (integrator interpretation).
        small_debit = service.request_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                                 wallet_id=wallet_id, direction="debit", amount_minor=100, reason="refund")
        big = service.approve_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                         adjustment_request_id=big_debit.request.id, expected_version=1)
        s.commit()
        assert small_debit.status == big.status == "posted"
        assert wallet_row(s, people["driver"])["posted_balance_minor"] == posted_before - 100 - BIG
    # DB backstop (0055) for the app role writing the rows directly.
    assert CONSTRAINT_RULES["q48_gate_money_refused"].code is ErrorCode.PRODUCTION_INVARIANTS_FAILED
    _refused_by_db(
        pg_db,
        "UPDATE topup_requests SET status = 'awaiting_second_approval', first_approver_id = :a, source_type = 'bank_statement', "
        "source_reference = 'RAW-Q70', received_amount_minor = amount_minor, received_at = now(), version = version + 1 "
        "WHERE id = :id",
        {"a": people["super"], "id": raw_topup.id}, rule="q48_gate_money_refused", role=app_role,
    )
    with pg_db.session() as s:  # gate passes once the seed rate is confirmed -> money in works again
        as_role(s, app_role)
        seed = service.current_global_standard(s)
        service.confirm_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=seed.id,
                               expected_version=seed.version, reason="rate reviewed")
        s.commit()
        as_role(s, app_role)
        approved = service.approve_topup(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                         **_approve_topup_kwargs(small_topup.id))
        s.commit()
        assert approved.status == "approved"


def test_amendment_hold_increase_needs_the_gate_decrease_does_not(pg_db, people, app_env, app_role, bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], B, people["super"])
        service.hold_fee(s, booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                         total_minor=20_000_000, fee_bps=1500, wallet_required=True)
        s.commit()
    _mark_production(pg_db)
    app_env(DeploymentEnvironment.PRODUCTION)
    with pg_db.session() as s:
        as_role(s, app_role)
        with pytest.raises(DomainError) as exc:
            service.adjust_hold(s, booking_id=booking, new_total_minor=30_000_000, fee_bps=1500, wallet_required=True)
        assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED and exc.value.details == GATE_FAILED
        s.rollback()
        as_role(s, app_role)
        down = service.adjust_hold(s, booking_id=booking, new_total_minor=10_000_000, fee_bps=1500, wallet_required=True)
        s.commit()
        assert down.delta_minor == -1_500_000 and wallet_row(s, people["driver"])["held_minor"] == 1_500_000


# --- Q69 / Q71 gate checks ---------------------------------------------------------------------------------


def test_q71_gate_fails_when_the_app_role_owns_an_object_and_q69_when_guard_disabled(pg_db, people, app_role):
    with pg_db.session() as s:
        seed = service.current_global_standard(s)
        service.confirm_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=seed.id,
                               expected_version=seed.version, reason="rate reviewed")
        s.commit()
        as_role(s, app_role)
        gate = q48_gate_status(s)
        assert gate.ok, gate.as_dict()
        owns = next(c for c in gate.checks if c.name == "app_role_owns_no_objects")
        assert owns.detail == "relations=0 functions=0 types=0 schemas=0"
    with pg_db.engine.begin() as conn:
        conn.execute(text(f'GRANT CREATE ON SCHEMA public TO "{app_role}"'))
        as_role(conn, app_role)
        conn.execute(text("CREATE TABLE app_role_owned_probe (id integer)"))
        conn.execute(text("CREATE FUNCTION app_role_owned_fn() RETURNS integer LANGUAGE sql AS 'SELECT 1'"))
    with pg_db.session() as s:
        as_role(s, app_role)
        gate = q48_gate_status(s)
        assert gate.failed == ["app_role_owns_no_objects"]
        detail = next(c.detail for c in gate.checks if c.name == "app_role_owns_no_objects")
        assert "relations=0" not in detail and "functions=1" in detail
        assert s.execute(text("SELECT public.platform_q48_gate_passed()")).scalar() is False
    with pg_db.engine.begin() as conn:
        conn.execute(text("DROP TABLE app_role_owned_probe"))
        conn.execute(text("DROP FUNCTION app_role_owned_fn()"))
        conn.execute(text("ALTER TABLE topup_requests DISABLE TRIGGER trg_topup_requests_approval_guard"))
    try:
        with pg_db.session() as s:
            as_role(s, app_role)
            assert q48_gate_status(s).failed == ["approver_guard_enforced"]
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE topup_requests ENABLE TRIGGER trg_topup_requests_approval_guard"))
