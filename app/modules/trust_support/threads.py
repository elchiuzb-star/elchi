"""Booking-bound operator chat (ADR-0026, Q141). Replaces the client/driver-facing dispute flow.

"Shikoyat qilish" on a booking opens - or returns - the requester's open thread for that booking. One open thread per
(booking, requester) is guaranteed by the database (partial unique index), so a repeated tap or a network retry lands
in the same conversation; the client and the driver of one booking have separate threads and never read each other's.

What a thread is **not**: opening, answering or closing it moves no money, releases or cancels no commission, grants or
removes no bonus and records no fraud verdict. When staff decide a financial outcome they use the existing authorised
commands (finance ``finalize_fee``, ledger adjustments, an internal staff dispute in ``disputes_v2``) - never a side
effect of the chat.

Honest status (spec §5.2, §16, Q87): the requester sees whether staff have seen the thread (``waiting`` /
``assigned`` / ``answered`` / ``closed``); nothing here promises a response time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.enums import ActorSide, Capability, EventType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import (
    PublicIdPrefix,
    format_public_id,
    new_public_uuid,
    parse_public_id,
)
from app.modules.bookings import service as bookings_service
from app.modules.identity import service as identity_service
from app.modules.marketplace.service import ContactFilterHit
from app.modules.trust_support.models import SupportMessage, SupportThread
from app.modules.trust_support.service import (
    _audit,
    _check_version,
    _emit,
    _now,
    _require,
    filter_free_text,
)

OPEN, CLOSED = "open", "closed"
MESSAGE_MAX_LENGTH = 4000  # DB CHECK ck_support_messages_text
# Q83 (chat pilot number): a person writes at most this many lines per window into one thread.
MESSAGE_RATE_LIMIT = 20
MESSAGE_RATE_WINDOW = timedelta(minutes=1)
OPEN_INDEX = "uq_support_threads_open"


def thread_public_id(thread: SupportThread) -> str:
    return format_public_id(PublicIdPrefix.SUPPORT_THREAD, thread.public_id)


def message_public_id(message: SupportMessage) -> str:
    return format_public_id(PublicIdPrefix.SUPPORT_MESSAGE, message.public_id)


@dataclass(frozen=True, slots=True)
class ThreadView:
    thread: SupportThread
    booking_public_id: str
    messages: list[SupportMessage]


def staff_status(thread: SupportThread) -> str:
    """What the requester is told - facts only, no promised time."""
    if thread.status == CLOSED:
        return "closed"
    if thread.last_staff_message_at is not None:
        return "answered"
    if thread.assigned_to is not None:
        return "assigned"
    return "waiting"


def _by_public_id(session: Session, value: str, *, lock: bool = False) -> SupportThread:
    uid = parse_public_id(value, PublicIdPrefix.SUPPORT_THREAD)
    stmt = select(SupportThread).where(SupportThread.public_id == uid)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    thread = session.execute(stmt).scalar_one_or_none()
    if thread is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return thread


def _open_thread_for(session: Session, booking_id: int, user_id: int, *, lock: bool) -> SupportThread | None:
    stmt = select(SupportThread).where(SupportThread.booking_id == booking_id, SupportThread.requester_user_id == user_id,
                                       SupportThread.status == OPEN)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return session.execute(stmt).scalar_one_or_none()


def _add_message(session: Session, thread: SupportThread, *, author_user_id: int | None, side: str, text_value: str,
                 filtered: bool, now: datetime) -> SupportMessage:
    message = SupportMessage(public_id=new_public_uuid(), thread_id=thread.id, author_user_id=author_user_id,
                             author_side=side, body=text_value, file_ids=[], filtered=filtered, created_at=now)
    session.add(message)
    thread.message_count += 1
    thread.last_message_at = now
    if side == ActorSide.OPERATOR.value:
        thread.last_staff_message_at = now
    thread.updated_at = now
    thread.version += 1
    session.flush()
    return message


def _clean(text_value: str | None) -> str | None:
    value = (text_value or "").strip()
    if not value:
        return None
    if len(value) > MESSAGE_MAX_LENGTH:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "text", "max_length": MESSAGE_MAX_LENGTH})
    return value


def _masked(session: Session, *, actor_user_id: int, value: str, warnings: list[dict] | None,
            filter_hits: list[ContactFilterHit] | None) -> tuple[str, bool]:
    before = len(warnings) if warnings is not None else 0
    masked = filter_free_text(session, actor_user_id=actor_user_id, field="text", subject_type="support_thread",
                              text_value=value, warnings=warnings, filter_hits=filter_hits) or value
    return masked, warnings is not None and len(warnings) > before


def open_or_get_thread(
    session: Session, *, booking_public_id_value: str, actor_user_id: int, text_value: str | None = None,
    warnings: list[dict] | None = None, filter_hits: list[ContactFilterHit] | None = None, now: datetime | None = None,
) -> tuple[SupportThread, bool]:
    """The complaint button. Returns ``(thread, created)``: the requester's open thread for this booking, or a new one.

    Only the booking's client or driver may open one (anyone else: 404, the booking's existence is not revealed).
    Lock: the requester's ``users`` row (ADR-0017 order) serialises two taps; the partial unique index is the last line.
    """
    now = _now(now)
    booking = bookings_service.get_booking_by_public_id(session, booking_public_id_value)
    side = bookings_service.participant_side(booking, actor_user_id)
    if side not in (ActorSide.CLIENT, ActorSide.DRIVER):
        raise DomainError(ErrorCode.NOT_FOUND)
    first = _clean(text_value)
    identity_service.lock_user_eligibility(session, [actor_user_id], mode="update")
    existing = _open_thread_for(session, booking.id, actor_user_id, lock=True)
    if existing is not None:
        if first is not None:
            post_message(session, thread_public_id_value=thread_public_id(existing), actor_user_id=actor_user_id,
                         text_value=first, warnings=warnings, filter_hits=filter_hits, now=now)
        return existing, False
    thread = SupportThread(public_id=new_public_uuid(), booking_id=booking.id, requester_user_id=actor_user_id,
                           requester_side=side.value, status=OPEN, message_count=0, created_at=now, updated_at=now, version=1)
    try:
        with session.begin_nested():
            session.add(thread)
            session.flush()
    except IntegrityError as exc:
        if OPEN_INDEX not in str(exc.orig):
            raise
        existing = _open_thread_for(session, booking.id, actor_user_id, lock=True)
        if existing is None:  # pragma: no cover - the index said it exists
            raise
        return existing, False
    if first is not None:
        masked, filtered = _masked(session, actor_user_id=actor_user_id, value=first, warnings=warnings, filter_hits=filter_hits)
        _add_message(session, thread, author_user_id=actor_user_id, side=side.value, text_value=masked, filtered=filtered, now=now)
    booking_pid = bookings_service.booking_public_id(booking)
    _emit(session, EventType.SUPPORT_THREAD_OPENED, aggregate_type="support_thread", aggregate_public_id=thread_public_id(thread),
          aggregate_version=thread.version, now=now, aggregate_id=thread.id,
          payload={"thread_id": thread_public_id(thread), "booking_id": booking_pid, "requester_side": side.value})
    _audit(session, actor_user_id=actor_user_id, entity_type="support_thread", action="support_thread_opened",
           details={"thread_id": thread_public_id(thread), "booking_id": booking_pid, "requester_side": side.value})
    return thread, True


def _own_thread(session: Session, thread_public_id_value: str, user_id: int, *, lock: bool = False) -> SupportThread:
    thread = _by_public_id(session, thread_public_id_value, lock=lock)
    if thread.requester_user_id != user_id:
        raise DomainError(ErrorCode.NOT_FOUND)  # the other party's (or anyone's) thread does not exist for this caller
    return thread


def post_message(
    session: Session, *, thread_public_id_value: str, actor_user_id: int, text_value: str,
    warnings: list[dict] | None = None, filter_hits: list[ContactFilterHit] | None = None, now: datetime | None = None,
) -> SupportMessage:
    """The requester writes into their own open thread (contact filter Q43; rate limit Q83)."""
    now = _now(now)
    value = _clean(text_value)
    if value is None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "text"})
    thread = _own_thread(session, thread_public_id_value, actor_user_id, lock=True)
    if thread.status != OPEN:
        raise DomainError(ErrorCode.SUPPORT_THREAD_CLOSED, details={"thread_id": thread_public_id(thread)})
    recent = int(session.execute(
        select(func.count(SupportMessage.id)).where(SupportMessage.thread_id == thread.id,
                                                    SupportMessage.author_user_id == actor_user_id,
                                                    SupportMessage.created_at >= now - MESSAGE_RATE_WINDOW)
    ).scalar_one())
    if recent >= MESSAGE_RATE_LIMIT:
        raise DomainError(ErrorCode.RATE_LIMITED, details={"limit": MESSAGE_RATE_LIMIT,
                                                           "window_s": int(MESSAGE_RATE_WINDOW.total_seconds())})
    masked, filtered = _masked(session, actor_user_id=actor_user_id, value=value, warnings=warnings, filter_hits=filter_hits)
    return _add_message(session, thread, author_user_id=actor_user_id, side=thread.requester_side, text_value=masked,
                        filtered=filtered, now=now)


def messages_of(session: Session, thread: SupportThread, *, include_staff_only: bool) -> list[SupportMessage]:
    """The thread's lines in order. The requester never receives a ``staff_only`` line (0093: the other participant's
    or staff evidence carried over from a dispute) - filtered here, in the query, not by the screen."""
    stmt = select(SupportMessage).where(SupportMessage.thread_id == thread.id)
    if not include_staff_only:
        stmt = stmt.where(SupportMessage.staff_only.is_(False))
    return list(session.execute(stmt.order_by(SupportMessage.id)).scalars())


def visible_message_counts(session: Session, thread_ids: list[int]) -> dict[int, int]:
    """How many lines each requester actually sees (``message_count`` on the row also counts staff-only lines)."""
    if not thread_ids:
        return {}
    rows = session.execute(
        select(SupportMessage.thread_id, func.count()).where(SupportMessage.thread_id.in_(thread_ids),
                                                             SupportMessage.staff_only.is_(False))
        .group_by(SupportMessage.thread_id)
    ).all()
    return {thread_id: int(count) for thread_id, count in rows}


def get_thread_for_user(session: Session, thread_public_id_value: str, user_id: int) -> ThreadView:
    thread = _own_thread(session, thread_public_id_value, user_id)
    return ThreadView(thread, _booking_pid(session, thread), messages_of(session, thread, include_staff_only=False))


def thread_for_booking(session: Session, booking_public_id_value: str, user_id: int) -> SupportThread | None:
    """The caller's open thread for this booking, if any (the button says "continue" instead of "open")."""
    booking = bookings_service.get_booking_by_public_id(session, booking_public_id_value)
    if bookings_service.participant_side(booking, user_id) not in (ActorSide.CLIENT, ActorSide.DRIVER):
        raise DomainError(ErrorCode.NOT_FOUND)
    return _open_thread_for(session, booking.id, user_id, lock=False)


def list_user_threads(session: Session, user_id: int, *, limit: int) -> list[SupportThread]:
    return list(session.execute(
        select(SupportThread).where(SupportThread.requester_user_id == user_id)
        .order_by(SupportThread.status.desc(), SupportThread.updated_at.desc(), SupportThread.id.desc()).limit(limit)
    ).scalars())


def _booking_pid(session: Session, thread: SupportThread) -> str:
    return bookings_service.booking_public_id(bookings_service.get_booking(session, thread.booking_id))


# --- staff ------------------------------------------------------------------------------------------------------------------


def admin_list_threads(session: Session, *, actor_user_id: int, status: str | None, assigned: str | None,
                       after_id: int | None, limit: int, now: datetime | None = None) -> list[SupportThread]:
    """The operator queue: open threads first-come; ``assigned`` = ``me`` / ``unassigned`` / ``None`` (any)."""
    _require(session, actor_user_id, Capability.OPS_VIEW, _now(now))
    stmt = select(SupportThread)
    if status is not None:
        stmt = stmt.where(SupportThread.status == status)
    if assigned == "me":
        stmt = stmt.where(SupportThread.assigned_to == actor_user_id)
    elif assigned == "unassigned":
        stmt = stmt.where(SupportThread.assigned_to.is_(None))
    if after_id is not None:
        stmt = stmt.where(SupportThread.id > after_id)
    return list(session.execute(stmt.order_by(SupportThread.id).limit(limit)).scalars())


def admin_get_thread(session: Session, *, thread_public_id_value: str, actor_user_id: int,
                     now: datetime | None = None) -> ThreadView:
    """Staff read (``ops.view``) - audited, like staff reading a booking chat (N10)."""
    _require(session, actor_user_id, Capability.OPS_VIEW, _now(now))
    thread = _by_public_id(session, thread_public_id_value)
    _audit(session, actor_user_id=actor_user_id, entity_type="support_thread", action="support_thread_viewed",
           details={"thread_id": thread_public_id(thread)})
    return ThreadView(thread, _booking_pid(session, thread), messages_of(session, thread, include_staff_only=True))


# --- staff access to evidence files (ADR-0026) -------------------------------------------------------------------------
#
# The chat never hands a raw storage key to anyone. Staff see a readable label and an opaque reference
# (``<message public id>.<n>``); opening one goes through ``staff_file_link``, which checks the capability and that the
# file belongs to *this* thread, audits the view and only then mints the existing short-lived signed URL
# (``app.utils.file_access.media_ref`` - the download endpoint verifies the signature and its expiry). Viewing a file
# changes no booking, money or bonus state. Requesters never get a reference or a link.

_SIDE_LABEL = {"client": "mijoz", "driver": "haydovchi", "operator": "xodim", "system": "tizim"}


@dataclass(frozen=True, slots=True)
class StaffFile:
    ref: str
    name: str
    message: SupportMessage


def staff_files(messages: list[SupportMessage]) -> list[StaffFile]:
    """Every file of the thread's lines as ``(ref, label)`` - the label says what it is, never where it is stored."""
    out: list[StaffFile] = []
    number = 0
    for message in messages:
        for index, stored in enumerate(message.file_ids or []):
            number += 1
            extension = (str(stored).rsplit(".", 1)[-1].split("?", 1)[0] if "." in str(stored) else "fayl").upper()[:5]
            when = message.created_at.strftime("%d.%m.%Y") if message.created_at else ""
            label = f"Dalil {number} - {_SIDE_LABEL.get(message.author_side, message.author_side)}, {when}, {extension}"
            out.append(StaffFile(ref=f"{message_public_id(message)}.{index}", name=label, message=message))
    return out


def staff_file_link(session: Session, *, thread_public_id_value: str, file_ref: str, actor_user_id: int,
                    now: datetime | None = None) -> tuple[str, dict[str, str]]:
    """``(label, media_ref)`` for one evidence file of this thread - ``ops.trust_review`` staff only, audited.

    404 for a reference that does not belong to this thread (another thread's file, a made-up index) - the same answer
    as for a thread that does not exist, so nothing is learned by probing."""
    from app.utils.file_access import media_ref

    now = _now(now)
    _require(session, actor_user_id, Capability.OPS_TRUST_REVIEW, now)
    thread = _by_public_id(session, thread_public_id_value)
    message_part, _, index_part = file_ref.rpartition(".")
    if not message_part or not index_part.isdigit():
        raise DomainError(ErrorCode.NOT_FOUND)
    try:
        message_uid = parse_public_id(message_part, PublicIdPrefix.SUPPORT_MESSAGE)
    except (ValueError, DomainError):
        raise DomainError(ErrorCode.NOT_FOUND) from None
    message = session.execute(select(SupportMessage).where(SupportMessage.public_id == message_uid,
                                                           SupportMessage.thread_id == thread.id)).scalar_one_or_none()
    index = int(index_part)
    if message is None or index >= len(message.file_ids or []):
        raise DomainError(ErrorCode.NOT_FOUND)
    link = media_ref(message.file_ids[index])
    if link is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    label = next(f.name for f in staff_files(messages_of(session, thread, include_staff_only=True)) if f.ref == file_ref)
    _audit(session, actor_user_id=actor_user_id, entity_type="support_thread", action="support_thread_file_viewed",
           details={"thread_id": thread_public_id(thread), "file_ref": file_ref, "staff_only": bool(message.staff_only)})
    return label, link


def _notify_requester(session: Session, thread: SupportThread, now: datetime) -> None:
    _emit(session, EventType.SUPPORT_THREAD_REPLIED, aggregate_type="user",
          aggregate_public_id=identity_service.user_public_id(session, thread.requester_user_id),
          aggregate_version=thread.version, now=now, aggregate_id=thread.requester_user_id,
          payload={"thread_id": thread_public_id(thread), "booking_id": _booking_pid(session, thread), "status": thread.status})


def staff_command(
    session: Session, *, thread_public_id_value: str, actor_user_id: int, command: str, expected_version: int,
    text_value: str | None = None, assignee_user_id: int | None = None, now: datetime | None = None,
) -> SupportThread:
    """``assign`` (to self by default), ``reply`` (a message to the requester), ``close`` (with an optional note).

    ``ops.trust_review`` for every command. None of them touches a booking, a wallet, a bonus or a strike.
    """
    now = _now(now)
    if command not in ("assign", "reply", "close"):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "command"})
    _require(session, actor_user_id, Capability.OPS_TRUST_REVIEW, now)
    thread = _by_public_id(session, thread_public_id_value, lock=True)
    _check_version(thread.version, expected_version)
    if thread.status != OPEN:
        raise DomainError(ErrorCode.SUPPORT_THREAD_CLOSED, details={"thread_id": thread_public_id(thread)})
    if command == "assign":
        target = assignee_user_id or actor_user_id
        if target != actor_user_id:
            _require(session, target, Capability.OPS_TRUST_REVIEW, now)  # only a staff member who can answer
        thread.assigned_to, thread.assigned_at = target, now
        thread.updated_at, thread.version = now, thread.version + 1
        session.flush()
    elif command == "reply":
        value = _clean(text_value)
        if value is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "text"})
        if thread.assigned_to is None:
            thread.assigned_to, thread.assigned_at = actor_user_id, now
        _add_message(session, thread, author_user_id=actor_user_id, side=ActorSide.OPERATOR.value, text_value=value,
                     filtered=False, now=now)
        _notify_requester(session, thread, now)
    else:
        note = _clean(text_value)
        if note is not None:
            _add_message(session, thread, author_user_id=actor_user_id, side=ActorSide.OPERATOR.value, text_value=note,
                         filtered=False, now=now)
        thread.status, thread.closed_by, thread.closed_at, thread.close_note = CLOSED, actor_user_id, now, note
        thread.updated_at, thread.version = now, thread.version + 1
        session.flush()
        _notify_requester(session, thread, now)
    _audit(session, actor_user_id=actor_user_id, entity_type="support_thread", action=f"support_thread_{command}",
           details={"thread_id": thread_public_id(thread), "assigned_to": thread.assigned_to})
    return thread


def open_thread_count(session: Session, booking_id: int) -> int:
    """For the booking's staff view; informational only - it gates nothing."""
    return int(session.execute(
        select(func.count(SupportThread.id)).where(SupportThread.booking_id == booking_id, SupportThread.status == OPEN)
    ).scalar_one())
