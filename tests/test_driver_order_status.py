from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, City, DriverProfile, Notification, Order, StatusHistory, User


@pytest.fixture()
def driver_status_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998970000001", role="client", status="active", is_phone_verified=True)
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True)
    db.add_all([client_user, from_city, to_city])
    db.commit()
    for item in [client_user, from_city, to_city]:
        db.refresh(item)
    tokens = {"client": create_access_token(str(client_user.id))}
    ids = {"client": client_user.id, "from_city": from_city.id, "to_city": to_city.id}
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


def create_driver(
    session_factory: sessionmaker,
    *,
    verification_status: str = "approved",
    user_status: str = "active",
    is_available: bool = False,
) -> dict[str, int | str]:
    db = session_factory()
    suffix = db.scalar(select(func.count(User.id))) + 30
    user = User(phone=f"+99897{suffix:07d}", role="driver", status=user_status, is_phone_verified=True)
    db.add(user)
    db.flush()
    driver = DriverProfile(
        user_id=user.id,
        full_name="Ali Valiyev",
        verification_status=verification_status,
        is_available=is_available,
    )
    db.add(driver)
    db.commit()
    result = {"profile_id": driver.id, "user_id": user.id, "token": create_access_token(str(user.id))}
    db.close()
    return result


def create_assigned_order(
    session_factory: sessionmaker,
    ids: dict[str, int],
    driver_id: int,
    *,
    status: str = "accepted",
) -> int:
    db = session_factory()
    count = db.scalar(select(func.count(Order.id))) + 1
    order = Order(
        order_number=f"ORD-ST11-{count}",
        client_id=ids["client"],
        from_city_id=ids["from_city"],
        to_city_id=ids["to_city"],
        pickup_address="Toshkent, Chilonzor",
        dropoff_address="Samarqand, Registon",
        pickup_lat=Decimal("41.2995000"),
        pickup_lng=Decimal("69.2401000"),
        dropoff_lat=Decimal("39.6542000"),
        dropoff_lng=Decimal("66.9597000"),
        sender_phone="+998901234567",
        receiver_phone="+998911112233",
        cargo_photo_url="/uploads/cargo_photo/2026/06/photo.jpg",
        suggested_price=Decimal("60000"),
        final_price=Decimal("55000"),
        payment_method="cash",
        payment_status="unpaid",
        status=status,
        assigned_driver_id=driver_id,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    order_id = order.id
    db.close()
    return order_id


def get_order(session_factory: sessionmaker, order_id: int) -> Order:
    db = session_factory()
    order = db.get(Order, order_id)
    db.expunge(order)
    db.close()
    return order


def test_assigned_approved_driver_can_mark_order_picked_up(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory, is_available=False)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver["token"]))

    assert response.status_code == 200
    assert response.json()["message"] == "Order marked as picked up"
    assert response.json()["data"]["status"] == "picked_up"
    db = session_factory()
    order = db.get(Order, order_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "picked_up"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_marked_picked_up", AuditLog.entity_id == order_id))
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["client"], Notification.type == "picked_up"))
    assert order.picked_up_at is not None
    assert order.in_transit_at is None
    assert order.delivered_at is None
    assert history is not None
    assert history.old_status == "accepted"
    assert history.reason == "driver_marked_picked_up"
    assert audit is not None
    assert notification is not None
    db.close()


def test_assigned_driver_can_list_own_orders(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory, is_available=False)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.get("/api/v1/driver/orders", headers=headers(driver["token"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 1
    assert data["items"][0]["id"] == order_id
    assert data["items"][0]["status"] == "accepted"
    assert data["items"][0]["pickup_address"] == "Toshkent, Chilonzor"
    assert data["items"][0]["pickup_lat"] == pytest.approx(41.2995)
    assert data["items"][0]["receiver_phone"] == "+998911112233"


def test_driver_cannot_mark_another_drivers_order_picked_up(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    assigned_driver = create_driver(session_factory)
    other_driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, assigned_driver["profile_id"], status="accepted")

    response = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(other_driver["token"]))

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "You can update only your assigned orders"}


@pytest.mark.parametrize("order_status", ["draft", "published", "bidding", "cancelled"])
def test_driver_cannot_mark_invalid_status_order_picked_up(driver_status_client, order_status: str) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status=order_status)

    response = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver["token"]))

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "ORDER_INVALID_STATUS", "message": "Invalid order status transition"}


def test_assigned_driver_can_mark_picked_up_order_in_transit(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="picked_up")

    response = client.post(f"/api/v1/driver/orders/{order_id}/in-transit", headers=headers(driver["token"]))

    assert response.status_code == 200
    assert response.json()["message"] == "Order marked as in transit"
    db = session_factory()
    order = db.get(Order, order_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "in_transit"))
    assert order.status == "in_transit"
    assert order.in_transit_at is not None
    assert history is not None
    assert history.old_status == "picked_up"
    assert history.reason == "driver_marked_in_transit"
    db.close()


def test_driver_cannot_mark_accepted_order_directly_in_transit(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.post(f"/api/v1/driver/orders/{order_id}/in-transit", headers=headers(driver["token"]))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_assigned_driver_can_mark_in_transit_order_delivered(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="in_transit")

    response = client.post(f"/api/v1/driver/orders/{order_id}/delivered", headers=headers(driver["token"]))

    assert response.status_code == 200
    assert response.json()["message"] == "Order marked as delivered"
    db = session_factory()
    order = db.get(Order, order_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "delivered"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_marked_delivered", AuditLog.entity_id == order_id))
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["client"], Notification.type == "delivered"))
    assert order.status == "delivered"
    assert order.delivered_at is not None
    assert order.confirmed_at is None
    assert order.payment_status == "unpaid"
    assert history is not None
    assert history.old_status == "in_transit"
    assert history.reason == "driver_marked_delivered"
    assert audit is not None
    assert notification is not None
    db.close()


def test_driver_cannot_mark_picked_up_order_directly_delivered(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="picked_up")

    response = client.post(f"/api/v1/driver/orders/{order_id}/delivered", headers=headers(driver["token"]))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_driver_can_cancel_accepted_assigned_order_with_reason(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.post(
        f"/api/v1/driver/orders/{order_id}/cancel",
        headers=headers(driver["token"]),
        json={"reason": "Mashina buzilib qoldi"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Order cancelled"
    db = session_factory()
    order = db.get(Order, order_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "cancelled"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_cancelled_order", AuditLog.entity_id == order_id))
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["client"], Notification.type == "cancelled"))
    assert order.status == "cancelled"
    assert order.cancel_reason == "Mashina buzilib qoldi"
    assert order.cancelled_by == driver["user_id"]
    assert order.cancelled_at is not None
    assert order.payment_status == "unpaid"
    assert history is not None
    assert history.old_status == "accepted"
    assert history.reason == "Mashina buzilib qoldi"
    assert audit is not None
    assert notification is not None
    db.close()


@pytest.mark.parametrize("order_status", ["picked_up", "in_transit", "delivered"])
def test_driver_cannot_cancel_after_pickup(driver_status_client, order_status: str) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status=order_status)

    response = client.post(
        f"/api/v1/driver/orders/{order_id}/cancel",
        headers=headers(driver["token"]),
        json={"reason": "Mashina buzilib qoldi"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_driver_cancel_without_reason_is_rejected(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.post(f"/api/v1/driver/orders/{order_id}/cancel", headers=headers(driver["token"]), json={})

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Cancel reason is required"}


def test_unapproved_driver_cannot_update_status(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory, verification_status="pending")
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver["token"]))

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "DRIVER_NOT_APPROVED", "message": "Driver must be approved"}


def test_inactive_driver_cannot_update_status(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory, user_status="inactive")
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver["token"]))

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}


def test_non_driver_and_anonymous_user_cannot_access_status_endpoint(driver_status_client) -> None:
    client, tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    non_driver = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(tokens["client"]))
    anonymous = client.post(f"/api/v1/driver/orders/{order_id}/picked-up")

    assert non_driver.status_code == 403
    assert non_driver.json()["error"] == {"code": "FORBIDDEN", "message": "Driver role required"}
    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == {"code": "UNAUTHORIZED", "message": "Authentication required"}


def test_duplicate_picked_up_request_does_not_duplicate_status_history(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    first = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver["token"]))
    second = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver["token"]))

    assert first.status_code == 200
    assert second.status_code == 400
    db = session_factory()
    history_count = db.scalar(
        select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "picked_up")
    )
    assert history_count == 1
    db.close()


def test_stage_11_does_not_require_forbidden_fields(driver_status_client) -> None:
    client, _tokens, session_factory, ids = driver_status_client
    driver = create_driver(session_factory)
    order_id = create_assigned_order(session_factory, ids, driver["profile_id"], status="accepted")

    response = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver["token"]))

    assert response.status_code == 200
    order_columns = set(Order.__table__.columns.keys())
    assert "otp" not in order_columns
    assert "qr" not in order_columns
    assert "pickup_proof" not in order_columns
    assert "delivery_proof" not in order_columns
    assert "cargo_type" in order_columns
    assert "weight" not in order_columns
    assert "size" not in order_columns
