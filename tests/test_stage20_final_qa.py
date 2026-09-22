from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AuditLog,
    Bid,
    City,
    DriverProfile,
    DriverRoute,
    Notification,
    Order,
    OrderOffer,
    Rating,
    RouteTariff,
    StatusHistory,
    User,
)


@pytest.fixture()
def final_qa_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    monkeypatch.setattr(settings, "public_upload_base_url", "/uploads")
    monkeypatch.setattr(settings, "max_image_upload_mb", 5)
    monkeypatch.setattr(settings, "max_document_upload_mb", 10)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    admin = User(phone="+998990000001", role="admin", status="active", is_phone_verified=True)
    operator = User(phone="+998990000002", role="operator", status="active", is_phone_verified=True)
    super_admin = User(phone="+998990000003", role="super_admin", status="active", is_phone_verified=True)
    blocked_user = User(phone="+998990000004", role="client", status="blocked", is_phone_verified=True)
    inactive_user = User(phone="+998990000005", role="client", status="inactive", is_phone_verified=True)
    db.add_all([admin, operator, super_admin, blocked_user, inactive_user])
    db.commit()
    ids = {
        "admin": admin.id,
        "operator": operator.id,
        "super_admin": super_admin.id,
        "blocked_user": blocked_user.id,
        "inactive_user": inactive_user.id,
    }
    tokens = {
        "admin": create_access_token(str(admin.id)),
        "operator": create_access_token(str(operator.id)),
        "super_admin": create_access_token(str(super_admin.id)),
        "blocked_user": create_access_token(str(blocked_user.id)),
        "inactive_user": create_access_token(str(inactive_user.id)),
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


def request_and_verify_otp(client: TestClient, phone: str, role: str) -> dict:
    request_response = client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": role})
    assert request_response.status_code == 200
    dev_otp = request_response.json()["data"]["dev_otp"]
    assert dev_otp == settings.dev_mock_otp
    assert len(dev_otp) == settings.otp_length

    verify_response = client.post("/api/v1/auth/verify-otp", json={"phone": phone, "role": role, "otp": dev_otp})
    assert verify_response.status_code == 200
    body = verify_response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["role"] == role
    return body


def create_city(client: TestClient, admin_token: str, name: str, region: str) -> int:
    response = client.post(
        "/api/v1/admin/cities",
        headers=headers(admin_token),
        json={"name_uz": name, "name_ru": name, "region": region, "requires_district": False},
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def upload_cargo_photo(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/files/upload",
        headers=headers(token),
        data={"type": "cargo_photo"},
        files={"file": ("cargo.jpg", b"\xff\xd8\xff\xe0fake-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 200
    return response.json()["data"]["file_url"]


def test_full_mvp_happy_path_and_database_consistency(final_qa_client) -> None:
    client, tokens, session_factory, ids = final_qa_client

    client_auth = request_and_verify_otp(client, "+998991000001", "client")
    driver_auth = request_and_verify_otp(client, "+998991000002", "driver")
    client_token = client_auth["access_token"]
    driver_token = driver_auth["access_token"]

    assert client.get("/api/v1/auth/me", headers=headers(client_token)).json()["role"] == "client"
    driver_me = client.get("/api/v1/auth/me", headers=headers(driver_token))
    assert driver_me.status_code == 200
    assert driver_me.json()["role"] == "driver"

    # Staff never reach the OTP path (commit 2ba7f0b): no public admin
    # registration and no OTP login, they sign in via /auth/staff-login.
    public_admin = client.post("/api/v1/auth/request-otp", json={"phone": "+998991000003", "role": "admin"})
    assert public_admin.status_code == 400
    assert public_admin.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"
    with session_factory() as check_db:
        assert check_db.scalar(select(User).where(User.phone == "+998991000003")) is None

    city_a_id = create_city(client, tokens["admin"], "Toshkent", "Toshkent")
    city_b_id = create_city(client, tokens["admin"], "Samarqand", "Samarqand")
    city_c_id = create_city(client, tokens["admin"], "Buxoro", "Buxoro")

    tariff_response = client.post(
        "/api/v1/admin/route-tariffs",
        headers=headers(tokens["admin"]),
        json={
            "from_city_id": city_a_id,
            "to_city_id": city_b_id,
            "min_price": "50000",
            "suggested_price": "60000",
            "max_price": "80000",
        },
    )
    assert tariff_response.status_code == 200
    assert client.get("/api/v1/admin/cities", headers=headers(tokens["operator"])).status_code == 200
    assert client.get("/api/v1/admin/route-tariffs", headers=headers(tokens["operator"])).status_code == 200
    assert client.post("/api/v1/admin/cities", headers=headers(client_token), json={"name_uz": "Xiva"}).status_code == 403
    assert (
        client.post(
            "/api/v1/admin/route-tariffs",
            headers=headers(driver_token),
            json={"from_city_id": city_b_id, "to_city_id": city_c_id, "suggested_price": "70000"},
        ).status_code
        == 403
    )

    profile_response = client.get("/api/v1/driver/profile", headers=headers(driver_token))
    assert profile_response.status_code == 200
    assert profile_response.json()["data"]["verification_status"] == "new"
    assert profile_response.json()["data"]["is_available"] is False

    update_profile = client.patch(
        "/api/v1/driver/profile",
        headers=headers(driver_token),
        json={
            "full_name": "Ali Valiyev",
            "car_model": "Cobalt",
            "plate_number": "01A123BC",
            "car_color": "White",
            "verification_status": "approved",
            "rating": 5,
            "completed_orders": 10,
            "is_available": True,
        },
    )
    assert update_profile.status_code == 200
    assert update_profile.json()["data"]["verification_status"] == "new"
    assert "rating" not in update_profile.json()["data"]

    document_types = ["passport", "selfie", "license", "car_document", "car_photo"]
    for document_type in document_types:
        uploaded = client.post(
            "/api/v1/files/upload",
            headers=headers(driver_token),
            data={"type": document_type},
            files={"file": ("file.jpg", b"\xff\xd8\xff\xe0fake-image-bytes", "image/jpeg")},
        )
        assert uploaded.status_code == 200
        response = client.post(
            "/api/v1/driver/documents",
            headers=headers(driver_token),
            json={"document_type": document_type, "file_url": uploaded.json()["data"]["file_url"]},
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "pending"

    rejected_upload_type = client.post(
        "/api/v1/files/upload",
        headers=headers(client_token),
        data={"type": "pickup_proof"},
        files={"file": ("proof.jpg", b"\xff\xd8\xff\xe0fake-image-bytes", "image/jpeg")},
    )
    assert rejected_upload_type.status_code == 400

    db = session_factory()
    driver_user = db.scalar(select(User).where(User.phone == "+998991000002"))
    driver_profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == driver_user.id))
    driver_profile_id = driver_profile.id
    driver_user_id = driver_user.id
    db.close()

    operator_approval = client.post(f"/api/v1/admin/drivers/{driver_profile_id}/approve", headers=headers(tokens["operator"]), json={})
    assert operator_approval.status_code == 403
    approve_response = client.post(
        f"/api/v1/admin/drivers/{driver_profile_id}/approve",
        headers=headers(tokens["admin"]),
        json={"comment": "Required documents checked"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["verification_status"] == "approved"
    assert approve_response.json()["data"]["is_available"] is False

    availability_response = client.patch("/api/v1/driver/availability", headers=headers(driver_token), json={"is_available": True})
    assert availability_response.status_code == 200
    assert availability_response.json()["data"]["is_available"] is True

    route_response = client.post(
        "/api/v1/driver/routes",
        headers=headers(driver_token),
        json={"from_city_id": city_a_id, "to_city_id": city_b_id},
    )
    assert route_response.status_code == 200
    assert route_response.json()["data"]["status"] == "available"
    assert "departure_time" not in route_response.json()["data"]
    assert "capacity" not in route_response.json()["data"]

    same_city_route = client.post(
        "/api/v1/driver/routes",
        headers=headers(driver_token),
        json={"from_city_id": city_a_id, "to_city_id": city_a_id},
    )
    assert same_city_route.status_code == 400

    cargo_photo_url = upload_cargo_photo(client, client_token)
    order_payload = {
        "from_city_id": city_a_id,
        "to_city_id": city_b_id,
        "pickup_address": "Toshkent, Chilonzor, 12-mavze",
        "dropoff_address": "Samarqand, Registon ko'chasi",
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": cargo_photo_url,
        "comment": "Handle carefully",
    }
    create_order_response = client.post("/api/v1/client/orders", headers=headers(client_token), json=order_payload)
    assert create_order_response.status_code == 200
    order_id = create_order_response.json()["data"]["id"]
    assert create_order_response.json()["data"]["payment_method"] == "cash"
    assert create_order_response.json()["data"]["payment_status"] == "unpaid"

    publish_response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(client_token))
    assert publish_response.status_code == 200
    assert publish_response.json()["data"]["status"] == "published"
    assert publish_response.json()["data"]["matched_drivers_count"] == 1

    feed_response = client.get("/api/v1/driver/orders/feed", headers=headers(driver_token))
    assert feed_response.status_code == 200
    assert feed_response.json()["data"]["items"][0]["id"] == order_id
    assert "sender_phone" not in feed_response.json()["data"]["items"][0]
    assert "pickup_address" not in feed_response.json()["data"]["items"][0]

    limited_detail = client.get(f"/api/v1/driver/orders/{order_id}", headers=headers(driver_token))
    assert limited_detail.status_code == 200
    for forbidden_key in ["sender_phone", "receiver_phone", "pickup_address", "dropoff_address"]:
        assert forbidden_key not in limited_detail.json()["data"]

    bid_response = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=headers(driver_token), json={"price": 55000})
    assert bid_response.status_code == 200
    bid_id = bid_response.json()["data"]["bid_id"]
    assert bid_response.json()["data"]["status"] == "active"

    client_order_detail = client.get(f"/api/v1/client/orders/{order_id}", headers=headers(client_token))
    assert client_order_detail.status_code == 200
    assert client_order_detail.json()["data"]["bids_count"] == 1

    select_response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(client_token),
        json={"bid_id": bid_id},
    )
    assert select_response.status_code == 200
    assert select_response.json()["data"]["status"] == "accepted"
    assert Decimal(str(select_response.json()["data"]["final_price"])) == Decimal("55000")

    full_detail = client.get(f"/api/v1/driver/orders/{order_id}", headers=headers(driver_token))
    assert full_detail.status_code == 200
    assert full_detail.json()["data"]["sender_phone"] == "+998901234567"
    assert full_detail.json()["data"]["receiver_phone"] == "+998911112233"
    assert full_detail.json()["data"]["pickup_address"] == "Toshkent, Chilonzor, 12-mavze"

    picked_up = client.post(f"/api/v1/driver/orders/{order_id}/picked-up", headers=headers(driver_token))
    in_transit = client.post(f"/api/v1/driver/orders/{order_id}/in-transit", headers=headers(driver_token))
    delivered = client.post(f"/api/v1/driver/orders/{order_id}/delivered", headers=headers(driver_token))
    assert picked_up.status_code == 200
    assert in_transit.status_code == 200
    assert delivered.status_code == 200

    confirm_response = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(client_token))
    assert confirm_response.status_code == 200
    assert confirm_response.json()["data"]["status"] == "confirmed"
    assert confirm_response.json()["data"]["payment_method"] == "cash"
    assert confirm_response.json()["data"]["payment_status"] == "paid_manual"

    rating_response = client.post(
        f"/api/v1/client/orders/{order_id}/rating",
        headers=headers(client_token),
        json={"rating": 5, "comment": "Great delivery"},
    )
    assert rating_response.status_code == 200
    assert rating_response.json()["data"]["rating"] == 5

    admin_detail = client.get(f"/api/v1/admin/orders/{order_id}", headers=headers(tokens["operator"]))
    assert admin_detail.status_code == 200
    assert admin_detail.json()["data"]["status_history"]
    assert admin_detail.json()["data"]["bids"]
    for forbidden_key in ["otp", "qr", "pickup_proof", "delivery_proof"]:
        assert forbidden_key not in admin_detail.text

    db = session_factory()
    order = db.get(Order, order_id)
    bid = db.get(Bid, bid_id)
    accepted_bids_count = db.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id, Bid.status == "accepted"))
    rating_count = db.scalar(select(func.count(Rating.id)).where(Rating.order_id == order_id))
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id, OrderOffer.driver_id == driver_profile_id))
    status_history = list(db.scalars(select(StatusHistory).where(StatusHistory.order_id == order_id).order_by(StatusHistory.id)))
    audit_actions = set(db.scalars(select(AuditLog.action)))
    notification_types = set(db.scalars(select(Notification.type).where(Notification.user_id.in_([ids["admin"], driver_user_id, client_auth["user"]["id"]]))))

    assert order.client_id == client_auth["user"]["id"]
    assert order.assigned_driver_id == driver_profile_id
    assert order.accepted_bid_id == bid_id
    assert order.final_price == bid.price
    assert order.status == "confirmed"
    assert order.confirmed_at is not None
    assert order.payment_method == "cash"
    assert order.payment_status == "paid_manual"
    assert accepted_bids_count == 1
    assert rating_count == 1
    assert offer.result == "bid_sent"
    assert [item.new_status for item in status_history] == [
        "draft",
        "published",
        "bidding",
        "accepted",
        "picked_up",
        "in_transit",
        "delivered",
        "confirmed",
    ]
    assert {"city_created", "route_tariff_created", "driver_approved", "order_published", "driver_bid_created", "driver_selected", "order_confirmed"}.issubset(
        audit_actions
    )
    assert {"driver_approved", "driver_selected", "confirmed", "rating_received"}.issubset(notification_types)
    db.close()


def test_stage20_removed_features_are_not_active_model_or_openapi_fields(final_qa_client) -> None:
    client, _tokens, _session_factory, _ids = final_qa_client
    removed_fields = {
        "weight",
        "size",
        "volume",
        "capacity",
        "free_space",
        "driver_capacity",
        "departure_time",
        "arrival_time",
        "pickup_time",
        "delivery_time",
        "otp",
        "qr",
        "pickup_proof",
        "delivery_proof",
        "receiver_confirmation_code",
        "delivery_photo",
        "gps",
        "tracking",
        "online_payment",
        "payme",
        "click",
        "escrow",
        "p2p",
        "chat",
    }

    active_columns = set()
    for model in [Order, DriverRoute, RouteTariff, Bid, OrderOffer, Rating, DriverProfile]:
        active_columns.update(model.__table__.columns.keys())
    assert active_columns.isdisjoint(removed_fields)

    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    request_properties = set()
    for component in schema.json()["components"]["schemas"].values():
        request_properties.update(component.get("properties", {}).keys())
    auth_allowed_fields = {"otp"}
    forbidden_openapi_fields = (removed_fields | {"online_payment"}) - auth_allowed_fields
    assert request_properties.isdisjoint(forbidden_openapi_fields)


def test_stage20_core_permission_regressions(final_qa_client) -> None:
    client, tokens, _session_factory, _ids = final_qa_client

    protected_endpoints = [
        ("get", "/api/v1/auth/me"),
        ("get", "/api/v1/driver/profile"),
        ("get", "/api/v1/admin/orders"),
        ("get", "/api/v1/admin/audit-logs"),
    ]
    for method, url in protected_endpoints:
        response = getattr(client, method)(url)
        assert response.status_code == 401

    anonymous_upload = client.post(
        "/api/v1/files/upload",
        data={"type": "cargo_photo"},
        files={"file": ("cargo.jpg", b"\xff\xd8\xff\xe0fake-image-bytes", "image/jpeg")},
    )
    assert anonymous_upload.status_code == 401

    blocked_response = client.get("/api/v1/auth/me", headers=headers(tokens["blocked_user"]))
    inactive_response = client.get("/api/v1/auth/me", headers=headers(tokens["inactive_user"]))
    assert blocked_response.status_code == 403
    assert inactive_response.status_code == 403

    client_auth = request_and_verify_otp(client, "+998992000001", "client")
    driver_auth = request_and_verify_otp(client, "+998992000002", "driver")
    assert client.get("/api/v1/driver/profile", headers=headers(client_auth["access_token"])).status_code == 403
    assert client.get("/api/v1/admin/orders", headers=headers(driver_auth["access_token"])).status_code == 403
    assert client.get("/api/v1/admin/audit-logs", headers=headers(tokens["operator"])).status_code == 403
    assert client.get("/api/v1/admin/audit-logs", headers=headers(tokens["admin"])).status_code == 200
    assert client.get("/api/v1/admin/audit-logs", headers=headers(tokens["super_admin"])).status_code == 200
