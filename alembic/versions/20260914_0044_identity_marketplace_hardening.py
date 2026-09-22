"""identity + marketplace hardening (wave 1.5 BR fixes)

Owner: A1 (wave 1.5) - modules `identity`, `marketplace`.
Content (DATA_MODEL.md §5, wave 1.5 BR review):
  * proposal_versions: demand snapshot columns baggage_ml, cargo_weight_g, cargo_volume_ml and
    parcel dimensions parcel_length_cm / parcel_width_cm / parcel_height_cm (AC12; A4 reserves from them);
  * proposal_versions: once a status is final, status / status_reason / closed_at are frozen (BR #11);
  * driver_eligibility_blocks: lift_reason only together with lifting; CHECK lifted_at IS NULL OR
    lift_reason IS NOT NULL (BR #12);
  * user_roles Q3 trigger: lock the users row FOR NO KEY UPDATE instead of FOR UPDATE, so it does not
    conflict with the FOR KEY SHARE locks taken by foreign-key inserts (wave 1.5 deadlock fix);
  * users: BEFORE UPDATE OF role trigger enforcing Q3 on the legacy column (BR #13). Staff<->staff and
    client<->driver switches stay allowed.
Tables: none new.
FK dependencies: 0032, 0040.

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / CREATE OR REPLACE /
inspector checks, re-runnable backfills); do not change revision ids or the chain.
downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260914_0044
Revises: 20260914_0043
Create Date: 2026-09-14 00:44:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260914_0044"
down_revision: str = "20260914_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAFF_ROLES_SQL = "('operator', 'admin', 'super_admin', 'finance')"
MARKETPLACE_ROLES_SQL = "('client', 'driver')"


def _add_constraint_if_missing(table: str, name: str, definition: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}' AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # --- proposal_versions: demand snapshot (AC12) --------------------------------------
    op.execute(
        """
        ALTER TABLE proposal_versions
            ADD COLUMN IF NOT EXISTS baggage_ml INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS cargo_weight_g INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS cargo_volume_ml INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS parcel_length_cm INTEGER NULL,
            ADD COLUMN IF NOT EXISTS parcel_width_cm INTEGER NULL,
            ADD COLUMN IF NOT EXISTS parcel_height_cm INTEGER NULL
        """
    )
    _add_constraint_if_missing(
        "proposal_versions",
        "ck_proposal_versions_demand",
        "CHECK (baggage_ml >= 0 AND cargo_weight_g >= 0 AND cargo_volume_ml >= 0"
        " AND (parcel_length_cm IS NULL OR parcel_length_cm > 0)"
        " AND (parcel_width_cm IS NULL OR parcel_width_cm > 0)"
        " AND (parcel_height_cm IS NULL OR parcel_height_cm > 0))",
    )

    # --- proposal_versions: final status is frozen (BR #11) -----------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION marketplace_proposal_versions_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'proposal versions are immutable and cannot be deleted'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status', 'status_reason', 'closed_at'])
               IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'status_reason', 'closed_at']) THEN
                RAISE EXCEPTION 'proposal version content is immutable'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.status <> 'active' AND (
                NEW.status IS DISTINCT FROM OLD.status
                OR NEW.status_reason IS DISTINCT FROM OLD.status_reason
                OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
            ) THEN
                RAISE EXCEPTION 'proposal version status % is final (immutable)', OLD.status
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )

    # --- driver_eligibility_blocks: lift_reason only with lifting (BR #12) ---------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION identity_eligibility_blocks_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'driver eligibility blocks are immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.lifted_at IS NOT NULL
               OR NEW.id <> OLD.id
               OR NEW.driver_user_id <> OLD.driver_user_id
               OR NEW.reason <> OLD.reason
               OR NEW.blocked_by <> OLD.blocked_by
               OR NEW.blocked_at <> OLD.blocked_at
               OR (NEW.lift_reason IS DISTINCT FROM OLD.lift_reason AND NEW.lifted_at IS NULL) THEN
                RAISE EXCEPTION 'driver eligibility blocks are immutable except for lifting once'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    _add_constraint_if_missing(
        "driver_eligibility_blocks",
        "ck_driver_eligibility_blocks_lift_reason",
        "CHECK (lifted_at IS NULL OR lift_reason IS NOT NULL) NOT VALID",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM driver_eligibility_blocks WHERE lifted_at IS NOT NULL AND lift_reason IS NULL
            ) THEN
                ALTER TABLE driver_eligibility_blocks VALIDATE CONSTRAINT ck_driver_eligibility_blocks_lift_reason;
            END IF;
        END $$;
        """
    )

    # --- Q3 on user_roles: FOR NO KEY UPDATE (deadlock fix) ------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION identity_user_roles_q3_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            primary_role TEXT;
            has_staff BOOLEAN;
            has_marketplace BOOLEAN;
        BEGIN
            IF NEW.status <> 'active' THEN
                RETURN NEW;
            END IF;
            -- users is first in the global lock order (ADR-0017). NO KEY UPDATE still serialises
            -- role writes but does not block FOR KEY SHARE taken by foreign-key inserts.
            SELECT u.role INTO primary_role FROM users u WHERE u.id = NEW.user_id FOR NO KEY UPDATE;
            SELECT bool_or(r IN {STAFF_ROLES_SQL}), bool_or(r IN {MARKETPLACE_ROLES_SQL})
            INTO has_staff, has_marketplace
            FROM (
                SELECT ur.role AS r FROM user_roles ur
                WHERE ur.user_id = NEW.user_id AND ur.status = 'active' AND ur.id <> NEW.id
                UNION ALL SELECT NEW.role
                UNION ALL SELECT primary_role
            ) AS roles;
            IF has_staff AND has_marketplace THEN
                RAISE EXCEPTION 'staff and marketplace roles cannot be combined on user %', NEW.user_id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_user_roles_staff_marketplace_separation';
            END IF;
            RETURN NEW;
        END $$
        """
    )

    # --- Q3 on the legacy users.role column (BR #13) -------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION identity_users_role_q3_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            has_staff BOOLEAN;
            has_marketplace BOOLEAN;
        BEGIN
            IF NEW.role IS NOT DISTINCT FROM OLD.role THEN
                RETURN NEW;
            END IF;
            SELECT bool_or(r IN {STAFF_ROLES_SQL}), bool_or(r IN {MARKETPLACE_ROLES_SQL})
            INTO has_staff, has_marketplace
            FROM (
                SELECT ur.role AS r FROM user_roles ur WHERE ur.user_id = NEW.id AND ur.status = 'active'
                UNION ALL SELECT OLD.role
                UNION ALL SELECT NEW.role
            ) AS roles;
            IF has_staff AND has_marketplace THEN
                RAISE EXCEPTION 'staff and marketplace roles cannot be combined on user %', NEW.id
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_users_role_staff_marketplace_separation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE TRIGGER trg_users_role_q3_guard
        BEFORE UPDATE OF role ON users
        FOR EACH ROW EXECUTE FUNCTION identity_users_role_q3_guard()
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
