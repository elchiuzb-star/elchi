"""Proof that the harness reproduces real races and that row locks fix them.

This is the pattern later AC06/AC07/AC08/AC19/AC41 tests build on:
N workers, one Session/connection each, released together by a barrier.
"""

from __future__ import annotations

import time

import pytest
from psycopg import errors as pg_errors
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from tests.pg.conftest import PgDatabase
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg

WORKERS = 20
# Widens the read -> write window so the unlocked race is reproducible.
THINK_TIME_S = 0.15


@pytest.fixture
def last_unit(pg_db: PgDatabase) -> PgDatabase:
    with pg_db.engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE race_counter (id int PRIMARY KEY, remaining int NOT NULL CHECK (remaining >= 0))")
        )
        conn.execute(text("CREATE TABLE race_claims (worker int PRIMARY KEY, claimed_at timestamptz DEFAULT now())"))
        conn.execute(text("INSERT INTO race_counter VALUES (1, 1)"))
    return pg_db


def _state(db: PgDatabase) -> tuple[int, int]:
    with db.engine.connect() as conn:
        remaining = conn.scalar(text("SELECT remaining FROM race_counter WHERE id = 1"))
        claims = conn.scalar(text("SELECT count(*) FROM race_claims"))
    return remaining, claims


def test_select_for_update_lets_exactly_one_worker_take_last_unit(last_unit: PgDatabase) -> None:
    def take(worker: int, session: Session) -> bool:
        remaining = session.execute(text("SELECT remaining FROM race_counter WHERE id = 1 FOR UPDATE")).scalar_one()
        time.sleep(THINK_TIME_S)  # others queue on the row lock meanwhile
        if remaining <= 0:
            session.rollback()
            return False
        session.execute(text("UPDATE race_counter SET remaining = remaining - 1 WHERE id = 1"))
        session.execute(text("INSERT INTO race_claims (worker) VALUES (:w)"), {"w": worker})
        session.commit()
        return True

    report = run_concurrently(WORKERS, take, engine=last_unit.engine)

    assert report.failures == []
    assert report.values().count(True) == 1
    assert report.values().count(False) == WORKERS - 1
    assert _state(last_unit) == (0, 1)


def test_conditional_update_is_also_atomic(last_unit: PgDatabase) -> None:
    def take(worker: int, session: Session) -> bool:
        row = session.execute(
            text("UPDATE race_counter SET remaining = remaining - 1 WHERE id = 1 AND remaining > 0 RETURNING remaining")
        ).first()
        if row is None:
            session.rollback()
            return False
        session.execute(text("INSERT INTO race_claims (worker) VALUES (:w)"), {"w": worker})
        session.commit()
        return True

    report = run_concurrently(WORKERS, take, engine=last_unit.engine)

    assert report.failures == []
    assert report.values().count(True) == 1
    assert _state(last_unit) == (0, 1)


def test_nowait_conflicts_are_reported_per_worker(last_unit: PgDatabase) -> None:
    """Losers get LockNotAvailable instead of waiting (the 409-conflict path)."""

    def take(worker: int, session: Session) -> bool:
        session.execute(text("SELECT remaining FROM race_counter WHERE id = 1 FOR UPDATE NOWAIT")).scalar_one()
        time.sleep(1.0)  # hold the lock long enough for every other worker to hit it
        session.execute(text("UPDATE race_counter SET remaining = remaining - 1 WHERE id = 1"))
        session.execute(text("INSERT INTO race_claims (worker) VALUES (:w)"), {"w": worker})
        session.commit()
        return True

    report = run_concurrently(WORKERS, take, engine=last_unit.engine)

    assert len(report.successes) == 1
    conflicts = report.errors_of(OperationalError)
    assert len(conflicts) == WORKERS - 1, [repr(r.error) for r in report.failures]
    assert all(isinstance(r.error.orig, pg_errors.LockNotAvailable) for r in conflicts)
    assert _state(last_unit) == (0, 1)


def test_negative_control_unlocked_read_then_write_oversells(last_unit: PgDatabase) -> None:
    """Without a lock the classic lost update happens: several workers 'win'.

    Under READ COMMITTED every worker reads remaining=1, sleeps, then writes the
    stale value 0 (the later UPDATEs wait on the row, then overwrite). This must
    show >1 claim; if it ever does not, the harness is not creating overlap and
    the positive tests above prove nothing.
    """

    def take(worker: int, session: Session) -> bool:
        remaining = session.execute(text("SELECT remaining FROM race_counter WHERE id = 1")).scalar_one()
        time.sleep(THINK_TIME_S)
        if remaining <= 0:
            session.rollback()
            return False
        session.execute(text("UPDATE race_counter SET remaining = :v WHERE id = 1"), {"v": remaining - 1})
        session.execute(text("INSERT INTO race_claims (worker) VALUES (:w)"), {"w": worker})
        session.commit()
        return True

    report = run_concurrently(WORKERS, take, engine=last_unit.engine)

    assert report.failures == []
    winners = report.values().count(True)
    remaining, claims = _state(last_unit)
    assert remaining == 0
    assert claims == winners
    assert winners > 1, "race not reproduced: harness did not create overlapping transactions"
