"""geo hardening (wave 1.5 BR fixes)

Owner: A2 (wave 1.5) - module `geo`.
Planned content (DATA_MODEL.md §5, wave 1.5 BR review):
  * feature_flag_values: DB guard requiring a non-empty approval_reference when enabling
    passenger_enabled / card_payments_enabled while platform_environment is 'production'
    (Q5, K7; complements the service check);
  * route_versions: reject source = 'fixture' while platform_environment is 'production'.
Tables: none new (trigger functions on feature_flag_values, route_versions).
FK dependencies: 0031 (platform_environment), 0033, 0035.

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / CREATE OR REPLACE /
inspector checks, re-runnable backfills); do not change revision ids or the chain.
downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260914_0043
Revises: 20260914_0042
Create Date: 2026-09-14 00:43:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260914_0043"
down_revision: str = "20260914_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL only. Idempotent: CREATE OR REPLACE / IF NOT EXISTS / catalogue checks.
    if op.get_bind().dialect.name != "postgresql":
        return

    # Fail closed (aligned with 0042): a missing table, missing row or unknown value counts as
    # production. Only explicit non-production markers relax the guards.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_production_guard_active() RETURNS boolean
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            marker TEXT;
        BEGIN
            IF to_regclass('platform_environment') IS NULL THEN
                RETURN true;
            END IF;
            SELECT environment INTO marker FROM platform_environment WHERE id = 1;
            RETURN marker IS NULL OR marker NOT IN ('staging', 'development', 'test');
        END
        $$
        """
    )

    # Q5/K7 at DB level: under the production marker passenger/card flags cannot be enabled without an
    # approval reference. (Q1 wallet_required is A3's trigger; not duplicated here.)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_feature_flag_values_production_rules() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT geo_production_guard_active() THEN
                RETURN NEW;
            END IF;
            IF NEW.enabled AND NEW.flag_key IN ('passenger_enabled', 'card_payments_enabled')
               AND (NEW.approval_reference IS NULL OR btrim(NEW.approval_reference) = '') THEN
                RAISE EXCEPTION 'feature_flag_values: enabling % in production requires approval_reference', NEW.flag_key
                    USING ERRCODE = 'check_violation';
            END IF;
            -- wallet_required=false (Q1) is enforced by A3's feature_flag_wallet_required_guard (0041/0042).
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_feature_flag_values_production_rules "
        "BEFORE INSERT OR UPDATE ON feature_flag_values "
        "FOR EACH ROW EXECUTE FUNCTION geo_feature_flag_values_production_rules()"
    )

    # Synthetic fixture routes never enter a production database.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_route_versions_production_source() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.source = 'fixture' AND geo_production_guard_active() THEN
                RAISE EXCEPTION 'route_versions: source fixture is forbidden in production'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_route_versions_production_source "
        "BEFORE INSERT ON route_versions "
        "FOR EACH ROW EXECUTE FUNCTION geo_route_versions_production_source()"
    )

    # Decision 27: meeting-point evidence (note or photo) is required for every active stop before
    # a corridor goes to pilot. Opaque file reference (H0 file module); no FK.
    op.execute("ALTER TABLE corridor_stops ADD COLUMN IF NOT EXISTS meeting_photo_file_id TEXT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_corridor_stops_meeting_photo_file_id'
            ) THEN
                ALTER TABLE corridor_stops ADD CONSTRAINT ck_corridor_stops_meeting_photo_file_id
                    CHECK (meeting_photo_file_id IS NULL OR length(btrim(meeting_photo_file_id)) BETWEEN 1 AND 128);
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    pass
