"""promotions rate events: abuse limits for the referral HTTP surface (stage 5)

Owner: referral stage 5 (ADR-0023 §16, §19) - module `promotions`.
Content (DATA_MODEL.md §5):
  * ``promo_rate_events`` - one row per counted request of an abuse-prone referral endpoint (public code check per
    source, attribution per user). The same mechanism the rest of the platform uses - count rows in a time window
    (OTP per IP, listings per author, support tickets) - with a table of its own because a code check stores nothing
    else. ``key_hash`` is an HMAC of the source (IP or user id) with a purpose subkey: no IP address and no user id is
    stored in clear. Rows older than a day are deleted by the ``promotions.purge_rate_events`` job.

Rules: idempotent; single head; downgrade() is a dev/test tool, not a rollback (ADR-0016, spec §18.3).

Revision ID: 20260923_0088
Revises: 20260923_0087
Create Date: 2026-09-23 00:88:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0088"
down_revision: str = "20260923_0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS = ("code_check", "attribution")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    actions = ", ".join(f"'{action}'" for action in ACTIONS)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS promo_rate_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            action VARCHAR(32) NOT NULL,
            key_hash CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_promo_rate_events_action CHECK (action IN ({actions}))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promo_rate_events_window ON promo_rate_events (action, key_hash, created_at)"
    )


def downgrade() -> None:
    """Dev/test tool only (ADR-0016): not a rollback strategy."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS promo_rate_events")
