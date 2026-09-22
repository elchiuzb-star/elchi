"""Outbox dispatcher (ADR-0012, AC33, N2/Q16, ADR-0019 §9) on PostgreSQL."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.contracts.communications import OUTBOX_MAX_ATTEMPTS
from app.contracts.errors import ErrorCode
from app.contracts.events import CLIENT_REDACTED_PAYLOAD_KEYS
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.timeutil import utc_now
from app.modules.communications import dispatch as dispatch_registry
from app.modules.communications import service as comms
from tests.pg.communications.conftest import (
    accepted_deal,
    dispatch_all,
    domain_error,
    driver_trip,
    enqueue_user_event,
    passenger_request_body,
    post,
    propose,
    publish_listing,
    rows,
    scalar,
)
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg


def _consumed(db, event_id=None) -> int:  # noqa: ANN001
    if event_id is None:
        return int(scalar(db, "SELECT count(*) FROM audit_logs WHERE entity_type = 'fake_consumer'"))
    return int(scalar(db, "SELECT count(*) FROM audit_logs WHERE entity_type = 'fake_consumer' AND details->>'event_id' = :e",
                      e=str(event_id)))


def test_ac33_dispatcher_crash_before_commit_then_single_delivery(bw, fake_consumers) -> None:  # noqa: ANN001
    event_id = enqueue_user_event(bw.db, bw.w.client_id)

    with bw.db.session() as s:  # the worker dies after doing the work but before COMMIT
        assert comms.dispatch_outbox(s) > 0
        s.rollback()
    assert scalar(bw.db, "SELECT dispatched_at FROM outbox_events WHERE event_id = :e", e=event_id) is None
    assert _consumed(bw.db, event_id) == 0
    assert scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE event_id = :e", e=event_id) == 0

    dispatch_all(bw.db)  # next run
    assert scalar(bw.db, "SELECT dispatched_at FROM outbox_events WHERE event_id = :e", e=event_id) is not None
    assert _consumed(bw.db, event_id) == 1
    assert scalar(bw.db, "SELECT count(*) FROM consumer_receipts WHERE event_id = :e", e=event_id) == 2
    delivery = rows(bw.db, "SELECT user_id, status, audience FROM notification_deliveries WHERE event_id = :e", e=event_id)
    assert [(d.user_id, d.status, d.audience) for d in delivery] == [(bw.w.client_id, "sent", "client")]

    # at-least-once: the same event arrives again -> no second effect
    with bw.db.engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("UPDATE outbox_events SET dispatched_at = NULL WHERE event_id = :e"), {"e": event_id})
    dispatch_all(bw.db)
    assert _consumed(bw.db, event_id) == 1
    assert scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE event_id = :e", e=event_id) == 1


def test_parallel_dispatchers_process_each_event_once(bw, fake_consumers) -> None:  # noqa: ANN001
    dispatch_all(bw.db)  # drain the world's own events first
    event_ids = [enqueue_user_event(bw.db, bw.w.client_id if i % 2 else bw.w.driver_id) for i in range(40)]
    handled_by: dict[int, int] = {}

    def worker(index: int, session) -> int:  # noqa: ANN001
        total = 0
        for _ in range(50):
            handled = comms.dispatch_outbox(session, limit=3)
            session.commit()
            total += handled
            if handled == 0:
                break
        handled_by[index] = total
        return total

    report = run_concurrently(4, worker, engine=bw.db.engine)
    assert not report.failures, report.failures
    assert sum(report.values()) == 40
    assert _consumed(bw.db) == 40
    for event_id in event_ids:
        assert _consumed(bw.db, event_id) == 1
    assert scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE event_id = ANY(:ids)", ids=event_ids) == 40
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL") == 0


def test_wallet_and_commission_never_reach_the_client(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    dispatch_all(bw.db)
    client_rows = rows(bw.db, "SELECT event_type, status, payload FROM notification_deliveries WHERE user_id = :u", u=bw.w.client_id)
    assert client_rows, "client got no copies at all"
    for row in client_rows:
        if row.status == "sent":
            assert not row.event_type.startswith(("wallet.", "commission.")), row
            assert not (set(row.payload) & CLIENT_REDACTED_PAYLOAD_KEYS), row
    accepted_client = [r for r in client_rows if r.event_type == "booking.accepted"]
    assert accepted_client and "commission_status" not in accepted_client[0].payload
    driver_accepted = rows(bw.db, "SELECT payload FROM notification_deliveries WHERE user_id = :u AND event_type = 'booking.accepted'",
                           u=bw.w.driver_id)
    assert "commission_status" in driver_accepted[0].payload
    driver_wallet = scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE user_id = :u AND event_type LIKE 'wallet.%' "
                                  "AND status = 'sent'", u=bw.w.driver_id)
    assert driver_wallet >= 1
    assert deal.booking_id


def test_competing_driver_copy_carries_only_listing_id(bw) -> None:  # noqa: ANN001
    listing = publish_listing(bw, bw.w.client_id, passenger_request_body(bw))
    _t1, trip1 = driver_trip(bw, bw.w.driver_id, "01A100AA")
    propose(bw, listing, bw.w.driver_id, trip_public_id=trip1)
    _t2, trip2 = driver_trip(bw, bw.w.driver2_id, "01A200BB")
    ref2 = propose(bw, listing, bw.w.driver2_id, trip_public_id=trip2)
    dispatch_all(bw.db)

    event_id = scalar(bw.db, "SELECT event_id FROM outbox_events WHERE event_type = 'proposal.created' AND aggregate_public_id = :t",
                      t=ref2.thread_id)
    copies = {r.user_id: r for r in rows(bw.db, "SELECT user_id, audience, status, payload, link FROM notification_deliveries "
                                                "WHERE event_id = :e AND channel = 'in_app'", e=event_id)}
    assert copies[bw.w.driver_id].audience == "competing_driver"
    assert copies[bw.w.driver_id].payload == {"listing_id": listing}
    assert copies[bw.w.driver_id].link == f"/listings/{listing}"
    assert copies[bw.w.driver2_id].audience == "driver" and "revision" in copies[bw.w.driver2_id].payload
    assert copies[bw.w.client_id].audience == "client" and copies[bw.w.client_id].payload["thread_id"] == ref2.thread_id
    assert bw.w.client2_id not in copies


def test_failing_consumer_dead_letters_after_max_attempts_and_n9_retry(bw, fake_consumers) -> None:  # noqa: ANN001
    dispatch_all(bw.db)
    fake_consumers.STATE["fail"] = True
    event_id = enqueue_user_event(bw.db, bw.w.client_id)
    moment = utc_now()
    for attempt in range(1, OUTBOX_MAX_ATTEMPTS + 1):
        moment += timedelta(hours=7)
        dispatch_all(bw.db, now=moment)
        state = rows(bw.db, "SELECT attempts, dead_lettered_at, dispatched_at, last_error FROM outbox_events WHERE event_id = :e", e=event_id)[0]
        assert state.attempts == attempt and state.dispatched_at is None
    assert state.dead_lettered_at is not None and "RuntimeError" in state.last_error
    assert _consumed(bw.db, event_id) == 0 and scalar(bw.db, "SELECT count(*) FROM consumer_receipts WHERE event_id = :e", e=event_id) == 0
    assert scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE event_id = :e", e=event_id) == 0

    public_id = format_public_id(PublicIdPrefix.EVENT, event_id)
    with bw.db.session() as s:
        dead = comms.list_outbox_for_staff(s, actor_user_id=bw.operator_id, state="dead", after_id=None, limit=10)
        assert [row.event_id for row in dead] == [event_id]
        assert domain_error(lambda: comms.retry_outbox_event(
            s, event_public_id_value=public_id, actor_user_id=bw.w.client_id, reason="not staff")).code is ErrorCode.CAPABILITY_REQUIRED
    with bw.db.session() as s:
        comms.retry_outbox_event(s, event_public_id_value=public_id, actor_user_id=bw.operator_id, reason="consumer fixed")
        s.commit()
    audit = rows(bw.db, "SELECT details FROM audit_logs WHERE action = 'outbox_event_retry'")[0].details
    assert audit["previous_attempts"] == OUTBOX_MAX_ATTEMPTS and audit["was_dead_lettered"] is True and audit["reason"] == "consumer fixed"
    with bw.db.session() as s:
        assert domain_error(lambda: comms.retry_outbox_event(
            s, event_public_id_value=public_id, actor_user_id=bw.operator_id, reason="twice")).code is ErrorCode.INVALID_STATE_TRANSITION

    fake_consumers.STATE["fail"] = False
    dispatch_all(bw.db, now=moment)
    assert _consumed(bw.db, event_id) == 1
    with bw.db.session() as s:
        assert domain_error(lambda: comms.retry_outbox_event(
            s, event_public_id_value=public_id, actor_user_id=bw.operator_id, reason="done")).code is ErrorCode.INVALID_STATE_TRANSITION


def test_relevance_check_false_skips_the_delivery(bw, fake_consumers) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    fake_consumers.STATE["relevant"] = False
    post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="salom")
    dispatch_all(bw.db)
    row = rows(bw.db, "SELECT status, skip_reason, payload FROM notification_deliveries WHERE event_type = 'chat.message.created'")[0]
    assert (row.status, row.skip_reason, row.payload) == ("skipped", "not_relevant", {})
    with bw.db.session() as s:
        assert all(n.event_type != "chat.message.created" for n in comms.list_notifications(
            s, user_id=bw.w.driver_id, unread_only=False, before_id=None, limit=100))


def test_missing_or_broken_consumer_modules_do_not_stop_dispatch(bw, fake_consumers) -> None:  # noqa: ANN001
    registry = dispatch_registry.load_registry()
    assert registry.loaded_modules == ("tests.pg.communications.fake_consumers",)
    assert registry.failed_modules == ("app.modules.not_delivered_yet.consumers",)
    assert {c.name for c in registry.consumers} == {"test.counting", "test.exploding"}  # the invalid entry is skipped
    default = dispatch_registry.load_registry(dispatch_registry.CONSUMER_MODULES)
    assert set(default.loaded_modules) | set(default.failed_modules) == set(dispatch_registry.CONSUMER_MODULES)
    enqueue_user_event(bw.db, bw.w.client_id)
    assert dispatch_all(bw.db) > 0
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL") == 0


def test_staff_only_events_are_not_delivered_per_user_and_n1_shows_staff_copy(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="+998 90 123 45 67")
    dispatch_all(bw.db)
    assert scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE event_type = 'trust.contact_filter.hit'") == 0
    with bw.db.session() as s:
        assert comms.is_staff_viewer(s, bw.operator_id) and not comms.is_staff_viewer(s, bw.w.client_id)
        staff = comms.list_staff_events(s, after_id=None, limit=500)
        assert any(row.event_type == "trust.contact_filter.hit" for row in staff)
        client = comms.list_user_events(s, user_id=bw.w.client_id, after_id=None, limit=500)
        assert client and all(row.event_type != "trust.contact_filter.hit" for row in client)
        assert all(not row.event_type.startswith(("wallet.", "commission.")) for row in client)


def _enqueue_trip_stale(bw, trip_id: int) -> object:  # noqa: ANN001
    from app.contracts.enums import EventType
    from app.contracts.events import EventEnvelope
    from app.modules.platform.service import enqueue_event
    from app.modules.trips import service as trips_service

    with bw.db.session() as s:
        trip = trips_service.get_trip(s, trip_id)
        row = enqueue_event(
            s,
            EventEnvelope(EventType.TRACKING_STALE, "trip", trips_service.trip_public_id(trip), trip.version, utc_now(),
                          {"trip_id": trips_service.trip_public_id(trip), "freshness": "lost", "last_captured_at": None}),
            aggregate_id=trip.id,
        )
        event_id = row.event_id
        s.commit()
    return event_id


def _stale_recipients(bw, event_id) -> dict:  # noqa: ANN001
    return {r.user_id: r.audience for r in rows(bw.db, "SELECT user_id, audience FROM notification_deliveries "
                                                       "WHERE event_id = :e AND status = 'sent'", e=event_id)}


def test_br_l1_trip_tracking_events_reach_clients_only_inside_the_tracking_window(bw, monkeypatch) -> None:  # noqa: ANN001
    from app.contracts.enums import TrackingFreshness, TrackingWindowReason
    from app.contracts.tracking import TrackingWindow

    deal = accepted_deal(bw)  # pickup ~2 days ahead -> window closed
    dispatch_all(bw.db)

    closed = _enqueue_trip_stale(bw, deal.trip_id)
    dispatch_all(bw.db)
    assert _stale_recipients(bw, closed) == {bw.w.driver_id: "driver"}

    from app.modules.tracking import service as tracking_service

    real = tracking_service.booking_live_state

    def open_window(session, booking_id, *, now=None):  # noqa: ANN001, ANN202
        state = real(session, booking_id, now=now)
        return tracking_service.BookingLiveState(TrackingWindow(True, TrackingWindowReason.OPEN), TrackingFreshness.LOST,
                                                 state.last_captured_at, state.driver_arrived_at)

    monkeypatch.setattr(tracking_service, "booking_live_state", open_window)
    opened = _enqueue_trip_stale(bw, deal.trip_id)
    dispatch_all(bw.db)
    assert _stale_recipients(bw, opened) == {bw.w.driver_id: "driver", bw.w.client_id: "client"}

    monkeypatch.delattr(tracking_service, "booking_live_state")  # A6 reader unavailable -> clients get nothing
    missing = _enqueue_trip_stale(bw, deal.trip_id)
    dispatch_all(bw.db)
    assert _stale_recipients(bw, missing) == {bw.w.driver_id: "driver"}
