"""Q45 strikes, review queue and cancellation signals on PostgreSQL 16 (STATE_MACHINES §12.1)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import DBAPIError

from app.contracts.communications import ChatActivitySummary, DispatchedEvent
from app.contracts.enums import EventType
from app.contracts.errors import ErrorCode
from app.contracts.events import EventAudience, payload_for_audience
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.trust_support import service as trust_service
from app.modules.trust_support.consumers import cancellation_signals, contact_filter_strikes
from tests.pg.bookings.conftest import accept, driver_trip, passenger_request_body, propose, publish_listing
from tests.pg.trust_support.conftest import BW, consume, domain_error, hit_event, rows, scalar

pytestmark = pytest.mark.pg


def _reviews(bw: BW, signal: str) -> list:
    return rows(bw.db, "SELECT id, public_id, subject_user_id, status, evidence, signal_count, version FROM trust_review_items "
                       "WHERE signal_type = :s ORDER BY id", s=signal)


def test_duplicate_hit_one_strike_three_strikes_one_review(bw: BW) -> None:
    user = bw.w.driver_id
    t0 = utc_now()
    first = hit_event(bw, user, t0)
    consume(bw, contact_filter_strikes, first)
    consume(bw, contact_filter_strikes, first)  # redelivered: no second hit row
    assert scalar(bw.db, "SELECT count(*) FROM contact_filter_hits") == 1
    assert scalar(bw.db, "SELECT count(*) FROM contact_strikes") == 0  # first hit in the window is a warning only

    second = hit_event(bw, user, t0 + timedelta(minutes=1))
    consume(bw, contact_filter_strikes, second)
    consume(bw, contact_filter_strikes, second)
    assert scalar(bw.db, "SELECT count(*) FROM contact_strikes") == 1
    for minute in (2, 3):
        consume(bw, contact_filter_strikes, hit_event(bw, user, t0 + timedelta(minutes=minute)))
    reviews = _reviews(bw, "contact_filter_strikes")
    assert len(reviews) == 1 and reviews[0].subject_user_id == user and reviews[0].status == "open"
    assert reviews[0].evidence["strike_count"] == 3 and len(reviews[0].evidence["source_event_ids"]) == 3
    assert set(reviews[0].evidence) <= {"source_event_ids", "strike_count", "hit_count", "window_days"}
    consume(bw, contact_filter_strikes, hit_event(bw, user, t0 + timedelta(minutes=4)))
    reviews = _reviews(bw, "contact_filter_strikes")
    assert len(reviews) == 1 and reviews[0].evidence["strike_count"] == 4 and reviews[0].signal_count == 2
    strike_events = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'trust.contact_strike.recorded' ORDER BY id")
    assert [e.payload["strike_count"] for e in strike_events] == [1, 2, 3, 4]
    assert payload_for_audience(EventType.CONTACT_STRIKE_RECORDED, strike_events[0].payload, EventAudience.CLIENT) is None
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'trust.review.opened'") == 1
    # hits older than the 7-day window do not count: a lone hit a week later is free again
    consume(bw, contact_filter_strikes, hit_event(bw, bw.w.client_id, t0 - timedelta(days=10)))
    consume(bw, contact_filter_strikes, hit_event(bw, bw.w.client_id, t0))
    assert scalar(bw.db, "SELECT count(*) FROM contact_strikes WHERE user_id = :u", u=bw.w.client_id) == 0
    for statement in ("UPDATE contact_strikes SET reason_code = 'contact_filter'", "DELETE FROM contact_strikes"):
        with pytest.raises(DBAPIError) as info:
            with bw.db.engine.begin() as conn:
                conn.exec_driver_sql(statement)
        assert info.value.orig.diag.constraint_name == "append_only_violation"


def test_proof_code_only_hits_are_evidence_but_never_strikes_br_l7(bw: BW) -> None:
    t0 = utc_now()
    for minute in range(5):
        consume(bw, contact_filter_strikes, hit_event(bw, bw.w.client_id, t0 + timedelta(minutes=minute), categories=("proof_code",)))
    assert scalar(bw.db, "SELECT count(*) FROM contact_filter_hits WHERE user_id = :u", u=bw.w.client_id) == 5  # kept
    assert scalar(bw.db, "SELECT count(*) FROM contact_strikes") == 0
    assert _reviews(bw, "contact_filter_strikes") == []
    # a real contact category still counts: first phone hit is the free one, the second is a strike
    consume(bw, contact_filter_strikes, hit_event(bw, bw.w.client_id, t0 + timedelta(minutes=6), categories=("phone", "proof_code")))
    assert scalar(bw.db, "SELECT count(*) FROM contact_strikes") == 0
    consume(bw, contact_filter_strikes, hit_event(bw, bw.w.client_id, t0 + timedelta(minutes=7)))
    assert scalar(bw.db, "SELECT count(*) FROM contact_strikes WHERE user_id = :u", u=bw.w.client_id) == 1


def test_review_commands_are_versioned_and_warning_reaches_user(bw: BW) -> None:
    t0 = utc_now()
    for minute in range(4):
        consume(bw, contact_filter_strikes, hit_event(bw, bw.w.driver_id, t0 + timedelta(minutes=minute)))
    review = _reviews(bw, "contact_filter_strikes")[0]
    from app.contracts.ids import PublicIdPrefix, format_public_id

    public = format_public_id(PublicIdPrefix.TRUST_REVIEW, review.public_id)

    def command(actor: int, name: str, version: int, decision: str | None = None):  # noqa: ANN202
        with bw.db.session() as s:
            item = trust_service.review_command(s, review_public_id_value=public, actor_user_id=actor, command=name,
                                                expected_version=version, decision=decision, note="checked chat")
            s.commit()
            return item

    assert domain_error(lambda: command(bw.w.client_id, "start_review", review.version)).code is ErrorCode.CAPABILITY_REQUIRED
    assert domain_error(lambda: command(bw.operator_id, "start_review", review.version + 5)).code is ErrorCode.VERSION_CONFLICT
    started = command(bw.operator_id, "start_review", review.version)
    assert started.status == "under_review"
    assert domain_error(lambda: command(bw.operator_id, "action", started.version)).code is ErrorCode.VALIDATION_ERROR
    done = command(bw.operator_id, "action", started.version, "warning_issued")
    assert (done.status, done.decision) == ("actioned", "warning_issued")
    assert domain_error(lambda: command(bw.operator_id, "dismiss", done.version)).code is ErrorCode.INVALID_STATE_TRANSITION
    warning = rows(bw.db, "SELECT aggregate_type, payload FROM outbox_events WHERE event_type = 'trust.warning_issued'")
    assert [(w.aggregate_type, set(w.payload)) for w in warning] == [("user", {"review_id", "signal_type"})]
    # no automatic ban: eligibility untouched
    assert scalar(bw.db, "SELECT count(*) FROM driver_eligibility_blocks") == 0
    with bw.db.session() as s:
        _, strikes = trust_service.user_strikes(s, actor_user_id=bw.operator_id,
                                                user_public_id_value=format_public_id(PublicIdPrefix.USER, scalar(bw.db, "SELECT public_id FROM users WHERE id = :u", u=bw.w.driver_id)))
        assert len(strikes) == 3


def _cancel(bw: BW, booking, actor: int) -> None:  # noqa: ANN001
    with bw.db.session() as s:
        bookings_service.cancel_booking(s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=actor,
                                        expected_version=s.get(type(booking), booking.id).version, reason_code="plans_changed")
        s.commit()


def _cancelled_event(bw: BW, booking) -> DispatchedEvent:  # noqa: ANN001
    return DispatchedEvent(uuid.uuid4(), EventType.BOOKING_CANCELLED, "booking", bookings_service.booking_public_id(booking),
                           booking.id, 2, utc_now(), {"service_type": "passenger", "cancelled_by_side": "client"})


def test_quick_cancel_after_chat_and_repeated_pair_signals(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    trip_id, trip_public = driver_trip(bw, bw.w.driver_id, "01T200AA", seats=4)
    first_listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=1))
    first = accept(bw, propose(bw, first_listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1), bw.w.client_id)
    _cancel(bw, first, bw.w.client_id)

    summary = ChatActivitySummary(message_count=3, first_message_at=utc_now() - timedelta(hours=1),
                                  last_message_at=utc_now() - timedelta(minutes=5), contact_filter_hit_count=1,
                                  last_contact_filter_hit_at=utc_now() - timedelta(minutes=20))
    monkeypatch.setattr(trust_service, "_chat_activity", lambda session, booking_id: summary)
    event = _cancelled_event(bw, first)
    consume(bw, cancellation_signals, event)
    consume(bw, cancellation_signals, event)  # redelivery changes nothing
    quick = _reviews(bw, "quick_cancel_after_chat")
    assert len(quick) == 1 and quick[0].subject_user_id == bw.w.client_id and quick[0].signal_count == 1
    assert quick[0].evidence == {"booking_ids": [bookings_service.booking_public_id(first)], "hit_count": 1}
    assert _reviews(bw, "repeated_pair_cancellations") == []

    monkeypatch.setattr(trust_service, "_chat_activity", lambda session, booking_id: None)  # A7 absent: no quick signal
    second_listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw, seats=1))
    second = accept(bw, propose(bw, second_listing, bw.w.driver_id, trip_public_id=trip_public, quantity=1), bw.w.client_id)
    _cancel(bw, second, bw.w.client_id)
    consume(bw, cancellation_signals, _cancelled_event(bw, second))
    pair = _reviews(bw, "repeated_pair_cancellations")
    assert len(pair) == 1 and pair[0].subject_user_id == bw.w.client_id  # BR L8: subject = party that cancelled
    assert pair[0].evidence["cancel_count"] == 2 and len(pair[0].evidence["booking_ids"]) == 2
    assert len(_reviews(bw, "quick_cancel_after_chat")) == 1
