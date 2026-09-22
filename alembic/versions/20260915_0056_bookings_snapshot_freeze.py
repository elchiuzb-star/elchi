"""bookings snapshot freeze

Owner: A4 (wave 2.1) - module `bookings`.
Content (DATA_MODEL.md §5, WAVE1_CARDS "Wave 2.1"):
  * Q60: ``trg_bookings_snapshot_freeze`` (BEFORE UPDATE on bookings). ``quantity``, ``unit_price_minor``,
    ``total_minor``, ``commission_minor`` and the resource columns (``seats``, ``baggage_ml``, ``cargo_weight_g``,
    ``cargo_volume_ml``) change ONLY together with a ``booking_amendments`` row of the same booking that was moved
    ``proposed -> accepted`` in the same transaction and whose ``new_*`` values match (commission: old commission +
    ``fee_delta_minor``). Every other agreement column is frozen (the 0048 guard keeps its own list; this trigger
    adds price basis, stops, occurrences, windows, route/trip version). Raises
    ``USING ERRCODE = 'restrict_violation', CONSTRAINT = 'booking_snapshot_frozen'`` (v2 envelope 409
    INTEGRITY_CONFLICT). "Same transaction" = a transaction-local marker (``elchi.booking_amendments_accepted``)
    set by an AFTER UPDATE trigger on ``booking_amendments``; it is rolled back with a savepoint. The service
    therefore flushes the amendment status before the booking columns.
  * proof reissue (BR blocker 3): append-only ``booking_proof_reissues`` (who, which side, kind, rotation from/to,
    reason, self-service flag); the self-service rate limit reads it. Rotation increase resets failed_attempts
    (0049 guard already allows this).
  * Q65: no new delivery column - ``service_ended_at`` is the delivery moment and ``booking_status_history`` records
    who confirmed; partial index for the ``awaiting_confirmation`` queue (arrived / delivered by end time).
  * Q66: ``bookings.finance_review_reason`` / ``finance_review_at`` (+ CHECK, partial index for ``finance_review``).
FK / object dependencies: 0048-0051 (bookings, proofs, amendments).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0056
Revises: 20260915_0055
Create Date: 2026-09-15 00:56:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0056"
down_revision: str = "20260915_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FREEZE_RULE = "booking_snapshot_frozen"  # app.contracts.db_errors.CONSTRAINT_RULES
ACCEPTED_AMENDMENTS_SETTING = "elchi.booking_amendments_accepted"
REISSUABLE_PROOF_KINDS = ("boarding_code", "pickup_code", "delivery_code", "return_code")
FINANCE_REVIEW_REASONS = ("dispute_module_unavailable",)  # enums.CommissionReviewReason
# Columns that may change only with an accepted amendment of this transaction (Q60).
AMENDABLE_COLUMNS = (
    "quantity", "unit_price_minor", "total_minor", "commission_minor", "seats", "baggage_ml", "cargo_weight_g", "cargo_volume_ml",
)
# Agreement columns frozen after accept (in addition to the 0048 guard list).
FROZEN_COLUMNS = (
    "id", "public_id", "service_type", "client_user_id", "driver_user_id", "trip_id", "corridor_id", "request_listing_id",
    "supply_listing_id", "proposal_thread_id", "accepted_proposal_version_id", "route_version_id", "trip_version",
    "pickup_stop_id", "dropoff_stop_id", "pickup_occurrence_seq", "dropoff_occurrence_seq", "pickup_window_start",
    "pickup_window_end", "dropoff_window_start", "dropoff_window_end", "price_basis", "currency", "payment_method",
    "fee_policy_id", "fee_bps", "listing_version", "listing_terms_version", "terms_snapshot", "created_at",
)


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _row(prefix: str, columns: Sequence[str]) -> str:
    return "(" + ", ".join(f"{prefix}.{column}" for column in columns) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- Q66 finance review marker ------------------------------------------------------------------------------
    op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS finance_review_reason VARCHAR(48)")
    op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS finance_review_at TIMESTAMPTZ")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_bookings_finance_review') THEN
                ALTER TABLE bookings ADD CONSTRAINT ck_bookings_finance_review CHECK (
                    (finance_review_reason IS NULL) = (finance_review_at IS NULL)
                    AND (finance_review_reason IS NULL OR finance_review_reason IN {_in(FINANCE_REVIEW_REASONS)})
                );
            END IF;
        END
        $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bookings_finance_review ON bookings (id) "
        "WHERE finance_review_reason IS NOT NULL AND commission_status = 'held'"
    )
    # --- Q65 awaiting_confirmation queue (arrived passengers, delivered parcels) -----------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bookings_awaiting_confirmation ON bookings (service_ended_at, id) "
        "WHERE service_status IN ('arrived', 'delivered')"
    )

    # --- proof reissue history (BR blocker 3) ----------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS booking_proof_reissues (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            booking_id BIGINT NOT NULL CONSTRAINT fk_booking_proof_reissues_booking_id REFERENCES bookings (id),
            proof_kind VARCHAR(24) NOT NULL,
            from_rotation SMALLINT NOT NULL,
            to_rotation SMALLINT NOT NULL,
            actor_user_id INTEGER NOT NULL CONSTRAINT fk_booking_proof_reissues_actor_user_id REFERENCES users (id),
            actor_side VARCHAR(16) NOT NULL,
            self_service BOOLEAN NOT NULL,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_booking_proof_reissues_kind CHECK (proof_kind IN {_in(REISSUABLE_PROOF_KINDS)}),
            CONSTRAINT ck_booking_proof_reissues_rotation CHECK (from_rotation >= 0 AND to_rotation = from_rotation + 1),
            CONSTRAINT ck_booking_proof_reissues_side CHECK (
                actor_side IN ('client', 'operator') AND self_service = (actor_side = 'client')
            ),
            CONSTRAINT ck_booking_proof_reissues_reason CHECK (self_service OR coalesce(btrim(reason), '') <> '')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_booking_proof_reissues_booking ON booking_proof_reissues "
        "(booking_id, proof_kind, created_at)"
    )
    _trigger(
        "trg_booking_proof_reissues_append_only",
        "booking_proof_reissues",
        "TRIGGER trg_booking_proof_reissues_append_only BEFORE UPDATE OR DELETE ON booking_proof_reissues "
        "FOR EACH ROW EXECUTE FUNCTION bookings_append_only()",
    )
    _trigger(
        "trg_booking_proof_reissues_no_truncate",
        "booking_proof_reissues",
        "TRIGGER trg_booking_proof_reissues_no_truncate BEFORE TRUNCATE ON booking_proof_reissues "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )

    # --- Q60 accepted-amendment marker + snapshot freeze ------------------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION booking_amendments_mark_accepted() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'proposed' AND NEW.status = 'accepted' THEN
                PERFORM set_config(
                    '{ACCEPTED_AMENDMENTS_SETTING}',
                    coalesce(nullif(current_setting('{ACCEPTED_AMENDMENTS_SETTING}', true), ''), ',') || NEW.id::text || ',',
                    true
                );
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    _trigger(
        "trg_booking_amendments_mark_accepted",
        "booking_amendments",
        "TRIGGER trg_booking_amendments_mark_accepted AFTER UPDATE ON booking_amendments "
        "FOR EACH ROW EXECUTE FUNCTION booking_amendments_mark_accepted()",
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION bookings_snapshot_freeze() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            marker TEXT;
        BEGIN
            IF {_row('NEW', FROZEN_COLUMNS)} IS DISTINCT FROM {_row('OLD', FROZEN_COLUMNS)} THEN
                RAISE EXCEPTION 'booking snapshot column is frozen (Q60)'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{FREEZE_RULE}';
            END IF;
            IF {_row('NEW', AMENDABLE_COLUMNS)} IS NOT DISTINCT FROM {_row('OLD', AMENDABLE_COLUMNS)} THEN
                RETURN NEW;
            END IF;
            marker := current_setting('{ACCEPTED_AMENDMENTS_SETTING}', true);
            IF marker IS NULL OR marker = '' OR NOT EXISTS (
                SELECT 1
                FROM booking_amendments a
                WHERE a.id = ANY (string_to_array(btrim(marker, ','), ',')::bigint[])
                  AND a.booking_id = NEW.id
                  AND a.status = 'accepted'
                  AND a.new_quantity = NEW.quantity
                  AND a.new_unit_price_minor = NEW.unit_price_minor
                  AND a.new_total_minor = NEW.total_minor
                  AND NEW.commission_minor = OLD.commission_minor + a.fee_delta_minor
                  -- resources follow the amendment: pilot amendments change only passenger seats (= quantity);
                  -- baggage and cargo never change, parcel resources stay as agreed (BR M1).
                  AND NEW.baggage_ml = OLD.baggage_ml
                  AND NEW.cargo_weight_g = OLD.cargo_weight_g
                  AND NEW.cargo_volume_ml = OLD.cargo_volume_ml
                  AND (
                      (NEW.service_type = 'passenger' AND NEW.seats = a.new_quantity)
                      OR (NEW.service_type <> 'passenger' AND NEW.seats = OLD.seats)
                  )
            ) THEN
                RAISE EXCEPTION 'booking amount/resource columns change only with an accepted amendment (Q60)'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{FREEZE_RULE}';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_bookings_snapshot_freeze",
        "bookings",
        "TRIGGER trg_bookings_snapshot_freeze BEFORE UPDATE ON bookings "
        "FOR EACH ROW EXECUTE FUNCTION bookings_snapshot_freeze()",
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
