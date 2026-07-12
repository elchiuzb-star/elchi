from datetime import date, datetime, time, timezone
from math import ceil
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.services.audit_service import NOISY_AUDIT_ACTIONS, redact_sensitive_value
from app.services.city_service import pagination
from app.utils.api_response import error_response

ALLOWED_ACTOR_ROLES = {"client", "driver", "operator", "admin", "super_admin", "system"}


def parse_datetime_filter(value: str | None) -> datetime | JSONResponse | None:
    if value is None:
        return None
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid filter value")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_created_to(value: str | None) -> datetime | JSONResponse | None:
    if value is None:
        return None
    if len(value) == 10:
        try:
            return datetime.combine(date.fromisoformat(value), time.max, tzinfo=timezone.utc)
        except ValueError:
            return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid filter value")
    return parse_datetime_filter(value)


def audit_details(log: AuditLog) -> dict[str, Any]:
    return log.details or {}


def actor_summary(actor: User | None) -> dict[str, Any] | None:
    if actor is None:
        return None
    return {
        "id": actor.id,
        "role": actor.role,
        "phone": actor.phone,
        "full_name": actor.full_name,
    }


def audit_log_to_dict(log: AuditLog, actor: User | None) -> dict[str, Any]:
    details = audit_details(log)
    return {
        "id": log.id,
        "actor": actor_summary(actor),
        "actor_role": details.get("actor_role") or (actor.role if actor else "system"),
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "action": log.action,
        "reason": details.get("reason"),
        "old_value": redact_sensitive_value(details.get("old_value")),
        "new_value": redact_sensitive_value(details.get("new_value")),
        "ip_address": details.get("ip_address"),
        "user_agent": details.get("user_agent"),
        "created_at": log.created_at,
    }


def validate_pagination(page: int, limit: int) -> JSONResponse | None:
    if page < 1 or limit < 1 or limit > 100:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid pagination parameters")
    return None


def list_audit_logs(
    db: Session,
    actor_id: int | None,
    actor_role: str | None,
    entity_type: str | None,
    entity_id: int | None,
    action: str | None,
    created_from: str | None,
    created_to: str | None,
    search: str | None,
    page: int,
    limit: int,
) -> dict[str, Any] | JSONResponse:
    pagination_error = validate_pagination(page, limit)
    if pagination_error is not None:
        return pagination_error
    if actor_role is not None and actor_role not in ALLOWED_ACTOR_ROLES:
        return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "Invalid filter value")
    parsed_from = parse_datetime_filter(created_from)
    if isinstance(parsed_from, JSONResponse):
        return parsed_from
    parsed_to = parse_created_to(created_to)
    if isinstance(parsed_to, JSONResponse):
        return parsed_to

    filters = []
    if actor_id is not None:
        filters.append(AuditLog.actor_id == actor_id)
    if actor_role is not None:
        filters.append(AuditLog.details["actor_role"].as_string() == actor_role)
    if entity_type is not None:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        filters.append(AuditLog.entity_id == entity_id)
    if action is not None:
        filters.append(AuditLog.action == action)
    else:
        filters.append(AuditLog.action.not_in(NOISY_AUDIT_ACTIONS))
    if parsed_from is not None:
        filters.append(AuditLog.created_at >= parsed_from)
    if parsed_to is not None:
        filters.append(AuditLog.created_at <= parsed_to)
    if search is not None and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                AuditLog.action.ilike(pattern),
                AuditLog.entity_type.ilike(pattern),
                AuditLog.details["reason"].as_string().ilike(pattern),
                User.phone.ilike(pattern),
                User.full_name.ilike(pattern),
            )
        )

    stmt = select(AuditLog, User).outerjoin(User, User.id == AuditLog.actor_id)
    count_stmt = select(func.count(AuditLog.id)).outerjoin(User, User.id == AuditLog.actor_id)
    for item in filters:
        stmt = stmt.where(item)
        count_stmt = count_stmt.where(item)

    offset, safe_limit = pagination(page, limit)
    total = db.scalar(count_stmt) or 0
    rows = list(db.execute(stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(safe_limit)))
    return {
        "items": [audit_log_to_dict(log, actor) for log, actor in rows],
        "pagination": {
            "page": page,
            "limit": safe_limit,
            "total": total,
            "total_pages": ceil(total / safe_limit) if total else 0,
        },
    }


def get_audit_log_detail(db: Session, audit_log_id: int) -> dict[str, Any] | JSONResponse:
    row = db.execute(
        select(AuditLog, User).outerjoin(User, User.id == AuditLog.actor_id).where(AuditLog.id == audit_log_id)
    ).first()
    if row is None:
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Audit log not found")
    log, actor = row
    return audit_log_to_dict(log, actor)
