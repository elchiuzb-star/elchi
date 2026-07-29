"""add otp_codes.ip_address for per-IP rate limiting

Revision ID: 20260729_0028
Revises: 20260705_0027
Create Date: 2026-07-29 00:28:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260729_0028"
down_revision: str = "20260705_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("otp_codes", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.create_index("ix_otp_codes_ip_address", "otp_codes", ["ip_address"])


def downgrade() -> None:
    op.drop_index("ix_otp_codes_ip_address", table_name="otp_codes")
    op.drop_column("otp_codes", "ip_address")
