"""platform extensions: postgis and btree_gist

Owner: A10a (wave 1) - module `platform` (infrastructure).
Planned content (DATA_MODEL.md §5): CREATE EXTENSION IF NOT EXISTS postgis; btree_gist.
Tables: none. btree_gist is needed by the exclusion constraints in 0036 (commission
policies) and 0038 (trips); postgis by 0034/0035 (geo) and later tracking.

Implemented by the integrator (A0a) because it is trivial. Production deploy only after
the PostGIS image switch (ADR-0013). Extensions are never dropped on downgrade.

Rules: must stay idempotent; do not change revision ids or the chain (ADR-0016).

Revision ID: 20260913_0030
Revises: 20260803_0029
Create Date: 2026-09-13 00:30:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260913_0030"
down_revision: str = "20260803_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL-only objects; the SQLite suite never runs migrations, but keep
    # a local SQLite `alembic upgrade` from failing.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade() -> None:
    # Shared infrastructure: never dropped (ADR-0013). Downgrade is not a rollback (spec §18.3).
    pass
