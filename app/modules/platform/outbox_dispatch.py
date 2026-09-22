"""Outbox dispatch primitives (ADR-0012 §4; table A3, dispatch A7).

Every function takes the caller's session and never commits. The dispatcher
(``app.modules.communications.service.dispatch_outbox``) composes them:

    BEGIN
      claim_due_events            SELECT ... FOR UPDATE SKIP LOCKED LIMIT n (parallel dispatchers never share a row)
      per event: SAVEPOINT
        claim_receipt             INSERT consumer_receipts ON CONFLICT DO NOTHING (duplicate -> consumer skipped)
        consumer(session, event)  same transaction
        recipient deliveries      notification_deliveries ON CONFLICT DO NOTHING
      RELEASE -> mark_dispatched | ROLLBACK TO SAVEPOINT -> mark_failed (backoff / dead-letter)
    COMMIT

A crash before COMMIT leaves ``dispatched_at`` NULL and the row unlocked: the next run sends it again (AC33);
receipts and the delivery unique key make the second run a no-op for work that did commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.contracts.communications import OUTBOX_MAX_ATTEMPTS, DispatchedEvent, outbox_retry_delay
from app.contracts.enums import EventType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.platform.models import ConsumerReceipt, OutboxEvent

__all__ = [
    "LAST_ERROR_MAX_LENGTH",
    "OutboxAdminState",
    "OutboxRetry",
    "claim_due_events",
    "claim_receipt",
    "dispatched_event",
    "events_by_ids",
    "list_outbox_events",
    "lock_outbox_event",
    "mark_dispatched",
    "mark_failed",
    "retry_outbox_event",
]

LAST_ERROR_MAX_LENGTH = 500


def claim_due_events(session: Session, *, now: datetime, limit: int) -> list[OutboxEvent]:
    """Lock up to ``limit`` due, undispatched, not dead-lettered events (oldest first); locked rows are skipped."""
    if limit < 1:
        return []
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.dispatched_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
            OutboxEvent.next_attempt_at <= now,
        )
        .order_by(OutboxEvent.next_attempt_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return list(session.execute(stmt).scalars())


def dispatched_event(row: OutboxEvent) -> DispatchedEvent:
    """Read-only consumer view. Raises ``ValueError`` for an event type this code does not know."""
    return DispatchedEvent(
        event_id=row.event_id,
        event_type=EventType(row.event_type),
        aggregate_type=row.aggregate_type,
        aggregate_public_id=row.aggregate_public_id,
        aggregate_id=row.aggregate_id,
        aggregate_version=row.aggregate_version,
        occurred_at=row.occurred_at,
        payload=dict(row.payload or {}),
    )


def claim_receipt(session: Session, *, consumer: str, event_id: uuid.UUID, now: datetime) -> bool:
    """Insert the ``(consumer, event_id)`` receipt; ``False`` when the consumer already processed the event."""
    inserted = session.execute(
        pg_insert(ConsumerReceipt)
        .values(consumer=consumer, event_id=event_id, processed_at=now)
        .on_conflict_do_nothing(index_elements=["consumer", "event_id"])
        .returning(ConsumerReceipt.id)
    ).scalar_one_or_none()
    return inserted is not None


def mark_dispatched(session: Session, row: OutboxEvent, *, now: datetime) -> None:
    row.dispatched_at = now
    row.last_error = None
    session.flush()


def _error_text(error: BaseException | str) -> str:
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return text[:LAST_ERROR_MAX_LENGTH]


def mark_failed(session: Session, row: OutboxEvent, *, now: datetime, error: BaseException | str) -> str:
    """``attempts + 1`` and the next backoff slot, or dead-letter after ``OUTBOX_MAX_ATTEMPTS``; -> ``retry|dead``."""
    row.attempts = int(row.attempts or 0) + 1
    row.last_error = _error_text(error)
    delay = outbox_retry_delay(min(row.attempts, OUTBOX_MAX_ATTEMPTS))
    if delay is None:
        row.dead_lettered_at = now
        outcome = "dead"
    else:
        row.next_attempt_at = now + delay
        outcome = "retry"
    session.flush()
    return outcome


# --- operator queue (N8/N9) -----------------------------------------------------------------------------------------


class OutboxAdminState:
    FAILED = "failed"  # attempted at least once, still retrying
    DEAD = "dead"  # dead-lettered


@dataclass(frozen=True, slots=True)
class OutboxRetry:
    event: OutboxEvent
    previous_attempts: int
    was_dead: bool


def list_outbox_events(session: Session, *, state: str, after_id: int | None, limit: int) -> list[OutboxEvent]:
    """Newest first by id; ``after_id`` is the last id of the previous page."""
    if state == OutboxAdminState.DEAD:
        condition = OutboxEvent.dead_lettered_at.is_not(None)
    elif state == OutboxAdminState.FAILED:
        condition = and_(
            OutboxEvent.dispatched_at.is_(None), OutboxEvent.dead_lettered_at.is_(None), OutboxEvent.attempts > 0
        )
    else:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "state", "allowed": ["failed", "dead"]})
    stmt = select(OutboxEvent).where(condition)
    if after_id is not None:
        stmt = stmt.where(OutboxEvent.id < after_id)
    return list(session.execute(stmt.order_by(OutboxEvent.id.desc()).limit(limit)).scalars())


def lock_outbox_event(session: Session, event_id: uuid.UUID) -> OutboxEvent:
    row = session.execute(
        select(OutboxEvent).where(OutboxEvent.event_id == event_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


def retry_outbox_event(session: Session, event_id: uuid.UUID, *, now: datetime) -> OutboxRetry:
    """N9: a failed or dead-lettered event gets a fresh schedule now; dispatched/untried -> 409."""
    row = lock_outbox_event(session, event_id)
    was_dead = row.dead_lettered_at is not None
    if row.dispatched_at is not None or (not was_dead and int(row.attempts or 0) == 0):
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            details={"state": "dispatched" if row.dispatched_at is not None else "pending"},
        )
    previous = int(row.attempts or 0)
    row.dead_lettered_at = None
    row.attempts = 0
    row.next_attempt_at = now
    session.flush()
    return OutboxRetry(row, previous, was_dead)


def events_by_ids(session: Session, event_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, OutboxEvent]:
    if not event_ids:
        return {}
    rows = session.execute(select(OutboxEvent).where(OutboxEvent.event_id.in_(list(event_ids)))).scalars()
    return {row.event_id: row for row in rows}
