"""Concurrency harness for PostgreSQL race tests (AC06-AC08, AC19, AC41).

Every worker gets its own Session bound to its own connection. The connection
is opened *before* the barrier, so all workers start their critical section at
the same moment instead of racing on connection setup.

Nothing here wraps workers in a shared transaction: each worker commits or
rolls back independently, exactly like concurrent API requests would.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class WorkerResult:
    index: int
    value: Any = None
    error: BaseException | None = None
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ConcurrencyReport:
    results: list[WorkerResult]

    @property
    def successes(self) -> list[WorkerResult]:
        return [r for r in self.results if r.ok]

    @property
    def failures(self) -> list[WorkerResult]:
        return [r for r in self.results if not r.ok]

    def values(self) -> list[Any]:
        return [r.value for r in self.successes]

    def errors_of(self, exc_type: type[BaseException]) -> list[WorkerResult]:
        return [r for r in self.failures if isinstance(r.error, exc_type)]


def run_concurrently(
    n: int,
    fn: Callable[[int, Session], Any],
    *,
    engine: Engine,
    timeout_s: float = 60.0,
) -> ConcurrencyReport:
    """Run ``fn(worker_index, session)`` in ``n`` threads released together.

    ``fn`` owns its transaction: it must ``commit()`` what it wants kept.
    Any uncommitted work is rolled back when the session closes. Exceptions
    are captured per worker (never re-raised here) so the caller can assert on
    the exact success/conflict split. A worker that cannot reach the barrier
    (e.g. connection failure) breaks it and every worker reports the error.
    The engine's pool must allow ``n`` simultaneous connections.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    barrier = threading.Barrier(n)

    def worker(index: int) -> WorkerResult:
        started = time.perf_counter()
        try:
            with Session(engine, expire_on_commit=False) as session:
                session.connection()  # check out a real connection up front
                barrier.wait(timeout=timeout_s)
                started = time.perf_counter()
                value = fn(index, session)
            return WorkerResult(index, value=value, elapsed_s=time.perf_counter() - started)
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            barrier.abort()
            return WorkerResult(index, error=exc, elapsed_s=time.perf_counter() - started)

    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="pg-race") as pool:
        futures = [pool.submit(worker, i) for i in range(n)]
        results = [f.result(timeout=timeout_s * 2) for f in futures]
    return ConcurrencyReport(results)
