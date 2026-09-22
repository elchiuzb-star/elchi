"""Outbox consumers of the trust & support module (A7 dispatcher loads ``CONSUMERS`` lazily, ADR-0012).

Each consumer runs inside the dispatcher's transaction, never commits, never calls an external API and writes only
trust & support tables (plus staff-only outbox events). ``consumer_receipts`` deduplicates redelivered events; the
tables are idempotent on their own as well (``UNIQUE(source_event_id)``, evidence merge).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.contracts.communications import DispatchedEvent
from app.contracts.enums import EventType
from app.modules.trust_support import service


@dataclass(frozen=True)
class TrustConsumer:
    """``communications.EventConsumer`` implementation."""

    name: str
    event_types: frozenset[EventType]
    handler: Callable[[Any, DispatchedEvent], None]

    def __call__(self, session: Any, event: DispatchedEvent) -> None:
        if EventType(event.event_type) in self.event_types:
            self.handler(session, event)


contact_filter_strikes = TrustConsumer(
    name="contact_filter_strikes",
    event_types=frozenset({EventType.CONTACT_FILTER_HIT}),
    handler=service.consume_contact_filter_hit,
)

cancellation_signals = TrustConsumer(
    name="cancellation_signals",
    event_types=frozenset({EventType.BOOKING_CANCELLED}),
    handler=service.consume_booking_cancelled,
)

CONSUMERS: tuple[TrustConsumer, ...] = (contact_filter_strikes, cancellation_signals)

# No relevance checks: trust events are staff-only or state changes that stay true.
RELEVANCE_CHECKS: dict[EventType, Callable[[Any, DispatchedEvent], bool]] = {}
