"""D16/Q15: non-terminal v2 bookings are obligations even without an active trip."""

from __future__ import annotations

from app.contracts.enums import Role
from app.modules.identity.capabilities import (
    DRIVER_NEW_BUSINESS_CAPABILITIES,
    OBLIGATION_CAPABILITIES,
    DriverFacts,
    compute_capabilities,
)


def test_blocked_driver_with_open_booking_keeps_only_obligation_capabilities() -> None:
    facts = DriverFacts(verification_status="approved", active_block_reason="review", active_trip_count=0, active_booking_count=1)
    assert facts.has_active_obligations
    caps = compute_capabilities(roles=frozenset({Role.DRIVER}), account_active=True, driver=facts)
    assert OBLIGATION_CAPABILITIES <= caps
    assert not (DRIVER_NEW_BUSINESS_CAPABILITIES - OBLIGATION_CAPABILITIES) & caps


def test_no_trip_and_no_booking_means_no_obligations() -> None:
    assert not DriverFacts(verification_status="approved", active_block_reason="review").has_active_obligations
