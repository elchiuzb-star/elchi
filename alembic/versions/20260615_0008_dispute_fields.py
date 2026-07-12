"""dispute fields

Revision ID: 20260615_0008
Revises: 20260613_0007
Create Date: 2026-06-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260615_0008"
down_revision: str | None = "20260613_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("disputes", sa.Column("comment", sa.Text(), nullable=True))
    op.add_column("disputes", sa.Column("resolved_by", sa.Integer(), nullable=True))
    op.add_column("disputes", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_disputes_resolved_by_users", "disputes", "users", ["resolved_by"], ["id"])
    op.create_index("ix_disputes_resolved_by", "disputes", ["resolved_by"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_disputes_resolved_by", table_name="disputes")
    op.drop_constraint("fk_disputes_resolved_by_users", "disputes", type_="foreignkey")
    op.drop_column("disputes", "resolved_at")
    op.drop_column("disputes", "resolved_by")
    op.drop_column("disputes", "comment")
