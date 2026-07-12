"""add district center coordinates

Revision ID: 20260622_0021
Revises: 20260622_0020
Create Date: 2026-06-22 00:21:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260622_0021"
down_revision: str | None = "20260622_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("center_lat", sa.Numeric(10, 7), nullable=True))
    op.add_column("districts", sa.Column("center_lng", sa.Numeric(10, 7), nullable=True))


def downgrade() -> None:
    op.drop_column("districts", "center_lng")
    op.drop_column("districts", "center_lat")
