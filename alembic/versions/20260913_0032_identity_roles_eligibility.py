"""identity: users.public_id, user_roles, driver eligibility blocks, document validity

Owner: A1 (wave 1) - module `identity`.
Content (DATA_MODEL.md §1.2, §5): users.public_id (backfill, then NOT NULL + UNIQUE);
user_roles (UNIQUE user_id+role, backfill from users.role, trigger forbidding staff +
marketplace roles on one user - decision Q3); driver_eligibility_blocks (partial unique
active block per driver - D16); driver_document_validity (valid_until per driver_documents row).
Tables: user_roles, driver_eligibility_blocks, driver_document_validity (+ column users.public_id).
FK dependencies: users, driver_documents (legacy).

Notes:
* users.public_id gets DB default gen_random_uuid() so legacy v1 inserts (which do not
  know the column) keep working; users.role and v1 auth are unchanged.
* The Q3 trigger also counts users.role (the legacy primary role) and locks the users
  row, so two concurrent role activations serialise instead of both passing the check.
* driver_document_validity cascades with driver_documents: v1 account deletion
  hard-deletes documents (app/services/account_deletion_service.py).

Rules: owner fills upgrade(); must stay idempotent (IF NOT EXISTS / inspector checks,
re-runnable backfills); do not change revision ids or the chain. downgrade() is not a
rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260913_0032
Revises: 20260913_0031
Create Date: 2026-09-13 00:32:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0032"
down_revision: str = "20260913_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of app.contracts.enums.Role at the time of this migration (incl. Q17 finance).
ALL_ROLES_SQL = "('client', 'driver', 'operator', 'admin', 'super_admin', 'finance')"
STAFF_ROLES_SQL = "('operator', 'admin', 'super_admin', 'finance')"
MARKETPLACE_ROLES_SQL = "('client', 'driver')"

# Re-runnable: legacy primary role -> user_roles row; never duplicates, never revives a revoked row.
BACKFILL_USER_ROLES_SQL = f"""
INSERT INTO user_roles (user_id, role, status)
SELECT u.id, u.role, 'active'
FROM users u
WHERE u.role IN {ALL_ROLES_SQL}
ORDER BY u.id
ON CONFLICT (user_id, role) DO NOTHING
"""


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

    # --- users.public_id (ADR-0002) -------------------------------------------------
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS public_id uuid")
    op.execute("UPDATE users SET public_id = gen_random_uuid() WHERE public_id IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN public_id SET DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE users ALTER COLUMN public_id SET NOT NULL")
    _add_constraint_if_missing("users", "uq_users_public_id", "UNIQUE (public_id)")

    # --- user_roles (ADR-0007, Q3) --------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS user_roles (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id INTEGER NOT NULL
                CONSTRAINT fk_user_roles_user_id REFERENCES users (id) ON DELETE CASCADE,
            role VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            granted_by INTEGER NULL CONSTRAINT fk_user_roles_granted_by REFERENCES users (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_roles_user_role UNIQUE (user_id, role),
            CONSTRAINT ck_user_roles_role CHECK (role IN {ALL_ROLES_SQL}),
            CONSTRAINT ck_user_roles_status CHECK (status IN ('active', 'revoked'))
        )
        """
    )
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
            -- users is first in the global lock order (ADR-0017); serialises activations.
            SELECT u.role INTO primary_role FROM users u WHERE u.id = NEW.user_id FOR UPDATE;
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
    op.execute(
        """
        CREATE OR REPLACE TRIGGER trg_user_roles_q3_guard
        BEFORE INSERT OR UPDATE ON user_roles
        FOR EACH ROW EXECUTE FUNCTION identity_user_roles_q3_guard()
        """
    )
    op.execute(BACKFILL_USER_ROLES_SQL)

    # --- driver_eligibility_blocks (D16) --------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS driver_eligibility_blocks (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            driver_user_id INTEGER NOT NULL
                CONSTRAINT fk_driver_eligibility_blocks_driver_user_id REFERENCES users (id),
            reason TEXT NOT NULL,
            blocked_by INTEGER NOT NULL
                CONSTRAINT fk_driver_eligibility_blocks_blocked_by REFERENCES users (id),
            blocked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            lifted_by INTEGER NULL CONSTRAINT fk_driver_eligibility_blocks_lifted_by REFERENCES users (id),
            lifted_at TIMESTAMPTZ NULL,
            lift_reason TEXT NULL,
            CONSTRAINT ck_driver_eligibility_blocks_reason CHECK (length(btrim(reason)) > 0),
            CONSTRAINT ck_driver_eligibility_blocks_lift_pair CHECK ((lifted_at IS NULL) = (lifted_by IS NULL)),
            CONSTRAINT ck_driver_eligibility_blocks_lift_after_block CHECK (lifted_at IS NULL OR lifted_at >= blocked_at)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_driver_eligibility_blocks_active
        ON driver_eligibility_blocks (driver_user_id) WHERE lifted_at IS NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_driver_eligibility_blocks_driver_user_id "
        "ON driver_eligibility_blocks (driver_user_id)"
    )
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
               OR NEW.blocked_at <> OLD.blocked_at THEN
                RAISE EXCEPTION 'driver eligibility blocks are immutable except for lifting once'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE TRIGGER trg_driver_eligibility_blocks_guard
        BEFORE UPDATE OR DELETE ON driver_eligibility_blocks
        FOR EACH ROW EXECUTE FUNCTION identity_eligibility_blocks_guard()
        """
    )

    # --- driver_document_validity (D16: expired document -> not eligible) -----------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS driver_document_validity (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            driver_document_id INTEGER NOT NULL
                CONSTRAINT fk_driver_document_validity_driver_document_id
                REFERENCES driver_documents (id) ON DELETE CASCADE,
            valid_until TIMESTAMPTZ NOT NULL,
            verified_by INTEGER NOT NULL
                CONSTRAINT fk_driver_document_validity_verified_by REFERENCES users (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_driver_document_validity_driver_document_id UNIQUE (driver_document_id)
        )
        """
    )


def downgrade() -> None:
    # Not a rollback strategy (ADR-0016, spec §18.3).
    pass
