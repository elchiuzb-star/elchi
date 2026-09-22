"""wallet: ledger accounts, wallet accounts, holds, ledger transactions/entries, top-ups

Owner: A3 (wave 1) - module `wallet`.
Content (DATA_MODEL.md §1.6, §5): ledger_accounts (+ system account seed); wallet_accounts
(UNIQUE driver+currency, held >= 0, CHECK posted - held >= 0 OR test_overdraft_allowed);
wallet_holds (UNIQUE booking_id+charge_kind, amount_minor > 0, 0 <= reversed_minor <=
captured_minor, state-guard trigger; booking_id FK added later by A4, migration 0045+);
ledger_transactions (UNIQUE reference_kind+reference_key, reversal_of_id NOT unique,
immutable); ledger_entries (amount > 0, immutable, deferred balance constraint trigger);
topup_requests (partial unique source reference, distinct second approver, terminal rows
frozen); reconciliation_runs.
Additions (reported to A0a for DATA_MODEL):
  * ledger_adjustment_requests - two-person rule for large manual adjustments (Q17);
  * deferred constraint trigger keeping wallet_accounts.posted_balance_minor equal to the
    ledger and held_minor equal to active holds (balance cache cannot drift);
  * BR N1 trigger: test_overdraft_allowed = true is rejected while
    platform_environment.environment = 'production';
  * wallet_holds.fee_bps / booking_public_id snapshot columns (adjust_hold keeps bps, D10).
Tables: ledger_accounts, wallet_accounts, wallet_holds, ledger_transactions, ledger_entries,
topup_requests, ledger_adjustment_requests, reconciliation_runs.
FK dependencies: users (legacy), platform_environment (0031), commission_policies (0036).

Rules: idempotent; do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0041
Revises: 20260913_0040
Create Date: 2026-09-13 00:41:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0041"
down_revision: str = "20260913_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def _constraint_trigger(name: str, table: str, events: str, function: str) -> None:
    # Constraint triggers have no IF NOT EXISTS; drop-and-create keeps upgrade re-runnable.
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {name} AFTER {events} ON {table} "
        f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {function}()"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- shared guard functions -------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wallet_reject_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is immutable (%)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'check_violation';
        END;
        $$
        """
    )

    # --- ledger_accounts ----------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_accounts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            code VARCHAR(64) NOT NULL,
            kind VARCHAR(16) NOT NULL,
            owner_user_id INTEGER REFERENCES users (id),
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ledger_accounts_code_currency UNIQUE (code, currency),
            CONSTRAINT ck_ledger_accounts_kind CHECK (kind IN ('asset', 'liability', 'revenue', 'contra')),
            CONSTRAINT ck_ledger_accounts_currency CHECK (currency = 'UZS')
        )
        """
    )
    _trigger(
        "trg_ledger_accounts_immutable",
        "ledger_accounts",
        "TRIGGER trg_ledger_accounts_immutable BEFORE UPDATE OR DELETE ON ledger_accounts "
        "FOR EACH ROW EXECUTE FUNCTION wallet_reject_mutation()",
    )
    op.execute(
        """
        INSERT INTO ledger_accounts (code, kind, currency) VALUES
            ('cash_bank', 'asset', 'UZS'),
            ('cash_desk', 'asset', 'UZS'),
            ('commission_revenue', 'revenue', 'UZS'),
            ('manual_adjustments', 'contra', 'UZS')
        ON CONFLICT (code, currency) DO NOTHING
        """
    )

    # --- wallet_accounts ----------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_accounts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            driver_user_id INTEGER NOT NULL REFERENCES users (id),
            ledger_account_id BIGINT NOT NULL REFERENCES ledger_accounts (id),
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            posted_balance_minor BIGINT NOT NULL DEFAULT 0,
            held_minor BIGINT NOT NULL DEFAULT 0,
            test_overdraft_allowed BOOLEAN NOT NULL DEFAULT false,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_wallet_accounts_public_id UNIQUE (public_id),
            CONSTRAINT uq_wallet_accounts_driver_currency UNIQUE (driver_user_id, currency),
            CONSTRAINT uq_wallet_accounts_ledger_account UNIQUE (ledger_account_id),
            CONSTRAINT ck_wallet_accounts_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_wallet_accounts_held_non_negative CHECK (held_minor >= 0),
            CONSTRAINT ck_wallet_accounts_available_non_negative
                CHECK (posted_balance_minor - held_minor >= 0 OR test_overdraft_allowed),
            CONSTRAINT ck_wallet_accounts_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wallet_accounts_test_overdraft ON wallet_accounts (id) "
        "WHERE test_overdraft_allowed"
    )
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
            -- BR N1: overdraft wallets may never exist in a production database.
            IF NEW.test_overdraft_allowed AND EXISTS (
                SELECT 1 FROM platform_environment WHERE id = 1 AND environment = 'production'
            ) THEN
                RAISE EXCEPTION 'test_overdraft_allowed is forbidden in production (platform_environment)'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_wallet_accounts_guard",
        "wallet_accounts",
        "TRIGGER trg_wallet_accounts_guard BEFORE INSERT OR UPDATE OR DELETE ON wallet_accounts "
        "FOR EACH ROW EXECUTE FUNCTION wallet_accounts_guard()",
    )

    # --- ledger_transactions / ledger_entries ------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_transactions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            reference_kind VARCHAR(32) NOT NULL,
            reference_key VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            reversal_of_id BIGINT REFERENCES ledger_transactions (id),
            wallet_id BIGINT REFERENCES wallet_accounts (id),
            booking_id BIGINT,
            created_by INTEGER REFERENCES users (id),
            second_approver_id INTEGER REFERENCES users (id),
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ledger_transactions_public_id UNIQUE (public_id),
            CONSTRAINT uq_ledger_transactions_reference UNIQUE (reference_kind, reference_key),
            CONSTRAINT ck_ledger_transactions_reference_kind
                CHECK (reference_kind IN ('topup', 'commission_capture', 'commission_reversal', 'adjustment')),
            CONSTRAINT ck_ledger_transactions_distinct_approver
                CHECK (second_approver_id IS NULL OR created_by IS NULL OR second_approver_id <> created_by),
            CONSTRAINT ck_ledger_transactions_evidence_object CHECK (jsonb_typeof(evidence) = 'object'),
            CONSTRAINT ck_ledger_transactions_reversal_link
                CHECK (reference_kind <> 'commission_reversal' OR reversal_of_id IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ledger_transactions_reversal_of_id ON ledger_transactions (reversal_of_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ledger_transactions_wallet_id ON ledger_transactions (wallet_id, id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_entries (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            transaction_id BIGINT NOT NULL REFERENCES ledger_transactions (id),
            account_id BIGINT NOT NULL REFERENCES ledger_accounts (id),
            direction VARCHAR(6) NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_ledger_entries_direction CHECK (direction IN ('debit', 'credit')),
            CONSTRAINT ck_ledger_entries_amount_positive CHECK (amount_minor > 0),
            CONSTRAINT ck_ledger_entries_currency CHECK (currency = 'UZS')
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ledger_entries_transaction_id ON ledger_entries (transaction_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ledger_entries_account_id ON ledger_entries (account_id, id)")
    for table in ("ledger_transactions", "ledger_entries"):
        _trigger(
            f"trg_{table}_immutable",
            table,
            f"TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION wallet_reject_mutation()",
        )
        _trigger(
            f"trg_{table}_no_truncate",
            table,
            f"TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION wallet_reject_mutation()",
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ledger_assert_transaction_balanced() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            tx_id BIGINT;
            entry_count BIGINT;
            unbalanced_currency CHAR(3);
        BEGIN
            -- PL/pgSQL resolves every NEW.field in an expression, so branch with IF, not CASE.
            IF TG_TABLE_NAME = 'ledger_entries' THEN
                tx_id := NEW.transaction_id;
            ELSE
                tx_id := NEW.id;
            END IF;
            SELECT count(*) INTO entry_count FROM ledger_entries WHERE transaction_id = tx_id;
            IF entry_count < 2 THEN
                RAISE EXCEPTION 'LEDGER_UNBALANCED: transaction % has % entries', tx_id, entry_count
                    USING ERRCODE = 'check_violation';
            END IF;
            SELECT currency INTO unbalanced_currency
            FROM ledger_entries
            WHERE transaction_id = tx_id
            GROUP BY currency
            HAVING sum(CASE WHEN direction = 'debit' THEN amount_minor ELSE 0 END)
                <> sum(CASE WHEN direction = 'credit' THEN amount_minor ELSE 0 END)
            LIMIT 1;
            IF unbalanced_currency IS NOT NULL THEN
                RAISE EXCEPTION 'LEDGER_UNBALANCED: transaction % is unbalanced in %', tx_id, unbalanced_currency
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    _constraint_trigger(
        "trg_ledger_entries_balanced", "ledger_entries", "INSERT", "ledger_assert_transaction_balanced"
    )
    _constraint_trigger(
        "trg_ledger_transactions_has_entries", "ledger_transactions", "INSERT", "ledger_assert_transaction_balanced"
    )

    # --- wallet_holds -------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_holds (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            wallet_id BIGINT NOT NULL REFERENCES wallet_accounts (id),
            booking_id BIGINT NOT NULL,
            booking_public_id VARCHAR(64),
            charge_kind VARCHAR(16) NOT NULL,
            fee_bps INTEGER NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            status VARCHAR(16) NOT NULL,
            captured_minor BIGINT NOT NULL DEFAULT 0,
            reversed_minor BIGINT NOT NULL DEFAULT 0,
            capture_transaction_id BIGINT REFERENCES ledger_transactions (id),
            escalate_at TIMESTAMPTZ,
            resolved_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_wallet_holds_booking_charge UNIQUE (booking_id, charge_kind),
            CONSTRAINT ck_wallet_holds_charge_kind CHECK (charge_kind IN ('commission')),
            CONSTRAINT ck_wallet_holds_status CHECK (status IN ('active', 'captured', 'released')),
            CONSTRAINT ck_wallet_holds_fee_bps CHECK (fee_bps BETWEEN 1 AND 10000),
            CONSTRAINT ck_wallet_holds_amount_positive CHECK (amount_minor > 0),
            CONSTRAINT ck_wallet_holds_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_wallet_holds_reversal_bounds
                CHECK (captured_minor >= 0 AND reversed_minor >= 0 AND reversed_minor <= captured_minor),
            CONSTRAINT ck_wallet_holds_capture_consistent CHECK (
                (status = 'captured') = (capture_transaction_id IS NOT NULL)
                AND (status = 'captured' OR captured_minor = 0)
                AND (status <> 'captured' OR captured_minor = amount_minor)
            ),
            CONSTRAINT ck_wallet_holds_resolution CHECK ((status = 'active') = (resolved_at IS NULL)),
            CONSTRAINT ck_wallet_holds_version CHECK (version >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_wallet_holds_wallet_status ON wallet_holds (wallet_id, status)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wallet_holds_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'wallet_holds cannot be deleted' USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'active' THEN
                    RAISE EXCEPTION 'wallet_holds must be created active' USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.wallet_id, NEW.booking_id, NEW.charge_kind, NEW.fee_bps, NEW.currency, NEW.created_at)
               IS DISTINCT FROM (OLD.wallet_id, OLD.booking_id, OLD.charge_kind, OLD.fee_bps, OLD.currency, OLD.created_at) THEN
                RAISE EXCEPTION 'wallet_holds identity columns are immutable' USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.status = 'active' THEN
                RETURN NEW;  -- adjust (amount), capture or release; CHECKs validate the target row
            END IF;
            -- captured/released are terminal: only reversed_minor may grow on captured holds (D4).
            IF NEW.status <> OLD.status
               OR NEW.amount_minor <> OLD.amount_minor
               OR NEW.captured_minor <> OLD.captured_minor
               OR NEW.capture_transaction_id IS DISTINCT FROM OLD.capture_transaction_id
               OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at
               OR NEW.reversed_minor < OLD.reversed_minor THEN
                RAISE EXCEPTION 'wallet_holds: % hold % is terminal', OLD.status, OLD.id USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_wallet_holds_guard",
        "wallet_holds",
        "TRIGGER trg_wallet_holds_guard BEFORE INSERT OR UPDATE OR DELETE ON wallet_holds "
        "FOR EACH ROW EXECUTE FUNCTION wallet_holds_guard()",
    )

    # --- balance cache consistency (deferred, per wallet) -------------------------------------------
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
                SELECT id INTO target_wallet FROM wallet_accounts WHERE ledger_account_id = NEW.account_id;
                IF target_wallet IS NULL THEN
                    RETURN NULL;  -- system account entry
                END IF;
            END IF;
            SELECT id, ledger_account_id, posted_balance_minor, held_minor INTO w
            FROM wallet_accounts WHERE id = target_wallet;
            SELECT COALESCE(sum(CASE WHEN direction = 'credit' THEN amount_minor ELSE -amount_minor END), 0)
              INTO ledger_balance FROM ledger_entries WHERE account_id = w.ledger_account_id;
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
        "trg_wallet_accounts_cache_consistent", "wallet_accounts", "INSERT OR UPDATE", "wallet_assert_cache_consistent"
    )
    _constraint_trigger(
        "trg_wallet_holds_cache_consistent", "wallet_holds", "INSERT OR UPDATE", "wallet_assert_cache_consistent"
    )
    _constraint_trigger(
        "trg_ledger_entries_cache_consistent", "ledger_entries", "INSERT", "wallet_assert_cache_consistent"
    )

    # --- topup_requests -------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS topup_requests (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            driver_user_id INTEGER NOT NULL REFERENCES users (id),
            wallet_id BIGINT NOT NULL REFERENCES wallet_accounts (id),
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            method VARCHAR(16) NOT NULL,
            payer_reference VARCHAR(128),
            evidence_file_id VARCHAR(128),
            note TEXT,
            status VARCHAR(32) NOT NULL,
            source_type VARCHAR(32),
            source_reference VARCHAR(128),
            received_amount_minor BIGINT,
            received_at TIMESTAMPTZ,
            first_approver_id INTEGER REFERENCES users (id),
            second_approver_id INTEGER REFERENCES users (id),
            rejected_by INTEGER REFERENCES users (id),
            reject_reason TEXT,
            decided_at TIMESTAMPTZ,
            ledger_transaction_id BIGINT REFERENCES ledger_transactions (id),
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_topup_requests_public_id UNIQUE (public_id),
            CONSTRAINT ck_topup_requests_amount_positive CHECK (amount_minor > 0),
            CONSTRAINT ck_topup_requests_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_topup_requests_method CHECK (method IN ('bank_transfer', 'cash_desk')),
            CONSTRAINT ck_topup_requests_status
                CHECK (status IN ('pending', 'awaiting_second_approval', 'approved', 'rejected')),
            CONSTRAINT ck_topup_requests_source_type
                CHECK (source_type IS NULL OR source_type IN ('bank_statement', 'cashier_receipt')),
            CONSTRAINT ck_topup_requests_received_positive
                CHECK (received_amount_minor IS NULL OR received_amount_minor > 0),
            CONSTRAINT ck_topup_requests_distinct_approvers
                CHECK (second_approver_id IS NULL OR second_approver_id <> first_approver_id),
            CONSTRAINT ck_topup_requests_source_when_approving CHECK (
                status NOT IN ('awaiting_second_approval', 'approved')
                OR (source_type IS NOT NULL AND source_reference IS NOT NULL
                    AND received_amount_minor IS NOT NULL AND first_approver_id IS NOT NULL)
            ),
            CONSTRAINT ck_topup_requests_posting_iff_approved
                CHECK ((status = 'approved') = (ledger_transaction_id IS NOT NULL)),
            CONSTRAINT ck_topup_requests_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_topup_requests_source_reference "
        "ON topup_requests (source_type, source_reference) "
        "WHERE status IN ('awaiting_second_approval', 'approved')"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_topup_requests_driver ON topup_requests (driver_user_id, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_topup_requests_status ON topup_requests (status, id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wallet_terminal_request_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION '% rows cannot be deleted', TG_TABLE_NAME USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.status IN ('approved', 'rejected', 'posted') THEN
                RAISE EXCEPTION '% % is terminal (%)', TG_TABLE_NAME, OLD.id, OLD.status USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_topup_requests_guard",
        "topup_requests",
        "TRIGGER trg_topup_requests_guard BEFORE UPDATE OR DELETE ON topup_requests "
        "FOR EACH ROW EXECUTE FUNCTION wallet_terminal_request_guard()",
    )

    # --- ledger_adjustment_requests (Q17 two-person rule) ------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_adjustment_requests (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            wallet_id BIGINT NOT NULL REFERENCES wallet_accounts (id),
            direction VARCHAR(6) NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            reason TEXT NOT NULL,
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            booking_id BIGINT,
            reversal_of_transaction_id BIGINT REFERENCES ledger_transactions (id),
            status VARCHAR(32) NOT NULL,
            requested_by INTEGER NOT NULL REFERENCES users (id),
            approved_by INTEGER REFERENCES users (id),
            ledger_transaction_id BIGINT REFERENCES ledger_transactions (id),
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ledger_adjustment_requests_public_id UNIQUE (public_id),
            CONSTRAINT ck_ledger_adjustment_requests_direction CHECK (direction IN ('debit', 'credit')),
            CONSTRAINT ck_ledger_adjustment_requests_amount CHECK (amount_minor > 0),
            CONSTRAINT ck_ledger_adjustment_requests_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_ledger_adjustment_requests_status
                CHECK (status IN ('pending_second_approval', 'posted', 'rejected')),
            CONSTRAINT ck_ledger_adjustment_requests_distinct_approver
                CHECK (approved_by IS NULL OR approved_by <> requested_by),
            CONSTRAINT ck_ledger_adjustment_requests_posted
                CHECK ((status = 'posted') = (ledger_transaction_id IS NOT NULL)),
            CONSTRAINT ck_ledger_adjustment_requests_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ledger_adjustment_requests_status ON ledger_adjustment_requests (status, id)"
    )
    _trigger(
        "trg_ledger_adjustment_requests_guard",
        "ledger_adjustment_requests",
        "TRIGGER trg_ledger_adjustment_requests_guard BEFORE UPDATE OR DELETE ON ledger_adjustment_requests "
        "FOR EACH ROW EXECUTE FUNCTION wallet_terminal_request_guard()",
    )

    # --- reconciliation_runs --------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reconciliation_runs (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_date DATE NOT NULL,
            wallets_checked INTEGER NOT NULL,
            mismatch_count INTEGER NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_reconciliation_runs_run_date UNIQUE (run_date),
            CONSTRAINT ck_reconciliation_runs_counts CHECK (wallets_checked >= 0 AND mismatch_count >= 0)
        )
        """
    )

    # BR N1 / DATA_MODEL §1.1: on a production marker, reject wallet_required=false rows in A2's
    # flag table (service-level FLAG_LOCKED_IN_ENVIRONMENT stays A2's). Guarded: skipped if the
    # table or its columns are absent; coordinated with A2 via the report.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION feature_flag_wallet_required_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.flag_key = 'wallet_required' AND NOT NEW.enabled AND EXISTS (
                SELECT 1 FROM platform_environment WHERE id = 1 AND environment = 'production'
            ) THEN
                RAISE EXCEPTION 'wallet_required cannot be false in production (platform_environment)'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.feature_flag_values') IS NOT NULL
               AND (SELECT count(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature_flag_values'
                      AND column_name IN ('flag_key', 'enabled')) = 2 THEN
                DROP TRIGGER IF EXISTS trg_feature_flag_wallet_required_guard ON feature_flag_values;
                CREATE TRIGGER trg_feature_flag_wallet_required_guard
                    BEFORE INSERT OR UPDATE ON feature_flag_values
                    FOR EACH ROW EXECUTE FUNCTION feature_flag_wallet_required_guard();
            END IF;
        END
        $$;
        """
    )

    # Retry the corridor FK of 0036 in case the geo catalogue was created after it (idempotent).
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.service_corridors') IS NOT NULL
               AND to_regclass('public.commission_policies') IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_commission_policies_scope_corridor') THEN
                ALTER TABLE commission_policies
                    ADD CONSTRAINT fk_commission_policies_scope_corridor
                    FOREIGN KEY (scope_corridor_id) REFERENCES service_corridors (id);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (spec §18.3); ledger history must never be dropped.
    pass
