"""Communications contract (wave 3, A7): chat rules, outbox dispatch, consumer protocol (spec §15, §16; ADR-0012,
ADR-0020; Q43-Q45, Q65; N2/Q16).

Pure: stdlib + contracts only. Pilot defaults marked "(pilot)" can change through a contract update.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.contracts.enums import ChatThreadKind, EventType
from app.contracts.timeutil import ensure_aware_utc

# --- chat ---------------------------------------------------------------------------------------------------------

CHAT_TEXT_MAX_LENGTH = 1000
# Q65: 6-digit code-like chains are masked in chat (contact_filter.scan(text, mask_proof_codes=True)).
CHAT_MASK_PROOF_CODES = True
CHAT_MAX_MESSAGES_PER_MINUTE = 20  # (pilot) per author per thread -> 429 RATE_LIMITED
# (pilot) a booking chat stays writable this long after the booking's terminal time (lost item, support); aligned
# with the Q44 phone hide delay.
CHAT_WRITABLE_AFTER_TERMINAL = timedelta(hours=24)
# Attachments need a private upload type (H0, ADR-0015) and Q45 photo spot checks: off in wave 3
# (a request with attachment_file_id -> 400 VALIDATION_ERROR reason=chat_attachments_not_available).
CHAT_ATTACHMENTS_ENABLED = False


def chat_writable(
    *,
    kind: ChatThreadKind | str,
    now: datetime,
    proposal_thread_open: bool | None = None,
    booking_terminal_at: datetime | None = None,
) -> bool:
    """Whether a participant may post (read access is separate). Violation -> 409 CHAT_CLOSED.

    * proposal chat: only while the proposal thread is ``open`` (after accept the booking chat continues);
    * booking chat: until ``booking_terminal_at + CHAT_WRITABLE_AFTER_TERMINAL`` (never closed while non-terminal).
    """
    if ChatThreadKind(kind) is ChatThreadKind.PROPOSAL:
        return bool(proposal_thread_open)
    if booking_terminal_at is None:
        return True
    return ensure_aware_utc(now) < ensure_aware_utc(booking_terminal_at) + CHAT_WRITABLE_AFTER_TERMINAL


@dataclass(frozen=True, slots=True)
class ChatActivitySummary:
    """A7 export for A12 (Q45 quick-cancel-after-chat): counters and times only, never message text.

    Covers the booking chat and the chat of the booking's accepted proposal thread.
    """

    message_count: int
    first_message_at: datetime | None
    last_message_at: datetime | None
    contact_filter_hit_count: int
    last_contact_filter_hit_at: datetime | None


# --- outbox dispatch (ADR-0012 §4) ----------------------------------------------------------------------------------

OUTBOX_RETRY_SCHEDULE: tuple[timedelta, ...] = (
    timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6),
)
OUTBOX_MAX_ATTEMPTS = 10  # then dead_lettered_at + operator queue (N8/N9)
OUTBOX_BATCH_LIMIT = 100  # SELECT ... FOR UPDATE SKIP LOCKED LIMIT n
NOTIFICATION_DELIVERY_LEASE = timedelta(minutes=2)  # a claimed push delivery is retried after the lease expires
NOTIFICATION_DEDUP_WINDOW = timedelta(minutes=10)  # (pilot) §6.6: duplicate route pushes collapse into one
# ADR-0012 §9: a push payload carries only these keys; the client re-reads state through the API.
PUSH_PAYLOAD_KEYS: frozenset[str] = frozenset({"event_type", "aggregate_id", "title_key"})


def outbox_retry_delay(attempts: int) -> timedelta | None:
    """Delay before the next attempt after ``attempts`` failed attempts; ``None`` means dead-letter."""
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive int")
    if attempts >= OUTBOX_MAX_ATTEMPTS:
        return None
    return OUTBOX_RETRY_SCHEDULE[min(attempts, len(OUTBOX_RETRY_SCHEDULE)) - 1]


@dataclass(frozen=True, slots=True)
class DispatchedEvent:
    """Read-only view of one ``outbox_events`` row handed to consumers (A7 dispatcher -> A5/A12 consumers)."""

    event_id: uuid.UUID
    event_type: EventType
    aggregate_type: str
    aggregate_public_id: str
    aggregate_id: int | None
    aggregate_version: int
    occurred_at: datetime
    payload: Mapping[str, Any]


class EventConsumer(Protocol):
    """A domain consumer run by the A7 dispatcher inside the dispatcher's DB transaction.

    ``name`` is the ``consumer_receipts.consumer`` key (at-least-once delivery; the receipt is written in the same
    transaction, so a duplicate event is skipped). A consumer never commits, never calls an external API and only
    writes its own module's tables (AGENTS §4). Raising marks the event attempt failed (retry/backoff).
    """

    name: str
    event_types: frozenset[EventType]

    def __call__(self, session: Any, event: DispatchedEvent) -> None: ...
