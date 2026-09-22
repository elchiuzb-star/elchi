"""BR N1 + wave 1.5 (#1-#3, decision 28, 36): DB environment marker, fail-closed guards,
money-command refusal, unconfirmed seed policy, app-role grants; N4 account deletion facts."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.errors import DomainError, ErrorCode
from app.modules.platform import service as platform_service
from app.modules.platform.service import DeploymentEnvironment
from app.modules.wallet import service
from tests.pg.wallet.conftest import ADMIN_CAPS, SUPER_CAPS, as_role, fund_wallet

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[3]
UNCONFIRMED = getattr(ErrorCode, "COMMISSION_POLICY_UNCONFIRMED", ErrorCode.SERVICE_UNAVAILABLE)


def _mark(pg_db, env):
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = :e, set_by = 'test' WHERE id = 1"), {"e": env})


def _delete_marker(pg_db):
    with pg_db.engine.begin() as conn:  # superuser bypass, simulating an operator mistake
        conn.execute(text("ALTER TABLE platform_environment DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM platform_environment"))
        conn.execute(text("ALTER TABLE platform_environment ENABLE TRIGGER USER"))


def _small_credit(s, people, wallet_id):
    return service.request_adjustment(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                      wallet_id=wallet_id, direction="credit", amount_minor=1, reason="x")


@pytest.fixture
def app_env(monkeypatch):
    def set_env(env: DeploymentEnvironment):
        monkeypatch.setattr(service, "app_environment", lambda: env)
        monkeypatch.setattr(platform_service, "app_environment", lambda: env)

    return set_env


def test_marker_seeded_non_production_and_healthy_report(pg_db):
    with pg_db.session() as s:
        assert platform_service.get_db_environment(s) is DeploymentEnvironment.DEVELOPMENT
        report = service.assert_production_invariants(s)
    assert report.ok and not report.is_production and not report.alert
    assert {c.name for c in report.checks} >= {"environment_marker", "global_standard_active_now"}
    assert report.as_dict()["status"] == "pass"


def test_trigger_rejects_overdraft_wallet_on_production_marker(pg_db, people):
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, people["driver"])
        s.commit()
        wallet_id = wallet.id
    _mark(pg_db, "production")
    with pytest.raises(DBAPIError, match="forbidden in production"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE wallet_accounts SET test_overdraft_allowed = true WHERE id = :id"), {"id": wallet_id})
    with pg_db.session() as s:
        with pytest.raises(DomainError):
            service.set_test_overdraft_allowed(s, wallet_id, True, actor_user_id=people["super"])


def test_marker_cannot_enter_production_with_overdraft_wallet_nor_leave_it(pg_db, people):
    with pg_db.session() as s:
        wallet = service.get_or_create_wallet(s, people["driver"])
        service.set_test_overdraft_allowed(s, wallet.id, True, actor_user_id=people["super"])
        s.commit()
    with pytest.raises(DBAPIError, match="test_overdraft_allowed"):
        _mark(pg_db, "production")
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE wallet_accounts SET test_overdraft_allowed = false"))
    _mark(pg_db, "production")
    for statement in ("UPDATE platform_environment SET environment = 'development'", "DELETE FROM platform_environment"):
        with pytest.raises(DBAPIError, match="platform_environment"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement))


def test_money_commands_refuse_while_invariants_fail(pg_db, people, bookings):
    """Real DB marker: the database says production, the app (development) does not."""
    b1, b2 = bookings.ids(2, driver_user_id=people["driver"])
    with pg_db.session() as s:
        fund_wallet(s, people["driver"], 10_000_000, people["super"])
        service.hold_fee(s, booking_id=b1, booking_public_id=f"bkg_{b1}", driver_user_id=people["driver"],
                         total_minor=40_000_000, fee_bps=1500, wallet_required=True)
        wallet_id = service.get_or_create_wallet(s, people["driver"]).id
        s.commit()
    _mark(pg_db, "production")
    with pg_db.session() as s:
        report = service.assert_production_invariants(s)
        assert not report.ok and report.alert and report.is_production
        assert "environment_marker" in report.failed and report.as_dict()["status"] == "fail"
        for call in (
            lambda: service.capture_fee(s, booking_id=b1),
            lambda: service.release_fee(s, booking_id=b1),
            lambda: service.hold_fee(s, booking_id=b2, booking_public_id=f"bkg_{b2}", driver_user_id=people["driver"],
                                     total_minor=1_000_000, fee_bps=1500, wallet_required=True),
            lambda: _small_credit(s, people, wallet_id),
        ):
            with pytest.raises(DomainError) as exc:
                call()
            assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED and exc.value.http_status == 503
            s.rollback()
    with pg_db.session() as s:
        assert s.execute(text("SELECT status FROM wallet_holds WHERE booking_id = :b"), {"b": b1}).scalar() == "active"


def test_br2_missing_marker_fails_closed(pg_db, people):
    with pg_db.session() as s:
        wallet_id = service.get_or_create_wallet(s, people["driver"]).id
        s.commit()
    _delete_marker(pg_db)
    with pg_db.session() as s:
        assert platform_service.is_production(s)
        report = service.assert_production_invariants(s)
        assert not report.ok and report.is_production and "environment_marker" in report.failed
        with pytest.raises(DomainError) as exc:
            _small_credit(s, people, wallet_id)
        assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED
    with pytest.raises(DBAPIError, match="forbidden in production"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE wallet_accounts SET test_overdraft_allowed = true WHERE id = :id"), {"id": wallet_id})


def test_br1_truncate_history_and_reinsert_after_production_refused(pg_db):
    _mark(pg_db, "production")
    for statement in (
        "TRUNCATE platform_environment",
        "TRUNCATE platform_environment_history",
        "UPDATE platform_environment_history SET environment = 'test'",
        "DELETE FROM platform_environment_history",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement))
    with pg_db.engine.connect() as conn:
        history = conn.execute(text("SELECT environment FROM platform_environment_history ORDER BY id")).scalars().all()
    assert history == ["development", "production"]
    _delete_marker(pg_db)
    for env in ("development", "production"):
        with pytest.raises(DBAPIError, match="re-insert refused"):
            with pg_db.engine.begin() as conn:
                conn.execute(text("INSERT INTO platform_environment (id, environment, set_by) VALUES (1, :e, 't')"),
                             {"e": env})


def test_br3_unknown_app_environment_fails_closed(pg_db, people, monkeypatch):
    from app.core.config import settings

    with pg_db.session() as s:
        fund_wallet(s, people["driver"], 1_000_000, people["super"])
        wallet_id = service.get_or_create_wallet(s, people["driver"]).id
        s.commit()
    monkeypatch.setattr(settings, "environment", "prod")
    with pg_db.session() as s:
        assert platform_service.is_production(s)
        report = service.assert_production_invariants(s)
        assert not report.ok and report.is_production and report.app_environment == "invalid"
        assert "app_environment_valid" in report.failed
        with pytest.raises(DomainError) as exc:
            _small_credit(s, people, wallet_id)
        assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED


def test_consistent_production_passes_and_wallet_required_false_is_config_error(pg_db, people, app_env, app_role,
                                                                              bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:  # Q70: top-ups before the switch (a superuser session never passes the gate)
        seed = service.current_global_standard(s)
        service.confirm_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=seed.id,
                               expected_version=seed.version, reason="rate reviewed")
        fund_wallet(s, people["driver"], 10_000_000, people["super"])
        s.commit()
    _mark(pg_db, "production")
    app_env(DeploymentEnvironment.PRODUCTION)
    with pg_db.session() as s:
        as_role(s, app_role)  # Q56: the gate passes only for a non-superuser app role
        report = service.assert_production_invariants(s)
        assert report.ok and report.is_production, report.as_dict()
        with pytest.raises(DomainError) as exc:
            service.hold_fee(s, booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                             total_minor=40_000_000, fee_bps=1500, wallet_required=False)
        assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED


def test_decision28_unconfirmed_seed_blocks_production_quotes_and_holds(pg_db, people, app_env, app_role, bookings):
    booking = bookings.new(driver_user_id=people["driver"])
    with pg_db.session() as s:  # Q70: fund before the production switch
        fund_wallet(s, people["driver"], 10_000_000, people["super"])
        s.commit()
    _mark(pg_db, "production")
    app_env(DeploymentEnvironment.PRODUCTION)
    with pg_db.session() as s:
        as_role(s, app_role)
        seed = service.current_global_standard(s)
        assert seed.created_by is None and seed.confirmed_by is None
        with pytest.raises(DomainError) as exc:
            service.quote_fee(s, corridor_id=None, service_type="parcel", total_minor=1_000_000)
        assert exc.value.code is UNCONFIRMED and exc.value.details == {"reason": "commission_policy_unconfirmed"}
        hold_args = dict(booking_id=booking, booking_public_id=f"bkg_{booking}", driver_user_id=people["driver"],
                         total_minor=40_000_000, fee_bps=1500, wallet_required=True)
        with pytest.raises(DomainError) as exc:  # Q56: the Q48 gate (seed unconfirmed) blocks new holds first
            service.hold_fee(s, fee_policy_id=seed.id, **hold_args)
        assert exc.value.code is ErrorCode.PRODUCTION_INVARIANTS_FAILED
        assert exc.value.details == {"failed": ["q48_money_gate"]}
        s.rollback()
        as_role(s, app_role)
        with pytest.raises(DomainError) as exc:
            service.confirm_policy(s, actor_user_id=people["admin"], actor_capabilities=ADMIN_CAPS, policy_id=seed.id,
                                   expected_version=seed.version, reason="x")
        assert exc.value.code is ErrorCode.FORBIDDEN
        s.rollback()
        as_role(s, app_role)
        confirmed = service.confirm_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                           policy_id=seed.id, expected_version=seed.version, reason="rate reviewed")
        s.commit()
        as_role(s, app_role)
        assert confirmed.confirmed_by == people["super"]
        assert service.quote_fee(s, corridor_id=None, service_type="parcel", total_minor=1_000_000).fee_bps == 1500
        with pytest.raises(DomainError) as exc:
            service.hold_fee(s, **hold_args)  # production requires the snapshotted policy id
        assert exc.value.code is ErrorCode.VALIDATION_ERROR
        s.rollback()
        as_role(s, app_role)
        assert service.hold_fee(s, fee_policy_id=seed.id, **hold_args).changed
        s.commit()
        as_role(s, app_role)
        with pytest.raises(DomainError) as exc:
            service.confirm_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=seed.id,
                                   expected_version=confirmed.version, reason="again")
        assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
    with pytest.raises(DBAPIError, match="only an unconfirmed migration seed"):
        with pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE commission_policies SET confirmed_by = NULL, confirmed_at = NULL, "
                              "version = version + 1 WHERE id = :id"), {"id": seed.id})


def test_n4_blocking_state_for_user(pg_db, people):
    with pg_db.session() as s:
        assert not service.blocking_state_for_user(s, people["driver"]).blocks_deletion
        service.get_or_create_wallet(s, people["driver"])
        assert not service.blocking_state_for_user(s, people["driver"]).blocks_deletion
        service.create_topup(s, driver_user_id=people["driver"], amount_minor=5, method="bank_transfer")
        state = service.blocking_state_for_user(s, people["driver"], lock=True)
        assert state.blocks_deletion and state.pending_topups_count == 1
        fund_wallet(s, people["driver2"], 1_000_000, people["super"])
        state2 = service.blocking_state_for_user(s, people["driver2"])
        assert state2.blocks_deletion and state2.as_details()["wallet_posted_minor"] == 1_000_000
        s.rollback()


def _flag_insert_sql(pg_db):
    with pg_db.engine.connect() as conn:
        present = conn.execute(text(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_feature_flag_wallet_required_guard'")).scalar()
        columns = conn.execute(text(
            "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'feature_flag_values'")).all()
    if not columns:
        pytest.skip("feature_flag_values (A2, 0033) not present")
    assert present == 1
    values = {}
    for name, data_type, nullable, default in columns:
        if name == "id" or default is not None or nullable == "YES":
            continue
        values[name] = {"uuid": "gen_random_uuid()", "boolean": "false", "integer": "1", "bigint": "1", "smallint": "1",
                        "timestamp with time zone": "now()"}.get(data_type, "'x'")
    values.update({"flag_key": "'wallet_required'", "enabled": "false", "scope_type": "'country'", "scope_ref": "'UZ'"})
    return f"INSERT INTO feature_flag_values ({', '.join(values)}) VALUES ({', '.join(values.values())})"


@pytest.mark.parametrize("marker", ["production", "missing"])
def test_wallet_required_flag_trigger_fails_closed(pg_db, marker):
    sql = _flag_insert_sql(pg_db)
    if marker == "production":
        _mark(pg_db, "production")
    else:
        _delete_marker(pg_db)
    # A3's trigger and A2's own production rule both refuse the row; either message proves fail-closed.
    with pytest.raises(DBAPIError, match="wallet_required (cannot be false|is locked to true) in production"):
        with pg_db.engine.begin() as conn:
            conn.execute(text(sql))


def test_decision36_app_role_grants_applied_when_role_exists(pg_db):
    path = REPO_ROOT / "alembic" / "versions" / "20260914_0042_platform_wallet_hardening.py"
    spec = importlib.util.spec_from_file_location("a3_migration_0042", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    role = f"elchi_app_t{uuid.uuid4().hex[:8]}"
    with pg_db.engine.begin() as conn:
        conn.execute(text(f'CREATE ROLE "{role}"'))
    try:
        with pg_db.engine.begin() as conn:
            conn.execute(text(f'GRANT ALL ON ledger_entries, platform_environment, commission_policies TO "{role}"'))
            assert module.apply_app_role_grants(conn, role) is True
            assert module.apply_app_role_grants(conn, role) is True  # idempotent
            assert module.apply_app_role_grants(conn, "no_such_role_a3") is False
            assert module.apply_app_role_grants(conn, None) is False

        def allowed(conn, table, privilege):
            return conn.execute(text("SELECT has_table_privilege(:r, :t, :p)"),
                                {"r": role, "t": table, "p": privilege}).scalar()

        with pg_db.engine.connect() as conn:
            assert not allowed(conn, "ledger_entries", "UPDATE") and not allowed(conn, "ledger_entries", "TRUNCATE")
            assert allowed(conn, "ledger_entries", "INSERT")
            assert not allowed(conn, "platform_environment", "UPDATE") and allowed(conn, "platform_environment", "SELECT")
            assert not allowed(conn, "commission_policies", "DELETE") and allowed(conn, "commission_policies", "UPDATE")
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))
