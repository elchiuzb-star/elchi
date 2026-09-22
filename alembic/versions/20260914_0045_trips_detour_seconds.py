"""trips detour seconds + marketplace terms version and offer labels (wave 1.6)

Owner: A1 (wave 1.6) - modules `trips`, `marketplace`.
Content (DATA_MODEL.md §5, wave 1.6):
  * trips.detour_used_s (seconds; A2/AGENTS §6 "Detour"), backfilled from detour_used_minutes x 60,
    CHECK detour_used_s <= max_detour_minutes x 60. detour_used_minutes stays (expand-only) and is
    no longer written by v2 code; detour_used_m already exists in metres.
  * listings.terms_version (BR N1): bumped only by proposal-invalidating edits; listings.version keeps
    counting every edit for optimistic concurrency. proposal_versions.listing_terms_version snapshots
    it; A4 compares listing_terms_version with listings.terms_version at accept.
  * listing_offer_labels (R1, Q40): stable anonymous "Haydovchi #N" ordinal per (listing, driver),
    independent of user and public ids.

Rules: idempotent (IF NOT EXISTS / guarded DO blocks, re-runnable backfills); do not change the
revision id, file name or down_revision; single head. downgrade() is not a rollback strategy
(ADR-0016, spec §18.3).

Revision ID: 20260914_0045
Revises: 20260914_0044
Create Date: 2026-09-14 00:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260914_0045"
down_revision: str = "20260914_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_constraint_if_missing(table: str, name: str, definition: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}' AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- trips: detour counter in seconds (N5) -----------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns WHERE table_name = 'trips' AND column_name = 'detour_used_s'
            ) THEN
                ALTER TABLE trips ADD COLUMN detour_used_s INTEGER NOT NULL DEFAULT 0;
                UPDATE trips SET detour_used_s = detour_used_minutes * 60 WHERE detour_used_minutes <> 0;
            END IF;
        END $$;
        """
    )
    _add_constraint_if_missing(
        "trips",
        "ck_trips_detour_used_s",
        "CHECK (detour_used_s >= 0 AND detour_used_s <= max_detour_minutes * 60)",
    )

    # --- listings / proposal_versions: terms version (N1) -------------------------------
    op.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS terms_version INTEGER NOT NULL DEFAULT 1")
    _add_constraint_if_missing("listings", "ck_listings_terms_version", "CHECK (terms_version >= 1 AND terms_version <= version)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'proposal_versions' AND column_name = 'listing_terms_version'
            ) THEN
                -- Pre-launch backfill: no edit has bumped terms_version yet, so every snapshot is 1.
                ALTER TABLE proposal_versions ADD COLUMN listing_terms_version INTEGER NOT NULL DEFAULT 1;
            END IF;
        END $$;
        """
    )
    _add_constraint_if_missing(
        "proposal_versions", "ck_proposal_versions_listing_terms_version", "CHECK (listing_terms_version >= 1)"
    )

    # --- listing_offer_labels (R1, Q40) --------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS listing_offer_labels (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            listing_id BIGINT NOT NULL
                CONSTRAINT fk_listing_offer_labels_listing_id REFERENCES listings (id) ON DELETE CASCADE,
            driver_user_id INTEGER NOT NULL
                CONSTRAINT fk_listing_offer_labels_driver_user_id REFERENCES users (id),
            label_seq INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_listing_offer_labels_listing_driver UNIQUE (listing_id, driver_user_id),
            CONSTRAINT uq_listing_offer_labels_listing_seq UNIQUE (listing_id, label_seq),
            CONSTRAINT ck_listing_offer_labels_label_seq CHECK (label_seq >= 1)
        )
        """
    )
    # Existing driver threads get labels in first-contact order; re-runnable (skips labelled pairs).
    op.execute(
        """
        INSERT INTO listing_offer_labels (listing_id, driver_user_id, label_seq)
        SELECT first.listing_id, first.driver_user_id,
               COALESCE(existing.max_seq, 0) + row_number() OVER (PARTITION BY first.listing_id ORDER BY first.first_id)
        FROM (
            SELECT listing_id, driver_user_id, min(id) AS first_id
            FROM proposal_threads GROUP BY listing_id, driver_user_id
        ) AS first
        LEFT JOIN (
            SELECT listing_id, max(label_seq) AS max_seq FROM listing_offer_labels GROUP BY listing_id
        ) AS existing ON existing.listing_id = first.listing_id
        WHERE NOT EXISTS (
            SELECT 1 FROM listing_offer_labels l
            WHERE l.listing_id = first.listing_id AND l.driver_user_id = first.driver_user_id
        )
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
