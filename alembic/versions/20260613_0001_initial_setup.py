"""initial setup

Revision ID: 20260613_0001
Revises:
Create Date: 2026-06-13
"""

from collections.abc import Sequence

revision: str = "20260613_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
