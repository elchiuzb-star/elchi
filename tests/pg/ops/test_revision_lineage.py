"""Q50 launch gate: an image older than the database recognises the schema (A0a/A10a, wave 5).

Decision 32 lets readiness answer ``200 degraded`` with ``migrations: ahead`` while a deploy rollback is in
progress - but only if the running image can tell that the database head *descends* from its own head. Until
wave 5 that decision was made from the image's own migration files, so an image built before the newer revision
answered ``unknown`` -> 503 (Q50 accepted that and made the lineage a launch gate).

Migration 0067 + ``alembic/env.py`` now record the graph in ``alembic_revision_lineage``; these tests use a probe
whose script directory does **not** know the database's revision - exactly what an older image sees - and prove:

* the lineage is written for the whole chain, with the same edges as the shipped script graph;
* an old image + a descendant database -> ``ahead`` (200 degraded), not 503;
* a database on a revision that does **not** descend from the code head stays ``mismatch``/``unknown`` -> 503:
  the lineage never turns an unknown schema into a healthy answer;
* the app role may read the table and may not write it.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import errors, sql
from sqlalchemy import text

from app.api import health_probes
from app.api.health_probes import (
    ReadinessProbe,
    classify_with_lineage,
    get_readiness_probe,
    read_revision_lineage,
)
from tests.pg.conftest import PgDatabase, _libpq_dsn, run_alembic, script_heads

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[3]
CLOSED_REDIS_URL = "redis://127.0.0.1:6399/0"


class _BlindScript:
    """The script directory of an image that does not ship the database's revision."""

    def __init__(self, known: set[str]) -> None:
        self._known = known

    def get_revision(self, revision: str) -> Any:
        if revision not in self._known:
            return None
        raise AssertionError("the blind script directory must only be asked about unknown revisions")


def _client(probe: ReadinessProbe) -> TestClient:
    app = FastAPI()
    app.include_router(health_probes.router)
    app.dependency_overrides[get_readiness_probe] = lambda: probe
    return TestClient(app)


def _shipped_edges() -> set[tuple[str, str | None]]:
    script = health_probes.shipped_script_directory()
    edges: set[tuple[str, str | None]] = set()
    for entry in script.walk_revisions("base", "heads"):
        parents = entry.down_revision
        if parents is None:
            edges.add((entry.revision, None))
        elif isinstance(parents, str):
            edges.add((entry.revision, parents))
        else:
            edges.update((entry.revision, parent) for parent in parents)
    return edges


def test_lineage_is_recorded_for_the_whole_chain(pg_db: PgDatabase) -> None:
    with pg_db.engine.connect() as conn:
        graph = read_revision_lineage(conn)
        rows = {
            (revision, parent)
            for revision, parent in conn.execute(
                text("SELECT revision, down_revision FROM alembic_revision_lineage")
            ).all()
        }
    assert rows == _shipped_edges()
    assert script_heads()[0] in graph


def test_old_image_reports_ahead_instead_of_503(pg_db: PgDatabase) -> None:
    """The database is on today's head; the probe pretends to be an image built one revision earlier."""
    script = health_probes.shipped_script_directory()
    head = script_heads()[0]
    parent = script.get_revision(head).down_revision
    assert isinstance(parent, str)

    probe = ReadinessProbe(
        engine_factory=lambda: pg_db.engine, redis_url=CLOSED_REDIS_URL, environment="test",
        expected_heads=lambda: (parent,), script_directory=lambda: _BlindScript({parent}),
        gate_hooks=(), cache_ttl_seconds=0,
    )
    response = _client(probe).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["migrations"] == "ahead"
    assert body["status"] == "degraded"


def test_lineage_does_not_bless_a_schema_that_is_not_a_descendant(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '20991231_9999'"))
        conn.execute(
            text("INSERT INTO alembic_revision_lineage (revision, down_revision) VALUES ('20991231_9999', NULL)")
        )
    probe = ReadinessProbe(
        engine_factory=lambda: pg_db.engine, redis_url=CLOSED_REDIS_URL, environment="test",
        expected_heads=lambda: (script_heads()[0],), script_directory=lambda: _BlindScript(set(script_heads())),
        gate_hooks=(), cache_ttl_seconds=0,
    )
    response = _client(probe).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] in {"mismatch", "unknown"}


def test_classifier_needs_the_database_to_know_its_own_head() -> None:
    # No lineage at all (older schema): the answer stays "unknown", never "ahead".
    assert classify_with_lineage(["b"], ["a"], {}) == "unknown"
    # Head not recorded: also unknown.
    assert classify_with_lineage(["b"], ["a"], {"a": set()}) == "unknown"
    # Recorded and descending: ahead.
    assert classify_with_lineage(["c"], ["a"], {"c": {"b"}, "b": {"a"}, "a": set()}) == "ahead"
    # Recorded but on another branch: mismatch.
    assert classify_with_lineage(["c"], ["a"], {"c": {"x"}, "x": set()}) == "mismatch"


def test_app_role_reads_the_lineage_but_cannot_write_it(pg_empty_db: PgDatabase) -> None:
    spec = importlib.util.spec_from_file_location("elchi_db_roles_lineage", REPO_ROOT / "scripts" / "db_roles.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    suffix = uuid.uuid4().hex[:10]
    owner, app_role, password = f"elchi_pgtest_owner_{suffix}", f"elchi_pgtest_app_{suffix}", uuid.uuid4().hex
    plan = module.RolePlan(database=pg_empty_db.name, owner=owner, owner_password=password,
                           app=app_role, app_password=password)
    admin_dsn = _libpq_dsn(pg_empty_db.url)
    try:
        module.bootstrap(admin_dsn, plan)
        owner_url = pg_empty_db.url.set(username=owner, password=password)
        assert run_alembic(owner_url, "upgrade", "head").returncode == 0
        module.bootstrap(admin_dsn, plan)

        app_url = pg_empty_db.url.set(username=app_role, password=password)
        with psycopg.connect(_libpq_dsn(app_url), autocommit=True) as conn:
            assert conn.execute("SELECT count(*) FROM alembic_revision_lineage").fetchone()[0] > 0
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("INSERT INTO alembic_revision_lineage (revision) VALUES ('forged')")
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            for role in (app_role, owner):
                conn.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role)))
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
