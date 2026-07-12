"""order offers matching fields

Revision ID: 20260613_0006
Revises: 20260613_0005
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260613_0006"
down_revision: str | None = "20260613_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("order_offers", sa.Column("result", sa.String(length=32), nullable=True))
    op.add_column("order_offers", sa.Column("shown_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE order_offers SET result = CASE WHEN status = 'offered' THEN 'shown' ELSE status END")
    op.execute("UPDATE order_offers SET status = 'shown' WHERE status = 'offered'")
    op.alter_column("order_offers", "result", nullable=False)

    op.create_index("idx_driver_routes_from_to", "driver_routes", ["from_city_id", "to_city_id"], unique=False)
    op.create_index("idx_driver_routes_status", "driver_routes", ["status"], unique=False)
    op.create_index(
        "idx_driver_profiles_verification_status",
        "driver_profiles",
        ["verification_status"],
        unique=False,
    )
    op.create_index("idx_driver_profiles_is_available", "driver_profiles", ["is_available"], unique=False)
    op.create_index("idx_orders_from_to", "orders", ["from_city_id", "to_city_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_orders_from_to", table_name="orders")
    op.drop_index("idx_driver_profiles_is_available", table_name="driver_profiles")
    op.drop_index("idx_driver_profiles_verification_status", table_name="driver_profiles")
    op.drop_index("idx_driver_routes_status", table_name="driver_routes")
    op.drop_index("idx_driver_routes_from_to", table_name="driver_routes")
    op.drop_column("order_offers", "shown_at")
    op.drop_column("order_offers", "result")
