"""Q73: restore_drill uses only a digest-pinned PostGIS image once the registry is set (no Docker needed)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.pg.ops.test_deploy_preflight import resolve_bash

REPO_ROOT = Path(__file__).resolve().parents[3]
DRILL = (REPO_ROOT / "scripts" / "restore_drill.sh").as_posix()
BASH, BASH_SOURCE = resolve_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason=BASH_SOURCE)

DIGEST = "registry.example.uz/elchi/elchi-postgis@sha256:" + "a" * 64
OTHER_DIGEST = "registry.example.uz/elchi/elchi-postgis@sha256:" + "b" * 64
TAG = "registry.example.uz/elchi/elchi-postgis:16.15-3.5.3-trixie"


def _drill(tmp_path: Path, *args: str, env_file: str | None = None, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items()
            if k not in {"ELCHI_POSTGIS_IMAGE", "ELCHI_DRILL_DB_IMAGE", "ELCHI_DRILL_REQUIRE_DIGEST", "ELCHI_APP_ENV_FILE", "DOCKER_HOST"}}
    base["ELCHI_APP_ENV_FILE"] = env_file or (tmp_path / "absent.env").as_posix()
    base.update(env)
    assert BASH is not None
    return subprocess.run([BASH, DRILL, *args], env=base, capture_output=True, text=True, timeout=60)


def test_no_registry_uses_dev_fallback_with_warning(tmp_path: Path) -> None:
    result = _drill(tmp_path, "--print-image")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "elchi-postgis:16.15-3.5.3-trixie"
    assert "NOT launch/RTO evidence" in result.stderr


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"ELCHI_POSTGIS_IMAGE": DIGEST}, DIGEST),
        ({"ELCHI_POSTGIS_IMAGE": DIGEST, "ELCHI_DRILL_DB_IMAGE": OTHER_DIGEST}, OTHER_DIGEST),
        ({"ELCHI_DRILL_REQUIRE_DIGEST": "1", "ELCHI_POSTGIS_IMAGE": DIGEST}, DIGEST),
    ],
)
def test_digest_pinned_image_is_accepted(tmp_path: Path, env: dict[str, str], expected: str) -> None:
    result = _drill(tmp_path, "--print-image", **env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "env",
    [
        {"ELCHI_POSTGIS_IMAGE": TAG},
        {"ELCHI_POSTGIS_IMAGE": "elchi-postgis:16.15-3.5.3-trixie"},
        {"ELCHI_POSTGIS_IMAGE": DIGEST, "ELCHI_DRILL_DB_IMAGE": "elchi-postgis:16.15-3.5.3-trixie"},
        {"ELCHI_POSTGIS_IMAGE": DIGEST[:-1]},
        {"ELCHI_DRILL_REQUIRE_DIGEST": "1"},
    ],
)
def test_tag_is_refused_once_registry_is_set(tmp_path: Path, env: dict[str, str]) -> None:
    result = _drill(tmp_path, "--print-image", **env)
    assert result.returncode == 2
    assert "Q73" in result.stderr and result.stdout == ""


def test_registry_read_from_app_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.app"
    env_file.write_text(f"ELCHI_ENVIRONMENT=production\nELCHI_POSTGIS_IMAGE={TAG}\n", encoding="utf-8")
    assert _drill(tmp_path, "--print-image", env_file=env_file.as_posix()).returncode == 2
    env_file.write_text(f'ELCHI_POSTGIS_IMAGE="{DIGEST}"\r\n', encoding="utf-8")
    result = _drill(tmp_path, "--print-image", env_file=env_file.as_posix())
    assert result.returncode == 0 and result.stdout.strip() == DIGEST


def test_full_drill_refuses_tag_before_touching_docker(tmp_path: Path) -> None:
    dump = tmp_path / "db.dump"
    dump.write_bytes(b"not a real dump")
    result = _drill(tmp_path, "--dump", dump.as_posix(), ELCHI_POSTGIS_IMAGE=TAG)
    assert result.returncode == 2
    assert "refusing image" in result.stderr
    assert "Starting disposable database" not in result.stdout
