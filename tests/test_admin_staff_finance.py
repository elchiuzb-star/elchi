"""Finance staff role on the v1 staff paths and staff create with username + password (Q17/Q69, admin panel).

v1 stays backward compatible: the old phone-only create, the staff list shape and every existing error keep working;
the new fields are additive. Rules that keep finance out (audit log, v1 settings, v1 staff list) are unchanged.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers mappers)
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, RefreshSession, User

PASSWORD = "S3cret-pass"


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    try:
        yield TestClient(app), db
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def make_staff(db: Session, username: str, role: str, phone: str) -> User:
    user = User(phone=phone, username=username, password_hash=hash_password(PASSWORD), role=role, status="active",
                is_phone_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/staff-login", json={"username": username, "password": password})


def bearer(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, str]:
    response = login(client, username, password)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def staff(ctx):
    client, db = ctx
    make_staff(db, "root", "super_admin", "+998901110001")
    make_staff(db, "ops", "operator", "+998901110002")
    make_staff(db, "fin", "finance", "+998901110003")
    return client, db


# --- finance signs in and reads only what its rules allow ---------------------------------------------------------


def test_finance_signs_in_with_password(staff) -> None:
    client, _ = staff
    response = login(client, "fin")
    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == "finance"


def test_finance_cannot_use_phone_otp(staff) -> None:
    client, _ = staff
    response = client.post("/api/v1/auth/request-otp", json={"phone": "+998901110003", "role": "finance"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"


def test_finance_reads_its_own_inbox_and_profile_but_not_closed_v1_surfaces(staff) -> None:
    client, _ = staff
    headers = bearer(client, "fin")
    assert client.get("/api/v1/notifications", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    renamed = client.patch("/api/v1/auth/me", json={"full_name": "Farida Moliya"}, headers=headers)
    assert renamed.status_code == 200, renamed.text
    # kept closed on purpose (AGENTS rules): staff list, audit log, v1 settings, v1 orders
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/audit-logs", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/settings", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/orders", headers=headers).status_code == 403


def test_finance_cannot_delete_its_own_account(staff) -> None:
    client, _ = staff
    response = client.delete("/api/v1/auth/me", headers=bearer(client, "fin"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "STAFF_DELETE_FORBIDDEN"


# --- staff list ----------------------------------------------------------------------------------------------------


def test_staff_list_includes_finance_with_additive_fields(staff) -> None:
    client, _ = staff
    response = client.get("/api/v1/admin/users", headers=bearer(client, "ops"))
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert {item["role"] for item in items} == {"super_admin", "operator", "finance"}
    for item in items:
        assert item["public_id"].startswith("usr_") and item["has_password"] is True and item["username"]
        assert "password_hash" not in item
        # the original keys are all still there
        assert {"id", "phone", "full_name", "role", "status", "is_phone_verified", "last_login_at", "created_at",
                "updated_at"} <= set(item)
    only_finance = client.get("/api/v1/admin/users", params={"role": "finance"}, headers=bearer(client, "ops"))
    assert [item["username"] for item in only_finance.json()["data"]["items"]] == ["fin"]
    by_username = client.get("/api/v1/admin/users", params={"search": "fin"}, headers=bearer(client, "ops"))
    assert [item["username"] for item in by_username.json()["data"]["items"]] == ["fin"]


def test_super_admin_manages_a_finance_user(staff) -> None:
    client, db = staff
    fin = db.scalar(select(User).where(User.username == "fin"))
    headers = bearer(client, "root")
    assert client.get(f"/api/v1/admin/users/{fin.id}", headers=headers).status_code == 200
    blocked = client.post(f"/api/v1/admin/users/{fin.id}/block", headers=headers)
    assert blocked.status_code == 200 and blocked.json()["data"]["status"] == "blocked"
    assert login(client, "fin").status_code == 403
    assert client.post(f"/api/v1/admin/users/{fin.id}/unblock", headers=headers).status_code == 200
    ops = db.scalar(select(User).where(User.username == "ops"))
    moved = client.patch(f"/api/v1/admin/users/{ops.id}", json={"role": "finance"}, headers=headers)
    assert moved.status_code == 200 and moved.json()["data"]["role"] == "finance"
    refused = client.patch(f"/api/v1/admin/users/{ops.id}", json={"role": "super_admin"}, headers=headers)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


# --- create with username + password ------------------------------------------------------------------------------


def test_super_admin_creates_finance_with_a_login_that_works_at_once(staff) -> None:
    client, db = staff
    response = client.post(
        "/api/v1/admin/users",
        json={"phone": "901110009", "role": "finance", "full_name": "Yangi Moliya", "username": "  New.Fin ",
              "password": "Initial-pass1"},
        headers=bearer(client, "root"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["role"], body["username"], body["has_password"], body["phone"]) == (
        "finance", "new.fin", True, "+998901110009")
    assert body["public_id"].startswith("usr_") and "password" not in body and "password_hash" not in body
    signed_in = login(client, "NEW.FIN", "Initial-pass1")
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["role"] == "finance"
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "admin_user_created"))
    assert audit is not None and "Initial-pass1" not in str(audit.details)


def test_old_phone_only_create_still_works(staff) -> None:
    client, _ = staff
    response = client.post("/api/v1/admin/users", json={"phone": "+998901110010", "role": "operator"},
                           headers=bearer(client, "root"))
    assert response.status_code == 200, response.text
    assert response.json()["has_password"] is False and response.json()["username"] is None


@pytest.mark.parametrize(
    ("extra", "code", "field"),
    [
        ({"username": "only.name"}, "VALIDATION_ERROR", "password"),
        ({"password": "Initial-pass1"}, "VALIDATION_ERROR", "username"),
        ({"username": "ab", "password": "Initial-pass1"}, "VALIDATION_ERROR", "username"),
        ({"username": "bad name", "password": "Initial-pass1"}, "VALIDATION_ERROR", "username"),
        ({"username": "good.name", "password": "short"}, "VALIDATION_ERROR", "password"),
        ({"username": "good.name", "password": "ж" * 37}, "VALIDATION_ERROR", "password"),  # 74 bytes > bcrypt limit
    ],
)
def test_create_refuses_a_half_or_weak_login(staff, extra, code, field) -> None:
    client, _ = staff
    response = client.post("/api/v1/admin/users", json={"phone": "+998901110011", "role": "admin", **extra},
                           headers=bearer(client, "root"))
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"]["field"] == field


def test_create_refuses_a_taken_username_and_super_admin_role(staff) -> None:
    client, _ = staff
    headers = bearer(client, "root")
    taken = client.post("/api/v1/admin/users", json={"phone": "+998901110012", "role": "admin", "username": "OPS",
                                                     "password": "Initial-pass1"}, headers=headers)
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "USERNAME_TAKEN"
    role = client.post("/api/v1/admin/users", json={"phone": "+998901110013", "role": "super_admin"}, headers=headers)
    assert role.status_code == 400 and role.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
    not_super = client.post("/api/v1/admin/users", json={"phone": "+998901110014", "role": "admin"},
                            headers=bearer(client, "ops"))
    assert not_super.status_code == 403


# --- credentials reset --------------------------------------------------------------------------------------------


def test_credentials_reset_revokes_sessions_and_the_new_password_works(staff) -> None:
    client, db = staff
    fin = db.scalar(select(User).where(User.username == "fin"))
    old_session = login(client, "fin").json()
    response = client.put(f"/api/v1/admin/users/{fin.id}/credentials", json={"password": "Brand-new-pass"},
                          headers=bearer(client, "root"))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["has_password"] is True
    assert login(client, "fin").status_code == 401
    assert login(client, "fin", "Brand-new-pass").status_code == 200
    db.expire_all()
    revoked = db.scalars(select(RefreshSession).where(RefreshSession.user_id == fin.id)).all()
    assert any(row.is_revoked and row.revoked_reason == "admin_revoke" for row in revoked)
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old_session["refresh_token"]}).status_code == 401


def test_credentials_reset_guards(staff) -> None:
    client, db = staff
    headers = bearer(client, "root")
    ops = db.scalar(select(User).where(User.username == "ops"))
    renamed = client.put(f"/api/v1/admin/users/{ops.id}/credentials", json={"username": "olim.op"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["data"]["username"] == "olim.op"
    clash = client.put(f"/api/v1/admin/users/{ops.id}/credentials", json={"username": "fin"}, headers=headers)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "USERNAME_TAKEN"
    empty = client.put(f"/api/v1/admin/users/{ops.id}/credentials", json={}, headers=headers)
    assert empty.status_code == 400
    client_user = User(phone="+998901110099", role="client", status="active", is_phone_verified=True)
    db.add(client_user)
    db.commit()
    assert client.put(f"/api/v1/admin/users/{client_user.id}/credentials", json={"password": "Brand-new-pass"},
                      headers=headers).status_code == 404
    other_super = make_staff(db, "root2", "super_admin", "+998901110098")
    assert client.put(f"/api/v1/admin/users/{other_super.id}/credentials", json={"password": "Brand-new-pass"},
                      headers=headers).status_code == 404
    assert client.put(f"/api/v1/admin/users/{ops.id}/credentials", json={"password": "Brand-new-pass"},
                      headers=bearer(client, "fin")).status_code == 403
