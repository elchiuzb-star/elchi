"""T3a: the staff vehicle-verification queue (``GET /api/v2/admin/vehicles``), checked without a database.

A new v2 vehicle is born ``pending`` and only ``POST /admin/vehicles/{id}/verify`` moves it; before this route no
screen could find the pending rows, so a new driver could never open a trip (``VEHICLE_NOT_ELIGIBLE``). These tests
pin the route's promises: same capability as verify, cursor pagination bound to the filter, no contact data, and
an owner eligibility block that carries exactly what the eligibility command needs (its ``expected_version``).
Row-level SQL (status filter, keyset order) is proven in ``tests/pg/trips/test_admin_vehicle_queue_pg.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.contracts.enums import Capability, Role
from app.contracts.errors import DomainError, ErrorCode
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.capabilities import DriverFacts
from app.modules.identity.web import current_user_id, get_session
from app.modules.trips import service as trips_service
from app.modules.trips import views as trips_views
from app.modules.trips.schemas import AdminVehicleDTO, AdminVehicleOwnerDTO

STAFF_ID = 7
DRIVER_A = 101
DRIVER_B = 102
T0 = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)


def _vehicle(n: int, driver_user_id: int, *, status: str = "pending") -> SimpleNamespace:
    return SimpleNamespace(
        id=n,
        public_id=uuid.UUID(int=n),
        driver_user_id=driver_user_id,
        plate_number=f"01A{n:03d}BC",
        plate_normalized=f"01A{n:03d}BC",
        make_model="Chevrolet Cobalt",
        color="oq",
        seat_capacity=4,
        baggage_capacity_ml=400_000,
        cargo_max_weight_g=None,
        cargo_max_volume_ml=None,
        document_file_ids=[],
        verification_status=status,
        verification_reason=None,
        verified_at=None,
        version=1,
        created_at=T0 + timedelta(minutes=n),
        updated_at=T0 + timedelta(minutes=n),
    )


def _caps(user_id: int, *, driver: bool = True, blocked: str | None = None) -> identity_service.CapabilitySet:
    facts = DriverFacts(verification_status="pending", active_block_reason=blocked, active_trip_count=0) if driver else None
    reasons = ("not_verified",) + (("eligibility_blocked",) if blocked else ()) if driver else ()
    return identity_service.CapabilitySet(
        user_id=user_id,
        roles=frozenset({Role.DRIVER} if driver else {Role.CLIENT}),
        capabilities=frozenset(),
        account_active=True,
        driver=facts,
        driver_reasons=reasons,
    )


@pytest.fixture
def owners(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[int]]:
    """Fake identity reads for the owner block; counts calls so the per-owner cache is visible."""
    calls: dict[str, list[int]] = {"caps": [], "version": []}

    def get_capabilities(session: object, user_id: int, *, now: datetime | None = None) -> identity_service.CapabilitySet:
        calls["caps"].append(user_id)
        return _caps(user_id, driver=user_id != DRIVER_B, blocked="hujjat soxta" if user_id == DRIVER_A else None)

    def eligibility_version(session: object, user_id: int) -> int:
        calls["version"].append(user_id)
        return 3

    monkeypatch.setattr(identity_service, "get_capabilities", get_capabilities)
    monkeypatch.setattr(identity_service, "eligibility_version", eligibility_version)
    monkeypatch.setattr(identity_service, "user_public_id", lambda session, user_id: f"usr_{user_id}")
    return calls


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, owners: dict[str, list[int]]) -> Iterator[tuple[TestClient, list[dict]]]:
    seen: list[dict] = []
    world = [_vehicle(n, DRIVER_A if n % 2 else DRIVER_B) for n in range(1, 6)]

    def list_vehicles_for_review(session: object, **kwargs: object) -> list[SimpleNamespace]:
        seen.append(kwargs)
        rows = world
        if kwargs.get("statuses"):
            rows = [v for v in rows if v.verification_status in kwargs["statuses"]]  # type: ignore[operator]
        after = kwargs.get("after")
        if after is not None:
            rows = [v for v in rows if (v.created_at, v.id) > after]
        return rows[: int(kwargs["limit"])]  # type: ignore[arg-type]

    monkeypatch.setattr(trips_service, "list_vehicles_for_review", list_vehicles_for_review)
    app.dependency_overrides[current_user_id] = lambda: STAFF_ID
    app.dependency_overrides[get_session] = lambda: object()
    try:
        yield TestClient(app), seen
    finally:
        app.dependency_overrides.pop(current_user_id, None)
        app.dependency_overrides.pop(get_session, None)


def test_route_is_mounted_with_a_response_model() -> None:
    routes = {
        (method, route.path): route
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    route = routes[("GET", "/api/v2/admin/vehicles")]
    assert route.response_model is not None


def test_queue_rows_carry_no_contact_data() -> None:
    for dto in (AdminVehicleDTO, AdminVehicleOwnerDTO):
        leaked = [name for name in dto.model_fields if "phone" in name or "name" in name and name != "make_model"]
        assert leaked == [], (dto.__name__, leaked)


def test_status_filter_and_cursor_pagination(client: tuple[TestClient, list[dict]]) -> None:
    http, seen = client
    first = http.get("/api/v2/admin/vehicles", params={"status": "pending", "limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["data"]) == 2
    assert seen[0]["statuses"] == ["pending"] and seen[0]["limit"] == 3 and seen[0]["after"] is None
    assert seen[0]["actor_user_id"] == STAFF_ID
    cursor = body["meta"]["next_cursor"]
    assert cursor

    second = http.get("/api/v2/admin/vehicles", params={"status": "pending", "limit": 2, "cursor": cursor})
    assert second.status_code == 200, second.text
    assert seen[1]["after"] == (T0 + timedelta(minutes=2), 2)
    assert {row["id"] for row in second.json()["data"]}.isdisjoint({row["id"] for row in body["data"]})

    # The cursor is bound to the filter: reusing it for another status is refused, not silently re-read.
    other = http.get("/api/v2/admin/vehicles", params={"status": "approved", "cursor": cursor})
    assert other.status_code == 400 and other.json()["error"]["code"] == ErrorCode.INVALID_CURSOR.value


def test_no_status_means_every_status(client: tuple[TestClient, list[dict]]) -> None:
    http, seen = client
    assert http.get("/api/v2/admin/vehicles").status_code == 200
    assert seen[0]["statuses"] is None and seen[0]["limit"] == 21


def test_unknown_status_is_a_validation_error(client: tuple[TestClient, list[dict]]) -> None:
    http, _seen = client
    response = http.get("/api/v2/admin/vehicles", params={"status": "maybe"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR.value


def test_owner_block_carries_the_eligibility_command_inputs(client: tuple[TestClient, list[dict]]) -> None:
    http, _seen = client
    rows = http.get("/api/v2/admin/vehicles", params={"limit": 5}).json()["data"]
    owner = rows[0]["owner"]
    assert owner["user_id"] == f"usr_{DRIVER_A}"
    assert owner["is_driver"] is True and owner["eligible"] is False
    assert owner["eligibility_version"] == 3
    assert owner["blocked_reason"] == "hujjat soxta"
    assert "eligibility_blocked" in owner["reasons"]
    assert rows[0]["verification_status"] == "pending" and rows[0]["plate_number"]


def test_capability_refusal_is_passed_through(monkeypatch: pytest.MonkeyPatch, client: tuple[TestClient, list[dict]]) -> None:
    http, _seen = client

    def refuse(session: object, **kwargs: object) -> list:
        raise DomainError(ErrorCode.CAPABILITY_REQUIRED, details={"capability": Capability.OPS_DRIVER_ELIGIBILITY_MANAGE.value})

    monkeypatch.setattr(trips_service, "list_vehicles_for_review", refuse)
    response = http.get("/api/v2/admin/vehicles")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.CAPABILITY_REQUIRED.value


def test_service_checks_the_verify_capability_before_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity_service, "get_capabilities", lambda session, user_id, now=None: _caps(user_id))

    class NoReads:
        def execute(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("the queue was read before the capability check")

    with pytest.raises(DomainError) as info:
        trips_service.list_vehicles_for_review(NoReads(), actor_user_id=STAFF_ID)  # type: ignore[arg-type]
    assert info.value.code is ErrorCode.CAPABILITY_REQUIRED


def test_owner_is_read_once_per_page_and_a_non_driver_has_no_version(owners: dict[str, list[int]]) -> None:
    vehicles = [_vehicle(1, DRIVER_A), _vehicle(2, DRIVER_A), _vehicle(3, DRIVER_B)]
    rows = trips_views.admin_vehicle_dtos(object(), vehicles)  # type: ignore[arg-type]
    assert owners["caps"] == [DRIVER_A, DRIVER_B]
    assert rows[0].owner is rows[1].owner
    non_driver = rows[2].owner
    assert non_driver.is_driver is False and non_driver.eligibility_version is None and non_driver.reasons == []
