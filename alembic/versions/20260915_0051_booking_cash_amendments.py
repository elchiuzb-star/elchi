"""booking cash receipts, amendments and read-side indexes (A4, wave 2)

Owner: A4 (wave 2) - module `bookings`.
Content (DATA_MODEL.md §1.7; STATE_MACHINES §6, §9; AC26, D9, D10; N4, Q15):
  * cash_receipts - a participant's "cash paid" report and the counterparty's decision. Independent of the
    service status (AC26). Partial unique: at most one undecided (reported_paid / contested) receipt per booking.
  * booking_amendments - two-party change of an accepted agreement (spec §5.3(7)); the fee snapshot bps is kept
    (Q19, D10). Partial unique: one `proposed` amendment per booking.
  * partial indexes for the read-side hooks: v1 account deletion (N4) and v1 block_driver with active v2
    business (Q15) count non-terminal bookings per client / driver.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0051
Revises: 20260915_0050
Create Date: 2026-09-15 00:51:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0051"
down_revision: str = "20260915_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CASH_RECEIPT_STATUSES = ("reported_paid", "acknowledged", "contested", "resolved_paid", "resolved_unpaid")
AMENDMENT_STATUSES = ("proposed", "accepted", "rejected", "withdrawn", "expired")
TERMINAL_SERVICE_STATUSES = ("completed", "cancelled", "no_show", "returned")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- cash_receipts (AC26) ----------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS cash_receipts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            booking_id BIGINT NOT NULL CONSTRAINT fk_cash_receipts_booking_id REFERENCES bookings (id),
            reported_by_side VARCHAR(16) NOT NULL,
            reported_by_user_id INTEGER NOT NULL CONSTRAINT fk_cash_receipts_reported_by_user_id REFERENCES users (id),
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            status VARCHAR(24) NOT NULL DEFAULT 'reported_paid',
            reported_at TIMESTAMPTZ NOT NULL,
            note TEXT,
            decided_by_user_id INTEGER CONSTRAINT fk_cash_receipts_decided_by_user_id REFERENCES users (id),
            decided_at TIMESTAMPTZ,
            decision_comment TEXT,
            dispute_id BIGINT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cash_receipts_public_id UNIQUE (public_id),
            CONSTRAINT ck_cash_receipts_side CHECK (reported_by_side IN ('client', 'driver')),
            CONSTRAINT ck_cash_receipts_amount CHECK (amount_minor > 0),
            CONSTRAINT ck_cash_receipts_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_cash_receipts_status CHECK (status IN {_in(CASH_RECEIPT_STATUSES)}),
            CONSTRAINT ck_cash_receipts_decision CHECK ((status = 'reported_paid') = (decided_at IS NULL)),
            CONSTRAINT ck_cash_receipts_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cash_receipts_open ON cash_receipts (booking_id) "
        "WHERE status IN ('reported_paid', 'contested')"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_cash_receipts_booking ON cash_receipts (booking_id, id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cash_receipts_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'cash_receipts cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.public_id, NEW.booking_id, NEW.reported_by_side, NEW.reported_by_user_id, NEW.amount_minor,
                NEW.currency, NEW.reported_at, NEW.note, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.public_id, OLD.booking_id, OLD.reported_by_side, OLD.reported_by_user_id, OLD.amount_minor,
                OLD.currency, OLD.reported_at, OLD.note, OLD.created_at) THEN
                RAISE EXCEPTION 'cash receipt report is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.status IN ('acknowledged', 'resolved_paid', 'resolved_unpaid') THEN
                RAISE EXCEPTION 'cash receipt status % is final', OLD.status USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_cash_receipts_guard",
        "cash_receipts",
        "TRIGGER trg_cash_receipts_guard BEFORE UPDATE OR DELETE ON cash_receipts "
        "FOR EACH ROW EXECUTE FUNCTION cash_receipts_guard()",
    )
    _trigger(
        "trg_cash_receipts_no_truncate",
        "cash_receipts",
        "TRIGGER trg_cash_receipts_no_truncate BEFORE TRUNCATE ON cash_receipts "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )

    # --- booking_amendments (D9, D10) ----------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS booking_amendments (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            booking_id BIGINT NOT NULL CONSTRAINT fk_booking_amendments_booking_id REFERENCES bookings (id),
            booking_version INTEGER NOT NULL,
            author_side VARCHAR(16) NOT NULL,
            author_user_id INTEGER NOT NULL CONSTRAINT fk_booking_amendments_author_user_id REFERENCES users (id),
            status VARCHAR(16) NOT NULL DEFAULT 'proposed',
            changes JSONB NOT NULL,
            new_quantity INTEGER NOT NULL,
            new_unit_price_minor BIGINT NOT NULL,
            new_total_minor BIGINT NOT NULL,
            fee_delta_minor BIGINT NOT NULL,
            reason TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            decided_by_user_id INTEGER CONSTRAINT fk_booking_amendments_decided_by_user_id REFERENCES users (id),
            decided_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_booking_amendments_public_id UNIQUE (public_id),
            CONSTRAINT ck_booking_amendments_author_side CHECK (author_side IN ('client', 'driver')),
            CONSTRAINT ck_booking_amendments_status CHECK (status IN {_in(AMENDMENT_STATUSES)}),
            CONSTRAINT ck_booking_amendments_amounts CHECK (
                new_quantity > 0 AND new_unit_price_minor > 0 AND new_total_minor > 0
            ),
            CONSTRAINT ck_booking_amendments_decision CHECK ((status = 'proposed') = (decided_at IS NULL)),
            CONSTRAINT ck_booking_amendments_version CHECK (version >= 1 AND booking_version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_amendments_proposed ON booking_amendments (booking_id) "
        "WHERE status = 'proposed'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_booking_amendments_booking ON booking_amendments (booking_id, id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION booking_amendments_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'booking_amendments cannot be deleted' USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.status <> 'proposed' THEN
                RAISE EXCEPTION 'amendment status % is final', OLD.status USING ERRCODE = 'restrict_violation';
            END IF;
            IF (NEW.id, NEW.public_id, NEW.booking_id, NEW.booking_version, NEW.author_side, NEW.author_user_id,
                NEW.changes, NEW.new_quantity, NEW.new_unit_price_minor, NEW.new_total_minor, NEW.fee_delta_minor,
                NEW.reason, NEW.expires_at, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.public_id, OLD.booking_id, OLD.booking_version, OLD.author_side, OLD.author_user_id,
                OLD.changes, OLD.new_quantity, OLD.new_unit_price_minor, OLD.new_total_minor, OLD.fee_delta_minor,
                OLD.reason, OLD.expires_at, OLD.created_at) THEN
                RAISE EXCEPTION 'amendment content is immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_booking_amendments_guard",
        "booking_amendments",
        "TRIGGER trg_booking_amendments_guard BEFORE UPDATE OR DELETE ON booking_amendments "
        "FOR EACH ROW EXECUTE FUNCTION booking_amendments_guard()",
    )
    _trigger(
        "trg_booking_amendments_no_truncate",
        "booking_amendments",
        "TRIGGER trg_booking_amendments_no_truncate BEFORE TRUNCATE ON booking_amendments "
        "FOR EACH STATEMENT EXECUTE FUNCTION bookings_reject_truncate()",
    )

    # --- read-side hooks (N4 account deletion, Q15 v1 block_driver) ------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bookings_client_open ON bookings (client_user_id) "
        f"WHERE service_status NOT IN {_in(TERMINAL_SERVICE_STATUSES)}"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bookings_driver_open ON bookings (driver_user_id) "
        f"WHERE service_status NOT IN {_in(TERMINAL_SERVICE_STATUSES)}"
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
