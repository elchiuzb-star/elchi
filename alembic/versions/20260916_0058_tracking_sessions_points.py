"""tracking sessions points

Owner: A6 (wave 3) - module `tracking`.
Content (DATA_MODEL.md §1.8 and §5, WAVE1_CARDS "Wave 3", spec §10.3-§10.7, AC27-AC31, AC44, Q44, Q71):
  * tracking_sessions (public_id trs_, trip_id FK trips, driver_user_id FK users, device_id, platform
    (enums.ClientPlatform), app_version, status (enums.TrackingSessionStatus; CHECK), last_seq, started_at, ended_at,
    last trusted point columns: last_captured_at, last_received_at, last_point geometry(Point,4326), last_accuracy_m;
    candidate_captured_at / candidate_point = newest in-order non-mock point, used only by the speed plausibility rule)
    + partial unique (trip_id) WHERE status = 'active' (AC29)
  * tracking_points PARTITION BY RANGE (captured_date), PK (captured_date, session_id, seq); integer units
    (accuracy_m, speed_mps, heading_deg, battery_pct), is_mock, quality_flags (enums.TrackingQualityFlag).
    A DEFAULT partition catches days without a partition, so ingestion never runs DDL. Daily partitions are created
    and expired only by SECURITY DEFINER functions owned by the migration/owner role (Q36/Q71: the app role owns no
    objects); EXECUTE is revoked from PUBLIC (scripts/db_roles.py grants EXECUTE on functions to the app role):
      - tracking_ensure_point_partition(day)  (day clamped to [today-2, today+14]; moves DEFAULT rows of that day)
      - tracking_ensure_point_partitions()    (today-1 .. today+3)
      - tracking_drop_expired_point_partitions() (raw retention 7 days = contracts.tracking.RAW_POINT_RETENTION)
  * tracking_point_receipts PK (session_id, seq) - duplicate retry is a no-op (AC28); append-only (UPDATE refused)
  * tracking_track_simplified (UNIQUE trip_id), tracking_grants (token_hash CHAR(64) UNIQUE - crypto.secret_token_hash,
    ADR-0018; only revoked_at may change, once)
  * guard triggers with CONSTRAINT names from app.contracts.db_errors.CONSTRAINT_RULES:
    tracking_session_superseded, tracking_session_closed, append_only_violation
FK / object dependencies: 0038 (trips), 0048 (bookings), 0032 (users.public_id), 0030 (postgis).
No FK to other wave 3 modules (communications 0059, trust_support 0060, saved searches 0061).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0058
Revises: 20260915_0057
Create Date: 2026-09-16 00:58:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0058"
down_revision: str = "20260915_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
# app.contracts.tracking.RAW_POINT_RETENTION (7 days); tests/modules/tracking checks they match.
RAW_POINT_RETENTION_DAYS = 7
# Partition creation window accepted by tracking_ensure_point_partition (a SECURITY DEFINER function must not accept
# arbitrary input): MAX_POINT_AGE is 24 h, so older days never receive new points.
PARTITION_MIN_DAYS_BACK = 2
PARTITION_MAX_DAYS_AHEAD = 14
QUALITY_FLAGS_SQL = "ARRAY['low_accuracy', 'mock_location', 'implausible_speed', 'out_of_order']::TEXT[]"
SECURITY_DEFINER_FUNCTIONS = (
    "public.tracking_ensure_point_partition(DATE)",
    "public.tracking_ensure_point_partitions()",
    "public.tracking_drop_expired_point_partitions()",
)


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE TRIGGER {name} {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- tables -------------------------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.tracking_sessions (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            trip_id BIGINT NOT NULL,
            driver_user_id INTEGER NOT NULL,
            device_id VARCHAR(128) NOT NULL,
            platform VARCHAR(16) NOT NULL,
            app_version VARCHAR(64) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            last_seq BIGINT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at TIMESTAMPTZ,
            last_captured_at TIMESTAMPTZ,
            last_received_at TIMESTAMPTZ,
            last_point geometry(Point, 4326),
            last_accuracy_m INTEGER,
            candidate_captured_at TIMESTAMPTZ,
            candidate_point geometry(Point, 4326),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_tracking_sessions_public_id UNIQUE (public_id),
            CONSTRAINT fk_tracking_sessions_trip_id FOREIGN KEY (trip_id) REFERENCES public.trips (id),
            CONSTRAINT fk_tracking_sessions_driver_user_id FOREIGN KEY (driver_user_id) REFERENCES public.users (id),
            CONSTRAINT ck_tracking_sessions_status CHECK (status IN ('active', 'superseded', 'closed')),
            CONSTRAINT ck_tracking_sessions_platform CHECK (platform IN ('android', 'ios', 'web')),
            CONSTRAINT ck_tracking_sessions_ended_at CHECK ((status = 'active') = (ended_at IS NULL)),
            CONSTRAINT ck_tracking_sessions_last_seq CHECK (last_seq IS NULL OR last_seq >= 0),
            CONSTRAINT ck_tracking_sessions_last_accuracy CHECK (last_accuracy_m IS NULL OR last_accuracy_m BETWEEN 0 AND 10000),
            CONSTRAINT ck_tracking_sessions_live_point CHECK (
                (last_captured_at IS NULL) = (last_point IS NULL)
                AND (last_point IS NULL) = (last_accuracy_m IS NULL)
                AND (last_point IS NULL) = (last_received_at IS NULL)
            ),
            CONSTRAINT ck_tracking_sessions_candidate_point CHECK ((candidate_captured_at IS NULL) = (candidate_point IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tracking_sessions_trip_active ON public.tracking_sessions (trip_id) "
        "WHERE status = 'active'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tracking_sessions_trip_started ON public.tracking_sessions (trip_id, started_at, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tracking_sessions_driver_started ON public.tracking_sessions (driver_user_id, started_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_sessions_active_last_captured ON public.tracking_sessions (last_captured_at) "
        "WHERE status = 'active'"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.tracking_points (
            captured_date DATE NOT NULL,
            session_id BIGINT NOT NULL,
            seq BIGINT NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            point geometry(Point, 4326) NOT NULL,
            accuracy_m INTEGER NOT NULL,
            speed_mps INTEGER,
            heading_deg SMALLINT,
            battery_pct SMALLINT,
            is_mock BOOLEAN NOT NULL DEFAULT false,
            quality_flags TEXT[] NOT NULL DEFAULT '{{}}',
            CONSTRAINT pk_tracking_points PRIMARY KEY (captured_date, session_id, seq),
            CONSTRAINT fk_tracking_points_session_id FOREIGN KEY (session_id) REFERENCES public.tracking_sessions (id),
            CONSTRAINT ck_tracking_points_captured_date CHECK (captured_date = (captured_at AT TIME ZONE 'UTC')::date),
            CONSTRAINT ck_tracking_points_seq CHECK (seq >= 0),
            CONSTRAINT ck_tracking_points_accuracy CHECK (accuracy_m BETWEEN 0 AND 10000),
            CONSTRAINT ck_tracking_points_speed CHECK (speed_mps IS NULL OR speed_mps BETWEEN 0 AND 100),
            CONSTRAINT ck_tracking_points_heading CHECK (heading_deg IS NULL OR heading_deg BETWEEN 0 AND 359),
            CONSTRAINT ck_tracking_points_battery CHECK (battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100),
            CONSTRAINT ck_tracking_points_quality_flags CHECK (quality_flags <@ {QUALITY_FLAGS_SQL})
        ) PARTITION BY RANGE (captured_date)
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tracking_points_session_captured ON public.tracking_points (session_id, captured_at)")
    op.execute("CREATE TABLE IF NOT EXISTS public.tracking_points_default PARTITION OF public.tracking_points DEFAULT")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.tracking_point_receipts (
            session_id BIGINT NOT NULL,
            seq BIGINT NOT NULL,
            captured_date DATE NOT NULL,
            payload_hash CHAR(64) NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT pk_tracking_point_receipts PRIMARY KEY (session_id, seq),
            CONSTRAINT fk_tracking_point_receipts_session_id FOREIGN KEY (session_id) REFERENCES public.tracking_sessions (id),
            CONSTRAINT ck_tracking_point_receipts_seq CHECK (seq >= 0),
            CONSTRAINT ck_tracking_point_receipts_hash CHECK (payload_hash ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tracking_point_receipts_received_at ON public.tracking_point_receipts (received_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.tracking_track_simplified (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            trip_id BIGINT NOT NULL,
            geometry geometry(LineString, 4326) NOT NULL,
            point_count INTEGER NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_tracking_track_simplified_trip_id UNIQUE (trip_id),
            CONSTRAINT fk_tracking_track_simplified_trip_id FOREIGN KEY (trip_id) REFERENCES public.trips (id),
            CONSTRAINT ck_tracking_track_simplified_point_count CHECK (point_count >= 2)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_track_simplified_generated_at ON public.tracking_track_simplified (generated_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.tracking_grants (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            booking_id BIGINT NOT NULL,
            grantee_user_id INTEGER,
            token_hash CHAR(64),
            scope VARCHAR(32) NOT NULL,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_until TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            created_by_user_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_tracking_grants_public_id UNIQUE (public_id),
            CONSTRAINT uq_tracking_grants_token_hash UNIQUE (token_hash),
            CONSTRAINT fk_tracking_grants_booking_id FOREIGN KEY (booking_id) REFERENCES public.bookings (id),
            CONSTRAINT fk_tracking_grants_grantee_user_id FOREIGN KEY (grantee_user_id) REFERENCES public.users (id),
            CONSTRAINT fk_tracking_grants_created_by_user_id FOREIGN KEY (created_by_user_id) REFERENCES public.users (id),
            CONSTRAINT ck_tracking_grants_scope CHECK (scope IN ('recipient_link')),
            CONSTRAINT ck_tracking_grants_subject CHECK (grantee_user_id IS NOT NULL OR token_hash IS NOT NULL),
            CONSTRAINT ck_tracking_grants_validity CHECK (valid_until > valid_from),
            CONSTRAINT ck_tracking_grants_token_hash CHECK (token_hash IS NULL OR token_hash ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tracking_grants_booking_id ON public.tracking_grants (booking_id)")

    # --- guards ---------------------------------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.tracking_sessions_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'tracking_sessions rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'active' THEN
                    RAISE EXCEPTION 'tracking_sessions: a session starts active'
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'tracking_session_closed';
                END IF;
                IF EXISTS (SELECT 1 FROM public.trips t WHERE t.id = NEW.trip_id AND t.status IN ('completed', 'cancelled')) THEN
                    RAISE EXCEPTION 'tracking_sessions: trip % is finished', NEW.trip_id
                        USING ERRCODE = 'check_violation', CONSTRAINT = 'tracking_session_closed';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.trip_id IS DISTINCT FROM OLD.trip_id
               OR NEW.driver_user_id IS DISTINCT FROM OLD.driver_user_id OR NEW.device_id IS DISTINCT FROM OLD.device_id
               OR NEW.platform IS DISTINCT FROM OLD.platform OR NEW.app_version IS DISTINCT FROM OLD.app_version
               OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'tracking_sessions identity columns are immutable'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            IF OLD.status = 'superseded' AND (NEW.status, NEW.last_seq, NEW.ended_at, NEW.last_captured_at, NEW.candidate_captured_at)
                   IS DISTINCT FROM (OLD.status, OLD.last_seq, OLD.ended_at, OLD.last_captured_at, OLD.candidate_captured_at) THEN
                RAISE EXCEPTION 'tracking_sessions: session % was superseded', OLD.id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'tracking_session_superseded';
            END IF;
            IF OLD.status = 'closed' AND (NEW.status, NEW.last_seq, NEW.ended_at, NEW.last_captured_at, NEW.candidate_captured_at)
                   IS DISTINCT FROM (OLD.status, OLD.last_seq, OLD.ended_at, OLD.last_captured_at, OLD.candidate_captured_at) THEN
                RAISE EXCEPTION 'tracking_sessions: session % is closed', OLD.id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'tracking_session_closed';
            END IF;
            IF OLD.last_captured_at IS NOT NULL AND (NEW.last_captured_at IS NULL OR NEW.last_captured_at < OLD.last_captured_at) THEN
                -- AC28: the live marker never moves back in time
                RAISE EXCEPTION 'tracking_sessions: live point cannot move backwards'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_tracking_sessions_guard",
        "public.tracking_sessions",
        "BEFORE INSERT OR UPDATE OR DELETE ON public.tracking_sessions FOR EACH ROW EXECUTE FUNCTION public.tracking_sessions_guard()",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.tracking_point_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            session_status TEXT;
            trip_status TEXT;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            SELECT s.status, t.status INTO session_status, trip_status
              FROM public.tracking_sessions s JOIN public.trips t ON t.id = s.trip_id
             WHERE s.id = NEW.session_id;
            IF NOT FOUND THEN
                RETURN NEW;  -- the foreign key reports it
            END IF;
            IF session_status = 'superseded' THEN
                RAISE EXCEPTION 'tracking session % was superseded', NEW.session_id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'tracking_session_superseded';
            END IF;
            IF session_status <> 'active' OR trip_status IN ('completed', 'cancelled') THEN
                RAISE EXCEPTION 'tracking session % is closed', NEW.session_id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'tracking_session_closed';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_tracking_points_guard",
        "public.tracking_points",
        "BEFORE INSERT OR UPDATE ON public.tracking_points FOR EACH ROW EXECUTE FUNCTION public.tracking_point_guard()",
    )
    _trigger(
        "trg_tracking_point_receipts_guard",
        "public.tracking_point_receipts",
        "BEFORE INSERT OR UPDATE ON public.tracking_point_receipts FOR EACH ROW EXECUTE FUNCTION public.tracking_point_guard()",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.tracking_grants_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.revoked_at IS NOT NULL
               OR (NEW.id, NEW.public_id, NEW.booking_id, NEW.grantee_user_id, NEW.token_hash, NEW.scope, NEW.valid_from,
                   NEW.valid_until, NEW.created_by_user_id, NEW.created_at)
                  IS DISTINCT FROM
                  (OLD.id, OLD.public_id, OLD.booking_id, OLD.grantee_user_id, OLD.token_hash, OLD.scope, OLD.valid_from,
                   OLD.valid_until, OLD.created_by_user_id, OLD.created_at) THEN
                RAISE EXCEPTION 'tracking_grants: only revoked_at can be set, once'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = 'append_only_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_tracking_grants_guard",
        "public.tracking_grants",
        "BEFORE UPDATE ON public.tracking_grants FOR EACH ROW EXECUTE FUNCTION public.tracking_grants_guard()",
    )

    # --- partitions (SECURITY DEFINER, Q71) -------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.tracking_ensure_point_partition(p_day DATE) RETURNS BOOLEAN
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            today DATE := (now() AT TIME ZONE 'UTC')::date;
            part_name TEXT;
        BEGIN
            IF p_day IS NULL OR p_day < today - {PARTITION_MIN_DAYS_BACK} OR p_day > today + {PARTITION_MAX_DAYS_AHEAD} THEN
                RAISE EXCEPTION 'tracking_ensure_point_partition: % is outside the allowed range', p_day
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            part_name := 'tracking_points_p' || to_char(p_day, 'YYYYMMDD');
            IF to_regclass('public.' || part_name) IS NOT NULL THEN
                RETURN FALSE;
            END IF;
            PERFORM pg_advisory_xact_lock(hashtext('public.tracking_points partitions'));
            IF to_regclass('public.' || part_name) IS NOT NULL THEN
                RETURN FALSE;
            END IF;
            EXECUTE format('CREATE TABLE public.%I (LIKE public.tracking_points INCLUDING DEFAULTS INCLUDING CONSTRAINTS)', part_name);
            -- rows that fell into the DEFAULT partition for this day move into the new partition before ATTACH
            EXECUTE format(
                'WITH moved AS (DELETE FROM public.tracking_points_default WHERE captured_date = $1 RETURNING *) '
                'INSERT INTO public.%I SELECT * FROM moved', part_name
            ) USING p_day;
            EXECUTE format(
                'ALTER TABLE public.tracking_points ATTACH PARTITION public.%I FOR VALUES FROM (%L) TO (%L)',
                part_name, p_day, p_day + 1
            );
            RETURN TRUE;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.tracking_ensure_point_partitions() RETURNS INTEGER
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            today DATE := (now() AT TIME ZONE 'UTC')::date;
            day DATE;
            created INTEGER := 0;
        BEGIN
            FOR day IN SELECT generate_series(today - 1, today + 3, INTERVAL '1 day')::date LOOP
                IF public.tracking_ensure_point_partition(day) THEN
                    created := created + 1;
                END IF;
            END LOOP;
            RETURN created;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.tracking_drop_expired_point_partitions() RETURNS INTEGER
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            cutoff DATE := (now() AT TIME ZONE 'UTC')::date - {RAW_POINT_RETENTION_DAYS};
            part RECORD;
            removed INTEGER := 0;
            deleted INTEGER;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('public.tracking_points partitions'));
            FOR part IN
                SELECT c.relname
                  FROM pg_inherits i
                  JOIN pg_class c ON c.oid = i.inhrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE i.inhparent = 'public.tracking_points'::regclass
                   AND n.nspname = 'public'
                   AND c.relname ~ '^tracking_points_p[0-9]{{8}}$'
                   AND to_date(substr(c.relname, 18, 8), 'YYYYMMDD') < cutoff
                 ORDER BY c.relname
            LOOP
                EXECUTE format('DROP TABLE public.%I', part.relname);
                removed := removed + 1;
            END LOOP;
            DELETE FROM public.tracking_points_default WHERE captured_date < cutoff;
            GET DIAGNOSTICS deleted = ROW_COUNT;
            RETURN removed + deleted;
        END;
        $$
        """
    )
    for signature in SECURITY_DEFINER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute("SELECT public.tracking_ensure_point_partitions()")


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
