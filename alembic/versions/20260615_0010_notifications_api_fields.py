"""notifications api fields

Revision ID: 20260615_0010
Revises: 20260615_0009
Create Date: 2026-06-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260615_0010"
down_revision: str | None = "20260615_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("order_id", sa.Integer(), nullable=True))
    op.add_column("notifications", sa.Column("channel", sa.String(length=32), server_default="in_app", nullable=False))
    op.add_column("notifications", sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.execute("UPDATE notifications SET order_id = entity_id WHERE entity_type = 'order' AND order_id IS NULL")
    op.create_foreign_key("fk_notifications_order_id_orders", "notifications", "orders", ["order_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_notifications_order_id", "notifications", ["order_id"], unique=False)
    op.create_index("ix_notifications_type", "notifications", ["type"], unique=False)
    op.create_index("ix_notifications_is_read", "notifications", ["is_read"], unique=False)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_user_read_created", "notifications", ["user_id", "is_read", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_is_read", table_name="notifications")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_notifications_order_id", table_name="notifications")
    op.drop_constraint("fk_notifications_order_id_orders", "notifications", type_="foreignkey")
    op.drop_column("notifications", "sent_at")
    op.drop_column("notifications", "channel")
    op.drop_column("notifications", "order_id")
