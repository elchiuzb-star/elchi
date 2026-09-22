"""platform revision lineage

Owner: A0a / A10a (wave 5) - **Q50 launch gate**, ADR-0012 / ADR-0016, spec §18.3, §19.2 (readiness, Q32).

Problem: readiness compares the DB revisions with the heads of the *shipped* script graph (decision 32). After a
deploy rollback the database is one or more revisions ahead of the running image - and that image cannot know
revisions written after it was built, so it answers ``unknown`` -> 503, even though the schema is a safe,
expand-only descendant of what it needs. Q50 accepted that 503 temporarily and made the lineage a launch gate.

This migration creates the missing fact: ``alembic_revision_lineage`` records every applied revision with its
parent, so **any** image can walk the chain in the database and decide whether the DB head descends from its own
head - without owning the newer migration files.

  * ``revision`` / ``down_revision`` - the edge of the migration graph (``down_revision`` NULL = base).
  * ``applied_at`` - when this runner wrote the row; ``applied_by`` - the database role that ran it.
  * merges/branches: a revision with several parents is stored once per parent (unique edge).

Writer: ``alembic/env.py`` after every successful run (idempotent upsert of the whole shipped graph, so a
database migrated by older runners gets its history on the next deploy too). The table is read-only for the
app role (``scripts/db_roles.py``): the readiness probe only reads it.

Rules: idempotent (IF NOT EXISTS, ON CONFLICT DO NOTHING); single head; downgrade drops the table (dev/test only).

Revision ID: 20260916_0067
Revises: 20260916_0066
Create Date: 2026-09-17 08:05:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0067"
down_revision: str = "20260916_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "alembic_revision_lineage"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.{TABLE} (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            revision       VARCHAR(64) NOT NULL,
            down_revision  VARCHAR(64),
            applied_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            applied_by     TEXT NOT NULL DEFAULT current_user,
            CONSTRAINT uq_{TABLE}_edge UNIQUE NULLS NOT DISTINCT (revision, down_revision)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE public.{TABLE} IS "
        "'Q50: applied migration graph (revision -> parent) so an image older than the database can still "
        "recognise the schema as a descendant of its own head (readiness ahead vs unknown, decision 32). "
        "Written by alembic/env.py after every run; read by the readiness probe.'"
    )
    # The rows themselves are written by alembic/env.py right after this run finishes: it owns the ScriptDirectory
    # and can record the whole graph (including every revision applied before this table existed) in one upsert.


def downgrade() -> None:
    """Dev/test only (ADR-0016): the table is history, not state - dropping it loses no business data."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP TABLE IF EXISTS public.{TABLE}")
