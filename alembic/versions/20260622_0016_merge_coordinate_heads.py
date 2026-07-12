"""merge coordinate migration heads

Revision ID: 20260622_0016
Revises: 20260620_0015, ac62a9c9e9e2
Create Date: 2026-06-22 00:00:00.000000
"""

from collections.abc import Sequence


revision: str = "20260622_0016"
down_revision: tuple[str, str] = ("20260620_0015", "ac62a9c9e9e2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
