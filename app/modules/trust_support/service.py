"""Trust & support domain API (A12, wave 3). Public functions take the caller's ``Session`` and never commit.

Exports other modules rely on (signatures fixed by WAVE1_CARDS "Wave 3"):

* ``reputation_summaries(session, user_ids, *, service_type) -> dict[int, ReputationSummary]``   (A5 ranking, S2)
* ``register_booking_hooks() -> None`` - registers ``blocking_dispute_open`` (probe) and ``open_payment_dispute``
  (opener) with ``bookings.service``; the integrator calls it in ``configure_v2_ports()``            (AC20, AC26, Q74)
* ``blocking_state_for_user(session, user_id, *, lock=False) -> TrustBlockingState``           (v1/v2 account deletion)
* consumers ``consume_contact_filter_hit`` / ``consume_booking_cancelled`` (``trust_support.consumers.CONSUMERS``)

Worker functions for A10a (ServiceJob shape, no commit):

* ``emit_dispute_escalations(session, *, now=None, limit=200) -> int``    (§9.5 48 h, marks ``escalated_at``)
* ``publish_due_ratings(session, *, now=None, limit=200) -> int``         (§17.2 7-day window)
* ``refresh_reputation_snapshots(session, *, now=None, limit=200) -> int``

Lock order (ADR-0017): users (FOR SHARE / FOR NO KEY UPDATE, id ASC) -> bookings (``bookings.service.lock_booking``)
-> booking children (``disputes_v2``, ``ratings_v2``) -> ``dispute_evidence``. Support tickets and trust review items
are independent groups taken after users; per-user Q45 counting is serialised with a transaction advisory lock.
Disputes never write a booking/trip status and never restore a previous status (§11). No automatic capture after a
dispute is closed (Q84): a held commission is handed to A4 ``mark_finance_review_after_dispute`` and finance
finalizes it by hand.

M1 (wave 3.1): opening a dispute holds the trip's raw GPS through ``tracking.service.hold_trip_evidence`` and
closing it releases the hold, so evidence survives the 7-day raw retention (decision M1 (a)).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import contact_filter, trust
from app.contracts.communications import ChatActivitySummary, DispatchedEvent
from app.contracts.enums import (
    ActorSide,
    Capability,
    CashCollectionStatus,
    CashResolutionOutcome,
    CommissionStatus,
    DisputeStatus,
    DisputeResolutionCode,
    DisputeType,
    EventType,
    FraudSignalStatus,
    FraudSignalType,
    ReportReasonCode,
    ReportStatus,
    ReportSubjectType,
    ServiceType,
    SupportTicketKind,
    SupportTicketStatus,
    TrackingEvidenceReason,
    TrackingEvidenceSource,
    TrustReviewDecision,
    TrustReviewStatus,
    TrustSignalType,
)
from app.contracts.errors import DomainError, ErrorCode, WarningCode
from app.contracts.events import EventEnvelope
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.state_machines import DISPUTE, SUPPORT_TICKET, TRUST_REVIEW
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.models import AuditLog
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking, CashReceipt
from app.modules.identity import service as identity_service
from app.modules.marketplace.service import ContactFilterHit, record_contact_filter_hits
from app.modules.platform import service as platform_service
from app.modules.trust_support import rules
from app.modules.trust_support.models import (
    AbuseReport,
    ContactFilterHitRecord,
    ContactStrike,
    DisputeEvidence,
    DisputeV2,
    FraudSignal,
    RatingV2,
    ReputationSnapshot,
    SupportTicket,
    TrustReviewItem,
    UserBlock,
)

logger = logging.getLogger("elchi.trust_support")

__all__ = [
    "TrustBlockingState",
    "add_dispute_evidence",
    "block_user",
    "blocked_between",
    "blocked_user_ids",
    "blocking_dispute_open",
    "blocking_state_for_user",
    "create_report",
    "fraud_signal_command",
    "list_blocks",
    "list_fraud_signals",
    "list_reports",
    "report_command",
    "scan_fraud_signals",
    "unblock_user",
    "consume_booking_cancelled",
    "consume_contact_filter_hit",
    "create_rating",
    "create_support_ticket",
    "delete_account_v2",
    "dispute_command",
    "emit_dispute_escalations",
    "open_dispute",
    "open_payment_dispute",
    "publish_due_ratings",
    "refresh_reputation_snapshots",
    "register_booking_hooks",
    "reputation_summaries",
    "review_command",
    "support_ticket_command",
]

ACTIVE_DISPUTE_INDEX = "uq_disputes_v2_booking_type_active"
RATING_UNIQUE = "uq_ratings_v2_booking_author_subject"
ACTIVE_REVIEW_INDEX = "uq_trust_review_items_subject_signal_active"
SIGNAL_BATCH_LIMIT = 200
# pg_advisory_xact_lock(int4, int4) namespace for per-user Q45 counting (strikes, review upserts).
TRUST_ADVISORY_NAMESPACE = 60012

_ACTIVE = tuple(sorted(rules.ACTIVE_DISPUTE_STATUSES))
_BLOCKING_TYPES = tuple(sorted(rules.BLOCKING_DISPUTE_TYPE_VALUES))


# ==============================================================================================================
# helpers
# ==============================================================================================================


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now)


def _flush_or_translate(session: Session, translations: dict[str, Callable[[], DomainError]]) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        factory = translations.get(platform_service.constraint_name_of(exc) or "")
        if factory is None:
            raise
        raise factory() from exc


def _check_version(current: int, expected: int) -> None:
    if current != expected:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": current})


def _emit(
    session: Session, event_type: EventType, *, aggregate_type: str, aggregate_public_id: str, aggregate_version: int,
    payload: dict[str, Any], now: datetime, aggregate_id: int | None = None, dedup_key: str | None = None,
) -> None:
    platform_service.enqueue_event(
        session,
        EventEnvelope(event_type, aggregate_type, aggregate_public_id, max(int(aggregate_version), 1), now, payload),
        aggregate_id=aggregate_id,
        dedup_key=dedup_key,
    )


def _audit(session: Session, *, actor_user_id: int | None, entity_type: str, action: str, details: dict[str, Any]) -> None:
    """Audit row with ids and codes only (no free text beyond staff decision notes' presence)."""
    session.add(AuditLog(actor_id=actor_user_id, entity_type=entity_type, entity_id=None, action=action, details=details))


def _require(session: Session, user_id: int, capability: Capability, now: datetime) -> None:
    identity_service.require_capability(identity_service.get_capabilities(session, user_id, now=now), capability)


def _has(session: Session, user_id: int, capability: Capability, now: datetime) -> bool:
    return identity_service.get_capabilities(session, user_id, now=now).has(capability)


def _advisory_lock_user(session: Session, user_id: int) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:ns, :uid)"), {"ns": TRUST_ADVISORY_NAMESPACE, "uid": int(user_id)})


def dispute_public_id(dispute: DisputeV2) -> str:
    return format_public_id(PublicIdPrefix.DISPUTE, dispute.public_id)


def rating_public_id(rating: RatingV2) -> str:
    return format_public_id(PublicIdPrefix.RATING, rating.public_id)


def ticket_public_id(ticket: SupportTicket) -> str:
    return format_public_id(PublicIdPrefix.SUPPORT_TICKET, ticket.public_id)


def review_public_id(item: TrustReviewItem) -> str:
    return format_public_id(PublicIdPrefix.TRUST_REVIEW, item.public_id)


def filter_free_text(
    session: Session, *, actor_user_id: int, field: str, subject_type: str, text_value: str | None,
    warnings: list[dict] | None, filter_hits: list[ContactFilterHit] | None,
) -> str | None:
    """Q43 contact filter for rating comments, dispute text and support messages; only masked text is stored.

    Hits go to ``filter_hits`` (the API records them in a separate commit, R2-b) or, without a sink, straight into
    the caller's transaction through A1's ``record_contact_filter_hits`` (staff event, audit counts, no text).
    """
    if text_value is None:
        return None
    result = contact_filter.scan(text_value)
    if not result.has_contact:
        return text_value
    hit = ContactFilterHit(
        actor_user_id=actor_user_id,
        field=field,
        subject_type=subject_type,
        categories=dict(sorted(Counter(match.category.value for match in result.matches).items())),
        match_count=len(result.matches),
        filter_version=result.filter_version,
    )
    if filter_hits is None:
        record_contact_filter_hits(session, [hit])
    else:
        filter_hits.append(hit)
    if warnings is not None:
        warnings.append({"code": WarningCode.CONTACT_INFO_MASKED.value, "field": field, **result.warning_details()})
    return result.masked_text


# ==============================================================================================================
# reputation (§8.2, AC36, S2) - A5 export
# ==============================================================================================================


def _live_reputation(session: Session, user_ids: Sequence[int], service: ServiceType) -> dict[int, trust.ReputationSummary]:
    """Counters straight from ``ratings_v2`` and ``bookings`` (read-only). Faulted cancellations count as resolved
    (client fault / operator-justified cancels are not the driver's, §8.2); 8 bookings on one trip are 1 trip."""
    ids = list(user_ids)
    acc: dict[int, dict[str, int]] = {uid: Counter() for uid in ids}  # type: ignore[misc]
    if platform_service.table_exists(session, RatingV2.__tablename__):
        for row in session.execute(
            select(RatingV2.subject_user_id, func.count(RatingV2.id), func.coalesce(func.sum(RatingV2.stars), 0))
            .where(RatingV2.subject_user_id.in_(ids), RatingV2.service_type == service.value,
                   RatingV2.published_at.is_not(None), RatingV2.moderation_status == "visible")
            .group_by(RatingV2.subject_user_id)
        ):
            acc[row[0]]["rating_count"] += int(row[1])
            acc[row[0]]["rating_sum"] += int(row[2])
    if platform_service.table_exists(session, Booking.__tablename__):
        completed = Booking.service_status == rules.COMPLETED_STATUS
        for column, side in ((Booking.driver_user_id, "driver"), (Booking.client_user_id, "client")):
            faulted = and_(
                Booking.service_status == "cancelled",
                or_(Booking.fault_side == side, and_(Booking.fault_side.is_(None), Booking.cancelled_by_side == side)),
            )
            if side == "client":
                faulted = or_(faulted, Booking.service_status == "no_show")
            on_time = and_(completed, Booking.arrived_at_pickup_at.is_not(None),
                           Booking.arrived_at_pickup_at <= Booking.pickup_window_end)
            stmt = (
                select(
                    column,
                    func.coalesce(func.sum(case((completed, 1), else_=0)), 0),
                    func.coalesce(func.sum(case((faulted, 1), else_=0)), 0),
                    func.coalesce(func.sum(case((on_time, 1), else_=0)), 0),
                    func.count(func.distinct(case((completed, Booking.trip_id), else_=None))),
                )
                .where(column.in_(ids), Booking.service_type == service.value)
                .group_by(column)
            )
            for uid, done, faults, punctual, trips in session.execute(stmt):
                acc[uid]["completed_bookings"] += int(done)
                acc[uid]["eligible_resolved"] += int(done) + int(faults)
                if side == "driver":
                    acc[uid]["on_time_count"] += int(punctual)
                    acc[uid]["completed_trips"] += int(trips)
    return {
        uid: trust.ReputationSummary(
            user_id=uid,
            service_type=service,
            rating_count=values.get("rating_count", 0),
            rating_sum=values.get("rating_sum", 0),
            completed_bookings=values.get("completed_bookings", 0),
            completed_trips=values.get("completed_trips", 0),
            eligible_resolved=values.get("eligible_resolved", 0),
            on_time_count=values.get("on_time_count", 0),
        )
        for uid, values in acc.items()
    }


def reputation_summaries(
    session: Session, user_ids: Sequence[int], *, service_type: ServiceType | str
) -> dict[int, trust.ReputationSummary]:
    """A5 export. Snapshot when present, otherwise live counters; no ratings -> ``rating_count=0``,
    ``average_rating=None``, label ``new_verified`` - never a fake default (§8.2, AC36). Read-only."""
    service = ServiceType(service_type)
    ids = sorted({int(user_id) for user_id in user_ids})
    result = {uid: trust.ReputationSummary(user_id=uid, service_type=service) for uid in ids}
    if not ids or not platform_service.table_exists(session, ReputationSnapshot.__tablename__):
        return result
    found: set[int] = set()
    for snap in session.execute(
        select(ReputationSnapshot).where(ReputationSnapshot.user_id.in_(ids), ReputationSnapshot.service_type == service.value)
    ).scalars():
        found.add(snap.user_id)
        result[snap.user_id] = trust.ReputationSummary(
            user_id=snap.user_id, service_type=service, rating_count=snap.rating_count, rating_sum=snap.rating_sum,
            completed_bookings=snap.completed_bookings, completed_trips=snap.completed_trips,
            eligible_resolved=snap.eligible_resolved, on_time_count=snap.on_time_count,
        )
    missing = [uid for uid in ids if uid not in found]
    if missing:
        result.update(_live_reputation(session, missing, service))
    return result


def _write_snapshots(session: Session, pairs: Iterable[tuple[int, str]], now: datetime) -> int:
    by_service: dict[str, set[int]] = {}
    for user_id, service in pairs:
        by_service.setdefault(service, set()).add(int(user_id))
    written = 0
    for service, users in by_service.items():
        for summary in _live_reputation(session, sorted(users), ServiceType(service)).values():
            values = {
                "rating_count": summary.rating_count, "rating_sum": summary.rating_sum,
                "completed_bookings": summary.completed_bookings, "completed_trips": summary.completed_trips,
                "eligible_resolved": summary.eligible_resolved, "on_time_count": summary.on_time_count, "computed_at": now,
            }
            session.execute(
                pg_insert(ReputationSnapshot)
                .values(user_id=summary.user_id, service_type=service, **values)
                .on_conflict_do_update(constraint="uq_reputation_snapshots_user_service", set_=values)
            )
            written += 1
    return written


def refresh_reputation_snapshots(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """Worker: recompute snapshots of users whose published ratings or finished bookings are newer than the snapshot."""
    now = _now(now)
    rows = session.execute(
        text(
            """
            WITH changes AS (
                SELECT r.subject_user_id AS user_id, r.service_type, r.published_at AS changed_at
                  FROM ratings_v2 r WHERE r.published_at IS NOT NULL
                UNION ALL
                SELECT b.driver_user_id, b.service_type, COALESCE(b.service_terminal_at, b.completed_at, b.cancelled_at)
                  FROM bookings b WHERE b.service_status IN ('completed', 'cancelled', 'no_show', 'returned')
                UNION ALL
                SELECT b.client_user_id, b.service_type, COALESCE(b.service_terminal_at, b.completed_at, b.cancelled_at)
                  FROM bookings b WHERE b.service_status IN ('completed', 'cancelled', 'no_show', 'returned')
            )
            SELECT c.user_id, c.service_type
              FROM changes c
              LEFT JOIN reputation_snapshots s ON s.user_id = c.user_id AND s.service_type = c.service_type
             WHERE c.changed_at IS NOT NULL AND c.changed_at <= :now AND (s.id IS NULL OR c.changed_at > s.computed_at)
             GROUP BY c.user_id, c.service_type
             ORDER BY c.user_id, c.service_type
             LIMIT :limit
            """
        ),
        {"now": now, "limit": limit},
    ).all()
    return _write_snapshots(session, [(row.user_id, row.service_type) for row in rows], now)


# ==============================================================================================================
# booking hooks (AC20, AC26, Q74) - registered by the integrator
# ==============================================================================================================


def blocking_dispute_open(session: Session, booking_id: int) -> bool:
    """``trust.BlockingDisputeProbe``: an open/under_review ``service|commission|payment|delivery`` dispute exists.

    Read-only (the caller holds the booking lock). A missing ``disputes_v2`` table while the probe is registered is a
    deployment error: 503 instead of silently capturing (fail closed)."""
    if not platform_service.table_exists(session, DisputeV2.__tablename__):
        raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "dispute_table_missing"})
    return session.execute(
        select(DisputeV2.id).where(
            DisputeV2.booking_id == booking_id, DisputeV2.dispute_type.in_(_BLOCKING_TYPES), DisputeV2.status.in_(_ACTIVE)
        ).limit(1)
    ).first() is not None


def _emit_dispute_event(session: Session, booking: Booking, dispute: DisputeV2, event_type: EventType, now: datetime) -> None:
    # Q16: commission disputes reach drivers/staff only - events.payload_for_audience drops the client copy
    # (events.CLIENT_HIDDEN_DISPUTE_TYPES).
    payload: dict[str, Any] = {"booking_id": bookings_service.booking_public_id(booking), "dispute_type": dispute.dispute_type}
    if event_type is EventType.DISPUTE_RESOLVED:
        payload.update(status=dispute.status, resolution_code=dispute.resolution_code)
    _emit(session, event_type, aggregate_type="booking", aggregate_public_id=payload["booking_id"],
          aggregate_version=booking.version, payload=payload, now=now, aggregate_id=booking.id)


def _active_dispute(session: Session, booking_id: int, dispute_type: str, *, lock: bool) -> DisputeV2 | None:
    stmt = select(DisputeV2).where(
        DisputeV2.booking_id == booking_id, DisputeV2.dispute_type == dispute_type, DisputeV2.status.in_(_ACTIVE)
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return session.execute(stmt).scalar_one_or_none()


def open_payment_dispute(session: Session, booking: Booking, receipt: CashReceipt, actor_user_id: int, comment: str) -> int:
    """``trust.PaymentDisputeOpener`` (B8 contest, AC26). The booking is already locked by A4; inserts a ``payment``
    dispute linked to the receipt, or returns the id of the active one. Never changes booking/receipt status."""
    now = ensure_aware_utc(booking.updated_at) if booking.updated_at is not None else utc_now()
    existing = _active_dispute(session, booking.id, DisputeType.PAYMENT.value, lock=True)
    if existing is not None:
        return existing.id
    side = bookings_service.participant_side(booking, actor_user_id) or ActorSide.OPERATOR
    description = filter_free_text(
        session, actor_user_id=actor_user_id, field="dispute.description", subject_type="dispute",
        text_value=comment, warnings=None, filter_hits=None,
    ) or comment
    dispute = DisputeV2(
        public_id=new_public_uuid(), booking_id=booking.id, dispute_type=DisputeType.PAYMENT.value,
        status=DisputeStatus.OPEN.value, opened_by_user_id=actor_user_id, opened_by_side=side.value,
        description=description[: trust.DISPUTE_DESCRIPTION_MAX_LENGTH], cash_receipt_id=receipt.id,
        escalate_at=rules.dispute_escalate_at(now), version=1, created_at=now, updated_at=now,
    )
    session.add(dispute)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if platform_service.constraint_name_of(exc) != ACTIVE_DISPUTE_INDEX:
            raise
        found = _active_dispute(session, booking.id, DisputeType.PAYMENT.value, lock=True)
        if found is None:
            raise
        return found.id
    _emit_dispute_event(session, booking, dispute, EventType.DISPUTE_OPENED, now)
    return dispute.id


def register_booking_hooks() -> None:
    """Integrator: call once at start-up in ``app.api.v2.router.configure_v2_ports()`` (idempotent).

    Ends the Q74 fallback: ``bookings.service.dispute_state`` returns ``open``/``clear`` instead of ``unavailable``."""
    bookings_service.set_blocking_dispute_probe(blocking_dispute_open)
    bookings_service.set_payment_dispute_opener(open_payment_dispute)


# ==============================================================================================================
# disputes S3-S8
# ==============================================================================================================


def _viewer_side(session: Session, booking: Booking, user_id: int, now: datetime, *, staff_capability: Capability) -> str:
    side = bookings_service.participant_side(booking, user_id)
    if side is not None:
        return side.value
    if _has(session, user_id, staff_capability, now):
        return "staff"
    raise DomainError(ErrorCode.NOT_FOUND)


def evidence_file_keys(actor_user_id: int, file_ids: Sequence[str]) -> list[str]:
    """Wave 3.1 (H0): a dispute evidence reference must be a private upload of type ``dispute_evidence`` that this
    user uploaded and that exists on disk; the canonical storage key is stored. Anything else -> VALIDATION_ERROR,
    so nobody can attach somebody else's passport or selfie to a dispute (§15, S6).
    """
    from app.utils.file_access import FileReferenceError, resolve_attachment
    from app.utils.file_validation import DISPUTE_EVIDENCE_UPLOAD_TYPE

    keys: list[str] = []
    for item in file_ids:
        try:
            key = resolve_attachment(str(item), user_id=actor_user_id, expected_upload_type=DISPUTE_EVIDENCE_UPLOAD_TYPE)
        except FileReferenceError as exc:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "file_ids", "reason": "invalid_file_reference"}) from exc
        if key is not None:
            keys.append(key)
    return keys


def open_dispute(
    session: Session, *, booking_public_id_value: str, actor_user_id: int, dispute_type: DisputeType | str, description: str,
    evidence_file_ids: Sequence[str] = (), warnings: list[dict] | None = None,
    filter_hits: list[ContactFilterHit] | None = None, now: datetime | None = None,
) -> DisputeV2:
    """S3. Participant (a blocked driver too - obligation, D16) or staff with ``ops.dispute_resolve``.

    Lock order: users (both parties, FOR SHARE - serialises with account deletion) -> booking -> dispute insert."""
    now = _now(now)
    dtype = DisputeType(dispute_type)
    snapshot = bookings_service.get_booking_by_public_id(session, booking_public_id_value)
    viewer = _viewer_side(session, snapshot, actor_user_id, now, staff_capability=Capability.OPS_DISPUTE_RESOLVE)
    side = ActorSide.OPERATOR.value if viewer == "staff" else viewer
    if not rules.dispute_visible_to_side(dtype.value, side):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "type", "reason": "not_allowed_for_side"})
    if not (description or "").strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "description"})
    identity_service.lock_user_eligibility(session, [snapshot.client_user_id, snapshot.driver_user_id], mode="share")
    booking = bookings_service.lock_booking(session, snapshot.id)
    masked = filter_free_text(
        session, actor_user_id=actor_user_id, field="description", subject_type="dispute", text_value=description,
        warnings=warnings, filter_hits=filter_hits,
    )
    dispute = DisputeV2(
        public_id=new_public_uuid(), booking_id=booking.id, dispute_type=dtype.value, status=DisputeStatus.OPEN.value,
        opened_by_user_id=actor_user_id, opened_by_side=side, description=masked, escalate_at=rules.dispute_escalate_at(now),
        version=1, created_at=now, updated_at=now,
    )
    session.add(dispute)
    _flush_or_translate(
        session, {ACTIVE_DISPUTE_INDEX: lambda: DomainError(ErrorCode.DISPUTE_ALREADY_OPEN, details={"dispute_type": dtype.value})}
    )
    files = evidence_file_keys(actor_user_id, evidence_file_ids)
    if files:
        session.add(DisputeEvidence(dispute_id=dispute.id, author_user_id=actor_user_id, author_side=side, note=None,
                                    file_ids=files, created_at=now))
        session.flush()
    _tracking_evidence(session, trip_id=booking.trip_id, dispute_id=dispute.id, hold=True, now=now)
    if side == ActorSide.OPERATOR.value:
        _audit(session, actor_user_id=actor_user_id, entity_type="dispute", action="dispute_opened_by_staff",
               details={"dispute_id": dispute_public_id(dispute), "booking_id": bookings_service.booking_public_id(booking),
                        "dispute_type": dtype.value})
    _emit_dispute_event(session, booking, dispute, EventType.DISPUTE_OPENED, now)
    return dispute


def _dispute_ids(session: Session, dispute_public_id_value: str) -> tuple[int, int]:
    value = parse_public_id(dispute_public_id_value, PublicIdPrefix.DISPUTE)
    row = session.execute(select(DisputeV2.id, DisputeV2.booking_id).where(DisputeV2.public_id == value)).first()
    if row is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return row.id, row.booking_id


def _lock_dispute(session: Session, dispute_id: int) -> DisputeV2:
    return session.execute(
        select(DisputeV2).where(DisputeV2.id == dispute_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()


def get_dispute_for_viewer(
    session: Session, dispute_public_id_value: str, viewer_user_id: int, *, now: datetime | None = None
) -> tuple[DisputeV2, Booking, str]:
    """S5: participant (clients never see commission disputes) or ``ops.view`` staff; otherwise 404."""
    now = _now(now)
    dispute_id, booking_id = _dispute_ids(session, dispute_public_id_value)
    booking = bookings_service.get_booking(session, booking_id)
    viewer = _viewer_side(session, booking, viewer_user_id, now, staff_capability=Capability.OPS_VIEW)
    dispute = session.get(DisputeV2, dispute_id)
    if viewer != "staff" and not rules.dispute_visible_to_side(dispute.dispute_type, viewer):
        raise DomainError(ErrorCode.NOT_FOUND)
    return dispute, booking, viewer


def dispute_evidence(session: Session, dispute_id: int) -> list[DisputeEvidence]:
    return list(session.execute(select(DisputeEvidence).where(DisputeEvidence.dispute_id == dispute_id).order_by(DisputeEvidence.id)).scalars())


def add_dispute_evidence(
    session: Session, *, dispute_public_id_value: str, actor_user_id: int, note: str | None, file_ids: Sequence[str],
    warnings: list[dict] | None = None, filter_hits: list[ContactFilterHit] | None = None, now: datetime | None = None,
) -> DisputeV2:
    """S6. Lock order: booking -> dispute (re-checked) -> evidence insert. Closed dispute -> 409."""
    now = _now(now)
    if not (note or "").strip() and not file_ids:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "note", "reason": "note_or_files_required"})
    dispute_id, booking_id = _dispute_ids(session, dispute_public_id_value)
    snapshot = bookings_service.get_booking(session, booking_id)
    viewer = _viewer_side(session, snapshot, actor_user_id, now, staff_capability=Capability.OPS_DISPUTE_RESOLVE)
    bookings_service.lock_booking(session, booking_id)
    dispute = _lock_dispute(session, dispute_id)
    if viewer != "staff" and not rules.dispute_visible_to_side(dispute.dispute_type, viewer):
        raise DomainError(ErrorCode.NOT_FOUND)
    if dispute.status not in rules.ACTIVE_DISPUTE_STATUSES:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "dispute", "reason": "dispute_closed"})
    masked = filter_free_text(
        session, actor_user_id=actor_user_id, field="note", subject_type="dispute", text_value=(note or "").strip() or None,
        warnings=warnings, filter_hits=filter_hits,
    )
    side = ActorSide.OPERATOR.value if viewer == "staff" else viewer
    session.add(DisputeEvidence(dispute_id=dispute.id, author_user_id=actor_user_id, author_side=side, note=masked,
                                file_ids=evidence_file_keys(actor_user_id, file_ids), created_at=now))
    dispute.updated_at = now
    session.flush()
    return dispute


def list_user_disputes(
    session: Session, user_id: int, *, before: tuple[datetime, int] | None, limit: int
) -> list[DisputeV2]:
    """S4: disputes on the user's bookings (either side); clients never see commission disputes (Q16)."""
    stmt = (
        select(DisputeV2)
        .join(Booking, Booking.id == DisputeV2.booking_id)
        .where(or_(Booking.driver_user_id == user_id,
                   and_(Booking.client_user_id == user_id, DisputeV2.dispute_type.not_in(sorted(rules.CLIENT_HIDDEN_DISPUTE_TYPES)))))
    )
    if before is not None:
        moment, row_id = before
        stmt = stmt.where(or_(DisputeV2.created_at < moment, and_(DisputeV2.created_at == moment, DisputeV2.id < row_id)))
    return list(session.execute(stmt.order_by(DisputeV2.created_at.desc(), DisputeV2.id.desc()).limit(limit)).scalars())


def admin_list_disputes(
    session: Session, *, actor_user_id: int, status: str | None, dispute_type: str | None, escalated: bool | None,
    after_id: int | None, limit: int, now: datetime | None = None,
) -> list[DisputeV2]:
    """S7 (``ops.view``), oldest first."""
    _require(session, actor_user_id, Capability.OPS_VIEW, _now(now))
    stmt = select(DisputeV2)
    if status is not None:
        stmt = stmt.where(DisputeV2.status == DisputeStatus(status).value)
    if dispute_type is not None:
        stmt = stmt.where(DisputeV2.dispute_type == DisputeType(dispute_type).value)
    if escalated is not None:
        stmt = stmt.where(DisputeV2.escalated_at.is_not(None) if escalated else DisputeV2.escalated_at.is_(None))
    if after_id is not None:
        stmt = stmt.where(DisputeV2.id > after_id)
    return list(session.execute(stmt.order_by(DisputeV2.id).limit(limit)).scalars())


# Payment dispute resolution codes that imply the contested cash receipt's outcome (A4
# resolve_contested_cash_receipt). Wave 3.1 added the explicit ``cash_outcome`` command field
# (contracts.enums.CashResolutionOutcome): a payment dispute over a contested receipt cannot be closed without an
# outcome any more, and an explicit outcome that contradicts the resolution code is refused.
PAYMENT_RESOLUTION_CASH_OUTCOME: dict[str, str] = {
    DisputeResolutionCode.PAID_CONFIRMED.value: CashResolutionOutcome.PAID.value,
    DisputeResolutionCode.UNPAID_CONFIRMED.value: CashResolutionOutcome.UNPAID.value,
}

DISPUTE_COMMAND_TARGET = {
    "start_review": DisputeStatus.UNDER_REVIEW.value,
    "resolve": DisputeStatus.RESOLVED.value,
    "reject": DisputeStatus.REJECTED.value,
}
# Wave 3.1: the two commands that close a dispute; admin+ only (v1 Q13/Q38 parity).
DISPUTE_DECISION_COMMANDS = frozenset({"resolve", "reject"})
CASH_RESOLUTION_OUTCOMES = frozenset(outcome.value for outcome in CashResolutionOutcome)


def _cash_outcome_for_decision(
    session: Session, *, dispute_id: int, booking: Booking, command: str, resolution_code: str | None, requested: str | None
) -> str | None:
    """The contested receipt's outcome this decision settles, or ``None`` when there is nothing to settle.

    Wave 3.1: ``cash_outcome`` is explicit in the command. It must agree with a resolution code that already
    implies one, and a payment dispute over a *contested* receipt cannot be closed without an outcome - otherwise
    the receipt would stay ``contested`` with no open dispute left to settle it (§6, AC26).
    """
    implied = PAYMENT_RESOLUTION_CASH_OUTCOME.get(resolution_code or "") if command == "resolve" else None
    if requested is not None and requested not in CASH_RESOLUTION_OUTCOMES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "cash_outcome"})
    if requested is not None and implied is not None and requested != implied:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={
            "field": "cash_outcome", "resolution_code": resolution_code, "implied": implied})
    if command not in DISPUTE_DECISION_COMMANDS:
        if requested is not None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "cash_outcome", "command": command})
        return None
    dispute_type = session.execute(select(DisputeV2.dispute_type).where(DisputeV2.id == dispute_id)).scalar_one()
    contested = dispute_type == DisputeType.PAYMENT.value and booking.cash_status == CashCollectionStatus.CONTESTED.value
    if not contested:
        if requested is not None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={
                "field": "cash_outcome", "dispute_type": dispute_type, "cash_status": booking.cash_status})
        return None
    outcome = requested or implied
    if outcome is None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "cash_outcome", "cash_status": booking.cash_status})
    return outcome


def dispute_command(
    session: Session, *, dispute_public_id_value: str, actor_user_id: int, command: str, expected_version: int,
    resolution_code: str | None = None, resolution_text: str | None = None, reason: str | None = None,
    cash_outcome: str | None = None, now: datetime | None = None,
) -> DisputeV2:
    """S8 ``start_review | resolve | reject``. Records the decision only - money/service changes are separate
    commands (B13, W8, §11), except the contested cash receipt that STATE_MACHINES §6/§8 settles *through* this
    decision (``cash_outcome``, applied by A4 in this transaction).

    Capabilities (wave 3.1, v1 Q13/Q38 parity): ``start_review`` and leaving a note need ``ops.dispute_resolve``
    (operator+); ``resolve`` and ``reject`` need ``ops.dispute_decide`` (admin+); ``commission_adjusted`` also
    needs ``finance.adjustment``.

    Lock order: booking -> dispute. After a blocking dispute closes on a booking whose commission is still held, the
    booking goes to the finance review queue through A4 (U8: no automatic capture)."""
    now = _now(now)
    if command not in DISPUTE_COMMAND_TARGET:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "command"})
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    identity_service.require_capability(caps, Capability.OPS_DISPUTE_RESOLVE)
    if command in DISPUTE_DECISION_COMMANDS:
        identity_service.require_capability(caps, Capability.OPS_DISPUTE_DECIDE)
    dispute_id, booking_id = _dispute_ids(session, dispute_public_id_value)
    booking = bookings_service.lock_booking(session, booking_id)
    cash_outcome = _cash_outcome_for_decision(
        session, dispute_id=dispute_id, booking=booking, command=command,
        resolution_code=resolution_code, requested=cash_outcome,
    )
    if cash_outcome is not None:
        # STATE_MACHINES §6/§8: the payment decision is A4's separate cash command, in this transaction, after the
        # booking lock and before the dispute row lock (ADR-0017). A rollback of this command undoes it too.
        booking, _ = bookings_service.resolve_contested_cash_receipt(
            session, booking_id=booking.id, outcome=cash_outcome, actor_user_id=actor_user_id,
            reason=(resolution_text or "").strip() or f"dispute {resolution_code or command}", now=now,
        )
    dispute = _lock_dispute(session, dispute_id)
    _check_version(dispute.version, expected_version)
    target = DISPUTE_COMMAND_TARGET[command]
    DISPUTE.assert_transition(dispute.status, target, command)
    previous = dispute.status
    note = (reason or resolution_text or "").strip() or None
    if command == "start_review":
        dispute.assigned_to = actor_user_id
    elif command == "resolve":
        if resolution_code is None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "resolution_code"})
        if resolution_code in rules.FINANCIAL_RESOLUTION_CODES:
            identity_service.require_capability(caps, Capability.FINANCE_ADJUSTMENT)
        dispute.resolution_code = resolution_code
        dispute.resolution_text = (resolution_text or "").strip() or None
    else:
        if not (reason or resolution_text or "").strip():
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
        dispute.resolution_text = (reason or resolution_text or "").strip()
    if target in rules.TERMINAL_DISPUTE_STATUSES:
        dispute.decided_by = actor_user_id
        dispute.decided_at = now
        dispute.assigned_to = dispute.assigned_to or actor_user_id
    dispute.status = target
    dispute.version += 1
    dispute.updated_at = now
    session.flush()
    details: dict[str, Any] = {
        "dispute_id": dispute_public_id(dispute), "booking_id": bookings_service.booking_public_id(booking),
        "from_status": previous, "to_status": target, "resolution_code": dispute.resolution_code,
    }
    if cash_outcome is not None:
        details["cash_outcome"] = cash_outcome
    if command == "start_review" and note is not None:
        details["note"] = note  # Q38 parity: the operator reviews and leaves a comment; the decision is admin+
    _audit(session, actor_user_id=actor_user_id, entity_type="dispute", action=f"dispute_{command}", details=details)
    if target in rules.TERMINAL_DISPUTE_STATUSES:
        _emit_dispute_event(session, booking, dispute, EventType.DISPUTE_RESOLVED, now)
        _tracking_evidence(session, trip_id=booking.trip_id, dispute_id=dispute.id, hold=False, now=now)
        _after_blocking_dispute_closed(session, booking, dispute, now)
    return dispute


def _after_blocking_dispute_closed(session: Session, booking: Booking, dispute: DisputeV2, now: datetime) -> None:
    """Q84: never capture automatically. A held commission whose last blocking dispute closed goes to the
    finance review queue (A4 ``mark_finance_review_after_dispute``); finance decides with B13 ``finalize_fee``."""
    if dispute.dispute_type not in rules.BLOCKING_DISPUTE_TYPE_VALUES:
        return
    if booking.commission_status != CommissionStatus.HELD.value or blocking_dispute_open(session, booking.id):
        return
    mark = getattr(bookings_service, "mark_finance_review_after_dispute", None)
    if mark is None:
        logger.warning("bookings.service.mark_finance_review_after_dispute missing; booking %s stays held", booking.id)
        return
    try:
        with session.begin_nested():
            mark(session, booking_id=booking.id, reason=f"dispute_{dispute.status}: {dispute.dispute_type}", now=now)
    except DomainError as exc:
        if exc.code is not ErrorCode.INVALID_STATE_TRANSITION:
            raise
        # Service not finished yet: the later completion sees a clear probe and captures (AC20).
        logger.info("booking %s not finalizable after dispute %s: %s", booking.id, dispute.id, exc.details)


def emit_dispute_escalations(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """Worker (§9.5): active disputes past ``escalate_at`` get ``escalated_at`` (S7 ``escalated=true`` queue).

    Each escalation emits one staff-only ``dispute.escalation_due`` (dedup per dispute). ``SKIP LOCKED``: never waits."""
    now = _now(now)
    rows = list(
        session.execute(
            select(DisputeV2)
            .where(DisputeV2.status.in_(_ACTIVE), DisputeV2.escalated_at.is_(None), DisputeV2.escalate_at <= now)
            .order_by(DisputeV2.escalate_at, DisputeV2.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    for dispute in rows:
        dispute.escalated_at = now
    session.flush()
    for dispute in rows:
        booking = bookings_service.get_booking(session, dispute.booking_id)
        _emit(session, EventType.DISPUTE_ESCALATION_DUE, aggregate_type="dispute", aggregate_public_id=dispute_public_id(dispute),
              aggregate_version=dispute.version, now=now, aggregate_id=dispute.id, dedup_key=f"dispute_escalation:{dispute.id}",
              payload={"booking_id": bookings_service.booking_public_id(booking), "dispute_type": dispute.dispute_type,
                       "escalate_at": ensure_aware_utc(dispute.escalate_at).isoformat().replace("+00:00", "Z")})
    return len(rows)


# ==============================================================================================================
# ratings S1 (§17.2, AC36)
# ==============================================================================================================


def _publish_rating(session: Session, rating: RatingV2, booking: Booking, now: datetime) -> None:
    rating.published_at = now
    session.flush()
    _emit(session, EventType.RATING_PUBLISHED, aggregate_type="booking",
          aggregate_public_id=bookings_service.booking_public_id(booking), aggregate_version=booking.version,
          payload={"booking_id": bookings_service.booking_public_id(booking), "service_type": rating.service_type,
                   "subject_side": rating.subject_side}, now=now, aggregate_id=booking.id,
          dedup_key=f"rating_published:{rating.id}")


def create_rating(
    session: Session, *, booking_public_id_value: str, actor_user_id: int, subject_side: str, stars: int,
    comment: str | None = None, warnings: list[dict] | None = None, filter_hits: list[ContactFilterHit] | None = None,
    now: datetime | None = None,
) -> RatingV2:
    """S1: a participant rates the other side of a completed booking within the 7-day window. Both rated -> both
    published now; otherwise the worker publishes after the window (§17.2). Lock order: booking -> ratings."""
    now = _now(now)
    if not 1 <= int(stars) <= 5:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "stars"})
    snapshot = bookings_service.get_booking_by_public_id(session, booking_public_id_value)
    side = bookings_service.participant_side(snapshot, actor_user_id)
    if side is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if subject_side != rules.counterpart_side(side.value):
        raise DomainError(ErrorCode.RATING_NOT_ALLOWED, details={"reason": "subject_must_be_counterparty"})
    booking = bookings_service.lock_booking(session, snapshot.id)
    if booking.service_status != rules.COMPLETED_STATUS:
        raise DomainError(ErrorCode.RATING_NOT_ALLOWED, details={"reason": "booking_not_completed"})
    if not rules.rating_window_open(booking.completed_at, now):
        raise DomainError(ErrorCode.RATING_NOT_ALLOWED, details={"reason": "rating_window_closed"})
    subject_user_id = booking.driver_user_id if subject_side == ActorSide.DRIVER.value else booking.client_user_id
    masked = filter_free_text(
        session, actor_user_id=actor_user_id, field="comment", subject_type="rating",
        text_value=(comment or "").strip() or None, warnings=warnings, filter_hits=filter_hits,
    )
    rating = RatingV2(
        public_id=new_public_uuid(), booking_id=booking.id, author_user_id=actor_user_id, subject_user_id=subject_user_id,
        author_side=side.value, subject_side=subject_side, service_type=booking.service_type, stars=int(stars),
        comment=masked, moderation_status="visible", created_at=now,
    )
    session.add(rating)
    _flush_or_translate(session, {RATING_UNIQUE: lambda: DomainError(ErrorCode.RATING_ALREADY_EXISTS)})
    counterpart = session.execute(
        select(RatingV2).where(RatingV2.booking_id == booking.id, RatingV2.author_user_id == subject_user_id,
                               RatingV2.subject_user_id == actor_user_id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if counterpart is not None:
        for item in (counterpart, rating):
            if item.published_at is None:
                _publish_rating(session, item, booking, now)
        _write_snapshots(session, [(counterpart.subject_user_id, booking.service_type), (subject_user_id, booking.service_type)], now)
    return rating


def publish_due_ratings(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """Worker (§17.2): unpublished ratings whose booking's rating window has ended are published (one event each)."""
    now = _now(now)
    rows = session.execute(
        select(RatingV2, Booking)
        .join(Booking, Booking.id == RatingV2.booking_id)
        .where(RatingV2.published_at.is_(None), Booking.completed_at.is_not(None),
               Booking.completed_at <= now - rules.RATING_WINDOW)
        .order_by(RatingV2.id)
        .limit(limit)
        .with_for_update(skip_locked=True, of=RatingV2)
    ).all()
    for rating, booking in rows:
        _publish_rating(session, rating, booking, now)
    if rows:
        _write_snapshots(session, [(rating.subject_user_id, rating.service_type) for rating, _ in rows], now)
    return len(rows)


def ratings_for_viewer(session: Session, booking: Booking, viewer_user_id: int) -> list[RatingV2]:
    """Own ratings always; the counterpart's rating of the viewer only once published."""
    return list(
        session.execute(
            select(RatingV2).where(
                RatingV2.booking_id == booking.id,
                or_(RatingV2.author_user_id == viewer_user_id,
                    and_(RatingV2.subject_user_id == viewer_user_id, RatingV2.published_at.is_not(None))),
            ).order_by(RatingV2.id)
        ).scalars()
    )


# ==============================================================================================================
# support / SOS S13-S17 (§16)
# ==============================================================================================================


def create_support_ticket(
    session: Session, *, actor_user_id: int, kind: SupportTicketKind | str, booking_public_id_value: str | None = None,
    message: str | None = None, warnings: list[dict] | None = None, filter_hits: list[ContactFilterHit] | None = None,
    now: datetime | None = None,
) -> SupportTicket:
    """S14. SOS opens in any booking state (obligation, D16). ``booking_id`` only for the actor's own booking (404).

    SOS is never rate limited (BR M3): a repeat press while the user's SOS for the same booking (or the same
    booking-less SOS) is not resolved returns that ticket, increments ``press_count`` and alerts staff again.
    Support tickets keep the per-hour limit. Lock: requester ``users`` row FOR NO KEY UPDATE (serialises the dedup /
    rate-limit read and account deletion)."""
    now = _now(now)
    ticket_kind = SupportTicketKind(kind)
    booking: Booking | None = None
    if booking_public_id_value:
        booking = bookings_service.get_booking_by_public_id(session, booking_public_id_value)
        if bookings_service.participant_side(booking, actor_user_id) is None:
            raise DomainError(ErrorCode.NOT_FOUND)
    identity_service.lock_user_eligibility(session, [actor_user_id], mode="update")
    booking_pid = bookings_service.booking_public_id(booking) if booking else None
    trip_pid = _trip_public_id(session, booking.trip_id) if booking else None
    if ticket_kind is SupportTicketKind.SOS:
        existing = session.execute(
            select(SupportTicket).where(
                SupportTicket.user_id == actor_user_id, SupportTicket.kind == SupportTicketKind.SOS.value,
                SupportTicket.status != SupportTicketStatus.RESOLVED.value,
                SupportTicket.booking_id.is_(None) if booking is None else SupportTicket.booking_id == booking.id,
            ).order_by(SupportTicket.id.desc()).limit(1).with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if existing is not None:
            existing.press_count += 1
            existing.last_pressed_at = now
            existing.updated_at = now
            session.flush()
            _emit(session, EventType.SUPPORT_SOS_RAISED, aggregate_type="support_ticket",
                  aggregate_public_id=ticket_public_id(existing), aggregate_version=existing.version, now=now,
                  aggregate_id=existing.id, payload={"ticket_id": ticket_public_id(existing), "booking_id": booking_pid, "trip_id": trip_pid})
            return existing
    else:
        recent = int(session.execute(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.user_id == actor_user_id, SupportTicket.kind == ticket_kind.value,
                SupportTicket.created_at >= now - rules.SUPPORT_TICKET_RATE_WINDOW,
            )
        ).scalar_one())
        limit = rules.SUPPORT_TICKET_RATE_LIMIT
        if recent >= limit:
            raise DomainError(ErrorCode.RATE_LIMITED, details={"limit": limit, "window_s": int(rules.SUPPORT_TICKET_RATE_WINDOW.total_seconds())})
    masked = filter_free_text(
        session, actor_user_id=actor_user_id, field="message", subject_type="support_ticket",
        text_value=(message or "").strip() or None, warnings=warnings, filter_hits=filter_hits,
    )
    ticket = SupportTicket(
        public_id=new_public_uuid(), kind=ticket_kind.value, status=SupportTicketStatus.OPEN.value, user_id=actor_user_id,
        booking_id=booking.id if booking else None, trip_id=booking.trip_id if booking else None, message=masked,
        press_count=1, last_pressed_at=now, version=1, created_at=now, updated_at=now,
    )
    session.add(ticket)
    session.flush()
    if ticket_kind is SupportTicketKind.SOS:
        event_type, payload = EventType.SUPPORT_SOS_RAISED, {"ticket_id": ticket_public_id(ticket), "booking_id": booking_pid, "trip_id": trip_pid}
    else:
        event_type, payload = EventType.SUPPORT_TICKET_OPENED, {"ticket_id": ticket_public_id(ticket), "kind": ticket.kind,
                                                                "booking_id": booking_pid, "trip_id": trip_pid}
    _emit(session, event_type, aggregate_type="support_ticket", aggregate_public_id=ticket_public_id(ticket),
          aggregate_version=1, payload=payload, now=now, aggregate_id=ticket.id)
    return ticket


def _trip_public_id(session: Session, trip_id: int) -> str:
    from app.modules.trips import service as trips_service

    return trips_service.trip_public_id(trips_service.get_trip(session, trip_id))


def list_user_tickets(session: Session, user_id: int, *, before: tuple[datetime, int] | None, limit: int) -> list[SupportTicket]:
    stmt = select(SupportTicket).where(SupportTicket.user_id == user_id)
    if before is not None:
        moment, row_id = before
        stmt = stmt.where(or_(SupportTicket.created_at < moment, and_(SupportTicket.created_at == moment, SupportTicket.id < row_id)))
    return list(session.execute(stmt.order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc()).limit(limit)).scalars())


def admin_list_tickets(
    session: Session, *, actor_user_id: int, kind: str | None, status: str | None, after_id: int | None, limit: int,
    now: datetime | None = None,
) -> list[SupportTicket]:
    _require(session, actor_user_id, Capability.OPS_VIEW, _now(now))
    stmt = select(SupportTicket)
    if kind is not None:
        stmt = stmt.where(SupportTicket.kind == SupportTicketKind(kind).value)
    if status is not None:
        stmt = stmt.where(SupportTicket.status == SupportTicketStatus(status).value)
    if after_id is not None:
        stmt = stmt.where(SupportTicket.id > after_id)
    return list(session.execute(stmt.order_by(SupportTicket.id).limit(limit)).scalars())


SUPPORT_COMMAND_TARGET = {"acknowledge": SupportTicketStatus.ACKNOWLEDGED.value, "resolve": SupportTicketStatus.RESOLVED.value}


def support_ticket_command(
    session: Session, *, ticket_public_id_value: str, actor_user_id: int, command: str, expected_version: int,
    note: str | None = None, now: datetime | None = None,
) -> SupportTicket:
    """S17 (``ops.trust_review``). Acknowledging promises no response time (§16)."""
    now = _now(now)
    if command not in SUPPORT_COMMAND_TARGET:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "command"})
    _require(session, actor_user_id, Capability.OPS_TRUST_REVIEW, now)
    value = parse_public_id(ticket_public_id_value, PublicIdPrefix.SUPPORT_TICKET)
    ticket = session.execute(
        select(SupportTicket).where(SupportTicket.public_id == value).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if ticket is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    _check_version(ticket.version, expected_version)
    target = SUPPORT_COMMAND_TARGET[command]
    SUPPORT_TICKET.assert_transition(ticket.status, target, command)
    previous = ticket.status
    if command == "acknowledge":
        ticket.acknowledged_by, ticket.acknowledged_at = actor_user_id, now
    else:
        if not (note or "").strip():
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "note"})
        ticket.resolved_by, ticket.resolved_at, ticket.resolution_note = actor_user_id, now, note.strip()
    ticket.status = target
    ticket.version += 1
    ticket.updated_at = now
    session.flush()
    _audit(session, actor_user_id=actor_user_id, entity_type="support_ticket", action=f"support_ticket_{command}",
           details={"ticket_id": ticket_public_id(ticket), "kind": ticket.kind, "from_status": previous, "to_status": target})
    _emit(session, EventType.SUPPORT_TICKET_STATUS_CHANGED, aggregate_type="user",
          aggregate_public_id=identity_service.user_public_id(session, ticket.user_id), aggregate_version=ticket.version,
          payload={"ticket_id": ticket_public_id(ticket), "kind": ticket.kind, "from_status": previous, "to_status": target},
          now=now, aggregate_id=ticket.user_id)
    return ticket


def _tracking_evidence(session: Session, *, trip_id: int, dispute_id: int, hold: bool, now: datetime) -> None:
    """M1: hold this trip's raw GPS while a dispute is open, release it when the dispute closes.

    Lazy, like :func:`booking_live_state`: without the tracking module nothing happens and the raw points still
    expire after ``RAW_POINT_RETENTION`` - the limitation is stated, never hidden.
    """
    try:
        from app.modules.tracking import service as tracking_service

        hold_fn = tracking_service.hold_trip_evidence
        release_fn = tracking_service.release_trip_evidence
    except (ImportError, AttributeError):
        logger.warning("tracking evidence hold unavailable; raw points of trip %s expire normally (M1)", trip_id)
        return
    source = TrackingEvidenceSource.DISPUTE.value
    if hold:
        hold_fn(session, trip_id=trip_id, reason=TrackingEvidenceReason.DISPUTE.value, source_type=source,
                source_id=dispute_id, now=now)
    else:
        release_fn(session, trip_id=trip_id, source_type=source, source_id=dispute_id, now=now)


def booking_live_state(session: Session, booking_id: int):  # noqa: ANN201 - tracking.service.BookingLiveState | None
    """A6 export, lazily (wave 3 parallel): ``None`` when the tracking module is not importable yet."""
    try:
        from app.modules.tracking import service as tracking_service

        reader = tracking_service.booking_live_state
    except (ImportError, AttributeError):
        return None
    return reader(session, booking_id)


# ==============================================================================================================
# Q45 trust review queue S18-S20 and consumers
# ==============================================================================================================


def open_or_update_review(
    session: Session, *, subject_user_id: int, signal_type: TrustSignalType, evidence: dict[str, Any], at: datetime
) -> tuple[TrustReviewItem, bool]:
    """One open/under_review item per (subject, signal) - a repeated signal merges evidence into it (§12.1).

    Returns ``(item, opened)``. No automatic ban or fine. Caller holds the subject's advisory lock."""
    at = ensure_aware_utc(at)
    item = session.execute(
        select(TrustReviewItem)
        .where(TrustReviewItem.subject_user_id == subject_user_id, TrustReviewItem.signal_type == signal_type.value,
               TrustReviewItem.status.in_((TrustReviewStatus.OPEN.value, TrustReviewStatus.UNDER_REVIEW.value)))
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if item is not None:
        merged = rules.merge_evidence(item.evidence, evidence)
        if merged == item.evidence:
            return item, False  # duplicate signal (e.g. redelivered event): nothing new
        item.evidence = merged
        item.signal_count += 1
        item.last_signal_at = max(ensure_aware_utc(item.last_signal_at), at)
        item.version += 1
        item.updated_at = utc_now()
        session.flush()
        return item, False
    item = TrustReviewItem(
        public_id=new_public_uuid(), subject_user_id=subject_user_id, signal_type=signal_type.value,
        status=TrustReviewStatus.OPEN.value, evidence=rules.merge_evidence({}, evidence), signal_count=1,
        last_signal_at=at, version=1,
    )
    session.add(item)
    session.flush()
    subject = identity_service.user_public_id(session, subject_user_id)
    _emit(session, EventType.TRUST_REVIEW_OPENED, aggregate_type="trust_review", aggregate_public_id=review_public_id(item),
          aggregate_version=1, payload={"review_id": review_public_id(item), "signal_type": item.signal_type, "subject_id": subject},
          now=at, aggregate_id=item.id)
    return item, True


# BR L7 (orchestrator default, pending user confirmation): proof_code-only hits do not count toward Q45.
NON_STRIKE_CATEGORIES: frozenset[str] = frozenset({contact_filter.ContactCategory.PROOF_CODE.value})
_COUNTABLE_HIT = text(
    "NOT (cardinality(contact_filter_hits.categories) > 0 "
    "AND contact_filter_hits.categories <@ ARRAY['proof_code']::text[])"
)
assert NON_STRIKE_CATEGORIES == {"proof_code"}  # keep in sync with _COUNTABLE_HIT


def _counts_toward_strikes(categories: Sequence[str]) -> bool:
    return not (categories and set(categories) <= NON_STRIKE_CATEGORIES)


def consume_contact_filter_hit(session: Session, event: DispatchedEvent) -> None:
    """Consumer ``contact_filter_strikes`` (``trust.contact_filter.hit``, Q45).

    Every hit is logged once (``UNIQUE(source_event_id)``); when earlier hits of the actor in
    ``CONTACT_FILTER_STRIKE_WINDOW`` reach ``CONTACT_FILTER_FREE_HITS`` it is a strike (one per event); strikes in
    ``STRIKE_REVIEW_WINDOW`` reaching ``STRIKES_FOR_REVIEW`` open/update one ``contact_filter_strikes`` review item."""
    payload = dict(event.payload)
    if event.aggregate_type == "user" and event.aggregate_id:
        user_id = int(event.aggregate_id)
    else:
        user_id = identity_service.resolve_user_id(session, str(payload.get("actor_id") or event.aggregate_public_id))
    occurred = ensure_aware_utc(event.occurred_at)
    subject_type = str(payload.get("subject_type") or "unknown")[:32]
    categories = [str(item) for item in payload.get("categories") or []]
    _advisory_lock_user(session, user_id)
    hit_id = session.execute(
        pg_insert(ContactFilterHitRecord)
        .values(user_id=user_id, source_event_id=event.event_id, subject_type=subject_type,
                field=(str(payload["field"])[:64] if payload.get("field") else None), categories=categories,
                match_count=int(payload.get("match_count") or 0), occurred_at=occurred)
        .on_conflict_do_nothing(index_elements=["source_event_id"])
        .returning(ContactFilterHitRecord.id)
    ).scalar_one_or_none()
    if hit_id is None:
        return
    if not _counts_toward_strikes(categories):
        return  # BR L7: a proof_code-only match (e.g. an amount "150000") stays as evidence but is never a strike
    prior = int(session.execute(
        select(func.count(ContactFilterHitRecord.id)).where(
            ContactFilterHitRecord.user_id == user_id,
            ContactFilterHitRecord.id != hit_id,
            _COUNTABLE_HIT,
            ContactFilterHitRecord.occurred_at >= occurred - trust.CONTACT_FILTER_STRIKE_WINDOW,
            or_(ContactFilterHitRecord.occurred_at < occurred,
                and_(ContactFilterHitRecord.occurred_at == occurred, ContactFilterHitRecord.id < hit_id)),
        )
    ).scalar_one())
    if not trust.hit_is_strike(prior):
        return
    strike_id = session.execute(
        pg_insert(ContactStrike)
        .values(user_id=user_id, source_event_id=event.event_id, subject_type=subject_type, categories=categories,
                reason_code=rules.STRIKE_REASON_CONTACT_FILTER, occurred_at=occurred)
        .on_conflict_do_nothing(index_elements=["source_event_id"])
        .returning(ContactStrike.id)
    ).scalar_one_or_none()
    if strike_id is None:
        return
    window_start = occurred - trust.STRIKE_REVIEW_WINDOW
    strikes = session.execute(
        select(ContactStrike.source_event_id).where(
            ContactStrike.user_id == user_id, ContactStrike.occurred_at >= window_start, ContactStrike.occurred_at <= occurred
        ).order_by(ContactStrike.occurred_at, ContactStrike.id)
    ).scalars().all()
    actor_public_id = identity_service.user_public_id(session, user_id)
    strike_payload: dict[str, Any] = {"actor_id": actor_public_id, "strike_count": len(strikes),
                                      "reason_code": rules.STRIKE_REASON_CONTACT_FILTER, "subject_type": subject_type}
    if payload.get("subject_id") is not None:
        strike_payload["subject_id"] = str(payload["subject_id"])
    _emit(session, EventType.CONTACT_STRIKE_RECORDED, aggregate_type="user", aggregate_public_id=actor_public_id,
          aggregate_version=1, payload=strike_payload, now=occurred, aggregate_id=user_id)
    if trust.strikes_need_review(len(strikes)):
        hits = int(session.execute(
            select(func.count(ContactFilterHitRecord.id)).where(
                ContactFilterHitRecord.user_id == user_id, ContactFilterHitRecord.occurred_at >= window_start,
                ContactFilterHitRecord.occurred_at <= occurred, _COUNTABLE_HIT)
        ).scalar_one())
        open_or_update_review(
            session, subject_user_id=user_id, signal_type=TrustSignalType.CONTACT_FILTER_STRIKES, at=occurred,
            evidence={"source_event_ids": [str(item) for item in strikes], "strike_count": len(strikes), "hit_count": hits,
                      "window_days": trust.STRIKE_REVIEW_WINDOW.days},
        )


def _chat_activity(session: Session, booking_id: int) -> ChatActivitySummary | None:
    try:
        from app.modules.communications import service as communications_service

        reader = communications_service.chat_activity_for_booking
    except (ImportError, AttributeError):
        logger.info("communications.service.chat_activity_for_booking unavailable; quick_cancel_after_chat skipped")
        return None
    return reader(session, booking_id)


def consume_booking_cancelled(session: Session, event: DispatchedEvent) -> None:
    """Consumer ``cancellation_signals`` (``booking.cancelled``, Q45): quick cancel after a chat contact-filter hit
    (subject: the cancelling side) and repeated cancellations of one client+driver pair (subject: the party that
    cancelled this booking; the evidence lists the pair's cancelled bookings).
    Operator/system cancellations are not signals."""
    if event.aggregate_type == "booking" and event.aggregate_id:
        booking_id = int(event.aggregate_id)
    else:
        booking_id = bookings_service.resolve_booking_id(session, event.aggregate_public_id)
    booking = bookings_service.get_booking(session, booking_id)
    side = booking.cancelled_by_side
    if booking.service_status != "cancelled" or side not in rules.PARTICIPANT_SIDES:
        return
    cancelled_at = ensure_aware_utc(booking.cancelled_at or event.occurred_at)
    booking_pid = bookings_service.booking_public_id(booking)
    canceller = booking.client_user_id if side == ActorSide.CLIENT.value else booking.driver_user_id

    summary = _chat_activity(session, booking.id)
    if summary is not None and trust.is_quick_cancel_after_chat(summary.last_contact_filter_hit_at, cancelled_at):
        _advisory_lock_user(session, canceller)
        open_or_update_review(
            session, subject_user_id=canceller, signal_type=TrustSignalType.QUICK_CANCEL_AFTER_CHAT, at=cancelled_at,
            evidence={"booking_ids": [booking_pid], "hit_count": int(summary.contact_filter_hit_count)},
        )

    pair = session.execute(
        select(Booking.public_id).where(
            Booking.client_user_id == booking.client_user_id, Booking.driver_user_id == booking.driver_user_id,
            Booking.service_status == "cancelled", Booking.cancelled_by_side.in_(sorted(rules.PARTICIPANT_SIDES)),
            Booking.cancelled_at >= cancelled_at - trust.REPEATED_PAIR_CANCEL_WINDOW, Booking.cancelled_at <= cancelled_at,
        ).order_by(Booking.cancelled_at, Booking.id)
    ).scalars().all()
    if trust.is_repeated_pair_cancellation(len(pair)):
        _advisory_lock_user(session, canceller)
        open_or_update_review(
            session, subject_user_id=canceller, signal_type=TrustSignalType.REPEATED_PAIR_CANCELLATIONS,
            at=cancelled_at,
            evidence={"booking_ids": [format_public_id(PublicIdPrefix.BOOKING, value) for value in pair],
                      "cancel_count": len(pair), "window_days": trust.REPEATED_PAIR_CANCEL_WINDOW.days},
        )


def admin_list_reviews(
    session: Session, *, actor_user_id: int, status: str | None, signal_type: str | None, after_id: int | None, limit: int,
    now: datetime | None = None,
) -> list[TrustReviewItem]:
    _require(session, actor_user_id, Capability.OPS_VIEW, _now(now))
    stmt = select(TrustReviewItem)
    if status is not None:
        stmt = stmt.where(TrustReviewItem.status == TrustReviewStatus(status).value)
    if signal_type is not None:
        stmt = stmt.where(TrustReviewItem.signal_type == TrustSignalType(signal_type).value)
    if after_id is not None:
        stmt = stmt.where(TrustReviewItem.id > after_id)
    return list(session.execute(stmt.order_by(TrustReviewItem.id).limit(limit)).scalars())


REVIEW_COMMAND_TARGET = {
    "start_review": TrustReviewStatus.UNDER_REVIEW.value,
    "dismiss": TrustReviewStatus.DISMISSED.value,
    "action": TrustReviewStatus.ACTIONED.value,
}


def review_command(
    session: Session, *, review_public_id_value: str, actor_user_id: int, command: str, expected_version: int,
    decision: str | None, note: str, now: datetime | None = None,
) -> TrustReviewItem:
    """S19 (``ops.trust_review``). ``warning_issued`` -> ``trust.warning_issued`` to the user; ``escalated_to_admin``
    is a record only (an admin blocks eligibility separately through I5)."""
    now = _now(now)
    if command not in REVIEW_COMMAND_TARGET:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "command"})
    _require(session, actor_user_id, Capability.OPS_TRUST_REVIEW, now)
    if not (note or "").strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "note"})
    value = parse_public_id(review_public_id_value, PublicIdPrefix.TRUST_REVIEW)
    item = session.execute(
        select(TrustReviewItem).where(TrustReviewItem.public_id == value).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if item is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    _check_version(item.version, expected_version)
    target = REVIEW_COMMAND_TARGET[command]
    TRUST_REVIEW.assert_transition(item.status, target, command)
    stored_decision = rules.review_decision_for(command, decision)
    previous = item.status
    item.note = note.strip()
    if command == "start_review":
        item.assigned_to = actor_user_id
    else:
        item.decision, item.decided_by, item.decided_at = stored_decision, actor_user_id, now
    item.status = target
    item.version += 1
    item.updated_at = now
    session.flush()
    _audit(session, actor_user_id=actor_user_id, entity_type="trust_review", action=f"trust_review_{command}",
           details={"review_id": review_public_id(item), "signal_type": item.signal_type, "from_status": previous,
                    "to_status": target, "decision": stored_decision})
    if stored_decision == TrustReviewDecision.WARNING_ISSUED.value:
        _emit(session, EventType.TRUST_WARNING_ISSUED, aggregate_type="user",
              aggregate_public_id=identity_service.user_public_id(session, item.subject_user_id), aggregate_version=item.version,
              payload={"review_id": review_public_id(item), "signal_type": item.signal_type}, now=now,
              aggregate_id=item.subject_user_id)
    return item


def user_strikes(session: Session, *, actor_user_id: int, user_public_id_value: str, now: datetime | None = None) -> tuple[int, list[ContactStrike]]:
    """S20 (``ops.view``): strikes of the last ``STRIKE_REVIEW_WINDOW`` (newest first)."""
    now = _now(now)
    _require(session, actor_user_id, Capability.OPS_VIEW, now)
    user_id = identity_service.resolve_user_id(session, user_public_id_value)
    strikes = list(session.execute(
        select(ContactStrike).where(ContactStrike.user_id == user_id, ContactStrike.occurred_at >= now - trust.STRIKE_REVIEW_WINDOW)
        .order_by(ContactStrike.occurred_at.desc(), ContactStrike.id.desc())
    ).scalars())
    return user_id, strikes


# ==============================================================================================================
# account deletion (§17.8, N4, I4)
# ==============================================================================================================


@dataclass(frozen=True, slots=True)
class TrustBlockingState:
    """Open trust cases that block account deletion: active disputes on the user's bookings, open SOS tickets."""

    open_disputes: int
    open_sos_tickets: int

    @property
    def blocks_deletion(self) -> bool:
        return bool(self.open_disputes or self.open_sos_tickets)

    def as_details(self) -> dict[str, int]:
        return {"open_disputes": self.open_disputes, "open_sos_tickets": self.open_sos_tickets}


def blocking_state_for_user(session: Session, user_id: int, *, lock: bool = False) -> TrustBlockingState:
    """Read-only. ``lock`` takes ``FOR SHARE`` on the found dispute and ticket rows (after the deletion's users and
    bookings locks: users -> bookings -> disputes_v2 -> support_tickets -> wallet). New disputes/SOS lock the parties'
    ``users`` rows first, so they serialise with the deletion's ``users FOR UPDATE``. Zeros without the tables."""
    if not platform_service.table_exists(session, DisputeV2.__tablename__):
        return TrustBlockingState(0, 0)
    disputes = (
        select(DisputeV2.id)
        .join(Booking, Booking.id == DisputeV2.booking_id)
        .where(
            DisputeV2.status.in_(_ACTIVE),
            or_(Booking.driver_user_id == user_id, DisputeV2.opened_by_user_id == user_id,
                and_(Booking.client_user_id == user_id, DisputeV2.dispute_type.not_in(sorted(rules.CLIENT_HIDDEN_DISPUTE_TYPES)))),
        )
        .order_by(DisputeV2.id)
    )
    tickets = select(SupportTicket.id).where(
        SupportTicket.user_id == user_id, SupportTicket.kind == SupportTicketKind.SOS.value,
        SupportTicket.status != SupportTicketStatus.RESOLVED.value,
    ).order_by(SupportTicket.id)
    if lock:
        disputes = disputes.with_for_update(read=True, of=DisputeV2)
        tickets = tickets.with_for_update(read=True)
    return TrustBlockingState(len(session.execute(disputes).all()), len(session.execute(tickets).all()))


class _DeferredCommitSession:
    """Adapter for reusing the v1 ``delete_own_account`` inside the v2 idempotent runner (ADR-0005).

    The v1 service commits; here ``commit`` only flushes and ``rollback`` is left to the runner, so the deletion and
    its idempotency record commit together (a refused deletion is rolled back with the stored 409)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.flush()

    def rollback(self) -> None:  # the v2 runner rolls back the savepoint / transaction
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def delete_account_v2(session: Session, *, actor_user_id: int) -> None:
    """I4 ``DELETE /me``: the v1 deletion service (orders -> users -> driver_profiles -> bookings -> trust -> wallet
    checks, anonymise-and-retain). A refusal -> ``409 ACCOUNT_DELETION_BLOCKED`` with all blocking counters."""
    from app.models import User
    from app.modules.wallet import service as wallet_service
    from app.services import account_deletion_service

    user = session.get(User, actor_user_id)
    if user is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    result = account_deletion_service.delete_own_account(_DeferredCommitSession(session), user)  # type: ignore[arg-type]
    if isinstance(result, dict):
        return
    body = json.loads(result.body)
    code = str(body.get("error", {}).get("code", "blocked"))
    if result.status_code == 403:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": code.lower()})
    bookings_state = bookings_service.blocking_state_for_user(session, actor_user_id)
    wallet_state = wallet_service.blocking_state_for_user(session, actor_user_id)
    trust_state = blocking_state_for_user(session, actor_user_id)
    details: dict[str, Any] = {
        "reason": code.lower(),
        "active_orders": account_deletion_service.blocking_orders(session, user),
        **bookings_state.as_details(),
        **wallet_state.as_details(),
        **trust_state.as_details(),
    }
    details["open_disputes"] = trust_state.open_disputes + account_deletion_service.blocking_disputes(session, user)
    raise DomainError(ErrorCode.ACCOUNT_DELETION_BLOCKED, details=details)


# ==============================================================================================================
# S9-S12: blocks (§8.1), reports and fraud signals (§17.3) - wave 6
# ==============================================================================================================


def block_user(session: Session, *, actor_user_id: int, blocked_public_id: str, now: datetime | None = None) -> UserBlock:
    """S9. Idempotent and silent: the blocked user is not notified and no reason is stored (§8.1).

    A block is not a moderation verdict - it only removes the pair from each other's feed, proposals and accept
    path. Obligations already agreed (an active booking) are untouched: they are finished, then the two simply
    do not meet again.
    """
    now = _now(now)
    blocked_id = identity_service.resolve_user_id(session, blocked_public_id)
    if blocked_id == actor_user_id:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "user_id", "reason": "cannot_block_self"})
    existing = session.execute(
        select(UserBlock).where(UserBlock.blocker_user_id == actor_user_id, UserBlock.blocked_user_id == blocked_id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    block = UserBlock(public_id=new_public_uuid(), blocker_user_id=actor_user_id, blocked_user_id=blocked_id,
                      created_at=now)
    session.add(block)
    _flush_or_translate(session, {"uq_user_blocks_pair": lambda: DomainError(ErrorCode.INTEGRITY_CONFLICT)})
    return block


def unblock_user(session: Session, *, actor_user_id: int, blocked_public_id: str) -> None:
    """S10. Idempotent: removing a block that is not there is a success, not a 404."""
    blocked_id = identity_service.resolve_user_id(session, blocked_public_id)
    session.execute(
        delete(UserBlock).where(UserBlock.blocker_user_id == actor_user_id, UserBlock.blocked_user_id == blocked_id)
    )


def list_blocks(session: Session, *, actor_user_id: int) -> list[UserBlock]:
    return list(
        session.execute(
            select(UserBlock).where(UserBlock.blocker_user_id == actor_user_id).order_by(UserBlock.id.desc())
        ).scalars()
    )


def blocked_between(session: Session, user_a: int, user_b: int) -> bool:
    """§8.1: a block counts in both directions - neither side sees the other."""
    if user_a == user_b:
        return False
    return session.execute(
        select(UserBlock.id).where(
            or_(
                and_(UserBlock.blocker_user_id == user_a, UserBlock.blocked_user_id == user_b),
                and_(UserBlock.blocker_user_id == user_b, UserBlock.blocked_user_id == user_a),
            )
        ).limit(1)
    ).scalar_one_or_none() is not None


def blocked_user_ids(session: Session, user_id: int) -> set[int]:
    """Every user hidden from ``user_id`` (blocked by them or blocking them). Read-only, used by the feed."""
    rows = session.execute(
        select(UserBlock.blocker_user_id, UserBlock.blocked_user_id).where(
            or_(UserBlock.blocker_user_id == user_id, UserBlock.blocked_user_id == user_id)
        )
    ).all()
    return {blocker if blocked == user_id else blocked for blocker, blocked in rows}


def report_public_id(report: AbuseReport) -> str:
    return format_public_id(PublicIdPrefix.REPORT, report.public_id)


def fraud_signal_public_id(signal: FraudSignal) -> str:
    return format_public_id(PublicIdPrefix.FRAUD_SIGNAL, signal.public_id)


def block_public_id(block: UserBlock) -> str:
    return format_public_id(PublicIdPrefix.USER_BLOCK, block.public_id)


_REPORT_SUBJECT_RESOLVERS: dict[str, PublicIdPrefix] = {
    ReportSubjectType.USER.value: PublicIdPrefix.USER,
    ReportSubjectType.LISTING.value: PublicIdPrefix.LISTING,
    ReportSubjectType.BOOKING.value: PublicIdPrefix.BOOKING,
    ReportSubjectType.CHAT_MESSAGE.value: PublicIdPrefix.CHAT_MESSAGE,
}


def _report_subject_user(session: Session, subject_type: str, subject_id: str) -> int | None:
    """Who the report is about, when that is knowable. A wrong or invisible id is a 404 (ADR-0005)."""
    prefix = _REPORT_SUBJECT_RESOLVERS.get(subject_type)
    if prefix is None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "subject_type"})
    parse_public_id(subject_id, prefix)  # shape check; an unknown id stays a 404 below
    if subject_type == ReportSubjectType.USER.value:
        return identity_service.resolve_user_id(session, subject_id)
    if subject_type == ReportSubjectType.BOOKING.value:
        booking = bookings_service.get_booking_by_public_id(session, subject_id)
        return booking.driver_user_id
    if subject_type == ReportSubjectType.LISTING.value:
        from app.modules.marketplace import service as marketplace_service

        listing = marketplace_service.get_listing_by_public_id(session, subject_id)
        return listing.owner_user_id
    return None  # a chat message is reported by its id; the operator opens the thread


def create_report(
    session: Session, *, actor_user_id: int, data: Any, warnings: list[dict] | None = None,
    filter_hits: list[ContactFilterHit] | None = None, now: datetime | None = None,
) -> AbuseReport:
    """S11 (§17.3). Files what a user noticed; it changes nothing by itself - an operator reviews it.

    Rate limited per user (``rules.REPORT_RATE_LIMIT`` per ``REPORT_RATE_WINDOW``) so one account cannot flood the
    queue, and the free text passes the contact filter first (Q43), so a report is not a channel for a phone number.
    """
    now = _now(now)
    subject_type = ReportSubjectType(data.subject_type).value
    from app.modules.marketplace import service as marketplace_service

    details = marketplace_service.filter_free_text(
        session, actor_user_id=actor_user_id, field="details", text=data.details, warnings=warnings,
        filter_hits=filter_hits,
    )
    identity_service.lock_user_eligibility(session, [actor_user_id], mode="update")
    window_start = now - rules.REPORT_RATE_WINDOW
    recent = session.execute(
        select(func.count(AbuseReport.id)).where(
            AbuseReport.reporter_user_id == actor_user_id, AbuseReport.created_at >= window_start
        )
    ).scalar_one()
    if recent >= rules.REPORT_RATE_LIMIT:
        raise DomainError(
            ErrorCode.RATE_LIMITED,
            details={"limit": rules.REPORT_RATE_LIMIT, "window_s": int(rules.REPORT_RATE_WINDOW.total_seconds())},
        )
    subject_user_id = _report_subject_user(session, subject_type, data.subject_id)
    if subject_user_id == actor_user_id and subject_type == ReportSubjectType.USER.value:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "subject_id", "reason": "cannot_report_self"})
    report = AbuseReport(
        public_id=new_public_uuid(), reporter_user_id=actor_user_id, subject_type=subject_type,
        subject_ref=data.subject_id, subject_user_id=subject_user_id,
        reason_code=ReportReasonCode(data.reason_code).value, details=details,
        status=ReportStatus.OPEN.value, created_at=now, updated_at=now, version=1,
    )
    session.add(report)
    session.flush()
    return report


def list_reports(
    session: Session, *, actor_user_id: int, status: str | None = None, mine: bool = False,
    after_id: int | None = None, limit: int = 20, now: datetime | None = None,
) -> list[AbuseReport]:
    """S12: staff queue (``ops.view``) or, with ``mine``, the reporter's own reports."""
    if not mine:
        _require(session, actor_user_id, Capability.OPS_VIEW, _now(now))
    stmt = select(AbuseReport)
    if mine:
        stmt = stmt.where(AbuseReport.reporter_user_id == actor_user_id)
    if status:
        stmt = stmt.where(AbuseReport.status == ReportStatus(status).value)
    if after_id is not None:
        stmt = stmt.where(AbuseReport.id < after_id)
    return list(session.execute(stmt.order_by(AbuseReport.id.desc()).limit(max(1, min(limit, 100)))).scalars())


def report_command(
    session: Session, *, actor_user_id: int, report_public_id_value: str, status: str, expected_version: int,
    note: str | None = None, now: datetime | None = None,
) -> AbuseReport:
    """S12b. Operator triage (``ops.trust_review``). The decision is recorded; no account is changed here."""
    now = _now(now)
    _require(session, actor_user_id, Capability.OPS_TRUST_REVIEW, now)
    value = parse_public_id(report_public_id_value, PublicIdPrefix.REPORT)
    report = session.execute(
        select(AbuseReport).where(AbuseReport.public_id == value).with_for_update()
    ).scalar_one_or_none()
    if report is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if report.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"expected_version": report.version})
    target = ReportStatus(status)
    if report.status in (ReportStatus.DISMISSED.value, ReportStatus.ACTIONED.value):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "report", "status": report.status})
    report.status = target.value
    report.review_note = (note or None)
    report.version += 1
    report.updated_at = now
    if target in (ReportStatus.DISMISSED, ReportStatus.ACTIONED):
        report.reviewed_by = actor_user_id
        report.reviewed_at = now
    session.flush()
    _audit(session, actor_user_id=actor_user_id, entity_type="abuse_report", action="report_command",
           details={"report_id": report_public_id(report), "status": target.value})
    return report


def _fraud_signal(
    session: Session, *, signal_type: FraudSignalType, subject_user_id: int, window_key: str,
    evidence: dict[str, Any], now: datetime,
) -> bool:
    """Insert one signal; a repeat inside the same window is a no-op (unique (type, subject, window))."""
    inserted = session.execute(
        pg_insert(FraudSignal)
        .values(
            public_id=new_public_uuid(), signal_type=signal_type.value, subject_user_id=subject_user_id,
            window_key=window_key[:64], evidence=evidence, status=FraudSignalStatus.OPEN.value, detected_at=now,
            version=1,
        )
        .on_conflict_do_nothing(index_elements=["signal_type", "subject_user_id", "window_key"])
        .returning(FraudSignal.id)
    ).scalar_one_or_none()
    return inserted is not None


def scan_fraud_signals(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """§17.3 scheduled scan (A10a worker). Returns how many **new** signals were opened. No commit, no verdict.

    Three observations, all of them questions for a human:

    * ``shared_device_accounts`` - one push device has belonged to several accounts (``device_account_links``);
    * ``self_dealing_device`` - the client and the driver of one booking share a device (§17.3 fake trips);
    * ``repeated_pair_bookings`` - the same client/driver pair completed an unusual number of bookings inside
      ``REPEATED_PAIR_WINDOW``.

    Nothing is blocked, no rating changes and no money moves: the row lands in the operator queue (S12).
    """
    now = _now(now)
    opened = 0
    window_day = now.date().isoformat()

    from app.modules.communications import service as communications_service

    groups = communications_service.device_account_groups(
        session, min_accounts=rules.SHARED_DEVICE_MIN_ACCOUNTS, since=now - rules.REPEATED_PAIR_WINDOW, limit=limit
    )
    refs = identity_service.user_refs(session, [user_id for group in groups for user_id in group])
    for group in groups:
        key = f"{window_day}:{'-'.join(str(user_id) for user_id in group)}"
        for user_id in group:
            others = [refs[other][0] for other in group if other != user_id and other in refs]
            if _fraud_signal(
                session, signal_type=FraudSignalType.SHARED_DEVICE_ACCOUNTS, subject_user_id=user_id,
                window_key=key, evidence={"accounts_on_device": len(group), "other_accounts": sorted(others)},
                now=now,
            ):
                opened += 1

    device_pairs = {frozenset(group) for group in groups}
    recent_bookings = session.execute(
        select(Booking.id, Booking.public_id, Booking.client_user_id, Booking.driver_user_id)
        .where(Booking.created_at >= now - rules.REPEATED_PAIR_WINDOW)
        .order_by(Booking.id.desc())
        .limit(limit)
    ).all()
    for booking_id, booking_public_id, client_user_id, driver_user_id in recent_bookings:
        if not any({client_user_id, driver_user_id} <= group for group in device_pairs):
            continue
        booking_ref = format_public_id(PublicIdPrefix.BOOKING, booking_public_id)
        for user_id in (client_user_id, driver_user_id):
            if _fraud_signal(
                session, signal_type=FraudSignalType.SELF_DEALING_DEVICE, subject_user_id=user_id,
                window_key=f"booking:{booking_id}", evidence={"booking_id": booking_ref, "shared_device": 1}, now=now,
            ):
                opened += 1

    pair_rows = session.execute(
        select(Booking.client_user_id, Booking.driver_user_id, func.count(Booking.id))
        .where(
            Booking.created_at >= now - rules.REPEATED_PAIR_WINDOW,
            Booking.service_status == rules.COMPLETED_STATUS,
        )
        .group_by(Booking.client_user_id, Booking.driver_user_id)
        .having(func.count(Booking.id) >= rules.REPEATED_PAIR_MIN_BOOKINGS)
        .limit(limit)
    ).all()
    for client_user_id, driver_user_id, count in pair_rows:
        window = f"{window_day}:{client_user_id}-{driver_user_id}"
        for user_id in (client_user_id, driver_user_id):
            if _fraud_signal(
                session, signal_type=FraudSignalType.REPEATED_PAIR_BOOKINGS, subject_user_id=user_id,
                window_key=window,
                evidence={"completed_bookings": int(count), "window_days": rules.REPEATED_PAIR_WINDOW.days},
                now=now,
            ):
                opened += 1
    return opened


def list_fraud_signals(
    session: Session, *, actor_user_id: int, status: str | None = None, after_id: int | None = None,
    limit: int = 20, now: datetime | None = None,
) -> list[FraudSignal]:
    """S12 (``ops.view``). The queue an operator reads; the platform never acted on these rows by itself."""
    _require(session, actor_user_id, Capability.OPS_VIEW, _now(now))
    stmt = select(FraudSignal)
    if status:
        stmt = stmt.where(FraudSignal.status == FraudSignalStatus(status).value)
    if after_id is not None:
        stmt = stmt.where(FraudSignal.id < after_id)
    return list(session.execute(stmt.order_by(FraudSignal.id.desc()).limit(max(1, min(limit, 100)))).scalars())


def fraud_signal_command(
    session: Session, *, actor_user_id: int, signal_public_id: str, status: str, expected_version: int,
    note: str | None = None, now: datetime | None = None,
) -> FraudSignal:
    """S12b (``ops.trust_review``). ``confirmed`` records the operator's finding; any consequence is a separate,
    explicit command (block, eligibility, dispute) so no account is punished by a background job."""
    now = _now(now)
    _require(session, actor_user_id, Capability.OPS_TRUST_REVIEW, now)
    value = parse_public_id(signal_public_id, PublicIdPrefix.FRAUD_SIGNAL)
    signal = session.execute(
        select(FraudSignal).where(FraudSignal.public_id == value).with_for_update()
    ).scalar_one_or_none()
    if signal is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if signal.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"expected_version": signal.version})
    if signal.status in (FraudSignalStatus.DISMISSED.value, FraudSignalStatus.CONFIRMED.value):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "fraud_signal", "status": signal.status})
    target = FraudSignalStatus(status)
    signal.status = target.value
    signal.review_note = note or None
    signal.version += 1
    if target in (FraudSignalStatus.DISMISSED, FraudSignalStatus.CONFIRMED):
        signal.reviewed_by = actor_user_id
        signal.reviewed_at = now
    session.flush()
    _audit(session, actor_user_id=actor_user_id, entity_type="fraud_signal", action="fraud_signal_command",
           details={"signal_id": fraud_signal_public_id(signal), "status": target.value})
    return signal
