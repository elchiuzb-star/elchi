from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import City, District, Order, RouteTariff, StatusHistory, User


@pytest.fixture()
def order_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    users = {
        "client": User(phone="+998920000001", role="client", status="active", is_phone_verified=True),
        "other_client": User(phone="+998920000002", role="client", status="active", is_phone_verified=True),
        "driver": User(phone="+998920000003", role="driver", status="active", is_phone_verified=True),
        "operator": User(phone="+998920000004", role="operator", status="active", is_phone_verified=True),
        "blocked_client": User(phone="+998920000005", role="client", status="blocked", is_phone_verified=True),
    }
    active_from = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
    active_to = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
    inactive = City(name="Inactive", name_uz="Inactive", is_active=False, requires_district=False)
    db.add_all([*users.values(), active_from, active_to, inactive])
    db.commit()
    for user in users.values():
        db.refresh(user)
    db.refresh(active_from)
    db.refresh(active_to)
    db.refresh(inactive)
    db.add(
        RouteTariff(
            from_city_id=active_from.id,
            to_city_id=active_to.id,
            suggested_price=Decimal("60000"),
            is_active=True,
        )
    )
    db.commit()
    tokens = {role: create_access_token(str(user.id)) for role, user in users.items()}
    ids = {"from_city": active_from.id, "to_city": active_to.id, "inactive_city": inactive.id}
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), tokens, TestingSessionLocal, ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def valid_payload(ids: dict[str, int]) -> dict:
    return {
        "from_city_id": ids["from_city"],
        "to_city_id": ids["to_city"],
        "pickup_address": "Toshkent, Chilonzor",
        "dropoff_address": "Samarqand center",
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": None,
        "comment": "Ehtiyot qiling",
    }


def create_order(client: TestClient, token: str, ids: dict[str, int], payload_updates: dict | None = None):
    payload = valid_payload(ids)
    if payload_updates:
        payload.update(payload_updates)
    return client.post("/api/v1/client/orders", headers=headers(token), json=payload)


def test_client_can_create_order_draft_with_cash_defaults_and_tariff(order_client) -> None:
    client, tokens, session_factory, ids = order_client

    response = create_order(client, tokens["client"], ids)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "draft"
    assert data["payment_method"] == "cash"
    assert data["payment_status"] == "unpaid"
    assert Decimal(str(data["suggested_price"])) == Decimal("60000")
    assert data["final_price"] is None
    assert data["order_number"].startswith("ORD-")

    db = session_factory()
    history = db.scalar(select(StatusHistory).where(StatusHistory.new_status == "draft"))
    assert history is not None
    assert history.changed_by_role == "client"
    db.close()


def test_client_can_create_order_with_optional_coordinates(order_client) -> None:
    client, tokens, session_factory, ids = order_client

    response = create_order(
        client,
        tokens["client"],
        ids,
        {
            "pickup_lat": 41.2995,
            "pickup_lng": 69.2401,
            "dropoff_lat": 39.6542,
            "dropoff_lng": 66.9597,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pickup_lat"] == pytest.approx(41.2995)
    assert data["pickup_lng"] == pytest.approx(69.2401)
    assert data["dropoff_lat"] == pytest.approx(39.6542)
    assert data["dropoff_lng"] == pytest.approx(66.9597)
    db = session_factory()
    order = db.get(Order, data["id"])
    assert str(order.pickup_lat) == "41.2995000"
    assert str(order.dropoff_lng) == "66.9597000"
    db.close()


@pytest.mark.parametrize(
    "payload_updates",
    [
        {"pickup_lat": 41.2995},
        {"pickup_lng": 69.2401},
        {"dropoff_lat": 39.6542},
        {"dropoff_lng": 66.9597},
        {"pickup_lat": 91, "pickup_lng": 69.2401},
        {"dropoff_lat": 39.6542, "dropoff_lng": 181},
    ],
)
def test_order_coordinates_are_validated(order_client, payload_updates: dict) -> None:
    client, tokens, _session_factory, ids = order_client

    response = create_order(client, tokens["client"], ids, payload_updates)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_order_without_tariff_has_null_suggested_price(order_client) -> None:
    client, tokens, session_factory, ids = order_client
    db = session_factory()
    city = City(name="Buxoro", name_uz="Buxoro", is_active=True, requires_district=False)
    db.add(city)
    db.commit()
    db.refresh(city)
    ids = {**ids, "to_city": city.id}
    db.close()

    response = create_order(client, tokens["client"], ids)

    assert response.status_code == 200
    assert response.json()["data"]["suggested_price"] is None
    assert response.json()["message"] == "Order draft created without suggested price"


def test_order_create_access_rules(order_client) -> None:
    client, tokens, _session_factory, ids = order_client

    assert client.post("/api/v1/client/orders", json=valid_payload(ids)).status_code == 401
    driver = create_order(client, tokens["driver"], ids)
    operator = create_order(client, tokens["operator"], ids)
    blocked = create_order(client, tokens["blocked_client"], ids)

    assert driver.status_code == 403
    assert driver.json()["error"]["message"] == "Client role required"
    assert operator.status_code == 403
    assert blocked.status_code == 403


@pytest.mark.parametrize(
    "field",
    [
        "from_city_id",
        "to_city_id",
        "pickup_address",
        "dropoff_address",
        "sender_phone",
        "receiver_phone",
    ],
)
def test_required_order_fields_are_validated(order_client, field: str) -> None:
    client, tokens, _session_factory, ids = order_client
    payload = valid_payload(ids)
    payload.pop(field)

    response = client.post("/api/v1/client/orders", headers=headers(tokens["client"]), json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_cargo_photo_is_optional(order_client) -> None:
    client, tokens, _session_factory, ids = order_client
    payload = valid_payload(ids)
    payload.pop("cargo_photo_url")

    response = client.post("/api/v1/client/orders", headers=headers(tokens["client"]), json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "draft"


def test_cargo_type_is_accepted_and_persisted(order_client) -> None:
    client, tokens, _session_factory, ids = order_client

    response = create_order(client, tokens["client"], ids, {"cargo_type": "parcel"})

    assert response.status_code == 200
    order_id = response.json()["data"]["id"]
    detail = client.get(f"/api/v1/client/orders/{order_id}", headers=headers(tokens["client"]))
    assert detail.json()["data"]["cargo_type"] == "parcel"


def test_invalid_cargo_type_is_rejected(order_client) -> None:
    client, tokens, _session_factory, ids = order_client

    response = create_order(client, tokens["client"], ids, {"cargo_type": "documents"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_city_validation_for_create_order(order_client) -> None:
    client, tokens, _session_factory, ids = order_client

    same_city = create_order(client, tokens["client"], ids, {"to_city_id": ids["from_city"]})
    inactive_from = create_order(client, tokens["client"], ids, {"from_city_id": ids["inactive_city"]})
    inactive_to = create_order(client, tokens["client"], ids, {"to_city_id": ids["inactive_city"]})

    assert same_city.status_code == 400
    assert inactive_from.status_code == 400
    assert inactive_from.json()["error"]["code"] == "CITY_INACTIVE"
    assert inactive_to.status_code == 400


def test_order_requires_districts_for_district_required_cities(order_client) -> None:
    client, tokens, session_factory, ids = order_client
    db = session_factory()
    from_city = db.get(City, ids["from_city"])
    to_city = db.get(City, ids["to_city"])
    from_city.requires_district = True
    to_city.requires_district = True
    from_district = District(city_id=from_city.id, name_uz="Chilonzor", is_active=True)
    to_district = District(city_id=to_city.id, name_uz="Samarqand shahri", is_active=True)
    db.add_all([from_district, to_district])
    db.commit()
    db.refresh(from_district)
    db.refresh(to_district)
    district_ids = {"from_district_id": from_district.id, "to_district_id": to_district.id}
    db.close()

    missing = create_order(client, tokens["client"], ids)
    created = create_order(client, tokens["client"], ids, district_ids)

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "DISTRICT_REQUIRED"
    assert created.status_code == 200
    data = created.json()["data"]
    assert data["from_district"]["name_uz"] == "Chilonzor"
    assert data["to_district"]["name_uz"] == "Samarqand shahri"


def test_order_rejects_marker_outside_selected_district(order_client) -> None:
    client, tokens, session_factory, ids = order_client
    db = session_factory()
    from_city = db.get(City, ids["from_city"])
    to_city = db.get(City, ids["to_city"])
    from_city.requires_district = True
    to_city.requires_district = True
    from_district = District(city_id=from_city.id, name_uz="Chilonzor", is_active=True, center_lat=41.2850, center_lng=69.2000)
    to_district = District(city_id=to_city.id, name_uz="Samarqand shahri", is_active=True, center_lat=39.6542, center_lng=66.9597)
    db.add_all([from_district, to_district])
    db.commit()
    db.refresh(from_district)
    db.refresh(to_district)
    db.close()

    response = create_order(
        client,
        tokens["client"],
        ids,
        {
            "from_district_id": from_district.id,
            "to_district_id": to_district.id,
            "pickup_lat": 40.7821,
            "pickup_lng": 72.3442,
            "dropoff_lat": 39.6542,
            "dropoff_lng": 66.9597,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LOCATION_MISMATCH"


def test_forbidden_order_fields_are_rejected(order_client) -> None:
    client, tokens, _session_factory, ids = order_client
    payload = valid_payload(ids)
    payload["weight"] = 3
    payload["size"] = "small"
    payload["pickup_time"] = "2026-06-13T10:00:00"
    payload["delivery_time"] = "2026-06-14T10:00:00"

    response = client.post("/api/v1/client/orders", headers=headers(tokens["client"]), json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_client_can_publish_own_draft_order_and_history_written(order_client) -> None:
    client, tokens, session_factory, ids = order_client
    order_id = create_order(client, tokens["client"], ids).json()["data"]["id"]

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "published"
    assert response.json()["data"]["matched_drivers_count"] == 0

    db = session_factory()
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "published"))
    assert history is not None
    assert history.old_status == "draft"
    db.close()


def test_client_cannot_publish_another_or_cancelled_order(order_client) -> None:
    client, tokens, _session_factory, ids = order_client
    order_id = create_order(client, tokens["other_client"], ids).json()["data"]["id"]
    own_order_id = create_order(client, tokens["client"], ids).json()["data"]["id"]
    client.post(f"/api/v1/client/orders/{own_order_id}/cancel", headers=headers(tokens["client"]), json={"reason": "No need"})

    other_response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))
    cancelled_response = client.post(f"/api/v1/client/orders/{own_order_id}/publish", headers=headers(tokens["client"]))

    assert other_response.status_code == 403
    assert cancelled_response.status_code == 400
    assert cancelled_response.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_client_can_list_only_own_orders_and_view_detail(order_client) -> None:
    client, tokens, _session_factory, ids = order_client
    own_order_id = create_order(client, tokens["client"], ids).json()["data"]["id"]
    other_order_id = create_order(client, tokens["other_client"], ids).json()["data"]["id"]

    list_response = client.get("/api/v1/client/orders", headers=headers(tokens["client"]))
    detail_response = client.get(f"/api/v1/client/orders/{own_order_id}", headers=headers(tokens["client"]))
    other_detail = client.get(f"/api/v1/client/orders/{other_order_id}", headers=headers(tokens["client"]))

    assert list_response.status_code == 200
    items = list_response.json()["data"]["items"]
    assert [item["id"] for item in items] == [own_order_id]
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["id"] == own_order_id
    assert other_detail.status_code == 403
    assert other_detail.json()["error"] == {"code": "FORBIDDEN", "message": "You can access only your own orders"}


@pytest.mark.parametrize("order_status", ["draft", "published", "bidding", "accepted"])
def test_client_can_cancel_allowed_statuses(order_client, order_status: str) -> None:
    client, tokens, session_factory, ids = order_client
    order_id = create_order(client, tokens["client"], ids).json()["data"]["id"]
    db = session_factory()
    order = db.get(Order, order_id)
    order.status = order_status
    db.commit()
    db.close()

    response = client.post(
        f"/api/v1/client/orders/{order_id}/cancel",
        headers=headers(tokens["client"]),
        json={"reason": "Client changed mind"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"
    assert response.json()["data"]["cancel_reason"] == "Client changed mind"

    db = session_factory()
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "cancelled"))
    assert history is not None
    assert history.old_status == order_status
    assert history.reason == "Client changed mind"
    db.close()


def test_cancel_reason_is_required(order_client) -> None:
    client, tokens, _session_factory, ids = order_client
    order_id = create_order(client, tokens["client"], ids).json()["data"]["id"]

    response = client.post(f"/api/v1/client/orders/{order_id}/cancel", headers=headers(tokens["client"]), json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("order_status", ["picked_up", "in_transit", "delivered", "confirmed"])
def test_client_cannot_cancel_after_pickup_statuses(order_client, order_status: str) -> None:
    client, tokens, session_factory, ids = order_client
    order_id = create_order(client, tokens["client"], ids).json()["data"]["id"]
    db = session_factory()
    order = db.get(Order, order_id)
    order.status = order_status
    db.commit()
    db.close()

    response = client.post(
        f"/api/v1/client/orders/{order_id}/cancel",
        headers=headers(tokens["client"]),
        json={"reason": "Too late"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ORDER_INVALID_STATUS"
    assert response.json()["error"]["message"] == "Client cannot cancel order after pickup"
