"""driver document review fields

Revision ID: 20260615_0009
Revises: 20260615_0008
Create Date: 2026-06-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260615_0009"
down_revision: str | None = "20260615_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("driver_documents", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("driver_documents", sa.Column("reviewed_by", sa.Integer(), nullable=True))
    op.add_column("driver_documents", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_driver_documents_reviewed_by_users", "driver_documents", "users", ["reviewed_by"], ["id"])
    op.create_index("ix_driver_documents_reviewed_by", "driver_documents", ["reviewed_by"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_driver_documents_reviewed_by", table_name="driver_documents")
    op.drop_constraint("fk_driver_documents_reviewed_by_users", "driver_documents", type_="foreignkey")
    op.drop_column("driver_documents", "reviewed_at")
    op.drop_column("driver_documents", "reviewed_by")
    op.drop_column("driver_documents", "rejection_reason")
