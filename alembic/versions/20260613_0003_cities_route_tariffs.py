"""cities and route tariffs fields

Revision ID: 20260613_0003
Revises: 20260613_0002
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260613_0003"
down_revision: str | None = "20260613_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cities", sa.Column("name_uz", sa.String(length=255), nullable=True))
    op.add_column("cities", sa.Column("name_ru", sa.String(length=255), nullable=True))
    op.add_column("cities", sa.Column("region", sa.String(length=255), nullable=True))
    op.execute("UPDATE cities SET name_uz = name WHERE name_uz IS NULL")
    op.alter_column("cities", "name_uz", nullable=False)
    op.create_index(op.f("ix_cities_name_uz"), "cities", ["name_uz"], unique=False)
    op.create_index(op.f("ix_cities_name_ru"), "cities", ["name_ru"], unique=False)
    op.create_index(op.f("ix_cities_region"), "cities", ["region"], unique=False)
    op.create_unique_constraint("uq_cities_name_uz", "cities", ["name_uz"])

    op.add_column("route_tariffs", sa.Column("min_price", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("route_tariffs", sa.Column("max_price", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("route_tariffs", sa.Column("is_active", sa.Boolean(), nullable=True))
    op.execute("UPDATE route_tariffs SET is_active = true WHERE is_active IS NULL")
    op.alter_column("route_tariffs", "is_active", nullable=False)
    op.create_index(op.f("ix_route_tariffs_is_active"), "route_tariffs", ["is_active"], unique=False)
    op.create_check_constraint(
        "ck_route_tariffs_min_price_nonnegative",
        "route_tariffs",
        "min_price IS NULL OR min_price >= 0",
    )
    op.create_check_constraint(
        "ck_route_tariffs_max_price_nonnegative",
        "route_tariffs",
        "max_price IS NULL OR max_price >= 0",
    )
    op.create_check_constraint(
        "ck_route_tariffs_min_lte_suggested",
        "route_tariffs",
        "min_price IS NULL OR min_price <= suggested_price",
    )
    op.create_check_constraint(
        "ck_route_tariffs_suggested_lte_max",
        "route_tariffs",
        "max_price IS NULL OR suggested_price <= max_price",
    )


def downgrade() -> None:
    op.drop_constraint("ck_route_tariffs_suggested_lte_max", "route_tariffs", type_="check")
    op.drop_constraint("ck_route_tariffs_min_lte_suggested", "route_tariffs", type_="check")
    op.drop_constraint("ck_route_tariffs_max_price_nonnegative", "route_tariffs", type_="check")
    op.drop_constraint("ck_route_tariffs_min_price_nonnegative", "route_tariffs", type_="check")
    op.drop_index(op.f("ix_route_tariffs_is_active"), table_name="route_tariffs")
    op.drop_column("route_tariffs", "is_active")
    op.drop_column("route_tariffs", "max_price")
    op.drop_column("route_tariffs", "min_price")

    op.drop_constraint("uq_cities_name_uz", "cities", type_="unique")
    op.drop_index(op.f("ix_cities_region"), table_name="cities")
    op.drop_index(op.f("ix_cities_name_ru"), table_name="cities")
    op.drop_index(op.f("ix_cities_name_uz"), table_name="cities")
    op.drop_column("cities", "region")
    op.drop_column("cities", "name_ru")
    op.drop_column("cities", "name_uz")
