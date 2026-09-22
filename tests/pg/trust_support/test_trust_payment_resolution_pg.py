"""Payment dispute resolution drives A4 ``resolve_contested_cash_receipt`` (STATE_MACHINES §6, §8; AC26) and keeps U8.

Wave 3.1: closing a dispute is admin+ (v1 Q13/Q38 parity) and carries the cash outcome as its own command field.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking, CashReceipt
from app.modules.trust_support import service as trust_service
from tests.pg.trust_support.conftest import BW, arrived_passenger, captures, complete, dispute_command, rows, scalar

pytestmark = pytest.mark.pg


def _contest(bw: BW, booking: Booking, client_id: int, driver_id: int) -> str:
    with bw.db.session() as s:
        current = s.get(Booking, booking.id)
        _, receipt = bookings_service.report_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(current), actor_user_id=driver_id,
            expected_version=current.version, amount_minor=current.total_minor, reported_at=bw.base + timedelta(hours=3),
            now=bw.base + timedelta(hours=3),
        )
        receipt_public = format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id)
        s.commit()
    with bw.db.session() as s:
        current = s.get(Booking, booking.id)
        receipt = s.execute(select(CashReceipt).where(CashReceipt.booking_id == booking.id)).scalar_one()
        _, contested = bookings_service.contest_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(current), receipt_public_id=receipt_public,
            actor_user_id=client_id, expected_version=receipt.version, comment="Pul berilmadi",
            now=bw.base + timedelta(hours=3, minutes=1),
        )
        dispute = s.get(trust_service.DisputeV2, contested.dispute_id)
        public = trust_service.dispute_public_id(dispute)
        s.commit()
        return public


def _queue(bw: BW) -> list[int]:
    with bw.db.session() as s:
        return [b.id for b in bookings_service.admin_queue(s, actor_user_id=bw.finance_id, queue="finance_review",
                                                           corridor_id=None, after_id=None, limit=50)]


def test_paid_confirmed_acknowledges_cash_and_hands_held_fee_to_finance(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T600AA")
    dispute = _contest(bw, booking, bw.w.client_id, bw.w.driver_id)
    assert complete(bw, booking).commission_status == "held"  # open payment dispute delays capture
    before = captures(bw)
    done = dispute_command(bw, dispute, bw.w.admin_id, "resolve", resolution_code="paid_confirmed", resolution_text="driver receipt ok")
    assert done.status == "resolved"
    row = rows(bw.db, "SELECT service_status, cash_status, commission_status FROM bookings WHERE id = :b", b=booking.id)[0]
    assert (row.service_status, row.cash_status, row.commission_status) == ("completed", "acknowledged", "held")
    assert scalar(bw.db, "SELECT status FROM cash_receipts WHERE booking_id = :b", b=booking.id) == "resolved_paid"
    assert _queue(bw) == [booking.id] and captures(bw) == before  # U8 kept: no automatic capture


def test_unpaid_confirmed_returns_cash_to_unpaid_service_unchanged(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T601AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    dispute = _contest(bw, booking, bw.w.client2_id, bw.w.driver2_id)
    dispute_command(bw, dispute, bw.w.admin_id, "resolve", resolution_code="unpaid_confirmed")
    row = rows(bw.db, "SELECT service_status, cash_status FROM bookings WHERE id = :b", b=booking.id)[0]
    assert (row.service_status, row.cash_status) == ("arrived", "unpaid")
    assert scalar(bw.db, "SELECT status FROM cash_receipts WHERE booking_id = :b", b=booking.id) == "resolved_unpaid"


def test_version_conflict_rolls_back_and_a_close_needs_an_explicit_cash_outcome(bw: BW, hooks) -> None:  # noqa: ANN001
    from app.contracts.errors import DomainError, ErrorCode

    booking = arrived_passenger(bw, "01T602AA")
    dispute = _contest(bw, booking, bw.w.client_id, bw.w.driver_id)
    with pytest.raises(DomainError) as info:
        dispute_command(bw, dispute, bw.w.admin_id, "resolve", expected_version=7, resolution_code="paid_confirmed")
    assert info.value.code is ErrorCode.VERSION_CONFLICT
    assert scalar(bw.db, "SELECT cash_status FROM bookings WHERE id = :b", b=booking.id) == "contested"  # rolled back

    # wave 3.1: a resolution code that implies nothing may not leave the receipt contested with no dispute left
    with pytest.raises(DomainError) as info:
        dispute_command(bw, dispute, bw.w.admin_id, "resolve", resolution_code="no_action")
    assert info.value.code is ErrorCode.VALIDATION_ERROR and info.value.details["field"] == "cash_outcome"
    # ... and an explicit outcome may not contradict the code
    with pytest.raises(DomainError) as info:
        dispute_command(bw, dispute, bw.w.admin_id, "resolve", resolution_code="paid_confirmed", cash_outcome="unpaid")
    assert info.value.details == {"field": "cash_outcome", "resolution_code": "paid_confirmed", "implied": "paid"}
    assert scalar(bw.db, "SELECT cash_status FROM bookings WHERE id = :b", b=booking.id) == "contested"

    dispute_command(bw, dispute, bw.w.admin_id, "resolve", resolution_code="no_action", cash_outcome="unpaid")
    assert scalar(bw.db, "SELECT cash_status FROM bookings WHERE id = :b", b=booking.id) == "unpaid"
    assert scalar(bw.db, "SELECT status FROM cash_receipts WHERE booking_id = :b", b=booking.id) == "resolved_unpaid"
    assert scalar(bw.db, "SELECT details->>'cash_outcome' FROM audit_logs WHERE action = 'dispute_resolve' "
                         "ORDER BY id DESC LIMIT 1") == "unpaid"


def test_only_admin_and_above_close_a_dispute(bw: BW, hooks) -> None:  # noqa: ANN001
    """Wave 3.1 (v1 Q13/Q38 parity): the operator reviews and comments; resolve/reject is admin+."""
    from app.contracts.errors import DomainError, ErrorCode

    booking = arrived_passenger(bw, "01T603AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    dispute = _contest(bw, booking, bw.w.client2_id, bw.w.driver2_id)
    started = dispute_command(bw, dispute, bw.operator_id, "start_review", reason="mijoz bilan gaplashdim")
    assert started.status == "under_review"
    assert scalar(bw.db, "SELECT details->>'note' FROM audit_logs WHERE action = 'dispute_start_review' "
                         "ORDER BY id DESC LIMIT 1") == "mijoz bilan gaplashdim"
    with pytest.raises(DomainError) as info:
        dispute_command(bw, dispute, bw.operator_id, "resolve", resolution_code="unpaid_confirmed")
    assert info.value.code is ErrorCode.CAPABILITY_REQUIRED
    assert info.value.details["capability"] == "ops.dispute_decide"
    with pytest.raises(DomainError) as info:
        dispute_command(bw, dispute, bw.operator_id, "reject", reason="asossiz")
    assert info.value.code is ErrorCode.CAPABILITY_REQUIRED
    assert scalar(bw.db, "SELECT status FROM disputes_v2 WHERE booking_id = :b", b=booking.id) == "under_review"
    assert dispute_command(bw, dispute, bw.w.admin_id, "resolve", resolution_code="unpaid_confirmed").status == "resolved"
