"""Communications worker tasks (A7). Wiring belongs to A10a (``app/worker``):

* ServiceJob ``communications.dispatch_outbox`` -> ``app.modules.communications.service.dispatch_outbox``
  (``fn(session, *, now=None, limit=200) -> int``; handles at most ``OUTBOX_BATCH_LIMIT`` events per call, so use
  ``batch_limit=OUTBOX_BATCH_LIMIT`` for the job to keep batching while the queue is full).
* Locked module task ``communications.push_delivery`` -> :func:`push_delivery_task` (no arguments; own sessions;
  ``run_locked``): lease claim -> commit -> provider send OUTSIDE any transaction -> result transaction.
  With the default disabled provider (Q82: in-app only until a provider ADR) it returns 0 without touching the database.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.contracts.timeutil import utc_now
from app.modules.communications import service
from app.modules.communications.providers import PushProvider, PushResult, get_push_provider

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

PUSH_DELIVERY_LOCK_KEY = "communications.push_delivery"
PUSH_BATCH_LIMIT = 100


def deliver_push_batch(
    *, engine: Engine | None = None, provider: PushProvider | None = None, now: datetime | None = None, limit: int = PUSH_BATCH_LIMIT
) -> int:
    """One claim/send/result round; returns the number of sends attempted."""
    provider = provider or get_push_provider()
    if not provider.enabled:
        return 0
    if engine is None:
        from app.db.session import engine as default_engine

        engine = default_engine
    claim_time = now or utc_now()
    with Session(engine, expire_on_commit=False) as session:
        try:
            claims = service.claim_push_deliveries(session, provider=provider, now=claim_time, limit=limit)
            session.commit()
        except BaseException:
            session.rollback()
            raise
    if not claims:
        return 0
    results: list[PushResult] = []
    for claim in claims:  # external calls: no DB transaction open here (spec §15)
        try:
            results.append(provider.send(claim.message))
        except Exception as exc:  # noqa: BLE001 - a provider error is a failed attempt, never a crash (AC34)
            logger.warning("push_send_failed delivery=%s error=%s", claim.message.delivery_id, type(exc).__name__)
            results.append(PushResult(False, type(exc).__name__))
    with Session(engine) as session:
        try:
            for claim, result in zip(claims, results, strict=True):
                service.record_push_result(session, claim, result, now=now or utc_now())
            session.commit()
        except BaseException:
            session.rollback()
            raise
    return len(claims)


def push_delivery_task(*, engine: Engine | None = None) -> int:
    """Worker task: :func:`deliver_push_batch` under ``run_locked`` (one replica at a time); 0 when skipped."""
    if not get_push_provider().enabled:
        return 0
    from app.worker import run_locked

    ran, handled = run_locked(PUSH_DELIVERY_LOCK_KEY, lambda: deliver_push_batch(engine=engine), engine=engine)
    return int(handled or 0) if ran else 0
