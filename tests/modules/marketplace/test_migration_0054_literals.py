"""Migration 0054 freezes the Q68 enum values; they must equal the contract enums (a contract change needs a migration)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.contracts.db_errors import CONSTRAINT_RULES
from app.contracts.enums import AMENITY_VALUES, PARCEL_TYPE_VALUES
from app.contracts.errors import ErrorCode

MIGRATION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260915_0054_marketplace_trips_hardening.py"


def _migration():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("migration_0054", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_0054_enum_literals_equal_contract() -> None:
    module = _migration()
    assert set(module.PARCEL_TYPES) == PARCEL_TYPE_VALUES and len(module.PARCEL_TYPES) == len(PARCEL_TYPE_VALUES)
    assert set(module.AMENITIES) == AMENITY_VALUES and len(module.AMENITIES) == len(AMENITY_VALUES)


def test_0054_stops_locked_rule_is_a_contract_constraint_name() -> None:
    module = _migration()
    assert module.STOPS_LOCKED_RULE in CONSTRAINT_RULES
    assert CONSTRAINT_RULES[module.STOPS_LOCKED_RULE].code is ErrorCode.TRIP_STOPS_LOCKED
    assert (module.revision, module.down_revision) == ("20260915_0054", "20260915_0053")
