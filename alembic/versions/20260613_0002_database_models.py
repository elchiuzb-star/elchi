"""database models

Revision ID: 20260613_0002
Revises: 20260613_0001
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260613_0002"
down_revision: str | None = "20260613_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_phone_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
    )
    op.create_index(op.f("ix_users_phone"), "users", ["phone"], unique=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_cities_name"), "cities", ["name"], unique=False)

    op.create_table(
        "client_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "driver_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("car_model", sa.String(length=255), nullable=True),
        sa.Column("plate_number", sa.String(length=32), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("rating_avg", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plate_number"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "driver_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["driver_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_driver_documents_driver_id"), "driver_documents", ["driver_id"], unique=False)

    op.create_table(
        "driver_routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("from_city_id", sa.Integer(), nullable=False),
        sa.Column("to_city_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("from_city_id <> to_city_id", name="ck_driver_routes_distinct_cities"),
        sa.ForeignKeyConstraint(["driver_id"], ["driver_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["to_city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_driver_routes_driver_id"), "driver_routes", ["driver_id"], unique=False)
    op.create_index(op.f("ix_driver_routes_from_city_id"), "driver_routes", ["from_city_id"], unique=False)
    op.create_index(op.f("ix_driver_routes_to_city_id"), "driver_routes", ["to_city_id"], unique=False)

    op.create_table(
        "route_tariffs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_city_id", sa.Integer(), nullable=False),
        sa.Column("to_city_id", sa.Integer(), nullable=False),
        sa.Column("suggested_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("from_city_id <> to_city_id", name="ck_route_tariffs_distinct_cities"),
        sa.CheckConstraint("suggested_price >= 0", name="ck_route_tariffs_suggested_price_nonnegative"),
        sa.ForeignKeyConstraint(["from_city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["to_city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_city_id", "to_city_id", name="uq_route_tariffs_route"),
    )
    op.create_index(op.f("ix_route_tariffs_from_city_id"), "route_tariffs", ["from_city_id"], unique=False)
    op.create_index(op.f("ix_route_tariffs_to_city_id"), "route_tariffs", ["to_city_id"], unique=False)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("from_city_id", sa.Integer(), nullable=False),
        sa.Column("to_city_id", sa.Integer(), nullable=False),
        sa.Column("pickup_address", sa.String(length=1024), nullable=False),
        sa.Column("dropoff_address", sa.String(length=1024), nullable=False),
        sa.Column("sender_phone", sa.String(length=32), nullable=False),
        sa.Column("receiver_phone", sa.String(length=32), nullable=False),
        sa.Column("cargo_photo_url", sa.String(length=1024), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("suggested_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("final_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("payment_status", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_driver_id", sa.Integer(), nullable=True),
        sa.Column("accepted_bid_id", sa.Integer(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("from_city_id <> to_city_id", name="ck_orders_distinct_cities"),
        sa.ForeignKeyConstraint(["assigned_driver_id"], ["driver_profiles.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["from_city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["to_city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
    )
    op.create_index(op.f("ix_orders_assigned_driver_id"), "orders", ["assigned_driver_id"], unique=False)
    op.create_index(op.f("ix_orders_client_id"), "orders", ["client_id"], unique=False)
    op.create_index(op.f("ix_orders_from_city_id"), "orders", ["from_city_id"], unique=False)
    op.create_index(op.f("ix_orders_order_number"), "orders", ["order_number"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)
    op.create_index(op.f("ix_orders_to_city_id"), "orders", ["to_city_id"], unique=False)

    op.create_table(
        "bids",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("price > 0", name="ck_bids_price_positive"),
        sa.ForeignKeyConstraint(["driver_id"], ["driver_profiles.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "driver_id", name="uq_bids_order_driver"),
    )
    op.create_index(op.f("ix_bids_driver_id"), "bids", ["driver_id"], unique=False)
    op.create_index(op.f("ix_bids_order_id"), "bids", ["order_id"], unique=False)
    op.create_foreign_key("fk_orders_accepted_bid_id_bids", "orders", "bids", ["accepted_bid_id"], ["id"])

    op.create_table(
        "order_offers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["driver_profiles.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "driver_id", name="uq_order_offers_order_driver"),
    )
    op.create_index(op.f("ix_order_offers_driver_id"), "order_offers", ["driver_id"], unique=False)
    op.create_index(op.f("ix_order_offers_order_id"), "order_offers", ["order_id"], unique=False)

    op.create_table(
        "status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_status_history_changed_by_user_id"), "status_history", ["changed_by_user_id"], unique=False)
    op.create_index(op.f("ix_status_history_order_id"), "status_history", ["order_id"], unique=False)

    op.create_table(
        "disputes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("opened_by_user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("previous_order_status", sa.String(length=32), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_disputes_opened_by_user_id"), "disputes", ["opened_by_user_id"], unique=False)
    op.create_index(op.f("ix_disputes_order_id"), "disputes", ["order_id"], unique=False)

    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_ratings_rating_range"),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["driver_id"], ["driver_profiles.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index(op.f("ix_ratings_client_id"), "ratings", ["client_id"], unique=False)
    op.create_index(op.f("ix_ratings_driver_id"), "ratings", ["driver_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_entity_id"), "audit_logs", ["entity_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_entity_type"), "audit_logs", ["entity_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_entity_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_entity_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_ratings_driver_id"), table_name="ratings")
    op.drop_index(op.f("ix_ratings_client_id"), table_name="ratings")
    op.drop_table("ratings")
    op.drop_index(op.f("ix_disputes_order_id"), table_name="disputes")
    op.drop_index(op.f("ix_disputes_opened_by_user_id"), table_name="disputes")
    op.drop_table("disputes")
    op.drop_index(op.f("ix_status_history_order_id"), table_name="status_history")
    op.drop_index(op.f("ix_status_history_changed_by_user_id"), table_name="status_history")
    op.drop_table("status_history")
    op.drop_index(op.f("ix_order_offers_order_id"), table_name="order_offers")
    op.drop_index(op.f("ix_order_offers_driver_id"), table_name="order_offers")
    op.drop_table("order_offers")
    op.drop_constraint("fk_orders_accepted_bid_id_bids", "orders", type_="foreignkey")
    op.drop_index(op.f("ix_bids_order_id"), table_name="bids")
    op.drop_index(op.f("ix_bids_driver_id"), table_name="bids")
    op.drop_table("bids")
    op.drop_index(op.f("ix_orders_to_city_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_order_number"), table_name="orders")
    op.drop_index(op.f("ix_orders_from_city_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_client_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_assigned_driver_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_route_tariffs_to_city_id"), table_name="route_tariffs")
    op.drop_index(op.f("ix_route_tariffs_from_city_id"), table_name="route_tariffs")
    op.drop_table("route_tariffs")
    op.drop_index(op.f("ix_driver_routes_to_city_id"), table_name="driver_routes")
    op.drop_index(op.f("ix_driver_routes_from_city_id"), table_name="driver_routes")
    op.drop_index(op.f("ix_driver_routes_driver_id"), table_name="driver_routes")
    op.drop_table("driver_routes")
    op.drop_index(op.f("ix_driver_documents_driver_id"), table_name="driver_documents")
    op.drop_table("driver_documents")
    op.drop_table("driver_profiles")
    op.drop_table("client_profiles")
    op.drop_index(op.f("ix_cities_name"), table_name="cities")
    op.drop_table("cities")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_phone"), table_name="users")
    op.drop_table("users")
