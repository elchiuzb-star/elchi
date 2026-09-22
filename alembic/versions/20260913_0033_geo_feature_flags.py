"""geo: feature flag values and append-only change history (STUB)

Owner: A2 (wave 1) - module `geo` (feature flag core, ADR-0008).
Planned content (DATA_MODEL.md §1.3, §5): feature_flag_values (UNIQUE flag_key+scope_type+scope_ref,
CHECK flag_key/scope_type IN ...), feature_flag_changes (append-only, immutable trigger).
Tables: feature_flag_values, feature_flag_changes.
FK dependencies: users (legacy). scope_ref is text (no FK to corridors).

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0033
Revises: 20260913_0032
Create Date: 2026-09-13 00:33:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0033"
down_revision: str = "20260913_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Values mirror app.contracts.enums.FeatureFlagKey / FlagScopeType (contract: never rename).
_FLAG_KEYS = (
    "passenger_enabled",
    "parcel_enabled",
    "driver_listing_enabled",
    "corridor_matching_enabled",
    "wallet_required",
    "tracking_enabled",
    "card_payments_enabled",
)
_SCOPE_TYPES = ("cohort", "corridor", "region", "country")


def _sql_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    # PostgreSQL-only (plpgsql triggers). Idempotent: IF NOT EXISTS / OR REPLACE.
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS feature_flag_values (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            flag_key TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_ref TEXT NOT NULL,
            enabled BOOLEAN NOT NULL,
            approval_reference TEXT NULL,
            reason TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_feature_flag_values_public_id UNIQUE (public_id),
            CONSTRAINT uq_feature_flag_values_key_scope UNIQUE (flag_key, scope_type, scope_ref),
            CONSTRAINT fk_feature_flag_values_updated_by FOREIGN KEY (updated_by) REFERENCES users (id),
            CONSTRAINT ck_feature_flag_values_flag_key CHECK (flag_key IN ({_sql_list(_FLAG_KEYS)})),
            CONSTRAINT ck_feature_flag_values_scope_type CHECK (scope_type IN ({_sql_list(_SCOPE_TYPES)})),
            CONSTRAINT ck_feature_flag_values_scope_ref CHECK (
                length(scope_ref) BETWEEN 1 AND 64 AND scope_ref = btrim(scope_ref)
                AND (scope_type <> 'country' OR scope_ref = 'UZ')
            ),
            CONSTRAINT ck_feature_flag_values_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
            CONSTRAINT ck_feature_flag_values_approval_reference CHECK (
                approval_reference IS NULL OR length(btrim(approval_reference)) BETWEEN 1 AND 200
            ),
            CONSTRAINT ck_feature_flag_values_version CHECK (version >= 1)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feature_flag_changes (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            flag_value_id BIGINT NOT NULL,
            flag_key TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_ref TEXT NOT NULL,
            value_version INTEGER NOT NULL,
            old_enabled BOOLEAN NULL,
            new_enabled BOOLEAN NOT NULL,
            actor_user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            approval_reference TEXT NULL,
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_feature_flag_changes_value_version UNIQUE (flag_value_id, value_version),
            CONSTRAINT fk_feature_flag_changes_flag_value FOREIGN KEY (flag_value_id) REFERENCES feature_flag_values (id),
            CONSTRAINT fk_feature_flag_changes_actor FOREIGN KEY (actor_user_id) REFERENCES users (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_feature_flag_changes_key_changed "
        "ON feature_flag_changes (flag_key, changed_at, id)"
    )

    # Values: identity columns immutable, version +1 per update, updated_at from the DB clock,
    # rows are never deleted (disable instead) so history stays attached.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_feature_flag_values_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'feature_flag_values rows cannot be deleted; disable the flag instead'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.public_id IS DISTINCT FROM OLD.public_id
               OR NEW.flag_key IS DISTINCT FROM OLD.flag_key OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
               OR NEW.scope_ref IS DISTINCT FROM OLD.scope_ref OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'feature_flag_values identity columns are immutable'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF NEW.version IS DISTINCT FROM OLD.version + 1 THEN
                RAISE EXCEPTION 'feature_flag_values.version must increase by exactly 1'
                    USING ERRCODE = 'check_violation';
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_feature_flag_values_guard "
        "BEFORE UPDATE OR DELETE ON feature_flag_values "
        "FOR EACH ROW EXECUTE FUNCTION geo_feature_flag_values_guard()"
    )

    # Every insert/update of a value appends exactly one history row, whoever wrote it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_feature_flag_values_record_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO feature_flag_changes (
                flag_value_id, flag_key, scope_type, scope_ref, value_version,
                old_enabled, new_enabled, actor_user_id, reason, approval_reference, changed_at
            ) VALUES (
                NEW.id, NEW.flag_key, NEW.scope_type, NEW.scope_ref, NEW.version,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.enabled END, NEW.enabled, NEW.updated_by,
                NEW.reason, NEW.approval_reference, now()
            );
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_feature_flag_values_record_change "
        "AFTER INSERT OR UPDATE ON feature_flag_values "
        "FOR EACH ROW EXECUTE FUNCTION geo_feature_flag_values_record_change()"
    )

    # History is append-only.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_feature_flag_changes_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'feature_flag_changes is append-only' USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_feature_flag_changes_append_only "
        "BEFORE UPDATE OR DELETE ON feature_flag_changes "
        "FOR EACH ROW EXECUTE FUNCTION geo_feature_flag_changes_append_only()"
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_feature_flag_changes_no_truncate "
        "BEFORE TRUNCATE ON feature_flag_changes "
        "FOR EACH STATEMENT EXECUTE FUNCTION geo_feature_flag_changes_append_only()"
    )


def downgrade() -> None:
    pass
