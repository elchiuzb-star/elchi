"""ADR-0027 Q157: a driver's time proposal - at most 3 h earlier or 12 h later than the client's window (pure rule)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.marketplace.rules import time_proposal_in_range

TZ = timezone(timedelta(hours=5))
START, END = datetime(2026, 10, 7, 7, 55, tzinfo=TZ), datetime(2026, 10, 7, 8, 55, tzinfo=TZ)
LIMITS = {"max_early": timedelta(hours=3), "max_late": timedelta(hours=12)}


@pytest.mark.parametrize(
    ("pickup", "allowed"),
    [
        (datetime(2026, 10, 7, 4, 55, tzinfo=TZ), True),  # exactly 3 h before the window starts
        (datetime(2026, 10, 7, 4, 54, tzinfo=TZ), False),
        (datetime(2026, 10, 6, 23, 43, tzinfo=TZ), False),  # the 06.10 e2e case: 8 h earlier
        (datetime(2026, 10, 7, 20, 55, tzinfo=TZ), True),  # exactly 12 h after the window ends
        (datetime(2026, 10, 7, 20, 56, tzinfo=TZ), False),
    ],
)
def test_asymmetric_limits(pickup: datetime, allowed: bool) -> None:
    assert time_proposal_in_range(request_start=START, request_end=END, pickup_at=pickup, **LIMITS) is allowed


def test_defaults_are_three_and_twelve_hours() -> None:
    from app.core.config import Settings

    fields = Settings.model_fields
    assert fields["time_proposal_max_early_shift_minutes"].default == 180
    assert fields["time_proposal_max_late_shift_minutes"].default == 720
