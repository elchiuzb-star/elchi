"""Integrator check (wave 2 bookings pass): P8 accept over the REAL mounted app (``app.main``).

A4's own HTTP tests use a test-local FastAPI app; this proves the integrated mount keeps the idempotency
route scope ``/api/v2/proposals/{thread_id}/accept``, the 201 envelope and replay semantics (ADR-0005).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_db
from app.main import app
from tests.pg.bookings.conftest import BW, auth, counter, listing_version, request_with_driver_proposal, scalar

pytestmark = pytest.mark.pg


@pytest.fixture
def mounted(bw: BW) -> Iterator[TestClient]:
    def override_db() -> Iterator:
        session = bw.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_accept_idempotent_replay_over_mounted_app(bw: BW, mounted: TestClient) -> None:
    listing, _, _, ref = request_with_driver_proposal(bw)
    body = {"proposal_version_id": ref.version_id, "expected_listing_terms_version": listing_version(bw, listing)}
    url = f"/api/v2/proposals/{ref.thread_id}/accept"
    headers = auth(bw.w.client_id, "client", "mounted-accept-0001")

    first = mounted.post(url, json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["data"]["id"].startswith("bkg_")
    assert "X-Request-ID" in first.headers  # integrated middleware

    replay = mounted.post(url, json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json() == first.json()
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 1

    with bw.db.session() as db:
        routes = db.execute(text("SELECT route FROM idempotency_records WHERE route LIKE '%/accept%'")).scalars().all()
    assert routes and all("/api/v2/proposals/" in route for route in routes), routes


def test_driver_reads_the_listing_terms_version_from_the_thread_and_accepts_with_it(bw: BW, mounted: TestClient) -> None:
    """Q54: the accepting driver sees only ``ListingPublicDTO`` (no terms_version), so the thread it is a party to
    carries it; accepting with exactly that value succeeds without a 409 PROPOSAL_CHANGED round trip."""
    listing, _, _, ref = request_with_driver_proposal(bw)
    ref = counter(bw, ref, bw.w.client_id, unit=18_500_000)  # the client's counter is now the driver's to accept

    read = mounted.get(f"/api/v2/proposals/{ref.thread_id}", headers=auth(bw.w.driver_id, "driver"))
    assert read.status_code == 200, read.text
    thread = read.json()["data"]
    assert thread["listing_terms_version"] == listing_version(bw, listing)
    assert thread["current_version"]["listing_terms_version"] == thread["listing_terms_version"]
    client_view = mounted.get(f"/api/v2/proposals/{ref.thread_id}", headers=auth(bw.w.client_id, "client")).json()["data"]
    assert client_view["listing_terms_version"] == thread["listing_terms_version"]
    assert "fee_quote" not in client_view["current_version"] or client_view["current_version"]["fee_quote"] is None  # Q16

    accepted = mounted.post(
        f"/api/v2/proposals/{ref.thread_id}/accept",
        json={"proposal_version_id": thread["current_version"]["id"],
              "expected_listing_terms_version": thread["listing_terms_version"]},
        headers=auth(bw.w.driver_id, "driver", "mounted-driver-accept-0001"),
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["data"]["id"].startswith("bkg_")
