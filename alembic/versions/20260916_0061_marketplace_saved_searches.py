"""marketplace saved searches

Owner: A5 (wave 3) - module `marketplace.feed` (sub-package app/modules/marketplace/feed/, A1 owns the rest of
marketplace).
Content (DATA_MODEL.md §1.5 and §5, WAVE1_CARDS "Wave 3", spec §6.6, §8, AC18, AC35, AC36):
  * saved_searches (public_id svs_, user_id FK users, service_type (enums.ServiceType), side (enums.FeedSide),
    origin_stop_id? FK corridor_stops | origin_region_id? FK regions, destination_stop_id? | destination_region_id?
    (CHECK exactly one per end), time_window_start, time_window_end (CHECK end > start), quantity (CHECK > 0),
    notify BOOLEAN, last_notified_at?, deleted_at?, created_at, updated_at)
  * per-user limit feed.SAVED_SEARCH_MAX_PER_USER: service check under the users lock (FOR NO KEY UPDATE) plus guard
    trigger RAISE ... USING CONSTRAINT = 'saved_search_limit' (db_errors -> SAVED_SEARCH_LIMIT_REACHED). The guard
    counts live searches (not deleted, window not over) and takes the same users row lock itself, so concurrent
    inserts that bypass the service are serialised too.
  * saved_search_notifications (saved_search_id, listing_id, notified_at; UNIQUE(saved_search_id, listing_id)) -
    one saved_search.matched event per listing (§6.6 duplicate push)
FK / object dependencies: 0039 (listings), 0034 (regions, corridor_stops), 0032 (users).
No FK to other wave 3 modules (tracking 0058, communications 0059, trust_support 0060).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0061
Revises: 20260916_0060
Create Date: 2026-09-16 01:01:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0061"
down_revision: str = "20260916_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of app.contracts.feed.SAVED_SEARCH_MAX_PER_USER at the time of this migration (pilot default, U4).
# tests/modules/marketplace/feed asserts they are equal; changing the limit needs a forward migration.
SAVED_SEARCH_LIMIT = 10


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_searches (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            user_id INTEGER NOT NULL,
            service_type VARCHAR(16) NOT NULL,
            side VARCHAR(16) NOT NULL,
            origin_stop_id BIGINT,
            origin_region_id BIGINT,
            destination_stop_id BIGINT,
            destination_region_id BIGINT,
            time_window_start TIMESTAMPTZ NOT NULL,
            time_window_end TIMESTAMPTZ NOT NULL,
            quantity INTEGER NOT NULL,
            notify BOOLEAN NOT NULL DEFAULT true,
            last_notified_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_saved_searches_public_id UNIQUE (public_id),
            CONSTRAINT fk_saved_searches_user_id FOREIGN KEY (user_id) REFERENCES users (id),
            CONSTRAINT fk_saved_searches_origin_stop_id FOREIGN KEY (origin_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_saved_searches_origin_region_id FOREIGN KEY (origin_region_id) REFERENCES regions (id),
            CONSTRAINT fk_saved_searches_destination_stop_id
                FOREIGN KEY (destination_stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT fk_saved_searches_destination_region_id
                FOREIGN KEY (destination_region_id) REFERENCES regions (id),
            CONSTRAINT ck_saved_searches_service_type CHECK (service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_saved_searches_side CHECK (side IN ('requests', 'offers')),
            CONSTRAINT ck_saved_searches_origin_one CHECK (num_nonnulls(origin_stop_id, origin_region_id) = 1),
            CONSTRAINT ck_saved_searches_destination_one
                CHECK (num_nonnulls(destination_stop_id, destination_region_id) = 1),
            CONSTRAINT ck_saved_searches_window CHECK (time_window_end > time_window_start),
            CONSTRAINT ck_saved_searches_quantity CHECK (quantity > 0),
            CONSTRAINT ck_saved_searches_parcel_quantity CHECK (service_type <> 'parcel' OR quantity = 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_saved_searches_user_created ON saved_searches (user_id, created_at, id) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_saved_searches_notify_match "
        "ON saved_searches (service_type, side, time_window_end) WHERE deleted_at IS NULL AND notify"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_search_notifications (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            saved_search_id BIGINT NOT NULL,
            listing_id BIGINT NOT NULL,
            notified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_saved_search_notifications_search_listing UNIQUE (saved_search_id, listing_id),
            CONSTRAINT fk_saved_search_notifications_saved_search_id
                FOREIGN KEY (saved_search_id) REFERENCES saved_searches (id),
            CONSTRAINT fk_saved_search_notifications_listing_id FOREIGN KEY (listing_id) REFERENCES listings (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_saved_search_notifications_listing_id ON saved_search_notifications (listing_id)"
    )

    # Limit guard (feed.SAVED_SEARCH_MAX_PER_USER). Lock order: users row first (ADR-0017), FOR NO KEY UPDATE so FK
    # inserts (FOR KEY SHARE) are not blocked; re-entrant when the service already holds it.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION saved_searches_limit_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            live_count INTEGER;
        BEGIN
            IF NEW.deleted_at IS NOT NULL OR NEW.time_window_end <= now() THEN
                RETURN NEW;
            END IF;
            PERFORM 1 FROM users WHERE id = NEW.user_id FOR NO KEY UPDATE;
            SELECT count(*) INTO live_count
              FROM saved_searches
             WHERE user_id = NEW.user_id
               AND deleted_at IS NULL
               AND time_window_end > now()
               AND id IS DISTINCT FROM NEW.id;
            IF live_count >= {SAVED_SEARCH_LIMIT} THEN
                RAISE EXCEPTION 'saved search limit reached for user %', NEW.user_id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'saved_search_limit';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_saved_searches_limit ON saved_searches")
    op.execute(
        "CREATE TRIGGER trg_saved_searches_limit BEFORE INSERT OR UPDATE OF deleted_at, user_id, time_window_end "
        "ON saved_searches FOR EACH ROW EXECUTE FUNCTION saved_searches_limit_guard()"
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
