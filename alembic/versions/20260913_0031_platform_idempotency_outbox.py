"""platform: idempotency records, outbox events, consumer receipts, environment marker

Owner: A3 (wave 1) - module `platform`.
Content (DATA_MODEL.md §1.1, §5): idempotency_records (UNIQUE actor_user_id+route+idem_key),
outbox_events (UNIQUE event_id, partial index on undispatched), consumer_receipts
(UNIQUE consumer+event_id).
Addition (BR N1, reported to A0a for DATA_MODEL): platform_environment - singleton DB-level
environment marker seeded from ELCHI_ENVIRONMENT; a trigger forbids leaving `production`,
deleting the row, and entering `production` while any test_overdraft_allowed wallet exists.
Tables: idempotency_records, outbox_events, consumer_receipts, platform_environment.
FK dependencies: users (legacy).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT); do not change revision
ids or the chain. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0031
Revises: 20260913_0030
Create Date: 2026-09-13 00:31:00.000000
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260913_0031"
down_revision: str = "20260913_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENVIRONMENTS = ("production", "staging", "development", "test")
# Allowlist (wave 1.5 BR #3): only these ELCHI_ENVIRONMENT spellings are accepted. Anything else
# (e.g. "prod", "live", empty) stops the migration instead of silently seeding "development".
_ENVIRONMENT_ALIASES = {
    "local": "development",
    "development": "development",
    "test": "test",
    "staging": "staging",
    "production": "production",
}


def _marker_from_settings() -> str:
    value = os.environ.get("ELCHI_ENVIRONMENT")
    if value is None:
        try:
            from app.core.config import settings

            value = settings.environment
        except Exception:  # noqa: BLE001 - migrations must not depend on app import success
            value = None
    key = (value or "").strip().lower()
    if key not in _ENVIRONMENT_ALIASES:
        raise RuntimeError(
            f"ELCHI_ENVIRONMENT={value!r} is not allowed; use one of {sorted(_ENVIRONMENT_ALIASES)}"
        )
    return _ENVIRONMENT_ALIASES[key]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_records (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            actor_user_id INTEGER NOT NULL REFERENCES users (id),
            route VARCHAR(255) NOT NULL,
            idem_key VARCHAR(128) NOT NULL,
            request_hash CHAR(64) NOT NULL,
            state VARCHAR(16) NOT NULL,
            response_status SMALLINT,
            response_body JSONB,
            resource_type VARCHAR(64),
            resource_id VARCHAR(64),
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_idempotency_records_actor_route_key UNIQUE (actor_user_id, route, idem_key),
            CONSTRAINT ck_idempotency_records_state CHECK (state IN ('processing', 'completed')),
            CONSTRAINT ck_idempotency_records_completed_has_response
                CHECK (state <> 'completed' OR response_status IS NOT NULL),
            CONSTRAINT ck_idempotency_records_status_range
                CHECK (response_status IS NULL OR response_status BETWEEN 200 AND 499)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_idempotency_records_expires_at ON idempotency_records (expires_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id UUID NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            aggregate_type VARCHAR(64) NOT NULL,
            aggregate_id BIGINT,
            aggregate_public_id VARCHAR(64) NOT NULL,
            aggregate_version INTEGER NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            dedup_key VARCHAR(255),
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            dispatched_at TIMESTAMPTZ,
            dead_lettered_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_outbox_events_event_id UNIQUE (event_id),
            CONSTRAINT ck_outbox_events_aggregate_version CHECK (aggregate_version >= 1),
            CONSTRAINT ck_outbox_events_attempts CHECK (attempts >= 0),
            CONSTRAINT ck_outbox_events_payload_object CHECK (jsonb_typeof(payload) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_outbox_events_pending ON outbox_events (next_attempt_at) "
        "WHERE dispatched_at IS NULL AND dead_lettered_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_outbox_events_aggregate ON outbox_events (aggregate_type, aggregate_public_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS consumer_receipts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            consumer VARCHAR(64) NOT NULL,
            event_id UUID NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_consumer_receipts_consumer_event UNIQUE (consumer, event_id)
        )
        """
    )

    # --- BR N1: DB-level environment marker ------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_environment (
            id SMALLINT PRIMARY KEY,
            environment VARCHAR(16) NOT NULL,
            set_by VARCHAR(128) NOT NULL,
            note TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_platform_environment_singleton CHECK (id = 1),
            CONSTRAINT ck_platform_environment_value
                CHECK (environment IN ('production', 'staging', 'development', 'test'))
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_environment_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            overdraft_count BIGINT := 0;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'platform_environment marker cannot be deleted'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.environment = 'production' AND NEW.environment <> 'production' THEN
                RAISE EXCEPTION 'platform_environment: production marker cannot be downgraded to %', NEW.environment
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.environment = 'production' AND to_regclass('public.wallet_accounts') IS NOT NULL THEN
                EXECUTE 'SELECT count(*) FROM wallet_accounts WHERE test_overdraft_allowed' INTO overdraft_count;
                IF overdraft_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: % wallet(s) have test_overdraft_allowed; cannot mark production',
                        overdraft_count USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            -- A2's flag table (0033): wallet_required may not be false in production (Q1).
            IF NEW.environment = 'production' AND to_regclass('public.feature_flag_values') IS NOT NULL
               AND (SELECT count(*) FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'feature_flag_values'
                      AND column_name IN ('flag_key', 'enabled')) = 2 THEN
                EXECUTE 'SELECT count(*) FROM feature_flag_values WHERE flag_key = ''wallet_required'' AND NOT enabled'
                    INTO overdraft_count;
                IF overdraft_count > 0 THEN
                    RAISE EXCEPTION 'platform_environment: wallet_required=false flag rows exist; cannot mark production'
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_platform_environment_guard ON platform_environment")
    op.execute(
        "CREATE TRIGGER trg_platform_environment_guard BEFORE INSERT OR UPDATE OR DELETE ON platform_environment "
        "FOR EACH ROW EXECUTE FUNCTION platform_environment_guard()"
    )
    marker = _marker_from_settings()
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO platform_environment (id, environment, set_by, note) "
            "VALUES (1, :env, 'migration:20260913_0031', 'seeded from ELCHI_ENVIRONMENT') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"env": marker},
    )
    if marker == "production":
        # Upgrade only; never downgraded automatically (the trigger forbids it anyway).
        bind.execute(
            sa.text(
                "UPDATE platform_environment SET environment = 'production', "
                "set_by = 'migration:20260913_0031', updated_at = now() "
                "WHERE id = 1 AND environment <> 'production'"
            )
        )


def downgrade() -> None:
    # Not a rollback strategy (spec §18.3); idempotency/outbox history is kept.
    pass
