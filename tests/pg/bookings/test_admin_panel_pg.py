"""Admin panel backend additions on real PostgreSQL 16 (ADMIN-BACKEND-CONTRACT; ADR-0021, Q17, Q69).

* ``finalize_fee`` asks for an MFA step-up like the other money commands (enforced mode refuses, audit-only records).
* ``GET /admin/ops/queues/summary`` counts and ``OpsQueueItemDTO.service_type``.
* staff lookups: bookings by code fragment, users, trips, wallets - each PII read leaves its audit row.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.core.config import settings
from app.db.session import get_db
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.identity import mfa
from app.modules.operations import service as ops_service
from tests.pg.bookings.conftest import (
    BW,
    accept,
    act,
    add_user,
    auth,
    codes_for,
    domain_error,
    operator,
    request_with_driver_proposal,
    run_trip_action,
    scalar,
)

pytestmark = pytest.mark.pg


def completed_held_booking(bw: BW, *, plate: str = "01B500AA") -> Booking:
    """A passenger booking completed without a dispute probe: commission ``held`` in the finance queue (Q74)."""
    _, trip_id, _, ref = request_with_driver_proposal(bw, plate=plate)
    booking = accept(bw, ref, bw.w.client_id)
    run_trip_action(bw, trip_id, bw.w.driver_id, "start_boarding", now=bw.base - timedelta(minutes=30))
    act(bw, booking.id, bw.w.driver_id, "board", now=bw.base + timedelta(minutes=5))
    act(bw, booking.id, bw.w.driver_id, "drop_off", now=bw.base + timedelta(hours=3))
    done = act(bw, booking.id, bw.w.client_id, "complete", now=bw.base + timedelta(hours=3, minutes=10))
    assert (done.commission_status, done.finance_review_reason) == ("held", "dispute_module_unavailable")
    return done


# --- finalize_fee step-up (ADR-0021) ----------------------------------------------------------------------------------


def test_finalize_fee_is_refused_without_step_up_when_enforcement_is_on(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    booking = completed_held_booking(bw)
    with bw.db.session() as s:
        add_user(s, "+998900000409", "super_admin", full_name="Second Super")  # two super_admins: enforcement applies
        s.commit()
    monkeypatch.setattr(settings, "staff_mfa_mode", mfa.ENFORCE_PRIVILEGED)

    refused = domain_error(lambda: operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture"))
    assert refused.code is ErrorCode.FORBIDDEN
    assert refused.details["reason"] == "step_up_required"
    assert refused.details["capability"] == "finance.fee_finalize"
    assert scalar(bw.db, "SELECT commission_status FROM bookings WHERE id = :b", b=booking.id) == "held"  # no money moved
    assert scalar(bw.db, "SELECT count(*) FROM ledger_transactions WHERE reference_kind = 'commission_capture'") == 0


def test_finalize_fee_in_audit_only_mode_records_the_missing_step_up_and_captures(bw: BW) -> None:
    booking = completed_held_booking(bw, plate="01B501AA")
    assert settings.staff_mfa_mode == mfa.AUDIT_ONLY
    finalized = operator(bw, booking.id, bw.finance_id, "finalize_fee", fee_mode="capture")
    assert finalized.commission_status == "captured"
    recorded = scalar(
        bw.db,
        "SELECT count(*) FROM staff_mfa_events WHERE user_id = :u AND event_type = 'verify_failed' "
        "AND detail->>'capability' = 'finance.fee_finalize'",
        u=bw.finance_id,
    )
    assert recorded == 1


def test_non_money_operator_commands_never_ask_for_a_step_up(bw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    with bw.db.session() as s:
        add_user(s, "+998900000410", "super_admin", full_name="Second Super")
        s.commit()
    monkeypatch.setattr(settings, "staff_mfa_mode", mfa.ENFORCE_PRIVILEGED)
    _, trip_id, _, ref = request_with_driver_proposal(bw, plate="01B502AA")
    booking = accept(bw, ref, bw.w.client_id)
    # a plain operator command (no money capability) is not touched by MFA, even under enforcement
    error = domain_error(lambda: operator(bw, booking.id, bw.operator_id, "confirm_no_show"))
    assert error.code is ErrorCode.INVALID_STATE_TRANSITION  # the domain answer, not a step-up refusal


# --- ops queue summary + service_type ---------------------------------------------------------------------------------


def test_queue_summary_counts_every_queue_and_items_carry_the_service(bw: BW) -> None:
    booking = completed_held_booking(bw, plate="01B503AA")
    with bw.db.session() as s:
        counts = {c.queue: c for c in ops_service.ops_queue_summary(s, actor_user_id=bw.finance_id)}
        items = ops_service.ops_queue(s, actor_user_id=bw.finance_id, queue="finance_review")
    assert set(counts) == {q.value for q in ops_service.OpsQueue}
    assert counts["finance_review"].count == 1 and counts["finance_review"].capped is False
    assert counts["finance_review"].cap == ops_service.OPS_QUEUE_SUMMARY_CAP
    assert [item.service_type for item in items] == ["passenger"]
    with bw.db.session() as s:
        small = {c.queue: c for c in ops_service.ops_queue_summary(s, actor_user_id=bw.operator_id, cap=0)}
    assert small["finance_review"].capped is True and small["finance_review"].count == 0  # "0+" means "at least one"
    with bw.db.session() as s:
        session_booking = s.get(Booking, booking.id)
        assert session_booking.service_type == "passenger"


def test_queue_summary_needs_ops_view(bw: BW) -> None:
    with bw.db.session() as s:
        error = domain_error(lambda: ops_service.ops_queue_summary(s, actor_user_id=bw.w.client_id))
    assert error.code in (ErrorCode.FORBIDDEN, ErrorCode.CAPABILITY_REQUIRED)


# --- HTTP: lookups --------------------------------------------------------------------------------------------------


@pytest.fixture
def admin_client(bw: BW) -> Iterator[TestClient]:
    from sqlalchemy.exc import DBAPIError

    from app.api.v2.web import db_error_handler
    from app.modules.bookings.api import router as bookings_router
    from app.modules.identity.api import router as identity_router
    from app.modules.identity.web import domain_error_handler
    from app.modules.operations.api import router as operations_router
    from app.modules.trips.api import router as trips_router
    from app.modules.wallet.api import router as wallet_router

    app = FastAPI()
    for router in (identity_router, trips_router, bookings_router, operations_router, wallet_router):
        app.include_router(router, prefix="/api/v2")
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(DBAPIError, db_error_handler)

    async def server_error(request, exc):  # noqa: ANN001, ANN202
        return JSONResponse(status_code=500, content={"success": False, "error": {"code": "SERVER_ERROR", "message": str(exc)}})

    app.add_exception_handler(Exception, server_error)

    def override_db() -> Iterator[Session]:
        session = bw.db.session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_queue_summary_endpoint_is_not_shadowed_by_the_queue_route(bw: BW, admin_client: TestClient) -> None:
    completed_held_booking(bw, plate="01B504AA")
    response = admin_client.get("/api/v2/admin/ops/queues/summary", headers=auth(bw.finance_id, "finance"))
    assert response.status_code == 200, response.text
    rows = {row["queue"]: row for row in response.json()["data"]}
    assert rows["finance_review"] == {"queue": "finance_review", "count": 1, "capped": False, "cap": 200}
    listed = admin_client.get("/api/v2/admin/ops/queues/finance_review", headers=auth(bw.finance_id, "finance"))
    assert listed.json()["data"][0]["service_type"] == "passenger"


def test_booking_search_by_code_fragment_is_staff_only_and_audited(bw: BW, admin_client: TestClient) -> None:
    booking = completed_held_booking(bw, plate="01B505AA")
    public_id = bookings_service.booking_public_id(booking)
    for q in (public_id, public_id[:8], public_id[4:10].upper()):
        found = admin_client.get("/api/v2/admin/bookings/search", params={"q": q}, headers=auth(bw.finance_id, "finance"))
        assert found.status_code == 200, found.text
        assert [row["id"] for row in found.json()["data"]] == [public_id]
        assert found.json()["data"][0]["viewer_side"] == "staff"
    audits = scalar(bw.db, "SELECT count(*) FROM audit_logs WHERE action = 'booking_contacts_viewed' "
                           "AND details->>'surface' = 'B12:search'")
    assert audits == 3  # the staff view shows phones once the service started
    bad = admin_client.get("/api/v2/admin/bookings/search", params={"q": "trp_abcd"}, headers=auth(bw.operator_id, "operator"))
    assert bad.status_code == 400
    client_side = admin_client.get("/api/v2/admin/bookings/search", params={"q": public_id[:8]},
                                   headers=auth(bw.w.client_id, "client"))
    assert client_side.status_code == 403


def test_user_search_returns_ids_and_writes_a_value_free_audit_row(bw: BW, admin_client: TestClient) -> None:
    response = admin_client.get("/api/v2/admin/users/search", params={"q": "Farida"}, headers=auth(bw.operator_id, "operator"))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [row["role"] for row in data] == ["finance"] and data[0]["id"].startswith("usr_")
    details = scalar(bw.db, "SELECT details::text FROM audit_logs WHERE action = 'staff_user_search_viewed'")
    assert "Farida" not in details and data[0]["id"] in details
    by_phone = admin_client.get("/api/v2/admin/users/search", params={"q": "900000402"}, headers=auth(bw.operator_id, "operator"))
    assert [row["id"] for row in by_phone.json()["data"]] == [data[0]["id"]]
    by_id = admin_client.get("/api/v2/admin/users/search", params={"q": data[0]["id"], "role": "finance"},
                             headers=auth(bw.finance_id, "finance"))
    assert len(by_id.json()["data"]) == 1
    denied = admin_client.get("/api/v2/admin/users/search", params={"q": "Farida"}, headers=auth(bw.w.client_id, "client"))
    assert denied.status_code == 403


def test_trip_search_by_code_and_by_driver(bw: BW, admin_client: TestClient) -> None:
    booking = completed_held_booking(bw, plate="01B506AA")
    with bw.db.session() as s:
        from app.modules.trips import service as trips_service

        trip = trips_service.get_trip(s, s.get(Booking, booking.id).trip_id)
        trip_id = trips_service.trip_public_id(trip)
        from app.modules.identity import service as identity_service

        driver_public = identity_service.user_public_id(s, trip.driver_user_id)
    by_code = admin_client.get("/api/v2/admin/trips/search", params={"q": trip_id[:9]}, headers=auth(bw.operator_id, "operator"))
    assert by_code.status_code == 200, by_code.text
    assert [row["id"] for row in by_code.json()["data"]] == [trip_id]
    row = by_code.json()["data"][0]
    assert row["driver_id"] == driver_public and "phone" not in row
    by_driver = admin_client.get("/api/v2/admin/trips/search", params={"q": driver_public}, headers=auth(bw.operator_id, "operator"))
    assert trip_id in [r["id"] for r in by_driver.json()["data"]]


def test_wallet_lookup_needs_finance_reports_and_is_audited(bw: BW, admin_client: TestClient) -> None:
    found = admin_client.get("/api/v2/admin/wallets", params={"q": "+998900000301"}, headers=auth(bw.finance_id, "finance"))
    assert found.status_code == 200, found.text
    data = found.json()["data"]
    assert len(data) == 1 and data[0]["id"].startswith("wal_") and data[0]["driver_phone"] == "+998900000301"
    assert data[0]["available_minor"] == data[0]["posted_balance_minor"] - data[0]["held_minor"]
    audit = scalar(bw.db, "SELECT details::text FROM audit_logs WHERE action = 'wallet_lookup_viewed'")
    assert data[0]["id"] in audit and "+998900000301" not in audit
    by_wallet = admin_client.get("/api/v2/admin/wallets", params={"q": data[0]["id"]}, headers=auth(bw.finance_id, "finance"))
    assert [row["id"] for row in by_wallet.json()["data"]] == [data[0]["id"]]
    denied = admin_client.get("/api/v2/admin/wallets", params={"q": "+998900000301"}, headers=auth(bw.operator_id, "operator"))
    assert denied.status_code == 403


def test_topup_admin_dto_names_the_driver(bw: BW, admin_client: TestClient) -> None:
    response = admin_client.get("/api/v2/admin/topups", headers=auth(bw.finance_id, "finance"))
    assert response.status_code == 200, response.text
    first = response.json()["data"][0]
    assert first["driver"]["id"].startswith("usr_")
    assert "display_name" in first["driver"]
    assert first["first_approver"]["display_name"] == "Super"  # "Super Admin" -> first name only
