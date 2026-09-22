"""Chat N6/N7/N10/N11 on PostgreSQL (spec §16, Q43-Q45, Q65; WAVE1_CARDS "Wave 3" A7)."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.contracts import events as contract_events
from app.contracts.communications import CHAT_MAX_MESSAGES_PER_MINUTE
from app.contracts.enums import EventType, QuickReplyCode
from app.contracts.errors import ErrorCode, WarningCode
from app.contracts.timeutil import utc_now
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from app.modules.communications import service as comms
from app.modules.communications.api import message_dto
from tests.pg.communications.conftest import (
    accepted_deal,
    auth,
    dispatch_all,
    domain_error,
    open_thread,
    post,
    rows,
    scalar,
)

pytestmark = pytest.mark.pg

PHONE_AND_CODE = "Menga yozing +998 90 123 45 67, kod 482913"


def test_phone_and_six_digit_code_are_masked_in_response_and_database(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    posted, warnings = post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text=PHONE_AND_CODE)

    assert [w["code"] for w in warnings] == [WarningCode.CONTACT_INFO_MASKED.value]
    assert {"phone", "proof_code"} <= set(warnings[0]["categories"])
    stored = scalar(bw.db, "SELECT text FROM chat_messages WHERE id = :id", id=posted.message.id)
    for secret in ("123 45 67", "998", "482913"):
        assert secret not in stored
    categories = scalar(bw.db, "SELECT contact_filter_categories FROM chat_messages WHERE id = :id", id=posted.message.id)
    assert categories.get("phone") == 1 and categories.get("proof_code") == 1
    assert "482913" not in (message_dto(posted.message, bw.w.driver_id).text or "")
    # R2 / Q45: hit summary without text (audit + staff-only event)
    hit = rows(bw.db, "SELECT details FROM audit_logs WHERE action = 'contact_filter_hit' ORDER BY id DESC LIMIT 1")[0].details
    assert hit["subject_type"] == "chat_message" and "text" not in json.dumps(hit).replace('"chat.text"', "")


def test_contact_filter_hit_survives_a_following_4xx(bw, comms_client) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)  # the proposal thread is accepted -> its chat is read-only
    response = comms_client.post(
        f"/api/v2/proposals/{deal.ref.thread_id}/messages", json={"text": PHONE_AND_CODE},
        headers=auth(bw.w.driver_id, "driver", f"chat-{uuid.uuid4().hex}"),
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == ErrorCode.CHAT_CLOSED.value
    assert scalar(bw.db, "SELECT count(*) FROM chat_messages") == 0
    assert scalar(
        bw.db, "SELECT count(*) FROM audit_logs WHERE action = 'contact_filter_hit' AND details->>'subject_type' = 'chat_message'"
    ) == 1


def test_proposal_chat_closes_on_accept_and_booking_chat_24h_after_terminal(bw) -> None:  # noqa: ANN001
    from app.modules.marketplace import service as marketplace_service  # noqa: F401

    listing_ref = open_thread(bw)
    post(bw.db, "proposal", listing_ref.thread_id, bw.w.driver_id, text="Assalomu alaykum")
    post(bw.db, "proposal", listing_ref.thread_id, bw.w.client_id, quick=QuickReplyCode.CLARIFY_STOP)

    from tests.pg.communications.conftest import accept

    booking = accept(bw, listing_ref, bw.w.client_id)
    error = domain_error(lambda: post(bw.db, "proposal", listing_ref.thread_id, bw.w.client_id, text="yana"))
    assert error.code is ErrorCode.CHAT_CLOSED
    booking_public = bookings_service.booking_public_id(booking)
    post(bw.db, "booking", booking_public, bw.w.client_id, text="Bron chatida yozaman")

    with bw.db.session() as s:  # proposal chat stays readable
        assert len(comms.list_messages(s, kind="proposal", parent_public_id=listing_ref.thread_id,
                                       viewer_user_id=bw.w.client_id, before_id=None, limit=10)) == 2

    with bw.db.session() as s:
        current = s.get(Booking, booking.id)
        bookings_service.cancel_booking(s, booking_public_id_value=booking_public, actor_user_id=bw.w.client_id,
                                        expected_version=current.version, reason_code="plans_changed")
        s.commit()
    terminal_at = scalar(bw.db, "SELECT coalesce(service_terminal_at, updated_at) FROM bookings WHERE id = :b", b=booking.id)
    post(bw.db, "booking", booking_public, bw.w.driver_id, text="Yo'qolgan buyum?", now=terminal_at + timedelta(hours=23))
    late = domain_error(lambda: post(bw.db, "booking", booking_public, bw.w.driver_id, text="kech",
                                     now=terminal_at + timedelta(hours=24, seconds=1)))
    assert late.code is ErrorCode.CHAT_CLOSED


def test_only_parties_read_and_write_staff_reads_with_audit_and_hides(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    posted, _ = post(bw.db, "booking", deal.booking_public_id, bw.w.driver_id, text="5 daqiqada yetaman")

    with bw.db.session() as s:
        for outsider in (bw.w.client2_id, bw.operator_id):  # staff use N10, never the party route
            assert domain_error(lambda: comms.list_messages(
                s, kind="booking", parent_public_id=deal.booking_public_id, viewer_user_id=outsider, before_id=None, limit=10
            )).code is ErrorCode.NOT_FOUND
    assert domain_error(lambda: post(bw.db, "booking", deal.booking_public_id, bw.w.client2_id, text="salom")).code is ErrorCode.NOT_FOUND

    with bw.db.session() as s:
        assert domain_error(lambda: comms.list_messages_for_staff(
            s, kind="booking", parent_public_id=deal.booking_public_id, actor_user_id=bw.w.client2_id, before_id=None, limit=10
        )).code is ErrorCode.CAPABILITY_REQUIRED
    with bw.db.session() as s:
        staff_view = comms.list_messages_for_staff(
            s, kind="booking", parent_public_id=deal.booking_public_id, actor_user_id=bw.operator_id, before_id=None, limit=10
        )
        s.commit()
    assert [m.id for m in staff_view] == [posted.message.id]
    audit = rows(bw.db, "SELECT actor_id, details FROM audit_logs WHERE action = 'chat_viewed'")
    assert len(audit) == 1 and audit[0].actor_id == bw.operator_id and "text" not in audit[0].details

    with bw.db.session() as s:
        hidden = comms.hide_message(s, message_public_id_value=comms.message_public_id(posted.message),
                                    actor_user_id=bw.operator_id, reason="spam check")
        dto = message_dto(hidden, bw.w.client_id)
        s.commit()
    assert dto.text is None and dto.moderation_status.value == "hidden_by_staff"
    assert scalar(bw.db, "SELECT count(*) FROM audit_logs WHERE action = 'chat_message_hidden'") == 1
    with bw.db.session() as s:
        assert domain_error(lambda: comms.hide_message(
            s, message_public_id_value=comms.message_public_id(posted.message), actor_user_id=bw.w.client_id, reason="nope"
        )).code is ErrorCode.CAPABILITY_REQUIRED


def test_rate_limit_per_author_per_thread(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    base = utc_now()
    for index in range(CHAT_MAX_MESSAGES_PER_MINUTE):
        post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text=f"xabar {index}", now=base + timedelta(milliseconds=500 * index))
    error = domain_error(lambda: post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="ortiqcha",
                                      now=base + timedelta(seconds=11)))
    assert error.code is ErrorCode.RATE_LIMITED and error.details["limit"] == CHAT_MAX_MESSAGES_PER_MINUTE
    post(bw.db, "booking", deal.booking_public_id, bw.w.driver_id, text="boshqa muallif", now=base + timedelta(seconds=11))
    post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="bir daqiqadan keyin", now=base + timedelta(seconds=61))


def test_attachment_is_refused_in_wave3(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    error = domain_error(lambda: post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="rasm", attachment="fil_x"))
    assert error.code is ErrorCode.VALIDATION_ERROR and error.details["reason"] == "chat_attachments_not_available"


def test_quick_reply_price_agreed_does_not_change_the_agreement(bw) -> None:  # noqa: ANN001
    ref = open_thread(bw)
    before = rows(bw.db, "SELECT state, version, current_version_id FROM proposal_threads WHERE public_id IS NOT NULL")
    posted, warnings = post(bw.db, "proposal", ref.thread_id, bw.w.client_id, quick=QuickReplyCode.PRICE_AGREED)
    assert warnings == [] and posted.message.text is None
    assert rows(bw.db, "SELECT state, version, current_version_id FROM proposal_threads WHERE public_id IS NOT NULL") == before
    assert scalar(bw.db, "SELECT count(*) FROM bookings") == 0


def test_chat_event_has_no_text_and_reaches_only_the_other_party(bw) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    posted, _ = post(bw.db, "booking", deal.booking_public_id, bw.w.client_id, text="Maxfiy matn salom")
    event = rows(bw.db, "SELECT event_id, payload FROM outbox_events WHERE event_type = 'chat.message.created'")[0]
    assert set(event.payload) <= contract_events.EVENT_PAYLOAD_ALLOWLIST[EventType.CHAT_MESSAGE_CREATED]
    assert "Maxfiy" not in json.dumps(event.payload) and event.payload["author_side"] == "client"

    dispatch_all(bw.db)
    deliveries = rows(bw.db, "SELECT user_id, status, audience, link FROM notification_deliveries WHERE event_id = :e", e=event.event_id)
    assert [(d.user_id, d.status, d.audience) for d in deliveries] == [(bw.w.driver_id, "sent", "driver")]
    assert deliveries[0].link == f"/bookings/{deal.booking_public_id}/messages"
    assert posted.message.id


def test_chat_activity_summary_covers_proposal_and_booking_chats(bw) -> None:  # noqa: ANN001
    from tests.pg.communications.conftest import accept

    ref = open_thread(bw)
    first, _ = post(bw.db, "proposal", ref.thread_id, bw.w.driver_id, text="Salom")
    post(bw.db, "proposal", ref.thread_id, bw.w.client_id, text="Raqamim 90 123 45 67")
    booking = accept(bw, ref, bw.w.client_id)
    last, _ = post(bw.db, "booking", bookings_service.booking_public_id(booking), bw.w.client_id, text="Yo'ldaman")
    # another booking's chat is not counted
    other = accepted_deal(bw, client_id=bw.w.client2_id, driver_id=bw.w.driver2_id, plate="01A777AA")
    post(bw.db, "booking", other.booking_public_id, bw.w.client2_id, text="boshqa")

    with bw.db.session() as s:
        summary = comms.chat_activity_for_booking(s, booking.id)
        empty = comms.chat_activity_for_booking(s, 987654321)
    assert summary.message_count == 3 and summary.contact_filter_hit_count == 1
    assert summary.first_message_at == first.message.created_at and summary.last_message_at == last.message.created_at
    assert summary.last_contact_filter_hit_at is not None
    assert empty.message_count == 0 and empty.first_message_at is None
    assert scalar(bw.db, "SELECT count(*) FROM chat_threads") == 3
    _ = text
