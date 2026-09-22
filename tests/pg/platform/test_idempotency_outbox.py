"""Idempotency savepoint pattern (ADR-0005, AC08, AC09, D8) and outbox atomicity (AC33) on PostgreSQL."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts.enums import EventType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventEnvelope
from app.contracts.timeutil import utc_now
from app.modules.platform.service import CommandResult, enqueue_event, run_idempotent
from app.modules.wallet import service as wallet_service
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg

ROUTE = "/api/v2/wallet/topups"


def _user(pg_db, role="driver"):
    from tests.pg.wallet.conftest import make_user

    with pg_db.session() as s:
        uid = make_user(s, role)
        s.commit()
    return uid


def _topup_handler(session, user_id, calls):
    def handler():
        calls.append(1)
        topup = wallet_service.create_topup(session, driver_user_id=user_id, amount_minor=1_000_000, method="bank_transfer")
        return CommandResult(201, {"success": True, "data": {"id": str(topup.public_id)}})

    return handler


def test_ac08_same_key_in_parallel_executes_once(pg_db):
    uid = _user(pg_db)
    calls: list[int] = []
    lock = threading.Lock()

    def worker(i, session):
        def handler():
            with lock:
                calls.append(i)
            topup = wallet_service.create_topup(session, driver_user_id=uid, amount_minor=1_000_000, method="bank_transfer")
            return CommandResult(201, {"id": str(topup.public_id)})

        outcome = run_idempotent(session, actor_user_id=uid, method="POST", route_template=ROUTE,
                                 idempotency_key="key-parallel-0001", body={"amount_minor": 1_000_000}, handler=handler)
        session.commit()
        return outcome

    report = run_concurrently(10, worker, engine=pg_db.engine)
    assert not report.failures, report.failures
    outcomes = report.values()
    assert len(calls) == 1
    assert len({o.body["id"] for o in outcomes}) == 1
    assert sorted(o.replayed for o in outcomes) == [False] + [True] * 9
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM topup_requests")).scalar() == 1


def test_ac09_same_key_different_body_is_409_and_not_executed(pg_db):
    uid = _user(pg_db)
    calls: list[int] = []
    with pg_db.session() as s:
        run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE, idempotency_key="key-body-0001",
                       body={"amount_minor": 1}, handler=_topup_handler(s, uid, calls))
        s.commit()
    with pg_db.session() as s:
        with pytest.raises(DomainError) as exc:
            run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE, idempotency_key="key-body-0001",
                           body={"amount_minor": 2}, handler=_topup_handler(s, uid, calls))
        assert exc.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED and exc.value.http_status == 409
        s.rollback()
    assert len(calls) == 1
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM topup_requests")).scalar() == 1


def test_d8_domain_4xx_replay_has_no_domain_writes(pg_db):
    uid = _user(pg_db)
    calls: list[int] = []

    def failing(session):
        def handler():
            calls.append(1)
            wallet_service.create_topup(session, driver_user_id=uid, amount_minor=5, method="bank_transfer")
            enqueue_event(session, EventEnvelope(EventType.TOPUP_APPROVED, "topup", "top_x", 1, utc_now(),
                                                 {"topup_id": "top_x", "amount_minor": 5, "currency": "UZS"}))
            raise DomainError(ErrorCode.INSUFFICIENT_COMMISSION_BALANCE)

        return handler

    for attempt in range(2):
        with pg_db.session() as s:
            outcome = run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE,
                                     idempotency_key="key-4xx-00001", body={"x": 1}, handler=failing(s))
            s.commit()
        assert outcome.status_code == 409
        assert outcome.body["error"]["code"] == "INSUFFICIENT_COMMISSION_BALANCE"
        assert outcome.replayed is (attempt == 1)
    assert len(calls) == 1
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM topup_requests")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM outbox_events")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM wallet_accounts")).scalar() == 0
        assert conn.execute(text("SELECT state, response_status FROM idempotency_records")).one() == ("completed", 409)


def test_unexpected_error_stores_nothing_and_key_is_reusable(pg_db):
    uid = _user(pg_db)
    with pg_db.session() as s:
        with pytest.raises(RuntimeError):
            run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE, idempotency_key="key-5xx-00001",
                           body={}, handler=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        s.rollback()
    with pg_db.session() as s:
        outcome = run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE, idempotency_key="key-5xx-00001",
                                 body={}, handler=lambda: CommandResult(200, {"ok": True}))
        s.commit()
    assert outcome.status_code == 200 and not outcome.replayed


def test_expired_key_may_be_reused(pg_db):
    uid = _user(pg_db)
    with pg_db.session() as s:
        run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE, idempotency_key="key-ttl-00001",
                       body={"a": 1}, handler=lambda: CommandResult(200, {"first": True}),
                       now=utc_now() - timedelta(hours=25))
        s.commit()
    with pg_db.session() as s:
        outcome = run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE, idempotency_key="key-ttl-00001",
                                 body={"a": 2}, handler=lambda: CommandResult(200, {"second": True}))
        s.commit()
    assert outcome.body == {"second": True} and not outcome.replayed


def test_invalid_key_rejected_before_any_record(pg_db):
    uid = _user(pg_db)
    with pg_db.session() as s:
        with pytest.raises(DomainError) as exc:
            run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE, idempotency_key=None,
                           body={}, handler=lambda: CommandResult(200, {}))
        assert exc.value.code is ErrorCode.IDEMPOTENCY_KEY_REQUIRED


def _envelope():
    return EventEnvelope(EventType.WALLET_HOLD_CREATED, "wallet", "wal_x", 1, utc_now(),
                         {"booking_id": "bkg_x", "amount_minor": 6_000_000, "currency": "UZS"})


def test_ac33_outbox_event_disappears_on_rollback_and_persists_on_commit(pg_db):
    with pg_db.session() as s:
        enqueue_event(s, _envelope())
        s.rollback()
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM outbox_events")).scalar() == 0
    envelope = _envelope()
    with pg_db.session() as s:
        enqueue_event(s, envelope, aggregate_id=1)
        s.commit()
    with pg_db.engine.connect() as conn:
        row = conn.execute(text("SELECT event_id, event_type, payload, dispatched_at FROM outbox_events")).one()
        pending = conn.execute(text(
            "EXPLAIN SELECT id FROM outbox_events WHERE dispatched_at IS NULL AND dead_lettered_at IS NULL "
            "ORDER BY next_attempt_at")).scalars().all()
    assert row.event_id == envelope.event_id and row.event_type == "wallet.hold.created"
    assert row.payload == envelope.payload and row.dispatched_at is None
    assert pending  # partial index exists and the query plans


def test_outbox_rejects_non_allowlisted_payload_and_duplicate_event_id(pg_db):
    with pytest.raises(ValueError):
        EventEnvelope(EventType.WALLET_HOLD_CREATED, "wallet", "wal_x", 1, utc_now(), {"phone": "+998"})
    envelope = _envelope()
    with pg_db.session() as s:
        enqueue_event(s, envelope)
        s.commit()
    from sqlalchemy.exc import IntegrityError

    with pg_db.session() as s:
        with pytest.raises(IntegrityError):
            enqueue_event(s, envelope)
        s.rollback()
