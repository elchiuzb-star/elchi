"""trips driver directions: a driver's standing direction, trips made from it, driver time proposals (ADR-0027)

Owner: trips + marketplace (ADR-0027) - integrator A0a.
Content (DATA_MODEL.md §5):
  * ``driver_directions`` - a driver's "where from -> where to" (region + optional district on each end), the car and
    the capacity it offers, status ``active`` / ``paused`` / ``archived``, row ``version``. No time, no stop, no
    corridor is asked from the driver (Q150): the corridor the server resolved is stored for matching only. One live
    (not archived) direction per driver and pair of ends (``NULLS NOT DISTINCT``: a region-only end is one value).
  * ``trips.direction_id`` - the direction a trip was made from (nullable: manual and legacy trips have none).
  * ``proposal_versions.outside_request_window`` - a driver's time proposal (Q153): the pickup window lies outside
    the client's request window, so only the client's own accept or counter turns it into a booking.

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20261006_0096
Revises: 20260925_0095
Create Date: 2026-10-06 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261006_0096"
down_revision: str = "20260925_0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS driver_directions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            driver_user_id INTEGER NOT NULL,
            vehicle_id BIGINT NOT NULL,
            corridor_id BIGINT NOT NULL,
            origin_region_id BIGINT NOT NULL,
            origin_district_id BIGINT,
            destination_region_id BIGINT NOT NULL,
            destination_district_id BIGINT,
            seat_capacity SMALLINT NOT NULL,
            cargo_capacity_weight_g INTEGER NOT NULL DEFAULT 0,
            cargo_capacity_volume_ml INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_driver_directions_public_id UNIQUE (public_id),
            CONSTRAINT fk_driver_directions_driver_user_id FOREIGN KEY (driver_user_id) REFERENCES users (id),
            CONSTRAINT fk_driver_directions_vehicle_id FOREIGN KEY (vehicle_id) REFERENCES vehicles (id),
            CONSTRAINT fk_driver_directions_corridor_id FOREIGN KEY (corridor_id) REFERENCES service_corridors (id),
            CONSTRAINT fk_driver_directions_origin_region_id FOREIGN KEY (origin_region_id) REFERENCES regions (id),
            CONSTRAINT fk_driver_directions_origin_district_id FOREIGN KEY (origin_district_id) REFERENCES geo_districts (id),
            CONSTRAINT fk_driver_directions_destination_region_id FOREIGN KEY (destination_region_id) REFERENCES regions (id),
            CONSTRAINT fk_driver_directions_destination_district_id FOREIGN KEY (destination_district_id)
                REFERENCES geo_districts (id),
            CONSTRAINT ck_driver_directions_status CHECK (status IN ('active', 'paused', 'archived')),
            CONSTRAINT ck_driver_directions_ends CHECK (
                origin_region_id <> destination_region_id
                OR origin_district_id IS DISTINCT FROM destination_district_id
            ),
            CONSTRAINT ck_driver_directions_capacity CHECK (
                seat_capacity >= 0 AND cargo_capacity_weight_g >= 0 AND cargo_capacity_volume_ml >= 0
                AND (seat_capacity > 0 OR cargo_capacity_weight_g > 0 OR cargo_capacity_volume_ml > 0)
            ),
            CONSTRAINT ck_driver_directions_version CHECK (version >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_driver_directions_driver_status ON driver_directions (driver_user_id, status, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_driver_directions_corridor ON driver_directions (corridor_id)")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_driver_directions_live_ends ON driver_directions
            (driver_user_id, origin_region_id, origin_district_id, destination_region_id, destination_district_id)
            NULLS NOT DISTINCT WHERE status <> 'archived'
        """
    )
    op.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS direction_id BIGINT")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_trips_direction_id') THEN
                ALTER TABLE trips ADD CONSTRAINT fk_trips_direction_id
                    FOREIGN KEY (direction_id) REFERENCES driver_directions (id);
            END IF;
        END
        $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trips_direction_id ON trips (direction_id) WHERE direction_id IS NOT NULL")
    op.execute(
        "ALTER TABLE proposal_versions ADD COLUMN IF NOT EXISTS outside_request_window BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE proposal_versions DROP COLUMN IF EXISTS outside_request_window")
    op.execute("DROP INDEX IF EXISTS ix_trips_direction_id")
    op.execute("ALTER TABLE trips DROP CONSTRAINT IF EXISTS fk_trips_direction_id")
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS direction_id")
    op.execute("DROP TABLE IF EXISTS driver_directions")
