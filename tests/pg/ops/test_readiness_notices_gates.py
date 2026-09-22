"""Q57 notices and the Q48 gate in readiness / app.ops.gates (unit: fake hooks, no database)."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api import health_probes
from app.api.health_probes import ReadinessProbe, _InvariantLogLimiter, get_readiness_probe, result_notices


class FakeReport:
    def __init__(self, ok: bool, failed=(), notices=(), is_production=True):  # noqa: ANN001
        self.ok, self.failed, self.is_production = ok, list(failed), is_production
        self.notices = tuple(types.SimpleNamespace(name=n, detail={"secret": "x"}) for n in notices)


@contextmanager
def _fake_modules(**functions):  # noqa: ANN003
    names = []
    for module_name, (attribute, fn) in functions.items():
        module = types.ModuleType(module_name)
        setattr(module, attribute, fn)
        sys.modules[module_name] = module
        names.append(module_name)
    try:
        yield
    finally:
        for name in names:
            sys.modules.pop(name, None)


class _Probe(ReadinessProbe):
    """DB checks short-circuited to ok so only hook handling is under test."""

    def _check_database(self):  # noqa: ANN202
        engine = create_engine("sqlite://")
        return "ok", "ok", self._check_invariants(engine)


def _probe(**kwargs) -> ReadinessProbe:  # noqa: ANN003
    defaults = dict(engine_factory=lambda: None, redis_url=None, environment="production",
                    log_limiter=_InvariantLogLimiter(0), cache_ttl_seconds=0)
    defaults.update(kwargs)
    return _Probe(**defaults)


def _get(probe: ReadinessProbe):  # noqa: ANN202
    app = FastAPI()
    app.include_router(health_probes.router)
    app.dependency_overrides[get_readiness_probe] = lambda: probe
    return TestClient(app).get("/health/ready")


def test_notice_alone_never_degrades_or_503(monkeypatch: pytest.MonkeyPatch) -> None:
    with _fake_modules(fake_wallet_notice=("check", lambda s: FakeReport(True, notices=["unconfirmed_seed_policy_active"]))):
        probe = _probe(redis_url="redis://unused", invariant_hooks=[("fake_wallet_notice", "check")], gate_hooks=())
        monkeypatch.setattr(health_probes, "redis_ping", lambda url: True)
        response = _get(probe)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["production_invariants"] == "ok"
    assert body["notices"] == ["unconfirmed_seed_policy_active"]
    assert "secret" not in response.text, "notice details are not exposed"


def test_notices_are_listed_alongside_a_real_failure() -> None:
    with _fake_modules(fake_wallet_fail=("check", lambda s: FakeReport(False, ["no_negative_available"], ["n1", "n1", "n0"]))):
        response = _get(_probe(invariant_hooks=[("fake_wallet_fail", "check")], gate_hooks=()))
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["notices"] == ["n0", "n1"]


def test_no_notices_key_is_an_empty_list() -> None:
    with _fake_modules(fake_wallet_plain=("check", lambda s: True)):
        body = _get(_probe(invariant_hooks=[("fake_wallet_plain", "check")], gate_hooks=())).json()
    assert body["notices"] == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"ok": True, "notices": [{"name": "a", "detail": {}}, "b"]}, ["a", "b"]),
        (FakeReport(True, notices=["x"]), ["x"]),
        (True, []),
        ({"ok": True, "notices": [{"detail": {}}, 5]}, []),
    ],
)
def test_result_notices_shapes(raw: object, expected: list[str]) -> None:
    assert result_notices(raw) == expected


def test_failing_q48_gate_is_part_of_production_invariants() -> None:
    with _fake_modules(
        fake_wallet_ok=("check", lambda s: FakeReport(True)),
        fake_platform_gate=("q48_gate_status", lambda s: {"ok": False, "problems": ["balance_guard_not_fixed"]}),
    ):
        probe = _probe(invariant_hooks=[("fake_wallet_ok", "check")],
                       gate_hooks=[("fake_missing_gate_module", "q48_gate_status"), ("fake_platform_gate", "q48_gate_status")])
        response = _get(probe)
    assert response.status_code == 200
    assert response.json()["checks"]["production_invariants"] == "fail"
    assert response.json()["status"] == "degraded"


def test_missing_q48_gate_hook_is_not_a_failure() -> None:
    with _fake_modules(fake_wallet_ok2=("check", lambda s: FakeReport(True))):
        probe = _probe(invariant_hooks=[("fake_wallet_ok2", "check")], gate_hooks=[("fake_no_such_gate", "q48_gate_status")])
        body = _get(probe).json()
    assert body["checks"]["production_invariants"] == "ok"
    assert body["status"] == "ready" or body["checks"]["redis"] != "ok"


def test_gates_status_json_separates_q48_from_other_invariant_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ops import gates

    monkeypatch.setattr(gates, "enabled_v2_service_flags", lambda conn: ["parcel_enabled:corridor:c1"])
    engine = create_engine("sqlite://")
    with _fake_modules(
        fake_wallet_mix=("check", lambda s: FakeReport(False, ["global_standard_active_now"])),
        fake_gate_mix=("q48_gate_status", lambda s: {"ok": False, "problems": ["roles_not_split"]}),
    ):
        probe = _probe(invariant_hooks=[("fake_wallet_mix", "check")], gate_hooks=[("fake_gate_mix", "q48_gate_status")])
        result = gates.status(probe=probe, engine=engine)
    assert result["q48_gate"] == {"available": True, "ok": False, "failed": ["roles_not_split"]}
    assert result["invariant_failures_excluding_q48"] == ["fake_wallet_mix.check:global_standard_active_now"]
    assert result["enabled_v2_service_flags"] == ["parcel_enabled:corridor:c1"]


class _NoticeProbe(_Probe):
    """Like _Probe, plus the informational notice hooks (wave 2.1 geo notices)."""

    def _check_database(self):  # noqa: ANN202
        result = super()._check_database()
        self._collect_notices(create_engine("sqlite://"))
        return result


def test_geo_notices_are_informational_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_probes, "redis_ping", lambda url: True)
    with _fake_modules(
        fake_wallet_geo=("check", lambda s: FakeReport(True, notices=["unconfirmed_seed_policy_active"])),
        fake_geo_service=("readiness_notices", lambda s: ["routing_provider_disabled", "q47_violations_present"]),
    ):
        probe = _NoticeProbe(engine_factory=lambda: None, redis_url="redis://unused", environment="production",
                             log_limiter=_InvariantLogLimiter(0), cache_ttl_seconds=0,
                             invariant_hooks=[("fake_wallet_geo", "check")], gate_hooks=(),
                             notice_hooks=[("fake_geo_service", "readiness_notices")])
        response = _get(probe)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready" and body["checks"]["production_invariants"] == "ok"
    assert body["notices"] == ["q47_violations_present", "routing_provider_disabled", "unconfirmed_seed_policy_active"]


@pytest.mark.parametrize(
    "hook",
    [
        ("fake_geo_absent_module", "readiness_notices"),
        ("fake_geo_crash", "readiness_notices"),
        ("fake_geo_crash", "missing_attribute"),
    ],
)
def test_missing_or_crashing_notice_hook_never_changes_status(monkeypatch: pytest.MonkeyPatch, hook: tuple[str, str]) -> None:
    monkeypatch.setattr(health_probes, "redis_ping", lambda url: True)

    def crash(session):  # noqa: ANN001, ANN202
        raise RuntimeError("geo notices broken")

    with _fake_modules(fake_wallet_geo2=("check", lambda s: FakeReport(True)), fake_geo_crash=("readiness_notices", crash)):
        probe = _NoticeProbe(engine_factory=lambda: None, redis_url="redis://unused", environment="production",
                             log_limiter=_InvariantLogLimiter(0), cache_ttl_seconds=0,
                             invariant_hooks=[("fake_wallet_geo2", "check")], gate_hooks=(), notice_hooks=[hook])
        response = _get(probe)
    assert response.status_code == 200
    assert response.json()["status"] == "ready" and response.json()["notices"] == []


def test_default_notice_hook_is_geo_readiness_notices() -> None:
    assert ("app.modules.geo.service", "readiness_notices") in health_probes.READINESS_NOTICE_HOOKS


def test_gates_status_without_gate_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ops import gates

    monkeypatch.setattr(gates, "enabled_v2_service_flags", lambda conn: [])
    with _fake_modules(fake_wallet_only=("check", lambda s: FakeReport(True))):
        probe = _probe(invariant_hooks=[("fake_wallet_only", "check")], gate_hooks=[("fake_absent_gate", "q48_gate_status")])
        result = gates.status(probe=probe, engine=create_engine("sqlite://"))
    assert result["q48_gate"] == {"available": False, "ok": None, "failed": []}
    assert result["invariant_failures_excluding_q48"] == []
