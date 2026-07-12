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
from app.models import AuditLog, Bid, City, DriverProfile, DriverRoute, Notification, Order, RouteTariff, StatusHistory, SystemSetting, User


@pytest.fixture()
def select_driver_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998960000001", role="client", status="active", is_phone_verified=True)
    other_client = User(phone="+998960000002", role="client", status="active", is_phone_verified=True)
    from_city = City(name="Toshkent", name_uz="Toshkent", requires_district=False, is_active=True)
    to_city = City(name="Samarqand", name_uz="Samarqand", requires_district=False, is_active=True)
    db.add_all([client_user, other_client, from_city, to_city])
    db.commit()
    for item in [client_user, other_client, from_city, to_city]:
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
        "pickup_address": "Toshkent, Chilonzor, aniq manzil",
        "dropoff_address": "Samarqand, aniq manzil",
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": "/uploads/cargo_photo/2026/06/photo.jpg",
        "comment": "Ehtiyot qilib olib boring",
    }


def create_driver(
    session_factory: sessionmaker,
    ids: dict[str, int],
    *,
    verification_status: str = "approved",
    user_status: str = "active",
    full_name: str = "Ali Valiyev",
) -> dict[str, int | str]:
    db = session_factory()
    suffix = db.scalar(select(func.count(User.id))) + 20
    user = User(phone=f"+99896{suffix:07d}", role="driver", status=user_status, is_phone_verified=True)
    db.add(user)
    db.flush()
    driver = DriverProfile(
        user_id=user.id,
        full_name=full_name,
        car_model="Cobalt",
        plate_number=f"01A{suffix:03d}BC",
        verification_status=verification_status,
        is_available=True,
        rating_avg=Decimal("4.80"),
        completed_orders=24,
    )
    db.add(driver)
    db.flush()
    db.add(
        DriverRoute(
            driver_id=driver.id,
            from_city_id=ids["from_city"],
            to_city_id=ids["to_city"],
            status="available",
        )
    )
    db.commit()
    result = {
        "profile_id": driver.id,
        "user_id": user.id,
        "phone": user.phone,
        "token": create_access_token(str(user.id)),
    }
    db.close()
    return result


def create_order(client: TestClient, token: str, ids: dict[str, int]) -> int:
    response = client.post("/api/v1/client/orders", headers=headers(token), json=order_payload(ids))
    assert response.status_code == 200
    return response.json()["data"]["id"]


def publish_order(client: TestClient, token: str, order_id: int) -> None:
    response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(token))
    assert response.status_code == 200


def create_bid(client: TestClient, driver_token: str, order_id: int, price: int) -> int:
    response = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver_token),
        json={"price": price},
    )
    assert response.status_code == 200
    return response.json()["data"]["bid_id"]


def bidding_order_with_bids(select_driver_client, *, bid_status: str = "active"):
    client, tokens, session_factory, ids = select_driver_client
    selected_driver = create_driver(session_factory, ids, full_name="Ali Valiyev")
    other_driver = create_driver(session_factory, ids, full_name="Vali Aliyev")
    order_id = create_order(client, tokens["client"], ids)
    publish_order(client, tokens["client"], order_id)
    selected_bid_id = create_bid(client, selected_driver["token"], order_id, 55000)
    other_bid_id = create_bid(client, other_driver["token"], order_id, 62000)
    if bid_status != "active":
        db = session_factory()
        bid = db.get(Bid, selected_bid_id)
        bid.status = bid_status
        db.commit()
        db.close()
    return client, tokens, session_factory, ids, selected_driver, other_driver, order_id, selected_bid_id, other_bid_id


def test_client_sees_only_active_own_order_bids_sorted_by_price(select_driver_client) -> None:
    client, tokens, session_factory, ids = select_driver_client
    expensive_driver = create_driver(session_factory, ids, full_name="Qimmat Haydovchi")
    cheap_driver = create_driver(session_factory, ids, full_name="Arzon Haydovchi")
    inactive_driver = create_driver(session_factory, ids, full_name="Yopiq Taklif")
    order_id = create_order(client, tokens["client"], ids)
    publish_order(client, tokens["client"], order_id)
    expensive_bid_id = create_bid(client, expensive_driver["token"], order_id, 62000)
    cheap_bid_id = create_bid(client, cheap_driver["token"], order_id, 55000)
    inactive_bid_id = create_bid(client, inactive_driver["token"], order_id, 50000)
    db = session_factory()
    inactive_bid = db.get(Bid, inactive_bid_id)
    inactive_bid.status = "closed"
    db.commit()
    db.close()

    response = client.get(f"/api/v1/client/orders/{order_id}/bids", headers=headers(tokens["client"]))
    forbidden = client.get(f"/api/v1/client/orders/{order_id}/bids", headers=headers(tokens["other_client"]))

    assert response.status_code == 200
    bids = response.json()["data"]
    assert [item["id"] for item in bids] == [cheap_bid_id, expensive_bid_id]
    assert [Decimal(str(item["price"])) for item in bids] == [Decimal("55000"), Decimal("62000")]
    assert bids[0]["status"] == "active"
    assert bids[0]["driver"]["id"] == cheap_driver["profile_id"]
    assert bids[0]["driver"]["full_name"] == "Arzon Haydovchi"
    assert bids[0]["driver"]["car_model"] == "Cobalt"
    assert bids[0]["driver"]["plate_number"].startswith("01A")
    assert Decimal(str(bids[0]["driver"]["rating"])) == Decimal("4.8")
    assert bids[0]["driver"]["completed_orders"] == 24
    assert inactive_bid_id not in [item["id"] for item in bids]
    assert forbidden.status_code == 403
    assert forbidden.json()["error"] == {"code": "FORBIDDEN", "message": "You can view bids only for your own order"}


def test_client_can_select_active_bid_for_own_bidding_order(select_driver_client) -> None:
    client, tokens, session_factory, ids, selected_driver, _other_driver, order_id, selected_bid_id, other_bid_id = bidding_order_with_bids(
        select_driver_client
    )

    response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": selected_bid_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Driver selected"
    data = body["data"]
    assert data["order_id"] == order_id
    assert data["status"] == "accepted"
    assert Decimal(str(data["final_price"])) == Decimal("55000")
    assert data["assigned_driver"]["id"] == selected_driver["profile_id"]
    assert data["assigned_driver"]["phone"] == selected_driver["phone"]
    assert data["assigned_driver"]["car_model"] == "Cobalt"
    assert data["assigned_driver"]["plate_number"].startswith("01A")
    assert Decimal(str(data["assigned_driver"]["rating"])) == Decimal("4.8")
    assert data["assigned_driver"]["completed_orders"] == 24
    assert data["accepted_bid"] == {"id": selected_bid_id, "price": 55000.0, "status": "accepted"}

    db = session_factory()
    order = db.get(Order, order_id)
    selected_bid = db.get(Bid, selected_bid_id)
    other_bid = db.get(Bid, other_bid_id)
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "accepted"))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_selected", AuditLog.entity_id == order_id))
    notification = db.scalar(select(Notification).where(Notification.user_id == selected_driver["user_id"], Notification.type == "driver_selected"))
    assert order.status == "accepted"
    assert order.assigned_driver_id == selected_driver["profile_id"]
    assert order.accepted_bid_id == selected_bid_id
    assert order.final_price == Decimal("55000")
    assert order.system_fee_rate == Decimal("0.1500")
    assert order.system_fee == Decimal("8250.00")
    assert order.driver_income == Decimal("46750.00")
    assert order.accepted_at is not None
    assert order.payment_method == "cash"
    assert order.payment_status == "unpaid"
    assert selected_bid.status == "accepted"
    assert other_bid.status == "closed"
    assert history is not None
    assert history.old_status == "bidding"
    assert history.changed_by_role == "client"
    assert history.reason == "driver_selected"
    assert audit is not None
    assert audit.details["new_value"]["accepted_bid_id"] == selected_bid_id
    assert notification is not None
    assert notification.title == "Siz tanlandingiz"
    db.close()


def test_selected_order_keeps_commission_snapshot_when_setting_changes(select_driver_client) -> None:
    client, tokens, session_factory, _ids, _selected_driver, _other_driver, order_id, selected_bid_id, _other_bid_id = bidding_order_with_bids(
        select_driver_client
    )
    db = session_factory()
    db.add(
        SystemSetting(
            key="driver_commission_rate",
            value="0.20",
            description="Driver commission for test",
        )
    )
    db.commit()
    db.close()

    response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": selected_bid_id},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert Decimal(str(data["system_fee_rate"])) == Decimal("0.2")
    assert Decimal(str(data["system_fee"])) == Decimal("11000.0")
    assert Decimal(str(data["driver_income"])) == Decimal("44000.0")

    db = session_factory()
    setting = db.get(SystemSetting, "driver_commission_rate")
    setting.value = "0.10"
    db.commit()
    order = db.get(Order, order_id)
    assert order.system_fee_rate == Decimal("0.2000")
    assert order.system_fee == Decimal("11000.00")
    assert order.driver_income == Decimal("44000.00")
    db.close()


def test_client_cannot_select_bid_for_another_clients_order(select_driver_client) -> None:
    client, tokens, _session_factory, _ids, _selected_driver, _other_driver, order_id, selected_bid_id, _other_bid_id = bidding_order_with_bids(
        select_driver_client
    )

    response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["other_client"]),
        json={"bid_id": selected_bid_id},
    )

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "You can select driver only for your own order"}


@pytest.mark.parametrize("order_status", ["draft", "published", "accepted"])
def test_client_cannot_select_when_order_is_not_bidding(select_driver_client, order_status: str) -> None:
    client, tokens, session_factory, _ids, _selected_driver, _other_driver, order_id, selected_bid_id, _other_bid_id = bidding_order_with_bids(
        select_driver_client
    )
    db = session_factory()
    order = db.get(Order, order_id)
    order.status = order_status
    db.commit()
    db.close()

    response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": selected_bid_id},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "ORDER_INVALID_STATUS", "message": "Only bidding orders can accept a driver"}


@pytest.mark.parametrize("bid_status", ["closed", "rejected", "expired"])
def test_client_cannot_select_inactive_bid_statuses(select_driver_client, bid_status: str) -> None:
    client, tokens, _session_factory, _ids, _selected_driver, _other_driver, order_id, selected_bid_id, _other_bid_id = bidding_order_with_bids(
        select_driver_client,
        bid_status=bid_status,
    )

    response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": selected_bid_id},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "BID_NOT_ACTIVE", "message": "Only active bids can be selected"}


def test_client_cannot_select_bid_from_another_order(select_driver_client) -> None:
    client, tokens, session_factory, ids, _selected_driver, _other_driver, order_id, _selected_bid_id, _other_bid_id = bidding_order_with_bids(
        select_driver_client
    )
    extra_driver = create_driver(session_factory, ids)
    other_order_id = create_order(client, tokens["client"], ids)
    publish_order(client, tokens["client"], other_order_id)
    other_order_bid_id = create_bid(client, extra_driver["token"], other_order_id, 58000)

    response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": other_order_bid_id},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Bid does not belong to this order"}


@pytest.mark.parametrize(
    ("verification_status", "user_status", "error_code", "message"),
    [
        ("pending", "active", "DRIVER_NOT_APPROVED", "Selected driver is not approved"),
        ("approved", "blocked", "DRIVER_BLOCKED", "Selected driver is not available"),
    ],
)
def test_client_cannot_select_unapproved_or_blocked_driver_bid(
    select_driver_client,
    verification_status: str,
    user_status: str,
    error_code: str,
    message: str,
) -> None:
    client, tokens, session_factory, ids = select_driver_client
    driver = create_driver(session_factory, ids, verification_status=verification_status, user_status=user_status)
    order_id = create_order(client, tokens["client"], ids)
    db = session_factory()
    order = db.get(Order, order_id)
    order.status = "bidding"
    bid = Bid(order_id=order_id, driver_id=driver["profile_id"], price=Decimal("55000"), status="active")
    db.add(bid)
    db.commit()
    db.refresh(bid)
    bid_id = bid.id
    db.close()

    response = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": bid_id},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {"code": error_code, "message": message}


def test_double_selection_request_fails_without_inconsistent_state(select_driver_client) -> None:
    client, tokens, session_factory, _ids, selected_driver, _other_driver, order_id, selected_bid_id, _other_bid_id = bidding_order_with_bids(
        select_driver_client
    )

    first = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": selected_bid_id},
    )
    second = client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": selected_bid_id},
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "ORDER_INVALID_STATUS"

    db = session_factory()
    order = db.get(Order, order_id)
    accepted_bids_count = db.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id, Bid.status == "accepted"))
    accepted_history_count = db.scalar(
        select(func.count(StatusHistory.id)).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "accepted")
    )
    assert order.assigned_driver_id == selected_driver["profile_id"]
    assert accepted_bids_count == 1
    assert accepted_history_count == 1
    db.close()


def test_selected_driver_gets_full_detail_and_other_driver_does_not(select_driver_client) -> None:
    client, tokens, _session_factory, _ids, _selected_driver, other_driver, order_id, selected_bid_id, _other_bid_id = bidding_order_with_bids(
        select_driver_client
    )
    client.post(
        f"/api/v1/client/orders/{order_id}/select-driver",
        headers=headers(tokens["client"]),
        json={"bid_id": selected_bid_id},
    )

    selected_detail = client.get(f"/api/v1/driver/orders/{order_id}", headers=headers(_selected_driver["token"]))
    other_detail = client.get(f"/api/v1/driver/orders/{order_id}", headers=headers(other_driver["token"]))

    assert selected_detail.status_code == 200
    selected_data = selected_detail.json()["data"]
    assert selected_data["pickup_address"] == "Toshkent, Chilonzor, aniq manzil"
    assert selected_data["dropoff_address"] == "Samarqand, aniq manzil"
    assert selected_data["sender_phone"] == "+998901234567"
    assert selected_data["receiver_phone"] == "+998911112233"
    assert selected_data["payment_method"] == "cash"
    assert selected_data["payment_status"] == "unpaid"
    assert other_detail.status_code == 200
    other_data = other_detail.json()["data"]
    assert other_data["id"] == order_id
    assert other_data["my_bid"]["id"] == _other_bid_id
    assert "pickup_address" not in other_data
    assert "sender_phone" not in other_data
