"""Operations worker functions (A13, wave 4; wired by A10a into ``app.worker``).

ServiceJob shape ``fn(session, *, now=None, limit=200) -> int`` (no commit; the worker commits per batch):

* :func:`refresh_kpi_daily` - recomputes the last ``KPI_BACKFILL_DAYS`` finished days for "all corridors" and for
  every corridor that is live, so a late booking or a corrected cancellation is reflected instead of frozen.
  Returns the number of ``kpi_daily`` rows written; the job is idempotent (upsert on day+metric+corridor).
* :func:`expire_share_links` - revokes share links whose ``expires_at`` has passed, so the active-link limit and
  the operator view show reality. The row itself is kept (the DB guard refuses DELETE).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.operations import rules, service
from app.modules.operations.models import ShareLink

logger = logging.getLogger(__name__)

BATCH_LIMIT = 200
# Yesterday plus the two days before it: late writes (a completion, a cancellation) still move the numbers.
KPI_BACKFILL_DAYS = 3


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _live_corridor_ids(session: Session) -> list[int]:
    """Corridors worth a per-corridor series: the ones that are open for business (geo service)."""
    from app.modules.geo import service as geo_service
    from app.modules.geo.models import ServiceCorridor

    ids = list(session.execute(select(ServiceCorridor.id).order_by(ServiceCorridor.id)).scalars())
    infos = geo_service.get_corridors(session, ids)
    return sorted(info.id for info in infos.values() if info.is_operable)


def refresh_kpi_daily(session: Session, *, now: datetime | None = None, limit: int = BATCH_LIMIT) -> int:
    """Recompute the recent finished days (§20.4). No commit; returns the number of rows written."""
    now = _now(now)
    yesterday = rules.local_date(now) - timedelta(days=1)
    corridor_ids = _live_corridor_ids(session)
    written = 0
    for offset in range(KPI_BACKFILL_DAYS):
        written += service.collect_kpi_daily(session, day=yesterday - timedelta(days=offset), now=now,
                                             corridor_ids=corridor_ids)
        if written >= limit:
            break
    if written:
        logger.info("kpi_daily_refreshed rows=%d days=%d corridors=%d", written, KPI_BACKFILL_DAYS, len(corridor_ids))
    return written


def expire_share_links(session: Session, *, now: datetime | None = None, limit: int = BATCH_LIMIT) -> int:
    """Revoke share links past ``expires_at``; the page already refuses them, this keeps the data honest."""
    now = _now(now)
    due = list(
        session.execute(
            select(ShareLink.id)
            .where(ShareLink.revoked_at.is_(None), ShareLink.expires_at <= now)
            .order_by(ShareLink.id)
            .limit(limit)
        ).scalars()
    )
    if not due:
        return 0
    session.execute(update(ShareLink).where(ShareLink.id.in_(due)).values(revoked_at=now))
    session.flush()
    return len(due)
