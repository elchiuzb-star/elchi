"""Promotions worker jobs (referral stage 3). ``fn(session, limit=, now=) -> handled count`` for ``SERVICE_JOBS``.

The runner (``app.worker.run_service_job``) takes an advisory lock per job, commits after each batch and rolls back
on an exception, so a crash before commit leaves nothing half-done and the work is picked up again; every effect is
keyed (unique rows), so a re-run after a lost acknowledgement creates nothing twice. None of these jobs grants a
reward by itself on a review decision, forfeits a reward because a review is late, or deletes an obligation.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.promotions import identity, qualification, service


def process_qualifications(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    return qualification.process_qualification_events(session, limit=limit, now=now)


def recheck_granted(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    return qualification.recheck_granted(session, limit=limit, now=now)


def expire_enrollments(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    return qualification.expire_enrollments(session, limit=limit, now=now)


def expire_lots(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    return len(service.expire_due_lots(session, limit=limit, now=now))


def pause_exhausted_campaigns(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    return len(service.pause_exhausted_campaigns(session, limit=limit, now=now))


def escalate_reviews(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    return qualification.escalate_overdue_reviews(session, limit=limit, now=now)


def purge_identity_digests(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    return identity.purge_expired_identity_digests(session, now=now)


def purge_rate_events(session: Session, *, limit: int = 5000, now: datetime | None = None) -> int:
    """Referral stage 5: abuse-limit counters older than a day are never read again (no IP/user id is stored)."""
    from app.modules.promotions import portal

    return portal.purge_rate_events(session, limit=limit, now=now)
