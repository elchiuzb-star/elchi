from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, User
from app.services.audit_service import write_audit_log


@pytest.fixture()
def audit_logs_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    users = {
        "client": User(phone="+998980000001", role="client", status="active", is_phone_verified=True, full_name="Client"),
        "driver": User(phone="+998980000002", role="driver", status="active", is_phone_verified=True, full_name="Driver"),
        "operator": User(phone="+998980000003", role="operator", status="active", is_phone_verified=True, full_name="Operator"),
        "admin": User(phone="+998980000004", role="admin", status="active", is_phone_verified=True, full_name="Admin"),
        "super_admin": User(phone="+998980000005", role="super_admin", status="active", is_phone_verified=True, full_name="Super"),
        "blocked_admin": User(phone="+998980000006", role="admin", status="blocked", is_phone_verified=True),
    }
    db.add_all(users.values())
    db.flush()
    write_audit_log(
        db,
        users["admin"],
        "orders",
        1001,
        "admin_order_cancelled",
        old_value={"status": "accepted"},
        new_value={"status": "cancelled", "access_token": "secret-token"},
        reason="Client unreachable",
        ip_address="127.0.0.1",
        user_agent="pytest",
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    write_audit_log(
        db,
        users["operator"],
        "drivers",
        2001,
        "driver_approved",
        old_value={"verification_status": "pending"},
        new_value={"verification_status": "approved"},
        reason="Documents checked",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    write_audit_log(
        db,
        users["super_admin"],
        "route_tariffs",
        3001,
        "route_tariff_updated",
        old_value={"suggested_price": 50000},
        new_value={"suggested_price": 60000, "api_key": "hidden"},
        reason="Price correction",
        created_at=datetime.now(timezone.utc),
    )
    db.add(
        AuditLog(
            actor_id=users["super_admin"].id,
            entity_type="auth",
            entity_id=users["super_admin"].id,
            action="token_refreshed",
            details={
                "actor_role": "super_admin",
                "old_value": None,
                "new_value": {"phone": users["super_admin"].phone, "role": users["super_admin"].role},
                "reason": None,
                "ip_address": None,
                "user_agent": None,
            },
            created_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
    )
    db.flush()
    logs = list(db.scalars(select(AuditLog).order_by(AuditLog.id.asc())))
    db.commit()

    tokens = {key: create_access_token(str(user.id)) for key, user in users.items()}
    ids = {key: user.id for key, user in users.items()}
    ids.update({"order_log": logs[0].id, "driver_log": logs[1].id, "tariff_log": logs[2].id})
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), tokens, TestingSessionLocal, ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admin_and_super_admin_can_list_audit_logs(audit_logs_client, role: str) -> None:
    client, tokens, _session_factory, _ids = audit_logs_client

    response = client.get("/api/v1/admin/audit-logs", headers=headers(tokens[role]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 3
    assert "token_refreshed" not in {item["action"] for item in data["items"]}
    assert data["items"][0]["action"] == "route_tariff_updated"
    assert data["items"][0]["created_at"] >= data["items"][1]["created_at"]


@pytest.mark.parametrize("role", ["client", "driver", "operator", "blocked_admin"])
def test_non_admin_roles_cannot_list_audit_logs(audit_logs_client, role: str) -> None:
    client, tokens, _session_factory, _ids = audit_logs_client

    response = client.get("/api/v1/admin/audit-logs", headers=headers(tokens[role]))

    assert response.status_code == 403
    expected_message = "User account is not active" if role == "blocked_admin" else "Admin or super admin role required"
    assert response.json()["error"] == {"code": "FORBIDDEN", "message": expected_message}


def test_anonymous_user_cannot_list_audit_logs(audit_logs_client) -> None:
    client, _tokens, _session_factory, _ids = audit_logs_client

    response = client.get("/api/v1/admin/audit-logs")

    assert response.status_code == 401
    assert response.json()["error"] == {"code": "UNAUTHORIZED", "message": "Authentication required"}


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admin_can_view_audit_log_detail_with_values(audit_logs_client, role: str) -> None:
    client, tokens, _session_factory, ids = audit_logs_client

    response = client.get(f"/api/v1/admin/audit-logs/{ids['order_log']}", headers=headers(tokens[role]))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["actor"]["phone"] == "+998980000004"
    assert data["actor_role"] == "admin"
    assert data["entity_type"] == "orders"
    assert data["entity_id"] == 1001
    assert data["old_value"] == {"status": "accepted"}
    assert data["new_value"] == {"status": "cancelled", "access_token": "[REDACTED]"}
    assert data["reason"] == "Client unreachable"
    assert data["ip_address"] == "127.0.0.1"
    assert data["user_agent"] == "pytest"


def test_audit_log_not_found_returns_not_found(audit_logs_client) -> None:
    client, tokens, _session_factory, _ids = audit_logs_client

    response = client.get("/api/v1/admin/audit-logs/999999", headers=headers(tokens["admin"]))

    assert response.status_code == 404
    assert response.json()["error"] == {"code": "NOT_FOUND", "message": "Audit log not found"}


def test_audit_log_filters_work(audit_logs_client) -> None:
    client, tokens, _session_factory, ids = audit_logs_client

    by_actor = client.get(f"/api/v1/admin/audit-logs?actor_id={ids['operator']}", headers=headers(tokens["admin"]))
    by_role = client.get("/api/v1/admin/audit-logs?actor_role=operator", headers=headers(tokens["admin"]))
    by_entity_type = client.get("/api/v1/admin/audit-logs?entity_type=orders", headers=headers(tokens["admin"]))
    by_entity_id = client.get("/api/v1/admin/audit-logs?entity_id=2001", headers=headers(tokens["admin"]))
    by_action = client.get("/api/v1/admin/audit-logs?action=route_tariff_updated", headers=headers(tokens["admin"]))
    by_noisy_action = client.get("/api/v1/admin/audit-logs?action=token_refreshed", headers=headers(tokens["admin"]))
    by_search = client.get("/api/v1/admin/audit-logs?search=Client unreachable", headers=headers(tokens["admin"]))

    assert by_actor.json()["data"]["pagination"]["total"] == 1
    assert by_actor.json()["data"]["items"][0]["action"] == "driver_approved"
    assert by_role.json()["data"]["pagination"]["total"] == 1
    assert by_entity_type.json()["data"]["items"][0]["entity_type"] == "orders"
    assert by_entity_id.json()["data"]["items"][0]["entity_id"] == 2001
    assert by_action.json()["data"]["items"][0]["action"] == "route_tariff_updated"
    assert by_noisy_action.json()["data"]["pagination"]["total"] == 1
    assert by_noisy_action.json()["data"]["items"][0]["action"] == "token_refreshed"
    assert by_search.json()["data"]["items"][0]["reason"] == "Client unreachable"


def test_audit_log_date_filters_pagination_and_invalid_values(audit_logs_client) -> None:
    client, tokens, session_factory, _ids = audit_logs_client
    db = session_factory()
    middle_log = db.scalar(select(AuditLog).where(AuditLog.action == "driver_approved"))
    date_filter = middle_log.created_at.date().isoformat()
    db.close()

    from_response = client.get(f"/api/v1/admin/audit-logs?created_from={date_filter}", headers=headers(tokens["admin"]))
    to_response = client.get(f"/api/v1/admin/audit-logs?created_to={date_filter}", headers=headers(tokens["admin"]))
    paginated = client.get("/api/v1/admin/audit-logs?page=2&limit=1", headers=headers(tokens["admin"]))
    invalid_limit = client.get("/api/v1/admin/audit-logs?limit=101", headers=headers(tokens["admin"]))
    invalid_role = client.get("/api/v1/admin/audit-logs?actor_role=owner", headers=headers(tokens["admin"]))
    invalid_date = client.get("/api/v1/admin/audit-logs?created_from=not-a-date", headers=headers(tokens["admin"]))

    assert from_response.status_code == 200
    assert from_response.json()["data"]["pagination"]["total"] == 2
    assert to_response.json()["data"]["pagination"]["total"] == 2
    assert paginated.json()["data"]["pagination"] == {"page": 2, "limit": 1, "total": 3, "total_pages": 3}
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Invalid pagination parameters"}
    assert invalid_role.status_code == 400
    assert invalid_role.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Invalid filter value"}
    assert invalid_date.status_code == 400
    assert invalid_date.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Invalid filter value"}


def test_audit_log_endpoints_are_read_only(audit_logs_client) -> None:
    client, tokens, _session_factory, ids = audit_logs_client

    post_response = client.post("/api/v1/admin/audit-logs", headers=headers(tokens["admin"]), json={})
    patch_response = client.patch(f"/api/v1/admin/audit-logs/{ids['order_log']}", headers=headers(tokens["admin"]), json={})
    delete_response = client.delete(f"/api/v1/admin/audit-logs/{ids['order_log']}", headers=headers(tokens["admin"]))

    assert post_response.status_code == 405
    assert patch_response.status_code == 405
    assert delete_response.status_code == 405


def test_audit_logs_are_immutable_in_orm(audit_logs_client) -> None:
    _client, _tokens, session_factory, ids = audit_logs_client
    db = session_factory()

    log = db.get(AuditLog, ids["order_log"])
    log.action = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        db.commit()
    db.rollback()

    log = db.get(AuditLog, ids["order_log"])
    db.delete(log)
    with pytest.raises(ValueError, match="immutable"):
        db.commit()
    db.rollback()
    assert db.get(AuditLog, ids["order_log"]) is not None
    db.close()


def test_write_audit_log_redacts_sensitive_values(audit_logs_client) -> None:
    _client, _tokens, session_factory, ids = audit_logs_client
    db = session_factory()
    actor = db.get(User, ids["admin"])

    write_audit_log(
        db,
        actor,
        "users",
        ids["client"],
        "user_updated",
        old_value={"password_hash": "old"},
        new_value={"nested": {"refresh_token": "new"}, "safe": "value"},
    )
    db.commit()
    log = db.scalar(select(AuditLog).where(AuditLog.action == "user_updated"))

    assert log.actor_id == ids["admin"]
    assert log.details["actor_role"] == "admin"
    assert log.details["old_value"] == {"password_hash": "[REDACTED]"}
    assert log.details["new_value"] == {"nested": {"refresh_token": "[REDACTED]"}, "safe": "value"}
    db.close()


def test_stage_17_does_not_add_forbidden_audit_fields(audit_logs_client) -> None:
    _client, _tokens, _session_factory, _ids = audit_logs_client

    audit_columns = set(AuditLog.__table__.columns.keys())
    forbidden_columns = {
        "gps_location",
        "payment_gateway_id",
        "otp_code",
        "qr_code",
        "proof_file",
        "capacity",
        "weight",
        "size",
        "cargo_type",
    }

    assert forbidden_columns.isdisjoint(audit_columns)
