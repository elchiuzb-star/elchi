"""identity: why a refresh session ended

Owner: A1/A12 (wave 8) - spec §17.6, user decision of 17.09.2026 (option A of
``docs/architecture/decisions-pending/v1-logout-access-token.md``).

v1 now refuses an access token whose login session is gone. Without this column "gone" would also cover the
session that a **token refresh** replaced, and the frozen Android client (AGENTS §2) would start getting 401s
on requests that were already in flight when it rotated its token - a failure mode the approved decision never
asked for. The reason separates the two:

  * ``logout`` / ``admin_revoke`` - the session really ended; v1 and v2 both refuse its access token at once;
  * ``rotated`` - a successor session exists; v2 (our own client) still refuses it, v1 lets the old access
    token finish its natural life.

``NULL`` means a row revoked before this migration: the reason is unknown, so it is treated as ended (fail
closed). That costs at most one access-token lifetime of stale-token 401s, once, right after deploy.

Rules: additive nullable column, idempotent, no backfill of history that we cannot know; single head.
downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0072
Revises: 20260917_0071
Create Date: 2026-09-17 16:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0072"
down_revision: str = "20260917_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = ("logout", "rotated", "admin_revoke", "account_deleted")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect != "postgresql":
        return
    op.execute("ALTER TABLE public.refresh_sessions ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR(32)")
    op.execute("ALTER TABLE public.refresh_sessions DROP CONSTRAINT IF EXISTS ck_refresh_sessions_revoked_reason")
    values = ", ".join(f"'{reason}'" for reason in REASONS)
    op.execute(
        "ALTER TABLE public.refresh_sessions ADD CONSTRAINT ck_refresh_sessions_revoked_reason CHECK ("
        f"revoked_reason IS NULL OR (is_revoked AND revoked_reason IN ({values}))) NOT VALID"
    )
    op.execute("ALTER TABLE public.refresh_sessions VALIDATE CONSTRAINT ck_refresh_sessions_revoked_reason")
    op.execute(
        "COMMENT ON COLUMN public.refresh_sessions.revoked_reason IS "
        "'§17.6: why the session ended. NULL on a live session, and on rows revoked before 0072 (treated as "
        "ended). ''rotated'' means a successor session exists.'"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): the column is additive, so dropping it only loses the reason."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.refresh_sessions DROP CONSTRAINT IF EXISTS ck_refresh_sessions_revoked_reason")
    op.execute("ALTER TABLE public.refresh_sessions DROP COLUMN IF EXISTS revoked_reason")
