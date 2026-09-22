"""A1 v2 routers through HTTP on PostgreSQL (test-local app; the integrator wires /api/v2).

Covers envelopes and status codes, Idempotency-Key replay via A3's platform service,
error rendering, public vs owner listing views and OpenAPI response models.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts.errors import DomainError
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.identity.api import router as identity_router
from app.modules.identity.web import domain_error_handler
from app.modules.marketplace.api import router as marketplace_router
from app.modules.trips.api import router as trips_router
from tests.pg.identity.a1_world import World, make_trip, make_vehicle, passenger_request

pytestmark = pytest.mark.pg


@pytest.fixture
def client(world: World) -> Iterator[TestClient]:
    app = FastAPI()
    for router in (identity_router, trips_router, marketplace_router):
        app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)

    def override_db() -> Iterator:
        session = world.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


def auth(user_id: int, role: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {create_access_token(str(user_id), extra_claims={'role': role})}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def test_openapi_declares_response_models(client: TestClient) -> None:
    spec = client.app.openapi()
    operations = [(path, method, op) for path, ops in spec["paths"].items() for method, op in ops.items()]
    assert len(operations) >= 25
    for path, method, op in operations:
        success = [code for code in op["responses"] if code.startswith("2")]
        assert success and "content" in op["responses"][success[0]], (method, path)


def test_me_and_capabilities(client: TestClient, world: World) -> None:
    me = client.get("/api/v2/me", headers=auth(world.driver_id, "driver"))
    assert me.status_code == 200
    assert me.json()["data"]["id"].startswith("usr_") and me.json()["data"]["primary_role"] == "driver"
    caps = client.get("/api/v2/me/capabilities", headers=auth(world.driver_id, "driver")).json()["data"]
    assert "trip.create" in caps["capabilities"]
    assert caps["driver_eligibility"] == {
        "verification_status": "approved",
        "eligible": True,
        "reasons": [],
        "has_active_obligations": False,
    }


def test_role_activation_and_q3(client: TestClient, world: World) -> None:
    response = client.post("/api/v2/me/roles", json={"role": "driver"}, headers=auth(world.client_id, "client", "role-key-0001"))
    assert response.status_code == 200 and set(response.json()["data"]["roles"]) == {"client", "driver"}
    staff = client.post("/api/v2/me/roles", json={"role": "client"}, headers=auth(world.admin_id, "admin", "role-key-0002"))
    assert staff.status_code == 409 and staff.json()["error"]["code"] == "ROLE_COMBINATION_FORBIDDEN"
    missing_key = client.post("/api/v2/me/roles", json={"role": "driver"}, headers=auth(world.client_id, "client"))
    assert missing_key.status_code == 400 and missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_listing_create_idempotent_replay_and_views(client: TestClient, world: World) -> None:
    body = passenger_request(world, start=world.base_time).model_dump(mode="json")
    first = client.post("/api/v2/listings", json=body, headers=auth(world.client_id, "client", "listing-key-01"))
    assert first.status_code == 201, first.text
    data = first.json()["data"]
    assert (data["quantity"], data["unit_price_minor"], data["total_minor"], data["currency"]) == (2, 20_000_000, 40_000_000, "UZS")
    assert data["departure_window_start"].endswith("Z")

    replay = client.post("/api/v2/listings", json=body, headers=auth(world.client_id, "client", "listing-key-01"))
    assert replay.status_code == 201 and replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json() == first.json()
    reused = client.post(
        "/api/v2/listings", json={**body, "unit_price_minor": 1}, headers=auth(world.client_id, "client", "listing-key-01")
    )
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    listing_id = data["id"]
    assert client.get(f"/api/v2/listings/{listing_id}").status_code == 404  # draft is hidden from others
    published = client.post(
        f"/api/v2/listings/{listing_id}/publish", json={"expected_version": 1}, headers=auth(world.client_id, "client", "publish-key-1")
    )
    assert published.status_code == 200 and published.json()["data"]["status"] == "published"
    public = client.get(f"/api/v2/listings/{listing_id}").json()["data"]
    assert not {"owner", "owner_display_name", "passenger"} & set(public)  # R2: no identity before accept


def test_proposal_http_errors_and_fee_visibility(client: TestClient, world: World) -> None:
    body = passenger_request(world, start=world.base_time).model_dump(mode="json")
    listing_id = client.post("/api/v2/listings", json=body, headers=auth(world.client_id, "client", "listing-key-02")).json()["data"]["id"]
    client.post(f"/api/v2/listings/{listing_id}/publish", json={"expected_version": 1}, headers=auth(world.client_id, "client", "publish-key-2"))
    vehicle = make_vehicle(world, world.driver_id, "01C300CC")
    _, trip_public_id = make_trip(world, world.driver_id, vehicle, start=world.base_time)
    proposal = {
        "trip_id": trip_public_id,
        "pickup_stop_id": world.stop_public_ids["A"],
        "dropoff_stop_id": world.stop_public_ids["D"],
        "pickup_window_start": world.base_time.isoformat(),
        "pickup_window_end": (world.base_time + timedelta(minutes=30)).isoformat(),
        "quantity": 2,
        "price_basis": "per_seat",
        "unit_price_minor": 20_000_000,
    }
    own = client.post(f"/api/v2/listings/{listing_id}/proposals", json=proposal, headers=auth(world.client_id, "client", "prop-key-self1"))
    assert own.status_code == 403 and own.json()["error"]["code"] == "SELF_DEALING_FORBIDDEN"

    created = client.post(f"/api/v2/listings/{listing_id}/proposals", json=proposal, headers=auth(world.driver_id, "driver", "prop-key-00001"))
    assert created.status_code == 201, created.text
    thread = created.json()["data"]
    assert thread["current_version"]["fee_quote"]["commission_minor"] == 6_000_000  # driver sees the fee
    thread_id = thread["id"]

    client_view = client.get(f"/api/v2/proposals/{thread_id}", headers=auth(world.client_id, "client")).json()["data"]
    assert client_view["current_version"]["fee_quote"] is None  # never shown to the client (Q16)
    assert client_view["driver"] == {"side": "driver", "label": "Haydovchi #1", "id": None, "display_name": None, "reputation": None}
    assert client_view["client"]["id"] is None and client_view["client"]["label"] == "Mijoz"

    stale = client.post(
        f"/api/v2/proposals/{thread_id}/counter",
        json={"expected_revision": 2, "unit_price_minor": 18_000_000},
        headers=auth(world.client_id, "client", "counter-key-01"),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "PROPOSAL_CHANGED"
    stranger = client.get(f"/api/v2/proposals/{thread_id}", headers=auth(world.client2_id, "client"))
    assert stranger.status_code == 404
