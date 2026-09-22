"""identity: staff MFA (TOTP), recovery codes and an append-only event log

Owner: A12/A1 (wave 8) - ADR-0021, accepted by the product owner on 17.09.2026. Spec §17.5, §17.6.

Three tables, and two rules that the database - not the application - enforces, because they are the reason
MFA is worth having at all:

  * ``staff_mfa_factors.activated_by <> user_id``: the person who enrolls a factor can never be the person who
    activates it. One employee must not be able to hand themselves a second factor quietly (Q17/Q49 spirit);
  * ``staff_mfa_events`` rows for ``factor_activated`` / ``factor_reset`` carry an actor different from the
    subject, and the table refuses UPDATE and DELETE - an attacker with app-role access cannot erase the trail.

Recovery codes are stored as SHA-256 only (ADR-0018) and are **not** a way around anything: consuming one lets
its owner enroll a new factor, and the application never treats it as a financial approval.

Rules: idempotent, additive, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0074
Revises: 20260917_0073
Create Date: 2026-09-17 17:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0074"
down_revision: str = "20260917_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACTOR_STATUSES = ("pending", "active", "revoked")
EVENT_TYPES = (
    "factor_enrolled", "factor_activated", "factor_revoked", "factor_reset",
    "verify_succeeded", "verify_failed", "step_up", "recovery_code_used", "break_glass_used",
)
TWO_PERSON_EVENTS = ("factor_activated", "factor_reset")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.staff_mfa_factors (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            user_id INTEGER NOT NULL REFERENCES public.users (id),
            factor_type VARCHAR(16) NOT NULL DEFAULT 'totp',
            secret_cipher BYTEA NOT NULL,
            secret_key_version SMALLINT NOT NULL DEFAULT 1,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            last_counter BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            activated_at TIMESTAMPTZ,
            activated_by INTEGER REFERENCES public.users (id),
            revoked_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT uq_staff_mfa_factors_public_id UNIQUE (public_id),
            CONSTRAINT ck_staff_mfa_factors_status CHECK (status IN {_in(FACTOR_STATUSES)}),
            CONSTRAINT ck_staff_mfa_factors_type CHECK (factor_type IN ('totp')),
            -- The whole point of the second pair of eyes: an enroller cannot approve their own factor.
            CONSTRAINT ck_staff_mfa_factors_two_person CHECK (activated_by IS NULL OR activated_by <> user_id),
            CONSTRAINT ck_staff_mfa_factors_activation CHECK (
                (status = 'active') = (activated_at IS NOT NULL AND activated_by IS NOT NULL)
            )
        )
        """
    )
    # One active factor per staff account; pending enrollments may be replaced freely.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_mfa_factors_active_user "
        "ON public.staff_mfa_factors (user_id) WHERE status = 'active'"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.staff_mfa_recovery_codes (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES public.users (id),
            code_hash CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            used_at TIMESTAMPTZ,
            CONSTRAINT uq_staff_mfa_recovery_code_hash UNIQUE (code_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staff_mfa_recovery_codes_user "
        "ON public.staff_mfa_recovery_codes (user_id, id)"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.staff_mfa_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES public.users (id),
            actor_user_id INTEGER REFERENCES public.users (id),
            event_type VARCHAR(32) NOT NULL,
            detail JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_staff_mfa_events_type CHECK (event_type IN {_in(EVENT_TYPES)}),
            CONSTRAINT ck_staff_mfa_events_two_person CHECK (
                event_type NOT IN {_in(TWO_PERSON_EVENTS)}
                OR (actor_user_id IS NOT NULL AND actor_user_id <> user_id)
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_staff_mfa_events_user ON public.staff_mfa_events (user_id, id)")

    # Append-only: the audit trail is worthless if the same role that is compromised can rewrite it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.staff_mfa_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'staff_mfa_events is append-only'
                USING ERRCODE = 'restrict_violation', CONSTRAINT = 'staff_mfa_events_append_only';
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS staff_mfa_events_append_only ON public.staff_mfa_events")
    op.execute(
        "CREATE TRIGGER staff_mfa_events_append_only BEFORE UPDATE OR DELETE ON public.staff_mfa_events "
        "FOR EACH ROW EXECUTE FUNCTION public.staff_mfa_events_append_only()"
    )

    op.execute(
        "COMMENT ON TABLE public.staff_mfa_factors IS "
        "'ADR-0021: staff second factor. The secret is sealed (AES-GCM), never stored or logged in the clear; "
        "activation needs a different super_admin (ck_staff_mfa_factors_two_person).'"
    )
    op.execute(
        "COMMENT ON TABLE public.staff_mfa_recovery_codes IS "
        "'ADR-0021: SHA-256 of one-time recovery codes. A code restores the ability to enroll a factor; it is "
        "never a financial approval and never bypasses the two-person money rule.'"
    )
    op.execute(
        "COMMENT ON TABLE public.staff_mfa_events IS 'ADR-0021: append-only MFA audit trail, no secrets.'"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS staff_mfa_events_append_only ON public.staff_mfa_events")
    op.execute("DROP FUNCTION IF EXISTS public.staff_mfa_events_append_only()")
    op.execute("DROP TABLE IF EXISTS public.staff_mfa_events")
    op.execute("DROP TABLE IF EXISTS public.staff_mfa_recovery_codes")
    op.execute("DROP TABLE IF EXISTS public.staff_mfa_factors")
