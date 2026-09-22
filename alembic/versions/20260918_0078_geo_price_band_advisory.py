"""geo: a price band advises the auction, it does not decide it

Owner: A0a/A2 (wave 15) - user decision Q90 (18.09.2026), which softens Q42/Q53/Q67.

ELCHI is a two-sided auction: the price is what the two people agree on, not what the platform computes. A
corridor band that hard-rejects an offer turns the negotiation into a fixed-fare booking - the exact drift this
wave exists to undo. So the band stays, and what changes is what it *does*: by default it is advice (a warning
on the response, a ranking and anomaly signal), and only a band an admin has deliberately marked ``enforced``
still refuses a price.

``enforced`` is therefore false by default and is meant to stay false except for a genuine abuse or safety
limit that somebody has decided to impose and can be held to.

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260918_0078
Revises: 20260918_0077
Create Date: 2026-09-18 04:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260918_0078"
down_revision: str = "20260918_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE public.corridor_price_bands ADD COLUMN IF NOT EXISTS enforced BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "COMMENT ON COLUMN public.corridor_price_bands.enforced IS "
        "'Q90: false (default) means the band only warns and ranks - a negotiated price is never refused for "
        "being outside it. True is an admin-imposed abuse/safety limit and does refuse.'"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): every band falls back to advisory."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.corridor_price_bands DROP COLUMN IF EXISTS enforced")
