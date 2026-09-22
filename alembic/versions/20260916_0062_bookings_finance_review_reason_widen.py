"""bookings finance review reason widen

Owner: A4 (wave 3.1) - module `bookings` (commission / finance queue).
Content (DATA_MODEL.md §5 `…_0062` reservation, WAVE1_CARDS wave 3 follow-up W3-6):
  * widen `ck_bookings_finance_review` with the new `CommissionReviewReason.DISPUTE_RESOLVED`
    ("dispute_resolved"), so `bookings.service.mark_finance_review_after_dispute` can record why a finished
    booking whose commission is still `held` entered the B12 `finance_review` queue (U8: no automatic capture;
    finance closes it with `finalize_fee`).
  * forward migration only (spec §18.3): the old CHECK is dropped and re-added as NOT VALID, then VALIDATEd, so
    the table is not rewritten and existing rows are re-checked without an ACCESS EXCLUSIVE scan.
FK / object dependencies: 0048 (bookings), 0056 (the CHECK and the finance_review columns), 0061 (chain head).

Widening a CHECK is backward compatible: every value accepted before is still accepted, so an older image that
does not know `dispute_resolved` keeps working (it simply never writes the value).

Rules: idempotent (guarded DO blocks); do not change the revision id, file name or down_revision; single head.
downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0062
Revises: 20260916_0061
Create Date: 2026-09-16 01:02:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0062"
down_revision: str = "20260916_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_bookings_finance_review"
# enums.CommissionReviewReason (0056 shipped only the first value).
FINANCE_REVIEW_REASONS = ("dispute_module_unavailable", "dispute_resolved")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Re-run safe: the CHECK is only replaced when it does not accept 'dispute_resolved' yet.
    op.execute(
        f"""
        DO $$
        DECLARE
            definition TEXT;
        BEGIN
            SELECT pg_get_constraintdef(oid) INTO definition
              FROM pg_constraint
             WHERE conname = '{CONSTRAINT}' AND conrelid = 'bookings'::regclass;
            IF definition IS NOT NULL AND position('dispute_resolved' in definition) > 0 THEN
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


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016): narrowing the CHECK would refuse rows written by the new code."""
