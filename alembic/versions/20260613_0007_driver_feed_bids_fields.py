"""driver feed bids fields

Revision ID: 20260613_0007
Revises: 20260613_0006
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260613_0007"
down_revision: str | None = "20260613_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("order_offers", sa.Column("responded_at", sa.DateTime(), nullable=True))
    op.create_index("idx_order_offers_result", "order_offers", ["result"], unique=False)
    op.create_index("idx_bids_order_driver", "bids", ["order_id", "driver_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_bids_order_driver", table_name="bids")
    op.drop_index("idx_order_offers_result", table_name="order_offers")
    op.drop_column("order_offers", "responded_at")
