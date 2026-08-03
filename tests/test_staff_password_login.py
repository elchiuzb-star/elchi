"""Staff sign in with username + password; the OTP path is closed to them."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers mappers)
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User

PASSWORD = "S3cret-pass"


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


def make_user(
    db: Session,
    username: str = "admin",
    role: str = "super_admin",
    phone: str = "+998901234599",
    status: str = "active",
) -> User:
    user = User(
        phone=phone,
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role,
        status=status,
        is_phone_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/staff-login", json={"username": username, "password": password})


def test_staff_login_returns_tokens(ctx) -> None:
    client, db = ctx
    make_user(db)
    response = login(client, "admin")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["role"] == "super_admin"


def test_username_is_case_insensitive(ctx) -> None:
    client, db = ctx
    make_user(db)
    assert login(client, "ADMIN").status_code == 200


def test_wrong_password_is_rejected(ctx) -> None:
    client, db = ctx
    make_user(db)
    assert login(client, "admin", "not-the-password").status_code == 401


def test_unknown_username_is_rejected(ctx) -> None:
    client, _ = ctx
    assert login(client, "nobody").status_code == 401


def test_non_staff_cannot_use_staff_login(ctx) -> None:
    """A client account with a password set must not reach the admin panel."""
    client, db = ctx
    make_user(db, username="pretender", role="client", phone="+998901234598")
    assert login(client, "pretender").status_code == 401


def test_blocked_staff_is_rejected(ctx) -> None:
    client, db = ctx
    make_user(db, status="blocked")
    assert login(client, "admin").status_code == 403


def test_staff_cannot_request_otp(ctx) -> None:
    client, db = ctx
    make_user(db)
    response = client.post(
        "/api/v1/auth/request-otp", json={"phone": "+998901234599", "role": "admin"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"


def test_client_otp_is_unaffected(ctx) -> None:
    client, _ = ctx
    response = client.post(
        "/api/v1/auth/request-otp", json={"phone": "+998901234511", "role": "client"}
    )
    assert response.status_code == 200, response.text
