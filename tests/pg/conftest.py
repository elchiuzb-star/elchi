"""PostgreSQL 16 + PostGIS fixtures for stage-2 invariant tests.

Configuration
    ELCHI_TEST_PG_URL           SQLAlchemy URL of a *maintenance* database on a
                                disposable server; the user must be allowed to
                                CREATE DATABASE. Default matches docker-compose.test.yml:
                                postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_test
                                (port 45432, Q76: 55432 sat inside a Windows
                                excluded TCP range; see docker-compose.test.yml)
    ELCHI_TEST_PG_REQUIRED      "1": an unreachable server is a hard error for every
                                pg test instead of a skip. scripts/test-pg.* set it.
    ELCHI_TEST_PG_ALLOW_REMOTE  "1": allow a host other than localhost/127.0.0.1/::1.
    ELCHI_TEST_PG_KEEP          "1": keep created databases for debugging.

Safety guard (always on): the URL host must be local unless ALLOW_REMOTE=1, and
the database name must contain a "test" token (e.g. elchi_test). A URL that
fails the guard is a hard error, never a skip. Test databases are created and
dropped only with the ``elchi_pgtest_`` prefix; the URL database itself is only
used to issue CREATE/DROP DATABASE.

If the server is unreachable (and REQUIRED is not set) every test using these
fixtures is skipped with the reason; the SQLite suite in tests/ never touches
this file's fixtures.

Isolation strategy (see docs/architecture/BASELINE_TESTS.md):
    session  -> one template DB: CREATE EXTENSION postgis + `alembic upgrade head`
    per test -> CREATE DATABASE <unique> TEMPLATE <template> STRATEGY FILE_COPY
Each test owns a whole database, so tests may open any number of independent
connections and commit for real (needed for FOR UPDATE / race tests). No
wrapping transaction, no TRUNCATE lists to maintain, triggers stay intact.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_PG_URL = "postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_test"
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PREFIX = "elchi_pgtest_"

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# "test" as a separate token: elchi_test, test, test-db, elchi_pgtest_x ... but not "contest" or "elchi".
DISPOSABLE_DB_RE = re.compile(r"(^|[_\-.])(pg)?test([_\-.]|\d|$)", re.IGNORECASE)
# libpq also accepts the host in the query string (?host=...); check those too.
_HOST_QUERY_KEYS = ("host", "hostaddr")


class UnsafeTestDatabaseUrl(ValueError):
    """ELCHI_TEST_PG_URL points somewhere tests must not create/drop databases."""


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip() == "1"


def _hosts_of(url: URL) -> list[str]:
    hosts: list[str] = []
    if url.host:
        hosts.append(url.host)
    for key in _HOST_QUERY_KEYS:
        value = url.query.get(key)
        values = value if isinstance(value, tuple) else (value,) if value else ()
        for item in values:
            hosts.extend(part for part in str(item).split(",") if part)
    return [h.strip().strip("[]").lower() for h in hosts]


def validate_test_pg_url(raw: str, *, allow_remote: bool = False) -> URL:
    """Parse and vet a test server URL. Raises UnsafeTestDatabaseUrl."""
    try:
        url = make_url(raw)
    except ArgumentError as exc:
        raise UnsafeTestDatabaseUrl(f"ELCHI_TEST_PG_URL is not a valid SQLAlchemy URL: {exc}") from None
    shown = url.render_as_string(hide_password=True)
    if url.get_backend_name() != "postgresql":
        raise UnsafeTestDatabaseUrl(f"ELCHI_TEST_PG_URL must be a PostgreSQL URL, got {shown}")
    hosts = _hosts_of(url)
    if not hosts:
        raise UnsafeTestDatabaseUrl(
            f"ELCHI_TEST_PG_URL must name its host explicitly (e.g. 127.0.0.1), got {shown}"
        )
    remote = [h for h in hosts if h not in LOCAL_HOSTS]
    if remote and not allow_remote:
        raise UnsafeTestDatabaseUrl(
            f"Refusing non-local test PostgreSQL host(s) {remote} in {shown}: tests create and drop "
            "databases. Set ELCHI_TEST_PG_ALLOW_REMOTE=1 only for a disposable server."
        )
    database = url.database or ""
    if not DISPOSABLE_DB_RE.search(database):
        raise UnsafeTestDatabaseUrl(
            f"Refusing database {database!r} in {shown}: the maintenance database name must contain a "
            "'test' token (e.g. elchi_test) so a production/dev URL cannot be used by mistake."
        )
    return url.set(drivername="postgresql+psycopg")


def _libpq_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _keep() -> bool:
    return _flag(os.environ, "ELCHI_TEST_PG_KEEP")


@dataclass(frozen=True)
class PgServer:
    admin_url: URL
    server_version: str
    postgis_version: str

    def admin_connect(self) -> psycopg.Connection:
        return psycopg.connect(_libpq_dsn(self.admin_url), autocommit=True, connect_timeout=5)

    def url_for(self, database: str) -> URL:
        return self.admin_url.set(database=database)

    def create_database(self, name: str, template: str | None = None) -> None:
        _assert_owned(name)
        query = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        if template:
            _assert_owned(template)
            query = sql.SQL("CREATE DATABASE {} TEMPLATE {} STRATEGY FILE_COPY").format(
                sql.Identifier(name), sql.Identifier(template)
            )
        with self.admin_connect() as conn:
            conn.execute(query)

    def drop_database(self, name: str) -> None:
        _assert_owned(name)
        if _keep():
            return
        with self.admin_connect() as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _assert_owned(name: str) -> None:
    if not name.startswith(DB_PREFIX):
        raise UnsafeTestDatabaseUrl(f"refusing to create/drop database {name!r} without prefix {DB_PREFIX!r}")


@dataclass(frozen=True)
class PgTemplate:
    name: str
    head: str
    migrate_seconds: float
    alembic_log: str


@dataclass
class PgDatabase:
    name: str
    url: URL
    engine: Engine
    clone_seconds: float
    _sessionmaker: sessionmaker = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._sessionmaker = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def session(self) -> Session:
        return self._sessionmaker()

    @property
    def url_str(self) -> str:
        return self.url.render_as_string(hide_password=False)


def unique_db_name(kind: str) -> str:
    return f"{DB_PREFIX}{kind}_{uuid.uuid4().hex[:12]}"


def run_alembic(database_url: URL, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the real alembic CLI against ``database_url`` in a subprocess.

    A subprocess is used on purpose: app.core.config caches Settings at import
    time, so ELCHI_DATABASE_URL must be set before `app` is imported.
    """
    _assert_owned(database_url.database or "")
    env = os.environ.copy()
    env["ELCHI_DATABASE_URL"] = database_url.render_as_string(hide_password=False)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(REPO_ROOT / "alembic.ini"), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def script_heads() -> list[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return list(ScriptDirectory.from_config(config).get_heads())


@pytest.fixture(scope="session")
def pg_server() -> PgServer:
    # Session scope: pytest caches a failure/skip here, so an unreachable server
    # costs one connection attempt and every pg test reports the same message.
    try:
        url = validate_test_pg_url(
            os.environ.get("ELCHI_TEST_PG_URL", DEFAULT_PG_URL),
            allow_remote=_flag(os.environ, "ELCHI_TEST_PG_ALLOW_REMOTE"),
        )
    except UnsafeTestDatabaseUrl as exc:
        pytest.fail(f"[tests/pg safety guard] {exc}", pytrace=False)
    shown = url.render_as_string(hide_password=True)
    try:
        with psycopg.connect(_libpq_dsn(url), autocommit=True, connect_timeout=3) as conn:
            server_version = conn.execute("SHOW server_version").fetchone()[0]
            row = conn.execute(
                "SELECT default_version FROM pg_available_extensions WHERE name = 'postgis'"
            ).fetchone()
    except psycopg.OperationalError as exc:
        reason = (
            f"PostgreSQL not reachable at {shown} ({exc.__class__.__name__}: {str(exc).strip()[:200]}). "
            "Start it with scripts/test-pg.ps1 or scripts/test-pg.sh, or set ELCHI_TEST_PG_URL."
        )
        if _flag(os.environ, "ELCHI_TEST_PG_REQUIRED"):
            pytest.fail(f"[ELCHI_TEST_PG_REQUIRED=1] {reason}", pytrace=False)
        pytest.skip(reason)
    if not server_version.startswith("16."):
        pytest.fail(f"tests/pg expect PostgreSQL 16 (production major), server is {server_version}", pytrace=False)
    if row is None:
        pytest.fail(f"PostGIS extension is not available on {shown}; use the postgis/postgis image", pytrace=False)
    return PgServer(admin_url=url, server_version=server_version, postgis_version=row[0])


@pytest.fixture(scope="session")
def pg_template(pg_server: PgServer) -> Iterator[PgTemplate]:
    name = unique_db_name("tpl")
    pg_server.create_database(name)
    try:
        with psycopg.connect(_libpq_dsn(pg_server.url_for(name)), autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        started = time.perf_counter()
        result = run_alembic(pg_server.url_for(name), "upgrade", "head")
        migrate_seconds = time.perf_counter() - started
        log = result.stdout + result.stderr
        if result.returncode != 0:
            pytest.fail(f"alembic upgrade head failed on PostgreSQL {pg_server.server_version}:\n{log}")
        with psycopg.connect(_libpq_dsn(pg_server.url_for(name)), autocommit=True) as conn:
            head = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        with pg_server.admin_connect() as conn:
            # Freeze it: nobody may connect (which would also block cloning).
            conn.execute(sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS false IS_TEMPLATE true").format(sql.Identifier(name)))
        yield PgTemplate(name=name, head=head, migrate_seconds=migrate_seconds, alembic_log=log)
    finally:
        if not _keep():
            with pg_server.admin_connect() as conn:
                conn.execute(sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE false").format(sql.Identifier(name)))
        pg_server.drop_database(name)


@pytest.fixture
def pg_db(pg_server: PgServer, pg_template: PgTemplate) -> Iterator[PgDatabase]:
    """A private, fully migrated PostGIS database for one test."""
    name = unique_db_name("t")
    started = time.perf_counter()
    pg_server.create_database(name, template=pg_template.name)
    clone_seconds = time.perf_counter() - started
    # Pool sized for the concurrency harness (up to ~50 simultaneous workers).
    engine = create_engine(pg_server.url_for(name), pool_size=50, max_overflow=10, pool_timeout=30)
    try:
        yield PgDatabase(name=name, url=pg_server.url_for(name), engine=engine, clone_seconds=clone_seconds)
    finally:
        engine.dispose()
        pg_server.drop_database(name)


@pytest.fixture
def pg_empty_db(pg_server: PgServer) -> Iterator[PgDatabase]:
    """An empty database with no extension pre-installed (like a fresh prod volume)."""
    name = unique_db_name("empty")
    pg_server.create_database(name)
    engine = create_engine(pg_server.url_for(name), pool_size=5)
    try:
        yield PgDatabase(name=name, url=pg_server.url_for(name), engine=engine, clone_seconds=0.0)
    finally:
        engine.dispose()
        pg_server.drop_database(name)
