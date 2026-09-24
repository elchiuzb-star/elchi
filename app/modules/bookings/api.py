"""API v2 bookings router: P8 accept, B1-B13, T9 trip actions, T10 manifest. Mounted by the integrator.

Every endpoint declares ``response_model``. Commands go through the shared idempotent runner
(``app.api.v2.web.run_command``: Idempotency-Key, savepoint pattern, ``run_with_db_retry``). Participant actions
use ``_run_action_command``, the same runner plus one step: wrong proof codes are recorded after the command's
savepoint rolled back its 4xx, in the same transaction, so the attempt limit holds (spec §11).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v2.web import (
    ERROR_RESPONSES,
    current_user_id,
    decode_id_cursor,
    decode_time_id_cursor,
    encode_page_cursor,
    get_session,
    page_scope,
    run_command,
    session_ref_of,
)
from app.api.v2.web import to_api_warnings
from app.contracts.dto import MAX_PAGE_LIMIT, Envelope, PageMeta
from app.contracts.enums import AdminBookingQueue, BookingAction, OperatorBookingCommand, ProofKind
from app.contracts.errors import WarningCode
from app.contracts.promo import CLIENT_FEATURES_HEADER, parse_client_features
from app.modules.bookings import service as bookings_service
from app.modules.promotions.booking import ConsentInput, DriverAck
from app.modules.bookings.schemas import (
    AcceptRequest,
    AmendmentAccept,
    AmendmentCreate,
    AmendmentDecision,
    AmendmentDTO,
    AmendmentPromoConfirmation,
    BookingActionRequest,
    BookingCancel,
    BookingClientDTO,
    BookingCodesDTO,
    BookingDTO,
    CashReceiptDecision,
    CashReceiptDTO,
    CashReceiptReport,
    OperatorBookingCommandRequest,
    ProofReissueRequest,
    TripActionRequest,
    TripManifestDTO,
)
from app.modules.bookings.views import (
    amendment_dto,
    booking_view,
    cash_receipt_dto,
    codes_dto,
    manifest_dto,
    staff_contact_fields,
)
from app.modules.trips.schemas import TripDTO
from app.modules.trips.views import trip_dto

router = APIRouter(tags=["v2 Bookings"])

AnyBooking = BookingDTO | BookingClientDTO
TripAction = Literal["start_boarding", "depart", "complete", "interrupt", "resume", "cancel"]


def _delivery_code_warnings(codes: list) -> list:  # noqa: ANN001
    """Q65: the sender is told to give the delivery code only to the receiver."""
    if any(kind is ProofKind.DELIVERY_CODE for kind, _ in codes):
        return to_api_warnings([{"code": WarningCode.DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY.value, "field": "codes.delivery_code"}])
    return []


def _features(request: Request) -> frozenset[str]:
    """X-Elchi-Client-Features: what this client can render (Q110). Never an authority; absent = none."""
    return parse_client_features(request.headers.get(CLIENT_FEATURES_HEADER))


def _consent(body) -> ConsentInput | None:  # noqa: ANN001 - any body with an optional promo_consent
    consent = getattr(body, "promo_consent", None)
    return None if consent is None else ConsentInput(consent.passenger_bonus_minor, consent.cash_due_minor)


def _driver_ack(body) -> DriverAck | None:  # noqa: ANN001 - any body with an optional promo_driver_ack
    ack = getattr(body, "promo_driver_ack", None)
    return None if ack is None else DriverAck(ack.cash_to_collect_minor, ack.commission_charged_minor)


def _role_of(session: Session, booking, user_id: int) -> str:  # noqa: ANN001
    return bookings_service.get_booking_for_viewer(session, bookings_service.booking_public_id(booking), user_id)[1]


def _view_for(session: Session, booking, user_id: int) -> AnyBooking:  # noqa: ANN001
    return booking_view(session, booking, viewer_role=_role_of(session, booking, user_id))


def _run_action_command(
    request: Request,
    session: Session,
    *,
    actor_user_id: int,
    idempotency_key: str | None,
    body: BaseModel,
    handler: Callable[[list[bookings_service.ProofFailure]], BaseModel],
) -> JSONResponse:
    failures: list[bookings_service.ProofFailure] = []

    def wrapped() -> BaseModel:
        failures.clear()  # a deadlock retry re-runs the handler: keep only this attempt's failures
        return handler(failures)

    def record_attempts(replayed: bool) -> None:
        if failures and not replayed:
            # The PROOF_INVALID 4xx is stored; its savepoint was rolled back. Count the attempt now (spec §11).
            bookings_service.record_failed_proof_attempts(session, list(failures))

    # Shared runner (integration pass): same Idempotency-Key / savepoint / retry semantics as every command.
    return run_command(
        request, session, actor_user_id=actor_user_id, idempotency_key=idempotency_key, body=body, handler=wrapped,
        resource_type="booking", after_command=record_attempts,
    )


# --- P8 accept ---------------------------------------------------------------------------------------------------


@router.post("/proposals/{thread_id}/accept", response_model=Envelope[AnyBooking], status_code=201, responses=ERROR_RESPONSES)
def accept_proposal(
    thread_id: str,
    body: AcceptRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> AnyBooking:
        booking = bookings_service.accept_proposal(
            session,
            thread_public_id=thread_id,
            actor_user_id=user_id,
            proposal_version_public_id=body.proposal_version_id,
            expected_listing_version=body.terms_version,
            client_features=_features(request),
            promo_consent=_consent(body),
            client_session=session_ref_of(request),
            promo_driver_ack=_driver_ack(body),
        )
        return _view_for(session, booking, user_id)

    return run_command(
        request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
        success_status=201, resource_type="booking",
    )


# --- B1, B2 reads ------------------------------------------------------------------------------------------------


@router.get("/bookings/{booking_id}", response_model=Envelope[AnyBooking], responses=ERROR_RESPONSES)
def get_booking(booking_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> Envelope[AnyBooking]:
    booking, role = bookings_service.get_booking_for_viewer(session, booking_id, user_id)
    dto = booking_view(session, booking, viewer_role=role)
    if role == bookings_service.ViewerRole.STAFF:
        # Staff visibility of contacts/full plate is unchanged but audited (STATE_MACHINES §9/§11, Q44, Q64).
        bookings_service.record_staff_contact_view(
            session, actor_user_id=user_id, booking_ids=[dto.id], surface="B1", fields=staff_contact_fields(dto)
        )
        session.commit()
    return Envelope[AnyBooking](data=dto)


@router.get("/me/bookings", response_model=Envelope[list[AnyBooking]], responses=ERROR_RESPONSES)
def list_my_bookings(
    role: Literal["client", "driver"] | None = Query(default=None),
    status: str | None = Query(default=None, max_length=24),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[AnyBooking]]:
    scope = page_scope("GET /me/bookings", role=role, status=status)
    rows = bookings_service.list_user_bookings(
        session, user_id, role=role, status=status, before=decode_time_id_cursor(cursor, scope), limit=limit + 1
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].created_at, page[-1].id], scope) if more else None
    data = [
        booking_view(
            session, b, viewer_role=bookings_service.ViewerRole.CLIENT if b.client_user_id == user_id else bookings_service.ViewerRole.DRIVER
        )
        for b in page
    ]
    return Envelope[list[AnyBooking]](data=data, meta=PageMeta(next_cursor=next_cursor, limit=limit))


# --- B3 cancel, B4 actions, B5 codes -----------------------------------------------------------------------------


@router.post("/bookings/{booking_id}/cancel", response_model=Envelope[AnyBooking], responses=ERROR_RESPONSES)
def cancel_booking(
    booking_id: str,
    body: BookingCancel,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler():  # noqa: ANN202 - (dto, warnings)
        warnings: list[dict] = []
        booking = bookings_service.cancel_booking(
            session, booking_public_id_value=booking_id, actor_user_id=user_id, expected_version=body.expected_version,
            reason_code=body.reason_code, comment=body.comment, warnings=warnings,
        )
        return _view_for(session, booking, user_id), warnings

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="booking")


@router.post("/bookings/{booking_id}/actions/{action}", response_model=Envelope[AnyBooking], responses=ERROR_RESPONSES)
def booking_action(
    booking_id: str,
    action: BookingAction,
    body: BookingActionRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler(failures: list[bookings_service.ProofFailure]) -> AnyBooking:
        booking = bookings_service.perform_action(
            session,
            booking_public_id_value=booking_id,
            actor_user_id=user_id,
            action=action,
            data=bookings_service.ActionInput(
                expected_version=body.expected_version,
                code=body.code,
                evidence_file_ids=tuple(body.evidence_file_ids),
                note=body.note,
                contact_attempts=tuple(item.model_dump(mode="json") for item in body.contact_attempts),
                observed_at=body.observed_at,
            ),
            proof_failures=failures,
        )
        return _view_for(session, booking, user_id)

    return _run_action_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler)


@router.get("/bookings/{booking_id}/codes", response_model=Envelope[BookingCodesDTO], responses=ERROR_RESPONSES)
def get_booking_codes(booking_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> Envelope[BookingCodesDTO]:
    codes = bookings_service.booking_codes(session, booking_public_id_value=booking_id, viewer_user_id=user_id)
    return Envelope[BookingCodesDTO](data=codes_dto(booking_id, codes), warnings=_delivery_code_warnings(codes) or None)


@router.post("/bookings/{booking_id}/codes/{kind}/reissue", response_model=Envelope[BookingCodesDTO], responses=ERROR_RESPONSES)
def reissue_booking_code(
    booking_id: str,
    kind: ProofKind,
    body: ProofReissueRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """B5a (wave 2.1, BR blocker 3): the code owner reissues one code; the response carries only the new code."""

    def handler():  # noqa: ANN202 - (dto, warnings)
        warnings: list = []
        _, reissued_kind, code = bookings_service.reissue_proof_code(
            session, booking_public_id_value=booking_id, actor_user_id=user_id, proof_kind=kind, reason=body.reason,
            warnings=warnings,
        )
        codes = [(reissued_kind, code)]
        return codes_dto(booking_id, codes), [*warnings, *_delivery_code_warnings(codes)]

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="booking")


# --- B6-B8 cash receipts -------------------------------------------------------------------------------------------


@router.post("/bookings/{booking_id}/cash-receipts", response_model=Envelope[CashReceiptDTO], status_code=201, responses=ERROR_RESPONSES)
def report_cash_receipt(
    booking_id: str,
    body: CashReceiptReport,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> CashReceiptDTO:
        booking, receipt = bookings_service.report_cash_receipt(
            session, booking_public_id_value=booking_id, actor_user_id=user_id, expected_version=body.expected_version,
            amount_minor=body.amount_minor, reported_at=body.reported_at, note=body.note,
            client_features=_features(request), client_session=session_ref_of(request),
        )
        return cash_receipt_dto(receipt, booking)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       success_status=201, resource_type="cash_receipt")


def _cash_decision(decision: str, booking_id: str, receipt_id: str, body: CashReceiptDecision, request: Request,
                   idempotency_key: str | None, user_id: int, session: Session) -> JSONResponse:
    operation = bookings_service.acknowledge_cash_receipt if decision == "acknowledge" else bookings_service.contest_cash_receipt

    def handler() -> CashReceiptDTO:
        booking, receipt = operation(
            session, booking_public_id_value=booking_id, receipt_public_id=receipt_id, actor_user_id=user_id,
            expected_version=body.expected_version, comment=body.comment, client_features=_features(request),
            client_session=session_ref_of(request),
        )
        return cash_receipt_dto(receipt, booking)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="cash_receipt")


@router.post("/bookings/{booking_id}/cash-receipts/{receipt_id}/acknowledge", response_model=Envelope[CashReceiptDTO], responses=ERROR_RESPONSES)
def acknowledge_cash_receipt(
    booking_id: str, receipt_id: str, body: CashReceiptDecision, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return _cash_decision("acknowledge", booking_id, receipt_id, body, request, idempotency_key, user_id, session)


@router.post("/bookings/{booking_id}/cash-receipts/{receipt_id}/contest", response_model=Envelope[CashReceiptDTO], responses=ERROR_RESPONSES)
def contest_cash_receipt(
    booking_id: str, receipt_id: str, body: CashReceiptDecision, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return _cash_decision("contest", booking_id, receipt_id, body, request, idempotency_key, user_id, session)


# --- B9-B11 amendments ---------------------------------------------------------------------------------------------


@router.get("/bookings/{booking_id}/amendments", response_model=Envelope[list[AmendmentDTO]], responses=ERROR_RESPONSES)
def list_amendments(
    booking_id: str,
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[AmendmentDTO]]:
    """B9: the booking's amendments, so the side that did not propose one can see and answer it."""
    booking, rows = bookings_service.list_booking_amendments(
        session, booking_public_id_value=booking_id, actor_user_id=user_id, limit=limit
    )
    role = _role_of(session, booking, user_id)
    return Envelope[list[AmendmentDTO]](data=[amendment_dto(row, booking, viewer_role=role, session=session) for row in rows])


@router.post("/bookings/{booking_id}/amendments", response_model=Envelope[AmendmentDTO], status_code=201, responses=ERROR_RESPONSES)
def create_amendment(
    booking_id: str, body: AmendmentCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler():  # noqa: ANN202 - (dto, warnings)
        warnings: list[dict] = []
        amendment = bookings_service.create_amendment(
            session, booking_public_id_value=booking_id, actor_user_id=user_id, expected_version=body.expected_version,
            changes=body.changes.model_dump(mode="json", exclude_none=True), reason=body.reason, warnings=warnings,
            client_features=_features(request), promo_consent=_consent(body), promo_driver_ack=_driver_ack(body),
            client_session=session_ref_of(request),
        )
        booking = bookings_service.get_booking(session, amendment.booking_id)
        return amendment_dto(amendment, booking, viewer_role=_role_of(session, booking, user_id), session=session), warnings

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       success_status=201, resource_type="amendment")


@router.post("/amendments/{amendment_id}/accept", response_model=Envelope[AnyBooking], responses=ERROR_RESPONSES)
def accept_amendment(
    amendment_id: str, body: AmendmentAccept, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> AnyBooking:
        booking = bookings_service.accept_amendment(
            session, amendment_public_id=amendment_id, actor_user_id=user_id, expected_version=body.expected_version,
            client_features=_features(request), promo_consent=_consent(body), promo_driver_ack=_driver_ack(body),
            client_session=session_ref_of(request),
        )
        return _view_for(session, booking, user_id)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="booking")


@router.post("/amendments/{amendment_id}/promo-confirmation", response_model=Envelope[AmendmentDTO],
             responses=ERROR_RESPONSES)
def confirm_amendment_promo(
    amendment_id: str, body: AmendmentPromoConfirmation, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    """Q126: the proposer renews its promo confirmation of an open amendment (after a stale-confirmation refusal)."""
    def handler() -> AmendmentDTO:
        amendment = bookings_service.confirm_amendment_promo(
            session, amendment_public_id=amendment_id, actor_user_id=user_id, client_features=_features(request),
            client_session=session_ref_of(request), promo_consent=_consent(body), promo_driver_ack=_driver_ack(body),
        )
        booking = bookings_service.get_booking(session, amendment.booking_id)
        return amendment_dto(amendment, booking, viewer_role=_role_of(session, booking, user_id), session=session)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="amendment")


def _amendment_decision(decision: Literal["reject", "withdraw"], amendment_id: str, body: AmendmentDecision, request: Request,
                        idempotency_key: str | None, user_id: int, session: Session) -> JSONResponse:
    def handler() -> AmendmentDTO:
        amendment = bookings_service.decide_amendment(
            session, amendment_public_id=amendment_id, actor_user_id=user_id, expected_version=body.expected_version, decision=decision
        )
        booking = bookings_service.get_booking(session, amendment.booking_id)
        return amendment_dto(amendment, booking, viewer_role=_role_of(session, booking, user_id), session=session)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="amendment")


@router.post("/amendments/{amendment_id}/reject", response_model=Envelope[AmendmentDTO], responses=ERROR_RESPONSES)
def reject_amendment(
    amendment_id: str, body: AmendmentDecision, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return _amendment_decision("reject", amendment_id, body, request, idempotency_key, user_id, session)


@router.post("/amendments/{amendment_id}/withdraw", response_model=Envelope[AmendmentDTO], responses=ERROR_RESPONSES)
def withdraw_amendment(
    amendment_id: str, body: AmendmentDecision, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    return _amendment_decision("withdraw", amendment_id, body, request, idempotency_key, user_id, session)


# --- B12, B13 operator ---------------------------------------------------------------------------------------------


@router.get("/admin/bookings", response_model=Envelope[list[BookingDTO]], responses=ERROR_RESPONSES)
def list_admin_bookings(
    queue: AdminBookingQueue = Query(...),
    corridor_id: str | None = Query(default=None, max_length=64),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[BookingDTO]]:
    corridor = None
    if corridor_id is not None:
        from app.contracts.ids import PublicIdPrefix, parse_public_id
        from app.modules.geo.models import ServiceCorridor
        from sqlalchemy import select

        value = parse_public_id(corridor_id, PublicIdPrefix.CORRIDOR)
        corridor = session.execute(select(ServiceCorridor.id).where(ServiceCorridor.public_id == value)).scalar_one_or_none() or -1
    scope = page_scope("GET /admin/bookings", queue=queue, corridor=corridor_id)
    rows = bookings_service.admin_queue(
        session, actor_user_id=user_id, queue=queue.value, corridor_id=corridor, after_id=decode_id_cursor(cursor, scope),
        limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].id], scope) if more else None
    data = [booking_view(session, b, viewer_role=bookings_service.ViewerRole.STAFF) for b in page]
    shown = [(dto.id, staff_contact_fields(dto)) for dto in data]
    fields = sorted({field for _, dto_fields in shown for field in dto_fields})
    if fields:
        # Wave 2.1 medium: staff list responses that show phones / full plates leave an audit row (no values).
        bookings_service.record_staff_contact_view(
            session, actor_user_id=user_id, booking_ids=[dto_id for dto_id, dto_fields in shown if dto_fields],
            surface=f"B12:{queue.value}", fields=fields,
        )
        session.commit()
    return Envelope[list[BookingDTO]](data=data, meta=PageMeta(next_cursor=next_cursor, limit=limit))


@router.post("/admin/bookings/{booking_id}/commands/{command}", response_model=Envelope[BookingDTO], responses=ERROR_RESPONSES)
def operator_booking_command(
    booking_id: str,
    command: OperatorBookingCommand,
    body: OperatorBookingCommandRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> BookingDTO:
        booking = bookings_service.operator_command(
            session, booking_public_id_value=booking_id, actor_user_id=user_id, command=command,
            expected_version=body.expected_version, reason=body.reason, evidence_file_ids=tuple(body.evidence_file_ids),
            fee_mode=body.fee_decision.mode if body.fee_decision else None, proof_kind=body.proof_kind,
            cancel_fault_side=body.cancel_fault_side,
        )
        return booking_view(session, booking, viewer_role=bookings_service.ViewerRole.STAFF)  # type: ignore[return-value]

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="booking")


# --- T9 trip actions, T10 manifest ---------------------------------------------------------------------------------


@router.post("/trips/{trip_id}/actions/{action}", response_model=Envelope[TripDTO], responses=ERROR_RESPONSES)
def trip_action(
    trip_id: str,
    body: TripActionRequest,
    request: Request,
    action: TripAction = Path(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> TripDTO:
        trip = bookings_service.trip_action(
            session, trip_public_id_value=trip_id, actor_user_id=user_id, action=action, expected_version=body.expected_version,
            reason=body.reason,
        )
        return trip_dto(session, trip)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body, handler=handler,
                       resource_type="trip")


@router.get("/trips/{trip_id}/manifest", response_model=Envelope[TripManifestDTO], responses=ERROR_RESPONSES)
def get_trip_manifest(trip_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)) -> Envelope[TripManifestDTO]:
    trip, entries = bookings_service.trip_manifest(session, trip_public_id_value=trip_id, viewer_user_id=user_id)
    return Envelope[TripManifestDTO](data=manifest_dto(session, trip, entries))
