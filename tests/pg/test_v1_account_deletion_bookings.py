"""v1 account deletion vs v2 bookings (H1 wiring of A4's N4 check, ADR-0006 D5).

Deletion refuses with 409 ACTIVE_BOOKINGS_EXIST while the account has an open v2
booking as client or driver; completed/cancelled bookings do not block. Accept
and deletion both start with the users row lock (accept FOR NO KEY UPDATE, deletion
FOR UPDATE), so they serialize: either the booking exists and deletion is refused,
or deletion committed first and accept fails.

Builds on A4's fixtures and helpers (tests/pg/bookings/conftest.py, not edited).
"""

from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError
from app.models import User
from app.modules.bookings import service as bookings_service
from app.modules.trips import service as trips_service
from app.services import account_deletion_service
from app.services.account_deletion_service import delete_own_account
from tests.pg.bookings.conftest import (  # noqa: F401  (bw, world, lock_clock are fixtures)
    BW,
    STAGGER_S,
    USERS_LOCK,
    accept,
    act,
    bw,
    codes_for,
    hold_inside,
    listing_version,
    lock_clock,
    operator,
    request_with_driver_proposal,
    run_trip_action,
    scalar,
    world,
)
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg

BOOKINGS_MESSAGE = "Tugallanmagan safar yoki jo'natma bronlaringiz bor. Ular yakunlangach hisobni o'chirish mumkin"


def delete_account(bw: BW, user_id: int):  # noqa: ANN201
    with bw.db.session() as s:
        return delete_own_account(s, s.get(User, user_id))


def assert_bookings_refusal(result, *, as_client: int, as_driver: int) -> None:  # noqa: ANN001
    assert isinstance(result, JSONResponse) and result.status_code == 409
    body = json.loads(result.body)
    # Same v1 error envelope as ACTIVE_DISPUTES_EXIST / WALLET_BALANCE_EXISTS; only the code differs.
    assert set(body) == {"success", "error"} and body["success"] is False
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == "ACTIVE_BOOKINGS_EXIST"
    assert body["error"]["message"] == BOOKINGS_MESSAGE
    details = body["error"]["details"]
    assert details["active_bookings_as_client"] == as_client
    assert details["active_bookings_as_driver"] == as_driver
    assert details["active_bookings"] == as_client + as_driver


def user_status(bw: BW, user_id: int) -> str:
    return scalar(bw.db, "SELECT status FROM users WHERE id = :u", u=user_id)


def test_client_with_confirmed_v2_booking_cannot_delete_account(bw: BW) -> None:
    _listing, _trip_id, _trip, ref = request_with_driver_proposal(bw, plate="01H100AA")
    booking = accept(bw, ref, bw.w.client_id)
    assert booking.service_status == "confirmed"

    assert_bookings_refusal(delete_account(bw, bw.w.client_id), as_client=1, as_driver=0)
    assert user_status(bw, bw.w.client_id) == "active"


def test_driver_with_active_v2_booking_cannot_delete_account(bw: BW) -> None:
    _listing, _trip_id, _trip, ref = request_with_driver_proposal(bw, plate="01H200AA")
    accept(bw, ref, bw.w.client_id)

    # The bookings check runs before the wallet check, so the funded wallet does not mask it.
    assert_bookings_refusal(delete_account(bw, bw.w.driver_id), as_client=0, as_driver=1)
    assert user_status(bw, bw.w.driver_id) == "active"


def _complete_passenger_booking(bw: BW, plate: str):  # noqa: ANN202
    _listing, trip_id, _trip, ref = request_with_driver_proposal(bw, plate=plate)
    booking = accept(bw, ref, bw.w.client_id)
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30)) == "boarding"
    code = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    act(bw, booking.id, bw.w.driver_id, "board", code=code, now=bw.base + timedelta(minutes=5))
    act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    return act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))


def test_completed_booking_with_held_commission_blocks_deletion_until_finalized(bw: BW) -> None:
    """Q74 (no A12 probe): a completed booking keeps its commission held for finance review. A held commission is an open
    money obligation (N4 ``held_commission_bookings``), so deletion is refused; after ``finalize_fee`` it is allowed."""
    final = _complete_passenger_booking(bw, "01H300AA")
    assert (final.service_status, final.commission_status) == ("completed", "held")

    refused = delete_account(bw, bw.w.client_id)
    assert_bookings_refusal(refused, as_client=0, as_driver=0)
    assert json.loads(refused.body)["error"]["details"]["held_commission_bookings"] == 1
    assert user_status(bw, bw.w.client_id) == "active"

    finalized = operator(bw, final.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="no dispute")
    assert finalized.commission_status == "captured"
    result = delete_account(bw, bw.w.client_id)
    assert isinstance(result, dict) and result["deleted"] is True, result
    assert user_status(bw, bw.w.client_id) == "deleted"


def test_completed_booking_with_a12_hooks_captures_at_completion_and_does_not_block_deletion(bw: BW) -> None:
    from app.modules.trust_support import service as trust_service

    trust_service.register_booking_hooks()  # A12 probe registered: no open dispute -> clear -> capture at completion
    try:
        final = _complete_passenger_booking(bw, "01H310AA")
        assert (final.service_status, final.commission_status, final.finance_review_reason) == ("completed", "captured", None)
        result = delete_account(bw, bw.w.client_id)
        assert isinstance(result, dict) and result["deleted"] is True, result
        assert user_status(bw, bw.w.client_id) == "deleted"
    finally:
        bookings_service.set_blocking_dispute_probe(None)
        bookings_service.set_payment_dispute_opener(None)


@pytest.mark.parametrize("end_state", ["cancelled"])
def test_completed_or_cancelled_booking_does_not_block_deletion(bw: BW, end_state: str) -> None:
    _listing, trip_id, _trip, ref = request_with_driver_proposal(bw, plate="01H320AA")
    booking = accept(bw, ref, bw.w.client_id)
    if end_state == "completed":  # pragma: no cover - see the two held/hooks tests above (Q74)
        raise AssertionError("covered by the Q74 tests")
    else:
        with bw.db.session() as s:
            final = bookings_service.cancel_booking(
                s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
                expected_version=1, reason_code="plans_changed",
            )
            s.commit()
    assert final.service_status == end_state

    result = delete_account(bw, bw.w.client_id)

    assert isinstance(result, dict) and result["deleted"] is True, result
    assert user_status(bw, bw.w.client_id) == "deleted"


def run_accept_vs_deletion(bw: BW, *, client_id: int, driver_id: int, plate: str, accept_first: bool, clock=None):  # noqa: ANN001, ANN201
    _listing, _trip_id, _trip, ref = request_with_driver_proposal(bw, plate=plate, client_id=client_id, driver_id=driver_id)
    expected = listing_version(bw, ref.listing_id)
    early = 1 if accept_first else 0

    def work(index: int, session: Session):  # noqa: ANN202
        if clock is not None:
            clock.bind(index)
        if index != early:
            time.sleep(STAGGER_S)
        if index == 0:
            return delete_own_account(session, session.get(User, client_id))
        try:
            return accept(bw, ref, client_id, session=session, expected_listing_version=expected)
        except DomainError as exc:  # a refused accept is a valid outcome, not a crash
            return exc

    return early, run_concurrently(2, work, engine=bw.db.engine)


def test_accept_vs_client_account_deletion_is_consistent(bw: BW, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:  # noqa: F811
    hold_inside(monkeypatch, account_deletion_service, "blocking_disputes")  # deletion: inside orders/users/profile locks
    hold_inside(monkeypatch, trips_service, "lock_trip")  # accept: right after its users lock
    clock = lock_clock(USERS_LOCK)
    seen: set[str] = set()
    rounds = [
        (bw.w.client_id, bw.w.driver_id, "01H400AA", True),
        (bw.w.client2_id, bw.w.driver2_id, "01H500AA", False),
    ]
    for client_id, driver_id, plate, accept_first in rounds:
        clock.reset()
        early, report = run_accept_vs_deletion(bw, client_id=client_id, driver_id=driver_id, plate=plate, accept_first=accept_first, clock=clock)

        assert report.failures == [], [f"worker {r.index}: {r.error!r}" for r in report.failures]
        clock.assert_waited(early=early, late=1 - early)
        deletion, accepted = report.results[0].value, report.results[1].value
        bookings = scalar(bw.db, "SELECT count(*) FROM bookings WHERE client_user_id = :c", c=client_id)
        if isinstance(accepted, DomainError):
            seen.add("delete_first")
            assert isinstance(deletion, dict) and deletion["deleted"] is True, deletion
            assert user_status(bw, client_id) == "deleted" and bookings == 0
        else:
            seen.add("accept_first")
            assert bookings == 1 and user_status(bw, client_id) == "active"
            assert_bookings_refusal(deletion, as_client=1, as_driver=0)
    assert seen == {"accept_first", "delete_first"}


def test_negative_control_deletion_without_bookings_check_deletes_account_with_open_booking(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bookings_service, "blocking_state_for_user", lambda session, user_id, *, lock=False: bookings_service.BookingBlockingState(0, 0, 0, 0, 0))
    hold_inside(monkeypatch, trips_service, "lock_trip")  # accept holds the users lock, deletion queues behind it
    _early, report = run_accept_vs_deletion(bw, client_id=bw.w.client_id, driver_id=bw.w.driver_id, plate="01H600AA", accept_first=True)

    assert report.failures == []
    open_bookings = scalar(bw.db, "SELECT count(*) FROM bookings WHERE client_user_id = :c AND service_status = 'confirmed'", c=bw.w.client_id)
    # Without the check the invariant breaks: the account is deleted while its booking is still open.
    assert user_status(bw, bw.w.client_id) == "deleted" and open_bookings == 1, (
        "negative control did not reproduce: the test would not detect a missing bookings check"
    )
