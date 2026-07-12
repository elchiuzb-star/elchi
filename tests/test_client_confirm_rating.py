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
from app.models import AuditLog, City, DriverProfile, Notification, Order, Rating, StatusHistory, User


@pytest.fixture()
def confirm_rating_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998980000001", role="client", status="active", is_phone_verified=True)
    other_client = User(phone="+998980000002", role="client", status="active", is_phone_verified=True)
    driver_user = User(phone="+998980000003", role="driver", status="active", is_phone_verified=True)
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True)
    db.add_all([client_user, other_client, driver_user, from_city, to_city])
    db.flush()
    driver = DriverProfile(
        user_id=driver_user.id,
        full_name="Ali Valiyev",
        verification_status="approved",
        is_available=True,
        rating_avg=Decimal("0"),
    )
    db.add(driver)
    db.commit()
    tokens = {
        "client": create_access_token(str(client_user.id)),
        "other_client": create_access_token(str(other_client.id)),
        "driver": create_access_token(str(driver_user.id)),
    }
    ids = {
        "client": client_user.id,
        "other_client": other_client.id,
        "driver_user": driver_user.id,
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


def create_order(
    session_factory: sessionmaker,
    ids: dict[str, int],
    *,
    client_id: int | None = None,
    driver_id: int | None = None,
    status: str = "delivered",
) -> int:
    db = session_factory()
    count = db.scalar(select(func.count(Order.id))) + 1
    order = Order(
        order_number=f"ORD-ST12-{count}",
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


def test_client_can_confirm_own_delivered_order(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="delivered")

    response = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(tokens["client"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["order_id"] == order_id
    assert data["status"] == "confirmed"
    assert data["payment_method"] == "cash"
    assert data["payment_status"] == "paid_manual"
    assert data["confirmed_at"] is not None

    db = session_factory()
    order = db.get(Order, order_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "confirmed"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "order_confirmed", AuditLog.entity_id == order_id))
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["driver_user"], Notification.type == "confirmed"))
    assert order.status == "confirmed"
    assert order.confirmed_at is not None
    assert order.payment_method == "cash"
    assert order.payment_status == "paid_manual"
    assert history is not None
    assert history.old_status == "delivered"
    assert history.changed_by_role == "client"
    assert history.reason == "client_confirmed"
    assert audit is not None
    assert audit.details["new_value"]["payment_status"] == "paid_manual"
    assert notification is not None
    db.close()


def test_client_cannot_confirm_another_clients_order(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, client_id=ids["other_client"], status="delivered")

    response = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(tokens["client"]))

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "You can access only your own orders"}


@pytest.mark.parametrize("order_status", ["draft", "published", "bidding", "accepted", "picked_up", "in_transit", "confirmed", "cancelled", "disputed"])
def test_client_cannot_confirm_invalid_statuses(confirm_rating_client, order_status: str) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status=order_status)

    response = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(tokens["client"]))

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "ORDER_INVALID_STATUS", "message": "Only delivered orders can be confirmed"}


def test_client_cannot_confirm_order_without_assigned_driver(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, driver_id=None, status="delivered")
    db = session_factory()
    order = db.get(Order, order_id)
    order.assigned_driver_id = None
    db.commit()
    db.close()

    response = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(tokens["client"]))

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Order has no assigned driver"}


def test_duplicate_confirm_fails_and_does_not_duplicate_history(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="delivered")

    first = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(tokens["client"]))
    second = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(tokens["client"]))

    assert first.status_code == 200
    assert second.status_code == 400
    db = session_factory()
    count = db.scalar(select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "confirmed"))
    assert count == 1
    db.close()


def test_client_can_rate_own_confirmed_order_and_driver_rating_recalculates(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="confirmed")

    response = client.post(
        f"/api/v1/client/orders/{order_id}/rating",
        headers=headers(tokens["client"]),
        json={"rating": 5, "comment": "Yaxshi yetkazib berdi"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["order_id"] == order_id
    assert data["driver_id"] == ids["driver"]
    assert data["rating"] == 5
    assert data["comment"] == "Yaxshi yetkazib berdi"

    db = session_factory()
    rating = db.scalar(select(Rating).where(Rating.order_id == order_id))
    driver = db.get(DriverProfile, ids["driver"])
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "rating_created", AuditLog.entity_id == rating.id))
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["driver_user"], Notification.type == "rating_received"))
    assert rating is not None
    assert rating.client_id == ids["client"]
    assert driver.rating_avg == Decimal("5.00")
    assert audit is not None
    assert notification is not None
    db.close()


def test_rating_comment_is_optional(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="confirmed")

    response = client.post(f"/api/v1/client/orders/{order_id}/rating", headers=headers(tokens["client"]), json={"rating": 4})

    assert response.status_code == 200
    assert response.json()["data"]["comment"] is None


@pytest.mark.parametrize("rating_value", [0, 6])
def test_rating_must_be_between_one_and_five(confirm_rating_client, rating_value: int) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="confirmed")

    response = client.post(
        f"/api/v1/client/orders/{order_id}/rating",
        headers=headers(tokens["client"]),
        json={"rating": rating_value},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Rating must be between 1 and 5"}


def test_client_cannot_rate_before_confirmed(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="delivered")

    response = client.post(f"/api/v1/client/orders/{order_id}/rating", headers=headers(tokens["client"]), json={"rating": 5})

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "ORDER_INVALID_STATUS", "message": "Only confirmed orders can be rated"}


def test_client_cannot_rate_another_clients_order(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, client_id=ids["other_client"], status="confirmed")

    response = client.post(f"/api/v1/client/orders/{order_id}/rating", headers=headers(tokens["client"]), json={"rating": 5})

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "You can access only your own orders"}


def test_client_cannot_rate_order_without_assigned_driver(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="confirmed")
    db = session_factory()
    order = db.get(Order, order_id)
    order.assigned_driver_id = None
    db.commit()
    db.close()

    response = client.post(f"/api/v1/client/orders/{order_id}/rating", headers=headers(tokens["client"]), json={"rating": 5})

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Order has no assigned driver"}


def test_client_cannot_rate_same_order_twice(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="confirmed")

    first = client.post(f"/api/v1/client/orders/{order_id}/rating", headers=headers(tokens["client"]), json={"rating": 5})
    second = client.post(f"/api/v1/client/orders/{order_id}/rating", headers=headers(tokens["client"]), json={"rating": 4})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"] == {"code": "ALREADY_EXISTS", "message": "Rating already exists for this order"}


def test_stage_12_does_not_require_forbidden_confirmation_or_payment_fields(confirm_rating_client) -> None:
    client, tokens, session_factory, ids = confirm_rating_client
    order_id = create_order(session_factory, ids, status="delivered")

    response = client.post(f"/api/v1/client/orders/{order_id}/confirm", headers=headers(tokens["client"]), json={})

    assert response.status_code == 200
    order_columns = set(Order.__table__.columns.keys())
    assert "otp" not in order_columns
    assert "qr" not in order_columns
    assert "delivery_proof" not in order_columns
    assert "payment_gateway_session" not in order_columns
    assert "cargo_type" in order_columns
    assert "weight" not in order_columns
    assert "size" not in order_columns
