"""Communications domain API (A7, wave 3): chat (N6, N7, N10, N11), outbox dispatch (ADR-0012), in-app inbox
(N1, N4, N5), push devices (N2, N3) and push delivery bookkeeping.

Public functions take the caller's session and never commit (AGENTS §4); the API layer / worker commits.
No function here calls an external API: push sending happens in ``communications.jobs`` outside transactions.

Privacy (Q16, Q43-Q45, Q65): chat text is stored only masked (``contact_filter.scan(..., mask_proof_codes=True)``);
DTOs carry an author side, never a user id/name/phone; every delivered copy is ``events.payload_for_audience``;
push payloads carry only ``PUSH_PAYLOAD_KEYS``.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.contracts import contact_filter
from app.contracts.communications import (
    CHAT_ATTACHMENTS_ENABLED,
    CHAT_MASK_PROOF_CODES,
    CHAT_MAX_MESSAGES_PER_MINUTE,
    CHAT_WRITABLE_AFTER_TERMINAL,
    NOTIFICATION_DEDUP_WINDOW,
    NOTIFICATION_DELIVERY_LEASE,
    OUTBOX_BATCH_LIMIT,
    ChatActivitySummary,
    DispatchedEvent,
    chat_writable,
    outbox_retry_delay,
)
from app.contracts.crypto import secret_token_hash
from app.contracts.dto import ChatMessageCreate
from app.contracts.enums import (
    ActorSide,
    Capability,
    ChatModerationStatus,
    ChatThreadKind,
    EventType,
    NotificationChannel,
    NotificationDeliveryStatus,
)
from app.contracts.errors import DomainError, ErrorCode, WarningCode
from app.contracts.events import EVENT_AUDIENCES, EventAudience, EventEnvelope, payload_for_audience
from app.contracts.ids import PublicIdPrefix, format_public_id, parse_public_id
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.models.audit_log import AuditLog
from app.modules.communications import dispatch as dispatch_registry
from app.modules.communications.models import (
    ChatMessage,
    ChatThread,
    DeviceAccountLink,
    DeviceToken,
    NotificationDedup,
    NotificationDelivery,
)
from app.modules.communications.providers import PushMessage, PushProvider, PushResult, push_payload
from app.modules.communications.recipients import resolve_recipients
from app.modules.platform import outbox_dispatch
from app.modules.platform.models import OutboxEvent
from app.modules.platform.service import enqueue_event

logger = logging.getLogger(__name__)

RATE_WINDOW = timedelta(minutes=1)
CHAT_FILTER_FIELD = "text"
STAFF_ONLY = frozenset({EventAudience.STAFF})
STAFF_EVENT_TYPES: tuple[str, ...] = tuple(
    sorted(event_type.value for event_type, audiences in EVENT_AUDIENCES.items() if EventAudience.STAFF in audiences)
)


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def thread_public_id(thread: ChatThread) -> str:
    return format_public_id(PublicIdPrefix.CHAT_THREAD, thread.public_id)


def message_public_id(message: ChatMessage) -> str:
    return format_public_id(PublicIdPrefix.CHAT_MESSAGE, message.public_id)


def device_public_id(device: DeviceToken) -> str:
    return format_public_id(PublicIdPrefix.DEVICE, device.public_id)


def notification_public_id(delivery: NotificationDelivery) -> str:
    return format_public_id(PublicIdPrefix.NOTIFICATION, delivery.public_id)


def event_public_id(event_id: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.EVENT, event_id)


def _audit(session: Session, actor_user_id: int, entity_type: str, entity_id: int | None, action: str, details: dict) -> None:
    session.add(AuditLog(actor_id=actor_user_id, entity_type=entity_type, entity_id=entity_id, action=action, details=details))


def _require(session: Session, user_id: int, capability: Capability) -> None:
    from app.modules.identity import service as identity_service

    identity_service.require_capability(identity_service.get_capabilities(session, user_id), capability)


# --- chat: parents ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatParent:
    kind: ChatThreadKind
    parent_id: int
    parent_public_id: str
    client_user_id: int
    driver_user_id: int
    proposal_thread_open: bool | None = None
    booking_terminal_at: datetime | None = None

    def side_of(self, user_id: int) -> ActorSide | None:
        if user_id == self.client_user_id:
            return ActorSide.CLIENT
        if user_id == self.driver_user_id:
            return ActorSide.DRIVER
        return None


def _proposal_parent(session: Session, thread_public_id_value: str, *, lock: bool = False) -> ChatParent:
    from app.modules.marketplace import service as marketplace_service
    from app.modules.marketplace.models import ProposalThread

    thread = marketplace_service.get_thread_by_public_id(session, thread_public_id_value)
    if lock:
        # proposal_threads group of the lock order (ADR-0017); FOR SHARE: accept/close waits for the post, not vice versa.
        thread = session.execute(
            select(ProposalThread).where(ProposalThread.id == thread.id).with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).scalar_one()
    return ChatParent(
        ChatThreadKind.PROPOSAL, thread.id, marketplace_service.thread_public_id(thread), thread.client_user_id,
        thread.driver_user_id, proposal_thread_open=thread.state == "open",
    )


def _booking_parent(session: Session, booking_public_id_value: str) -> ChatParent:
    from app.modules.bookings import service as bookings_service
    from app.modules.bookings.rules import TERMINAL_SERVICE_STATUSES

    booking = bookings_service.get_booking_by_public_id(session, booking_public_id_value)
    terminal_at = booking.service_terminal_at
    if terminal_at is None and booking.service_status in TERMINAL_SERVICE_STATUSES:
        terminal_at = booking.updated_at
    return ChatParent(
        ChatThreadKind.BOOKING, booking.id, bookings_service.booking_public_id(booking), booking.client_user_id,
        booking.driver_user_id, booking_terminal_at=terminal_at,
    )


def _parent(session: Session, kind: ChatThreadKind | str, parent_public_id: str, *, lock: bool = False) -> ChatParent:
    kind = ChatThreadKind(kind)
    if kind is ChatThreadKind.PROPOSAL:
        return _proposal_parent(session, parent_public_id, lock=lock)
    return _booking_parent(session, parent_public_id)


def _party_parent(session: Session, kind: ChatThreadKind | str, parent_public_id: str, user_id: int, *, lock: bool = False) -> tuple[ChatParent, ActorSide]:
    parent = _parent(session, kind, parent_public_id, lock=lock)
    side = parent.side_of(user_id)
    if side is None:
        raise DomainError(ErrorCode.NOT_FOUND)  # staff use N10; others must not learn the chat exists
    return parent, side


def _thread_filter(parent: ChatParent):  # noqa: ANN202 - SQL expression
    if parent.kind is ChatThreadKind.PROPOSAL:
        return ChatThread.proposal_thread_id == parent.parent_id
    return ChatThread.booking_id == parent.parent_id


def _find_thread(session: Session, parent: ChatParent) -> ChatThread | None:
    return session.execute(select(ChatThread).where(_thread_filter(parent))).scalar_one_or_none()


def _lock_or_create_thread(session: Session, parent: ChatParent, now: datetime) -> ChatThread:
    column = "proposal_thread_id" if parent.kind is ChatThreadKind.PROPOSAL else "booking_id"
    session.execute(
        pg_insert(ChatThread)
        .values(public_id=uuid.uuid4(), kind=parent.kind.value, created_at=now, **{column: parent.parent_id})
        .on_conflict_do_nothing(index_elements=[column])
    )
    # Serialises posts per thread (rate limit, counters); FK inserts of messages only take KEY SHARE.
    return session.execute(
        select(ChatThread).where(_thread_filter(parent)).with_for_update(key_share=True).execution_options(populate_existing=True)
    ).scalar_one()


# --- chat: commands ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PostedMessage:
    message: ChatMessage
    thread: ChatThread
    side: ActorSide


def post_message(
    session: Session,
    *,
    kind: ChatThreadKind | str,
    parent_public_id: str,
    actor_user_id: int,
    data: ChatMessageCreate,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
    filter_hits: list | None = None,
) -> PostedMessage:
    """N7. Order: party (404) -> attachment (400) -> contact filter (hit recorded even if a 4xx follows, R2-b)
    -> writable (409 CHAT_CLOSED) -> rate limit (429) -> insert + ``chat.message.created``."""
    from app.modules.marketplace.service import ContactFilterHit, record_contact_filter_hits

    now = _now(now)
    parent, side = _party_parent(session, kind, parent_public_id, actor_user_id, lock=True)
    if data.attachment_file_id is not None and not CHAT_ATTACHMENTS_ENABLED:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR, details={"field": "attachment_file_id", "reason": "chat_attachments_not_available"}
        )

    text_value = data.text or None
    categories: dict[str, int] = {}
    filter_version: str | None = None
    if text_value is not None:
        result = contact_filter.scan(text_value, mask_proof_codes=CHAT_MASK_PROOF_CODES)
        if result.has_contact:
            categories = dict(sorted(Counter(match.category.value for match in result.matches).items()))
            filter_version = result.filter_version
            hit = ContactFilterHit(
                actor_user_id=actor_user_id, field=f"chat.{CHAT_FILTER_FIELD}", subject_type="chat_message",
                categories=categories, match_count=len(result.matches), filter_version=result.filter_version,
            )
            if filter_hits is None:
                record_contact_filter_hits(session, [hit])
            else:
                filter_hits.append(hit)
            if warnings is not None:
                warnings.append({"code": WarningCode.CONTACT_INFO_MASKED.value, "field": CHAT_FILTER_FIELD, **result.warning_details()})
            text_value = result.masked_text

    if not chat_writable(
        kind=parent.kind, now=now, proposal_thread_open=parent.proposal_thread_open, booking_terminal_at=parent.booking_terminal_at
    ):
        raise DomainError(ErrorCode.CHAT_CLOSED, details={"thread_kind": parent.kind.value})

    thread = _lock_or_create_thread(session, parent, now)
    window_start = now - RATE_WINDOW
    recent = session.execute(
        select(func.count(ChatMessage.id), func.min(ChatMessage.created_at)).where(
            ChatMessage.thread_id == thread.id,
            ChatMessage.author_user_id == actor_user_id,
            ChatMessage.created_at > window_start,
        )
    ).one()
    if int(recent[0]) >= CHAT_MAX_MESSAGES_PER_MINUTE:
        oldest = ensure_aware_utc(recent[1]) if recent[1] is not None else now
        retry_after = max(1, int((oldest + RATE_WINDOW - now).total_seconds()) + 1)
        raise DomainError(
            ErrorCode.RATE_LIMITED, details={"limit": CHAT_MAX_MESSAGES_PER_MINUTE, "window_s": 60, "retry_after_s": retry_after}
        )

    message = ChatMessage(
        public_id=uuid.uuid4(),
        thread_id=thread.id,
        author_user_id=actor_user_id,
        author_side=side.value,
        text=text_value,
        quick_reply_code=None if data.quick_reply_code is None else data.quick_reply_code.value,
        attachment_file_id=None,
        contact_filter_categories=categories,
        contact_filter_version=filter_version,
        moderation_status=ChatModerationStatus.VISIBLE.value,
        created_at=now,
    )
    session.add(message)
    thread.message_count = int(thread.message_count or 0) + 1
    thread.last_message_at = now
    session.flush()
    enqueue_event(
        session,
        EventEnvelope(
            EventType.CHAT_MESSAGE_CREATED, "chat_thread", thread_public_id(thread), thread.message_count, now,
            {
                "thread_id": thread_public_id(thread),
                "thread_kind": parent.kind.value,
                "message_id": message_public_id(message),
                "author_side": side.value,
                "quick_reply": message.quick_reply_code,
            },
        ),
        aggregate_id=thread.id,
    )
    return PostedMessage(message, thread, side)


@dataclass(frozen=True, slots=True)
class ChatState:
    """Whether this participant may still write, and until when."""

    kind: ChatThreadKind
    writable: bool
    writable_until: datetime | None
    message_count: int


def chat_state(
    session: Session, kind: ChatThreadKind | str, parent_public_id: str, user_id: int, *,
    now: datetime | None = None,
) -> ChatState:
    """N6: the state the chat screen opens with. A non-participant gets 404, like the message list.

    Read-only on purpose - asking whether you may write must never be the thing that creates the thread.
    """
    now = _now(now)
    parent, _side = _party_parent(session, kind, parent_public_id, user_id)
    thread = _find_thread(session, parent)
    writable = chat_writable(
        kind=parent.kind, now=now, proposal_thread_open=parent.proposal_thread_open,
        booking_terminal_at=parent.booking_terminal_at,
    )
    # Only a terminal booking has a deadline; while the trip runs there is nothing to count down, and once
    # the deadline has passed `writable` already says so and a date in the past would only confuse.
    deadline = (
        parent.booking_terminal_at + CHAT_WRITABLE_AFTER_TERMINAL
        if parent.kind is ChatThreadKind.BOOKING and parent.booking_terminal_at is not None
        else None
    )
    return ChatState(
        kind=parent.kind,
        writable=writable,
        writable_until=deadline if writable else None,
        message_count=thread.message_count if thread is not None else 0,
    )


def _messages_page(session: Session, thread: ChatThread | None, *, before_id: int | None, limit: int) -> list[ChatMessage]:
    if thread is None:
        return []
    stmt = select(ChatMessage).where(ChatMessage.thread_id == thread.id)
    if before_id is not None:
        stmt = stmt.where(ChatMessage.id < before_id)
    return list(session.execute(stmt.order_by(ChatMessage.id.desc()).limit(limit)).scalars())


def list_messages(
    session: Session, *, kind: ChatThreadKind | str, parent_public_id: str, viewer_user_id: int, before_id: int | None, limit: int
) -> list[ChatMessage]:
    """N6: parties only, newest first."""
    parent, _side = _party_parent(session, kind, parent_public_id, viewer_user_id)
    return _messages_page(session, _find_thread(session, parent), before_id=before_id, limit=limit)


def list_messages_for_staff(
    session: Session, *, kind: ChatThreadKind | str, parent_public_id: str, actor_user_id: int, before_id: int | None, limit: int
) -> list[ChatMessage]:
    """N10: ``ops.view`` + audit ``chat_viewed`` (no message content in the audit row)."""
    _require(session, actor_user_id, Capability.OPS_VIEW)
    parent = _parent(session, kind, parent_public_id)
    thread = _find_thread(session, parent)
    messages = _messages_page(session, thread, before_id=before_id, limit=limit)
    _audit(
        session, actor_user_id, "chat_thread", None if thread is None else thread.id, "chat_viewed",
        {"thread_kind": parent.kind.value, "parent_id": parent.parent_public_id, "messages_returned": len(messages)},
    )
    session.flush()
    return messages


def hide_message(session: Session, *, message_public_id_value: str, actor_user_id: int, reason: str, now: datetime | None = None) -> ChatMessage:
    """N11: ``ops.trust_review``; content stays (immutable), parties see ``text = null``; audited with the reason."""
    now = _now(now)
    _require(session, actor_user_id, Capability.OPS_TRUST_REVIEW)
    value = parse_public_id(message_public_id_value, PublicIdPrefix.CHAT_MESSAGE)
    message = session.execute(
        select(ChatMessage).where(ChatMessage.public_id == value).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if message is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if message.moderation_status == ChatModerationStatus.HIDDEN_BY_STAFF.value:
        return message
    message.moderation_status = ChatModerationStatus.HIDDEN_BY_STAFF.value
    message.moderated_by = actor_user_id
    message.moderated_at = now
    _audit(session, actor_user_id, "chat_message", message.id, "chat_message_hidden",
           {"message_id": message_public_id(message), "reason": reason})
    session.flush()
    return message


def booking_chat_thread_public_id(session: Session, booking_id: int) -> str | None:
    """A4 export (wave 5): the public id of a booking's existing chat thread, or None - read-only, never creates.

    Until this was wired, ``BookingDTO.contact.chat_thread_id`` stayed null and a client could not tell an
    unopened chat from a missing one (wave 4d follow-up).
    """
    thread = session.execute(select(ChatThread).where(ChatThread.booking_id == booking_id)).scalar_one_or_none()
    return thread_public_id(thread) if thread is not None else None


def register_booking_hooks() -> None:
    """Integrator: call once at start-up (``app.api.v2.router.configure_v2_ports``). Idempotent."""
    from app.modules.bookings import service as bookings_service

    bookings_service.set_chat_thread_lookup(booking_chat_thread_public_id)


def chat_activity_for_booking(session: Session, booking_id: int) -> ChatActivitySummary:
    """A12 export (Q45): the booking chat + the chat of the booking's accepted proposal thread; counts/times only."""
    from app.modules.bookings.models import Booking
    from app.modules.marketplace.models import ProposalVersion

    thread_ids: list[int] = []
    booking = session.get(Booking, booking_id)
    if booking is None:
        return ChatActivitySummary(0, None, None, 0, None)
    proposal_thread_id = session.execute(
        select(ProposalVersion.thread_id).where(ProposalVersion.id == booking.accepted_proposal_version_id)
    ).scalar_one_or_none()
    conditions = [ChatThread.booking_id == booking_id]
    if proposal_thread_id is not None:
        conditions.append(ChatThread.proposal_thread_id == proposal_thread_id)
    thread_ids = list(session.execute(select(ChatThread.id).where(or_(*conditions))).scalars())
    if not thread_ids:
        return ChatActivitySummary(0, None, None, 0, None)
    count, first_at, last_at = session.execute(
        select(func.count(ChatMessage.id), func.min(ChatMessage.created_at), func.max(ChatMessage.created_at)).where(
            ChatMessage.thread_id.in_(thread_ids)
        )
    ).one()
    hit_count, last_hit_at = session.execute(
        select(func.count(ChatMessage.id), func.max(ChatMessage.created_at)).where(
            ChatMessage.thread_id.in_(thread_ids), ChatMessage.contact_filter_version.is_not(None)
        )
    ).one()
    return ChatActivitySummary(
        message_count=int(count or 0),
        first_message_at=first_at,
        last_message_at=last_at,
        contact_filter_hit_count=int(hit_count or 0),
        last_contact_filter_hit_at=last_hit_at,
    )


# --- outbox dispatch ----------------------------------------------------------------------------------------------------


def _dedup_window_start(moment: datetime) -> datetime:
    moment = ensure_aware_utc(moment)
    window = int(NOTIFICATION_DEDUP_WINDOW.total_seconds())
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp(epoch - epoch % window, tz=moment.tzinfo)


def _title_key(event_type: str) -> str:
    return f"notification.{event_type}.title"


def _body_key(event_type: str) -> str:
    return f"notification.{event_type}.body"


def _insert_delivery(session: Session, row: OutboxEvent, *, user_id: int, audience: EventAudience, channel: NotificationChannel,
                     status: NotificationDeliveryStatus, payload: dict, link: str | None, now: datetime,
                     skip_reason: str | None = None) -> bool:
    inserted = session.execute(
        pg_insert(NotificationDelivery)
        .values(
            public_id=uuid.uuid4(), event_id=row.event_id, event_type=row.event_type, aggregate_type=row.aggregate_type,
            aggregate_public_id=row.aggregate_public_id, aggregate_version=row.aggregate_version, occurred_at=row.occurred_at,
            user_id=user_id, audience=audience.value, channel=channel.value, status=status.value, payload=payload, link=link,
            skip_reason=skip_reason, attempts=0, next_attempt_at=now,
            sent_at=now if status is NotificationDeliveryStatus.SENT else None, created_at=now, updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "user_id", "channel"])
        .returning(NotificationDelivery.id)
    ).scalar_one_or_none()
    return inserted is not None


def _push_dedup_claimed(session: Session, row: OutboxEvent, user_id: int) -> bool:
    key = (row.dedup_key or f"{row.event_type}:{row.aggregate_public_id}")[:255]
    window_start = _dedup_window_start(row.occurred_at)
    session.execute(
        pg_insert(NotificationDedup)
        .values(user_id=user_id, dedup_key=key, window_start=window_start, event_id=row.event_id)
        .on_conflict_do_nothing(index_elements=["user_id", "dedup_key", "window_start"])
    )
    owner = session.execute(
        select(NotificationDedup.event_id).where(
            NotificationDedup.user_id == user_id, NotificationDedup.dedup_key == key, NotificationDedup.window_start == window_start
        )
    ).scalar_one()
    return owner == row.event_id


def _active_device_count(session: Session, user_id: int, provider: PushProvider) -> int:
    if not provider.platforms:
        return 0
    return int(session.execute(
        select(func.count(DeviceToken.id)).where(
            DeviceToken.user_id == user_id,
            DeviceToken.revoked_at.is_(None),
            DeviceToken.platform.in_(sorted(platform.value for platform in provider.platforms)),
        )
    ).scalar_one())


def _deliver(session: Session, row: OutboxEvent, event: DispatchedEvent, relevant: bool, provider: PushProvider, now: datetime) -> int:
    """In-app copy per recipient (+ push row when a provider is enabled and the user has a device)."""
    if EVENT_AUDIENCES[event.event_type] <= STAFF_ONLY:
        return 0
    created = 0
    for recipient in resolve_recipients(session, event):
        copy = payload_for_audience(event.event_type, dict(event.payload), recipient.audience)
        if copy is None:
            _insert_delivery(session, row, user_id=recipient.user_id, audience=recipient.audience, channel=NotificationChannel.IN_APP,
                             status=NotificationDeliveryStatus.SKIPPED, payload={}, link=None, now=now, skip_reason="audience")
            continue
        if not relevant:
            _insert_delivery(session, row, user_id=recipient.user_id, audience=recipient.audience, channel=NotificationChannel.IN_APP,
                             status=NotificationDeliveryStatus.SKIPPED, payload={}, link=None, now=now, skip_reason="not_relevant")
            continue
        if _insert_delivery(session, row, user_id=recipient.user_id, audience=recipient.audience, channel=NotificationChannel.IN_APP,
                            status=NotificationDeliveryStatus.SENT, payload=copy, link=recipient.link, now=now):
            created += 1
        if provider.enabled and _active_device_count(session, recipient.user_id, provider):
            fresh = _push_dedup_claimed(session, row, recipient.user_id)
            _insert_delivery(
                session, row, user_id=recipient.user_id, audience=recipient.audience, channel=NotificationChannel(provider.channel),
                status=NotificationDeliveryStatus.PENDING if fresh else NotificationDeliveryStatus.SKIPPED,
                payload=push_payload(event_type=row.event_type, aggregate_id=row.aggregate_public_id, title_key=_title_key(row.event_type)),
                link=recipient.link, now=now, skip_reason=None if fresh else "dedup",
            )
    return created


def dispatch_outbox(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """Worker ServiceJob (ADR-0012 §4, AC33): claim due events with ``FOR UPDATE SKIP LOCKED`` (at most
    ``OUTBOX_BATCH_LIMIT`` per call), run consumers with ``consumer_receipts`` and write per-user deliveries in one
    savepoint per event, then ``dispatched_at`` or backoff/dead-letter. DB only; never commits. Returns events handled.
    """
    from app.modules.communications.providers import get_push_provider

    now = _now(now)
    rows = outbox_dispatch.claim_due_events(session, now=now, limit=min(max(int(limit), 0), OUTBOX_BATCH_LIMIT))
    if not rows:
        return 0
    registry = dispatch_registry.load_registry()
    provider = get_push_provider()
    for row in rows:
        savepoint = session.begin_nested()
        try:
            event = outbox_dispatch.dispatched_event(row)
            dispatch_registry.run_consumers(session, registry, event, now=now)
            relevant = dispatch_registry.is_relevant(session, registry, event)
            _deliver(session, row, event, relevant, provider, now)
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001 - one bad event must not block the batch
            if savepoint.is_active:
                savepoint.rollback()
            outcome = outbox_dispatch.mark_failed(session, row, now=now, error=exc)
            logger.warning("outbox_dispatch_failed event_id=%s event_type=%s outcome=%s error=%s",
                           row.event_id, row.event_type, outcome, type(exc).__name__)
            continue
        outbox_dispatch.mark_dispatched(session, row, now=now)
    return len(rows)


# --- push delivery (claim / result; the send itself is in jobs.py) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PushClaim:
    delivery_id: int
    lease_until: datetime
    attempts: int
    message: PushMessage


def claim_push_deliveries(session: Session, *, provider: PushProvider, now: datetime | None = None, limit: int = 100) -> list[PushClaim]:
    """Lease due push deliveries of the provider's channel (``SKIP LOCKED``); re-check relevance and devices."""
    now = _now(now)
    if not provider.enabled:
        return []
    rows = list(session.execute(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.channel == NotificationChannel(provider.channel).value,
            NotificationDelivery.status.in_([NotificationDeliveryStatus.PENDING.value, NotificationDeliveryStatus.FAILED.value]),
            NotificationDelivery.next_attempt_at <= now,
            or_(NotificationDelivery.lease_until.is_(None), NotificationDelivery.lease_until < now),
        )
        .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalars())
    if not rows:
        return []
    registry = dispatch_registry.load_registry()
    events = outbox_dispatch.events_by_ids(session, [row.event_id for row in rows])
    claims: list[PushClaim] = []
    for row in rows:
        row.updated_at = now
        outbox_row = events.get(row.event_id)
        if outbox_row is not None:
            try:
                relevant = dispatch_registry.is_relevant(session, registry, outbox_dispatch.dispatched_event(outbox_row))
            except Exception:  # noqa: BLE001 - treat a broken check as a failed attempt below
                logger.exception("push_relevance_check_failed delivery_id=%s", row.id)
                relevant = True
            if not relevant:
                row.status, row.skip_reason, row.lease_until = NotificationDeliveryStatus.SKIPPED.value, "not_relevant", None
                continue
        devices = list(session.execute(
            select(DeviceToken).where(
                DeviceToken.user_id == row.user_id,
                DeviceToken.revoked_at.is_(None),
                DeviceToken.platform.in_(sorted(platform.value for platform in provider.platforms) or [""]),
            ).order_by(DeviceToken.id)
        ).scalars())
        if not devices:
            row.status, row.skip_reason, row.lease_until = NotificationDeliveryStatus.SKIPPED.value, "no_device", None
            continue
        row.attempts = int(row.attempts or 0) + 1
        row.lease_until = now + NOTIFICATION_DELIVERY_LEASE
        payload = {key: value for key, value in dict(row.payload).items()}
        claims.append(PushClaim(
            row.id, row.lease_until, row.attempts,
            PushMessage(notification_public_id(row), row.user_id, NotificationChannel(row.channel),
                        tuple(device_public_id(device) for device in devices), payload),
        ))
    session.flush()
    return claims


def record_push_result(session: Session, claim: PushClaim, result: PushResult, *, now: datetime | None = None) -> str | None:
    """Apply one send result if the lease is still ours; -> new status or ``None`` (lease lost)."""
    now = _now(now)
    row = session.execute(
        select(NotificationDelivery)
        .where(NotificationDelivery.id == claim.delivery_id, NotificationDelivery.lease_until == claim.lease_until)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        return None
    row.lease_until = None
    row.updated_at = now
    if result.ok:
        row.status, row.sent_at, row.last_error = NotificationDeliveryStatus.SENT.value, now, None
    else:
        row.last_error = (result.error or "push_failed")[:500]
        delay = outbox_retry_delay(max(1, int(row.attempts or 1)))
        if delay is None:
            row.status = NotificationDeliveryStatus.DEAD.value
        else:
            row.status, row.next_attempt_at = NotificationDeliveryStatus.FAILED.value, now + delay
    session.flush()
    return row.status


# --- inbox and events (N1, N4, N5) -----------------------------------------------------------------------------------------


def is_staff_viewer(session: Session, user_id: int) -> bool:
    from app.modules.identity import service as identity_service

    return identity_service.get_capabilities(session, user_id).has(Capability.OPS_VIEW)


def list_user_events(session: Session, *, user_id: int, after_id: int | None, limit: int) -> list[NotificationDelivery]:
    stmt = select(NotificationDelivery).where(
        NotificationDelivery.user_id == user_id,
        NotificationDelivery.channel == NotificationChannel.IN_APP.value,
        NotificationDelivery.status == NotificationDeliveryStatus.SENT.value,
    )
    if after_id is not None:
        stmt = stmt.where(NotificationDelivery.id > after_id)
    return list(session.execute(stmt.order_by(NotificationDelivery.id).limit(limit)).scalars())


def list_staff_events(session: Session, *, after_id: int | None, limit: int) -> list[OutboxEvent]:
    stmt = select(OutboxEvent).where(OutboxEvent.event_type.in_(STAFF_EVENT_TYPES))
    if after_id is not None:
        stmt = stmt.where(OutboxEvent.id > after_id)
    return list(session.execute(stmt.order_by(OutboxEvent.id).limit(limit)).scalars())


def staff_payload(row: OutboxEvent) -> dict:
    try:
        return payload_for_audience(EventType(row.event_type), dict(row.payload or {}), EventAudience.STAFF) or {}
    except ValueError:
        return {}


def list_notifications(session: Session, *, user_id: int, unread_only: bool, before_id: int | None, limit: int) -> list[NotificationDelivery]:
    stmt = select(NotificationDelivery).where(
        NotificationDelivery.user_id == user_id,
        NotificationDelivery.channel == NotificationChannel.IN_APP.value,
        NotificationDelivery.status == NotificationDeliveryStatus.SENT.value,
    )
    if unread_only:
        stmt = stmt.where(NotificationDelivery.read_at.is_(None))
    if before_id is not None:
        stmt = stmt.where(NotificationDelivery.id < before_id)
    return list(session.execute(stmt.order_by(NotificationDelivery.id.desc()).limit(limit)).scalars())


def mark_notification_read(session: Session, *, notification_public_id_value: str, user_id: int, now: datetime | None = None) -> NotificationDelivery:
    now = _now(now)
    value = parse_public_id(notification_public_id_value, PublicIdPrefix.NOTIFICATION)
    row = session.execute(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.public_id == value,
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.channel == NotificationChannel.IN_APP.value,
            NotificationDelivery.status == NotificationDeliveryStatus.SENT.value,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if row.read_at is None:
        row.read_at = now
        row.updated_at = now
        session.flush()
    return row


def notification_keys(row: NotificationDelivery) -> tuple[str, str]:
    return _title_key(row.event_type), _body_key(row.event_type)


# --- devices (N2, N3) --------------------------------------------------------------------------------------------------------


def register_device(session: Session, *, user_id: int, platform: str, token: str, app_version: str | None, now: datetime | None = None) -> DeviceToken:
    """Upsert by ``(platform, sha256(token))``: a token moving to another account is re-bound and un-revoked."""
    now = _now(now)
    token_hash = secret_token_hash(token)
    session.execute(
        pg_insert(DeviceToken)
        .values(public_id=uuid.uuid4(), user_id=user_id, platform=platform, token_hash=token_hash, app_version=app_version,
                created_at=now, last_seen_at=now)
        .on_conflict_do_nothing(index_elements=["platform", "token_hash"])
    )
    device = session.execute(
        select(DeviceToken).where(DeviceToken.platform == platform, DeviceToken.token_hash == token_hash)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    if device.user_id != user_id or device.revoked_at is not None:
        device.user_id = user_id
        device.revoked_at = None
        device.public_id = uuid.uuid4()  # a new owner never learns the previous owner's device id
        device.created_at = now
    device.app_version = app_version
    device.last_seen_at = now
    # §17.3: keep the account <-> device history the re-bind above would otherwise erase. This is a *signal
    # source* for human review (A12), not an authorisation fact: nothing here blocks anyone.
    session.execute(
        pg_insert(DeviceAccountLink)
        .values(platform=platform, token_hash=token_hash, user_id=user_id, first_seen_at=now, last_seen_at=now)
        .on_conflict_do_update(
            index_elements=["platform", "token_hash", "user_id"], set_={"last_seen_at": now}
        )
    )
    session.flush()
    return device


def device_account_groups(
    session: Session, *, min_accounts: int = 2, since: datetime | None = None, limit: int = 200
) -> list[list[int]]:
    """A12 export (§17.3): user ids that have shared one push device. Read-only; no token leaves this module."""
    stmt = select(DeviceAccountLink.platform, DeviceAccountLink.token_hash,
                  func.array_agg(aggregate_order_by(DeviceAccountLink.user_id, DeviceAccountLink.user_id)))
    if since is not None:
        stmt = stmt.where(DeviceAccountLink.last_seen_at >= since)
    stmt = (
        stmt.group_by(DeviceAccountLink.platform, DeviceAccountLink.token_hash)
        .having(func.count(func.distinct(DeviceAccountLink.user_id)) >= max(2, min_accounts))
        .limit(limit)
    )
    groups: list[list[int]] = []
    for _platform, _token_hash, user_ids in session.execute(stmt).all():
        groups.append(sorted({int(value) for value in user_ids}))
    return groups


def revoke_device(session: Session, *, device_public_id_value: str, user_id: int, now: datetime | None = None) -> None:
    now = _now(now)
    value = parse_public_id(device_public_id_value, PublicIdPrefix.DEVICE)
    device = session.execute(
        select(DeviceToken).where(DeviceToken.public_id == value, DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if device is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    device.revoked_at = now
    session.flush()


# --- operator outbox queue (N8, N9) ----------------------------------------------------------------------------------------


def list_outbox_for_staff(session: Session, *, actor_user_id: int, state: str, after_id: int | None, limit: int) -> list[OutboxEvent]:
    _require(session, actor_user_id, Capability.OPS_VIEW)
    return outbox_dispatch.list_outbox_events(session, state=state, after_id=after_id, limit=limit)


def retry_outbox_event(session: Session, *, event_public_id_value: str, actor_user_id: int, reason: str, now: datetime | None = None) -> OutboxEvent:
    now = _now(now)
    _require(session, actor_user_id, Capability.OPS_BOOKING_COMMAND)
    event_id = parse_public_id(event_public_id_value, PublicIdPrefix.EVENT)
    retry = outbox_dispatch.retry_outbox_event(session, event_id, now=now)
    _audit(session, actor_user_id, "outbox_event", retry.event.id, "outbox_event_retry", {
        "event_id": event_public_id_value, "event_type": retry.event.event_type, "previous_attempts": retry.previous_attempts,
        "was_dead_lettered": retry.was_dead, "reason": reason,
    })
    session.flush()
    return retry.event


def messages_by_ids(session: Session, ids: Sequence[int]) -> dict[int, ChatMessage]:
    if not ids:
        return {}
    return {row.id: row for row in session.execute(select(ChatMessage).where(ChatMessage.id.in_(list(ids)))).scalars()}
