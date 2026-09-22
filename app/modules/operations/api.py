"""API v2 operations and growth router: O1-O3, O4-O7 (API_V2_CONTRACT §13). Mounted by the integrator.

``GET /public/listings/{token}`` is the only unauthenticated route of this module: it answers with the PII-free
page of §20.2 and, for an unknown, revoked, expired or closed link, with a plain 404 (a share token is a secret,
ADR-0018, so the answer must not reveal that it once existed).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, Path, Query, Request
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
)
from app.contracts.dto import MAX_PAGE_LIMIT, EmptyDTO, Envelope, PageMeta
from app.contracts.enums import OpsQueue
from app.contracts.operations import OPS_QUEUE_DEFAULT_LIMIT, OPS_QUEUE_MAX_LIMIT
from app.modules.marketplace.schemas import ListingCreate, ListingDTO
from app.modules.marketplace.views import listing_dto
from app.modules.operations import service
from app.modules.operations.schemas import (
    KpiDTO,
    LegacyOrderViewDTO,
    KpiValueDTO,
    ListingOnBehalfCreate,
    OpsQueueItemDTO,
    ProviderQuotaDTO,
    PublicListingPageDTO,
    ShareLinkCreate,
    ShareLinkDTO,
    SloDTO,
    SloValueDTO,
)

router = APIRouter(tags=["v2 Operations"])
logger = logging.getLogger(__name__)


class ListingOnBehalfBody(ListingCreate, ListingOnBehalfCreate):
    """O7: A1's listing body plus the real owner and the consent reference (§20.2)."""


# --- O1-O3 share links ---------------------------------------------------------------------------------------


@router.post("/listings/{listing_id}/share-links", response_model=Envelope[ShareLinkDTO], status_code=201,
             responses=ERROR_RESPONSES)
def create_share_link(
    listing_id: str, body: ShareLinkCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> ShareLinkDTO:
        created = service.create_share_link(
            session, listing_public_id_value=listing_id, actor_user_id=user_id,
            channel=body.channel.value, ttl_hours=body.ttl_hours,
        )
        return ShareLinkDTO(
            id=service.share_link_public_id(created.row),
            channel=body.channel,
            url=created.url,
            share_text=created.share_text,
            expires_at=created.row.expires_at,
            created_at=created.row.created_at,
        )

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="share_link")


@router.delete("/share-links/{share_link_id}", response_model=Envelope[EmptyDTO], responses=ERROR_RESPONSES)
def revoke_share_link(
    share_link_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> Envelope[EmptyDTO]:
    service.revoke_share_link(session, share_link_public_id_value=share_link_id, actor_user_id=user_id)
    session.commit()
    return Envelope[EmptyDTO](data=EmptyDTO())


@router.get("/public/listings/{token}", response_model=Envelope[PublicListingPageDTO], responses=ERROR_RESPONSES)
def public_listing_page(
    token: str = Path(max_length=512), session: Session = Depends(get_session)
) -> Envelope[PublicListingPageDTO]:
    page = service.open_public_listing(session, token=token)
    session.commit()  # the open counter is the only write
    return Envelope[PublicListingPageDTO](
        data=PublicListingPageDTO(
            kind=page.kind,
            service_type=page.service_type,
            origin_stop_name=page.origin_stop_name,
            destination_stop_name=page.destination_stop_name,
            departure_date=page.departure_date,
            departure_window_start=page.departure_window_start,
            departure_window_end=page.departure_window_end,
            timezone=page.timezone,
            price_basis=page.price_basis,
            unit_price_minor=page.unit_price_minor,
            quantity=page.quantity,
            total_minor=page.total_minor,
            currency=page.currency,
            status_open=page.status_open,
            cta=page.cta,
        )
    )


# --- O4-O6 operator queues and metrics -------------------------------------------------------------------------


@router.get("/admin/ops/queues/{queue}", response_model=Envelope[list[OpsQueueItemDTO]], responses=ERROR_RESPONSES)
def ops_queue(
    queue: OpsQueue,
    corridor_id: str | None = Query(default=None, max_length=64),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=OPS_QUEUE_DEFAULT_LIMIT, ge=1, le=OPS_QUEUE_MAX_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[OpsQueueItemDTO]]:
    scope = page_scope(f"GET /admin/ops/queues/{queue.value}", corridor_id=corridor_id)
    items = service.ops_queue(
        session, actor_user_id=user_id, queue=queue.value, corridor_id=corridor_id,
        after_id=decode_id_cursor(cursor, scope), limit=min(limit, OPS_QUEUE_MAX_LIMIT),
    )
    return Envelope[list[OpsQueueItemDTO]](
        data=[
            OpsQueueItemDTO(queue=queue, item_type=item.item_type, item_id=item.item_id, corridor=item.corridor,
                            age_minutes=item.age_minutes, summary=item.summary)
            for item in items
        ],
        meta=PageMeta(next_cursor=None, limit=limit),
    )


@router.get("/admin/metrics/kpi", response_model=Envelope[KpiDTO], responses=ERROR_RESPONSES)
def kpi(
    corridor_id: str | None = Query(default=None, max_length=64),
    date_from: str | None = Query(default=None, alias="from", max_length=10),
    date_to: str | None = Query(default=None, alias="to", max_length=10),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[KpiDTO]:
    report = service.kpi_report(
        session, actor_user_id=user_id, date_from=_as_date(date_from, "from"), date_to=_as_date(date_to, "to"),
        corridor_id=corridor_id,
    )
    return Envelope[KpiDTO](
        data=KpiDTO(
            date_from=report.date_from.isoformat(),
            date_to=report.date_to.isoformat(),
            corridor_id=report.corridor_id,
            metrics=[
                KpiValueDTO(metric=value.metric, numerator=value.numerator, denominator=value.denominator,
                            value=value.value, target=value.target, small_sample=value.small_sample)
                for value in report.metrics
            ],
            missing_metrics=report.missing_metrics,
            computed_at=report.computed_at,
        )
    )


@router.get("/admin/metrics/slo", response_model=Envelope[SloDTO], responses=ERROR_RESPONSES)
def slo(
    date_from: str | None = Query(default=None, alias="from", max_length=10),
    date_to: str | None = Query(default=None, alias="to", max_length=10),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[SloDTO]:
    report = service.slo_report(
        session, actor_user_id=user_id, date_from=_as_date(date_from, "from"), date_to=_as_date(date_to, "to")
    )
    return Envelope[SloDTO](
        data=SloDTO(
            date_from=report.date_from.isoformat(),
            date_to=report.date_to.isoformat(),
            indicators=[
                SloValueDTO(name=item.name, value=item.value, target=item.target, sample_size=item.sample_size,
                            measured=item.measured, note=item.note)
                for item in report.indicators
            ],
        )
    )


# --- O8 legacy read-only projection (A10b, wave 5; Q4, AC37) ---------------------------------------------------


@router.get("/admin/legacy-orders", response_model=Envelope[list[LegacyOrderViewDTO]], responses=ERROR_RESPONSES)
def legacy_orders(
    status: str | None = Query(default=None, max_length=32),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=service.LEGACY_ORDERS_MAX_LIMIT),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[LegacyOrderViewDTO]]:
    """O8: v1 orders, read-only (Q4). There is no v2 write path for these rows - a mutation attempt on the
    projection is refused by the database itself with 409 LEGACY_OBJECT_READ_ONLY."""
    scope = page_scope("GET /admin/legacy-orders", status=status)
    rows = service.legacy_orders(
        session, actor_user_id=user_id, status=status, after_id=decode_id_cursor(cursor, scope), limit=limit + 1
    )
    page, more = rows[:limit], len(rows) > limit
    return Envelope[list[LegacyOrderViewDTO]](
        data=[_legacy_dto(row) for row in page],
        meta=PageMeta(next_cursor=encode_page_cursor([page[-1].legacy_order_id], scope) if more else None, limit=limit),
    )


@router.get("/admin/legacy-orders/{legacy_order_number}", response_model=Envelope[LegacyOrderViewDTO],
            responses=ERROR_RESPONSES)
def legacy_order(
    legacy_order_number: str = Path(max_length=64),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[LegacyOrderViewDTO]:
    row = service.legacy_order(session, actor_user_id=user_id, legacy_order_number=legacy_order_number)
    return Envelope[LegacyOrderViewDTO](data=_legacy_dto(row))


def _legacy_dto(row: service.LegacyOrderRow) -> LegacyOrderViewDTO:
    return LegacyOrderViewDTO(
        legacy_order_number=row.legacy_order_number, status=row.status, route_summary=row.route_summary,
        final_price_minor=row.final_price_minor, legacy_calculated_fee_minor=row.legacy_calculated_fee_minor,
        flags=list(row.flags), created_at=row.created_at, updated_at=row.updated_at,
    )


@router.get("/admin/metrics/provider-quota", response_model=Envelope[list[ProviderQuotaDTO]],
            responses=ERROR_RESPONSES)
def provider_quota(
    day: str | None = Query(default=None, max_length=10),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> Envelope[list[ProviderQuotaDTO]]:
    """§10.8: today's map/routing consumption with the 70 % warn / 85 % restrict thresholds.

    An empty list means the adapter made no billable call (in production the routing provider is off by Q24), not
    that consumption is unknown.
    """
    quotas = service.provider_quota(session, actor_user_id=user_id, day=_as_date(day, "day"))
    return Envelope[list[ProviderQuotaDTO]](
        data=[
            ProviderQuotaDTO(provider=q.provider, day=q.day.isoformat(), calls=q.calls, credits=q.credits,
                             failures=q.failures, limit=q.limit, ratio=q.ratio, state=q.state, estimated=q.estimated)
            for q in quotas
        ]
    )


# --- O7 listing on behalf of an owner ---------------------------------------------------------------------------


@router.post("/admin/listings/on-behalf", response_model=Envelope[ListingDTO], status_code=201, responses=ERROR_RESPONSES)
def create_listing_on_behalf(
    body: ListingOnBehalfBody, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id), session: Session = Depends(get_session),
) -> JSONResponse:
    def handler() -> ListingDTO:
        listing = service.create_listing_on_behalf(
            session, actor_user_id=user_id, owner_public_id=body.owner_user_id,
            consent_reference=body.consent_reference,
            data=ListingCreate.model_validate(body.model_dump(mode="json", exclude={"owner_user_id", "consent_reference"})),
        )
        return listing_dto(session, listing, viewer_user_id=listing.owner_user_id)

    return run_command(request, session, actor_user_id=user_id, idempotency_key=idempotency_key, body=body,
                       handler=handler, success_status=201, resource_type="listing")


def _as_date(value: str | None, field: str):  # noqa: ANN202 - date | None
    from datetime import date

    from app.contracts.errors import DomainError, ErrorCode

    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": field, "reason": "expected_yyyy_mm_dd"}) from exc
