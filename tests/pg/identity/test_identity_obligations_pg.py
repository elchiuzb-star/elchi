"""D16/Q15 on PostgreSQL: a blocked driver keeps obligation capabilities while a v2 booking is non-terminal,
even after the trip itself is completed (parcel ``delivered`` awaiting sender confirmation, Q65)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.identity import service as identity_service
from app.modules.identity.capabilities import (
    DRIVER_ACCOUNT_CAPABILITIES,
    DRIVER_NEW_BUSINESS_CAPABILITIES,
    OBLIGATION_CAPABILITIES,
)
from tests.pg.bookings.conftest import (  # noqa: F401  (bw fixture)
    BW,
    accept,
    act,
    bw,
    operator,
    driver_trip,
    parcel_request_body,
    propose,
    publish_listing,
    run_trip_action,
)

pytestmark = pytest.mark.pg


def test_blocked_driver_keeps_obligations_for_a_delivered_parcel_after_trip_completion(bw: BW) -> None:
    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01O150AA")
    booking = accept(
        bw,
        propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000, dropoff="C", price_basis="total"),
        bw.w.client_id,
    )
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    run_trip_action(bw, trip_id, bw.w.driver_id, "depart", now=bw.base + timedelta(minutes=5))  # Q142: in transit
    delivered = operator(bw, booking.id, bw.operator_id, "mark_delivered", now=bw.base + timedelta(hours=2),
                         reason="receiver confirmed to support")  # Q139: staff record the outcome
    assert delivered.service_status == "delivered"
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "complete", now=bw.base + timedelta(hours=4)) == "completed"

    with bw.db.session() as s:
        identity_service.block_driver_eligibility(
            s, driver_user_id=bw.w.driver_id, actor_user_id=bw.w.admin_id, expected_version=1, reason="document review"
        )
        s.commit()
    with bw.db.session() as s:
        caps = identity_service.get_capabilities(s, bw.w.driver_id)
    assert caps.driver is not None and caps.driver.active_trip_count == 0 and caps.driver.active_booking_count == 1
    assert caps.driver.has_active_obligations and not caps.driver_eligible
    assert OBLIGATION_CAPABILITIES <= caps.capabilities
    assert not (DRIVER_NEW_BUSINESS_CAPABILITIES - OBLIGATION_CAPABILITIES) & caps.capabilities

    with bw.db.session() as s:  # control: the other blocked driver without v2 business has no obligation capabilities
        identity_service.block_driver_eligibility(
            s, driver_user_id=bw.w.driver2_id, actor_user_id=bw.w.admin_id, expected_version=1, reason="document review"
        )
        s.commit()
        other = identity_service.get_capabilities(s, bw.w.driver2_id)
    # wallet view/top-up stay open for any active driver account (Q22); trip/tracking obligations do not
    assert not other.driver.has_active_obligations
    assert not ((OBLIGATION_CAPABILITIES - DRIVER_ACCOUNT_CAPABILITIES) & other.capabilities)
