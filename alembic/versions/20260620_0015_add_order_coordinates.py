"""add order coordinates

Revision ID: 20260620_0015
Revises: 20260618_0014
Create Date: 2026-06-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260620_0015"
down_revision: str | None = "20260618_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("pickup_lat", sa.Numeric(10, 7), nullable=True))
    op.add_column("orders", sa.Column("pickup_lng", sa.Numeric(10, 7), nullable=True))
    op.add_column("orders", sa.Column("dropoff_lat", sa.Numeric(10, 7), nullable=True))
    op.add_column("orders", sa.Column("dropoff_lng", sa.Numeric(10, 7), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "dropoff_lng")
    op.drop_column("orders", "dropoff_lat")
    op.drop_column("orders", "pickup_lng")
    op.drop_column("orders", "pickup_lat")
