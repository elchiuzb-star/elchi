"""Q72 (wave 2.1): the 0057 migration's frozen constants match the contracts; marker helper is a no-op off PG."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.contracts.db_errors import CONSTRAINT_RULES
from app.contracts.enums import FLAG_CHANGE_SOURCE_ADMIN_API, FLAG_CHANGE_SOURCE_SETTING, V2_SERVICE_FLAGS
from app.modules.geo import service

MIGRATION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260915_0057_geo_flag_enable_source_guard.py"


def _migration():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("a2_migration_0057", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_constants_match_contracts() -> None:
    module = _migration()
    assert set(module.V2_SERVICE_FLAGS) == {flag.value for flag in V2_SERVICE_FLAGS}
    assert module.FLAG_CHANGE_SOURCE_SETTING == FLAG_CHANGE_SOURCE_SETTING
    assert module.FLAG_CHANGE_SOURCE_ADMIN_API == FLAG_CHANGE_SOURCE_ADMIN_API
    assert module.CONSTRAINT_NAME in CONSTRAINT_RULES
    assert set(service.V2_SERVICE_FLAGS) == set(V2_SERVICE_FLAGS)


def test_migration_never_writes_flag_rows() -> None:
    source = MIGRATION.read_text(encoding="utf-8").upper()
    assert "INSERT INTO FEATURE_FLAG_VALUES" not in source and "UPDATE FEATURE_FLAG_VALUES" not in source


def test_mark_flag_change_source_is_noop_outside_postgresql() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        service.mark_flag_change_source(session)
    with engine.connect() as conn:
        service.mark_flag_change_source(conn)
