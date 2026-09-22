"""Unit tests: capability computation (ADR-0007, D16, Q3, Q17). No database."""

from __future__ import annotations

import pytest

from app.contracts.enums import (
    NEW_BUSINESS_CAPABILITIES,
    OBLIGATION_CAPABILITIES,
    STAFF_ROLE_CAPABILITIES,
    Capability,
    Role,
)
from app.contracts.errors import DomainError, ErrorCode
from app.modules.identity.capabilities import (
    CLIENT_NEW_BUSINESS_CAPABILITIES,
    DRIVER_ACCOUNT_CAPABILITIES,
    DRIVER_NEW_BUSINESS_CAPABILITIES,
    DriverFacts,
    IneligibilityReason,
    compute_capabilities,
    driver_ineligibility_reasons,
    effective_roles,
)
from app.modules.identity.service import CapabilitySet, require_capability

APPROVED = DriverFacts(verification_status="approved")


def caps(roles: set[Role], *, active: bool = True, driver: DriverFacts | None = None) -> frozenset[Capability]:
    return compute_capabilities(roles=frozenset(roles), account_active=active, driver=driver)


def test_client_gets_only_client_new_business() -> None:
    assert caps({Role.CLIENT}) == CLIENT_NEW_BUSINESS_CAPABILITIES


def test_eligible_driver_gets_new_business_and_obligations() -> None:
    result = caps({Role.DRIVER}, driver=APPROVED)
    assert result == DRIVER_NEW_BUSINESS_CAPABILITIES | OBLIGATION_CAPABILITIES


def test_client_and_driver_on_one_account_is_allowed() -> None:
    result = caps({Role.CLIENT, Role.DRIVER}, driver=APPROVED)
    assert NEW_BUSINESS_CAPABILITIES <= result


def test_blocked_driver_with_active_trip_keeps_only_obligations() -> None:
    """D16: block removes new business; trip.operate and tracking.publish stay for the running trip."""
    facts = DriverFacts(verification_status="approved", active_block_reason="fraud review", active_trip_count=1)
    result = caps({Role.DRIVER}, driver=facts)
    assert result == OBLIGATION_CAPABILITIES
    assert Capability.TRIP_OPERATE in result and Capability.TRACKING_PUBLISH in result
    assert not result & NEW_BUSINESS_CAPABILITIES


def test_blocked_driver_without_trip_keeps_only_wallet_capabilities() -> None:
    """Decision 22: wallet view and top-up request stay for any active driver-role account."""
    facts = DriverFacts(verification_status="approved", active_block_reason="fraud review", active_trip_count=0)
    assert caps({Role.DRIVER}, driver=facts) == DRIVER_ACCOUNT_CAPABILITIES


@pytest.mark.parametrize("facts", [DriverFacts(verification_status="pending"), DriverFacts(verification_status=None), None])
def test_unverified_driver_without_trip_can_view_wallet_and_request_topup(facts: DriverFacts | None) -> None:
    assert caps({Role.DRIVER}, driver=facts) == {Capability.WALLET_VIEW_OWN, Capability.WALLET_TOPUP_REQUEST}


def test_wallet_capabilities_need_an_active_account_and_the_driver_role() -> None:
    assert caps({Role.DRIVER}, active=False, driver=None) == frozenset()
    assert not caps({Role.CLIENT}) & DRIVER_ACCOUNT_CAPABILITIES


def test_blocked_driver_keeps_client_capabilities() -> None:
    facts = DriverFacts(verification_status="approved", active_block_reason="x")
    assert caps({Role.CLIENT, Role.DRIVER}, driver=facts) == CLIENT_NEW_BUSINESS_CAPABILITIES | DRIVER_ACCOUNT_CAPABILITIES


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (DriverFacts(verification_status="pending"), IneligibilityReason.NOT_VERIFIED),
        (DriverFacts(verification_status="approved", expired_document_ids=(7,)), IneligibilityReason.DOCUMENT_EXPIRED),
        (DriverFacts(verification_status="approved", active_block_reason="r"), IneligibilityReason.ELIGIBILITY_BLOCKED),
        (DriverFacts(verification_status=None), IneligibilityReason.DRIVER_PROFILE_MISSING),
        (None, IneligibilityReason.DRIVER_PROFILE_MISSING),
    ],
)
def test_ineligibility_reasons(facts: DriverFacts | None, reason: IneligibilityReason) -> None:
    assert reason.value in driver_ineligibility_reasons(account_active=True, facts=facts)
    assert not caps({Role.DRIVER}, driver=facts) & NEW_BUSINESS_CAPABILITIES


def test_suspended_account_has_no_capabilities_even_with_trip() -> None:
    facts = DriverFacts(verification_status="approved", active_trip_count=2)
    assert caps({Role.DRIVER}, active=False, driver=facts) == frozenset()
    assert caps({Role.ADMIN}, active=False) == frozenset()


@pytest.mark.parametrize("role", [Role.OPERATOR, Role.ADMIN, Role.SUPER_ADMIN, Role.FINANCE])
def test_staff_roles_map_to_contract_capabilities(role: Role) -> None:
    assert caps({role}) == STAFF_ROLE_CAPABILITIES[role]


def test_multiple_staff_roles_union() -> None:
    assert caps({Role.OPERATOR, Role.FINANCE}) == STAFF_ROLE_CAPABILITIES[Role.OPERATOR] | STAFF_ROLE_CAPABILITIES[Role.FINANCE]


def test_effective_roles_legacy_primary_plus_activated() -> None:
    assert effective_roles("client", ["driver"]) == {Role.CLIENT, Role.DRIVER}
    assert effective_roles("client", ["client", "unknown"]) == {Role.CLIENT}


@pytest.mark.parametrize("staff", ["operator", "finance"])
def test_effective_roles_q3_violation_trusts_legacy_primary_family(staff: str) -> None:
    """A combination can only come from a legacy v1 write; users.role decides the family."""
    assert effective_roles(staff, ["client", "driver"]) == {Role(staff)}
    assert effective_roles("driver", [staff]) == {Role.DRIVER}


def _capset(roles: set[Role], capabilities: frozenset[Capability], reasons: tuple[str, ...] = ()) -> CapabilitySet:
    return CapabilitySet(
        user_id=1,
        roles=frozenset(roles),
        capabilities=capabilities,
        account_active=True,
        driver=None,
        driver_reasons=reasons,
    )


def test_require_capability_driver_without_eligibility_is_driver_not_eligible() -> None:
    with pytest.raises(DomainError) as info:
        require_capability(_capset({Role.DRIVER}, frozenset(), ("eligibility_blocked",)), Capability.TRIP_CREATE)
    assert info.value.code is ErrorCode.DRIVER_NOT_ELIGIBLE
    assert info.value.details == {"reasons": ["eligibility_blocked"]}


def test_require_capability_without_role_is_capability_required() -> None:
    with pytest.raises(DomainError) as info:
        require_capability(_capset({Role.CLIENT}, CLIENT_NEW_BUSINESS_CAPABILITIES), Capability.TRIP_CREATE)
    assert info.value.code is ErrorCode.CAPABILITY_REQUIRED
