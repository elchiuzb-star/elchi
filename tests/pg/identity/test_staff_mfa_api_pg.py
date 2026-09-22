"""Wave 9: staff MFA over HTTP on PostgreSQL (I6-I11, ADR-0021).

The service rules were proven in ``test_staff_mfa_pg.py``; what is proven here is that the routes do not undo
them, and the two failures that only appear once there is a screen in front of the service:

* a staff member who starts a *second* enrollment (new phone) must keep working with the old factor - reading
  the newest row instead would have stopped their money commands the moment they opened the screen;
* six digits are guessable, so an account that keeps failing stops answering for a while.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.contracts.errors import DomainError
from app.core.config import settings
from app.core.secret_box import open_sealed
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.identity import mfa
from app.modules.identity.api import router as identity_router
from app.modules.identity.web import domain_error_handler
from tests.pg.identity.a1_world import World, add_user

pytestmark = pytest.mark.pg


@pytest.fixture
def client(world: World) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(identity_router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)

    def override_db() -> Iterator:
        session = world.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


def auth(user_id: int, role: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(user_id), extra_claims={'role': role})}",
        "Idempotency-Key": str(uuid.uuid4()),
    }


def super_admin(world: World, suffix: str) -> int:
    with world.db.session() as session:
        user_id = add_user(session, f"+9989011{suffix}", "super_admin", full_name=f"Super {suffix}")
        session.commit()
        return user_id


def public_id(world: World, user_id: int) -> str:
    with world.db.session() as session:
        from app.modules.identity import service as identity_service

        return identity_service.user_public_id(session, user_id)


def live_code(world: World, user_id: int, *, status: str = "pending", step: int = 0) -> str:
    """Generate the code the staff member's authenticator would show for that factor."""
    with world.db.session() as session:
        row = session.execute(
            text(
                "SELECT secret_cipher, public_id, secret_key_version FROM staff_mfa_factors "
                "WHERE user_id = :u AND status = :s ORDER BY id DESC LIMIT 1"
            ),
            {"u": user_id, "s": status},
        ).one()
    secret = open_sealed(settings.secret_key, mfa.SECRET_PURPOSE, row[0], aad=str(row[1]), key_version=row[2])
    totp = pyotp.TOTP(secret, interval=mfa.TOTP_INTERVAL_SECONDS)
    return totp.at(int(time.time()) + step * mfa.TOTP_INTERVAL_SECONDS)


def ok(response, status: int = 200):  # noqa: ANN001, ANN201
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is True, body
    return body["data"]


def err(response, status: int, code: str) -> dict:  # noqa: ANN001
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is False and body["error"]["code"] == code, body
    return body["error"]


def enroll(client: TestClient, user_id: int, role: str = "super_admin") -> dict:
    return ok(client.post("/api/v2/me/mfa/enroll", headers=auth(user_id, role)), 201)


def test_a_marketplace_account_has_no_mfa_surface(client: TestClient, world: World) -> None:
    """Q3: staff and marketplace accounts are separate; a client must not be able to enroll staff MFA."""
    error = err(client.get("/api/v2/me/mfa", headers=auth(world.client_id, "client")), 403, "FORBIDDEN")
    assert error["details"]["reason"] == "staff_only"
    err(client.post("/api/v2/me/mfa/enroll", headers=auth(world.client_id, "client")), 403, "FORBIDDEN")


def test_enrollment_is_pending_until_a_different_super_admin_activates_it(client: TestClient, world: World) -> None:
    subject = super_admin(world, "0201")
    approver = super_admin(world, "0202")

    enrollment = enroll(client, subject)
    assert enrollment["factor_id"].startswith("mfa_")
    assert len(enrollment["recovery_codes"]) == mfa.RECOVERY_CODE_COUNT
    assert enrollment["activation_required"] is True
    assert enrollment["provisioning_uri"].startswith("otpauth://")

    state = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    assert (state["enrolled"], state["active"], state["pending_activation"]) == (True, False, True)
    assert state["recovery_codes_remaining"] == mfa.RECOVERY_CODE_COUNT
    assert "secret" not in state

    # The enroller cannot wave their own factor through - the whole point of the second pair of eyes.
    self_activation = client.post(
        f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/activate",
        json={"code": live_code(world, subject)},
        headers=auth(subject, "super_admin"),
    )
    assert err(self_activation, 403, "FORBIDDEN")["details"]["reason"] == "self_activation"

    activated = ok(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/activate",
            json={"code": live_code(world, subject)},
            headers=auth(approver, "super_admin"),
        )
    )
    assert activated["status"] == "active" and activated["activated_at"] is not None
    after = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    assert (after["active"], after["pending_activation"]) == (True, False)


def test_step_up_is_fresh_for_five_minutes_and_a_wrong_code_is_refused(client: TestClient, world: World) -> None:
    subject = super_admin(world, "0211")
    approver = super_admin(world, "0212")
    enroll(client, subject)
    ok(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/activate",
            json={"code": live_code(world, subject)},
            headers=auth(approver, "super_admin"),
        )
    )

    wrong = client.post("/api/v2/me/mfa/step-up", json={"code": "000000"}, headers=auth(subject, "super_admin"))
    assert err(wrong, 400, "VALIDATION_ERROR")["details"]["reason"] == "invalid_code"

    proved = ok(
        client.post(
            "/api/v2/me/mfa/step-up",
            json={"code": live_code(world, subject, status="active")},
            headers=auth(subject, "super_admin"),
        )
    )
    assert proved["expires_at"] > proved["stepped_up_at"]
    state = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    assert state["step_up_fresh"] is True and state["step_up_max_age_seconds"] == 300


def test_guessing_stops_the_account_answering(client: TestClient, world: World) -> None:
    subject = super_admin(world, "0221")
    approver = super_admin(world, "0222")
    enroll(client, subject)
    ok(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/activate",
            json={"code": live_code(world, subject)},
            headers=auth(approver, "super_admin"),
        )
    )

    for _ in range(mfa.MAX_FAILED_ATTEMPTS):
        err(
            client.post("/api/v2/me/mfa/step-up", json={"code": "000000"}, headers=auth(subject, "super_admin")),
            400,
            "VALIDATION_ERROR",
        )
    blocked = client.post(
        "/api/v2/me/mfa/step-up",
        json={"code": live_code(world, subject, status="active")},
        headers=auth(subject, "super_admin"),
    )
    details = err(blocked, 429, "RATE_LIMITED")["details"]
    assert details["limit"] == mfa.MAX_FAILED_ATTEMPTS and details["reason"] == "too_many_failed_codes"
    # A correct code is refused too: the limit protects the account, not the caller's patience.
    state = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    assert state["failed_attempts_in_window"] >= mfa.MAX_FAILED_ATTEMPTS


def test_a_second_enrollment_does_not_disarm_the_working_factor(client: TestClient, world: World) -> None:
    """New phone: the old factor keeps working until somebody activates the new one."""
    subject = super_admin(world, "0231")
    approver = super_admin(world, "0232")
    enroll(client, subject)
    ok(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/activate",
            json={"code": live_code(world, subject)},
            headers=auth(approver, "super_admin"),
        )
    )

    enroll(client, subject)  # the new phone
    state = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    assert (state["active"], state["pending_activation"]) == (True, True)

    proved = client.post(
        "/api/v2/me/mfa/step-up",
        json={"code": live_code(world, subject, status="active")},
        headers=auth(subject, "super_admin"),
    )
    assert proved.status_code == 200, proved.text


def test_a_recovery_code_buys_an_enrollment_and_nothing_else(client: TestClient, world: World) -> None:
    subject = super_admin(world, "0241")
    approver = super_admin(world, "0242")
    codes = enroll(client, subject)["recovery_codes"]
    ok(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/activate",
            json={"code": live_code(world, subject)},
            headers=auth(approver, "super_admin"),
        )
    )

    used = ok(client.post("/api/v2/me/mfa/recovery", json={"code": codes[0]}, headers=auth(subject, "super_admin")))
    assert used == {
        "enrollment_allowed": True,
        "recovery_codes_remaining": mfa.RECOVERY_CODE_COUNT - 1,
        "factor_revoked": True,
    }
    state = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    # Q17/Q49: recovery restores access, never authority - there is no active factor and no fresh step-up.
    assert (state["active"], state["step_up_fresh"]) == (False, False)
    err(
        client.post("/api/v2/me/mfa/recovery", json={"code": codes[0]}, headers=auth(subject, "super_admin")),
        400,
        "VALIDATION_ERROR",
    )


def test_reset_needs_a_different_super_admin_and_leaves_nothing_usable(client: TestClient, world: World) -> None:
    subject = super_admin(world, "0251")
    approver = super_admin(world, "0252")
    enroll(client, subject)
    ok(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/activate",
            json={"code": live_code(world, subject)},
            headers=auth(approver, "super_admin"),
        )
    )

    self_reset = client.post(
        f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/reset",
        json={"reason": "lost phone"},
        headers=auth(subject, "super_admin"),
    )
    assert err(self_reset, 403, "FORBIDDEN")["details"]["reason"] == "self_reset"

    operator = add_user_operator(world)
    err(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/reset",
            json={"reason": "lost phone"},
            headers=auth(operator, "operator"),
        ),
        403,
        "CAPABILITY_REQUIRED",
    )

    done = ok(
        client.post(
            f"/api/v2/admin/staff/{public_id(world, subject)}/mfa/reset",
            json={"reason": "lost phone"},
            headers=auth(approver, "super_admin"),
        )
    )
    assert done["factors_revoked"] == 1 and done["recovery_codes_invalidated"] is True
    state = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    assert (state["enrolled"], state["active"], state["recovery_codes_remaining"]) == (False, False, 0)

    with world.db.session() as session:
        actor = session.scalar(
            text(
                "SELECT actor_user_id FROM staff_mfa_events WHERE user_id = :u AND event_type = 'factor_reset'"
            ),
            {"u": subject},
        )
    assert actor == approver


def add_user_operator(world: World) -> int:
    with world.db.session() as session:
        user_id = add_user(session, f"+998902{str(uuid.uuid4().int)[:6]}", "operator", full_name="Operator")
        session.commit()
        return user_id


def test_enrollment_replays_the_same_secret_for_one_idempotency_key(client: TestClient, world: World) -> None:
    subject = super_admin(world, "0261")
    headers = auth(subject, "super_admin")
    first = ok(client.post("/api/v2/me/mfa/enroll", headers=headers), 201)
    second = client.post("/api/v2/me/mfa/enroll", headers=headers)
    assert second.status_code == 201 and second.headers.get("Idempotent-Replayed") == "true"
    assert second.json()["data"] == first


def test_state_reports_why_enforcement_is_still_off(client: TestClient, world: World) -> None:
    subject = super_admin(world, "0271")
    state = ok(client.get("/api/v2/me/mfa", headers=auth(subject, "super_admin")))
    assert state["mode"] == settings.staff_mfa_mode == "audit_only"
    assert state["enforced"] is False
    assert state["active_super_admin_count"] >= 1
