"""Wave 1.7 HTTP: F1 Q47 check endpoint and the Q53 price band warning on G13."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase
from tests.pg.geo.test_geo_api_pg import Harness, err, ok

pytestmark = pytest.mark.pg


@pytest.fixture
def h(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(pg_db, monkeypatch)


def test_price_band_warning_when_corridor_floor_exceeds_segment_floor(h: Harness) -> None:
    base = f"/admin/corridors/{h.fixture.corridor.api_id}/price-bands/passenger"
    toshkent, qarshi = h.fixture.stops["toshkent"].api_id, h.fixture.stops["qarshi"].api_id
    wide = h.call("PUT", base, as_="admin", key=True, json={"floor_minor": 10_000_00, "ceiling_minor": 90_000_00, "reason": "safety"})
    ok(wide)
    assert "warnings" not in wide.json()
    segment = h.call(
        "PUT", base, as_="admin", key="band-seg-" + uuid.uuid4().hex,
        json={"origin_stop_id": toshkent, "destination_stop_id": qarshi, "floor_minor": 5_000_00, "ceiling_minor": 8_000_00, "reason": "real price"},
    )
    assert ok(segment)["origin_stop_id"] == toshkent  # saved; the warning is non-fatal
    warnings = segment.json()["warnings"]
    assert [w["code"] for w in warnings] == ["CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR"]
    assert warnings[0]["details"] == {"service_type": "passenger", "corridor_floor_minor": 10_000_00, "lowest_segment_floor_minor": 5_000_00}
    assert "loose safety limits" in warnings[0]["message"]
    parcel = h.call("PUT", f"/admin/corridors/{h.fixture.corridor.api_id}/price-bands/parcel", as_="admin", key=True, json={"floor_minor": 1, "ceiling_minor": 2, "reason": "x"})
    assert "warnings" not in parcel.json()


def test_q47_check_endpoint(h: Harness) -> None:
    path = "/admin/geo/checks/q47"
    assert ok(h.call("GET", path, as_="operator")) == []
    err(h.call("GET", path, as_="client"), 403, "FORBIDDEN")
    fx = h.fixture
    with h.pg_db.engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))  # simulate pre-0046 data
        conn.execute(text("UPDATE corridor_stops SET meeting_note = NULL WHERE id = :id"), {"id": fx.stop_id("kitob")})
    items = ok(h.call("GET", path, as_="operator"))
    assert items == [
        {
            "corridor_id": fx.corridor.api_id,
            "name": fx.corridor.name,
            "rollout_state": "pilot",
            "active_stops": 6,
            "stops_missing_evidence": [fx.stops["kitob"].api_id],
            "reasons": ["stops_missing_meeting_evidence"],
        }
    ]
