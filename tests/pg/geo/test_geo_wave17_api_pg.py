"""Wave 1.7 HTTP: F1 public-corridor check endpoint (ADR-0028: a confirmed road) and G13 corridor-wide bands (Q160)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.pg.conftest import PgDatabase
from tests.pg.geo.test_geo_api_pg import Harness, err, ok

pytestmark = pytest.mark.pg


@pytest.fixture
def h(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(pg_db, monkeypatch)


def test_a_corridor_band_stands_alone_with_no_warning(h: Harness) -> None:
    """Q160: there is no stop pair to price, so the corridor band has nothing to be compared with - no warning."""
    base = f"/admin/corridors/{h.fixture.corridor.api_id}/price-bands/passenger"
    wide = h.call("PUT", base, as_="admin", key=True, json={"floor_minor": 10_000_00, "ceiling_minor": 90_000_00, "reason": "safety"})
    ok(wide)
    assert "warnings" not in wide.json()


def test_q47_check_endpoint(h: Harness) -> None:
    path = "/admin/geo/checks/q47"
    assert ok(h.call("GET", path, as_="operator")) == []
    err(h.call("GET", path, as_="client"), 403, "FORBIDDEN")
    fx = h.fixture
    with h.pg_db.engine.begin() as conn:  # legacy/bypassed data: the public corridor's road back to draft
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("UPDATE route_versions SET status = 'draft', confirmed_at = NULL WHERE corridor_id = :c"), {"c": fx.corridor.id})
    items = ok(h.call("GET", path, as_="operator"))
    assert items == [
        {
            "corridor_id": fx.corridor.api_id,
            "name": fx.corridor.name,
            "rollout_state": "pilot",
            "reasons": ["needs_confirmed_road"],
        }
    ]
