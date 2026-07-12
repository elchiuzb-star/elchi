from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AuditLog,
    City,
    District,
    DriverProfile,
    DriverRoute,
    Notification,
    Order,
    OrderOffer,
    RouteTariff,
    StatusHistory,
    User,
)


@pytest.fixture()
def matching_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998930000001", role="client", status="active", is_phone_verified=True)
    other_client = User(phone="+998930000002", role="client", status="active", is_phone_verified=True)
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
    wrong_city = City(name="Buxoro", name_uz="Buxoro", is_active=True, requires_district=False)
    db.add_all([client_user, other_client, from_city, to_city, wrong_city])
    db.commit()
    for item in [client_user, other_client, from_city, to_city, wrong_city]:
        db.refresh(item)
    db.add(
        RouteTariff(
            from_city_id=from_city.id,
            to_city_id=to_city.id,
            suggested_price=Decimal("60000"),
            is_active=True,
        )
    )
    db.commit()
    tokens = {
        "client": create_access_token(str(client_user.id)),
        "other_client": create_access_token(str(other_client.id)),
    }
    ids = {
        "client": client_user.id,
        "other_client": other_client.id,
        "from_city": from_city.id,
        "to_city": to_city.id,
        "wrong_city": wrong_city.id,
    }
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


def order_payload(ids: dict[str, int]) -> dict:
    payload = {
        "from_city_id": ids["from_city"],
        "to_city_id": ids["to_city"],
        "pickup_address": "Toshkent, Chilonzor",
        "dropoff_address": "Samarqand center",
        "pickup_lat": 41.2995,
        "pickup_lng": 69.2401,
        "dropoff_lat": 39.6542,
        "dropoff_lng": 66.9597,
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": "/uploads/cargo_photo/2026/06/photo.jpg",
    }
    if "from_district" in ids:
        payload["from_district_id"] = ids["from_district"]
    if "to_district" in ids:
        payload["to_district_id"] = ids["to_district"]
    return payload


def create_order(client: TestClient, token: str, ids: dict[str, int]) -> int:
    response = client.post("/api/v1/client/orders", headers=headers(token), json=order_payload(ids))
    assert response.status_code == 200
    return response.json()["data"]["id"]


def create_driver(
    session_factory: sessionmaker,
    ids: dict[str, int],
    *,
    verification_status: str = "approved",
    is_available: bool = True,
    user_status: str = "active",
    route_status: str = "available",
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    from_district_id: int | None = None,
    to_district_id: int | None = None,
) -> DriverProfile:
    db = session_factory()
    suffix = db.scalar(select(func.count(User.id))) + 1
    user = User(
        phone=f"+99894{suffix:07d}",
        role="driver",
        status=user_status,
        is_phone_verified=True,
    )
    db.add(user)
    db.flush()
    driver = DriverProfile(
        user_id=user.id,
        verification_status=verification_status,
        is_available=is_available,
    )
    db.add(driver)
    db.flush()
    db.add(
        DriverRoute(
            driver_id=driver.id,
            from_city_id=from_city_id or ids["from_city"],
            to_city_id=to_city_id or ids["to_city"],
            from_district_id=from_district_id,
            to_district_id=to_district_id,
            status=route_status,
        )
    )
    db.commit()
    db.refresh(driver)
    db.close()
    return driver


def test_publish_creates_order_offer_for_matching_driver(matching_client) -> None:
    client, tokens, session_factory, ids = matching_client
    matched_driver = create_driver(session_factory, ids)
    order_id = create_order(client, tokens["client"], ids)

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "published"
    assert response.json()["data"]["matched_drivers_count"] == 1
    assert response.json()["message"] == "Order published"

    db = session_factory()
    order = db.get(Order, order_id)
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id))
    assert order.status == "published"
    assert order.published_at is not None
    assert offer is not None
    assert offer.driver_id == matched_driver.id
    assert offer.result == "shown"
    assert offer.status == "shown"
    assert offer.shown_at is not None
    assert db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "published")) is not None
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "order_published", AuditLog.entity_id == order_id))
    assert audit is not None
    assert audit.details["new_value"]["matched_drivers_count"] == 1
    notification = db.scalar(select(Notification).where(Notification.user_id == matched_driver.user_id))
    assert notification is not None
    assert notification.type == "order_published"
    db.close()


@pytest.mark.parametrize(
    "driver_kwargs",
    [
        {"verification_status": "new"},
        {"verification_status": "pending"},
        {"verification_status": "rejected"},
        {"verification_status": "blocked"},
        {"user_status": "blocked"},
        {"user_status": "inactive"},
        {"is_available": False},
        {"route_status": "unavailable"},
        {"route_status": "busy"},
        {"from_city_id": "wrong"},
        {"to_city_id": "wrong"},
    ],
)
def test_ineligible_drivers_do_not_match(matching_client, driver_kwargs: dict) -> None:
    client, tokens, session_factory, ids = matching_client
    kwargs = dict(driver_kwargs)
    if kwargs.get("from_city_id") == "wrong":
        kwargs["from_city_id"] = ids["wrong_city"]
    if kwargs.get("to_city_id") == "wrong":
        kwargs["to_city_id"] = ids["wrong_city"]
    create_driver(session_factory, ids, **kwargs)
    order_id = create_order(client, tokens["client"], ids)

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 200
    assert response.json()["data"]["matched_drivers_count"] == 0
    assert response.json()["message"] == "Order published, but no matched drivers found"

    db = session_factory()
    assert db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id)) is None
    db.close()


def test_duplicate_order_offers_are_not_created(matching_client) -> None:
    client, tokens, session_factory, ids = matching_client
    driver = create_driver(session_factory, ids)
    order_id = create_order(client, tokens["client"], ids)
    db = session_factory()
    db.add(OrderOffer(order_id=order_id, driver_id=driver.id, status="shown", result="shown"))
    db.commit()
    db.close()

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 200
    assert response.json()["data"]["matched_drivers_count"] == 0

    db = session_factory()
    offers_count = db.scalar(select(func.count(OrderOffer.id)).where(OrderOffer.order_id == order_id))
    assert offers_count == 1
    db.close()


def test_matching_requires_exact_required_district_pair(matching_client) -> None:
    client, tokens, session_factory, ids = matching_client
    db = session_factory()
    from_city = db.get(City, ids["from_city"])
    to_city = db.get(City, ids["to_city"])
    from_city.requires_district = True
    to_city.requires_district = True
    from_district = District(city_id=from_city.id, name_uz="Chilonzor", is_active=True, center_lat=41.2995, center_lng=69.2401)
    other_from_district = District(city_id=from_city.id, name_uz="Yunusobod", is_active=True, center_lat=41.3667, center_lng=69.2875)
    to_district = District(city_id=to_city.id, name_uz="Samarqand shahri", is_active=True, center_lat=39.6542, center_lng=66.9597)
    db.add_all([from_district, other_from_district, to_district])
    db.commit()
    db.refresh(from_district)
    db.refresh(other_from_district)
    db.refresh(to_district)
    district_ids = {**ids, "from_district": from_district.id, "to_district": to_district.id}
    db.close()

    matched_driver = create_driver(
        session_factory,
        ids,
        from_district_id=from_district.id,
        to_district_id=to_district.id,
    )
    create_driver(
        session_factory,
        ids,
        from_district_id=other_from_district.id,
        to_district_id=to_district.id,
    )
    order_id = create_order(client, tokens["client"], district_ids)

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 200
    assert response.json()["data"]["matched_drivers_count"] == 1

    db = session_factory()
    offers = list(db.scalars(select(OrderOffer).where(OrderOffer.order_id == order_id)))
    assert [offer.driver_id for offer in offers] == [matched_driver.id]
    db.close()


def test_publish_same_order_twice_fails(matching_client) -> None:
    client, tokens, session_factory, ids = matching_client
    create_driver(session_factory, ids)
    order_id = create_order(client, tokens["client"], ids)

    first = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))
    second = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_publishing_another_clients_order_fails_with_forbidden(matching_client) -> None:
    client, tokens, _session_factory, ids = matching_client
    order_id = create_order(client, tokens["other_client"], ids)

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "You can publish only your own orders"}


def test_publish_missing_required_field_returns_details(matching_client) -> None:
    client, tokens, session_factory, ids = matching_client
    order_id = create_order(client, tokens["client"], ids)
    db = session_factory()
    order = db.get(Order, order_id)
    order.sender_phone = ""
    db.commit()
    db.close()

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]["missing_fields"] == ["sender_phone"]


def test_publish_succeeds_without_cargo_photo(matching_client) -> None:
    client, tokens, session_factory, ids = matching_client
    order_id = create_order(client, tokens["client"], ids)
    db = session_factory()
    order = db.get(Order, order_id)
    order.cargo_photo_url = None
    db.commit()
    db.close()

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 200


def test_matching_does_not_require_forbidden_fields(matching_client) -> None:
    client, tokens, session_factory, ids = matching_client
    create_driver(session_factory, ids)
    order_id = create_order(client, tokens["client"], ids)

    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert response.status_code == 200
    assert response.json()["data"]["matched_drivers_count"] == 1

    db = session_factory()
    route_columns = set(DriverRoute.__table__.columns.keys())
    order_columns = set(Order.__table__.columns.keys())
    assert "departure_time" not in route_columns
    assert "capacity" not in route_columns
    assert "cargo_type" in order_columns
    assert "weight" not in order_columns
    assert "size" not in order_columns
    db.close()
