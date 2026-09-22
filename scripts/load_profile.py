"""§19.3 load profile harness (A11/A13, wave 5). Measures what it runs; never guesses the rest.

The spec fixes a *test profile*, not a result: 50 drivers sending tracking points, 200 viewers watching, 20
parallel accept requests and a catalogue of 100 000 active/history listings, with targets "feed server p95 < 1 s"
and "booking accept p95 < 2 s". Two honesty rules follow from §19.3 and §9.2:

* a percentile is only printed when the measured sample is large enough for it (``--min-samples``, default 200
  per endpoint); below that the run prints the counts and says the percentile is not reportable;
* everything the harness did **not** exercise is listed by name in the report, so a staging number can never be
  read as production capacity.

This file is the runner, not the environment: it needs an API that is already up (``--base-url``) and a database
that is already seeded. It performs read-only GETs by default; ``--scenario accept`` additionally needs prepared
accept payloads (``--accept-plan FILE``), because an accept is a money command and must not be invented here.

Usage::

    py scripts/load_profile.py --base-url http://127.0.0.1:8000 --scenario health --duration 30 --concurrency 20
    py scripts/load_profile.py --base-url ... --scenario feed --token-file tokens.txt --duration 60 --concurrency 200
    py scripts/load_profile.py --base-url ... --scenario accept --accept-plan plan.json --concurrency 20

Report: p50/p95/p99, error rate by HTTP status, requests/s, the wall clock window, and the machine context the
operator must attach (commit, head, image, CPU/RAM) - see ``--note``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MIN_SAMPLES = 200
TARGETS_SECONDS = {"feed": 1.0, "accept": 2.0}


@dataclass
class Sample:
    seconds: float
    status: int


@dataclass
class Result:
    name: str
    samples: list[Sample] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def durations(self) -> list[float]:
        return [sample.seconds for sample in self.samples if 200 <= sample.status < 400]

    def percentile(self, fraction: float) -> float | None:
        values = sorted(self.durations)
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(fraction * len(values)) - 1))
        return values[index]

    def statuses(self) -> Counter:
        return Counter(sample.status for sample in self.samples)


def _request(url: str, token: str | None, timeout: float) -> Sample:
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception:  # noqa: BLE001 - connection reset / timeout counts as an error, not a crash
        status = 0
    return Sample(time.perf_counter() - started, status)


def run_scenario(
    *, url: str, tokens: list[str], duration: float, concurrency: int, timeout: float, warmup: float, name: str
) -> Result:
    result = Result(name=name)
    lock = threading.Lock()
    stop_at = time.monotonic() + duration + warmup
    warmup_until = time.monotonic() + warmup

    def worker(index: int) -> None:
        token = tokens[index % len(tokens)] if tokens else None
        while time.monotonic() < stop_at:
            sample = _request(url, token, timeout)
            if time.monotonic() >= warmup_until:
                with lock:
                    result.samples.append(sample)

    result.started_at = time.time()
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    result.finished_at = time.time()
    return result


def render(result: Result, *, min_samples: int, target: float | None, note: str, not_measured: list[str]) -> str:
    lines = [
        f"scenario: {result.name}",
        f"window:   {time.strftime('%FT%TZ', time.gmtime(result.started_at))} .. "
        f"{time.strftime('%FT%TZ', time.gmtime(result.finished_at))}"
        f" ({result.finished_at - result.started_at:.1f} s)",
        f"requests: {len(result.samples)} (successful: {len(result.durations)})",
        f"statuses: {dict(sorted(result.statuses().items()))}",
    ]
    if result.finished_at > result.started_at:
        lines.append(f"rate:     {len(result.samples) / (result.finished_at - result.started_at):.1f} req/s")
    if len(result.durations) < min_samples:
        lines.append(
            f"p50/p95/p99: NOT REPORTABLE - {len(result.durations)} successful samples < --min-samples "
            f"{min_samples}. Counts above are the whole result of this run."
        )
    else:
        p50, p95, p99 = (result.percentile(f) for f in (0.5, 0.95, 0.99))
        mean = statistics.fmean(result.durations)
        lines.append(f"p50:      {p50:.3f} s\np95:      {p95:.3f} s\np99:      {p99:.3f} s\nmean:     {mean:.3f} s")
        if target is not None:
            verdict = "within" if p95 is not None and p95 < target else "ABOVE"
            lines.append(f"target:   p95 < {target:.1f} s -> {verdict}")
    if note:
        lines.append(f"context:  {note}")
    lines.append("not measured in this run:")
    lines.extend(f"  - {item}" for item in not_measured)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="§19.3 load profile runner")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--scenario", choices=("health", "feed", "public-listing", "custom"), default="health")
    parser.add_argument("--path", default=None, help="path for --scenario custom")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--warmup", type=float, default=5.0)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--token-file", type=Path, default=None, help="one bearer token per line")
    parser.add_argument("--note", default="", help="commit, head, image, CPU/RAM of the machine under test")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    paths = {
        "health": "/health/live",
        "feed": "/api/v2/feed/requests",
        "public-listing": "/api/v2/public/listings/{token}",
        "custom": args.path or "/",
    }
    path = paths[args.scenario]
    tokens = [line.strip() for line in args.token_file.read_text().splitlines() if line.strip()] if args.token_file else []
    if args.scenario == "feed" and not tokens:
        parser.error("--scenario feed needs --token-file (the feed is authenticated)")

    not_measured = [
        "accept p95 (a money command: run it with a prepared plan on staging, never against production)",
        "50 drivers sending tracking points (needs real devices or a device simulator - §10.5)",
        "100 000 listing catalogue unless the target database really holds it (check before quoting a number)",
        "Android network quality and battery behaviour (out of this repository's scope)",
    ]
    result = run_scenario(
        url=args.base_url.rstrip("/") + path, tokens=tokens, duration=args.duration, concurrency=args.concurrency,
        timeout=args.timeout, warmup=args.warmup, name=args.scenario,
    )
    if args.json:
        print(json.dumps({
            "scenario": result.name,
            "samples": len(result.samples),
            "successful": len(result.durations),
            "statuses": dict(result.statuses()),
            "p50": result.percentile(0.5),
            "p95": result.percentile(0.95),
            "p99": result.percentile(0.99),
            "reportable": len(result.durations) >= args.min_samples,
            "note": args.note,
            "not_measured": not_measured,
        }, indent=2))
    else:
        print(render(result, min_samples=args.min_samples, target=TARGETS_SECONDS.get(args.scenario),
                     note=args.note, not_measured=not_measured))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
