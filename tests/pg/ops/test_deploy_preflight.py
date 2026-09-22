"""Pure preflight checks in scripts/lib/preflight.sh (no Docker, no network).

Bash resolution (wave 1.7 NEW-2): on Windows ``shutil.which("bash")`` may be the WSL launcher in
System32, which cannot read Windows paths. Order: ``BASH_FOR_TESTS`` -> Git Bash (default install
path, then derived from ``git --exec-path``) -> ``bash`` on PATH unless it is the WSL launcher ->
skip with the reason.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PREFLIGHT = (REPO_ROOT / "scripts" / "lib" / "preflight.sh").as_posix()


def _is_wsl_launcher(path: str) -> bool:
    lowered = path.replace("/", "\\").lower()
    return "\\windows\\system32\\" in lowered or "\\windowsapps\\" in lowered


def resolve_bash() -> tuple[str | None, str]:
    explicit = os.environ.get("BASH_FOR_TESTS")
    if explicit:
        return (explicit, "BASH_FOR_TESTS") if Path(explicit).exists() else (None, f"BASH_FOR_TESTS={explicit} does not exist")
    if os.name == "nt":
        candidates = [Path(r"C:\Program Files\Git\bin\bash.exe"), Path(r"C:\Program Files\Git\usr\bin\bash.exe")]
        git = shutil.which("git")
        if git:
            try:
                exec_path = subprocess.run([git, "--exec-path"], capture_output=True, text=True, timeout=10).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                exec_path = ""
            if exec_path:  # .../Git/mingw64/libexec/git-core -> .../Git/bin/bash.exe
                root = Path(exec_path).parents[2]
                candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate), "Git Bash"
    found = shutil.which("bash")
    if found and not (os.name == "nt" and _is_wsl_launcher(found)):
        return found, "PATH"
    if found:
        return None, f"only the WSL bash launcher was found ({found}); install Git Bash or set BASH_FOR_TESTS"
    return None, "bash not found; set BASH_FOR_TESTS"


BASH, BASH_SOURCE = resolve_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason=BASH_SOURCE)


def _bash(script: str, *args: str, stdin: str | None = None, python: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if python:
        env["ELCHI_PREFLIGHT_PYTHON"] = Path(sys.executable).as_posix()
    return subprocess.run(
        [BASH, "-c", f'source "{PREFLIGHT}"; {script}', "preflight-test", *args],
        input=stdin, capture_output=True, text=True, timeout=60, env=env,
    )


def test_bash_is_not_the_wsl_launcher() -> None:
    assert BASH is not None and not (os.name == "nt" and _is_wsl_launcher(BASH)), (BASH, BASH_SOURCE)
    assert "GNU bash" in subprocess.run([BASH, "--version"], capture_output=True, text=True, timeout=10).stdout


@pytest.mark.parametrize(
    "value",
    ["", "   ", "203.0.113.7/32", "10.0.0.0/8 192.168.1.10/32", "2001:db8::/32", "2001:db8::1/128 198.51.100.0/24",
     "fd00::/8", "::1/128"],
)
def test_valid_monitoring_cidrs(value: str) -> None:
    result = _bash('validate_monitoring_cidrs "$1"', value)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("<monitoring-ip>/32", "placeholder"),
        ("0.0.0.0/0", "everyone"),
        ("::/0", "everyone"),
        ("10.0.0.0/8 0.0.0.0/0", "everyone"),
        ("10.0.0.0/8,192.168.0.0/16", "space-separated"),
        ("203.0.113.7", "not a CIDR"),
        ("256.1.1.1/32", "not a CIDR"),
        ("10.0.0.0/33", "not a CIDR"),
        ("example.org/32", "not a CIDR"),
        ("2001:db8:::/32", "not a CIDR"),
        ("2001:db8::/129", "not a CIDR"),
        ("1:2:3:4:5:6:7:8:9/64", "not a CIDR"),
        ("10.0.0.0/8; rm -rf /", "not a CIDR"),
    ],
)
def test_invalid_monitoring_cidrs_are_rejected(value: str, message: str) -> None:
    result = _bash('validate_monitoring_cidrs "$1"', value)
    assert result.returncode != 0
    assert message in result.stderr, result.stderr


def test_admin_only_keys_in_app_env_are_detected(tmp_path: Path) -> None:
    clean = tmp_path / "app.env"
    clean.write_text(
        "ELCHI_ENVIRONMENT=production\nELCHI_DATABASE_URL=postgresql+psycopg://elchi_app:x@db:5432/elchi\n"
        "# POSTGRES_PASSWORD=commented-out-is-fine\nREDIS_PASSWORD=abc\n",
        encoding="utf-8",
    )
    ok = _bash('app_env_forbidden_keys "$1"', clean.as_posix())
    assert ok.returncode == 0 and ok.stdout == ""

    leaky = tmp_path / "leaky.env"
    leaky.write_text(
        clean.read_text(encoding="utf-8")
        + "POSTGRES_PASSWORD=secret\n  export ELCHI_MIGRATION_DATABASE_URL=postgresql://o:x@db/elchi\n"
        "ELCHI_DB_ADMIN_URL=postgresql://a@/elchi\nELCHI_DB_OWNER_PASSWORD=y\n",
        encoding="utf-8",
    )
    bad = _bash('app_env_forbidden_keys "$1"', leaky.as_posix())
    assert bad.returncode == 1
    assert bad.stdout.split() == ["POSTGRES_PASSWORD", "ELCHI_DB_OWNER_PASSWORD", "ELCHI_MIGRATION_DATABASE_URL",
                                  "ELCHI_DB_ADMIN_URL"]


RENDERED = {
    "name": "elchi",
    "services": {
        "api": {"image": "elchi-api:abc", "environment": {"ELCHI_DATABASE_URL": "postgresql+psycopg://elchi_app:x@db/elchi"}},
        "migrate": {"image": "elchi-api:abc", "environment": {"ELCHI_MIGRATION_DATABASE_URL": "u", "POSTGRES_PASSWORD": "z"}},
        "worker": {"image": "elchi-api:abc", "environment": ["ELCHI_ENVIRONMENT=production", "ELCHI_DB_OWNER_PASSWORD=leaked"]},
        "caddy": {"image": "caddy:2.11.4-alpine@sha256:" + "5" * 64, "environment": {"ELCHI_DOMAIN": "x"}},
        "redis": {"image": "redis:7.4.11"},
    },
}


def test_rendered_compose_json_env_is_checked_per_service() -> None:
    stdin = json.dumps(RENDERED)
    api = _bash("rendered_env_forbidden_keys api", stdin=stdin, python=True)
    assert api.returncode == 0 and api.stdout.strip() == "", api.stderr
    worker = _bash("rendered_env_forbidden_keys worker", stdin=stdin, python=True)
    assert worker.returncode == 1 and worker.stdout.split() == ["ELCHI_DB_OWNER_PASSWORD"], worker.stderr
    migrate = _bash("rendered_env_forbidden_keys migrate", stdin=stdin, python=True)
    assert migrate.returncode == 1


@pytest.mark.parametrize(
    ("service", "stdin", "message"),
    [
        ("api", json.dumps({"services": {"worker": {"environment": {"A": "1"}}}}), "not found"),
        ("redis", json.dumps(RENDERED), "no environment block"),
        ("api", "name: elchi\nservices: {}\n", "not JSON"),
    ],
)
def test_rendered_env_check_fails_closed(service: str, stdin: str, message: str) -> None:
    result = _bash(f"rendered_env_forbidden_keys {service}", stdin=stdin, python=True)
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert message in result.stderr


def test_rendered_service_image_from_json() -> None:
    ok = _bash("rendered_service_image caddy", stdin=json.dumps(RENDERED), python=True)
    assert ok.returncode == 0 and ok.stdout.strip().startswith("caddy:2.11.4-alpine@sha256:")
    missing = _bash("rendered_service_image nope", stdin=json.dumps(RENDERED), python=True)
    assert missing.returncode == 2


def test_real_compose_json_shape_is_supported(tmp_path: Path) -> None:
    """Shape produced by `docker compose config --format json` (environment as a mapping)."""
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not available")
    app_env = tmp_path / "app.env"
    admin_env = tmp_path / "db-admin.env"
    app_env.write_text(
        f"ELCHI_APP_ENV_FILE={app_env.as_posix()}\nELCHI_DB_ADMIN_ENV_FILE={admin_env.as_posix()}\n"
        "ELCHI_POSTGIS_IMAGE=elchi-postgis:local\nREDIS_PASSWORD=0123456789abcdef0123456789abcdef\n"
        "ELCHI_ENVIRONMENT=staging\nELCHI_DATABASE_URL=postgresql+psycopg://elchi_app:x@db/elchi\n",
        encoding="utf-8",
    )
    admin_env.write_text("POSTGRES_USER=a\nPOSTGRES_PASSWORD=b\nPOSTGRES_DB=elchi\nELCHI_DB_ADMIN_URL=c\n", encoding="utf-8")
    rendered = subprocess.run(
        ["docker", "compose", "--env-file", str(app_env), "-f", str(REPO_ROOT / "docker-compose.prod.yml"),
         "--profile", "ops", "config", "--format", "json"],
        capture_output=True, text=True, timeout=60,
    )
    if rendered.returncode != 0:
        pytest.skip(f"docker compose config unavailable: {rendered.stderr.strip()[:200]}")
    for service in ("api", "worker"):
        result = _bash(f"rendered_env_forbidden_keys {service}", stdin=rendered.stdout, python=True)
        assert result.returncode == 0, (service, result.stdout, result.stderr)
    for service in ("db-roles", "migrate"):
        assert _bash(f"rendered_env_forbidden_keys {service}", stdin=rendered.stdout, python=True).returncode == 1


def test_diff_guarded_tables(tmp_path: Path) -> None:
    expected = tmp_path / "expected.txt"
    expected.write_text("# comment\nledger_account_balances\n\n", encoding="utf-8")
    assert _bash('diff_guarded_tables "$1" "$2"', expected.as_posix(), "ledger_account_balances").returncode == 0
    extra = _bash('diff_guarded_tables "$1" "$2"', expected.as_posix(), "ledger_account_balances,wallet_accounts")
    assert extra.returncode == 1 and "differ" in extra.stderr
    assert _bash('diff_guarded_tables "$1" "$2"', expected.as_posix(), "").returncode == 1


@pytest.mark.parametrize(
    ("image", "pinned"),
    [
        ("registry.example.uz/elchi/elchi-postgis@sha256:" + "a" * 64, True),
        ("elchi-postgis@sha256:" + "0123456789abcdef" * 4, True),
        ("elchi-postgis:16.15-3.5.3-trixie", False),
        ("registry.example.uz/elchi/elchi-postgis:16.15@sha256:" + "a" * 63, False),
        ("registry.example.uz/elchi/elchi-postgis@sha256:" + "A" * 64, False),
        ("", False),
    ],
)
def test_digest_pinning(image: str, pinned: bool) -> None:
    assert (_bash('is_digest_pinned "$1"', image).returncode == 0) is pinned
