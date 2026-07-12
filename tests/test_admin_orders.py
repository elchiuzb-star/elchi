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
from app.models import AuditLog, Bid, City, Dispute, DriverProfile, DriverRoute, Notification, Order, StatusHistory, User


@pytest.fixture()
def admin_orders_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    users = {
        "client": User(phone="+998910000001", role="client", status="active", is_phone_verified=True, full_name="Client Name"),
        "operator": User(phone="+998910000002", role="operator", status="active", is_phone_verified=True),
        "admin": User(phone="+998910000003", role="admin", status="active", is_phone_verified=True),
        "super_admin": User(phone="+998910000004", role="super_admin", status="active", is_phone_verified=True),
        "driver_user": User(phone="+998910000005", role="driver", status="active", is_phone_verified=True),
        "blocked_driver_user": User(phone="+998910000006", role="driver", status="blocked", is_phone_verified=True),
    }
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True)
    wrong_city = City(name="Buxoro", name_uz="Buxoro", is_active=True)
    db.add_all([*users.values(), from_city, to_city, wrong_city])
    db.flush()
    driver = DriverProfile(
        user_id=users["driver_user"].id,
        full_name="Ali Valiyev",
        car_model="Cobalt",
        plate_number="01A123BC",
        verification_status="approved",
        is_available=True,
    )
    blocked_driver = DriverProfile(user_id=users["blocked_driver_user"].id, verification_status="approved", is_available=True)
    pending_driver_user = User(phone="+998910000007", role="driver", status="active", is_phone_verified=True)
    db.add(pending_driver_user)
    db.flush()
    pending_driver = DriverProfile(user_id=pending_driver_user.id, verification_status="pending", is_available=True)
    db.add_all([driver, blocked_driver, pending_driver])
    db.flush()
    db.add(DriverRoute(driver_id=driver.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"))
    db.add(DriverRoute(driver_id=blocked_driver.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"))
    db.add(DriverRoute(driver_id=pending_driver.id, from_city_id=from_city.id, to_city_id=to_city.id, status="available"))
    db.commit()
    tokens = {key: create_access_token(str(user.id)) for key, user in users.items()}
    tokens["pending_driver"] = create_access_token(str(pending_driver_user.id))
    ids = {
        "client": users["client"].id,
        "operator": users["operator"].id,
        "admin": users["admin"].id,
        "super_admin": users["super_admin"].id,
        "driver_user": users["driver_user"].id,
        "driver": driver.id,
        "blocked_driver": blocked_driver.id,
        "pending_driver": pending_driver.id,
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


def create_order(
    session_factory: sessionmaker,
    ids: dict[str, int],
    *,
    status: str = "accepted",
    driver_id: int | None = None,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
) -> int:
    db = session_factory()
    count = db.scalar(select(func.count(Order.id))) + 1
    order = Order(
        order_number=f"ORD-ST14-{count}",
        client_id=ids["client"],
        from_city_id=from_city_id or ids["from_city"],
        to_city_id=to_city_id or ids["to_city"],
        pickup_address="Toshkent, Chilonzor",
        dropoff_address="Samarqand, Registon",
        sender_phone="+998901234567",
        receiver_phone="+998911112233",
        cargo_photo_url="/uploads/cargo_photo/2026/06/photo.jpg",
        suggested_price=Decimal("60000"),
        final_price=Decimal("55000") if status not in {"draft", "published", "bidding"} else None,
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


def add_bid(session_factory: sessionmaker, order_id: int, driver_id: int, price: int = 55000, status: str = "active") -> int:
    db = session_factory()
    bid = Bid(order_id=order_id, driver_id=driver_id, price=Decimal(str(price)), status=status)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    bid_id = bid.id
    db.close()
    return bid_id


@pytest.mark.parametrize("role", ["operator", "admin", "super_admin"])
def test_staff_can_list_all_orders(admin_orders_client, role: str) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    create_order(session_factory, ids, status="accepted", driver_id=ids["driver"])

    response = client.get("/api/v1/admin/orders", headers=headers(tokens[role]))

    assert response.status_code == 200
    assert response.json()["data"]["pagination"]["total"] == 1
    item = response.json()["data"]["items"][0]
    assert item["client"]["phone"] == "+998910000001"
    assert item["assigned_driver"]["plate_number"] == "01A123BC"


@pytest.mark.parametrize("role", ["client", "driver_user"])
def test_non_staff_cannot_access_admin_orders(admin_orders_client, role: str) -> None:
    client, tokens, _session_factory, _ids = admin_orders_client

    response = client.get("/api/v1/admin/orders", headers=headers(tokens[role]))

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "Operator or admin role required"}


def test_operator_can_view_order_detail(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="accepted", driver_id=ids["driver"])
    bid_id = add_bid(session_factory, order_id, ids["driver"], status="accepted")
    db = session_factory()
    order = db.get(Order, order_id)
    order.accepted_bid_id = bid_id
    db.add(StatusHistory(order_id=order_id, old_status="bidding", new_status="accepted", changed_by_user_id=ids["client"], changed_by_role="client", reason="driver_selected"))
    db.add(Dispute(order_id=order_id, opened_by_user_id=ids["client"], reason="delayed", status="open", previous_order_status="accepted"))
    db.commit()
    db.close()

    response = client.get(f"/api/v1/admin/orders/{order_id}", headers=headers(tokens["operator"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["client"]["full_name"] == "Client Name"
    assert data["assigned_driver"]["phone"] == "+998910000005"
    assert data["accepted_bid"]["id"] == bid_id
    assert data["bids"][0]["driver_id"] == ids["driver"]
    assert data["status_history"][0]["reason"] == "driver_selected"
    assert data["dispute"]["reason"] == "delayed"
    assert "otp" not in data
    assert "pickup_proof" not in data


def test_operator_can_manually_change_status_with_reason(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="picked_up", driver_id=ids["driver"])

    response = client.patch(
        f"/api/v1/admin/orders/{order_id}/status",
        headers=headers(tokens["operator"]),
        json={"status": "in_transit", "reason": "Driver called operator"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["old_status"] == "picked_up"
    assert data["new_status"] == "in_transit"
    db = session_factory()
    order = db.get(Order, order_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "in_transit"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "admin_order_status_updated", AuditLog.entity_id == order_id))
    assert order.in_transit_at is not None
    assert history.reason == "Driver called operator"
    assert audit is not None
    db.close()


def test_manual_status_requires_reason_and_rejects_invalid_status(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="picked_up", driver_id=ids["driver"])

    missing_reason = client.patch(f"/api/v1/admin/orders/{order_id}/status", headers=headers(tokens["operator"]), json={"status": "in_transit"})
    invalid_status = client.patch(
        f"/api/v1/admin/orders/{order_id}/status",
        headers=headers(tokens["operator"]),
        json={"status": "draft", "reason": "Bad target"},
    )

    assert missing_reason.status_code == 400
    assert missing_reason.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Reason is required for manual admin/operator action"}
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_operator_cannot_cancel_confirmed_order_but_admin_and_super_admin_can(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    operator_order_id = create_order(session_factory, ids, status="confirmed", driver_id=ids["driver"])
    admin_order_id = create_order(session_factory, ids, status="confirmed", driver_id=ids["driver"])
    super_order_id = create_order(session_factory, ids, status="confirmed", driver_id=ids["driver"])

    operator_response = client.post(
        f"/api/v1/admin/orders/{operator_order_id}/cancel",
        headers=headers(tokens["operator"]),
        json={"reason": "Exceptional cancellation"},
    )
    admin_response = client.post(
        f"/api/v1/admin/orders/{admin_order_id}/cancel",
        headers=headers(tokens["admin"]),
        json={"reason": "Exceptional cancellation"},
    )
    super_response = client.post(
        f"/api/v1/admin/orders/{super_order_id}/cancel",
        headers=headers(tokens["super_admin"]),
        json={"reason": "Exceptional cancellation"},
    )

    assert operator_response.status_code == 400
    assert operator_response.json()["error"]["code"] == "ORDER_INVALID_STATUS"
    assert admin_response.status_code == 200
    assert super_response.status_code == 200


def test_operator_can_cancel_accepted_order_and_close_active_bids(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="accepted", driver_id=ids["driver"])
    bid_id = add_bid(session_factory, order_id, ids["driver"], status="active")

    response = client.post(
        f"/api/v1/admin/orders/{order_id}/cancel",
        headers=headers(tokens["operator"]),
        json={"reason": "Client unreachable"},
    )

    assert response.status_code == 200
    db = session_factory()
    order = db.get(Order, order_id)
    bid = db.get(Bid, bid_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "cancelled"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "admin_order_cancelled", AuditLog.entity_id == order_id))
    assert order.status == "cancelled"
    assert order.cancel_reason == "Client unreachable"
    assert order.cancelled_by == ids["operator"]
    assert order.cancelled_at is not None
    assert bid.status == "closed"
    assert history.reason == "Client unreachable"
    assert audit is not None
    db.close()


@pytest.mark.parametrize("order_status", ["published", "bidding"])
def test_operator_can_manually_assign_approved_driver(admin_orders_client, order_status: str) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status=order_status)
    bid_id = add_bid(session_factory, order_id, ids["driver"], status="active")

    response = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 55000, "reason": "Client requested operator assistance"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "accepted"
    assert data["assigned_driver"]["id"] == ids["driver"]
    assert data["accepted_bid_id"] == bid_id
    db = session_factory()
    order = db.get(Order, order_id)
    bid = db.get(Bid, bid_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "accepted"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "admin_driver_assigned", AuditLog.entity_id == order_id))
    notification_count = db.scalar(select(func.count(Notification.id)).where(Notification.entity_id == order_id, Notification.type == "admin_driver_assigned"))
    assert order.status == "accepted"
    assert order.assigned_driver_id == ids["driver"]
    assert order.final_price == Decimal("55000")
    assert order.system_fee_rate == Decimal("0.1500")
    assert order.system_fee == Decimal("8250.00")
    assert order.driver_income == Decimal("46750.00")
    assert order.accepted_at is not None
    assert bid.status == "accepted"
    assert history.reason == "Client requested operator assistance"
    assert audit is not None
    assert notification_count == 2
    db.close()


def test_manual_assign_closes_other_active_bids(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="bidding")
    selected_bid_id = add_bid(session_factory, order_id, ids["driver"], status="active")
    other_driver_user = User(phone="+998910000008", role="driver", status="active", is_phone_verified=True)
    db = session_factory()
    db.add(other_driver_user)
    db.flush()
    other_driver = DriverProfile(user_id=other_driver_user.id, verification_status="approved", is_available=True)
    db.add(other_driver)
    db.flush()
    db.add(DriverRoute(driver_id=other_driver.id, from_city_id=ids["from_city"], to_city_id=ids["to_city"], status="available"))
    db.commit()
    other_driver_id = other_driver.id
    db.close()
    other_bid_id = add_bid(session_factory, order_id, other_driver_id, price=61000, status="active")

    response = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 55000, "reason": "Manual assign"},
    )

    assert response.status_code == 200
    db = session_factory()
    assert db.get(Bid, selected_bid_id).status == "accepted"
    assert db.get(Bid, other_bid_id).status == "closed"
    db.close()


def test_manual_assign_validation_errors(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="published")
    cancelled_order_id = create_order(session_factory, ids, status="cancelled")
    mismatch_order_id = create_order(session_factory, ids, status="published", from_city_id=ids["wrong_city"], to_city_id=ids["to_city"])

    missing_reason = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 55000},
    )
    invalid_price = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 0, "reason": "Manual assign"},
    )
    pending_driver = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["pending_driver"], "final_price": 55000, "reason": "Manual assign"},
    )
    blocked_driver = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["blocked_driver"], "final_price": 55000, "reason": "Manual assign"},
    )
    route_mismatch = client.post(
        f"/api/v1/admin/orders/{mismatch_order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 55000, "reason": "Manual assign"},
    )
    cancelled = client.post(
        f"/api/v1/admin/orders/{cancelled_order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 55000, "reason": "Manual assign"},
    )

    assert missing_reason.status_code == 400
    assert invalid_price.json()["error"]["message"] == "final_price must be greater than 0"
    assert pending_driver.json()["error"]["code"] == "DRIVER_NOT_APPROVED"
    assert blocked_driver.json()["error"]["code"] == "DRIVER_BLOCKED"
    assert route_mismatch.json()["error"]["code"] == "ROUTE_NOT_MATCHED"
    assert cancelled.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_concurrent_manual_assignment_second_request_fails(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="published")

    first = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 55000, "reason": "Manual assign"},
    )
    second = client.post(
        f"/api/v1/admin/orders/{order_id}/assign-driver",
        headers=headers(tokens["operator"]),
        json={"driver_id": ids["driver"], "final_price": 56000, "reason": "Manual assign again"},
    )

    assert first.status_code == 200
    assert second.status_code == 400
    db = session_factory()
    order = db.get(Order, order_id)
    history_count = db.scalar(select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "accepted"))
    assert order.assigned_driver_id == ids["driver"]
    assert history_count == 1
    db.close()


def test_stage_14_does_not_add_forbidden_fields(admin_orders_client) -> None:
    client, tokens, session_factory, ids = admin_orders_client
    order_id = create_order(session_factory, ids, status="accepted", driver_id=ids["driver"])

    response = client.get(f"/api/v1/admin/orders/{order_id}", headers=headers(tokens["operator"]))

    assert response.status_code == 200
    order_columns = set(Order.__table__.columns.keys())
    route_columns = set(DriverRoute.__table__.columns.keys())
    assert "otp" not in order_columns
    assert "qr" not in order_columns
    assert "pickup_proof" not in order_columns
    assert "delivery_proof" not in order_columns
    assert "departure_time" not in route_columns
    assert "capacity" not in route_columns
    assert "cargo_type" in order_columns
    assert "weight" not in order_columns
    assert "size" not in order_columns
