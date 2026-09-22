"""CLI: ``python -m app.worker [--once] [--healthcheck [--max-age SECONDS]]``."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from app.worker import (
    DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    heartbeat_age,
    heartbeat_path,
    register_default_tasks,
    run_forever,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--once", action="store_true", help="run one iteration and exit")
    parser.add_argument("--healthcheck", action="store_true", help="exit 0 if the heartbeat is fresh")
    parser.add_argument("--max-age", type=float, default=DEFAULT_HEARTBEAT_MAX_AGE_SECONDS)
    parser.add_argument("--list-jobs", action="store_true", help="print scheduled jobs (wired/pending) as JSON and exit")
    args = parser.parse_args(argv)

    if args.list_jobs:
        import json

        from app.worker import describe_jobs

        print(json.dumps(describe_jobs(), indent=2))
        return 0

    if args.healthcheck:
        age = heartbeat_age()
        if age is None or age > args.max_age:
            print(f"unhealthy: heartbeat {heartbeat_path()} age={age}", file=sys.stderr)
            return 1
        return 0

    from app.ops.logging import configure_logging

    configure_logging()  # JSON lines with PII redaction (BR #13)
    stop = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        logging.getLogger("elchi.worker").info("worker_signal signum=%s", signum)
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    if not args.once:
        # Long-running worker only: `--once` stays a dependency-free loop/heartbeat smoke check.
        register_default_tasks()  # geo routing_cache cleanup + SERVICE_JOBS whose functions exist
    return run_forever(stop, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
