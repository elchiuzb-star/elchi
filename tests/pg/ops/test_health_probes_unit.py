"""Probe logic that needs neither Docker nor a database (runs in the plain suite)."""

from __future__ import annotations

import socket
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api import health_probes
from app.api.health_probes import ReadinessProbe, _InvariantLogLimiter, _normalise_invariant_result, get_readiness_probe, redis_ping


def _client(probe: ReadinessProbe) -> TestClient:
    app = FastAPI()
    app.include_router(health_probes.router)
    app.dependency_overrides[get_readiness_probe] = lambda: probe
    return TestClient(app)


class _FakeRedis:
    """One-connection RESP server: records commands, answers AUTH/PING."""

    def __init__(self, password: str | None) -> None:
        self.password = password
        self.commands: list[list[bytes]] = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.sock.accept()
        with conn:
            stream = conn.makefile("rb")
            authed = self.password is None
            while True:
                header = stream.readline()
                if not header:
                    return
                parts = []
                for _ in range(int(header[1:])):
                    size = int(stream.readline()[1:])
                    parts.append(stream.read(size + 2)[:-2])
                self.commands.append(parts)
                if parts[0] == b"AUTH":
                    authed = parts[-1].decode() == self.password
                    conn.sendall(b"+OK\r\n" if authed else b"-WRONGPASS invalid password\r\n")
                elif parts[0] == b"PING":
                    conn.sendall(b"+PONG\r\n" if authed else b"-NOAUTH Authentication required.\r\n")

    def close(self) -> None:
        self.sock.close()


def test_redis_ping_sends_auth_then_ping() -> None:
    server = _FakeRedis(password="s3cr:et/")
    try:
        assert redis_ping(f"redis://:s3cr%3Aet%2F@127.0.0.1:{server.port}/0") is True
        server.thread.join(timeout=2)
        assert server.commands == [[b"AUTH", b"s3cr:et/"], [b"PING"]]
    finally:
        server.close()


def test_redis_ping_wrong_password_is_false() -> None:
    server = _FakeRedis(password="right")
    try:
        assert redis_ping(f"redis://:wrong@127.0.0.1:{server.port}/0") is False
    finally:
        server.close()


@pytest.mark.parametrize("url", ["redis://127.0.0.1:1/0", "rediss://127.0.0.1:6379", "not a url", "redis://"])
def test_redis_ping_never_raises(url: str) -> None:
    assert redis_ping(url, timeout=0.5) is False


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (True, (True, [], None)),
        (False, (False, [], None)),
        ({"ok": False, "violations": ["a", "b"]}, (False, ["a", "b"], None)),
        (type("R", (), {"ok": True, "violations": ()})(), (True, [], None)),
        # A3 ProductionInvariantReport shape: ok, is_production, failed
        (type("Report", (), {"ok": False, "is_production": True, "failed": ["no_test_overdraft_wallets"]})(),
         (False, ["no_test_overdraft_wallets"], True)),
    ],
)
def test_invariant_result_shapes(result: object, expected: tuple[bool, list[str], bool | None]) -> None:
    assert _normalise_invariant_result(result) == expected


def test_invariant_result_without_ok_is_rejected() -> None:
    with pytest.raises(TypeError):
        _normalise_invariant_result({"violations": []})


def test_log_limiter_logs_changes_and_throttles_repeats() -> None:
    limiter = _InvariantLogLimiter(interval=3600)
    assert limiter.should_log("fail") is True
    assert limiter.should_log("fail") is False
    assert limiter.should_log("ok") is True
    assert limiter.should_log("fail") is True


def test_unreachable_postgres_is_503_and_live_stays_200() -> None:
    engine = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/elchi_test_unreachable",
        connect_args={"connect_timeout": 1},
    )
    probe = ReadinessProbe(engine_factory=lambda: engine, redis_url=None, environment="production")
    client = _client(probe)
    assert client.get("/health/live").status_code == 200
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {
            "database": "unavailable",
            "migrations": "skipped",
            "redis": "not_configured",
            "production_invariants": "skipped",
        },
        "notices": [],
    }
    assert "nobody" not in response.text and "psycopg" not in response.text


def test_classify_schema_against_the_real_script_graph() -> None:
    from app.api.health_probes import classify_schema, shipped_script_directory

    script = shipped_script_directory()
    head = script.get_heads()[0]
    parent = script.get_revision(head).down_revision
    assert classify_schema([head], [head], script) == "ok"
    assert classify_schema([head], [parent], script) == "ahead"  # DB newer than code
    assert classify_schema([parent], [head], script) == "mismatch"  # DB behind code
    assert classify_schema(["20991231_9999"], [head], script) == "unknown"
    assert classify_schema(["not-a-revision!"], [head], script) == "unknown"
    assert classify_schema([], [head], script) == "unknown"


def test_cache_returns_same_result_within_ttl_and_refreshes_after() -> None:
    now = [100.0]
    runs = {"n": 0}

    def engine_factory():
        runs["n"] += 1
        raise RuntimeError("down")

    probe = ReadinessProbe(engine_factory=engine_factory, redis_url=None, environment="test",
                           cache_ttl_seconds=3, clock=lambda: now[0])
    first = probe.run()
    now[0] += 2.9
    assert probe.run() is first and runs["n"] == 1
    now[0] += 0.2
    assert probe.run() is not first and runs["n"] == 2


def test_expected_heads_come_from_shipped_scripts() -> None:
    heads = health_probes.expected_migration_heads()
    assert len(heads) == 1 and heads[0][:8].isdigit()


def test_openapi_declares_response_models() -> None:
    app = FastAPI()
    app.include_router(health_probes.router)
    paths = app.openapi()["paths"]
    ready = paths["/health/ready"]["get"]["responses"]
    assert ready["200"]["content"]["application/json"]["schema"]["$ref"].endswith("ReadinessResponse")
    assert ready["503"]["content"]["application/json"]["schema"]["$ref"].endswith("ReadinessResponse")
    assert paths["/health/live"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "LiveResponse"
    )
