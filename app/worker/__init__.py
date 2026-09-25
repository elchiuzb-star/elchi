"""Background worker skeleton (ADR-0012). Run as ``python -m app.worker``.

Same image and commit as the API. The loop runs registered tasks, handles
SIGTERM/SIGINT gracefully and writes a heartbeat file for the container
healthcheck. What it runs:

* :data:`SERVICE_JOBS` -- a module service function per job (wave 2.1: listing/proposal/amendment
  expiry, booking confirmation-overdue and hold-escalation signals; wave 3.1: tracking staleness and
  tracking-window signals, dispute escalation, rating publication, reputation snapshots, saved-search
  expiry and last the A7 outbox dispatch ``SELECT ... FOR UPDATE SKIP LOCKED`` with its consumers).
  Each job runs in its own session, under a per-job :func:`run_locked` advisory lock, so any number of
  worker replicas runs it at most once at a time.
* :data:`LOCKED_MODULE_TASKS` -- tasks that own their session and take their own lock: geo routing-cache
  cleanup and invariant scan, tracking retention (partitions + purges) and push delivery (whose provider
  call happens outside every transaction).

Register work by appending a callable to ``TASKS``. A task receives nothing,
owns its DB session/transaction, and should not raise for expected conditions.

Health (BR #18): if every task fails in ``ELCHI_WORKER_MAX_FAILED_ROUNDS``
consecutive rounds (default 3), the heartbeat is no longer written, so the
container healthcheck turns unhealthy instead of hiding a broken worker.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from app.contracts.communications import OUTBOX_BATCH_LIMIT

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.engine import Engine

logger = logging.getLogger("elchi.worker")

DEFAULT_POLL_SECONDS = 5.0
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS = 60.0
DEFAULT_MAX_FAILED_ROUNDS = 3

T = TypeVar("T")
Task = Callable[[], None]
TASKS: list[Task] = []


def heartbeat_path() -> Path:
    raw = os.environ.get("ELCHI_WORKER_HEARTBEAT_FILE")
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "elchi-worker.heartbeat"


def poll_seconds() -> float:
    try:
        value = float(os.environ.get("ELCHI_WORKER_POLL_SECONDS", DEFAULT_POLL_SECONDS))
    except ValueError:
        return DEFAULT_POLL_SECONDS
    return min(max(value, 0.2), 300.0)


def max_failed_rounds() -> int:
    try:
        return max(1, int(os.environ.get("ELCHI_WORKER_MAX_FAILED_ROUNDS", DEFAULT_MAX_FAILED_ROUNDS)))
    except ValueError:
        return DEFAULT_MAX_FAILED_ROUNDS


def write_heartbeat(path: Path | None = None) -> None:
    target = path or heartbeat_path()
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(f"{time.time():.3f}\n", encoding="ascii")
    os.replace(tmp, target)


def heartbeat_age(path: Path | None = None) -> float | None:
    target = path or heartbeat_path()
    try:
        return max(0.0, time.time() - float(target.read_text(encoding="ascii").strip()))
    except (OSError, ValueError):
        return None


# ── advisory locks ───────────────────────────────────────────────────────────


def advisory_lock_key(lock_key: int | str) -> int:
    """Stable signed 64-bit key: ints pass through, strings are hashed (blake2b)."""
    if isinstance(lock_key, bool):
        raise TypeError("lock_key must be int or str")
    if isinstance(lock_key, int):
        if not -(2**63) <= lock_key < 2**63:
            raise ValueError("lock_key out of bigint range")
        return lock_key
    if isinstance(lock_key, str) and lock_key:
        digest = hashlib.blake2b(f"elchi:worker:{lock_key}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big", signed=True)
    raise TypeError("lock_key must be a non-empty str or an int")


def run_locked(lock_key: int | str, fn: Callable[[], T], *, engine: Engine | None = None) -> tuple[bool, T | None]:
    """Run ``fn`` only if this process wins ``pg_try_advisory_lock(lock_key)``.

    Returns ``(True, result)`` after running, or ``(False, None)`` when another
    session holds the lock (the job is skipped, not queued). The lock is session-level
    on a dedicated connection and is released even if ``fn`` raises (the exception
    propagates). ``fn`` must open its own session/transaction.
    """
    from sqlalchemy import text

    if engine is None:
        from app.db.session import engine as default_engine

        engine = default_engine
    key = advisory_lock_key(lock_key)
    with engine.connect() as conn:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
        conn.commit()
        if not acquired:
            logger.info("worker_lock_busy key=%s", lock_key)
            return False, None
        try:
            return True, fn()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            conn.commit()


# ── loop ─────────────────────────────────────────────────────────────────────


def run_tasks_once(tasks: Sequence[Task] | None = None) -> int:
    """Run every task once; returns the number of failed tasks."""
    failures = 0
    for task in tasks if tasks is not None else TASKS:
        try:
            task()
        except Exception:  # noqa: BLE001 - one broken task must not stop the loop
            failures += 1
            logger.exception("worker_task_failed task=%s", getattr(task, "__name__", repr(task)))
    return failures


def run_forever(
    stop: threading.Event,
    *,
    once: bool = False,
    tasks: Sequence[Task] | None = None,
    max_rounds: int | None = None,
) -> int:
    active = TASKS if tasks is None else tasks
    interval = poll_seconds()
    limit = max_failed_rounds()
    logger.info("worker_started tasks=%d poll_seconds=%.1f once=%s", len(active), interval, once)
    failures = 0
    failed_rounds = 0
    rounds = 0
    while not stop.is_set():
        failures = run_tasks_once(active)
        rounds += 1
        if active and failures == len(active):
            failed_rounds += 1
        else:
            failed_rounds = 0
        if failed_rounds >= limit:
            logger.error("worker_unhealthy_all_tasks_failing consecutive_rounds=%d (heartbeat withheld)", failed_rounds)
        else:
            write_heartbeat()
        if once or (max_rounds is not None and rounds >= max_rounds):
            break
        stop.wait(interval)
    logger.info("worker_stopped")
    return 1 if once and failures else 0


# ── scheduled jobs ───────────────────────────────────────────────────────────

# Interim scheduling (wave 1.6 integration); A7 owns job scheduling later.
ROUTING_CACHE_CLEANUP_INTERVAL_SECONDS = 3600.0


def every(interval_seconds: float, task: Callable[[], object], *, clock: Callable[[], float] = time.monotonic) -> Task:
    """Wrap ``task`` so the poll loop runs it at most once per ``interval_seconds`` (the first call runs).

    A failing run still waits a full interval before the next attempt; the failure is logged by
    :func:`run_tasks_once`.
    """
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    last_run: list[float] = []

    def scheduled() -> None:
        now = clock()
        if last_run and now - last_run[0] < interval_seconds:
            return
        last_run[:] = [now]
        task()

    scheduled.__name__ = f"every_{interval_seconds:g}s_{getattr(task, '__name__', 'task')}"
    scheduled.wrapped_task = task  # type: ignore[attr-defined]
    return scheduled


DEFAULT_EXPIRY_INTERVAL_SECONDS = 60.0
DEFAULT_SIGNAL_INTERVAL_SECONDS = 300.0
EXPIRY_INTERVAL_ENV = "ELCHI_WORKER_EXPIRY_INTERVAL_SECONDS"
SIGNAL_INTERVAL_ENV = "ELCHI_WORKER_SIGNAL_INTERVAL_SECONDS"

# Wave 3.1 (A10a): intervals of the wave 3 owners' jobs. The outbox is polled as fast as the loop allows
# (ADR-0012 §4); tracking staleness is a 120 s rule (contracts.tracking.DELAYED_MAX_AGE_SECONDS), so those
# signals run once a minute; reputation snapshots and tracking retention are the heavy, rare ones.
OUTBOX_INTERVAL_ENV = "ELCHI_WORKER_OUTBOX_INTERVAL_SECONDS"
DEFAULT_OUTBOX_INTERVAL_SECONDS = 5.0
PUSH_INTERVAL_ENV = "ELCHI_WORKER_PUSH_INTERVAL_SECONDS"
DEFAULT_PUSH_INTERVAL_SECONDS = 10.0
TRACKING_SIGNAL_INTERVAL_ENV = "ELCHI_WORKER_TRACKING_SIGNAL_INTERVAL_SECONDS"
DEFAULT_TRACKING_SIGNAL_INTERVAL_SECONDS = 60.0
TRACKING_RETENTION_INTERVAL_ENV = "ELCHI_WORKER_TRACKING_RETENTION_INTERVAL_SECONDS"
DEFAULT_TRACKING_RETENTION_INTERVAL_SECONDS = 3600.0
FRAUD_SCAN_INTERVAL_ENV = "ELCHI_WORKER_FRAUD_SCAN_INTERVAL_SECONDS"
DEFAULT_FRAUD_SCAN_INTERVAL_SECONDS = 3600  # §17.3: a daily-ish scan is enough; the signal is not time critical
REPUTATION_INTERVAL_ENV = "ELCHI_WORKER_REPUTATION_INTERVAL_SECONDS"
DEFAULT_REPUTATION_INTERVAL_SECONDS = 900.0

# Wave 4 (A13): KPI are daily counts, so the refresh is hourly at most; expired share links are revoked hourly.
KPI_INTERVAL_ENV = "ELCHI_WORKER_KPI_INTERVAL_SECONDS"
DEFAULT_KPI_INTERVAL_SECONDS = 3600.0
SHARE_LINK_INTERVAL_ENV = "ELCHI_WORKER_SHARE_LINK_INTERVAL_SECONDS"
DEFAULT_SHARE_LINK_INTERVAL_SECONDS = 3600.0


@dataclass(frozen=True)
class ServiceJob:
    """A scheduled call of a module SERVICE function ``fn(session, *, now=None, limit=200) -> int``.

    The worker never writes module tables itself (AGENTS §4): it opens the session, calls the owner's
    service function batch by batch, commits after each batch and rolls back on error. The function
    returns how many rows it handled; a full batch (``== batch_limit``) triggers another batch, up to
    ``max_batches`` per run. Service functions do not call external APIs (SMS/push go through the outbox).
    """

    name: str
    module: str
    attribute: str
    interval_env: str
    default_interval_seconds: float
    batch_limit: int = 200
    max_batches: int = 20

    @property
    def lock_key(self) -> str:
        return f"job.{self.name}"

    def interval_seconds(self) -> float:
        raw = os.environ.get(self.interval_env)
        try:
            value = float(raw) if raw else self.default_interval_seconds
        except ValueError:
            logger.warning("worker_job_interval_invalid env=%s value=%r", self.interval_env, raw)
            return self.default_interval_seconds
        return min(max(value, 5.0), 86400.0)


# Q139 (ADR-0026): parcel `delivered` -> operator queue at once (no sender confirmation) is part of
# A4's emit_confirmation_overdue_signals (passenger `arrived` + parcel `delivered`); the B12 queue itself is a query.
# referral stage 3 (ADR-0023): qualification/grant intake, rechecks, expiry, review escalation, identity purge.
PROMOTIONS_INTERVAL_ENV = "ELCHI_WORKER_PROMOTIONS_INTERVAL_SECONDS"
DEFAULT_PROMOTIONS_INTERVAL_SECONDS = 60.0
PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV = "ELCHI_WORKER_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS"
DEFAULT_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS = 300.0
_PROMO = "app.modules.promotions.jobs"

SERVICE_JOBS: tuple[ServiceJob, ...] = (
    ServiceJob("marketplace.expire_due_listings", "app.modules.marketplace.service", "expire_due_listings",
               EXPIRY_INTERVAL_ENV, DEFAULT_EXPIRY_INTERVAL_SECONDS),
    ServiceJob("marketplace.expire_due_proposals", "app.modules.marketplace.service", "expire_due_proposals",
               EXPIRY_INTERVAL_ENV, DEFAULT_EXPIRY_INTERVAL_SECONDS),
    # ADR-0025: offers of a booked/closed/changed saved request that a command skipped (SKIP LOCKED)
    ServiceJob("marketplace.close_stale_intent_threads", "app.modules.marketplace.intents", "close_stale_intent_threads",
               EXPIRY_INTERVAL_ENV, DEFAULT_EXPIRY_INTERVAL_SECONDS),
    # ADR-0026 (Q138): close what is still open of the retired driver-listing model (listings, their offers, requests)
    ServiceJob("marketplace.retire_driver_listings", "app.modules.marketplace.service", "retire_driver_listings",
               EXPIRY_INTERVAL_ENV, DEFAULT_EXPIRY_INTERVAL_SECONDS),
    ServiceJob("bookings.expire_due_amendments", "app.modules.bookings.service", "expire_due_amendments",
               EXPIRY_INTERVAL_ENV, DEFAULT_EXPIRY_INTERVAL_SECONDS),
    ServiceJob("bookings.emit_confirmation_overdue_signals", "app.modules.bookings.service",
               "emit_confirmation_overdue_signals", SIGNAL_INTERVAL_ENV, DEFAULT_SIGNAL_INTERVAL_SECONDS),
    ServiceJob("bookings.emit_hold_escalation_signals", "app.modules.bookings.service",
               "emit_hold_escalation_signals", SIGNAL_INTERVAL_ENV, DEFAULT_SIGNAL_INTERVAL_SECONDS),
    # wave 3 (wired in 3.1). Signals first, dispatch last: events enqueued in this round leave in the same round.
    ServiceJob("tracking.emit_stale_signals", "app.modules.tracking.jobs", "emit_stale_signals",
               TRACKING_SIGNAL_INTERVAL_ENV, DEFAULT_TRACKING_SIGNAL_INTERVAL_SECONDS),
    ServiceJob("tracking.emit_window_opened_signals", "app.modules.tracking.jobs", "emit_window_opened_signals",
               TRACKING_SIGNAL_INTERVAL_ENV, DEFAULT_TRACKING_SIGNAL_INTERVAL_SECONDS),
    ServiceJob("trust_support.emit_dispute_escalations", "app.modules.trust_support.service",
               "emit_dispute_escalations", SIGNAL_INTERVAL_ENV, DEFAULT_SIGNAL_INTERVAL_SECONDS),
    ServiceJob("trust_support.publish_due_ratings", "app.modules.trust_support.service", "publish_due_ratings",
               SIGNAL_INTERVAL_ENV, DEFAULT_SIGNAL_INTERVAL_SECONDS),
    ServiceJob("trust_support.refresh_reputation_snapshots", "app.modules.trust_support.service",
               "refresh_reputation_snapshots", REPUTATION_INTERVAL_ENV, DEFAULT_REPUTATION_INTERVAL_SECONDS),
    # wave 6 (A12): §17.3 fraud signals - observation only, opened for human review, never an automatic block.
    ServiceJob("trust_support.scan_fraud_signals", "app.modules.trust_support.service", "scan_fraud_signals",
               FRAUD_SCAN_INTERVAL_ENV, DEFAULT_FRAUD_SCAN_INTERVAL_SECONDS, max_batches=1),
    ServiceJob("marketplace.expire_saved_searches", "app.modules.marketplace.feed.service", "expire_saved_searches",
               EXPIRY_INTERVAL_ENV, DEFAULT_EXPIRY_INTERVAL_SECONDS),
    # wave 6: §17.7 - the §20.4 search counters are deleted once they are older than the retention window.
    ServiceJob("marketplace.purge_search_events", "app.modules.marketplace.feed.service", "purge_search_events",
               EXPIRY_INTERVAL_ENV, DEFAULT_EXPIRY_INTERVAL_SECONDS),
    # wave 4 (A13)
    ServiceJob("operations.refresh_kpi_daily", "app.modules.operations.jobs", "refresh_kpi_daily",
               KPI_INTERVAL_ENV, DEFAULT_KPI_INTERVAL_SECONDS, max_batches=1),
    ServiceJob("operations.expire_share_links", "app.modules.operations.jobs", "expire_share_links",
               SHARE_LINK_INTERVAL_ENV, DEFAULT_SHARE_LINK_INTERVAL_SECONDS),
    # referral stage 3: before the outbox dispatch, so the events they enqueue leave in the same round
    ServiceJob("promotions.process_qualifications", _PROMO, "process_qualifications",
               PROMOTIONS_INTERVAL_ENV, DEFAULT_PROMOTIONS_INTERVAL_SECONDS),
    ServiceJob("promotions.recheck_granted", _PROMO, "recheck_granted",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, DEFAULT_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS),
    ServiceJob("promotions.expire_enrollments", _PROMO, "expire_enrollments",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, DEFAULT_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS),
    ServiceJob("promotions.review_retired_parcel_enrollments", _PROMO, "review_retired_parcel_enrollments",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, DEFAULT_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS),
    ServiceJob("promotions.expire_lots", _PROMO, "expire_lots",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, DEFAULT_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS),
    ServiceJob("promotions.pause_exhausted_campaigns", _PROMO, "pause_exhausted_campaigns",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, DEFAULT_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS),
    ServiceJob("promotions.escalate_reviews", _PROMO, "escalate_reviews",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, DEFAULT_PROMOTIONS_HOUSEKEEPING_INTERVAL_SECONDS),
    ServiceJob("promotions.purge_identity_digests", _PROMO, "purge_identity_digests",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, 3600.0, max_batches=1),
    ServiceJob("promotions.purge_rate_events", _PROMO, "purge_rate_events",
               PROMOTIONS_HOUSEKEEPING_INTERVAL_ENV, 3600.0, max_batches=1),
    # A7 claims at most OUTBOX_BATCH_LIMIT events per call, so the job keeps batching while the queue is full.
    ServiceJob("communications.dispatch_outbox", "app.modules.communications.service", "dispatch_outbox",
               OUTBOX_INTERVAL_ENV, DEFAULT_OUTBOX_INTERVAL_SECONDS, batch_limit=OUTBOX_BATCH_LIMIT),
)


# Module-owned tasks that open their own session and take their own run_locked lock (A2 geo.jobs):
# called with no arguments; ``lock_key`` here is documentation of the owner's key.
GEO_SCAN_INTERVAL_ENV = "ELCHI_WORKER_GEO_SCAN_INTERVAL_SECONDS"
LOCKED_MODULE_TASKS: tuple[ServiceJob, ...] = (
    ServiceJob("geo.routing_cache_cleanup", "app.modules.geo.jobs", "routing_cache_cleanup_task",
               "ELCHI_WORKER_ROUTING_CACHE_CLEANUP_INTERVAL_SECONDS", ROUTING_CACHE_CLEANUP_INTERVAL_SECONDS),
    ServiceJob("geo.invariant_scan", "app.modules.geo.jobs", "geo_invariant_scan_task",
               GEO_SCAN_INTERVAL_ENV, 900.0),
    # A6 retention: partition create/drop through the SECURITY DEFINER functions of 0058 plus row purges.
    ServiceJob("tracking.retention", "app.modules.tracking.jobs", "retention_task",
               TRACKING_RETENTION_INTERVAL_ENV, DEFAULT_TRACKING_RETENTION_INTERVAL_SECONDS),
    # A7 push: claim -> commit -> provider send outside any transaction -> result. Returns 0 while U3 is pending.
    ServiceJob("communications.push_delivery", "app.modules.communications.jobs", "push_delivery_task",
               PUSH_INTERVAL_ENV, DEFAULT_PUSH_INTERVAL_SECONDS),
)


def resolve_service_function(job: ServiceJob) -> Callable[..., object] | None:
    """The owner's function, or None (logged) when it is not shipped yet or its module fails to import."""
    try:
        module = importlib.import_module(job.module)
    except Exception:  # noqa: BLE001 - a broken module must not take the worker (and other jobs) down
        logger.exception("worker_job_import_failed job=%s module=%s", job.name, job.module)
        return None
    fn = getattr(module, job.attribute, None)
    if not callable(fn):
        logger.warning("worker_job_pending job=%s expected=%s.%s", job.name, job.module, job.attribute)
        return None
    return fn


def run_service_job(
    job: ServiceJob,
    fn: Callable[..., object],
    *,
    engine: Engine | None = None,
    now: datetime | None = None,
) -> tuple[bool, int]:
    """Run ``job`` under its advisory lock; -> (ran, rows handled). Exceptions propagate after rollback."""
    from sqlalchemy.orm import Session

    if engine is None:
        from app.db.session import engine as default_engine

        engine = default_engine
    bound_engine = engine

    def batches() -> int:
        total = 0
        kwargs: dict[str, object] = {"limit": job.batch_limit}
        if now is not None:
            kwargs["now"] = now
        with Session(bound_engine) as session:
            for _ in range(job.max_batches):
                try:
                    handled = int(fn(session, **kwargs) or 0)
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise
                total += handled
                if handled < job.batch_limit:
                    break
        return total

    started = time.monotonic()
    ran, total = run_locked(job.lock_key, batches, engine=bound_engine)
    if ran and total:
        logger.info("worker_job_done job=%s handled=%d seconds=%.2f", job.name, total, time.monotonic() - started)
    return ran, int(total or 0)


def service_job_task(job: ServiceJob, fn: Callable[..., object], *, engine: Engine | None = None) -> Task:
    def task() -> None:
        run_service_job(job, fn, engine=engine)

    task.__name__ = f"job_{job.name.replace('.', '_')}"
    task.job_name = job.name  # type: ignore[attr-defined]
    return task


# Lock keys the module tasks take themselves (documentation for ``--list-jobs``; the owner's constant wins).
_OWNER_LOCK_KEYS = {
    "geo.routing_cache_cleanup": "geo.routing_cache_cleanup",
    "geo.invariant_scan": "geo.invariant_scan",
    "tracking.retention": "tracking.retention",
    "communications.push_delivery": "communications.push_delivery",
}


def describe_jobs(jobs: Sequence[ServiceJob] | None = None) -> list[dict[str, object]]:
    """Ops view (``python -m app.worker --list-jobs``): wired or pending per job. Imports modules, no DB."""
    selected = (*LOCKED_MODULE_TASKS, *SERVICE_JOBS) if jobs is None else tuple(jobs)
    return [
        {
            "job": job.name,
            "function": f"{job.module}.{job.attribute}",
            "interval_seconds": job.interval_seconds(),
            "lock_key": _OWNER_LOCK_KEYS.get(job.name, job.lock_key),
            "status": "wired" if resolve_service_function(job) is not None else "pending",
        }
        for job in selected
    ]


def register_default_tasks(tasks: list[Task] | None = None, *, jobs: Sequence[ServiceJob] = SERVICE_JOBS) -> list[Task]:
    """Register the scheduled jobs that exist today (idempotent). Called by ``python -m app.worker``.

    A job whose service function is not shipped yet (or whose module fails to import) is not
    registered and is logged as ``worker_job_pending`` / ``worker_job_import_failed``; the worker still starts.
    """
    target = TASKS if tasks is None else tasks
    for job in LOCKED_MODULE_TASKS:
        task = resolve_service_function(job)  # the owner's task takes its own run_locked lock
        if task is None or any(getattr(t, "wrapped_task", None) is task for t in target):
            continue
        target.append(every(job.interval_seconds(), task))
        logger.info("worker_job_registered job=%s interval_seconds=%g", job.name, job.interval_seconds())

    registered = {getattr(getattr(task, "wrapped_task", None), "job_name", None) for task in target}
    for job in jobs:
        if job.name in registered:
            continue
        fn = resolve_service_function(job)
        if fn is None:
            continue
        target.append(every(job.interval_seconds(), service_job_task(job, fn)))
        registered.add(job.name)
        logger.info("worker_job_registered job=%s interval_seconds=%g", job.name, job.interval_seconds())
    return target
