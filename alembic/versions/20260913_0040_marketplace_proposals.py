"""marketplace: proposal threads and immutable proposal versions

Owner: A1 (wave 1) - module `marketplace`.
Content (DATA_MODEL.md §1.5, §5): proposal_threads (client <> driver, price revisions
0..3, partial unique open thread per listing/parties/trip), proposal_versions (UNIQUE thread_id+revision,
content-immutable trigger allowing only status/status_reason/closed_at, partial unique active
version per thread, fee quote snapshot fee_policy_id/fee_bps/commission_minor).
Tables: proposal_threads, proposal_versions.
FK dependencies: listings (0039), trips (0038), corridor_stops (0034), route_versions (0035),
commission_policies (0036), users (legacy).

Notes:
* The open-thread index uses NULLS NOT DISTINCT (PostgreSQL 15+) instead of coalesce(trip_id, 0),
  so a NULL trip still collides and no expression index is needed.
* The immutability trigger compares the whole row minus status/status_reason/closed_at, so a
  column added later is immutable by default; a status can change only away from 'active'.
* The fee quote (fee_policy_id, fee_bps, commission_minor) is frozen in the version and is valid
  until expires_at (AC43, D13).

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0040
Revises: 20260913_0039
Create Date: 2026-09-13 00:40:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0040"
down_revision: str = "20260913_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS proposal_threads (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            listing_id BIGINT NOT NULL CONSTRAINT fk_proposal_threads_listing_id REFERENCES listings (id),
            client_user_id INTEGER NOT NULL CONSTRAINT fk_proposal_threads_client_user_id REFERENCES users (id),
            driver_user_id INTEGER NOT NULL CONSTRAINT fk_proposal_threads_driver_user_id REFERENCES users (id),
            trip_id BIGINT NULL CONSTRAINT fk_proposal_threads_trip_id REFERENCES trips (id),
            state VARCHAR(16) NOT NULL DEFAULT 'open',
            current_version_id BIGINT NULL,
            client_price_revisions SMALLINT NOT NULL DEFAULT 0,
            driver_price_revisions SMALLINT NOT NULL DEFAULT 0,
            closed_reason VARCHAR(64) NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_proposal_threads_public_id UNIQUE (public_id),
            CONSTRAINT ck_proposal_threads_distinct_parties CHECK (client_user_id <> driver_user_id),
            CONSTRAINT ck_proposal_threads_state CHECK (state IN ('open', 'accepted', 'closed')),
            CONSTRAINT ck_proposal_threads_client_price_revisions CHECK (client_price_revisions BETWEEN 0 AND 3),
            CONSTRAINT ck_proposal_threads_driver_price_revisions CHECK (driver_price_revisions BETWEEN 0 AND 3),
            CONSTRAINT ck_proposal_threads_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_proposal_threads_open_context
        ON proposal_threads (listing_id, client_user_id, driver_user_id, trip_id) NULLS NOT DISTINCT
        WHERE state = 'open'
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proposal_threads_listing_state ON proposal_threads (listing_id, state, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proposal_threads_client_user_id ON proposal_threads (client_user_id, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proposal_threads_driver_user_id ON proposal_threads (driver_user_id, id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_proposal_threads_trip_id ON proposal_threads (trip_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS proposal_versions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            thread_id BIGINT NOT NULL CONSTRAINT fk_proposal_versions_thread_id REFERENCES proposal_threads (id),
            revision SMALLINT NOT NULL,
            author_side VARCHAR(16) NOT NULL,
            author_user_id INTEGER NOT NULL CONSTRAINT fk_proposal_versions_author_user_id REFERENCES users (id),
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            status_reason VARCHAR(64) NULL,
            pickup_stop_id BIGINT NOT NULL CONSTRAINT fk_proposal_versions_pickup_stop_id REFERENCES corridor_stops (id),
            dropoff_stop_id BIGINT NOT NULL
                CONSTRAINT fk_proposal_versions_dropoff_stop_id REFERENCES corridor_stops (id),
            pickup_occurrence_seq SMALLINT NULL,
            dropoff_occurrence_seq SMALLINT NULL,
            pickup_window_start TIMESTAMPTZ NOT NULL,
            pickup_window_end TIMESTAMPTZ NOT NULL,
            quantity INTEGER NOT NULL,
            price_basis VARCHAR(16) NOT NULL,
            unit_price_minor BIGINT NOT NULL,
            total_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL DEFAULT 'UZS',
            expires_at TIMESTAMPTZ NOT NULL,
            listing_version INTEGER NOT NULL,
            trip_version INTEGER NULL,
            route_version_id BIGINT NULL
                CONSTRAINT fk_proposal_versions_route_version_id REFERENCES route_versions (id),
            fee_policy_id BIGINT NOT NULL
                CONSTRAINT fk_proposal_versions_fee_policy_id REFERENCES commission_policies (id),
            fee_bps INTEGER NOT NULL,
            commission_minor BIGINT NOT NULL,
            message TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed_at TIMESTAMPTZ NULL,
            CONSTRAINT uq_proposal_versions_public_id UNIQUE (public_id),
            CONSTRAINT uq_proposal_versions_thread_revision UNIQUE (thread_id, revision),
            CONSTRAINT ck_proposal_versions_revision CHECK (revision >= 1),
            CONSTRAINT ck_proposal_versions_author_side CHECK (author_side IN ('client', 'driver')),
            CONSTRAINT ck_proposal_versions_status
                CHECK (status IN ('active', 'superseded', 'accepted', 'rejected', 'withdrawn', 'expired')),
            CONSTRAINT ck_proposal_versions_price_basis CHECK (price_basis IN ('per_seat', 'total')),
            CONSTRAINT ck_proposal_versions_currency CHECK (currency = 'UZS'),
            CONSTRAINT ck_proposal_versions_distinct_stops CHECK (pickup_stop_id <> dropoff_stop_id),
            CONSTRAINT ck_proposal_versions_occurrence_order CHECK (
                pickup_occurrence_seq IS NULL OR dropoff_occurrence_seq IS NULL
                OR pickup_occurrence_seq < dropoff_occurrence_seq
            ),
            CONSTRAINT ck_proposal_versions_pickup_window CHECK (pickup_window_end > pickup_window_start),
            CONSTRAINT ck_proposal_versions_positive_price_quantity CHECK (quantity > 0 AND unit_price_minor > 0),
            CONSTRAINT ck_proposal_versions_total_minor CHECK (
                total_minor = CASE price_basis
                    WHEN 'per_seat' THEN unit_price_minor * quantity
                    ELSE unit_price_minor
                END
            ),
            CONSTRAINT ck_proposal_versions_fee CHECK (
                fee_bps BETWEEN 0 AND 10000 AND commission_minor >= 0 AND commission_minor <= total_minor
            ),
            CONSTRAINT ck_proposal_versions_closed_at CHECK ((status = 'active') = (closed_at IS NULL)),
            CONSTRAINT ck_proposal_versions_message CHECK (message IS NULL OR length(message) <= 500)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_proposal_versions_active
        ON proposal_versions (thread_id) WHERE status = 'active'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_proposal_versions_active_expires_at
        ON proposal_versions (expires_at) WHERE status = 'active'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_proposal_threads_current_version_id'
                  AND conrelid = 'proposal_threads'::regclass
            ) THEN
                ALTER TABLE proposal_threads ADD CONSTRAINT fk_proposal_threads_current_version_id
                    FOREIGN KEY (current_version_id) REFERENCES proposal_versions (id);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION marketplace_proposal_versions_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'proposal versions are immutable and cannot be deleted'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status', 'status_reason', 'closed_at'])
               IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'status_reason', 'closed_at']) THEN
                RAISE EXCEPTION 'proposal version content is immutable'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND OLD.status <> 'active' THEN
                RAISE EXCEPTION 'proposal version status % is final (immutable)', OLD.status
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE TRIGGER trg_proposal_versions_immutable
        BEFORE UPDATE OR DELETE ON proposal_versions
        FOR EACH ROW EXECUTE FUNCTION marketplace_proposal_versions_immutable()
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
