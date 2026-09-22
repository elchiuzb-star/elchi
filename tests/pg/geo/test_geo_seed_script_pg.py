"""scripts/seed_geo_fixtures.py: dev/test only, re-runnable, refuses production and a missing marker (BR #6)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import text

from tests.pg.conftest import REPO_ROOT, PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user

pytestmark = pytest.mark.pg


def run_seed(pg_db: PgDatabase, actor: int, environment: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"ELCHI_DATABASE_URL": pg_db.url_str, "ELCHI_ENVIRONMENT": environment, "ELCHI_GEO_ROUTING_PROVIDER": "disabled"})
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "seed_geo_fixtures.py"), "--actor-user-id", str(actor)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def corridors(pg_db: PgDatabase) -> int:
    with pg_db.engine.connect() as conn:
        return conn.scalar(text("SELECT count(*) FROM service_corridors"))


def test_seed_refuses_production_settings_and_is_idempotent(pg_db: PgDatabase) -> None:
    admin = create_user(pg_db, "admin")
    refused = run_seed(pg_db, admin, "production")
    assert refused.returncode == 2 and "never be seeded in production" in refused.stderr
    assert corridors(pg_db) == 0

    first = run_seed(pg_db, admin, "development")
    assert first.returncode == 0, first.stdout + first.stderr
    second = run_seed(pg_db, admin, "development")
    assert second.returncode == 0 and "already present" in second.stdout
    with pg_db.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM service_corridors")) == 1
        assert conn.scalar(text("SELECT count(*) FROM corridor_stops WHERE is_active")) == 6
        assert conn.scalar(text("SELECT count(*) FROM route_versions WHERE status = 'confirmed' AND source = 'fixture'")) == 2


def test_seed_refuses_production_marker(pg_db: PgDatabase) -> None:
    admin = create_user(pg_db, "admin")
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))
    refused = run_seed(pg_db, admin, "development")
    assert refused.returncode == 2 and "never be seeded in production" in refused.stderr
    assert corridors(pg_db) == 0


def test_seed_refuses_missing_marker(pg_db: PgDatabase) -> None:
    admin = create_user(pg_db, "admin")
    with pg_db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE platform_environment DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM platform_environment"))
        conn.execute(text("ALTER TABLE platform_environment ENABLE TRIGGER USER"))
    refused = run_seed(pg_db, admin, "development")
    # Fail closed: platform.is_production may already treat a missing marker as production (A3 0042);
    # the script also has its own explicit missing-marker check. Either way nothing is seeded.
    assert refused.returncode == 2 and ("marker is missing" in refused.stderr or "production" in refused.stderr)
    assert corridors(pg_db) == 0
