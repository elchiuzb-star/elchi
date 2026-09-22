"""wallet balance guard + adjustment withdraw (wave 1.6)

Owner: A3 (wave 1.6) - modules `wallet`, `platform`.
Content (DATA_MODEL.md §5, wave 1.6 BR re-review):
  * N1: ``ledger_account_balances`` may only be written from inside the ledger trigger chain
    (``pg_trigger_depth() >= 2``); the session-setting guard of 0042 is gone (any role could set it).
    Every driver-liability ledger entry now carries an immutable, database-assigned
    ``account_seq`` and ``running_balance_minor`` (computed under the balance row lock in a BEFORE
    INSERT SECURITY DEFINER trigger). The deferred cache check compares the balance row with the
    latest entry's running total, so forging the balance row and ``wallet_accounts.posted_balance_minor``
    together is detected at commit even if the guard were bypassed.
  * N2: SECURITY DEFINER functions use ``search_path = pg_catalog, public, pg_temp`` (pg_temp last)
    and schema-qualify every table.
  * N7: the running-balance backfill runs under ACCESS EXCLUSIVE locks on ledger_entries and
    ledger_account_balances (no concurrent entry can be missed) and only fills rows without a sequence.
  * Q49: ledger_adjustment_requests status ``withdrawn`` (requester only); CHECK rejected_by <> requested_by;
    terminal guard includes ``withdrawn``.
  * Marker: switching platform_environment to production is refused while passenger/card flag rows are
    enabled without an approval reference (Q5/K7), in addition to the 0042 checks.
Q48: no production v2 money flow until this and the DB role split (Q36) are in (launch gate).

Rules: idempotent (CREATE OR REPLACE / guarded DO blocks); do not change the revision id, file
name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260914_0047
Revises: 20260914_0046
Create Date: 2026-09-14 00:47:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0047"
down_revision: str = "20260914_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def backfill_running_balances(bind) -> None:
    """Assign account_seq/running_balance_minor to driver-liability entries that lack them and
    rebuild ledger_account_balances from the entries. Caller holds the transaction (N7).

    Exported for the PG test. Takes ACCESS EXCLUSIVE locks so no entry is inserted meanwhile and
    bypasses the immutability/writer guards only inside this locked transaction.
    """
    bind.execute(sa.text("LOCK TABLE public.ledger_entries IN ACCESS EXCLUSIVE MODE"))
    bind.execute(sa.text("LOCK TABLE public.ledger_account_balances IN ACCESS EXCLUSIVE MODE"))
    missing = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM public.ledger_entries e JOIN public.ledger_accounts a "
        "ON a.id = e.account_id AND a.kind = 'liability' WHERE e.account_seq IS NULL)"
    )).scalar_one()
    if missing:
        bind.execute(sa.text("ALTER TABLE public.ledger_entries DISABLE TRIGGER trg_ledger_entries_immutable"))
        bind.execute(sa.text(
            """
            WITH ordered AS (
                SELECT e.id,
                       row_number() OVER w AS seq,
                       sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor ELSE -e.amount_minor END) OVER w AS running
                FROM public.ledger_entries e
                JOIN public.ledger_accounts a ON a.id = e.account_id AND a.kind = 'liability'
                WINDOW w AS (PARTITION BY e.account_id ORDER BY e.id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            )
            UPDATE public.ledger_entries e
               SET account_seq = o.seq, running_balance_minor = o.running
              FROM ordered o
             WHERE e.id = o.id AND e.account_seq IS NULL
            """
        ))
        bind.execute(sa.text("ALTER TABLE public.ledger_entries ENABLE TRIGGER trg_ledger_entries_immutable"))
    # L2 (wave 1.7): never overwrite a drifted balance row; stop with details so it is investigated.
    drifted = bind.execute(sa.text(
        """
        SELECT b.account_id, b.balance_minor, COALESCE(l.running_balance_minor, 0) AS ledger_running
        FROM public.ledger_account_balances b
        LEFT JOIN (
            SELECT DISTINCT ON (account_id) account_id, running_balance_minor
            FROM public.ledger_entries WHERE account_seq IS NOT NULL ORDER BY account_id, account_seq DESC
        ) l ON l.account_id = b.account_id
        WHERE b.balance_minor <> COALESCE(l.running_balance_minor, 0)
        ORDER BY b.account_id LIMIT 20
        """
    )).all()
    if drifted:
        raise RuntimeError(
            "ledger_account_balances drift detected (account_id, cached, ledger running): "
            f"{[tuple(row) for row in drifted]}. Investigate before migrating; nothing was overwritten."
        )
    # Run the deferred cache checks at statement end so no trigger events are pending when the guard is
    # re-enabled (ALTER TABLE refuses tables with pending events); restored to DEFERRED afterwards.
    bind.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
    bind.execute(sa.text("ALTER TABLE public.ledger_account_balances DISABLE TRIGGER trg_ledger_account_balances_guard"))
    bind.execute(sa.text(
        """
        INSERT INTO public.ledger_account_balances AS b (account_id, balance_minor, last_account_seq, updated_at)
        SELECT DISTINCT ON (e.account_id) e.account_id, e.running_balance_minor, e.account_seq, now()
        FROM public.ledger_entries e
        WHERE e.account_seq IS NOT NULL
        ORDER BY e.account_id, e.account_seq DESC
        ON CONFLICT (account_id) DO UPDATE
            SET balance_minor = EXCLUDED.balance_minor, last_account_seq = EXCLUDED.last_account_seq
            WHERE (b.balance_minor, b.last_account_seq) IS DISTINCT FROM (EXCLUDED.balance_minor, EXCLUDED.last_account_seq)
        """
    ))
    bind.execute(sa.text("ALTER TABLE public.ledger_account_balances ENABLE TRIGGER trg_ledger_account_balances_guard"))
    bind.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- N1: immutable per-entry running balance ----------------------------------------------------
    op.execute("ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS account_seq BIGINT")
    op.execute("ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS running_balance_minor BIGINT")
    op.execute("ALTER TABLE ledger_account_balances ADD COLUMN IF NOT EXISTS last_account_seq BIGINT NOT NULL DEFAULT 0")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_entries_account_seq ON ledger_entries (account_id, account_seq) "
        "WHERE account_seq IS NOT NULL"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ledger_entries_running_pair') THEN
                ALTER TABLE ledger_entries ADD CONSTRAINT ck_ledger_entries_running_pair
                    CHECK ((account_seq IS NULL) = (running_balance_minor IS NULL));
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.ledger_account_balances_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- Only the ledger_entries BEFORE INSERT trigger (depth 1) writes here, so this guard runs at
            -- depth >= 2. Direct statements run at depth 1 whatever session settings are used.
            IF pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'ledger_account_balances is maintained by trigger only (%)', TG_OP
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.ledger_entries_running_balance() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            delta BIGINT;
            new_balance BIGINT;
            new_seq BIGINT;
        BEGIN
            IF NEW.account_seq IS NOT NULL OR NEW.running_balance_minor IS NOT NULL THEN
                RAISE EXCEPTION 'ledger_entries: account_seq and running_balance_minor are assigned by the database'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM public.ledger_accounts WHERE id = NEW.account_id AND kind = 'liability') THEN
                RETURN NEW;  -- system accounts: no hot balance row
            END IF;
            IF NEW.direction = 'credit' THEN
                delta := NEW.amount_minor;
            ELSE
                delta := -NEW.amount_minor;
            END IF;
            INSERT INTO public.ledger_account_balances AS b (account_id, balance_minor, last_account_seq, updated_at)
            VALUES (NEW.account_id, delta, 1, now())
            ON CONFLICT (account_id) DO UPDATE
                SET balance_minor = b.balance_minor + EXCLUDED.balance_minor,
                    last_account_seq = b.last_account_seq + 1,
                    updated_at = now()
            RETURNING b.balance_minor, b.last_account_seq INTO new_balance, new_seq;
            NEW.running_balance_minor := new_balance;
            NEW.account_seq := new_seq;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_apply_balance ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS public.ledger_entries_apply_balance()")
    _trigger(
        "trg_ledger_entries_running_balance",
        "ledger_entries",
        "TRIGGER trg_ledger_entries_running_balance BEFORE INSERT ON ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION public.ledger_entries_running_balance()",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.wallet_assert_cache_consistent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            target_wallet BIGINT;
            w RECORD;
            ledger_balance BIGINT;
            latest_running BIGINT;
            active_holds BIGINT;
        BEGIN
            IF TG_TABLE_NAME = 'wallet_accounts' THEN
                target_wallet := NEW.id;
            ELSIF TG_TABLE_NAME = 'wallet_holds' THEN
                target_wallet := NEW.wallet_id;
            ELSE
                SELECT id INTO target_wallet FROM public.wallet_accounts WHERE ledger_account_id = NEW.account_id;
                IF target_wallet IS NULL THEN
                    RETURN NULL;
                END IF;
            END IF;
            SELECT id, ledger_account_id, posted_balance_minor, held_minor INTO w
            FROM public.wallet_accounts WHERE id = target_wallet;
            SELECT COALESCE((SELECT balance_minor FROM public.ledger_account_balances
                             WHERE account_id = w.ledger_account_id), 0) INTO ledger_balance;
            SELECT COALESCE((SELECT e.running_balance_minor FROM public.ledger_entries e
                             WHERE e.account_id = w.ledger_account_id AND e.account_seq IS NOT NULL
                             ORDER BY e.account_seq DESC LIMIT 1), 0) INTO latest_running;
            SELECT COALESCE(sum(amount_minor), 0) INTO active_holds
              FROM public.wallet_holds WHERE wallet_id = w.id AND status = 'active';
            IF ledger_balance <> latest_running THEN
                RAISE EXCEPTION 'wallet % running balance % differs from latest ledger entry %', w.id, ledger_balance,
                    latest_running USING ERRCODE = 'check_violation';
            END IF;
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
    backfill_running_balances(bind)  # N7

    # --- N2: history writer with a safe search_path ----------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.platform_environment_record_history() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.environment IS DISTINCT FROM OLD.environment THEN
                INSERT INTO public.platform_environment_history (environment, set_by, note)
                VALUES (NEW.environment, NEW.set_by, NEW.note);
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )

    # --- marker: production switch also needs approved passenger/card flags ------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.platform_environment_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            found_count BIGINT := 0;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'platform_environment marker cannot be deleted' USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'INSERT' AND EXISTS (
                SELECT 1 FROM public.platform_environment_history WHERE environment = 'production'
            ) THEN
                RAISE EXCEPTION 'platform_environment: a production marker was recorded before; re-insert refused'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.environment = 'production' AND NEW.environment <> 'production' THEN
                RAISE EXCEPTION 'platform_environment: production marker cannot be downgraded to %', NEW.environment
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.environment <> 'production' THEN
                RETURN NEW;
            END IF;
            IF to_regclass('public.wallet_accounts') IS NOT NULL THEN
                SELECT count(*) INTO found_count FROM public.wallet_accounts WHERE test_overdraft_allowed;
                IF found_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: % wallet(s) have test_overdraft_allowed; cannot mark production',
                        found_count USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            IF to_regclass('public.feature_flag_values') IS NOT NULL
               AND (SELECT count(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature_flag_values'
                      AND column_name IN ('flag_key', 'enabled', 'approval_reference')) = 3 THEN
                EXECUTE 'SELECT count(*) FROM public.feature_flag_values WHERE flag_key = ''wallet_required'' AND NOT enabled'
                    INTO found_count;
                IF found_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: wallet_required=false flag rows exist; cannot mark production'
                        USING ERRCODE = 'check_violation';
                END IF;
                EXECUTE 'SELECT count(*) FROM public.feature_flag_values WHERE flag_key IN (''passenger_enabled'', '
                        '''card_payments_enabled'') AND enabled AND COALESCE(btrim(approval_reference), '''') = '''''
                    INTO found_count;
                IF found_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: % passenger/card flag row(s) enabled without an approval reference; cannot mark production',
                        found_count USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    # --- Q49: withdrawn status, rejecter <> requester ----------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_ledger_adjustment_requests_status'
                  AND pg_get_constraintdef(oid) LIKE '%withdrawn%'
            ) THEN
                ALTER TABLE ledger_adjustment_requests DROP CONSTRAINT IF EXISTS ck_ledger_adjustment_requests_status;
                ALTER TABLE ledger_adjustment_requests ADD CONSTRAINT ck_ledger_adjustment_requests_status
                    CHECK (status IN ('pending_second_approval', 'posted', 'rejected', 'withdrawn'));
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ledger_adjustment_requests_rejecter') THEN
                ALTER TABLE ledger_adjustment_requests ADD CONSTRAINT ck_ledger_adjustment_requests_rejecter
                    CHECK (rejected_by IS NULL OR rejected_by <> requested_by);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ledger_adjustment_requests_withdrawn') THEN
                ALTER TABLE ledger_adjustment_requests ADD CONSTRAINT ck_ledger_adjustment_requests_withdrawn
                    CHECK (status <> 'withdrawn' OR (decided_at IS NOT NULL AND rejected_by IS NULL))
                    ;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.wallet_terminal_request_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION '% rows cannot be deleted', TG_TABLE_NAME USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.status IN ('approved', 'rejected', 'posted', 'withdrawn') THEN
                RAISE EXCEPTION '% % is terminal (%)', TG_TABLE_NAME, OLD.id, OLD.status USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (spec §18.3).
    pass
