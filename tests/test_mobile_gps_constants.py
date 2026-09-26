"""Q148: the web GPS publisher's limits stay equal to the tracking contract (spec §10.3-§10.4).

`mobile-app/src/app/gpsOutbox.ts` mirrors `app/contracts/tracking.py` by hand (the client cannot import Python). A
point the client builds outside these bounds fails the whole batch with 422, and a queue longer than the contract's
is history the server would refuse - so a drift is a bug, caught here.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.contracts import tracking

OUTBOX = Path(__file__).resolve().parent.parent / "mobile-app" / "src" / "app" / "gpsOutbox.ts"


def _constants() -> dict[str, int]:
    text = OUTBOX.read_text(encoding="utf-8")
    values: dict[str, int] = {}
    for name, expression in re.findall(r"export const ([A-Z_]+) = ([0-9_ *]+);", text):
        product = 1
        for factor in expression.split("*"):
            product *= int(factor.strip().replace("_", ""))
        values[name] = product
    return values


def test_outbox_limits_match_the_contract() -> None:
    values = _constants()
    assert values["MAX_POINTS_PER_BATCH"] == tracking.MAX_POINTS_PER_BATCH
    assert values["LOCAL_QUEUE_MAX_POINTS"] == tracking.LOCAL_QUEUE_MAX_POINTS
    assert values["LOCAL_QUEUE_MAX_AGE_MS"] == int(tracking.LOCAL_QUEUE_MAX_AGE.total_seconds() * 1000)
    assert values["MAX_ACCURACY_M"] == tracking.MAX_ACCURACY_M
    assert values["MAX_SPEED_MPS_INPUT"] == tracking.MAX_SPEED_MPS_INPUT


def test_send_cadence_and_freshness_match_the_contract() -> None:
    values = _constants()
    assert values["SEND_INTERVAL_MOVING_SECONDS"] == tracking.SEND_INTERVAL_MOVING_SECONDS
    low, high = tracking.SEND_INTERVAL_WAITING_SECONDS
    assert low <= values["SEND_INTERVAL_WAITING_SECONDS"] <= high
    assert values["FRESH_MAX_AGE_SECONDS"] == tracking.FRESH_MAX_AGE_SECONDS
    assert values["DELAYED_MAX_AGE_SECONDS"] == tracking.DELAYED_MAX_AGE_SECONDS


def test_publishable_trip_statuses_match_the_server() -> None:
    from app.modules.tracking.rules import PUBLISHABLE_TRIP_STATUSES

    text = OUTBOX.read_text(encoding="utf-8")
    match = re.search(r"PUBLISHABLE_TRIP_STATUSES: ReadonlySet<string> = new Set\(\[([^\]]*)\]\)", text)
    assert match, "PUBLISHABLE_TRIP_STATUSES not found in gpsOutbox.ts"
    assert set(re.findall(r'"([a-z_]+)"', match.group(1))) == set(PUBLISHABLE_TRIP_STATUSES)
