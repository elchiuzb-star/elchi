"""Migration 20260913_0030 (postgis, btree_gist) on real PostgreSQL 16 + PostGIS (ADR-0013, ADR-0016).

Targets the 0030 revision explicitly, so the result does not depend on other
owners' in-progress migrations; the head-twice test covers the whole chain.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase, run_alembic, script_heads

pytestmark = pytest.mark.pg

BEFORE = "20260803_0029"
REVISION = "20260913_0030"
EXTENSIONS = ("postgis", "btree_gist")


def _extensions(db: PgDatabase) -> dict[str, tuple[int, str]]:
    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT extname, oid, extversion FROM pg_extension WHERE extname = ANY(:names)"),
            {"names": list(EXTENSIONS)},
        )
        return {name: (int(oid), version) for name, oid, version in rows}


def _version(db: PgDatabase) -> list[str]:
    with db.engine.connect() as conn:
        return sorted(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())


def _upgrade(db: PgDatabase, target: str) -> str:
    result = run_alembic(db.url, "upgrade", target)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    return output


def test_0030_installs_extensions_on_fresh_database_and_repeat_is_noop(pg_empty_db: PgDatabase) -> None:
    _upgrade(pg_empty_db, BEFORE)
    assert _extensions(pg_empty_db) == {}, "a fresh database must not have the extensions before 0030"

    first = _upgrade(pg_empty_db, REVISION)
    assert f"{BEFORE} -> {REVISION}" in first
    installed = _extensions(pg_empty_db)
    assert set(installed) == set(EXTENSIONS)
    assert _version(pg_empty_db) == [REVISION]

    second = _upgrade(pg_empty_db, REVISION)
    assert "Running upgrade" not in second, second
    assert _extensions(pg_empty_db) == installed, "second upgrade must not recreate extensions"
    assert _version(pg_empty_db) == [REVISION]


def test_0030_is_safe_when_extensions_already_exist(pg_empty_db: PgDatabase) -> None:
    """The pg_template fixture (and a restored post-0030 dump) pre-creates postgis."""
    with pg_empty_db.engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION postgis"))
    before = _extensions(pg_empty_db)
    _upgrade(pg_empty_db, REVISION)
    after = _extensions(pg_empty_db)
    assert after["postgis"] == before["postgis"]
    assert "btree_gist" in after


def test_btree_gist_and_postgis_are_usable_after_0030(pg_empty_db: PgDatabase) -> None:
    _upgrade(pg_empty_db, REVISION)
    with pg_empty_db.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE overlap_probe (vehicle_id bigint, during tstzrange,"
                " EXCLUDE USING gist (vehicle_id WITH =, during WITH &&))"
            )
        )
        conn.execute(text("INSERT INTO overlap_probe VALUES (1, tstzrange('2026-09-13 08:00Z', '2026-09-13 10:00Z'))"))
        conn.execute(text("INSERT INTO overlap_probe VALUES (2, tstzrange('2026-09-13 08:00Z', '2026-09-13 10:00Z'))"))
        assert conn.scalar(
            text(
                "SELECT ST_DWithin(ST_SetSRID(ST_MakePoint(69.2401, 41.2995), 4326)::geography,"
                " ST_SetSRID(ST_MakePoint(69.2401, 41.3085), 4326)::geography, 1500)"
            )
        ) is True
    with pytest.raises(Exception, match="exclusion constraint"):
        with pg_empty_db.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TEMP TABLE overlap_probe2 (vehicle_id bigint, during tstzrange,"
                    " EXCLUDE USING gist (vehicle_id WITH =, during WITH &&))"
                )
            )
            conn.execute(text("INSERT INTO overlap_probe2 VALUES (1, tstzrange('2026-09-13 08:00Z', '2026-09-13 10:00Z'))"))
            conn.execute(text("INSERT INTO overlap_probe2 VALUES (1, tstzrange('2026-09-13 09:00Z', '2026-09-13 11:00Z'))"))


def test_upgrade_head_twice_is_noop_and_single_head(pg_empty_db: PgDatabase) -> None:
    heads = script_heads()
    assert len(heads) == 1, heads
    _upgrade(pg_empty_db, "head")
    assert _version(pg_empty_db) == heads
    installed = _extensions(pg_empty_db)
    second = _upgrade(pg_empty_db, "head")
    assert "Running upgrade" not in second, second
    assert _version(pg_empty_db) == heads
    assert _extensions(pg_empty_db) == installed
