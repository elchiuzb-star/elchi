"""Outbox consumer registry (WAVE1_CARDS "Wave 3" common rules; ``communications.EventConsumer``).

Each module listed in :data:`CONSUMER_MODULES` may expose ``CONSUMERS: tuple[EventConsumer, ...]`` and
``RELEVANCE_CHECKS: dict[EventType, Callable[[Session, DispatchedEvent], bool]]``. Modules are imported lazily; an
import error is logged and the dispatcher keeps running (modules of parallel agents may not exist yet).
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.contracts.communications import DispatchedEvent, EventConsumer
from app.contracts.enums import EventType
from app.modules.platform import outbox_dispatch

logger = logging.getLogger(__name__)

CONSUMER_MODULES: tuple[str, ...] = ("app.modules.trust_support.consumers", "app.modules.marketplace.feed.consumers")

RelevanceCheck = Callable[[Session, DispatchedEvent], bool]


@dataclass(frozen=True)
class ConsumerRegistry:
    consumers: tuple[EventConsumer, ...] = ()
    relevance_checks: dict[EventType, tuple[RelevanceCheck, ...]] = field(default_factory=dict)
    loaded_modules: tuple[str, ...] = ()
    failed_modules: tuple[str, ...] = ()


_cache: dict[tuple[str, ...], ConsumerRegistry] = {}


def reset_registry() -> None:
    _cache.clear()


def _valid_consumer(consumer: object) -> bool:
    name = getattr(consumer, "name", None)
    event_types = getattr(consumer, "event_types", None)
    return (
        isinstance(name, str)
        and 0 < len(name) <= 64
        and isinstance(event_types, (set, frozenset))
        and all(isinstance(item, EventType) for item in event_types)
        and callable(consumer)
    )


def load_registry(modules: Sequence[str] | None = None) -> ConsumerRegistry:
    """Import the consumer modules once per process (per module tuple); failures are logged, never raised."""
    key = tuple(CONSUMER_MODULES if modules is None else modules)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    consumers: list[EventConsumer] = []
    names: set[str] = set()
    checks: dict[EventType, list[RelevanceCheck]] = {}
    loaded: list[str] = []
    failed: list[str] = []
    for module_name in key:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            failed.append(module_name)
            if exc.name and module_name.startswith(exc.name):
                logger.info("outbox_consumer_module_pending module=%s", module_name)
            else:
                logger.exception("outbox_consumer_module_import_failed module=%s", module_name)
            continue
        except Exception:  # noqa: BLE001 - a broken module must not stop the dispatcher
            failed.append(module_name)
            logger.exception("outbox_consumer_module_import_failed module=%s", module_name)
            continue
        loaded.append(module_name)
        for consumer in getattr(module, "CONSUMERS", ()) or ():
            if not _valid_consumer(consumer):
                logger.error("outbox_consumer_invalid module=%s consumer=%r", module_name, consumer)
                continue
            if consumer.name in names:
                logger.error("outbox_consumer_duplicate_name module=%s name=%s", module_name, consumer.name)
                continue
            names.add(consumer.name)
            consumers.append(consumer)
        for event_type, check in dict(getattr(module, "RELEVANCE_CHECKS", {}) or {}).items():
            if not isinstance(event_type, EventType) or not callable(check):
                logger.error("outbox_relevance_check_invalid module=%s event_type=%r", module_name, event_type)
                continue
            checks.setdefault(event_type, []).append(check)
    registry = ConsumerRegistry(
        consumers=tuple(consumers),
        relevance_checks={event_type: tuple(items) for event_type, items in checks.items()},
        loaded_modules=tuple(loaded),
        failed_modules=tuple(failed),
    )
    _cache[key] = registry
    return registry


def run_consumers(session: Session, registry: ConsumerRegistry, event: DispatchedEvent, *, now: datetime) -> int:
    """Run every consumer subscribed to the event once (receipt in the same transaction). Exceptions propagate."""
    ran = 0
    for consumer in registry.consumers:
        if event.event_type not in consumer.event_types:
            continue
        if not outbox_dispatch.claim_receipt(session, consumer=consumer.name, event_id=event.event_id, now=now):
            continue  # duplicate delivery of an event this consumer already processed
        consumer(session, event)
        ran += 1
    return ran


def is_relevant(session: Session, registry: ConsumerRegistry, event: DispatchedEvent) -> bool:
    """All registered checks for the event type must say ``True`` (§6.6: cancelled/expired listing -> skipped)."""
    return all(check(session, event) for check in registry.relevance_checks.get(event.event_type, ()))
