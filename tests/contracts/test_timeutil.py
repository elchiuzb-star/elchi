from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.timeutil import (
    UTC,
    ensure_aware_utc,
    legacy_naive_as_utc,
    parse_iso_datetime,
    to_display_time,
    to_iso_utc,
    utc_now,
    windows_intersect,
)


def test_utc_now_is_aware() -> None:
    assert utc_now().utcoffset() == timedelta(0)


def test_parse_with_tashkent_offset_normalises_to_utc() -> None:
    parsed = parse_iso_datetime("2026-09-13T12:45:00+05:00")
    assert parsed == datetime(2026, 9, 13, 7, 45, tzinfo=UTC)
    assert parsed.tzinfo == UTC


def test_parse_accepts_z_suffix() -> None:
    assert parse_iso_datetime("2026-09-13T07:45:00Z") == datetime(2026, 9, 13, 7, 45, tzinfo=UTC)


@pytest.mark.parametrize("value", ["2026-09-13T12:45:00", "2026-09-13", "tomorrow 13:00", "13:00"])
def test_parse_rejects_naive_or_date_only(value: str) -> None:
    with pytest.raises(ValueError):
        parse_iso_datetime(value)


def test_ensure_aware_rejects_naive() -> None:
    with pytest.raises(ValueError):
        ensure_aware_utc(datetime(2026, 9, 13, 12, 0))


def test_to_iso_utc_uses_z() -> None:
    value = datetime(2026, 9, 13, 12, 45, tzinfo=timezone(timedelta(hours=5)))
    assert to_iso_utc(value) == "2026-09-13T07:45:00Z"


def test_display_time_is_tashkent_offset() -> None:
    shown = to_display_time(datetime(2026, 9, 13, 7, 45, tzinfo=UTC))
    assert shown.utcoffset() == timedelta(hours=5)
    assert (shown.hour, shown.minute) == (12, 45)


def test_legacy_naive_values_are_read_as_utc() -> None:
    assert legacy_naive_as_utc(None) is None
    assert legacy_naive_as_utc(datetime(2026, 9, 13, 7, 45)) == datetime(2026, 9, 13, 7, 45, tzinfo=UTC)


def test_windows_are_half_open() -> None:
    t = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    assert windows_intersect(t, t + hour, t + timedelta(minutes=30), t + 2 * hour)
    assert not windows_intersect(t, t + hour, t + hour, t + 2 * hour)
    with pytest.raises(ValueError):
        windows_intersect(t, t, t, t + hour)
