"""K8 WebSocket (AC31, AC34): same auth and scope as REST, state read from PostgreSQL on every push.

Protocol (JSON text frames):

* client -> ``{"action": "subscribe", "booking_id": "bkg_...", "access_token": "<JWT>"}`` (participant / staff; the
  ``Authorization: Bearer`` header is accepted instead of ``access_token``) or
  ``{"action": "subscribe", "tracking_token": "<recipient link token>"}``. Sent within ``SUBSCRIBE_TIMEOUT_SECONDS``.
* server -> ``{"type": "tracking.point", "booking_id"?: ..., "data": BookingTrackingDTO | PublicTrackingDTO}`` every
  ``PUSH_INTERVAL_SECONDS`` (= ``tracking.WS_PUSH_INTERVAL_SECONDS``); additionally ``{"type": "tracking.stale", ...}``
  when freshness turns ``lost``/``no_data``.
* close codes: ``4401`` missing/invalid auth **or a revoked login session** (§17.6), ``4403`` window closed (or
  not open), ``4404`` unknown booking, token, revoked or expired link.

Every push opens a short DB session (no connection is held between pushes) and re-checks the window/grant, so the
endpoint is correct with several uvicorn workers and without Redis (no in-memory fan-out).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.contracts import tracking as contract
from app.contracts.enums import TrackingFreshness
from app.contracts.errors import DomainError, ErrorCode

PUSH_INTERVAL_SECONDS: float = float(contract.WS_PUSH_INTERVAL_SECONDS)
SUBSCRIBE_TIMEOUT_SECONDS: float = 10.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_WINDOW_CLOSED = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_SERVER_ERROR = 1011
MAX_TOKEN_LENGTH = 4096


def get_session_factory() -> Callable[[], Session]:
    """Dependency (tests override it): a factory of short-lived sessions."""
    from app.db.session import SessionLocal

    return SessionLocal


@dataclass(frozen=True, slots=True)
class Subscription:
    booking_id: str | None = None
    access_token: str | None = None
    tracking_token: str | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    close_code: int | None = None
    message: dict[str, Any] | None = None
    freshness: TrackingFreshness | None = None


def parse_subscription(message: Any, authorization: str | None) -> Subscription | None:
    if not isinstance(message, dict) or message.get("action") != "subscribe":
        return None
    tracking_token = message.get("tracking_token")
    if isinstance(tracking_token, str) and tracking_token:
        return Subscription(tracking_token=tracking_token[:MAX_TOKEN_LENGTH])
    booking_id = message.get("booking_id")
    access_token = message.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        scheme, _, credentials = (authorization or "").partition(" ")
        access_token = credentials.strip() if scheme.lower() == "bearer" else None
    if not isinstance(booking_id, str) or not booking_id or not access_token:
        return None
    return Subscription(booking_id=booking_id, access_token=access_token[:MAX_TOKEN_LENGTH])


def _authenticated_user_id(session: Session, access_token: str) -> int | None:
    from app.core.security import verify_token
    from app.models import User
    from app.services.auth_service import session_revoked

    payload = verify_token(access_token)
    if not payload or payload.get("type") != "access" or payload.get("sub") is None:
        return None
    # §17.6: a revoked login session closes the real-time channel too, not only the next REST call. Checked on
    # every push (this function runs per push), so a logout takes effect within one push interval.
    if session_revoked(session, payload):
        return None
    try:
        user = session.get(User, int(payload["sub"]))
    except (TypeError, ValueError):
        return None
    if user is None or user.status != "active":
        return None
    return user.id


def take_snapshot(factory: Callable[[], Session], subscription: Subscription, *, first: bool) -> Snapshot:
    """One push: authenticate, re-check scope/window, build the DTO (runs in a worker thread)."""
    from app.modules.tracking import service as tracking_service

    with factory() as session:
        try:
            if subscription.tracking_token is not None:
                state = tracking_service.public_tracking_state(session, token=subscription.tracking_token)
                session.rollback()
                if not state.grant_valid:
                    return Snapshot(CLOSE_NOT_FOUND)
                if state.dto is None:
                    return Snapshot(CLOSE_WINDOW_CLOSED)
                return Snapshot(message={"type": "tracking.point", "data": state.dto.model_dump(mode="json")},
                                freshness=state.dto.freshness)
            user_id = _authenticated_user_id(session, subscription.access_token or "")
            if user_id is None:
                session.rollback()
                return Snapshot(CLOSE_UNAUTHORIZED)
            dto = tracking_service.booking_tracking(
                session, booking_public_id_value=subscription.booking_id or "", viewer_user_id=user_id, audit=first
            )
            session.commit()  # staff audit row on the first push only
            return Snapshot(message={"type": "tracking.point", "booking_id": dto.booking_id, "data": dto.model_dump(mode="json")},
                            freshness=dto.freshness)
        except DomainError as exc:
            session.rollback()
            if exc.code is ErrorCode.NOT_FOUND:
                return Snapshot(CLOSE_NOT_FOUND)
            if exc.code in (ErrorCode.TRACKING_WINDOW_NOT_OPEN, ErrorCode.FORBIDDEN):
                return Snapshot(CLOSE_WINDOW_CLOSED)
            return Snapshot(CLOSE_SERVER_ERROR)


async def tracking_websocket(websocket: WebSocket, factory: Callable[[], Session] = Depends(get_session_factory)) -> None:
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=SUBSCRIBE_TIMEOUT_SECONDS)
    except WebSocketDisconnect:
        return
    except (asyncio.TimeoutError, ValueError, KeyError, RuntimeError):
        await _close(websocket, CLOSE_UNAUTHORIZED)
        return
    subscription = parse_subscription(raw, websocket.headers.get("authorization"))
    if subscription is None:
        await _close(websocket, CLOSE_UNAUTHORIZED)
        return
    first = True
    previous: TrackingFreshness | None = None
    try:
        while True:
            snapshot = await run_in_threadpool(take_snapshot, factory, subscription, first=first)
            if snapshot.close_code is not None:
                await _close(websocket, snapshot.close_code)
                return
            await websocket.send_json(snapshot.message)
            stale = (TrackingFreshness.LOST, TrackingFreshness.NO_DATA)
            if snapshot.freshness in stale and previous not in stale and not first:
                await websocket.send_json({"type": "tracking.stale", "data": {"freshness": snapshot.freshness.value}})
            previous = snapshot.freshness
            first = False
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=PUSH_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        return


async def _close(websocket: WebSocket, code: int) -> None:
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close(code=code)
