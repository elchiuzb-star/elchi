"""Wave 1.5 contract additions: DetourQuote snapshot (Q25), COMMISSION_POLICY_UNCONFIRMED (Q28)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.detour import DEFAULT_DETOUR_QUOTE_TTL, DetourQuote, detour_legs_conflict, total_detour_seconds
from app.contracts.errors import ErrorCode, http_status_for

T0 = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)


def _quote(after_seq: int = 1, extra_s: int = 300, **overrides) -> DetourQuote:
    values = dict(
        route_version_id="rtv_abc",
        trip_version=3,
        after_seq=after_seq,
        extra_s=extra_s,
        extra_m=2_500,
        measured_at=T0,
        expires_at=T0 + DEFAULT_DETOUR_QUOTE_TTL,
    )
    values.update(overrides)
    return DetourQuote(**values)


def test_detour_quote_is_bound_to_versions_and_expiry() -> None:
    quote = _quote()
    assert quote.is_valid_for(route_version_id="rtv_abc", trip_version=3, now=T0 + timedelta(minutes=5))
    assert not quote.is_valid_for(route_version_id="rtv_other", trip_version=3, now=T0)
    assert not quote.is_valid_for(route_version_id="rtv_abc", trip_version=4, now=T0)
    assert not quote.is_valid_for(route_version_id="rtv_abc", trip_version=3, now=T0 + DEFAULT_DETOUR_QUOTE_TTL)


@pytest.mark.parametrize(
    "overrides",
    [
        {"extra_s": -1},
        {"extra_m": 1.5},
        {"trip_version": 0},
        {"after_seq": True},
        {"route_version_id": ""},
        {"expires_at": T0},
        {"measured_at": datetime(2026, 9, 14, 8, 0)},
    ],
)
def test_detour_quote_validation(overrides: dict) -> None:
    with pytest.raises((ValueError, TypeError)):
        _quote(**overrides)


def test_two_detours_on_same_leg_conflict_q25() -> None:
    assert not detour_legs_conflict([_quote(after_seq=1), _quote(after_seq=2)])
    assert detour_legs_conflict([_quote(after_seq=2), _quote(after_seq=2)])
    assert total_detour_seconds([_quote(extra_s=300), _quote(after_seq=2, extra_s=120)]) == 420


def test_commission_policy_unconfirmed_code_q28() -> None:
    assert http_status_for(ErrorCode.COMMISSION_POLICY_UNCONFIRMED) == 503
