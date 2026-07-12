from datetime import datetime, timezone
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import AuditLog, City, DriverDocument, DriverProfile, DriverRoute, Order, RefreshSession, User
from app.schemas.admin_driver import (
    AdminDriverApprove,
    AdminDriverBlock,
    AdminDriverReject,
    AdminDriverVehicleUpdate,
)
from app.services.audit_service import write_audit_log
from app.services.city_service import pagination
from app.services.driver_service import normalize_plate_number, normalize_plate_number_key
from app.services.notification_service import create_notification
from app.utils.api_response import error_response

ADMIN_DRIVER_VIEW_ROLES = {"operator", "admin", "super_admin"}
ADMIN_DRIVER_MUTATION_ROLES = {"admin", "super_admin"}
VERIFICATION_STATUSES = {"new", "pending", "approved", "rejected", "blocked"}
REQUIRED_DOCUMENT_TYPES = ("passport", "selfie", "license", "car_document", "car_photo")


def require_reason(reason: str | None) -> str | JSONResponse:
    if reason is None or not reason.strip():
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Reason is required")
    return reason.strip()


def user_list_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "phone": user.phone,
        "full_name": user.full_name,
        "status": user.status,
    }


def user_detail_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "phone": user.phone,
        "full_name": user.full_name,
        "status": user.status,
        "is_phone_verified": user.is_phone_verified,
        "created_at": user.created_at,
    }


def city_summary(city: City | None) -> dict[str, Any] | None:
    if city is None:
        return None
    return {"id": city.id, "name_uz": city.name_uz}


def driver_list_item_to_dict(driver: DriverProfile) -> dict[str, Any]:
    return {
        "id": driver.id,
        "user": user_list_to_dict(driver.user),
        "car_model": driver.car_model,
        "plate_number": driver.plate_number,
        "plate_number_normalized": driver.plate_number_normalized,
        "car_color": driver.car_color,
        "verification_status": driver.verification_status,
        "is_available": driver.is_available,
        "rating": driver.rating_avg,
        "total_orders": driver.total_orders,
        "completed_orders": driver.completed_orders,
        "cancelled_orders": driver.cancelled_orders,
        "dispute_count": driver.dispute_count,
        "created_at": driver.created_at,
        "updated_at": driver.updated_at,
    }


def document_to_dict(document: DriverDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "document_type": document.document_type,
        "file_url": document.file_url,
        "status": document.status,
        "rejection_reason": document.rejection_reason,
        "reviewed_by": document.reviewed_by,
        "reviewed_at": document.reviewed_at,
        "created_at": document.created_at,
    }


def route_to_dict(route: DriverRoute, db: Session) -> dict[str, Any]:
    return {
        "id": route.id,
        "from_city": city_summary(db.get(City, route.from_city_id)),
        "to_city": city_summary(db.get(City, route.to_city_id)),
        "status": route.status,
    }


def driver_detail_to_dict(driver: DriverProfile, db: Session) -> dict[str, Any]:
    documents = sorted(driver.documents, key=lambda item: item.created_at, reverse=True)
    routes = sorted(driver.routes, key=lambda item: item.created_at, reverse=True)
    return {
        "id": driver.id,
        "user": user_detail_to_dict(driver.user),
        "car_model": driver.car_model,
        "plate_number": driver.plate_number,
        "plate_number_normalized": driver.plate_number_normalized,
        "car_color": driver.car_color,
        "verification_status": driver.verification_status,
        "is_available": driver.is_available,
        "rating": driver.rating_avg,
        "total_orders": driver.total_orders,
        "completed_orders": driver.completed_orders,
        "cancelled_orders": driver.cancelled_orders,
        "dispute_count": driver.dispute_count,
        "documents": [document_to_dict(document) for document in documents],
        "routes": [route_to_dict(route, db) for route in routes],
        "created_at": driver.created_at,
        "updated_at": driver.updated_at,
    }


def list_admin_drivers(
    db: Session,
    verification_status: str | None,
    is_available: bool | None,
    search: str | None,
    phone: str | None,
    plate_number: str | None,
    page: int,
    limit: int,
) -> dict[str, Any] | JSONResponse:
    if verification_status is not None and verification_status not in VERIFICATION_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid verification_status")

    filters = []
    if verification_status is not None:
        filters.append(DriverProfile.verification_status == verification_status)
    if is_available is not None:
        filters.append(DriverProfile.is_available == is_available)
    if phone is not None:
        filters.append(User.phone.contains(phone))
    if plate_number is not None:
        filters.append(DriverProfile.plate_number.contains(plate_number))
    if search is not None and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                User.full_name.ilike(pattern),
                User.phone.ilike(pattern),
                DriverProfile.plate_number.ilike(pattern),
                DriverProfile.car_model.ilike(pattern),
            )
        )

    stmt = select(DriverProfile).join(User, User.id == DriverProfile.user_id).options(joinedload(DriverProfile.user))
    count_stmt = select(func.count(DriverProfile.id)).join(User, User.id == DriverProfile.user_id)
    for item in filters:
        stmt = stmt.where(item)
        count_stmt = count_stmt.where(item)

    offset, safe_limit = pagination(page, limit)
    total = db.scalar(count_stmt) or 0
    drivers = list(db.scalars(stmt.order_by(DriverProfile.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "items": [driver_list_item_to_dict(driver) for driver in drivers],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
    }


def get_admin_driver_detail(db: Session, driver_id: int) -> dict[str, Any] | JSONResponse:
    driver = db.scalar(
        select(DriverProfile)
        .where(DriverProfile.id == driver_id)
        .options(joinedload(DriverProfile.user), selectinload(DriverProfile.documents), selectinload(DriverProfile.routes))
    )
    if driver is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Driver not found")
    return driver_detail_to_dict(driver, db)


def get_driver_for_update(db: Session, driver_id: int) -> DriverProfile | JSONResponse:
    driver = db.scalar(
        select(DriverProfile)
        .where(DriverProfile.id == driver_id)
        .with_for_update()
    )
    if driver is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Driver not found")
    db.refresh(driver, attribute_names=["user", "documents", "routes"])
    return driver


def add_driver_notification(db: Session, driver: DriverProfile, notification_type: str, title: str, message: str) -> None:
    create_notification(db, driver.user_id, notification_type, title, message, entity_type="driver", entity_id=driver.id)


def missing_required_documents(driver: DriverProfile) -> list[str]:
    submitted_types = {document.document_type for document in driver.documents if document.document_type in REQUIRED_DOCUMENT_TYPES}
    return [document_type for document_type in REQUIRED_DOCUMENT_TYPES if document_type not in submitted_types]


def mark_documents_reviewed(db: Session, actor: User, driver: DriverProfile, document_status: str, reason: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    for document in driver.documents:
        if document.document_type not in REQUIRED_DOCUMENT_TYPES or document.status != "pending":
            continue
        old_value = {
            "status": document.status,
            "rejection_reason": document.rejection_reason,
            "reviewed_by": document.reviewed_by,
            "reviewed_at": document.reviewed_at,
        }
        document.status = document_status
        document.reviewed_by = actor.id
        document.reviewed_at = now
        document.rejection_reason = reason if document_status == "rejected" else None
        db.add(document)
        write_audit_log(
            db,
            actor,
            "driver_documents",
            document.id,
            "driver_document_status_updated",
            old_value=old_value,
            new_value={
                "status": document.status,
                "rejection_reason": document.rejection_reason,
                "reviewed_by": document.reviewed_by,
                "reviewed_at": document.reviewed_at,
            },
            reason=reason,
        )


def approve_driver(db: Session, actor: User, driver_id: int, payload: AdminDriverApprove) -> dict[str, Any] | JSONResponse:
    driver = get_driver_for_update(db, driver_id)
    if isinstance(driver, JSONResponse):
        return driver
    if driver.verification_status == "blocked":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_INVALID_STATUS", "Blocked driver cannot be approved")
    if driver.user.status != "active":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_INVALID_STATUS", "Driver user must be active")
    missing_documents = missing_required_documents(driver)
    if missing_documents:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "DRIVER_DOCUMENTS_INCOMPLETE",
            "Required driver documents are missing",
            {"missing": missing_documents},
        )

    old_status = driver.verification_status
    old_available = driver.is_available
    driver.verification_status = "approved"
    driver.is_available = False
    db.add(driver)
    mark_documents_reviewed(db, actor, driver, "approved")
    db.flush()
    write_audit_log(
        db,
        actor,
        "drivers",
        driver.id,
        "driver_approved",
        old_value={"verification_status": old_status, "is_available": old_available},
        new_value={"verification_status": driver.verification_status, "is_available": driver.is_available},
        reason=payload.comment,
    )
    add_driver_notification(db, driver, "driver_approved", "Tasdiqlandingiz", "Haydovchi profilingiz tasdiqlandi")
    db.commit()
    db.refresh(driver)
    return {"driver_id": driver.id, "verification_status": driver.verification_status, "is_available": driver.is_available}


def update_driver_vehicle(
    db: Session,
    actor: User,
    driver_id: int,
    payload: AdminDriverVehicleUpdate,
) -> dict[str, Any] | JSONResponse:
    driver = get_driver_for_update(db, driver_id)
    if isinstance(driver, JSONResponse):
        return driver

    update_data = payload.model_dump(exclude_unset=True)

    if "plate_number" in update_data and update_data["plate_number"] is not None:
        update_data["plate_number"] = normalize_plate_number(update_data["plate_number"])
        normalized_plate = normalize_plate_number_key(update_data["plate_number"])
        if normalized_plate is None:
            return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "plate_number cannot be empty")
        existing = db.scalar(
            select(DriverProfile).where(
                DriverProfile.plate_number_normalized == normalized_plate,
                DriverProfile.id != driver.id,
            )
        )
        if existing is None:
            for candidate in db.scalars(select(DriverProfile).where(DriverProfile.id != driver.id)):
                if normalize_plate_number_key(candidate.plate_number) == normalized_plate:
                    existing = candidate
                    break
        if existing is not None:
            return error_response(status.HTTP_409_CONFLICT, "PLATE_NUMBER_ALREADY_EXISTS", "Plate number already exists")
        update_data["plate_number_normalized"] = normalized_plate

    old_value = {
        "full_name": driver.full_name,
        "car_model": driver.car_model,
        "plate_number": driver.plate_number,
        "car_color": driver.car_color,
    }
    if "full_name" in update_data:
        driver.user.full_name = update_data["full_name"]
        driver.full_name = update_data["full_name"]
    for field in ("car_model", "plate_number", "plate_number_normalized", "car_color"):
        if field in update_data:
            setattr(driver, field, update_data[field])

    db.add_all([driver.user, driver])
    db.flush()
    write_audit_log(
        db,
        actor,
        "driver_profiles",
        driver.id,
        "driver_vehicle_updated_by_admin",
        old_value=old_value,
        new_value={
            "full_name": driver.full_name,
            "car_model": driver.car_model,
            "plate_number": driver.plate_number,
            "car_color": driver.car_color,
        },
    )
    add_driver_notification(
        db,
        driver,
        "driver_vehicle_updated",
        "Avtomobil ma'lumotlari yangilandi",
        "Avtomobil ma'lumotlaringiz operator tomonidan yangilandi",
    )
    db.commit()
    return get_admin_driver_detail(db, driver.id)


def reject_driver(db: Session, actor: User, driver_id: int, payload: AdminDriverReject) -> dict[str, Any] | JSONResponse:
    reason = require_reason(payload.reason)
    if isinstance(reason, JSONResponse):
        return reason
    driver = get_driver_for_update(db, driver_id)
    if isinstance(driver, JSONResponse):
        return driver
    if driver.verification_status == "blocked":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_INVALID_STATUS", "Blocked driver cannot be rejected")
    if driver.verification_status == "approved":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_INVALID_STATUS", "Approved driver should be blocked instead")

    old_status = driver.verification_status
    old_available = driver.is_available
    driver.verification_status = "rejected"
    driver.is_available = False
    db.add(driver)
    mark_documents_reviewed(db, actor, driver, "rejected", reason)
    db.flush()
    write_audit_log(
        db,
        actor,
        "drivers",
        driver.id,
        "driver_rejected",
        old_value={"verification_status": old_status, "is_available": old_available},
        new_value={"verification_status": driver.verification_status, "is_available": driver.is_available},
        reason=reason,
    )
    add_driver_notification(db, driver, "driver_rejected", "Verifikatsiya rad etildi", f"Sabab: {reason}")
    db.commit()
    db.refresh(driver)
    return {
        "driver_id": driver.id,
        "verification_status": driver.verification_status,
        "is_available": driver.is_available,
        "reason": reason,
    }


def block_driver(db: Session, actor: User, driver_id: int, payload: AdminDriverBlock) -> dict[str, Any] | JSONResponse:
    reason = require_reason(payload.reason)
    if isinstance(reason, JSONResponse):
        return reason
    driver = get_driver_for_update(db, driver_id)
    if isinstance(driver, JSONResponse):
        return driver
    if driver.verification_status == "blocked":
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_ALREADY_BLOCKED", "Driver is already blocked")

    old_status = driver.verification_status
    old_available = driver.is_available
    old_user_status = driver.user.status
    driver.verification_status = "blocked"
    driver.is_available = False
    driver.user.status = "blocked"
    db.add_all([driver, driver.user])
    disabled_count = 0
    for route in driver.routes:
        if route.status != "unavailable":
            route.status = "unavailable"
            disabled_count += 1
            db.add(route)
    now = datetime.now(timezone.utc)
    revoked_session_count = 0
    for session in db.scalars(
        select(RefreshSession).where(
            RefreshSession.user_id == driver.user_id,
            RefreshSession.is_revoked == False,  # noqa: E712
        )
    ):
        session.is_revoked = True
        session.revoked_at = now
        revoked_session_count += 1
        db.add(session)
    active_orders_count = db.scalar(
        select(func.count(Order.id)).where(
            Order.assigned_driver_id == driver.id,
            Order.status.in_(["accepted", "picked_up", "in_transit", "delivered", "disputed"]),
        )
    ) or 0
    db.flush()
    write_audit_log(
        db,
        actor,
        "drivers",
        driver.id,
        "driver_blocked",
        old_value={"verification_status": old_status, "user_status": old_user_status, "is_available": old_available},
        new_value={
            "verification_status": driver.verification_status,
            "user_status": driver.user.status,
            "is_available": driver.is_available,
        },
        reason=reason,
    )
    if disabled_count:
        write_audit_log(
            db,
            actor,
            "driver_routes",
            driver.id,
            "driver_routes_disabled_after_block",
            old_value={"disabled_count": 0},
            new_value={"disabled_count": disabled_count},
            reason=reason,
        )
    add_driver_notification(db, driver, "driver_blocked", "Profil bloklandi", f"Sabab: {reason}")
    db.commit()
    db.refresh(driver)
    return {
        "driver_id": driver.id,
        "verification_status": driver.verification_status,
        "user_status": driver.user.status,
        "is_available": driver.is_available,
        "reason": reason,
        "disabled_routes_count": disabled_count,
        "revoked_refresh_sessions_count": revoked_session_count,
        "active_orders_count": active_orders_count,
        "warning": "Driver has active orders. Admin must resolve them manually." if active_orders_count else None,
    }
