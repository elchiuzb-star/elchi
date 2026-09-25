"""API v2 trust & support router: I4, S1-S8, S13-S20 (API_V2_CONTRACT §1, §12). Mounted by the integrator.

Commands use the shared idempotent runner (``app.api.v2.web.run_command``). Free text is masked (Q43) and the
contact-filter hits are recorded after the command in their own commit, so a later 4xx cannot erase the Q45 signal
(R2-b; same pattern as the marketplace router). Every endpoint declares ``response_model``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v2.web import (
    ERROR_RESPONSES,
    active_session_user_id,
    current_user_id,
    decode_id_cursor,
    decode_time_id_cursor,
    encode_page_cursor,
    get_session,
    page_scope,
    run_command,
)
from app.contracts.dto import MAX_PAGE_LIMIT, EmptyDTO, Envelope, PageMeta
from app.contracts.enums import (
    DisputeStatus,
    FraudSignalStatus,
    ReportStatus,
    DisputeType,
    ServiceType,
    SupportTicketKind,
    SupportTicketStatus,
    TrustReviewStatus,
    TrustSignalType,
)
from app.contracts.timeutil import ensure_aware_utc
from app.contracts.trust import STRIKE_REVIEW_WINDOW
from app.modules.bookings import service as bookings_service
from app.modules.identity import service as identity_service
from app.modules.marketplace.service import ContactFilterHit, record_contact_filter_hits
from app.modules.trust_support import config, service, threads
from app.modules.trust_support.models import (
    AbuseReport,
    SupportMessage,
    SupportThread,
    DisputeV2,
    FraudSignal,
    RatingV2,
    SupportTicket,
    TrustReviewItem,
    UserBlock,
)
from app.modules.trust_support.schemas import (
    AccountDeletionDTO,
    AccountDeletionRequest,
    BlockCreate,
    BlockDTO,
    BookingLiveStateDTO,
    DisputeCommand,
    DisputeDTO,
    DisputeEvidenceDTO,
    DisputeResolutionDTO,
    FraudSignalCommand,
    FraudSignalDTO,
    RatingCreate,
    RatingDTO,
    ReportCommand,
    ReportCreate,
    ReportDTO,
    ReputationDTO,
    StrikeDTO,
    SupportContactsDTO,
    SupportTicketAdminDTO,
    SupportMessageCreate,
    SupportMessageDTO,
    SupportFileLinkDTO,
    SupportFileRefDTO,
    SupportThreadAdminDTO,
    SupportThreadCommand,
    SupportThreadDTO,
    SupportThreadOpen,
    SupportTicketCommand,
    SupportTicketCreate,
    SupportTicketDTO,
    TrustReviewCommand,
    TrustReviewDTO,
    UserStrikesDTO,
)
from app.utils.file_access import signed_file_url

router = APIRouter(tags=["v2 Trust & support"])
logger = logging.getLogger("elchi.trust_support.api")


# --- plumbing ---------------------------------------------------------------------------------------------------------


def _run_filtered(
    request: Request, session: Session, *, actor_user_id: int, idempotency_key: str | None, body: BaseModel | None,
    build: Callable[[list[dict], list[ContactFilterHit]], BaseModel], success_status: int = 200, resource_type: str | None = None,
) -> JSONResponse:
    hits: list[ContactFilterHit] = []

    def handler():  # noqa: ANN202 - (dto, warnings)
        hits.clear()  # a deadlock retry re-runs the handler: keep only this attempt's hits
        warnings: list[dict] = []
        return build(warnings, hits), warnings

    try:
        return run_command(request, session, actor_user_id=actor_user_id, idempotency_key=idempotency_key, body=body,
                           handler=handler, success_status=success_status, resource_type=resource_type)
    finally:
        if hits:
            try:
                record_contact_filter_hits(session, list(hits))
                session.commit()
            except Exception:  # never mask the command's own outcome
                session.rollback()
                logger.exception("recording contact filter hits failed")


def _command_name(value: str) -> str:
    return value.replace("-", "_")


# --- DTO builders -----------------------------------------------------------------------------------------------------


def dispute_dto(session: Session, dispute: DisputeV2) -> DisputeDTO:
    booking = bookings_service.get_booking(session, dispute.booking_id)
    resolution = None
    if dispute.status in ("resolved", "rejected"):
        resolution = DisputeResolutionDTO(code=dispute.resolution_code, text=dispute.resolution_text, decided_at=dispute.decided_at)
    return DisputeDTO(
        id=service.dispute_public_id(dispute),
        booking_id=bookings_service.booking_public_id(booking),
        type=dispute.dispute_type,
        status=dispute.status,
        version=dispute.version,
        opened_by_side=dispute.opened_by_side,
        description=dispute.description,
        evidence=[
            DisputeEvidenceDTO(
                author_side=item.author_side, note=item.note, file_ids=list(item.file_ids or []),
                file_urls=[url for url in (signed_file_url(file_id) for file_id in (item.file_ids or [])) if url],
                created_at=item.created_at,
            )
            for item in service.dispute_evidence(session, dispute.id)
        ],
        resolution=resolution,
        created_at=dispute.created_at,
        escalate_at=dispute.escalate_at,
        escalated=dispute.escalated_at is not None,
    )


def rating_dto(session: Session, rating: RatingV2) -> RatingDTO:
    booking = bookings_service.get_booking(session, rating.booking_id)
    return RatingDTO(
        id=service.rating_public_id(rating), booking_id=bookings_service.booking_public_id(booking),
        subject_side=rating.subject_side, stars=rating.stars, comment_moderated=rating.comment,
        published_at=rating.published_at, created_at=rating.created_at,
    )


def _ticket_fields(session: Session, ticket: SupportTicket) -> dict:
    booking_id = None
    if ticket.booking_id is not None:
        booking_id = bookings_service.booking_public_id(bookings_service.get_booking(session, ticket.booking_id))
    return {
        "id": service.ticket_public_id(ticket), "kind": ticket.kind, "status": ticket.status, "booking_id": booking_id,
        "message": ticket.message, "version": ticket.version, "created_at": ticket.created_at,
        "acknowledged_at": ticket.acknowledged_at, "resolved_at": ticket.resolved_at,
    }


def ticket_dto(session: Session, ticket: SupportTicket) -> SupportTicketDTO:
    return SupportTicketDTO(**_ticket_fields(session, ticket))


def ticket_admin_dto(session: Session, ticket: SupportTicket) -> SupportTicketAdminDTO:
    live = None
    if ticket.kind == SupportTicketKind.SOS.value and ticket.booking_id is not None:
        state = service.booking_live_state(session, ticket.booking_id)
        if state is not None:
            live = BookingLiveStateDTO(window_open=bool(state.window.is_open), freshness=state.freshness,
                                       last_captured_at=state.last_captured_at, driver_arrived_at=state.driver_arrived_at)
    trip_id = None
    if ticket.trip_id is not None:
        trip_id = service._trip_public_id(session, ticket.trip_id)  # noqa: SLF001 - module-internal reader
    return SupportTicketAdminDTO(
        **_ticket_fields(session, ticket), user_id=identity_service.user_public_id(session, ticket.user_id), trip_id=trip_id, live=live,
        press_count=ticket.press_count, last_pressed_at=ticket.last_pressed_at,
    )


def review_dto(session: Session, item: TrustReviewItem) -> TrustReviewDTO:
    refs = identity_service.user_refs(session, [uid for uid in (item.subject_user_id, item.decided_by) if uid is not None])
    return TrustReviewDTO(
        id=service.review_public_id(item), subject_user_id=refs[item.subject_user_id][0], signal_type=item.signal_type,
        status=item.status, evidence=dict(item.evidence or {}), signal_count=item.signal_count, last_signal_at=item.last_signal_at,
        decision=item.decision, decided_by=refs[item.decided_by][0] if item.decided_by is not None else None,
        decided_at=item.decided_at, version=item.version, created_at=item.created_at,
    )


# --- I4 account deletion ----------------------------------------------------------------------------------------------


@router.delete("/me", response_model=Envelope[AccountDeletionDTO], responses=ERROR_RESPONSES)
def delete_me(
    request: Request,
    body: AccountDeletionRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> AccountDeletionDTO:
        service.delete_account_v2(session, actor_user_id=user_id)
        return AccountDeletionDTO(status="deleted")

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="user")


# --- S1, S2 ratings -----------------------------------------------------------------------------------------------------


@router.post("/bookings/{booking_id}/ratings", response_model=Envelope[RatingDTO], status_code=201, responses=ERROR_RESPONSES)
def create_rating(
    booking_id: str, body: RatingCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def build(warnings: list[dict], hits: list[ContactFilterHit]) -> RatingDTO:
        rating = service.create_rating(
            session, booking_public_id_value=booking_id, actor_user_id=user_id, subject_side=body.subject_side,
            stars=body.stars, comment=body.comment, warnings=warnings, filter_hits=hits,
        )
        return rating_dto(session, rating)

    return _run_filtered(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, build=build,
                         success_status=201, resource_type="rating")


@router.get("/users/{user_id}/reputation", response_model=Envelope[ReputationDTO], responses=ERROR_RESPONSES)
def get_reputation(
    user_id: str, service_type: ServiceType = Query(...), viewer_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[ReputationDTO]:
    internal = identity_service.resolve_user_id(session, user_id)
    summary = service.reputation_summaries(session, [internal], service_type=service_type)[internal]
    return Envelope[ReputationDTO](data=ReputationDTO(
        user_id=user_id, service_type=service_type, rating_count=summary.rating_count, average_rating=summary.average_rating,
        label=summary.label, completed_bookings=summary.completed_bookings, completed_trips=summary.completed_trips,
    ))


# --- S3-S8 disputes -----------------------------------------------------------------------------------------------------


# ADR-0026 (Q141): the client/driver-facing dispute routes (POST /bookings/{id}/disputes, GET /me/disputes,
# GET /disputes/{id}, POST /disputes/{id}/evidence) are removed - "Shikoyat qilish" opens the booking-bound operator
# chat below. `disputes_v2` stays a staff-only internal record (admin routes), with its existing money/promo effects.


@router.get("/admin/disputes", response_model=Envelope[list[DisputeDTO]], responses=ERROR_RESPONSES)
def admin_list_disputes(
    status: DisputeStatus | None = Query(default=None), type: DisputeType | None = Query(default=None),  # noqa: A002
    escalated: bool | None = Query(default=None), cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[DisputeDTO]]:
    scope = page_scope("GET /admin/disputes", status=status, type=type, escalated=escalated)
    rows = service.admin_list_disputes(
        session, actor_user_id=user_id, status=status.value if status else None, dispute_type=type.value if type else None,
        escalated=escalated, after_id=decode_id_cursor(cursor, scope), limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].id], scope) if more else None
    return Envelope[list[DisputeDTO]](data=[dispute_dto(session, d) for d in page], meta=PageMeta(next_cursor=next_cursor, limit=limit))


@router.post("/admin/disputes/{dispute_id}/{command}", response_model=Envelope[DisputeDTO], responses=ERROR_RESPONSES)
def admin_dispute_command(
    dispute_id: str, command: Literal["start-review", "resolve", "reject"], body: DisputeCommand, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> DisputeDTO:
        dispute = service.dispute_command(
            session, dispute_public_id_value=dispute_id, actor_user_id=user_id, command=_command_name(command),
            expected_version=body.expected_version, resolution_code=body.resolution_code.value if body.resolution_code else None,
            resolution_text=body.resolution_text, reason=body.reason,
            cash_outcome=body.cash_outcome.value if body.cash_outcome else None,
        )
        return dispute_dto(session, dispute)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="dispute")


# --- ADR-0026 (Q141): booking-bound operator chat --------------------------------------------------------------------------


def _message_dto(message: SupportMessage, *, viewer_user_id: int | None) -> SupportMessageDTO:
    if message.author_side == "system":
        author = "system"
    elif message.author_side == "operator":
        author = "operator"
    elif viewer_user_id is not None and message.author_user_id == viewer_user_id:
        author = "me"
    else:
        author = message.author_side
    return SupportMessageDTO(id=threads.message_public_id(message), author=author, text=message.body,
                             has_files=bool(message.file_ids), created_at=message.created_at,
                             staff_only=bool(message.staff_only) if viewer_user_id is None else False)


def _thread_fields(thread: SupportThread, booking_pid: str, messages: list[SupportMessage], viewer: int | None,
                   message_count: int | None = None) -> dict:
    return {
        "id": threads.thread_public_id(thread), "booking_id": booking_pid, "requester_side": thread.requester_side,
        "status": thread.status, "staff_status": threads.staff_status(thread),
        "message_count": thread.message_count if message_count is None else message_count,
        "version": thread.version, "created_at": thread.created_at, "closed_at": thread.closed_at,
        "messages": [_message_dto(m, viewer_user_id=viewer) for m in messages],
    }


def thread_dto(session: Session, view: threads.ThreadView, viewer_user_id: int) -> SupportThreadDTO:
    # the requester's view: staff-only lines were already left out, and the count is of what they see
    return SupportThreadDTO(**_thread_fields(view.thread, view.booking_public_id, view.messages, viewer_user_id,
                                             message_count=len(view.messages)))


def thread_admin_dto(session: Session, view: threads.ThreadView) -> SupportThreadAdminDTO:
    thread = view.thread
    return SupportThreadAdminDTO(
        **_thread_fields(thread, view.booking_public_id, view.messages, None),
        requester_user_id=identity_service.user_public_id(session, thread.requester_user_id),
        assigned_to=identity_service.user_public_id(session, thread.assigned_to) if thread.assigned_to else None,
        carried_over_from_dispute=thread.source_dispute_id is not None,
        files=[SupportFileRefDTO(ref=f.ref, name=f.name, message_id=threads.message_public_id(f.message),
                                 staff_only=bool(f.message.staff_only)) for f in threads.staff_files(view.messages)],
    )


@router.post("/bookings/{booking_id}/support-thread", response_model=Envelope[SupportThreadDTO], responses=ERROR_RESPONSES)
def open_support_thread(
    booking_id: str, body: SupportThreadOpen, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    """"Shikoyat qilish": the caller's open operator chat for this booking - an existing one, or a new one (200 either
    way; a retry or a second tap never creates a duplicate)."""
    def build(warnings: list[dict], hits: list[ContactFilterHit]) -> SupportThreadDTO:
        thread, _ = threads.open_or_get_thread(session, booking_public_id_value=booking_id, actor_user_id=user_id,
                                               text_value=body.text, warnings=warnings, filter_hits=hits)
        return thread_dto(session, threads.get_thread_for_user(session, threads.thread_public_id(thread), user_id), user_id)

    return _run_filtered(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, build=build,
                         resource_type="support_thread")


@router.get("/bookings/{booking_id}/support-thread", response_model=Envelope[SupportThreadDTO | None], responses=ERROR_RESPONSES)
def get_booking_support_thread(
    booking_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[SupportThreadDTO | None]:
    thread = threads.thread_for_booking(session, booking_id, user_id)
    if thread is None:
        return Envelope[SupportThreadDTO | None](data=None)
    return Envelope[SupportThreadDTO | None](
        data=thread_dto(session, threads.get_thread_for_user(session, threads.thread_public_id(thread), user_id), user_id))


@router.get("/me/support-threads", response_model=Envelope[list[SupportThreadDTO]], responses=ERROR_RESPONSES)
def list_my_support_threads(
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[SupportThreadDTO]]:
    rows = threads.list_user_threads(session, user_id, limit=limit)
    counts = threads.visible_message_counts(session, [t.id for t in rows])
    data = [SupportThreadDTO(**_thread_fields(t, threads._booking_pid(session, t), [], user_id,  # noqa: SLF001
                                              message_count=counts.get(t.id, 0))) for t in rows]
    return Envelope[list[SupportThreadDTO]](data=data)


@router.get("/support-threads/{thread_id}", response_model=Envelope[SupportThreadDTO], responses=ERROR_RESPONSES)
def get_support_thread(
    thread_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[SupportThreadDTO]:
    return Envelope[SupportThreadDTO](data=thread_dto(session, threads.get_thread_for_user(session, thread_id, user_id), user_id))


@router.post("/support-threads/{thread_id}/messages", response_model=Envelope[SupportThreadDTO], status_code=201,
             responses=ERROR_RESPONSES)
def post_support_message(
    thread_id: str, body: SupportMessageCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def build(warnings: list[dict], hits: list[ContactFilterHit]) -> SupportThreadDTO:
        threads.post_message(session, thread_public_id_value=thread_id, actor_user_id=user_id, text_value=body.text,
                             warnings=warnings, filter_hits=hits)
        return thread_dto(session, threads.get_thread_for_user(session, thread_id, user_id), user_id)

    return _run_filtered(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, build=build,
                         success_status=201, resource_type="support_message")


@router.get("/admin/support-threads", response_model=Envelope[list[SupportThreadAdminDTO]], responses=ERROR_RESPONSES)
def admin_list_support_threads(
    status: Literal["open", "closed"] | None = Query(default="open"),
    assigned: Literal["me", "unassigned"] | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[SupportThreadAdminDTO]]:
    scope = page_scope("GET /admin/support-threads", status=status, assigned=assigned)
    rows = threads.admin_list_threads(session, actor_user_id=user_id, status=status, assigned=assigned,
                                      after_id=decode_id_cursor(cursor, scope), limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].id], scope) if more else None
    data = [thread_admin_dto(session, threads.ThreadView(t, threads._booking_pid(session, t), [])) for t in page]  # noqa: SLF001
    return Envelope[list[SupportThreadAdminDTO]](data=data, meta=PageMeta(next_cursor=next_cursor, limit=limit))


@router.get("/admin/support-threads/{thread_id}", response_model=Envelope[SupportThreadAdminDTO], responses=ERROR_RESPONSES)
def admin_get_support_thread(
    thread_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[SupportThreadAdminDTO]:
    view = threads.admin_get_thread(session, thread_public_id_value=thread_id, actor_user_id=user_id)
    session.commit()  # the staff-view audit row is kept even though this is a read
    return Envelope[SupportThreadAdminDTO](data=thread_admin_dto(session, view))


@router.get("/admin/support-threads/{thread_id}/files/{file_ref}", response_model=Envelope[SupportFileLinkDTO],
            responses=ERROR_RESPONSES)
def admin_support_thread_file(
    thread_id: str, file_ref: str = Path(max_length=80),
    user_id: int = Depends(active_session_user_id), session: Session = Depends(get_session),
) -> Envelope[SupportFileLinkDTO]:
    """ADR-0026: open one evidence file of a complaint thread - live staff session + ``ops.trust_review`` + the file
    belongs to this thread; the view is audited and the answer is a short-lived signed link (no money or bonus effect)."""
    name, link = threads.staff_file_link(session, thread_public_id_value=thread_id, file_ref=file_ref, actor_user_id=user_id)
    session.commit()  # keep the audit row of the view
    return Envelope[SupportFileLinkDTO](data=SupportFileLinkDTO(ref=file_ref, name=name, url=link["url"],
                                                                expires_at=link["expires_at"], content_type=link["content_type"]))


@router.post("/admin/support-threads/{thread_id}/{command}", response_model=Envelope[SupportThreadAdminDTO],
             responses=ERROR_RESPONSES)
def admin_support_thread_command(
    thread_id: str, command: Literal["assign", "reply", "close"], body: SupportThreadCommand, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> SupportThreadAdminDTO:
        assignee = identity_service.resolve_user_id(session, body.assignee_id) if body.assignee_id else None
        threads.staff_command(session, thread_public_id_value=thread_id, actor_user_id=user_id, command=command,
                              expected_version=body.expected_version, text_value=body.text, assignee_user_id=assignee)
        return thread_admin_dto(session, threads.admin_get_thread(session, thread_public_id_value=thread_id, actor_user_id=user_id))

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="support_thread")


# --- S13-S17 support / SOS ------------------------------------------------------------------------------------------------


@router.get("/support/contacts", response_model=Envelope[SupportContactsDTO], responses=ERROR_RESPONSES)
def support_contacts(user_id: int = Depends(current_user_id)) -> Envelope[SupportContactsDTO]:
    available, phone, hours = config.support_contacts()
    return Envelope[SupportContactsDTO](data=SupportContactsDTO(available=available, phone=phone, hours_text=hours))


@router.post("/support/tickets", response_model=Envelope[SupportTicketDTO], status_code=201, responses=ERROR_RESPONSES)
def create_support_ticket(
    body: SupportTicketCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def build(warnings: list[dict], hits: list[ContactFilterHit]) -> SupportTicketDTO:
        ticket = service.create_support_ticket(
            session, actor_user_id=user_id, kind=body.kind, booking_public_id_value=body.booking_id, message=body.message,
            warnings=warnings, filter_hits=hits,
        )
        return ticket_dto(session, ticket)

    return _run_filtered(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, build=build,
                         success_status=201, resource_type="support_ticket")


@router.get("/me/support/tickets", response_model=Envelope[list[SupportTicketDTO]], responses=ERROR_RESPONSES)
def list_my_tickets(
    cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[SupportTicketDTO]]:
    scope = page_scope("GET /me/support/tickets")
    rows = service.list_user_tickets(session, user_id, before=decode_time_id_cursor(cursor, scope), limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].created_at, page[-1].id], scope) if more else None
    return Envelope[list[SupportTicketDTO]](data=[ticket_dto(session, t) for t in page], meta=PageMeta(next_cursor=next_cursor, limit=limit))


@router.get("/admin/support/tickets", response_model=Envelope[list[SupportTicketAdminDTO]], responses=ERROR_RESPONSES)
def admin_list_tickets(
    kind: SupportTicketKind | None = Query(default=None), status: SupportTicketStatus | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[SupportTicketAdminDTO]]:
    scope = page_scope("GET /admin/support/tickets", kind=kind, status=status)
    rows = service.admin_list_tickets(
        session, actor_user_id=user_id, kind=kind.value if kind else None, status=status.value if status else None,
        after_id=decode_id_cursor(cursor, scope), limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].id], scope) if more else None
    return Envelope[list[SupportTicketAdminDTO]](data=[ticket_admin_dto(session, t) for t in page], meta=PageMeta(next_cursor=next_cursor, limit=limit))


@router.post("/admin/support/tickets/{ticket_id}/{command}", response_model=Envelope[SupportTicketAdminDTO], responses=ERROR_RESPONSES)
def admin_ticket_command(
    ticket_id: str, command: Literal["acknowledge", "resolve"], body: SupportTicketCommand, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> SupportTicketAdminDTO:
        ticket = service.support_ticket_command(
            session, ticket_public_id_value=ticket_id, actor_user_id=user_id, command=command,
            expected_version=body.expected_version, note=body.note,
        )
        return ticket_admin_dto(session, ticket)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="support_ticket")


# --- S18-S20 trust review queue (Q45) ---------------------------------------------------------------------------------


@router.get("/admin/trust/reviews", response_model=Envelope[list[TrustReviewDTO]], responses=ERROR_RESPONSES)
def admin_list_reviews(
    status: TrustReviewStatus | None = Query(default=None), signal_type: TrustSignalType | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[TrustReviewDTO]]:
    scope = page_scope("GET /admin/trust/reviews", status=status, signal_type=signal_type)
    rows = service.admin_list_reviews(
        session, actor_user_id=user_id, status=status.value if status else None,
        signal_type=signal_type.value if signal_type else None, after_id=decode_id_cursor(cursor, scope), limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].id], scope) if more else None
    return Envelope[list[TrustReviewDTO]](data=[review_dto(session, r) for r in page], meta=PageMeta(next_cursor=next_cursor, limit=limit))


@router.post("/admin/trust/reviews/{review_id}/{command}", response_model=Envelope[TrustReviewDTO], responses=ERROR_RESPONSES)
def admin_review_command(
    review_id: str, command: Literal["start-review", "dismiss", "action"], body: TrustReviewCommand, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> TrustReviewDTO:
        item = service.review_command(
            session, review_public_id_value=review_id, actor_user_id=user_id, command=_command_name(command),
            expected_version=body.expected_version, decision=body.decision.value if body.decision else None, note=body.note,
        )
        return review_dto(session, item)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="trust_review")


@router.get("/admin/trust/users/{user_id}/strikes", response_model=Envelope[UserStrikesDTO], responses=ERROR_RESPONSES)
def admin_user_strikes(
    user_id: str, viewer_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[UserStrikesDTO]:
    internal, strikes = service.user_strikes(session, actor_user_id=viewer_id, user_public_id_value=user_id)
    return Envelope[UserStrikesDTO](data=UserStrikesDTO(
        user_id=identity_service.user_public_id(session, internal),
        window_days=STRIKE_REVIEW_WINDOW.days,
        strikes_in_window=len(strikes),
        strikes=[StrikeDTO(subject_type=s.subject_type, categories=list(s.categories or []), reason_code=s.reason_code,
                           occurred_at=s.occurred_at) for s in strikes],
    ))


# --- S9-S12: blocks (§8.1), reports and fraud signals (§17.3) -----------------------------------------------------


def block_dto(session: Session, block: UserBlock) -> BlockDTO:
    return BlockDTO(
        id=service.block_public_id(block),
        user_id=identity_service.user_public_id(session, block.blocked_user_id),
        created_at=ensure_aware_utc(block.created_at),
    )


def report_dto(report: AbuseReport) -> ReportDTO:
    return ReportDTO(
        id=service.report_public_id(report), subject_type=report.subject_type, subject_id=report.subject_ref,
        reason_code=report.reason_code, status=report.status, details=report.details,
        created_at=ensure_aware_utc(report.created_at),
        reviewed_at=ensure_aware_utc(report.reviewed_at) if report.reviewed_at else None,
        version=report.version,
    )


def fraud_signal_dto(session: Session, signal: FraudSignal) -> FraudSignalDTO:
    return FraudSignalDTO(
        id=service.fraud_signal_public_id(signal), signal_type=signal.signal_type,
        subject_user_id=identity_service.user_public_id(session, signal.subject_user_id),
        status=signal.status, evidence=dict(signal.evidence or {}),
        detected_at=ensure_aware_utc(signal.detected_at),
        reviewed_at=ensure_aware_utc(signal.reviewed_at) if signal.reviewed_at else None,
        version=signal.version,
    )


@router.post("/blocks", response_model=Envelope[BlockDTO], status_code=201, responses=ERROR_RESPONSES)
def create_block(
    body: BlockCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    """S9 (§8.1). Silent and idempotent: the blocked user is never told and a repeat call returns the same row."""

    def handler() -> BlockDTO:
        return block_dto(session, service.block_user(session, actor_user_id=user_id, blocked_public_id=body.user_id))

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="user_block")


@router.get("/blocks", response_model=Envelope[list[BlockDTO]], responses=ERROR_RESPONSES)
def list_blocks(
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[list[BlockDTO]]:
    return Envelope[list[BlockDTO]](
        data=[block_dto(session, row) for row in service.list_blocks(session, actor_user_id=user_id)]
    )


@router.delete("/blocks/{blocked_user_id}", response_model=Envelope[EmptyDTO], responses=ERROR_RESPONSES)
def delete_block(
    request: Request, blocked_user_id: str = Path(max_length=64),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    """S10. Idempotent: removing a block that is not there is a success, not a 404."""

    def handler() -> EmptyDTO:
        service.unblock_user(session, actor_user_id=user_id, blocked_public_id=blocked_user_id)
        return EmptyDTO()

    return run_command(request, session, actor_user_id=user_id, idempotency_key=None, body=None, handler=handler,
                       resource_type="user_block")


@router.post("/reports", response_model=Envelope[ReportDTO], status_code=201, responses=ERROR_RESPONSES)
def create_report(
    body: ReportCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    """S11 (§17.3). Filing a report changes nothing by itself: an operator reviews it, no automatic judgement."""

    def build(warnings: list[dict], hits: list[ContactFilterHit]) -> ReportDTO:
        return report_dto(
            service.create_report(session, actor_user_id=user_id, data=body, warnings=warnings, filter_hits=hits)
        )

    return _run_filtered(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                         build=build, success_status=201, resource_type="abuse_report")


@router.get("/me/reports", response_model=Envelope[list[ReportDTO]], responses=ERROR_RESPONSES)
def list_my_reports(
    cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[ReportDTO]]:
    scope = page_scope("GET /me/reports")
    rows = service.list_reports(session, actor_user_id=user_id, mine=True,
                                after_id=decode_id_cursor(cursor, scope), limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    return Envelope[list[ReportDTO]](
        data=[report_dto(row) for row in page],
        meta=PageMeta(next_cursor=encode_page_cursor([page[-1].id], scope) if more else None, limit=limit),
    )


@router.get("/admin/reports", response_model=Envelope[list[ReportDTO]], responses=ERROR_RESPONSES)
def admin_list_reports(
    status: ReportStatus | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[ReportDTO]]:
    scope = page_scope("GET /admin/reports", status=status)
    rows = service.list_reports(session, actor_user_id=user_id, status=status.value if status else None,
                                after_id=decode_id_cursor(cursor, scope), limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    return Envelope[list[ReportDTO]](
        data=[report_dto(row) for row in page],
        meta=PageMeta(next_cursor=encode_page_cursor([page[-1].id], scope) if more else None, limit=limit),
    )


@router.post("/admin/reports/{report_id}/review", response_model=Envelope[ReportDTO], responses=ERROR_RESPONSES)
def review_report(
    body: ReportCommand, request: Request, report_id: str = Path(max_length=64),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> ReportDTO:
        return report_dto(service.report_command(
            session, actor_user_id=user_id, report_public_id_value=report_id, status=body.status,
            expected_version=body.expected_version, note=body.note,
        ))

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="abuse_report")


@router.get("/admin/fraud-signals", response_model=Envelope[list[FraudSignalDTO]], responses=ERROR_RESPONSES)
def admin_list_fraud_signals(
    status: FraudSignalStatus | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512), limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[FraudSignalDTO]]:
    """S12. Informational queue: no row here has blocked, charged or down-ranked anybody (§17.3)."""
    scope = page_scope("GET /admin/fraud-signals", status=status)
    rows = service.list_fraud_signals(session, actor_user_id=user_id, status=status.value if status else None,
                                      after_id=decode_id_cursor(cursor, scope), limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    return Envelope[list[FraudSignalDTO]](
        data=[fraud_signal_dto(session, row) for row in page],
        meta=PageMeta(next_cursor=encode_page_cursor([page[-1].id], scope) if more else None, limit=limit),
    )


@router.post("/admin/fraud-signals/{signal_id}/review", response_model=Envelope[FraudSignalDTO],
             responses=ERROR_RESPONSES)
def review_fraud_signal(
    body: FraudSignalCommand, request: Request, signal_id: str = Path(max_length=64),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> FraudSignalDTO:
        return fraud_signal_dto(session, service.fraud_signal_command(
            session, actor_user_id=user_id, signal_public_id=signal_id, status=body.status,
            expected_version=body.expected_version, note=body.note,
        ))

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="fraud_signal")
