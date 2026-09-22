"""BR #18: ``run_locked`` gives at-most-one concurrent run across worker replicas (real PostgreSQL)."""

from __future__ import annotations

import threading

import pytest

from app import worker
from tests.pg.conftest import PgDatabase
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg


def test_second_caller_skips_while_first_holds_the_lock(pg_db: PgDatabase) -> None:
    inside, release = threading.Event(), threading.Event()
    results: dict[str, tuple[bool, object]] = {}

    def long_job() -> str:
        inside.set()
        assert release.wait(10)
        return "first-done"

    thread = threading.Thread(target=lambda: results.__setitem__("first", worker.run_locked("reconcile", long_job, engine=pg_db.engine)))
    thread.start()
    assert inside.wait(10)
    results["second"] = worker.run_locked("reconcile", lambda: "second-ran", engine=pg_db.engine)
    other_key = worker.run_locked("expire-listings", lambda: "other-ran", engine=pg_db.engine)
    release.set()
    thread.join(10)

    assert results["first"] == (True, "first-done")
    assert results["second"] == (False, None)
    assert other_key == (True, "other-ran"), "different job keys do not block each other"
    assert worker.run_locked("reconcile", lambda: "third-ran", engine=pg_db.engine) == (True, "third-ran")


def test_lock_released_when_job_raises(pg_db: PgDatabase) -> None:
    def broken() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        worker.run_locked(7, broken, engine=pg_db.engine)
    assert worker.run_locked(7, lambda: "after", engine=pg_db.engine) == (True, "after")


def test_twenty_concurrent_replicas_run_the_job_at_most_once(pg_db: PgDatabase) -> None:
    ran: list[int] = []
    gate = threading.Event()

    def job_for(index: int):
        def job() -> int:
            ran.append(index)
            gate.wait(0.5)  # keep the lock held while the others try
            return index

        return job

    report = run_concurrently(
        20, lambda index, _session: worker.run_locked("partition-maintenance", job_for(index), engine=pg_db.engine),
        engine=pg_db.engine,
    )
    assert not report.failures, [r.error for r in report.failures]
    acquired = [value for value in report.values() if value[0]]
    assert len(ran) == len(acquired) >= 1
    assert len(acquired) == 1, f"expected exactly one replica to run, got {len(acquired)}"
