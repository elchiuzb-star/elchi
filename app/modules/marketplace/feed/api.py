"""API v2 feed router (M1-M5, API_V2_CONTRACT §6). Mounted by the integrator under ``/api/v2``."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v2.web import (
    ERROR_RESPONSES,
    current_user_id,
    decode_time_id_cursor,
    encode_page_cursor,
    envelope_body,
    get_session,
    page_scope,
    run_command,
    run_versioned,
)
from app.contracts.cursor import decode_cursor
from app.contracts.dto import MAX_PAGE_LIMIT, Envelope, PageMeta
from app.contracts.enums import FeedSide, FeedSort, ReputationLabel, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.feed import FEED_DEFAULT_LIMIT, FEED_MAX_LIMIT
from app.contracts.timeutil import ensure_aware_utc, parse_iso_datetime, to_iso_utc
from app.contracts.trust import ReputationSummary
from app.core.config import cursor_signing_secret, settings
from app.modules.marketplace.feed import service as feed_service
from app.modules.marketplace.feed.models import SavedSearch
from app.modules.marketplace.feed.schemas import (
    EmptyDTO,
    FeedEnvelope,
    FeedItemDTO,
    FeedMatchDTO,
    FeedPageMeta,
    FeedReputationDTO,
    MatchDTO,
    SavedSearchCreate,
    SavedSearchDTO,
    TripAvailabilitySummaryDTO,
)
from app.modules.marketplace.ports import get_ports
from app.modules.marketplace.views import listing_public_dto

router = APIRouter(tags=["v2 Feed"])


def _parse_dt(value: str, field_name: str) -> datetime:
    try:
        return parse_iso_datetime(value, field=field_name)
    except (TypeError, ValueError):
        raise DomainError(
            ErrorCode.VALIDATION_ERROR, details={"field": field_name, "reason": "iso_datetime_with_offset_required"}
        ) from None


def _decode_key(token: str | None, scope: str) -> tuple[int, int, int] | None:
    if token is None:
        return None
    values = decode_cursor(token, scope=scope, secret=cursor_signing_secret(settings))
    if len(values) != 3 or any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise DomainError(ErrorCode.INVALID_CURSOR)
    return values[0], values[1], values[2]


def reputation_dto(summary: ReputationSummary) -> FeedReputationDTO:
    average = summary.average_rating
    return FeedReputationDTO(
        label=summary.label,
        rating_count=summary.rating_count,
        average_rating=round(average, 1) if average is not None else None,
        completed_bookings=summary.completed_bookings,
    )


def _labels(item: feed_service.RankedItem) -> list[str]:
    labels: list[str] = []
    if item.reputation.label is ReputationLabel.NEW_VERIFIED:
        labels.append(ReputationLabel.NEW_VERIFIED.value)  # "new, documents verified" - never a fake 4.5 (§8.2)
    if item.group.value == "alternative":
        labels.append("alternative")
    return labels


def _match_dto(item: feed_service.RankedItem) -> FeedMatchDTO:
    return FeedMatchDTO(
        match_type=item.match_type,
        reasons=list(item.reasons),
        pickup_eta_window_start=item.pickup_eta_window_start,
        pickup_eta_window_end=item.pickup_eta_window_end,
        detour_minutes=None,  # the feed never offers detours (Q46)
        is_estimate=item.is_estimate,
    )


def feed_item_dto(session: Session, item: feed_service.RankedItem) -> FeedItemDTO:
    return FeedItemDTO(
        listing=listing_public_dto(session, item.listing),
        match=_match_dto(item),
        group=item.group,
        ready_to_accept=item.ready_to_accept,
        labels=_labels(item),
        reputation=reputation_dto(item.reputation),
        comparable_total_minor=item.comparable_total_minor,
    )


def match_dto(session: Session, item: feed_service.RankedItem, ranking_version: str) -> MatchDTO:
    availability = item.availability
    summary = None
    if availability is not None:
        passenger = item.listing.service_type == ServiceType.PASSENGER.value
        summary = TripAvailabilitySummaryDTO(
            seat_capacity=availability.seat_capacity if passenger else None,
            min_remaining_seats=availability.min_remaining_seats if passenger else None,
            min_remaining_cargo_weight_g=None if passenger else availability.min_remaining_cargo_weight_g,
            min_remaining_cargo_volume_ml=None if passenger else availability.min_remaining_cargo_volume_ml,
        )
    return MatchDTO(
        listing=listing_public_dto(session, item.listing),
        trip_availability_summary=summary,
        match=_match_dto(item),
        ranking_version=ranking_version,
        group=item.group,
        ready_to_accept=item.ready_to_accept,
        labels=_labels(item),
        reputation=reputation_dto(item.reputation),
        comparable_total_minor=item.comparable_total_minor,
    )


def _meta(page: feed_service.FeedPage, scope: str) -> FeedPageMeta:
    return FeedPageMeta(
        next_cursor=encode_page_cursor(list(page.next_key), scope) if page.next_key else None,
        limit=page.limit,
        ranking_version=page.ranking_version,
        match_scope=page.match_scope,
        degraded=list(page.degraded),
    )


def saved_search_dtos(session: Session, rows: list[SavedSearch]) -> list[SavedSearchDTO]:
    stop_ids = sorted({v for r in rows for v in (r.origin_stop_id, r.destination_stop_id) if v is not None})
    region_ids = {v for r in rows for v in (r.origin_region_id, r.destination_region_id) if v is not None}
    district_ids = {v for r in rows for v in (r.origin_district_id, r.destination_district_id) if v is not None}
    stops = get_ports().geo.stops_by_ids(session, stop_ids) if stop_ids else {}
    regions = feed_service.region_public_ids(session, region_ids)
    districts = feed_service.district_public_ids(session, district_ids)

    def stop_ref(stop_id: int | None) -> str | None:
        return stops[stop_id].public_id if stop_id is not None and stop_id in stops else None

    return [
        SavedSearchDTO(
            id=feed_service.saved_search_public_id(row),
            service_type=ServiceType(row.service_type),
            side=FeedSide(row.side),
            origin_stop_id=stop_ref(row.origin_stop_id),
            origin_region_id=regions.get(row.origin_region_id) if row.origin_region_id else None,
            origin_district_id=districts.get(row.origin_district_id) if row.origin_district_id else None,
            destination_stop_id=stop_ref(row.destination_stop_id),
            destination_region_id=regions.get(row.destination_region_id) if row.destination_region_id else None,
            destination_district_id=districts.get(row.destination_district_id) if row.destination_district_id else None,
            time_window_start=ensure_aware_utc(row.time_window_start),
            time_window_end=ensure_aware_utc(row.time_window_end),
            quantity=row.quantity,
            notify=row.notify,
            last_notified_at=ensure_aware_utc(row.last_notified_at) if row.last_notified_at else None,
            created_at=ensure_aware_utc(row.created_at),
        )
        for row in rows
    ]


# --- M1 ---------------------------------------------------------------------------------------------------------------


@router.get("/feed", response_model=FeedEnvelope, responses=ERROR_RESPONSES)
def get_feed(
    service_type: ServiceType = Query(...),
    side: FeedSide = Query(...),
    date_from: str = Query(..., description="ISO-8601 with offset"),
    date_to: str = Query(..., description="ISO-8601 with offset"),
    origin_stop_id: str | None = Query(default=None),
    origin_region_id: str | None = Query(default=None),
    origin_district_id: str | None = Query(default=None, description="District end (wave 10); one end, one kind."),
    destination_stop_id: str | None = Query(default=None),
    destination_region_id: str | None = Query(default=None),
    destination_district_id: str | None = Query(default=None),
    seats: int | None = Query(default=None, ge=1, le=60),
    max_total_minor: int | None = Query(default=None, gt=0),
    amenities: list[str] | None = Query(default=None),
    sort: FeedSort = Query(default=FeedSort.RECOMMENDED),
    include_alternatives: bool = Query(default=False),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=FEED_DEFAULT_LIMIT, ge=1, le=FEED_MAX_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    criteria = feed_service.FeedCriteria(
        service_type=service_type,
        side=side,
        date_from=_parse_dt(date_from, "date_from"),
        date_to=_parse_dt(date_to, "date_to"),
        origin_stop_id=origin_stop_id,
        origin_region_id=origin_region_id,
        origin_district_id=origin_district_id,
        destination_stop_id=destination_stop_id,
        destination_region_id=destination_region_id,
        destination_district_id=destination_district_id,
        seats=seats,
        max_total_minor=max_total_minor,
        amenities=tuple(sorted(set(amenities or ()))),
        sort=sort,
        include_alternatives=include_alternatives,
    )
    scope = page_scope(
        "feed",
        viewer=user_id,
        service_type=service_type.value,
        side=side.value,
        date_from=to_iso_utc(criteria.date_from),
        date_to=to_iso_utc(criteria.date_to),
        origin_stop_id=origin_stop_id,
        origin_region_id=origin_region_id,
        origin_district_id=origin_district_id,
        destination_stop_id=destination_stop_id,
        destination_region_id=destination_region_id,
        destination_district_id=destination_district_id,
        seats=seats,
        max_total_minor=max_total_minor,
        amenities=",".join(criteria.amenities) or None,
        sort=sort.value,
        alternatives=include_alternatives,
    )
    page = feed_service.feed(
        session, viewer_user_id=user_id, criteria=criteria, after_key=_decode_key(cursor, scope), limit=limit
    )
    items = [feed_item_dto(session, item) for item in page.items]
    # §20.4: one anonymous counter row per search (no user, no stops, no filters) so search_with_match_rate can
    # be measured at all. Only the first page counts: paging through results is the same search.
    if cursor is None:
        feed_service.record_search(session, criteria=criteria, page=page)
        session.commit()
    return JSONResponse(content=envelope_body(items, _meta(page, scope)))


# --- M2 ---------------------------------------------------------------------------------------------------------------


# Q138 (ADR-0026): GET /listings/{id}/matches is removed - it paired a client request with driver listings (and a
# driver listing with requests); with driver listings retired the driver's request feed is the only match surface.


@router.post("/saved-searches", response_model=Envelope[SavedSearchDTO], status_code=201, responses=ERROR_RESPONSES)
def create_saved_search(
    body: SavedSearchCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    return run_command(
        request,
        session,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        body=body,
        handler=lambda: saved_search_dtos(
            session, [feed_service.create_saved_search(session, user_id=user_id, data=body)]
        )[0],
        success_status=201,
        resource_type="saved_search",
    )


@router.get("/me/saved-searches", response_model=Envelope[list[SavedSearchDTO]], responses=ERROR_RESPONSES)
def list_my_saved_searches(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_LIMIT),
    user_id: int = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> JSONResponse:
    scope = page_scope("me_saved_searches", viewer=user_id)
    rows = feed_service.list_saved_searches(
        session, user_id=user_id, after=decode_time_id_cursor(cursor, scope), limit=limit + 1
    )
    page = rows[:limit]
    next_cursor = (
        encode_page_cursor([ensure_aware_utc(page[-1].created_at), page[-1].id], scope) if len(rows) > limit else None
    )
    return JSONResponse(content=envelope_body(saved_search_dtos(session, page), PageMeta(next_cursor=next_cursor, limit=limit)))


@router.delete("/saved-searches/{saved_search_id}", response_model=Envelope[EmptyDTO], responses=ERROR_RESPONSES)
def delete_saved_search(
    saved_search_id: str, user_id: int = Depends(current_user_id), session: Session = Depends(get_session)
) -> JSONResponse:
    def handler() -> EmptyDTO:
        feed_service.delete_saved_search(session, user_id=user_id, saved_search_public_id=saved_search_id)
        return EmptyDTO()

    return JSONResponse(content=envelope_body(run_versioned(session, handler)))
