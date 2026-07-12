"""driver profile fields

Revision ID: 20260613_0004
Revises: 20260613_0003
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260613_0004"
down_revision: str | None = "20260613_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=255), nullable=True))

    op.add_column("driver_profiles", sa.Column("car_color", sa.String(length=64), nullable=True))
    op.add_column("driver_profiles", sa.Column("total_orders", sa.Integer(), nullable=True))
    op.add_column("driver_profiles", sa.Column("completed_orders", sa.Integer(), nullable=True))
    op.add_column("driver_profiles", sa.Column("cancelled_orders", sa.Integer(), nullable=True))
    op.add_column("driver_profiles", sa.Column("dispute_count", sa.Integer(), nullable=True))

    op.execute("UPDATE driver_profiles SET total_orders = 0 WHERE total_orders IS NULL")
    op.execute("UPDATE driver_profiles SET completed_orders = 0 WHERE completed_orders IS NULL")
    op.execute("UPDATE driver_profiles SET cancelled_orders = 0 WHERE cancelled_orders IS NULL")
    op.execute("UPDATE driver_profiles SET dispute_count = 0 WHERE dispute_count IS NULL")
    op.execute("UPDATE driver_profiles SET rating_avg = 0 WHERE rating_avg IS NULL")

    op.alter_column("driver_profiles", "total_orders", nullable=False)
    op.alter_column("driver_profiles", "completed_orders", nullable=False)
    op.alter_column("driver_profiles", "cancelled_orders", nullable=False)
    op.alter_column("driver_profiles", "dispute_count", nullable=False)
    op.alter_column("driver_profiles", "rating_avg", nullable=False)


def downgrade() -> None:
    op.alter_column("driver_profiles", "rating_avg", nullable=True)
    op.drop_column("driver_profiles", "dispute_count")
    op.drop_column("driver_profiles", "cancelled_orders")
    op.drop_column("driver_profiles", "completed_orders")
    op.drop_column("driver_profiles", "total_orders")
    op.drop_column("driver_profiles", "car_color")
    op.drop_column("users", "full_name")
