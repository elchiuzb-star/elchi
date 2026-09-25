"""marketplace parcel catalog: no second-approver requirement (ADR-0026 follow-up)

Owner: A0a (integrator) - module `marketplace` (parcel size catalog, Q140).
Content: drops `ck_parcel_category_versions_two_people` (0092). The size catalog is a separate concept from the
prohibited-items policy (§5.2); the two-person approval was copied from that policy's pattern and no approved rule in
this repository requires it for the catalog (the explicit two-person rules - Q17, Q69, Q114 - are about money). The
catalog stays versioned (draft -> active -> superseded), managed only with `platform.policy_manage`, audited, and a
`synthetic` version is still never activated in production.
Forward only, idempotent (`DROP CONSTRAINT IF EXISTS`). `downgrade()` is not a rollback strategy (ADR-0016).

Revision ID: 20260925_0094
Revises: 20260925_0093
Create Date: 2026-09-25 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_0094"
down_revision: str = "20260925_0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.parcel_category_versions DROP CONSTRAINT IF EXISTS ck_parcel_category_versions_two_people")


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""
