"""add districts and district route fields

Revision ID: 20260622_0020
Revises: 20260620_0015
Create Date: 2026-06-22 00:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260622_0020"
down_revision: str | None = "20260620_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cities", sa.Column("type", sa.String(length=32), nullable=False, server_default="region"))
    op.add_column("cities", sa.Column("requires_district", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("cities", sa.Column("display_order", sa.Integer(), nullable=False, server_default="1000"))

    op.execute(
        """
        UPDATE cities
        SET type = 'city',
            requires_district = false,
            display_order = 1,
            region = COALESCE(region, 'Toshkent shahri')
        WHERE lower(name_uz) IN ('toshkent', 'toshkent shahri')
        """
    )
    op.execute(
        """
        UPDATE cities
        SET type = 'republic'
        WHERE lower(name_uz) IN ('nukus', 'qoraqalpogiston', 'qoraqalpogiston respublikasi')
        """
    )

    op.create_table(
        "districts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("name_uz", sa.String(length=120), nullable=False),
        sa.Column("name_ru", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_districts_city_id", "districts", ["city_id"])
    op.create_index("ix_districts_is_active", "districts", ["is_active"])
    op.create_index("ix_districts_name_ru", "districts", ["name_ru"])
    op.create_index("ix_districts_name_uz", "districts", ["name_uz"])
    op.create_index("ix_districts_city_lower_name_uz", "districts", ["city_id", sa.text("lower(name_uz)")], unique=True)

    op.add_column("orders", sa.Column("from_district_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("to_district_id", sa.Integer(), nullable=True))
    op.create_index("ix_orders_from_district_id", "orders", ["from_district_id"])
    op.create_index("ix_orders_to_district_id", "orders", ["to_district_id"])
    op.create_foreign_key("fk_orders_from_district_id_districts", "orders", "districts", ["from_district_id"], ["id"])
    op.create_foreign_key("fk_orders_to_district_id_districts", "orders", "districts", ["to_district_id"], ["id"])

    op.add_column("driver_routes", sa.Column("from_district_id", sa.Integer(), nullable=True))
    op.add_column("driver_routes", sa.Column("to_district_id", sa.Integer(), nullable=True))
    op.create_index("ix_driver_routes_from_district_id", "driver_routes", ["from_district_id"])
    op.create_index("ix_driver_routes_to_district_id", "driver_routes", ["to_district_id"])
    op.create_foreign_key("fk_driver_routes_from_district_id_districts", "driver_routes", "districts", ["from_district_id"], ["id"])
    op.create_foreign_key("fk_driver_routes_to_district_id_districts", "driver_routes", "districts", ["to_district_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_driver_routes_to_district_id_districts", "driver_routes", type_="foreignkey")
    op.drop_constraint("fk_driver_routes_from_district_id_districts", "driver_routes", type_="foreignkey")
    op.drop_index("ix_driver_routes_to_district_id", table_name="driver_routes")
    op.drop_index("ix_driver_routes_from_district_id", table_name="driver_routes")
    op.drop_column("driver_routes", "to_district_id")
    op.drop_column("driver_routes", "from_district_id")

    op.drop_constraint("fk_orders_to_district_id_districts", "orders", type_="foreignkey")
    op.drop_constraint("fk_orders_from_district_id_districts", "orders", type_="foreignkey")
    op.drop_index("ix_orders_to_district_id", table_name="orders")
    op.drop_index("ix_orders_from_district_id", table_name="orders")
    op.drop_column("orders", "to_district_id")
    op.drop_column("orders", "from_district_id")

    op.drop_index("ix_districts_city_lower_name_uz", table_name="districts")
    op.drop_index("ix_districts_name_uz", table_name="districts")
    op.drop_index("ix_districts_name_ru", table_name="districts")
    op.drop_index("ix_districts_is_active", table_name="districts")
    op.drop_index("ix_districts_city_id", table_name="districts")
    op.drop_table("districts")

    op.drop_column("cities", "display_order")
    op.drop_column("cities", "requires_district")
    op.drop_column("cities", "type")
