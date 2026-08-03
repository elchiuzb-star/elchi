from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token, verify_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, ClientProfile, DriverProfile, OtpCode, RefreshSession, User


@pytest.fixture()
def client() -> TestClient:
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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_client_login_flow(client: TestClient) -> None:
    otp_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone": "+998901111111", "role": "client"},
    )
    assert otp_response.status_code == 200
    assert otp_response.json()["data"]["dev_otp"] == "12345"

    token_response = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+998901111111", "role": "client", "otp": "12345"},
    )
    assert token_response.status_code == 200
    body = token_response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "client"
    assert body["user"]["is_phone_verified"] is True
    assert body["access_token"]
    assert body["refresh_token"]

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["phone"] == "+998901111111"

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": body["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    assert refresh_response.json()["access_token"]
    assert refresh_response.json()["refresh_token"] != body["refresh_token"]

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"refresh_token": refresh_response.json()["refresh_token"]},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"success": True, "message": "Logged out."}

    with next(app.dependency_overrides[get_db]()) as db:
        actions = set(db.scalars(select(AuditLog.action)))
        assert "user_registered" in actions
        assert {"otp_requested", "user_logged_in", "token_refreshed", "user_logged_out"}.isdisjoint(actions)


def test_staff_user_can_update_own_full_name(client: TestClient) -> None:
    with next(app.dependency_overrides[get_db]()) as db:
        user = User(phone="+998901111112", role="operator", status="active", is_phone_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(str(user.id))

    response = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "  Ali Valiyev  "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["full_name"] == "Ali Valiyev"
    with next(app.dependency_overrides[get_db]()) as db:
        updated = db.scalar(select(User).where(User.phone == "+998901111112"))
        assert updated.full_name == "Ali Valiyev"


def test_non_staff_cannot_update_full_name_through_auth_me(client: TestClient) -> None:
    client.post("/api/v1/auth/request-otp", json={"phone": "+998901111113", "role": "client"})
    token_response = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+998901111113", "role": "client", "otp": "12345"},
    )

    response = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_response.json()['access_token']}"},
        json={"full_name": "Client Name"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_driver_login_flow_creates_driver_profile(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/request-otp",
        json={"phone": "+998902222222", "role": "driver"},
    )

    token_response = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+998902222222", "role": "driver", "otp": "12345"},
    )

    assert token_response.status_code == 200
    assert token_response.json()["user"]["role"] == "driver"

    with next(app.dependency_overrides[get_db]()) as db:
        user = db.scalar(select(User).where(User.phone == "+998902222222"))
        assert user is not None
        profile = db.scalar(select(DriverProfile).where(DriverProfile.user_id == user.id))
        assert profile is not None
        assert profile.verification_status == "new"
        assert profile.is_available is False
        assert profile.rating_avg == 0
        assert profile.total_orders == 0
        assert profile.completed_orders == 0
        assert profile.cancelled_orders == 0
        assert profile.dispute_count == 0


def test_existing_driver_missing_profile_is_repaired_on_verify(client: TestClient) -> None:
    with next(app.dependency_overrides[get_db]()) as db:
        user = User(phone="+998902333333", role="driver", status="active", is_phone_verified=True)
        db.add(user)
        db.commit()

    client.post("/api/v1/auth/request-otp", json={"phone": "+998902333333", "role": "driver"})
    response = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+998902333333", "role": "driver", "otp": "12345"},
    )

    assert response.status_code == 200
    with next(app.dependency_overrides[get_db]()) as db:
        user = db.scalar(select(User).where(User.phone == "+998902333333"))
        profiles = list(db.scalars(select(DriverProfile).where(DriverProfile.user_id == user.id)))
        assert len(profiles) == 1


def test_client_login_flow_creates_client_profile(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/request-otp",
        json={"phone": "+998903333333", "role": "client"},
    )
    client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+998903333333", "role": "client", "otp": "12345"},
    )

    with next(app.dependency_overrides[get_db]()) as db:
        user = db.scalar(select(User).where(User.phone == "+998903333333"))
        assert user is not None
        profile = db.scalar(select(ClientProfile).where(ClientProfile.user_id == user.id))
        assert profile is not None


@pytest.mark.parametrize("role", ["operator", "admin", "super_admin"])
def test_admin_roles_cannot_register_publicly(client: TestClient, role: str) -> None:
    """Staff never reach the OTP path at all — they sign in with a password."""
    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone": "+998909999999", "role": role},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"


def test_invalid_otp_is_rejected(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/request-otp",
        json={"phone": "+998904444444", "role": "client"},
    )

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+998904444444", "role": "client", "otp": "11111"},
    )

    assert response.status_code == 400


def test_phone_normalization_and_role_mismatch(client: TestClient) -> None:
    first = client.post("/api/v1/auth/request-otp", json={"phone": "90 555 55 55", "role": "client"})
    assert first.status_code == 200
    assert first.json()["data"]["phone"] == "+998905555555"

    mismatch = client.post("/api/v1/auth/request-otp", json={"phone": "+998905555555", "role": "driver"})
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "ROLE_MISMATCH"


def test_invalid_phone_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/request-otp", json={"phone": "+77123456789", "role": "client"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PHONE"


def test_otp_cooldown_send_limit_expiry_used_and_attempts(client: TestClient) -> None:
    phone = "+998906666666"
    first = client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": "client"})
    assert first.status_code == 200
    assert len(first.json()["data"]["dev_otp"]) == 5

    cooldown = client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": "client"})
    assert cooldown.status_code == 400
    assert cooldown.json()["error"]["code"] == "OTP_RESEND_TOO_SOON"

    with next(app.dependency_overrides[get_db]()) as db:
        otp = db.scalar(select(OtpCode).where(OtpCode.phone == phone))
        otp.created_at = otp.created_at.replace(year=2020)
        otp.expires_at = otp.expires_at.replace(year=2020)
        db.commit()

    expired = client.post("/api/v1/auth/verify-otp", json={"phone": phone, "role": "client", "otp": "11111"})
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "OTP_EXPIRED"

    for idx in range(5):
        phone_for_limit = f"+9989077777{idx:02d}"
        client.post("/api/v1/auth/request-otp", json={"phone": phone_for_limit, "role": "client"})
        with next(app.dependency_overrides[get_db]()) as db:
            otp = db.scalar(select(OtpCode).where(OtpCode.phone == phone_for_limit))
            otp.created_at = otp.created_at.replace(year=2020 + idx)
            db.commit()

    limited_phone = "+998908888888"
    for idx in range(5):
        response = client.post("/api/v1/auth/request-otp", json={"phone": limited_phone, "role": "client"})
        assert response.status_code == 200
        with next(app.dependency_overrides[get_db]()) as db:
            otp = db.scalar(select(OtpCode).where(OtpCode.phone == limited_phone).order_by(OtpCode.created_at.desc()))
            otp.created_at = otp.created_at - timedelta(minutes=2)
            db.commit()
    limit_response = client.post("/api/v1/auth/request-otp", json={"phone": limited_phone, "role": "client"})
    assert limit_response.status_code == 429
    assert limit_response.json()["error"]["code"] == "OTP_SEND_LIMIT_EXCEEDED"


def test_used_otp_and_too_many_attempts_are_rejected(client: TestClient) -> None:
    phone = "+998909111111"
    client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": "client"})
    ok = client.post("/api/v1/auth/verify-otp", json={"phone": phone, "role": "client", "otp": "12345"})
    reused = client.post("/api/v1/auth/verify-otp", json={"phone": phone, "role": "client", "otp": "12345"})
    assert ok.status_code == 200
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "OTP_USED"

    phone_attempts = "+998909222222"
    client.post("/api/v1/auth/request-otp", json={"phone": phone_attempts, "role": "client"})
    for _ in range(5):
        assert client.post(
            "/api/v1/auth/verify-otp",
            json={"phone": phone_attempts, "role": "client", "otp": "99999"},
        ).status_code == 400
    too_many = client.post("/api/v1/auth/verify-otp", json={"phone": phone_attempts, "role": "client", "otp": "99999"})
    assert too_many.status_code == 400
    assert too_many.json()["error"]["code"] == "OTP_TOO_MANY_ATTEMPTS"


def test_existing_staff_can_login_but_blocked_inactive_deleted_cannot(client: TestClient) -> None:
    with next(app.dependency_overrides[get_db]()) as db:
        users = [
            User(phone="+998901000001", role="admin", status="active", is_phone_verified=True),
            User(phone="+998901000002", role="operator", status="active", is_phone_verified=True),
            User(phone="+998901000003", role="super_admin", status="active", is_phone_verified=True),
            User(phone="+998901000004", role="client", status="blocked", is_phone_verified=True),
            User(phone="+998901000005", role="client", status="inactive", is_phone_verified=True),
            User(phone="+998901000006", role="client", status="deleted", is_phone_verified=True),
        ]
        db.add_all(users)
        db.commit()

    for phone, role in [
        ("+998901000001", "admin"),
        ("+998901000002", "operator"),
        ("+998901000003", "super_admin"),
    ]:
        assert client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": role}).status_code == 200
        assert client.post("/api/v1/auth/verify-otp", json={"phone": phone, "role": role, "otp": "12345"}).status_code == 200

    for phone in ["+998901000004", "+998901000005", "+998901000006"]:
        response = client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": "client"})
        assert response.status_code == 403


def test_token_types_refresh_rotation_and_logout(client: TestClient) -> None:
    client.post("/api/v1/auth/request-otp", json={"phone": "+998902000001", "role": "client"})
    login = client.post("/api/v1/auth/verify-otp", json={"phone": "+998902000001", "role": "client", "otp": "12345"}).json()
    access_payload = verify_token(login["access_token"])
    refresh_payload = verify_token(login["refresh_token"])
    assert access_payload["type"] == "access"
    assert access_payload["phone"] == "+998902000001"
    assert access_payload["role"] == "client"
    assert refresh_payload["type"] == "refresh"

    me_with_refresh = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login['refresh_token']}"})
    assert me_with_refresh.status_code == 401

    refresh_with_access = client.post("/api/v1/auth/refresh", json={"refresh_token": login["access_token"]})
    assert refresh_with_access.status_code == 401

    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refresh.status_code == 200
    rotated = refresh.json()
    assert rotated["refresh_token"] != login["refresh_token"]

    old_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert old_refresh.status_code == 401
    assert old_refresh.json()["error"]["code"] == "REFRESH_TOKEN_REVOKED"

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert logout.status_code == 200
    with next(app.dependency_overrides[get_db]()) as db:
        session = db.scalar(select(RefreshSession).where(RefreshSession.jti == verify_token(rotated["refresh_token"])["jti"]))
        assert session.is_revoked is True


def test_super_admin_can_create_admin_and_operator_users(client: TestClient) -> None:
    with next(app.dependency_overrides[get_db]()) as db:
        super_admin = User(phone="+998903000001", role="super_admin", status="active", is_phone_verified=True)
        admin = User(phone="+998903000002", role="admin", status="active", is_phone_verified=True)
        operator = User(phone="+998903000003", role="operator", status="active", is_phone_verified=True)
        db.add_all([super_admin, admin, operator])
        db.commit()
        super_token = create_access_token(str(super_admin.id))
        admin_token = create_access_token(str(admin.id))
        operator_token = create_access_token(str(operator.id))

    create_admin = client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"phone": "90-300-00-04", "role": "admin", "full_name": "Admin User"},
    )
    create_operator = client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"phone": "+998903000005", "role": "operator", "full_name": "Operator User"},
    )
    create_super = client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={"phone": "+998903000006", "role": "super_admin"},
    )
    admin_forbidden = client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"phone": "+998903000007", "role": "admin"},
    )
    operator_forbidden = client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {operator_token}"},
        json={"phone": "+998903000008", "role": "operator"},
    )

    assert create_admin.status_code == 200
    assert create_admin.json()["phone"] == "+998903000004"
    assert create_operator.status_code == 200
    assert create_super.status_code == 400
    assert admin_forbidden.status_code == 403
    assert operator_forbidden.status_code == 403

    # Newly created staff sign in with a username and password, so the OTP path
    # stays closed to them. Their credentials are set via set_staff_password.py.
    for phone, staff_role in (("+998903000004", "admin"), ("+998903000005", "operator")):
        refused = client.post("/api/v1/auth/request-otp", json={"phone": phone, "role": staff_role})
        assert refused.status_code == 400
        assert refused.json()["error"]["code"] == "PASSWORD_LOGIN_REQUIRED"
