"""add users.username and users.password_hash for staff password login

Revision ID: 20260803_0029
Revises: 20260729_0028
Create Date: 2026-08-03 00:29:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0029"
down_revision: str = "20260729_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both nullable: only staff have them, clients and drivers stay on SMS OTP.
    op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    # Unique, but nullable — Postgres allows many NULLs under a unique index.
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "username")
