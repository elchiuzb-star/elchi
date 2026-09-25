"""Pure capability and driver-eligibility computation (ADR-0007, D16, Q3).

No I/O: ``service.py`` gathers the facts from the database and calls these
functions, so the rules are unit-testable and identical for every caller.

* ``users.role`` is the legacy primary role; ``user_roles`` adds activated roles.
* Staff and marketplace roles never combine (Q3). A combination can only appear
  through a legacy v1 write, in which case the legacy primary family wins.
* Account suspension (``users.status != 'active'``) removes every capability.
* Losing driver eligibility removes only new-business capabilities; a driver
  with an active trip keeps the obligation capabilities (D16).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.contracts.enums import (
    MARKETPLACE_ROLES,
    NEW_BUSINESS_CAPABILITIES,
    OBLIGATION_CAPABILITIES,
    STAFF_ROLE_CAPABILITIES,
    STAFF_ROLES,
    Capability,
    Role,
    role_combination_allowed,
)

ACTIVE_USER_STATUS = "active"
APPROVED_VERIFICATION_STATUS = "approved"

CLIENT_NEW_BUSINESS_CAPABILITIES: frozenset[Capability] = frozenset(
    {Capability.LISTING_CREATE_REQUEST, Capability.PROPOSAL_SUBMIT_AS_CLIENT}
)
DRIVER_NEW_BUSINESS_CAPABILITIES: frozenset[Capability] = frozenset(
    # Q138 (ADR-0026): LISTING_CREATE_TRIP_OFFER is no longer granted - drivers answer client requests only.
    {Capability.PROPOSAL_SUBMIT_AS_DRIVER, Capability.TRIP_CREATE}
)

# Decision 22 (wave 1.5): any active driver-role account may view its commission wallet and
# request a top-up, even when unverified or blocked and without trips.
DRIVER_ACCOUNT_CAPABILITIES: frozenset[Capability] = frozenset(
    {Capability.WALLET_VIEW_OWN, Capability.WALLET_TOPUP_REQUEST}
)

if CLIENT_NEW_BUSINESS_CAPABILITIES | DRIVER_NEW_BUSINESS_CAPABILITIES != NEW_BUSINESS_CAPABILITIES:  # pragma: no cover
    raise RuntimeError("NEW_BUSINESS_CAPABILITIES changed in app.contracts.enums; update identity.capabilities")


class IneligibilityReason(StrEnum):
    """Module-private reason codes shown in ``CapabilitiesDTO.driver_eligibility.reasons``."""

    DRIVER_PROFILE_MISSING = "driver_profile_missing"
    NOT_VERIFIED = "driver_not_verified"
    ACCOUNT_INACTIVE = "account_inactive"
    ELIGIBILITY_BLOCKED = "eligibility_blocked"
    DOCUMENT_EXPIRED = "document_expired"


@dataclass(frozen=True, slots=True)
class DriverFacts:
    """Everything eligibility depends on, read under one transaction."""

    verification_status: str | None  # None: no driver_profiles row
    active_block_reason: str | None = None
    expired_document_ids: tuple[int, ...] = ()
    active_trip_count: int = 0
    # Non-terminal v2 bookings (A4 ``driver_v2_obligations``): e.g. a parcel ``delivered`` awaiting sender
    # confirmation (Q65), a pending no-show review or custody case after the trip itself is terminal (D16, Q15).
    active_booking_count: int = 0

    @property
    def has_active_obligations(self) -> bool:
        return self.active_trip_count > 0 or self.active_booking_count > 0


def parse_roles(values: Iterable[str | Role | None]) -> frozenset[Role]:
    known = {role.value for role in Role}
    return frozenset(Role(value) for value in values if value is not None and str(value) in known)


def effective_roles(primary_role: str | None, activated_roles: Iterable[str]) -> frozenset[Role]:
    """Legacy primary role plus active ``user_roles`` rows, Q3-consistent."""
    primary = next(iter(parse_roles([primary_role])), None)
    roles = parse_roles([primary_role, *activated_roles])
    if role_combination_allowed(roles):
        return roles
    # Only reachable through a legacy write that bypassed user_roles; trust users.role.
    family = STAFF_ROLES if primary in STAFF_ROLES else MARKETPLACE_ROLES
    return frozenset(role for role in roles if role in family)


def driver_ineligibility_reasons(*, account_active: bool, facts: DriverFacts | None) -> list[str]:
    if facts is None or facts.verification_status is None:
        reasons = [IneligibilityReason.DRIVER_PROFILE_MISSING.value]
        if not account_active:
            reasons.append(IneligibilityReason.ACCOUNT_INACTIVE.value)
        return reasons
    reasons: list[str] = []
    if not account_active:
        reasons.append(IneligibilityReason.ACCOUNT_INACTIVE.value)
    if facts.verification_status != APPROVED_VERIFICATION_STATUS:
        reasons.append(IneligibilityReason.NOT_VERIFIED.value)
    if facts.active_block_reason is not None:
        reasons.append(IneligibilityReason.ELIGIBILITY_BLOCKED.value)
    if facts.expired_document_ids:
        reasons.append(IneligibilityReason.DOCUMENT_EXPIRED.value)
    return reasons


def compute_capabilities(
    *, roles: frozenset[Role], account_active: bool, driver: DriverFacts | None
) -> frozenset[Capability]:
    if not account_active:
        return frozenset()
    capabilities: set[Capability] = set()
    for role in roles & STAFF_ROLES:
        capabilities |= STAFF_ROLE_CAPABILITIES[role]
    if Role.CLIENT in roles:
        capabilities |= CLIENT_NEW_BUSINESS_CAPABILITIES
    if Role.DRIVER in roles:
        capabilities |= DRIVER_ACCOUNT_CAPABILITIES
        if not driver_ineligibility_reasons(account_active=True, facts=driver):
            capabilities |= DRIVER_NEW_BUSINESS_CAPABILITIES | OBLIGATION_CAPABILITIES
        elif driver is not None and driver.has_active_obligations:
            capabilities |= OBLIGATION_CAPABILITIES
    return frozenset(capabilities)
