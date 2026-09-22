"""A12 dispute hooks and disputes on PostgreSQL 16 (AC20, AC26, Q66/Q74, STATE_MACHINES §8, §12.3)."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventAudience, payload_for_audience
from app.contracts.enums import EventType
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking, CashReceipt
from app.modules.trust_support import service as trust_service
from tests.pg.bookings.conftest import FUNDED_MINOR, auth, wallet
from tests.pg.harness import run_concurrently
from tests.pg.trust_support.conftest import (
    BW,
    COMPLETE_AT_OFFSET,
    arrived_passenger,
    captures,
    complete,
    dispute_command,
    domain_error,
    open_dispute,
    rows,
    scalar,
)

pytestmark = pytest.mark.pg


def _queue(bw: BW, actor: int, queue: str) -> list[int]:
    with bw.db.session() as s:
        return [b.id for b in bookings_service.admin_queue(s, actor_user_id=actor, queue=queue, corridor_id=None, after_id=None, limit=50)]


def test_registered_probe_clear_captures_once_and_skips_finance_queue(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T100AA")
    before = captures(bw)
    done = complete(bw, booking)
    assert (done.service_status, done.commission_status, done.finance_review_reason) == ("completed", "captured", None)
    assert captures(bw) == before + 1  # AC20: one capture in the completion transaction
    assert _queue(bw, bw.finance_id, "finance_review") == []
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'commission.finance_review_required'") == 0


@pytest.mark.parametrize("dispute_type", ["service", "commission", "payment", "delivery"])
def test_registered_probe_open_blocking_dispute_delays_capture(bw: BW, hooks, dispute_type: str) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T101AA")
    actor = bw.w.driver_id if dispute_type == "commission" else bw.w.client_id
    open_dispute(bw, booking.id, actor, dispute_type)
    before = captures(bw)
    done = complete(bw, booking)
    assert (done.service_status, done.commission_status, done.finance_review_reason) == ("completed", "held", None)
    assert captures(bw) == before
    assert _queue(bw, bw.finance_id, "finance_review") == []  # Q74 fallback is over: not the finance queue
    assert wallet(bw, bw.w.driver_id) == (FUNDED_MINOR, 5_700_000)


@pytest.mark.parametrize("dispute_type", ["no_show", "safety", "other"])
def test_non_blocking_dispute_types_do_not_delay_capture(bw: BW, hooks, dispute_type: str) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T102AA")
    open_dispute(bw, booking.id, bw.w.client_id, dispute_type)
    assert complete(bw, booking).commission_status == "captured"


def test_resolving_last_blocking_dispute_hands_held_commission_to_finance_review_without_capture(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T103AA")
    service_dispute = open_dispute(bw, booking.id, bw.w.client_id, "service")
    delivery_dispute = open_dispute(bw, booking.id, bw.w.client_id, "delivery")
    assert complete(bw, booking).commission_status == "held"
    before = captures(bw)

    dispute_command(bw, service_dispute, bw.operator_id, "start_review")  # operator reviews (wave 3.1)
    resolved = dispute_command(bw, service_dispute, bw.w.admin_id, "resolve", resolution_code="service_confirmed")
    assert resolved.status == "resolved" and resolved.decided_by == bw.w.admin_id  # admin+ decides
    assert _queue(bw, bw.finance_id, "finance_review") == []  # another blocking dispute is still open

    dispute_command(bw, delivery_dispute, bw.w.admin_id, "reject", reason="no evidence")
    assert _queue(bw, bw.finance_id, "finance_review") == [booking.id]
    assert captures(bw) == before  # U8: never an automatic capture
    assert scalar(bw.db, "SELECT commission_status FROM bookings WHERE id = :b", b=booking.id) == "held"
    events = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'dispute.resolved' ORDER BY id")
    assert [e.payload["status"] for e in events] == ["resolved", "rejected"]
    # M1 (wave 3.1): the raw GPS of the trip was held while a dispute was open and released with the last decision
    holds = rows(bw.db, "SELECT reason, source_type, released_at FROM tracking_evidence_holds WHERE trip_id = :t "
                        "ORDER BY id", t=scalar(bw.db, "SELECT trip_id FROM bookings WHERE id = :b", b=booking.id))
    assert [(h.reason, h.source_type) for h in holds] == [("dispute", "dispute"), ("dispute", "dispute")]
    assert all(h.released_at is not None for h in holds)
    # booking/trip status untouched by the dispute machine (§11)
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "completed"


def test_dispute_rules_versions_capabilities_and_terminal_freeze(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T104AA")
    public = open_dispute(bw, booking.id, bw.w.driver_id, "commission")
    with bw.db.session() as s:
        assert domain_error(lambda: trust_service.get_dispute_for_viewer(s, public, bw.w.client_id)).code is ErrorCode.NOT_FOUND
        assert domain_error(lambda: trust_service.open_dispute(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client_id,
            dispute_type="commission", description="x")).code is ErrorCode.VALIDATION_ERROR
        assert domain_error(lambda: trust_service.open_dispute(
            s, booking_public_id_value=bookings_service.booking_public_id(booking), actor_user_id=bw.w.client2_id,
            dispute_type="service", description="x")).code is ErrorCode.NOT_FOUND
    # commission dispute events reach driver/staff, never the client (Q16, events.CLIENT_HIDDEN_DISPUTE_TYPES)
    opened = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'dispute.opened'")
    assert len(opened) == 1
    assert payload_for_audience(EventType.DISPUTE_OPENED, opened[0].payload, EventAudience.CLIENT) is None
    assert payload_for_audience(EventType.DISPUTE_OPENED, opened[0].payload, EventAudience.DRIVER) is not None
    assert domain_error(lambda: dispute_command(bw, public, bw.w.admin_id, "resolve", expected_version=9,
                                                resolution_code="no_action")).code is ErrorCode.VERSION_CONFLICT
    assert domain_error(lambda: dispute_command(bw, public, bw.operator_id, "resolve",
                                                resolution_code="no_action")).code is ErrorCode.CAPABILITY_REQUIRED
    assert domain_error(lambda: dispute_command(bw, public, bw.w.admin_id, "resolve",
                                                resolution_code="commission_adjusted")).code is ErrorCode.CAPABILITY_REQUIRED
    assert domain_error(lambda: dispute_command(bw, public, bw.w.client_id, "start_review", expected_version=1)).code is ErrorCode.CAPABILITY_REQUIRED
    done = dispute_command(bw, public, bw.super_id, "resolve", resolution_code="commission_adjusted", resolution_text="reversal W8")
    assert done.status == "resolved"
    assert domain_error(lambda: dispute_command(bw, public, bw.super_id, "reject", reason="late")).code is ErrorCode.INVALID_STATE_TRANSITION
    with pytest.raises(DBAPIError) as info:
        with bw.db.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE disputes_v2 SET resolution_text = 'tampered'")
    assert info.value.orig.diag.constraint_name == "dispute_terminal_frozen"
    with bw.db.session() as s:
        assert domain_error(lambda: trust_service.add_dispute_evidence(
            s, dispute_public_id_value=public, actor_user_id=bw.w.driver_id, note="late note", file_ids=[])).code is ErrorCode.INVALID_STATE_TRANSITION


def test_parallel_same_type_disputes_open_exactly_one_ac26(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T105AA")

    def work(index: int, session: Session):  # noqa: ANN202
        actor = bw.w.client_id if index % 2 == 0 else bw.w.driver_id
        try:
            return open_dispute(bw, booking.id, actor, "service", session=session)
        except DomainError as exc:
            return exc

    report = run_concurrently(6, work, engine=bw.db.engine)
    assert report.failures == [], [r.error for r in report.failures]
    values = report.values()
    assert len([v for v in values if isinstance(v, str)]) == 1
    assert all(v.code is ErrorCode.DISPUTE_ALREADY_OPEN for v in values if isinstance(v, DomainError))
    assert scalar(bw.db, "SELECT count(*) FROM disputes_v2 WHERE booking_id = :b", b=booking.id) == 1


def test_dispute_open_vs_completion_race_serialises_without_deadlock(bw: BW, hooks) -> None:  # noqa: ANN001
    outcomes = set()
    for round_no, plate in enumerate(("01T106AA", "01T107AA")):
        client_id, driver_id = (bw.w.client_id, bw.w.driver_id) if round_no % 2 == 0 else (bw.w.client2_id, bw.w.driver2_id)
        booking = arrived_passenger(bw, plate, client_id=client_id, driver_id=driver_id)

        def work(index: int, session: Session):  # noqa: ANN202
            if index == round_no % 2:
                time.sleep(0.15)
            if index == 0:
                return open_dispute(bw, booking.id, client_id, "service", session=session)
            fresh = session.get(Booking, booking.id)
            result = bookings_service.perform_action(
                session, booking_public_id_value=bookings_service.booking_public_id(fresh), actor_user_id=client_id,
                action="complete", data=bookings_service.ActionInput(expected_version=fresh.version), now=bw.base + COMPLETE_AT_OFFSET,
            )
            session.commit()
            return result.commission_status

        report = run_concurrently(2, work, engine=bw.db.engine)
        failures = [r.error for r in report.failures]
        assert all(isinstance(e, DomainError) and e.code is ErrorCode.VERSION_CONFLICT for e in failures), failures
        status = scalar(bw.db, "SELECT commission_status FROM bookings WHERE id = :b", b=booking.id)
        disputes = scalar(bw.db, "SELECT count(*) FROM disputes_v2 WHERE booking_id = :b", b=booking.id)
        if status == "captured":
            # the dispute (if any) was committed after the capture
            outcomes.add("capture_first")
        else:
            assert status == "held" and disputes == 1
            outcomes.add("dispute_first")
    assert outcomes  # no deadlock, every round consistent


def test_contest_opens_payment_dispute_linked_to_receipt_and_delays_capture(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T110AA")
    with bw.db.session() as s:
        current = s.get(Booking, booking.id)
        _, receipt = bookings_service.report_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(current), actor_user_id=bw.w.driver_id,
            expected_version=current.version, amount_minor=current.total_minor, reported_at=bw.base + timedelta(hours=3),
            now=bw.base + timedelta(hours=3),
        )
        receipt_public = format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id)
        s.commit()
    with bw.db.session() as s:
        current = s.get(Booking, booking.id)
        receipt = s.execute(__import__("sqlalchemy").select(CashReceipt).where(CashReceipt.booking_id == booking.id)).scalar_one()
        after, contested = bookings_service.contest_cash_receipt(
            s, booking_public_id_value=bookings_service.booking_public_id(current), receipt_public_id=receipt_public,
            actor_user_id=bw.w.client_id, expected_version=receipt.version, comment="Pul berilmadi, +998 90 123 45 67 ga qo'ng'iroq qiling",
            now=bw.base + timedelta(hours=3, minutes=1),
        )
        dispute_id = contested.dispute_id
        assert dispute_id is not None
        assert trust_service.open_payment_dispute(s, after, contested, bw.w.client_id, "again") == dispute_id  # idempotent
        s.commit()
    row = rows(bw.db, "SELECT dispute_type, status, cash_receipt_id, description FROM disputes_v2 WHERE id = :d", d=dispute_id)[0]
    assert (row.dispute_type, row.status) == ("payment", "open") and row.cash_receipt_id is not None
    assert "123 45 67" not in row.description  # Q43 masked
    assert scalar(bw.db, "SELECT service_status FROM bookings WHERE id = :b", b=booking.id) == "arrived"
    assert complete(bw, booking).commission_status == "held"


def test_escalation_worker_marks_due_disputes_once(bw: BW, hooks) -> None:  # noqa: ANN001
    booking = arrived_passenger(bw, "01T111AA")
    public = open_dispute(bw, booking.id, bw.w.client_id, "service")
    from app.contracts.timeutil import utc_now

    with bw.db.session() as s:
        assert trust_service.emit_dispute_escalations(s, now=utc_now() + timedelta(hours=47)) == 0
        assert trust_service.emit_dispute_escalations(s, now=utc_now() + timedelta(hours=49)) == 1
        s.commit()
    with bw.db.session() as s:
        assert trust_service.emit_dispute_escalations(s, now=utc_now() + timedelta(hours=50)) == 0
        rows_ = trust_service.admin_list_disputes(s, actor_user_id=bw.operator_id, status=None, dispute_type=None, escalated=True,
                                                  after_id=None, limit=10)
        assert [trust_service.dispute_public_id(d) for d in rows_] == [public]
    due = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'dispute.escalation_due'")
    assert len(due) == 1 and set(due[0].payload) == {"booking_id", "dispute_type", "escalate_at"}
    assert payload_for_audience(EventType.DISPUTE_ESCALATION_DUE, due[0].payload, EventAudience.CLIENT) is None


def _evidence_upload(owner_id: int) -> str:
    """A real private `dispute_evidence` upload of this user (wave 3.1: evidence is bound to its uploader)."""
    from app.utils.file_access import sign_file_key
    from app.utils.file_storage import store_upload_file
    from app.utils.file_validation import DISPUTE_EVIDENCE_UPLOAD_TYPE, FileValidationResult

    png = bytes.fromhex("89504e470d0a1a0a") + b"0" * 64
    validated = FileValidationResult(
        upload_type=DISPUTE_EVIDENCE_UPLOAD_TYPE, extension="png", mime_type="image/png", size_bytes=len(png),
        original_filename="evidence.png", content=png,
    )
    return sign_file_key(store_upload_file(validated, owner_id=owner_id))


def test_dispute_http_flow_events_and_evidence_append_only(bw: BW, hooks, trust_client, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    booking = arrived_passenger(bw, "01T112AA")
    booking_public = f"/api/v2/bookings/{bookings_service.booking_public_id(booking)}/disputes"
    body = {"type": "service", "description": "Telefonim 90 123 45 67",
            "evidence_file_ids": [_evidence_upload(bw.w.client_id)]}
    first = trust_client.post(booking_public, json=body, headers=auth(bw.w.client_id, "client", "idem-key-dsp-1"))
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["warnings"][0]["code"] == "CONTACT_INFO_MASKED" and "123 45 67" not in data["data"]["description"]
    replay = trust_client.post(booking_public, json=body, headers=auth(bw.w.client_id, "client", "idem-key-dsp-1"))
    assert replay.status_code == 201 and replay.json()["data"]["id"] == data["data"]["id"]
    again = trust_client.post(booking_public, json=body, headers=auth(bw.w.driver_id, "driver", "idem-key-dsp-2"))
    assert again.status_code == 409 and again.json()["error"]["code"] == "DISPUTE_ALREADY_OPEN"
    # masked-text hits survive as staff-only events (R2-b): the first command and the refused 409 attempt; not the replay
    assert scalar(bw.db, "SELECT count(*) FROM outbox_events WHERE event_type = 'trust.contact_filter.hit'") == 2
    # H0 wave 3.1: somebody else's upload cannot be attached as evidence.
    stolen = trust_client.post(f"/api/v2/disputes/{data['data']['id']}/evidence",
                               json={"note": "rasm", "file_ids": [_evidence_upload(bw.w.client_id)]},
                               headers=auth(bw.w.driver_id, "driver", "idem-key-ev-0"))
    assert stolen.status_code == 400 and stolen.json()["error"]["details"]["field"] == "file_ids"
    evidence = trust_client.post(f"/api/v2/disputes/{data['data']['id']}/evidence",
                                 json={"note": "rasm", "file_ids": [_evidence_upload(bw.w.driver_id)]},
                                 headers=auth(bw.w.driver_id, "driver", "idem-key-ev-1"))
    assert evidence.status_code == 200 and len(evidence.json()["data"]["evidence"]) == 2
    mine = trust_client.get("/api/v2/me/disputes", headers=auth(bw.w.driver_id, "driver"))
    assert [d["id"] for d in mine.json()["data"]] == [data["data"]["id"]]
    assert trust_client.get("/api/v2/admin/disputes", headers=auth(bw.w.client_id, "client")).status_code == 403
    staff = trust_client.post(f"/api/v2/admin/disputes/{data['data']['id']}/start-review", json={"expected_version": 1},
                              headers=auth(bw.operator_id, "operator", "idem-key-cmd-1"))
    assert staff.status_code == 200 and staff.json()["data"]["status"] == "under_review"
    opened = rows(bw.db, "SELECT payload FROM outbox_events WHERE event_type = 'dispute.opened'")
    assert [o.payload for o in opened] == [{"booking_id": bookings_service.booking_public_id(booking), "dispute_type": "service"}]
    for statement in ("UPDATE dispute_evidence SET note = 'x'", "DELETE FROM dispute_evidence"):
        with pytest.raises(DBAPIError) as info:
            with bw.db.engine.begin() as conn:
                conn.exec_driver_sql(statement)
        assert info.value.orig.diag.constraint_name == "append_only_violation"
    from app.contracts.db_errors import map_db_error

    assert map_db_error(sqlstate="23001", constraint="append_only_violation").code is ErrorCode.INTEGRITY_CONFLICT
    assert payload_for_audience(EventType.DISPUTE_OPENED, opened[0].payload, EventAudience.CLIENT) is not None
