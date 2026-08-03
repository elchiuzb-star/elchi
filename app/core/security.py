from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt is used directly rather than through passlib: passlib 1.7.4 reads
# bcrypt.__about__, which bcrypt removed in 4.1, so the passlib backend raises
# on first use against the installed bcrypt 5.x.
BCRYPT_ROUNDS = 12
# bcrypt silently truncates at 72 bytes; reject longer input instead.
MAX_PASSWORD_BYTES = 72


def create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + expires_delta
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "jti": str(uuid4()),
        "iat": issued_at,
        "exp": expires_at,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    return create_token(
        subject=subject,
        token_type="access",
        expires_delta=expires_delta or timedelta(minutes=settings.access_token_expire_minutes),
        extra_claims=extra_claims,
    )


def create_refresh_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    return create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=expires_delta or timedelta(days=settings.refresh_token_expire_days),
        extra_claims=extra_claims,
    )


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time check. Returns False rather than raising on a malformed or
    missing hash, so a user without a password simply fails to authenticate."""
    if not hashed_password:
        return False
    encoded = plain_password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False
