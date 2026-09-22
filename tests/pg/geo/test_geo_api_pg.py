"""HTTP tests for G1-G11 and F1-F4 on PostgreSQL + PostGIS, including idempotent replays (BR #7)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_current_user
from app.api.v2.web import domain_error_handler
from app.contracts.enums import Capability
from app.contracts.errors import DomainError
from app.db.session import get_db
from app.models import User
from app.modules.geo import api as geo_api
from app.modules.geo.config import PRODUCTION_PROVIDER_REFUSAL
from app.modules.geo.routing import DisabledRoutingProvider, FakeRoutingProvider
from tests.fixtures.geo.loader import load_geo_fixture
from tests.pg.conftest import PgDatabase
from tests.pg.geo.geo_pg_helpers import create_user, set_q48_gate, set_support_phone

pytestmark = pytest.mark.pg


class Harness:
    def __init__(self, pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pg_db = pg_db
        self.provider = FakeRoutingProvider()
        self.users = {role: create_user(pg_db, role) for role in ("operator", "admin", "super_admin", "client")}
        self.users["driver"] = create_user(pg_db, "driver")
        self.users["driver2"] = create_user(pg_db, "driver")
        drivers = {self.users["driver"], self.users["driver2"]}
        # Identity capabilities are A1's; this test isolates geo: drivers may create trips.
        monkeypatch.setattr(geo_api, "_identity_capabilities", lambda db, uid: frozenset({Capability.TRIP_CREATE}) if uid in drivers else frozenset())
        with pg_db.session() as db:
            self.fixture = load_geo_fixture(db, actor_user_id=self.users["admin"], with_routes=False)

        app = FastAPI()
        app.include_router(geo_api.router, prefix="/api/v2")
        app.add_exception_handler(DomainError, domain_error_handler)

        @app.exception_handler(RequestValidationError)
        async def validation_error(_request, exc: RequestValidationError) -> JSONResponse:  # noqa: ANN001
            return JSONResponse(status_code=400, content={"success": False, "error": {"code": "VALIDATION_ERROR", "message": "invalid"}})

        def db_override() -> Iterator:
            session = pg_db.session()
            try:
                yield session
            finally:
                session.close()

        def user_override(authorization: str | None = Header(default=None)) -> User:
            if not authorization:
                raise HTTPException(status_code=401)
            with pg_db.session() as session:
                user = session.get(User, int(authorization.split()[1]))
                if user is None:
                    raise HTTPException(status_code=401)
                return user

        app.dependency_overrides[get_db] = db_override
        app.dependency_overrides[get_current_user] = user_override
        app.dependency_overrides[geo_api.get_routing_provider] = lambda: self.provider
        self.app = app
        self.client = TestClient(app)

    def call(self, method: str, path: str, *, as_: str | None = None, key: str | bool = False, **kw):  # noqa: ANN003, ANN201
        headers = kw.pop("headers", {})
        if as_ is not None:
            headers["Authorization"] = f"Bearer {self.users[as_]}"
        if key:
            headers["Idempotency-Key"] = key if isinstance(key, str) else str(uuid.uuid4())
        return self.client.request(method, "/api/v2" + path, headers=headers, **kw)

    def count(self, sql: str) -> int:
        with self.pg_db.engine.connect() as conn:
            return conn.scalar(text(sql))


@pytest.fixture
def h(pg_db: PgDatabase, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(pg_db, monkeypatch)


def ok(response, status: int = 200):  # noqa: ANN001, ANN201
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


def err(response, status: int, code: str) -> dict:  # noqa: ANN001
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is False and body["error"]["code"] == code, body
    return body["error"]


def test_openapi_every_geo_route_has_a_response_model(h: Harness) -> None:
    spec = h.app.openapi()
    count = 0
    for path, operations in spec["paths"].items():
        for method, op in operations.items():
            success = [code for code in op["responses"] if code.startswith("2")]
            schema = op["responses"][success[0]]["content"]["application/json"]["schema"]
            assert "$ref" in schema and "Envelope" in schema["$ref"], (method, path)
            count += 1
    # wave 10: G16 /districts, G17 /corridors/{id}/districts; wave 11: G18 /corridors/{id}/routes
    assert count == 22
    assert "attribution" in spec["components"]["schemas"]["RouteVersionDTO"]["properties"]


def test_public_catalogue_g1_to_g4(h: Harness) -> None:
    regions = ok(h.call("GET", "/regions"))
    assert {r["code"] for r in regions} == {"UZ-TK", "UZ-SA", "UZ-QA"} and all(r["id"].startswith("reg_") for r in regions)
    corridors = ok(h.call("GET", "/corridors"))
    assert [c["id"] for c in corridors] == [h.fixture.corridor.api_id]
    assert corridors[0]["enabled_services"] == [] and corridors[0]["stops_count"] == 6
    assert ok(h.call("GET", "/corridors", params={"service_type": "parcel"})) == []
    stops = ok(h.call("GET", f"/corridors/{h.fixture.corridor.api_id}/stops"))
    assert len(stops) == 6 and stops[0]["id"].startswith("stp_") and stops[0]["district"]["id"].startswith("dst_")
    err(h.call("GET", "/corridors/cor_notreal/stops"), 404, "NOT_FOUND")
    assert [s["name_uz"] for s in ok(h.call("GET", "/stops/search", params={"q": "chiroq"}))] == ["Chiroqchi bekati (fixture)"]
    region_qa = next(r["id"] for r in regions if r["code"] == "UZ-QA")
    assert len(ok(h.call("GET", "/stops/search", params={"q": "bekati", "region_id": region_qa}))) == 3
    err(h.call("GET", "/stops/search", params={"q": "c"}), 400, "VALIDATION_ERROR")


def test_route_preview_idempotency_and_confirm_g5_g6(h: Harness) -> None:
    stop_ids = [h.fixture.stops[k].api_id for k in ("toshkent", "samarqand", "chiroqchi", "qarshi")]
    body = {"stop_ids": stop_ids, "departure_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}

    err(h.call("POST", "/routes/preview", as_="driver", json=body), 400, "IDEMPOTENCY_KEY_REQUIRED")
    err(h.call("POST", "/routes/preview", as_="client", key=True, json=body), 403, "CAPABILITY_REQUIRED")
    err(h.call("POST", "/routes/preview", as_="driver", key=True, json=dict(body, departure_at="2026-09-21T06:00:00")), 400, "VALIDATION_ERROR")
    assert h.provider.calls == []

    # Outage: 503, generic body, nothing stored (not even the idempotency record) -> the same key works later.
    key = "preview-" + uuid.uuid4().hex
    h.provider.outage = True
    before_routes = h.count("SELECT count(*) FROM route_versions")
    failure = err(h.call("POST", "/routes/preview", as_="driver", key=key, json=body), 503, "ROUTING_UNAVAILABLE")
    assert failure["details"] == {"retryable": True}
    assert h.count("SELECT count(*) FROM route_versions") == before_routes
    assert h.count(f"SELECT count(*) FROM idempotency_records WHERE idem_key = '{key}'") == 0
    h.provider.outage = False

    created = h.call("POST", "/routes/preview", as_="driver", key=key, json=body)
    draft = ok(created, 201)
    assert draft["status"] == "draft" and draft["id"].startswith("rtv_") and draft["is_estimate"] is True
    assert draft["attribution"] == "Synthetic route from the Elchi test router (not a real road)"
    assert [s["seq"] for s in draft["stops"]] == [0, 1, 2, 3] and draft["stops"][0]["cumulative_distance_m"] == 0
    calls = len(h.provider.calls)

    replay = h.call("POST", "/routes/preview", as_="driver", key=key, json=body)
    assert replay.status_code == 201 and replay.json() == created.json()
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert len(h.provider.calls) == calls  # a replay never calls the router
    assert h.count("SELECT count(*) FROM route_versions") == before_routes + 1
    err(h.call("POST", "/routes/preview", as_="driver", key=key, json=dict(body, stop_ids=stop_ids[:2])), 409, "IDEMPOTENCY_KEY_REUSED")
    assert len(h.provider.calls) == calls

    # A domain 4xx from the read phase is stored and replayed, even after the cause is gone.
    kitob = h.fixture.stops["kitob"]
    ok(h.call("PATCH", f"/admin/stops/{kitob.api_id}", as_="admin", json={"expected_version": kitob.version, "is_active": False}))
    bad_key = "preview-inactive-" + uuid.uuid4().hex
    inactive_body = dict(body, stop_ids=[stop_ids[0], kitob.api_id])
    err(h.call("POST", "/routes/preview", as_="driver", key=bad_key, json=inactive_body), 409, "CORRIDOR_NOT_ACTIVE")
    ok(h.call("PATCH", f"/admin/stops/{kitob.api_id}", as_="admin", json={"expected_version": kitob.version + 1, "is_active": True}))
    err(h.call("POST", "/routes/preview", as_="driver", key=bad_key, json=inactive_body), 409, "CORRIDOR_NOT_ACTIVE")
    assert len(h.provider.calls) == calls

    confirm_key = "confirm-" + uuid.uuid4().hex
    err(h.call("POST", f"/routes/{draft['id']}/confirm", as_="driver2", key=True), 404, "NOT_FOUND")
    confirmed = ok(h.call("POST", f"/routes/{draft['id']}/confirm", as_="driver", key=confirm_key))
    assert confirmed["status"] == "confirmed"
    replayed = h.call("POST", f"/routes/{draft['id']}/confirm", as_="driver", key=confirm_key)
    assert ok(replayed) == confirmed and replayed.headers.get("Idempotent-Replayed") == "true"
    err(h.call("POST", f"/routes/{draft['id']}/confirm", as_="driver", key=True), 409, "INVALID_STATE_TRANSITION")


def test_decision_24_production_gets_no_router(h: Harness) -> None:
    with h.pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))
    with h.pg_db.session() as db:
        provider = geo_api.get_routing_provider(db)
    assert isinstance(provider, DisabledRoutingProvider) and provider.reason == PRODUCTION_PROVIDER_REFUSAL


def test_admin_corridors_and_stops_g7_to_g11(h: Harness) -> None:
    regions = {r["code"]: r["id"] for r in ok(h.call("GET", "/regions"))}
    create = {
        "name": "Toshkent - Samarqand (test)",
        "origin_region_id": regions["UZ-TK"],
        "destination_region_id": regions["UZ-SA"],
        "default_max_detour_minutes": 15,
        "default_max_detour_m": 5000,
        "search_radius_m": 3000,
    }
    err(h.call("POST", "/admin/corridors", as_="operator", key=True, json=create), 403, "FORBIDDEN")
    key = "corridor-" + uuid.uuid4().hex
    first = h.call("POST", "/admin/corridors", as_="admin", key=key, json=create)
    corridor = ok(first, 201)
    assert corridor["rollout_state"] == "draft" and corridor["version"] == 1 and corridor["config_version"] == 1
    again = h.call("POST", "/admin/corridors", as_="admin", key=key, json=create)
    assert again.status_code == 201 and again.json() == first.json() and again.headers.get("Idempotent-Replayed") == "true"
    assert h.count("SELECT count(*) FROM service_corridors") == 2
    err(h.call("POST", "/admin/corridors", as_="admin", key=True, json=create), 400, "VALIDATION_ERROR")
    err(h.call("GET", f"/corridors/{corridor['id']}/stops"), 404, "NOT_FOUND")

    page1 = h.call("GET", "/admin/corridors", as_="operator", params={"limit": 1})
    cursor = page1.json()["meta"]["next_cursor"]
    assert len(ok(page1)) == 1 and cursor
    second = h.call("GET", "/admin/corridors", as_="operator", params={"limit": 1, "cursor": cursor})
    assert [c["id"] for c in ok(second)] == [corridor["id"]] and second.json()["meta"]["next_cursor"] is None
    err(h.call("GET", "/admin/corridors", as_="operator", params={"cursor": cursor + "x"}), 400, "INVALID_CURSOR")
    err(h.call("GET", "/admin/corridors", as_="client"), 403, "FORBIDDEN")

    path = f"/admin/corridors/{corridor['id']}"
    err(h.call("PATCH", path, as_="admin", json={"expected_version": 1, "reason": "go", "rollout_state": "active"}), 409, "INVALID_STATE_TRANSITION")
    no_stop = err(h.call("PATCH", path, as_="admin", json={"expected_version": 1, "reason": "go", "rollout_state": "internal"}), 409, "INVALID_STATE_TRANSITION")
    assert no_stop["details"]["reason"] == "needs_active_stop"

    stop_key = "stop-" + uuid.uuid4().hex
    stop_body = {"name_uz": "Yangi bekat", "district_id": h.fixture.district_api_ids["samarqand"], "point": {"lat": 39.65, "lng": 66.96}, "is_active": True, "meeting_note": "Darvoza"}
    stop = ok(h.call("POST", f"/admin/corridors/{corridor['id']}/stops", as_="admin", key=stop_key, json=stop_body), 201)
    assert stop["is_active"] and stop["version"] == 1 and stop["corridor_id"] == corridor["id"] and stop["meeting_photo_file_id"] is None and stop["meeting_photo_url"] is None
    assert ok(h.call("POST", f"/admin/corridors/{corridor['id']}/stops", as_="admin", key=stop_key, json=stop_body), 201)["id"] == stop["id"]
    err(h.call("POST", f"/admin/corridors/{corridor['id']}/stops", as_="admin", key=True, json=dict(stop_body, point={"lat": 91, "lng": 0})), 400, "VALIDATION_ERROR")

    internal = ok(h.call("PATCH", path, as_="admin", json={"expected_version": 1, "reason": "internal test", "rollout_state": "internal", "search_radius_m": 2500}))
    assert internal["version"] == 2 and internal["config_version"] == 2 and internal["config"]["search_radius_m"] == 2500
    err(h.call("PATCH", path, as_="admin", json={"expected_version": 1, "reason": "stale", "name": "x"}), 409, "VERSION_CONFLICT")

    patched = ok(h.call("PATCH", f"/admin/stops/{stop['id']}", as_="admin", json={"expected_version": 1, "meeting_note": "Darvoza oldida", "point": {"lat": 39.66, "lng": 66.97}}))
    assert patched["version"] == 2 and patched["meeting_note"] == "Darvoza oldida" and patched["point"] == {"lat": 39.66, "lng": 66.97}
    err(h.call("PATCH", f"/admin/stops/{stop['id']}", as_="admin", json={"expected_version": 1, "name_uz": "x"}), 409, "VERSION_CONFLICT")
    err(h.call("PATCH", f"/admin/stops/{stop['id']}", as_="admin", json={"expected_version": 2, "point": None}), 400, "VALIDATION_ERROR")


def test_feature_flags_f1_to_f4(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    corridor_id = h.fixture.corridor.api_id
    assert ok(h.call("GET", "/feature-flags/effective", params={"corridor_id": corridor_id})) == {
        "corridor_id": corridor_id,
        "flags": {"passenger_enabled": False, "parcel_enabled": False, "driver_listing_enabled": False, "tracking_enabled": False},
    }

    path = f"/admin/feature-flags/parcel_enabled/scopes/corridor/{corridor_id}"
    err(h.call("PUT", path, as_="operator", key=True, json={"enabled": True, "reason": "pilot"}), 403, "FORBIDDEN")
    err(h.call("PUT", path, as_="admin", json={"enabled": True, "reason": "pilot"}), 400, "IDEMPOTENCY_KEY_REQUIRED")
    key = "flag-" + uuid.uuid4().hex
    created = ok(h.call("PUT", path, as_="admin", key=key, json={"enabled": True, "reason": "pilot start"}))
    assert created["id"].startswith("flg_") and created["version"] == 1 and created["updated_by"].startswith("usr_")
    replay = h.call("PUT", path, as_="admin", key=key, json={"enabled": True, "reason": "pilot start"})
    assert ok(replay)["version"] == 1 and replay.headers.get("Idempotent-Replayed") == "true"
    assert h.count("SELECT count(*) FROM feature_flag_changes WHERE flag_key = 'parcel_enabled'") == 1
    err(h.call("PUT", path, as_="admin", key=True, json={"enabled": False, "reason": "no version"}), 409, "VERSION_CONFLICT")
    assert ok(h.call("PUT", path, as_="admin", key=True, json={"expected_version": 1, "enabled": False, "reason": "pause"}))["version"] == 2
    ok(h.call("PUT", path, as_="admin", key=True, json={"expected_version": 2, "enabled": True, "reason": "resume"}))
    err(h.call("PUT", "/admin/feature-flags/parcel_enabled/scopes/corridor/cor_aaaaaaaaaaaaaaaaaaaaaaaaaa", as_="admin", key=True, json={"enabled": True, "reason": "x"}), 404, "NOT_FOUND")

    assert ok(h.call("GET", "/feature-flags/effective", params={"corridor_id": corridor_id}))["flags"]["parcel_enabled"] is True
    assert ok(h.call("GET", "/corridors", params={"service_type": "parcel"}))[0]["enabled_services"] == ["parcel"]
    listed = ok(h.call("GET", "/admin/feature-flags", as_="operator", params={"flag_key": "parcel_enabled"}))
    assert len(listed) == 1 and listed[0]["version"] == 3
    err(h.call("GET", "/admin/feature-flags", as_="client"), 403, "FORBIDDEN")

    page = h.call("GET", "/admin/feature-flags/parcel_enabled/history", as_="operator", params={"limit": 2})
    assert [(c["version"], c["old_enabled"], c["new_enabled"], c["reason"]) for c in ok(page)] == [(3, False, True, "resume"), (2, True, False, "pause")]
    rest = ok(h.call("GET", "/admin/feature-flags/parcel_enabled/history", as_="operator", params={"limit": 2, "cursor": page.json()["meta"]["next_cursor"]}))
    assert [(c["version"], c["old_enabled"]) for c in rest] == [(1, None)]

    # Production (DB marker, BR #5): Q1 and Q5.
    with h.pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))
    set_q48_gate(h.pg_db, monkeypatch, passed=True)  # Q56 gate open; Q56 itself is tested in test_geo_q48_gate_q47_pg
    err(h.call("PUT", "/admin/feature-flags/wallet_required/scopes/country/UZ", as_="super_admin", key=True, json={"enabled": False, "reason": "try"}), 409, "FLAG_LOCKED_IN_ENVIRONMENT")
    set_support_phone(monkeypatch)  # Q87: passenger needs a reachable support phone before it can be enabled
    passenger = f"/admin/feature-flags/passenger_enabled/scopes/corridor/{corridor_id}"
    err(h.call("PUT", passenger, as_="admin", key=True, json={"enabled": True, "approval_reference": "LEGAL-1", "reason": "launch"}), 403, "FORBIDDEN")
    err(h.call("PUT", passenger, as_="super_admin", key=True, json={"enabled": True, "reason": "launch"}), 400, "APPROVAL_REFERENCE_REQUIRED")
    launched = ok(h.call("PUT", passenger, as_="super_admin", key=True, json={"enabled": True, "approval_reference": "LEGAL-1", "reason": "launch"}))
    assert launched["approval_reference"] == "LEGAL-1"
    assert ok(h.call("GET", "/feature-flags/effective", params={"corridor_id": corridor_id}))["flags"]["passenger_enabled"] is True
