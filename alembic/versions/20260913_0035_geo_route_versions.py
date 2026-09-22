"""geo: route versions, route version stops, routing cache (STUB)

Owner: A2 (wave 1) - module `geo`.
Planned content (DATA_MODEL.md §1.3, §5): route_versions (geometry LineString 4326, GiST,
confirmed rows immutable), route_version_stops (UNIQUE route_version_id+seq),
routing_cache (UNIQUE provider+request_hash).
Tables: route_versions, route_version_stops, routing_cache.
FK dependencies: users (legacy), corridor_stops (0034); postgis (0030).
Moved before commission policies (was 0036); needed by trips (0038).

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0035
Revises: 20260913_0034
Create Date: 2026-09-13 00:35:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0035"
down_revision: str = "20260913_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL + PostGIS (0030) only. Idempotent.
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS route_versions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            corridor_id BIGINT NOT NULL,
            created_by_user_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_version TEXT NOT NULL,
            request_hash CHAR(64) NOT NULL,
            geometry geometry(LineString, 4326) NOT NULL,
            distance_m INTEGER NOT NULL,
            duration_s INTEGER NOT NULL,
            is_estimate BOOLEAN NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            confirmed_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_route_versions_public_id UNIQUE (public_id),
            CONSTRAINT fk_route_versions_corridor FOREIGN KEY (corridor_id) REFERENCES service_corridors (id),
            CONSTRAINT fk_route_versions_created_by FOREIGN KEY (created_by_user_id) REFERENCES users (id),
            CONSTRAINT ck_route_versions_source CHECK (source IN ('routing_provider', 'fixture')),
            CONSTRAINT ck_route_versions_status CHECK (status IN ('draft', 'confirmed')),
            CONSTRAINT ck_route_versions_confirmed_at CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL)),
            CONSTRAINT ck_route_versions_distance CHECK (distance_m > 0),
            CONSTRAINT ck_route_versions_duration CHECK (duration_s > 0),
            CONSTRAINT ck_route_versions_geometry_valid CHECK (ST_IsValid(geometry) AND ST_NPoints(geometry) >= 2)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_route_versions_geometry_gist ON route_versions USING gist (geometry)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_route_versions_geography_gist "
        "ON route_versions USING gist ((geometry::geography))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_route_versions_corridor_status ON route_versions (corridor_id, status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS route_version_stops (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            route_version_id BIGINT NOT NULL,
            seq INTEGER NOT NULL,
            stop_id BIGINT NOT NULL,
            cumulative_distance_m INTEGER NOT NULL,
            cumulative_duration_s INTEGER NOT NULL,
            line_fraction NUMERIC(8, 7) NOT NULL,
            CONSTRAINT uq_route_version_stops_seq UNIQUE (route_version_id, seq),
            CONSTRAINT fk_route_version_stops_route_version FOREIGN KEY (route_version_id)
                REFERENCES route_versions (id) ON DELETE CASCADE,
            CONSTRAINT fk_route_version_stops_stop FOREIGN KEY (stop_id) REFERENCES corridor_stops (id),
            CONSTRAINT ck_route_version_stops_seq CHECK (seq >= 0),
            CONSTRAINT ck_route_version_stops_cumulative CHECK (cumulative_distance_m >= 0 AND cumulative_duration_s >= 0),
            CONSTRAINT ck_route_version_stops_origin CHECK (
                seq <> 0 OR (cumulative_distance_m = 0 AND cumulative_duration_s = 0)
            ),
            CONSTRAINT ck_route_version_stops_line_fraction CHECK (line_fraction BETWEEN 0 AND 1)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_route_version_stops_stop ON route_version_stops (stop_id)")

    # Draft -> confirmed is the only allowed update; confirmed rows are immutable.
    # Confirmation validates the stop list (>= 2 stops, seq 0..n-1, non-decreasing cumulatives).
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
                IF stop_count < 2 OR max_seq <> stop_count - 1 THEN
                    RAISE EXCEPTION 'route_versions needs stops with seq 0..n-1 (n >= 2) before confirmation'
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
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_route_versions_guard "
        "BEFORE UPDATE OR DELETE ON route_versions "
        "FOR EACH ROW EXECUTE FUNCTION geo_route_versions_guard()"
    )

    # Stops of a route version are written once while it is a draft; never updated.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_route_version_stops_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            parent_status TEXT;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'route_version_stops rows are immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            SELECT status INTO parent_status FROM route_versions
            WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.route_version_id ELSE NEW.route_version_id END;
            IF parent_status = 'confirmed' THEN
                RAISE EXCEPTION 'stops of a confirmed route version are immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_route_version_stops_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON route_version_stops "
        "FOR EACH ROW EXECUTE FUNCTION geo_route_version_stops_guard()"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS routing_cache (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            provider TEXT NOT NULL,
            request_hash CHAR(64) NOT NULL,
            response JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_routing_cache_provider_request UNIQUE (provider, request_hash),
            CONSTRAINT ck_routing_cache_expiry CHECK (expires_at > created_at)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_routing_cache_expires_at ON routing_cache (expires_at)")


def downgrade() -> None:
    pass
