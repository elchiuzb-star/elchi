"""K4-K9 on PostgreSQL: AC30, AC31, AC44, parcel window (U1 default), grants (hash only), WebSocket, staff audit."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.contracts.errors import ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.tracking import service as tracking_service
from app.modules.tracking import ws as ws_module
from tests.pg.tracking.conftest import (
    BW,
    act,
    auth,
    codes_for,
    domain_error,
    parcel_booking,
    passenger_booking,
    point,
    rows,
    run_trip_action,
    scalar,
    send,
    start_session,
)

pytestmark = pytest.mark.pg
PHONES = ("+998900000201", "+998900000202", "+998900000301", "+998977777777")


def _public(booking) -> str:  # noqa: ANN001
    from app.modules.bookings.service import booking_public_id

    return booking_public_id(booking)


def _no_personal_data(body: object) -> None:
    dumped = json.dumps(body)
    for phone in PHONES:
        assert phone not in dumped
    for key in ("phone", "full_name", "plate_number", "name"):
        assert f'"{key}"' not in dumped


def test_ac44_two_days_before_is_403_with_opens_at(client: TestClient, tw: BW) -> None:
    _, _, booking = passenger_booking(tw, "01K100AA", boarding=False)
    response = client.get(f"/api/v2/bookings/{_public(booking)}/tracking", headers=auth(tw.w.client_id, "client"))
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "TRACKING_WINDOW_NOT_OPEN" and error["details"]["reason"] == "not_yet_open"
    assert error["details"]["opens_at"].startswith((tw.base - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"))


def test_ac30_other_users_get_404_and_participant_dto_has_no_contacts(client: TestClient, tw: BW) -> None:
    _, trip_public, booking = passenger_booking(tw, "01K101AA")
    now = tw.base - timedelta(minutes=10)
    send(tw, start_session(tw, trip_public), [point(0, now, acc=150)], now=now)
    url = f"/api/v2/bookings/{_public(booking)}/tracking"
    assert client.get(url, headers=auth(tw.w.client2_id, "client")).status_code == 404
    assert client.get(url, headers=auth(tw.w.driver2_id, "driver")).status_code == 404
    act(tw, booking.id, tw.w.driver_id, "arrive_at_pickup", now=now + timedelta(minutes=1), observed_at=now + timedelta(minutes=1))
    with tw.db.session() as s:
        dto = tracking_service.booking_tracking(s, booking_public_id_value=_public(booking), viewer_user_id=tw.w.client_id,
                                                now=now + timedelta(minutes=2))
    body = dto.model_dump(mode="json")
    assert body["window"]["is_open"] and body["last_point"]["low_accuracy"] is True
    assert body["driver_arrived_at"] is not None and body["subject_label"] == "vehicle_carrying_your_booking"
    assert "gps_active" not in json.dumps(body)
    _no_personal_data(body)
    assert client.get("/api/v2/public/tracking/not-a-real-token").status_code == 404


def test_staff_view_is_audited_without_coordinates(client: TestClient, tw: BW) -> None:
    trip_id, trip_public, booking = passenger_booking(tw, "01K102AA", boarding=False)
    response = client.get(f"/api/v2/bookings/{_public(booking)}/tracking", headers=auth(tw.operator_id, "operator"))
    assert response.status_code == 200 and response.json()["data"]["window"]["is_open"] is False
    admin = client.get(f"/api/v2/admin/trips/{trip_public}/tracking", headers=auth(tw.operator_id, "operator"))
    assert admin.status_code == 200 and admin.json()["data"]["active_session"] is False
    assert admin.json()["data"]["freshness"] == "no_data"
    assert client.get(f"/api/v2/admin/trips/{trip_public}/tracking", headers=auth(tw.w.client_id, "client")).status_code == 403
    audits = rows(tw.db, "SELECT actor_id, details FROM audit_logs WHERE action = 'tracking_viewed' ORDER BY id")
    assert [a.actor_id for a in audits] == [tw.operator_id, tw.operator_id]
    assert {a.details["surface"] for a in audits} == {"booking_tracking", "admin_trip_tracking"}
    assert all("lat" not in json.dumps(a.details) for a in audits)


def test_parcel_window_opens_only_at_pickup(tw: BW) -> None:
    trip_id, trip_public, booking = parcel_booking(tw, "01K103AA")
    now = tw.base - timedelta(minutes=5)
    send(tw, start_session(tw, trip_public), [point(0, now)], now=now)
    err = domain_error(lambda: _view(tw, booking, now))
    assert err.code is ErrorCode.TRACKING_WINDOW_NOT_OPEN and err.details == {"reason": "parcel_not_picked_up"}
    act(tw, booking.id, tw.w.driver_id, "pick_up", code=codes_for(tw, booking.id, tw.w.client_id)["pickup_code"], now=tw.base)
    assert _view(tw, booking, tw.base + timedelta(seconds=5)).window.is_open


def test_l10_parcel_grant_before_pickup_is_valid_after_pickup(tw: BW) -> None:
    trip_id, trip_public, booking = parcel_booking(tw, "01K108AA")
    with tw.db.session() as s:
        grant, token = tracking_service.create_grant(s, actor_user_id=tw.w.client_id, booking_public_id_value=_public(booking),
                                                     scope="recipient_link", ttl_minutes=15, now=tw.base - timedelta(hours=10))
        assert grant.valid_from == booking.pickup_window_start and grant.valid_until == booking.pickup_window_start + timedelta(minutes=15)
        s.commit()
    send(tw, start_session(tw, trip_public), [point(0, tw.base - timedelta(seconds=5))], now=tw.base)
    act(tw, booking.id, tw.w.driver_id, "pick_up", code=codes_for(tw, booking.id, tw.w.client_id)["pickup_code"], now=tw.base)
    with tw.db.session() as s:
        state = tracking_service.public_tracking_state(s, token=token, now=tw.base + timedelta(minutes=5))
    assert state.grant_valid and state.dto is not None and state.dto.status_label == "parcel.picked_up"


def _view(bw: BW, booking, now):  # noqa: ANN001, ANN202
    with bw.db.session() as s:
        return tracking_service.booking_tracking(s, booking_public_id_value=_public(booking), viewer_user_id=bw.w.client_id, now=now)


def test_ac31_finished_booking_closes_rest_and_websocket(client: TestClient, tw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_module, "PUSH_INTERVAL_SECONDS", 0.05)
    trip_id, trip_public, booking = passenger_booking(tw, "01K104AA")
    act(tw, booking.id, tw.w.driver_id, "board", code=codes_for(tw, booking.id, tw.w.client_id)["boarding_code"], now=tw.base)
    sid = start_session(tw, trip_public)
    real_now = utc_now()
    send(tw, sid, [point(0, real_now - timedelta(seconds=3))], now=real_now)  # onboard: open regardless of the clock
    token = auth(tw.w.client_id, "client")["Authorization"].split(" ", 1)[1]
    with client.websocket_connect("/api/v2/ws") as socket:
        socket.send_json({"action": "subscribe", "booking_id": _public(booking), "access_token": token})
        first = socket.receive_json()
        assert first["type"] == "tracking.point" and first["data"]["freshness"] == "fresh"
        _no_personal_data(first)
        run_trip_action(tw, trip_id, tw.w.driver_id, "depart", now=tw.base + timedelta(minutes=5))
        act(tw, booking.id, tw.w.driver_id, "drop_off", now=tw.base + timedelta(hours=2))
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(50):
                socket.receive_json()
        assert closed.value.code == 4403
    response = client.get(f"/api/v2/bookings/{_public(booking)}/tracking", headers=auth(tw.w.client_id, "client"))
    assert response.status_code == 403 and response.json()["error"]["details"]["reason"] == "booking_finished"


def test_websocket_auth_and_unknown_codes(client: TestClient, tw: BW) -> None:
    with client.websocket_connect("/api/v2/ws") as socket:
        socket.send_json({"action": "subscribe", "booking_id": "bkg_x"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4401
    with client.websocket_connect("/api/v2/ws") as socket:
        socket.send_json({"action": "subscribe", "booking_id": "bkg_x", "access_token": "garbage"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4401
    with client.websocket_connect("/api/v2/ws") as socket:
        socket.send_json({"action": "subscribe", "tracking_token": "unknown-token"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4404
    token = auth(tw.w.client2_id, "client")["Authorization"].split(" ", 1)[1]
    _, _, booking = passenger_booking(tw, "01K105AA", boarding=False)
    with client.websocket_connect("/api/v2/ws") as socket:
        socket.send_json({"action": "subscribe", "booking_id": _public(booking), "access_token": token})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4404  # someone else's booking


def test_recipient_link_stores_only_hash_and_follows_revoke(client: TestClient, tw: BW, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_module, "PUSH_INTERVAL_SECONDS", 0.05)
    trip_id, trip_public, booking = passenger_booking(tw, "01K106AA")
    act(tw, booking.id, tw.w.driver_id, "board", code=codes_for(tw, booking.id, tw.w.client_id)["boarding_code"], now=tw.base)
    real_now = utc_now()
    send(tw, start_session(tw, trip_public), [point(0, real_now - timedelta(seconds=2))], now=real_now)
    url = f"/api/v2/bookings/{_public(booking)}/tracking-grants"
    headers = auth(tw.w.client_id, "client", key="grant-key-1")
    created = client.post(url, json={"scope": "recipient_link", "ttl_minutes": 60}, headers=headers)
    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == "no-store"
    link = created.json()["data"]["url"]
    token = link.rsplit("/", 1)[1]
    assert len(token) >= 43  # 32 random bytes, url-safe base64
    replay = client.post(url, json={"scope": "recipient_link", "ttl_minutes": 60}, headers=headers)
    assert replay.status_code == 201 and replay.json()["data"]["url"] is None
    everything = json.dumps([list(r) for r in rows(tw.db, "SELECT row_to_json(g)::text FROM tracking_grants g")]
                            + [list(r) for r in rows(tw.db, "SELECT response_body::text FROM idempotency_records")])
    assert token not in everything
    from app.contracts.crypto import secret_token_hash

    assert scalar(tw.db, "SELECT count(*) FROM tracking_grants WHERE token_hash = :h", h=secret_token_hash(token)) == 1

    public = client.get(link)
    assert public.status_code == 200, public.text
    assert public.headers["referrer-policy"] == "no-referrer" and public.headers["cache-control"] == "no-store"
    assert public.json()["data"]["status_label"] == "passenger.onboard"
    _no_personal_data(public.json())

    with client.websocket_connect("/api/v2/ws") as socket:
        socket.send_json({"action": "subscribe", "tracking_token": token})
        assert socket.receive_json()["type"] == "tracking.point"
        grant_id = created.json()["data"]["id"]
        assert client.delete(f"{url}/{grant_id}", headers=auth(tw.w.client_id, "client")).status_code == 200
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(50):
                socket.receive_json()
        assert closed.value.code == 4404
    missing = client.get(link)
    assert missing.status_code == 404 and missing.headers["referrer-policy"] == "no-referrer"
    assert client.delete(f"{url}/{grant_id}", headers=auth(tw.w.client_id, "client")).status_code == 200  # idempotent


def test_grant_rules(client: TestClient, tw: BW) -> None:
    _, _, booking = passenger_booking(tw, "01K107AA", boarding=False)
    url = f"/api/v2/bookings/{_public(booking)}/tracking-grants"
    body = {"scope": "recipient_link", "ttl_minutes": 60}
    assert client.post(url, json=body, headers=auth(tw.w.driver_id, "driver", key="grant-driver")).status_code == 403
    assert client.post(url, json=body, headers=auth(tw.w.client2_id, "client", key="grant-other")).status_code == 404
    too_long = client.post(url, json={"scope": "recipient_link", "ttl_minutes": 1441}, headers=auth(tw.w.client_id, "client", key="grant-long"))
    assert too_long.status_code == 400 and too_long.json()["error"]["details"]["max"] == 1440
    # two days early: the window opens more than TRACKING_GRANT_MAX_TTL ahead -> refused (BR L10)
    early = client.post(url, json=body, headers=auth(tw.w.client_id, "client", key="grant-early"))
    assert early.status_code == 400 and early.json()["error"]["details"]["reason"] == "grant_too_early"
    with tw.db.session() as s:  # 2 h before pickup: starts when the window opens, TTL counted from there
        grant, token = tracking_service.create_grant(s, actor_user_id=tw.w.client_id, booking_public_id_value=_public(booking),
                                                     scope="recipient_link", ttl_minutes=60, now=tw.base - timedelta(hours=2))
        assert grant.valid_from == tw.base - timedelta(minutes=30) and grant.valid_until == tw.base + timedelta(minutes=30)
        s.commit()
    assert client.get(f"/api/v2/public/tracking/{token}").status_code == 404  # real clock: not valid yet
    with tw.db.session() as s:
        before = tracking_service.public_tracking_state(s, token=token, now=tw.base - timedelta(minutes=31))
        assert not before.grant_valid  # the link starts with the window
        opened = tracking_service.public_tracking_state(s, token=token, now=tw.base - timedelta(minutes=29))
        assert opened.grant_valid and opened.window.is_open
        expired = tracking_service.public_tracking_state(s, token=token, now=tw.base + timedelta(minutes=31))
        assert not expired.grant_valid
