"""Time handling for stage 2 (spec §14, ADR-0004).

* Storage: ``timestamptz`` in UTC. Application values are timezone-aware.
* API input: ISO-8601 with an explicit offset; naive or date-only values are
  rejected ("ertaga 13:00" must arrive as an exact instant).
* API output: UTC ISO-8601 with ``Z``.
* Display: ``Asia/Tashkent`` (clients format; server helpers exist for SMS/push text).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

UTC = timezone.utc
DISPLAY_TIMEZONE_NAME = "Asia/Tashkent"
# Uzbekistan has used a fixed UTC+05:00 without DST since 1992. Used only if the
# IANA database is missing from the runtime image.
_TASHKENT_FIXED = timezone(timedelta(hours=5), DISPLAY_TIMEZONE_NAME)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware_utc(value: datetime, *, field: str = "datetime") -> datetime:
    """Reject naive datetimes; normalise aware ones to UTC."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset")
    return value.astimezone(UTC)


def parse_iso_datetime(value: str, *, field: str = "datetime") -> datetime:
    """Parse ISO-8601 that *must* carry an offset (``Z`` or ``+05:00``)."""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if "T" not in text and " " not in text:
        raise ValueError(f"{field} must contain a date and a time")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid ISO-8601: {value!r}") from exc
    return ensure_aware_utc(parsed, field=field)


def to_iso_utc(value: datetime) -> str:
    """Serialize as UTC with ``Z`` suffix, e.g. ``2026-09-13T07:45:00Z``."""
    return ensure_aware_utc(value).isoformat().replace("+00:00", "Z")


def display_timezone() -> tzinfo:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            return ZoneInfo(DISPLAY_TIMEZONE_NAME)
        except ZoneInfoNotFoundError:
            return _TASHKENT_FIXED
    except ImportError:  # pragma: no cover - zoneinfo is stdlib since 3.9
        return _TASHKENT_FIXED


def to_display_time(value: datetime) -> datetime:
    return ensure_aware_utc(value).astimezone(display_timezone())


def legacy_naive_as_utc(value: datetime | None) -> datetime | None:
    """Interpret a value read from a legacy ``timestamp without time zone`` column.

    Legacy services write ``datetime.now(timezone.utc)`` into naive columns
    (e.g. ``orders.accepted_at``); PostgreSQL stores it converted to the session
    TimeZone. This helper is only correct if that TimeZone is UTC, which A10a
    must verify on production (ADR-0004) before any backfill uses it.
    """
    if value is None:
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


def windows_intersect(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    """Half-open interval intersection ``[start, end)`` on aware datetimes."""
    a0, a1 = ensure_aware_utc(start_a), ensure_aware_utc(end_a)
    b0, b1 = ensure_aware_utc(start_b), ensure_aware_utc(end_b)
    if a1 <= a0 or b1 <= b0:
        raise ValueError("window end must be after start")
    return a0 < b1 and b0 < a1
