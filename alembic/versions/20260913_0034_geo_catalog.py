"""geo: regions, districts, settlements, legacy city mapping, corridors, corridor stops (STUB)

Owner: A2 (wave 1) - module `geo`.
Planned content (DATA_MODEL.md §1.3, §5): regions, geo_districts, settlements,
legacy_city_mappings (catalogue mapping only, not orders), service_corridors,
corridor_config_versions (immutable), corridor_stops (geometry Point 4326, GiST).
Tables: regions, geo_districts, settlements, legacy_city_mappings, service_corridors,
corridor_config_versions, corridor_stops.
FK dependencies: cities, districts (legacy); postgis (0030).
Moved before commission policies (was 0035): commission_policies.scope_corridor_id -> service_corridors.

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0034
Revises: 20260913_0033
Create Date: 2026-09-13 00:34:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0034"
down_revision: str = "20260913_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_POINT_VALID = "ST_IsValid({col}) AND NOT ST_IsEmpty({col}) AND ST_X({col}) BETWEEN -180 AND 180 AND ST_Y({col}) BETWEEN -90 AND 90"


def upgrade() -> None:
    # PostgreSQL + PostGIS (0030) only. Idempotent. No geography seed: production
    # geography is entered and verified by operators (spec §6.2, §21 A2).
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS regions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            code TEXT NOT NULL,
            name_uz TEXT NOT NULL,
            name_ru TEXT NULL,
            boundary geometry(MultiPolygon, 4326) NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_regions_public_id UNIQUE (public_id),
            CONSTRAINT uq_regions_code UNIQUE (code),
            CONSTRAINT ck_regions_code CHECK (code ~ '^[A-Z]{2}-[A-Z0-9]{1,3}$'),
            CONSTRAINT ck_regions_name_uz CHECK (length(btrim(name_uz)) BETWEEN 1 AND 120),
            CONSTRAINT ck_regions_boundary_valid CHECK (boundary IS NULL OR ST_IsValid(boundary))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_regions_boundary_gist ON regions USING gist (boundary)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS geo_districts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            region_id BIGINT NOT NULL,
            name_uz TEXT NOT NULL,
            name_ru TEXT NULL,
            legacy_district_id INTEGER NULL,
            boundary geometry(MultiPolygon, 4326) NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_geo_districts_public_id UNIQUE (public_id),
            CONSTRAINT uq_geo_districts_legacy_district_id UNIQUE (legacy_district_id),
            CONSTRAINT fk_geo_districts_region FOREIGN KEY (region_id) REFERENCES regions (id),
            CONSTRAINT fk_geo_districts_legacy_district FOREIGN KEY (legacy_district_id) REFERENCES districts (id),
            CONSTRAINT ck_geo_districts_name_uz CHECK (length(btrim(name_uz)) BETWEEN 1 AND 120),
            CONSTRAINT ck_geo_districts_boundary_valid CHECK (boundary IS NULL OR ST_IsValid(boundary))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_geo_districts_region_lower_name_uz "
        "ON geo_districts (region_id, lower(name_uz))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_geo_districts_boundary_gist ON geo_districts USING gist (boundary)")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS settlements (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            district_id BIGINT NOT NULL,
            name_uz TEXT NOT NULL,
            name_ru TEXT NULL,
            kind TEXT NOT NULL,
            point geometry(Point, 4326) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_settlements_public_id UNIQUE (public_id),
            CONSTRAINT fk_settlements_district FOREIGN KEY (district_id) REFERENCES geo_districts (id),
            CONSTRAINT ck_settlements_kind CHECK (kind IN ('city', 'town', 'village', 'other')),
            CONSTRAINT ck_settlements_name_uz CHECK (length(btrim(name_uz)) BETWEEN 1 AND 120),
            CONSTRAINT ck_settlements_point_valid CHECK ({_POINT_VALID.format(col="point")})
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_settlements_point_gist ON settlements USING gist (point)")

    # Legacy cities are catalogue input only; `cities.type = 'region'` is NOT assumed to be a city.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_city_mappings (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            legacy_city_id INTEGER NOT NULL,
            region_id BIGINT NULL,
            settlement_id BIGINT NULL,
            mapping_status TEXT NOT NULL DEFAULT 'unverified',
            note TEXT NULL,
            verified_by INTEGER NULL,
            verified_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_legacy_city_mappings_legacy_city_id UNIQUE (legacy_city_id),
            CONSTRAINT fk_legacy_city_mappings_city FOREIGN KEY (legacy_city_id) REFERENCES cities (id),
            CONSTRAINT fk_legacy_city_mappings_region FOREIGN KEY (region_id) REFERENCES regions (id),
            CONSTRAINT fk_legacy_city_mappings_settlement FOREIGN KEY (settlement_id) REFERENCES settlements (id),
            CONSTRAINT fk_legacy_city_mappings_verified_by FOREIGN KEY (verified_by) REFERENCES users (id),
            CONSTRAINT ck_legacy_city_mappings_status CHECK (mapping_status IN ('verified', 'unverified', 'ambiguous')),
            CONSTRAINT ck_legacy_city_mappings_verified CHECK (
                mapping_status <> 'verified'
                OR (verified_by IS NOT NULL AND verified_at IS NOT NULL AND (region_id IS NOT NULL OR settlement_id IS NOT NULL))
            )
        )
        """
    )
    # Re-runnable: one `unverified` row per legacy city, no guessed region.
    op.execute(
        "INSERT INTO legacy_city_mappings (legacy_city_id, mapping_status) "
        "SELECT id, 'unverified' FROM cities ORDER BY id "
        "ON CONFLICT (legacy_city_id) DO NOTHING"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS service_corridors (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            name TEXT NOT NULL,
            origin_region_id BIGINT NOT NULL,
            destination_region_id BIGINT NOT NULL,
            rollout_state TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL,
            updated_by INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_service_corridors_public_id UNIQUE (public_id),
            CONSTRAINT fk_service_corridors_origin_region FOREIGN KEY (origin_region_id) REFERENCES regions (id),
            CONSTRAINT fk_service_corridors_destination_region FOREIGN KEY (destination_region_id) REFERENCES regions (id),
            CONSTRAINT fk_service_corridors_created_by FOREIGN KEY (created_by) REFERENCES users (id),
            CONSTRAINT fk_service_corridors_updated_by FOREIGN KEY (updated_by) REFERENCES users (id),
            CONSTRAINT ck_service_corridors_rollout_state CHECK (rollout_state IN ('draft', 'internal', 'pilot', 'active', 'closed')),
            CONSTRAINT ck_service_corridors_name CHECK (length(btrim(name)) BETWEEN 1 AND 120),
            CONSTRAINT ck_service_corridors_version CHECK (version >= 1)
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_service_corridors_lower_name ON service_corridors (lower(name))")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS corridor_config_versions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            corridor_id BIGINT NOT NULL,
            revision INTEGER NOT NULL,
            search_radius_m INTEGER NOT NULL,
            default_max_detour_minutes INTEGER NOT NULL,
            default_max_detour_m INTEGER NOT NULL,
            ranking_weights JSONB NOT NULL DEFAULT '{}'::jsonb,
            price_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_corridor_config_versions_revision UNIQUE (corridor_id, revision),
            CONSTRAINT fk_corridor_config_versions_corridor FOREIGN KEY (corridor_id) REFERENCES service_corridors (id),
            CONSTRAINT fk_corridor_config_versions_created_by FOREIGN KEY (created_by) REFERENCES users (id),
            CONSTRAINT ck_corridor_config_versions_revision CHECK (revision >= 1),
            CONSTRAINT ck_corridor_config_versions_search_radius CHECK (search_radius_m BETWEEN 100 AND 50000),
            CONSTRAINT ck_corridor_config_versions_detour_minutes CHECK (default_max_detour_minutes BETWEEN 0 AND 240),
            CONSTRAINT ck_corridor_config_versions_detour_m CHECK (default_max_detour_m BETWEEN 0 AND 200000),
            CONSTRAINT ck_corridor_config_versions_json CHECK (
                jsonb_typeof(ranking_weights) = 'object' AND jsonb_typeof(price_reference) = 'object'
            )
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_immutable_row() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_corridor_config_versions_immutable "
        "BEFORE UPDATE OR DELETE ON corridor_config_versions "
        "FOR EACH ROW EXECUTE FUNCTION geo_immutable_row()"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS corridor_stops (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            corridor_id BIGINT NOT NULL,
            geo_district_id BIGINT NOT NULL,
            name_uz TEXT NOT NULL,
            name_ru TEXT NULL,
            point geometry(Point, 4326) NOT NULL,
            meeting_note TEXT NULL,
            sequence_hint INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT false,
            verified_by INTEGER NULL,
            verified_at TIMESTAMPTZ NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_corridor_stops_public_id UNIQUE (public_id),
            CONSTRAINT fk_corridor_stops_corridor FOREIGN KEY (corridor_id) REFERENCES service_corridors (id),
            CONSTRAINT fk_corridor_stops_district FOREIGN KEY (geo_district_id) REFERENCES geo_districts (id),
            CONSTRAINT fk_corridor_stops_verified_by FOREIGN KEY (verified_by) REFERENCES users (id),
            CONSTRAINT ck_corridor_stops_name_uz CHECK (length(btrim(name_uz)) BETWEEN 1 AND 120),
            CONSTRAINT ck_corridor_stops_meeting_note CHECK (meeting_note IS NULL OR length(meeting_note) <= 500),
            CONSTRAINT ck_corridor_stops_point_valid CHECK ({_POINT_VALID.format(col="point")}),
            CONSTRAINT ck_corridor_stops_active_verified CHECK (
                NOT is_active OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)
            ),
            CONSTRAINT ck_corridor_stops_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_corridor_stops_corridor_lower_name_uz "
        "ON corridor_stops (corridor_id, lower(name_uz))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_corridor_stops_point_gist ON corridor_stops USING gist (point)")
    # Metre queries use `point::geography`; this expression index serves them.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_corridor_stops_geography_gist "
        "ON corridor_stops USING gist ((point::geography))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_corridor_stops_district ON corridor_stops (geo_district_id)")


def downgrade() -> None:
    pass
