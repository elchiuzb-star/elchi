"""v1 wire compatibility for the legacy timestamps typed by migration 0066 (Q9, AGENTS §2).

Until wave 5 the v1 lifecycle columns (``orders.published_at``, ``disputes.resolved_at``,
``driver_documents.reviewed_at``, ...) were ``timestamp without time zone``, so a v1 response carried them as
``"2026-09-16T19:48:44"`` - no offset. Migration 0066 gives them ``timestamptz`` (UTC, proven against the data),
which would make FastAPI serialize the very same instant as ``"2026-09-16T19:48:44+00:00"``.

The frozen Android client parses those strings, and the v1 contract says the response shape does not change
(AGENTS §2), so every v1 handler passes such a value through :func:`v1_naive`: the instant is converted to UTC and
the offset is dropped, which reproduces the old string exactly. Nothing is shifted - only the suffix is removed.

v2 never uses this: v2 DTOs require aware datetimes and serialize with ``Z`` (ADR-0005). Columns that were always
``timestamptz`` (``created_at``, ``updated_at``) keep their offset in v1 as before; this helper is only for the
columns 0066 converted.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["v1_naive"]


def v1_naive(value: datetime | None) -> datetime | None:
    """Return ``value`` as a naive UTC datetime, exactly as v1 returned it before migration 0066."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
