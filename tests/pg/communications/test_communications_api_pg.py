"""Mounted communications router (N1-N11) over HTTP on PostgreSQL."""

from __future__ import annotations

import uuid

import pytest

from app.contracts.errors import ErrorCode, WarningCode
from app.contracts.idempotency import IDEMPOTENT_REPLAY_HEADER
from tests.pg.communications.conftest import accepted_deal, auth, dispatch_all, enqueue_user_event, scalar

pytestmark = pytest.mark.pg


def _key() -> str:
    return f"k-{uuid.uuid4().hex}"


def test_chat_inbox_devices_and_operator_queue_over_http(bw, comms_client, fake_consumers) -> None:  # noqa: ANN001
    deal = accepted_deal(bw)
    path = f"/api/v2/bookings/{deal.booking_public_id}/messages"
    key = _key()
    body = {"text": "Qo'ng'iroq qiling 90 123 45 67"}
    created = comms_client.post(path, json=body, headers=auth(bw.w.client_id, "client", key))
    assert created.status_code == 201, created.text
    envelope = created.json()
    assert envelope["data"]["author_side"] == "client" and envelope["data"]["is_mine"] is True
    assert "123 45 67" not in envelope["data"]["text"]
    assert envelope["warnings"][0]["code"] == WarningCode.CONTACT_INFO_MASKED.value
    replay = comms_client.post(path, json=body, headers=auth(bw.w.client_id, "client", key))
    assert replay.status_code == 201 and replay.headers.get(IDEMPOTENT_REPLAY_HEADER) == "true" and replay.json() == envelope
    assert scalar(bw.db, "SELECT count(*) FROM chat_messages") == 1
    assert scalar(bw.db, "SELECT count(*) FROM audit_logs WHERE action = 'contact_filter_hit'") == 1  # replay records nothing

    listed = comms_client.get(path, headers=auth(bw.w.driver_id, "driver"))
    assert listed.status_code == 200
    item = listed.json()["data"][0]
    assert item["is_mine"] is False and set(item) == {"id", "author_side", "is_mine", "text", "quick_reply_code", "moderation_status", "created_at"}
    assert comms_client.get(path, headers=auth(bw.w.client2_id, "client")).status_code == 404
    attachment = comms_client.post(path, json={"text": "rasm", "attachment_file_id": "fil_x"}, headers=auth(bw.w.client_id, "client", _key()))
    assert attachment.status_code == 400 and attachment.json()["error"]["details"]["reason"] == "chat_attachments_not_available"

    dispatch_all(bw.db)
    inbox = comms_client.get("/api/v2/notifications", headers=auth(bw.w.driver_id, "driver"))
    assert inbox.status_code == 200
    chat = [n for n in inbox.json()["data"] if n["type"] == "chat.message.created"]
    assert chat and chat[0]["id"].startswith("ntf_") and chat[0]["is_read"] is False
    assert chat[0]["title_key"] == "notification.chat.message.created.title" and "text" not in chat[0]["params"]
    read = comms_client.post(f"/api/v2/notifications/{chat[0]['id']}/read", json={}, headers=auth(bw.w.driver_id, "driver"))
    assert read.status_code == 200 and read.json()["data"]["is_read"] is True
    unread = comms_client.get("/api/v2/notifications?unread=true", headers=auth(bw.w.driver_id, "driver")).json()["data"]
    assert all(n["id"] != chat[0]["id"] for n in unread)
    assert comms_client.post(f"/api/v2/notifications/{chat[0]['id']}/read", json={}, headers=auth(bw.w.client_id, "client")).status_code == 404

    events = comms_client.get("/api/v2/events?limit=2", headers=auth(bw.w.client_id, "client"))
    assert events.status_code == 200
    page = events.json()
    assert all(e["id"].startswith("evt_") and not e["event_type"].startswith(("wallet.", "commission.")) for e in page["data"])
    if page["meta"]["next_cursor"]:
        nxt = comms_client.get(f"/api/v2/events?limit=2&after={page['meta']['next_cursor']}", headers=auth(bw.w.client_id, "client"))
        assert nxt.status_code == 200 and {e["id"] for e in nxt.json()["data"]}.isdisjoint({e["id"] for e in page["data"]})
        other_user = comms_client.get(f"/api/v2/events?after={page['meta']['next_cursor']}", headers=auth(bw.w.driver_id, "driver"))
        assert other_user.status_code == 400 and other_user.json()["error"]["code"] == ErrorCode.INVALID_CURSOR.value
    bad = comms_client.get("/api/v2/events?after=garbage", headers=auth(bw.w.client_id, "client"))
    assert bad.status_code == 400 and bad.json()["error"]["code"] == ErrorCode.INVALID_CURSOR.value

    device = comms_client.post("/api/v2/devices/push-token", json={"platform": "web", "token_or_subscription": "x" * 40, "app_version": "1.2.0"},
                               headers=auth(bw.w.driver_id, "driver", _key()))
    assert device.status_code == 201, device.text
    device_id = device.json()["data"]["id"]
    assert device_id.startswith("dev_") and "token" not in str(device.json()["data"])
    assert comms_client.delete(f"/api/v2/devices/{device_id}", headers=auth(bw.w.client_id, "client")).status_code == 404
    assert comms_client.delete(f"/api/v2/devices/{device_id}", headers=auth(bw.w.driver_id, "driver")).status_code == 200
    assert comms_client.delete(f"/api/v2/devices/{device_id}", headers=auth(bw.w.driver_id, "driver")).status_code == 404

    # N10/N11 staff
    staff_list = comms_client.get(f"/api/v2/admin/bookings/{deal.booking_public_id}/messages", headers=auth(bw.operator_id, "operator"))
    assert staff_list.status_code == 200 and staff_list.json()["data"][0]["author_user_id"].startswith("usr_")
    assert comms_client.get(f"/api/v2/admin/bookings/{deal.booking_public_id}/messages", headers=auth(bw.w.client_id, "client")).status_code == 403
    message_id = staff_list.json()["data"][0]["id"]
    hidden = comms_client.post(f"/api/v2/admin/chat/messages/{message_id}/hide", json={"reason": "tekshiruv"},
                               headers=auth(bw.operator_id, "operator", _key()))
    assert hidden.status_code == 200, hidden.text
    assert comms_client.get(path, headers=auth(bw.w.driver_id, "driver")).json()["data"][0]["text"] is None

    # N8/N9 operator queue
    fake_consumers.STATE["fail"] = True
    event_id = enqueue_user_event(bw.db, bw.w.client_id)
    dispatch_all(bw.db)
    failed = comms_client.get("/api/v2/admin/outbox?state=failed", headers=auth(bw.operator_id, "operator"))
    assert failed.status_code == 200
    from app.contracts.ids import PublicIdPrefix, format_public_id

    target = [e for e in failed.json()["data"] if e["id"] == format_public_id(PublicIdPrefix.EVENT, event_id) and e["attempts"] == 1]
    assert target
    assert comms_client.get("/api/v2/admin/outbox?state=failed", headers=auth(bw.w.client_id, "client")).status_code == 403
    retry = comms_client.post(f"/api/v2/admin/outbox/{target[0]['id']}/retry", json={"reason": "qayta urinish"},
                              headers=auth(bw.operator_id, "operator", _key()))
    assert retry.status_code == 200, retry.text
    assert retry.json()["data"]["attempts"] == 0
    again = comms_client.post(f"/api/v2/admin/outbox/{target[0]['id']}/retry", json={"reason": "qayta urinish"},
                              headers=auth(bw.operator_id, "operator", _key()))
    assert again.status_code == 409 and again.json()["error"]["code"] == ErrorCode.INVALID_STATE_TRANSITION.value
