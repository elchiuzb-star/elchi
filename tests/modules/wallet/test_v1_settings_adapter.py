"""v1 settings adapter on SQLite: unchanged GET shape, Q2 roles on PATCH, 0% rejected (ADR-0009 §9)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
import app.modules.wallet.models  # noqa: F401  (registers commission_policies before create_all)
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import SystemSetting, User
from app.modules.wallet.models import CommissionPolicy
from app.services.system_settings_service import get_driver_commission_rate

GET_KEYS = {"driver_commission_rate", "driver_commission_percent", "is_default", "updated_at", "updated_by_user_id"}


@pytest.fixture
def ctx():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    tokens = {}
    with Session() as db:
        for role in ("client", "operator", "admin", "super_admin"):
            user = User(phone=f"+99897000{len(tokens):04d}", role=role, status="active", is_phone_verified=True)
            db.add(user)
            db.flush()
            tokens[role] = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
        db.commit()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app), tokens, Session
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_get_shape_unchanged_and_roles(ctx):
    client, tokens, _ = ctx
    for role in ("operator", "admin", "super_admin"):
        response = client.get("/api/v1/admin/settings", headers=tokens[role])
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"success", "data", "message"} and set(body["data"]) == GET_KEYS
        assert body["data"]["driver_commission_percent"] == 15.0 and body["data"]["is_default"] is True
    assert client.get("/api/v1/admin/settings", headers=tokens["client"]).status_code == 403


def test_patch_admin_forbidden_with_v1_error_shape(ctx):
    client, tokens, Session = ctx
    response = client.patch("/api/v1/admin/settings/driver-commission", json={"driver_commission_percent": 12},
                            headers=tokens["admin"])
    assert response.status_code == 403
    assert response.json() == {"success": False, "error": {"code": "FORBIDDEN", "message": "Insufficient permissions."}}
    with Session() as db:
        assert db.execute(select(func.count()).select_from(CommissionPolicy)).scalar() == 0


def test_patch_zero_percent_is_v1_validation_error(ctx):
    client, tokens, _ = ctx
    response = client.patch("/api/v1/admin/settings/driver-commission", json={"driver_commission_percent": 0},
                            headers=tokens["super_admin"])
    assert response.status_code == 400 and response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_super_admin_patch_creates_policy_versions_and_keeps_shape(ctx):
    client, tokens, Session = ctx
    first = client.patch("/api/v1/admin/settings/driver-commission", json={"driver_commission_percent": "12.5"},
                         headers=tokens["super_admin"])
    assert first.status_code == 200, first.json()
    assert set(first.json()["data"]) == GET_KEYS and first.json()["data"]["driver_commission_percent"] == 12.5
    second = client.patch("/api/v1/admin/settings/driver-commission", json={"driver_commission_percent": 10},
                          headers=tokens["super_admin"])
    assert second.status_code == 200
    got = client.get("/api/v1/admin/settings", headers=tokens["operator"]).json()["data"]
    assert got["driver_commission_percent"] == 10.0 and got["is_default"] is False
    with Session() as db:
        rows = db.execute(select(CommissionPolicy).order_by(CommissionPolicy.id)).scalars().all()
        assert [(r.fee_bps, r.effective_to is None) for r in rows] == [(1250, False), (1000, True)]
        assert get_driver_commission_rate(db) == Decimal("0.1000")
        assert db.get(SystemSetting, "driver_commission_rate").value == "0.1000"
