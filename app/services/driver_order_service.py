from datetime import datetime, timezone
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Bid, City, District, DriverProfile, DriverRoute, Order, OrderOffer, StatusHistory, User
from app.schemas.bid import BidCreate, BidUpdate, OrderReject
from app.schemas.driver_order import DriverOrderCancel
from app.services.audit_service import write_audit_log
from app.services.city_service import pagination
from app.services.driver_locks import lock_bid_row, lock_driver_user_and_profile, lock_order_row
from app.services.notification_service import create_notification
from app.services.review_accounts import client_id_matches_review_side, is_review_driver_profile, review_pairing_allowed
from app.services.system_settings_service import DEFAULT_DRIVER_COMMISSION_RATE, calculate_order_income
from app.utils.api_response import error_response
from app.utils.file_access import signed_file_url
from app.utils.legacy_time import v1_naive

OPEN_FEED_STATUSES = {"published", "bidding"}
TERMINAL_BID_UPDATE_ORDER_STATUSES = {"accepted", "cancelled", "confirmed"}
MAX_BID_PRICE_UPDATES = 3
DRIVER_STATUS_TRANSITIONS = {
    "picked_up": {
        "expected": "accepted",
        "timestamp_field": "picked_up_at",
        "reason": "driver_marked_picked_up",
        "action": "driver_marked_picked_up",
        "notification_type": "picked_up",
        "notification_title": "Yuk olindi",
        "notification_message": "Haydovchi yukni olganini belgiladi",
        "response_message": "Order marked as picked up",
    },
    "in_transit": {
        "expected": "picked_up",
        "timestamp_field": "in_transit_at",
        "reason": "driver_marked_in_transit",
        "action": "driver_marked_in_transit",
        "notification_type": "in_transit",
        "notification_title": "Yuk yo'lda",
        "notification_message": "Yuk manzilga ketmoqda",
        "response_message": "Order marked as in transit",
    },
    "delivered": {
        "expected": "in_transit",
        "timestamp_field": "delivered_at",
        "reason": "driver_marked_delivered",
        "action": "driver_marked_delivered",
        "notification_type": "delivered",
        "notification_title": "Yetkazildi",
        "notification_message": "Haydovchi yuk yetkazilganini belgiladi. Iltimos tasdiqlang.",
        "response_message": "Order marked as delivered",
    },
}


def get_driver_profile_for_user(db: Session, user: User) -> DriverProfile | JSONResponse:
    profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
    if profile is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_NOT_APPROVED", "Driver must be approved")
    return profile


def ensure_driver_eligible(profile: DriverProfile, user: User | None = None) -> JSONResponse | None:
    if user is not None and user.status != "active":
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Driver account must be active")
    if profile.verification_status != "approved":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_NOT_APPROVED", "Driver must be approved")
    if not profile.is_available:
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_NOT_AVAILABLE", "Driver must be available")
    return None


def ensure_assigned_driver_can_update_status(profile: DriverProfile, user: User) -> JSONResponse | None:
    if user.status != "active":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_BLOCKED", "Driver is blocked or inactive")
    if profile.verification_status != "approved":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_NOT_APPROVED", "Driver must be approved")
    return None


def city_summary(city: City) -> dict[str, Any]:
    return {"id": city.id, "name_uz": city.name_uz}


def district_summary(district: District | None) -> dict[str, Any] | None:
    if district is None:
        return None
    return {"id": district.id, "city_id": district.city_id, "name_uz": district.name_uz, "name_ru": district.name_ru}


def area(address: str | None) -> str | None:
    if address is None:
        return None
    return address.split(",", 1)[0].strip()


def bid_to_dict(bid: Bid | None) -> dict[str, Any] | None:
    if bid is None:
        return None
    return {
        "id": bid.id,
        "price": bid.price,
        "status": bid.status,
        "created_at": bid.created_at,
        "price_update_count": bid.price_update_count,
        "price_updates_left": max(0, MAX_BID_PRICE_UPDATES - bid.price_update_count),
    }


def bid_auction_to_dict(db: Session, bid: Bid, current_driver_id: int) -> dict[str, Any]:
    driver = db.get(DriverProfile, bid.driver_id)
    user = db.get(User, driver.user_id) if driver is not None else None
    return {
        "id": bid.id,
        "order_id": bid.order_id,
        "price": bid.price,
        "status": bid.status,
        "created_at": bid.created_at,
        "price_update_count": bid.price_update_count,
        "price_updates_left": max(0, MAX_BID_PRICE_UPDATES - bid.price_update_count),
        "is_mine": bid.driver_id == current_driver_id,
        "driver": {
            "id": driver.id if driver else None,
            "full_name": (driver.full_name or (user.full_name if user else None)) if driver else None,
            "car_model": driver.car_model if driver else None,
            "plate_number": driver.plate_number if driver else None,
            "rating": driver.rating_avg if driver else None,
            "completed_orders": driver.completed_orders if driver else 0,
        },
    }


def active_order_bids_to_list(db: Session, order_id: int, current_driver_id: int) -> list[dict[str, Any]]:
    bids = list(
        db.scalars(
            select(Bid)
            .join(DriverProfile, DriverProfile.id == Bid.driver_id)
            .where(Bid.order_id == order_id, Bid.status == "active")
            .order_by(
                Bid.price.asc(),
                DriverProfile.rating_avg.desc(),
                DriverProfile.completed_orders.desc(),
                Bid.created_at.asc(),
            )
        )
    )
    return [bid_auction_to_dict(db, bid, current_driver_id) for bid in bids]


def order_income_to_dict(order: Order) -> dict[str, Any]:
    stored_rate = order.system_fee_rate if order.system_fee_rate is not None else DEFAULT_DRIVER_COMMISSION_RATE
    if order.final_price is None:
        return {
            "gross_income": None,
            "system_fee": None,
            "driver_income": None,
            "system_fee_rate": stored_rate,
        }
    fallback = calculate_order_income(order.final_price, stored_rate)
    gross_income = fallback["gross_income"]
    system_fee_rate = order.system_fee_rate if order.system_fee_rate is not None else fallback["system_fee_rate"]
    system_fee = order.system_fee if order.system_fee is not None else fallback["system_fee"]
    driver_income = order.driver_income if order.driver_income is not None else fallback["driver_income"]
    return {
        "gross_income": gross_income,
        "system_fee": system_fee,
        "driver_income": driver_income,
        "system_fee_rate": system_fee_rate,
    }


def limited_order_to_dict(db: Session, order: Order, driver_id: int) -> dict[str, Any]:
    my_bid = db.scalar(select(Bid).where(Bid.order_id == order.id, Bid.driver_id == driver_id))
    from_district = db.get(District, order.from_district_id) if order.from_district_id else None
    to_district = db.get(District, order.to_district_id) if order.to_district_id else None
    return {
        "id": order.id,
        "order_number": order.order_number,
        "from_city": city_summary(db.get(City, order.from_city_id)),
        "to_city": city_summary(db.get(City, order.to_city_id)),
        "from_district": district_summary(from_district),
        "to_district": district_summary(to_district),
        "pickup_area": from_district.name_uz if from_district else area(order.pickup_address),
        "dropoff_area": to_district.name_uz if to_district else area(order.dropoff_address),
        "cargo_type": order.cargo_type,
        # Cargo photo is visible only to the owner, the assigned driver and staff.
        "cargo_photo_url": None,
        "suggested_price": order.suggested_price,
        "client_price": order.client_price,
        "status": order.status,
        "my_bid": bid_to_dict(my_bid),
        "bids": active_order_bids_to_list(db, order.id, driver_id),
        "created_at": order.created_at,
    }


def full_order_to_dict(db: Session, order: Order) -> dict[str, Any]:
    from_district = db.get(District, order.from_district_id) if order.from_district_id else None
    to_district = db.get(District, order.to_district_id) if order.to_district_id else None
    data = {
        "id": order.id,
        "order_number": order.order_number,
        "from_city": city_summary(db.get(City, order.from_city_id)),
        "to_city": city_summary(db.get(City, order.to_city_id)),
        "from_district": district_summary(from_district),
        "to_district": district_summary(to_district),
        "pickup_address": order.pickup_address,
        "dropoff_address": order.dropoff_address,
        "pickup_lat": order.pickup_lat,
        "pickup_lng": order.pickup_lng,
        "dropoff_lat": order.dropoff_lat,
        "dropoff_lng": order.dropoff_lng,
        "sender_phone": order.sender_phone,
        "receiver_phone": order.receiver_phone,
        "cargo_type": order.cargo_type,
        # A cancelled order keeps assigned_driver_id; the photo link stops there.
        "cargo_photo_url": None if order.status == "cancelled" else signed_file_url(order.cargo_photo_url),
        "comment": order.comment,
        "suggested_price": order.suggested_price,
        "client_price": order.client_price,
        "final_price": order.final_price,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "status": order.status,
        "delivered_at": v1_naive(order.delivered_at),
        "confirmed_at": v1_naive(order.confirmed_at),
        "created_at": order.created_at,
    }
    data.update(order_income_to_dict(order))
    return data


def driver_has_available_route_for_order(db: Session, profile: DriverProfile, order: Order) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    DriverRoute.driver_id == profile.id,
                    DriverRoute.from_city_id == order.from_city_id,
                    DriverRoute.to_city_id == order.to_city_id,
                    DriverRoute.from_district_id.is_(None) if order.from_district_id is None else DriverRoute.from_district_id == order.from_district_id,
                    DriverRoute.to_district_id.is_(None) if order.to_district_id is None else DriverRoute.to_district_id == order.to_district_id,
                    DriverRoute.status == "available",
                )
            )
        )
    )


def lock_order(db: Session, order_id: int) -> Order | None:
    """SELECT ... FOR UPDATE on the order, refreshing any stale identity-map copy.

    Every v1 path that changes an order's bids takes this lock first (order ->
    bids), matching select_driver_for_order and client/admin cancel.
    """
    return lock_order_row(db, order_id)


def recheck_driver_eligibility_locked(db: Session, profile: DriverProfile) -> JSONResponse | None:
    """Lock users -> driver_profiles (after the order/bid locks) and re-check.

    Closes the block_driver/account-deletion race: a block that committed first
    is seen here; a block that starts later waits for this transaction. The
    alternative (closing the driver's bids inside block_driver) would make
    block_driver lock bids after users, reversing orders -> bids -> users.
    """
    locked_profile, locked_user = lock_driver_user_and_profile(db, profile.id)
    if locked_profile is None or locked_user is None:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Driver account must be active")
    return ensure_driver_eligible(locked_profile, locked_user)


def get_offer(db: Session, order_id: int, driver_id: int) -> OrderOffer | None:
    return db.scalar(select(OrderOffer).where(OrderOffer.order_id == order_id, OrderOffer.driver_id == driver_id))


def ensure_order_visible(db: Session, profile: DriverProfile, order: Order) -> JSONResponse | None:
    # Store-review isolation comes first: no existing bid or offer overrides it.
    if not review_pairing_allowed(db, order.client_id, profile.user_id):
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Order is not visible to this driver")
    if order.assigned_driver_id == profile.id:
        return None
    driver_bid = db.scalar(select(Bid).where(Bid.order_id == order.id, Bid.driver_id == profile.id))
    if driver_bid is not None:
        return None
    if order.status not in OPEN_FEED_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Order is not open for bids")
    offer = get_offer(db, order.id, profile.id)
    if offer is not None and offer.result == "rejected":
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Order is not visible to this driver")
    if not driver_has_available_route_for_order(db, profile, order):
        return error_response(status.HTTP_400_BAD_REQUEST, "ROUTE_NOT_MATCHED", "Order does not match driver's route")
    return None


def feed_query(db: Session, profile: DriverProfile, order_status: str | None, from_city_id: int | None, to_city_id: int | None):
    stmt = (
        select(Order)
        .outerjoin(
            OrderOffer,
            and_(
                OrderOffer.order_id == Order.id,
                OrderOffer.driver_id == profile.id,
            ),
        )
        .join(DriverRoute, DriverRoute.driver_id == profile.id)
        .where(
            or_(OrderOffer.id.is_(None), OrderOffer.result.in_(["shown", "bid_sent", "ignored"])),
            Order.status.in_(["published", "bidding"]),
            DriverRoute.from_city_id == Order.from_city_id,
            DriverRoute.to_city_id == Order.to_city_id,
            or_(
                and_(DriverRoute.from_district_id.is_(None), Order.from_district_id.is_(None)),
                DriverRoute.from_district_id == Order.from_district_id,
            ),
            or_(
                and_(DriverRoute.to_district_id.is_(None), Order.to_district_id.is_(None)),
                DriverRoute.to_district_id == Order.to_district_id,
            ),
            DriverRoute.status == "available",
        )
    )
    review_filter = client_id_matches_review_side(Order.client_id, is_review_driver_profile(db, profile))
    if review_filter is not None:
        stmt = stmt.where(review_filter)
    if order_status is not None:
        if order_status not in OPEN_FEED_STATUSES:
            return None
        stmt = stmt.where(Order.status == order_status)
    if from_city_id is not None:
        stmt = stmt.where(Order.from_city_id == from_city_id)
    if to_city_id is not None:
        stmt = stmt.where(Order.to_city_id == to_city_id)
    return stmt.distinct()


def list_driver_feed(
    db: Session,
    profile: DriverProfile,
    page: int,
    limit: int,
    order_status: str | None = None,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
) -> dict[str, Any] | JSONResponse:
    eligibility_error = ensure_driver_eligible(profile)
    if eligibility_error is not None:
        return eligibility_error
    stmt = feed_query(db, profile, order_status, from_city_id, to_city_id)
    if stmt is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid order status")
    offset, safe_limit = pagination(page, limit)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    orders = list(db.scalars(stmt.order_by(Order.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "items": [limited_order_to_dict(db, order, profile.id) for order in orders],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
    }


def list_assigned_driver_orders(
    db: Session,
    profile: DriverProfile,
    page: int,
    limit: int,
    order_status: str | None = None,
) -> dict[str, Any] | JSONResponse:
    driver_order_statuses = {
        "published",
        "bidding",
        "accepted",
        "picked_up",
        "in_transit",
        "delivered",
        "confirmed",
        "cancelled",
        "disputed",
    }
    if order_status is not None and order_status not in driver_order_statuses:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid order status")
    stmt = (
        select(Order)
        .outerjoin(Bid, and_(Bid.order_id == Order.id, Bid.driver_id == profile.id))
        .where(or_(Order.assigned_driver_id == profile.id, Bid.id.is_not(None)))
        .distinct()
    )
    if order_status is not None:
        stmt = stmt.where(Order.status == order_status)
    offset, safe_limit = pagination(page, limit)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    orders = list(db.scalars(stmt.order_by(Order.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "items": [
            full_order_to_dict(db, order) if order.assigned_driver_id == profile.id else limited_order_to_dict(db, order, profile.id)
            for order in orders
        ],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
    }


def get_driver_order_detail(db: Session, profile: DriverProfile, order_id: int) -> dict[str, Any] | JSONResponse:
    order = db.get(Order, order_id)
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.assigned_driver_id == profile.id:
        return full_order_to_dict(db, order)
    eligibility_error = ensure_driver_eligible(profile)
    if eligibility_error is not None:
        return eligibility_error
    visible_error = ensure_order_visible(db, profile, order)
    if visible_error is not None:
        return visible_error
    return limited_order_to_dict(db, order, profile.id)


def create_bid(db: Session, user: User, profile: DriverProfile, order_id: int, payload: BidCreate) -> Bid | JSONResponse:
    eligibility_error = ensure_driver_eligible(profile, user)
    if eligibility_error is not None:
        return eligibility_error
    # Lock the order so a concurrent cancel/select-driver cannot commit between
    # the status check and the bid insert (no active bid on a closed order).
    order = lock_order(db, order_id)
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.status not in OPEN_FEED_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Order is not open for bids")
    locked_eligibility_error = recheck_driver_eligibility_locked(db, profile)
    if locked_eligibility_error is not None:
        return locked_eligibility_error
    visible_error = ensure_order_visible(db, profile, order)
    if visible_error is not None:
        return visible_error
    existing_bid = db.scalar(select(Bid).where(Bid.order_id == order.id, Bid.driver_id == profile.id))
    if existing_bid is not None:
        return error_response(status.HTTP_409_CONFLICT, "ALREADY_EXISTS", "Driver already has a bid for this order")

    bid = Bid(order_id=order.id, driver_id=profile.id, price=payload.price, status="active")
    db.add(bid)
    offer = get_offer(db, order.id, profile.id)
    if offer is None:
        offer = OrderOffer(order_id=order.id, driver_id=profile.id, status="shown", result="shown")
        db.add(offer)
    offer.result = "bid_sent"
    offer.status = "bid_sent"
    offer.responded_at = datetime.now(timezone.utc)
    old_status = order.status
    if order.status == "published":
        order.status = "bidding"
        db.add(order)
        db.flush()
        db.add(
            StatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status="bidding",
                changed_by_user_id=user.id,
                changed_by_role="driver",
                reason="first_bid_created",
            )
        )
        write_audit_log(
            db,
            user,
            "orders",
            order.id,
            "order_status_changed_to_bidding",
            old_value={"status": old_status},
            new_value={"status": order.status},
            reason="first_bid_created",
        )
    driver_name = profile.full_name or user.full_name or user.phone
    vehicle = " / ".join([value for value in [profile.car_model, profile.plate_number] if value]) or "Avtomobil ma'lumoti kiritilmagan"
    rating_text = f"{profile.rating_avg:.1f}" if profile.rating_avg is not None else "hali baholanmagan"
    create_notification(
        db,
        order.client_id,
        "new_bid",
        "Yangi haydovchi taklifi",
        f"{driver_name} {payload.price} so'm taklif qildi. Avtomobil: {vehicle}. Reyting: {rating_text}. Bajarilgan buyurtmalar: {profile.completed_orders}.",
        order_id=order.id,
    )
    db.flush()
    write_audit_log(
        db,
        user,
        "bids",
        bid.id,
        "driver_bid_created",
        new_value={"order_id": order.id, "price": bid.price, "status": bid.status},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return error_response(status.HTTP_409_CONFLICT, "ALREADY_EXISTS", "Driver already has a bid for this order")
    db.refresh(bid)
    return bid


def update_bid(db: Session, user: User, profile: DriverProfile, bid_id: int, payload: BidUpdate) -> Bid | JSONResponse:
    eligibility_error = ensure_driver_eligible(profile, user)
    if eligibility_error is not None:
        return eligibility_error
    bid = db.get(Bid, bid_id)
    if bid is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Bid not found")
    if bid.driver_id != profile.id:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You can update only your own bids")
    # Lock order first, then the bid (same order as select_driver_for_order and
    # client cancel), and re-read both so the checks below see committed state.
    order = lock_order(db, bid.order_id)
    bid = lock_bid_row(db, bid_id)
    if bid is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Bid not found")
    if order is None or order.status not in OPEN_FEED_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Order is not open for bids")
    if order.status in TERMINAL_BID_UPDATE_ORDER_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Order is not open for bids")
    if bid.status != "active":
        # A closed, accepted or rejected bid is never revived.
        return error_response(status.HTTP_409_CONFLICT, "BID_NOT_ACTIVE", "Only active bids can be updated")
    locked_eligibility_error = recheck_driver_eligibility_locked(db, profile)
    if locked_eligibility_error is not None:
        return locked_eligibility_error
    if not review_pairing_allowed(db, order.client_id, profile.user_id):
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Order is not visible to this driver")
    price_changed = payload.price != bid.price
    if price_changed and bid.price_update_count >= MAX_BID_PRICE_UPDATES:
        return error_response(
            status.HTTP_409_CONFLICT,
            "BID_UPDATE_LIMIT_REACHED",
            f"Taklif narxini {MAX_BID_PRICE_UPDATES} martadan ko'p o'zgartirib bo'lmaydi",
            {"max_updates": MAX_BID_PRICE_UPDATES, "used": bid.price_update_count},
        )
    old_value = {"price": bid.price, "status": bid.status, "price_update_count": bid.price_update_count}
    bid.price = payload.price
    bid.status = "active"
    if price_changed:
        bid.price_update_count += 1
    db.add(bid)
    driver_name = profile.full_name or user.full_name or user.phone
    vehicle = " / ".join([value for value in [profile.car_model, profile.plate_number] if value]) or "Avtomobil ma'lumoti kiritilmagan"
    rating_text = f"{profile.rating_avg:.1f}" if profile.rating_avg is not None else "hali baholanmagan"
    create_notification(
        db,
        order.client_id,
        "new_bid",
        "Taklif yangilandi",
        f"{driver_name} taklif narxini {payload.price} so'mga o'zgartirdi. Avtomobil: {vehicle}. Reyting: {rating_text}. Bajarilgan buyurtmalar: {profile.completed_orders}.",
        order_id=order.id,
    )
    db.flush()
    write_audit_log(
        db,
        user,
        "bids",
        bid.id,
        "driver_bid_updated",
        old_value=old_value,
        new_value={"price": bid.price, "status": bid.status, "price_update_count": bid.price_update_count},
    )
    db.commit()
    db.refresh(bid)
    return bid


def reject_order(db: Session, user: User, profile: DriverProfile, order_id: int, payload: OrderReject) -> JSONResponse | dict:
    eligibility_error = ensure_driver_eligible(profile, user)
    if eligibility_error is not None:
        return eligibility_error
    # Order lock first: this path closes/rejects the driver's bid, so it follows
    # the same order -> bids lock order as select-driver and cancel.
    order = lock_order(db, order_id)
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.status in {"cancelled", "confirmed"}:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Order is not open for bids")
    if order.assigned_driver_id is not None and order.assigned_driver_id != profile.id:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Order is not visible to this driver")
    if not driver_has_available_route_for_order(db, profile, order) and get_offer(db, order.id, profile.id) is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "ROUTE_NOT_MATCHED", "Order does not match driver's route")

    offer = get_offer(db, order.id, profile.id)
    if offer is None:
        offer = OrderOffer(order_id=order.id, driver_id=profile.id, status="shown", result="shown")
        db.add(offer)
    old_value = {"result": offer.result}
    offer.result = "rejected"
    offer.status = "rejected"
    offer.responded_at = datetime.now(timezone.utc)
    bid = db.scalar(select(Bid).where(Bid.order_id == order.id, Bid.driver_id == profile.id, Bid.status == "active"))
    if bid is not None:
        bid.status = "rejected"
        db.add(bid)
    db.add(offer)
    db.flush()
    write_audit_log(
        db,
        user,
        "order_offers",
        offer.id,
        "driver_order_rejected",
        old_value=old_value,
        new_value={"result": offer.result, "reason": payload.reason},
        reason=payload.reason,
    )
    db.commit()
    return {"success": True, "message": "Order rejected"}


def validate_assigned_order_for_status(
    db: Session,
    user: User,
    profile: DriverProfile,
    order_id: int,
) -> Order | JSONResponse:
    eligibility_error = ensure_assigned_driver_can_update_status(profile, user)
    if eligibility_error is not None:
        return eligibility_error
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.assigned_driver_id != profile.id:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You can update only your assigned orders")
    if order.status in {"cancelled", "confirmed", "disputed"}:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Invalid order status transition")
    return order


def mark_driver_order_status(
    db: Session,
    user: User,
    profile: DriverProfile,
    order_id: int,
    new_status: str,
) -> dict[str, Any] | JSONResponse:
    config = DRIVER_STATUS_TRANSITIONS[new_status]
    order = validate_assigned_order_for_status(db, user, profile, order_id)
    if isinstance(order, JSONResponse):
        return order
    if order.status != config["expected"]:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Invalid order status transition")

    now = datetime.now(timezone.utc)
    old_status = order.status
    order.status = new_status
    setattr(order, config["timestamp_field"], now)
    db.add(order)
    db.flush()
    db.add(
        StatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by_user_id=user.id,
            changed_by_role="driver",
            reason=config["reason"],
        )
    )
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        config["action"],
        old_value={"status": old_status},
        new_value={"status": order.status},
        reason=config["reason"],
    )
    create_notification(
        db,
        order.client_id,
        config["notification_type"],
        config["notification_title"],
        config["notification_message"],
        order_id=order.id,
    )
    db.commit()
    db.refresh(order)
    return {
        "success": True,
        "data": {
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            config["timestamp_field"]: getattr(order, config["timestamp_field"]),
        },
        "message": config["response_message"],
    }


def cancel_assigned_order_by_driver(
    db: Session,
    user: User,
    profile: DriverProfile,
    order_id: int,
    payload: DriverOrderCancel,
) -> dict[str, Any] | JSONResponse:
    if payload.reason is None or not payload.reason.strip():
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Cancel reason is required")
    order = validate_assigned_order_for_status(db, user, profile, order_id)
    if isinstance(order, JSONResponse):
        return order
    if order.status != "accepted":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Invalid order status transition")

    now = datetime.now(timezone.utc)
    old_status = order.status
    reason = payload.reason.strip()
    order.status = "cancelled"
    order.cancel_reason = reason
    order.cancelled_by = user.id
    order.cancelled_at = now
    db.add(order)
    db.flush()
    db.add(
        StatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status="cancelled",
            changed_by_user_id=user.id,
            changed_by_role="driver",
            reason=reason,
        )
    )
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "driver_cancelled_order",
        old_value={"status": old_status},
        new_value={"status": order.status, "cancel_reason": order.cancel_reason},
        reason=reason,
    )
    create_notification(db, order.client_id, "cancelled", "Buyurtma bekor qilindi", "Haydovchi buyurtmani bekor qildi", order_id=order.id)
    db.commit()
    db.refresh(order)
    return {
        "success": True,
        "data": {
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "cancel_reason": order.cancel_reason,
            "cancelled_at": v1_naive(order.cancelled_at),
        },
        "message": "Order cancelled",
    }
