"""ADR-0026 follow-up on real PostgreSQL (Q144, Q145, Q138 + Q40).

* Q144: a parcel completed by staff never captures by itself - the commission stays held in the finance queue and only
  `finalize_fee` (`finance.fee_finalize`) captures it; an operator cannot. Repeated taps, parallel commands and HTTP
  retries end in one completion and one capture; the audit row says what the completion was based on.
* Q145: before a booking the client may change a request's seat count (open offers expire, an old offer cannot be
  accepted for the new count); after it, the quantity is not amendable and the DTO says so.
* Q138 + Q40: the request owner compares the answers by the anonymous set (vehicle class, seats, rating group);
  the driver side never gets it and nothing identifies the driver before accept.
SYNTHETIC people and amounts.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingPatch
from app.modules.marketplace.views import thread_dto
from tests.pg.bookings.conftest import (
    BW,
    accept,
    auth,
    booked,
    domain_error,
    driver_trip,
    legacy_offer_booking,
    operator,
    parcel_request_body,
    passenger_request_body,
    propose,
    publish_listing,
    rows,
    run_trip_action,
    scalar,
    view,
)
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg


def _captures(bw: BW, booking_id: int) -> int:
    return int(scalar(bw.db, "SELECT count(*) FROM ledger_transactions WHERE booking_id = :b AND reference_kind = 'commission_capture'",
                      b=booking_id))


def _parcel_delivered(bw: BW, plate: str, *, driver_id: int | None = None) -> Booking:
    driver_id = driver_id or bw.w.driver_id
    listing = publish_listing(bw, bw.w.client_id, parcel_request_body(bw))
    trip_id, trip_public = driver_trip(bw, driver_id, plate)
    booking = accept(bw, propose(bw, listing, driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000,
                                 dropoff="C", price_basis="total"), bw.w.client_id)
    run_trip_action(bw, trip_id, driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    run_trip_action(bw, trip_id, driver_id, "depart", now=bw.base + timedelta(minutes=5))
    return operator(bw, booking.id, bw.operator_id, "mark_delivered", now=bw.base + timedelta(hours=2),
                    reason="receiver confirmed in the support chat")


@pytest.fixture
def probe_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """The running app registers the dispute probe (app.api.v2.router); here it answers "no dispute"."""
    monkeypatch.setattr(bookings_service, "_blocking_dispute_probe", lambda session, booking_id: False)


def test_staff_parcel_completion_goes_to_finance_and_only_finance_captures(bw: BW, probe_clear) -> None:  # noqa: ANN001
    booking = _parcel_delivered(bw, "01F100AA")
    done = operator(bw, booking.id, bw.operator_id, "complete_with_evidence", now=bw.base + timedelta(hours=3),
                    reason="receiver confirmed in the support chat; delivery photo on file")
    assert (done.service_status, done.commission_status, done.finance_review_reason) == ("completed", "held", "parcel_staff_completion")
    assert _captures(bw, booking.id) == 0  # an operator command moved no money, even with the dispute probe clear
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'commission.finance_review_required'") == 1
    refused = domain_error(lambda: operator(bw, booking.id, bw.operator_id, "finalize_fee", fee_mode="capture"))
    assert refused.code is ErrorCode.FORBIDDEN  # Q17: capture is finance.fee_finalize
    captured = operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture", reason="parcel completion reviewed")
    assert captured.commission_status == "captured" and _captures(bw, booking.id) == 1
    audit = rows(bw.db, "SELECT action, details FROM audit_logs WHERE action = 'booking_complete_with_evidence'")
    assert len(audit) == 1
    basis = audit[0].details
    assert basis["reason"].startswith("receiver confirmed") and basis["service_status_from"] == "delivered"
    assert basis["service_status_to"] == "completed" and basis["commission_status"] == "held" and basis["evidence_file_ids"] == []


def test_passenger_completion_by_the_client_still_captures_on_its_own(bw: BW, probe_clear) -> None:  # noqa: ANN001
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01F101AA")
    booking = booked(bw, trip_public, bw.w.client_id)
    from tests.pg.bookings.conftest import act, codes_for

    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    act(bw, booking.id, bw.w.driver_id, "board", code=codes_for(bw, booking.id, bw.w.client_id)["boarding_code"], now=bw.base)
    act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    done = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=5))
    assert (done.commission_status, done.finance_review_reason) == ("captured", None)  # unchanged passenger rule


def test_parallel_completion_and_parallel_finalize_end_in_one_completion_and_one_capture(bw: BW, probe_clear) -> None:  # noqa: ANN001
    booking = _parcel_delivered(bw, "01F102AA")
    version = scalar(bw.db, "SELECT version FROM bookings WHERE id = :b", b=booking.id)
    public = bookings_service.booking_public_id(booking)

    def complete(index: int, session: Session) -> str:
        bookings_service.operator_command(session, booking_public_id_value=public, actor_user_id=bw.operator_id,
                                          command="complete_with_evidence", expected_version=version,
                                          reason=f"completion tap {index}")
        session.commit()
        return "completed"

    report = run_concurrently(5, complete, engine=bw.db.engine)
    assert len(report.successes) == 1, report.results
    assert all(isinstance(r.error, DomainError) and r.error.code in (ErrorCode.VERSION_CONFLICT, ErrorCode.INVALID_STATE_TRANSITION)
               for r in report.failures), report.failures
    assert scalar(bw.db, "SELECT count(*) FROM booking_status_history WHERE booking_id = :b AND to_status = 'completed'",
                  b=booking.id) == 1
    version = scalar(bw.db, "SELECT version FROM bookings WHERE id = :b", b=booking.id)

    def finalize(index: int, session: Session) -> str:
        bookings_service.operator_command(session, booking_public_id_value=public, actor_user_id=bw.finance_id,
                                          command="finalize_fee", expected_version=version, fee_mode="capture",
                                          reason=f"finance tap {index}")
        session.commit()
        return "captured"

    report = run_concurrently(5, finalize, engine=bw.db.engine)
    assert len(report.successes) == 1, report.results
    assert _captures(bw, booking.id) == 1
    assert scalar(bw.db, "SELECT count(*) FROM wallet_holds WHERE booking_id = :b AND status = 'captured'", b=booking.id) == 1


def test_an_http_retry_of_the_completion_replays_the_first_answer(bw: BW, client, probe_clear) -> None:  # noqa: ANN001
    booking = _parcel_delivered(bw, "01F103AA")
    public = bookings_service.booking_public_id(booking)
    version = scalar(bw.db, "SELECT version FROM bookings WHERE id = :b", b=booking.id)
    url = f"/api/v2/admin/bookings/{public}/commands/complete_with_evidence"
    body = {"expected_version": version, "reason": "receiver confirmed in the support chat"}
    first = client.post(url, json=body, headers=auth(bw.operator_id, "operator", "adr26-complete-0001"))
    assert first.status_code == 200, first.text
    again = client.post(url, json=body, headers=auth(bw.operator_id, "operator", "adr26-complete-0001"))
    assert again.status_code == 200 and again.json()["data"]["version"] == first.json()["data"]["version"]
    assert scalar(bw.db, "SELECT count(*) FROM booking_status_history WHERE booking_id = :b AND to_status = 'completed'",
                  b=booking.id) == 1
    assert _captures(bw, booking.id) == 0


def test_closing_the_support_chat_is_not_completion(bw: BW, probe_clear) -> None:  # noqa: ANN001
    from app.modules.trust_support import threads

    booking = _parcel_delivered(bw, "01F104AA")
    public = bookings_service.booking_public_id(booking)
    with bw.db.session() as s:
        thread, _ = threads.open_or_get_thread(s, booking_public_id_value=public, actor_user_id=bw.w.client_id,
                                               text_value="Yetib keldi, rahmat", warnings=[], filter_hits=[])
        s.commit()
        thread_id, version = threads.thread_public_id(thread), thread.version
    with bw.db.session() as s:
        threads.staff_command(s, thread_public_id_value=thread_id, actor_user_id=bw.operator_id, command="close",
                              expected_version=version, text_value="Hal qilindi", assignee_user_id=None)
        s.commit()
    assert rows(bw.db, "SELECT service_status, commission_status, completed_at FROM bookings WHERE id = :b", b=booking.id) == [
        ("delivered", "held", None)]


# --- Q145: the quantity before and after a booking -------------------------------------------------------------------


def test_seats_change_before_a_booking_expires_old_offers_and_is_fixed_after_it(bw: BW) -> None:
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=2))
    _, trip_public = driver_trip(bw, bw.w.driver_id, "01F110AA", seats=4)
    old = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=2)
    with bw.db.session() as s:
        current = marketplace_service.get_listing_by_public_id(s, listing)
        marketplace_service.patch_listing(s, listing_public_id=listing, actor_user_id=bw.w.client_id, data=ListingPatch.model_validate(
            {"expected_version": current.version, "passenger": {"seat_count": 3, "adults": 3}}))
        s.commit()
    stale = domain_error(lambda: accept(bw, old, bw.w.client_id))
    assert stale.code in (ErrorCode.PROPOSAL_CHANGED, ErrorCode.INVALID_STATE_TRANSITION)  # no old offer stretched to 3 people
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0
    fresh = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=3)
    booking = accept(bw, fresh, bw.w.client_id)
    assert booking.quantity == 3
    assert view(bw, booking.id, "client")["quantity_amendable"] is False
    with bw.db.session() as s:
        refused = domain_error(lambda: bookings_service.create_amendment(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            expected_version=booking.version, changes={"quantity": 2}, reason="one fewer"))
    assert refused.code is ErrorCode.QUANTITY_MISMATCH
    with bw.db.session() as s:  # the price may still be amended by agreement
        bookings_service.create_amendment(s, booking_public_id_value=bookings_service.booking_public_id(booking),
                                          actor_user_id=bw.w.client_id, expected_version=booking.version,
                                          changes={"unit_price_minor": 18_000_000}, reason="agreed discount")
        s.commit()


def test_the_quantity_flag_follows_the_rule(bw: BW) -> None:
    _, trip_public = driver_trip(bw, bw.w.driver_id, "01F111AA", seats=3)
    legacy = legacy_offer_booking(bw, trip_public, bw.w.client_id)
    assert view(bw, legacy.id, "client")["quantity_amendable"] is True  # D10 stays for pre-Q138 offer bookings
    parcel = _parcel_delivered(bw, "01F112AA", driver_id=bw.w.driver2_id)  # another driver: one trip per time slot
    assert view(bw, parcel.id, "driver")["quantity_amendable"] is False


# --- Q138 + Q40: what the client compares -------------------------------------------------------------------------


def test_the_request_owner_compares_drivers_by_the_anonymous_set_only(bw: BW) -> None:
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=2))
    _, trip_public = driver_trip(bw, bw.w.driver_id, "01F120AA", seats=4)
    ref = propose(bw, listing, bw.w.driver_id, trip_public_id=trip_public, quantity=2)
    with bw.db.session() as s:
        thread = marketplace_service.get_thread_by_public_id(s, ref.thread_id)
        owner = thread_dto(s, thread, viewer_user_id=bw.w.client_id).model_dump(mode="json")
        driver = thread_dto(s, thread, viewer_user_id=bw.w.driver_id).model_dump(mode="json")
    summary = owner["driver_summary"]
    assert summary["seat_capacity"] == 4 and summary["vehicle_class"]
    # a new driver: the honest "new, verified" group with zero ratings - never an invented score (§8.2, AC36)
    assert summary["rating_bucket"] == "new_verified" and summary["rating_count"] == 0
    assert driver["driver_summary"] is None
    party = owner["driver"]
    assert (party["id"], party["display_name"]) == (None, None) and party["label"].startswith("Haydovchi")
    dumped = str(owner)
    assert "01F120AA" not in dumped and "+998" not in dumped  # no plate or phone before accept (Q43)
