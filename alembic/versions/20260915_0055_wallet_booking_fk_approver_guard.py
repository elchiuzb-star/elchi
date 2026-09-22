"""wallet booking fk approver guard

Owner: A3 (wave 2.1) - modules `wallet`, `platform` (gate parts).
Content (DATA_MODEL.md §5, WAVE1_CARDS "Wave 2.1"):
  * FK wallet_holds.booking_id and ledger_transactions.booking_id -> bookings(id) (ADD ... NOT VALID, then
    VALIDATE CONSTRAINT); ORM ForeignKey(..., name=...). Existing orphan references stop the migration loudly with
    their ids (forward fix, nothing is deleted).
  * Q69: topup_requests.first_approver_id / second_approver_id and ledger_adjustment_requests.approved_by /
    rejected_by (and the requester of a posting adjustment) must be an ACTIVE user whose effective roles include
    finance or super_admin at write time. Effective roles mirror app.modules.identity.capabilities.effective_roles:
    legacy primary users.role plus active user_roles rows. DB trigger, RAISE ... USING ERRCODE = 'check_violation',
    CONSTRAINT = 'approver_not_finance_staff'.
  * Q70: under the production marker (fail closed: missing/unknown marker counts as production) top-up approval
    (first and second) and posting a plain CREDIT adjustment are refused while platform_q48_gate_passed() is not
    true (same triggers; CONSTRAINT = 'q48_gate_money_refused'). Debit adjustments (Q31 refunds) and commission
    reversals (N5 obligations on a real capture) are not gated - integrator interpretation, see the A3 report.
  * Q69/Q71: q48_gate_checks() gains 'approver_guard_enforced' (both approval-guard triggers present and enabled)
    and 'app_role_owns_no_objects' (current_user owns no relation/sequence/function/type/schema in this database).
FK / object dependencies: 0048 (bookings), 0052 (gate functions, ledger source links), 0047, 0041, 0032 (user_roles).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0055
Revises: 20260915_0054
Create Date: 2026-09-15 00:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0055"
down_revision: str = "20260915_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
# app.contracts.enums Role.FINANCE / Role.SUPER_ADMIN (Q17, Q69).
APPROVER_ROLES_SQL = "('finance', 'super_admin')"
BOOKING_FOREIGN_KEYS = (
    ("wallet_holds", "fk_wallet_holds_booking_id"),
    ("ledger_transactions", "fk_ledger_transactions_booking_id"),
)
APPROVAL_GUARD_TRIGGERS = (
    ("topup_requests", "trg_topup_requests_approval_guard", "public.wallet_topup_approval_guard"),
    ("ledger_adjustment_requests", "trg_ledger_adjustment_requests_approval_guard",
     "public.wallet_adjustment_approval_guard"),
)


def add_booking_foreign_keys(bind) -> None:
    """NOT VALID first (new orphans refused at once), then report existing orphans, then VALIDATE.

    Exported for the PG test. Raises RuntimeError listing (table, row id, booking_id) for orphan references.
    """
    for table, name in BOOKING_FOREIGN_KEYS:
        bind.execute(sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{name}' AND conrelid = 'public.{table}'::regclass
                ) THEN
                    ALTER TABLE public.{table} ADD CONSTRAINT {name}
                        FOREIGN KEY (booking_id) REFERENCES public.bookings (id) NOT VALID;
                END IF;
            END
            $$;
            """
        ))
    for table, name in BOOKING_FOREIGN_KEYS:
        orphans = bind.execute(sa.text(
            f"SELECT t.id, t.booking_id FROM public.{table} t WHERE t.booking_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM public.bookings b WHERE b.id = t.booking_id) ORDER BY t.id LIMIT 20"
        )).all()
        if orphans:
            raise RuntimeError(
                f"20260915_0055: {table}.booking_id references missing bookings (id, booking_id): "
                f"{[tuple(row) for row in orphans]}. Investigate before migrating (forward fix; nothing is deleted)."
            )
        bind.execute(sa.text(f"ALTER TABLE public.{table} VALIDATE CONSTRAINT {name}"))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- FKs to bookings -------------------------------------------------------------------------------
    add_booking_foreign_keys(bind)

    # --- Q69: who may approve --------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.wallet_user_is_finance_approver(p_user_id INTEGER) RETURNS BOOLEAN
        LANGUAGE sql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.users u
                WHERE u.id = p_user_id
                  AND u.status = 'active'
                  AND (u.role IN {APPROVER_ROLES_SQL}
                       OR EXISTS (SELECT 1 FROM public.user_roles r
                                  WHERE r.user_id = u.id AND r.status = 'active' AND r.role IN {APPROVER_ROLES_SQL}))
            )
        $$
        """
    )
    # Fail closed like geo_production_guard_active (0043): no table / no row / unknown value -> production.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.wallet_production_guard_active() RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            marker TEXT;
        BEGIN
            IF to_regclass('public.platform_environment') IS NULL THEN
                RETURN true;
            END IF;
            SELECT environment INTO marker FROM public.platform_environment WHERE id = 1;
            RETURN marker IS NULL OR marker NOT IN ('staging', 'development', 'test');
        END;
        $$
        """
    )
    # SECURITY INVOKER on purpose: platform_q48_gate_passed() evaluates current_user (the app role).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.wallet_money_in_gate_passed() RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
        BEGIN
            IF NOT public.wallet_production_guard_active() THEN
                RETURN true;
            END IF;
            RETURN COALESCE(public.platform_q48_gate_passed(), false);
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.wallet_topup_approval_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = {SAFE_SEARCH_PATH} AS $$
        BEGIN
            IF NEW.first_approver_id IS NOT NULL
               AND (TG_OP = 'INSERT' OR NEW.first_approver_id IS DISTINCT FROM OLD.first_approver_id)
               AND NOT public.wallet_user_is_finance_approver(NEW.first_approver_id) THEN
                RAISE EXCEPTION 'approver_not_finance_staff: topup_requests.first_approver_id % is not an active finance/super_admin user',
                    NEW.first_approver_id USING ERRCODE = 'check_violation', CONSTRAINT = 'approver_not_finance_staff';
            END IF;
            IF NEW.second_approver_id IS NOT NULL
               AND (TG_OP = 'INSERT' OR NEW.second_approver_id IS DISTINCT FROM OLD.second_approver_id)
               AND NOT public.wallet_user_is_finance_approver(NEW.second_approver_id) THEN
                RAISE EXCEPTION 'approver_not_finance_staff: topup_requests.second_approver_id % is not an active finance/super_admin user',
                    NEW.second_approver_id USING ERRCODE = 'check_violation', CONSTRAINT = 'approver_not_finance_staff';
            END IF;
            -- Q70: first approval (-> awaiting_second_approval) and final approval (-> approved).
            IF NEW.status IN ('awaiting_second_approval', 'approved')
               AND (TG_OP = 'INSERT' OR NEW.status IS DISTINCT FROM OLD.status)
               AND NOT public.wallet_money_in_gate_passed() THEN
                RAISE EXCEPTION 'q48_gate_money_refused: top-up approval refused in production while the Q48 gate fails'
                    USING ERRCODE = 'object_not_in_prerequisite_state', CONSTRAINT = 'q48_gate_money_refused';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.wallet_adjustment_approval_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = {SAFE_SEARCH_PATH} AS $$
        BEGIN
            IF NEW.approved_by IS NOT NULL
               AND (TG_OP = 'INSERT' OR NEW.approved_by IS DISTINCT FROM OLD.approved_by)
               AND NOT public.wallet_user_is_finance_approver(NEW.approved_by) THEN
                RAISE EXCEPTION 'approver_not_finance_staff: ledger_adjustment_requests.approved_by % is not an active finance/super_admin user',
                    NEW.approved_by USING ERRCODE = 'check_violation', CONSTRAINT = 'approver_not_finance_staff';
            END IF;
            IF NEW.rejected_by IS NOT NULL
               AND (TG_OP = 'INSERT' OR NEW.rejected_by IS DISTINCT FROM OLD.rejected_by)
               AND NOT public.wallet_user_is_finance_approver(NEW.rejected_by) THEN
                RAISE EXCEPTION 'approver_not_finance_staff: ledger_adjustment_requests.rejected_by % is not an active finance/super_admin user',
                    NEW.rejected_by USING ERRCODE = 'check_violation', CONSTRAINT = 'approver_not_finance_staff';
            END IF;
            IF NEW.status = 'posted' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'posted') THEN
                -- A small adjustment is posted on its requester's own authority (finance.adjustment).
                IF NOT public.wallet_user_is_finance_approver(NEW.requested_by) THEN
                    RAISE EXCEPTION 'approver_not_finance_staff: ledger_adjustment_requests.requested_by % is not an active finance/super_admin user',
                        NEW.requested_by USING ERRCODE = 'check_violation', CONSTRAINT = 'approver_not_finance_staff';
                END IF;
                -- Q70: plain credits only; debits (Q31 refunds) and commission reversals are not gated.
                IF NEW.direction = 'credit' AND NEW.reversal_of_transaction_id IS NULL
                   AND NOT public.wallet_money_in_gate_passed() THEN
                    RAISE EXCEPTION 'q48_gate_money_refused: credit adjustment refused in production while the Q48 gate fails'
                        USING ERRCODE = 'object_not_in_prerequisite_state', CONSTRAINT = 'q48_gate_money_refused';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table, trigger, function in APPROVAL_GUARD_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"
        )

    # --- Q56 + Q69/Q71: gate checks (0052 body plus two checks) ----------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.q48_gate_checks()
        RETURNS TABLE (check_name TEXT, ok BOOLEAN, detail TEXT)
        LANGUAGE plpgsql STABLE SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            me OID;
            owned_relations BIGINT;
            owned_functions BIGINT;
            owned_types BIGINT;
            owned_schemas BIGINT;
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
            -- Q69: the approver guard triggers exist and are enabled.
            RETURN QUERY
                SELECT 'approver_guard_enforced'::TEXT,
                       (SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                          JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE n.nspname = 'public' AND t.tgenabled <> 'D'
                           AND ((c.relname = 'topup_requests' AND t.tgname = 'trg_topup_requests_approval_guard')
                             OR (c.relname = 'ledger_adjustment_requests'
                                 AND t.tgname = 'trg_ledger_adjustment_requests_approval_guard'))) = 2,
                       NULL::TEXT;
            -- Q71: an object owner can ALTER/DISABLE TRIGGER or re-grant itself; the app role must own nothing here.
            SELECT oid INTO me FROM pg_roles WHERE rolname = current_user;
            SELECT count(*) INTO owned_relations FROM pg_class WHERE relowner = me;
            SELECT count(*) INTO owned_functions FROM pg_proc WHERE proowner = me;
            SELECT count(*) INTO owned_types FROM pg_type WHERE typowner = me;
            SELECT count(*) INTO owned_schemas FROM pg_namespace WHERE nspowner = me;
            RETURN QUERY
                SELECT 'app_role_owns_no_objects'::TEXT,
                       (owned_relations + owned_functions + owned_types + owned_schemas) = 0,
                       format('relations=%s functions=%s types=%s schemas=%s',
                              owned_relations, owned_functions, owned_types, owned_schemas);
        END;
        $$
        """
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
