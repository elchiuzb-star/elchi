from datetime import date, datetime, time, timezone
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Bid, City, Dispute, DriverProfile, DriverRoute, Order, StatusHistory, User
from app.utils.file_access import signed_file_url
from app.schemas.admin_order import AdminAssignDriver, AdminOrderCancel, AdminOrderStatusUpdate
from app.services.audit_service import write_audit_log
from app.services.city_service import pagination
from app.services.dispute_service import ACTIVE_DISPUTE_STATUSES, has_active_dispute
from app.services.driver_locks import lock_driver_user_and_profile
from app.services.notification_service import create_notification
from app.services.review_accounts import is_review_order, review_order_ids, review_pairing_allowed
from app.services.system_settings_service import apply_order_commission
from app.utils.api_response import error_response
from app.utils.legacy_time import v1_naive

ADMIN_ORDER_ROLES = {"operator", "admin", "super_admin"}
ORDER_STATUSES = {"draft", "published", "bidding", "accepted", "picked_up", "in_transit", "delivered", "confirmed", "cancelled", "disputed"}
MANUAL_TARGET_STATUSES = ORDER_STATUSES - {"draft"}
NORMAL_TRANSITIONS = {
    "draft": "published",
    "published": "bidding",
    "bidding": "accepted",
    "accepted": "picked_up",
    "picked_up": "in_transit",
    "in_transit": "delivered",
    "delivered": "confirmed",
}
TIMESTAMP_FIELDS = {
    "published": "published_at",
    "accepted": "accepted_at",
    "picked_up": "picked_up_at",
    "in_transit": "in_transit_at",
    "delivered": "delivered_at",
    "confirmed": "confirmed_at",
    "cancelled": "cancelled_at",
}


def require_reason(reason: str | None) -> str | JSONResponse:
    if reason is None or not reason.strip():
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Reason is required for manual admin/operator action")
    return reason.strip()


def city_summary(city: City | None) -> dict[str, Any] | None:
    if city is None:
        return None
    return {"id": city.id, "name_uz": city.name_uz}


def user_summary(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "phone": user.phone, "full_name": user.full_name}


def driver_summary(db: Session, driver_id: int | None, *, include_stats: bool = False) -> dict[str, Any] | None:
    if driver_id is None:
        return None
    driver = db.get(DriverProfile, driver_id)
    if driver is None:
        return None
    user = db.get(User, driver.user_id)
    data = {
        "id": driver.id,
        "phone": user.phone if user else None,
        "full_name": driver.full_name or (user.full_name if user else None),
        "car_model": driver.car_model,
        "plate_number": driver.plate_number,
    }
    if include_stats:
        data["rating"] = driver.rating_avg
        data["completed_orders"] = driver.completed_orders
    return data


def order_summary_to_dict(db: Session, order: Order, is_review: bool | None = None) -> dict[str, Any]:
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "from_city": city_summary(db.get(City, order.from_city_id)),
        "to_city": city_summary(db.get(City, order.to_city_id)),
        "client": user_summary(db.get(User, order.client_id)),
        "assigned_driver": driver_summary(db, order.assigned_driver_id),
        "suggested_price": order.suggested_price,
        "final_price": order.final_price,
        "system_fee_rate": order.system_fee_rate,
        "system_fee": order.system_fee,
        "driver_income": order.driver_income,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        # Additive: store-review test traffic (client or assigned driver on the allowlist).
        "is_review_account": is_review_order(db, order) if is_review is None else is_review,
    }


def bid_summary_to_dict(db: Session, bid: Bid) -> dict[str, Any]:
    driver = db.get(DriverProfile, bid.driver_id)
    user = db.get(User, driver.user_id) if driver else None
    return {
        "id": bid.id,
        "driver_id": bid.driver_id,
        "driver_name": driver.full_name or (user.full_name if user else None) if driver else None,
        "price": bid.price,
        "status": bid.status,
        "created_at": bid.created_at,
    }


def admin_order_detail_to_dict(db: Session, order: Order) -> dict[str, Any]:
    bids = list(db.scalars(select(Bid).where(Bid.order_id == order.id).order_by(Bid.created_at.desc())))
    history = list(db.scalars(select(StatusHistory).where(StatusHistory.order_id == order.id).order_by(StatusHistory.created_at.asc())))
    dispute = db.scalar(select(Dispute).where(Dispute.order_id == order.id).order_by(Dispute.created_at.desc()))
    accepted_bid = db.get(Bid, order.accepted_bid_id) if order.accepted_bid_id else None
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "from_city": city_summary(db.get(City, order.from_city_id)),
        "to_city": city_summary(db.get(City, order.to_city_id)),
        "pickup_address": order.pickup_address,
        "dropoff_address": order.dropoff_address,
        "sender_phone": order.sender_phone,
        "receiver_phone": order.receiver_phone,
        "cargo_photo_url": signed_file_url(order.cargo_photo_url),
        "comment": order.comment,
        "suggested_price": order.suggested_price,
        "final_price": order.final_price,
        "system_fee_rate": order.system_fee_rate,
        "system_fee": order.system_fee,
        "driver_income": order.driver_income,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "client": user_summary(db.get(User, order.client_id)),
        "assigned_driver": driver_summary(db, order.assigned_driver_id, include_stats=True),
        "accepted_bid": {
            "id": accepted_bid.id,
            "price": accepted_bid.price,
            "status": accepted_bid.status,
        } if accepted_bid else None,
        "bids": [bid_summary_to_dict(db, bid) for bid in bids],
        "status_history": [
            {
                "old_status": item.old_status,
                "new_status": item.new_status,
                "changed_by_role": item.changed_by_role,
                "reason": item.reason,
                "created_at": item.created_at,
            }
            for item in history
        ],
        "dispute": {
            "id": dispute.id,
            "reason": dispute.reason,
            "status": dispute.status,
            "previous_order_status": dispute.previous_order_status,
        } if dispute else None,
        "published_at": v1_naive(order.published_at),
        "accepted_at": v1_naive(order.accepted_at),
        "picked_up_at": v1_naive(order.picked_up_at),
        "in_transit_at": v1_naive(order.in_transit_at),
        "delivered_at": v1_naive(order.delivered_at),
        "confirmed_at": v1_naive(order.confirmed_at),
        "cancelled_at": v1_naive(order.cancelled_at),
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "is_review_account": is_review_order(db, order),
    }


def list_admin_orders(
    db: Session,
    order_status: str | None,
    from_city_id: int | None,
    to_city_id: int | None,
    client_phone: str | None,
    driver_phone: str | None,
    order_number: str | None,
    payment_status: str | None,
    created_from: date | None,
    created_to: date | None,
    page: int,
    limit: int,
) -> dict[str, Any] | JSONResponse:
    if order_status is not None and order_status not in ORDER_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid order status")
    stmt = select(Order)
    count_stmt = select(func.count(Order.id))
    filters = []
    if order_status is not None:
        filters.append(Order.status == order_status)
    if from_city_id is not None:
        filters.append(Order.from_city_id == from_city_id)
    if to_city_id is not None:
        filters.append(Order.to_city_id == to_city_id)
    if order_number is not None:
        filters.append(Order.order_number.contains(order_number))
    if payment_status is not None:
        filters.append(Order.payment_status == payment_status)
    if created_from is not None:
        filters.append(Order.created_at >= datetime.combine(created_from, time.min, tzinfo=timezone.utc))
    if created_to is not None:
        filters.append(Order.created_at <= datetime.combine(created_to, time.max, tzinfo=timezone.utc))
    if client_phone is not None:
        client_ids = select(User.id).where(User.phone.contains(client_phone))
        filters.append(Order.client_id.in_(client_ids))
    if driver_phone is not None:
        driver_ids = select(DriverProfile.id).join(User, User.id == DriverProfile.user_id).where(User.phone.contains(driver_phone))
        filters.append(Order.assigned_driver_id.in_(driver_ids))
    for item in filters:
        stmt = stmt.where(item)
        count_stmt = count_stmt.where(item)
    offset, safe_limit = pagination(page, limit)
    total = db.scalar(count_stmt) or 0
    orders = list(db.scalars(stmt.order_by(Order.created_at.desc()).offset(offset).limit(safe_limit)))
    review_ids = review_order_ids(db, orders)  # batched: two queries for the page
    return {
        "items": [order_summary_to_dict(db, order, is_review=order.id in review_ids) for order in orders],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
    }


def get_admin_order_detail(db: Session, order_id: int) -> dict[str, Any] | JSONResponse:
    order = db.get(Order, order_id)
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    return admin_order_detail_to_dict(db, order)


def add_order_notifications(db: Session, order: Order, notification_type: str, title: str, message: str) -> None:
    create_notification(db, order.client_id, notification_type, title, message, order_id=order.id)
    if order.assigned_driver_id is not None:
        driver = db.get(DriverProfile, order.assigned_driver_id)
        if driver is not None:
            create_notification(db, driver.user_id, notification_type, title, message, order_id=order.id)


def set_order_timestamp(order: Order, new_status: str) -> None:
    field = TIMESTAMP_FIELDS.get(new_status)
    if field is not None and getattr(order, field) is None:
        setattr(order, field, datetime.now(timezone.utc))


def validate_manual_status_transition(user: User, order: Order, target_status: str) -> JSONResponse | None:
    if target_status not in MANUAL_TARGET_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    if target_status == order.status:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    if order.status == "cancelled":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    if order.status == "confirmed" and target_status not in {"cancelled", "disputed"}:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    if order.status == "confirmed" and target_status == "cancelled" and user.role == "operator":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    if order.status == "confirmed" and target_status == "disputed" and user.role == "operator":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    return None


def active_dispute_error(db: Session, order: Order, *, cancelling: bool = False) -> JSONResponse | None:
    """Q12 / decision 37: no manual status change or admin cancel (including out of
    `disputed`) while a dispute is open or under review: the order's status is
    decided by resolving the dispute first."""
    dispute_id = db.scalar(
        select(Dispute.id)
        .where(Dispute.order_id == order.id, Dispute.status.in_(list(ACTIVE_DISPUTE_STATUSES)))
        .order_by(Dispute.id.desc())
    )
    if dispute_id is None:
        return None
    if cancelling:
        message = (
            f"Order has an active dispute. Resolve or reject it via PATCH /api/v1/admin/disputes/{dispute_id} first, "
            f"then cancel the order via POST /api/v1/admin/orders/{order.id}/cancel"
        )
    else:
        message = f"Order has an active dispute. Resolve or reject it via PATCH /api/v1/admin/disputes/{dispute_id} first"
    return error_response(status.HTTP_409_CONFLICT, "DISPUTE_ACTIVE", message)


def update_admin_order_status(db: Session, user: User, order_id: int, payload: AdminOrderStatusUpdate) -> dict[str, Any] | JSONResponse:
    reason = require_reason(payload.reason)
    if isinstance(reason, JSONResponse):
        return reason
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    dispute_error = active_dispute_error(db, order)
    if dispute_error is not None:
        return dispute_error
    transition_error = validate_manual_status_transition(user, order, payload.status)
    if transition_error is not None:
        return transition_error
    if payload.status == "disputed" and not has_active_dispute(db, order.id):
        # A disputed order without a dispute record has nothing to resolve and
        # no previous status to review. Disputes are opened only via the
        # disputes endpoint, which writes the record in the same transaction.
        return error_response(
            status.HTTP_409_CONFLICT,
            "DISPUTE_REQUIRED",
            f"Open a dispute via POST /api/v1/orders/{order.id}/disputes instead of forcing the disputed status",
        )
    old_status = order.status
    order.status = payload.status
    set_order_timestamp(order, payload.status)
    if payload.status == "confirmed":
        order.payment_status = "paid_manual"
    if payload.status == "cancelled":
        order.cancel_reason = reason
        order.cancelled_by = user.id
        order.cancelled_at = datetime.now(timezone.utc)
    db.add(order)
    db.flush()
    db.add(StatusHistory(order_id=order.id, old_status=old_status, new_status=order.status, changed_by_user_id=user.id, changed_by_role=user.role, reason=reason))
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "admin_order_status_updated",
        old_value={"status": old_status},
        new_value={"status": order.status},
        reason=reason,
    )
    add_order_notifications(db, order, "admin_order_status_updated", "Buyurtma holati yangilandi", "Operator buyurtma holatini yangiladi")
    db.commit()
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "old_status": old_status,
        "new_status": order.status,
        "changed_by_role": user.role,
        "reason": reason,
    }


def driver_has_available_route(db: Session, driver_id: int, order: Order) -> bool:
    return bool(
        db.scalar(
            select(DriverRoute.id).where(
                DriverRoute.driver_id == driver_id,
                DriverRoute.from_city_id == order.from_city_id,
                DriverRoute.to_city_id == order.to_city_id,
                DriverRoute.status == "available",
            )
        )
    )


def validate_driver_for_assignment(db: Session, driver_id: int) -> tuple[DriverProfile, User] | JSONResponse:
    # Caller holds the order and bid locks; users -> driver_profiles come next.
    driver, user = lock_driver_user_and_profile(db, driver_id)
    if driver is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Driver not found")
    if driver.verification_status != "approved":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_NOT_APPROVED", "Only approved drivers can be assigned")
    if user is None or user.status != "active":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_BLOCKED", "Driver is blocked or inactive")
    return driver, user


def assign_driver_manually(db: Session, user: User, order_id: int, payload: AdminAssignDriver) -> dict[str, Any] | JSONResponse:
    reason = require_reason(payload.reason)
    if isinstance(reason, JSONResponse):
        return reason
    if payload.final_price <= 0:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "final_price must be greater than 0")
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.status not in {"published", "bidding"}:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    # Lock order (app/services/driver_locks.py): order -> active bids by id ->
    # driver user -> driver profile; eligibility is re-checked inside the locks.
    active_bids = list(db.scalars(select(Bid).where(Bid.order_id == order.id, Bid.status == "active").order_by(Bid.id).with_for_update()))
    driver_result = validate_driver_for_assignment(db, payload.driver_id)
    if isinstance(driver_result, JSONResponse):
        return driver_result
    driver, driver_user = driver_result
    if not review_pairing_allowed(db, order.client_id, driver_user.id):
        # Store-review drivers never serve real clients (and vice versa).
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_NOT_AVAILABLE", "Driver is not available for this order")
    if not driver_has_available_route(db, driver.id, order):
        return error_response(status.HTTP_400_BAD_REQUEST, "ROUTE_NOT_MATCHED", "Driver does not have an available route for this order")

    old_status = order.status
    accepted_bid_id = None
    for bid in active_bids:
        if bid.driver_id == driver.id:
            bid.status = "accepted"
            accepted_bid_id = bid.id
        else:
            bid.status = "closed"
        db.add(bid)
    order.assigned_driver_id = driver.id
    order.accepted_bid_id = accepted_bid_id
    order.final_price = payload.final_price
    apply_order_commission(db, order)
    order.status = "accepted"
    order.accepted_at = datetime.now(timezone.utc)
    db.add(order)
    db.flush()
    db.add(StatusHistory(order_id=order.id, old_status=old_status, new_status="accepted", changed_by_user_id=user.id, changed_by_role=user.role, reason=reason))
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "admin_driver_assigned",
        old_value={"status": old_status, "assigned_driver_id": None, "final_price": None},
        new_value={
            "status": order.status,
            "assigned_driver_id": order.assigned_driver_id,
            "accepted_bid_id": order.accepted_bid_id,
            "final_price": order.final_price,
            "system_fee_rate": order.system_fee_rate,
            "system_fee": order.system_fee,
            "driver_income": order.driver_income,
        },
        reason=reason,
    )
    add_order_notifications(db, order, "admin_driver_assigned", "Haydovchi tayinlandi", "Operator buyurtmaga haydovchi tayinladi")
    db.commit()
    db.refresh(order)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "assigned_driver": driver_summary(db, driver.id),
        "final_price": order.final_price,
        "system_fee_rate": order.system_fee_rate,
        "system_fee": order.system_fee,
        "driver_income": order.driver_income,
        "accepted_bid_id": order.accepted_bid_id,
    }


def close_active_bids(db: Session, order_id: int) -> None:
    bids = list(db.scalars(select(Bid).where(Bid.order_id == order_id, Bid.status == "active").order_by(Bid.id).with_for_update()))
    for bid in bids:
        bid.status = "closed"
        db.add(bid)


def cancel_order_manually(db: Session, user: User, order_id: int, payload: AdminOrderCancel) -> dict[str, Any] | JSONResponse:
    reason = require_reason(payload.reason)
    if isinstance(reason, JSONResponse):
        return reason
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if order.status == "cancelled":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    dispute_error = active_dispute_error(db, order, cancelling=True)
    if dispute_error is not None:
        return dispute_error
    if order.status == "confirmed" and user.role == "operator":
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This status transition is not allowed")
    old_status = order.status
    order.status = "cancelled"
    order.cancel_reason = reason
    order.cancelled_by = user.id
    order.cancelled_at = datetime.now(timezone.utc)
    close_active_bids(db, order.id)
    db.add(order)
    db.flush()
    db.add(StatusHistory(order_id=order.id, old_status=old_status, new_status="cancelled", changed_by_user_id=user.id, changed_by_role=user.role, reason=reason))
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "admin_order_cancelled",
        old_value={"status": old_status},
        new_value={"status": order.status, "cancel_reason": order.cancel_reason},
        reason=reason,
    )
    add_order_notifications(db, order, "admin_order_cancelled", "Buyurtma bekor qilindi", "Operator buyurtmani bekor qildi")
    db.commit()
    db.refresh(order)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "old_status": old_status,
        "new_status": order.status,
        "cancel_reason": order.cancel_reason,
        "cancelled_by": order.cancelled_by,
        "cancelled_at": v1_naive(order.cancelled_at),
    }
