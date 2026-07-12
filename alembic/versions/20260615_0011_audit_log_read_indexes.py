"""audit log read indexes

Revision ID: 20260615_0011
Revises: 20260615_0010
Create Date: 2026-06-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260615_0011"
down_revision: str | None = "20260615_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("idx_audit_logs_entity_type_entity_id", "audit_logs", ["entity_type", "entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_audit_logs_entity_type_entity_id", table_name="audit_logs")
    op.drop_index("idx_audit_logs_created_at", table_name="audit_logs")
