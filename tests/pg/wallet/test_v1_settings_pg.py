"""v1 settings adapter over HTTP on PostgreSQL (Q2, ADR-0009 §9): PATCH creates policy versions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app

pytestmark = pytest.mark.pg


@pytest.fixture
def v1_client(pg_db):
    def override():
        session = pg_db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def test_v1_patch_creates_global_standard_version_on_postgres(v1_client, people, pg_db):
    url = "/api/v1/admin/settings/driver-commission"
    denied = v1_client.patch(url, json={"driver_commission_percent": 12}, headers=_auth(people["admin"]))
    assert denied.status_code == 403
    assert denied.json() == {"success": False, "error": {"code": "FORBIDDEN", "message": "Insufficient permissions."}}
    zero = v1_client.patch(url, json={"driver_commission_percent": 0}, headers=_auth(people["super"]))
    assert zero.status_code == 400 and zero.json()["error"]["code"] == "VALIDATION_ERROR"

    ok = v1_client.patch(url, json={"driver_commission_percent": "12.5"}, headers=_auth(people["super"]))
    assert ok.status_code == 200, ok.json()
    assert set(ok.json()) == {"success", "data", "message"}
    assert set(ok.json()["data"]) == {"driver_commission_rate", "driver_commission_percent", "is_default",
                                      "updated_at", "updated_by_user_id"}
    with pg_db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT fee_bps, effective_to IS NULL, created_by, ended_by FROM commission_policies "
            "WHERE kind = 'standard' AND scope_key = '*:*' ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(1500, False, None, people["super"]), (1250, True, people["super"], None)]
    got = v1_client.get("/api/v1/admin/settings", headers=_auth(people["admin"])).json()["data"]
    assert got["driver_commission_percent"] == 12.5 and got["is_default"] is False
