"""Alembic on real PostgreSQL 16 (the SQLite suite never runs migrations).

Downgrade is intentionally not tested: it is not a rollback strategy (spec 18.3).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.pg.conftest import PgDatabase, PgServer, PgTemplate, run_alembic, script_heads

pytestmark = pytest.mark.pg


def test_upgrade_head_from_empty_matches_single_script_head(pg_template: PgTemplate, pg_db: PgDatabase) -> None:
    heads = script_heads()
    assert len(heads) == 1, f"expected a single alembic head, got {heads}"
    assert pg_template.head == heads[0]
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == heads[0]


def test_upgrade_head_on_fresh_database_without_preinstalled_extensions(pg_empty_db: PgDatabase) -> None:
    """A brand-new database (no CREATE EXTENSION beforehand) migrates to the script head.

    Deliberately does NOT assert whether PostGIS ends up installed: migration
    0030 (A10a, ADR-0013) is expected to add it. This must stay green both
    before and after that migration lands.
    """
    result = run_alembic(pg_empty_db.url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    with pg_empty_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == script_heads()[0]


def test_template_is_at_head_and_has_postgis(pg_template: PgTemplate, pg_db: PgDatabase, pg_server: PgServer) -> None:
    assert pg_template.head == script_heads()[0]
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == script_heads()[0]
        installed = conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'"))
        assert installed == pg_server.postgis_version
        assert conn.scalar(text("SELECT ST_SRID(ST_SetSRID(ST_MakePoint(69.24, 41.30), 4326))")) == 4326


def test_alembic_current_reports_head_on_clone(pg_db: PgDatabase) -> None:
    result = run_alembic(pg_db.url, "current")
    assert result.returncode == 0, result.stderr
    assert f"{script_heads()[0]} (head)" in result.stdout


def test_audit_log_immutability_trigger_exists_on_postgres(pg_db: PgDatabase) -> None:
    """Migration 0024 is a no-op on SQLite, so only this suite exercises it."""
    with pg_db.engine.begin() as conn:
        log_id = conn.scalar(
            text("INSERT INTO audit_logs (entity_type, action) VALUES ('probe', 'created') RETURNING id")
        )
    for statement in (
        "UPDATE audit_logs SET action = 'tampered' WHERE id = :id",
        "DELETE FROM audit_logs WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(statement), {"id": log_id})
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT action FROM audit_logs WHERE id = :id"), {"id": log_id}) == "created"


def test_orm_metadata_matches_migrated_schema(pg_db: PgDatabase) -> None:
    """Drift between app.models and the migrated schema (informational gate)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.models  # noqa: F401
    from app.db.base import Base

    def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
        # PostGIS-owned tables are not part of the app schema.
        if type_ == "table" and reflected and compare_to is None:
            return name in Base.metadata.tables
        return True

    diffs = _compare_with_postgis_types(pg_db, Base.metadata, include_object)
    assert diffs == [], "\n".join(map(repr, diffs))


def _compare_with_postgis_types(pg_db: PgDatabase, metadata, include_object) -> list:  # noqa: ANN001
    """compare_metadata that also compares PostGIS columns.

    Without geoalchemy2 (not a dependency) SQLAlchemy reflects ``geometry``/``geography`` as NullType
    and alembic silently skips them. Register a placeholder reflected type and compare the column's
    real ``format_type()`` (e.g. ``geometry(Point,4326)``) with the DDL the model compiles to.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy.types import UserDefinedType

    class _ReflectedPostgis(UserDefinedType):
        cache_ok = True

        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003 - reflection passes typmod args
            super().__init__()

        def get_col_spec(self, **_kw) -> str:  # noqa: ANN003
            return "postgis"

    def normalize(spec: str) -> str:
        return spec.replace(" ", "").replace('"', "").lower()

    with pg_db.engine.connect() as conn:
        actual = {
            (table, column): normalize(spec)
            for table, column, spec in conn.execute(
                text(
                    "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_type t ON t.oid = a.atttypid "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped "
                    "AND t.typname IN ('geometry', 'geography')"
                )
            )
        }

        def compare_type(_ctx, inspected_column, metadata_column, inspected_type, metadata_type):  # noqa: ANN001, ANN202
            key = (metadata_column.table.name, metadata_column.name)
            expected = normalize(metadata_type.compile(dialect=conn.dialect))
            if key in actual or expected.startswith(("geometry", "geography")):
                return actual.get(key) != expected  # True -> reported as modify_type
            return None  # default comparison for everything else

        ischema_names = conn.dialect.ischema_names
        saved = {name: ischema_names.get(name) for name in ("geometry", "geography")}
        ischema_names.update({"geometry": _ReflectedPostgis, "geography": _ReflectedPostgis})
        try:
            context = MigrationContext.configure(
                conn,
                opts={"include_object": include_object, "compare_type": compare_type, "compare_server_default": False},
            )
            return compare_metadata(context, metadata)
        finally:
            for name, value in saved.items():
                if value is None:
                    ischema_names.pop(name, None)
                else:
                    ischema_names[name] = value


def test_geometry_drift_is_detected(pg_db: PgDatabase) -> None:
    """Self-check for the comparison above: a wrong geometry subtype/SRID must be reported."""
    from sqlalchemy import Column, Integer, MetaData, Table

    from app.modules.geo.models import Geometry

    with pg_db.engine.begin() as conn:
        conn.execute(text("CREATE TABLE drift_probe (id integer PRIMARY KEY, pt geometry(Point,4326))"))
    try:
        matching = MetaData()
        Table("drift_probe", matching, Column("id", Integer, primary_key=True, autoincrement=False), Column("pt", Geometry("Point")))
        only_probe = lambda obj, name, type_, reflected, compare_to: type_ != "table" or name == "drift_probe"  # noqa: E731
        assert _compare_with_postgis_types(pg_db, matching, only_probe) == []

        drifted = MetaData()
        Table(
            "drift_probe", drifted, Column("id", Integer, primary_key=True, autoincrement=False),
            Column("pt", Geometry("LineString", srid=3857)),
        )
        diffs = _compare_with_postgis_types(pg_db, drifted, only_probe)
        assert any("modify_type" in repr(diff) and "pt" in repr(diff) for diff in diffs), diffs
    finally:
        with pg_db.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS drift_probe"))
