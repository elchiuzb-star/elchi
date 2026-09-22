"""Worker skeleton: one iteration, heartbeat and the container healthcheck (no Docker needed)."""

from __future__ import annotations

import json
import os
import subprocess
import threading

import pytest
import sys
import time
from pathlib import Path

from app import worker

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(args: list[str], heartbeat: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ELCHI_WORKER_HEARTBEAT_FILE"] = str(heartbeat)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "app.worker", *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60
    )


def test_healthcheck_fails_without_heartbeat(tmp_path: Path) -> None:
    assert _run(["--healthcheck"], tmp_path / "hb").returncode == 1


def test_once_writes_heartbeat_and_healthcheck_passes(tmp_path: Path) -> None:
    heartbeat = tmp_path / "hb"
    result = _run(["--once"], heartbeat)
    assert result.returncode == 0, result.stderr
    # JSON log lines on stdout (app.ops.logging)
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert [line["message"] for line in lines][:1] == ["worker_started tasks=0 poll_seconds=5.0 once=True"]
    assert lines[-1]["message"] == "worker_stopped" and lines[-1]["logger"] == "elchi.worker"
    assert _run(["--healthcheck"], heartbeat).returncode == 0


def test_stale_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    heartbeat = tmp_path / "hb"
    heartbeat.write_text(f"{time.time() - 120:.3f}\n", encoding="ascii")
    assert _run(["--healthcheck", "--max-age", "60"], heartbeat).returncode == 1


def test_failing_task_does_not_stop_the_loop() -> None:
    calls: list[str] = []

    def broken() -> None:
        calls.append("broken")
        raise RuntimeError("boom")

    def fine() -> None:
        calls.append("fine")

    assert worker.run_tasks_once([broken, fine]) == 1
    assert calls == ["broken", "fine"]


def test_heartbeat_withheld_after_consecutive_all_task_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELCHI_WORKER_MAX_FAILED_ROUNDS", "2")
    monkeypatch.setenv("ELCHI_WORKER_POLL_SECONDS", "0.2")
    beats: list[int] = []
    monkeypatch.setattr(worker, "write_heartbeat", lambda path=None: beats.append(1))

    def broken() -> None:
        raise RuntimeError("db down")

    worker.run_forever(threading.Event(), tasks=[broken], max_rounds=4)
    assert len(beats) == 1, "round 1 fails (1 < 2) -> beat; rounds 2-4 withheld"


def test_partial_failure_resets_the_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELCHI_WORKER_MAX_FAILED_ROUNDS", "2")
    monkeypatch.setenv("ELCHI_WORKER_POLL_SECONDS", "0.2")
    beats: list[int] = []
    monkeypatch.setattr(worker, "write_heartbeat", lambda path=None: beats.append(1))
    rounds = iter([True, True, False, True])

    def flaky() -> None:
        if next(rounds):
            raise RuntimeError("fail")

    def fine() -> None:
        return None

    worker.run_forever(threading.Event(), tasks=[flaky, fine], max_rounds=4)
    assert len(beats) == 4, "one task still succeeds every round -> never all-failed"


@pytest.mark.parametrize(("key", "expected_type"), [(42, int), ("nightly-reconcile", int)])
def test_advisory_lock_key_is_stable_bigint(key: int | str, expected_type: type) -> None:
    value = worker.advisory_lock_key(key)
    assert isinstance(value, expected_type) and -(2**63) <= value < 2**63
    assert worker.advisory_lock_key(key) == value


@pytest.mark.parametrize("bad", ["", True, 2**63, 1.5])
def test_advisory_lock_key_rejects_bad_input(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        worker.advisory_lock_key(bad)  # type: ignore[arg-type]
