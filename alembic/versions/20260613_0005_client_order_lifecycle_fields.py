"""client order lifecycle fields

Revision ID: 20260613_0005
Revises: 20260613_0004
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260613_0005"
down_revision: str | None = "20260613_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("cancelled_by", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("published_at", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("picked_up_at", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("in_transit_at", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("delivered_at", sa.DateTime(), nullable=True))
    op.add_column("orders", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_orders_cancelled_by_users", "orders", "users", ["cancelled_by"], ["id"])
    op.create_index(op.f("ix_orders_cancelled_by"), "orders", ["cancelled_by"], unique=False)

    op.add_column("status_history", sa.Column("changed_by_role", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("status_history", "changed_by_role")
    op.drop_index(op.f("ix_orders_cancelled_by"), table_name="orders")
    op.drop_constraint("fk_orders_cancelled_by_users", "orders", type_="foreignkey")
    op.drop_column("orders", "cancelled_at")
    op.drop_column("orders", "delivered_at")
    op.drop_column("orders", "in_transit_at")
    op.drop_column("orders", "picked_up_at")
    op.drop_column("orders", "published_at")
    op.drop_column("orders", "cancelled_by")
    op.drop_column("orders", "cancel_reason")
