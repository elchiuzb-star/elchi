"""API v2 communications router (API_V2_CONTRACT §11, N1-N11). Mounted by the integrator under ``/api/v2``."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v2.web import (
    ERROR_RESPONSES,
    current_user_id,
    decode_id_cursor,
    encode_page_cursor,
    get_session,
    page_scope,
    run_command,
    run_versioned,
)
from app.contracts.dto import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    ChatMessageCreate,
    ChatMessageDTO,
    ChatThreadDTO,
    Envelope,
    EventDTO,
    PageMeta,
)
from app.contracts.enums import ActorSide, ChatModerationStatus, ChatThreadKind, ClientPlatform, QuickReplyCode
from app.modules.communications import service
from app.modules.communications.models import ChatMessage, DeviceToken, NotificationDelivery
from app.modules.communications.schemas import (
    ChatHideRequest,
    ChatMessageAdminDTO,
    DeviceDTO,
    NotificationDTO,
    OutboxEventAdminDTO,
    OutboxRetryRequest,
    PushTokenRegister,
)
from app.modules.platform.models import OutboxEvent

router = APIRouter(tags=["v2 Communications"])
logger = logging.getLogger(__name__)

_FILTER_HITS: ContextVar[list | None] = ContextVar("communications_filter_hits", default=None)
LIMIT = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)


def _recording_hits(session: Session, runner, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
    """R2-b (marketplace precedent): contact-filter hits are committed separately after the command, whatever its
    outcome, so a domain 4xx rolling back the command savepoint cannot erase the Q45 signal. Replays record nothing."""
    from app.modules.marketplace.service import record_contact_filter_hits

    hits: list = []
    token = _FILTER_HITS.set(hits)
    try:
        return runner(*args, **kwargs)
    finally:
        _FILTER_HITS.reset(token)
        if hits:
            try:
                record_contact_filter_hits(session, hits)
                session.commit()
            except Exception:  # never mask the command's own outcome
                session.rollback()
                logger.exception("recording chat contact filter hits failed")


def _with_warnings(build):  # noqa: ANN001, ANN202
    hits = _FILTER_HITS.get()
    if hits is not None:
        hits.clear()  # a deadlock retry re-runs the handler: keep only this attempt's hits
    warnings: list[dict] = []
    dto = build(warnings)
    return dto, warnings


# --- DTO builders ---------------------------------------------------------------------------------------------------


def message_dto(message: ChatMessage, viewer_user_id: int) -> ChatMessageDTO:
    hidden = message.moderation_status == ChatModerationStatus.HIDDEN_BY_STAFF.value
    return ChatMessageDTO(
        id=service.message_public_id(message),
        author_side=ActorSide(message.author_side),
        is_mine=message.author_user_id == viewer_user_id,
        text=None if hidden else message.text,
        quick_reply_code=None if hidden or message.quick_reply_code is None else QuickReplyCode(message.quick_reply_code),
        moderation_status=ChatModerationStatus(message.moderation_status),
        created_at=message.created_at,
    )


def admin_message_dto(session: Session, message: ChatMessage) -> ChatMessageAdminDTO:
    from app.modules.identity import service as identity_service

    return ChatMessageAdminDTO(
        id=service.message_public_id(message),
        author_side=ActorSide(message.author_side),
        author_user_id=identity_service.user_public_id(session, message.author_user_id),
        text=message.text,
        quick_reply_code=None if message.quick_reply_code is None else QuickReplyCode(message.quick_reply_code),
        contact_filter_categories={str(k): int(v) for k, v in dict(message.contact_filter_categories or {}).items()},
        moderation_status=ChatModerationStatus(message.moderation_status),
        moderated_at=message.moderated_at,
        created_at=message.created_at,
    )


def notification_dto(row: NotificationDelivery) -> NotificationDTO:
    title_key, body_key = service.notification_keys(row)
    return NotificationDTO(
        id=service.notification_public_id(row), type=row.event_type, title_key=title_key, body_key=body_key,
        params=dict(row.payload or {}), is_read=row.read_at is not None, created_at=row.created_at, link=row.link,
    )


def device_dto(device: DeviceToken) -> DeviceDTO:
    return DeviceDTO(id=service.device_public_id(device), platform=ClientPlatform(device.platform), created_at=device.created_at)


def outbox_dto(row: OutboxEvent) -> OutboxEventAdminDTO:
    return OutboxEventAdminDTO(
        id=service.event_public_id(row.event_id), event_type=row.event_type, aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_public_id, aggregate_version=row.aggregate_version, occurred_at=row.occurred_at,
        payload=service.staff_payload(row), attempts=int(row.attempts or 0), next_attempt_at=row.next_attempt_at,
        dispatched_at=row.dispatched_at, dead_lettered_at=row.dead_lettered_at, last_error=row.last_error,
    )


def _page(items: list, limit: int, scope: str) -> tuple[list, PageMeta]:
    page, more = items[:limit], len(items) > limit
    return page, PageMeta(next_cursor=encode_page_cursor([page[-1].id], scope) if more else None, limit=limit)


# --- N1 events ------------------------------------------------------------------------------------------------------------


@router.get("/events", response_model=Envelope[list[EventDTO]], responses=ERROR_RESPONSES)
def list_events(
    after: str | None = Query(default=None),
    limit: int = LIMIT,
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[EventDTO]]:
    if service.is_staff_viewer(session, user_id):
        scope = page_scope("events", audience="staff")
        rows = service.list_staff_events(session, after_id=decode_id_cursor(after, scope), limit=limit + 1)
        page, meta = _page(rows, limit, scope)
        data = [
            EventDTO(id=service.event_public_id(row.event_id), event_type=row.event_type, aggregate_type=row.aggregate_type,
                     aggregate_id=row.aggregate_public_id, aggregate_version=row.aggregate_version, occurred_at=row.occurred_at,
                     payload=service.staff_payload(row))
            for row in page
        ]
        return Envelope[list[EventDTO]](data=data, meta=meta)
    scope = page_scope("events", user=user_id)
    rows = service.list_user_events(session, user_id=user_id, after_id=decode_id_cursor(after, scope), limit=limit + 1)
    page, meta = _page(rows, limit, scope)
    data = [
        EventDTO(id=service.event_public_id(row.event_id), event_type=row.event_type, aggregate_type=row.aggregate_type,
                 aggregate_id=row.aggregate_public_id, aggregate_version=row.aggregate_version, occurred_at=row.occurred_at,
                 payload=dict(row.payload or {}))
        for row in page
    ]
    return Envelope[list[EventDTO]](data=data, meta=meta)


# --- N2/N3 devices ----------------------------------------------------------------------------------------------------------


@router.post("/devices/push-token", response_model=Envelope[DeviceDTO], status_code=201, responses=ERROR_RESPONSES)
def register_push_token(
    body: PushTokenRegister,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
        handler=lambda: device_dto(service.register_device(
            session, user_id=user_id, platform=body.platform.value, token=body.token_or_subscription, app_version=body.app_version
        )),
        success_status=201, resource_type="device",
    )


@router.delete("/devices/{device_id}", response_model=Envelope[dict[str, Any]], responses=ERROR_RESPONSES)
def revoke_device(
    device_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[dict[str, Any]]:
    run_versioned(session, lambda: service.revoke_device(session, device_public_id_value=device_id, user_id=user_id))
    return Envelope[dict[str, Any]](data={})


# --- N4/N5 notifications ---------------------------------------------------------------------------------------------------


@router.get("/notifications", response_model=Envelope[list[NotificationDTO]], responses=ERROR_RESPONSES)
def list_notifications(
    unread: bool = Query(default=False),
    cursor: str | None = Query(default=None),
    limit: int = LIMIT,
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[NotificationDTO]]:
    scope = page_scope("notifications", user=user_id, unread=unread)
    rows = service.list_notifications(
        session, user_id=user_id, unread_only=unread, before_id=decode_id_cursor(cursor, scope), limit=limit + 1
    )
    page, meta = _page(rows, limit, scope)
    return Envelope[list[NotificationDTO]](data=[notification_dto(row) for row in page], meta=meta)


@router.post("/notifications/{notification_id}/read", response_model=Envelope[NotificationDTO], responses=ERROR_RESPONSES)
def read_notification(
    notification_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[NotificationDTO]:
    dto = run_versioned(
        session,
        lambda: notification_dto(service.mark_notification_read(session, notification_public_id_value=notification_id, user_id=user_id)),
    )
    return Envelope[NotificationDTO](data=dto)


# --- N6/N7 chat ---------------------------------------------------------------------------------------------------------------


def _list_chat(session: Session, kind: ChatThreadKind, parent_id: str, user_id: int, cursor: str | None, limit: int) -> Envelope[list[ChatMessageDTO]]:
    scope = page_scope("chat_messages", kind=kind.value, parent=parent_id)
    rows = service.list_messages(
        session, kind=kind, parent_public_id=parent_id, viewer_user_id=user_id, before_id=decode_id_cursor(cursor, scope), limit=limit + 1
    )
    page, meta = _page(rows, limit, scope)
    return Envelope[list[ChatMessageDTO]](data=[message_dto(row, user_id) for row in page], meta=meta)


def _post_chat(
    request: Request, session: Session, kind: ChatThreadKind, parent_id: str, body: ChatMessageCreate, user_id: int, idempotency_key: str | None
) -> JSONResponse:
    return _recording_hits(
        session,
        run_command,
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: _with_warnings(
            lambda warnings: message_dto(
                service.post_message(
                    session, kind=kind, parent_public_id=parent_id, actor_user_id=user_id, data=body,
                    warnings=warnings, filter_hits=_FILTER_HITS.get(),
                ).message,
                user_id,
            )
        ),
        success_status=201,
        resource_type="chat_message",
    )


@router.get("/proposals/{thread_id}/messages", response_model=Envelope[list[ChatMessageDTO]], responses=ERROR_RESPONSES)
def list_proposal_messages(
    thread_id: str, cursor: str | None = Query(default=None), limit: int = LIMIT,
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[ChatMessageDTO]]:
    return _list_chat(session, ChatThreadKind.PROPOSAL, thread_id, user_id, cursor, limit)


@router.get("/bookings/{booking_id}/messages", response_model=Envelope[list[ChatMessageDTO]], responses=ERROR_RESPONSES)
def list_booking_messages(
    booking_id: str, cursor: str | None = Query(default=None), limit: int = LIMIT,
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[ChatMessageDTO]]:
    return _list_chat(session, ChatThreadKind.BOOKING, booking_id, user_id, cursor, limit)


@router.get("/bookings/{booking_id}/chat", response_model=Envelope[ChatThreadDTO], responses=ERROR_RESPONSES)
def get_booking_chat_state(
    booking_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[ChatThreadDTO]:
    """N6: what the chat screen opens with, so a closed conversation is drawn as closed.

    The messages themselves come from the list route; this one answers only "may I still write, and until
    when" - the question the client previously had to guess by sending and reading the refusal.
    """
    state = service.chat_state(session, ChatThreadKind.BOOKING, booking_id, user_id)
    return Envelope[ChatThreadDTO](
        data=ChatThreadDTO(
            kind=state.kind, writable=state.writable, writable_until=state.writable_until,
            message_count=state.message_count,
        )
    )


@router.post("/proposals/{thread_id}/messages", response_model=Envelope[ChatMessageDTO], status_code=201, responses=ERROR_RESPONSES)
def post_proposal_message(
    thread_id: str, body: ChatMessageCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return _post_chat(request, session, ChatThreadKind.PROPOSAL, thread_id, body, user_id, idempotency_key)


@router.post("/bookings/{booking_id}/messages", response_model=Envelope[ChatMessageDTO], status_code=201, responses=ERROR_RESPONSES)
def post_booking_message(
    booking_id: str, body: ChatMessageCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return _post_chat(request, session, ChatThreadKind.BOOKING, booking_id, body, user_id, idempotency_key)


# --- N8/N9 operator outbox queue ------------------------------------------------------------------------------------------------


@router.get("/admin/outbox", response_model=Envelope[list[OutboxEventAdminDTO]], responses=ERROR_RESPONSES)
def list_outbox(
    state: str = Query(default="failed", pattern=r"^(failed|dead)$"),
    cursor: str | None = Query(default=None),
    limit: int = LIMIT,
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[OutboxEventAdminDTO]]:
    scope = page_scope("admin_outbox", state=state)
    rows = service.list_outbox_for_staff(
        session, actor_user_id=user_id, state=state, after_id=decode_id_cursor(cursor, scope), limit=limit + 1
    )
    page, meta = _page(rows, limit, scope)
    return Envelope[list[OutboxEventAdminDTO]](data=[outbox_dto(row) for row in page], meta=meta)


@router.post("/admin/outbox/{event_id}/retry", response_model=Envelope[OutboxEventAdminDTO], responses=ERROR_RESPONSES)
def retry_outbox(
    event_id: str, body: OutboxRetryRequest, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
        handler=lambda: outbox_dto(service.retry_outbox_event(session, event_public_id_value=event_id, actor_user_id=user_id, reason=body.reason)),
        resource_type="outbox_event",
    )


# --- N10/N11 staff chat --------------------------------------------------------------------------------------------------------


def _staff_chat(session: Session, kind: ChatThreadKind, parent_id: str, user_id: int, cursor: str | None, limit: int) -> Envelope[list[ChatMessageAdminDTO]]:
    scope = page_scope("admin_chat_messages", kind=kind.value, parent=parent_id)
    before_id = decode_id_cursor(cursor, scope)

    def handler() -> Envelope[list[ChatMessageAdminDTO]]:
        rows = service.list_messages_for_staff(
            session, kind=kind, parent_public_id=parent_id, actor_user_id=user_id, before_id=before_id, limit=limit + 1
        )
        page, meta = _page(rows, limit, scope)
        return Envelope[list[ChatMessageAdminDTO]](data=[admin_message_dto(session, row) for row in page], meta=meta)

    return run_versioned(session, handler)  # commits the chat_viewed audit row


@router.get("/admin/bookings/{booking_id}/messages", response_model=Envelope[list[ChatMessageAdminDTO]], responses=ERROR_RESPONSES)
def admin_booking_messages(
    booking_id: str, cursor: str | None = Query(default=None), limit: int = LIMIT,
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[ChatMessageAdminDTO]]:
    return _staff_chat(session, ChatThreadKind.BOOKING, booking_id, user_id, cursor, limit)


@router.get("/admin/proposals/{thread_id}/messages", response_model=Envelope[list[ChatMessageAdminDTO]], responses=ERROR_RESPONSES)
def admin_proposal_messages(
    thread_id: str, cursor: str | None = Query(default=None), limit: int = LIMIT,
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[ChatMessageAdminDTO]]:
    return _staff_chat(session, ChatThreadKind.PROPOSAL, thread_id, user_id, cursor, limit)


@router.post("/admin/chat/messages/{message_id}/hide", response_model=Envelope[ChatMessageAdminDTO], responses=ERROR_RESPONSES)
def hide_chat_message(
    message_id: str, body: ChatHideRequest, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
        handler=lambda: admin_message_dto(
            session, service.hide_message(session, message_public_id_value=message_id, actor_user_id=user_id, reason=body.reason)
        ),
        resource_type="chat_message",
    )
