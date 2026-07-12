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
from app.models import AuditLog, City, Dispute, DriverProfile, Notification, Order, StatusHistory, User


@pytest.fixture()
def disputes_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    users = {
        "client": User(phone="+998990000001", role="client", status="active", is_phone_verified=True),
        "other_client": User(phone="+998990000002", role="client", status="active", is_phone_verified=True),
        "driver_user": User(phone="+998990000003", role="driver", status="active", is_phone_verified=True),
        "other_driver_user": User(phone="+998990000004", role="driver", status="active", is_phone_verified=True),
        "operator": User(phone="+998990000005", role="operator", status="active", is_phone_verified=True),
        "admin": User(phone="+998990000006", role="admin", status="active", is_phone_verified=True),
    }
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True)
    db.add_all([*users.values(), from_city, to_city])
    db.flush()
    driver = DriverProfile(user_id=users["driver_user"].id, full_name="Ali Valiyev", verification_status="approved", is_available=True)
    other_driver = DriverProfile(user_id=users["other_driver_user"].id, full_name="Vali Aliyev", verification_status="approved", is_available=True)
    db.add_all([driver, other_driver])
    db.commit()
    tokens = {key: create_access_token(str(user.id)) for key, user in users.items()}
    ids = {
        "client": users["client"].id,
        "other_client": users["other_client"].id,
        "driver_user": users["driver_user"].id,
        "other_driver_user": users["other_driver_user"].id,
        "operator": users["operator"].id,
        "admin": users["admin"].id,
        "driver": driver.id,
        "other_driver": other_driver.id,
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


def create_order(
    session_factory: sessionmaker,
    ids: dict[str, int],
    *,
    client_id: int | None = None,
    driver_id: int | None = None,
    status: str = "accepted",
) -> int:
    db = session_factory()
    count = db.scalar(select(func.count(Order.id))) + 1
    order = Order(
        order_number=f"ORD-ST13-{count}",
        client_id=client_id or ids["client"],
        from_city_id=ids["from_city"],
        to_city_id=ids["to_city"],
        pickup_address="Toshkent, Chilonzor",
        dropoff_address="Samarqand, Registon",
        sender_phone="+998901234567",
        receiver_phone="+998911112233",
        cargo_photo_url="/uploads/cargo_photo/2026/06/photo.jpg",
        suggested_price=Decimal("60000"),
        final_price=Decimal("55000"),
        payment_method="cash",
        payment_status="unpaid",
        status=status,
        assigned_driver_id=driver_id if driver_id is not None else ids["driver"],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    order_id = order.id
    db.close()
    return order_id


def open_dispute_request(client: TestClient, token: str, order_id: int, reason: str = "delayed"):
    return client.post(
        f"/api/v1/orders/{order_id}/disputes",
        headers=headers(token),
        json={"reason": reason, "comment": "Haydovchi kechikyapti"},
    )


@pytest.mark.parametrize("order_status", ["accepted", "picked_up", "in_transit", "delivered"])
def test_client_can_open_dispute_for_own_allowed_order_statuses(disputes_client, order_status: str) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status=order_status)

    response = open_dispute_request(client, tokens["client"], order_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["order_id"] == order_id
    assert data["status"] == "open"
    assert data["previous_order_status"] == order_status
    assert data["order_status"] == "disputed"

    db = session_factory()
    order = db.get(Order, order_id)
    dispute = db.scalar(select(Dispute).where(Dispute.order_id == order_id))
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "disputed"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "dispute_opened", AuditLog.entity_id == order_id))
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["driver_user"], Notification.type == "disputed"))
    assert order.status == "disputed"
    assert dispute.previous_order_status == order_status
    assert dispute.comment == "Haydovchi kechikyapti"
    assert history.reason == "dispute_opened"
    assert audit is not None
    assert notification is not None
    db.close()


def test_client_cannot_open_dispute_for_another_clients_order(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, client_id=ids["other_client"], status="accepted")

    response = open_dispute_request(client, tokens["client"], order_id)

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "You do not have permission to open dispute for this order"}


def test_driver_can_open_dispute_for_assigned_order(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, driver_id=ids["driver"], status="in_transit")

    response = open_dispute_request(client, tokens["driver_user"], order_id, reason="damaged")

    assert response.status_code == 200
    assert response.json()["data"]["reason"] == "damaged"
    db = session_factory()
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["client"], Notification.type == "disputed"))
    assert notification is not None
    db.close()


def test_driver_cannot_open_dispute_for_unassigned_order(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, driver_id=ids["driver"], status="in_transit")

    response = open_dispute_request(client, tokens["other_driver_user"], order_id)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(("role", "order_status"), [("operator", "published"), ("admin", "confirmed")])
def test_staff_can_open_dispute_for_any_allowed_order(disputes_client, role: str, order_status: str) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, client_id=ids["other_client"], status=order_status)

    response = open_dispute_request(client, tokens[role], order_id, reason="other")

    assert response.status_code == 200
    assert response.json()["data"]["previous_order_status"] == order_status


@pytest.mark.parametrize("order_status", ["draft", "cancelled"])
def test_draft_and_cancelled_orders_cannot_be_disputed(disputes_client, order_status: str) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status=order_status)

    response = open_dispute_request(client, tokens["client"], order_id)

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "ORDER_INVALID_STATUS", "message": "This order status cannot be disputed"}


def test_invalid_reason_and_duplicate_active_dispute_are_rejected(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status="accepted")

    invalid = open_dispute_request(client, tokens["client"], order_id, reason="photo_proof")
    first = open_dispute_request(client, tokens["client"], order_id)
    second = open_dispute_request(client, tokens["client"], order_id)

    assert invalid.status_code == 400
    assert invalid.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Invalid dispute reason"}
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"] == {"code": "ALREADY_EXISTS", "message": "This order already has an active dispute"}


def test_dispute_list_visibility_for_client_driver_and_operator(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    own_order_id = create_order(session_factory, ids, status="accepted")
    other_order_id = create_order(session_factory, ids, client_id=ids["other_client"], driver_id=ids["other_driver"], status="accepted")
    open_dispute_request(client, tokens["client"], own_order_id)
    open_dispute_request(client, tokens["operator"], other_order_id)

    client_list = client.get("/api/v1/disputes", headers=headers(tokens["client"]))
    driver_list = client.get("/api/v1/disputes", headers=headers(tokens["driver_user"]))
    operator_list = client.get("/api/v1/disputes", headers=headers(tokens["operator"]))

    assert client_list.status_code == 200
    assert [item["order_id"] for item in client_list.json()["data"]["items"]] == [own_order_id]
    assert driver_list.status_code == 200
    assert [item["order_id"] for item in driver_list.json()["data"]["items"]] == [own_order_id]
    assert operator_list.status_code == 200
    assert operator_list.json()["data"]["pagination"]["total"] == 2


def test_admin_list_and_detail_include_order_context(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status="delivered")
    dispute_id = open_dispute_request(client, tokens["client"], order_id).json()["data"]["dispute_id"]

    list_response = client.get("/api/v1/admin/disputes?status=open", headers=headers(tokens["operator"]))
    detail_response = client.get(f"/api/v1/admin/disputes/{dispute_id}", headers=headers(tokens["operator"]))

    assert list_response.status_code == 200
    item = list_response.json()["data"]["items"][0]
    assert item["order"]["order_number"].startswith("ORD-ST13-")
    assert item["order"]["client_phone"] == "+998990000001"
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["order"]["pickup_address"] == "Toshkent, Chilonzor"
    assert detail["client"]["phone"] == "+998990000001"
    assert detail["driver"]["phone"] == "+998990000003"
    assert detail["status_history"]


def test_operator_can_update_dispute_to_under_review(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status="picked_up")
    dispute_id = open_dispute_request(client, tokens["client"], order_id).json()["data"]["dispute_id"]

    response = client.patch(
        f"/api/v1/admin/disputes/{dispute_id}",
        headers=headers(tokens["operator"]),
        json={"status": "under_review", "resolution": "Operator bog'landi"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["dispute_status"] == "under_review"
    db = session_factory()
    order = db.get(Order, order_id)
    dispute = db.get(Dispute, dispute_id)
    assert order.status == "disputed"
    assert dispute.resolution == "Operator bog'landi"
    db.close()


@pytest.mark.parametrize("target_status", ["resolved", "rejected"])
def test_resolved_or_rejected_dispute_requires_resolution(disputes_client, target_status: str) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status="in_transit")
    dispute_id = open_dispute_request(client, tokens["client"], order_id).json()["data"]["dispute_id"]

    response = client.patch(
        f"/api/v1/admin/disputes/{dispute_id}",
        headers=headers(tokens["operator"]),
        json={"status": target_status},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Resolution is required for resolved or rejected dispute"}


@pytest.mark.parametrize(("target_status", "reason"), [("resolved", "dispute_resolved"), ("rejected", "dispute_rejected")])
def test_final_dispute_status_restores_order_and_writes_history(disputes_client, target_status: str, reason: str) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status="in_transit")
    dispute_id = open_dispute_request(client, tokens["client"], order_id).json()["data"]["dispute_id"]

    response = client.patch(
        f"/api/v1/admin/disputes/{dispute_id}",
        headers=headers(tokens["operator"]),
        json={"status": target_status, "resolution": "Muammo hal qilindi"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dispute_status"] == target_status
    assert data["order_status"] == "in_transit"
    assert data["resolved_by"] == ids["operator"]
    assert data["resolved_at"] is not None

    db = session_factory()
    order = db.get(Order, order_id)
    dispute = db.get(Dispute, dispute_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.reason == reason))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "order_status_restored_after_dispute", AuditLog.entity_id == order_id))
    notification_count = db.scalar(select(func.count(Notification.id)).where(Notification.entity_id == order_id, Notification.type == "disputed"))
    assert order.status == "in_transit"
    assert dispute.resolution == "Muammo hal qilindi"
    assert dispute.resolved_by == ids["operator"]
    assert dispute.resolved_at is not None
    assert history is not None
    assert history.old_status == "disputed"
    assert audit is not None
    assert notification_count >= 2
    db.close()


def test_final_dispute_cannot_be_reopened(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status="delivered")
    dispute_id = open_dispute_request(client, tokens["client"], order_id).json()["data"]["dispute_id"]
    client.patch(
        f"/api/v1/admin/disputes/{dispute_id}",
        headers=headers(tokens["operator"]),
        json={"status": "resolved", "resolution": "Hal qilindi"},
    )

    response = client.patch(
        f"/api/v1/admin/disputes/{dispute_id}",
        headers=headers(tokens["operator"]),
        json={"status": "open"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Resolved or rejected disputes are final"


def test_non_staff_cannot_access_admin_disputes(disputes_client) -> None:
    client, tokens, _session_factory, _ids = disputes_client

    response = client.get("/api/v1/admin/disputes", headers=headers(tokens["client"]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_stage_13_does_not_require_forbidden_fields(disputes_client) -> None:
    client, tokens, session_factory, ids = disputes_client
    order_id = create_order(session_factory, ids, status="accepted")

    response = open_dispute_request(client, tokens["client"], order_id)

    assert response.status_code == 200
    order_columns = set(Order.__table__.columns.keys())
    dispute_columns = set(Dispute.__table__.columns.keys())
    assert "otp" not in dispute_columns
    assert "qr" not in dispute_columns
    assert "pickup_proof" not in dispute_columns
    assert "delivery_proof" not in dispute_columns
    assert "payment_gateway_refund" not in dispute_columns
    assert "cargo_type" in order_columns
    assert "weight" not in order_columns
    assert "size" not in order_columns
