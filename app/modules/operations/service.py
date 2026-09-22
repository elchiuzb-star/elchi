"""Operations and growth domain API (A13, wave 4; spec §19.3, §20.2, §20.4; API_V2_CONTRACT §13).

Public functions take the caller's ``Session`` and never commit (AGENTS §4). This module owns ``share_links`` and
``kpi_daily`` only; everything else is read through the owning module's service functions:

* queues (O4)  -> ``bookings.service.admin_queue``, ``trust_support.service.admin_list_*``
* listings (O1, O3, O7) -> ``marketplace.service`` / ``marketplace.views``
* corridors and stops (names for the public page) -> the marketplace geo port

Business truthfulness (spec §9, §20.4):
* the share page shows route, window and price - never a name, phone, plate or exact address (Q43);
* the token is a secret (ADR-0018): stored as SHA-256, shown once, and an unknown, revoked or expired token is a
  plain ``404`` so the page cannot be used to probe which tokens exist;
* KPI ratios come from stored counts; a zero denominator stays ``null`` and a metric this system does not measure
  (feed searches are not logged) is listed in ``missing_metrics`` instead of being reported as zero;
* the SLO answer marks request latency as ``measured=false`` because this application does not time its own
  requests; tracking freshness covers every trip, so offline trips are not hidden.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.contracts.crypto import new_secret_token, secret_token_hash
from app.contracts.enums import (
    Capability,
    KpiMetric,
    ListingStatus,
    OpsQueue,
    ShareLinkChannel,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.operations import (
    KPI_MAX_RANGE_DAYS,
    OFFER_TARGET,
    PROVIDER_CREDIT_COST,
    PROVIDER_DAILY_CREDIT_LIMIT,
    PROVIDER_QUOTA_RESTRICT_RATIO,
    PROVIDER_QUOTA_WARN_RATIO,
    SHARE_LINK_MAX_ACTIVE_PER_LISTING,
    SHARE_LINK_TOKEN_BYTES,
    SLO_MAX_RANGE_DAYS,
    TRACKING_FRESH_SECONDS,
)
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.contracts.tracking import DELAYED_MAX_AGE_SECONDS
from app.models import AuditLog
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.models import Listing
from app.modules.marketplace.ports import get_ports
from app.modules.operations import rules
from app.ops import metrics
from app.modules.operations.models import KpiDaily, ShareLink

logger = logging.getLogger(__name__)

__all__ = [
    "OpsQueueItem",
    "PublicListingPage",
    "collect_kpi_daily",
    "create_listing_on_behalf",
    "create_share_link",
    "kpi_report",
    "list_share_links",
    "ops_queue",
    "open_public_listing",
    "revoke_share_link",
    "share_link_public_id",
    "slo_report",
]

PUBLIC_URL_TEMPLATE_ENV = "ELCHI_SHARE_PUBLIC_URL_TEMPLATE"


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _audit(session: Session, *, actor_user_id: int | None, entity_type: str, action: str, details: dict[str, Any]) -> None:
    session.add(AuditLog(actor_id=actor_user_id, entity_type=entity_type, entity_id=None, action=action, details=details))


def share_link_public_id(row: ShareLink) -> str:
    return format_public_id(PublicIdPrefix.SHARE_LINK, row.public_id)


# --- O1-O3 share links ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreatedShareLink:
    """The row plus the one-time secret: the token exists in this object and in the response, nowhere else."""

    row: ShareLink
    token: str
    url: str
    share_text: str


@dataclass(frozen=True, slots=True)
class PublicListingPage:
    kind: str
    service_type: str
    origin_stop_name: str
    destination_stop_name: str
    departure_window_start: datetime
    departure_window_end: datetime
    timezone: str
    price_basis: str
    unit_price_minor: int
    quantity: int
    total_minor: int
    currency: str
    status_open: bool
    cta: str

    @property
    def departure_date(self) -> str:
        return rules.local_date(self.departure_window_start).isoformat()


def _owned_listing(session: Session, listing_public_id_value: str, actor_user_id: int) -> Listing:
    listing = marketplace_service.get_listing_by_public_id(session, listing_public_id_value)
    if listing.owner_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)  # somebody else's listing is invisible (ADR-0005)
    return listing


def _stop_names(session: Session, listing: Listing) -> tuple[str, str]:
    stops = get_ports().geo.stops_by_ids(session, [listing.origin_stop_id, listing.destination_stop_id])
    origin, destination = stops.get(listing.origin_stop_id), stops.get(listing.destination_stop_id)
    return (origin.name_uz if origin else "?"), (destination.name_uz if destination else "?")


def create_share_link(
    session: Session,
    *,
    listing_public_id_value: str,
    actor_user_id: int,
    channel: str = ShareLinkChannel.GENERIC.value,
    ttl_hours: int,
    now: datetime | None = None,
) -> CreatedShareLink:
    """O1: a share link for an open listing of the caller (§20.2).

    Raises ``NOT_FOUND`` (unknown or somebody else's listing), ``LISTING_NOT_OPEN`` (draft, fulfilled, expired or
    cancelled) and ``VALIDATION_ERROR`` (too many active links). No commit.
    """
    now = _now(now)
    channel_value = ShareLinkChannel(channel).value
    listing = _owned_listing(session, listing_public_id_value, actor_user_id)
    if listing.status not in rules.SHAREABLE_LISTING_STATUSES:
        raise DomainError(ErrorCode.LISTING_NOT_OPEN, details={"status": listing.status})
    active = session.execute(
        select(func.count(ShareLink.id)).where(
            ShareLink.listing_id == listing.id, ShareLink.revoked_at.is_(None), ShareLink.expires_at > now
        )
    ).scalar_one()
    if active >= SHARE_LINK_MAX_ACTIVE_PER_LISTING:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            details={"field": "share_links", "reason": "too_many_active", "limit": SHARE_LINK_MAX_ACTIVE_PER_LISTING},
        )
    token = new_secret_token(SHARE_LINK_TOKEN_BYTES)
    row = ShareLink(
        public_id=new_public_uuid(),
        listing_id=listing.id,
        created_by_user_id=actor_user_id,
        channel=channel_value,
        token_hash=secret_token_hash(token),
        expires_at=now + timedelta(hours=int(ttl_hours)),
        created_at=now,
    )
    session.add(row)
    session.flush()
    origin, destination = _stop_names(session, listing)
    url = rules.public_url(token, os.environ.get(PUBLIC_URL_TEMPLATE_ENV))
    text_for_chat = rules.share_text(
        channel=channel_value,
        kind=listing.kind,
        service_type=listing.service_type,
        origin=origin,
        destination=destination,
        departure_start=ensure_aware_utc(listing.departure_window_start),
        departure_end=ensure_aware_utc(listing.departure_window_end),
        total_minor=listing.total_minor,
        currency=listing.currency,
        url=url,
    )
    return CreatedShareLink(row=row, token=token, url=url, share_text=text_for_chat)


def list_share_links(session: Session, *, listing_public_id_value: str, actor_user_id: int) -> list[ShareLink]:
    """Active links of the caller's listing (without tokens - those exist only in the creation response)."""
    listing = _owned_listing(session, listing_public_id_value, actor_user_id)
    return list(
        session.execute(
            select(ShareLink).where(ShareLink.listing_id == listing.id).order_by(ShareLink.id)
        ).scalars()
    )


def revoke_share_link(
    session: Session, *, share_link_public_id_value: str, actor_user_id: int, now: datetime | None = None
) -> ShareLink:
    """O2: revoke the link. Idempotent; the row is never deleted (the DB guard refuses DELETE). No commit."""
    now = _now(now)
    value = parse_public_id(share_link_public_id_value, PublicIdPrefix.SHARE_LINK)
    row = session.execute(
        select(ShareLink).where(ShareLink.public_id == value).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    listing = session.get(Listing, row.listing_id)
    if listing is None or listing.owner_user_id != actor_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    if row.revoked_at is None:
        row.revoked_at = now
        session.flush()
    return row


def open_public_listing(session: Session, *, token: str, now: datetime | None = None) -> PublicListingPage:
    """O3: the public page behind the token (§20.2). Unknown, revoked, expired or closed -> ``NOT_FOUND``.

    Counts the open (``opened_count``) so growth can be measured without any viewer identity. No commit.
    """
    now = _now(now)
    if not token or len(token) > 512:
        raise DomainError(ErrorCode.NOT_FOUND)
    row = session.execute(
        select(ShareLink).where(ShareLink.token_hash == secret_token_hash(token)).with_for_update()
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or ensure_aware_utc(row.expires_at) <= now:
        raise DomainError(ErrorCode.NOT_FOUND)
    listing = session.get(Listing, row.listing_id)
    if listing is None or listing.status not in rules.SHAREABLE_LISTING_STATUSES:
        raise DomainError(ErrorCode.NOT_FOUND)
    row.opened_count += 1
    row.last_opened_at = now
    session.flush()
    origin, destination = _stop_names(session, listing)
    expired = ensure_aware_utc(listing.expires_at) <= now
    return PublicListingPage(
        kind=listing.kind,
        service_type=listing.service_type,
        origin_stop_name=origin,
        destination_stop_name=destination,
        departure_window_start=ensure_aware_utc(listing.departure_window_start),
        departure_window_end=ensure_aware_utc(listing.departure_window_end),
        timezone=listing.timezone,
        price_basis=listing.price_basis,
        unit_price_minor=listing.unit_price_minor,
        quantity=listing.quantity,
        total_minor=listing.total_minor,
        currency=listing.currency,
        status_open=listing.status == ListingStatus.PUBLISHED.value and not expired,
        cta=rules.page_cta(status=listing.status, expired=expired),
    )


# --- O4 operator queues --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpsQueueItem:
    queue: str
    item_type: str
    item_id: str
    corridor: str | None
    age_minutes: int
    summary: str


def _age_minutes(moment: datetime | None, now: datetime) -> int:
    if moment is None:
        return 0
    return max(0, int((now - ensure_aware_utc(moment)).total_seconds() // 60))


def _corridor_public_id(session: Session, corridor_id: int | None) -> str | None:
    from app.modules.geo import service as geo_service

    if corridor_id is None:
        return None
    try:
        return geo_service.get_corridor(session, corridor_id).api_id
    except DomainError:
        return None


def _corridor_key(session: Session, corridor_public_id: str | None) -> int | None:
    """``cor_...`` -> internal id; an unknown corridor is ``NOT_FOUND`` (never silently "all corridors")."""
    from app.modules.geo import service as geo_service

    if not corridor_public_id:
        return None
    try:
        return geo_service.get_corridor_by_api_id(session, corridor_public_id).id
    except DomainError as exc:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": "corridor_id"}) from exc


def ops_queue(
    session: Session,
    *,
    actor_user_id: int,
    queue: str,
    corridor_id: str | None = None,
    after_id: int | None = None,
    limit: int = 20,
    now: datetime | None = None,
) -> list[OpsQueueItem]:
    """O4: one operator queue, built from the owning module's own queue function (§16). No new table, no writes.

    ``ops.view`` is required; the summary carries route and status only - no phone, name or address.
    """
    now = _now(now)
    queue_value = OpsQueue(queue).value
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.OPS_VIEW
    )
    if queue_value in _BOOKING_QUEUES:
        return _booking_queue_items(
            session, actor_user_id=actor_user_id, queue=queue_value, corridor_id=corridor_id,
            after_id=after_id, limit=limit, now=now,
        )
    if queue_value in _OPERATIONAL_QUEUES:
        return _operational_queue_items(
            session, queue=queue_value, corridor_id=corridor_id, limit=limit, now=now
        )
    return _trust_queue_items(
        session, actor_user_id=actor_user_id, queue=queue_value, after_id=after_id, limit=limit, now=now
    )


_BOOKING_QUEUES = frozenset(
    {
        OpsQueue.AWAITING_CONFIRMATION.value,
        OpsQueue.NO_SHOW_REVIEW.value,
        OpsQueue.CUSTODY_CASE.value,
        OpsQueue.HOLD_ESCALATION.value,
        OpsQueue.FINANCE_REVIEW.value,
    }
)


def _booking_queue_items(
    session: Session, *, actor_user_id: int, queue: str, corridor_id: str | None, after_id: int | None,
    limit: int, now: datetime,
) -> list[OpsQueueItem]:
    from app.modules.bookings import service as bookings_service

    corridor_key = _corridor_key(session, corridor_id)
    rows = bookings_service.admin_queue(
        session, actor_user_id=actor_user_id, queue=queue, corridor_id=corridor_key, after_id=after_id,
        limit=limit, now=now,
    )
    items: list[OpsQueueItem] = []
    for booking in rows:
        items.append(
            OpsQueueItem(
                queue=queue,
                item_type="booking",
                item_id=bookings_service.booking_public_id(booking),
                corridor=_corridor_public_id(session, getattr(booking, "corridor_id", None)),
                age_minutes=_age_minutes(booking.updated_at or booking.created_at, now),
                summary=f"{booking.service_type} {booking.service_status} x{booking.quantity}",
            )
        )
    return items


# --- §16 operational queues (wave 6): read-only views of rows other modules already own -------------------------

_OPERATIONAL_QUEUES = frozenset(
    {OpsQueue.UNANSWERED_LISTING.value, OpsQueue.STALE_TRACKING.value, OpsQueue.INELIGIBLE_DRIVER_TRIP.value}
)
# A listing this close to departure with no proposal at all is what an operator should see first (§16).
UNANSWERED_LISTING_HORIZON = timedelta(hours=24)
# A trip starting this soon whose driver lost eligibility needs a human before the passengers stand at the stop.
INELIGIBLE_DRIVER_HORIZON = timedelta(hours=12)


def _operational_queue_items(
    session: Session, *, queue: str, corridor_id: str | None, limit: int, now: datetime
) -> list[OpsQueueItem]:
    corridor_key = _corridor_key(session, corridor_id)
    if queue == OpsQueue.UNANSWERED_LISTING.value:
        rows = session.execute(
            text(
                """
                SELECT l.public_id, l.corridor_id, l.service_type, l.kind, l.departure_window_start, l.published_at
                  FROM listings l
                 WHERE l.status = 'published'
                   AND l.departure_window_start BETWEEN :now AND :horizon
                   AND (CAST(:corridor AS BIGINT) IS NULL OR l.corridor_id = :corridor)
                   AND NOT EXISTS (SELECT 1 FROM proposal_threads t WHERE t.listing_id = l.id)
                 ORDER BY l.departure_window_start
                 LIMIT :limit
                """
            ),
            {"now": now, "horizon": now + UNANSWERED_LISTING_HORIZON, "corridor": corridor_key, "limit": limit},
        ).all()
        return [
            OpsQueueItem(
                queue=queue, item_type="listing",
                item_id=format_public_id(PublicIdPrefix.LISTING, row.public_id),
                corridor=_corridor_public_id(session, row.corridor_id),
                age_minutes=_age_minutes(row.published_at, now),
                summary=f"{row.kind} {row.service_type} without an offer, departs in "
                        f"{max(0, int((ensure_aware_utc(row.departure_window_start) - now).total_seconds() // 60))} min",
            )
            for row in rows
        ]

    if queue == OpsQueue.STALE_TRACKING.value:
        threshold = now - timedelta(seconds=DELAYED_MAX_AGE_SECONDS)
        rows = session.execute(
            text(
                """
                SELECT t.public_id, rv.corridor_id AS corridor_id,
                       COALESCE(s.last_captured_at, s.started_at) AS last_point_at
                  FROM tracking_sessions s
                  JOIN trips t ON t.id = s.trip_id
                  JOIN route_versions rv ON rv.id = t.route_version_id
                 WHERE s.status = 'active'
                   AND t.status IN ('boarding', 'in_progress')
                   AND COALESCE(s.last_captured_at, s.started_at) < :threshold
                   AND (CAST(:corridor AS BIGINT) IS NULL OR rv.corridor_id = :corridor)
                 ORDER BY last_point_at
                 LIMIT :limit
                """
            ),
            {"threshold": threshold, "corridor": corridor_key, "limit": limit},
        ).all()
        return [
            OpsQueueItem(
                queue=queue, item_type="trip", item_id=format_public_id(PublicIdPrefix.TRIP, row.public_id),
                corridor=_corridor_public_id(session, row.corridor_id),
                age_minutes=_age_minutes(row.last_point_at, now),
                # §10.5/§9: the queue says the signal is missing, never that the driver did something wrong.
                summary="no GPS point for over 2 minutes (connection may be lost)",
            )
            for row in rows
        ]

    # INELIGIBLE_DRIVER_TRIP: the eligibility answer comes from identity, not from a copy kept here.
    rows = session.execute(
        text(
            """
            SELECT t.public_id, rv.corridor_id AS corridor_id, t.driver_user_id, t.planned_start_at
              FROM trips t
              JOIN route_versions rv ON rv.id = t.route_version_id
             WHERE t.status IN ('planned', 'boarding')
               AND t.planned_start_at BETWEEN :now AND :horizon
               AND (CAST(:corridor AS BIGINT) IS NULL OR rv.corridor_id = :corridor)
             ORDER BY t.planned_start_at
             LIMIT :scan_limit
            """
        ),
        {"now": now, "horizon": now + INELIGIBLE_DRIVER_HORIZON, "corridor": corridor_key,
         "scan_limit": max(limit * 5, limit)},
    ).all()
    items: list[OpsQueueItem] = []
    for row in rows:
        capabilities = identity_service.get_capabilities(session, row.driver_user_id, now=now)
        if capabilities.driver_eligible:
            continue
        items.append(
            OpsQueueItem(
                queue=queue, item_type="trip", item_id=format_public_id(PublicIdPrefix.TRIP, row.public_id),
                corridor=_corridor_public_id(session, row.corridor_id),
                age_minutes=_age_minutes(row.planned_start_at, now),
                summary="driver is not eligible for new business before this departure",
            )
        )
        if len(items) >= limit:
            break
    return items


def _trust_queue_items(
    session: Session, *, actor_user_id: int, queue: str, after_id: int | None, limit: int, now: datetime
) -> list[OpsQueueItem]:
    from app.modules.trust_support import service as trust_service

    if queue == OpsQueue.DISPUTE.value:
        rows = trust_service.admin_list_disputes(
            session, actor_user_id=actor_user_id, status=None, dispute_type=None, escalated=None,
            after_id=after_id, limit=limit,
        )
        return [
            OpsQueueItem(
                queue=queue, item_type="dispute", item_id=trust_service.dispute_public_id(row), corridor=None,
                age_minutes=_age_minutes(row.created_at, now),
                summary=f"{row.dispute_type} {row.status}" + (" escalated" if row.escalated_at else ""),
            )
            for row in rows
            if row.status in ("open", "under_review")
        ]
    if queue == OpsQueue.SUPPORT_TICKET.value:
        rows = trust_service.admin_list_tickets(
            session, actor_user_id=actor_user_id, status=None, kind=None, after_id=after_id, limit=limit
        )
        return [
            OpsQueueItem(
                queue=queue, item_type="support_ticket", item_id=trust_service.ticket_public_id(row), corridor=None,
                age_minutes=_age_minutes(row.created_at, now), summary=f"{row.kind} {row.status}",
            )
            for row in rows
            if row.status in ("open", "in_progress")
        ]
    rows = trust_service.admin_list_reviews(
        session, actor_user_id=actor_user_id, status=None, signal_type=None, after_id=after_id, limit=limit
    )
    return [
        OpsQueueItem(
            queue=queue, item_type="trust_review", item_id=trust_service.review_public_id(row), corridor=None,
            age_minutes=_age_minutes(row.created_at, now),
            summary=f"{row.signal_type} {row.status} x{row.signal_count}",
        )
        for row in rows
        if row.status == "open"
    ]


# --- O5 KPI ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KpiValue:
    metric: str
    numerator: int
    denominator: int
    value: float | None
    target: float | None
    small_sample: bool


@dataclass(frozen=True, slots=True)
class KpiReport:
    date_from: date
    date_to: date
    corridor_id: str | None
    metrics: list[KpiValue]
    missing_metrics: list[str]
    computed_at: datetime | None


# Metrics the spec lists (§20.4) that this system cannot measure honestly today; reported as missing, never as 0.
# Wave 7: the last two §20.4 metrics became measurable from stored data (confirmed route distances and the
# ledger), so nothing is listed here any more. The tuple stays: a metric that turns out to be unmeasurable is
# named here again rather than reported as zero.
MISSING_METRICS: tuple[str, ...] = ()


def _range(date_from: date | None, date_to: date | None, now: datetime, *, max_days: int) -> tuple[date, date]:
    end = date_to or rules.local_date(now)
    start = date_from or (end - timedelta(days=13))
    if start > end:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "from", "reason": "after_to"})
    if (end - start).days + 1 > max_days:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "from", "reason": "range_too_long", "max_days": max_days})
    return start, end


def kpi_report(
    session: Session,
    *,
    actor_user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    corridor_id: str | None = None,
    now: datetime | None = None,
) -> KpiReport:
    """O5: the stored daily counts summed over the range (§20.4). Read-only; the worker writes ``kpi_daily``."""
    now = _now(now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.OPS_VIEW
    )
    start, end = _range(date_from, date_to, now, max_days=KPI_MAX_RANGE_DAYS)
    corridor_key = _corridor_key(session, corridor_id)
    stmt: Select = (
        select(
            KpiDaily.metric,
            func.sum(KpiDaily.numerator),
            func.sum(KpiDaily.denominator),
            func.max(KpiDaily.computed_at),
        )
        .where(KpiDaily.day >= start, KpiDaily.day <= end)
        .group_by(KpiDaily.metric)
        .order_by(KpiDaily.metric)
    )
    stmt = stmt.where(KpiDaily.corridor_id == corridor_key) if corridor_key is not None else stmt.where(KpiDaily.corridor_id.is_(None))
    metrics: list[KpiValue] = []
    computed_at: datetime | None = None
    for metric, numerator, denominator, last_computed in session.execute(stmt).all():
        ratio = rules.Ratio(int(numerator or 0), int(denominator or 0))
        is_ratio = rules.metric_is_ratio(metric)
        metrics.append(
            KpiValue(
                metric=metric,
                numerator=ratio.numerator,
                denominator=ratio.denominator,
                value=ratio.value if is_ratio else None,
                target=rules.kpi_target(metric),
                small_sample=ratio.small_sample if is_ratio else False,
            )
        )
        if last_computed is not None:
            computed_at = max(computed_at or ensure_aware_utc(last_computed), ensure_aware_utc(last_computed))
    return KpiReport(
        date_from=start, date_to=end, corridor_id=corridor_id, metrics=metrics,
        missing_metrics=list(MISSING_METRICS), computed_at=computed_at,
    )


_KPI_SQL: dict[str, str] = {
    # published listings of the day (denominator = numerator: a plain count, no ratio is shown)
    KpiMetric.LISTINGS_PUBLISHED.value: """
        SELECT count(*) AS numerator, count(*) AS denominator
          FROM listings l
         WHERE l.published_at >= :start AND l.published_at < :end
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR l.corridor_id = :corridor_id)
    """,
    # bookings created from listings published that day / listings published that day
    KpiMetric.LISTING_TO_BOOKING.value: """
        SELECT (SELECT count(*) FROM bookings b
                  JOIN listings bl ON bl.id = COALESCE(b.request_listing_id, b.supply_listing_id)
                 WHERE bl.published_at >= :start AND bl.published_at < :end
                   AND (CAST(:corridor_id AS BIGINT) IS NULL OR bl.corridor_id = :corridor_id)) AS numerator,
               (SELECT count(*) FROM listings l
                 WHERE l.published_at >= :start AND l.published_at < :end
                   AND (CAST(:corridor_id AS BIGINT) IS NULL OR l.corridor_id = :corridor_id)) AS denominator
    """,
    # listings that received a proposal within OFFER_TARGET of publication (§20.4 >= 70 %)
    KpiMetric.OFFER_WITHIN_TARGET.value: """
        SELECT count(*) FILTER (WHERE t.first_offer_at IS NOT NULL
                                  AND t.first_offer_at <= l.published_at + :offer_window) AS numerator,
               count(*) AS denominator
          FROM listings l
          LEFT JOIN (SELECT listing_id, min(created_at) AS first_offer_at FROM proposal_threads GROUP BY listing_id) t
                 ON t.listing_id = l.id
         WHERE l.published_at >= :start AND l.published_at < :end
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR l.corridor_id = :corridor_id)
    """,
    # bookings confirmed that day: how many reached `completed` (>= 90 %)
    KpiMetric.BOOKING_COMPLETION.value: """
        SELECT count(*) FILTER (WHERE b.service_status = 'completed') AS numerator, count(*) AS denominator
          FROM bookings b
         WHERE b.created_at >= :start AND b.created_at < :end
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR b.corridor_id = :corridor_id)
    """,
    # driver-fault cancellations of bookings created that day (<= 5 %)
    KpiMetric.DRIVER_FAULT_CANCEL.value: """
        SELECT count(*) FILTER (WHERE b.service_status = 'cancelled' AND b.fault_side = 'driver') AS numerator,
               count(*) AS denominator
          FROM bookings b
         WHERE b.created_at >= :start AND b.created_at < :end
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR b.corridor_id = :corridor_id)
    """,
    # §20.4 searches that found at least one result / searches (anonymous counters, no search history)
    KpiMetric.SEARCH_WITH_MATCH_RATE.value: """
        SELECT count(*) FILTER (WHERE s.matched) AS numerator, count(*) AS denominator
          FROM feed_search_events s
         WHERE s.occurred_at >= :start AND s.occurred_at < :end
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR s.corridor_id = :corridor_id)
    """,
    # §20.4 mean seconds from publishing a listing to its first proposal. numerator = total seconds,
    # denominator = listings that did get an offer, so the reader's division is the mean (not a ratio).
    KpiMetric.TIME_TO_FIRST_VALID_OFFER.value: """
        SELECT COALESCE(sum(EXTRACT(EPOCH FROM (t.first_offer_at - l.published_at))), 0)::BIGINT AS numerator,
               count(*) AS denominator
          FROM listings l
          JOIN (SELECT listing_id, min(created_at) AS first_offer_at FROM proposal_threads GROUP BY listing_id) t
                 ON t.listing_id = l.id
         WHERE l.published_at >= :start AND l.published_at < :end
           AND t.first_offer_at >= l.published_at
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR l.corridor_id = :corridor_id)
    """,
    # §20.4 booked seat-metres / offered seat-metres for trips departing that day.
    #
    # Distance comes from `route_version_stops.cumulative_distance_m` - the distance stored with the route
    # version a human confirmed. A trip whose route has no usable distance is excluded from BOTH sides (and
    # counted by `seat_km_route_coverage`): a straight line is never substituted for a road, and no routing
    # provider is called from a metric. Parcel bookings hold no seat, so they do not appear in a seat-km ratio.
    # Cancelled and no-show bookings never consumed the seat, so they are not "booked".
    KpiMetric.BOOKED_SEAT_KM_RATIO.value: """
        WITH eligible_trips AS (
            SELECT t.id, t.seat_capacity, rv.corridor_id,
                   (SELECT max(rvs.cumulative_distance_m) FROM route_version_stops rvs
                     WHERE rvs.route_version_id = t.route_version_id) AS route_distance_m
              FROM trips t
              JOIN route_versions rv ON rv.id = t.route_version_id
             WHERE t.planned_start_at >= :start AND t.planned_start_at < :end
               AND t.status <> 'cancelled'
               AND (CAST(:corridor_id AS BIGINT) IS NULL OR rv.corridor_id = :corridor_id)
        ),
        measurable AS (
            SELECT * FROM eligible_trips WHERE route_distance_m IS NOT NULL AND route_distance_m > 0
        ),
        booked AS (
            SELECT COALESCE(sum(b.seats * (drop_stop.cumulative_distance_m - pick_stop.cumulative_distance_m)), 0)
                       AS seat_metres
              FROM bookings b
              JOIN measurable m ON m.id = b.trip_id
              JOIN trip_stop_occurrences pick ON pick.trip_id = b.trip_id AND pick.seq = b.pickup_occurrence_seq
              JOIN trip_stop_occurrences drop_occ ON drop_occ.trip_id = b.trip_id AND drop_occ.seq = b.dropoff_occurrence_seq
              JOIN route_version_stops pick_stop ON pick_stop.route_version_id = b.route_version_id
                                               AND pick_stop.seq = pick.route_version_stop_seq
              JOIN route_version_stops drop_stop ON drop_stop.route_version_id = b.route_version_id
                                               AND drop_stop.seq = drop_occ.route_version_stop_seq
             WHERE b.seats > 0
               AND b.service_status NOT IN ('cancelled', 'no_show')
               AND drop_stop.cumulative_distance_m > pick_stop.cumulative_distance_m
        )
        SELECT (SELECT seat_metres FROM booked)::BIGINT AS numerator,
               COALESCE((SELECT sum(seat_capacity * route_distance_m) FROM measurable), 0)::BIGINT AS denominator
    """,
    # The coverage of the ratio above: without it, a number computed over half the trips would look like a fact
    # about all of them (§20.4 "kichik n'da foiz yonida son").
    KpiMetric.SEAT_KM_ROUTE_COVERAGE.value: """
        SELECT count(*) FILTER (
                   WHERE (SELECT max(rvs.cumulative_distance_m) FROM route_version_stops rvs
                           WHERE rvs.route_version_id = t.route_version_id) > 0) AS numerator,
               count(*) AS denominator
          FROM trips t
          JOIN route_versions rv ON rv.id = t.route_version_id
         WHERE t.planned_start_at >= :start AND t.planned_start_at < :end
           AND t.status <> 'cancelled'
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR rv.corridor_id = :corridor_id)
    """,
    # §20.4 net commission per corridor: what the ledger actually credited to commission revenue that day, minus
    # what was reversed. Holds are not ledger rows, a top-up credits the driver's prepaid liability (not revenue)
    # and the legacy calculated fee never enters the ledger at all - so none of them can leak in here.
    # This is revenue, NOT profit: no operating cost is subtracted. The denominator is the number of bookings
    # behind the amount, so the reader sees "X tiyin from N bookings" instead of an invented ratio.
    KpiMetric.NET_COMMISSION_PER_CORRIDOR.value: """
        SELECT COALESCE(sum(CASE WHEN e.direction = 'credit' THEN e.amount_minor ELSE -e.amount_minor END), 0)::BIGINT
                   AS numerator,
               count(DISTINCT t.booking_id) AS denominator
          FROM ledger_entries e
          JOIN ledger_transactions t ON t.id = e.transaction_id
          JOIN ledger_accounts a ON a.id = e.account_id
          JOIN bookings b ON b.id = t.booking_id
         WHERE a.code = 'commission_revenue'
           AND e.currency = 'UZS'
           AND t.created_at >= :start AND t.created_at < :end
           AND (CAST(:corridor_id AS BIGINT) IS NULL OR b.corridor_id = :corridor_id)
    """,
    # clients who booked that day and had booked before / clients who booked that day
    KpiMetric.REPEAT_CLIENT.value: """
        WITH day_clients AS (
            SELECT b.client_user_id, min(b.created_at) AS first_of_day
              FROM bookings b
             WHERE b.created_at >= :start AND b.created_at < :end
               AND (CAST(:corridor_id AS BIGINT) IS NULL OR b.corridor_id = :corridor_id)
             GROUP BY b.client_user_id
        )
        SELECT count(*) FILTER (
                   WHERE EXISTS (SELECT 1 FROM bookings e
                                  WHERE e.client_user_id = d.client_user_id AND e.created_at < d.first_of_day)) AS numerator,
               count(*) AS denominator
          FROM day_clients d
    """,
}


def collect_kpi_daily(
    session: Session, *, day: date | None = None, now: datetime | None = None, corridor_ids: list[int] | None = None
) -> int:
    """Compute one day's metrics and upsert them into ``kpi_daily``. Returns the number of rows written. No commit.

    ``day`` defaults to yesterday in the display timezone, so a day is only computed once it is over.
    """
    now = _now(now)
    target_day = day or (rules.local_date(now) - timedelta(days=1))
    start = datetime.combine(target_day, datetime.min.time(), tzinfo=rules.DISPLAY_TZ)
    end = start + timedelta(days=1)
    scopes: list[int | None] = [None, *(corridor_ids or [])]
    written = 0
    for corridor_key in scopes:
        for metric, sql in _KPI_SQL.items():
            row = session.execute(
                text(sql), {"start": start, "end": end, "corridor_id": corridor_key, "offer_window": OFFER_TARGET}
            ).one()
            session.execute(
                pg_insert(KpiDaily)
                .values(
                    day=target_day, metric=metric, corridor_id=corridor_key,
                    numerator=int(row.numerator or 0), denominator=int(row.denominator or 0), computed_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_kpi_daily_day_metric_corridor",
                    set_={
                        "numerator": int(row.numerator or 0),
                        "denominator": int(row.denominator or 0),
                        "computed_at": now,
                    },
                )
            )
            written += 1
    session.flush()
    return written


# --- O6 SLO ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SloValue:
    name: str
    value: float | None
    target: float | None
    sample_size: int
    measured: bool
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SloReport:
    date_from: date
    date_to: date
    indicators: list[SloValue]


def slo_report(
    session: Session,
    *,
    actor_user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    now: datetime | None = None,
) -> SloReport:
    """O6 (§19.3): what this system actually measures.

    ``tracking_freshness`` = share of consecutive stored points less than ``TRACKING_FRESH_SECONDS`` apart, over
    **every** trip in the range (offline trips are in the denominator, so they cannot be hidden). Request latency
    is not measured in-process: those indicators are returned with ``measured=false`` and a null value.
    """
    now = _now(now)
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=now), Capability.OPS_VIEW
    )
    start_day, end_day = _range(date_from, date_to, now, max_days=SLO_MAX_RANGE_DAYS)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=rules.DISPLAY_TZ)
    end = datetime.combine(end_day, datetime.min.time(), tzinfo=rules.DISPLAY_TZ) + timedelta(days=1)
    row = session.execute(
        text(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE gap_seconds <= :fresh_seconds) AS fresh
              FROM (
                SELECT EXTRACT(EPOCH FROM (p.captured_at - lag(p.captured_at)
                                           OVER (PARTITION BY p.session_id ORDER BY p.captured_at))) AS gap_seconds
                  FROM tracking_points p
                 WHERE p.captured_at >= :start AND p.captured_at < :end
              ) gaps
             WHERE gap_seconds IS NOT NULL
            """
        ),
        {"start": start, "end": end, "fresh_seconds": TRACKING_FRESH_SECONDS},
    ).one()
    freshness = rules.freshness_ratio(int(row.fresh or 0), int(row.total or 0))
    indicators = [
        SloValue(
            name="tracking_freshness",
            value=freshness.value,
            target=rules.freshness_target(),
            sample_size=freshness.denominator,
            measured=True,
            note="Share of consecutive stored points under 30 s apart, over every trip in the range.",
        ),
        _latency_indicator("feed_p95_seconds", metrics.BUCKET_FEED, target=1.0),
        _latency_indicator("booking_accept_p95_seconds", metrics.BUCKET_ACCEPT, target=2.0),
        _error_rate_indicator(),
        _outbox_lag_indicator(session, now),
    ]
    return SloReport(date_from=start_day, date_to=end_day, indicators=indicators)


# --- §19.2 operational indicators (wave 6) ----------------------------------------------------------------------

# Below this many samples a percentile says more about luck than about the service (§20.4's "kichik n" rule).
LATENCY_MIN_SAMPLES = 20


def _latency_indicator(name: str, bucket: str, *, target: float) -> SloValue:
    """§19.3 p95 from this process's own measurements (``app.ops.metrics``).

    The number is server-side handler time for the worker that answers this request, since its start - not a
    cluster-wide, client-perceived latency. With too few samples it stays ``null`` instead of a lucky value.
    """
    snapshot = metrics.REGISTRY.snapshot(bucket)
    if snapshot.sample_size < LATENCY_MIN_SAMPLES:
        return SloValue(
            name=name, value=None, target=target, sample_size=snapshot.sample_size, measured=False,
            note=(
                f"Only {snapshot.sample_size} request(s) measured in this worker process since start "
                f"(minimum {LATENCY_MIN_SAMPLES}); server-side handler time only."
            ),
        )
    return SloValue(
        name=name, value=round(snapshot.p95_seconds or 0.0, 4), target=target, sample_size=snapshot.sample_size,
        measured=True,
        note="Server-side handler time in this worker process since start; not client-perceived and not cluster-wide.",
    )


def _error_rate_indicator() -> SloValue:
    """§19.2 "5xx": share of server errors across every measured route of this process."""
    snapshots = metrics.REGISTRY.all_snapshots()
    total = sum(item.count for item in snapshots)
    errors = sum(item.errors_5xx for item in snapshots)
    if total == 0:
        return SloValue(name="server_error_rate", value=None, target=None, sample_size=0, measured=False,
                        note="No request measured in this worker process yet.")
    return SloValue(
        name="server_error_rate", value=round(errors / total, 4), target=None, sample_size=total, measured=True,
        note=f"{errors} of {total} requests answered 5xx in this worker process since start.",
    )


def _outbox_lag_indicator(session: Session, now: datetime) -> SloValue:
    """§19.2 "outbox lag/retries": how old the oldest undelivered event is, in seconds."""
    row = session.execute(
        text(
            """
            SELECT count(*) AS pending,
                   COALESCE(EXTRACT(EPOCH FROM (:now - min(occurred_at))), 0) AS oldest_seconds,
                   COALESCE(sum(attempts), 0) AS attempts,
                   count(*) FILTER (WHERE dead_lettered_at IS NOT NULL) AS dead_lettered
              FROM outbox_events
             WHERE dispatched_at IS NULL
            """
        ),
        {"now": now},
    ).one()
    pending = int(row.pending or 0)
    return SloValue(
        name="outbox_oldest_pending_seconds",
        value=round(float(row.oldest_seconds or 0.0), 1) if pending else 0.0,
        target=None, sample_size=pending, measured=True,
        note=(
            f"{pending} undelivered event(s), {int(row.attempts or 0)} delivery attempt(s), "
            f"{int(row.dead_lettered or 0)} dead-lettered."
        ),
    )


# --- O7 listing on behalf of an owner --------------------------------------------------------------------------


def create_listing_on_behalf(
    session: Session,
    *,
    actor_user_id: int,
    owner_public_id: str,
    consent_reference: str,
    data: Any,
    warnings: list[dict] | None = None,
    filter_hits: list[Any] | None = None,
    now: datetime | None = None,
) -> Listing:
    """O7 (§20.2): an operator creates a listing for a real owner who agreed to it.

    The owner stays the owner; ``created_by_operator_id`` and ``consent_reference`` are stored by A1 and an audit
    row is written here. Raises ``CAPABILITY_REQUIRED`` / ``VALIDATION_ERROR`` / ``NOT_FOUND``. No commit.
    """
    now = _now(now)
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    identity_service.require_capability(caps, Capability.OPS_BOOKING_COMMAND)
    reference = (consent_reference or "").strip()
    if not reference:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "consent_reference"})
    owner_id = identity_service.resolve_user_id(session, owner_public_id)
    listing = marketplace_service.create_listing(
        session,
        owner_user_id=owner_id,
        data=data,
        now=now,
        created_by_operator_id=actor_user_id,
        consent_reference=reference,
        warnings=warnings,
        filter_hits=filter_hits,
    )
    _audit(
        session,
        actor_user_id=actor_user_id,
        entity_type="listing",
        action="listing_created_on_behalf",
        details={
            "listing_id": marketplace_service.listing_public_id(listing),
            "owner_user_id": owner_public_id,
            "consent_reference": reference,
        },
    )
    return listing


# --- O8 legacy read-only projection (A10b, wave 5; Q4, AC37) ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegacyOrderRow:
    """One row of ``legacy_parcel_orders_v``. Built by the reader, never stored anywhere."""

    legacy_order_id: int
    legacy_order_number: str
    status: str
    route_summary: str
    final_price_minor: int | None
    legacy_calculated_fee_minor: int | None
    flags: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


LEGACY_ORDER_FLAGS = ("unknown_time", "unknown_dimensions")
LEGACY_ORDERS_MAX_LIMIT = 100

_LEGACY_ORDER_COLUMNS = """
    legacy_order_id, legacy_order_number, status,
    from_city_name, to_city_name, from_district_name, to_district_name,
    final_price_minor, legacy_calculated_fee_minor,
    unknown_time, unknown_dimensions, created_at, updated_at
"""


def _legacy_row(row: Any) -> LegacyOrderRow:
    origin = row.from_city_name if not row.from_district_name else f"{row.from_city_name} ({row.from_district_name})"
    destination = row.to_city_name if not row.to_district_name else f"{row.to_city_name} ({row.to_district_name})"
    flags = tuple(
        name
        for name, present in (("unknown_time", row.unknown_time), ("unknown_dimensions", row.unknown_dimensions))
        if present
    )
    return LegacyOrderRow(
        legacy_order_id=row.legacy_order_id,
        legacy_order_number=row.legacy_order_number,
        status=row.status,
        route_summary=f"{origin} \u2192 {destination}",
        final_price_minor=row.final_price_minor,
        legacy_calculated_fee_minor=row.legacy_calculated_fee_minor,
        flags=flags,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def legacy_orders(
    session: Session,
    *,
    actor_user_id: int,
    status: str | None = None,
    after_id: int | None = None,
    limit: int = 20,
    now: datetime | None = None,
) -> list[LegacyOrderRow]:
    """O8 list. Reads ``legacy_parcel_orders_v`` only - never ``orders`` and never a v2 write table (Q4).

    Ordering is by the legacy id descending, so a cursor is a plain id; the projection is a view, so a second
    read cannot duplicate or re-charge anything (AC37).
    """
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=_now(now)), Capability.OPS_VIEW
    )
    limit = max(1, min(limit, LEGACY_ORDERS_MAX_LIMIT))
    sql = (
        f"SELECT {_LEGACY_ORDER_COLUMNS} FROM public.legacy_parcel_orders_v"
        " WHERE (CAST(:status AS TEXT) IS NULL OR status = CAST(:status AS TEXT))"
        "   AND (CAST(:after_id AS BIGINT) IS NULL OR legacy_order_id < CAST(:after_id AS BIGINT))"
        " ORDER BY legacy_order_id DESC LIMIT :limit"
    )
    rows = session.execute(text(sql), {"status": status, "after_id": after_id, "limit": limit}).all()
    return [_legacy_row(row) for row in rows]


def legacy_order(
    session: Session, *, actor_user_id: int, legacy_order_number: str, now: datetime | None = None
) -> LegacyOrderRow:
    """O8 detail by the v1 order number (legacy rows have no ``public_id``). Unknown number -> 404 (ADR-0005)."""
    identity_service.require_capability(
        identity_service.get_capabilities(session, actor_user_id, now=_now(now)), Capability.OPS_VIEW
    )
    sql = (
        f"SELECT {_LEGACY_ORDER_COLUMNS} FROM public.legacy_parcel_orders_v"
        " WHERE legacy_order_number = :number"
    )
    row = session.execute(text(sql), {"number": legacy_order_number}).first()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"resource": "legacy_order"})
    return _legacy_row(row)


# --- §10.8 map / routing quota accounting (wave 6) --------------------------------------------------------------


def record_provider_usage(
    session: Session, *, provider: str, operation: str, calls: int = 1, failures: int = 0,
    now: datetime | None = None,
) -> None:
    """Count one adapter call against today's quota (§10.8). Never raises: accounting must not fail a request.

    This is Elchi's own tally with the published credit weights, not the provider's invoice; the operator view
    says so. GPS ingestion is never counted or restricted here - only map/routing calls are.
    """
    now = _now(now)
    credits = PROVIDER_CREDIT_COST.get(operation, 1.0) * max(0, calls)
    try:
        session.execute(
            text(
                """
                INSERT INTO provider_usage_daily (day, provider, operation, calls, credits, failures, updated_at)
                VALUES (:day, :provider, :operation, :calls, :credits, :failures, :now)
                ON CONFLICT (day, provider, operation) DO UPDATE
                   SET calls = provider_usage_daily.calls + EXCLUDED.calls,
                       credits = provider_usage_daily.credits + EXCLUDED.credits,
                       failures = provider_usage_daily.failures + EXCLUDED.failures,
                       updated_at = EXCLUDED.updated_at
                """
            ),
            {"day": rules.local_date(now), "provider": provider[:32], "operation": operation[:32],
             "calls": max(0, calls), "credits": credits, "failures": max(0, failures), "now": now},
        )
    except Exception:  # noqa: BLE001 - a counter is never worth a failed request
        logger.warning("provider usage not recorded provider=%s operation=%s", provider, operation)


@dataclass(frozen=True, slots=True)
class ProviderQuota:
    provider: str
    day: date
    calls: int
    credits: float
    failures: int
    limit: int
    ratio: float
    state: str  # ok | warn | restrict
    estimated: bool = True


def provider_quota(
    session: Session, *, actor_user_id: int | None = None, day: date | None = None, now: datetime | None = None,
    limit: int = PROVIDER_DAILY_CREDIT_LIMIT,
) -> list[ProviderQuota]:
    """§10.8 daily consumption per provider with the 70 % / 85 % thresholds.

    ``estimated`` is always true: the credits are computed from published weights, so the number guides an
    operator decision, it does not reconcile a bill.
    """
    if actor_user_id is not None:
        identity_service.require_capability(
            identity_service.get_capabilities(session, actor_user_id, now=_now(now)), Capability.OPS_VIEW
        )
    target = day or rules.local_date(_now(now))
    rows = session.execute(
        text(
            "SELECT provider, COALESCE(sum(calls), 0) AS calls, COALESCE(sum(credits), 0) AS credits, "
            "       COALESCE(sum(failures), 0) AS failures "
            "  FROM provider_usage_daily WHERE day = :day GROUP BY provider ORDER BY provider"
        ),
        {"day": target},
    ).all()
    quotas: list[ProviderQuota] = []
    for provider, calls, credits, failures in rows:
        used = float(credits or 0)
        ratio = (used / limit) if limit else 0.0
        state = "restrict" if ratio >= PROVIDER_QUOTA_RESTRICT_RATIO else "warn" if ratio >= PROVIDER_QUOTA_WARN_RATIO else "ok"
        quotas.append(
            ProviderQuota(provider=provider, day=target, calls=int(calls or 0), credits=round(used, 2),
                          failures=int(failures or 0), limit=limit, ratio=round(ratio, 4), state=state)
        )
    return quotas
