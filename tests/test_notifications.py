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
from app.models import City, DriverProfile, DriverRoute, Notification, Order, RouteTariff, User
from app.services.notification_service import ALLOWED_NOTIFICATION_TYPES, create_notification


@pytest.fixture()
def notifications_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998970000001", role="client", status="active", is_phone_verified=True)
    other_client = User(phone="+998970000002", role="client", status="active", is_phone_verified=True)
    driver_user = User(phone="+998970000003", role="driver", status="active", is_phone_verified=True)
    operator = User(phone="+998970000004", role="operator", status="active", is_phone_verified=True)
    blocked_user = User(phone="+998970000005", role="client", status="blocked", is_phone_verified=True)
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
    db.add_all([client_user, other_client, driver_user, operator, blocked_user, from_city, to_city])
    db.flush()
    driver = DriverProfile(
        user_id=driver_user.id,
        car_model="Cobalt",
        plate_number="01A777AA",
        verification_status="approved",
        is_available=True,
    )
    db.add(driver)
    db.flush()
    db.add(DriverRoute(driver_id=driver.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"))
    db.add(RouteTariff(from_city_id=from_city.id, to_city_id=to_city.id, suggested_price=Decimal("60000"), is_active=True))
    order = Order(
        order_number="ORD-ST16-1",
        client_id=client_user.id,
        from_city_id=from_city.id,
        to_city_id=to_city.id,
        pickup_address="Toshkent, Chilonzor",
        dropoff_address="Samarqand, Registon",
        sender_phone="+998901234567",
        receiver_phone="+998911112233",
        cargo_photo_url="/uploads/cargo_photo/2026/06/photo.jpg",
        suggested_price=Decimal("60000"),
        payment_method="cash",
        payment_status="unpaid",
        status="published",
    )
    db.add(order)
    db.flush()
    create_notification(db, client_user.id, "new_bid", "Yangi taklif", "Haydovchi yangi narx taklif qildi", order_id=order.id)
    read_notification = create_notification(db, client_user.id, "cancelled", "Buyurtma bekor qilindi", "Buyurtma bekor qilindi", order_id=order.id)
    read_notification.is_read = True
    create_notification(db, other_client.id, "new_bid", "Other", "Hidden", order_id=order.id)
    db.commit()

    tokens = {
        "client": create_access_token(str(client_user.id)),
        "other_client": create_access_token(str(other_client.id)),
        "driver": create_access_token(str(driver_user.id)),
        "operator": create_access_token(str(operator.id)),
        "blocked": create_access_token(str(blocked_user.id)),
    }
    ids = {
        "client": client_user.id,
        "other_client": other_client.id,
        "driver_user": driver_user.id,
        "driver": driver.id,
        "from_city": from_city.id,
        "to_city": to_city.id,
        "order": order.id,
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


def test_authenticated_user_can_list_own_notifications_with_unread_count(notifications_client) -> None:
    client, tokens, _session_factory, ids = notifications_client

    response = client.get("/api/v1/notifications?page=1&limit=20", headers=headers(tokens["client"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 2
    assert data["unread_count"] == 1
    assert {item["type"] for item in data["items"]} == {"new_bid", "cancelled"}
    assert all(item["order_id"] == ids["order"] for item in data["items"])
    assert all(item["channel"] == "in_app" for item in data["items"])
    assert all("body" in item for item in data["items"])


def test_anonymous_and_blocked_users_cannot_access_notifications(notifications_client) -> None:
    client, tokens, _session_factory, _ids = notifications_client

    anonymous = client.get("/api/v1/notifications")
    blocked = client.get("/api/v1/notifications", headers=headers(tokens["blocked"]))

    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == {"code": "UNAUTHORIZED", "message": "Authentication required"}
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "FORBIDDEN"


def test_user_sees_only_own_notifications(notifications_client) -> None:
    client, tokens, _session_factory, _ids = notifications_client

    response = client.get("/api/v1/notifications", headers=headers(tokens["other_client"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 1
    assert data["items"][0]["title"] == "Other"


def test_notification_filters_and_pagination_work(notifications_client) -> None:
    client, tokens, _session_factory, ids = notifications_client

    unread = client.get("/api/v1/notifications?is_read=false", headers=headers(tokens["client"]))
    by_type = client.get("/api/v1/notifications?type=cancelled", headers=headers(tokens["client"]))
    by_order = client.get(f"/api/v1/notifications?order_id={ids['order']}", headers=headers(tokens["client"]))
    paginated = client.get("/api/v1/notifications?page=1&limit=1", headers=headers(tokens["client"]))
    invalid_type = client.get("/api/v1/notifications?type=sms_sent", headers=headers(tokens["client"]))

    assert unread.json()["data"]["pagination"]["total"] == 1
    assert unread.json()["data"]["items"][0]["is_read"] is False
    assert by_type.json()["data"]["pagination"]["total"] == 1
    assert by_type.json()["data"]["items"][0]["type"] == "cancelled"
    assert by_order.json()["data"]["pagination"]["total"] == 2
    assert paginated.json()["data"]["pagination"]["limit"] == 1
    assert invalid_type.status_code == 400
    assert invalid_type.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Invalid notification type"}


def test_user_can_mark_own_notification_read_idempotently(notifications_client) -> None:
    client, tokens, session_factory, ids = notifications_client
    db = session_factory()
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["client"], Notification.is_read == False))  # noqa: E712
    notification_id = notification.id
    db.close()

    first = client.patch(f"/api/v1/notifications/{notification_id}/read", headers=headers(tokens["client"]), json={})
    second = client.patch(f"/api/v1/notifications/{notification_id}/read", headers=headers(tokens["client"]), json={})

    assert first.status_code == 200
    assert first.json()["data"] == {"id": notification_id, "is_read": True}
    assert second.status_code == 200
    assert second.json()["data"] == {"id": notification_id, "is_read": True}


def test_user_cannot_mark_another_users_notification_read(notifications_client) -> None:
    client, tokens, session_factory, ids = notifications_client
    db = session_factory()
    other_notification = db.scalar(select(Notification).where(Notification.user_id == ids["other_client"]))
    db.close()

    response = client.patch(f"/api/v1/notifications/{other_notification.id}/read", headers=headers(tokens["client"]), json={})
    missing = client.patch("/api/v1/notifications/999999/read", headers=headers(tokens["client"]), json={})

    assert response.status_code == 404
    assert response.json()["error"] == {"code": "NOT_FOUND", "message": "Notification not found"}
    assert missing.status_code == 404
    assert missing.json()["error"] == {"code": "NOT_FOUND", "message": "Notification not found"}


def test_mark_all_read_updates_only_current_user_notifications(notifications_client) -> None:
    client, tokens, session_factory, ids = notifications_client

    response = client.patch("/api/v1/notifications/read-all", headers=headers(tokens["client"]), json={})

    assert response.status_code == 200
    assert response.json()["data"]["updated_count"] == 1
    db = session_factory()
    client_unread = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == ids["client"], Notification.is_read == False))  # noqa: E712
    other_unread = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == ids["other_client"], Notification.is_read == False))  # noqa: E712
    assert client_unread == 0
    assert other_unread == 1
    db.close()


def test_notification_service_creates_in_app_notification_with_defaults(notifications_client) -> None:
    _client, _tokens, session_factory, ids = notifications_client
    db = session_factory()

    notification = create_notification(db, ids["driver_user"], "driver_selected", "Siz tanlandingiz", "Mijoz sizning taklifingizni tanladi", order_id=ids["order"])
    db.commit()
    db.refresh(notification)

    assert notification.type == "driver_selected"
    assert notification.message == "Mijoz sizning taklifingizni tanladi"
    assert notification.order_id == ids["order"]
    assert notification.channel == "in_app"
    assert notification.is_read is False
    assert notification.sent_at is not None
    db.close()


def test_notification_service_validates_type_and_can_create_mvp_lifecycle_types(notifications_client) -> None:
    _client, _tokens, session_factory, ids = notifications_client
    db = session_factory()
    created_types = [
        "order_published",
        "new_bid",
        "driver_selected",
        "picked_up",
        "in_transit",
        "delivered",
        "confirmed",
        "cancelled",
        "disputed",
        "rating_received",
        "driver_approved",
        "driver_rejected",
        "driver_blocked",
    ]

    invalid = create_notification(db, ids["client"], "sms_sent", "SMS", "No external provider", order_id=ids["order"])
    for notification_type in created_types:
        assert notification_type in ALLOWED_NOTIFICATION_TYPES
        result = create_notification(db, ids["client"], notification_type, notification_type, "body", order_id=ids["order"])
        assert not hasattr(result, "status_code")
    db.commit()

    assert invalid.status_code == 400
    assert db.scalar(select(func.count(Notification.id)).where(Notification.user_id == ids["client"])) >= len(created_types)
    db.close()


def test_order_published_creates_notification_for_matched_driver(notifications_client) -> None:
    client, tokens, session_factory, ids = notifications_client
    payload = {
        "from_city_id": ids["from_city"],
        "to_city_id": ids["to_city"],
        "pickup_address": "Toshkent, Chilonzor",
        "dropoff_address": "Samarqand, Registon",
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": None,
    }

    create_response = client.post("/api/v1/client/orders", headers=headers(tokens["client"]), json=payload)
    order_id = create_response.json()["data"]["id"]
    publish_response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))

    assert publish_response.status_code == 200
    db = session_factory()
    notification = db.scalar(
        select(Notification).where(
            Notification.user_id == ids["driver_user"],
            Notification.order_id == order_id,
            Notification.type == "order_published",
        )
    )
    assert notification is not None
    assert notification.title == "Yangi buyurtma"
    assert notification.channel == "in_app"
    assert notification.sent_at is not None
    db.close()


def test_stage_16_does_not_add_external_notification_or_tracking_fields(notifications_client) -> None:
    _client, _tokens, _session_factory, _ids = notifications_client

    notification_columns = set(Notification.__table__.columns.keys())
    forbidden_columns = {"sms_provider_id", "fcm_token", "email_status", "websocket_channel", "otp", "qr", "gps_location"}
    forbidden_tables = {"chat_messages", "payment_notifications", "sms_deliveries", "fcm_deliveries", "tracking_events"}

    assert forbidden_columns.isdisjoint(notification_columns)
    # Scoped to legacy v1 models (wave 3 integration, A0a): stage-2 chat/tracking tables live in wired v2 modules
    # (app.modules.*) and may share Base.metadata in the same process; v1 models must still not add them.
    legacy_tables = {
        mapper.local_table.name for mapper in Base.registry.mappers if mapper.class_.__module__.startswith("app.models")
    }
    assert forbidden_tables.isdisjoint(legacy_tables)
