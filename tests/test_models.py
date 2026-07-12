from sqlalchemy import CheckConstraint, UniqueConstraint

import app.models
from app.db.base import Base


EXPECTED_TABLES = {
    "users",
    "client_profiles",
    "driver_profiles",
    "driver_documents",
    "cities",
    "districts",
    "driver_routes",
    "route_tariffs",
    "orders",
    "bids",
    "order_offers",
    "status_history",
    "disputes",
    "ratings",
    "notifications",
    "audit_logs",
    "otp_codes",
    "refresh_sessions",
    "system_settings",
}

BANNED_FIELDS = {
    "departure_time",
    "capacity",
    "weight",
    "size",
    "otp",
    "qr",
    "pickup_proof",
    "delivery_proof",
    "online_payment",
}


def table_columns(table_name: str) -> set[str]:
    return set(Base.metadata.tables[table_name].columns.keys())


def unique_constraint_columns(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def check_constraint_names(table_name: str) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_stage_2_tables_are_registered() -> None:
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_required_unique_constraints_exist() -> None:
    assert ("phone",) in unique_constraint_columns("users")
    assert ("user_id",) in unique_constraint_columns("client_profiles")
    assert ("user_id",) in unique_constraint_columns("driver_profiles")
    assert ("plate_number",) in unique_constraint_columns("driver_profiles")
    assert ("order_number",) in unique_constraint_columns("orders")
    assert ("order_id", "driver_id") in unique_constraint_columns("bids")
    assert ("order_id", "driver_id") in unique_constraint_columns("order_offers")
    assert ("order_id",) in unique_constraint_columns("ratings")


def test_required_check_constraints_exist() -> None:
    assert "ck_orders_distinct_cities" in check_constraint_names("orders")
    assert "ck_ratings_rating_range" in check_constraint_names("ratings")


def test_banned_mvp_fields_are_not_present() -> None:
    all_columns = {
        column_name
        for table in Base.metadata.tables.values()
        for column_name in table.columns.keys()
    }

    assert BANNED_FIELDS.isdisjoint(all_columns)
