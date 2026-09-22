"""API v2 router for wallet, top-ups, ledger, finance reports and commission policies (W1-W20).

Mounted by the integrator under ``/api/v2``. Every endpoint declares ``response_model`` for
OpenAPI; handlers return ``JSONResponse`` so idempotent replays return the stored body verbatim.

Commands (wave 1.5 BR #14):
* the required capability is checked *before* the idempotency record is claimed, so a
  403/401 is never stored and never replayed (a later retry by an authorized user works);
* ``platform.run_idempotent`` (ADR-0005 savepoint pattern) runs inside ``run_with_db_retry``
  (deadlock/serialization retried, ADR-0017 §5);
* a non-retryable database error (e.g. a deferred ledger trigger failing at COMMIT) rolls back
  and returns the v2 ``500 SERVER_ERROR`` envelope; nothing is stored.

Wallet data is only returned to its owner or to finance staff (Q16).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import Date, cast, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.contracts.cursor import decode_cursor, encode_cursor
from app.contracts.dto import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, Envelope
from app.contracts.enums import (
    OBLIGATION_CAPABILITIES,
    STAFF_ROLE_CAPABILITIES,
    Capability,
    CommissionPolicyKind,
    Role,
    ServiceType,
    TopupStatus,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.idempotency import IDEMPOTENCY_HEADER, IDEMPOTENT_REPLAY_HEADER
from app.contracts.ids import PublicIdPrefix, format_public_id, parse_public_id
from app.contracts.timeutil import UTC, utc_now
from app.db.session import get_db
from app.models import User
from app.modules.platform.service import CommandResult, run_idempotent, run_with_db_retry, table_exists
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import (
    CommissionPolicy,
    LedgerAccount,
    LedgerAdjustmentRequest,
    LedgerEntry,
    LedgerTransaction,
    ReconciliationRun,
    TopupRequest,
    WalletAccount,
    WalletHold,
)
from app.modules.wallet.policy import fee_percent_text
from app.modules.wallet.schemas import (
    AdjustmentApprove,
    AdjustmentReject,
    AdjustmentWithdraw,
    CommissionPolicyConfirm,
    CommissionPolicyCreate,
    CommissionPolicyDTO,
    CommissionPolicyEnd,
    CommissionPolicyScope,
    FeeQuoteDTO,
    FinanceReportDTO,
    LedgerAdjustmentCreate,
    LedgerAdjustmentDTO,
    LedgerEntryDTO,
    LedgerLineDTO,
    LedgerReferenceDTO,
    LedgerTransactionDTO,
    ReconciliationDTO,
    SplitAdjustmentSignalDTO,
    TopupAdminDTO,
    TopupApprove,
    TopupCreate,
    TopupDTO,
    TopupEvidenceDTO,
    TopupReject,
    UserRefDTO,
    WalletDTO,
)

logger = logging.getLogger("elchi.wallet.api")

router = APIRouter(tags=["Wallet"])

FINANCE_REPORTS = ("commission_revenue", "calculated_commission", "cash_inflows", "reversals", "legacy_calculated_fee")
ADJUSTMENT_STATUS_ALIASES = {
    "pending": "pending_second_approval",
    "approved": "posted",
    "rejected": "rejected",
    "withdrawn": "withdrawn",
    "pending_second_approval": "pending_second_approval",
    "posted": "posted",
}
ADJUSTMENT_STATUS_PATTERN = "^(pending|approved|rejected|withdrawn|pending_second_approval|posted)$"

CapabilityHandler = Callable[[frozenset[Capability]], CommandResult]


# --- plumbing ----------------------------------------------------------------------------------------


def _error(exc: DomainError) -> JSONResponse:
    headers = {"Retry-After": "1"} if exc.code is ErrorCode.IDEMPOTENCY_IN_PROGRESS else None
    return JSONResponse(status_code=exc.http_status, content={"success": False, "error": exc.to_error_body()},
                        headers=headers)


def _envelope(data: Any, *, next_cursor: str | None = None, limit: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"success": True, "data": data, "message": None}
    if limit is not None:
        body["meta"] = {"next_cursor": next_cursor, "limit": limit}
    return jsonable_encoder(body)


def _dump(model: Any) -> Any:
    if isinstance(model, list):
        return [item.model_dump(mode="json", by_alias=True) for item in model]
    return model.model_dump(mode="json", by_alias=True)


def resolve_capabilities(session: Session, user: User) -> frozenset[Capability]:
    """Server-computed capabilities (ADR-0007). A1's identity service when present, else role maps."""
    try:
        from app.modules.identity import service as identity_service  # type: ignore[attr-defined]

        get_capabilities = getattr(identity_service, "get_capabilities", None)
    except ImportError:
        get_capabilities = None
    if get_capabilities is not None:
        result = get_capabilities(session, user.id)  # A1: (session, user_id) -> CapabilitySet
        values = getattr(result, "capabilities", result)
        return frozenset(Capability(value) for value in values)
    try:
        role = Role(user.role)
    except ValueError:
        return frozenset()
    if role in STAFF_ROLE_CAPABILITIES:
        return STAFF_ROLE_CAPABILITIES[role]
    if role is Role.DRIVER:
        return frozenset(OBLIGATION_CAPABILITIES)
    return frozenset()


def _require(session: Session, user: User, capability: Capability) -> frozenset[Capability]:
    caps = resolve_capabilities(session, user)
    if capability in caps:
        # ADR-0021: money commands additionally need a factor check from the last few minutes. Audit-only
        # while the platform has a single super_admin, so this cannot lock the pilot out (mfa.audit_only).
        from app.modules.identity import mfa

        mfa.require_step_up(session, user_id=user.id, capability=capability)
        return caps
    if capability.value.startswith(("finance.", "ops.", "staff.")):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": capability.value})
    if capability is Capability.PROPOSAL_SUBMIT_AS_DRIVER and user.role == Role.DRIVER.value:
        raise DomainError(ErrorCode.DRIVER_NOT_ELIGIBLE)
    raise DomainError(ErrorCode.CAPABILITY_REQUIRED, details={"capability": capability.value})


def _cursor_secret() -> bytes:
    # Wave 1.6 N4: the dedicated cursor key (ELCHI_CURSOR_SIGNING_KEY, else derived from secret_key).
    from app.core.config import cursor_signing_secret

    return cursor_signing_secret()


def _decode_after(cursor: str | None, scope: str) -> int | None:
    if cursor is None:
        return None
    values = decode_cursor(cursor, scope=scope, secret=_cursor_secret())
    if len(values) != 1 or not isinstance(values[0], int) or isinstance(values[0], bool):
        raise DomainError(ErrorCode.INVALID_CURSOR)
    return values[0]


def _next_cursor(last_id: int | None, scope: str, page_len: int, limit: int) -> str | None:
    if last_id is None or page_len < limit:
        return None
    return encode_cursor([last_id], scope=scope, secret=_cursor_secret())


def _server_error(session: Session, where: str) -> JSONResponse:
    session.rollback()
    logger.exception("wallet_api_db_error where=%s", where)
    return _error(DomainError(ErrorCode.SERVER_ERROR))


def _read(session: Session, fn: Callable[[], JSONResponse]) -> JSONResponse:
    try:
        return fn()
    except DomainError as exc:
        session.rollback()
        return _error(exc)
    except DBAPIError:
        return _server_error(session, "read")


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path_format", None) or getattr(route, "path", None) or request.url.path


def _command(
    request: Request,
    session: Session,
    user: User,
    capability: Capability,
    body: Any,
    handler: CapabilityHandler,
    path_params: dict[str, Any] | None = None,
) -> JSONResponse:
    route_template = _route_template(request)
    try:
        caps = _require(session, user, capability)  # before the idempotency claim: 403 is never stored
    except DomainError as exc:
        session.rollback()
        return _error(exc)
    except DBAPIError:
        return _server_error(session, route_template)

    def attempt():
        outcome = run_idempotent(
            session,
            actor_user_id=user.id,
            method=request.method,
            route_template=route_template,
            idempotency_key=request.headers.get(IDEMPOTENCY_HEADER),
            body=body,
            path_params=path_params,
            handler=lambda: handler(caps),
        )
        session.commit()
        return outcome

    try:
        outcome = run_with_db_retry(session, attempt)
    except DomainError as exc:
        session.rollback()
        return _error(exc)
    except DBAPIError:
        return _server_error(session, route_template)
    headers = {IDEMPOTENT_REPLAY_HEADER: "true"} if outcome.replayed else None
    return JSONResponse(status_code=outcome.status_code, content=outcome.body, headers=headers)


def _user_ref(session: Session, user_id: int | None) -> UserRefDTO | None:
    if user_id is None:
        return None
    try:
        from app.modules.identity.service import user_public_id  # A1: (session, user_id) -> "usr_..."
    except ImportError:  # pragma: no cover - identity module ships in wave 1
        return UserRefDTO(id=None)
    try:
        return UserRefDTO(id=user_public_id(session, user_id))
    except DomainError:
        return UserRefDTO(id=None)


def _by_public_id(session: Session, model: Any, text_value: str, prefix: PublicIdPrefix) -> Any:
    public = parse_public_id(text_value, prefix)
    row = session.execute(select(model).where(model.public_id == public)).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _corridor_internal_id(session: Session, corridor_public_id: str | None) -> int | None:
    """Resolve ``cor_`` ids through A2 (read-only). NOT_FOUND for unknown ids."""
    if corridor_public_id is None:
        return None
    public = parse_public_id(corridor_public_id, PublicIdPrefix.CORRIDOR)
    from app.modules.geo.models import ServiceCorridor

    corridor = session.execute(select(ServiceCorridor).where(ServiceCorridor.public_id == public)).scalar_one_or_none()
    if corridor is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return corridor.id


def _corridor_public_id(session: Session, corridor_id: int | None) -> str | None:
    if corridor_id is None:
        return None
    from app.modules.geo.models import ServiceCorridor

    public = session.execute(select(ServiceCorridor.public_id).where(ServiceCorridor.id == corridor_id)).scalar_one_or_none()
    return None if public is None else format_public_id(PublicIdPrefix.CORRIDOR, public)


def _day_bounds(from_: date, to: date) -> tuple[datetime, datetime]:
    if to < from_ or (to - from_) > timedelta(days=366):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "to"})
    return datetime.combine(from_, time.min, tzinfo=UTC), datetime.combine(to + timedelta(days=1), time.min, tzinfo=UTC)


# --- DTO builders --------------------------------------------------------------------------------------


def _topup_dto(topup: TopupRequest) -> TopupDTO:
    return TopupDTO(
        id=format_public_id(PublicIdPrefix.TOPUP, topup.public_id),
        status=TopupStatus(topup.status),
        amount_minor=topup.amount_minor,
        method=topup.method,
        created_at=_aware(topup.created_at),
        decided_at=_aware(topup.decided_at),
    )


def _topup_admin_dto(session: Session, topup: TopupRequest) -> TopupAdminDTO:
    base = _topup_dto(topup).model_dump()
    return TopupAdminDTO(
        **base,
        driver=_user_ref(session, topup.driver_user_id),
        evidence=TopupEvidenceDTO(
            payer_reference=topup.payer_reference,
            evidence_file_id=topup.evidence_file_id,
            note=topup.note,
            source_type=topup.source_type,
            source_reference=topup.source_reference,
            received_amount_minor=topup.received_amount_minor,
            received_at=_aware(topup.received_at),
        ),
        first_approver=_user_ref(session, topup.first_approver_id),
        second_approver=_user_ref(session, topup.second_approver_id),
        version=topup.version,
    )


def _transaction_dto(session: Session, transaction: LedgerTransaction) -> LedgerTransactionDTO:
    entries = session.execute(
        select(LedgerAccount.code, LedgerEntry.direction, LedgerEntry.amount_minor)
        .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
        .where(LedgerEntry.transaction_id == transaction.id)
        .order_by(LedgerEntry.id)
    ).all()
    reversal_of = None
    if transaction.reversal_of_id is not None:
        original = session.get(LedgerTransaction, transaction.reversal_of_id)
        reversal_of = format_public_id(PublicIdPrefix.LEDGER_TRANSACTION, original.public_id)
    return LedgerTransactionDTO(
        id=format_public_id(PublicIdPrefix.LEDGER_TRANSACTION, transaction.public_id),
        reference=f"{transaction.reference_kind}:{transaction.reference_key}",
        entries=[LedgerEntryDTO(account_code=code, direction=direction, amount_minor=amount) for code, direction, amount in entries],
        reversal_of=reversal_of,
        created_by=_user_ref(session, transaction.created_by),
        second_approver=_user_ref(session, transaction.second_approver_id),
        created_at=_aware(transaction.created_at),
    )


def _adjustment_dto(session: Session, request: LedgerAdjustmentRequest) -> LedgerAdjustmentDTO:
    wallet = session.get(WalletAccount, request.wallet_id)
    transaction = None if request.ledger_transaction_id is None else session.get(LedgerTransaction, request.ledger_transaction_id)
    return LedgerAdjustmentDTO(
        id=format_public_id(PublicIdPrefix.LEDGER_ADJUSTMENT, request.public_id),
        status=request.status,
        wallet_id=format_public_id(PublicIdPrefix.WALLET, wallet.public_id),
        direction=request.direction,
        amount_minor=request.amount_minor,
        reason=request.reason,
        requested_by=_user_ref(session, request.requested_by),
        approved_by=_user_ref(session, request.approved_by),
        rejected_by=_user_ref(session, request.rejected_by),
        reject_reason=request.reject_reason,
        decided_at=_aware(request.decided_at),
        pending_age_seconds=(
            max(0, int((utc_now() - _aware(request.created_at)).total_seconds()))
            if request.status == "pending_second_approval" else None
        ),
        version=request.version,
        transaction=None if transaction is None else _transaction_dto(session, transaction),
        created_at=_aware(request.created_at),
    )


def _policy_dto(session: Session, policy: CommissionPolicy) -> CommissionPolicyDTO:
    now = utc_now()
    start, end = _aware(policy.effective_from), _aware(policy.effective_to)
    return CommissionPolicyDTO(
        id=format_public_id(PublicIdPrefix.COMMISSION_POLICY, policy.public_id),
        kind=CommissionPolicyKind(policy.kind),
        scope=CommissionPolicyScope(
            corridor_id=_corridor_public_id(session, policy.scope_corridor_id),
            service_type=None if policy.scope_service_type is None else ServiceType(policy.scope_service_type),
        ),
        fee_bps=policy.fee_bps,
        fee_percent=fee_percent_text(policy.fee_bps),
        effective_from=start,
        effective_to=end,
        campaign_name=policy.campaign_name,
        reason=policy.reason,
        created_by=_user_ref(session, policy.created_by),
        created_at=_aware(policy.created_at),
        version=policy.version,
        is_active_now=start <= now and (end is None or now < end),
        is_confirmed=policy.created_by is not None or policy.confirmed_by is not None,
    )


def _ok(status_code: int, dto: Any) -> CommandResult:
    return CommandResult(status_code, _envelope(_dump(dto)))


def _adjustment_by_public_id(session: Session, adjustment_id: str) -> LedgerAdjustmentRequest:
    return _by_public_id(session, LedgerAdjustmentRequest, adjustment_id, PublicIdPrefix.LEDGER_ADJUSTMENT)


# --- W1-W4: driver wallet --------------------------------------------------------------------------------


@router.get("/wallet", response_model=Envelope[WalletDTO])
def get_my_wallet(user: User = Depends(get_current_active_user), db: Session = Depends(get_db)) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.WALLET_VIEW_OWN)
        snapshot = wallet_service.get_wallet(db, user.id)
        db.commit()  # the wallet row may have been created lazily
        dto = WalletDTO(
            id=snapshot.public_id, currency=snapshot.currency, posted_balance_minor=snapshot.posted_balance_minor,
            held_minor=snapshot.held_minor, available_minor=snapshot.available_minor,
            pending_topups_minor=snapshot.pending_topups_minor, as_of=snapshot.as_of,
        )
        return JSONResponse(_envelope(_dump(dto)))

    return _read(db, run)


@router.get("/wallet/transactions", response_model=Envelope[list[LedgerLineDTO]])
def list_my_transactions(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.WALLET_VIEW_OWN)
        wallet = wallet_service.get_or_create_wallet(db, user.id)
        scope = f"GET /wallet/transactions|{wallet.id}"
        lines = wallet_service.list_ledger_lines(db, wallet_id=wallet.id, before_entry_id=_decode_after(cursor, scope), limit=limit)
        db.commit()
        data = [
            LedgerLineDTO(
                transaction_id=line.transaction_public_id, occurred_at=line.occurred_at, kind=line.kind,
                direction=line.direction, amount_minor=line.amount_minor, balance_after_minor=line.balance_after_minor,
                reference=LedgerReferenceDTO(type=line.reference_kind, id=line.transaction_public_id),
            )
            for line in lines
        ]
        next_cursor = _next_cursor(lines[-1].entry_id if lines else None, scope, len(lines), limit)
        return JSONResponse(_envelope(_dump(data), next_cursor=next_cursor, limit=limit))

    return _read(db, run)


@router.post("/wallet/topups", response_model=Envelope[TopupDTO], status_code=201)
def create_my_topup(
    payload: TopupCreate, request: Request, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
) -> JSONResponse:
    def handler(caps: frozenset[Capability]) -> CommandResult:
        topup = wallet_service.create_topup(
            db, driver_user_id=user.id, amount_minor=payload.amount_minor, method=payload.method,
            payer_reference=payload.payer_reference, evidence_file_id=payload.evidence_file_id, note=payload.note,
        )
        return _ok(201, _topup_dto(topup))

    return _command(request, db, user, Capability.WALLET_TOPUP_REQUEST, payload.model_dump(mode="json"), handler)


@router.get("/wallet/topups", response_model=Envelope[list[TopupDTO]])
def list_my_topups(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.WALLET_VIEW_OWN)
        scope = f"GET /wallet/topups|{user.id}"
        query = select(TopupRequest).where(TopupRequest.driver_user_id == user.id)
        after = _decode_after(cursor, scope)
        if after is not None:
            query = query.where(TopupRequest.id < after)
        rows = list(db.execute(query.order_by(TopupRequest.id.desc()).limit(limit)).scalars())
        next_cursor = _next_cursor(rows[-1].id if rows else None, scope, len(rows), limit)
        return JSONResponse(_envelope(_dump([_topup_dto(row) for row in rows]), next_cursor=next_cursor, limit=limit))

    return _read(db, run)


# --- W5-W8, W16-W18: finance staff -------------------------------------------------------------------------


@router.get("/admin/topups", response_model=Envelope[list[TopupAdminDTO]])
def list_topups_admin(
    status: TopupStatus | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_REPORTS)
        scope = f"GET /admin/topups|{status.value if status else '*'}"
        query = select(TopupRequest)
        if status is not None:
            query = query.where(TopupRequest.status == status.value)
        after = _decode_after(cursor, scope)
        if after is not None:
            query = query.where(TopupRequest.id < after)
        rows = list(db.execute(query.order_by(TopupRequest.id.desc()).limit(limit)).scalars())
        next_cursor = _next_cursor(rows[-1].id if rows else None, scope, len(rows), limit)
        return JSONResponse(_envelope(_dump([_topup_admin_dto(db, row) for row in rows]), next_cursor=next_cursor, limit=limit))

    return _read(db, run)


@router.post("/admin/topups/{topup_id}/approve", response_model=Envelope[TopupAdminDTO])
def approve_topup_admin(
    topup_id: str, payload: TopupApprove, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    def handler(caps: frozenset[Capability]) -> CommandResult:
        topup = _by_public_id(db, TopupRequest, topup_id, PublicIdPrefix.TOPUP)
        topup = wallet_service.approve_topup(
            db, actor_user_id=user.id, actor_capabilities=caps, topup_id=topup.id,
            expected_version=payload.expected_version, source_type=payload.source_type,
            source_reference=payload.source_reference, received_amount_minor=payload.received_amount_minor,
            received_at=payload.received_at, note=payload.note,
        )
        return _ok(200, _topup_admin_dto(db, topup))

    return _command(request, db, user, Capability.FINANCE_TOPUP_APPROVE, payload.model_dump(mode="json"), handler,
                    {"topup_id": topup_id})


@router.post("/admin/topups/{topup_id}/reject", response_model=Envelope[TopupAdminDTO])
def reject_topup_admin(
    topup_id: str, payload: TopupReject, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    def handler(caps: frozenset[Capability]) -> CommandResult:
        topup = _by_public_id(db, TopupRequest, topup_id, PublicIdPrefix.TOPUP)
        topup = wallet_service.reject_topup(
            db, actor_user_id=user.id, actor_capabilities=caps, topup_id=topup.id,
            expected_version=payload.expected_version, reason=payload.reason,
        )
        return _ok(200, _topup_admin_dto(db, topup))

    return _command(request, db, user, Capability.FINANCE_TOPUP_APPROVE, payload.model_dump(mode="json"), handler,
                    {"topup_id": topup_id})


@router.post(
    "/admin/ledger/adjustments",
    response_model=Envelope[LedgerTransactionDTO] | Envelope[LedgerAdjustmentDTO],
    status_code=201,
    responses={202: {"model": Envelope[LedgerAdjustmentDTO], "description": "Awaiting a second approver (W16)."}},
)
def create_adjustment(
    payload: LedgerAdjustmentCreate, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    def handler(caps: frozenset[Capability]) -> CommandResult:
        wallet = _by_public_id(db, WalletAccount, payload.wallet_id, PublicIdPrefix.WALLET)
        reversal_of = None
        if payload.reversal_of_transaction_id is not None:
            reversal_of = _by_public_id(db, LedgerTransaction, payload.reversal_of_transaction_id,
                                        PublicIdPrefix.LEDGER_TRANSACTION)
            if reversal_of.wallet_id != wallet.id:
                raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reversal_of_transaction_id"})
        booking_internal_id = None
        if payload.booking_id is not None:
            hold = db.execute(select(WalletHold).where(WalletHold.booking_public_id == payload.booking_id)).scalar_one_or_none()
            if hold is None or hold.wallet_id != wallet.id:
                raise DomainError(ErrorCode.NOT_FOUND)
            booking_internal_id = hold.booking_id
        outcome = wallet_service.request_adjustment(
            db, actor_user_id=user.id, actor_capabilities=caps, wallet_id=wallet.id, direction=payload.direction,
            amount_minor=payload.amount_minor, reason=payload.reason, evidence_file_ids=payload.evidence_file_ids,
            booking_id=booking_internal_id, reversal_of_transaction_id=None if reversal_of is None else reversal_of.id,
        )
        if outcome.transaction is None:
            return _ok(202, _adjustment_dto(db, outcome.request))
        return _ok(201, _transaction_dto(db, outcome.transaction))

    return _command(request, db, user, Capability.FINANCE_ADJUSTMENT, payload.model_dump(mode="json"), handler)


@router.get("/admin/ledger/adjustments", response_model=Envelope[list[LedgerAdjustmentDTO]])
def list_adjustments(
    status: str | None = Query(default=None, pattern=ADJUSTMENT_STATUS_PATTERN),
    wallet_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """W18: adjustment requests, newest first. Contract statuses ``pending|approved|rejected`` map to the
    stored ``pending_second_approval|posted|rejected``; the stored names are accepted as aliases."""

    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_REPORTS)
        stored_status = None if status is None else ADJUSTMENT_STATUS_ALIASES[status]
        wallet_internal = None if wallet_id is None else _by_public_id(db, WalletAccount, wallet_id, PublicIdPrefix.WALLET).id
        scope = f"GET /admin/ledger/adjustments|{stored_status or '*'}|{wallet_internal or '*'}"
        query = select(LedgerAdjustmentRequest)
        if stored_status is not None:
            query = query.where(LedgerAdjustmentRequest.status == stored_status)
        if wallet_internal is not None:
            query = query.where(LedgerAdjustmentRequest.wallet_id == wallet_internal)
        after = _decode_after(cursor, scope)
        if after is not None:
            query = query.where(LedgerAdjustmentRequest.id < after)
        rows = list(db.execute(query.order_by(LedgerAdjustmentRequest.id.desc()).limit(limit)).scalars())
        next_cursor = _next_cursor(rows[-1].id if rows else None, scope, len(rows), limit)
        return JSONResponse(_envelope(_dump([_adjustment_dto(db, row) for row in rows]), next_cursor=next_cursor, limit=limit))

    return _read(db, run)


@router.get("/admin/ledger/adjustments/{adjustment_id}", response_model=Envelope[LedgerAdjustmentDTO])
def get_adjustment(
    adjustment_id: str, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
) -> JSONResponse:
    """W18 (proposed): one adjustment request."""

    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_REPORTS)
        return JSONResponse(_envelope(_dump(_adjustment_dto(db, _adjustment_by_public_id(db, adjustment_id)))))

    return _read(db, run)


@router.post("/admin/ledger/adjustments/{adjustment_id}/approve", response_model=Envelope[LedgerTransactionDTO])
def approve_adjustment_admin(
    adjustment_id: str, payload: AdjustmentApprove, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    def handler(caps: frozenset[Capability]) -> CommandResult:
        adjustment = _adjustment_by_public_id(db, adjustment_id)
        outcome = wallet_service.approve_adjustment(
            db, actor_user_id=user.id, actor_capabilities=caps, adjustment_request_id=adjustment.id,
            expected_version=payload.expected_version, note=payload.note,
        )
        return _ok(200, _transaction_dto(db, outcome.transaction))

    return _command(request, db, user, Capability.FINANCE_ADJUSTMENT_APPROVE, payload.model_dump(mode="json"), handler,
                    {"adjustment_id": adjustment_id})


@router.post("/admin/ledger/adjustments/{adjustment_id}/reject", response_model=Envelope[LedgerAdjustmentDTO])
def reject_adjustment_admin(
    adjustment_id: str, payload: AdjustmentReject, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    """W17 (proposed): close a pending adjustment request with a reason."""

    def handler(caps: frozenset[Capability]) -> CommandResult:
        adjustment = _adjustment_by_public_id(db, adjustment_id)
        rejected = wallet_service.reject_adjustment(
            db, actor_user_id=user.id, actor_capabilities=caps, adjustment_request_id=adjustment.id,
            expected_version=payload.expected_version, reason=payload.reason,
        )
        return _ok(200, _adjustment_dto(db, rejected))

    return _command(request, db, user, Capability.FINANCE_ADJUSTMENT_APPROVE, payload.model_dump(mode="json"), handler,
                    {"adjustment_id": adjustment_id})


@router.post("/admin/ledger/adjustments/{adjustment_id}/withdraw", response_model=Envelope[LedgerAdjustmentDTO])
def withdraw_adjustment_admin(
    adjustment_id: str, payload: AdjustmentWithdraw, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    """W17a (proposed, Q49): the requester withdraws their own pending adjustment request."""

    def handler(caps: frozenset[Capability]) -> CommandResult:
        adjustment = _adjustment_by_public_id(db, adjustment_id)
        withdrawn = wallet_service.withdraw_adjustment(
            db, actor_user_id=user.id, actor_capabilities=caps, adjustment_request_id=adjustment.id,
            expected_version=payload.expected_version, reason=payload.reason,
        )
        return _ok(200, _adjustment_dto(db, withdrawn))

    return _command(request, db, user, Capability.FINANCE_ADJUSTMENT, payload.model_dump(mode="json"), handler,
                    {"adjustment_id": adjustment_id})


# --- W9-W10, W20: reports ------------------------------------------------------------------------------------


@router.get("/admin/finance/reports/{report}", response_model=Envelope[FinanceReportDTO])
def finance_report(
    report: str,
    from_: date = Query(alias="from"),
    to: date = Query(),
    corridor_id: str | None = Query(default=None),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_REPORTS)
        if report not in FINANCE_REPORTS:
            raise DomainError(ErrorCode.NOT_FOUND)
        start, end = _day_bounds(from_, to)
        if corridor_id is not None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "corridor_id", "reason": "available_with_bookings_wave2"})
        if report == "legacy_calculated_fee":
            raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "legacy_views_wave5"})
        pg = db.get_bind().dialect.name == "postgresql"
        if report == "calculated_commission":
            created = WalletHold.created_at
            day = cast(func.timezone("Asia/Tashkent", created), Date) if pg else func.date(created)
            query = select(day.label("d"), func.sum(WalletHold.amount_minor), func.count()).where(created >= start, created < end)
        else:
            kind = {"commission_revenue": "commission_capture", "cash_inflows": "topup", "reversals": "commission_reversal"}[report]
            created = LedgerTransaction.created_at
            day = cast(func.timezone("Asia/Tashkent", created), Date) if pg else func.date(created)
            query = (
                select(day.label("d"), func.sum(LedgerEntry.amount_minor), func.count(func.distinct(LedgerTransaction.id)))
                .join(LedgerEntry, LedgerEntry.transaction_id == LedgerTransaction.id)
                .where(LedgerTransaction.reference_kind == kind, LedgerEntry.direction == "debit", created >= start, created < end)
            )
        rows = db.execute(query.group_by("d").order_by("d")).all()
        data = FinanceReportDTO(
            report=report,
            period={"from": from_, "to": to},
            rows=[{"date": d if isinstance(d, date) else date.fromisoformat(str(d)), "corridor": None,
                   "amount_minor": int(total or 0), "count": int(count)} for d, total, count in rows],
            totals={"amount_minor": sum(int(t or 0) for _, t, _ in rows), "count": sum(int(c) for _, _, c in rows)},
        )
        return JSONResponse(_envelope(_dump(data)))

    return _read(db, run)


@router.get("/admin/finance/reconciliation", response_model=Envelope[ReconciliationDTO])
def finance_reconciliation(
    run_date: date | None = Query(default=None, alias="date"),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Reads a stored run only (BR #9). Runs are produced by ``wallet.service.run_reconciliation``
    (worker, or ``python -m app.modules.wallet.checks reconcile``); a missing run is 404."""

    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_REPORTS)
        target = run_date or utc_now().date()
        stored = db.execute(select(ReconciliationRun).where(ReconciliationRun.run_date == target)).scalar_one_or_none()
        if stored is None:
            raise DomainError(ErrorCode.NOT_FOUND, details={"reason": "reconciliation_not_run", "date": target.isoformat()})
        details = stored.details or {}
        data = ReconciliationDTO(date=target, wallets_checked=stored.wallets_checked,
                                 mismatches=details.get("mismatches", []),
                                 unbalanced_transactions=details.get("unbalanced_transactions", []),
                                 overdraft_wallets=details.get("overdraft_wallets", []),
                                 orphan_postings=details.get("orphan_postings", []))
        return JSONResponse(_envelope(_dump(data)))

    return _read(db, run)


@router.get("/admin/finance/signals/split-adjustments", response_model=Envelope[list[SplitAdjustmentSignalDTO]])
def split_adjustment_signals(
    from_: date = Query(alias="from"),
    to: date = Query(),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """W20 (proposed, decision 30): possible splitting of adjustments around the two-person threshold."""

    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_REPORTS)
        start, end = _day_bounds(from_, to)
        signals = wallet_service.split_adjustment_signals(db, since=start, until=end)
        data = []
        for signal in signals:
            wallet = db.get(WalletAccount, signal.wallet_id)
            publics = db.execute(
                select(LedgerAdjustmentRequest.id, LedgerAdjustmentRequest.public_id)
                .where(LedgerAdjustmentRequest.id.in_(signal.adjustment_request_ids))
            ).all()
            by_id = dict(publics)
            data.append(SplitAdjustmentSignalDTO(
                wallet_id=format_public_id(PublicIdPrefix.WALLET, wallet.public_id),
                requested_by=_user_ref(db, signal.requested_by),
                window_start=signal.window_start,
                window_end=signal.window_end,
                count=signal.count,
                amount_minor=signal.amount_minor,
                adjustment_ids=[format_public_id(PublicIdPrefix.LEDGER_ADJUSTMENT, by_id[i]) for i in signal.adjustment_request_ids],
            ))
        return JSONResponse(_envelope(_dump(data)))

    return _read(db, run)


# --- W11-W15, W19: commission ------------------------------------------------------------------------------------


@router.get("/commission/quote", response_model=Envelope[FeeQuoteDTO])
def commission_quote(
    service_type: ServiceType = Query(),
    total_minor: int = Query(ge=0),
    corridor_id: str | None = Query(default=None),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.PROPOSAL_SUBMIT_AS_DRIVER)
        internal = _corridor_internal_id(db, corridor_id)
        if internal is not None:
            from app.modules.geo.models import ServiceCorridor

            state = db.execute(select(ServiceCorridor.rollout_state).where(ServiceCorridor.id == internal)).scalar_one()
            if state in ("draft", "closed"):
                raise DomainError(ErrorCode.CORRIDOR_NOT_ACTIVE)
        quote = wallet_service.quote_fee(db, corridor_id=internal, service_type=service_type, total_minor=total_minor)
        dto = FeeQuoteDTO(policy_id=quote.policy_public_id, policy_kind=quote.policy_kind, fee_bps=quote.fee_bps,
                          commission_minor=quote.commission_minor, net_minor=quote.net_minor, valid_until=None)
        return JSONResponse(_envelope(_dump(dto)))

    return _read(db, run)


@router.get("/admin/commission-policies", response_model=Envelope[list[CommissionPolicyDTO]])
def list_commission_policies(
    active_at: datetime | None = Query(default=None),
    kind: CommissionPolicyKind | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_COMMISSION_POLICY_VIEW)
        if active_at is not None and active_at.tzinfo is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "active_at"})
        scope = f"GET /admin/commission-policies|{active_at.isoformat() if active_at else '*'}|{kind.value if kind else '*'}"
        rows = wallet_service.list_policies(db, active_at=active_at, kind=kind, after_id=_decode_after(cursor, scope), limit=limit)
        next_cursor = _next_cursor(rows[-1].id if rows else None, scope, len(rows), limit)
        return JSONResponse(_envelope(_dump([_policy_dto(db, row) for row in rows]), next_cursor=next_cursor, limit=limit))

    return _read(db, run)


@router.post("/admin/commission-policies", response_model=Envelope[CommissionPolicyDTO], status_code=201)
def create_commission_policy(
    payload: CommissionPolicyCreate, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    def handler(caps: frozenset[Capability]) -> CommandResult:
        corridor = _corridor_internal_id(db, payload.scope.corridor_id)
        policy = wallet_service.create_policy(
            db, actor_user_id=user.id, actor_capabilities=caps, kind=payload.kind, corridor_id=corridor,
            service_type=payload.scope.service_type, fee_bps=payload.fee_bps, effective_from=payload.effective_from,
            effective_to=payload.effective_to, campaign_name=payload.campaign_name, reason=payload.reason,
            corridor_public_id=payload.scope.corridor_id,
        )
        return _ok(201, _policy_dto(db, policy))

    return _command(request, db, user, Capability.FINANCE_COMMISSION_POLICY_MANAGE, payload.model_dump(mode="json"), handler)


@router.get("/admin/commission-policies/{policy_id}", response_model=Envelope[CommissionPolicyDTO])
def get_commission_policy(
    policy_id: str, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
) -> JSONResponse:
    def run() -> JSONResponse:
        _require(db, user, Capability.FINANCE_COMMISSION_POLICY_VIEW)
        policy = _by_public_id(db, CommissionPolicy, policy_id, PublicIdPrefix.COMMISSION_POLICY)
        return JSONResponse(_envelope(_dump(_policy_dto(db, policy))))

    return _read(db, run)


@router.post("/admin/commission-policies/{policy_id}/end", response_model=Envelope[CommissionPolicyDTO])
def end_commission_policy(
    policy_id: str, payload: CommissionPolicyEnd, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    def handler(caps: frozenset[Capability]) -> CommandResult:
        policy = _by_public_id(db, CommissionPolicy, policy_id, PublicIdPrefix.COMMISSION_POLICY)
        policy = wallet_service.end_policy(
            db, actor_user_id=user.id, actor_capabilities=caps, policy_id=policy.id,
            expected_version=payload.expected_version, effective_to=payload.effective_to, reason=payload.reason,
        )
        return _ok(200, _policy_dto(db, policy))

    return _command(request, db, user, Capability.FINANCE_COMMISSION_POLICY_MANAGE, payload.model_dump(mode="json"),
                    handler, {"policy_id": policy_id})


@router.post("/admin/commission-policies/{policy_id}/confirm", response_model=Envelope[CommissionPolicyDTO])
def confirm_commission_policy(
    policy_id: str, payload: CommissionPolicyConfirm, request: Request,
    user: User = Depends(get_current_active_user), db: Session = Depends(get_db),
) -> JSONResponse:
    """W19 (proposed, decision 28): super_admin confirms the migration-seeded global rate once."""

    def handler(caps: frozenset[Capability]) -> CommandResult:
        policy = _by_public_id(db, CommissionPolicy, policy_id, PublicIdPrefix.COMMISSION_POLICY)
        policy = wallet_service.confirm_policy(
            db, actor_user_id=user.id, actor_capabilities=caps, policy_id=policy.id,
            expected_version=payload.expected_version, reason=payload.reason,
        )
        return _ok(200, _policy_dto(db, policy))

    return _command(request, db, user, Capability.FINANCE_COMMISSION_POLICY_MANAGE, payload.model_dump(mode="json"),
                    handler, {"policy_id": policy_id})


def wallet_tables_present(session: Session) -> bool:
    """Helper for readiness wiring: the wallet schema is migrated."""
    return table_exists(session, "wallet_accounts")
