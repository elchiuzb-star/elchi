"""Push delivery bookkeeping with the fake provider (U3 pending): lease, provider outside tx, backoff, dedup, AC34."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.contracts.communications import PUSH_PAYLOAD_KEYS
from app.contracts.timeutil import utc_now
from app.modules.communications import jobs
from app.modules.communications import service as comms
from app.modules.communications.providers import FakePushProvider, PushResult, get_push_provider, set_push_provider
from tests.pg.communications.conftest import accepted_deal, dispatch_all, post, rows, scalar

pytestmark = pytest.mark.pg


def _register(bw, user_id: int, token: str = "web-push-subscription-endpoint-0001") -> str:  # noqa: ANN001
    with bw.db.session() as s:
        device = comms.register_device(s, user_id=user_id, platform="web", token=token, app_version="1.0.0")
        public_id = comms.device_public_id(device)
        s.commit()
    return public_id


def _push_rows(bw, **filters: object) -> list:  # noqa: ANN001
    return rows(bw.db, "SELECT id, user_id, event_type, status, attempts, next_attempt_at, skip_reason, payload, last_error "
                       "FROM notification_deliveries WHERE channel <> 'in_app' ORDER BY id")


def test_disabled_provider_creates_no_push_rows_and_task_is_noop(bw) -> None:  # noqa: ANN001
    assert not get_push_provider().enabled
    _register(bw, bw.w.driver_id)
    accepted_deal(bw)
    dispatch_all(bw.db)
    assert _push_rows(bw) == []
    assert jobs.push_delivery_task(engine=bw.db.engine) == 0
    token_hashes = rows(bw.db, "SELECT token_hash FROM device_tokens")
    assert len(token_hashes[0].token_hash) == 64 and "subscription" not in token_hashes[0].token_hash


def test_push_is_sent_outside_the_transaction_with_allowlisted_payload(bw) -> None:  # noqa: ANN001
    provider = FakePushProvider()
    set_push_provider(provider)
    device = _register(bw, bw.w.driver_id)
    accepted_deal(bw)
    dispatch_all(bw.db)
    pending = _push_rows(bw)
    assert pending and {r.user_id for r in pending} == {bw.w.driver_id}  # the client has no device
    assert all(r.status in ("pending", "skipped") for r in pending)

    sent = jobs.deliver_push_batch(engine=bw.db.engine, provider=provider)
    assert sent == len([r for r in pending if r.status == "pending"]) == len(provider.sent)
    for message in provider.sent:
        assert set(message.payload) <= PUSH_PAYLOAD_KEYS and message.device_ids == (device,)
    assert {r.status for r in _push_rows(bw)} <= {"sent", "skipped"}
    assert jobs.deliver_push_batch(engine=bw.db.engine, provider=provider) == 0


def test_provider_failure_marks_failed_with_backoff_and_booking_is_untouched(bw) -> None:  # noqa: ANN001
    provider = FakePushProvider(fail=True)
    set_push_provider(provider)
    _register(bw, bw.w.driver_id)
    deal = accepted_deal(bw)
    booking_before = rows(bw.db, "SELECT version, service_status, commission_status FROM bookings WHERE id = :b", b=deal.booking_id)
    dispatch_all(bw.db)
    started = utc_now()
    assert jobs.deliver_push_batch(engine=bw.db.engine, provider=provider) > 0
    failed = [r for r in _push_rows(bw) if r.status == "failed"]
    assert failed and all(r.attempts == 1 and r.next_attempt_at >= started + timedelta(seconds=50) for r in failed)
    assert all(r.last_error == "fake_provider_failure" for r in failed)

    provider.fail, provider.raise_error = False, True
    later = utc_now() + timedelta(minutes=2)
    assert jobs.deliver_push_batch(engine=bw.db.engine, provider=provider, now=later) == len(failed)
    again = [r for r in _push_rows(bw) if r.status == "failed"]
    assert again and all(r.attempts == 2 and r.last_error == "RuntimeError" for r in again)
    assert rows(bw.db, "SELECT version, service_status, commission_status FROM bookings WHERE id = :b", b=deal.booking_id) == booking_before


def test_duplicate_pushes_collapse_inside_the_dedup_window(bw) -> None:  # noqa: ANN001
    set_push_provider(FakePushProvider())
    deal = accepted_deal(bw)
    dispatch_all(bw.db)
    _register(bw, bw.w.driver_id)
    post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="birinchi")
    post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="ikkinchi")
    dispatch_all(bw.db)
    chat_in_app = scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE event_type = 'chat.message.created' "
                                "AND channel = 'in_app' AND status = 'sent'")
    chat_push = [(r.status, r.skip_reason) for r in _push_rows(bw) if r.event_type == "chat.message.created"]
    assert chat_in_app == 2
    assert sorted(chat_push, key=str) == sorted([("pending", None), ("skipped", "dedup")], key=str)


def test_expired_lease_is_reclaimed_and_a_stale_result_is_ignored(bw) -> None:  # noqa: ANN001
    provider = FakePushProvider()
    set_push_provider(provider)
    _register(bw, bw.w.driver_id)
    deal = accepted_deal(bw)
    dispatch_all(bw.db)
    post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="lease")
    dispatch_all(bw.db)
    t0 = utc_now()
    with bw.db.session() as s:
        first = comms.claim_push_deliveries(s, provider=provider, now=t0, limit=500)
        s.commit()
    assert first
    with bw.db.session() as s:
        assert comms.claim_push_deliveries(s, provider=provider, now=t0 + timedelta(minutes=1), limit=500) == []
        s.commit()
    with bw.db.session() as s:
        second = comms.claim_push_deliveries(s, provider=provider, now=t0 + timedelta(minutes=3), limit=500)
        s.commit()
    assert {c.delivery_id for c in second} == {c.delivery_id for c in first} and all(c.attempts == 2 for c in second)
    with bw.db.session() as s:
        assert comms.record_push_result(s, first[0], PushResult(True), now=t0 + timedelta(minutes=3)) is None
        assert comms.record_push_result(s, second[0], PushResult(True), now=t0 + timedelta(minutes=3)) == "sent"
        s.commit()
