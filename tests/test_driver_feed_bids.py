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
from app.models import (
    AuditLog,
    Bid,
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
def driver_orders_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998950000001", role="client", status="active", is_phone_verified=True)
    from_city = City(name="Toshkent", name_uz="Toshkent", is_active=True, requires_district=False)
    to_city = City(name="Samarqand", name_uz="Samarqand", is_active=True, requires_district=False)
    wrong_city = City(name="Buxoro", name_uz="Buxoro", is_active=True, requires_district=False)
    db.add_all([client_user, from_city, to_city, wrong_city])
    db.commit()
    for item in [client_user, from_city, to_city, wrong_city]:
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
    tokens = {"client": create_access_token(str(client_user.id))}
    ids = {
        "client": client_user.id,
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
        "pickup_address": "Chilonzor, 12-mavze, uy 4",
        "dropoff_address": "Samarqand shahar, Registon ko'chasi",
        "pickup_lat": 41.2995,
        "pickup_lng": 69.2401,
        "dropoff_lat": 39.6542,
        "dropoff_lng": 66.9597,
        "sender_phone": "+998901234567",
        "receiver_phone": "+998911112233",
        "cargo_photo_url": "/uploads/cargo_photo/2026/06/photo.jpg",
        "comment": "Ehtiyot qilib olib boring",
    }
    if "from_district" in ids:
        payload["from_district_id"] = ids["from_district"]
    if "to_district" in ids:
        payload["to_district_id"] = ids["to_district"]
    return payload


def create_driver(
    session_factory: sessionmaker,
    ids: dict[str, int],
    *,
    verification_status: str = "approved",
    is_available: bool = True,
    route_status: str = "available",
    from_city_id: int | None = None,
    to_city_id: int | None = None,
    from_district_id: int | None = None,
    to_district_id: int | None = None,
    full_name: str | None = None,
    car_model: str | None = None,
    plate_number: str | None = None,
    rating_avg: Decimal | None = None,
    completed_orders: int = 0,
) -> dict[str, int | str]:
    db = session_factory()
    suffix = db.scalar(select(func.count(User.id))) + 10
    user = User(phone=f"+99895{suffix:07d}", role="driver", status="active", is_phone_verified=True)
    db.add(user)
    db.flush()
    driver = DriverProfile(
        user_id=user.id,
        verification_status=verification_status,
        is_available=is_available,
        full_name=full_name,
        car_model=car_model,
        plate_number=plate_number,
        rating_avg=rating_avg or Decimal("0.00"),
        completed_orders=completed_orders,
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
    result = {"profile_id": driver.id, "user_id": user.id, "token": create_access_token(str(user.id))}
    db.close()
    return result


def create_and_publish_order(client: TestClient, tokens: dict[str, str], ids: dict[str, int]) -> int:
    create_response = client.post("/api/v1/client/orders", headers=headers(tokens["client"]), json=order_payload(ids))
    assert create_response.status_code == 200
    order_id = create_response.json()["data"]["id"]
    publish_response = client.post(f"/api/v1/client/orders/{order_id}/publish", headers=headers(tokens["client"]))
    assert publish_response.status_code == 200
    return order_id


def test_approved_available_driver_can_see_matched_order_in_feed(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    response = client.get("/api/v1/driver/orders/feed", headers=headers(driver["token"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 1
    item = data["items"][0]
    assert item["id"] == order_id
    assert item["pickup_area"] == "Chilonzor"
    assert item["dropoff_area"] == "Samarqand shahar"
    assert item["my_bid"] is None
    assert "pickup_address" not in item
    assert "pickup_lat" not in item
    assert "dropoff_lat" not in item
    assert "sender_phone" not in item


def test_matching_driver_can_see_feed_even_when_offer_was_not_precreated(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    db = session_factory()
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id, OrderOffer.driver_id == driver["profile_id"]))
    db.delete(offer)
    db.commit()
    db.close()

    response = client.get("/api/v1/driver/orders/feed", headers=headers(driver["token"]))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["items"]] == [order_id]


def test_unapproved_driver_cannot_use_feed(driver_orders_client) -> None:
    client, _tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids, verification_status="pending")

    response = client.get("/api/v1/driver/orders/feed", headers=headers(driver["token"]))

    assert response.status_code == 400
    assert response.json()["error"] == {"code": "DRIVER_NOT_APPROVED", "message": "Driver must be approved"}


def test_unavailable_driver_cannot_create_bid(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    unavailable_driver = create_driver(session_factory, ids, is_available=False)
    approved_driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    db = session_factory()
    db.add(OrderOffer(order_id=order_id, driver_id=unavailable_driver["profile_id"], status="shown", result="shown"))
    db.commit()
    db.close()

    response = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(unavailable_driver["token"]),
        json={"price": 55000},
    )

    assert approved_driver["profile_id"] != unavailable_driver["profile_id"]
    assert response.status_code == 400
    assert response.json()["error"] == {"code": "DRIVER_NOT_AVAILABLE", "message": "Driver must be available"}


def test_wrong_route_driver_cannot_see_order_in_feed(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids, from_city_id=ids["wrong_city"])
    create_and_publish_order(client, tokens, ids)

    response = client.get("/api/v1/driver/orders/feed", headers=headers(driver["token"]))

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_driver_feed_matches_exact_required_district_pair(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
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
    matching_driver = create_driver(
        session_factory,
        ids,
        from_district_id=from_district.id,
        to_district_id=to_district.id,
    )
    wrong_district_driver = create_driver(
        session_factory,
        ids,
        from_district_id=other_from_district.id,
        to_district_id=to_district.id,
    )
    order_id = create_and_publish_order(client, tokens, district_ids)

    matching_feed = client.get("/api/v1/driver/orders/feed", headers=headers(matching_driver["token"]))
    wrong_feed = client.get("/api/v1/driver/orders/feed", headers=headers(wrong_district_driver["token"]))

    assert matching_feed.status_code == 200
    assert [item["id"] for item in matching_feed.json()["data"]["items"]] == [order_id]
    assert matching_feed.json()["data"]["items"][0]["pickup_area"] == "Chilonzor"
    assert wrong_feed.status_code == 200
    assert wrong_feed.json()["data"]["items"] == []


def test_driver_can_update_and_delete_own_route(driver_orders_client) -> None:
    client, _tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)

    db = session_factory()
    route = db.scalar(select(DriverRoute).where(DriverRoute.driver_id == driver["profile_id"]))
    route_id = route.id
    db.close()

    update_response = client.patch(
        f"/api/v1/driver/routes/{route_id}",
        headers=headers(driver["token"]),
        json={"from_city_id": ids["to_city"], "to_city_id": ids["from_city"]},
    )

    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["id"] == route_id
    assert updated["from_city"]["id"] == ids["to_city"]
    assert updated["to_city"]["id"] == ids["from_city"]

    delete_response = client.delete(f"/api/v1/driver/routes/{route_id}", headers=headers(driver["token"]))

    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["status"] == "deleted"
    db = session_factory()
    deleted_route = db.get(DriverRoute, route_id)
    assert deleted_route is None
    db.close()


def test_rejected_order_does_not_appear_in_feed(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    db = session_factory()
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id, OrderOffer.driver_id == driver["profile_id"]))
    offer.result = "rejected"
    db.commit()
    db.close()

    response = client.get("/api/v1/driver/orders/feed", headers=headers(driver["token"]))

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_driver_sees_limited_detail_before_assignment(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    response = client.get(f"/api/v1/driver/orders/{order_id}", headers=headers(driver["token"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pickup_area"] == "Chilonzor"
    assert data["dropoff_area"] == "Samarqand shahar"
    assert "pickup_address" not in data
    assert "dropoff_address" not in data
    assert "pickup_lat" not in data
    assert "pickup_lng" not in data
    assert "dropoff_lat" not in data
    assert "dropoff_lng" not in data
    assert "sender_phone" not in data
    assert "receiver_phone" not in data


def test_assigned_driver_sees_full_detail(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)
    db = session_factory()
    order = db.get(Order, order_id)
    order.status = "accepted"
    order.assigned_driver_id = driver["profile_id"]
    order.final_price = Decimal("55000")
    order.system_fee_rate = Decimal("0.0000")
    order.system_fee = Decimal("0.00")
    order.driver_income = Decimal("55000.00")
    db.commit()
    db.close()

    response = client.get(f"/api/v1/driver/orders/{order_id}", headers=headers(driver["token"]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pickup_address"] == "Chilonzor, 12-mavze, uy 4"
    assert data["dropoff_address"] == "Samarqand shahar, Registon ko'chasi"
    assert data["sender_phone"] == "+998901234567"
    assert data["receiver_phone"] == "+998911112233"
    assert data["pickup_lat"] == pytest.approx(41.2995)
    assert data["pickup_lng"] == pytest.approx(69.2401)
    assert data["dropoff_lat"] == pytest.approx(39.6542)
    assert data["dropoff_lng"] == pytest.approx(66.9597)
    assert data["payment_method"] == "cash"
    assert Decimal(str(data["system_fee_rate"])) == Decimal("0.0")
    assert Decimal(str(data["system_fee"])) == Decimal("0.0")
    assert Decimal(str(data["driver_income"])) == Decimal("55000.0")


def test_driver_can_create_bid_and_first_bid_changes_order_to_bidding(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    response = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 55000},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert Decimal(str(data["price"])) == Decimal("55000")
    assert data["status"] == "active"

    db = session_factory()
    order = db.get(Order, order_id)
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id, OrderOffer.driver_id == driver["profile_id"]))
    history = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order_id, StatusHistory.new_status == "bidding"))
    notification = db.scalar(select(Notification).where(Notification.user_id == ids["client"], Notification.type == "new_bid"))
    bid_audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_bid_created"))
    status_audit = db.scalar(select(AuditLog).where(AuditLog.action == "order_status_changed_to_bidding"))
    assert order.status == "bidding"
    assert offer.result == "bid_sent"
    assert offer.responded_at is not None
    assert history is not None
    assert history.old_status == "published"
    assert history.reason == "first_bid_created"
    assert notification is not None
    assert bid_audit is not None
    assert status_audit is not None
    db.close()


def test_driver_feed_detail_and_history_show_active_auction_bids(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    low_driver = create_driver(
        session_factory,
        ids,
        full_name="Arzon Haydovchi",
        car_model="Cobalt",
        plate_number="01A111AA",
        rating_avg=Decimal("4.90"),
        completed_orders=32,
    )
    high_driver = create_driver(
        session_factory,
        ids,
        full_name="Qimmat Haydovchi",
        car_model="Lacetti",
        plate_number="01B222BB",
        rating_avg=Decimal("4.50"),
        completed_orders=8,
    )
    top_rating_driver = create_driver(
        session_factory,
        ids,
        full_name="Reytingi Yuqori",
        car_model="Nexia",
        plate_number="01D444DD",
        rating_avg=Decimal("4.95"),
        completed_orders=1,
    )
    more_completed_driver = create_driver(
        session_factory,
        ids,
        full_name="Ko'p Buyurtmali",
        car_model="Spark",
        plate_number="01E555EE",
        rating_avg=Decimal("4.90"),
        completed_orders=40,
    )
    closed_driver = create_driver(
        session_factory,
        ids,
        full_name="Yopiq Haydovchi",
        car_model="Damas",
        plate_number="01C333CC",
        rating_avg=Decimal("4.10"),
        completed_orders=3,
    )
    order_id = create_and_publish_order(client, tokens, ids)

    high_bid = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(high_driver["token"]),
        json={"price": 62000},
    )
    low_bid = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(low_driver["token"]),
        json={"price": 55000},
    )
    top_rating_bid = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(top_rating_driver["token"]),
        json={"price": 55000},
    )
    more_completed_bid = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(more_completed_driver["token"]),
        json={"price": 55000},
    )
    closed_bid = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(closed_driver["token"]),
        json={"price": 50000},
    )
    assert high_bid.status_code == 200
    assert low_bid.status_code == 200
    assert top_rating_bid.status_code == 200
    assert more_completed_bid.status_code == 200
    assert closed_bid.status_code == 200
    high_bid_id = high_bid.json()["data"].get("id") or high_bid.json()["data"]["bid_id"]
    low_bid_id = low_bid.json()["data"].get("id") or low_bid.json()["data"]["bid_id"]
    top_rating_bid_id = top_rating_bid.json()["data"].get("id") or top_rating_bid.json()["data"]["bid_id"]
    more_completed_bid_id = more_completed_bid.json()["data"].get("id") or more_completed_bid.json()["data"]["bid_id"]
    closed_bid_id = closed_bid.json()["data"].get("id") or closed_bid.json()["data"]["bid_id"]

    db = session_factory()
    db.get(Bid, closed_bid_id).status = "closed"
    db.commit()
    db.close()

    feed = client.get("/api/v1/driver/orders/feed", headers=headers(high_driver["token"]))
    detail = client.get(f"/api/v1/driver/orders/{order_id}", headers=headers(high_driver["token"]))
    history = client.get("/api/v1/driver/orders", headers=headers(high_driver["token"]))

    assert feed.status_code == 200
    assert detail.status_code == 200
    assert history.status_code == 200

    feed_item = feed.json()["data"]["items"][0]
    detail_item = detail.json()["data"]
    history_item = history.json()["data"]["items"][0]

    for item in (feed_item, detail_item, history_item):
        bid_ids = [bid["id"] for bid in item["bids"]]
        assert bid_ids == [top_rating_bid_id, more_completed_bid_id, low_bid_id, high_bid_id]
        assert closed_bid_id not in bid_ids
        assert [Decimal(str(bid["price"])) for bid in item["bids"]] == [
            Decimal("55000"),
            Decimal("55000"),
            Decimal("55000"),
            Decimal("62000"),
        ]
        assert item["bids"][0]["driver"]["full_name"] == "Reytingi Yuqori"
        assert Decimal(str(item["bids"][0]["driver"]["rating"])) == Decimal("4.95")
        assert item["bids"][0]["driver"]["completed_orders"] == 1
        assert item["bids"][1]["driver"]["full_name"] == "Ko'p Buyurtmali"
        assert Decimal(str(item["bids"][1]["driver"]["rating"])) == Decimal("4.90")
        assert item["bids"][1]["driver"]["completed_orders"] == 40
        assert item["bids"][2]["driver"]["full_name"] == "Arzon Haydovchi"
        assert item["bids"][2]["driver"]["car_model"] == "Cobalt"
        assert item["bids"][2]["driver"]["plate_number"] == "01A111AA"
        assert Decimal(str(item["bids"][2]["driver"]["rating"])) == Decimal("4.90")
        assert item["bids"][2]["driver"]["completed_orders"] == 32
        assert item["bids"][3]["is_mine"] is True
        assert "phone" not in item["bids"][0]["driver"]


def test_driver_orders_history_includes_orders_with_my_bid(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    bid_response = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 55000},
    )
    assert bid_response.status_code == 200

    response = client.get("/api/v1/driver/orders", headers=headers(driver["token"]))

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["id"] == order_id
    assert Decimal(str(item["my_bid"]["price"])) == Decimal("55000")
    assert item["my_bid"]["status"] == "active"
    assert "sender_phone" not in item


def test_bid_price_must_be_greater_than_zero(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    response = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 0},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_duplicate_bid_is_rejected(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    first = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=headers(driver["token"]), json={"price": 55000})
    second = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=headers(driver["token"]), json={"price": 56000})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"] == {"code": "ALREADY_EXISTS", "message": "Driver already has a bid for this order"}


def test_driver_can_update_own_active_bid(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)
    bid_id = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 55000},
    ).json()["data"]["bid_id"]

    response = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=headers(driver["token"]), json={"price": 60000})

    assert response.status_code == 200
    assert Decimal(str(response.json()["data"]["price"])) == Decimal("60000")
    assert response.json()["data"]["status"] == "active"

    db = session_factory()
    bid = db.get(Bid, bid_id)
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_bid_updated"))
    notification = db.scalar(select(Notification).where(Notification.title == "Taklif yangilandi"))
    assert bid.status == "active"
    assert bid.price == Decimal("60000")
    assert audit is not None
    assert notification is not None
    db.close()


def test_driver_can_change_bid_price_max_three_times(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)
    bid_id = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 55000},
    ).json()["data"]["bid_id"]

    # Three price changes are allowed.
    for i, price in enumerate([60000, 65000, 70000], start=1):
        res = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=headers(driver["token"]), json={"price": price})
        assert res.status_code == 200
        assert res.json()["data"]["price_update_count"] == i
        assert res.json()["data"]["price_updates_left"] == 3 - i

    # The fourth change is rejected.
    blocked = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=headers(driver["token"]), json={"price": 75000})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "BID_UPDATE_LIMIT_REACHED"

    db = session_factory()
    bid = db.get(Bid, bid_id)
    assert bid.price == Decimal("70000")
    assert bid.price_update_count == 3
    db.close()


def test_resubmitting_same_bid_price_does_not_use_a_change(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)
    bid_id = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 55000},
    ).json()["data"]["bid_id"]

    # Sending the same price several times must not consume the change quota.
    for _ in range(5):
        res = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=headers(driver["token"]), json={"price": 55000})
        assert res.status_code == 200
        assert res.json()["data"]["price_update_count"] == 0


def test_driver_cannot_update_another_drivers_bid(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    owner = create_driver(session_factory, ids)
    other = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)
    bid_id = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(owner["token"]),
        json={"price": 55000},
    ).json()["data"]["bid_id"]

    response = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=headers(other["token"]), json={"price": 60000})

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": "You can update only your own bids"}


def test_driver_cannot_update_bid_after_order_accepted(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)
    bid_id = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 55000},
    ).json()["data"]["bid_id"]

    db = session_factory()
    order = db.get(Order, order_id)
    order.status = "accepted"
    db.commit()
    db.close()

    response = client.patch(f"/api/v1/driver/bids/{bid_id}", headers=headers(driver["token"]), json={"price": 60000})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ORDER_INVALID_STATUS"


def test_driver_can_reject_visible_order_and_it_leaves_feed(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    response = client.post(
        f"/api/v1/driver/orders/{order_id}/reject",
        headers=headers(driver["token"]),
        json={"reason": "Narx mos emas"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Order rejected"}

    feed = client.get("/api/v1/driver/orders/feed", headers=headers(driver["token"]))
    assert feed.status_code == 200
    assert feed.json()["data"]["items"] == []

    db = session_factory()
    order = db.get(Order, order_id)
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id, OrderOffer.driver_id == driver["profile_id"]))
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "driver_order_rejected"))
    assert order.status == "published"
    assert offer.result == "rejected"
    assert offer.responded_at is not None
    assert audit.details["reason"] == "Narx mos emas"
    db.close()


def test_reject_after_bidding_marks_active_bid_rejected_without_changing_order_status(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)
    bid_id = client.post(
        f"/api/v1/driver/orders/{order_id}/bids",
        headers=headers(driver["token"]),
        json={"price": 55000},
    ).json()["data"]["bid_id"]

    response = client.post(f"/api/v1/driver/orders/{order_id}/reject", headers=headers(driver["token"]), json={})

    assert response.status_code == 200
    db = session_factory()
    order = db.get(Order, order_id)
    bid = db.get(Bid, bid_id)
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id, OrderOffer.driver_id == driver["profile_id"]))
    assert order.status == "bidding"
    assert bid.status == "rejected"
    assert offer.result == "rejected"
    db.close()


def test_stage_9_does_not_require_forbidden_route_or_cargo_fields(driver_orders_client) -> None:
    client, tokens, session_factory, ids = driver_orders_client
    driver = create_driver(session_factory, ids)
    order_id = create_and_publish_order(client, tokens, ids)

    response = client.post(f"/api/v1/driver/orders/{order_id}/bids", headers=headers(driver["token"]), json={"price": 55000})

    assert response.status_code == 200
    route_columns = set(DriverRoute.__table__.columns.keys())
    order_columns = set(Order.__table__.columns.keys())
    assert "departure_time" not in route_columns
    assert "capacity" not in route_columns
    assert "cargo_type" in order_columns
    assert "weight" not in order_columns
    assert "size" not in order_columns
