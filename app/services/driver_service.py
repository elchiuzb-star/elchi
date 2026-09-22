from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import City, District, DriverDocument, DriverProfile, DriverRoute, User
from app.schemas.driver import (
    ALLOWED_DRIVER_DOCUMENT_MIME_TYPES,
    ALLOWED_DOCUMENT_TYPES,
    ALLOWED_ROUTE_STATUSES,
    DriverAvailabilityUpdate,
    DriverDocumentCreate,
    DriverProfileUpdate,
    DriverRouteCreate,
    DriverRouteStatusUpdate,
)
from app.services.audit_service import write_audit_log
from app.services.driver_locks import LockMode, lock_driver_user_and_profile
from app.services.city_service import district_ref, pagination, validate_active_city_district_pair
from app.utils.api_response import error_response
from app.utils.file_access import FileReferenceError, resolve_attachment, signed_file_url


def normalize_plate_number(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def normalize_plate_number_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().replace("-", "")
    normalized = "".join(normalized.split()).upper()
    return normalized or None


def get_or_create_driver_profile(db: Session, user: User) -> DriverProfile:
    profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
    if profile is None:
        profile = DriverProfile(
            user_id=user.id,
            full_name=user.full_name,
            verification_status="new",
            is_available=False,
            rating_avg=0,
            total_orders=0,
            completed_orders=0,
            cancelled_orders=0,
            dispute_count=0,
        )
        db.add(profile)
        db.flush()
        write_audit_log(
            db,
            user,
            "driver_profiles",
            profile.id,
            "driver_profile_auto_created",
            new_value={"user_id": user.id, "verification_status": "new", "is_available": False},
        )
        db.commit()
        db.refresh(profile)
    return profile


def profile_to_dict(profile: DriverProfile, user: User) -> dict[str, Any]:
    return {
        "id": profile.id,
        "user": {
            "id": user.id,
            "phone": user.phone,
            "full_name": user.full_name or profile.full_name,
            "status": user.status,
        },
        "full_name": profile.full_name,
        "car_model": profile.car_model,
        "plate_number": profile.plate_number,
        "plate_number_normalized": profile.plate_number_normalized,
        "car_color": profile.car_color,
        "verification_status": profile.verification_status,
        "rating": profile.rating_avg,
        "total_orders": profile.total_orders,
        "completed_orders": profile.completed_orders,
        "cancelled_orders": profile.cancelled_orders,
        "dispute_count": profile.dispute_count,
        "is_available": profile.is_available,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def profile_update_dict(profile: DriverProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "full_name": profile.full_name,
        "car_model": profile.car_model,
        "plate_number": profile.plate_number,
        "plate_number_normalized": profile.plate_number_normalized,
        "car_color": profile.car_color,
        "verification_status": profile.verification_status,
        "is_available": profile.is_available,
    }


def lock_driver_self_service(
    db: Session,
    user: User,
    profile: DriverProfile,
    *,
    user_mode: LockMode = "key_share",
    profile_mode: LockMode = "no_key_update",
) -> JSONResponse | None:
    """Lock users -> driver_profiles before any other row a self-service write touches.

    Account deletion locks users FOR UPDATE and then deletes documents/routes; by
    taking the users lock first, this transaction waits for deletion while holding
    nothing (no deadlock) and then sees the deleted status. See driver_locks.py.
    """
    locked_profile, locked_user = lock_driver_user_and_profile(db, profile.id, user_mode=user_mode, profile_mode=profile_mode)
    if locked_profile is None or locked_user is None or locked_user.status != "active":
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "User account is not active")
    return None


def update_driver_profile(
    db: Session,
    user: User,
    profile: DriverProfile,
    payload: DriverProfileUpdate,
) -> DriverProfile | JSONResponse:
    update_data = payload.model_dump(exclude_unset=True)
    lock_error = lock_driver_self_service(
        db,
        user,
        profile,
        user_mode="no_key_update" if "full_name" in update_data else "key_share",
        # N-A: a plate change updates a unique column -> FOR UPDATE up front.
        profile_mode="update" if "plate_number" in update_data else "no_key_update",
    )
    if lock_error is not None:
        return lock_error

    # Q94: vehicle details are entered **once**. Each field locks as soon as it holds a value - not only after
    # approval - because the car on the road is what the client is told to look for, and a self-service edit
    # between approval runs lets a driver swap it without anyone seeing. The name stays editable, and staff
    # change a locked field through PATCH /api/v1/admin/drivers/{driver_id}/vehicle.
    locked_fields = []
    if (
        "car_model" in update_data
        and profile.car_model
        and (update_data.get("car_model") or None) != (profile.car_model or None)
    ):
        locked_fields.append("car_model")
    if (
        "car_color" in update_data
        and profile.car_color
        and (update_data.get("car_color") or None) != (profile.car_color or None)
    ):
        locked_fields.append("car_color")
    if (
        "plate_number" in update_data
        and profile.plate_number_normalized
        and normalize_plate_number_key(update_data.get("plate_number")) != profile.plate_number_normalized
    ):
        locked_fields.append("plate_number")
    if locked_fields:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "DRIVER_VEHICLE_LOCKED",
            "Vehicle details are entered once. Contact an admin or operator to change them.",
            {"locked_fields": locked_fields},
        )

    if "plate_number" in update_data and update_data["plate_number"] is not None:
        update_data["plate_number"] = normalize_plate_number(update_data["plate_number"])
        normalized_plate = normalize_plate_number_key(update_data["plate_number"])
        if normalized_plate is None:
            return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "plate_number cannot be empty")
        existing = db.scalar(
            select(DriverProfile).where(
                DriverProfile.plate_number_normalized == normalized_plate,
                DriverProfile.id != profile.id,
            )
        )
        if existing is None:
            for candidate in db.scalars(select(DriverProfile).where(DriverProfile.id != profile.id)):
                if normalize_plate_number_key(candidate.plate_number) == normalized_plate:
                    existing = candidate
                    break
        if existing is not None:
            return error_response(status.HTTP_409_CONFLICT, "PLATE_NUMBER_ALREADY_EXISTS", "Plate number already exists")
        update_data["plate_number_normalized"] = normalized_plate

    old_value = profile_update_dict(profile)
    if "full_name" in update_data:
        user.full_name = update_data["full_name"]
        profile.full_name = update_data["full_name"]
    for field in ("car_model", "plate_number", "plate_number_normalized", "car_color"):
        if field in update_data:
            setattr(profile, field, update_data[field])

    db.add_all([user, profile])
    db.flush()
    write_audit_log(
        db,
        user,
        "driver_profiles",
        profile.id,
        "driver_profile_updated",
        old_value=old_value,
        new_value=profile_update_dict(profile),
    )
    db.commit()
    db.refresh(profile)
    return profile


def submit_driver_document(
    db: Session,
    user: User,
    profile: DriverProfile,
    payload: DriverDocumentCreate,
) -> DriverDocument | JSONResponse:
    if payload.document_type not in ALLOWED_DOCUMENT_TYPES:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "DRIVER_DOCUMENT_INVALID_TYPE",
            "Invalid document_type",
            {"allowed_document_types": sorted(ALLOWED_DOCUMENT_TYPES)},
        )
    if payload.mime_type is not None and payload.mime_type not in ALLOWED_DRIVER_DOCUMENT_MIME_TYPES:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "DRIVER_DOCUMENT_INVALID_TYPE",
            "Invalid driver document file type",
            {"allowed_mime_types": sorted(ALLOWED_DRIVER_DOCUMENT_MIME_TYPES)},
        )
    if payload.size_bytes is not None and payload.size_bytes > settings.max_document_upload_mb * 1024 * 1024:
        return error_response(status.HTTP_400_BAD_REQUEST, "DRIVER_DOCUMENT_TOO_LARGE", "Driver document is too large")

    lock_error = lock_driver_self_service(db, user, profile)
    if lock_error is not None:
        return lock_error
    old_status = profile.verification_status
    document = db.scalar(
        select(DriverDocument).where(
            DriverDocument.driver_id == profile.id,
            DriverDocument.document_type == payload.document_type,
        )
    )
    try:
        stored_file_url = resolve_attachment(
            payload.file_url,
            user_id=user.id,
            expected_upload_type=payload.document_type,
            current_stored=document.file_url if document is not None else None,
        )
    except FileReferenceError:
        stored_file_url = None
    if stored_file_url is None:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "Invalid file reference",
            {"field": "file_url"},
        )
    if document is None:
        document = DriverDocument(driver_id=profile.id, document_type=payload.document_type)
    document.file_url = stored_file_url
    document.status = "pending"
    document.rejection_reason = None
    document.reviewed_by = None
    document.reviewed_at = None
    db.add(document)
    if profile.verification_status in {"new", "rejected"}:
        profile.verification_status = "pending"
        db.add(profile)
    db.flush()
    write_audit_log(
        db,
        user,
        "driver_documents",
        document.id,
        "driver_document_uploaded",
        old_value={"verification_status": old_status},
        new_value=document_to_dict(document, sign_urls=False),
    )
    if old_status != profile.verification_status and profile.verification_status == "pending":
        write_audit_log(
            db,
            user,
            "driver_profiles",
            profile.id,
            "driver_submitted_for_review",
            old_value={"verification_status": old_status},
            new_value={"verification_status": profile.verification_status},
        )
    db.commit()
    db.refresh(document)
    return document


def list_driver_documents(db: Session, profile: DriverProfile) -> list[DriverDocument]:
    """Documents the driver has uploaded, so the app can show per-document state."""
    return list(
        db.scalars(
            select(DriverDocument)
            .where(DriverDocument.driver_id == profile.id)
            .order_by(DriverDocument.id.asc())
        )
    )


def document_to_dict(document: DriverDocument, *, sign_urls: bool = True) -> dict[str, Any]:
    # sign_urls=False for audit logs: they keep the stored value, never a signature.
    return {
        "document_id": document.id,
        "driver_id": document.driver_id,
        "document_type": document.document_type,
        "file_url": signed_file_url(document.file_url) if sign_urls else document.file_url,
        "status": document.status,
        "rejection_reason": document.rejection_reason,
    }


def update_availability(
    db: Session,
    user: User,
    profile: DriverProfile,
    payload: DriverAvailabilityUpdate,
) -> DriverProfile | JSONResponse:
    lock_error = lock_driver_self_service(db, user, profile)
    if lock_error is not None:
        return lock_error
    if payload.is_available:
        if user.status == "blocked":
            return error_response(status.HTTP_403_FORBIDDEN, "DRIVER_BLOCKED", "Driver is blocked")
        if profile.verification_status != "approved":
            return error_response(
                status.HTTP_400_BAD_REQUEST,
                "DRIVER_NOT_APPROVED",
                "Driver must be approved before becoming available",
            )

    old_value = {"is_available": profile.is_available}
    profile.is_available = payload.is_available
    db.add(profile)
    db.flush()
    write_audit_log(
        db,
        user,
        "driver_profiles",
        profile.id,
        "driver_availability_changed",
        old_value=old_value,
        new_value={"is_available": profile.is_available},
    )
    db.commit()
    db.refresh(profile)
    return profile


def city_summary(city: City) -> dict[str, Any]:
    return {"id": city.id, "name_uz": city.name_uz}


def district_summary(district: District | None) -> dict[str, Any] | None:
    return district_ref(district)


def route_to_dict(route: DriverRoute, from_city: City, to_city: City, from_district: District | None = None, to_district: District | None = None) -> dict[str, Any]:
    return {
        "id": route.id,
        "from_city": city_summary(from_city),
        "to_city": city_summary(to_city),
        "from_district": district_summary(from_district),
        "to_district": district_summary(to_district),
        "from_district_id": route.from_district_id,
        "to_district_id": route.to_district_id,
        "status": route.status,
        "created_at": route.created_at,
    }


def validate_active_city_pair(db: Session, from_city_id: int, to_city_id: int) -> tuple[City, City] | JSONResponse:
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


def create_driver_route(
    db: Session,
    user: User,
    profile: DriverProfile,
    payload: DriverRouteCreate,
) -> DriverRoute | JSONResponse:
    lock_error = lock_driver_self_service(db, user, profile)
    if lock_error is not None:
        return lock_error
    if profile.verification_status != "approved":
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "DRIVER_NOT_APPROVED",
            "Only approved drivers can create routes",
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

    existing = db.scalar(
        select(DriverRoute).where(
            DriverRoute.driver_id == profile.id,
            DriverRoute.from_city_id == payload.from_city_id,
            DriverRoute.to_city_id == payload.to_city_id,
            DriverRoute.from_district_id.is_(payload.from_district_id) if payload.from_district_id is None else DriverRoute.from_district_id == payload.from_district_id,
            DriverRoute.to_district_id.is_(payload.to_district_id) if payload.to_district_id is None else DriverRoute.to_district_id == payload.to_district_id,
            DriverRoute.status != "unavailable",
        )
    )
    if existing is not None:
        return error_response(status.HTTP_409_CONFLICT, "ROUTE_ALREADY_EXISTS", "Active route already exists")

    route = DriverRoute(
        driver_id=profile.id,
        from_city_id=payload.from_city_id,
        to_city_id=payload.to_city_id,
        from_district_id=payload.from_district_id,
        to_district_id=payload.to_district_id,
        status="available",
    )
    db.add(route)
    db.flush()
    from_city, to_city, from_district, to_district = route_parts
    write_audit_log(
        db,
        user,
        "driver_routes",
        route.id,
        "driver_route_created",
        new_value=route_to_dict(route, from_city, to_city, from_district, to_district),
    )
    db.commit()
    db.refresh(route)
    return route


def list_driver_routes(
    db: Session,
    profile: DriverProfile,
    route_status: str | None,
    page: int,
    limit: int,
) -> list[DriverRoute] | JSONResponse:
    if route_status is not None and route_status not in ALLOWED_ROUTE_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid route status")
    stmt = select(DriverRoute).where(DriverRoute.driver_id == profile.id)
    if route_status is not None:
        stmt = stmt.where(DriverRoute.status == route_status)
    offset, safe_limit = pagination(page, limit)
    return list(db.scalars(stmt.order_by(DriverRoute.created_at.desc()).offset(offset).limit(safe_limit)))


def get_owned_route(db: Session, profile: DriverProfile, route_id: int) -> DriverRoute | JSONResponse:
    route = db.get(DriverRoute, route_id)
    if route is None or route.driver_id != profile.id:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Route not found")
    return route


def update_route_status(
    db: Session,
    user: User,
    profile: DriverProfile,
    route_id: int,
    payload: DriverRouteStatusUpdate,
) -> DriverRoute | JSONResponse:
    if payload.status not in ALLOWED_ROUTE_STATUSES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid route status")
    lock_error = lock_driver_self_service(db, user, profile)
    if lock_error is not None:
        return lock_error
    route = get_owned_route(db, profile, route_id)
    if isinstance(route, JSONResponse):
        return route
    if payload.status == "available":
        if user.status == "blocked":
            return error_response(status.HTTP_403_FORBIDDEN, "DRIVER_BLOCKED", "Driver is blocked")
        if profile.verification_status != "approved":
            return error_response(
                status.HTTP_400_BAD_REQUEST,
                "DRIVER_NOT_APPROVED",
                "Only approved drivers can set route available",
            )
    old_value = {"status": route.status}
    route.status = payload.status
    db.add(route)
    db.flush()
    write_audit_log(
        db,
        user,
        "driver_routes",
        route.id,
        "driver_route_status_updated",
        old_value=old_value,
        new_value={"status": route.status},
    )
    db.commit()
    db.refresh(route)
    return route


def update_driver_route(
    db: Session,
    user: User,
    profile: DriverProfile,
    route_id: int,
    payload: DriverRouteCreate,
) -> DriverRoute | JSONResponse:
    lock_error = lock_driver_self_service(db, user, profile)
    if lock_error is not None:
        return lock_error
    route = get_owned_route(db, profile, route_id)
    if isinstance(route, JSONResponse):
        return route
    if route.status == "unavailable":
        return error_response(status.HTTP_400_BAD_REQUEST, "ROUTE_UNAVAILABLE", "Unavailable route cannot be edited")

    route_parts = validate_active_city_district_pair(
        db,
        payload.from_city_id,
        payload.to_city_id,
        payload.from_district_id,
        payload.to_district_id,
    )
    if isinstance(route_parts, JSONResponse):
        return route_parts

    existing = db.scalar(
        select(DriverRoute).where(
            DriverRoute.driver_id == profile.id,
            DriverRoute.id != route.id,
            DriverRoute.from_city_id == payload.from_city_id,
            DriverRoute.to_city_id == payload.to_city_id,
            DriverRoute.from_district_id.is_(payload.from_district_id) if payload.from_district_id is None else DriverRoute.from_district_id == payload.from_district_id,
            DriverRoute.to_district_id.is_(payload.to_district_id) if payload.to_district_id is None else DriverRoute.to_district_id == payload.to_district_id,
            DriverRoute.status != "unavailable",
        )
    )
    if existing is not None:
        return error_response(status.HTTP_409_CONFLICT, "ROUTE_ALREADY_EXISTS", "Active route already exists")

    old_value = {
        "from_city_id": route.from_city_id,
        "to_city_id": route.to_city_id,
        "from_district_id": route.from_district_id,
        "to_district_id": route.to_district_id,
        "status": route.status,
    }
    route.from_city_id = payload.from_city_id
    route.to_city_id = payload.to_city_id
    route.from_district_id = payload.from_district_id
    route.to_district_id = payload.to_district_id
    db.add(route)
    db.flush()
    from_city, to_city, from_district, to_district = route_parts
    write_audit_log(
        db,
        user,
        "driver_routes",
        route.id,
        "driver_route_updated",
        old_value=old_value,
        new_value=route_to_dict(route, from_city, to_city, from_district, to_district),
    )
    db.commit()
    db.refresh(route)
    return route


def disable_driver_route(db: Session, user: User, profile: DriverProfile, route_id: int) -> int | JSONResponse:
    """Permanently remove a driver route (hard delete).

    Drivers can keep routes and toggle them available/unavailable via
    ``update_route_status``; this is the explicit "remove route" action.
    """
    lock_error = lock_driver_self_service(db, user, profile)
    if lock_error is not None:
        return lock_error
    route = get_owned_route(db, profile, route_id)
    if isinstance(route, JSONResponse):
        return route
    deleted_route_id = route.id
    old_value = {"status": route.status}
    write_audit_log(
        db,
        user,
        "driver_routes",
        deleted_route_id,
        "driver_route_deleted",
        old_value=old_value,
        new_value={"status": "deleted"},
    )
    db.delete(route)
    db.commit()
    return deleted_route_id
