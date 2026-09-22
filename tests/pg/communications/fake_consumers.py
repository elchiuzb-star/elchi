"""TEST-ONLY consumer module for the A7 dispatcher (stands in for A5/A12 consumers until they are delivered).

Loaded through ``communications.dispatch.CONSUMER_MODULES`` (monkeypatched). The counting consumer writes one
``audit_logs`` row per processed event so tests can count side effects; ``STATE`` toggles failure and relevance.
"""

from __future__ import annotations

from sqlalchemy import text

from app.contracts.communications import DispatchedEvent
from app.contracts.enums import EventType

STATE: dict[str, object] = {"fail": False, "relevant": True}


class CountingConsumer:
    name = "test.counting"
    event_types = frozenset({EventType.TRUST_WARNING_ISSUED, EventType.LISTING_PUBLISHED})

    def __call__(self, session, event: DispatchedEvent) -> None:  # noqa: ANN001
        session.execute(
            text("INSERT INTO audit_logs (entity_type, action, details) VALUES ('fake_consumer', 'consumed', CAST(:d AS json))"),
            {"d": f'{{"event_id": "{event.event_id}", "event_type": "{event.event_type.value}"}}'},
        )


class ExplodingConsumer:
    name = "test.exploding"
    event_types = frozenset({EventType.TRUST_WARNING_ISSUED})

    def __call__(self, session, event: DispatchedEvent) -> None:  # noqa: ANN001
        if STATE["fail"]:
            raise RuntimeError("consumer failure requested by test")


def chat_still_relevant(session, event: DispatchedEvent) -> bool:  # noqa: ANN001
    return bool(STATE["relevant"])


CONSUMERS = (CountingConsumer(), ExplodingConsumer(), "not a consumer")
RELEVANCE_CHECKS = {EventType.CHAT_MESSAGE_CREATED: chat_still_relevant}
