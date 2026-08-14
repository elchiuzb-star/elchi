"""Self-service account deletion.

Required by both stores: Google Play requires in-app deletion plus a public web
request route, and Apple requires deletion initiated inside the app.

The approach is anonymise-and-retain rather than hard delete. Orders are shared
business records — a driver's completed job is also the client's history, and
both carry financial obligations — so the rows stay while the identity attached
to them is stripped. What can only belong to the departing user (documents,
sessions, notifications, offered routes) is removed outright.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    DriverDocument,
    DriverProfile,
    DriverRoute,
    Notification,
    Order,
    OtpCode,
    RefreshSession,
    User,
)
from app.services.audit_service import write_audit_log
from app.utils.api_response import error_response

logger = logging.getLogger("elchi.account")

# An order in any of these states is still in flight. Someone mid-delivery
# cannot disappear — the counterparty is relying on them.
IN_FLIGHT_ORDER_STATUSES = {
    "published",
    "bidding",
    "accepted",
    "picked_up",
    "in_transit",
    "delivered",
}


def _tombstone_phone(user_id: int) -> str:
    """Frees the real number for re-registration while keeping the column
    unique and obviously non-personal."""
    return f"deleted-{user_id}"


def _remove_upload(file_url: str) -> None:
    """Delete a stored upload. Best-effort: a missing file must not abort the
    deletion, since the user's request matters more than tidy storage."""
    name = (file_url or "").rsplit("/", 1)[-1]
    if not name:
        return
    try:
        path = Path(settings.upload_dir) / name
        if path.is_file():
            path.unlink()
    except OSError as exc:  # pragma: no cover - filesystem edge cases
        logger.warning("Could not remove upload %s: %s", name, exc)


def blocking_orders(db: Session, user: User) -> int:
    """Count the user's still-active orders, as client or as assigned driver."""
    stmt = select(Order).where(Order.status.in_(IN_FLIGHT_ORDER_STATUSES))
    if user.role == "driver":
        profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
        if profile is None:
            return 0
        stmt = stmt.where(Order.assigned_driver_id == profile.id)
    else:
        stmt = stmt.where(Order.client_id == user.id)
    return len(db.scalars(stmt).all())


def delete_own_account(db: Session, user: User) -> dict[str, Any] | JSONResponse:
    """Anonymise the account and purge everything that is exclusively theirs."""
    if user.role in {"operator", "admin", "super_admin"}:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "STAFF_DELETE_FORBIDDEN",
            "Xodim hisobini o'chirish uchun administratorga murojaat qiling",
        )

    active = blocking_orders(db, user)
    if active:
        return error_response(
            status.HTTP_409_CONFLICT,
            "ACTIVE_ORDERS_EXIST",
            "Tugallanmagan buyurtmalaringiz bor. Ular yakunlangach hisobni o'chirish mumkin",
        )

    try:
        # Sessions first: revoke access before anything else changes.
        db.execute(delete(RefreshSession).where(RefreshSession.user_id == user.id))
        db.execute(delete(Notification).where(Notification.user_id == user.id))
        db.execute(delete(OtpCode).where(OtpCode.phone == user.phone))

        profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
        if profile is not None:
            documents = db.scalars(
                select(DriverDocument).where(DriverDocument.driver_id == profile.id)
            ).all()
            for document in documents:
                _remove_upload(document.file_url)
            db.execute(delete(DriverDocument).where(DriverDocument.driver_id == profile.id))
            # Stop matching this driver to new orders.
            db.execute(delete(DriverRoute).where(DriverRoute.driver_id == profile.id))
            profile.is_available = False
            profile.car_model = None
            profile.car_color = None
            # plate_number is unique and plate_number_normalized is its indexed
            # derivative — clear both so the plate can be registered again.
            profile.plate_number = None
            profile.plate_number_normalized = None
            db.add(profile)

        # The client's own contact details on past orders are theirs to erase;
        # the order rows themselves are retained as business records.
        if user.role == "client":
            for order in db.scalars(select(Order).where(Order.client_id == user.id)).all():
                order.sender_phone = ""
                order.receiver_phone = ""
                order.comment = None
                db.add(order)

        write_audit_log(
            db,
            user,
            "users",
            user.id,
            "account_deleted",
            old_value={"phone": user.phone, "role": user.role},
            new_value={"status": "deleted"},
        )

        user.phone = _tombstone_phone(user.id)
        user.username = None
        user.password_hash = None
        user.full_name = None
        user.is_phone_verified = False
        user.status = "deleted"
        db.add(user)

        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info("Account deleted: user_id=%s role=%s", user.id, user.role)
    return {
        "deleted": True,
        "message": "Hisobingiz o'chirildi. Telefon raqamingiz qayta ro'yxatdan o'tish uchun bo'sh",
    }
