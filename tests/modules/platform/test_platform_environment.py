"""Environment allowlist (wave 1.5 BR #3): unknown values are errors, never development."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.modules.platform import service as platform_service
from app.modules.platform.service import DeploymentEnvironment, normalize_environment

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("local", DeploymentEnvironment.DEVELOPMENT),
        ("development", DeploymentEnvironment.DEVELOPMENT),
        ("test", DeploymentEnvironment.TEST),
        (" Staging ", DeploymentEnvironment.STAGING),
        ("PRODUCTION", DeploymentEnvironment.PRODUCTION),
    ],
)
def test_allowlisted_values(value, expected):
    assert normalize_environment(value) is expected


@pytest.mark.parametrize("value", ["prod", "live", "dev", "", None, "production-eu"])
def test_unknown_values_raise(value):
    with pytest.raises(ValueError):
        normalize_environment(value)


def test_app_environment_and_is_production_fail_closed(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "prod")
    with pytest.raises(ValueError):
        platform_service.app_environment()
    assert platform_service.is_production() is True
    monkeypatch.setattr(settings, "environment", "local")
    assert platform_service.app_environment() is DeploymentEnvironment.DEVELOPMENT
    assert platform_service.is_production() is False


def _migration_0031():
    path = REPO_ROOT / "alembic" / "versions" / "20260913_0031_platform_idempotency_outbox.py"
    spec = importlib.util.spec_from_file_location("a3_migration_0031", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_seed_uses_the_same_allowlist(monkeypatch):
    module = _migration_0031()
    for value, expected in (("local", "development"), ("Production", "production"), ("test", "test")):
        monkeypatch.setenv("ELCHI_ENVIRONMENT", value)
        assert module._marker_from_settings() == expected
    for bad in ("prod", "live", ""):
        monkeypatch.setenv("ELCHI_ENVIRONMENT", bad)
        with pytest.raises(RuntimeError):
            module._marker_from_settings()
