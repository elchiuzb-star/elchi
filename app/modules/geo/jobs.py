"""Geo background jobs (worker-callable; scheduling is A7/A10a's).

``routing_cache`` rows expire (``expires_at``) but are never read after expiry; this job deletes
them in small batches so no long lock or large transaction is held (BR N4).

Wiring (worker owner):

    from app.modules.geo.jobs import routing_cache_cleanup_task
    TASKS.append(routing_cache_cleanup_task)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

ROUTING_CACHE_CLEANUP_LOCK_KEY = "geo.routing_cache_cleanup"
DEFAULT_BATCH_SIZE = 500
DEFAULT_MAX_BATCHES = 100


def purge_expired_routing_cache_batch(session: Session, *, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Delete up to ``batch_size`` expired rows (``SKIP LOCKED``). Does not commit; returns rows deleted."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    result = session.execute(
        text(
            "DELETE FROM routing_cache WHERE id IN ("
            " SELECT id FROM routing_cache WHERE expires_at <= now() ORDER BY id LIMIT :n FOR UPDATE SKIP LOCKED)"
        ),
        {"n": batch_size},
    )
    return int(result.rowcount or 0)


def cleanup_routing_cache(
    *, engine: Engine | None = None, batch_size: int = DEFAULT_BATCH_SIZE, max_batches: int = DEFAULT_MAX_BATCHES
) -> int:
    """Delete expired rows batch by batch, one short transaction per batch. Idempotent."""
    if engine is None:
        from app.db.session import engine as default_engine

        engine = default_engine
    total = 0
    for _ in range(max_batches):
        with Session(engine) as session:
            deleted = purge_expired_routing_cache_batch(session, batch_size=batch_size)
            session.commit()
        total += deleted
        if deleted < batch_size:
            break
    if total:
        logger.info("geo_routing_cache_cleanup deleted=%s", total)
    return total


def routing_cache_cleanup_task(*, engine: Engine | None = None) -> int:
    """Worker task: runs ``cleanup_routing_cache`` under ``run_locked`` (one replica at a time)."""
    from app.worker import run_locked

    ran, deleted = run_locked(ROUTING_CACHE_CLEANUP_LOCK_KEY, lambda: cleanup_routing_cache(engine=engine), engine=engine)
    return int(deleted or 0) if ran else 0


# --- geo invariant scan (alert signal; read-only) ---------------------------------------------------------

GEO_INVARIANT_SCAN_LOCK_KEY = "geo.invariant_scan"


def scan_geo_invariants(session: Session) -> list[dict[str, object]]:
    """Q47 corridor violations and production flag violations (``service.production_invariant_notices``).

    Read-only: takes no row locks and never commits. Each finding is logged as a warning (``geo_invariant_violation``)
    so monitoring can alert; nothing is repaired automatically (repair runbook: ``app.modules.geo.checks``).
    """
    from app.modules.geo.service import production_invariant_notices

    findings = production_invariant_notices(session)
    for finding in findings:
        logger.warning("geo_invariant_violation %s", finding)
    return findings


def run_geo_invariant_scan(*, engine: Engine | None = None) -> int:
    """One short read-only transaction (rolled back); returns the number of findings."""
    if engine is None:
        from app.db.session import engine as default_engine

        engine = default_engine
    with Session(engine) as session:
        try:
            return len(scan_geo_invariants(session))
        finally:
            session.rollback()


def geo_invariant_scan_task(*, engine: Engine | None = None) -> int:
    """Worker task: ``run_geo_invariant_scan`` under ``run_locked`` (one replica at a time); 0 when skipped."""
    from app.worker import run_locked

    ran, found = run_locked(GEO_INVARIANT_SCAN_LOCK_KEY, lambda: run_geo_invariant_scan(engine=engine), engine=engine)
    return int(found or 0) if ran else 0
