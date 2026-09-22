from collections import defaultdict
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

import app.models
from app.db.base import Base

# Legacy v1 tables: this set stays strict (spec §18.1 — nothing is dropped or silently added
# to app.models).
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

DATA_MODEL = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "DATA_MODEL.md"


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


def _tables_by_owner() -> tuple[set[str], dict[str, set[str]]]:
    """Legacy tables (mapped in app.models) and v2 tables per module (mapped in app.modules.<m>).

    Derived from the ORM registry, so a wave adding v2 tables does not need to edit this test;
    documentation is enforced separately against DATA_MODEL.md.
    """
    from app.modules import import_models

    import_models()
    legacy: set[str] = set()
    v2: dict[str, set[str]] = defaultdict(set)
    for mapper in Base.registry.mappers:
        module = mapper.class_.__module__
        names = {table.name for table in mapper.tables}
        if module.startswith("app.models"):
            legacy |= names
        elif module.startswith("app.modules."):
            v2[module.split(".")[2]] |= names
    return legacy, v2


def test_stage_2_tables_are_registered() -> None:
    legacy, v2 = _tables_by_owner()
    registered = set(Base.metadata.tables.keys())
    all_v2 = set().union(*v2.values())
    # Legacy stays exactly the v1 schema.
    assert legacy == EXPECTED_TABLES
    assert EXPECTED_TABLES <= registered
    # Every other registered table belongs to a v2 module model; no name collisions.
    assert registered - EXPECTED_TABLES == all_v2
    assert EXPECTED_TABLES.isdisjoint(all_v2)


def test_wired_v2_module_tables_are_registered() -> None:
    from app.modules import WIRED_MODEL_MODULES

    _, v2 = _tables_by_owner()
    for module_path in WIRED_MODEL_MODULES:
        module = module_path.split(".")[2]
        assert v2.get(module), f"no tables registered for wired module {module}"


def test_v2_tables_are_documented_in_data_model() -> None:
    _, v2 = _tables_by_owner()
    text = DATA_MODEL.read_text(encoding="utf-8")
    undocumented = sorted(name for names in v2.values() for name in names if f"`{name}`" not in text)
    assert undocumented == [], f"add to docs/architecture/DATA_MODEL.md: {undocumented}"


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
