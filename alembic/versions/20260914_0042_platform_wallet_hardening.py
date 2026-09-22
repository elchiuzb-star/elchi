"""platform + wallet hardening (wave 1.5 BR fixes)

Owner: A3 (wave 1.5) - modules `platform`, `wallet`.
Content (DATA_MODEL.md §5, wave 1.5 BR review):
  * #1 platform_environment_history (append-only, filled by trigger); TRUNCATE guards on the marker
    and its history; INSERT of a marker is refused once a production marker was ever recorded.
  * #2 fail-closed guards: a missing marker row counts as production in wallet_accounts_guard and
    feature_flag_wallet_required_guard (CREATE OR REPLACE of the 0041 functions).
  * #6 deferred constraint trigger: a global standard commission policy may only end when a
    successor global standard starts exactly then (only replace_global_standard does that).
  * #7 60 s clock-skew tolerance in commission_policies_guard; accepted values are clamped to now().
  * decision 28: commission_policies.confirmed_by / confirmed_at (one-time confirm of the seed rate).
  * #8 ledger_account_balances: running balance per driver liability account maintained by an
    AFTER INSERT trigger on ledger_entries (SECURITY DEFINER writer); wallet_assert_cache_consistent
    reads it (O(1)); a deferred check on the balance table itself prevents drift.
  * #4 ledger_adjustment_requests.rejected_by / reject_reason / decided_at.
  * decision 36 (guarded, idempotent): when ELCHI_DB_APP_ROLE names an existing role that is not the
    migrating user, apply the grants below.

App-role grants (A10a runbook; the migrator/owner role keeps full rights):
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform_environment, platform_environment_history,
           ledger_account_balances FROM <app_role>;
    REVOKE UPDATE, DELETE, TRUNCATE ON ledger_transactions, ledger_entries FROM <app_role>;
    REVOKE DELETE, TRUNCATE ON commission_policies, wallet_accounts, wallet_holds, topup_requests,
           ledger_adjustment_requests, reconciliation_runs FROM <app_role>;
The marker CLI (``python -m app.modules.platform.environment set ...``) must run as the migrator role.

Tables: platform_environment_history, ledger_account_balances (new); columns/triggers on
platform_environment, commission_policies, ledger_entries, ledger_adjustment_requests, wallet_*.
FK dependencies: 0031, 0036, 0041.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks, re-runnable backfills);
do not change revision ids or the chain. downgrade() is not a rollback strategy (ADR-0016, §18.3).

Revision ID: 20260914_0042
Revises: 20260913_0041
Create Date: 2026-09-14 00:42:00.000000
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260914_0042"
down_revision: str = "20260913_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_CLOCK_TOLERANCE_SQL = "interval '60 seconds'"  # mirrors wallet.service.POLICY_CLOCK_TOLERANCE

APP_ROLE_REVOKES = (
    "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform_environment, platform_environment_history, "
    "ledger_account_balances FROM {role}",
    "REVOKE UPDATE, DELETE, TRUNCATE ON ledger_transactions, ledger_entries FROM {role}",
    "REVOKE DELETE, TRUNCATE ON commission_policies, wallet_accounts, wallet_holds, topup_requests, "
    "ledger_adjustment_requests, reconciliation_runs FROM {role}",
)


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def _constraint_trigger(name: str, table: str, events: str, function: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {name} AFTER {events} ON {table} "
        f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {function}()"
    )


def apply_app_role_grants(bind, role: str | None) -> bool:
    """Apply the app-role REVOKEs when ``role`` exists and is not the current user. Idempotent."""
    role = (role or "").strip()
    if not role:
        return False
    exists = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
    current = bind.execute(sa.text("SELECT current_user")).scalar_one()
    if exists is None or role == current:
        return False
    quoted = '"' + role.replace('"', '""') + '"'
    for statement in APP_ROLE_REVOKES:
        bind.execute(sa.text(statement.format(role=quoted)))
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- #1 marker history, TRUNCATE guards, no re-insert after production ----------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_environment_history (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            environment VARCHAR(16) NOT NULL,
            set_by VARCHAR(128) NOT NULL,
            note TEXT,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_platform_environment_history_value
                CHECK (environment IN ('production', 'staging', 'development', 'test'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_environment_history_environment "
        "ON platform_environment_history (environment)"
    )
    op.execute(
        "INSERT INTO platform_environment_history (environment, set_by, note) "
        "SELECT environment, set_by, 'backfill 20260914_0042' FROM platform_environment "
        "WHERE NOT EXISTS (SELECT 1 FROM platform_environment_history)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_environment_record_history() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.environment IS DISTINCT FROM OLD.environment THEN
                INSERT INTO platform_environment_history (environment, set_by, note)
                VALUES (NEW.environment, NEW.set_by, NEW.note);
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    _trigger(
        "trg_platform_environment_record_history",
        "platform_environment",
        "TRIGGER trg_platform_environment_record_history AFTER INSERT OR UPDATE ON platform_environment "
        "FOR EACH ROW EXECUTE FUNCTION platform_environment_record_history()",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_environment_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            found_count BIGINT := 0;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'platform_environment marker cannot be deleted' USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'INSERT' AND EXISTS (
                SELECT 1 FROM platform_environment_history WHERE environment = 'production'
            ) THEN
                RAISE EXCEPTION 'platform_environment: a production marker was recorded before; re-insert refused'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.environment = 'production' AND NEW.environment <> 'production' THEN
                RAISE EXCEPTION 'platform_environment: production marker cannot be downgraded to %', NEW.environment
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.environment = 'production' AND to_regclass('public.wallet_accounts') IS NOT NULL THEN
                EXECUTE 'SELECT count(*) FROM wallet_accounts WHERE test_overdraft_allowed' INTO found_count;
                IF found_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: % wallet(s) have test_overdraft_allowed; cannot mark production',
                        found_count USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            IF NEW.environment = 'production' AND to_regclass('public.feature_flag_values') IS NOT NULL
               AND (SELECT count(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature_flag_values'
                      AND column_name IN ('flag_key', 'enabled')) = 2 THEN
                EXECUTE 'SELECT count(*) FROM feature_flag_values WHERE flag_key = ''wallet_required'' AND NOT enabled'
                    INTO found_count;
                IF found_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: wallet_required=false flag rows exist; cannot mark production'
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in ("platform_environment", "platform_environment_history"):
        _trigger(
            f"trg_{table}_no_truncate",
            table,
            f"TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION wallet_reject_mutation()",
        )
    _trigger(
        "trg_platform_environment_history_immutable",
        "platform_environment_history",
        "TRIGGER trg_platform_environment_history_immutable BEFORE UPDATE OR DELETE ON platform_environment_history "
        "FOR EACH ROW EXECUTE FUNCTION wallet_reject_mutation()",
    )

    # --- #2 fail-closed marker checks (missing marker = production) ------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wallet_accounts_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'wallet_accounts cannot be deleted' USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'UPDATE' AND (NEW.id, NEW.public_id, NEW.driver_user_id, NEW.ledger_account_id, NEW.currency,
                                    NEW.created_at)
                    IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.driver_user_id, OLD.ledger_account_id, OLD.currency,
                                      OLD.created_at) THEN
                RAISE EXCEPTION 'wallet_accounts identity columns are immutable' USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.test_overdraft_allowed AND NOT EXISTS (
                SELECT 1 FROM platform_environment WHERE id = 1 AND environment <> 'production'
            ) THEN
                RAISE EXCEPTION 'test_overdraft_allowed is forbidden in production (platform_environment production or missing)'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION feature_flag_wallet_required_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.flag_key = 'wallet_required' AND NOT NEW.enabled AND NOT EXISTS (
                SELECT 1 FROM platform_environment WHERE id = 1 AND environment <> 'production'
            ) THEN
                RAISE EXCEPTION 'wallet_required cannot be false in production (platform_environment production or missing)'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    # --- decision 28 + #7 + #6: commission policies -----------------------------------------------
    op.execute("ALTER TABLE commission_policies ADD COLUMN IF NOT EXISTS confirmed_by INTEGER REFERENCES users (id)")
    op.execute("ALTER TABLE commission_policies ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_commission_policies_confirm_pair') THEN
                ALTER TABLE commission_policies ADD CONSTRAINT ck_commission_policies_confirm_pair
                    CHECK ((confirmed_by IS NULL) = (confirmed_at IS NULL));
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION commission_policies_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'commission_policies are immutable (delete)' USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.effective_from < now() - {POLICY_CLOCK_TOLERANCE_SQL} THEN
                    RAISE EXCEPTION 'commission_policies: retroactive effective_from %', NEW.effective_from
                        USING ERRCODE = 'check_violation';
                END IF;
                NEW.effective_from := GREATEST(NEW.effective_from, now());
                IF NEW.confirmed_by IS NOT NULL OR NEW.confirmed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'commission_policies: confirmation is a separate one-time step'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.id, NEW.public_id, NEW.kind, NEW.scope_corridor_id, NEW.scope_service_type, NEW.fee_bps,
                NEW.effective_from, NEW.campaign_name, NEW.reason, NEW.created_by, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.public_id, OLD.kind, OLD.scope_corridor_id, OLD.scope_service_type, OLD.fee_bps,
                OLD.effective_from, OLD.campaign_name, OLD.reason, OLD.created_by, OLD.created_at) THEN
                RAISE EXCEPTION 'commission_policies are immutable; only a one-time end or seed confirmation is allowed'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'commission_policies: version must increase by one' USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at THEN
                IF OLD.confirmed_by IS NOT NULL OR OLD.created_by IS NOT NULL
                   OR NEW.confirmed_by IS NULL OR NEW.confirmed_at IS NULL THEN
                    RAISE EXCEPTION 'commission_policies: only an unconfirmed migration seed can be confirmed, once'
                        USING ERRCODE = 'check_violation';
                END IF;
                IF (NEW.effective_to, NEW.ended_by, NEW.ended_reason)
                   IS DISTINCT FROM (OLD.effective_to, OLD.ended_by, OLD.ended_reason) THEN
                    RAISE EXCEPTION 'commission_policies: confirmation cannot change other fields'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.ended_by IS NOT NULL THEN
                RAISE EXCEPTION 'commission_policies: policy % already ended', OLD.id USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.ended_by IS NULL OR NEW.effective_to IS NULL THEN
                RAISE EXCEPTION 'commission_policies: ending requires ended_by and effective_to'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.effective_to IS NOT NULL AND OLD.effective_to <= now() THEN
                RAISE EXCEPTION 'commission_policies: policy % already expired', OLD.id USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.effective_to < now() - {POLICY_CLOCK_TOLERANCE_SQL} THEN
                RAISE EXCEPTION 'commission_policies: retroactive effective_to %', NEW.effective_to
                    USING ERRCODE = 'check_violation';
            END IF;
            NEW.effective_to := GREATEST(NEW.effective_to, now());
            IF OLD.effective_to IS NOT NULL AND NEW.effective_to > OLD.effective_to THEN
                RAISE EXCEPTION 'commission_policies: effective_to may only be shortened' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION commission_policies_global_successor() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.kind = 'standard' AND NEW.scope_corridor_id IS NULL AND NEW.scope_service_type IS NULL
               AND NEW.effective_to IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM commission_policies p
                WHERE p.id <> NEW.id AND p.kind = 'standard' AND p.scope_corridor_id IS NULL
                  AND p.scope_service_type IS NULL AND p.effective_from = NEW.effective_to
            ) THEN
                RAISE EXCEPTION 'commission_policies: global standard % cannot end at % without a successor',
                    NEW.id, NEW.effective_to USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    _constraint_trigger(
        "trg_commission_policies_global_successor", "commission_policies", "INSERT OR UPDATE",
        "commission_policies_global_successor",
    )

    # --- #4 adjustment request rejection -----------------------------------------------------------
    op.execute(
        "ALTER TABLE ledger_adjustment_requests ADD COLUMN IF NOT EXISTS rejected_by INTEGER REFERENCES users (id)"
    )
    op.execute("ALTER TABLE ledger_adjustment_requests ADD COLUMN IF NOT EXISTS reject_reason TEXT")
    op.execute("ALTER TABLE ledger_adjustment_requests ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ledger_adjustment_requests_rejection') THEN
                ALTER TABLE ledger_adjustment_requests ADD CONSTRAINT ck_ledger_adjustment_requests_rejection
                    CHECK (status <> 'rejected' OR (rejected_by IS NOT NULL AND reject_reason IS NOT NULL));
            END IF;
        END
        $$;
        """
    )

    # --- #8 running balance per driver liability account -------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_account_balances (
            account_id BIGINT PRIMARY KEY REFERENCES ledger_accounts (id),
            balance_minor BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Backfill before (or despite) the writer guard; DO NOTHING keeps trigger-maintained rows on re-run.
    # N7 (wave 1.6): block concurrent entry inserts while summing; 0047 rebuilds balances under an
    # ACCESS EXCLUSIVE lock and replaces this session-setting guard with a pg_trigger_depth() guard.
    op.execute("LOCK TABLE public.ledger_entries IN SHARE ROW EXCLUSIVE MODE")
    op.execute("SELECT set_config('elchi.ledger_balance_writer', 'on', true)")
    op.execute(
        """
        INSERT INTO ledger_account_balances (account_id, balance_minor)
        SELECT e.account_id, sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor ELSE -e.amount_minor END)
        FROM ledger_entries e JOIN ledger_accounts a ON a.id = e.account_id AND a.kind = 'liability'
        GROUP BY e.account_id
        ON CONFLICT (account_id) DO NOTHING
        """
    )
    op.execute("SELECT set_config('elchi.ledger_balance_writer', 'off', true)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ledger_account_balances_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('elchi.ledger_balance_writer', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'ledger_account_balances is maintained by trigger only (%)', TG_OP
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )
    _trigger(
        "trg_ledger_account_balances_guard",
        "ledger_account_balances",
        "TRIGGER trg_ledger_account_balances_guard BEFORE INSERT OR UPDATE OR DELETE ON ledger_account_balances "
        "FOR EACH ROW EXECUTE FUNCTION ledger_account_balances_guard()",
    )
    _trigger(
        "trg_ledger_account_balances_no_truncate",
        "ledger_account_balances",
        "TRIGGER trg_ledger_account_balances_no_truncate BEFORE TRUNCATE ON ledger_account_balances "
        "FOR EACH STATEMENT EXECUTE FUNCTION wallet_reject_mutation()",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ledger_entries_apply_balance() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
            delta BIGINT;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM ledger_accounts WHERE id = NEW.account_id AND kind = 'liability') THEN
                RETURN NULL;  -- system accounts: no hot balance row (captures would serialize on revenue)
            END IF;
            IF NEW.direction = 'credit' THEN
                delta := NEW.amount_minor;
            ELSE
                delta := -NEW.amount_minor;
            END IF;
            PERFORM set_config('elchi.ledger_balance_writer', 'on', true);
            INSERT INTO ledger_account_balances AS b (account_id, balance_minor, updated_at)
            VALUES (NEW.account_id, delta, now())
            ON CONFLICT (account_id) DO UPDATE
                SET balance_minor = b.balance_minor + EXCLUDED.balance_minor, updated_at = now();
            PERFORM set_config('elchi.ledger_balance_writer', 'off', true);
            RETURN NULL;
        END;
        $$
        """
    )
    _trigger(
        "trg_ledger_entries_apply_balance",
        "ledger_entries",
        "TRIGGER trg_ledger_entries_apply_balance AFTER INSERT ON ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION ledger_entries_apply_balance()",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wallet_assert_cache_consistent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            target_wallet BIGINT;
            w RECORD;
            ledger_balance BIGINT;
            active_holds BIGINT;
        BEGIN
            IF TG_TABLE_NAME = 'wallet_accounts' THEN
                target_wallet := NEW.id;
            ELSIF TG_TABLE_NAME = 'wallet_holds' THEN
                target_wallet := NEW.wallet_id;
            ELSE
                -- ledger_entries and ledger_account_balances both carry account_id
                SELECT id INTO target_wallet FROM wallet_accounts WHERE ledger_account_id = NEW.account_id;
                IF target_wallet IS NULL THEN
                    RETURN NULL;
                END IF;
            END IF;
            SELECT id, ledger_account_id, posted_balance_minor, held_minor INTO w
            FROM wallet_accounts WHERE id = target_wallet;
            SELECT COALESCE((SELECT balance_minor FROM ledger_account_balances WHERE account_id = w.ledger_account_id), 0)
              INTO ledger_balance;
            SELECT COALESCE(sum(amount_minor), 0) INTO active_holds
              FROM wallet_holds WHERE wallet_id = w.id AND status = 'active';
            IF w.posted_balance_minor <> ledger_balance THEN
                RAISE EXCEPTION 'wallet % posted_balance_minor % differs from ledger %', w.id, w.posted_balance_minor,
                    ledger_balance USING ERRCODE = 'check_violation';
            END IF;
            IF w.held_minor <> active_holds THEN
                RAISE EXCEPTION 'wallet % held_minor % differs from active holds %', w.id, w.held_minor, active_holds
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    _constraint_trigger(
        "trg_ledger_account_balances_cache_consistent", "ledger_account_balances", "INSERT OR UPDATE",
        "wallet_assert_cache_consistent",
    )

    # --- decision 36: app-role grants (only when a separate role is configured and exists) ---------
    apply_app_role_grants(bind, os.environ.get("ELCHI_DB_APP_ROLE"))


def downgrade() -> None:
    # Not a rollback strategy (spec §18.3).
    pass
