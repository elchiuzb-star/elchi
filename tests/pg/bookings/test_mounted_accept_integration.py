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
from tests.pg.bookings.conftest import BW, auth, listing_version, request_with_driver_proposal, scalar

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
