"""Seed one client order in `bidding` state with several driver bids.

Creates (idempotently):
  * client  +998901234567
  * 6 drivers (approved, available), including the requested +998901234576
  * one published/bidding order for that client on the first active route
  * one active bid per driver at a different price + an OrderOffer per driver

Run:  ./.venv/Scripts/python.exe scripts/seed_bidding_demo.py
"""
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
    RouteTariff,
    StatusHistory,
    User,
)

CLIENT_PHONE = "+998901234567"
CLIENT_NAME = "Test Mijoz"
ORDER_NUMBER = "BID-DEMO-001"

# (phone, full_name, car_model, car_color, bid_price). The requested driver is included.
DRIVERS: list[tuple[str, str, str, str, int]] = [
    ("+998901234576", "Akmal Jo'rayev", "Chevrolet Cobalt", "Oq", 58000),
    ("+998901234571", "Sardor Aliyev", "Chevrolet Lacetti", "Kumush", 55000),
    ("+998901234572", "Jamshid Valiev", "Chevrolet Nexia 3", "Ko'k", 62000),
    ("+998901234573", "Farrux Ismoilov", "Kia K5", "Qora", 65000),
    ("+998901234574", "Diyorbek Sobirov", "Hyundai Elantra", "Kulrang", 60000),
    ("+998901234575", "Rustam Nazarov", "Toyota Corolla", "Qora", 70000),
]


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ensure_client(db) -> User:
    user = db.scalar(select(User).where(User.phone == CLIENT_PHONE))
    if user is None:
        user = User(phone=CLIENT_PHONE, role="client", status="active", is_phone_verified=True)
        db.add(user)
        db.flush()
    user.role = "client"
    user.status = "active"
    user.is_phone_verified = True
    user.full_name = CLIENT_NAME
    db.add(user)

    profile = db.scalar(select(ClientProfile).where(ClientProfile.user_id == user.id))
    if profile is None:
        profile = ClientProfile(user_id=user.id)
    profile.full_name = CLIENT_NAME
    db.add(profile)
    db.flush()
    return user


def ensure_driver(db, phone: str, full_name: str, car_model: str, car_color: str, index: int) -> DriverProfile:
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
    plate_number = f"01 B {index:03d} EL"
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


def ensure_driver_route(db, driver: DriverProfile, from_city_id: int, to_city_id: int,
                        from_district_id: int | None, to_district_id: int | None) -> None:
    route = db.scalar(
        select(DriverRoute).where(
            DriverRoute.driver_id == driver.id,
            DriverRoute.from_city_id == from_city_id,
            DriverRoute.to_city_id == to_city_id,
        )
    )
    if route is None:
        route = DriverRoute(
            driver_id=driver.id,
            from_city_id=from_city_id,
            to_city_id=to_city_id,
            from_district_id=from_district_id,
            to_district_id=to_district_id,
        )
    route.status = "available"
    db.add(route)


def ensure_status_history(db, order: Order, new_status: str, user: User, old_status: str | None) -> None:
    exists = db.scalar(
        select(StatusHistory).where(StatusHistory.order_id == order.id, StatusHistory.new_status == new_status)
    )
    if exists is None:
        db.add(
            StatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_user_id=user.id,
                changed_by_role=user.role,
                reason="bidding_demo_seed",
            )
        )


def ensure_offer(db, order: Order, driver: DriverProfile) -> None:
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order.id, OrderOffer.driver_id == driver.id))
    if offer is None:
        offer = OrderOffer(order_id=order.id, driver_id=driver.id)
    offer.status = "shown"
    offer.result = "shown"
    offer.shown_at = order.published_at
    db.add(offer)


def ensure_bid(db, order: Order, driver: DriverProfile, price: Decimal) -> Bid:
    bid = db.scalar(select(Bid).where(Bid.order_id == order.id, Bid.driver_id == driver.id))
    if bid is None:
        bid = Bid(order_id=order.id, driver_id=driver.id, price=price, status="active")
    bid.price = price
    bid.status = "active"
    bid.comment = "Narx taklifi"
    db.add(bid)
    db.flush()
    return bid


def main() -> None:
    db = SessionLocal()
    try:
        tariff = db.scalar(
            select(RouteTariff).where(RouteTariff.is_active == True).order_by(RouteTariff.id.asc())  # noqa: E712
        )
        if tariff is None:
            raise RuntimeError("No active route tariff. Run scripts/seed_admin_required_data.py first.")

        from_city = db.get(City, tariff.from_city_id)
        to_city = db.get(City, tariff.to_city_id)
        from_district = db.scalar(
            select(District).where(District.city_id == tariff.from_city_id, District.is_active == True)  # noqa: E712
            .order_by(District.display_order.asc(), District.id.asc())
        )
        to_district = db.scalar(
            select(District).where(District.city_id == tariff.to_city_id, District.is_active == True)  # noqa: E712
            .order_by(District.display_order.asc(), District.id.asc())
        )

        client = ensure_client(db)
        drivers = [
            ensure_driver(db, phone, name, car, color, idx)
            for idx, (phone, name, car, color, _price) in enumerate(DRIVERS, start=1)
        ]

        now = datetime.now(timezone.utc)
        order = db.scalar(select(Order).where(Order.order_number == ORDER_NUMBER))
        if order is None:
            order = Order(order_number=ORDER_NUMBER, client_id=client.id)
            db.add(order)

        order.client_id = client.id
        order.from_city_id = tariff.from_city_id
        order.to_city_id = tariff.to_city_id
        order.from_district_id = from_district.id if from_district else None
        order.to_district_id = to_district.id if to_district else None
        order.pickup_address = f"{from_district.name_uz if from_district else 'Markaz'}, Amir Temur ko'chasi 1"
        order.dropoff_address = f"{to_district.name_uz if to_district else 'Markaz'}, Registon ko'chasi 5"
        order.pickup_lat = from_district.center_lat if from_district else None
        order.pickup_lng = from_district.center_lng if from_district else None
        order.dropoff_lat = to_district.center_lat if to_district else None
        order.dropoff_lng = to_district.center_lng if to_district else None
        order.sender_phone = client.phone
        order.receiver_phone = "+998907654321"
        order.cargo_type = "parcel"
        order.comment = "Bidding demo buyurtma"
        order.suggested_price = money(tariff.suggested_price or Decimal("60000"))
        order.client_price = money(tariff.suggested_price or Decimal("60000"))
        order.final_price = None
        order.payment_method = "cash"
        order.payment_status = "unpaid"
        order.status = "bidding"
        order.assigned_driver_id = None
        order.accepted_bid_id = None
        order.published_at = now - timedelta(hours=1)
        db.add(order)
        db.flush()

        ensure_status_history(db, order, "draft", client, None)
        ensure_status_history(db, order, "published", client, "draft")
        ensure_status_history(db, order, "bidding", client, "published")

        for driver, (_phone, _name, _car, _color, price) in zip(drivers, DRIVERS):
            ensure_driver_route(
                db, driver, tariff.from_city_id, tariff.to_city_id,
                order.from_district_id, order.to_district_id,
            )
            ensure_offer(db, order, driver)
            ensure_bid(db, order, driver, money(price))

        db.commit()

        print(f"client={client.phone} (id={client.id})")
        print(f"order={order.order_number} (id={order.id}) status={order.status} "
              f"route={from_city.name_uz}->{to_city.name_uz} suggested={order.suggested_price}")
        print(f"drivers/bids={len(DRIVERS)}")
        for driver, (phone, name, _car, _color, price) in zip(drivers, DRIVERS):
            print(f"  bid {money(price)} so'm  <-  {phone}  {name}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
