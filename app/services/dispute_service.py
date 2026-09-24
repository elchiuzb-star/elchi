from datetime import datetime, timezone
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, City, Dispute, DriverProfile, Order, StatusHistory, User
from app.schemas.dispute import DisputeCreate, DisputeUpdate
from app.services.audit_service import write_audit_log
from app.services.city_service import pagination
from app.services.notification_service import create_notification
from app.utils.api_response import error_response
from app.utils.legacy_time import v1_naive

ALLOWED_DISPUTE_REASONS = {
    "delayed",
    "lost",
    "damaged",
    "receiver_denied",
    "wrong_address",
    "payment_issue",
    "prohibited_item",
    "other",
}
ALLOWED_DISPUTE_STATUSES = {"open", "under_review", "resolved", "rejected"}
ACTIVE_DISPUTE_STATUSES = {"open", "under_review"}
ADMIN_ROLES = {"operator", "admin", "super_admin"}
FINAL_DISPUTE_STATUSES = {"resolved", "rejected"}
DISPUTE_RESOLVER_ROLES = {"admin", "super_admin"}
OPERATOR_DISPUTE_TARGET_STATUS = "under_review"
OPEN_ROLES = {"client", "driver", *ADMIN_ROLES}
USER_DISPUTABLE_STATUSES = {"accepted", "picked_up", "in_transit", "delivered"}
ADMIN_DISPUTABLE_STATUSES = {"published", "bidding", "accepted", "picked_up", "in_transit", "delivered", "confirmed"}
RESTORABLE_STATUSES = {"published", "bidding", "accepted", "picked_up", "in_transit", "delivered", "confirmed"}


def user_summary(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "role": user.role}


def get_driver_profile_for_user(db: Session, user_id: int) -> DriverProfile | None:
    return db.scalar(select(DriverProfile).where(DriverProfile.user_id == user_id))


def order_city_name(db: Session, city_id: int) -> str | None:
    city = db.get(City, city_id)
    return city.name_uz if city else None


def dispute_to_public_dict(db: Session, dispute: Dispute) -> dict[str, Any]:
    order = db.get(Order, dispute.order_id)
    opened_by = db.get(User, dispute.opened_by_user_id)
    return {
        "id": dispute.id,
        "order_id": dispute.order_id,
        "order_number": order.order_number if order else None,
        "reason": dispute.reason,
        "status": dispute.status,
        "previous_order_status": dispute.previous_order_status,
        "opened_by": user_summary(opened_by),
        "created_at": dispute.created_at,
    }


def dispute_to_admin_list_dict(db: Session, dispute: Dispute) -> dict[str, Any]:
    order = db.get(Order, dispute.order_id)
    opened_by = db.get(User, dispute.opened_by_user_id)
    client = db.get(User, order.client_id) if order else None
    driver = db.get(DriverProfile, order.assigned_driver_id) if order and order.assigned_driver_id else None
    driver_user = db.get(User, driver.user_id) if driver else None
    return {
        "id": dispute.id,
        "order": {
            "id": order.id if order else None,
            "order_number": order.order_number if order else None,
            "status": order.status if order else None,
            "from_city": order_city_name(db, order.from_city_id) if order else None,
            "to_city": order_city_name(db, order.to_city_id) if order else None,
            "client_phone": client.phone if client else None,
            "driver_phone": driver_user.phone if driver_user else None,
            "final_price": order.final_price if order else None,
        },
        "reason": dispute.reason,
        "comment": dispute.comment,
        "status": dispute.status,
        "previous_order_status": dispute.previous_order_status,
        "opened_by": user_summary(opened_by),
        "created_at": dispute.created_at,
    }


def dispute_detail_to_dict(db: Session, dispute: Dispute) -> dict[str, Any]:
    order = db.get(Order, dispute.order_id)
    client = db.get(User, order.client_id) if order else None
    driver = db.get(DriverProfile, order.assigned_driver_id) if order and order.assigned_driver_id else None
    driver_user = db.get(User, driver.user_id) if driver else None
    history = list(db.scalars(select(StatusHistory).where(StatusHistory.order_id == dispute.order_id).order_by(StatusHistory.created_at.asc())))
    audits = list(db.scalars(select(AuditLog).where(AuditLog.entity_id == dispute.order_id).order_by(AuditLog.created_at.desc()).limit(20)))
    return {
        "id": dispute.id,
        "order": {
            "id": order.id if order else None,
            "order_number": order.order_number if order else None,
            "status": order.status if order else None,
            "previous_order_status": dispute.previous_order_status,
            "from_city": order_city_name(db, order.from_city_id) if order else None,
            "to_city": order_city_name(db, order.to_city_id) if order else None,
            "pickup_address": order.pickup_address if order else None,
            "dropoff_address": order.dropoff_address if order else None,
            "sender_phone": order.sender_phone if order else None,
            "receiver_phone": order.receiver_phone if order else None,
            "final_price": order.final_price if order else None,
            "payment_method": order.payment_method if order else None,
            "payment_status": order.payment_status if order else None,
        },
        "client": {
            "id": client.id if client else None,
            "phone": client.phone if client else None,
            "full_name": client.full_name if client else None,
        },
        "driver": {
            "id": driver.id if driver else None,
            "phone": driver_user.phone if driver_user else None,
            "full_name": driver.full_name if driver else None,
            "car_model": driver.car_model if driver else None,
            "plate_number": driver.plate_number if driver else None,
        },
        "reason": dispute.reason,
        "comment": dispute.comment,
        "status": dispute.status,
        "resolution": dispute.resolution,
        "resolved_by": dispute.resolved_by,
        "resolved_at": v1_naive(dispute.resolved_at),
        "created_at": dispute.created_at,
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
        "audit_summary": [
            {"action": item.action, "actor_id": item.actor_id, "created_at": item.created_at}
            for item in audits
        ],
    }


def can_user_access_order_for_dispute(db: Session, user: User, order: Order) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    if user.role == "client":
        return order.client_id == user.id
    if user.role == "driver":
        profile = get_driver_profile_for_user(db, user.id)
        return profile is not None and order.assigned_driver_id == profile.id
    return False


def validate_open_status(user: User, order: Order) -> JSONResponse | None:
    allowed = ADMIN_DISPUTABLE_STATUSES if user.role in ADMIN_ROLES else USER_DISPUTABLE_STATUSES
    if order.status not in allowed:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "This order status cannot be disputed")
    return None


def has_active_dispute(db: Session, order_id: int) -> bool:
    return bool(
        db.scalar(
            select(Dispute.id).where(
                Dispute.order_id == order_id,
                Dispute.status.in_(list(ACTIVE_DISPUTE_STATUSES)),
            )
        )
    )


def add_dispute_notifications(db: Session, order: Order, opened_by: User) -> None:
    if opened_by.role == "driver":
        create_notification(db, order.client_id, "disputed", "Muammo ochildi", "Buyurtma bo'yicha muammo ochildi", order_id=order.id)
    elif order.assigned_driver_id is not None:
        driver = db.get(DriverProfile, order.assigned_driver_id)
        if driver is not None:
            create_notification(db, driver.user_id, "disputed", "Muammo ochildi", "Buyurtma bo'yicha muammo ochildi", order_id=order.id)
    # TODO: add operator/admin group notifications when staff notification targets exist.
    # Checked 24.09.2026: none exists yet. v1 ``notifications`` rows are per-user only (no group/role target), and a
    # fan-out to every staff user would invent one. The v2 outbox does not deliver staff events per user either
    # (``app/modules/communications/recipients.py``: "Staff-only events are not delivered per user"), and the v2 O4
    # dispute queue (``operations.service.ops_queue``) lists v2 ``trust_support`` disputes, not these v1 rows.
    # Staff find new v1 disputes through ``GET /api/v1/admin/disputes`` (status=open). Needs a decision on a staff
    # target (group inbox or queue) before this can be wired.


def open_dispute(db: Session, user: User, order_id: int, payload: DisputeCreate) -> Dispute | JSONResponse:
    if user.role not in OPEN_ROLES:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You do not have permission to open dispute for this order")
    if payload.reason not in ALLOWED_DISPUTE_REASONS:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid dispute reason")
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Order not found")
    if not can_user_access_order_for_dispute(db, user, order):
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You do not have permission to open dispute for this order")
    if has_active_dispute(db, order.id):
        return error_response(status.HTTP_409_CONFLICT, "ALREADY_EXISTS", "This order already has an active dispute")
    status_error = validate_open_status(user, order)
    if status_error is not None:
        return status_error

    previous_status = order.status
    dispute = Dispute(
        order_id=order.id,
        opened_by_user_id=user.id,
        reason=payload.reason,
        comment=payload.comment,
        status="open",
        previous_order_status=previous_status,
    )
    order.status = "disputed"
    db.add(dispute)
    db.add(order)
    db.flush()
    db.add(
        StatusHistory(
            order_id=order.id,
            old_status=previous_status,
            new_status="disputed",
            changed_by_user_id=user.id,
            changed_by_role=user.role,
            reason="dispute_opened",
        )
    )
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "dispute_opened",
        old_value={"order_status": previous_status},
        new_value={"order_status": order.status, "dispute_reason": dispute.reason},
        reason="dispute_opened",
    )
    write_audit_log(
        db,
        user,
        "orders",
        order.id,
        "order_status_changed_to_disputed",
        old_value={"status": previous_status},
        new_value={"status": order.status},
        reason="dispute_opened",
    )
    add_dispute_notifications(db, order, user)
    db.commit()
    db.refresh(dispute)
    return dispute


def list_disputes(
    db: Session,
    user: User,
    dispute_status: str | None,
    reason: str | None,
    page: int,
    limit: int,
    *,
    admin: bool = False,
    order_id: int | None = None,
    opened_by: int | None = None,
    from_city_id: int | None = None,
    to_city_id: int | None = None,
) -> dict[str, Any] | JSONResponse:
    if dispute_status is not None and dispute_status not in ALLOWED_DISPUTE_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid dispute status")
    if reason is not None and reason not in ALLOWED_DISPUTE_REASONS:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid dispute reason")

    stmt = select(Dispute).join(Order, Order.id == Dispute.order_id)
    count_stmt = select(func.count(Dispute.id)).join(Order, Order.id == Dispute.order_id)
    filters = []
    if not admin:
        if user.role == "client":
            filters.append(Order.client_id == user.id)
        elif user.role == "driver":
            profile = get_driver_profile_for_user(db, user.id)
            filters.append(Order.assigned_driver_id == (profile.id if profile else -1))
        elif user.role not in ADMIN_ROLES:
            return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Insufficient permissions")
    if dispute_status is not None:
        filters.append(Dispute.status == dispute_status)
    if reason is not None:
        filters.append(Dispute.reason == reason)
    if order_id is not None:
        filters.append(Dispute.order_id == order_id)
    if opened_by is not None:
        filters.append(Dispute.opened_by_user_id == opened_by)
    if from_city_id is not None:
        filters.append(Order.from_city_id == from_city_id)
    if to_city_id is not None:
        filters.append(Order.to_city_id == to_city_id)
    for item in filters:
        stmt = stmt.where(item)
        count_stmt = count_stmt.where(item)

    offset, safe_limit = pagination(page, limit)
    total = db.scalar(count_stmt) or 0
    disputes = list(db.scalars(stmt.order_by(Dispute.created_at.desc()).offset(offset).limit(safe_limit)))
    serializer = dispute_to_admin_list_dict if admin else dispute_to_public_dict
    return {
        "items": [serializer(db, dispute) for dispute in disputes],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
    }


def get_admin_dispute_detail(db: Session, dispute_id: int) -> dict[str, Any] | JSONResponse:
    dispute = db.get(Dispute, dispute_id)
    if dispute is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Dispute not found")
    return dispute_detail_to_dict(db, dispute)


def notify_dispute_parties(db: Session, order: Order, notification_type: str, title: str, message: str) -> None:
    create_notification(db, order.client_id, notification_type, title, message, order_id=order.id)
    if order.assigned_driver_id is not None:
        driver = db.get(DriverProfile, order.assigned_driver_id)
        if driver is not None:
            create_notification(db, driver.user_id, notification_type, title, message, order_id=order.id)


def update_dispute(db: Session, user: User, dispute_id: int, payload: DisputeUpdate) -> dict[str, Any] | JSONResponse:
    # Existence first, for every staff role: a missing dispute is 404 before any
    # validation or permission check. The endpoint is staff-only (401/403 for
    # everyone else before this point), so existence is not leaked to clients,
    # and staff get one consistent answer, as with other v1 admin endpoints.
    dispute = db.scalar(select(Dispute).where(Dispute.id == dispute_id).with_for_update())
    if dispute is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Dispute not found")
    if payload.status not in ALLOWED_DISPUTE_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid dispute status")
    # Q13 / decision 38: resolving/rejecting changes the order's status, so it is
    # admin+ only. An operator may only move a dispute to under_review, with a
    # non-empty note (the existing `resolution` text field).
    if user.role not in DISPUTE_RESOLVER_ROLES:
        if payload.status in FINAL_DISPUTE_STATUSES:
            return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Admin role required to resolve or reject a dispute")
        if payload.status != OPERATOR_DISPUTE_TARGET_STATUS:
            return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Operators can only move a dispute to under_review")
        if payload.resolution is None or not payload.resolution.strip():
            return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "A note is required to move a dispute to under_review")
    if payload.status in {"resolved", "rejected"} and (payload.resolution is None or not payload.resolution.strip()):
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Resolution is required for resolved or rejected dispute")
    if dispute.status in {"resolved", "rejected"} and payload.status != dispute.status:
        return error_response(status.HTTP_400_BAD_REQUEST, "ORDER_INVALID_STATUS", "Resolved or rejected disputes are final")

    order = db.scalar(select(Order).where(Order.id == dispute.order_id).with_for_update())
    old_status = dispute.status
    dispute.status = payload.status
    if payload.resolution is not None:
        dispute.resolution = payload.resolution
    if payload.status in {"resolved", "rejected"}:
        dispute.resolution = payload.resolution.strip()
        dispute.resolved_by = user.id
        dispute.resolved_at = datetime.now(timezone.utc)

    restored_status = order.status if order else None
    if order is not None and payload.status in {"resolved", "rejected"} and order.status == "disputed":
        target_status = dispute.previous_order_status if dispute.previous_order_status in RESTORABLE_STATUSES else None
        if target_status is not None:
            order.status = target_status
            restored_status = target_status
            db.add(order)
            db.add(
                StatusHistory(
                    order_id=order.id,
                    old_status="disputed",
                    new_status=target_status,
                    changed_by_user_id=user.id,
                    changed_by_role=user.role,
                    reason="dispute_resolved" if payload.status == "resolved" else "dispute_rejected",
                )
            )
            write_audit_log(
                db,
                user,
                "orders",
                order.id,
                "order_status_restored_after_dispute",
                old_value={"status": "disputed"},
                new_value={"status": target_status},
                reason="dispute_resolved" if payload.status == "resolved" else "dispute_rejected",
            )

    db.add(dispute)
    db.flush()
    action = "dispute_resolved" if payload.status == "resolved" else "dispute_rejected" if payload.status == "rejected" else "dispute_status_updated"
    write_audit_log(
        db,
        user,
        "disputes",
        dispute.id,
        action,
        old_value={"status": old_status},
        new_value={"status": dispute.status, "resolution": dispute.resolution},
        reason=payload.resolution,
    )
    if order is not None:
        notify_dispute_parties(
            db,
            order,
            "disputed",
            "Nizo yangilandi",
            "Buyurtma bo'yicha nizo holati yangilandi",
        )
    db.commit()
    db.refresh(dispute)
    return {
        "dispute_id": dispute.id,
        "order_id": dispute.order_id,
        "dispute_status": dispute.status,
        "order_status": restored_status,
        "resolution": dispute.resolution,
        "resolved_by": dispute.resolved_by,
        "resolved_at": v1_naive(dispute.resolved_at),
    }
