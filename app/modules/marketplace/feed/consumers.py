"""Outbox consumers of the feed (A5), loaded lazily by A7's dispatcher (``communications.dispatch.CONSUMER_MODULES``).

* ``saved_search_matcher`` - ``listing.published`` -> ``saved_search.matched`` (one per user and listing, §6.6).
* ``RELEVANCE_CHECKS`` - before a ``saved_search.matched`` push A7 asks whether it is still relevant
  (listing published and not expired, search not deleted and notifying).

Consumers never commit, never call external APIs and write only the feed tables and outbox events.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.contracts.communications import DispatchedEvent
from app.contracts.enums import EventType
from app.contracts.errors import DomainError
from app.modules.marketplace.feed import service as feed_service


class SavedSearchMatcher:
    name = "saved_search_matcher"
    event_types: frozenset[EventType] = frozenset({EventType.LISTING_PUBLISHED})

    def __call__(self, session: Any, event: DispatchedEvent) -> None:
        if EventType(event.event_type) is not EventType.LISTING_PUBLISHED:
            return
        listing_id = event.aggregate_id
        if listing_id is None:
            from app.modules.marketplace import service as marketplace_service

            try:
                listing_id = marketplace_service.resolve_listing_id(session, event.aggregate_public_id)
            except DomainError:
                return
        feed_service.match_saved_searches_for_listing(session, listing_id)


saved_search_matcher = SavedSearchMatcher()

CONSUMERS: tuple[SavedSearchMatcher, ...] = (saved_search_matcher,)

RELEVANCE_CHECKS: dict[EventType, Callable[[Any, DispatchedEvent], bool]] = {
    EventType.SAVED_SEARCH_MATCHED: feed_service.saved_search_match_still_relevant,
}
