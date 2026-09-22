"""booking proofs: booking_proofs, booking_proof_attempts (A4, wave 2)

Owner: A4 (wave 2) - module `bookings`.
Content (DATA_MODEL.md §1.7; spec §11; ADR-0018 §2-§3, §7 N5):
  * booking_proofs - one row per (booking, proof_kind): the code rotation and key version it was issued
    under, the failed-attempt counter (<= 5, then PROOF_ATTEMPTS_EXCEEDED until an operator rotates) and the
    acceptance record. Codes are never stored in plaintext: they are derived from the proof-code keyring
    (``crypto.derive_proof_code``); only the keyed hash of the accepted code is kept as evidence.
    Guard: an accepted proof is final; attempts only grow unless the rotation grows (operator reset).
  * booking_proof_attempts - append-only log of every submitted code (success or failure, no code text).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0049
Revises: 20260915_0048
Create Date: 2026-09-15 00:49:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0049"
down_revision: str = "20260915_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROOF_KINDS = ("boarding_code", "pickup_code", "delivery_code", "return_code", "operator_evidence")
MAX_FAILED_ATTEMPTS = 5


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS booking_proofs (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL CONSTRAINT fk_booking_proofs_booking_id REFERENCES bookings (id),
            proof_kind VARCHAR(24) NOT NULL,
            code_rotation SMALLINT NOT NULL DEFAULT 0,
            key_version SMALLINT NOT NULL DEFAULT 1,
            failed_attempts SMALLINT NOT NULL DEFAULT 0,
            code_hash CHAR(64),
            accepted_at TIMESTAMPTZ,
            actor_user_id INTEGER CONSTRAINT fk_booking_proofs_actor_user_id REFERENCES users (id),
            evidence_file_ids TEXT[] NOT NULL DEFAULT '{{}}',
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_booking_proofs_booking_kind UNIQUE (booking_id, proof_kind),
            CONSTRAINT ck_booking_proofs_kind CHECK (proof_kind IN {_in(PROOF_KINDS)}),
            CONSTRAINT ck_booking_proofs_failed_attempts CHECK (failed_attempts BETWEEN 0 AND {MAX_FAILED_ATTEMPTS}),
            CONSTRAINT ck_booking_proofs_rotation CHECK (code_rotation >= 0 AND key_version >= 1),
            CONSTRAINT ck_booking_proofs_accepted CHECK (
                (accepted_at IS NULL) = (actor_user_id IS NULL) AND (accepted_at IS NOT NULL OR code_hash IS NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION booking_proofs_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'booking_proofs cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.booking_id, NEW.proof_kind, NEW.created_at)
               IS DISTINCT FROM (OLD.id, OLD.booking_id, OLD.proof_kind, OLD.created_at) THEN
                RAISE EXCEPTION 'booking proof identity is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.accepted_at IS NOT NULL THEN
                RAISE EXCEPTION 'an accepted booking proof is final' USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.code_rotation < OLD.code_rotation THEN
                RAISE EXCEPTION 'proof code rotation cannot decrease' USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.code_rotation = OLD.code_rotation AND NEW.failed_attempts < OLD.failed_attempts THEN
                RAISE EXCEPTION 'failed proof attempts reset only with a new code rotation'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_booking_proofs_guard",
        "booking_proofs",
        "TRIGGER trg_booking_proofs_guard BEFORE UPDATE OR DELETE ON booking_proofs "
        "FOR EACH ROW EXECUTE FUNCTION booking_proofs_guard()",
    )
    _trigger(
        "trg_booking_proofs_no_truncate",
        "booking_proofs",
        "TRIGGER trg_booking_proofs_no_truncate BEFORE TRUNCATE ON booking_proofs "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS booking_proof_attempts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL CONSTRAINT fk_booking_proof_attempts_booking_id REFERENCES bookings (id),
            proof_kind VARCHAR(24) NOT NULL,
            code_rotation SMALLINT NOT NULL,
            actor_user_id INTEGER NOT NULL CONSTRAINT fk_booking_proof_attempts_actor_user_id REFERENCES users (id),
            succeeded BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_booking_proof_attempts_kind CHECK (proof_kind IN {_in(PROOF_KINDS)})
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_booking_proof_attempts_booking ON booking_proof_attempts (booking_id, proof_kind, id)"
    )
    _trigger(
        "trg_booking_proof_attempts_append_only",
        "booking_proof_attempts",
        "TRIGGER trg_booking_proof_attempts_append_only BEFORE UPDATE OR DELETE ON booking_proof_attempts "
        "FOR EACH ROW EXECUTE FUNCTION bookings_append_only()",
    )
    _trigger(
        "trg_booking_proof_attempts_no_truncate",
        "booking_proof_attempts",
        "TRIGGER trg_booking_proof_attempts_no_truncate BEFORE TRUNCATE ON booking_proof_attempts "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
