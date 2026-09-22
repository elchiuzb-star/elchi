"""trips: trips, stop occurrences, segment resources

Owner: A1 (wave 1) - module `trips`.
Content (DATA_MODEL.md §1.4, §5): trips (status CHECK, blocked_period tstzrange,
EXCLUDE USING gist for driver_user_id and vehicle_id over active statuses - AC13),
trip_stop_occurrences (UNIQUE trip_id+seq), trip_segment_resources (UNIQUE trip_id+from_seq,
CHECK 0 <= used <= capacity for seats / baggage_ml / cargo_weight_g / cargo_volume_ml).
Tables: trips, trip_stop_occurrences, trip_segment_resources.
FK dependencies: users (legacy), vehicles (0037), route_versions and corridor_stops (0034/0035);
btree_gist (0030).

Notes:
* blocked_period is written by the application as [planned_start_at, planned_end_at + buffer);
  a CHECK guarantees it always covers the planned interval, so the exclusion constraint can
  never be dodged by a narrow range.
* completed/cancelled trips fall out of the exclusion predicate (D1).

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0038
Revises: 20260913_0037
Create Date: 2026-09-13 00:38:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0038"
down_revision: str = "20260913_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIP_STATUSES_SQL = "('planned', 'boarding', 'in_progress', 'completed', 'cancelled', 'interrupted')"
ACTIVE_TRIP_STATUSES_SQL = "('planned', 'boarding', 'in_progress', 'interrupted')"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS trips (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            driver_user_id INTEGER NOT NULL CONSTRAINT fk_trips_driver_user_id REFERENCES users (id),
            vehicle_id BIGINT NOT NULL CONSTRAINT fk_trips_vehicle_id REFERENCES vehicles (id),
            route_version_id BIGINT NOT NULL CONSTRAINT fk_trips_route_version_id REFERENCES route_versions (id),
            status VARCHAR(16) NOT NULL DEFAULT 'planned',
            planned_start_at TIMESTAMPTZ NOT NULL,
            planned_end_at TIMESTAMPTZ NOT NULL,
            blocked_period TSTZRANGE NOT NULL,
            booking_cutoff_at TIMESTAMPTZ NOT NULL,
            timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Tashkent',
            seat_capacity SMALLINT NOT NULL,
            baggage_capacity_ml INTEGER NOT NULL DEFAULT 0,
            cargo_capacity_weight_g INTEGER NOT NULL DEFAULT 0,
            cargo_capacity_volume_ml INTEGER NOT NULL DEFAULT 0,
            max_detour_minutes INTEGER NOT NULL,
            max_detour_m INTEGER NOT NULL,
            detour_used_minutes INTEGER NOT NULL DEFAULT 0,
            detour_used_m INTEGER NOT NULL DEFAULT 0,
            pickup_wait_minutes INTEGER NOT NULL DEFAULT 10,
            version INTEGER NOT NULL DEFAULT 1,
            cancel_reason TEXT NULL,
            interrupted_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_trips_public_id UNIQUE (public_id),
            CONSTRAINT ck_trips_status CHECK (status IN {TRIP_STATUSES_SQL}),
            CONSTRAINT ck_trips_planned_interval CHECK (planned_end_at > planned_start_at),
            CONSTRAINT ck_trips_blocked_period_covers_plan CHECK (
                NOT isempty(blocked_period)
                AND NOT lower_inf(blocked_period) AND NOT upper_inf(blocked_period)
                AND lower(blocked_period) <= planned_start_at
                AND upper(blocked_period) >= planned_end_at
            ),
            CONSTRAINT ck_trips_booking_cutoff CHECK (booking_cutoff_at <= planned_start_at),
            CONSTRAINT ck_trips_capacities CHECK (
                seat_capacity >= 0 AND baggage_capacity_ml >= 0
                AND cargo_capacity_weight_g >= 0 AND cargo_capacity_volume_ml >= 0
            ),
            CONSTRAINT ck_trips_detour CHECK (
                max_detour_minutes >= 0 AND max_detour_m >= 0
                AND detour_used_minutes >= 0 AND detour_used_m >= 0
                AND detour_used_minutes <= max_detour_minutes AND detour_used_m <= max_detour_m
            ),
            CONSTRAINT ck_trips_pickup_wait_minutes CHECK (pickup_wait_minutes >= 0),
            CONSTRAINT ck_trips_version CHECK (version >= 1),
            CONSTRAINT ex_trips_driver_overlap EXCLUDE USING gist (
                driver_user_id WITH =, blocked_period WITH &&
            ) WHERE (status IN {ACTIVE_TRIP_STATUSES_SQL}),
            CONSTRAINT ex_trips_vehicle_overlap EXCLUDE USING gist (
                vehicle_id WITH =, blocked_period WITH &&
            ) WHERE (status IN {ACTIVE_TRIP_STATUSES_SQL})
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_trips_driver_user_id_planned_start_at "
        "ON trips (driver_user_id, planned_start_at, id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trips_vehicle_id ON trips (vehicle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_trips_status_planned_start_at ON trips (status, planned_start_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trip_stop_occurrences (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            trip_id BIGINT NOT NULL
                CONSTRAINT fk_trip_stop_occurrences_trip_id REFERENCES trips (id) ON DELETE CASCADE,
            seq SMALLINT NOT NULL,
            stop_id BIGINT NOT NULL CONSTRAINT fk_trip_stop_occurrences_stop_id REFERENCES corridor_stops (id),
            route_version_stop_seq SMALLINT NOT NULL,
            planned_arrival_at TIMESTAMPTZ NOT NULL,
            dwell_minutes SMALLINT NOT NULL DEFAULT 0,
            eta_arrival_at TIMESTAMPTZ NULL,
            CONSTRAINT uq_trip_stop_occurrences_trip_seq UNIQUE (trip_id, seq),
            CONSTRAINT ck_trip_stop_occurrences_seq CHECK (seq >= 1 AND route_version_stop_seq >= 0),
            CONSTRAINT ck_trip_stop_occurrences_dwell_minutes CHECK (dwell_minutes >= 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trip_segment_resources (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            trip_id BIGINT NOT NULL
                CONSTRAINT fk_trip_segment_resources_trip_id REFERENCES trips (id) ON DELETE CASCADE,
            from_seq SMALLINT NOT NULL,
            to_seq SMALLINT NOT NULL,
            seat_capacity SMALLINT NOT NULL,
            seats_used SMALLINT NOT NULL DEFAULT 0,
            baggage_capacity_ml INTEGER NOT NULL,
            baggage_used_ml INTEGER NOT NULL DEFAULT 0,
            cargo_capacity_weight_g INTEGER NOT NULL,
            cargo_used_weight_g INTEGER NOT NULL DEFAULT 0,
            cargo_capacity_volume_ml INTEGER NOT NULL,
            cargo_used_volume_ml INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_trip_segment_resources_trip_from_seq UNIQUE (trip_id, from_seq),
            CONSTRAINT ck_trip_segment_resources_adjacent CHECK (from_seq >= 1 AND to_seq = from_seq + 1),
            CONSTRAINT ck_trip_segment_resources_seats CHECK (seats_used >= 0 AND seats_used <= seat_capacity),
            CONSTRAINT ck_trip_segment_resources_baggage
                CHECK (baggage_used_ml >= 0 AND baggage_used_ml <= baggage_capacity_ml),
            CONSTRAINT ck_trip_segment_resources_cargo_weight
                CHECK (cargo_used_weight_g >= 0 AND cargo_used_weight_g <= cargo_capacity_weight_g),
            CONSTRAINT ck_trip_segment_resources_cargo_volume
                CHECK (cargo_used_volume_ml >= 0 AND cargo_used_volume_ml <= cargo_capacity_volume_ml)
        )
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
