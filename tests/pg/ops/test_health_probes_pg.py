"""/health/ready against real PostgreSQL + PostGIS and the A0b test Redis (AC34, BR N1).

The router is mounted in a test-local app (wiring into app.main is the integrator's).
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import health_probes
from app.api.health_probes import ReadinessProbe, _InvariantLogLimiter, get_readiness_probe
from tests.pg.conftest import PgDatabase, run_alembic, script_heads

pytestmark = pytest.mark.pg

TEST_REDIS_URL = os.environ.get("ELCHI_TEST_REDIS_URL", "redis://127.0.0.1:36379/0")
CLOSED_REDIS_URL = "redis://127.0.0.1:1/0"  # nothing listens on port 1 locally


def _require_test_redis() -> None:
    try:
        socket.create_connection(("127.0.0.1", 36379), timeout=1).close()
    except OSError as exc:
        message = f"test Redis (docker-compose.test.yml, 127.0.0.1:36379) not reachable: {exc}"
        if os.environ.get("ELCHI_TEST_PG_REQUIRED") == "1":
            pytest.fail(message, pytrace=False)
        pytest.skip(message)


def _client(probe: ReadinessProbe) -> TestClient:
    app = FastAPI()
    app.include_router(health_probes.router)
    app.dependency_overrides[get_readiness_probe] = lambda: probe
    return TestClient(app)


def _probe(db: PgDatabase, *, redis_url: str | None = TEST_REDIS_URL, environment: str = "test", **kwargs) -> ReadinessProbe:
    # Wallet-hook semantics are tested in isolation; the real Q48 gate has its own test below.
    kwargs.setdefault("gate_hooks", ())
    return ReadinessProbe(
        engine_factory=lambda: db.engine,
        redis_url=redis_url,
        environment=environment,
        expected_heads=lambda: tuple(script_heads()),
        log_limiter=_InvariantLogLimiter(0),
        **kwargs,
    )


def test_real_q48_gate_fails_on_test_db_in_production_without_503(pg_db: PgDatabase) -> None:
    """A3's platform.service.q48_gate_status is part of production_invariants (Q56); the test DB
    (superuser test role, unconfirmed seed rate) cannot satisfy it -> fail/degraded, never 503."""
    platform = pytest.importorskip("app.modules.platform.service")
    if not hasattr(platform, "q48_gate_status"):
        pytest.skip("q48_gate_status not shipped")
    ok_hook = ("tests_fake_wallet_ok_for_gate", "assert_production_invariants")
    import sys
    import types

    nonprod_hook = ("tests_fake_wallet_nonprod_for_gate", "assert_production_invariants")
    module = types.ModuleType(ok_hook[0])
    module.assert_production_invariants = lambda session: {"ok": True, "is_production": True}  # type: ignore[attr-defined]
    nonprod = types.ModuleType(nonprod_hook[0])
    nonprod.assert_production_invariants = lambda session: {"ok": True, "is_production": False}  # type: ignore[attr-defined]
    sys.modules[ok_hook[0]] = module
    sys.modules[nonprod_hook[0]] = nonprod
    try:
        probe = _probe(pg_db, redis_url=CLOSED_REDIS_URL, environment="production", invariant_hooks=[ok_hook],
                       gate_hooks=health_probes.Q48_GATE_HOOKS)
        response = _client(probe).get("/health/ready")
        non_production = _client(_probe(pg_db, redis_url=CLOSED_REDIS_URL, environment="test", invariant_hooks=[nonprod_hook],
                                         gate_hooks=health_probes.Q48_GATE_HOOKS)).get("/health/ready")
    finally:
        sys.modules.pop(ok_hook[0], None)
        sys.modules.pop(nonprod_hook[0], None)
    assert response.status_code == 200
    assert response.json()["checks"]["production_invariants"] == "fail"
    assert response.json()["status"] == "degraded"
    body = non_production.json()
    assert body["checks"]["production_invariants"] == "not_applicable", "gate is only evaluated for production"


def _hook_module(monkeypatch: pytest.MonkeyPatch, name: str, fn: Callable[[Session], object]) -> tuple[str, str]:
    import sys
    import types

    module = types.ModuleType(name)
    module.assert_production_invariants = fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, name, module)
    return (name, "assert_production_invariants")


def test_ready_when_db_at_head_and_redis_up(pg_db: PgDatabase) -> None:
    _require_test_redis()
    response = _client(_probe(pg_db)).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "migrations": "ok", "redis": "ok", "production_invariants": "not_applicable"},
        # Q57: the migration-seeded global standard is unconfirmed on a fresh DB; informational only.
        # Wave 2.1: geo.service.readiness_notices -- no routing provider configured in tests (Q46), info only.
        "notices": ["routing_provider_disabled", "unconfirmed_seed_policy_active"],
    }
    assert response.headers["cache-control"] == "no-store"


def test_redis_down_is_degraded_not_503(pg_db: PgDatabase) -> None:
    response = _client(_probe(pg_db, redis_url=CLOSED_REDIS_URL)).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == "unavailable"
    assert body["checks"]["database"] == "ok"


def test_redis_auth_failure_is_degraded(pg_db: PgDatabase) -> None:
    _require_test_redis()
    # The test Redis has no password: AUTH is answered with an error -> not "ok".
    response = _client(_probe(pg_db, redis_url="redis://:wrong@127.0.0.1:36379/0")).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["redis"] == "unavailable"
    assert "wrong" not in response.text


def test_migrations_behind_head_is_503(pg_empty_db: PgDatabase) -> None:
    result = run_alembic(pg_empty_db.url, "upgrade", "20260803_0029")
    assert result.returncode == 0, result.stdout + result.stderr
    response = _client(_probe(pg_empty_db)).get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["migrations"] == "mismatch"


def test_missing_alembic_version_table_is_503(pg_empty_db: PgDatabase) -> None:
    response = _client(_probe(pg_empty_db)).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "unknown"


def test_production_invariant_violation_reports_fail_without_503(
    pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _require_test_redis()
    seen: dict[str, object] = {}

    def overdraft_found(session: Session) -> dict[str, object]:
        # Runs in a real DB session on the production-like schema.
        seen["tables"] = session.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")).scalar()
        return {"ok": False, "violations": ["overdraft_wallet:wal_test"]}

    hook = _hook_module(monkeypatch, "tests_fake_wallet_service_fail", overdraft_found)
    probe = _probe(pg_db, environment="production", invariant_hooks=[hook])
    with caplog.at_level(logging.ERROR, logger="elchi.health"):
        response = _client(probe).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "ok", "migrations": "ok", "redis": "ok", "production_invariants": "fail"}
    assert "overdraft_wallet" not in response.text, "violations must not leak in the public response"
    assert seen["tables"], "hook must run against the real database"
    records = [r for r in caplog.records if r.getMessage() == "production_invariants_failed"]
    assert records and records[0].levelno == logging.ERROR
    assert records[0].violations == [f"{hook[0]}:overdraft_wallet:wal_test"]


def test_production_invariants_ok_is_ready(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_test_redis()
    hook = _hook_module(monkeypatch, "tests_fake_wallet_service_ok", lambda session: {"ok": True, "violations": []})
    response = _client(_probe(pg_db, environment="production", invariant_hooks=[hook])).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["production_invariants"] == "ok"


def test_crashing_invariant_hook_is_error_not_503(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(session: Session) -> object:
        session.execute(text("SELECT * FROM table_that_does_not_exist"))
        return True

    hook = _hook_module(monkeypatch, "tests_fake_wallet_service_boom", boom)
    response = _client(_probe(pg_db, environment="production", invariant_hooks=[hook])).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["production_invariants"] == "error"
    assert response.json()["status"] == "degraded"


def test_wallet_module_not_shipped_yet_is_not_available_in_production(pg_db: PgDatabase) -> None:
    probe = _probe(pg_db, environment="production", invariant_hooks=[("app.modules.not_shipped_yet.service", "assert_production_invariants")])
    response = _client(probe).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["production_invariants"] == "not_available"


def test_hook_detecting_production_database_fails_even_when_app_env_is_not_production(
    pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = type("Report", (), {"ok": False, "is_production": True, "failed": ["environment_marker"]})()
    hook = _hook_module(monkeypatch, "tests_fake_wallet_service_prod_db", lambda session: report)
    response = _client(_probe(pg_db, redis_url=CLOSED_REDIS_URL, environment="staging", invariant_hooks=[hook])).get(
        "/health/ready"
    )
    assert response.status_code == 200
    assert response.json()["checks"]["production_invariants"] == "fail"


def test_real_a3_wallet_hook_non_production_is_not_applicable(pg_db: PgDatabase) -> None:
    """Integration with the shipped app.modules.wallet.service.assert_production_invariants."""
    pytest.importorskip("app.modules.wallet.service")
    response = _client(_probe(pg_db, redis_url=CLOSED_REDIS_URL, environment="development")).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["production_invariants"] == "not_applicable"


def test_real_a3_wallet_hook_production_db_marker_mismatch_fails_without_503(pg_db: PgDatabase) -> None:
    """DB marked production while the app is not: A3 reports environment_marker failure -> fail, still 200."""
    platform = pytest.importorskip("app.modules.platform.service")
    with pg_db.session() as session:
        platform.set_db_environment(session, "production", set_by="a10a-test", note="readiness test")
        session.commit()
    response = _client(_probe(pg_db, redis_url=CLOSED_REDIS_URL, environment="development")).get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["database"] == "ok" and body["checks"]["migrations"] == "ok"
    assert body["checks"]["production_invariants"] == "fail"
    assert body["status"] == "degraded"


def test_schema_ahead_of_code_is_degraded_not_503(pg_db: PgDatabase) -> None:
    """Decision 32: the DB head descends from the code head (expand-only) -> 200 degraded."""
    heads = script_heads()
    script = health_probes.shipped_script_directory()
    parent = script.get_revision(heads[0]).down_revision
    assert isinstance(parent, str)
    probe = ReadinessProbe(engine_factory=lambda: pg_db.engine, redis_url=CLOSED_REDIS_URL, environment="test",
                           expected_heads=lambda: (parent,), cache_ttl_seconds=0)
    response = _client(probe).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["migrations"] == "ahead"
    assert response.json()["status"] == "degraded"


def test_unknown_db_revision_is_503(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '20991231_9999'"))
    response = _client(_probe(pg_db, redis_url=CLOSED_REDIS_URL)).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "unknown"


def test_pool_timeout_is_busy_not_down(pg_db: PgDatabase) -> None:
    from sqlalchemy import create_engine

    tiny = create_engine(pg_db.url, pool_size=1, max_overflow=0, pool_timeout=0.3)
    held = tiny.connect()
    try:
        probe = ReadinessProbe(engine_factory=lambda: tiny, redis_url=CLOSED_REDIS_URL, environment="test",
                               expected_heads=lambda: tuple(script_heads()), cache_ttl_seconds=0)
        response = _client(probe).get("/health/ready")
    finally:
        held.close()
        tiny.dispose()
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["database"] == "busy"
    assert body["status"] == "degraded"


def test_concurrent_callers_share_one_run(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time as time_module

    calls = {"engine": 0, "hook": 0}
    lock = threading.Lock()

    def counting_engine():
        with lock:
            calls["engine"] += 1
        return pg_db.engine

    def slow_hook(session: Session) -> bool:
        with lock:
            calls["hook"] += 1
        time_module.sleep(0.5)
        return True

    hook = _hook_module(monkeypatch, "tests_fake_wallet_service_slow", slow_hook)
    probe = ReadinessProbe(engine_factory=counting_engine, redis_url=CLOSED_REDIS_URL, environment="production",
                           expected_heads=lambda: tuple(script_heads()), invariant_hooks=[hook], cache_ttl_seconds=5)
    client = _client(probe)
    barrier = threading.Barrier(8)
    statuses: list[int] = []

    def call() -> None:
        barrier.wait(5)
        statuses.append(client.get("/health/ready").status_code)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert statuses == [200] * 8
    assert calls == {"engine": 1, "hook": 1}, calls


def test_gates_status_runs_against_the_migrated_schema(pg_db: PgDatabase) -> None:
    """app.ops.gates SQL (enabled v2 service flags) and hook evaluation work on real PostgreSQL."""
    from app.ops import gates

    with pg_db.engine.connect() as conn:
        assert gates.enabled_v2_service_flags(conn) == []
    probe = ReadinessProbe(engine_factory=lambda: pg_db.engine, redis_url=None, environment="test",
                           expected_heads=lambda: tuple(script_heads()), cache_ttl_seconds=0)
    result = gates.status(probe=probe, engine=pg_db.engine)
    assert set(result) == {"hooks", "q48_gate", "invariant_failures_excluding_q48", "enabled_v2_service_flags"}
    wallet = result["hooks"]["app.modules.wallet.service.assert_production_invariants"]
    assert wallet["available"] is True and "error" not in wallet, wallet


def test_live_is_200_even_when_database_is_down() -> None:
    probe = ReadinessProbe(
        engine_factory=lambda: (_ for _ in ()).throw(RuntimeError("no db")),
        redis_url=None,
        environment="production",
    )
    client = _client(probe)
    assert client.get("/health/live").json() == {"status": "live"}
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"] == {
        "database": "unavailable",
        "migrations": "skipped",
        "redis": "not_configured",
        "production_invariants": "skipped",
    }
