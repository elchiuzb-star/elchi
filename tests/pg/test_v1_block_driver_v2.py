"""v1 admin block_driver vs v2 business (H1, Q15, D16, AC41).

* A driver with active v2 trips/bookings: admin block applies the v2 eligibility block (identity
  service) and v1 new-business block (verification_status, routes); ``users.status`` stays active,
  sessions stay live, the existing booking still progresses; a new accept is refused.
* Emergency full block (account suspended, obligations stop) is super_admin only.
* A driver without v2 business: unchanged v1 full block.
* block_driver vs accept serialize on the driver's users row (AC41).

Builds on A4's fixtures and helpers (tests/pg/bookings/conftest.py, not edited).
"""

from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.models import User
from app.modules.trips import service as trips_service
from app.schemas.admin_driver import AdminDriverBlock
from app.services import admin_driver_service
from app.services.admin_driver_service import block_driver
from tests.pg.bookings.conftest import (  # noqa: F401  (world, lock_clock are fixtures)
    BW,
    FUNDED_MINOR,
    STAGGER_S,
    USERS_LOCK,
    accept,
    act,
    add_user,
    codes_for,
    fund,
    domain_error,
    hold_inside,
    listing_version,
    lock_clock,
    passenger_request_body,
    propose,
    publish_listing,
    request_with_driver_proposal,
    run_trip_action,
    scalar,
    world,
)
from tests.pg.harness import run_concurrently

pytestmark = pytest.mark.pg


@pytest.fixture
def bw(world) -> BW:  # noqa: ANN001, F811
    """Same world as A4's ``bw``, but enables the v2 flags with the Q72 flag-change marker (0057 guard)."""
    from sqlalchemy import text

    from app.modules.geo import service as geo_service

    with world.db.session() as s:
        super_id = add_user(s, "+998900000400", "super_admin", full_name="Super Admin")
        operator_id = add_user(s, "+998900000401", "operator", full_name="Olim Operator")
        finance_id = add_user(s, "+998900000402", "finance", full_name="Farida Finance")
        s.commit()
    with world.db.engine.begin() as conn:
        geo_service.mark_flag_change_source(conn)
        for key in ("passenger_enabled", "parcel_enabled", "driver_listing_enabled"):
            conn.execute(
                text(
                    "INSERT INTO feature_flag_values (public_id, flag_key, scope_type, scope_ref, enabled, reason, updated_by) "
                    "VALUES (gen_random_uuid(), :k, 'country', 'UZ', true, 'H1 test', :u)"
                ),
                {"k": key, "u": world.admin_id},
            )
    built = BW(world, super_id, operator_id, finance_id)
    fund(built, world.driver_id, FUNDED_MINOR, super_id)
    fund(built, world.driver2_id, FUNDED_MINOR, super_id)
    return built


def profile_id(bw: BW, user_id: int) -> int:
    return int(scalar(bw.db, "SELECT id FROM driver_profiles WHERE user_id = :u", u=user_id))


def do_block(bw: BW, actor_id: int, driver_user_id: int, *, emergency: bool = False):  # noqa: ANN201
    pid = profile_id(bw, driver_user_id)
    with bw.db.session() as s:
        return block_driver(s, s.get(User, actor_id), pid, AdminDriverBlock(reason="fraud", emergency=emergency))


def user_status(bw: BW, user_id: int) -> str:
    return scalar(bw.db, "SELECT status FROM users WHERE id = :u", u=user_id)


def verification(bw: BW, user_id: int) -> str:
    return scalar(bw.db, "SELECT verification_status FROM driver_profiles WHERE user_id = :u", u=user_id)


def active_blocks(bw: BW, user_id: int) -> int:
    return int(scalar(bw.db, "SELECT count(*) FROM driver_eligibility_blocks WHERE driver_user_id = :u AND lifted_at IS NULL", u=user_id))


def error_of(result) -> tuple[int, dict]:  # noqa: ANN001
    assert isinstance(result, JSONResponse), result
    body = json.loads(result.body)
    assert set(body) == {"success", "error"} and body["success"] is False
    return result.status_code, body["error"]


def add_refresh_session(bw: BW, user_id: int) -> None:
    from app.models import RefreshSession
    from app.contracts.timeutil import utc_now

    with bw.db.session() as s:
        s.add(RefreshSession(user_id=user_id, jti=f"q15-{user_id}", token_hash="hash", expires_at=utc_now() + timedelta(days=1)))
        s.commit()


def live_sessions(bw: BW, user_id: int) -> int:
    return int(scalar(bw.db, "SELECT count(*) FROM refresh_sessions WHERE user_id = :u AND is_revoked = false", u=user_id))


def test_admin_block_with_active_v2_booking_blocks_only_new_business(bw: BW) -> None:
    _listing, trip_id, trip_public, ref = request_with_driver_proposal(bw, plate="01Q100AA")
    booking = accept(bw, ref, bw.w.client_id)
    # Prepared before the block on the same trip (2 of 4 seats left); accepting it afterwards is new business.
    listing2 = publish_listing(bw, bw.w.client2_id, passenger_request_body(bw, seats=2))
    ref2 = propose(bw, listing2, bw.w.driver_id, trip_public_id=trip_public, quantity=2)
    add_refresh_session(bw, bw.w.driver_id)

    result = do_block(bw, bw.w.admin_id, bw.w.driver_id)

    assert isinstance(result, dict), result
    assert result["block_type"] == "new_business_only" and result["v2_eligibility_blocked"] is True
    assert result["user_status"] == "active" and result["verification_status"] == "blocked"
    assert result["v2_active_trip_count"] == 1 and result["v2_active_booking_count"] == 1
    assert result["revoked_refresh_sessions_count"] == 0
    assert user_status(bw, bw.w.driver_id) == "active"
    assert verification(bw, bw.w.driver_id) == "blocked"
    assert active_blocks(bw, bw.w.driver_id) == 1
    assert live_sessions(bw, bw.w.driver_id) == 1

    # New business refused (D16, Q21).
    err = domain_error(lambda: accept(bw, ref2, bw.w.client2_id))
    assert err.code is ErrorCode.DRIVER_NOT_ELIGIBLE

    # The existing booking still progresses: trip operation and proofs continue (D16).
    assert run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30)) == "boarding"
    code = codes_for(bw, booking.id, bw.w.client_id)["boarding_code"]
    assert act(bw, booking.id, bw.w.driver_id, "board", code=code, now=bw.base + timedelta(minutes=5)).service_status == "onboard"
    act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    final = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    assert final.service_status == "completed"


def test_emergency_full_block_is_super_admin_only(bw: BW) -> None:
    _listing, trip_id, _trip, ref = request_with_driver_proposal(bw, plate="01Q200AA")
    accept(bw, ref, bw.w.client_id)
    add_refresh_session(bw, bw.w.driver_id)

    status_code, error = error_of(do_block(bw, bw.w.admin_id, bw.w.driver_id, emergency=True))
    assert status_code == 403 and error["code"] == "FORBIDDEN"
    assert user_status(bw, bw.w.driver_id) == "active" and verification(bw, bw.w.driver_id) == "approved"
    assert active_blocks(bw, bw.w.driver_id) == 0

    # Admin new-business block, then a repeated admin block is refused as before.
    assert do_block(bw, bw.w.admin_id, bw.w.driver_id)["block_type"] == "new_business_only"
    status_code, error = error_of(do_block(bw, bw.w.admin_id, bw.w.driver_id))
    assert status_code == 400 and error["code"] == "DRIVER_ALREADY_BLOCKED"

    # super_admin escalates to a full block: account suspended, sessions revoked, obligations stop.
    result = do_block(bw, bw.super_id, bw.w.driver_id, emergency=True)
    assert isinstance(result, dict), result
    assert result["block_type"] == "full" and result["user_status"] == "blocked"
    assert result["revoked_refresh_sessions_count"] == 1
    assert user_status(bw, bw.w.driver_id) == "blocked"
    assert active_blocks(bw, bw.w.driver_id) == 1  # the existing eligibility block is kept, not duplicated
    assert live_sessions(bw, bw.w.driver_id) == 0
    with pytest.raises(DomainError):
        run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))

    status_code, error = error_of(do_block(bw, bw.super_id, bw.w.driver_id, emergency=True))
    assert status_code == 400 and error["code"] == "DRIVER_ALREADY_BLOCKED"


def staff_with_super_admin_user_role(bw: BW, phone: str, role_status: str) -> int:
    """Legacy users.role='admin'; super_admin only through a user_roles row (BR L2)."""
    from sqlalchemy import text

    with bw.db.session() as s:
        user_id = add_user(s, phone, "admin", full_name="Role Staff")
        s.execute(
            text(
                "INSERT INTO user_roles (user_id, role, status) VALUES (:u, 'super_admin', :st) "
                "ON CONFLICT (user_id, role) DO UPDATE SET status = EXCLUDED.status"
            ),
            {"u": user_id, "st": role_status},
        )
        s.commit()
    return user_id


def test_emergency_block_allowed_for_super_admin_granted_via_user_roles(bw: BW) -> None:
    _listing, _trip_id, _trip, ref = request_with_driver_proposal(bw, plate="01Q600AA")
    accept(bw, ref, bw.w.client_id)
    actor_id = staff_with_super_admin_user_role(bw, "+998900000610", "active")

    result = do_block(bw, actor_id, bw.w.driver_id, emergency=True)

    assert isinstance(result, dict), result
    assert result["block_type"] == "full" and user_status(bw, bw.w.driver_id) == "blocked"


def test_emergency_block_refused_for_revoked_super_admin_user_role(bw: BW) -> None:
    _listing, _trip_id, _trip, ref = request_with_driver_proposal(bw, plate="01Q700AA")
    accept(bw, ref, bw.w.client_id)
    actor_id = staff_with_super_admin_user_role(bw, "+998900000611", "revoked")

    status_code, error = error_of(do_block(bw, actor_id, bw.w.driver_id, emergency=True))

    assert status_code == 403 and error == {"code": "FORBIDDEN", "message": "Only super_admin can perform an emergency full block"}
    assert user_status(bw, bw.w.driver_id) == "active" and active_blocks(bw, bw.w.driver_id) == 0


def test_driver_without_v2_business_keeps_v1_full_block(bw: BW) -> None:
    result = do_block(bw, bw.w.admin_id, bw.w.driver2_id)

    assert isinstance(result, dict), result
    assert result["block_type"] == "full" and result["v2_eligibility_blocked"] is False
    assert result["v2_active_trip_count"] == 0 and result["v2_active_booking_count"] == 0
    assert user_status(bw, bw.w.driver2_id) == "blocked"
    assert verification(bw, bw.w.driver2_id) == "blocked"
    assert active_blocks(bw, bw.w.driver2_id) == 0


def test_block_driver_vs_accept_serializes_on_driver_users_row(bw: BW, monkeypatch: pytest.MonkeyPatch, lock_clock) -> None:  # noqa: F811
    hold_inside(monkeypatch, admin_driver_service, "_driver_v2_obligations")  # block: inside users/profile locks
    hold_inside(monkeypatch, trips_service, "lock_trip")  # accept: right after its users lock
    clock = lock_clock(USERS_LOCK)
    seen: set[str] = set()
    rounds = [
        (bw.w.driver_id, bw.w.client_id, "01Q400AA", True),
        (bw.w.driver2_id, bw.w.client2_id, "01Q500AA", False),
    ]
    for driver_id, client_id, plate, accept_first in rounds:
        clock.reset()
        _listing, _trip_id, _trip, ref = request_with_driver_proposal(bw, plate=plate, client_id=client_id, driver_id=driver_id)
        expected = listing_version(bw, ref.listing_id)
        pid = profile_id(bw, driver_id)
        early = 1 if accept_first else 0

        def work(index: int, session: Session):  # noqa: ANN202
            clock.bind(index)
            if index != early:
                time.sleep(STAGGER_S)
            if index == 0:
                return block_driver(session, session.get(User, bw.w.admin_id), pid, AdminDriverBlock(reason="fraud"))  # noqa: B023
            try:
                return accept(bw, ref, client_id, session=session, expected_listing_version=expected)  # noqa: B023
            except DomainError as exc:
                return exc

        report = run_concurrently(2, work, engine=bw.db.engine)

        assert report.failures == [], [f"worker {r.index}: {r.error!r}" for r in report.failures]
        clock.assert_waited(early=early, late=1 - early)
        blocked, accepted = report.results[0].value, report.results[1].value
        assert isinstance(blocked, dict), blocked
        # The driver has a planned v2 trip either way, so the block is new-business only.
        assert blocked["block_type"] == "new_business_only"
        assert user_status(bw, driver_id) == "active" and active_blocks(bw, driver_id) == 1
        bookings = int(scalar(bw.db, "SELECT count(*) FROM bookings WHERE driver_user_id = :d", d=driver_id))
        if isinstance(accepted, DomainError):
            seen.add("block_first")
            assert accepted.code is ErrorCode.DRIVER_NOT_ELIGIBLE
            assert bookings == 0 and blocked["v2_active_booking_count"] == 0
        else:
            seen.add("accept_first")
            assert bookings == 1 and blocked["v2_active_booking_count"] == 1
    assert seen == {"accept_first", "block_first"}
