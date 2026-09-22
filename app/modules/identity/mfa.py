"""Staff MFA (ADR-0021, accepted 17.09.2026). TOTP only; WebAuthn is a later, separate decision.

The rules this module refuses to bend:

* **A second factor is activated by somebody else.** ``enroll`` creates a *pending* factor; only a different
  super_admin can activate it, and the database enforces the difference as well (``ck_..._two_person``).
* **Recovery restores access, never authority.** Consuming a recovery code lets its owner enroll a new factor.
  It does not verify a step-up, and it never counts as one of the two people a large adjustment needs (Q17,
  Q49). :func:`consume_recovery_code` therefore returns "you may enroll again" and nothing else.
* **One employee is never two approvers.** Every approval path takes ``actor_user_id`` and the subject, and
  refuses when they match - in Python for a clear error, and in the DB so no other writer can get around it.
* **Enforcement is switched on by a person, not by an accident.** The rollout is staged
  (``settings.staff_mfa_mode``: ``audit_only`` -> ``enforce_privileged`` -> ``enforce_all``) and starts in
  audit-only, where a missing or stale factor is recorded and allowed. Independently of the stage, enforcement
  never applies while a single active super_admin exists, because locking the platform's only operator out is
  worse than the risk MFA removes.

Secrets: the TOTP secret is sealed with :mod:`app.core.secret_box` under its own derived key, so the database
alone cannot mint codes. Nothing here logs a secret, a code or a recovery code.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import pyotp
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.contracts.enums import Capability, Role
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.core.config import settings
from app.core.secret_box import CURRENT_KEY_VERSION, SecretBoxError, open_sealed, seal
from app.modules.identity.models import StaffMfaEvent, StaffMfaFactor, StaffMfaRecoveryCode

SECRET_PURPOSE = "staff-mfa"
TOTP_INTERVAL_SECONDS = 30
#: One step either side, i.e. the code the user is reading plus clock skew - not a wide window.
TOTP_VALID_WINDOW = 1
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_BYTES = 10
#: ADR-0021: a money or flag command must be backed by a factor check no older than this.
STEP_UP_MAX_AGE = timedelta(minutes=5)
#: Six digits are guessable by a patient attacker, so failures are counted per account and the account stops
#: answering for a while. The window is deliberately short: this protects the code, it does not lock staff out
#: for a day. Recorded failures are the same ``verify_failed`` rows the audit trail already keeps.
MAX_FAILED_ATTEMPTS = 5
FAILED_ATTEMPT_WINDOW = timedelta(minutes=15)

#: The commands that require a fresh factor check. Everything here changes money, access or what users see.
STEP_UP_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.FINANCE_TOPUP_APPROVE,
        Capability.FINANCE_ADJUSTMENT_APPROVE,
        Capability.FINANCE_FEE_FINALIZE,
        Capability.FINANCE_COMMISSION_POLICY_MANAGE,
        Capability.OPS_FEATURE_FLAG_MANAGE,
        Capability.PLATFORM_POLICY_MANAGE,
        Capability.STAFF_MANAGE,
    }
)

MANDATORY_ROLES: frozenset[Role] = frozenset({Role.SUPER_ADMIN, Role.FINANCE})

_ACTIVE_SUPER_ADMINS = text("SELECT count(*) FROM users WHERE role = 'super_admin' AND status = 'active'")


@dataclass(frozen=True, slots=True)
class EnrollmentSecret:
    """Returned once, at enrollment. The caller shows it and forgets it; it is never readable again."""

    factor_public_id: str
    secret: str
    provisioning_uri: str
    recovery_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MfaState:
    enrolled: bool
    active: bool
    audit_only: bool
    stepped_up_at: datetime | None
    #: An enrollment waiting for a second super_admin. Independent of ``active``: re-enrolling does not take
    #: the working factor away, so both can be true at once.
    pending: bool = False

    def step_up_fresh(self, *, now: datetime | None = None) -> bool:
        if self.stepped_up_at is None:
            return False
        return (utc_now() if now is None else ensure_aware_utc(now)) - self.stepped_up_at <= STEP_UP_MAX_AGE


# --- mode ------------------------------------------------------------------------------------------------


def active_super_admin_count(session: Session) -> int:
    return int(session.scalar(_ACTIVE_SUPER_ADMINS) or 0)


AUDIT_ONLY = "audit_only"
ENFORCE_PRIVILEGED = "enforce_privileged"
ENFORCE_ALL = "enforce_all"
ROLLOUT_MODES = (AUDIT_ONLY, ENFORCE_PRIVILEGED, ENFORCE_ALL)


def audit_only(session: Session) -> bool:
    """Should a missing or stale factor be recorded and allowed, rather than refused?

    Two independent reasons say yes, and either is enough:

    1. **The rollout stage** (``settings.staff_mfa_mode``) is still ``audit_only``. ADR-0021 stages the
       rollout deliberately; enforcement must be switched on by a person, not by the arrival of a new staff
       account, or the first day somebody hires a second admin the money commands stop working.
    2. **There is only one active super_admin.** Enforcing then would risk locking the platform's only
       operator out, which is a worse outcome than the risk MFA removes. Production readiness therefore
       requires at least two super_admins (go-live checklist).
    """
    if settings.staff_mfa_mode not in ROLLOUT_MODES or settings.staff_mfa_mode == AUDIT_ONLY:
        return True
    return active_super_admin_count(session) < 2


# --- enrollment and activation ---------------------------------------------------------------------------


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").strip().replace("-", "").upper().encode("utf-8")).hexdigest()


def _record(session: Session, *, user_id: int, event_type: str, actor_user_id: int | None = None, **detail) -> None:
    session.add(
        StaffMfaEvent(user_id=user_id, actor_user_id=actor_user_id, event_type=event_type, detail=dict(detail))
    )


def recent_failed_attempts(session: Session, user_id: int, *, now: datetime | None = None) -> int:
    moment = utc_now() if now is None else ensure_aware_utc(now)
    return int(
        session.scalar(
            select(func.count())
            .select_from(StaffMfaEvent)
            .where(
                StaffMfaEvent.user_id == user_id,
                StaffMfaEvent.event_type == "verify_failed",
                StaffMfaEvent.created_at >= moment - FAILED_ATTEMPT_WINDOW,
                # Audit-only rows are written by :func:`require_step_up` when nobody submitted a code at all.
                # Counting them would lock a staff member out of the very screen that ends audit-only mode.
                func.coalesce(StaffMfaEvent.detail["mode"].as_string(), "") != "audit_only",
            )
        )
        or 0
    )


def record_failed_attempt(session: Session, *, user_id: int, purpose: str, actor_user_id: int | None = None) -> None:
    """Write a failed-code row that has to outlive the command's rolled-back savepoint (ADR-0005, BR D8).

    A wrong code is answered with a domain 4xx, and that rolls the handler's writes back - including the
    ``verify_failed`` row the service wrote. Without this the trail would be empty and the attempt counter
    would never rise, so guessing would be free. The route therefore re-records the attempt after the
    idempotent step (``run_command(after_command=...)``), never on a replay.
    """
    _record(session, user_id=user_id, event_type="verify_failed", actor_user_id=actor_user_id, purpose=purpose)


def guard_attempts(session: Session, user_id: int, *, now: datetime | None = None) -> None:
    """Refuse to check another code once this account has failed too often in the window.

    The counter is per account, not per connection, and it covers every path that accepts a code - login,
    step-up, activation by a second super_admin and recovery - because an attacker would otherwise simply pick
    the path that is not counted.
    """
    if recent_failed_attempts(session, user_id, now=now) < MAX_FAILED_ATTEMPTS:
        return
    raise DomainError(
        ErrorCode.RATE_LIMITED,
        details={
            "limit": MAX_FAILED_ATTEMPTS,
            "window_s": int(FAILED_ATTEMPT_WINDOW.total_seconds()),
            "retry_after_s": int(FAILED_ATTEMPT_WINDOW.total_seconds()),
            "reason": "too_many_failed_codes",
        },
    )


def _active_factor(session: Session, user_id: int) -> StaffMfaFactor | None:
    return session.scalar(
        select(StaffMfaFactor).where(StaffMfaFactor.user_id == user_id, StaffMfaFactor.status == "active")
    )


def enroll(session: Session, *, user_id: int, account_name: str, issuer: str = "Elchi") -> EnrollmentSecret:
    """Create a *pending* factor plus fresh recovery codes. Grants nothing until somebody else activates it."""
    secret = pyotp.random_base32()
    public_id = uuid.uuid4()
    factor = StaffMfaFactor(
        public_id=public_id,
        user_id=user_id,
        factor_type="totp",
        # The public id is the AAD, so a ciphertext moved onto another factor row will not decrypt.
        secret_cipher=seal(
            settings.secret_key, SECRET_PURPOSE, secret, aad=str(public_id), key_version=CURRENT_KEY_VERSION
        ),
        secret_key_version=CURRENT_KEY_VERSION,
        status="pending",
    )
    session.add(factor)
    session.flush()

    # Replace any earlier unused codes: a re-enrollment must not leave old paper codes valid.
    session.query(StaffMfaRecoveryCode).filter(
        StaffMfaRecoveryCode.user_id == user_id, StaffMfaRecoveryCode.used_at.is_(None)
    ).delete(synchronize_session=False)
    codes = tuple(secrets.token_hex(RECOVERY_CODE_BYTES).upper() for _ in range(RECOVERY_CODE_COUNT))
    for code in codes:
        session.add(StaffMfaRecoveryCode(user_id=user_id, code_hash=_hash_code(code)))

    _record(session, user_id=user_id, event_type="factor_enrolled", factor_type="totp")
    uri = pyotp.TOTP(secret, interval=TOTP_INTERVAL_SECONDS).provisioning_uri(name=account_name, issuer_name=issuer)
    return EnrollmentSecret(
        factor_public_id=format_public_id(PublicIdPrefix.STAFF_MFA_FACTOR, public_id),
        secret=secret,
        provisioning_uri=uri,
        recovery_codes=codes,
    )


def activate(
    session: Session, *, actor_user_id: int, subject_user_id: int, code: str, now: datetime | None = None
) -> StaffMfaFactor:
    """A different super_admin confirms the subject's pending factor by checking one live code."""
    if actor_user_id == subject_user_id:
        raise DomainError(
            ErrorCode.FORBIDDEN,
            details={"reason": "self_activation", "hint": "a second factor is activated by somebody else"},
        )
    from app.modules.identity import service as identity_service

    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id), Capability.STAFF_MFA_APPROVE
    )
    guard_attempts(session, subject_user_id, now=now)
    factor = session.scalar(
        select(StaffMfaFactor)
        .where(StaffMfaFactor.user_id == subject_user_id, StaffMfaFactor.status == "pending")
        .order_by(StaffMfaFactor.id.desc())
    )
    if factor is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"reason": "no_pending_factor"})
    if not _code_matches(factor, code):
        _record(
            session, user_id=subject_user_id, actor_user_id=actor_user_id, event_type="verify_failed",
            phase="activation",
        )
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "invalid_code"})

    moment = utc_now() if now is None else ensure_aware_utc(now)
    factor.status = "active"
    factor.activated_at = moment
    factor.activated_by = actor_user_id
    factor.version += 1
    _record(session, user_id=subject_user_id, actor_user_id=actor_user_id, event_type="factor_activated")
    return factor


def reset(session: Session, *, actor_user_id: int, subject_user_id: int, reason: str) -> int:
    """A different super_admin takes a staff member's factor away (lost phone, suspected compromise).

    It revokes, it never grants: afterwards the subject has no factor and must enroll again, and the new
    enrollment still needs a second person. Unused recovery codes are spent as well, because a reset is also
    the answer to "the codes may have been seen".

    Returns the number of factor rows revoked (0 when there was nothing to reset - still recorded).
    """
    if actor_user_id == subject_user_id:
        raise DomainError(
            ErrorCode.FORBIDDEN,
            details={"reason": "self_reset", "hint": "a factor is reset by somebody else"},
        )
    from app.modules.identity import service as identity_service

    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id), Capability.STAFF_MFA_APPROVE
    )
    moment = utc_now()
    factors = (
        session.scalars(
            select(StaffMfaFactor).where(
                StaffMfaFactor.user_id == subject_user_id, StaffMfaFactor.status.in_(("pending", "active"))
            )
        )
        .all()
    )
    for factor in factors:
        factor.status = "revoked"
        factor.revoked_at = moment
        factor.activated_at = None
        factor.activated_by = None
        factor.version += 1
    session.query(StaffMfaRecoveryCode).filter(
        StaffMfaRecoveryCode.user_id == subject_user_id, StaffMfaRecoveryCode.used_at.is_(None)
    ).delete(synchronize_session=False)
    _record(
        session, user_id=subject_user_id, actor_user_id=actor_user_id, event_type="factor_reset",
        revoked=len(factors), reason=reason[:200],
    )
    return len(factors)


def _secret_of(factor: StaffMfaFactor) -> str:
    try:
        return open_sealed(
            settings.secret_key,
            SECRET_PURPOSE,
            factor.secret_cipher,
            aad=str(factor.public_id),
            key_version=factor.secret_key_version,
        )
    except SecretBoxError as exc:  # a factor we cannot read must fail closed, never "accept anything"
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "factor_unreadable"}) from exc


def _code_matches(factor: StaffMfaFactor, code: str) -> bool:
    cleaned = (code or "").strip().replace(" ", "")
    if not cleaned.isdigit():
        return False
    totp = pyotp.TOTP(_secret_of(factor), interval=TOTP_INTERVAL_SECONDS)
    return bool(totp.verify(cleaned, valid_window=TOTP_VALID_WINDOW))


# --- verification and step-up ----------------------------------------------------------------------------


def verify(session: Session, *, user_id: int, code: str, purpose: str = "login", now: datetime | None = None) -> bool:
    """Check one code. Replay of the same time step is refused even inside its own 30-second window."""
    guard_attempts(session, user_id, now=now)
    factor = _active_factor(session, user_id)
    if factor is None:
        return False
    if not _code_matches(factor, code):
        _record(session, user_id=user_id, event_type="verify_failed", purpose=purpose)
        return False

    counter = int(time.time() // TOTP_INTERVAL_SECONDS)
    if factor.last_counter is not None and counter <= factor.last_counter:
        _record(session, user_id=user_id, event_type="verify_failed", purpose=purpose, reason="replayed")
        return False

    moment = utc_now() if now is None else ensure_aware_utc(now)
    factor.last_counter = counter
    factor.last_used_at = moment
    _record(session, user_id=user_id, event_type="verify_succeeded", purpose=purpose)
    if purpose == "step_up":
        _record(session, user_id=user_id, event_type="step_up")
    return True


def step_up(session: Session, *, user_id: int, code: str, now: datetime | None = None) -> bool:
    return verify(session, user_id=user_id, code=code, purpose="step_up", now=now)


def last_step_up_at(session: Session, user_id: int) -> datetime | None:
    value = session.scalar(
        select(func.max(StaffMfaEvent.created_at)).where(
            StaffMfaEvent.user_id == user_id, StaffMfaEvent.event_type == "step_up"
        )
    )
    return None if value is None else ensure_aware_utc(value)


def state(session: Session, user_id: int) -> MfaState:
    """What this account has now.

    ``active`` is asked of *any* active factor, not of the newest row: a staff member who starts a second
    enrollment (new phone) keeps working with the old factor until somebody activates the new one. Reading the
    newest row instead would report ``active=False`` and, under enforcement, would stop that person's money
    commands the moment they opened the enrollment screen.
    """
    factors = (
        session.scalars(
            select(StaffMfaFactor)
            .where(StaffMfaFactor.user_id == user_id, StaffMfaFactor.status.in_(("pending", "active")))
            .order_by(StaffMfaFactor.id.desc())
        )
        .all()
    )
    return MfaState(
        enrolled=bool(factors),
        active=any(factor.status == "active" for factor in factors),
        audit_only=audit_only(session),
        stepped_up_at=last_step_up_at(session, user_id),
        pending=any(factor.status == "pending" for factor in factors),
    )


def require_step_up(session: Session, *, user_id: int, capability: Capability, now: datetime | None = None) -> None:
    """Refuse a money/flag command that is not backed by a recent factor check.

    In audit-only mode the attempt is recorded and allowed - the alternative, during a pilot with one
    super_admin, is a platform nobody can operate.
    """
    if capability not in STEP_UP_CAPABILITIES:
        return
    current = state(session, user_id)
    if current.active and current.step_up_fresh(now=now):
        return
    if current.audit_only:
        _record(
            session, user_id=user_id, event_type="verify_failed", purpose="step_up",
            capability=capability.value, mode="audit_only",
        )
        return
    raise DomainError(
        ErrorCode.FORBIDDEN,
        details={
            "reason": "step_up_required",
            "capability": capability.value,
            "max_age_seconds": int(STEP_UP_MAX_AGE.total_seconds()),
        },
    )


# --- recovery --------------------------------------------------------------------------------------------


def consume_recovery_code(session: Session, *, user_id: int, code: str, now: datetime | None = None) -> bool:
    """Spend one recovery code so its owner can enroll a new factor.

    This is the whole effect. It does not verify a step-up, it does not approve money, and it never makes one
    employee count as the second person a large adjustment needs (Q17/Q49). The active factor is revoked, so
    the account is not left half-protected.
    """
    guard_attempts(session, user_id, now=now)
    row = session.scalar(
        select(StaffMfaRecoveryCode).where(
            StaffMfaRecoveryCode.user_id == user_id,
            StaffMfaRecoveryCode.code_hash == _hash_code(code),
            StaffMfaRecoveryCode.used_at.is_(None),
        )
    )
    if row is None:
        _record(session, user_id=user_id, event_type="verify_failed", purpose="recovery")
        return False
    moment = utc_now() if now is None else ensure_aware_utc(now)
    row.used_at = moment
    factor = _active_factor(session, user_id)
    if factor is not None:
        factor.status = "revoked"
        factor.revoked_at = moment
        factor.activated_at = None
        factor.activated_by = None
        factor.version += 1
    _record(session, user_id=user_id, event_type="recovery_code_used")
    # The session runs with autoflush off; the caller counts the remaining codes right after this returns.
    session.flush()
    return True


def unused_recovery_code_count(session: Session, user_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(StaffMfaRecoveryCode)
            .where(StaffMfaRecoveryCode.user_id == user_id, StaffMfaRecoveryCode.used_at.is_(None))
        )
        or 0
    )
