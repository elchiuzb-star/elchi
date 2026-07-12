from decimal import Decimal
from datetime import datetime, timedelta, timezone

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
from app.models import AuditLog, Bid, City, DriverDocument, DriverProfile, DriverRoute, Notification, Order, RefreshSession, User

REQUIRED_DOCUMENT_TYPES = ["passport", "selfie", "license", "car_document", "car_photo"]


@pytest.fixture()
def admin_drivers_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    users = {
        "client": User(phone="+998960000001", role="client", status="active", is_phone_verified=True, full_name="Client"),
        "driver_user": User(phone="+998960000002", role="driver", status="active", is_phone_verified=True, full_name="Ali Valiyev"),
        "operator": User(phone="+998960000003", role="operator", status="active", is_phone_verified=True),
        "admin": User(phone="+998960000004", role="admin", status="active", is_phone_verified=True),
        "super_admin": User(phone="+998960000005", role="super_admin", status="active", is_phone_verified=True),
    }
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True)
    db.add_all([*users.values(), from_city, to_city])
    db.flush()
    driver = DriverProfile(
        user_id=users["driver_user"].id,
        full_name="Ali Valiyev",
        car_model="Cobalt",
        plate_number="01A123BC",
        car_color="Oq",
        verification_status="pending",
        is_available=False,
    )
    db.add(driver)
    db.flush()
    for document_type in REQUIRED_DOCUMENT_TYPES:
        db.add(
            DriverDocument(
                driver_id=driver.id,
                document_type=document_type,
                file_url=f"/uploads/{document_type}/2026/06/doc.jpg",
                status="pending",
            )
        )
    db.add(DriverRoute(driver_id=driver.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"))
    db.commit()

    tokens = {key: create_access_token(str(user.id)) for key, user in users.items()}
    ids = {
        "client": users["client"].id,
        "driver_user": users["driver_user"].id,
        "operator": users["operator"].id,
        "admin": users["admin"].id,
        "super_admin": users["super_admin"].id,
        "driver": driver.id,
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


def create_driver(
    session_factory: sessionmaker,
    ids: dict[str, int],
    *,
    verification_status: str = "pending",
    is_available: bool = False,
    user_status: str = "active",
    with_documents: bool = True,
    with_route: bool = False,
) -> dict[str, int | str]:
    db = session_factory()
    suffix = db.scalar(select(func.count(User.id))) + 100
    user = User(phone=f"+99896{suffix:07d}", role="driver", status=user_status, is_phone_verified=True)
    db.add(user)
    db.flush()
    driver = DriverProfile(
        user_id=user.id,
        full_name=f"Driver {suffix}",
        car_model="Lacetti",
        plate_number=f"01B{suffix}BC",
        verification_status=verification_status,
        is_available=is_available,
    )
    db.add(driver)
    db.flush()
    if with_documents:
        for document_type in REQUIRED_DOCUMENT_TYPES:
            db.add(
                DriverDocument(
                    driver_id=driver.id,
                    document_type=document_type,
                    file_url=f"/uploads/{document_type}/2026/06/{suffix}.jpg",
                    status="pending",
                )
            )
    if with_route:
        db.add(DriverRoute(driver_id=driver.id, from_city_id=ids["from_city"], to_city_id=ids["to_city"], status="available"))
    db.commit()
    result = {"driver_id": driver.id, "user_id": user.id, "token": create_access_token(str(user.id))}
    db.close()
    return result


def create_order(session_factory: sessionmaker, ids: dict[str, int]) -> int:
    db = session_factory()
    order = Order(
        order_number=f"ORD-ST15-{db.scalar(select(func.count(Order.id))) + 1}",
        client_id=ids["client"],
        from_city_id=ids["from_city"],
        to_city_id=ids["to_city"],
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
    db.commit()
    order_id = order.id
    db.close()
    return order_id


@pytest.mark.parametrize("role", ["operator", "admin", "super_admin"])
def test_staff_can_list_drivers(admin_drivers_client, role: str) -> None:
    client, tokens, _session_factory, _ids = admin_drivers_client

    response = client.get("/api/v1/admin/drivers?verification_status=pending&search=Ali", headers=headers(tokens[role]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 1
    assert data["items"][0]["user"]["phone"] == "+998960000002"
    assert data["items"][0]["plate_number"] == "01A123BC"


@pytest.mark.parametrize("role", ["client", "driver_user"])
def test_non_staff_cannot_list_drivers(admin_drivers_client, role: str) -> None:
    client, tokens, _session_factory, _ids = admin_drivers_client

    response = client.get("/api/v1/admin/drivers", headers=headers(tokens[role]))

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "Admin access required"}


def test_admin_driver_list_requires_authentication(admin_drivers_client) -> None:
    client, _tokens, _session_factory, _ids = admin_drivers_client

    response = client.get("/api/v1/admin/drivers")

    assert response.status_code == 401
    assert response.json()["error"] == {"code": "UNAUTHORIZED", "message": "Authentication required"}


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_staff_can_view_driver_detail_with_documents_and_routes(admin_drivers_client, role: str) -> None:
    client, tokens, _session_factory, ids = admin_drivers_client

    response = client.get(f"/api/v1/admin/drivers/{ids['driver']}", headers=headers(tokens[role]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["documents"]) == 5
    assert data["documents"][0]["rejection_reason"] is None
    assert data["routes"][0]["status"] == "available"
    assert "departure_time" not in data["routes"][0]
    assert "capacity" not in data["routes"][0]


@pytest.mark.parametrize("action", ["approve", "reject", "block"])
def test_operator_cannot_mutate_driver_verification(admin_drivers_client, action: str) -> None:
    client, tokens, _session_factory, ids = admin_drivers_client
    payload = {"comment": "checked"} if action == "approve" else {"reason": "bad docs"}

    response = client.post(f"/api/v1/admin/drivers/{ids['driver']}/{action}", headers=headers(tokens["operator"]), json=payload)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "FORBIDDEN",
        "message": "Only admin or super_admin can perform driver verification actions",
    }


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admin_and_super_admin_can_approve_pending_driver(admin_drivers_client, role: str) -> None:
    client, tokens, session_factory, ids = admin_drivers_client
    target_driver_id = ids["driver"] if role == "admin" else create_driver(session_factory, ids)["driver_id"]

    response = client.post(
        f"/api/v1/admin/drivers/{target_driver_id}/approve",
        headers=headers(tokens[role]),
        json={"comment": "Documents checked"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verification_status"] == "approved"
    assert data["is_available"] is False
    db = session_factory()
    driver = db.get(DriverProfile, target_driver_id)
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_approved", AuditLog.entity_id == target_driver_id))
    notification = db.scalar(select(Notification).where(Notification.type == "driver_approved", Notification.entity_id == target_driver_id))
    approved_doc_count = db.scalar(select(func.count(DriverDocument.id)).where(DriverDocument.driver_id == target_driver_id, DriverDocument.status == "approved"))
    assert driver.verification_status == "approved"
    assert driver.is_available is False
    assert audit is not None
    assert notification is not None
    assert approved_doc_count == 5
    db.close()


def test_approve_rejects_missing_required_documents(admin_drivers_client) -> None:
    client, tokens, session_factory, ids = admin_drivers_client
    driver = create_driver(session_factory, ids, with_documents=False)

    response = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/approve",
        headers=headers(tokens["admin"]),
        json={"comment": "checked"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "DRIVER_DOCUMENTS_INCOMPLETE",
        "message": "Required driver documents are missing",
        "details": {"missing": REQUIRED_DOCUMENT_TYPES},
    }


def test_admin_can_reject_pending_driver_with_reason(admin_drivers_client) -> None:
    client, tokens, session_factory, ids = admin_drivers_client

    response = client.post(
        f"/api/v1/admin/drivers/{ids['driver']}/reject",
        headers=headers(tokens["admin"]),
        json={"reason": "License document is not clear"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verification_status"] == "rejected"
    assert data["is_available"] is False
    assert data["reason"] == "License document is not clear"
    db = session_factory()
    driver = db.get(DriverProfile, ids["driver"])
    document = db.scalar(select(DriverDocument).where(DriverDocument.driver_id == ids["driver"], DriverDocument.document_type == "license"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_rejected", AuditLog.entity_id == ids["driver"]))
    assert driver.verification_status == "rejected"
    assert driver.is_available is False
    assert document.status == "rejected"
    assert document.rejection_reason == "License document is not clear"
    assert audit.details["reason"] == "License document is not clear"
    db.close()


@pytest.mark.parametrize("action", ["reject", "block"])
def test_reason_is_required_for_reject_and_block(admin_drivers_client, action: str) -> None:
    client, tokens, _session_factory, ids = admin_drivers_client

    response = client.post(f"/api/v1/admin/drivers/{ids['driver']}/{action}", headers=headers(tokens["admin"]), json={})

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Reason is required"}


def test_rejected_driver_cannot_become_available_or_bid(admin_drivers_client) -> None:
    client, tokens, session_factory, ids = admin_drivers_client
    order_id = create_order(session_factory, ids)
    client.post(
        f"/api/v1/admin/drivers/{ids['driver']}/reject",
        headers=headers(tokens["admin"]),
        json={"reason": "Bad documents"},
    )

    availability = client.patch("/api/v1/driver/availability", headers=headers(tokens["driver_user"]), json={"is_available": True})
    bid = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=headers(tokens["driver_user"]), json={"price": 55000})

    assert availability.status_code == 400
    assert availability.json()["error"]["code"] == "DRIVER_NOT_APPROVED"
    assert bid.status_code == 400
    assert bid.json()["error"]["code"] == "DRIVER_NOT_APPROVED"


def test_admin_can_block_approved_driver_and_disable_routes(admin_drivers_client) -> None:
    client, tokens, session_factory, ids = admin_drivers_client
    driver = create_driver(session_factory, ids, verification_status="approved", is_available=True, with_route=True)
    db = session_factory()
    db.add(
        RefreshSession(
            user_id=driver["user_id"],
            jti="driver-block-test-jti",
            token_hash="hash",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    db.commit()
    db.close()

    response = client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/block",
        headers=headers(tokens["admin"]),
        json={"reason": "Fraud suspicion"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verification_status"] == "blocked"
    assert data["user_status"] == "blocked"
    assert data["is_available"] is False
    assert data["disabled_routes_count"] == 1
    assert data["revoked_refresh_sessions_count"] == 1
    db = session_factory()
    profile = db.get(DriverProfile, driver["driver_id"])
    user = db.get(User, driver["user_id"])
    route = db.scalar(select(DriverRoute).where(DriverRoute.driver_id == driver["driver_id"]))
    refresh_session = db.scalar(select(RefreshSession).where(RefreshSession.user_id == driver["user_id"]))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_blocked", AuditLog.entity_id == driver["driver_id"]))
    route_audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_routes_disabled_after_block", AuditLog.entity_id == driver["driver_id"]))
    assert profile.verification_status == "blocked"
    assert profile.is_available is False
    assert user.status == "blocked"
    assert route.status == "unavailable"
    assert refresh_session.is_revoked is True
    assert refresh_session.revoked_at is not None
    assert audit.details["reason"] == "Fraud suspicion"
    assert route_audit is not None
    db.close()


def test_blocked_driver_cannot_use_driver_marketplace_endpoints(admin_drivers_client) -> None:
    client, tokens, session_factory, ids = admin_drivers_client
    driver = create_driver(session_factory, ids, verification_status="approved", is_available=True, with_route=True)
    order_id = create_order(session_factory, ids)
    client.post(
        f"/api/v1/admin/drivers/{driver['driver_id']}/block",
        headers=headers(tokens["admin"]),
        json={"reason": "Fraud suspicion"},
    )

    availability = client.patch("/api/v1/driver/availability", headers=headers(driver["token"]), json={"is_available": True})
    route = client.post(
        "/api/v1/driver/routes",
        headers=headers(driver["token"]),
        json={"from_city_id": ids["from_city"], "to_city_id": ids["to_city"]},
    )
    feed = client.get("/api/v1/driver/orders/feed", headers=headers(driver["token"]))
    bid = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=headers(driver["token"]), json={"price": 55000})

    assert availability.status_code == 403
    assert route.status_code == 403
    assert feed.status_code == 403
    assert bid.status_code == 403
    assert availability.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}
    assert route.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}
    assert feed.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}
    assert bid.json()["error"] == {"code": "FORBIDDEN", "message": "User account is not active"}


def test_cannot_approve_or_block_already_blocked_driver(admin_drivers_client) -> None:
    client, tokens, _session_factory, ids = admin_drivers_client
    block = client.post(
        f"/api/v1/admin/drivers/{ids['driver']}/block",
        headers=headers(tokens["admin"]),
        json={"reason": "Fraud suspicion"},
    )

    approve = client.post(
        f"/api/v1/admin/drivers/{ids['driver']}/approve",
        headers=headers(tokens["admin"]),
        json={"comment": "checked"},
    )
    block_again = client.post(
        f"/api/v1/admin/drivers/{ids['driver']}/block",
        headers=headers(tokens["admin"]),
        json={"reason": "again"},
    )

    assert block.status_code == 200
    assert approve.status_code == 400
    assert approve.json()["error"] == {"code": "DRIVER_INVALID_STATUS", "message": "Blocked driver cannot be approved"}
    assert block_again.status_code == 400
    assert block_again.json()["error"] == {"code": "DRIVER_ALREADY_BLOCKED", "message": "Driver is already blocked"}


def test_consecutive_approve_then_reject_does_not_create_inconsistent_state(admin_drivers_client) -> None:
    client, tokens, session_factory, ids = admin_drivers_client

    approve = client.post(
        f"/api/v1/admin/drivers/{ids['driver']}/approve",
        headers=headers(tokens["admin"]),
        json={"comment": "checked"},
    )
    reject = client.post(
        f"/api/v1/admin/drivers/{ids['driver']}/reject",
        headers=headers(tokens["super_admin"]),
        json={"reason": "late reject"},
    )

    assert approve.status_code == 200
    assert reject.status_code == 400
    assert reject.json()["error"]["code"] == "DRIVER_INVALID_STATUS"
    db = session_factory()
    profile = db.get(DriverProfile, ids["driver"])
    user = db.get(User, ids["driver_user"])
    assert profile.verification_status == "approved"
    assert user.status == "active"
    db.close()


def test_stage_15_does_not_add_forbidden_fields(admin_drivers_client) -> None:
    client, tokens, _session_factory, ids = admin_drivers_client

    response = client.get(f"/api/v1/admin/drivers/{ids['driver']}", headers=headers(tokens["operator"]))

    assert response.status_code == 200
    data = response.json()["data"]
    route_columns = set(DriverRoute.__table__.columns.keys())
    order_columns = set(Order.__table__.columns.keys())
    assert "departure_time" not in route_columns
    assert "capacity" not in route_columns
    assert "free_space" not in route_columns
    assert "cargo_type" in order_columns
    assert "weight" not in order_columns
    assert "size" not in order_columns
    assert "otp" not in order_columns
    assert "qr" not in order_columns
    assert "pickup_proof" not in data
    assert "delivery_proof" not in data
    assert db_has_no_tracking_artifacts()


def db_has_no_tracking_artifacts() -> bool:
    forbidden_table_names = {"chat_messages", "tracking_events", "payments", "proofs"}
    return forbidden_table_names.isdisjoint(Base.metadata.tables.keys())


@pytest.mark.parametrize("role", ["operator", "admin", "super_admin"])
def test_staff_can_update_driver_vehicle(admin_drivers_client, role: str) -> None:
    client, tokens, _session_factory, ids = admin_drivers_client
    driver_id = ids["driver"]

    response = client.patch(
        f"/api/v1/admin/drivers/{driver_id}/vehicle",
        headers=headers(tokens[role]),
        json={"full_name": "Vali Aliyev", "car_model": "Malibu", "plate_number": "30 X 999 YZ", "car_color": "Qora"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["car_model"] == "Malibu"
    assert data["car_color"] == "Qora"
    assert data["plate_number_normalized"] == "30X999YZ"
    assert data["user"]["full_name"] == "Vali Aliyev"


def test_client_cannot_update_driver_vehicle(admin_drivers_client) -> None:
    client, tokens, _session_factory, ids = admin_drivers_client

    response = client.patch(
        f"/api/v1/admin/drivers/{ids['driver']}/vehicle",
        headers=headers(tokens["client"]),
        json={"car_model": "Malibu"},
    )

    assert response.status_code == 403


def test_admin_vehicle_update_rejects_duplicate_plate(admin_drivers_client) -> None:
    client, tokens, session_factory, ids = admin_drivers_client
    other = create_driver(session_factory, ids, verification_status="approved")
    db = session_factory()
    other_plate = db.scalar(select(DriverProfile.plate_number).where(DriverProfile.id == other["driver_id"]))
    db.close()

    response = client.patch(
        f"/api/v1/admin/drivers/{ids['driver']}/vehicle",
        headers=headers(tokens["admin"]),
        json={"plate_number": other_plate},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLATE_NUMBER_ALREADY_EXISTS"
