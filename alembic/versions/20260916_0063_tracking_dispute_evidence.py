"""tracking dispute evidence

Owner: A6 / A10a (wave 3.1) - module `tracking`.
Content (BR M1 decision (a): the raw GPS of a disputed trip must survive the 7-day raw retention):
  * tracking_evidence_holds (trip_id FK trips, reason, source_type + source_id = the business row that asked for the
    hold, UNIQUE (trip_id, source_type, source_id), created_at, released_at) - A12 opens a hold when a dispute is
    opened and releases it when the last dispute of that trip closes (tracking.service.hold/release_trip_evidence).
  * tracking_evidence_points - a copy of the raw points (trusted and untrusted) of a held trip, outside the daily
    partitions, so dropping an expired partition never destroys evidence. Append-only (UPDATE refused); the
    retention job deletes them EVIDENCE_RETENTION_AFTER_RELEASE (30 days) after the hold was released.
  * tracking_ensure_point_partition: a new daily partition inherits the ACL of the parent table, so a privilege
    revoked on public.tracking_points (wave 3.1 append-only class in scripts/db_roles.py) cannot be bypassed by
    naming a partition directly.
  * tracking_drop_expired_point_partitions: a partition that still holds points of an active hold that were not
    copied yet is skipped instead of dropped (evidence before disk).
FK / object dependencies: 0058 (tracking_sessions, tracking_points and the three SECURITY DEFINER functions),
0038 (trips), 0030 (postgis). No FK to trust_support: the hold carries source_type/source_id, so tracking keeps no
foreign key into another module's tables (AGENTS §4).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE); do not change the revision id, file name or down_revision;
single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0063
Revises: 20260916_0062
Create Date: 2026-09-16 01:03:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0063"
down_revision: str = "20260916_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_SEARCH_PATH = "pg_catalog, public, pg_temp"
RAW_POINT_RETENTION_DAYS = 7  # app.contracts.tracking.RAW_POINT_RETENTION
PARTITION_MIN_DAYS_BACK = 2
PARTITION_MAX_DAYS_AHEAD = 14
QUALITY_FLAGS_SQL = "ARRAY['low_accuracy', 'mock_location', 'implausible_speed', 'out_of_order']::TEXT[]"
# app.contracts.enums.TrackingEvidenceReason / TrackingEvidenceSource
EVIDENCE_REASONS = ("dispute",)
EVIDENCE_SOURCE_TYPES = ("dispute",)
APPEND_ONLY = "append_only_violation"
PARTITION_PATTERN = "^tracking_points_p[0-9]{8}$"


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE TRIGGER {name} {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.tracking_evidence_holds (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            trip_id BIGINT NOT NULL CONSTRAINT fk_tracking_evidence_holds_trip_id REFERENCES public.trips (id),
            reason VARCHAR(32) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            source_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            released_at TIMESTAMPTZ,
            CONSTRAINT uq_tracking_evidence_holds_source UNIQUE (trip_id, source_type, source_id),
            CONSTRAINT ck_tracking_evidence_holds_reason CHECK (reason IN {_in(EVIDENCE_REASONS)}),
            CONSTRAINT ck_tracking_evidence_holds_source_type CHECK (source_type IN {_in(EVIDENCE_SOURCE_TYPES)}),
            CONSTRAINT ck_tracking_evidence_holds_released CHECK (released_at IS NULL OR released_at >= created_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_evidence_holds_active ON public.tracking_evidence_holds (trip_id) "
        "WHERE released_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_evidence_holds_released ON public.tracking_evidence_holds (released_at) "
        "WHERE released_at IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.tracking_evidence_points (
            session_id BIGINT NOT NULL,
            seq BIGINT NOT NULL,
            trip_id BIGINT NOT NULL,
            captured_date DATE NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            point geometry(Point, 4326) NOT NULL,
            accuracy_m INTEGER NOT NULL,
            speed_mps INTEGER,
            heading_deg SMALLINT,
            battery_pct SMALLINT,
            is_mock BOOLEAN NOT NULL DEFAULT false,
            quality_flags TEXT[] NOT NULL DEFAULT '{{}}',
            copied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_tracking_evidence_points PRIMARY KEY (session_id, seq),
            CONSTRAINT fk_tracking_evidence_points_session_id FOREIGN KEY (session_id)
                REFERENCES public.tracking_sessions (id),
            CONSTRAINT fk_tracking_evidence_points_trip_id FOREIGN KEY (trip_id) REFERENCES public.trips (id),
            CONSTRAINT ck_tracking_evidence_points_captured_date
                CHECK (captured_date = (captured_at AT TIME ZONE 'UTC')::date),
            CONSTRAINT ck_tracking_evidence_points_seq CHECK (seq >= 0),
            CONSTRAINT ck_tracking_evidence_points_accuracy CHECK (accuracy_m BETWEEN 0 AND 10000),
            CONSTRAINT ck_tracking_evidence_points_quality_flags CHECK (quality_flags <@ {QUALITY_FLAGS_SQL})
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tracking_evidence_points_trip "
        "ON public.tracking_evidence_points (trip_id, captured_at)"
    )

    # Evidence is a copy of what was captured: never edited, only purged after the hold is released.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.tracking_evidence_points_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'tracking_evidence_points rows are append-only (%)', TG_OP
                USING ERRCODE = 'restrict_violation', CONSTRAINT = '{APPEND_ONLY}';
        END;
        $$
        """
    )
    _trigger(
        "trg_tracking_evidence_points_guard",
        "public.tracking_evidence_points",
        "BEFORE UPDATE ON public.tracking_evidence_points FOR EACH ROW "
        "EXECUTE FUNCTION public.tracking_evidence_points_guard()",
    )
    _trigger(
        "trg_tracking_evidence_points_no_truncate",
        "public.tracking_evidence_points",
        "BEFORE TRUNCATE ON public.tracking_evidence_points FOR EACH STATEMENT "
        "EXECUTE FUNCTION public.tracking_evidence_points_guard()",
    )

    # --- partition ACL inheritance ---------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.tracking_points_apply_parent_acl(p_partition TEXT) RETURNS VOID
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = {SAFE_SEARCH_PATH} AS $$
        DECLARE
            target REGCLASS := to_regclass('public.' || p_partition);
            grantee TEXT;
            privileges TEXT;
        BEGIN
            IF target IS NULL OR p_partition !~ '{PARTITION_PATTERN}' THEN
                RAISE EXCEPTION 'tracking_points_apply_parent_acl: % is not a tracking_points partition', p_partition
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            -- The parent carries no explicit grants (owner-only, e.g. a single-role dev database): leave the
            -- partition as created, so this never takes INSERT away from a role the parent never granted.
            IF (SELECT relacl IS NULL FROM pg_class WHERE oid = 'public.tracking_points'::regclass) THEN
                RETURN;
            END IF;
            -- start from nothing: a partition created by the owner otherwise keeps the owner's DEFAULT PRIVILEGES
            FOR grantee IN
                SELECT DISTINCT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(a.grantee::regrole::text) END
                  FROM pg_class c, aclexplode(c.relacl) a
                 WHERE c.oid = target AND a.grantee <> c.relowner
            LOOP
                EXECUTE format('REVOKE ALL ON public.%I FROM %s', p_partition, grantee);
            END LOOP;
            FOR grantee, privileges IN
                SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(a.grantee::regrole::text) END,
                       string_agg(DISTINCT a.privilege_type, ', ')
                  FROM pg_class c, aclexplode(c.relacl) a
                 WHERE c.oid = 'public.tracking_points'::regclass AND a.grantee <> c.relowner
                 GROUP BY 1
            LOOP
                EXECUTE format('GRANT %s ON public.%I TO %s', privileges, p_partition, grantee);
            END LOOP;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.tracking_points_apply_parent_acl(TEXT) FROM PUBLIC")

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
            EXECUTE format(
                'CREATE TABLE public.%I (LIKE public.tracking_points INCLUDING DEFAULTS INCLUDING CONSTRAINTS)',
                part_name
            );
            -- rows that fell into the DEFAULT partition for this day move into the new partition before ATTACH
            EXECUTE format(
                'WITH moved AS (DELETE FROM public.tracking_points_default WHERE captured_date = $1 RETURNING *) '
                'INSERT INTO public.%I SELECT * FROM moved', part_name
            ) USING p_day;
            EXECUTE format(
                'ALTER TABLE public.tracking_points ATTACH PARTITION public.%I FOR VALUES FROM (%L) TO (%L)',
                part_name, p_day, p_day + 1
            );
            -- wave 3.1: the partition gets exactly the parent's grants (an append-only parent stays append-only)
            PERFORM public.tracking_points_apply_parent_acl(part_name);
            RETURN TRUE;
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
            pending BOOLEAN;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('public.tracking_points partitions'));
            FOR part IN
                SELECT c.relname
                  FROM pg_inherits i
                  JOIN pg_class c ON c.oid = i.inhrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE i.inhparent = 'public.tracking_points'::regclass
                   AND n.nspname = 'public'
                   AND c.relname ~ '{PARTITION_PATTERN}'
                   AND to_date(substr(c.relname, 18, 8), 'YYYYMMDD') < cutoff
                 ORDER BY c.relname
            LOOP
                -- M1: never drop points of a trip under an active evidence hold before they have been copied
                EXECUTE format(
                    'SELECT EXISTS (SELECT 1 FROM public.%I p'
                    ' JOIN public.tracking_sessions s ON s.id = p.session_id'
                    ' JOIN public.tracking_evidence_holds h ON h.trip_id = s.trip_id AND h.released_at IS NULL'
                    ' WHERE NOT EXISTS (SELECT 1 FROM public.tracking_evidence_points e'
                    ' WHERE e.session_id = p.session_id AND e.seq = p.seq))', part.relname
                ) INTO pending;
                IF pending THEN
                    CONTINUE;
                END IF;
                EXECUTE format('DROP TABLE public.%I', part.relname);
                removed := removed + 1;
            END LOOP;
            DELETE FROM public.tracking_points_default d
             WHERE d.captured_date < cutoff
               AND NOT EXISTS (
                   SELECT 1
                     FROM public.tracking_sessions s
                     JOIN public.tracking_evidence_holds h ON h.trip_id = s.trip_id AND h.released_at IS NULL
                    WHERE s.id = d.session_id
                      AND NOT EXISTS (SELECT 1 FROM public.tracking_evidence_points e
                                       WHERE e.session_id = d.session_id AND e.seq = d.seq)
               );
            GET DIAGNOSTICS deleted = ROW_COUNT;
            RETURN removed + deleted;
        END;
        $$
        """
    )

    # Partitions that already exist were created before this rule (and before db_roles revoked the parent).
    op.execute(
        """
        DO $$
        DECLARE
            part RECORD;
        BEGIN
            FOR part IN
                SELECT c.relname
                  FROM pg_inherits i
                  JOIN pg_class c ON c.oid = i.inhrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE i.inhparent = 'public.tracking_points'::regclass
                   AND n.nspname = 'public'
                   AND c.relname ~ '^tracking_points_p[0-9]{8}$'
            LOOP
                PERFORM public.tracking_points_apply_parent_acl(part.relname);
            END LOOP;
        END
        $$
        """
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016): dropping these tables would destroy dispute evidence."""
