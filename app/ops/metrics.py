"""In-process request metrics (spec §19.2 "API p95, 5xx"; §19.3 SLO) - wave 6.

Until now the application did not time itself, so the SLO answer reported ``feed_p95`` and ``booking_accept_p95``
as ``measured: false`` - honest, but it also meant the two targets of §19.3 could never be checked from inside
Elchi. This module records what a request actually cost **on the server**, with three deliberate limits that the
reader must know, so the number is never quoted as more than it is:

1. **server time only** - from the first ASGI event to the last byte handed to the server, without the client's
   network, TLS handshake or device rendering;
2. **this process only** - each uvicorn worker keeps its own reservoir; with several workers the SLO endpoint
   answers for the worker that served the request, and a restart clears it. There is no metrics store yet (a
   Prometheus/OTel exporter is a separate decision), so the value carries ``sample_size`` and a note;
3. **bounded memory** - a fixed-size reservoir per bucket (the newest ``MAX_SAMPLES``), never a growing list.

No PII: the registry keys are route *templates* (``/api/v2/feed``), never the concrete ids of a path.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

# Buckets the SLO cares about (§19.3). Everything else is aggregated into "other" so the registry cannot grow
# with the URL space.
BUCKET_FEED = "feed"
BUCKET_ACCEPT = "booking_accept"
BUCKET_OTHER = "other"
MAX_SAMPLES = 2048

_FEED_ROUTES = ("/api/v2/feed", "/api/v2/listings/{listing_id}/matches")
_ACCEPT_ROUTE_SUFFIX = "/accept"


def bucket_for(route: str) -> str:
    """Map a route template to an SLO bucket. Unknown routes land in ``other`` (counted, not detailed)."""
    if route in _FEED_ROUTES:
        return BUCKET_FEED
    if route.startswith("/api/v2/proposals/") and route.endswith(_ACCEPT_ROUTE_SUFFIX):
        return BUCKET_ACCEPT
    return BUCKET_OTHER


@dataclass
class BucketStats:
    count: int = 0
    errors_5xx: int = 0
    errors_4xx: int = 0
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_SAMPLES))

    def percentile(self, fraction: float) -> float | None:
        values = sorted(self.samples)
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(fraction * len(values)) - 1))
        return values[index]


@dataclass(frozen=True, slots=True)
class BucketSnapshot:
    """What a reader may quote: the counts, the percentiles and how many samples they come from."""

    bucket: str
    count: int
    errors_4xx: int
    errors_5xx: int
    sample_size: int
    p50_seconds: float | None
    p95_seconds: float | None
    p99_seconds: float | None
    since: float


class RequestMetrics:
    """Thread-safe reservoir per bucket. Cheap enough to call on every request (a lock and a deque append)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, BucketStats] = {}
        self._since = time.time()

    def observe(self, *, route: str, status_code: int, duration_seconds: float) -> None:
        bucket = bucket_for(route)
        with self._lock:
            stats = self._buckets.setdefault(bucket, BucketStats())
            stats.count += 1
            if status_code >= 500:
                stats.errors_5xx += 1
            elif status_code >= 400:
                stats.errors_4xx += 1
            stats.samples.append(max(0.0, float(duration_seconds)))

    def snapshot(self, bucket: str) -> BucketSnapshot:
        with self._lock:
            stats = self._buckets.get(bucket) or BucketStats()
            return BucketSnapshot(
                bucket=bucket, count=stats.count, errors_4xx=stats.errors_4xx, errors_5xx=stats.errors_5xx,
                sample_size=len(stats.samples), p50_seconds=stats.percentile(0.5),
                p95_seconds=stats.percentile(0.95), p99_seconds=stats.percentile(0.99), since=self._since,
            )

    def all_snapshots(self) -> list[BucketSnapshot]:
        with self._lock:
            names = sorted(self._buckets)
        return [self.snapshot(name) for name in names]

    def reset(self) -> None:
        """Tests only: a fresh registry between cases."""
        with self._lock:
            self._buckets.clear()
            self._since = time.time()


REGISTRY = RequestMetrics()
