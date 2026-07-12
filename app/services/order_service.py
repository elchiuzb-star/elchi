from datetime import datetime, timezone
from decimal import Decimal
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Bid, City, District, DriverProfile, Order, OrderOffer, Rating, RouteTariff, StatusHistory, User
from app.schemas.order import ALLOWED_ORDER_STATUSES, ClientOrderCancel, ClientOrderCreate, ClientOrderRatingCreate, SelectDriverRequest
from app.services.audit_service import write_audit_log
from app.services.city_service import district_ref, pagination, validate_active_city_district_pair
from app.services.geo_service import validate_order_location_or_error
from app.services.matching_service import create_order_offers_for_published_order
from app.services.notification_service import create_notification
from app.services.system_settings_service import apply_order_commission
from app.utils.api_response import error_response
from app.utils.order_number import generate_order_number

CLIENT_CANCEL_ALLOWED_STATUSES = {"draft", "published", "bidding", "accepted"}
CLIENT_CANCEL_AFTER_PICKUP_STATUSES = {"picked_up", "in_transit", "delivered", "confirmed"}
CLIENT_EDIT_ALLOWED_STATUSES = {"draft", "published", "bidding"}


class PublishOrderResult:
    def __init__(self, order: Order, matched_drivers_count: int) -> None:
        self.order = order
        self.matched_drivers_count = matched_drivers_count


def city_summary(city: City) -> dict[str, Any]:
    return {"id": city.id, "name_uz": city.name_uz}


def district_summary(district: District | None) -> dict[str, Any] | None:
    return district_ref(district)


def validate_city_pair(db: Session, from_city_id: int, to_city_id: int) -> tuple[City, City] | JSONResponse:
    if from_city_id == to_city_id:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "from_city_id and to_city_id cannot be the same",
        )
    from_city = db.get(City, from_city_id)
    to_city = db.get(City, to_city_id)
    if from_city is None or to_city is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "City not found")
    if not from_city.is_active or not to_city.is_active:
        return error_response(status.HTTP_400_BAD_REQUEST, "CITY_INACTIVE", "Both cities must be active")
    return from_city, to_city


def get_active_tariff(db: Session, from_city_id: int, to_city_id: int) -> RouteTariff | None:
    return db.scalar(
        select(RouteTariff).where(
            RouteTariff.from_city_id == from_city_id,
            RouteTariff.to_city_id == to_city_id,
            RouteTariff.is_active == True,  # noqa: E712
        )
    )


def validate_client_price(client_price: Decimal | None, tariff: RouteTariff | None) -> JSONResponse | None:
    """Ensure the client's proposed price stays within the tariff min/max range (when defined)."""
    if client_price is None or tariff is None:
        return None
    if tariff.min_price is not None and client_price < tariff.min_price:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "CLIENT_PRICE_TOO_LOW",
            f"Narx eng kam {tariff.min_price:.0f} so'mdan kam bo'lmasligi kerak",
        )
    if tariff.max_price is not None and client_price > tariff.max_price:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "CLIENT_PRICE_TOO_HIGH",
            f"Narx eng ko'pi bilan {tariff.max_price:.0f} so'm bo'lishi mumkin",
        )
    return None


def write_status_history(
    db: Session,
    order: Order,
    old_status: str | None,
    new_status: str,
    actor: User,
    reason: str | None = None,
) -> None:
    db.add(
        StatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by_user_id=actor.id,
            changed_by_role=actor.role,
            reason=reason,
        )
    )


def get_bids_count(db: Session, order_id: int) -> int:
    return db.scalar(select(func.count(Bid.id)).where(Bid.order_id == order_id)) or 0


def assigned_driver_to_dict(db: Session, order: Order) -> dict[str, Any] | None:
    if order.assigned_driver_id is None:
        return None
    driver = db.get(DriverProfile, order.assigned_driver_id)
    if driver is None:
        return None
    user = db.get(User, driver.user_id)
    return {
        "id": driver.id,
        "full_name": driver.full_name or (user.full_name if user else None),
        "phone": user.phone if user else None,
        "car_model": driver.car_model,
        "plate_number": driver.plate_number,
        "rating": driver.rating_avg,
        "completed_orders": driver.completed_orders,
    }


def selected_driver_to_dict(db: Session, driver: DriverProfile) -> dict[str, Any]:
    user = db.get(User, driver.user_id)
    return {
        "id": driver.id,
        "full_name": driver.full_name or (user.full_name if user else None),
        "phone": user.phone if user else None,
        "car_model": driver.car_model,
        "plate_number": driver.plate_number,
        "rating": driver.rating_avg,
        "completed_orders": driver.completed_orders,
    }


def bid_summary_to_dict(db: Session, bid: Bid) -> dict[str, Any]:
    driver = db.get(DriverProfile, bid.driver_id)
    user = db.get(User, driver.user_id) if driver is not None else None
    return {
        "id": bid.id,
        "order_id": bid.order_id,
        "price": bid.price,
        "status": bid.status,
        "created_at": bid.created_at,
        "driver": {
            "id": driver.id if driver else None,
            "full_name": (driver.full_name or user.full_name) if driver and user else None,
            "car_model": driver.car_model if driver else None,
            "plate_number": driver.plate_number if driver else None,
            "rating": driver.rating_avg if driver else None,
            "completed_orders": driver.completed_orders if driver else 0,
        },
    }


def list_order_bids(db: Session, user: User, order_id: int) -> list[dict[str, Any]] | JSONResponse:
    order = db.get(Order, order_id)
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.client_id != user.id:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You can view bids only for your own order")
    bids = list(
        db.scalars(
            select(Bid)
            .where(Bid.order_id == order.id, Bid.status == "active")
            .order_by(Bid.price.asc(), Bid.created_at.asc())
        )
    )
    return [bid_summary_to_dict(db, bid) for bid in bids]


def order_detail_to_dict(db: Session, order: Order) -> dict[str, Any]:
    from_city = db.get(City, order.from_city_id)
    to_city = db.get(City, order.to_city_id)
    from_district = db.get(District, order.from_district_id) if order.from_district_id else None
    to_district = db.get(District, order.to_district_id) if order.to_district_id else None
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "from_city": city_summary(from_city),
        "to_city": city_summary(to_city),
        "from_district": district_summary(from_district),
        "to_district": district_summary(to_district),
        "from_district_id": order.from_district_id,
        "to_district_id": order.to_district_id,
        "pickup_address": order.pickup_address,
        "dropoff_address": order.dropoff_address,
        "pickup_lat": order.pickup_lat,
        "pickup_lng": order.pickup_lng,
        "dropoff_lat": order.dropoff_lat,
        "dropoff_lng": order.dropoff_lng,
        "sender_phone": order.sender_phone,
        "receiver_phone": order.receiver_phone,
        "cargo_type": order.cargo_type,
        "cargo_photo_url": order.cargo_photo_url,
        "comment": order.comment,
        "suggested_price": order.suggested_price,
        "client_price": order.client_price,
        "final_price": order.final_price,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "assigned_driver": assigned_driver_to_dict(db, order),
        "accepted_bid_id": order.accepted_bid_id,
        "bids_count": get_bids_count(db, order.id),
        "published_at": order.published_at,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def order_card_to_dict(db: Session, order: Order) -> dict[str, Any]:
    from_city = db.get(City, order.from_city_id)
    to_city = db.get(City, order.to_city_id)
    from_district = db.get(District, order.from_district_id) if order.from_district_id else None
    to_district = db.get(District, order.to_district_id) if order.to_district_id else None
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "from_city": from_city.name_uz if from_city else None,
        "to_city": to_city.name_uz if to_city else None,
        "from_district": district_summary(from_district),
        "to_district": district_summary(to_district),
        "cargo_type": order.cargo_type,
        "suggested_price": order.suggested_price,
        "client_price": order.client_price,
        "final_price": order.final_price,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "bids_count": get_bids_count(db, order.id),
        "created_at": order.created_at,
    }


def create_order_draft(db: Session, user: User, payload: ClientOrderCreate) -> Order | JSONResponse:
    route_parts = validate_active_city_district_pair(
        db,
        payload.from_city_id,
        payload.to_city_id,
        payload.from_district_id,
        payload.to_district_id,
    )
    if isinstance(route_parts, JSONResponse):
        return route_parts

    pickup_location_error = validate_order_location_or_error(
        db,
        lat=payload.pickup_lat,
        lng=payload.pickup_lng,
        region_id=payload.from_city_id,
        district_id=payload.from_district_id,
        label="pickup",
    )
    if pickup_location_error is not None:
        return pickup_location_error
    dropoff_location_error = validate_order_location_or_error(
        db,
        lat=payload.dropoff_lat,
        lng=payload.dropoff_lng,
        region_id=payload.to_city_id,
        district_id=payload.to_district_id,
        label="delivery",
    )
    if dropoff_location_error is not None:
        return dropoff_location_error

    tariff = get_active_tariff(db, payload.from_city_id, payload.to_city_id)
    client_price_error = validate_client_price(payload.client_price, tariff)
    if client_price_error is not None:
        return client_price_error
    order = Order(
        order_number=generate_order_number(),
        client_id=user.id,
        from_city_id=payload.from_city_id,
        to_city_id=payload.to_city_id,
        from_district_id=payload.from_district_id,
        to_district_id=payload.to_district_id,
        pickup_address=payload.pickup_address,
        dropoff_address=payload.dropoff_address,
        pickup_lat=payload.pickup_lat,
        pickup_lng=payload.pickup_lng,
        dropoff_lat=payload.dropoff_lat,
        dropoff_lng=payload.dropoff_lng,
        sender_phone=payload.sender_phone,
        receiver_phone=payload.receiver_phone,
        cargo_type=payload.cargo_type,
        cargo_photo_url=payload.cargo_photo_url,
        comment=payload.comment,
        suggested_price=tariff.suggested_price if tariff else None,
        client_price=payload.client_price,
        status="draft",
        payment_method="cash",
        payment_status="unpaid",
    )
    db.add(order)
    db.flush()
    write_status_history(db, order, None, "draft", user)
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "order_created",
        new_value={"order_number": order.order_number, "status": order.status},
    )
    db.commit()
    db.refresh(order)
    return order


def update_order(db: Session, user: User, order_id: int, payload: ClientOrderCreate) -> Order | JSONResponse:
    order = get_owned_order(db, user, order_id)
    if isinstance(order, JSONResponse):
        return order
    if order.status not in CLIENT_EDIT_ALLOWED_STATUSES:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "ORDER_INVALID_STATUS",
            "Faqat qoralama, e'lon qilingan yoki taklif kutilayotgan buyurtmalar tahrirlanadi",
        )

    route_changed = (
        order.from_city_id != payload.from_city_id
        or order.to_city_id != payload.to_city_id
        or order.from_district_id != payload.from_district_id
        or order.to_district_id != payload.to_district_id
    )
    if route_changed and order.status != "draft":
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "ORDER_ROUTE_LOCKED",
            "E'lon qilingan buyurtmada yo'nalishni o'zgartirib bo'lmaydi. Boshqa yo'nalish uchun buyurtmani bekor qilib, yangisini yarating.",
        )

    route_parts = validate_active_city_district_pair(
        db,
        payload.from_city_id,
        payload.to_city_id,
        payload.from_district_id,
        payload.to_district_id,
    )
    if isinstance(route_parts, JSONResponse):
        return route_parts

    pickup_location_error = validate_order_location_or_error(
        db,
        lat=payload.pickup_lat,
        lng=payload.pickup_lng,
        region_id=payload.from_city_id,
        district_id=payload.from_district_id,
        label="pickup",
    )
    if pickup_location_error is not None:
        return pickup_location_error
    dropoff_location_error = validate_order_location_or_error(
        db,
        lat=payload.dropoff_lat,
        lng=payload.dropoff_lng,
        region_id=payload.to_city_id,
        district_id=payload.to_district_id,
        label="delivery",
    )
    if dropoff_location_error is not None:
        return dropoff_location_error

    old_value = {
        "from_city_id": order.from_city_id,
        "to_city_id": order.to_city_id,
        "from_district_id": order.from_district_id,
        "to_district_id": order.to_district_id,
        "pickup_address": order.pickup_address,
        "dropoff_address": order.dropoff_address,
        "sender_phone": order.sender_phone,
        "receiver_phone": order.receiver_phone,
        "cargo_photo_url": order.cargo_photo_url,
        "comment": order.comment,
    }
    tariff = get_active_tariff(db, payload.from_city_id, payload.to_city_id)
    client_price_error = validate_client_price(payload.client_price, tariff)
    if client_price_error is not None:
        return client_price_error
    order.from_city_id = payload.from_city_id
    order.to_city_id = payload.to_city_id
    order.from_district_id = payload.from_district_id
    order.to_district_id = payload.to_district_id
    order.pickup_address = payload.pickup_address
    order.dropoff_address = payload.dropoff_address
    order.pickup_lat = payload.pickup_lat
    order.pickup_lng = payload.pickup_lng
    order.dropoff_lat = payload.dropoff_lat
    order.dropoff_lng = payload.dropoff_lng
    order.sender_phone = payload.sender_phone
    order.receiver_phone = payload.receiver_phone
    order.cargo_type = payload.cargo_type
    order.cargo_photo_url = payload.cargo_photo_url
    order.comment = payload.comment
    order.suggested_price = tariff.suggested_price if tariff else None
    order.client_price = payload.client_price
    db.add(order)
    db.flush()
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "order_updated",
        old_value=old_value,
        new_value={
            "from_city_id": order.from_city_id,
            "to_city_id": order.to_city_id,
            "from_district_id": order.from_district_id,
            "to_district_id": order.to_district_id,
            "pickup_address": order.pickup_address,
            "dropoff_address": order.dropoff_address,
            "sender_phone": order.sender_phone,
            "receiver_phone": order.receiver_phone,
            "cargo_photo_url": order.cargo_photo_url,
            "comment": order.comment,
        },
    )
    db.commit()
    db.refresh(order)
    return order


def get_owned_order(
    db: Session,
    user: User,
    order_id: int,
    forbidden_on_mismatch: bool = False,
) -> Order | JSONResponse:
    order = db.get(Order, order_id)
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.client_id != user.id:
        if forbidden_on_mismatch:
            return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You can publish only your own orders")
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You can access only your own orders")
    return order


def validate_order_complete(db: Session, order: Order) -> JSONResponse | None:
    route_parts = validate_active_city_district_pair(
        db,
        order.from_city_id,
        order.to_city_id,
        order.from_district_id,
        order.to_district_id,
    )
    if isinstance(route_parts, JSONResponse):
        return route_parts
    pickup_location_error = validate_order_location_or_error(
        db,
        lat=order.pickup_lat,
        lng=order.pickup_lng,
        region_id=order.from_city_id,
        district_id=order.from_district_id,
        label="pickup",
    )
    if pickup_location_error is not None:
        return pickup_location_error
    dropoff_location_error = validate_order_location_or_error(
        db,
        lat=order.dropoff_lat,
        lng=order.dropoff_lng,
        region_id=order.to_city_id,
        district_id=order.to_district_id,
        label="delivery",
    )
    if dropoff_location_error is not None:
        return dropoff_location_error
    missing_fields = [
        field_name
        for field_name, value in {
            "pickup_address": order.pickup_address,
            "dropoff_address": order.dropoff_address,
            "sender_phone": order.sender_phone,
            "receiver_phone": order.receiver_phone,
        }.items()
        if not value
    ]
    if missing_fields:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "Order is missing required fields",
            {"missing_fields": missing_fields},
        )
    return None


def publish_order(db: Session, user: User, order_id: int) -> PublishOrderResult | JSONResponse:
    order = get_owned_order(db, user, order_id, forbidden_on_mismatch=True)
    if isinstance(order, JSONResponse):
        return order
    if order.status != "draft":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Only draft orders can be published")
    validation_error = validate_order_complete(db, order)
    if validation_error is not None:
        return validation_error

    old_status = order.status
    order.status = "published"
    order.published_at = datetime.now(timezone.utc)
    db.add(order)
    db.flush()
    write_status_history(db, order, old_status, "published", user)
    matched_drivers_count = create_order_offers_for_published_order(db, order)
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "order_published",
        old_value={"status": old_status},
        new_value={"status": order.status, "matched_drivers_count": matched_drivers_count},
    )
    db.commit()
    db.refresh(order)
    return PublishOrderResult(order=order, matched_drivers_count=matched_drivers_count)


def list_client_orders(
    db: Session,
    user: User,
    order_status: str | None,
    from_city_id: int | None,
    to_city_id: int | None,
    page: int,
    limit: int,
) -> dict[str, Any] | JSONResponse:
    if order_status is not None and order_status not in ALLOWED_ORDER_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid order status")

    stmt = select(Order).where(Order.client_id == user.id)
    count_stmt = select(func.count(Order.id)).where(Order.client_id == user.id)
    if order_status is not None:
        stmt = stmt.where(Order.status == order_status)
        count_stmt = count_stmt.where(Order.status == order_status)
    if from_city_id is not None:
        stmt = stmt.where(Order.from_city_id == from_city_id)
        count_stmt = count_stmt.where(Order.from_city_id == from_city_id)
    if to_city_id is not None:
        stmt = stmt.where(Order.to_city_id == to_city_id)
        count_stmt = count_stmt.where(Order.to_city_id == to_city_id)

    offset, safe_limit = pagination(page, limit)
    total = db.scalar(count_stmt) or 0
    items = list(db.scalars(stmt.order_by(Order.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "items": [order_card_to_dict(db, order) for order in items],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
    }


def cancel_order(db: Session, user: User, order_id: int, payload: ClientOrderCancel) -> Order | JSONResponse:
    order = get_owned_order(db, user, order_id)
    if isinstance(order, JSONResponse):
        return order
    if order.status in CLIENT_CANCEL_AFTER_PICKUP_STATUSES:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "ORDER_INVALID_STATUS",
            "Client cannot cancel order after pickup",
        )
    if order.status not in CLIENT_CANCEL_ALLOWED_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Order cannot be cancelled")

    old_status = order.status
    order.status = "cancelled"
    order.cancel_reason = payload.reason
    order.cancelled_by = user.id
    order.cancelled_at = datetime.now(timezone.utc)
    db.add(order)
    db.flush()
    write_status_history(db, order, old_status, "cancelled", user, reason=payload.reason)
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "order_cancelled",
        old_value={"status": old_status},
        new_value={"status": order.status, "cancel_reason": order.cancel_reason},
        reason=payload.reason,
    )
    db.commit()
    db.refresh(order)
    return order


def select_driver_for_order(
    db: Session,
    user: User,
    order_id: int,
    payload: SelectDriverRequest,
) -> dict[str, Any] | JSONResponse:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.client_id != user.id:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "You can select driver only for your own order",
        )
    if order.status != "bidding":
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "ORDER_INVALID_STATUS",
            "Only bidding orders can accept a driver",
        )

    bid = db.scalar(select(Bid).where(Bid.id == payload.bid_id).with_for_update())
    if bid is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Bid not found")
    if bid.order_id != order.id:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Bid does not belong to this order")
    if bid.status != "active":
        return error_response(status.HTTP_400_BAD_REQUEST, "BID_NOT_ACTIVE", "Only active bids can be selected")

    driver = db.get(DriverProfile, bid.driver_id)
    driver_user = db.get(User, driver.user_id) if driver is not None else None
    if driver is None or driver.verification_status != "approved":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_NOT_APPROVED", "Selected driver is not approved")
    if driver_user is None or driver_user.status != "active":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_BLOCKED", "Selected driver is not available")

    old_value = {
        "status": order.status,
        "assigned_driver_id": order.assigned_driver_id,
        "accepted_bid_id": order.accepted_bid_id,
        "final_price": order.final_price,
        "system_fee_rate": order.system_fee_rate,
        "system_fee": order.system_fee,
        "driver_income": order.driver_income,
    }
    try:
        old_status = order.status
        order.assigned_driver_id = bid.driver_id
        order.accepted_bid_id = bid.id
        order.final_price = bid.price
        apply_order_commission(db, order)
        order.status = "accepted"
        order.accepted_at = datetime.now(timezone.utc)
        bid.status = "accepted"
        other_bids = list(db.scalars(select(Bid).where(Bid.order_id == order.id, Bid.id != bid.id).with_for_update()))
        for other_bid in other_bids:
            other_bid.status = "closed"
            db.add(other_bid)

        offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order.id, OrderOffer.driver_id == bid.driver_id))
        if offer is not None:
            offer.result = "bid_sent"
            if offer.responded_at is None:
                offer.responded_at = datetime.now(timezone.utc)
            db.add(offer)

        db.add(order)
        db.add(bid)
        db.flush()
        write_status_history(db, order, old_status, "accepted", user, reason="driver_selected")
        write_audit_log(
            db,
            user,
            "orders",
            order.id,
            "driver_selected",
            old_value=old_value,
            new_value={
                "status": order.status,
                "assigned_driver_id": order.assigned_driver_id,
                "accepted_bid_id": order.accepted_bid_id,
                "final_price": order.final_price,
                "system_fee_rate": order.system_fee_rate,
                "system_fee": order.system_fee,
                "driver_income": order.driver_income,
            },
        )
        create_notification(db, driver_user.id, "driver_selected", "Siz tanlandingiz", "Mijoz sizning taklifingizni tanladi", order_id=order.id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(order)
    db.refresh(bid)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "final_price": order.final_price,
        "system_fee_rate": order.system_fee_rate,
        "system_fee": order.system_fee,
        "driver_income": order.driver_income,
        "assigned_driver": selected_driver_to_dict(db, driver),
        "accepted_bid": {
            "id": bid.id,
            "price": bid.price,
            "status": bid.status,
        },
    }


def confirm_delivered_order(db: Session, user: User, order_id: int) -> dict[str, Any] | JSONResponse:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.client_id != user.id:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You can access only your own orders")
    if order.status != "delivered":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Only delivered orders can be confirmed")
    if order.assigned_driver_id is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Order has no assigned driver")
    driver = db.get(DriverProfile, order.assigned_driver_id)
    driver_user = db.get(User, driver.user_id) if driver is not None else None
    if driver is None or driver_user is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Order has no assigned driver")

    old_value = {"status": order.status, "payment_status": order.payment_status}
    old_status = order.status
    order.status = "confirmed"
    order.confirmed_at = datetime.now(timezone.utc)
    order.payment_method = "cash"
    order.payment_status = "paid_manual"
    db.add(order)
    db.flush()
    write_status_history(db, order, old_status, "confirmed", user, reason="client_confirmed")
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "order_confirmed",
        old_value=old_value,
        new_value={"status": order.status, "payment_status": order.payment_status},
        reason="client_confirmed",
    )
    create_notification(db, driver_user.id, "confirmed", "Buyurtma yakunlandi", "Mijoz buyurtmani tasdiqladi", order_id=order.id)
    db.commit()
    db.refresh(order)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "confirmed_at": order.confirmed_at,
    }


def recalculate_driver_rating(db: Session, driver_id: int) -> None:
    average = db.scalar(select(func.avg(Rating.rating)).where(Rating.driver_id == driver_id))
    driver = db.get(DriverProfile, driver_id)
    if driver is not None:
        driver.rating_avg = Decimal(str(round(float(average or 0), 2)))
        db.add(driver)


def create_order_rating(
    db: Session,
    user: User,
    order_id: int,
    payload: ClientOrderRatingCreate,
) -> Rating | JSONResponse:
    if payload.rating < 1 or payload.rating > 5:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Rating must be between 1 and 5")
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.client_id != user.id:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You can access only your own orders")
    if order.status != "confirmed":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Only confirmed orders can be rated")
    if order.assigned_driver_id is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Order has no assigned driver")
    existing_rating = db.scalar(select(Rating).where(Rating.order_id == order.id))
    if existing_rating is not None:
        return error_response(status.HTTP_409_CONFLICT, "ALREADY_EXISTS", "Rating already exists for this order")

    driver = db.get(DriverProfile, order.assigned_driver_id)
    driver_user = db.get(User, driver.user_id) if driver is not None else None
    if driver is None or driver_user is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Order has no assigned driver")

    rating = Rating(
        order_id=order.id,
        client_id=user.id,
        driver_id=order.assigned_driver_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(rating)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return error_response(status.HTTP_409_CONFLICT, "ALREADY_EXISTS", "Rating already exists for this order")

    recalculate_driver_rating(db, order.assigned_driver_id)
    write_audit_log(
        db,
        user,
        "ratings",
        rating.id,
        "rating_created",
        new_value={"order_id": order.id, "driver_id": order.assigned_driver_id, "rating": rating.rating},
    )
    create_notification(db, driver_user.id, "rating_received", "Yangi baho", "Mijoz sizga baho qoldirdi", order_id=order.id)
    db.commit()
    db.refresh(rating)
    return rating
