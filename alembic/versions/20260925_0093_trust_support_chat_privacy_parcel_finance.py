"""trust_support chat privacy and parcel finance review (ADR-0026 follow-up, Q144, Q141)

Owner: A0a (integrator) - modules `trust_support` (operator chat) and `bookings` (finance queue).
Content:
  * `support_messages.staff_only` - a line only staff read. The requester's own chat never shows it.
  * carried-over disputes (0092): the requester keeps what was theirs - the complaint text, their own evidence notes
    and the recorded decision. Evidence written by the other participant or by staff becomes `staff_only`. Before 0092
    both participants could read the whole dispute; the chat is narrower on purpose (no automatic widening, and the
    other side's material is not handed to a new audience). Files are never exposed to the requester through the
    chat at all (the user DTO carries no file ids or URLs); staff read them as before.
  * `ck_bookings_finance_review` gains `parcel_staff_completion` (Q144): while the parcel completion rule is open
    (D-1), a parcel completed by staff keeps its commission `held` and goes to the finance queue - capture stays a
    `finance.fee_finalize` decision, never a side effect of an operator command.
Forward only, idempotent: the column is added once, the marking only turns rows to `staff_only` (never back), the
CHECK is replaced only when it lacks the new value. `downgrade()` is not a rollback strategy (ADR-0016).

Revision ID: 20260925_0093
Revises: 20260924_0092
Create Date: 2026-09-25 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_0093"
down_revision: str = "20260924_0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_bookings_finance_review"
# enums.CommissionReviewReason
FINANCE_REVIEW_REASONS = ("dispute_module_unavailable", "dispute_resolved", "parcel_staff_completion")
# promo review kinds (0089 + Q147 `qualification_path_retired`)
REVIEW_KINDS = ("identity_match", "qualification_risk", "post_grant_recheck", "party_not_active", "reinstate_unfulfilled",
                "cancel_fault", "restoration_uncovered", "qualification_path_retired")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.support_messages ADD COLUMN IF NOT EXISTS staff_only BOOLEAN NOT NULL DEFAULT false")
    # The append-only trigger refuses every UPDATE; this one-time, one-directional marking is the only exception and
    # runs with the trigger disabled inside this migration's transaction.
    op.execute("ALTER TABLE public.support_messages DISABLE TRIGGER trg_support_messages_append_only")
    op.execute(
        """
        UPDATE public.support_messages m
           SET staff_only = true
          FROM public.support_threads t
         WHERE m.thread_id = t.id
           AND t.source_dispute_id IS NOT NULL
           AND m.source_kind = 'dispute_evidence'
           AND NOT m.staff_only
           AND NOT (m.author_user_id IS NOT DISTINCT FROM t.requester_user_id AND m.author_side = t.requester_side)
        """
    )
    op.execute("ALTER TABLE public.support_messages ENABLE TRIGGER trg_support_messages_append_only")
    op.execute(
        f"""
        DO $$
        DECLARE
            definition TEXT;
        BEGIN
            SELECT pg_get_constraintdef(oid) INTO definition
              FROM pg_constraint
             WHERE conname = '{CONSTRAINT}' AND conrelid = 'bookings'::regclass;
            IF definition IS NOT NULL AND position('parcel_staff_completion' in definition) > 0 THEN
                RETURN;
            END IF;
            IF definition IS NOT NULL THEN
                ALTER TABLE bookings DROP CONSTRAINT {CONSTRAINT};
            END IF;
            ALTER TABLE bookings ADD CONSTRAINT {CONSTRAINT} CHECK (
                (finance_review_reason IS NULL) = (finance_review_at IS NULL)
                AND (finance_review_reason IS NULL OR finance_review_reason IN {_in(FINANCE_REVIEW_REASONS)})
            ) NOT VALID;
            ALTER TABLE bookings VALIDATE CONSTRAINT {CONSTRAINT};
        END
        $$
        """
    )
    _promo_review_kinds()


def _promo_review_kinds() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            definition TEXT;
        BEGIN
            SELECT pg_get_constraintdef(oid) INTO definition
              FROM pg_constraint WHERE conname = 'ck_promo_reviews_kind' AND conrelid = 'promo_reviews'::regclass;
            IF definition IS NOT NULL AND position('qualification_path_retired' in definition) > 0 THEN
                RETURN;
            END IF;
            IF definition IS NOT NULL THEN
                ALTER TABLE promo_reviews DROP CONSTRAINT ck_promo_reviews_kind;
            END IF;
            ALTER TABLE promo_reviews ADD CONSTRAINT ck_promo_reviews_kind CHECK (kind IN {_in(REVIEW_KINDS)});
        END
        $$
        """
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
