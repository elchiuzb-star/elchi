"""Wave 6 / §19.2-§19.3: the application now measures its own requests - and says what that number is not.

* every request writes one structured access line with route template, status and ``duration_ms`` (§19.2), with
  ids that are opaque public ids and nothing else - no query string, no phone, no token;
* the SLO answer reports ``feed_p95_seconds`` / ``booking_accept_p95_seconds`` from those measurements instead of
  ``measured: false``, but only once the sample is big enough, and it states that the number is server-side
  handler time from one worker process;
* ``server_error_rate`` and ``outbox_oldest_pending_seconds`` (§19.2 "5xx", "outbox lag/retries") are reported
  from real counts.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.operations import service as operations_service
from app.ops import metrics
from app.ops.request_id import RequestIdMiddleware
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    auth,
    bw,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
def _fresh_registry() -> None:
    metrics.REGISTRY.reset()
    yield
    metrics.REGISTRY.reset()


def _app() -> TestClient:
    app = FastAPI()

    @app.get("/api/v2/feed")
    def feed() -> dict[str, str]:  # noqa: ANN202
        return {"ok": "1"}

    @app.get("/api/v2/bookings/{booking_id}")
    def booking(booking_id: str) -> dict[str, str]:  # noqa: ANN202, ARG001
        return {"ok": "1"}

    @app.get("/api/v2/boom")
    def boom() -> dict[str, str]:  # noqa: ANN202
        raise RuntimeError("boom")

    app.add_middleware(RequestIdMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_access_line_carries_route_status_and_duration_without_secrets(caplog: pytest.LogCaptureFixture) -> None:
    client = _app()
    with caplog.at_level(logging.INFO, logger="elchi.access"):
        client.get("/api/v2/bookings/bkg_01JQ8Z0000000000000000?token=secret-value")

    record = next(item for item in caplog.records if item.name == "elchi.access")
    assert record.route == "/api/v2/bookings/{booking_id}"  # the template, never the concrete path
    assert record.status_code == 200
    assert record.duration_ms >= 0
    assert record.booking_id == "bkg_01JQ8Z0000000000000000"  # §19.2 asks for it; a public id is not a secret
    assert "secret-value" not in str(vars(record))  # the query string never reaches the log


def test_latency_is_reported_only_with_enough_samples(bw: BW) -> None:  # noqa: F811
    client = _app()
    with bw.db.session() as session:
        before = {item.name: item for item in operations_service.slo_report(session, actor_user_id=bw.operator_id).indicators}
    assert before["feed_p95_seconds"].measured is False
    assert before["feed_p95_seconds"].value is None

    for _ in range(operations_service.LATENCY_MIN_SAMPLES):
        client.get("/api/v2/feed")

    with bw.db.session() as session:
        after = {item.name: item for item in operations_service.slo_report(session, actor_user_id=bw.operator_id).indicators}
    feed = after["feed_p95_seconds"]
    assert feed.measured is True
    assert feed.value is not None and feed.value >= 0
    assert feed.sample_size >= operations_service.LATENCY_MIN_SAMPLES
    assert "worker process" in (feed.note or ""), "the answer must say the number is per-process server time"
    # An untouched bucket stays honest instead of borrowing the feed's samples.
    assert after["booking_accept_p95_seconds"].measured is False


def test_server_error_rate_counts_real_failures(bw: BW) -> None:  # noqa: F811
    client = _app()
    client.get("/api/v2/feed")
    client.get("/api/v2/boom")

    with bw.db.session() as session:
        indicators = {item.name: item for item in operations_service.slo_report(session, actor_user_id=bw.operator_id).indicators}
    rate = indicators["server_error_rate"]
    assert rate.measured is True
    assert rate.sample_size == 2
    assert rate.value == 0.5


def test_outbox_lag_is_reported_from_the_queue(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        indicators = {item.name: item for item in operations_service.slo_report(session, actor_user_id=bw.operator_id).indicators}
    lag = indicators["outbox_oldest_pending_seconds"]
    assert lag.measured is True
    assert lag.value is not None and lag.value >= 0
    assert "undelivered event" in (lag.note or "")


def test_bucket_mapping_keeps_the_registry_small() -> None:
    assert metrics.bucket_for("/api/v2/feed") == metrics.BUCKET_FEED
    assert metrics.bucket_for("/api/v2/listings/{listing_id}/matches") == metrics.BUCKET_FEED
    assert metrics.bucket_for("/api/v2/proposals/{thread_id}/accept") == metrics.BUCKET_ACCEPT
    assert metrics.bucket_for("/api/v2/whatever/{id}") == metrics.BUCKET_OTHER
