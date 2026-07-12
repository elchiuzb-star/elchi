from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ClientProfile, User


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_client_can_get_and_update_own_profile() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    client_user = User(phone="+998904000001", role="client", status="active", is_phone_verified=True)
    driver_user = User(phone="+998904000002", role="driver", status="active", is_phone_verified=True)
    blocked_client = User(phone="+998904000003", role="client", status="blocked", is_phone_verified=True)
    db.add_all([client_user, driver_user, blocked_client])
    db.commit()
    client_token = create_access_token(str(client_user.id))
    driver_token = create_access_token(str(driver_user.id))
    blocked_token = create_access_token(str(blocked_client.id))
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        api = TestClient(app)

        initial = api.get("/api/v1/client/profile", headers=headers(client_token))
        assert initial.status_code == 200
        assert initial.json()["data"]["full_name"] is None

        update = api.patch(
            "/api/v1/client/profile",
            headers=headers(client_token),
            json={"full_name": "Ali Valiyev"},
        )
        assert update.status_code == 200
        assert update.json()["data"]["full_name"] == "Ali Valiyev"

        me = api.get("/api/v1/auth/me", headers=headers(client_token))
        assert me.status_code == 200
        assert me.json()["full_name"] == "Ali Valiyev"

        db = TestingSessionLocal()
        user = db.get(User, client_user.id)
        profile = db.scalar(select(ClientProfile).where(ClientProfile.user_id == client_user.id))
        assert user.full_name == "Ali Valiyev"
        assert profile.full_name == "Ali Valiyev"
        db.close()

        assert api.get("/api/v1/client/profile").status_code == 401
        assert api.get("/api/v1/client/profile", headers=headers(driver_token)).status_code == 403
        assert api.get("/api/v1/client/profile", headers=headers(blocked_token)).status_code == 403

        invalid = api.patch("/api/v1/client/profile", headers=headers(client_token), json={"full_name": ""})
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
