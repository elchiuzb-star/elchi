"""bookings positions without stops: stop-less roads and bookings on road-stretch trips (ADR-0028 phase 3)

Owner: bookings (ADR-0028, Q159) - integrator A0a.
Content (DATA_MODEL.md §5):
  * ``bookings.pickup_occurrence_seq`` / ``dropoff_occurrence_seq`` become nullable: a trip the system plans from a
    driver direction (or any trip created without legacy stops) has no ``trip_stop_occurrences``, so its bookings
    carry only their road positions. Bookings on trips with a legacy stop echo keep both.
  * ``ck_bookings_place_known``: both seqs or neither, and a booking without seqs has both road positions - a
    booking always says where it rides.
  * ``geo_route_versions_guard()`` (0035): a road may be confirmed with no stop at all (built from the corridor's two
    ends); legacy stops, when present, are still a gapless sequence of at least two.

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20261007_0100
Revises: 20261007_0099
Create Date: 2026-10-07 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007_0100"
down_revision: str = "20261007_0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_route_versions_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            stop_count INTEGER;
            max_seq INTEGER;
            bad_order INTEGER;
        BEGIN
            IF OLD.status = 'confirmed' THEN
                RAISE EXCEPTION 'confirmed route_versions are immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.public_id IS DISTINCT FROM OLD.public_id
               OR NEW.corridor_id IS DISTINCT FROM OLD.corridor_id
               OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
               OR NEW.source IS DISTINCT FROM OLD.source OR NEW.provider IS DISTINCT FROM OLD.provider
               OR NEW.provider_version IS DISTINCT FROM OLD.provider_version
               OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
               OR NOT ST_Equals(NEW.geometry, OLD.geometry) OR NEW.distance_m IS DISTINCT FROM OLD.distance_m
               OR NEW.duration_s IS DISTINCT FROM OLD.duration_s OR NEW.is_estimate IS DISTINCT FROM OLD.is_estimate
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'route_versions content is immutable; create a new version'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.status = 'confirmed' THEN
                SELECT count(*), max(seq) INTO stop_count, max_seq
                FROM route_version_stops WHERE route_version_id = NEW.id;
                -- ADR-0028 phase 3: a road built from its two ends has no stop at all; legacy stops, when present,
                -- are still a gapless 0..n-1 sequence of at least two.
                IF stop_count = 1 OR (stop_count >= 2 AND max_seq <> stop_count - 1) THEN
                    RAISE EXCEPTION 'route_versions needs no stops or stops with seq 0..n-1 (n >= 2) before confirmation'
                        USING ERRCODE = 'check_violation';
                END IF;
                SELECT count(*) INTO bad_order FROM (
                    SELECT cumulative_distance_m < lag(cumulative_distance_m) OVER w
                           OR cumulative_duration_s < lag(cumulative_duration_s) OVER w AS bad
                    FROM route_version_stops WHERE route_version_id = NEW.id
                    WINDOW w AS (ORDER BY seq)
                ) s WHERE s.bad;
                IF bad_order > 0 THEN
                    RAISE EXCEPTION 'route_version_stops cumulative values must be non-decreasing'
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute("ALTER TABLE bookings ALTER COLUMN pickup_occurrence_seq DROP NOT NULL")
    op.execute("ALTER TABLE bookings ALTER COLUMN dropoff_occurrence_seq DROP NOT NULL")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_bookings_place_known') THEN
                ALTER TABLE bookings ADD CONSTRAINT ck_bookings_place_known CHECK (
                    (pickup_occurrence_seq IS NULL) = (dropoff_occurrence_seq IS NULL)
                    AND (pickup_occurrence_seq IS NOT NULL
                         OR (pickup_position_m IS NOT NULL AND dropoff_position_m IS NOT NULL))
                );
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    """Dev/test only: fails if stop-less bookings exist (as it should - they have no seq to restore)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ck_bookings_place_known")
    op.execute("ALTER TABLE bookings ALTER COLUMN dropoff_occurrence_seq SET NOT NULL")
    op.execute("ALTER TABLE bookings ALTER COLUMN pickup_occurrence_seq SET NOT NULL")
