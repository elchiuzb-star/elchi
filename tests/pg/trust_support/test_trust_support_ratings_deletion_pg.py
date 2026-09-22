"""Support/SOS, ratings/reputation and account deletion (§16, §17.2, §17.8, AC36, N4) on PostgreSQL 16."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import EventType, ServiceType
from app.contracts.errors import ErrorCode
from app.contracts.events import EventAudience, payload_for_audience
from app.models import User
from app.modules.bookings import service as bookings_service
from app.modules.trust_support import service as trust_service
from app.services.account_deletion_service import delete_own_account
from tests.pg.bookings.conftest import auth
from tests.pg.trust_support.conftest import (
    BW,
    COMPLETE_AT_OFFSET,
    arrived_passenger,
    boarding_passenger,
    complete,
    domain_error,
    open_dispute,
    rows,
    scalar,
    user_public,
)

pytestmark = pytest.mark.pg


# --- support / SOS --------------------------------------------------------------------------------------------------


def test_sos_ticket_staff_only_event_rate_limit_and_commands(bw: BW, trust_client) -> None:  # noqa: ANN001
    _, booking = boarding_passenger(bw, "01T300AA")
    contacts = trust_client.get("/api/v2/support/contacts", headers=auth(bw.w.client_id, "client"))
    assert contacts.status_code == 200 and contacts.json()["data"] == {"available": False, "phone": None, "hours_text": None}

    body = {"kind": "sos", "booking_id": bookings_service.booking_public_id(booking), "message": "Menga @helper_bot yozing"}
    created = trust_client.post("/api/v2/support/tickets", json=body, headers=auth(bw.w.client_id, "client", "idem-sos-1"))
    assert created.status_code == 201, created.text
    ticket = created.json()["data"]
    assert ticket["status"] == "open" and "@helper_bot" not in ticket["message"]
    events = rows(bw.db, "SELECT event_type, payload FROM outbox_events WHERE event_type LIKE 'support.%'")
    assert [(e.event_type, set(e.payload)) for e in events] == [("support.sos.raised", {"ticket_id", "booking_id", "trip_id"})]
    for audience in (EventAudience.CLIENT, EventAudience.DRIVER):
        assert payload_for_audience(EventType.SUPPORT_SOS_RAISED, events[0].payload, audience) is None

    other = {"kind": "support", "booking_id": bookings_service.booking_public_id(booking)}
    assert trust_client.post("/api/v2/support/tickets", json=other, headers=auth(bw.w.client2_id, "client", "idem-sup-x")).status_code == 404
    # BR M3: SOS is never 429 - repeat presses land on the open ticket (same booking / same booking-less SOS)
    for n in range(4):
        again = trust_client.post("/api/v2/support/tickets", json={**body, "message": None}, headers=auth(bw.w.client_id, "client", f"idem-sos-rep-{n}"))
        assert again.status_code == 201 and again.json()["data"]["id"] == ticket["id"]
    loose = [trust_client.post("/api/v2/support/tickets", json={"kind": "sos"}, headers=auth(bw.w.client_id, "client", f"idem-sos-loose-{n}"))
             for n in range(5)]
    assert all(r.status_code == 201 for r in loose) and len({r.json()["data"]["id"] for r in loose}) == 1
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'support.sos.raised'") == 10
    for n in range(5):
        assert trust_client.post("/api/v2/support/tickets", json={"kind": "support"}, headers=auth(bw.w.client_id, "client", f"idem-sup-{n}")).status_code == 201
    limited = trust_client.post("/api/v2/support/tickets", json={"kind": "support"}, headers=auth(bw.w.client_id, "client", "idem-sup-9"))
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "RATE_LIMITED"

    admin = trust_client.get("/api/v2/admin/support/tickets?kind=sos", headers=auth(bw.operator_id, "operator"))
    assert admin.status_code == 200 and len(admin.json()["data"]) == 2
    assert {t["id"]: t["press_count"] for t in admin.json()["data"]}[ticket["id"]] == 5
    assert "phone" not in json.dumps(admin.json()["data"][0])
    ack = trust_client.post(f"/api/v2/admin/support/tickets/{ticket['id']}/acknowledge", json={"expected_version": 1},
                            headers=auth(bw.operator_id, "operator", "idem-ack-1"))
    assert ack.status_code == 200 and ack.json()["data"]["status"] == "acknowledged"
    no_note = trust_client.post(f"/api/v2/admin/support/tickets/{ticket['id']}/resolve", json={"expected_version": 2},
                                headers=auth(bw.operator_id, "operator", "idem-res-0"))
    assert no_note.status_code == 400
    resolved = trust_client.post(f"/api/v2/admin/support/tickets/{ticket['id']}/resolve", json={"expected_version": 2, "note": "called back"},
                                 headers=auth(bw.operator_id, "operator", "idem-res-1"))
    assert resolved.status_code == 200 and resolved.json()["data"]["status"] == "resolved"
    changed = rows(bw.db, "SELECT aggregate_type, payload FROM outbox_events WHERE event_type = 'support.ticket.status_changed' ORDER BY id")
    assert [c.payload["to_status"] for c in changed] == ["acknowledged", "resolved"] and changed[0].aggregate_type == "user"
    fresh = trust_client.post("/api/v2/support/tickets", json={**body, "message": None}, headers=auth(bw.w.client_id, "client", "idem-sos-after"))
    assert fresh.status_code == 201 and fresh.json()["data"]["id"] != ticket["id"]  # resolved SOS is not reused


# --- ratings / reputation -------------------------------------------------------------------------------------------


def _rate(bw: BW, booking, actor: int, subject_side: str, stars: int, *, now, comment: str | None = None):  # noqa: ANN001, ANN202
    with bw.db.session() as s:
        rating = trust_service.create_rating(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=actor, subject_side=subject_side,
            stars=stars, comment=comment, now=now,
        )
        s.commit()
        return rating


def test_rating_rules_publication_and_reputation(bw: BW, hooks) -> None:  # noqa: ANN001
    with bw.db.session() as s:
        new = trust_service.reputation_summaries(s, [bw.w.driver_id], service_type=ServiceType.PASSENGER)[bw.w.driver_id]
    assert (new.rating_count, new.average_rating, new.label.value) == (0, None, "new_verified")  # no fake 4.5

    _, open_booking = boarding_passenger(bw, "01T400AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    assert domain_error(lambda: _rate(bw, open_booking, bw.w.client2_id, "driver", 5, now=bw.base)).code is ErrorCode.RATING_NOT_ALLOWED

    booking = arrived_passenger(bw, "01T401AA")
    complete(bw, booking)
    done_at = bw.base + COMPLETE_AT_OFFSET
    assert domain_error(lambda: _rate(bw, booking, bw.w.client_id, "client", 5, now=done_at)).code is ErrorCode.RATING_NOT_ALLOWED
    first = _rate(bw, booking, bw.w.client_id, "driver", 5, now=done_at + timedelta(hours=1), comment="Zo'r, 90 123 45 67")
    assert first.published_at is None and "123 45 67" not in (first.comment or "")
    assert domain_error(lambda: _rate(bw, booking, bw.w.client_id, "driver", 4, now=done_at + timedelta(hours=2))).code is ErrorCode.RATING_ALREADY_EXISTS
    with bw.db.session() as s:
        hidden = trust_service.reputation_summaries(s, [bw.w.driver_id], service_type="passenger")[bw.w.driver_id]
    assert hidden.rating_count == 0 and hidden.completed_bookings == 1  # unpublished rating is not counted

    second = _rate(bw, booking, bw.w.driver_id, "client", 4, now=done_at + timedelta(hours=3))
    assert second.published_at is not None
    assert scalar(bw.db, "SELECT count(*) FROM ratings_v2 WHERE published_at IS NULL") == 0
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'rating.published'") == 2
    with bw.db.session() as s:
        driver = trust_service.reputation_summaries(s, [bw.w.driver_id], service_type="passenger")[bw.w.driver_id]
    assert (driver.rating_count, driver.average_rating, driver.label.value, driver.completed_trips) == (1, 5.0, "rated", 1)
    assert domain_error(lambda: _rate(bw, booking, bw.w.driver_id, "client", 3, now=done_at + timedelta(days=8))).code in (
        ErrorCode.RATING_NOT_ALLOWED, ErrorCode.RATING_ALREADY_EXISTS)
    with pytest.raises(DBAPIError) as info:
        with bw.db.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE ratings_v2 SET stars = 1")
    assert info.value.orig.diag.constraint_name == "append_only_violation"


def test_one_sided_rating_published_by_worker_after_window_and_snapshots(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T402AA")
    complete(bw, booking)
    done_at = bw.base + COMPLETE_AT_OFFSET
    _rate(bw, booking, bw.w.client_id, "driver", 3, now=done_at + timedelta(hours=1))
    with bw.db.session() as s:
        assert trust_service.publish_due_ratings(s, now=done_at + timedelta(days=6)) == 0
        assert trust_service.publish_due_ratings(s, now=done_at + timedelta(days=7, minutes=1)) == 1
        s.commit()
    with bw.db.session() as s:
        assert trust_service.publish_due_ratings(s, now=done_at + timedelta(days=9)) == 0
        refreshed = trust_service.refresh_reputation_snapshots(s, now=done_at + timedelta(days=9))
        s.commit()
    assert refreshed >= 1
    snap = rows(bw.db, "SELECT rating_count, rating_sum, completed_bookings FROM reputation_snapshots WHERE user_id = :u "
                       "AND service_type = 'passenger'", u=bw.w.driver_id)[0]
    assert (snap.rating_count, snap.rating_sum, snap.completed_bookings) == (1, 3, 1)
    with bw.db.session() as s:
        assert trust_service.refresh_reputation_snapshots(s, now=done_at + timedelta(days=9)) == 0


def test_one_five_star_is_not_ranked_above_two_hundred_ratings_ac36(bw: BW) -> None:
    with bw.db.engine.begin() as conn:
        for user_id, count, total in ((bw.w.driver_id, 1, 5), (bw.w.driver2_id, 200, 960)):
            conn.execute(text("INSERT INTO reputation_snapshots (user_id, service_type, rating_count, rating_sum, computed_at) "
                              "VALUES (:u, 'passenger', :c, :t, now())"), {"u": user_id, "c": count, "t": total})
    with bw.db.session() as s:
        summaries = trust_service.reputation_summaries(s, [bw.w.driver_id, bw.w.driver2_id, bw.w.client_id], service_type="passenger")
    assert summaries[bw.w.driver_id].average_rating == 5.0
    assert summaries[bw.w.driver_id].adjusted_rating < summaries[bw.w.driver2_id].adjusted_rating
    assert summaries[bw.w.client_id].average_rating is None and summaries[bw.w.client_id].rating_count == 0


# --- account deletion ------------------------------------------------------------------------------------------------


def test_open_dispute_blocks_v1_and_v2_account_deletion(bw: BW, hooks, trust_client) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T500AA")
    assert complete(bw, booking).commission_status == "captured"
    open_dispute(bw, booking.id, bw.w.client_id, "service")

    with bw.db.session() as s:
        result = delete_own_account(s, s.get(User, bw.w.client_id))
    assert isinstance(result, JSONResponse) and result.status_code == 409
    body = json.loads(result.body)
    assert set(body) == {"success", "error"} and body["error"]["code"] == "ACTIVE_DISPUTES_EXIST"
    assert body["error"]["details"] == {"open_disputes": 1, "open_sos_tickets": 0}

    refused = trust_client.request("DELETE", "/api/v2/me", headers=auth(bw.w.client_id, "client", "idem-del-1"))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ACCOUNT_DELETION_BLOCKED"
    details = refused.json()["error"]["details"]
    assert details["open_disputes"] == 1 and details["reason"] == "active_disputes_exist" and "wallet_posted_minor" in details
    assert scalar(bw.db, "SELECT status FROM users WHERE id = :u", u=bw.w.client_id) == "active"
    replay = trust_client.request("DELETE", "/api/v2/me", headers=auth(bw.w.client_id, "client", "idem-del-1"))
    assert replay.status_code == 409 and replay.headers.get("Idempotent-Replay") in ("true", None)


def test_open_sos_blocks_deletion_and_v2_deletion_succeeds_without_obligations(bw: BW, trust_client) -> None:  # noqa: ANN001
    with bw.db.session() as s:
        trust_service.create_support_ticket(s, actor_user_id=bw.w.client2_id, kind="sos")
        s.commit()
    blocked = trust_client.request("DELETE", "/api/v2/me", headers=auth(bw.w.client2_id, "client", "idem-del-sos"))
    assert blocked.status_code == 409 and blocked.json()["error"]["details"]["open_sos_tickets"] == 1

    deleted = trust_client.request("DELETE", "/api/v2/me", headers=auth(bw.w.client_id, "client", "idem-del-ok"))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"] == {"status": "deleted"}
    assert scalar(bw.db, "SELECT status FROM users WHERE id = :u", u=bw.w.client_id) == "deleted"
    assert scalar(bw.db, "SELECT state FROM idempotency_records WHERE idem_key = 'idem-del-ok'") == "completed"
    assert user_public(bw, bw.w.client2_id).startswith("usr_")
