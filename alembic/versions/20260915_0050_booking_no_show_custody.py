"""booking no-show reviews and custody cases (A4, wave 2)

Owner: A4 (wave 2) - module `bookings`.
Content (DATA_MODEL.md §1.7; STATE_MACHINES §3.1, §4, §5, §9; Q7, N3, D1, AC22, AC42):
  * no_show_reviews - the driver's report opens a `pending` review (the booking stays `awaiting_pickup`); only
    an operator decides (`confirmed` | `rejected`). Partial unique: one pending review per booking (Q7).
    Guard: a decided review is final and carries decided_by/decided_at.
  * custody_cases - a parcel that failed delivery or must return stays in the driver's custody under an
    operator case. Partial unique: one open case per booking (D1). Guard: a resolved case is final.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0050
Revises: 20260915_0049
Create Date: 2026-09-15 00:50:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0050"
down_revision: str = "20260915_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NO_SHOW_REVIEW_STATUSES = ("pending", "confirmed", "rejected")
CUSTODY_CASE_STATUSES = ("open", "resolved")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- no_show_reviews (Q7) ------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS no_show_reviews (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL CONSTRAINT fk_no_show_reviews_booking_id REFERENCES bookings (id),
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            reported_by INTEGER NOT NULL CONSTRAINT fk_no_show_reviews_reported_by REFERENCES users (id),
            arrived_at TIMESTAMPTZ NOT NULL,
            wait_until TIMESTAMPTZ NOT NULL,
            contact_attempts JSONB NOT NULL DEFAULT '[]'::jsonb,
            evidence_file_ids TEXT[] NOT NULL DEFAULT '{{}}',
            note TEXT,
            decided_by INTEGER CONSTRAINT fk_no_show_reviews_decided_by REFERENCES users (id),
            decided_at TIMESTAMPTZ,
            decision_command VARCHAR(32),
            decision_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_no_show_reviews_status CHECK (status IN {_in(NO_SHOW_REVIEW_STATUSES)}),
            CONSTRAINT ck_no_show_reviews_wait CHECK (wait_until >= arrived_at),
            CONSTRAINT ck_no_show_reviews_decision CHECK (
                (status = 'pending') = (decided_at IS NULL)
                AND (decided_at IS NULL OR decision_command IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_no_show_reviews_pending ON no_show_reviews (booking_id) WHERE status = 'pending'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_no_show_reviews_booking ON no_show_reviews (booking_id, id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION no_show_reviews_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'no_show_reviews cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.status <> 'pending' THEN
                RAISE EXCEPTION 'a decided no-show review is final' USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.booking_id, NEW.reported_by, NEW.arrived_at, NEW.wait_until, NEW.contact_attempts,
                NEW.evidence_file_ids, NEW.note, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.booking_id, OLD.reported_by, OLD.arrived_at, OLD.wait_until, OLD.contact_attempts,
                OLD.evidence_file_ids, OLD.note, OLD.created_at) THEN
                RAISE EXCEPTION 'no-show report content is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_no_show_reviews_guard",
        "no_show_reviews",
        "TRIGGER trg_no_show_reviews_guard BEFORE UPDATE OR DELETE ON no_show_reviews "
        "FOR EACH ROW EXECUTE FUNCTION no_show_reviews_guard()",
    )
    _trigger(
        "trg_no_show_reviews_no_truncate",
        "no_show_reviews",
        "TRIGGER trg_no_show_reviews_no_truncate BEFORE TRUNCATE ON no_show_reviews "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )

    # --- custody_cases (D1, AC22, AC42) ----------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS custody_cases (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL CONSTRAINT fk_custody_cases_booking_id REFERENCES bookings (id),
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            opened_reason_code VARCHAR(64) NOT NULL,
            opened_by INTEGER CONSTRAINT fk_custody_cases_opened_by REFERENCES users (id),
            opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_by INTEGER CONSTRAINT fk_custody_cases_resolved_by REFERENCES users (id),
            resolved_at TIMESTAMPTZ,
            resolution_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_custody_cases_status CHECK (status IN {_in(CUSTODY_CASE_STATUSES)}),
            CONSTRAINT ck_custody_cases_resolution CHECK ((status = 'open') = (resolved_at IS NULL))
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_custody_cases_open ON custody_cases (booking_id) WHERE status = 'open'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_custody_cases_booking ON custody_cases (booking_id, id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION custody_cases_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'custody_cases cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.status <> 'open' THEN
                RAISE EXCEPTION 'a resolved custody case is final' USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.booking_id, NEW.opened_reason_code, NEW.opened_by, NEW.opened_at, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.booking_id, OLD.opened_reason_code, OLD.opened_by, OLD.opened_at, OLD.created_at) THEN
                RAISE EXCEPTION 'custody case opening record is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_custody_cases_guard",
        "custody_cases",
        "TRIGGER trg_custody_cases_guard BEFORE UPDATE OR DELETE ON custody_cases "
        "FOR EACH ROW EXECUTE FUNCTION custody_cases_guard()",
    )
    _trigger(
        "trg_custody_cases_no_truncate",
        "custody_cases",
        "TRIGGER trg_custody_cases_no_truncate BEFORE TRUNCATE ON custody_cases "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
