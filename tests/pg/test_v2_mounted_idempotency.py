"""Idempotency over the REAL mounted app (app.main): route template scope is /api/v2/... (A1 request).

A1's own API tests use a test-local FastAPI app; this proves the integrated mount keeps the
same Idempotency-Key semantics (ADR-0005) and the single v2 error envelope.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.models  # noqa: F401
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models import User
from tests.pg.conftest import PgDatabase

pytestmark = pytest.mark.pg


@pytest.fixture
def mounted_client(pg_db: PgDatabase) -> Iterator[tuple[TestClient, int]]:
    with pg_db.session() as db:
        user = User(phone="+998934000001", role="client", status="active", is_phone_verified=True)
        db.add(user)
        db.commit()
        user_id = user.id

    def override_db() -> Iterator:
        session = pg_db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), user_id
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_idempotent_replay_over_mounted_v2_path(mounted_client, pg_db: PgDatabase) -> None:
    client, user_id = mounted_client
    token = create_access_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "mounted-replay-0001"}

    first = client.post("/api/v2/me/roles", json={"role": "driver"}, headers=headers)
    assert first.status_code == 200, first.text
    assert "Idempotent-Replayed" not in first.headers
    assert set(first.json()["data"]["roles"]) == {"client", "driver"}

    replay = client.post("/api/v2/me/roles", json={"role": "driver"}, headers=headers)
    assert replay.status_code == 200
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json() == first.json()

    reused = client.post("/api/v2/me/roles", json={"role": "client"}, headers=headers)
    assert reused.status_code == 409
    assert reused.json()["success"] is False and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    missing = client.post("/api/v2/me/roles", json={"role": "driver"}, headers={"Authorization": f"Bearer {token}"})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    with pg_db.session() as db:
        routes = db.execute(
            text("SELECT route FROM idempotency_records WHERE actor_user_id = :uid"), {"uid": user_id}
        ).scalars().all()
    assert routes, "idempotency record was not stored"
    assert all("/api/v2/me/roles" in route for route in routes), routes
