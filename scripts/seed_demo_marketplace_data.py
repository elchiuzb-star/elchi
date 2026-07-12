from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import sys
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models import (
    Bid,
    City,
    ClientProfile,
    District,
    DriverProfile,
    DriverRoute,
    Order,
    OrderOffer,
    Rating,
    RouteTariff,
    StatusHistory,
    User,
)


CLIENTS = [
    "Aziz Karimov",
    "Dilnoza Ergasheva",
    "Jasur Rasulov",
    "Madina Akmalova",
    "Oybek Hamidov",
    "Sevara Qodirova",
    "Bekzod Usmonov",
    "Nodira Salimova",
    "Sherzod Tursunov",
    "Malika Rahimova",
]

DRIVERS = [
    ("Akmal Jo'rayev", "Chevrolet Cobalt", "Oq"),
    ("Sardor Aliyev", "Chevrolet Lacetti", "Kumush"),
    ("Jamshid Valiev", "Chevrolet Nexia 3", "Ko'k"),
    ("Farrux Ismoilov", "Kia K5", "Qora"),
    ("Diyorbek Sobirov", "Hyundai Elantra", "Kulrang"),
    ("Rustam Nazarov", "Chevrolet Tracker", "Oq"),
    ("Sanjar Mamatov", "Toyota Corolla", "Qora"),
    ("Ibrohim Yusupov", "Chevrolet Gentra", "Kumush"),
    ("Ulug'bek Xolmatov", "BYD Chazor", "Ko'k"),
    ("Anvar Saidov", "Chevrolet Onix", "Oq"),
]

ORDER_STATUSES = [
    "published",
    "published",
    "published",
    "published",
    "published",
    "bidding",
    "bidding",
    "bidding",
    "bidding",
    "bidding",
    "accepted",
    "accepted",
    "accepted",
    "accepted",
    "accepted",
    "picked_up",
    "picked_up",
    "picked_up",
    "in_transit",
    "in_transit",
    "in_transit",
    "delivered",
    "delivered",
    "delivered",
    "confirmed",
    "confirmed",
    "confirmed",
    "confirmed",
    "cancelled",
    "disputed",
]

STATUS_SEQUENCE = ["draft", "published", "bidding", "accepted", "picked_up", "in_transit", "delivered", "confirmed"]
ASSIGNED_STATUSES = {"accepted", "picked_up", "in_transit", "delivered", "confirmed", "disputed"}
OPEN_STATUSES = {"published", "bidding"}


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def demo_client_phone(index: int) -> str:
    return f"+998901010{index:03d}"


def demo_driver_phone(index: int) -> str:
    return f"+998902020{index:03d}"


def route_key(route: RouteTariff) -> tuple[int, int]:
    return route.from_city_id, route.to_city_id


def first_district_by_city(db) -> dict[int, District]:
    districts = list(db.scalars(select(District).where(District.is_active == True).order_by(District.display_order.asc(), District.id.asc())))  # noqa: E712
    result: dict[int, District] = {}
    for district in districts:
        result.setdefault(district.city_id, district)
    return result


def ensure_client(db, index: int) -> User:
    phone = demo_client_phone(index)
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        user = User(phone=phone, role="client", status="active", is_phone_verified=True)
        db.add(user)
        db.flush()
    user.role = "client"
    user.status = "active"
    user.is_phone_verified = True
    user.full_name = CLIENTS[index - 1]
    db.add(user)

    profile = db.scalar(select(ClientProfile).where(ClientProfile.user_id == user.id))
    if profile is None:
        profile = ClientProfile(user_id=user.id)
    profile.full_name = CLIENTS[index - 1]
    db.add(profile)
    return user


def ensure_driver(db, index: int) -> DriverProfile:
    phone = demo_driver_phone(index)
    full_name, car_model, car_color = DRIVERS[index - 1]
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        user = User(phone=phone, role="driver", status="active", is_phone_verified=True)
        db.add(user)
        db.flush()
    user.role = "driver"
    user.status = "active"
    user.is_phone_verified = True
    user.full_name = full_name
    db.add(user)

    profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
    if profile is None:
        profile = DriverProfile(user_id=user.id)
    plate_number = f"01 D {index:03d} EL"
    profile.full_name = full_name
    profile.car_model = car_model
    profile.car_color = car_color
    profile.plate_number = plate_number
    profile.plate_number_normalized = plate_number.replace(" ", "")
    profile.verification_status = "approved"
    profile.is_available = True
    profile.rating_avg = money(Decimal("4.50") + Decimal(index % 5) / Decimal("10"))
    db.add(profile)
    db.flush()
    return profile


def ensure_driver_routes(db, drivers: list[DriverProfile], routes: list[RouteTariff]) -> None:
    for index, driver in enumerate(drivers):
        for offset in range(5):
            route = routes[(index * 7 + offset * 11) % len(routes)]
            exists = db.scalar(
                select(DriverRoute).where(
                    DriverRoute.driver_id == driver.id,
                    DriverRoute.from_city_id == route.from_city_id,
                    DriverRoute.to_city_id == route.to_city_id,
                )
            )
            if exists is None:
                db.add(
                    DriverRoute(
                        driver_id=driver.id,
                        from_city_id=route.from_city_id,
                        to_city_id=route.to_city_id,
                        status="available",
                    )
                )
            else:
                exists.status = "available"
                db.add(exists)


def ensure_status_history(db, order: Order, status: str, user: User, old_status: str | None = None) -> None:
    exists = db.scalar(select(StatusHistory).where(StatusHistory.order_id == order.id, StatusHistory.new_status == status))
    if exists is None:
        db.add(
            StatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=status,
                changed_by_user_id=user.id,
                changed_by_role=user.role,
                reason="demo_seed",
            )
        )


def ensure_bid(db, order: Order, driver: DriverProfile, price: Decimal, status: str, comment: str) -> Bid:
    bid = db.scalar(select(Bid).where(Bid.order_id == order.id, Bid.driver_id == driver.id))
    if bid is None:
        bid = Bid(order_id=order.id, driver_id=driver.id, price=price, status=status)
    bid.price = price
    bid.status = status
    bid.comment = comment
    db.add(bid)
    db.flush()
    return bid


def ensure_offer(db, order: Order, driver: DriverProfile, result = "shown") -> None:
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order.id, OrderOffer.driver_id == driver.id))
    if offer is None:
        offer = OrderOffer(order_id=order.id, driver_id=driver.id)
    offer.status = "shown"
    offer.result = result
    offer.shown_at = order.published_at
    db.add(offer)


def set_order_timestamps(order: Order, status: str, base_time: datetime) -> None:
    order.published_at = base_time
    if status in {"accepted", "picked_up", "in_transit", "delivered", "confirmed", "disputed"}:
        order.accepted_at = base_time + timedelta(hours=2)
    if status in {"picked_up", "in_transit", "delivered", "confirmed", "disputed"}:
        order.picked_up_at = base_time + timedelta(hours=4)
    if status in {"in_transit", "delivered", "confirmed", "disputed"}:
        order.in_transit_at = base_time + timedelta(hours=6)
    if status in {"delivered", "confirmed"}:
        order.delivered_at = base_time + timedelta(hours=10)
    if status == "confirmed":
        order.confirmed_at = base_time + timedelta(hours=12)
    if status == "cancelled":
        order.cancelled_at = base_time + timedelta(hours=1)
        order.cancel_reason = "Demo cancelled order"


def seed_orders(db, clients: list[User], drivers: list[DriverProfile], routes: list[RouteTariff], district_by_city: dict[int, District]) -> list[Order]:
    now = datetime.now(timezone.utc)
    orders: list[Order] = []
    for index, status in enumerate(ORDER_STATUSES, start=1):
        client = clients[(index - 1) % len(clients)]
        route = routes[(index * 13) % len(routes)]
        driver = drivers[(index - 1) % len(drivers)]
        order_number = f"DEMO-ORD-{index:03d}"
        order = db.scalar(select(Order).where(Order.order_number == order_number))
        if order is None:
            order = Order(order_number=order_number, client_id=client.id)
            db.add(order)

        from_district = district_by_city.get(route.from_city_id)
        to_district = district_by_city.get(route.to_city_id)
        suggested = money(route.suggested_price or Decimal("70000"))
        final_price = money(suggested * Decimal("1.05")) if status in ASSIGNED_STATUSES else None
        base_time = now - timedelta(days=30 - index, hours=index % 6)

        order.client_id = client.id
        order.from_city_id = route.from_city_id
        order.to_city_id = route.to_city_id
        order.from_district_id = from_district.id if from_district else None
        order.to_district_id = to_district.id if to_district else None
        order.pickup_address = f"{from_district.name_uz if from_district else 'Markaz'} demo pickup, uy {index}"
        order.dropoff_address = f"{to_district.name_uz if to_district else 'Markaz'} demo dropoff, uy {index + 10}"
        order.pickup_lat = from_district.center_lat if from_district else None
        order.pickup_lng = from_district.center_lng if from_district else None
        order.dropoff_lat = to_district.center_lat if to_district else None
        order.dropoff_lng = to_district.center_lng if to_district else None
        order.sender_phone = client.phone
        order.receiver_phone = f"+998909090{index:03d}"
        order.comment = f"Demo buyurtma #{index}"
        order.suggested_price = suggested
        order.final_price = final_price
        order.payment_method = "cash"
        order.payment_status = "paid" if status in {"delivered", "confirmed"} else "unpaid"
        order.status = status
        order.assigned_driver_id = driver.id if status in ASSIGNED_STATUSES else None
        order.accepted_bid_id = None
        order.cancelled_by = client.id if status == "cancelled" else None
        set_order_timestamps(order, status, base_time)
        db.add(order)
        db.flush()

        previous = None
        for step in STATUS_SEQUENCE:
            ensure_status_history(db, order, step, client, previous)
            previous = step
            if step == status or (status == "cancelled" and step == "published") or (status == "disputed" and step == "accepted"):
                break
        if status == "cancelled":
            ensure_status_history(db, order, "cancelled", client, "published")
        if status == "disputed":
            ensure_status_history(db, order, "disputed", client, "accepted")

        if status in OPEN_STATUSES:
            for offset in range(3):
                offer_driver = drivers[(index + offset) % len(drivers)]
                ensure_offer(db, order, offer_driver)
            if status == "bidding":
                for offset in range(2):
                    bid_driver = drivers[(index + offset) % len(drivers)]
                    ensure_bid(db, order, bid_driver, money(suggested * (Decimal("0.95") + Decimal(offset) / Decimal("20"))), "active", "Demo narx taklifi")

        if status in ASSIGNED_STATUSES:
            accepted_bid = ensure_bid(db, order, driver, final_price or suggested, "accepted", "Demo tanlangan haydovchi")
            order.accepted_bid_id = accepted_bid.id
            db.add(order)
            ensure_offer(db, order, driver, "accepted")

        if status == "confirmed":
            rating = db.scalar(select(Rating).where(Rating.order_id == order.id))
            if rating is None:
                rating = Rating(order_id=order.id, client_id=client.id, driver_id=driver.id)
            rating.rating = 5 if index % 2 else 4
            rating.comment = "Demo baho"
            db.add(rating)

        orders.append(order)
    return orders


def refresh_driver_stats(db, drivers: list[DriverProfile], orders: list[Order]) -> None:
    for driver in drivers:
        assigned = [order for order in orders if order.assigned_driver_id == driver.id]
        completed = [order for order in assigned if order.status in {"delivered", "confirmed"}]
        cancelled = [order for order in assigned if order.status == "cancelled"]
        ratings = list(db.scalars(select(Rating).where(Rating.driver_id == driver.id)))
        driver.total_orders = len(assigned)
        driver.completed_orders = len(completed)
        driver.cancelled_orders = len(cancelled)
        if ratings:
            driver.rating_avg = money(sum(Decimal(r.rating) for r in ratings) / Decimal(len(ratings)))
        db.add(driver)


def main() -> None:
    db = SessionLocal()
    try:
        active_cities = list(db.scalars(select(City).where(City.is_active == True)))  # noqa: E712
        active_routes = list(db.scalars(select(RouteTariff).where(RouteTariff.is_active == True).order_by(RouteTariff.id.asc())))  # noqa: E712
        if len(active_cities) < 2 or not active_routes:
            raise RuntimeError("Run scripts/seed_admin_required_data.py before this demo seed.")

        clients = [ensure_client(db, index) for index in range(1, 11)]
        drivers = [ensure_driver(db, index) for index in range(1, 11)]
        db.flush()

        ensure_driver_routes(db, drivers, active_routes)
        district_by_city = first_district_by_city(db)
        orders = seed_orders(db, clients, drivers, active_routes, district_by_city)
        refresh_driver_stats(db, drivers, orders)
        db.commit()

        print("demo_clients=10")
        print("demo_approved_drivers=10")
        print("demo_orders=30")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
