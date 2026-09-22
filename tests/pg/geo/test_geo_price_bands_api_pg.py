"""HTTP tests for G12-G14 corridor price bands (Q42): capabilities, idempotency, versions, history."""

from __future__ import annotations

import uuid

import pytest

from tests.pg.conftest import PgDatabase
from tests.pg.geo.test_geo_api_pg import Harness, err, ok

pytestmark = pytest.mark.pg


@pytest.fixture
def h(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(pg_db, monkeypatch)


def test_price_band_endpoints(h: Harness) -> None:
    corridor = h.fixture.corridor.api_id
    toshkent, qarshi = h.fixture.stops["toshkent"].api_id, h.fixture.stops["qarshi"].api_id
    base = f"/admin/corridors/{corridor}/price-bands"
    body = {"floor_minor": 10_000_00, "ceiling_minor": 50_000_00, "reason": "pilot pricing"}

    assert ok(h.call("GET", base, as_="operator")) == []
    err(h.call("GET", base, as_="client"), 403, "FORBIDDEN")
    err(h.call("PUT", f"{base}/passenger", as_="operator", key=True, json=body), 403, "FORBIDDEN")
    err(h.call("PUT", f"{base}/passenger", as_="admin", json=body), 400, "IDEMPOTENCY_KEY_REQUIRED")
    invalid = err(h.call("PUT", f"{base}/passenger", as_="admin", key=True, json=dict(body, floor_minor=60_000_00)), 400, "VALIDATION_ERROR")
    assert invalid["details"]["reason"] == "floor_above_ceiling"
    err(h.call("PUT", f"{base}/passenger", as_="admin", key=True, json=dict(body, floor_minor=0)), 400, "VALIDATION_ERROR")
    err(h.call("PUT", f"{base}/bus", as_="admin", key=True, json=body), 400, "VALIDATION_ERROR")
    err(h.call("PUT", "/admin/corridors/cor_aaaaaaaaaaaaaaaaaaaaaaaaaa/price-bands/passenger", as_="admin", key=True, json=body), 404, "NOT_FOUND")

    key = "band-" + uuid.uuid4().hex
    created = h.call("PUT", f"{base}/passenger", as_="admin", key=key, json=body)
    band = ok(created)
    assert band["price_basis"] == "per_seat" and band["version"] == 1 and band["origin_stop_id"] is None and band["currency"] == "UZS"
    assert band["updated_by"].startswith("usr_")
    replay = h.call("PUT", f"{base}/passenger", as_="admin", key=key, json=body)
    assert replay.json() == created.json() and replay.headers.get("Idempotent-Replayed") == "true"

    segment_body = dict(body, origin_stop_id=toshkent, destination_stop_id=qarshi, floor_minor=20_000_00, ceiling_minor=30_000_00)
    segment = ok(h.call("PUT", f"{base}/passenger", as_="admin", key=True, json=segment_body))
    assert segment["origin_stop_id"] == toshkent and segment["destination_stop_id"] == qarshi
    err(h.call("PUT", f"{base}/passenger", as_="admin", key=True, json=segment_body), 409, "VERSION_CONFLICT")
    retired = ok(h.call("PUT", f"{base}/passenger", as_="admin", key=True, json=dict(segment_body, expected_version=1, is_active=False, reason="retire")))
    assert retired["version"] == 2 and retired["is_active"] is False
    parcel = ok(h.call("PUT", f"{base}/parcel", as_="admin", key=True, json=dict(body, floor_minor=40_000_00, ceiling_minor=90_000_00)))
    assert parcel["price_basis"] == "total"

    listed = ok(h.call("GET", base, as_="operator"))
    assert [(b["service_type"], b["origin_stop_id"], b["version"]) for b in listed] == [("parcel", None, 1), ("passenger", None, 1), ("passenger", toshkent, 2)]

    page = h.call("GET", f"{base}/history", as_="operator", params={"limit": 2})
    first = ok(page)
    assert [(c["service_type"], c["version"], c["new_is_active"]) for c in first] == [("parcel", 1, True), ("passenger", 2, False)]
    assert first[1]["old_is_active"] is True and first[1]["reason"] == "retire" and first[1]["actor"].startswith("usr_")
    rest = ok(h.call("GET", f"{base}/history", as_="operator", params={"limit": 2, "cursor": page.json()["meta"]["next_cursor"]}))
    assert [(c["version"], c["origin_stop_id"]) for c in rest] == [(1, toshkent), (1, None)]
    err(h.call("GET", f"{base}/history", as_="operator", params={"cursor": "bogus"}), 400, "INVALID_CURSOR")
