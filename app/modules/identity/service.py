"""Identity domain API (A1): capabilities, driver eligibility (D16), role activation (Q3).

Public functions take the caller's ``Session`` and never commit (ADR-0001).
Lock helpers follow the global order (ADR-0017): ``users`` is always the first group.

Signatures other modules may rely on:

* ``get_capabilities(session, user_id, *, now=None) -> CapabilitySet``
* ``require_capability(caps, capability) -> None``  (DRIVER_NOT_ELIGIBLE / CAPABILITY_REQUIRED)
* ``ensure_driver_eligible(session, user_id, *, now=None) -> CapabilitySet``
* ``lock_user_eligibility(session, user_ids, *, mode="update"|"share") -> list[int]``
* ``activate_role(session, user_id, role, *, granted_by=None, now=None) -> CapabilitySet``
* ``set_driver_eligibility(session, *, driver_user_id, actor_user_id, action, expected_version, reason, now=None)``
  (``block_driver_eligibility`` / ``unblock_driver_eligibility`` are thin wrappers)
* ``get_driver_eligibility(session, driver_user_id, *, now=None) -> EligibilityState``
* ``user_public_id``, ``user_refs``, ``resolve_user_id``, ``get_user_summary``
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import MARKETPLACE_ROLES, Capability, Role, role_combination_allowed
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, parse_public_id
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.models import AuditLog, DriverDocument, DriverProfile
from app.modules.identity.capabilities import (
    ACTIVE_USER_STATUS,
    DRIVER_NEW_BUSINESS_CAPABILITIES,
    DriverFacts,
    compute_capabilities,
    driver_ineligibility_reasons,
    effective_roles,
)
from app.modules.identity.models import DriverDocumentValidity, DriverEligibilityBlock, UserRole, users_identity
from app.modules.platform.service import constraint_name_of

__all__ = [
    "CapabilitySet",
    "EligibilityState",
    "UserSummary",
    "activate_role",
    "block_driver_eligibility",
    "ensure_driver_eligible",
    "get_capabilities",
    "get_driver_eligibility",
    "get_user_summary",
    "lock_user_eligibility",
    "require_capability",
    "resolve_user_id",
    "set_driver_eligibility",
    "unblock_driver_eligibility",
    "user_public_id",
    "user_refs",
]

Q3_CONSTRAINT = "ck_user_roles_staff_marketplace_separation"
ACTIVE_BLOCK_INDEX = "uq_driver_eligibility_blocks_active"
ROLE_STATUS_ACTIVE = "active"
APPROVED_DOCUMENT_STATUS = "approved"


@dataclass(frozen=True, slots=True)
class UserSummary:
    id: int
    public_id: str
    phone: str
    full_name: str | None
    primary_role: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    user_id: int
    roles: frozenset[Role]
    capabilities: frozenset[Capability]
    account_active: bool
    driver: DriverFacts | None
    driver_reasons: tuple[str, ...]

    def has(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @property
    def driver_eligible(self) -> bool:
        return Role.DRIVER in self.roles and self.account_active and not self.driver_reasons


@dataclass(frozen=True, slots=True)
class EligibilityState:
    user_id: int
    user_public_id: str
    eligible: bool
    blocked_reason: str | None
    active_trip_public_ids: tuple[str, ...]
    version: int


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _flush_or_translate(session: Session, translations: dict[str, Callable[[], DomainError]]) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        factory = translations.get(constraint_name_of(exc) or "")
        if factory is None:
            raise
        raise factory() from exc


# --- users -------------------------------------------------------------------------------------


def _user_row(session: Session, user_id: int):  # noqa: ANN202 - RowMapping
    return (
        session.execute(select(users_identity).where(users_identity.c.id == user_id)).mappings().one_or_none()
    )


def get_user_summary(session: Session, user_id: int) -> UserSummary:
    row = _user_row(session, user_id)
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return UserSummary(
        id=row["id"],
        public_id=format_public_id(PublicIdPrefix.USER, row["public_id"]),
        phone=row["phone"],
        full_name=row["full_name"],
        primary_role=row["role"],
        status=row["status"],
        created_at=ensure_aware_utc(row["created_at"]),
    )


def user_public_id(session: Session, user_id: int) -> str:
    return get_user_summary(session, user_id).public_id


def user_refs(session: Session, user_ids: Iterable[int]) -> dict[int, tuple[str, str | None]]:
    """``{user_id: (usr_ public id, full_name)}`` for display; never phones."""
    ids = sorted({int(user_id) for user_id in user_ids})
    if not ids:
        return {}
    rows = session.execute(
        select(users_identity.c.id, users_identity.c.public_id, users_identity.c.full_name).where(
            users_identity.c.id.in_(ids)
        )
    )
    return {row.id: (format_public_id(PublicIdPrefix.USER, row.public_id), row.full_name) for row in rows}


def resolve_user_id(session: Session, public_id: str) -> int:
    value = parse_public_id(public_id, PublicIdPrefix.USER)
    user_id = session.execute(select(users_identity.c.id).where(users_identity.c.public_id == value)).scalar_one_or_none()
    if user_id is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return user_id


def lock_user_eligibility(
    session: Session, user_ids: Iterable[int], *, mode: Literal["update", "share"] = "update"
) -> list[int]:
    """First group of the global lock order: ``users`` rows by ascending id.

    ``update`` (``FOR NO KEY UPDATE``) serialises with admin eligibility blocks (AC41); ``share`` lets
    several readers of one user proceed while still excluding a concurrent block.
    Returns the ids that exist.
    """
    ids = sorted({int(user_id) for user_id in user_ids})
    if not ids:
        return []
    stmt = (
        select(users_identity.c.id)
        .where(users_identity.c.id.in_(ids))
        .order_by(users_identity.c.id)
        # update -> FOR NO KEY UPDATE: excludes FOR SHARE readers and admin blocks, but not the
        # FOR KEY SHARE that FK inserts (threads, listings, versions -> users) take (wave 1.5 deadlock fix).
        .with_for_update(read=(mode == "share"), key_share=(mode != "share"))
    )
    return list(session.execute(stmt).scalars())


# --- capabilities ---------------------------------------------------------------------------------


def _activated_roles(session: Session, user_id: int) -> list[str]:
    return list(
        session.execute(
            select(UserRole.role).where(UserRole.user_id == user_id, UserRole.status == ROLE_STATUS_ACTIVE)
        ).scalars()
    )


def _driver_facts(session: Session, user_id: int, now: datetime) -> DriverFacts:
    from app.modules.trips import service as trips_service  # trips imports identity at module level

    verification_status = session.execute(
        select(DriverProfile.verification_status).where(DriverProfile.user_id == user_id)
    ).scalar_one_or_none()
    block_reason = session.execute(
        select(DriverEligibilityBlock.reason).where(
            DriverEligibilityBlock.driver_user_id == user_id, DriverEligibilityBlock.lifted_at.is_(None)
        )
    ).scalar_one_or_none()
    expired_documents = tuple(
        session.execute(
            select(DriverDocumentValidity.driver_document_id)
            .join(DriverDocument, DriverDocument.id == DriverDocumentValidity.driver_document_id)
            .join(DriverProfile, DriverProfile.id == DriverDocument.driver_id)
            .where(
                DriverProfile.user_id == user_id,
                DriverDocument.status == APPROVED_DOCUMENT_STATUS,
                DriverDocumentValidity.valid_until <= now,
            )
            .order_by(DriverDocumentValidity.driver_document_id)
        ).scalars()
    )
    from app.modules.bookings import service as bookings_service  # bookings imports identity at module level

    obligations = bookings_service.driver_v2_obligations(session, user_id)  # read-only A4 API
    return DriverFacts(
        verification_status=verification_status,
        active_block_reason=block_reason,
        expired_document_ids=expired_documents,
        active_trip_count=max(trips_service.count_active_trips(session, user_id), len(obligations.active_trip_ids)),
        active_booking_count=obligations.active_booking_count,
    )


def get_capabilities(session: Session, user_id: int, *, now: datetime | None = None) -> CapabilitySet:
    """Server-side capabilities, recomputed on every call (no cache; blocks apply at once)."""
    now = _now(now)
    row = _user_row(session, user_id)
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    roles = effective_roles(row["role"], _activated_roles(session, user_id))
    account_active = row["status"] == ACTIVE_USER_STATUS
    driver = _driver_facts(session, user_id, now) if Role.DRIVER in roles else None
    reasons = (
        tuple(driver_ineligibility_reasons(account_active=account_active, facts=driver))
        if Role.DRIVER in roles
        else ()
    )
    return CapabilitySet(
        user_id=user_id,
        roles=roles,
        capabilities=compute_capabilities(roles=roles, account_active=account_active, driver=driver),
        account_active=account_active,
        driver=driver,
        driver_reasons=reasons,
    )


def require_capability(
    caps: CapabilitySet, capability: Capability, *, session: Session | None = None
) -> None:
    """Refuse a command the caller cannot run.

    ADR-0021 adds a second question for money and flag commands: not only *may* this person do it, but did
    they prove a second factor recently (``mfa.STEP_UP_CAPABILITIES``). That check needs a session, so callers
    that have one pass it; without a session the capability check behaves exactly as before. While the
    platform runs with a single super_admin the step-up is audit-only, so nothing is blocked by it yet.
    """
    if capability in caps.capabilities:
        if session is not None:
            from app.modules.identity import mfa

            mfa.require_step_up(session, user_id=caps.user_id, capability=capability)
        return
    if capability in DRIVER_NEW_BUSINESS_CAPABILITIES and Role.DRIVER in caps.roles:
        raise DomainError(ErrorCode.DRIVER_NOT_ELIGIBLE, details={"reasons": list(caps.driver_reasons)})
    raise DomainError(ErrorCode.CAPABILITY_REQUIRED, details={"capability": capability.value})


def ensure_driver_eligible(session: Session, user_id: int, *, now: datetime | None = None) -> CapabilitySet:
    caps = get_capabilities(session, user_id, now=now)
    if not caps.driver_eligible:
        reasons = list(caps.driver_reasons) if Role.DRIVER in caps.roles else ["not_a_driver"]
        raise DomainError(ErrorCode.DRIVER_NOT_ELIGIBLE, details={"reasons": reasons})
    return caps


def activate_role(
    session: Session, user_id: int, role: Role | str, *, granted_by: int | None = None, now: datetime | None = None
) -> CapabilitySet:
    """Self-service activation of a marketplace role (I3). Idempotent; Q3 in service and DB."""
    now = _now(now)
    try:
        role = Role(role)
    except ValueError:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "role"}) from None
    if role not in MARKETPLACE_ROLES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "role"})
    if not lock_user_eligibility(session, [user_id]):
        raise DomainError(ErrorCode.NOT_FOUND)
    row = _user_row(session, user_id)
    roles = effective_roles(row["role"], _activated_roles(session, user_id))
    if role in roles:
        return get_capabilities(session, user_id, now=now)
    if not role_combination_allowed(roles | {role}):
        raise DomainError(
            ErrorCode.ROLE_COMBINATION_FORBIDDEN, details={"roles": sorted(r.value for r in roles), "role": role.value}
        )
    existing = session.execute(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role == role.value).with_for_update(key_share=True)
    ).scalar_one_or_none()
    if existing is None:
        session.add(UserRole(user_id=user_id, role=role.value, status=ROLE_STATUS_ACTIVE, granted_by=granted_by))
    else:
        existing.status = ROLE_STATUS_ACTIVE
        existing.granted_by = granted_by
        existing.updated_at = now
    _flush_or_translate(
        session, {Q3_CONSTRAINT: lambda: DomainError(ErrorCode.ROLE_COMBINATION_FORBIDDEN, details={"role": role.value})}
    )
    return get_capabilities(session, user_id, now=now)


# --- driver eligibility (D16) ------------------------------------------------------------------


def eligibility_version(session: Session, driver_user_id: int) -> int:
    """1 + number of block events + number of unblock events (monotonic, no extra column)."""
    blocks, lifts = session.execute(
        select(func.count(DriverEligibilityBlock.id), func.count(DriverEligibilityBlock.lifted_at)).where(
            DriverEligibilityBlock.driver_user_id == driver_user_id
        )
    ).one()
    return 1 + int(blocks) + int(lifts)


def get_driver_eligibility(session: Session, driver_user_id: int, *, now: datetime | None = None) -> EligibilityState:
    from app.modules.trips import service as trips_service

    caps = get_capabilities(session, driver_user_id, now=now)
    if Role.DRIVER not in caps.roles:
        raise DomainError(ErrorCode.NOT_FOUND)
    return EligibilityState(
        user_id=driver_user_id,
        user_public_id=user_public_id(session, driver_user_id),
        eligible=caps.driver_eligible,
        blocked_reason=caps.driver.active_block_reason if caps.driver else None,
        active_trip_public_ids=tuple(trips_service.active_trip_public_ids(session, driver_user_id)),
        version=eligibility_version(session, driver_user_id),
    )


def set_driver_eligibility(
    session: Session,
    *,
    driver_user_id: int,
    actor_user_id: int,
    action: Literal["block", "unblock"],
    expected_version: int,
    reason: str,
    now: datetime | None = None,
) -> EligibilityState:
    """Admin eligibility block/unblock (I5).

    Locks only the driver ``users`` row (lock order group 1), so it serialises with
    listing publish, proposal submit, trip create and accept (AC41). Removes only
    new-business capabilities; ``users.status`` is never touched (D16).
    """
    now = _now(now)
    actor_caps = get_capabilities(session, actor_user_id, now=now)
    require_capability(actor_caps, Capability.OPS_DRIVER_ELIGIBILITY_MANAGE)
    reason = (reason or "").strip()
    if not reason:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    if not lock_user_eligibility(session, [driver_user_id]):
        raise DomainError(ErrorCode.NOT_FOUND)
    row = _user_row(session, driver_user_id)
    if Role.DRIVER not in effective_roles(row["role"], _activated_roles(session, driver_user_id)):
        raise DomainError(ErrorCode.NOT_FOUND)
    current_version = eligibility_version(session, driver_user_id)
    if expected_version != current_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": current_version})
    active = session.execute(
        select(DriverEligibilityBlock)
        .where(DriverEligibilityBlock.driver_user_id == driver_user_id, DriverEligibilityBlock.lifted_at.is_(None))
        .with_for_update(key_share=True)
    ).scalar_one_or_none()
    if action == "block":
        if active is not None:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "already_blocked"})
        session.add(
            DriverEligibilityBlock(driver_user_id=driver_user_id, reason=reason, blocked_by=actor_user_id, blocked_at=now)
        )
    elif action == "unblock":
        if active is None:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "not_blocked"})
        active.lifted_at = max(now, ensure_aware_utc(active.blocked_at))
        active.lifted_by = actor_user_id
        active.lift_reason = reason
    else:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "action"})
    _flush_or_translate(
        session,
        {ACTIVE_BLOCK_INDEX: lambda: DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "already_blocked"})},
    )
    session.add(
        AuditLog(
            actor_id=actor_user_id,
            entity_type="driver_eligibility",
            entity_id=driver_user_id,
            action=f"driver_eligibility_{action}",
            details={"reason": reason, "version": current_version + 1},
        )
    )
    session.flush()
    return get_driver_eligibility(session, driver_user_id, now=now)


def block_driver_eligibility(
    session: Session, *, driver_user_id: int, actor_user_id: int, expected_version: int, reason: str, now: datetime | None = None
) -> EligibilityState:
    return set_driver_eligibility(
        session,
        driver_user_id=driver_user_id,
        actor_user_id=actor_user_id,
        action="block",
        expected_version=expected_version,
        reason=reason,
        now=now,
    )


def unblock_driver_eligibility(
    session: Session, *, driver_user_id: int, actor_user_id: int, expected_version: int, reason: str, now: datetime | None = None
) -> EligibilityState:
    return set_driver_eligibility(
        session,
        driver_user_id=driver_user_id,
        actor_user_id=actor_user_id,
        action="unblock",
        expected_version=expected_version,
        reason=reason,
        now=now,
    )
