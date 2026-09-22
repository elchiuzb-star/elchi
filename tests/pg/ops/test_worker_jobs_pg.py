"""Wave 2.1 worker jobs on real PostgreSQL (A10a): per-job advisory lock, own transaction, isolation,
no external network I/O while the job's DB transaction is open."""

from __future__ import annotations

import socket
import threading
from datetime import timedelta

import pytest
from sqlalchemy import text

from app import worker
from app.contracts.timeutil import utc_now
from app.modules.marketplace import service as marketplace_service
from tests.pg.conftest import PgDatabase
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import World, world  # noqa: F401 - fixture
from tests.pg.marketplace.test_marketplace_pg import open_thread

pytestmark = pytest.mark.pg


def _job(name: str) -> worker.ServiceJob:
    return worker.ServiceJob(name, "unused", "unused", "ELCHI_TEST_UNUSED_INTERVAL", 60.0)


def _proposals_job() -> worker.ServiceJob:
    return next(job for job in worker.SERVICE_JOBS if job.name == "marketplace.expire_due_proposals")


def test_second_replica_skips_while_the_job_runs(pg_db: PgDatabase) -> None:
    inside, release = threading.Event(), threading.Event()
    calls: list[int] = []
    results: dict[str, tuple[bool, int]] = {}

    def slow(session, *, limit):  # noqa: ANN001, ANN202
        calls.append(1)
        session.execute(text("SELECT 1"))
        inside.set()
        assert release.wait(10)
        return 0

    job = _job("test.slow")
    first = threading.Thread(target=lambda: results.__setitem__("first", worker.run_service_job(job, slow, engine=pg_db.engine)))
    first.start()
    assert inside.wait(10)
    results["second"] = worker.run_service_job(job, slow, engine=pg_db.engine)
    results["other"] = worker.run_service_job(_job("test.other"), lambda s, *, limit: 0, engine=pg_db.engine)
    release.set()
    first.join(10)
    assert results == {"first": (True, 0), "second": (False, 0), "other": (True, 0)}
    assert len(calls) == 1


def test_real_expiry_job_concurrent_replicas_expire_once(world: World) -> None:
    _, thread_public_id, _ = open_thread(world)
    later = utc_now() + timedelta(hours=3)
    job = _proposals_job()
    fn = worker.resolve_service_function(job)
    assert fn is marketplace_service.expire_due_proposals

    report = run_concurrently(
        8, lambda index, _session: worker.run_service_job(job, fn, engine=world.db.engine, now=later), engine=world.db.engine
    )
    assert not report.failures, [r.error for r in report.failures]
    assert sum(handled for _ran, handled in report.values()) == 1
    with world.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, thread_public_id)
        assert thread.state == "closed"
        assert s.execute(text("SELECT count(*) FROM outbox_events WHERE event_type = 'proposal.expired'")).scalar_one() == 1


def test_failing_job_rolls_back_its_own_transaction_and_next_job_commits(pg_db: PgDatabase) -> None:
    with pg_db.engine.begin() as conn:
        conn.execute(text("CREATE TABLE worker_job_probe (job text NOT NULL)"))

    def broken(session, *, limit):  # noqa: ANN001, ANN202
        session.execute(text("INSERT INTO worker_job_probe VALUES ('broken')"))
        raise RuntimeError("boom")

    def fine(session, *, limit):  # noqa: ANN001, ANN202
        session.execute(text("INSERT INTO worker_job_probe VALUES ('fine')"))
        return 1

    broken_job = _job("test.broken")
    tasks = [
        worker.service_job_task(broken_job, broken, engine=pg_db.engine),
        worker.service_job_task(_job("test.fine"), fine, engine=pg_db.engine),
    ]
    assert worker.run_tasks_once(tasks) == 1
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT job FROM worker_job_probe")).scalars().all() == ["fine"]
        assert conn.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")).scalar_one() == 0
    assert worker.run_service_job(broken_job, lambda s, *, limit: 0, engine=pg_db.engine) == (True, 0), "lock released"


def test_no_external_network_io_inside_the_job_transaction(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Python-level sockets are forbidden while the real jobs run; libpq (the DB) does not use them."""
    open_thread(world)
    attempts: list[object] = []

    def refuse(*args: object, **kwargs: object) -> None:
        attempts.append(args)
        raise AssertionError("external network call inside a worker job")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    later = world.base_time + timedelta(hours=2)
    handled = 0
    for job in worker.SERVICE_JOBS:
        fn = worker.resolve_service_function(job)
        if fn is None:
            continue  # pending owner function: reported, not wired
        ran, count = worker.run_service_job(job, fn, engine=world.db.engine, now=max(later, utc_now() + timedelta(hours=3)))
        assert ran
        handled += count
    assert attempts == []
    assert handled >= 1
