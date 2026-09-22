"""BR L4: read-only preview of migration 0054's Q68 cleanup (scripts/q68_cleanup_impact.py)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("elchi_q68_cleanup_impact", REPO_ROOT / "scripts" / "q68_cleanup_impact.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


q68 = _load()


def test_values_come_from_the_migration_and_match_contracts() -> None:
    from app.contracts.enums import AMENITY_VALUES, PARCEL_TYPE_VALUES

    parcel_types, amenities = q68.frozen_values()
    assert "other" in parcel_types
    assert set(parcel_types) == set(PARCEL_TYPE_VALUES) and set(amenities) == set(AMENITY_VALUES)


def test_unsafe_literal_is_refused() -> None:
    with pytest.raises(ValueError):
        q68.impact_sql(["box", "x'); DROP TABLE users; --"], ["wifi"])


def test_print_sql_is_a_read_only_transaction() -> None:
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "q68_cleanup_impact.py"), "--print-sql"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("BEGIN READ ONLY; SELECT format(") and result.stdout.rstrip().endswith("COMMIT;")
    for verb in ("UPDATE ", "INSERT ", "DELETE ", "ALTER "):
        assert verb not in result.stdout.upper().replace("UPDATE-", "")


@pytest.mark.pg
def test_counts_match_the_cleanup_rules(pg_db: PgDatabase) -> None:
    sql = q68.impact_sql(*q68.frozen_values())
    with pg_db.engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA q68probe"))
        conn.execute(text("SET LOCAL search_path = q68probe"))
        conn.execute(text("CREATE TABLE parcel_listing_details (parcel_type text, accepted_parcel_types text[] NOT NULL)"))
        conn.execute(text("CREATE TABLE passenger_listing_details (amenities text[] NOT NULL)"))
        conn.execute(text(
            "INSERT INTO parcel_listing_details VALUES "
            "('box', ARRAY['box']),"                     # clean: untouched
            "(NULL, ARRAY['documents','bag']),"          # clean
            "(' Box ', ARRAY['box']),"                   # normalised, not 'other'
            "('fridge', ARRAY['box']),"                  # parcel_type -> other
            "('box', ARRAY['Bag','furniture','piano'])"  # 1 normalised + 2 elements -> other
        ))
        conn.execute(text(
            "INSERT INTO passenger_listing_details VALUES "
            "(ARRAY['wifi']),"
            "(ARRAY[]::text[]),"
            "(ARRAY['konditsioner','wifi']),"           # 1 dropped
            "(ARRAY['WiFi','music','massage'])"         # 'WiFi' kept (normalised), 2 dropped
        ))
        assert conn.execute(text(sql)).scalar_one() == (
            "parcel_rows=3 parcel_type_to_other=1 accepted_elements_to_other=2 amenity_rows=2 dropped_amenity_elements=3"
        )
