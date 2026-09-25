"""ADR-0026 (Q141): the booking-bound operator chat ("Shikoyat qilish") on real PostgreSQL.

What is proven here: the button opens the caller's chat for *that* booking; a retry or a second tap returns the same
open thread (HTTP idempotency and the partial unique index under a parallel burst); the client's and the driver's
threads are separate and private (404 for anyone else); staff assign, answer and close; the requester sees an honest
queue status; and nothing in the chat moves money, commission, bonuses or fraud verdicts. The last test carries old
disputes over through migration 20260924_0092 (re-run via stamp) with their text, evidence and decision.
SYNTHETIC people, phones and amounts.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.modules.bookings import service as bookings_service
from app.modules.trust_support import threads
from tests.pg.bookings.conftest import auth
from tests.pg.conftest import run_alembic
from tests.pg.harness import run_concurrently
from tests.pg.trust_support.conftest import BW, arrived_passenger, dispute_command, open_dispute, rows, scalar

pytestmark = pytest.mark.pg

_MONEY_SQL = """
SELECT (SELECT count(*) FROM ledger_transactions) AS ledger,
       (SELECT count(*) FROM wallet_holds) AS holds,
       (SELECT string_agg(commission_status || '/' || service_status || '/' || cash_status, ',' ORDER BY id) FROM bookings) AS bookings,
       (SELECT count(*) FROM promo_ledger_transactions) AS promo,
       (SELECT count(*) FROM fraud_signals) AS fraud
"""


def _money(bw: BW) -> tuple:
    return tuple(rows(bw.db, _MONEY_SQL)[0])


def _open(trust_client, booking_public: str, user_id: int, role: str, key: str, text: str | None = None):  # noqa: ANN001, ANN202
    return trust_client.post(f"/api/v2/bookings/{booking_public}/support-thread", json={"text": text},
                             headers=auth(user_id, role, key))


def test_complaint_button_opens_one_private_thread_per_side_and_staff_answer_without_money(bw: BW, trust_client) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T301AA")
    public = bookings_service.booking_public_id(booking)
    money_before = _money(bw)

    first = _open(trust_client, public, bw.w.client_id, "client", "sth-open-client-1", "Haydovchi kechikdi, tel 90 123 45 67")
    assert first.status_code == 200, first.text
    thread = first.json()["data"]
    assert (thread["booking_id"], thread["requester_side"], thread["status"], thread["staff_status"]) == (public, "client", "open", "waiting")
    assert first.json()["warnings"][0]["code"] == "CONTACT_INFO_MASKED"
    assert "123 45 67" not in thread["messages"][0]["text"] and thread["messages"][0]["author"] == "me"
    # a network retry (same key) and a second tap (new key, no text) both return the same open thread
    replay = _open(trust_client, public, bw.w.client_id, "client", "sth-open-client-1", "Haydovchi kechikdi, tel 90 123 45 67")
    again = _open(trust_client, public, bw.w.client_id, "client", "sth-open-client-2")
    assert replay.json()["data"]["id"] == again.json()["data"]["id"] == thread["id"]
    assert again.json()["data"]["message_count"] == 1
    assert scalar(bw.db, "SELECT count(*) FROM support_threads WHERE booking_id = :b", b=booking.id) == 1

    # the driver's complaint about the same booking is a separate, private thread
    driver_thread = _open(trust_client, public, bw.w.driver_id, "driver", "sth-open-driver-1", "Mijoz bekatda yo'q edi").json()["data"]
    assert driver_thread["id"] != thread["id"] and driver_thread["requester_side"] == "driver"
    for viewer, role, other in ((bw.w.client_id, "client", driver_thread["id"]), (bw.w.driver_id, "driver", thread["id"])):
        assert trust_client.get(f"/api/v2/support-threads/{other}", headers=auth(viewer, role)).status_code == 404
        posted = trust_client.post(f"/api/v2/support-threads/{other}/messages", json={"text": "salom"},
                                   headers=auth(viewer, role, f"sth-foreign-{role}"))
        assert posted.status_code == 404
    # a stranger cannot open or even see a chat for somebody else's booking
    assert _open(trust_client, public, bw.w.client2_id, "client", "sth-open-stranger").status_code == 404
    assert trust_client.get(f"/api/v2/bookings/{public}/support-thread", headers=auth(bw.w.client2_id, "client")).status_code == 404
    mine = trust_client.get(f"/api/v2/bookings/{public}/support-thread", headers=auth(bw.w.client_id, "client")).json()["data"]
    assert mine["id"] == thread["id"]
    assert [t["id"] for t in trust_client.get("/api/v2/me/support-threads", headers=auth(bw.w.client_id, "client")).json()["data"]] == [thread["id"]]

    # staff: the queue shows both, the requester and the booking; clients cannot read it
    assert trust_client.get("/api/v2/admin/support-threads", headers=auth(bw.w.client_id, "client")).status_code == 403
    queue = trust_client.get("/api/v2/admin/support-threads?assigned=unassigned", headers=auth(bw.operator_id, "operator")).json()["data"]
    assert {(t["id"], t["booking_id"], t["assigned_to"]) for t in queue} == {(thread["id"], public, None), (driver_thread["id"], public, None)}
    admin_url = f"/api/v2/admin/support-threads/{thread['id']}"
    assigned = trust_client.post(f"{admin_url}/assign", json={"expected_version": thread["version"]},
                                 headers=auth(bw.operator_id, "operator", "sth-assign-1"))
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["data"]["assigned_to"] is not None and assigned.json()["data"]["staff_status"] == "assigned"
    client_view = trust_client.get(f"/api/v2/support-threads/{thread['id']}", headers=auth(bw.w.client_id, "client")).json()["data"]
    assert client_view["staff_status"] == "assigned"  # the honest status the requester sees
    replied = trust_client.post(f"{admin_url}/reply", json={"expected_version": assigned.json()["data"]["version"],
                                                            "text": "Ko'rib chiqyapmiz"},
                                headers=auth(bw.operator_id, "operator", "sth-reply-1"))
    assert replied.status_code == 200 and replied.json()["data"]["staff_status"] == "answered"
    client_view = trust_client.get(f"/api/v2/support-threads/{thread['id']}", headers=auth(bw.w.client_id, "client")).json()["data"]
    assert [m["author"] for m in client_view["messages"]] == ["me", "operator"]
    driver_view = trust_client.get(f"/api/v2/support-threads/{driver_thread['id']}", headers=auth(bw.w.driver_id, "driver")).json()["data"]
    assert [m["author"] for m in driver_view["messages"]] == ["me"]  # nothing of the client's thread leaks over
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'support.thread.replied'") == 1
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'support.thread.opened'") == 2

    closed = trust_client.post(f"{admin_url}/close", json={"expected_version": replied.json()["data"]["version"]},
                               headers=auth(bw.operator_id, "operator", "sth-close-1"))
    assert closed.status_code == 200 and closed.json()["data"]["status"] == "closed"
    late = trust_client.post(f"/api/v2/support-threads/{thread['id']}/messages", json={"text": "yana"},
                             headers=auth(bw.w.client_id, "client", "sth-late-1"))
    assert late.status_code == 409 and late.json()["error"]["code"] == "SUPPORT_THREAD_CLOSED"
    reopened = _open(trust_client, public, bw.w.client_id, "client", "sth-open-client-3").json()["data"]
    assert reopened["id"] != thread["id"] and reopened["status"] == "open"  # a new complaint, the closed one stays as it was

    # opening, answering and closing never refunded, released, captured, granted or flagged anything
    assert _money(bw) == money_before


def test_a_burst_of_taps_opens_exactly_one_thread(bw: BW) -> None:
    booking = arrived_passenger(bw, "01T302AA")
    public = bookings_service.booking_public_id(booking)

    def work(index: int, session: Session) -> str:
        thread, _ = threads.open_or_get_thread(session, booking_public_id_value=public, actor_user_id=bw.w.client_id,
                                               text_value=None, warnings=[], filter_hits=[])
        session.commit()
        return threads.thread_public_id(thread)

    report = run_concurrently(6, work, engine=bw.db.engine)
    assert not report.failures, report.results
    assert len({r.value for r in report.results}) == 1
    assert scalar(bw.db, "SELECT count(*) FROM support_threads WHERE booking_id = :b AND status = 'open'", b=booking.id) == 1


def test_migration_carries_old_disputes_into_the_chat_with_their_history(bw: BW) -> None:
    """0092 converts every client/driver dispute: the text, each evidence note and the staff decision become messages
    of a thread for the same booking and person; an open dispute gives an open thread. Disputes are not modified.
    Re-running the body (stamp back + upgrade) duplicates nothing."""
    open_booking = arrived_passenger(bw, "01T303AA")
    decided_booking = arrived_passenger(bw, "01T304AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    still_open = open_dispute(bw, open_booking.id, bw.w.client_id, description="Haydovchi boshqa yo'ldan yurdi")
    decided = open_dispute(bw, decided_booking.id, bw.w.client2_id, description="Yuk kech keldi")
    dispute_command(bw, decided, bw.operator_id, "start_review")
    dispute_command(bw, decided, bw.w.admin_id, "reject", reason="dalil yo'q")
    disputes_before = rows(bw.db, "SELECT id, status, version FROM disputes_v2 ORDER BY id")
    assert scalar(bw.db, "SELECT count(*) FROM support_threads WHERE source_dispute_id IS NOT NULL") == 0

    for _ in range(2):  # the second pass proves the carry-over is idempotent
        assert run_alembic(bw.db.url, "stamp", "20260924_0091").returncode == 0
        result = run_alembic(bw.db.url, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr

    carried = rows(bw.db, "SELECT t.booking_id, t.requester_user_id, t.requester_side, t.status, t.message_count, d.public_id "
                          "FROM support_threads t JOIN disputes_v2 d ON d.id = t.source_dispute_id ORDER BY t.booking_id")
    assert [(r.booking_id, r.requester_user_id, r.requester_side, r.status) for r in carried] == [
        (open_booking.id, bw.w.client_id, "client", "open"), (decided_booking.id, bw.w.client2_id, "client", "closed")]
    decided_thread = scalar(bw.db, "SELECT t.id FROM support_threads t JOIN disputes_v2 d ON d.id = t.source_dispute_id "
                                   "WHERE t.booking_id = :b", b=decided_booking.id)
    lines = rows(bw.db, "SELECT author_side, source_kind, text FROM support_messages WHERE thread_id = :t ORDER BY created_at, id",
                 t=decided_thread)
    assert lines[0].source_kind == "dispute" and lines[0].text == "Yuk kech keldi"
    assert lines[-1].source_kind == "dispute_decision" and "rejected" in lines[-1].text
    assert scalar(bw.db, "SELECT count(*) FROM support_messages WHERE source_kind IS NOT NULL") == sum(r.message_count for r in carried)
    assert rows(bw.db, "SELECT id, status, version FROM disputes_v2 ORDER BY id") == disputes_before  # history untouched
    assert still_open  # the open complaint stays answerable in the chat


def _upload(owner_id: int) -> str:
    """A real private `dispute_evidence` upload of this user (returned as the signed URL the old API accepted)."""
    from app.utils.file_access import sign_file_key
    from app.utils.file_storage import store_upload_file
    from app.utils.file_validation import DISPUTE_EVIDENCE_UPLOAD_TYPE, FileValidationResult

    png = bytes.fromhex("89504e470d0a1a0a") + b"0" * 64
    validated = FileValidationResult(upload_type=DISPUTE_EVIDENCE_UPLOAD_TYPE, extension="png", mime_type="image/png",
                                     size_bytes=len(png), original_filename="evidence.png", content=png)
    return sign_file_key(store_upload_file(validated, owner_id=owner_id))


def _evidence(bw: BW, dispute: str, actor_id: int, note: str, files: list[str]) -> None:
    from app.modules.trust_support import service as trust_service

    with bw.db.session() as s:
        trust_service.add_dispute_evidence(s, dispute_public_id_value=dispute, actor_user_id=actor_id, note=note, file_ids=files)
        s.commit()


def test_carried_over_disputes_keep_the_other_sides_and_staff_material_away_from_the_requester(
    bw: BW, trust_client, tmp_path, monkeypatch  # noqa: ANN001
) -> None:
    """0092 + 0093 (ADR-0026, Q141): the requester reads their own complaint, their own evidence notes and the decision -
    not the other participant's or staff evidence, and no file at all (the user DTO carries no file id or link; a key
    without a signature is refused). Staff see everything, marked. Re-running the migrations duplicates nothing."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.files import router as files_router
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    booking = arrived_passenger(bw, "01T305AA")
    dispute = open_dispute(bw, booking.id, bw.w.client_id, description="Haydovchi yo'lni o'zgartirdi")
    own_file, driver_file, staff_file = _upload(bw.w.client_id), _upload(bw.w.driver_id), _upload(bw.operator_id)
    _evidence(bw, dispute, bw.w.client_id, "Mening skrinshotim", [own_file])
    _evidence(bw, dispute, bw.w.driver_id, "Haydovchining maxfiy izohi", [driver_file])
    _evidence(bw, dispute, bw.operator_id, "Xodimning ichki tekshiruv izohi", [staff_file])

    for _ in range(2):  # a re-run of the bodies (stamp back + upgrade) must not duplicate or reopen anything
        assert run_alembic(bw.db.url, "stamp", "20260924_0091").returncode == 0
        result = run_alembic(bw.db.url, "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr
    thread_id = scalar(bw.db, "SELECT id FROM support_threads WHERE source_dispute_id IS NOT NULL")
    assert scalar(bw.db, "SELECT count(*) FROM support_messages WHERE thread_id = :t", t=thread_id) == 4  # text + 3 evidence
    thread_public = rows(bw.db, "SELECT public_id FROM support_threads WHERE id = :t", t=thread_id)[0].public_id

    from app.contracts.ids import PublicIdPrefix, format_public_id

    public = format_public_id(PublicIdPrefix.SUPPORT_THREAD, thread_public)
    mine = trust_client.get(f"/api/v2/support-threads/{public}", headers=auth(bw.w.client_id, "client"))
    assert mine.status_code == 200, mine.text
    data = mine.json()["data"]
    texts = [m["text"] for m in data["messages"]]
    assert texts == ["Haydovchi yo'lni o'zgartirdi", "Mening skrinshotim"] and data["message_count"] == 2
    raw = mine.text
    assert "maxfiy" not in raw and "ichki" not in raw  # neither the other side's nor staff material reaches the requester
    for signed in (own_file, driver_file, staff_file):  # no file id or link at all in the requester's view
        key = signed.split("/files/", 1)[1].split("?", 1)[0]
        assert key not in raw
    listed = trust_client.get("/api/v2/me/support-threads", headers=auth(bw.w.client_id, "client")).json()["data"]
    assert [t["message_count"] for t in listed] == [2]
    # the other participant cannot open this thread at all
    assert trust_client.get(f"/api/v2/support-threads/{public}", headers=auth(bw.w.driver_id, "driver")).status_code == 404

    staff = trust_client.get(f"/api/v2/admin/support-threads/{public}", headers=auth(bw.operator_id, "operator")).json()["data"]
    flags = {m["text"]: m["staff_only"] for m in staff["messages"]}
    assert flags == {"Haydovchi yo'lni o'zgartirdi": False, "Mening skrinshotim": False,
                     "Haydovchining maxfiy izohi": True, "Xodimning ichki tekshiruv izohi": True}

    files = FastAPI()
    files.include_router(files_router, prefix="/api/v1")
    with TestClient(files) as http:
        key = driver_file.split("/files/", 1)[1].split("?", 1)[0]
        assert http.get(f"/api/v1/files/{key}").status_code == 403  # knowing a key opens nothing
        assert http.get(f"/api/v1/files/{key}?exp=9999999999&sig=forged").status_code == 403


def _login(bw: BW, user_id: int) -> tuple[dict[str, str], str]:
    """A real login (v1 flow): the access token is bound to a live session (§17.6 ``sid``)."""
    from app.core.security import verify_token
    from app.models import User
    from app.services import auth_service

    with bw.db.session() as session:
        payload = auth_service.build_token_response(session, session.get(User, user_id))
        session.commit()
    token = payload["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}, verify_token(token)["sid"]


def test_staff_open_evidence_files_only_through_a_checked_short_lived_link(bw: BW, trust_client, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """ADR-0026: staff see a file label and a reference, never the storage key; opening one needs a live staff session,
    ops.trust_review and the file belonging to this thread; the answer is the existing short-lived signed link, the view
    is audited and moves no money. Another thread's file, a requester, a revoked session and an expired link are refused."""
    import time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import text as sql_text

    from app.api.v1.files import router as files_router
    from app.contracts.ids import PublicIdPrefix, format_public_id
    from app.core.config import settings
    from app.utils.file_access import sign_file_key

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    first = arrived_passenger(bw, "01T310AA")
    second = arrived_passenger(bw, "01T311AA", client_id=bw.w.client2_id, driver_id=bw.w.driver2_id)
    one = open_dispute(bw, first.id, bw.w.client_id, description="Birinchi shikoyat")
    two = open_dispute(bw, second.id, bw.w.client2_id, description="Ikkinchi shikoyat")
    _evidence(bw, one, bw.w.client_id, "Mijoz rasmi", [_upload(bw.w.client_id)])
    _evidence(bw, one, bw.operator_id, "Xodimning ichki rasmi", [_upload(bw.operator_id)])
    _evidence(bw, two, bw.w.client2_id, "Boshqa murojaat rasmi", [_upload(bw.w.client2_id)])
    for _ in range(1):
        assert run_alembic(bw.db.url, "stamp", "20260924_0091").returncode == 0
        assert run_alembic(bw.db.url, "upgrade", "head").returncode == 0
    pids = {r.booking_id: format_public_id(PublicIdPrefix.SUPPORT_THREAD, r.public_id)
            for r in rows(bw.db, "SELECT booking_id, public_id FROM support_threads WHERE source_dispute_id IS NOT NULL")}
    thread_one, thread_two = pids[first.id], pids[second.id]
    money_before = _money(bw)

    staff_headers, staff_sid = _login(bw, bw.operator_id)
    detail = trust_client.get(f"/api/v2/admin/support-threads/{thread_one}", headers=staff_headers)
    assert detail.status_code == 200, detail.text
    files = detail.json()["data"]["files"]
    assert [f["staff_only"] for f in files] == [False, True] and all(f["name"].startswith("Dalil ") for f in files)
    assert "dispute_evidence/" not in detail.text  # no raw storage key anywhere in the staff answer either
    other_ref = trust_client.get(f"/api/v2/admin/support-threads/{thread_two}", headers=staff_headers).json()["data"]["files"][0]["ref"]

    url = f"/api/v2/admin/support-threads/{thread_one}/files/{files[1]['ref']}"
    opened = trust_client.get(url, headers=staff_headers)
    assert opened.status_code == 200, opened.text
    link = opened.json()["data"]
    assert link["name"] == files[1]["name"] and "/files/" in link["url"] and "sig=" in link["url"]
    files_app = FastAPI()
    files_app.include_router(files_router, prefix="/api/v1")
    with TestClient(files_app) as http:
        assert http.get(link["url"]).status_code == 200  # the signed link works while it is valid
        key = link["url"].split("/files/", 1)[1].split("?", 1)[0]
        assert http.get(f"/api/v1/files/{key}").status_code == 403  # the key alone opens nothing
        expired = sign_file_key(key, now=time.time() - 3 * 24 * 3600)
        assert http.get(expired).status_code == 403  # an expired link is refused

    # another thread's file through this thread, a made-up ref: 404
    assert trust_client.get(f"/api/v2/admin/support-threads/{thread_one}/files/{other_ref}", headers=staff_headers).status_code == 404
    assert trust_client.get(f"/api/v2/admin/support-threads/{thread_one}/files/smg_x.9", headers=staff_headers).status_code == 404
    # no live session claim (a bare token), a requester, another participant, staff without ops.trust_review: refused
    assert trust_client.get(url, headers=auth(bw.operator_id, "operator")).status_code == 401
    for user_id in (bw.w.client_id, bw.w.driver_id, bw.finance_id):
        headers, _ = _login(bw, user_id)
        answer = trust_client.get(url, headers=headers)
        assert answer.status_code in (403, 404), (user_id, answer.text)
        assert "sig=" not in answer.text
    # a revoked staff session stops working at once
    with bw.db.engine.begin() as conn:
        conn.execute(sql_text("UPDATE refresh_sessions SET is_revoked = true WHERE jti = :j"), {"j": staff_sid})
    assert trust_client.get(url, headers=staff_headers).status_code == 401
    # the requester still sees neither the internal file nor any link
    mine = trust_client.get(f"/api/v2/support-threads/{thread_one}", headers=auth(bw.w.client_id, "client"))
    assert "ichki" not in mine.text and "sig=" not in mine.text and "files" not in mine.json()["data"]
    assert scalar(bw.db, "SELECT count(*) FROM audit_logs WHERE action = 'support_thread_file_viewed'") == 1
    assert _money(bw) == money_before  # viewing a file moved no money, hold, bonus or booking state
