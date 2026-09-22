"""Safety guards and skip/fail policy of tests/pg (no PostgreSQL server needed).

Deliberately NOT marked ``pg``: these run in the normal suite so the guards are
enforced even on machines without Docker.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.pg.conftest import DEFAULT_PG_URL, REPO_ROOT, UnsafeTestDatabaseUrl, validate_test_pg_url


@pytest.mark.parametrize(
    "url",
    [
        DEFAULT_PG_URL,
        "postgresql+psycopg://u:p@localhost:5432/elchi_test",
        "postgresql://u:p@[::1]:55432/test",
        "postgresql+psycopg://u:p@LOCALHOST/elchi-test-2",
        "postgresql+psycopg://u:p@127.0.0.1/pgtest",
    ],
)
def test_local_disposable_urls_are_accepted(url: str) -> None:
    parsed = validate_test_pg_url(url)
    assert parsed.drivername == "postgresql+psycopg"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@10.0.0.5:5432/elchi_test",
        "postgresql+psycopg://u:p@db:5432/elchi_test",
        "postgresql+psycopg://u:p@api.elchigo.uz/elchi_test",
        "postgresql+psycopg://u:p@127.0.0.1.nip.io/elchi_test",
        # libpq honours ?host= over the URL authority
        "postgresql+psycopg://u:p@127.0.0.1/elchi_test?host=prod-db.internal",
        "postgresql+psycopg://u:p@localhost/elchi_test?hostaddr=192.168.1.10",
    ],
)
def test_remote_host_is_refused_without_explicit_opt_in(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseUrl, match="non-local"):
        validate_test_pg_url(url)
    assert validate_test_pg_url(url, allow_remote=True).database == "elchi_test"


def test_missing_host_is_refused() -> None:
    with pytest.raises(UnsafeTestDatabaseUrl, match="host explicitly"):
        validate_test_pg_url("postgresql+psycopg://u:p@/elchi_test")


@pytest.mark.parametrize("database", ["postgres", "elchi", "template1", "contest", "latest", "elchi_prod", ""])
def test_non_disposable_database_name_is_refused(database: str) -> None:
    with pytest.raises(UnsafeTestDatabaseUrl, match="'test' token"):
        validate_test_pg_url(f"postgresql+psycopg://u:p@127.0.0.1:55432/{database}")
    # allow_remote does not relax the name rule
    with pytest.raises(UnsafeTestDatabaseUrl, match="'test' token"):
        validate_test_pg_url(f"postgresql+psycopg://u:p@127.0.0.1:55432/{database}", allow_remote=True)


@pytest.mark.parametrize("url", ["sqlite:///elchi_test.db", "mysql://u:p@127.0.0.1/elchi_test", "not a url"])
def test_non_postgres_urls_are_refused(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseUrl):
        validate_test_pg_url(url)


# --- end-to-end policy: run a real pg test file in a child pytest -------------

UNREACHABLE_LOCAL = "postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:1/elchi_test"
PG_TEST_FILE = "tests/pg/test_postgis_smoke.py"  # 6 pg tests


def _child_pytest(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELCHI_TEST_PG_")}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", PG_TEST_FILE, "-m", "pg", "-p", "no:cacheprovider", "-o", "addopts=", "-q", "-rsE"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_unreachable_server_skips_by_default() -> None:
    result = _child_pytest({"ELCHI_TEST_PG_URL": UNREACHABLE_LOCAL})
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "6 skipped" in out and "PostgreSQL not reachable" in out, out


def test_unreachable_server_is_hard_error_when_required() -> None:
    result = _child_pytest({"ELCHI_TEST_PG_URL": UNREACHABLE_LOCAL, "ELCHI_TEST_PG_REQUIRED": "1"})
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "6 error" in out and "skipped" not in out, out
    assert "[ELCHI_TEST_PG_REQUIRED=1] PostgreSQL not reachable" in out, out


def test_guard_violation_is_hard_error_even_when_not_required() -> None:
    result = _child_pytest({"ELCHI_TEST_PG_URL": "postgresql+psycopg://u:p@10.255.255.1:5432/elchi_test"})
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "6 error" in out and "[tests/pg safety guard]" in out, out
