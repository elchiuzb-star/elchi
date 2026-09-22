"""API v2 listings (L1-L8) and proposals (P1-P7) router. Mounted by the integrator under ``/api/v2``.

P8 accept belongs to the bookings module (A4).
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts.dto import (
    MAX_PAGE_LIMIT,
    Envelope,
    PageMeta,
    ParcelPolicyDTO,
    ParcelPolicyItemDTO,
    ParcelPolicyVersionCreate,
    ParcelPolicyVersionDTO,
    VersionedCommand,
)
from app.contracts.enums import Capability, ListingKind, ListingStatus, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import ensure_aware_utc
from app.modules.identity import service as identity_service
from app.modules.identity.web import (
    ERROR_RESPONSES,
    current_user_id,
    decode_id_cursor,
    decode_time_id_cursor,
    encode_page_cursor,
    get_session,
    optional_user_id,
    page_scope,
    run_command,
    run_versioned,
)
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import (
    DirectionPreviewDTO,
    ListingCancel,
    ListingCommand,
    ListingCreate,
    ListingDTO,
    ListingOfferDTO,
    ListingPatch,
    ListingPublicDTO,
    ProposalCounter,
    ProposalCreate,
    PointEndInput,
    ProposalDecision,
    ProposalThreadDTO,
)
from app.api.v2.web import to_api_warnings
from app.modules.marketplace.models import ParcelPolicyItem, ParcelPolicyVersion
from app.modules.marketplace.views import (
    direction_preview_dto,
    listing_dto,
    listing_offer_dtos,
    listing_public_dto,
    thread_dto,
)

router = APIRouter(tags=["v2 Marketplace"])


logger = logging.getLogger(__name__)

# Contact-filter hits of the running command (R2-b, Q45); set by ``_recording_hits``.
_FILTER_HITS: ContextVar[list | None] = ContextVar("marketplace_filter_hits", default=None)


def _current_hits() -> list | None:
    return _FILTER_HITS.get()


def _with_warnings(build):  # noqa: ANN001, ANN202
    """Run a command that collects free-text warnings (R2, Q43); returns ``(dto, warnings)`` so the
    v2 runner writes them to ``Envelope.warnings`` (stored with the idempotent response)."""
    hits = _FILTER_HITS.get()
    if hits is not None:
        hits.clear()  # a deadlock retry re-runs the handler: keep only this attempt's hits
    warnings: list[dict] = []
    dto = build(warnings)
    return dto, to_api_warnings(warnings)


def _recording_hits(session: Session, runner, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
    """Persist contact-filter hits in their own committed transaction after the command, whatever its
    outcome: a domain 4xx rolls the command savepoint back, but the Q45 strike signal must survive (R2-b).
    An idempotent replay does not run the handler, so it records nothing twice."""
    hits: list = []
    token = _FILTER_HITS.set(hits)
    try:
        return runner(*args, **kwargs)
    finally:
        _FILTER_HITS.reset(token)
        if hits:
            try:
                marketplace_service.record_contact_filter_hits(session, hits)
                session.commit()
            except Exception:  # never mask the command's own outcome
                session.rollback()
                logger.exception("recording contact filter hits failed")

THREAD_STATES = r"^(open|accepted|closed)$"


def _contact_fields(dto: ListingDTO) -> list[str]:
    """Phone-bearing fields present in a full listing DTO (the only marketplace staff surface with phones:
    proposal threads are party-only and carry no phones for staff; offers are anonymized)."""
    parcel = dto.parcel
    if parcel is None:
        return []
    fields = [name for name, contact in (("parcel.sender.phone", parcel.sender), ("parcel.receiver.phone", parcel.receiver))
              if contact is not None and contact.phone]
    if parcel.photo is not None:  # Q6: a staff member opening the cargo photo is recorded like a phone view
        fields.append("parcel.photo")
    return fields


# --- listings -------------------------------------------------------------------------------------


@router.post("/listings", response_model=Envelope[ListingDTO], status_code=201, responses=ERROR_RESPONSES)
def create_listing(
    body: ListingCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
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
            lambda warnings: listing_dto(
                session,
                marketplace_service.create_listing(session, owner_user_id=user_id, data=body, warnings=warnings, filter_hits=_current_hits()),
                viewer_user_id=user_id,
            )
        ),
        success_status=201,
        resource_type="listing",
    )


@router.get("/directions/preview", response_model=Envelope[DirectionPreviewDTO], responses=ERROR_RESPONSES)
def preview_direction(
    origin_lat: float = Query(ge=-90, le=90),
    origin_lng: float = Query(ge=-180, le=180),
    origin_district_id: str = Query(min_length=1, max_length=64),
    destination_lat: float = Query(ge=-90, le=90),
    destination_lng: float = Query(ge=-180, le=180),
    destination_district_id: str = Query(min_length=1, max_length=64),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[DirectionPreviewDTO]:
    """Q88: can ELCHI carry someone between these two marked places, and along which road?

    The client asks before it builds a listing, so the person learns "these two places are not on an ELCHI
    route yet" while they can still move a pin - not after filling in a price. Read-only: it creates nothing
    and it runs the same resolution the create path runs, so the two cannot disagree.
    """
    del user_id  # authenticated read; the answer does not depend on who is asking
    preview = marketplace_service.preview_point_direction(
        session,
        origin=PointEndInput(lat=origin_lat, lng=origin_lng, district_id=origin_district_id),
        destination=PointEndInput(lat=destination_lat, lng=destination_lng, district_id=destination_district_id),
    )
    return Envelope[DirectionPreviewDTO](data=direction_preview_dto(session, preview))


@router.get("/listings/{listing_id}", response_model=Envelope[ListingDTO | ListingPublicDTO], responses=ERROR_RESPONSES)
def get_listing(
    listing_id: str, user_id: int | None = Depends(optional_user_id), session: Session = Depends(get_session)
) -> Envelope[ListingDTO | ListingPublicDTO]:
    listing = marketplace_service.get_listing_by_public_id(session, listing_id)
    is_staff = user_id is not None and identity_service.get_capabilities(session, user_id).has(Capability.OPS_VIEW)
    if user_id == listing.owner_user_id or is_staff:
        dto = listing_dto(session, listing, viewer_user_id=user_id)
        if is_staff and user_id != listing.owner_user_id:
            fields = _contact_fields(dto)
            if fields:  # BR M2: staff phone visibility is audited (no values); owner views are not
                marketplace_service.record_staff_listing_contact_view(
                    session, actor_user_id=user_id, listing_ids=[dto.id], surface="L2", fields=fields
                )
                session.commit()
        return Envelope[ListingDTO | ListingPublicDTO](data=dto)
    if listing.status == ListingStatus.DRAFT.value:
        raise DomainError(ErrorCode.NOT_FOUND)
    return Envelope[ListingDTO | ListingPublicDTO](data=listing_public_dto(session, listing))


@router.patch("/listings/{listing_id}", response_model=Envelope[ListingDTO], responses=ERROR_RESPONSES)
def patch_listing(
    listing_id: str, body: ListingPatch, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[ListingDTO]:
    dto, warnings = _recording_hits(
        session,
        run_versioned,
        session,
        lambda: _with_warnings(
            lambda warnings: listing_dto(
                session,
                marketplace_service.patch_listing(
                    session, listing_public_id=listing_id, actor_user_id=user_id, data=body, warnings=warnings, filter_hits=_current_hits()
                ),
                viewer_user_id=user_id,
            )
        ),
    )
    return Envelope[ListingDTO](data=dto, warnings=warnings or None)


def _listing_command(
    command: str,
    listing_id: str,
    body: ListingCommand,
    request: Request,
    idempotency_key: str | None,
    user_id: int,
    session: Session,
) -> JSONResponse:
    operation = {
        "publish": marketplace_service.publish_listing,
        "pause": marketplace_service.pause_listing,
        "resume": marketplace_service.resume_listing,
    }[command]
    return _recording_hits(
        session,
        run_command,
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: listing_dto(
            session,
            operation(session, listing_public_id=listing_id, actor_user_id=user_id, expected_version=body.expected_version),
            viewer_user_id=user_id,
        ),
        resource_type="listing",
    )


@router.post("/listings/{listing_id}/publish", response_model=Envelope[ListingDTO], responses=ERROR_RESPONSES)
def publish_listing(
    listing_id: str,
    body: ListingCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return _listing_command("publish", listing_id, body, request, idempotency_key, user_id, session)


@router.post("/listings/{listing_id}/pause", response_model=Envelope[ListingDTO], responses=ERROR_RESPONSES)
def pause_listing(
    listing_id: str,
    body: ListingCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return _listing_command("pause", listing_id, body, request, idempotency_key, user_id, session)


@router.post("/listings/{listing_id}/resume", response_model=Envelope[ListingDTO], responses=ERROR_RESPONSES)
def resume_listing(
    listing_id: str,
    body: ListingCommand,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return _listing_command("resume", listing_id, body, request, idempotency_key, user_id, session)


@router.post("/listings/{listing_id}/cancel", response_model=Envelope[ListingDTO], responses=ERROR_RESPONSES)
def cancel_listing(
    listing_id: str,
    body: ListingCancel,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
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
            lambda warnings: listing_dto(
                session,
                marketplace_service.cancel_listing(
                    session,
                    listing_public_id=listing_id,
                    actor_user_id=user_id,
                    expected_version=body.expected_version,
                    reason_code=body.reason_code,
                    comment=body.comment,
                    warnings=warnings, filter_hits=_current_hits(),
                ),
                viewer_user_id=user_id,
            )
        ),
        resource_type="listing",
    )


@router.get("/me/listings", response_model=Envelope[list[ListingDTO]], responses=ERROR_RESPONSES)
def list_my_listings(
    status: ListingStatus | None = Query(default=None),
    kind: ListingKind | None = Query(default=None),
    service_type: ServiceType | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[ListingDTO]]:
    filters = {
        "status": status.value if status else None,
        "kind": kind.value if kind else None,
        "service_type": service_type.value if service_type else None,
    }
    scope = page_scope("GET /me/listings", **filters)
    rows = marketplace_service.list_owner_listings(
        session, user_id, **filters, before=decode_time_id_cursor(cursor, scope), limit=limit + 1
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_page_cursor([page[-1].created_at, page[-1].id], scope) if more else None
    return Envelope[list[ListingDTO]](
        data=[listing_dto(session, listing, viewer_user_id=user_id) for listing in page],
        meta=PageMeta(next_cursor=next_cursor, limit=limit),
    )


# --- proposals ------------------------------------------------------------------------------------


@router.post(
    "/listings/{listing_id}/proposals", response_model=Envelope[ProposalThreadDTO], status_code=201, responses=ERROR_RESPONSES
)
def submit_proposal(
    listing_id: str,
    body: ProposalCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
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
            lambda warnings: thread_dto(
                session,
                marketplace_service.submit_proposal(
                    session, listing_public_id=listing_id, actor_user_id=user_id, data=body, warnings=warnings, filter_hits=_current_hits()
                ),
                viewer_user_id=user_id,
            )
        ),
        success_status=201,
        resource_type="proposal_thread",
    )


def _thread_page(
    session: Session, threads: list, limit: int, scope: str, viewer_user_id: int
) -> Envelope[list[ProposalThreadDTO]]:
    page, more = threads[:limit], len(threads) > limit
    next_cursor = encode_page_cursor([page[-1].id], scope) if more else None
    return Envelope[list[ProposalThreadDTO]](
        data=[thread_dto(session, thread, viewer_user_id=viewer_user_id) for thread in page],
        meta=PageMeta(next_cursor=next_cursor, limit=limit),
    )


@router.get("/listings/{listing_id}/proposals", response_model=Envelope[list[ProposalThreadDTO]], responses=ERROR_RESPONSES)
def list_listing_proposals(
    listing_id: str,
    state: str | None = Query(default=None, pattern=THREAD_STATES),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[ProposalThreadDTO]]:
    listing = marketplace_service.get_listing_by_public_id(session, listing_id)
    if listing.owner_user_id != user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    scope = page_scope("GET /listings/{listing_id}/proposals", listing=listing_id, state=state)
    threads = marketplace_service.list_listing_threads(
        session, listing.id, state=state, before_id=decode_id_cursor(cursor, scope), limit=limit + 1
    )
    return _thread_page(session, threads, limit, scope, user_id)


@router.get("/proposals/{thread_id}", response_model=Envelope[ProposalThreadDTO], responses=ERROR_RESPONSES)
def get_proposal(
    thread_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[ProposalThreadDTO]:
    thread = marketplace_service.get_thread_for_party(session, thread_id, user_id)
    return Envelope[ProposalThreadDTO](data=thread_dto(session, thread, viewer_user_id=user_id, include_versions=True))


@router.get("/me/proposals", response_model=Envelope[list[ProposalThreadDTO]], responses=ERROR_RESPONSES)
def list_my_proposals(
    state: str | None = Query(default=None, pattern=THREAD_STATES),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[ProposalThreadDTO]]:
    scope = page_scope("GET /me/proposals", state=state)
    threads = marketplace_service.list_user_threads(
        session, user_id, state=state, before_id=decode_id_cursor(cursor, scope), limit=limit + 1
    )
    return _thread_page(session, threads, limit, scope, user_id)


@router.post("/proposals/{thread_id}/counter", response_model=Envelope[ProposalThreadDTO], responses=ERROR_RESPONSES)
def counter_proposal(
    thread_id: str,
    body: ProposalCounter,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
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
            lambda warnings: thread_dto(
                session,
                marketplace_service.counter_proposal(
                    session, thread_public_id_value=thread_id, actor_user_id=user_id, data=body, warnings=warnings, filter_hits=_current_hits()
                ),
                viewer_user_id=user_id,
            )
        ),
        resource_type="proposal_thread",
    )


def _decision(
    command: str, thread_id: str, body: ProposalDecision, request: Request, idempotency_key: str | None, user_id: int, session: Session
) -> JSONResponse:
    operation = marketplace_service.reject_proposal if command == "reject" else marketplace_service.withdraw_proposal
    return _recording_hits(
        session,
        run_command,
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: thread_dto(
            session,
            operation(
                session,
                thread_public_id_value=thread_id,
                actor_user_id=user_id,
                expected_revision=body.expected_revision,
                reason_code=body.reason_code,
            ),
            viewer_user_id=user_id,
        ),
        resource_type="proposal_thread",
    )


@router.post("/proposals/{thread_id}/reject", response_model=Envelope[ProposalThreadDTO], responses=ERROR_RESPONSES)
def reject_proposal(
    thread_id: str,
    body: ProposalDecision,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return _decision("reject", thread_id, body, request, idempotency_key, user_id, session)


@router.post("/proposals/{thread_id}/withdraw", response_model=Envelope[ProposalThreadDTO], responses=ERROR_RESPONSES)
def withdraw_proposal(
    thread_id: str,
    body: ProposalDecision,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return _decision("withdraw", thread_id, body, request, idempotency_key, user_id, session)


@router.get("/listings/{listing_id}/offers", response_model=Envelope[list[ListingOfferDTO]], responses=ERROR_RESPONSES)
def list_listing_offers(
    listing_id: str,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> Envelope[list[ListingOfferDTO]]:
    """R1 open auction (driver view): anonymized current driver offers on a client request."""
    scope = page_scope("GET /listings/{listing_id}/offers", listing=listing_id)
    offers = marketplace_service.list_listing_offers(
        session,
        listing_public_id=listing_id,
        viewer_user_id=user_id,
        after_thread_id=decode_id_cursor(cursor, scope),
        limit=limit + 1,
    )
    page, more = offers[:limit], len(offers) > limit
    next_cursor = encode_page_cursor([page[-1].thread_id], scope) if more else None
    return Envelope[list[ListingOfferDTO]](
        data=listing_offer_dtos(session, page), meta=PageMeta(next_cursor=next_cursor, limit=limit)
    )


# --- §5.2 parcel policy: prohibited and restricted items (wave 7) -------------------------------------------------


def _policy_item_dto(item: ParcelPolicyItem) -> ParcelPolicyItemDTO:
    return ParcelPolicyItemDTO(
        code=item.code, category=item.category, applies_to=item.applies_to, title=item.title_uz,
        description=item.description_uz, legal_basis=item.legal_basis, source_ref=item.source_ref,
        source_checked_on=item.source_checked_on.isoformat() if item.source_checked_on else None,
    )


POLICY_MISSING_NOTICE = (
    "Taqiqlangan jo'natmalar ro'yxati hali tasdiqlanmagan. Yangi pochta e'lonlari va bronlari yopiq; "
    "mavjud bronlar davom etadi."
)
POLICY_ACTIVE_NOTICE = (
    "Quyidagi jo'natmalarni yuborib bo'lmaydi. Ro'yxat operator tasdiqlagan versiyadan olinadi; "
    "har band manbasi bilan ko'rsatilgan."
)


@router.get("/parcel-policy", response_model=Envelope[ParcelPolicyDTO], responses=ERROR_RESPONSES)
def parcel_policy(session: Session = Depends(get_session)) -> Envelope[ParcelPolicyDTO]:
    """§5.2 what may not be sent. Readable without authentication: a sender must see it before writing a listing.

    ``approved=false`` says the list is not published yet - it never means "everything is allowed".
    """
    view = service.active_parcel_policy(session)
    return Envelope[ParcelPolicyDTO](
        data=ParcelPolicyDTO(
            approved=view.approved, label=view.label, effective_from=view.effective_from,
            items=[_policy_item_dto(item) for item in view.items],
            notice=POLICY_ACTIVE_NOTICE if view.approved else POLICY_MISSING_NOTICE,
        )
    )


@router.get("/admin/parcel-policies", response_model=Envelope[list[ParcelPolicyVersionDTO]], responses=ERROR_RESPONSES)
def list_parcel_policies(
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[list[ParcelPolicyVersionDTO]]:
    versions = service.list_parcel_policy_versions(session, actor_user_id=user_id)
    return Envelope[list[ParcelPolicyVersionDTO]](
        data=[_policy_version_dto(session, version) for version in versions]
    )


@router.post("/admin/parcel-policies", response_model=Envelope[ParcelPolicyVersionDTO], status_code=201,
             responses=ERROR_RESPONSES)
def create_parcel_policy(
    body: ParcelPolicyVersionCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    """Draft a policy version (`platform.policy_manage`, super_admin). A draft applies to nobody."""

    def handler() -> ParcelPolicyVersionDTO:
        version = service.create_parcel_policy_version(
            session, actor_user_id=user_id, label=body.label, source_note=body.source_note, items=body.items
        )
        return _policy_version_dto(session, version)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="parcel_policy")


@router.post("/admin/parcel-policies/{policy_id}/confirm", response_model=Envelope[ParcelPolicyVersionDTO],
             responses=ERROR_RESPONSES)
def confirm_parcel_policy(
    body: VersionedCommand, request: Request, policy_id: str = Path(max_length=64),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    """Approve a drafted policy. The author cannot approve their own draft (Q17/Q49 spirit)."""

    def handler() -> ParcelPolicyVersionDTO:
        version = service.confirm_parcel_policy_version(
            session, actor_user_id=user_id, policy_public_id=policy_id, expected_version=body.expected_version
        )
        return _policy_version_dto(session, version)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, resource_type="parcel_policy")


def _policy_version_dto(session: Session, version: ParcelPolicyVersion) -> ParcelPolicyVersionDTO:
    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

    count = session.execute(
        sa_select(sa_func.count(ParcelPolicyItem.id)).where(ParcelPolicyItem.policy_version_id == version.id)
    ).scalar_one()
    return ParcelPolicyVersionDTO(
        id=service.parcel_policy_public_id(version), label=version.label, status=version.status,
        item_count=int(count),
        created_by=identity_service.user_public_id(session, version.created_by),
        confirmed_by=identity_service.user_public_id(session, version.confirmed_by) if version.confirmed_by else None,
        confirmed_at=ensure_aware_utc(version.confirmed_at) if version.confirmed_at else None,
        effective_from=ensure_aware_utc(version.effective_from) if version.effective_from else None,
        version=version.version,
    )
