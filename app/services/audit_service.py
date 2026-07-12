from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import AuditLog, User

SENSITIVE_AUDIT_KEYS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "otp",
    "secret",
    "api_key",
    "authorization",
}

NOISY_AUDIT_ACTIONS = {
    "otp_requested",
    "user_logged_in",
    "token_refreshed",
    "user_logged_out",
}


def redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(sensitive_key in key_text for sensitive_key in SENSITIVE_AUDIT_KEYS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    return value


def write_audit_log(
    db: Session,
    actor: User | None,
    entity_type: str,
    entity_id: int | None,
    action: str,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    actor_role: str | None = None,
    created_at: datetime | None = None,
) -> None:
    if action in NOISY_AUDIT_ACTIONS:
        return

    log = AuditLog(
        actor_id=actor.id if actor is not None else None,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details=jsonable_encoder({
            "actor_role": actor_role or (actor.role if actor is not None else "system"),
            "old_value": redact_sensitive_value(old_value),
            "new_value": redact_sensitive_value(new_value),
            "reason": reason,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }),
    )
    if created_at is not None:
        log.created_at = created_at
    db.add(log)
