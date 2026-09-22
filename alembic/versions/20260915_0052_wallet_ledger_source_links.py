"""wallet ledger source links + Q48 gate function (wave 1.7)

Owner: A3 (wave 1.7) - module `wallet` (Q55, Q56, BR L1).
Content (DATA_MODEL.md §5):
  * Q55: every ledger_transactions row links to exactly one business source:
      - ``topup_request``            -> approved top-up, same wallet, driver credit == received amount,
                                        approvals present (second, different approver above the threshold);
      - ``ledger_adjustment_request`` -> posted plain adjustment, same wallet, driver net == +/- amount,
                                        second different approver above the threshold;
      - ``wallet_hold``               -> capture (hold captured by this transaction, driver debit == captured)
                                        or reversal of that capture (sum of reversal credits == reversed_minor
                                        <= captured).
    ``public.ledger_transaction_source_problem(tx_id)`` returns NULL or the reason; deferred constraint
    triggers on ledger_transactions and ledger_entries INSERT refuse a posting at COMMIT when it has a reason
    (so extra entries appended to an old posting are refused too). No other liability account may appear.
    New topup_requests / ledger_adjustment_requests rows must start pending (an approved source cannot be inserted).
    Existing rows are backfilled under an ACCESS EXCLUSIVE lock; an unlinkable or invalid row fails the migration
    loudly with its ids.
  * Q56: ``public.q48_gate_checks()`` (one row per check) and ``public.q48_gate_ok()`` (boolean), SECURITY
    INVOKER so ``current_user`` is the caller's role; consumed by A2's 0053 and ``platform.service.q48_gate_status``.
  * L1: the platform_environment production switch refuses when the feature_flag_values columns needed for the
    ``wallet_required`` or approval-reference checks are missing (no silent skip); the two checks are independent.
FK / object dependencies: 0041 (ledger/wallet), 0042, 0047, 0048 (bookings).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0052
Revises: 20260915_0051
Create Date: 2026-09-15 00:52:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0052"
down_revision: str = "20260915_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
TWO_PERSON_THRESHOLD_MINOR = 100_000_000  # app.contracts.money.TWO_PERSON_APPROVAL_THRESHOLD_MINOR


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def _constraint_trigger(name: str, table: str, events: str, function: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {name} AFTER {events} ON {table} "
        f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {function}()"
    )


def backfill_source_links(bind) -> None:
    """Link existing postings to their business source and validate every posting (exported for the PG test).

    Raises RuntimeError (the migration stops) listing ids when a posting cannot be linked or its source is invalid.
    """
    bind.execute(sa.text("LOCK TABLE public.ledger_transactions IN ACCESS EXCLUSIVE MODE"))
    missing = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM public.ledger_transactions WHERE source_type IS NULL)"
    )).scalar_one()
    if missing:
        bind.execute(sa.text("ALTER TABLE public.ledger_transactions DISABLE TRIGGER trg_ledger_transactions_immutable"))
        bind.execute(sa.text(
            "UPDATE public.ledger_transactions tx SET source_type = 'topup_request', source_id = t.id "
            "FROM public.topup_requests t WHERE t.ledger_transaction_id = tx.id AND tx.reference_kind = 'topup' "
            "AND tx.source_type IS NULL"
        ))
        bind.execute(sa.text(
            "UPDATE public.ledger_transactions tx SET source_type = 'ledger_adjustment_request', source_id = r.id "
            "FROM public.ledger_adjustment_requests r WHERE r.ledger_transaction_id = tx.id "
            "AND tx.reference_kind = 'adjustment' AND tx.source_type IS NULL"
        ))
        bind.execute(sa.text(
            "UPDATE public.ledger_transactions tx SET source_type = 'wallet_hold', source_id = h.id "
            "FROM public.wallet_holds h WHERE h.capture_transaction_id = tx.id "
            "AND tx.reference_kind = 'commission_capture' AND tx.source_type IS NULL"
        ))
        bind.execute(sa.text(
            "UPDATE public.ledger_transactions tx SET source_type = 'wallet_hold', source_id = h.id "
            "FROM public.wallet_holds h WHERE h.capture_transaction_id = tx.reversal_of_id "
            "AND tx.reference_kind = 'commission_reversal' AND tx.source_type IS NULL"
        ))
        bind.execute(sa.text("ALTER TABLE public.ledger_transactions ENABLE TRIGGER trg_ledger_transactions_immutable"))
    unlinked = bind.execute(sa.text(
        "SELECT id, reference_kind, reference_key FROM public.ledger_transactions WHERE source_type IS NULL "
        "ORDER BY id LIMIT 20"
    )).all()
    if unlinked:
        raise RuntimeError(
            "20260915_0052: ledger transaction(s) cannot be linked to a business source (id, kind, key): "
            f"{[tuple(row) for row in unlinked]}. Investigate before migrating; nothing was changed."
        )
    invalid = bind.execute(sa.text(
        "SELECT id, problem FROM (SELECT id, public.ledger_transaction_source_problem(id) AS problem "
        "FROM public.ledger_transactions) s WHERE problem IS NOT NULL ORDER BY id LIMIT 20"
    )).all()
    if invalid:
        raise RuntimeError(
            "20260915_0052: ledger transaction(s) have an invalid business source (id, problem): "
            f"{[tuple(row) for row in invalid]}. Investigate before migrating; nothing was changed."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- Q55: source columns -------------------------------------------------------------------------
    op.execute("ALTER TABLE ledger_transactions ADD COLUMN IF NOT EXISTS source_type VARCHAR(32)")
    op.execute("ALTER TABLE ledger_transactions ADD COLUMN IF NOT EXISTS source_id BIGINT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ledger_transactions_source ON ledger_transactions (source_type, source_id)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ledger_transactions_source_type') THEN
                ALTER TABLE ledger_transactions ADD CONSTRAINT ck_ledger_transactions_source_type CHECK (
                    source_type IS NULL OR source_type IN ('topup_request', 'ledger_adjustment_request', 'wallet_hold'));
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ledger_transactions_source_pair') THEN
                ALTER TABLE ledger_transactions ADD CONSTRAINT ck_ledger_transactions_source_pair
                    CHECK ((source_type IS NULL) = (source_id IS NULL));
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.ledger_transaction_source_problem(p_tx_id BIGINT) RETURNS TEXT
        LANGUAGE plpgsql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            tx RECORD;
            t RECORD;
            r RECORD;
            h RECORD;
            source_wallet BIGINT;
            driver_account BIGINT;
            net BIGINT;
            expected BIGINT;
            total_reversed BIGINT;
            is_reversal BOOLEAN := false;
            threshold CONSTANT BIGINT := {TWO_PERSON_THRESHOLD_MINOR};
        BEGIN
            SELECT * INTO tx FROM public.ledger_transactions WHERE id = p_tx_id;
            IF NOT FOUND THEN
                RETURN 'transaction_missing';
            END IF;
            IF tx.source_type IS NULL OR tx.source_id IS NULL THEN
                RETURN 'source_missing';
            END IF;
            IF tx.source_type = 'topup_request' THEN
                IF tx.reference_kind <> 'topup' THEN
                    RETURN 'source_kind_mismatch';
                END IF;
                SELECT * INTO t FROM public.topup_requests WHERE id = tx.source_id;
                IF NOT FOUND THEN
                    RETURN 'topup_missing';
                END IF;
                IF t.status <> 'approved' OR t.ledger_transaction_id IS DISTINCT FROM tx.id THEN
                    RETURN 'topup_not_approved_for_transaction';
                END IF;
                IF t.first_approver_id IS NULL OR t.first_approver_id = t.driver_user_id THEN
                    RETURN 'topup_approval_invalid';
                END IF;
                IF t.received_amount_minor > threshold AND (t.second_approver_id IS NULL
                        OR t.second_approver_id = t.first_approver_id OR t.second_approver_id = t.driver_user_id) THEN
                    RETURN 'topup_second_approval_missing';
                END IF;
                source_wallet := t.wallet_id;
                expected := t.received_amount_minor;
            ELSIF tx.source_type = 'ledger_adjustment_request' THEN
                IF tx.reference_kind <> 'adjustment' THEN
                    RETURN 'source_kind_mismatch';
                END IF;
                SELECT * INTO r FROM public.ledger_adjustment_requests WHERE id = tx.source_id;
                IF NOT FOUND THEN
                    RETURN 'adjustment_missing';
                END IF;
                IF r.status <> 'posted' OR r.ledger_transaction_id IS DISTINCT FROM tx.id
                        OR r.reversal_of_transaction_id IS NOT NULL THEN
                    RETURN 'adjustment_not_posted_for_transaction';
                END IF;
                IF r.amount_minor > threshold AND (r.approved_by IS NULL OR r.approved_by = r.requested_by) THEN
                    RETURN 'adjustment_second_approval_missing';
                END IF;
                source_wallet := r.wallet_id;
                IF r.direction = 'credit' THEN
                    expected := r.amount_minor;
                ELSE
                    expected := -r.amount_minor;
                END IF;
            ELSIF tx.source_type = 'wallet_hold' THEN
                SELECT * INTO h FROM public.wallet_holds WHERE id = tx.source_id;
                IF NOT FOUND THEN
                    RETURN 'hold_missing';
                END IF;
                IF tx.booking_id IS DISTINCT FROM h.booking_id THEN
                    RETURN 'hold_booking_mismatch';
                END IF;
                source_wallet := h.wallet_id;
                IF tx.reference_kind = 'commission_capture' THEN
                    IF h.status <> 'captured' OR h.capture_transaction_id IS DISTINCT FROM tx.id THEN
                        RETURN 'hold_not_captured_by_transaction';
                    END IF;
                    expected := -h.captured_minor;
                ELSIF tx.reference_kind = 'commission_reversal' THEN
                    IF h.status <> 'captured' OR tx.reversal_of_id IS DISTINCT FROM h.capture_transaction_id THEN
                        RETURN 'reversal_not_of_hold_capture';
                    END IF;
                    is_reversal := true;
                ELSE
                    RETURN 'source_kind_mismatch';
                END IF;
            ELSE
                RETURN 'source_type_unknown';
            END IF;
            IF tx.wallet_id IS DISTINCT FROM source_wallet THEN
                RETURN 'wallet_mismatch';
            END IF;
            SELECT ledger_account_id INTO driver_account FROM public.wallet_accounts WHERE id = source_wallet;
            IF EXISTS (
                SELECT 1 FROM public.ledger_entries e JOIN public.ledger_accounts a ON a.id = e.account_id
                WHERE e.transaction_id = tx.id AND a.kind = 'liability' AND e.account_id <> driver_account
            ) THEN
                RETURN 'foreign_liability_entry';
            END IF;
            SELECT COALESCE(sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor ELSE -e.amount_minor END), 0)
              INTO net FROM public.ledger_entries e WHERE e.transaction_id = tx.id AND e.account_id = driver_account;
            IF NOT is_reversal THEN
                IF net <> expected THEN
                    RETURN format('amount_mismatch:%s<>%s', net, expected);
                END IF;
                RETURN NULL;
            END IF;
            IF net <= 0 THEN
                RETURN 'reversal_not_a_credit';
            END IF;
            SELECT COALESCE(sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor ELSE -e.amount_minor END), 0)
              INTO total_reversed
              FROM public.ledger_entries e JOIN public.ledger_transactions rt ON rt.id = e.transaction_id
             WHERE rt.reference_kind = 'commission_reversal' AND rt.reversal_of_id = h.capture_transaction_id
               AND e.account_id = driver_account;
            IF total_reversed <> h.reversed_minor OR total_reversed > h.captured_minor THEN
                RETURN format('reversal_total_mismatch:%s<>%s', total_reversed, h.reversed_minor);
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.ledger_source_link_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            tx_id BIGINT;
            problem TEXT;
        BEGIN
            IF TG_TABLE_NAME = 'ledger_entries' THEN
                tx_id := NEW.transaction_id;
            ELSE
                tx_id := NEW.id;
            END IF;
            problem := public.ledger_transaction_source_problem(tx_id);
            IF problem IS NOT NULL THEN
                RAISE EXCEPTION 'LEDGER_SOURCE_INVALID: transaction % %', tx_id, problem USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    backfill_source_links(bind)
    _constraint_trigger(
        "trg_ledger_transactions_source_link", "ledger_transactions", "INSERT", "public.ledger_source_link_guard"
    )
    _constraint_trigger("trg_ledger_entries_source_link", "ledger_entries", "INSERT", "public.ledger_source_link_guard")

    # --- Q55: sources are created pending (an approved source cannot be inserted directly) ----------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.wallet_request_insert_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.ledger_transaction_id IS NOT NULL
               OR (TG_TABLE_NAME = 'topup_requests' AND NEW.status <> 'pending')
               OR (TG_TABLE_NAME = 'ledger_adjustment_requests' AND NEW.status <> 'pending_second_approval') THEN
                RAISE EXCEPTION '% rows must be created pending without a ledger transaction', TG_TABLE_NAME
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in ("topup_requests", "ledger_adjustment_requests"):
        _trigger(
            f"trg_{table}_insert_pending",
            table,
            f"TRIGGER trg_{table}_insert_pending BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION public.wallet_request_insert_guard()",
        )

    # --- L1: marker switch, independent flag checks, no silent skip --------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.platform_environment_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            found_count BIGINT := 0;
            flag_columns BIGINT := 0;
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
            IF to_regclass('public.feature_flag_values') IS NOT NULL THEN
                SELECT count(*) INTO flag_columns FROM information_schema.columns
                 WHERE table_schema = 'public' AND table_name = 'feature_flag_values'
                   AND column_name IN ('flag_key', 'enabled');
                IF flag_columns <> 2 THEN
                    RAISE EXCEPTION 'platform_environment: cannot verify wallet_required flags (feature_flag_values columns missing); cannot mark production'
                        USING ERRCODE = 'check_violation';
                END IF;
                EXECUTE 'SELECT count(*) FROM public.feature_flag_values WHERE flag_key = ''wallet_required'' AND NOT enabled'
                    INTO found_count;
                IF found_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: wallet_required=false flag rows exist; cannot mark production'
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                               AND table_name = 'feature_flag_values' AND column_name = 'approval_reference') THEN
                    RAISE EXCEPTION 'platform_environment: cannot verify passenger/card approval references (approval_reference column missing); cannot mark production'
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

    # --- Q56: Q48 money gate (SECURITY INVOKER: current_user is the caller's role) -------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.q48_gate_checks()
        RETURNS TABLE (check_name TEXT, ok BOOLEAN, detail TEXT)
        LANGUAGE plpgsql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
        BEGIN
            RETURN QUERY
                SELECT 'app_role_not_superuser'::TEXT, NOT (r.rolsuper OR r.rolbypassrls), format('role=%s', current_user)
                FROM pg_roles r WHERE r.rolname = current_user;
            RETURN QUERY
                SELECT 'app_role_cannot_write_balances'::TEXT,
                       NOT (has_table_privilege(current_user, 'public.ledger_account_balances', 'INSERT')
                            OR has_table_privilege(current_user, 'public.ledger_account_balances', 'UPDATE')
                            OR has_table_privilege(current_user, 'public.ledger_account_balances', 'DELETE')),
                       NULL::TEXT;
            RETURN QUERY
                SELECT 'balance_guard_uses_trigger_depth'::TEXT,
                       COALESCE((SELECT bool_or(pg_get_functiondef(p.oid) ~* 'pg_trigger_depth')
                                 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                                 WHERE n.nspname = 'public' AND p.proname = 'ledger_account_balances_guard'), false),
                       NULL::TEXT;
            RETURN QUERY
                SELECT 'ledger_source_links_enforced'::TEXT,
                       (SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                          JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE n.nspname = 'public' AND t.tgenabled <> 'D'
                           AND ((c.relname = 'ledger_transactions' AND t.tgname = 'trg_ledger_transactions_source_link')
                             OR (c.relname = 'ledger_entries' AND t.tgname = 'trg_ledger_entries_source_link'))) = 2,
                       NULL::TEXT;
            RETURN QUERY
                SELECT 'seed_rate_confirmed'::TEXT,
                       COALESCE((SELECT p.created_by IS NOT NULL OR p.confirmed_by IS NOT NULL
                                 FROM public.commission_policies p
                                 WHERE p.kind = 'standard' AND p.scope_corridor_id IS NULL AND p.scope_service_type IS NULL
                                   AND p.effective_from <= now() AND (p.effective_to IS NULL OR p.effective_to > now())
                                 ORDER BY p.effective_from DESC LIMIT 1), false),
                       NULL::TEXT;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.q48_gate_ok() RETURNS BOOLEAN
        LANGUAGE sql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
            SELECT COALESCE(bool_and(ok), false) FROM public.q48_gate_checks()
        $$
        """
    )
    # Name A2's 0053 flag trigger resolves dynamically (to_regprocedure('platform_q48_gate_passed()')).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.platform_q48_gate_passed() RETURNS BOOLEAN
        LANGUAGE sql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
            SELECT public.q48_gate_ok()
        $$
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (spec §18.3).
    pass
