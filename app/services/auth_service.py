import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
from secrets import randbelow
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.models import AuditLog, ClientProfile, DriverProfile, OtpCode, RefreshSession, User
from app.schemas.auth import AdminUserCreate
from app.services import sms_service
from app.services.audit_service import write_audit_log
from app.utils.api_response import error_response

# Compared against when a username is not found, so a miss costs roughly the
# same as a real password check. The plaintext is irrelevant and unused.
_TIMING_DUMMY_HASH = hash_password("elchi-timing-equalizer-not-a-credential")

logger = logging.getLogger("elchi.auth")

PUBLIC_REGISTRATION_ROLES = {"client", "driver"}
STAFF_ROLES = {"operator", "admin", "super_admin"}
SUPER_ADMIN_CREATABLE_ROLES = {"operator", "admin"}
ALL_ROLES = PUBLIC_REGISTRATION_ROLES | STAFF_ROLES
ACTIVE_STATUSES = {"active"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_development() -> bool:
    return settings.debug and settings.environment.lower() in {"development", "local", "dev", "test"}


def normalize_phone(phone: str) -> str | JSONResponse:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 9:
        digits = f"998{digits}"
    if len(digits) == 12 and digits.startswith("998"):
        normalized = f"+{digits}"
        if len(normalized) == 13:
            return normalized
    return error_response(status.HTTP_400_BAD_REQUEST, "INVALID_PHONE", "Invalid Uzbekistan phone number")


def validate_role(role: str) -> str | JSONResponse:
    if role not in ALL_ROLES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ROLE_NOT_ALLOWED", "Role is not allowed")
    return role


def check_active_user(user: User) -> JSONResponse | None:
    if user.status == "blocked":
        return error_response(status.HTTP_403_FORBIDDEN, "USER_BLOCKED", "User account is blocked")
    if user.status == "inactive":
        return error_response(status.HTTP_403_FORBIDDEN, "USER_INACTIVE", "User account is inactive")
    if user.status == "deleted":
        return error_response(status.HTTP_403_FORBIDDEN, "USER_INACTIVE", "User account is deleted")
    if user.status not in ACTIVE_STATUSES:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "User account is not active")
    return None


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "phone": user.phone,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
        "is_phone_verified": user.is_phone_verified,
    }


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def otp_hash(otp: str) -> str:
    return sha256(f"{settings.secret_key}:{otp}".encode("utf-8")).hexdigest()


def generate_otp() -> str:
    # A random code whenever SMS is actually being sent. Only pure local dev
    # with SMS off falls back to the fixed mock (keeps the emulator flow simple).
    if is_development() and not settings.sms_enabled:
        return settings.dev_mock_otp
    upper = 10**settings.otp_length
    lower = 10 ** (settings.otp_length - 1)
    return str(randbelow(upper - lower) + lower)


def otp_message(code: str) -> str:
    """The SMS body — the real code interpolated into the active approved
    template. Eskiz approved '...kodi: %d', so a variable code passes moderation."""
    template = settings.sms_test_message if settings.sms_test_mode else settings.otp_message_template
    return template.format(code=code)


def is_review_login_phone(phone: str) -> bool:
    """Whether `phone` is one of the store-reviewer accounts."""
    if not (settings.review_login_phones and settings.review_login_otp):
        return False
    for raw in settings.review_login_phones.split(","):
        candidate = normalize_phone(raw.strip())
        if isinstance(candidate, str) and candidate == phone:
            return True
    return False


def is_review_login_otp(phone: str, value: str) -> bool:
    """Fixed code accepted only for the allowlisted reviewer phones.

    Unlike is_dev_mock_otp this works in production — that is the whole point —
    so it is scoped to an explicit list and compared in constant time.
    """
    if not is_review_login_phone(phone):
        return False
    return compare_digest(value, settings.review_login_otp or "")


def is_dev_mock_otp(value: str) -> bool:
    # Local-dev convenience backdoor; disabled entirely outside development.
    if not is_development():
        return False
    return value == settings.dev_mock_otp or value == settings.mock_otp_code


def create_profile_if_needed(db: Session, user: User) -> None:
    if user.role == "client":
        profile = db.scalar(select(ClientProfile).where(ClientProfile.user_id == user.id))
        if profile is None:
            db.add(ClientProfile(user_id=user.id))
    elif user.role == "driver":
        profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
        if profile is None:
            profile = DriverProfile(
                user_id=user.id,
                verification_status="new",
                is_available=False,
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


def count_recent_otps(db: Session, phone: str, role: str, now: datetime) -> int:
    window_start = now - timedelta(minutes=settings.otp_send_window_minutes)
    return db.scalar(select(func.count(OtpCode.id)).where(OtpCode.phone == phone, OtpCode.role == role, OtpCode.created_at >= window_start)) or 0


def _is_local_ip(ip: str | None) -> bool:
    """Loopback / private / emulator IPs — never a real public attacker source.
    Per-IP limits skip these so local + emulator testing isn't throttled; in
    production the proxy supplies real public client IPs via X-Forwarded-For."""
    if not ip:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_loopback or addr.is_private or addr.is_link_local


def count_recent_otps_by_ip(db: Session, ip: str, now: datetime) -> int:
    window_start = now - timedelta(minutes=settings.otp_ip_window_minutes)
    return db.scalar(select(func.count(OtpCode.id)).where(OtpCode.ip_address == ip, OtpCode.created_at >= window_start)) or 0


def count_otps_since(db: Session, since: datetime) -> int:
    return db.scalar(select(func.count(OtpCode.id)).where(OtpCode.created_at >= since)) or 0


def request_otp(db: Session, phone: str, role: str, ip_address: str | None = None) -> dict[str, Any] | JSONResponse:
    normalized_phone = normalize_phone(phone)
    if isinstance(normalized_phone, JSONResponse):
        return normalized_phone
    valid_role = validate_role(role)
    if isinstance(valid_role, JSONResponse):
        return valid_role
    # Staff authenticate with username + password via /auth/staff-login. Refuse
    # here so the OTP path isn't a second, weaker way into the admin panel.
    if role in STAFF_ROLES:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "PASSWORD_LOGIN_REQUIRED",
            "Staff accounts sign in with a username and password",
        )

    now = utcnow()
    user = db.scalar(select(User).where(User.phone == normalized_phone))
    if user is not None and user.role != role:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "ROLE_MISMATCH",
            "This phone number is already registered with another role",
        )
    if user is None:
        latest_for_phone = find_latest_otp(db, normalized_phone, None)
        if latest_for_phone is not None and latest_for_phone.used_at is None and ensure_aware(latest_for_phone.expires_at) >= now:
            if latest_for_phone.role != role:
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    "ROLE_MISMATCH",
                    "This phone number has a pending OTP for another role",
                )
    if user is not None:
        active_error = check_active_user(user)
        if active_error is not None:
            return active_error

    if role in STAFF_ROLES and user is None:
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Staff users must be created internally")

    latest_otp = db.scalar(
        select(OtpCode)
        .where(OtpCode.phone == normalized_phone, OtpCode.role == role)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if latest_otp is not None:
        seconds_since_last = (now - ensure_aware(latest_otp.created_at)).total_seconds()
        if seconds_since_last < settings.otp_resend_cooldown_seconds:
            return error_response(status.HTTP_429_TOO_MANY_REQUESTS, "OTP_RESEND_TOO_SOON", "Please wait before requesting another OTP")

    recent_count = count_recent_otps(db, normalized_phone, role, now)
    if recent_count >= settings.otp_max_send_requests:
        return error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "OTP_SEND_LIMIT_EXCEEDED",
            "Too many OTP requests. Please try again later",
        )

    # Hard global ceiling on total OTP sends (SMS-spend / mass-abuse guard).
    if count_otps_since(db, now - timedelta(days=1)) >= settings.otp_global_daily_cap:
        return error_response(status.HTTP_429_TOO_MANY_REQUESTS, "OTP_GLOBAL_LIMIT", "Service is busy. Please try again later")

    # Per-IP ceiling — stops one source fanning out across many phone numbers.
    if not _is_local_ip(ip_address) and count_recent_otps_by_ip(db, ip_address, now) >= settings.otp_max_requests_per_ip:
        return error_response(status.HTTP_429_TOO_MANY_REQUESTS, "OTP_IP_LIMIT", "Too many requests. Please try again later")

    for active_otp in db.scalars(
        select(OtpCode).where(OtpCode.phone == normalized_phone, OtpCode.role == role, OtpCode.used_at.is_(None))
    ):
        active_otp.used_at = now
        db.add(active_otp)

    otp = generate_otp()
    db.add(
        OtpCode(
            phone=normalized_phone,
            role=role,
            otp_hash=otp_hash(otp),
            expires_at=now + timedelta(seconds=settings.otp_expire_seconds),
            attempt_count=0,
            send_count_window_start=now - timedelta(minutes=settings.otp_send_window_minutes),
            ip_address=ip_address,
        )
    )
    write_audit_log(
        db,
        user,
        "auth",
        user.id if user is not None else None,
        "otp_requested",
        new_value={"phone": normalized_phone, "role": role, "existing_user": user is not None},
        actor_role=user.role if user is not None else "system",
    )
    db.commit()

    # Deliver over SMS when enabled. Failure is logged inside send_sms and does
    # not fail the request — the code is stored and the user can resend.
    # Reviewer accounts sign in with a fixed code, so sending an SMS would only
    # burn credit on a number nobody reads.
    if settings.sms_enabled and not is_review_login_phone(normalized_phone):
        sms_service.send_sms(normalized_phone, otp_message(otp))

    data = {
        "otp_sent": True,
        "phone": normalized_phone,
        "expires_in_seconds": settings.otp_expire_seconds,
        "resend_after_seconds": settings.otp_resend_cooldown_seconds,
    }
    # Only surface the code when there is no real SMS to deliver it (local dev /
    # emulator). Once SMS is enabled the code goes over the wire only, never in
    # the API response.
    if is_development() and not settings.sms_enabled:
        data["dev_otp"] = otp
    return data


def find_latest_otp(db: Session, phone: str, role: str | None) -> OtpCode | None:
    stmt = select(OtpCode).where(OtpCode.phone == phone)
    if role is not None:
        stmt = stmt.where(OtpCode.role == role)
    return db.scalar(stmt.order_by(OtpCode.created_at.desc()).limit(1))


def infer_role(db: Session, phone: str, role: str | None) -> str | JSONResponse:
    if role is not None:
        valid_role = validate_role(role)
        if isinstance(valid_role, JSONResponse):
            return valid_role
        return role
    latest_otp = find_latest_otp(db, phone, None)
    if latest_otp is not None:
        return latest_otp.role
    user = db.scalar(select(User).where(User.phone == phone))
    if user is not None:
        return user.role
    return error_response(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "role is required")


def verify_otp(db: Session, phone: str, otp: str, role: str | None = None) -> User | JSONResponse:
    normalized_phone = normalize_phone(phone)
    if isinstance(normalized_phone, JSONResponse):
        return normalized_phone
    resolved_role = infer_role(db, normalized_phone, role)
    if isinstance(resolved_role, JSONResponse):
        return resolved_role
    # Mirrors the guard in request_otp: an OTP issued before staff moved to
    # password login must not still be redeemable.
    if resolved_role in STAFF_ROLES:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "PASSWORD_LOGIN_REQUIRED",
            "Staff accounts sign in with a username and password",
        )

    if not (
        otp.isdigit()
        and (
            len(otp) == settings.otp_length
            or is_dev_mock_otp(otp)
            or is_review_login_otp(normalized_phone, otp)
        )
    ):
        return error_response(status.HTTP_400_BAD_REQUEST, "OTP_INVALID", "Invalid OTP code")

    otp_record = find_latest_otp(db, normalized_phone, resolved_role)
    if otp_record is None:
        return error_response(status.HTTP_400_BAD_REQUEST, "OTP_INVALID", "Invalid OTP code")

    now = utcnow()
    if otp_record.used_at is not None:
        return error_response(status.HTTP_400_BAD_REQUEST, "OTP_USED", "OTP code has already been used")
    if ensure_aware(otp_record.expires_at) < now:
        return error_response(status.HTTP_400_BAD_REQUEST, "OTP_EXPIRED", "OTP code has expired")
    if otp_record.attempt_count >= settings.otp_max_verify_attempts:
        return error_response(status.HTTP_400_BAD_REQUEST, "OTP_TOO_MANY_ATTEMPTS", "Too many OTP verification attempts")

    used_review_login = is_review_login_otp(normalized_phone, otp)
    if used_review_login:
        logger.warning("Store-reviewer login used for %s", normalized_phone)
    otp_matches = is_dev_mock_otp(otp) or used_review_login or otp_hash(otp) == otp_record.otp_hash
    if not otp_matches:
        otp_record.attempt_count += 1
        db.add(otp_record)
        db.commit()
        return error_response(status.HTTP_400_BAD_REQUEST, "OTP_INVALID", "Invalid OTP code")

    otp_record.used_at = now
    db.add(otp_record)

    user = db.scalar(select(User).where(User.phone == normalized_phone))
    if user is not None and user.role != resolved_role:
        return error_response(
            status.HTTP_400_BAD_REQUEST,
            "ROLE_MISMATCH",
            "This phone number is already registered with another role",
        )
    created_user = user is None
    if user is None:
        if resolved_role not in PUBLIC_REGISTRATION_ROLES:
            return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Staff users must be created internally")
        user = User(phone=normalized_phone, role=resolved_role, status="active", is_phone_verified=True)
        user.last_login_at = now
        db.add(user)
        db.flush()
    else:
        active_error = check_active_user(user)
        if active_error is not None:
            return active_error
        user.is_phone_verified = True
        user.last_login_at = now
        db.add(user)

    try:
        create_profile_if_needed(db, user)
        if created_user:
            write_audit_log(
                db,
                user,
                "users",
                user.id,
                "user_registered",
                new_value={"phone": user.phone, "role": user.role, "status": user.status},
            )
        write_audit_log(
            db,
            user,
            "auth",
            user.id,
            "user_logged_in",
            new_value={"phone": user.phone, "role": user.role},
        )
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def login_staff_with_password(db: Session, username: str, password: str) -> User | JSONResponse:
    """Authenticate a staff user by username + password.

    Every failure returns the same generic error so the response never reveals
    whether a username exists, whether it belongs to staff, or whether only the
    password was wrong.
    """
    invalid = error_response(
        status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", "Invalid username or password"
    )
    normalized = normalize_username(username)
    if not normalized or not password:
        return invalid

    user = db.scalar(select(User).where(User.username == normalized))
    # Burn a comparable amount of time when the username does not exist, so
    # response timing doesn't disclose which usernames are real.
    if user is None or user.role not in STAFF_ROLES or not user.password_hash:
        verify_password(password, _TIMING_DUMMY_HASH)
        return invalid

    if not verify_password(password, user.password_hash):
        return invalid

    active_error = check_active_user(user)
    if active_error is not None:
        return active_error

    user.last_login_at = utcnow()
    db.add(user)
    write_audit_log(
        db,
        user,
        "auth",
        user.id,
        "staff_logged_in",
        new_value={"username": user.username, "role": user.role},
    )
    db.commit()
    db.refresh(user)
    return user


def create_refresh_session(db: Session, user: User, refresh_token: str, payload: dict[str, Any]) -> None:
    expires_at = datetime.fromtimestamp(payload["exp"], timezone.utc) if isinstance(payload.get("exp"), int | float) else ensure_aware(payload["exp"])
    db.add(
        RefreshSession(
            user_id=user.id,
            jti=payload["jti"],
            token_hash=token_hash(refresh_token),
            expires_at=expires_at,
        )
    )


def build_token_response(db: Session, user: User) -> dict[str, Any]:
    subject = str(user.id)
    access_token = create_access_token(subject, extra_claims={"phone": user.phone, "role": user.role})
    refresh_token = create_refresh_token(subject)
    refresh_payload = verify_token(refresh_token)
    if refresh_payload is not None:
        create_refresh_session(db, user, refresh_token, refresh_payload)
        db.commit()
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": user_to_dict(user),
    }
    return {**data, "success": True, "data": data, "message": "Login successful"}


def refresh_tokens(db: Session, refresh_token: str) -> dict[str, Any] | JSONResponse:
    payload = verify_token(refresh_token)
    if payload is None:
        return error_response(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Invalid refresh token")
    if payload.get("type") != "refresh":
        return error_response(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Invalid refresh token")

    jti = payload.get("jti")
    subject = payload.get("sub")
    if not jti or subject is None:
        return error_response(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Invalid refresh token")

    session = db.scalar(select(RefreshSession).where(RefreshSession.jti == jti))
    if session is None or session.token_hash != token_hash(refresh_token):
        return error_response(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Invalid refresh token")
    if session.is_revoked:
        return error_response(status.HTTP_401_UNAUTHORIZED, "REFRESH_TOKEN_REVOKED", "Refresh token has been revoked")
    if ensure_aware(session.expires_at) < utcnow():
        return error_response(status.HTTP_401_UNAUTHORIZED, "TOKEN_EXPIRED", "Refresh token has expired")

    user = db.get(User, int(subject))
    if user is None:
        return error_response(status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", "Authentication required")
    active_error = check_active_user(user)
    if active_error is not None:
        return active_error

    session.is_revoked = True
    session.revoked_at = utcnow()
    db.add(session)
    write_audit_log(
        db,
        user,
        "auth",
        user.id,
        "token_refreshed",
        new_value={"phone": user.phone, "role": user.role},
    )
    return build_token_response(db, user)


def logout_refresh_session(db: Session, refresh_token: str | None) -> JSONResponse | None:
    if refresh_token is None:
        return None
    payload = verify_token(refresh_token)
    if payload is None or payload.get("type") != "refresh" or not payload.get("jti"):
        return error_response(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Invalid refresh token")
    session = db.scalar(select(RefreshSession).where(RefreshSession.jti == payload["jti"]))
    if session is not None and not session.is_revoked:
        session.is_revoked = True
        session.revoked_at = utcnow()
        db.add(session)
        user = db.get(User, session.user_id)
        write_audit_log(
            db,
            user,
            "auth",
            user.id if user is not None else None,
            "user_logged_out",
            new_value={"user_id": session.user_id},
            actor_role=user.role if user is not None else "system",
        )
        db.commit()
    return None


def create_admin_user(db: Session, actor: User, payload: AdminUserCreate) -> User | JSONResponse:
    if payload.role not in SUPER_ADMIN_CREATABLE_ROLES:
        return error_response(status.HTTP_400_BAD_REQUEST, "ROLE_NOT_ALLOWED", "Super admin can create only admin or operator users")
    normalized_phone = normalize_phone(payload.phone)
    if isinstance(normalized_phone, JSONResponse):
        return normalized_phone
    existing = db.scalar(select(User).where(User.phone == normalized_phone))
    if existing is not None:
        return error_response(status.HTTP_409_CONFLICT, "ALREADY_EXISTS", "Phone number is already registered")
    user = User(
        phone=normalized_phone,
        role=payload.role,
        full_name=payload.full_name,
        status="active",
        is_phone_verified=True,
    )
    db.add(user)
    db.flush()
    if AuditLog.__table__ is not None:
        write_audit_log(
            db,
            actor,
            "users",
            user.id,
            "admin_user_created",
            new_value={"phone": user.phone, "role": user.role, "full_name": user.full_name},
        )
    db.commit()
    db.refresh(user)
    return user
