"""Geo ORM models vs. migrated schema (same gate as tests/pg/test_migrations_smoke.py, geo models imported).

The shared drift test only imports ``app.models``; when geo models are loaded in the
same process (full suite) they join ``Base.metadata``. This test makes that state
deterministic and also proves the geo migrations are idempotent.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase, run_alembic, script_heads

pytestmark = pytest.mark.pg


def test_geo_models_match_migrated_schema(pg_db: PgDatabase) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.models  # noqa: F401
    import app.modules.geo.models  # noqa: F401
    from app.db.base import Base
    from app.modules.geo.models import GEO_TABLES

    for table in GEO_TABLES:
        assert table in Base.metadata.tables

    def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
        if type_ == "table" and reflected and compare_to is None:
            return name in Base.metadata.tables
        return True

    with pg_db.engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_object": include_object, "compare_type": True, "compare_server_default": False}
        )
        diffs = compare_metadata(context, Base.metadata)

    def touches_geo(diff: object) -> bool:
        items = diff if isinstance(diff, list) else [diff]
        for item in items:
            for part in item:
                table = getattr(part, "table", None)
                name = getattr(table, "name", None) or getattr(part, "name", None)
                if name in GEO_TABLES or part in GEO_TABLES:
                    return True
        return False

    # Only geo tables are A2's responsibility; other modules' drift is reported by their own gates.
    geo_diffs = [diff for diff in diffs if touches_geo(diff)]
    assert geo_diffs == [], "\n".join(map(repr, geo_diffs))


def test_second_upgrade_head_is_noop_and_single_head(pg_db: PgDatabase) -> None:
    heads = script_heads()
    assert len(heads) == 1, heads

    def snapshot() -> tuple:
        with pg_db.engine.connect() as conn:
            return (
                conn.execute(
                    text(
                        "SELECT table_name, column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' ORDER BY 1, 2"
                    )
                ).all(),
                conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1")).all(),
                conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1")).all(),
                conn.execute(text("SELECT conname FROM pg_constraint ORDER BY 1")).all(),
                conn.scalar(text("SELECT count(*) FROM legacy_city_mappings")),
            )

    before = snapshot()
    result = run_alembic(pg_db.url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot() == before
    # Re-running the geo upgrade bodies directly must also be harmless (IF NOT EXISTS / OR REPLACE).
    stamp = run_alembic(pg_db.url, "stamp", "20260913_0032")
    assert stamp.returncode == 0, stamp.stdout + stamp.stderr
    again = run_alembic(pg_db.url, "upgrade", "20260913_0035")
    assert again.returncode == 0, again.stdout + again.stderr
    stamp = run_alembic(pg_db.url, "stamp", "20260914_0042")
    assert stamp.returncode == 0, stamp.stdout + stamp.stderr
    again = run_alembic(pg_db.url, "upgrade", "20260914_0043")
    assert again.returncode == 0, again.stdout + again.stderr
    stamp = run_alembic(pg_db.url, "stamp", "20260914_0045")
    assert stamp.returncode == 0, stamp.stdout + stamp.stderr
    again = run_alembic(pg_db.url, "upgrade", "20260914_0046")
    assert again.returncode == 0, again.stdout + again.stderr
    restore = run_alembic(pg_db.url, "stamp", heads[0])
    assert restore.returncode == 0, restore.stdout + restore.stderr
    assert snapshot() == before
