"""add order client_price

Revision ID: 20260701_0026
Revises: 20260630_0025
Create Date: 2026-07-01 00:26:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260701_0026"
down_revision: str = "20260630_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("client_price", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "client_price")
