"""Wave 1.5 tests: IDEMPOTENCY_IN_PROGRESS via lock_timeout and deadlock retry (ADR-0005, ADR-0017 §5)."""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import text

from app.contracts.errors import DomainError, ErrorCode
from app.modules.platform import service as platform_service
from app.modules.platform.service import CommandResult, run_idempotent, run_with_db_retry
from tests.pg.harness import run_concurrently
from tests.pg.wallet.conftest import make_user

pytestmark = pytest.mark.pg

ROUTE = "/api/v2/wallet/topups"


def test_same_key_while_first_request_is_uncommitted_is_in_progress(pg_db, monkeypatch):
    monkeypatch.setattr(platform_service, "IDEMPOTENCY_LOCK_TIMEOUT", "300ms")
    with pg_db.session() as s:
        uid = make_user(s, "driver")
        s.commit()
    holder = pg_db.session()
    try:
        first = run_idempotent(holder, actor_user_id=uid, method="POST", route_template=ROUTE,
                               idempotency_key="key-inflight-0001", body={"a": 1},
                               handler=lambda: CommandResult(200, {"ok": True}))
        assert first.status_code == 200  # not committed: the record row is still locked
        started = time.perf_counter()
        with pg_db.session() as s:
            with pytest.raises(DomainError) as exc:
                run_idempotent(s, actor_user_id=uid, method="POST", route_template=ROUTE,
                               idempotency_key="key-inflight-0001", body={"a": 1},
                               handler=lambda: CommandResult(200, {"second": True}))
            assert exc.value.code is ErrorCode.IDEMPOTENCY_IN_PROGRESS and exc.value.http_status == 409
            s.rollback()
        assert time.perf_counter() - started < 5
    finally:
        holder.rollback()
        holder.close()
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM idempotency_records")).scalar() == 0


def test_deadlock_victim_is_retried_and_both_commands_succeed(pg_db):
    with pg_db.engine.begin() as conn:
        conn.execute(text("CREATE TABLE a3_deadlock_probe (id int PRIMARY KEY, v int NOT NULL)"))
        conn.execute(text("INSERT INTO a3_deadlock_probe VALUES (1, 0), (2, 0)"))
    attempts = [0, 0]
    both_hold_first_lock = threading.Barrier(2)

    def worker(i, session):
        first, second = (1, 2) if i == 0 else (2, 1)

        def command():
            attempts[i] += 1
            session.execute(text("UPDATE a3_deadlock_probe SET v = v + 1 WHERE id = :id"), {"id": first})
            if attempts[i] == 1:
                both_hold_first_lock.wait(timeout=20)
            session.execute(text("UPDATE a3_deadlock_probe SET v = v + 1 WHERE id = :id"), {"id": second})
            session.commit()
            return attempts[i]

        return run_with_db_retry(session, command)

    report = run_concurrently(2, worker, engine=pg_db.engine)
    assert not report.failures, report.failures
    assert sorted(report.values()) == [1, 2]  # exactly one deadlock victim, retried once
    with pg_db.engine.connect() as conn:
        assert conn.execute(text("SELECT v FROM a3_deadlock_probe ORDER BY id")).scalars().all() == [2, 2]
