"""v1 side of §17.6 - user decision of 17.09.2026 (option A in ``decisions-pending/v1-logout-access-token.md``).

Logging out now ends the *access* token too, not only the refresh token. The rule is deliberately narrow:

* only a token that names its login session (``sid``) is checked, so tokens minted before that claim existed
  keep working until they expire - this release logs nobody out by itself;
* the v1 envelope, status codes and token format are unchanged (AGENTS §2): a revoked session is the same
  ``401`` an expired token already produced;
* one device logging out never touches another device's session.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers the mappers)
from app.core.config import settings
from app.core.security import create_access_token, verify_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import OtpCode, RefreshSession, User


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():  # noqa: ANN202
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client: TestClient, phone: str) -> dict:
    with next(app.dependency_overrides[get_db]()) as db:  # a used OTP row blocks the next login, not this test
        for row in db.scalars(select(OtpCode).where(OtpCode.phone == phone)):
            db.delete(row)
        db.commit()
    client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": "client"})
    response = client.post(
        "/api/v1/auth/verify-otp", json={"phone": phone, "role": "client", "otp": settings.dev_mock_otp}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _me(client: TestClient, access_token: str):  # noqa: ANN202
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})


def test_logout_stops_the_access_token_immediately(client: TestClient) -> None:
    tokens = _login(client, "+998902100001")
    assert _me(client, tokens["access_token"]).status_code == 200

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert logout.status_code == 200

    after = _me(client, tokens["access_token"])
    assert after.status_code == 401, "the whole point: the token outlived the session before this change"
    body = after.json()
    assert body["success"] is False and body["error"]["code"], "v1 envelope shape is unchanged"


def test_a_token_without_the_session_claim_is_left_alone(client: TestClient) -> None:
    """Old clients hold tokens minted before `sid` existed; this release must not log them out."""
    with next(app.dependency_overrides[get_db]()) as db:
        user = User(phone="+998902100002", role="client", status="active", is_phone_verified=True)
        db.add(user)
        db.commit()
        legacy_token = create_access_token(str(user.id))  # no `sid` claim
    assert verify_token(legacy_token).get("sid") is None
    assert _me(client, legacy_token).status_code == 200


def test_logging_out_one_device_leaves_the_other_signed_in(client: TestClient) -> None:
    first = _login(client, "+998902100003")
    second = _login(client, "+998902100003")
    assert verify_token(first["access_token"])["sid"] != verify_token(second["access_token"])["sid"]

    client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {first['access_token']}"},
        json={"refresh_token": first["refresh_token"]},
    )
    assert _me(client, first["access_token"]).status_code == 401
    assert _me(client, second["access_token"]).status_code == 200, "a second phone is a separate session"


def test_refresh_rotation_does_not_kill_an_in_flight_access_token(client: TestClient) -> None:
    """The decision was about logout, not rotation.

    A refresh revokes the old session row and creates a successor, so a strict reading would 401 every request
    the frozen Android client already had in flight while it rotated. ``revoked_reason='rotated'`` keeps that
    from happening on v1: the old access token finishes its own lifetime, and nothing about logout is relaxed.
    """
    tokens = _login(client, "+998902100004")
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).json()
    assert _me(client, rotated["access_token"]).status_code == 200
    assert _me(client, tokens["access_token"]).status_code == 200

    # ... and logging out still ends it at once, which is the part that was approved.
    client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert _me(client, rotated["access_token"]).status_code == 401


def test_v2_still_refuses_a_rotated_session(client: TestClient) -> None:
    """The v2 client is ours, so it keeps the stricter rule shipped in wave 6 - v1 is the only exception."""
    from app.services.auth_service import session_revoked

    tokens = _login(client, "+998902100007")
    client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    payload = verify_token(tokens["access_token"])
    with next(app.dependency_overrides[get_db]()) as db:
        assert session_revoked(db, payload) is True  # v2 / tracking websocket
        assert session_revoked(db, payload, include_rotated=False) is False  # v1


def test_a_blocked_account_still_answers_403_not_401(client: TestClient) -> None:
    """The existing status check keeps its own code; session revocation did not swallow it."""
    tokens = _login(client, "+998902100005")
    with next(app.dependency_overrides[get_db]()) as db:
        user = db.scalar(select(User).where(User.phone == "+998902100005"))
        user.status = "blocked"
        db.commit()
    assert _me(client, tokens["access_token"]).status_code == 403


def test_an_unknown_session_id_is_refused(client: TestClient) -> None:
    """A forged or deleted session must fail closed, not fall through as "no session named"."""
    tokens = _login(client, "+998902100006")
    sid = verify_token(tokens["access_token"])["sid"]
    with next(app.dependency_overrides[get_db]()) as db:
        db.delete(db.scalar(select(RefreshSession).where(RefreshSession.jti == sid)))
        db.commit()
    assert _me(client, tokens["access_token"]).status_code == 401
