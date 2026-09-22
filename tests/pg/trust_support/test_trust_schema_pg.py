"""A12 ORM models vs migrated schema and idempotent 0060 upgrade (PostgreSQL 16)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase, run_alembic, script_heads

pytestmark = pytest.mark.pg


def test_trust_support_models_match_migrated_schema(pg_db: PgDatabase) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.models  # noqa: F401
    import app.modules.trust_support.models  # noqa: F401
    from app.db.base import Base
    from app.modules.trust_support.models import TRUST_SUPPORT_TABLES

    def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
        if type_ == "table" and reflected and compare_to is None:
            return name in Base.metadata.tables
        return True

    with pg_db.engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": True,
                                                         "compare_server_default": False})
        diffs = compare_metadata(context, Base.metadata)

    def touches(diff: object) -> bool:
        items = diff if isinstance(diff, list) else [diff]
        for item in items:
            for part in item:
                table = getattr(part, "table", None)
                name = getattr(table, "name", None) or getattr(part, "name", None)
                if name in TRUST_SUPPORT_TABLES or part in TRUST_SUPPORT_TABLES:
                    return True
        return False

    mine = [diff for diff in diffs if touches(diff)]
    assert mine == [], "\n".join(map(repr, mine))


def test_0060_upgrade_is_idempotent(pg_db: PgDatabase) -> None:
    heads = script_heads()
    assert len(heads) == 1

    def snapshot() -> tuple:
        with pg_db.engine.connect() as conn:
            return (
                conn.execute(text("SELECT table_name, column_name, data_type FROM information_schema.columns "
                                  "WHERE table_schema = 'public' ORDER BY 1, 2")).all(),
                conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1")).all(),
                conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1")).all(),
                conn.execute(text("SELECT conname FROM pg_constraint ORDER BY 1")).all(),
            )

    before = snapshot()
    assert run_alembic(pg_db.url, "stamp", "20260916_0059").returncode == 0
    again = run_alembic(pg_db.url, "upgrade", "20260916_0060")
    assert again.returncode == 0, again.stdout + again.stderr
    assert run_alembic(pg_db.url, "stamp", heads[0]).returncode == 0
    assert snapshot() == before
