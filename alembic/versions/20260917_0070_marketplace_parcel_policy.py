"""marketplace parcel policy (prohibited and restricted items)

Owner: A1 (wave 7) - spec §5.2 ("Pilot limiti va **taqiqlangan jo'natmalar ro'yxati** admin sozlamasida
beriladi"), §17.7, AGENTS §9 (no invented business rules).

Until now the pilot enforced size limits only, and the prohibited-items list existed nowhere: an empty list was
indistinguishable from "everything may be sent". This migration adds the *mechanism* - a versioned, explicitly
approved policy - while the **content** of the list stays a business/legal decision:

  * ``parcel_policy_versions`` - one row per drafted policy. ``draft`` is visible to staff only;
    ``active`` needs ``confirmed_by`` (a super_admin), exactly like the commission-policy confirmation of Q28.
    At most one active version at a time (partial unique index).
  * ``parcel_policy_items`` - the rules of that version: ``category`` (``prohibited`` = forbidden by law,
    ``restricted`` = allowed only with a permit/conditions, ``business_declined`` = Elchi does not carry it),
    a user-facing title and description, the legal or business basis, the source reference and **the date that
    source was checked**. Nothing here is generated from code: a row exists because a human put it there.

Fail-closed by design (§5.2 + AGENTS §9): with no confirmed active version the reader answers "policy missing",
and the marketplace refuses **new** parcel listings and bookings in production. Bookings that already exist keep
running - an unapproved list must never strand a parcel that is already on the road.

FK / object dependencies: 0032 (users).

Rules: idempotent (IF NOT EXISTS); do not change the revision id, file name or down_revision; single head.
downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0070
Revises: 20260917_0069
Create Date: 2026-09-17 13:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0070"
down_revision: str = "20260917_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_STATUSES = ("draft", "active", "superseded")
ITEM_CATEGORIES = ("prohibited", "restricted", "business_declined")
# Which shipments a rule applies to: every parcel, or only what a passenger carries as luggage.
ITEM_SCOPES = ("parcel", "passenger_baggage", "all")


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.parcel_policy_versions (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id      UUID NOT NULL,
            label          VARCHAR(64) NOT NULL,
            status         VARCHAR(16) NOT NULL DEFAULT 'draft',
            source_note    TEXT,
            created_by     INTEGER NOT NULL REFERENCES public.users(id),
            confirmed_by   INTEGER REFERENCES public.users(id),
            confirmed_at   TIMESTAMPTZ,
            effective_from TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            version        INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT uq_parcel_policy_versions_public_id UNIQUE (public_id),
            CONSTRAINT uq_parcel_policy_versions_label UNIQUE (label),
            CONSTRAINT ck_parcel_policy_versions_status CHECK (status IN {_in(POLICY_STATUSES)}),
            CONSTRAINT ck_parcel_policy_versions_confirm CHECK (
                (status = 'draft' AND confirmed_by IS NULL AND confirmed_at IS NULL AND effective_from IS NULL)
                OR (status IN ('active', 'superseded')
                    AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL AND effective_from IS NOT NULL)
            )
        )
        """
    )
    # Q28 pattern: exactly one approved policy is in force, so "which list applies" is never ambiguous.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_parcel_policy_versions_active "
        "ON public.parcel_policy_versions (status) WHERE status = 'active'"
    )
    op.execute(
        "COMMENT ON TABLE public.parcel_policy_versions IS "
        "'§5.2: the approved prohibited/restricted items policy. A draft is staff-only; active needs a "
        "super_admin confirmation. No approved version = no NEW parcel business in production (fail-closed), "
        "while existing bookings finish.'"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.parcel_policy_items (
            id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            policy_version_id BIGINT NOT NULL REFERENCES public.parcel_policy_versions(id) ON DELETE CASCADE,
            code              VARCHAR(64) NOT NULL,
            category          VARCHAR(24) NOT NULL,
            applies_to        VARCHAR(24) NOT NULL DEFAULT 'parcel',
            title_uz          TEXT NOT NULL,
            description_uz    TEXT NOT NULL,
            legal_basis       TEXT,
            source_ref        TEXT,
            source_checked_on DATE,
            display_order     INTEGER NOT NULL DEFAULT 100,
            CONSTRAINT uq_parcel_policy_items_code UNIQUE (policy_version_id, code),
            CONSTRAINT ck_parcel_policy_items_category CHECK (category IN {_in(ITEM_CATEGORIES)}),
            CONSTRAINT ck_parcel_policy_items_scope CHECK (applies_to IN {_in(ITEM_SCOPES)}),
            CONSTRAINT ck_parcel_policy_items_basis CHECK (
                category <> 'prohibited' OR (legal_basis IS NOT NULL AND source_ref IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_parcel_policy_items_version "
        "ON public.parcel_policy_items (policy_version_id, display_order, id)"
    )
    op.execute(
        "COMMENT ON TABLE public.parcel_policy_items IS "
        "'§5.2 rules of one policy version. A `prohibited` row must carry its legal basis and source (CHECK): "
        "the platform never tells a user something is illegal without naming why and where that comes from.'"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016)."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS public.parcel_policy_items")
    op.execute("DROP TABLE IF EXISTS public.parcel_policy_versions")
