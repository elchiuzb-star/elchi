"""add system commission settings

Revision ID: 20260625_0022
Revises: 20260622_0021, 20260622_0016
Create Date: 2026-06-25 00:22:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260625_0022"
down_revision: tuple[str, str] = ("20260622_0021", "20260622_0016")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(op.f("ix_system_settings_updated_by_user_id"), "system_settings", ["updated_by_user_id"], unique=False)
    op.add_column("orders", sa.Column("system_fee_rate", sa.Numeric(5, 4), nullable=True))
    op.add_column("orders", sa.Column("system_fee", sa.Numeric(12, 2), nullable=True))
    op.add_column("orders", sa.Column("driver_income", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "driver_income")
    op.drop_column("orders", "system_fee")
    op.drop_column("orders", "system_fee_rate")
    op.drop_index(op.f("ix_system_settings_updated_by_user_id"), table_name="system_settings")
    op.drop_table("system_settings")
