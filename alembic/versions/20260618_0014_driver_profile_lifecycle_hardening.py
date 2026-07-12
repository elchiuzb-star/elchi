"""driver profile lifecycle hardening

Revision ID: 20260618_0014
Revises: 20260618_0013
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260618_0014"
down_revision: str | None = "20260618_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("driver_profiles", sa.Column("plate_number_normalized", sa.String(length=32), nullable=True))
    op.execute(
        """
        UPDATE driver_profiles
        SET plate_number_normalized = upper(replace(replace(trim(plate_number), ' ', ''), '-', ''))
        WHERE plate_number IS NOT NULL
        """
    )
    op.create_index(op.f("ix_driver_profiles_plate_number_normalized"), "driver_profiles", ["plate_number_normalized"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_driver_profiles_plate_number_normalized"), table_name="driver_profiles")
    op.drop_column("driver_profiles", "plate_number_normalized")
