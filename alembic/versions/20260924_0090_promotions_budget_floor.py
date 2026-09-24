"""promotions budget floor (G14): a reduction never goes below spent + outstanding obligations; funding loss apart

Owner: referral stage 6 (ADR-0023 §20.2, Q132) - module `promotions`.
Content (DATA_MODEL.md §5):
  * ``promo_ledger_apply`` - a ``reduce_allocation`` posting must leave ``B >= S + L`` on the budget row it just
    updated (under that row's lock): B = allocated, S = consumed, L = promised + granted (granted already contains the
    part reserved on bookings - counted once) + approved reinstatements still waiting for budget room (open
    ``reinstate_unfulfilled`` reviews). Otherwise ``promo_budget_below_commitment``; nothing is written. Obligations
    waiting for a review or a late capture stay in promised / granted and so in L. No ledger kind lowers S.
  * new ledger / budget-request kind ``funding_loss`` - external funding that is really gone. It may go below S + L
    (a shortfall), cancels no obligation, needs a budget request with an evidence reference and the same finance /
    two-person rules; the service pauses the campaign in the same transaction (new promises stop, escalation).
  * ``promo_budget_cache_check`` counts ``funding_loss`` in the allocation.

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260924_0090
Revises: 20260923_0089
Create Date: 2026-09-24 00:90:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260924_0090"
down_revision: str = "20260923_0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
TWO_PERSON_THRESHOLD_MINOR = 100_000_000  # the same literal as 0084 (money.TWO_PERSON_APPROVAL_THRESHOLD_MINOR)
_LEDGER_KINDS = ("allocate", "reduce_allocation", "funding_loss", "promise", "release_promise", "grant", "consume",
                 "release_granted", "reinstate")
_BUDGET_CHANGES = ("allocate", "reduce_allocation", "funding_loss")
_LEDGER_LINKS_V3 = """
    (kind NOT IN ('promise', 'release_promise', 'grant') OR obligation_id IS NOT NULL)
    AND (kind NOT IN ('grant', 'consume', 'release_granted', 'reinstate') OR lot_id IS NOT NULL)
    AND (kind <> 'consume' OR redemption_id IS NOT NULL)
    AND (kind NOT IN ('allocate', 'reduce_allocation', 'funding_loss')
         OR (actor_user_id IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0))
    AND (kind <> 'funding_loss' OR budget_request_id IS NOT NULL)
    AND (reversal_of_id IS NULL OR kind = 'reduce_allocation')
    AND ((kind = 'reinstate') = (reinstates_id IS NOT NULL))
"""


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE promo_ledger_transactions DROP CONSTRAINT IF EXISTS ck_promo_ledger_transactions_kind")
    op.execute(f"ALTER TABLE promo_ledger_transactions ADD CONSTRAINT ck_promo_ledger_transactions_kind "
               f"CHECK (kind IN ({_in(_LEDGER_KINDS)}))")
    op.execute("ALTER TABLE promo_ledger_transactions DROP CONSTRAINT IF EXISTS ck_promo_ledger_transactions_links")
    op.execute(f"ALTER TABLE promo_ledger_transactions ADD CONSTRAINT ck_promo_ledger_transactions_links "
               f"CHECK ({_LEDGER_LINKS_V3})")
    op.execute("ALTER TABLE promo_budget_requests DROP CONSTRAINT IF EXISTS ck_promo_budget_requests_kind")
    op.execute(f"ALTER TABLE promo_budget_requests ADD CONSTRAINT ck_promo_budget_requests_kind "
               f"CHECK (kind IN ({_in(_BUDGET_CHANGES)}))")
    op.execute("ALTER TABLE promo_budget_requests DROP CONSTRAINT IF EXISTS ck_promo_budget_requests_funding_evidence")
    op.execute("ALTER TABLE promo_budget_requests ADD CONSTRAINT ck_promo_budget_requests_funding_evidence "
               "CHECK (kind <> 'funding_loss' OR (evidence_reference IS NOT NULL "
               "AND length(btrim(evidence_reference)) > 0))")

    # approved reinstatements still waiting for room: part of L (never hidden by a reduction)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_pending_reinstatements(p_campaign_id BIGINT) RETURNS BIGINT
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
            SELECT COALESCE(SUM(t.amount_minor), 0)::BIGINT
              FROM public.promo_reviews r
              JOIN public.promo_ledger_transactions t
                ON t.campaign_id = r.campaign_id AND t.kind = 'release_granted'
               AND r.dedup_key = 'reinstate_unfulfilled:' || t.id::text
             WHERE r.campaign_id = p_campaign_id AND r.kind = 'reinstate_unfulfilled'
               AND r.status IN ('open', 'under_review')
               AND NOT EXISTS (SELECT 1 FROM public.promo_ledger_transactions x
                                WHERE x.kind = 'reinstate' AND x.reinstates_id = t.id)
        $$
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_ledger_apply() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            d_alloc BIGINT := 0; d_prom BIGINT := 0; d_grant BIGINT := 0; d_cons BIGINT := 0; d_rel BIGINT := 0;
            b public.promo_budgets%ROWTYPE;
            req public.promo_budget_requests%ROWTYPE;
            camp_currency CHAR(3);
            pending BIGINT;
        BEGIN
            IF NEW.budget_seq IS NOT NULL THEN
                RAISE EXCEPTION 'promo_ledger_transactions.budget_seq is assigned by the database'
                    USING ERRCODE = 'check_violation';
            END IF;
            SELECT currency INTO camp_currency FROM public.promo_campaigns WHERE id = NEW.campaign_id;
            IF camp_currency IS DISTINCT FROM NEW.currency THEN
                RAISE EXCEPTION 'promo ledger currency differs from the campaign currency' USING ERRCODE = 'check_violation';
            END IF;
            CASE NEW.kind
                WHEN 'allocate' THEN d_alloc := NEW.amount_minor;
                WHEN 'reduce_allocation' THEN d_alloc := -NEW.amount_minor;
                WHEN 'funding_loss' THEN d_alloc := -NEW.amount_minor;
                WHEN 'promise' THEN d_prom := NEW.amount_minor;
                WHEN 'release_promise' THEN d_prom := -NEW.amount_minor; d_rel := NEW.amount_minor;
                WHEN 'grant' THEN d_prom := -NEW.amount_minor; d_grant := NEW.amount_minor;
                WHEN 'consume' THEN d_grant := -NEW.amount_minor; d_cons := NEW.amount_minor;
                WHEN 'release_granted' THEN d_grant := -NEW.amount_minor; d_rel := NEW.amount_minor;
                WHEN 'reinstate' THEN d_grant := NEW.amount_minor;
            END CASE;
            IF NEW.kind IN ({_in(_BUDGET_CHANGES)}) THEN
                -- Q105/Q69: budget changes only by an active finance or super_admin member of staff.
                IF NOT public.promo_is_finance_approver(NEW.actor_user_id) THEN
                    RAISE EXCEPTION 'promo budget change by a user who is not active finance staff'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'approver_not_finance_staff';
                END IF;
                IF NEW.amount_minor > {TWO_PERSON_THRESHOLD_MINOR} THEN
                    SELECT * INTO req FROM public.promo_budget_requests WHERE id = NEW.budget_request_id;
                    IF req.id IS NULL OR req.campaign_id <> NEW.campaign_id OR req.kind <> NEW.kind
                       OR req.amount_minor <> NEW.amount_minor OR req.status <> 'pending'
                       OR req.approved_by IS NULL OR req.approved_by = req.requested_by
                       OR NOT public.promo_is_finance_approver(req.approved_by)
                       OR NEW.actor_user_id <> req.approved_by THEN
                        RAISE EXCEPTION 'promo budget change above the two-person threshold needs a different approver'
                            USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_second_approver_required';
                    END IF;
                END IF;
            END IF;
            IF NEW.kind = 'funding_loss' THEN
                -- G14: a real loss of external funding is recorded with its evidence, never as a plain reduction
                SELECT * INTO req FROM public.promo_budget_requests WHERE id = NEW.budget_request_id;
                IF req.id IS NULL OR req.kind <> 'funding_loss' OR req.campaign_id <> NEW.campaign_id
                   OR req.amount_minor <> NEW.amount_minor OR req.evidence_reference IS NULL
                   OR length(btrim(req.evidence_reference)) = 0 THEN
                    RAISE EXCEPTION 'a funding loss needs its own budget request with an evidence reference'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_funding_loss_evidence';
                END IF;
            END IF;
            IF NEW.kind = 'allocate' THEN
                INSERT INTO public.promo_budgets AS pb (campaign_id, currency, allocated_minor, last_ledger_seq)
                VALUES (NEW.campaign_id, NEW.currency, d_alloc, 1)
                ON CONFLICT (campaign_id) DO UPDATE
                    SET allocated_minor = pb.allocated_minor + EXCLUDED.allocated_minor,
                        last_ledger_seq = pb.last_ledger_seq + 1,
                        updated_at = now()
                RETURNING pb.* INTO b;
            ELSE
                UPDATE public.promo_budgets AS pb
                   SET allocated_minor = pb.allocated_minor + d_alloc,
                       promised_minor = pb.promised_minor + d_prom,
                       granted_minor = pb.granted_minor + d_grant,
                       consumed_minor = pb.consumed_minor + d_cons,
                       released_minor = pb.released_minor + d_rel,
                       last_ledger_seq = pb.last_ledger_seq + 1,
                       updated_at = now()
                 WHERE pb.campaign_id = NEW.campaign_id
                RETURNING pb.* INTO b;
                IF b.id IS NULL THEN
                    RAISE EXCEPTION 'promo budget has no allocation'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_exhausted';
                END IF;
            END IF;
            -- The row lock taken by the UPDATE serialises concurrent postings; these checks see the latest row.
            IF NEW.kind IN ('promise', 'reinstate')
               AND b.promised_minor + b.granted_minor + b.consumed_minor > b.allocated_minor THEN
                RAISE EXCEPTION 'promo budget exhausted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_exhausted';
            END IF;
            IF NEW.kind = 'reduce_allocation' THEN
                pending := public.promo_pending_reinstatements(NEW.campaign_id);
                IF b.allocated_minor < b.consumed_minor + b.promised_minor + b.granted_minor + pending THEN
                    RAISE EXCEPTION 'promo budget reduction below spent + outstanding obligations (B >= S + L)'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_below_commitment';
                END IF;
            END IF;
            NEW.budget_seq := b.last_ledger_seq;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_ledger_apply", "promo_ledger_transactions",
             "TRIGGER trg_promo_ledger_apply BEFORE INSERT ON promo_ledger_transactions "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_ledger_apply()")

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.promo_budget_cache_check() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            s RECORD;
            b public.promo_budgets%ROWTYPE;
        BEGIN
            SELECT
                COALESCE(SUM(CASE kind WHEN 'allocate' THEN amount_minor WHEN 'reduce_allocation' THEN -amount_minor
                                      WHEN 'funding_loss' THEN -amount_minor ELSE 0 END), 0) AS alloc,
                COALESCE(SUM(CASE kind WHEN 'promise' THEN amount_minor WHEN 'release_promise' THEN -amount_minor
                                      WHEN 'grant' THEN -amount_minor ELSE 0 END), 0) AS prom,
                COALESCE(SUM(CASE kind WHEN 'grant' THEN amount_minor WHEN 'reinstate' THEN amount_minor
                                      WHEN 'consume' THEN -amount_minor WHEN 'release_granted' THEN -amount_minor ELSE 0 END), 0) AS grnt,
                COALESCE(SUM(CASE kind WHEN 'consume' THEN amount_minor ELSE 0 END), 0) AS cons,
                COALESCE(SUM(CASE kind WHEN 'release_promise' THEN amount_minor WHEN 'release_granted' THEN amount_minor ELSE 0 END), 0) AS rel
            INTO s FROM public.promo_ledger_transactions WHERE campaign_id = NEW.campaign_id;
            SELECT * INTO b FROM public.promo_budgets WHERE campaign_id = NEW.campaign_id;
            IF b.id IS NULL OR b.allocated_minor <> s.alloc OR b.promised_minor <> s.prom OR b.granted_minor <> s.grnt
               OR b.consumed_minor <> s.cons OR b.released_minor <> s.rel THEN
                RAISE EXCEPTION 'promo_budgets cache differs from the promo ledger (campaign %)', NEW.campaign_id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_budget_cache_mismatch';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )


def downgrade() -> None:
    """Dev/test only and deliberately empty: removing the floor would re-open the G14 hole, and the trigger calls
    ``promo_pending_reinstatements``. A correction is a forward migration (spec §18.3)."""
