"""wallet: versioned commission policies

Owner: A3 (wave 1) - module `wallet` (ADR-0009, decisions Q1/Q2/Q19).
Content (DATA_MODEL.md §1.6, §5): commission_policies - immutable rows; CHECK fee_bps
0..10000; CHECK standard => fee_bps > 0; CHECK campaign => effective_to and campaign_name
NOT NULL; generated scope_key; EXCLUDE USING gist (scope_key =, kind =, tstzrange &&);
trigger: no DELETE, no backdated INSERT, UPDATE only to end once (effective_to in the
future, shortening only); seed global standard policy from
system_settings.driver_commission_rate (exact legacy_rate_to_bps, re-runnable).
Tables: commission_policies.
FK dependencies: service_corridors (0034, added only if that table exists; 0041 retries),
users (legacy); btree_gist (0030).

Rules: idempotent; do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0036
Revises: 20260913_0035
Create Date: 2026-09-13 00:36:00.000000
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from alembic import op


revision: str = "20260913_0036"
down_revision: str = "20260913_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_DEFAULT_RATE = Decimal("0.15")  # app/services/system_settings_service.py default

ADD_CORRIDOR_FK_SQL = """
DO $$
BEGIN
    IF to_regclass('public.service_corridors') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_commission_policies_scope_corridor') THEN
        ALTER TABLE commission_policies
            ADD CONSTRAINT fk_commission_policies_scope_corridor
            FOREIGN KEY (scope_corridor_id) REFERENCES service_corridors (id);
    END IF;
END
$$;
"""


def _legacy_rate_bps(bind) -> tuple[int, str]:
    raw = None
    if bind.execute(sa.text("SELECT to_regclass('public.system_settings') IS NOT NULL")).scalar_one():
        raw = bind.execute(
            sa.text("SELECT value FROM system_settings WHERE key = 'driver_commission_rate'")
        ).scalar_one_or_none()
    return _parse_legacy_rate(raw)


def _parse_legacy_rate(raw) -> tuple[int, str]:
    """Pure rule shared (by test) with ``app.modules.wallet.checks.parse_legacy_rate`` (decision 29)."""
    try:
        rate = LEGACY_DEFAULT_RATE if raw is None else Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise RuntimeError(f"system_settings.driver_commission_rate={raw!r} is not a decimal") from exc
    scaled = rate * 10000
    if scaled != scaled.to_integral_value() or not (0 <= scaled <= 10000):
        raise RuntimeError(f"system_settings.driver_commission_rate={raw!r} is not a whole bps rate")
    bps = int(scaled)
    if bps == 0:
        # Q1: 0% exists only as a time-boxed campaign. Refuse loudly instead of inventing a rate.
        raise RuntimeError(
            "system_settings.driver_commission_rate is 0; a standard policy cannot be 0 bps (Q1). "
            "Set a positive legacy rate before migrating, then create a 0 bps campaign via super_admin."
        )
    source = "default 0.15 (no system_settings row)" if raw is None else f"system_settings.driver_commission_rate={raw}"
    return bps, source


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS commission_policies (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            kind VARCHAR(16) NOT NULL,
            scope_corridor_id BIGINT,
            scope_service_type VARCHAR(16),
            scope_key VARCHAR(64) GENERATED ALWAYS AS
                (COALESCE(CAST(scope_corridor_id AS TEXT), '*') || ':' || COALESCE(scope_service_type, '*')) STORED,
            fee_bps INTEGER NOT NULL,
            effective_from TIMESTAMPTZ NOT NULL,
            effective_to TIMESTAMPTZ,
            campaign_name VARCHAR(128),
            reason TEXT NOT NULL,
            created_by INTEGER REFERENCES users (id),
            ended_by INTEGER REFERENCES users (id),
            ended_reason TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_commission_policies_public_id UNIQUE (public_id),
            CONSTRAINT ck_commission_policies_kind CHECK (kind IN ('standard', 'campaign')),
            CONSTRAINT ck_commission_policies_scope_service_type
                CHECK (scope_service_type IS NULL OR scope_service_type IN ('passenger', 'parcel')),
            CONSTRAINT ck_commission_policies_fee_bps CHECK (fee_bps BETWEEN 0 AND 10000),
            CONSTRAINT ck_commission_policies_standard_positive CHECK (kind <> 'standard' OR fee_bps > 0),
            CONSTRAINT ck_commission_policies_campaign_timeboxed
                CHECK (kind <> 'campaign' OR (effective_to IS NOT NULL AND campaign_name IS NOT NULL)),
            CONSTRAINT ck_commission_policies_period CHECK (effective_to IS NULL OR effective_to > effective_from),
            CONSTRAINT ck_commission_policies_version CHECK (version >= 1),
            CONSTRAINT ck_commission_policies_reason CHECK (length(btrim(reason)) > 0),
            CONSTRAINT ck_commission_policies_end_pair CHECK ((ended_by IS NULL) = (ended_reason IS NULL)),
            CONSTRAINT ex_commission_policies_no_overlap EXCLUDE USING gist (
                scope_key WITH =,
                kind WITH =,
                tstzrange(effective_from, effective_to, '[)') WITH &&
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_commission_policies_active_lookup "
        "ON commission_policies (kind, scope_key, effective_from)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION commission_policies_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'commission_policies are immutable (delete)' USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'INSERT' THEN
                -- Backstop for app/DB clock skew; the service rejects effective_from < now - 60 s.
                IF NEW.effective_from < now() - interval '5 minutes' THEN
                    RAISE EXCEPTION 'commission_policies: retroactive effective_from %', NEW.effective_from
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.id, NEW.public_id, NEW.kind, NEW.scope_corridor_id, NEW.scope_service_type, NEW.fee_bps,
                NEW.effective_from, NEW.campaign_name, NEW.reason, NEW.created_by, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.public_id, OLD.kind, OLD.scope_corridor_id, OLD.scope_service_type, OLD.fee_bps,
                OLD.effective_from, OLD.campaign_name, OLD.reason, OLD.created_by, OLD.created_at) THEN
                RAISE EXCEPTION 'commission_policies are immutable; only a one-time end is allowed'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.ended_by IS NOT NULL THEN
                RAISE EXCEPTION 'commission_policies: policy % already ended', OLD.id USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.ended_by IS NULL OR NEW.effective_to IS NULL THEN
                RAISE EXCEPTION 'commission_policies: ending requires ended_by and effective_to'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.effective_to IS NOT NULL AND OLD.effective_to <= now() THEN
                RAISE EXCEPTION 'commission_policies: policy % already expired', OLD.id USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.effective_to < now() - interval '5 minutes' THEN
                RAISE EXCEPTION 'commission_policies: retroactive effective_to %', NEW.effective_to
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.effective_to IS NOT NULL AND NEW.effective_to > OLD.effective_to THEN
                RAISE EXCEPTION 'commission_policies: effective_to may only be shortened' USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'commission_policies: version must increase by one' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_commission_policies_guard ON commission_policies")
    op.execute(
        "CREATE TRIGGER trg_commission_policies_guard BEFORE INSERT OR UPDATE OR DELETE ON commission_policies "
        "FOR EACH ROW EXECUTE FUNCTION commission_policies_guard()"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_commission_policies_no_truncate ON commission_policies")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION commission_policies_no_truncate() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'commission_policies are immutable (truncate)' USING ERRCODE = 'check_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_commission_policies_no_truncate BEFORE TRUNCATE ON commission_policies "
        "FOR EACH STATEMENT EXECUTE FUNCTION commission_policies_no_truncate()"
    )
    op.execute(ADD_CORRIDOR_FK_SQL)

    # Seed: the global standard policy, exactly from the legacy rate (ADR-0009 §10). Re-runnable.
    has_global_standard = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM commission_policies WHERE kind = 'standard' "
            "AND scope_corridor_id IS NULL AND scope_service_type IS NULL)"
        )
    ).scalar_one()
    if not has_global_standard:
        bps, source = _legacy_rate_bps(bind)
        bind.execute(
            sa.text(
                "INSERT INTO commission_policies (public_id, kind, fee_bps, effective_from, reason) "
                "VALUES (:public_id, 'standard', :bps, now(), :reason)"
            ),
            {
                "public_id": uuid.uuid4(),
                "bps": bps,
                "reason": f"seed global standard from {source} (migration 20260913_0036)",
            },
        )


def downgrade() -> None:
    # Not a rollback strategy (spec §18.3); policy history is kept.
    pass
