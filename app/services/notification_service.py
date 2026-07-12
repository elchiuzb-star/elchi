from datetime import datetime, timezone
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Notification, User
from app.services.city_service import pagination
from app.utils.api_response import error_response

ALLOWED_NOTIFICATION_CHANNELS = {"in_app"}
ALLOWED_NOTIFICATION_TYPES = {
    "order_published",
    "new_bid",
    "driver_selected",
    "picked_up",
    "in_transit",
    "delivered",
    "confirmed",
    "cancelled",
    "disputed",
    "rating_received",
    "driver_approved",
    "driver_rejected",
    "driver_blocked",
    "admin_order_status_updated",
    "admin_driver_assigned",
    "admin_order_cancelled",
}


def validate_notification_type(notification_type: str) -> JSONResponse | None:
    if notification_type not in ALLOWED_NOTIFICATION_TYPES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid notification type")
    return None


def validate_notification_channel(channel: str) -> JSONResponse | None:
    if channel not in ALLOWED_NOTIFICATION_CHANNELS:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid notification channel")
    return None


def create_notification(
    db: Session,
    user_id: int,
    notification_type: str,
    title: str,
    body: str,
    order_id: int | None = None,
    channel: str = "in_app",
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> Notification | JSONResponse:
    type_error = validate_notification_type(notification_type)
    if type_error is not None:
        return type_error
    channel_error = validate_notification_channel(channel)
    if channel_error is not None:
        return channel_error
    if db.get(User, user_id) is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "User not found")

    resolved_entity_type = entity_type or ("order" if order_id is not None else None)
    resolved_entity_id = entity_id if entity_id is not None else order_id
    notification = Notification(
        user_id=user_id,
        order_id=order_id,
        type=notification_type,
        title=title,
        message=body,
        channel=channel,
        is_read=False,
        sent_at=datetime.now(timezone.utc) if channel == "in_app" else None,
        entity_type=resolved_entity_type,
        entity_id=resolved_entity_id,
    )
    db.add(notification)
    return notification


def notification_order_id(notification: Notification) -> int | None:
    if notification.order_id is not None:
        return notification.order_id
    if notification.entity_type == "order":
        return notification.entity_id
    return None


def notification_to_dict(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "body": notification.message,
        "order_id": notification_order_id(notification),
        "entity_type": notification.entity_type,
        "entity_id": notification.entity_id,
        "channel": notification.channel,
        "is_read": notification.is_read,
        "sent_at": notification.sent_at,
        "created_at": notification.created_at,
    }


def list_notifications(
    db: Session,
    user: User,
    is_read: bool | None,
    notification_type: str | None,
    order_id: int | None,
    page: int,
    limit: int,
) -> dict[str, Any] | JSONResponse:
    if notification_type is not None:
        type_error = validate_notification_type(notification_type)
        if type_error is not None:
            return type_error

    filters = [Notification.user_id == user.id]
    if is_read is not None:
        filters.append(Notification.is_read == is_read)
    if notification_type is not None:
        filters.append(Notification.type == notification_type)
    if order_id is not None:
        filters.append(or_(Notification.order_id == order_id, (Notification.entity_type == "order") & (Notification.entity_id == order_id)))

    stmt = select(Notification)
    count_stmt = select(func.count(Notification.id))
    for item in filters:
        stmt = stmt.where(item)
        count_stmt = count_stmt.where(item)

    offset, safe_limit = pagination(page, limit)
    total = db.scalar(count_stmt) or 0
    unread_count = db.scalar(
        select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
    ) or 0
    notifications = list(db.scalars(stmt.order_by(Notification.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "items": [notification_to_dict(notification) for notification in notifications],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
        "unread_count": unread_count,
    }


def mark_notification_read(db: Session, user: User, notification_id: int) -> dict[str, Any] | JSONResponse:
    notification = db.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id).with_for_update()
    )
    if notification is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Notification not found")
    notification.is_read = True
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return {"id": notification.id, "is_read": notification.is_read}


def mark_all_notifications_read(db: Session, user: User) -> dict[str, Any]:
    updated_count = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.is_read == False)) or 0  # noqa: E712
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read == False).values(is_read=True))  # noqa: E712
    db.commit()
    return {"updated_count": updated_count}
