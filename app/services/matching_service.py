from datetime import datetime, timezone

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import DriverProfile, DriverRoute, Order, OrderOffer, User
from app.services.notification_service import create_notification
from app.services.review_accounts import is_review_user_id, user_phone_matches_review_side


def find_matched_drivers_for_order(db: Session, order: Order) -> list[DriverProfile]:
    # Review (store) accounts are isolated: a review client's order reaches only
    # review drivers, and a real client's order never reaches a review driver.
    review_filter = user_phone_matches_review_side(User.phone, is_review_user_id(db, order.client_id))
    stmt = (
        select(DriverProfile)
        .join(User, User.id == DriverProfile.user_id)
        .join(DriverRoute, DriverRoute.driver_id == DriverProfile.id)
        .where(
            DriverRoute.from_city_id == order.from_city_id,
            DriverRoute.to_city_id == order.to_city_id,
            DriverRoute.from_district_id.is_(None) if order.from_district_id is None else DriverRoute.from_district_id == order.from_district_id,
            DriverRoute.to_district_id.is_(None) if order.to_district_id is None else DriverRoute.to_district_id == order.to_district_id,
            DriverRoute.status == "available",
            DriverProfile.verification_status == "approved",
            DriverProfile.is_available == True,  # noqa: E712
            User.status == "active",
        )
        .distinct()
    )
    if review_filter is not None:
        stmt = stmt.where(review_filter)
    return list(db.scalars(stmt))


def create_order_offers_for_published_order(db: Session, order: Order) -> int:
    matched_drivers = find_matched_drivers_for_order(db, order)
    created_count = 0
    now = datetime.now(timezone.utc)

    for driver in matched_drivers:
        duplicate_exists = db.scalar(
            select(
                exists().where(
                    OrderOffer.order_id == order.id,
                    OrderOffer.driver_id == driver.id,
                )
            )
        )
        if duplicate_exists:
            continue

        db.add(
            OrderOffer(
                order_id=order.id,
                driver_id=driver.id,
                status="shown",
                result="shown",
                shown_at=now,
            )
        )
        create_notification(
            db,
            driver.user_id,
            "order_published",
            "Yangi buyurtma",
            "Sizning yo'nalishingiz bo'yicha yangi buyurtma bor",
            order_id=order.id,
        )
        created_count += 1

    db.flush()
    return created_count
