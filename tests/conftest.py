"""Suite-wide test isolation (integrator, wave 3 integration pass).

``app.api.v2.router.configure_v2_ports()`` runs at app start-up and registers A12's dispute hooks in
``app.modules.bookings.service`` module-global state (dispute probe, payment dispute opener and, since
wave 5, A7's chat-thread lookup). Wave 6 adds the in-process request metrics registry for the same reason. A test that starts the app
would otherwise leak them into later tests, which then capture commission instead of following the Q74 fallback.
This fixture clears both hooks after every test. Tests that need the hooks register them inside the test (or their
own fixture), e.g. ``trust_support.service.register_booking_hooks()``.

Nothing is imported unless the bookings service is already loaded, so v1/SQLite tests pay no import cost.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest


def _reset_request_metrics() -> None:
    """Wave 6: ``app.ops.metrics.REGISTRY`` is process-global, so requests made by one test would otherwise
    decide another test's SLO answer (the §19.3 indicators read it). Cleared after every test; a test that wants
    measurements makes them itself."""
    metrics = sys.modules.get("app.ops.metrics")
    if metrics is not None:
        metrics.REGISTRY.reset()


def _reset_booking_dispute_hooks() -> None:
    bookings_service = sys.modules.get("app.modules.bookings.service")
    if bookings_service is None:
        return
    bookings_service.set_blocking_dispute_probe(None)
    bookings_service.set_payment_dispute_opener(None)
    # Wave 5: A7's chat-thread lookup is registered the same way (BookingDTO.contact.chat_thread_id).
    bookings_service.set_chat_thread_lookup(None)


@pytest.fixture(autouse=True)
def _isolate_booking_dispute_hooks() -> Iterator[None]:
    yield
    _reset_booking_dispute_hooks()
    _reset_request_metrics()
