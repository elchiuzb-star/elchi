"""trips: vehicles

Owner: A1 (wave 1) - module `trips`.
Content (DATA_MODEL.md §1.4, §5): vehicles (UNIQUE plate_normalized, CHECK seat_capacity > 0,
baggage_capacity_ml / cargo_max_weight_g / cargo_max_volume_ml positive, verification_status CHECK).
No automatic backfill from driver_profiles.
Tables: vehicles.
FK dependencies: users (legacy).

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0037
Revises: 20260913_0036
Create Date: 2026-09-13 00:37:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0037"
down_revision: str = "20260913_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vehicles (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            driver_user_id INTEGER NOT NULL CONSTRAINT fk_vehicles_driver_user_id REFERENCES users (id),
            plate_number VARCHAR(32) NOT NULL,
            plate_normalized VARCHAR(32) NOT NULL,
            make_model VARCHAR(120) NOT NULL,
            color VARCHAR(64) NOT NULL,
            seat_capacity SMALLINT NOT NULL,
            baggage_capacity_ml INTEGER NULL,
            cargo_max_weight_g INTEGER NULL,
            cargo_max_volume_ml INTEGER NULL,
            document_file_ids TEXT[] NOT NULL DEFAULT '{}',
            verification_status VARCHAR(16) NOT NULL DEFAULT 'pending',
            verification_reason TEXT NULL,
            verified_by INTEGER NULL CONSTRAINT fk_vehicles_verified_by REFERENCES users (id),
            verified_at TIMESTAMPTZ NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_vehicles_public_id UNIQUE (public_id),
            CONSTRAINT uq_vehicles_plate_normalized UNIQUE (plate_normalized),
            CONSTRAINT ck_vehicles_plate_normalized CHECK (length(plate_normalized) >= 2),
            CONSTRAINT ck_vehicles_seat_capacity CHECK (seat_capacity > 0),
            CONSTRAINT ck_vehicles_baggage_capacity_ml CHECK (baggage_capacity_ml IS NULL OR baggage_capacity_ml > 0),
            CONSTRAINT ck_vehicles_cargo_max_weight_g CHECK (cargo_max_weight_g IS NULL OR cargo_max_weight_g > 0),
            CONSTRAINT ck_vehicles_cargo_max_volume_ml CHECK (cargo_max_volume_ml IS NULL OR cargo_max_volume_ml > 0),
            CONSTRAINT ck_vehicles_verification_status
                CHECK (verification_status IN ('pending', 'approved', 'rejected', 'blocked')),
            CONSTRAINT ck_vehicles_version CHECK (version >= 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_vehicles_driver_user_id ON vehicles (driver_user_id)")


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
