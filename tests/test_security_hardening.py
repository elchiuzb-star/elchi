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
from app.models import Bid, City, DriverProfile, DriverRoute, Notification, Order, OrderOffer, RouteTariff, User


@pytest.fixture()
def security_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998981000001", role="client", status="active", is_phone_verified=True)
    other_client = User(phone="+998981000002", role="client", status="active", is_phone_verified=True)
    driver_user = User(phone="+998981000003", role="driver", status="active", is_phone_verified=True)
    other_driver_user = User(phone="+998981000004", role="driver", status="active", is_phone_verified=True)
    wrong_route_driver_user = User(phone="+998981000005", role="driver", status="active", is_phone_verified=True)
    operator = User(phone="+998981000006", role="operator", status="active", is_phone_verified=True)
    admin = User(phone="+998981000007", role="admin", status="active", is_phone_verified=True)
    blocked_client = User(phone="+998981000008", role="client", status="blocked", is_phone_verified=True)
    inactive_client = User(phone="+998981000009", role="client", status="inactive", is_phone_verified=True)
    blocked_driver = User(phone="+998981000010", role="driver", status="blocked", is_phone_verified=True)
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
    wrong_city = City(name="Buxoro", name_uz="Buxoro", is_active=True, requires_district=False)
    db.add_all(
        [
            client_user,
            other_client,
            driver_user,
            other_driver_user,
            wrong_route_driver_user,
            operator,
            admin,
            blocked_client,
            inactive_client,
            blocked_driver,
            from_city,
            to_city,
            wrong_city,
        ]
    )
    db.flush()
    driver = DriverProfile(user_id=driver_user.id, verification_status="approved", is_available=True)
    other_driver = DriverProfile(user_id=other_driver_user.id, verification_status="approved", is_available=True)
    wrong_route_driver = DriverProfile(user_id=wrong_route_driver_user.id, verification_status="approved", is_available=True)
    blocked_driver_profile = DriverProfile(user_id=blocked_driver.id, verification_status="approved", is_available=True)
    db.add_all([driver, other_driver, wrong_route_driver, blocked_driver_profile])
    db.flush()
    db.add_all(
        [
            DriverRoute(driver_id=driver.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"),
            DriverRoute(driver_id=other_driver.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"),
            DriverRoute(driver_id=wrong_route_driver.id, from_city_id=wrong_city.id, to_city_id=to_city.id, status="available"),
            RouteTariff(from_city_id=from_city.id, to_city_id=to_city.id, suggested_price=Decimal("60000"), is_active=True),
        ]
    )
    order = Order(
        order_number="ORD-ST18-1",
        client_id=client_user.id,
        from_city_id=from_city.id,
        to_city_id=to_city.id,
        pickup_address="Toshkent, Chilonzor 12",
        dropoff_address="Samarqand, Registon 1",
        sender_phone="+998901234567",
        receiver_phone="+998911112233",
        cargo_photo_url="/uploads/cargo_photo/2026/06/photo.jpg",
        suggested_price=Decimal("60000"),
        payment_method="cash",
        payment_status="unpaid",
        status="published",
    )
    other_order = Order(
        order_number="ORD-ST18-2",
        client_id=other_client.id,
        from_city_id=from_city.id,
        to_city_id=to_city.id,
        pickup_address="Toshkent, Yunusobod",
        dropoff_address="Samarqand, Center",
        sender_phone="+998901111111",
        receiver_phone="+998902222222",
        cargo_photo_url="/uploads/cargo_photo/2026/06/photo2.jpg",
        suggested_price=Decimal("60000"),
        payment_method="cash",
        payment_status="unpaid",
        status="published",
    )
    db.add_all([order, other_order])
    db.flush()
    db.add(OrderOffer(order_id=order.id, driver_id=driver.id, status="shown", result="shown"))
    db.add(Bid(order_id=order.id, driver_id=other_driver.id, price=Decimal("55000"), status="active"))
    db.add(Notification(user_id=other_client.id, type="new_bid", title="Other", message="Hidden", order_id=order.id, channel="in_app", is_read=False))
    db.commit()

    users = {
        "client": client_user,
        "other_client": other_client,
        "driver": driver_user,
        "other_driver": other_driver_user,
        "wrong_route_driver": wrong_route_driver_user,
        "operator": operator,
        "admin": admin,
        "blocked_client": blocked_client,
        "inactive_client": inactive_client,
        "blocked_driver": blocked_driver,
    }
    tokens = {key: create_access_token(str(user.id)) for key, user in users.items()}
    ids = {
        "client": client_user.id,
        "other_client": other_client.id,
        "driver_profile": driver.id,
        "other_driver_profile": other_driver.id,
        "order": order.id,
        "other_order": other_order.id,
        "from_city": from_city.id,
        "to_city": to_city.id,
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
    return {
        "from_city_id": ids["from_city"],
        "to_city_id": ids["to_city"],
        "pickup_address": "Toshkent",
        "dropoff_address": "Samarqand",
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": None,
    }


def test_anonymous_and_non_active_users_are_blocked_from_protected_actions(security_client) -> None:
    client, tokens, _session_factory, ids = security_client

    anonymous = client.get("/api/v1/client/orders")
    blocked_client = client.post("/api/v1/client/orders", headers=headers(tokens["blocked_client"]), json=order_payload(ids))
    inactive_client = client.post("/api/v1/client/orders", headers=headers(tokens["inactive_client"]), json=order_payload(ids))
    blocked_driver = client.get("/api/v1/driver/orders/feed", headers=headers(tokens["blocked_driver"]))

    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == {"code": "UNAUTHORIZED", "message": "Authentication required"}
    assert blocked_client.status_code == 403
    assert blocked_client.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}
    assert inactive_client.status_code == 403
    assert inactive_client.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}
    assert blocked_driver.status_code == 403
    assert blocked_driver.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}


def test_client_cannot_access_or_mutate_another_clients_order(security_client) -> None:
    client, tokens, _session_factory, ids = security_client

    detail = client.get(f"/api/v1/client/orders/{ids['other_order']}", headers=headers(tokens["client"]))
    publish = client.post(f"/api/v1/client/orders/{ids['other_order']}/publish", headers=headers(tokens["client"]))
    select = client.post(
        f"/api/v1/client/orders/{ids['other_order']}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": 1},
    )
    confirm = client.post(f"/api/v1/client/orders/{ids['other_order']}/confirm", headers=headers(tokens["client"]))
    rating = client.post(
        f"/api/v1/client/orders/{ids['other_order']}/rating",
        headers=headers(tokens["client"]),
        json={"rating": 5},
    )

    assert detail.json()["error"] == {"code": "FORBIDDEN", "message": "You can access only your own orders"}
    assert publish.json()["error"] == {"code": "FORBIDDEN", "message": "You can publish only your own orders"}
    assert select.json()["error"] == {"code": "FORBIDDEN", "message": "You can select driver only for your own order"}
    assert confirm.json()["error"] == {"code": "FORBIDDEN", "message": "You can access only your own orders"}
    assert rating.json()["error"] == {"code": "FORBIDDEN", "message": "You can access only your own orders"}


def test_driver_boundaries_and_private_order_visibility(security_client) -> None:
    client, tokens, session_factory, ids = security_client
    db = session_factory()
    other_bid = db.scalar(select(Bid).where(Bid.driver_id == ids["other_driver_profile"]))
    db.close()

    client_endpoint = client.get("/api/v1/client/orders", headers=headers(tokens["driver"]))
    admin_endpoint = client.get("/api/v1/admin/orders", headers=headers(tokens["driver"]))
    bid_update = client.patch(f"/api/v1/driver/bids/{other_bid.id}", headers=headers(tokens["driver"]), json={"price": 60000})
    detail = client.get(f"/api/v1/driver/orders/{ids['order']}", headers=headers(tokens["driver"]))
    wrong_route_feed = client.get("/api/v1/driver/orders/feed", headers=headers(tokens["wrong_route_driver"]))

    assert client_endpoint.status_code == 403
    assert admin_endpoint.status_code == 403
    assert bid_update.status_code == 403
    assert bid_update.json()["error"] == {"code": "FORBIDDEN", "message": "You can update only your own bids"}
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert "pickup_address" not in data
    assert "dropoff_address" not in data
    assert "sender_phone" not in data
    assert "receiver_phone" not in data
    assert wrong_route_feed.status_code == 200
    assert wrong_route_feed.json()["data"]["items"] == []


def test_operator_audit_and_driver_verification_boundaries(security_client) -> None:
    client, tokens, _session_factory, ids = security_client

    audit = client.get("/api/v1/admin/audit-logs", headers=headers(tokens["operator"]))
    approve = client.post(f"/api/v1/admin/drivers/{ids['driver_profile']}/approve", headers=headers(tokens["operator"]), json={})
    reject = client.post(f"/api/v1/admin/drivers/{ids['driver_profile']}/reject", headers=headers(tokens["operator"]), json={"reason": "bad"})
    block = client.post(f"/api/v1/admin/drivers/{ids['driver_profile']}/block", headers=headers(tokens["operator"]), json={"reason": "bad"})

    assert audit.status_code == 403
    assert audit.json()["error"] == {"code": "FORBIDDEN", "message": "Admin or super admin role required"}
    assert approve.status_code == 403
    assert reject.status_code == 403
    assert block.status_code == 403


def test_notification_ownership_and_payment_input_hardening(security_client) -> None:
    client, tokens, session_factory, ids = security_client
    db = session_factory()
    other_notification = db.scalar(select(Notification).where(Notification.user_id == ids["other_client"]))
    db.close()
    payload = order_payload(ids)
    payload["payment_method"] = "card"

    list_response = client.get("/api/v1/notifications", headers=headers(tokens["client"]))
    read_response = client.patch(f"/api/v1/notifications/{other_notification.id}/read", headers=headers(tokens["client"]))
    payment_response = client.post("/api/v1/client/orders", headers=headers(tokens["client"]), json=payload)

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"] == []
    assert read_response.status_code == 404
    assert read_response.json()["error"] == {"code": "NOT_FOUND", "message": "Notification not found"}
    assert payment_response.status_code == 400
    assert payment_response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_security_headers_are_present(security_client) -> None:
    client, _tokens, _session_factory, _ids = security_client

    response = client.get("/api/v1/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
