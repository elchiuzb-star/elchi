"""promotions qualification: intake events, qualification records, review queue, reinstate link (referral stage 3)

Owner: referral stage 3 (ADR-0023 §17; Q110/Q112/Q113/Q115) - module `promotions`.
Content (DATA_MODEL.md §5):
  * ``promo_qualification_events`` - durable intake log. An event only *starts* a check; the decision is taken from
    the source records. Service time (``occurred_at``), arrival (``received_at``) and processing (``processed_at``)
    are separate columns; ``dedup_key`` is unique so a redelivered event is a no-op.
  * ``promo_qualifications`` - one decision record per ``(enrollment, milestone)``: evidence booking ids, the time
    the last condition was met, ``ready_at`` (+48 h, Q110), ruleset version, status. Unique, so parallel workers
    or retries converge on one row.
  * ``promo_reviews`` - the review queue: kind, reason codes, evidence references (table + id only), ruleset
    version, SLA ``due_at``, escalation time, assignee, decision, note, decider, times. ``dedup_key`` unique so
    retries never duplicate a review; decided reviews are frozen (trigger).
  * ``promo_enrollments.last_checked_at`` (mutable bookkeeping, outside the frozen terms).
  * ``promo_lots.available_from`` - when the holder could first spend it; the spend period starts there.
  * ``promo_campaigns.processing_suspended_at`` / ``processing_suspend_reason`` - an operational stop for
    qualification/grant processing that deletes nothing.
  * ``promo_ledger_transactions.reinstates_id`` - a reinstatement points at the exact expiry release it undoes;
    one per original, never more than the original amount, same lot (trigger + partial unique index).

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260923_0086
Revises: 20260923_0085
Create Date: 2026-09-23 00:86:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0086"
down_revision: str = "20260923_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEDGER_LINKS_V2 = """
    (kind NOT IN ('promise', 'release_promise', 'grant') OR obligation_id IS NOT NULL)
    AND (kind NOT IN ('grant', 'consume', 'release_granted', 'reinstate') OR lot_id IS NOT NULL)
    AND (kind <> 'consume' OR redemption_id IS NOT NULL)
    AND (kind NOT IN ('allocate', 'reduce_allocation')
         OR (actor_user_id IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0))
    AND (reversal_of_id IS NULL OR kind = 'reduce_allocation')
    AND ((kind = 'reinstate') = (reinstates_id IS NOT NULL))
"""


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # --- intake log ------------------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_qualification_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL,
            kind VARCHAR(32) NOT NULL,
            occurred_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error VARCHAR(200),
            dedup_key VARCHAR(200) NOT NULL,
            CONSTRAINT uq_promo_qualification_events_dedup UNIQUE (dedup_key),
            CONSTRAINT fk_promo_qualification_events_booking FOREIGN KEY (booking_id) REFERENCES bookings (id),
            CONSTRAINT ck_promo_qualification_events_kind CHECK (kind IN (
                'booking_completed', 'cash_acknowledged', 'commission_captured', 'commission_reversed',
                'dispute_changed', 'booking_cancelled', 'sweep'
            )),
            CONSTRAINT ck_promo_qualification_events_attempts CHECK (attempts >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_qualification_events_pending ON promo_qualification_events (id) "
        "WHERE processed_at IS NULL"
    )

    # --- qualification records -------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_qualifications (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            enrollment_id BIGINT NOT NULL,
            milestone INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL,
            evidence_booking_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            conditions_met_at TIMESTAMPTZ,
            ready_at TIMESTAMPTZ,
            risk_ruleset_version VARCHAR(32),
            reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            cleared_review_id BIGINT,
            granted_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_qualifications_public_id UNIQUE (public_id),
            CONSTRAINT uq_promo_qualifications_enrollment_milestone UNIQUE (enrollment_id, milestone),
            CONSTRAINT fk_promo_qualifications_enrollment FOREIGN KEY (enrollment_id) REFERENCES promo_enrollments (id),
            CONSTRAINT ck_promo_qualifications_status CHECK (
                status IN ('waiting', 'review', 'qualified', 'granted', 'rejected')
            ),
            CONSTRAINT ck_promo_qualifications_milestone CHECK (milestone >= 0),
            CONSTRAINT ck_promo_qualifications_granted CHECK ((status = 'granted') = (granted_at IS NOT NULL)),
            CONSTRAINT ck_promo_qualifications_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_qualifications_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_qualifications rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF (NEW.enrollment_id, NEW.milestone, NEW.public_id) IS DISTINCT FROM (OLD.enrollment_id, OLD.milestone, OLD.public_id) THEN
                RAISE EXCEPTION 'promo_qualifications identity is immutable'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF OLD.status IN ('granted', 'rejected') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'promo_qualifications: % is final', OLD.status
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_qualifications_guard", "promo_qualifications",
             "TRIGGER trg_promo_qualifications_guard BEFORE UPDATE OR DELETE ON promo_qualifications "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_qualifications_guard()")

    # --- review queue ----------------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_reviews (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            kind VARCHAR(32) NOT NULL,
            dedup_key VARCHAR(200) NOT NULL,
            campaign_id BIGINT,
            attribution_id BIGINT,
            enrollment_id BIGINT,
            qualification_id BIGINT,
            booking_id BIGINT,
            reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            risk_ruleset_version VARCHAR(32),
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            opened_at TIMESTAMPTZ NOT NULL,
            due_at TIMESTAMPTZ,
            escalated_at TIMESTAMPTZ,
            assigned_to BIGINT,
            decision_note TEXT,
            decided_by BIGINT,
            decided_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_promo_reviews_public_id UNIQUE (public_id),
            CONSTRAINT uq_promo_reviews_dedup UNIQUE (dedup_key),
            CONSTRAINT fk_promo_reviews_campaign FOREIGN KEY (campaign_id) REFERENCES promo_campaigns (id),
            CONSTRAINT fk_promo_reviews_attribution FOREIGN KEY (attribution_id) REFERENCES referral_attributions (id),
            CONSTRAINT fk_promo_reviews_enrollment FOREIGN KEY (enrollment_id) REFERENCES promo_enrollments (id),
            CONSTRAINT fk_promo_reviews_qualification FOREIGN KEY (qualification_id) REFERENCES promo_qualifications (id),
            CONSTRAINT fk_promo_reviews_booking FOREIGN KEY (booking_id) REFERENCES bookings (id),
            CONSTRAINT fk_promo_reviews_assigned_to FOREIGN KEY (assigned_to) REFERENCES users (id),
            CONSTRAINT fk_promo_reviews_decided_by FOREIGN KEY (decided_by) REFERENCES users (id),
            CONSTRAINT ck_promo_reviews_kind CHECK (kind IN ('identity_match', 'qualification_risk', 'post_grant_recheck', 'party_not_active')),
            CONSTRAINT ck_promo_reviews_status CHECK (status IN ('open', 'under_review', 'approved', 'rejected')),
            CONSTRAINT ck_promo_reviews_decided CHECK (
                (status IN ('approved', 'rejected')) = (decided_at IS NOT NULL AND decided_by IS NOT NULL)
            ),
            CONSTRAINT ck_promo_reviews_evidence CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_typeof(reason_codes) = 'array'),
            CONSTRAINT ck_promo_reviews_version CHECK (version >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_promo_reviews_open ON promo_reviews (status, due_at) "
               "WHERE status IN ('open', 'under_review')")
    op.execute("CREATE INDEX IF NOT EXISTS ix_promo_reviews_enrollment ON promo_reviews (enrollment_id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_reviews_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'promo_reviews rows are never deleted'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF (NEW.kind, NEW.dedup_key, NEW.campaign_id, NEW.attribution_id, NEW.enrollment_id, NEW.qualification_id,
                NEW.booking_id, NEW.reason_codes, NEW.evidence, NEW.risk_ruleset_version, NEW.opened_at, NEW.public_id)
               IS DISTINCT FROM
               (OLD.kind, OLD.dedup_key, OLD.campaign_id, OLD.attribution_id, OLD.enrollment_id, OLD.qualification_id,
                OLD.booking_id, OLD.reason_codes, OLD.evidence, OLD.risk_ruleset_version, OLD.opened_at, OLD.public_id) THEN
                RAISE EXCEPTION 'promo_reviews: what was reviewed never changes'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            IF OLD.status IN ('approved', 'rejected') AND (NEW.status, NEW.decided_by, NEW.decided_at, NEW.decision_note)
               IS DISTINCT FROM (OLD.status, OLD.decided_by, OLD.decided_at, OLD.decision_note) THEN
                RAISE EXCEPTION 'promo_reviews: a decision is final'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_invalid_transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_reviews_guard", "promo_reviews",
             "TRIGGER trg_promo_reviews_guard BEFORE UPDATE OR DELETE ON promo_reviews "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_reviews_guard()")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_promo_qualifications_cleared_review') THEN
                ALTER TABLE promo_qualifications ADD CONSTRAINT fk_promo_qualifications_cleared_review
                    FOREIGN KEY (cleared_review_id) REFERENCES promo_reviews (id);
            END IF;
        END
        $$;
        """
    )

    # --- small additive columns --------------------------------------------------------------------------------
    op.execute("ALTER TABLE promo_enrollments ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ")
    op.execute("ALTER TABLE promo_lots ADD COLUMN IF NOT EXISTS available_from TIMESTAMPTZ")
    op.execute("UPDATE promo_lots SET available_from = created_at WHERE available_from IS NULL AND status <> 'pending_review'")
    op.execute("ALTER TABLE promo_campaigns ADD COLUMN IF NOT EXISTS processing_suspended_at TIMESTAMPTZ")
    op.execute("ALTER TABLE promo_campaigns ADD COLUMN IF NOT EXISTS processing_suspend_reason TEXT")

    # --- reinstatement link -----------------------------------------------------------------------------------
    op.execute("ALTER TABLE promo_ledger_transactions ADD COLUMN IF NOT EXISTS reinstates_id BIGINT")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_promo_ledger_transactions_reinstates') THEN
                ALTER TABLE promo_ledger_transactions ADD CONSTRAINT fk_promo_ledger_transactions_reinstates
                    FOREIGN KEY (reinstates_id) REFERENCES promo_ledger_transactions (id);
            END IF;
        END
        $$;
        """
    )
    op.execute("ALTER TABLE promo_ledger_transactions DROP CONSTRAINT IF EXISTS ck_promo_ledger_transactions_links")
    op.execute(f"ALTER TABLE promo_ledger_transactions ADD CONSTRAINT ck_promo_ledger_transactions_links CHECK ({_LEDGER_LINKS_V2})")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_promo_ledger_reinstate_once ON promo_ledger_transactions (reinstates_id) "
        "WHERE kind = 'reinstate'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.promo_ledger_reinstate_check() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            original public.promo_ledger_transactions%ROWTYPE;
        BEGIN
            IF NEW.kind <> 'reinstate' THEN
                RETURN NEW;
            END IF;
            SELECT * INTO original FROM public.promo_ledger_transactions WHERE id = NEW.reinstates_id;
            IF original.id IS NULL OR original.kind <> 'release_granted' OR original.lot_id IS DISTINCT FROM NEW.lot_id
               OR original.reference_key NOT LIKE 'release_granted:expiry%' OR NEW.amount_minor > original.amount_minor THEN
                RAISE EXCEPTION 'reinstate must undo one expiry release of the same lot, at most its amount'
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'promo_reinstate_invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger("trg_promo_ledger_reinstate_check", "promo_ledger_transactions",
             "TRIGGER trg_promo_ledger_reinstate_check BEFORE INSERT ON promo_ledger_transactions "
             "FOR EACH ROW EXECUTE FUNCTION public.promo_ledger_reinstate_check()")


def downgrade() -> None:
    """Dev/test only (ADR-0016). Never a production rollback."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_promo_ledger_reinstate_check ON promo_ledger_transactions")
    op.execute("DROP FUNCTION IF EXISTS public.promo_ledger_reinstate_check()")
    op.execute("DROP INDEX IF EXISTS uq_promo_ledger_reinstate_once")
    op.execute("ALTER TABLE promo_ledger_transactions DROP CONSTRAINT IF EXISTS fk_promo_ledger_transactions_reinstates")
    op.execute("ALTER TABLE promo_ledger_transactions DROP COLUMN IF EXISTS reinstates_id")
    op.execute("ALTER TABLE promo_qualifications DROP CONSTRAINT IF EXISTS fk_promo_qualifications_cleared_review")
    for table in ("promo_reviews", "promo_qualifications", "promo_qualification_events"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for function in ("promo_reviews_guard", "promo_qualifications_guard"):
        op.execute(f"DROP FUNCTION IF EXISTS public.{function}() CASCADE")
    op.execute("ALTER TABLE promo_campaigns DROP COLUMN IF EXISTS processing_suspend_reason")
    op.execute("ALTER TABLE promo_campaigns DROP COLUMN IF EXISTS processing_suspended_at")
    op.execute("ALTER TABLE promo_lots DROP COLUMN IF EXISTS available_from")
    op.execute("ALTER TABLE promo_enrollments DROP COLUMN IF EXISTS last_checked_at")
