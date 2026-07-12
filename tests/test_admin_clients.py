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
from app.models import AuditLog, ClientProfile, User


@pytest.fixture()
def admin_clients_client() -> tuple[TestClient, dict[str, str], sessionmaker, dict[str, int]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998940000001", role="client", status="active", is_phone_verified=True, full_name="Client User")
    operator = User(phone="+998940000002", role="operator", status="active", is_phone_verified=True)
    admin = User(phone="+998940000003", role="admin", status="active", is_phone_verified=True)
    super_admin = User(phone="+998940000004", role="super_admin", status="active", is_phone_verified=True)
    db.add_all([client_user, operator, admin, super_admin])
    db.flush()
    db.add(ClientProfile(user_id=client_user.id, full_name="Client Profile"))
    db.commit()
    tokens = {
        "client": create_access_token(str(client_user.id)),
        "operator": create_access_token(str(operator.id)),
        "admin": create_access_token(str(admin.id)),
        "super_admin": create_access_token(str(super_admin.id)),
    }
    ids = {"client": client_user.id}
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


def test_admin_can_block_and_unblock_client(admin_clients_client) -> None:
    client, tokens, session_factory, ids = admin_clients_client

    block = client.post(
        f"/api/v1/admin/clients/{ids['client']}/block",
        headers=headers(tokens["admin"]),
        json={"reason": "Fraud review"},
    )

    assert block.status_code == 200
    assert block.json()["data"]["status"] == "blocked"
    db = session_factory()
    user = db.get(User, ids["client"])
    block_audit = db.scalar(select(AuditLog).where(AuditLog.action == "client_blocked", AuditLog.entity_id == ids["client"]))
    assert user.status == "blocked"
    assert block_audit is not None
    assert block_audit.details["reason"] == "Fraud review"
    db.close()

    unblock = client.post(
        f"/api/v1/admin/clients/{ids['client']}/unblock",
        headers=headers(tokens["super_admin"]),
        json={"reason": "Review completed"},
    )

    assert unblock.status_code == 200
    assert unblock.json()["data"]["status"] == "active"
    db = session_factory()
    user = db.get(User, ids["client"])
    unblock_audit = db.scalar(select(AuditLog).where(AuditLog.action == "client_unblocked", AuditLog.entity_id == ids["client"]))
    assert user.status == "active"
    assert unblock_audit is not None
    assert unblock_audit.details["reason"] == "Review completed"
    db.close()


def test_operator_cannot_block_client(admin_clients_client) -> None:
    client, tokens, session_factory, ids = admin_clients_client

    response = client.post(
        f"/api/v1/admin/clients/{ids['client']}/block",
        headers=headers(tokens["operator"]),
        json={"reason": "Operator attempt"},
    )

    assert response.status_code == 403
    db = session_factory()
    user = db.get(User, ids["client"])
    assert user.status == "active"
    db.close()
