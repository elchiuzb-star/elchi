"""add bid price_update_count

Revision ID: 20260705_0027
Revises: 20260701_0026
Create Date: 2026-07-05 00:27:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260705_0027"
down_revision: str = "20260701_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bids",
        sa.Column("price_update_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("bids", "price_update_count")
