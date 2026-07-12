"""stage 5 city and route tariff hardening

Revision ID: 20260618_0013
Revises: 20260616_0012
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260618_0013"
down_revision: str | None = "20260616_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("cities", "name", existing_type=sa.String(length=255), type_=sa.String(length=120), existing_nullable=False)
    op.alter_column("cities", "name_uz", existing_type=sa.String(length=255), type_=sa.String(length=120), existing_nullable=False)
    op.alter_column("cities", "name_ru", existing_type=sa.String(length=255), type_=sa.String(length=120), existing_nullable=True)
    op.alter_column("cities", "region", existing_type=sa.String(length=255), type_=sa.String(length=120), existing_nullable=True)

    op.drop_constraint("uq_route_tariffs_route", "route_tariffs", type_="unique")
    op.create_index(
        "uq_route_tariffs_active_route",
        "route_tariffs",
        ["from_city_id", "to_city_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_route_tariffs_active_route", table_name="route_tariffs")
    op.create_unique_constraint("uq_route_tariffs_route", "route_tariffs", ["from_city_id", "to_city_id"])

    op.alter_column("cities", "region", existing_type=sa.String(length=120), type_=sa.String(length=255), existing_nullable=True)
    op.alter_column("cities", "name_ru", existing_type=sa.String(length=120), type_=sa.String(length=255), existing_nullable=True)
    op.alter_column("cities", "name_uz", existing_type=sa.String(length=120), type_=sa.String(length=255), existing_nullable=False)
    op.alter_column("cities", "name", existing_type=sa.String(length=120), type_=sa.String(length=255), existing_nullable=False)
