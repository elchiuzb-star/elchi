"""retired order pickup available time

Revision ID: 20260626_0023
Revises: 20260625_0022
Create Date: 2026-06-26 00:23:00.000000
"""

from collections.abc import Sequence


revision: str = "20260626_0023"
down_revision: str = "20260625_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
