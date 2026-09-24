"""Wave 2.1 worker job wiring (A10a): registration, pending/import-failure handling, batching, isolation.

No PostgreSQL here: the advisory lock is stubbed. Lock exclusivity, per-job transactions on real data and
"no external API inside the DB transaction" are proven in tests/pg/ops/test_worker_jobs_pg.py.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app import worker


def _job(name: str, module: str = "fake_jobs_module", attribute: str = "fn", **kwargs: object) -> worker.ServiceJob:
    return worker.ServiceJob(name, module, attribute, "ELCHI_TEST_WORKER_INTERVAL", 60.0, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def fake_module():  # noqa: ANN201
    module = types.ModuleType("fake_jobs_module")
    module.fn = lambda session, *, limit, now=None: 0  # type: ignore[attr-defined]
    sys.modules["fake_jobs_module"] = module
    yield module
    sys.modules.pop("fake_jobs_module", None)


@pytest.fixture
def unlocked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    keys: list[str] = []

    def fake_run_locked(key, fn, *, engine=None):  # noqa: ANN001, ANN202
        keys.append(key)
        return True, fn()

    monkeypatch.setattr(worker, "run_locked", fake_run_locked)
    return keys


def test_default_jobs_catalogue() -> None:
    names = [job.name for job in worker.SERVICE_JOBS]
    assert names == [
        "marketplace.expire_due_listings",
        "marketplace.expire_due_proposals",
        "marketplace.close_stale_intent_threads",
        "bookings.expire_due_amendments",
        "bookings.emit_confirmation_overdue_signals",
        "bookings.emit_hold_escalation_signals",
        # wave 3.1
        "tracking.emit_stale_signals",
        "tracking.emit_window_opened_signals",
        "trust_support.emit_dispute_escalations",
        "trust_support.publish_due_ratings",
        "trust_support.refresh_reputation_snapshots",
        # wave 6: §17.3 fraud observation (never an automatic block) and the §20.4 search-counter retention
        "trust_support.scan_fraud_signals",
        "marketplace.expire_saved_searches",
        "marketplace.purge_search_events",
        # wave 4
        "operations.refresh_kpi_daily",
        "operations.expire_share_links",
        # referral stage 3 (ADR-0023)
        "promotions.process_qualifications",
        "promotions.recheck_granted",
        "promotions.expire_enrollments",
        "promotions.expire_lots",
        "promotions.pause_exhausted_campaigns",
        "promotions.escalate_reviews",
        "promotions.purge_identity_digests",
        "promotions.purge_rate_events",
        "communications.dispatch_outbox",
    ]
    assert names[-1] == "communications.dispatch_outbox", "dispatch runs after the jobs that enqueue events"
    assert len({job.lock_key for job in worker.SERVICE_JOBS}) == len(names)
    intervals = {job.name: job.default_interval_seconds for job in worker.SERVICE_JOBS}
    assert intervals["marketplace.expire_due_listings"] == 60.0
    assert intervals["bookings.emit_hold_escalation_signals"] == 300.0
    assert intervals["tracking.emit_stale_signals"] == 60.0, "the 120 s staleness rule needs a minute-grained job"
    assert intervals["trust_support.refresh_reputation_snapshots"] == 900.0
    assert intervals["communications.dispatch_outbox"] == 5.0
    assert intervals["operations.refresh_kpi_daily"] == 3600.0, "KPI are daily counts, not a poll loop"
    outbox = next(job for job in worker.SERVICE_JOBS if job.name == "communications.dispatch_outbox")
    assert outbox.batch_limit == worker.OUTBOX_BATCH_LIMIT, "A7 claims at most OUTBOX_BATCH_LIMIT events per call"


def test_wave3_jobs_are_wired_and_locked_tasks_own_their_key() -> None:
    """Every wave 3 worker function named in the wave 3 report is registered (not 'pending')."""
    listed = {row["job"]: row for row in worker.describe_jobs()}
    expected = {
        "tracking.emit_stale_signals": "app.modules.tracking.jobs.emit_stale_signals",
        "tracking.emit_window_opened_signals": "app.modules.tracking.jobs.emit_window_opened_signals",
        "tracking.retention": "app.modules.tracking.jobs.retention_task",
        "communications.dispatch_outbox": "app.modules.communications.service.dispatch_outbox",
        "communications.push_delivery": "app.modules.communications.jobs.push_delivery_task",
        "trust_support.emit_dispute_escalations": "app.modules.trust_support.service.emit_dispute_escalations",
        "trust_support.publish_due_ratings": "app.modules.trust_support.service.publish_due_ratings",
        "trust_support.refresh_reputation_snapshots": "app.modules.trust_support.service.refresh_reputation_snapshots",
        "marketplace.expire_saved_searches": "app.modules.marketplace.feed.service.expire_saved_searches",
    }
    for name, function in expected.items():
        assert listed[name]["function"] == function
        assert listed[name]["status"] == "wired", f"{name} is not wired"

    from app.modules.communications import jobs as communications_jobs
    from app.modules.tracking import jobs as tracking_jobs

    assert listed["tracking.retention"]["lock_key"] == tracking_jobs.RETENTION_LOCK_KEY
    assert listed["communications.push_delivery"]["lock_key"] == communications_jobs.PUSH_DELIVERY_LOCK_KEY


def test_register_wires_existing_skips_pending_and_import_errors(
    fake_module: types.ModuleType, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_import = worker.importlib.import_module

    def import_module(name: str):  # noqa: ANN202
        if name == "broken_jobs_module":
            raise RuntimeError("import-time bug")
        return real_import(name)

    monkeypatch.setattr(worker.importlib, "import_module", import_module)
    jobs = [_job("a.wired"), _job("a.pending", attribute="not_shipped_yet"), _job("a.broken", module="broken_jobs_module")]
    tasks: list = []
    worker.register_default_tasks(tasks, jobs=jobs)
    worker.register_default_tasks(tasks, jobs=jobs)  # idempotent
    wired = [getattr(t.wrapped_task, "job_name", None) for t in tasks]
    assert wired.count("a.wired") == 1 and "a.pending" not in wired and "a.broken" not in wired
    locked = [t.wrapped_task.__name__ for t in tasks if not hasattr(t.wrapped_task, "job_name")]
    assert sorted(locked) == ["geo_invariant_scan_task", "push_delivery_task", "retention_task", "routing_cache_cleanup_task"]
    assert len(tasks) == len(worker.LOCKED_MODULE_TASKS) + 1, "the self-locking module tasks + the one wired service job"
    assert "worker_job_pending job=a.pending expected=fake_jobs_module.not_shipped_yet" in caplog.text
    assert "worker_job_import_failed job=a.broken" in caplog.text
    assert worker.describe_jobs(jobs)[1]["status"] == "pending" and worker.describe_jobs(jobs)[0]["status"] == "wired"


def test_interval_from_environment(fake_module: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _job("a.interval")
    assert job.interval_seconds() == 60.0
    monkeypatch.setenv("ELCHI_TEST_WORKER_INTERVAL", "30")
    assert job.interval_seconds() == 30.0
    monkeypatch.setenv("ELCHI_TEST_WORKER_INTERVAL", "1")
    assert job.interval_seconds() == 5.0, "clamped"
    monkeypatch.setenv("ELCHI_TEST_WORKER_INTERVAL", "soon")
    assert job.interval_seconds() == 60.0
    monkeypatch.setenv("ELCHI_TEST_WORKER_INTERVAL", "30")
    tasks: list = []
    worker.register_default_tasks(tasks, jobs=[job])
    assert tasks[-1].__name__ == "every_30s_job_a_interval"


def test_batches_commit_each_and_failure_rolls_back_only_the_failing_batch(tmp_path: Path, unlocked: list[str]) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE probe (batch INTEGER)"))
    seen: list[dict] = []
    fixed_now = datetime(2026, 9, 15, 10, tzinfo=UTC)

    def fn(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen.append(kwargs)
        batch = len(seen)
        session.execute(text("INSERT INTO probe VALUES (:b)"), {"b": batch})
        if batch == 3:
            raise RuntimeError("batch 3 failed")
        return 2

    job = _job("a.batches", batch_limit=2, max_batches=5)
    with pytest.raises(RuntimeError):
        worker.run_service_job(job, fn, engine=engine, now=fixed_now)
    assert seen == [{"limit": 2, "now": fixed_now}] * 3
    with engine.connect() as conn:
        assert conn.execute(text("SELECT batch FROM probe ORDER BY batch")).scalars().all() == [1, 2]
    assert unlocked == ["job.a.batches"]


def test_partial_batch_stops_and_max_batches_bounds_a_run(tmp_path: Path, unlocked: list[str]) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    counts = iter([200, 200, 7, 200])
    assert worker.run_service_job(_job("a.partial"), lambda s, **k: next(counts), engine=engine) == (True, 407)
    calls: list[int] = []
    always_full = _job("a.full", batch_limit=10, max_batches=3)
    assert worker.run_service_job(always_full, lambda s, **k: calls.append(1) or 10, engine=engine) == (True, 30)
    assert len(calls) == 3


def test_skipped_when_lock_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "run_locked", lambda key, fn, engine=None: (False, None))
    called: list[int] = []
    assert worker.run_service_job(_job("a.busy"), lambda s, **k: called.append(1), engine=create_engine("sqlite://")) == (False, 0)
    assert called == []


def test_failing_job_does_not_stop_the_next_job(tmp_path: Path, unlocked: list[str]) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    ran: list[str] = []

    def broken(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        raise RuntimeError("boom")

    def fine(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        ran.append("fine")
        return 0

    tasks = [worker.service_job_task(_job("a.broken"), broken, engine=engine), worker.service_job_task(_job("a.fine"), fine, engine=engine)]
    assert worker.run_tasks_once(tasks) == 1
    assert ran == ["fine"]


def test_list_jobs_cli_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    from app.worker.__main__ import main

    assert main(["--list-jobs"]) == 0
    listed = json.loads(capsys.readouterr().out)
    expected = [job.name for job in (*worker.LOCKED_MODULE_TASKS, *worker.SERVICE_JOBS)]
    assert [row["job"] for row in listed] == expected
    assert {row["status"] for row in listed} <= {"wired", "pending"}
    by_name = {row["job"]: row for row in listed}
    assert by_name["marketplace.expire_due_listings"]["status"] == "wired"
    assert by_name["geo.routing_cache_cleanup"]["interval_seconds"] == 3600.0
    assert by_name["geo.invariant_scan"]["lock_key"] == "geo.invariant_scan"


def test_locked_module_tasks_are_registered_once_with_their_own_lock() -> None:
    from app.modules.communications import jobs as communications_jobs
    from app.modules.geo import jobs as geo_jobs
    from app.modules.tracking import jobs as tracking_jobs

    tasks: list = []
    worker.register_default_tasks(tasks, jobs=())
    worker.register_default_tasks(tasks, jobs=())
    assert [t.wrapped_task for t in tasks] == [
        geo_jobs.routing_cache_cleanup_task,
        geo_jobs.geo_invariant_scan_task,
        tracking_jobs.retention_task,
        communications_jobs.push_delivery_task,
    ]
    assert geo_jobs.GEO_INVARIANT_SCAN_LOCK_KEY == "geo.invariant_scan"
    assert geo_jobs.ROUTING_CACHE_CLEANUP_LOCK_KEY == "geo.routing_cache_cleanup"
    assert tracking_jobs.RETENTION_LOCK_KEY == "tracking.retention"
    assert communications_jobs.PUSH_DELIVERY_LOCK_KEY == "communications.push_delivery"
