"""add order cargo_type

Revision ID: 20260630_0025
Revises: 20260626_0024
Create Date: 2026-06-30 00:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260630_0025"
down_revision: str = "20260626_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("cargo_type", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "cargo_type")
