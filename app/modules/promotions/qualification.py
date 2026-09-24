"""Qualification, grant, review queue and the promotions worker jobs (referral stage 3, ADR-0023 §17).

**Evidence, not events.** A ``promo_qualification_events`` row (or the periodic sweep) only *starts* a check. The
decision always re-reads the source records: the booking (``service_status``/``completed_at``), the acknowledged cash
receipt, the commission capture - a ``wallet_holds`` row of *this* booking whose ``capture_transaction_id`` is a
``commission_capture`` ledger transaction sourced from that hold and carrying the same ``booking_id`` - open
``disputes_v2`` and, for parcels, the booking's own pickup and delivery proofs. A payload saying "completed" or
"paid" is never trusted.

**Three clocks.** Service time (the source timestamps), arrival (``received_at``) and processing (``processed_at``)
are kept apart. Q120: a service counts when it was completed and the client's own payment condition was confirmed on
or before the enrollment's qualification deadline - however late the event arrives or the worker runs. The
platform's capture may come later (finance review, worker delay): it never disqualifies the user, but no grant
happens before a real positive C_net capture exists, and meanwhile the enrollment waits and keeps its reserve. The
payment time comes from server-stamped records only (``payment_timing``); an unclear late payment goes to review. The
48 h risk window starts at the last of completion, cash confirmation and capture ("not before 48 h").

**Grant = a reserved promise becoming a bonus.** Grants only convert obligations promised at enrollment (no new
budget cost); lot, promo-ledger posting, state changes and the outbox event commit together. Every obligation grants
once (unique lot per obligation), every ``(enrollment, milestone)`` has one qualification record.

**Lock order** (ADR-0023 §13 extended): ``bookings`` (FOR SHARE, id ASC) -> ``promo_campaigns`` (FOR SHARE) ->
``promo_enrollments`` (FOR NO KEY UPDATE) -> ``referral_attributions`` -> ``promo_qualifications`` ->
``promo_obligations`` -> ``promo_lots`` (id ASC) -> ``promo_redemptions`` -> ``promo_reviews`` -> ``promo_budgets``
(ledger trigger). Jobs handle each item in a savepoint; a deadlock or transient error rolls back that item only, it
is counted in ``attempts`` and retried on the next run. Commands called from the API run inside
``platform.service.run_with_db_retry`` (the whole transaction is retried).

**Booking flow (stage 4):** accept/complete/cash/capture/cancel/reversal call ``record_booking_event`` inside their own
transaction (a rollback leaves no event); the sweep still finds everything the events miss. **Not here:** HTTP; MFA.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.contracts.enums import (
    Capability,
    EventType,
    PromoCampaignKind,
    PromoObligationStatus,
    PromoRewardStatus,
    ReferralAttributionStatus,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventEnvelope
from app.contracts.ids import PublicIdPrefix, format_public_id
from app.contracts.promo import (
    CASH_TIME_UNVERIFIED,
    QUALIFICATION_RISK_WINDOW,
    REQUIRED_QUALIFYING_SERVICES,
    RISK_RULESET_V1,
    MilestoneEvidence,
    PaymentTiming,
    QualificationFacts,
    QualificationVerdict,
    ServiceEvidence,
    assess_risk,
    awaiting_capture,
    client_referral_progress,
    evaluate_qualification,
    milestone_progress,
    normalize_phone,
    milestones_reached,
    payment_timing,
    review_due_at,
    service_in_time,
)
from app.contracts.state_machines import PROMO_ENROLLMENT, REFERRAL_ATTRIBUTION
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.promotions import service as promo_service
from app.modules.promotions.models import (
    PromoCampaign,
    PromoCampaignVersion,
    PromoEnrollment,
    PromoLedgerTransaction,
    PromoLot,
    PromoObligation,
    PromoQualification,
    PromoQualificationEvent,
    PromoReview,
    ReferralAttribution,
)

CAPTURE_PENDING = {"commission_not_captured", "no_net_commission"}

__all__ = [
    "BookingEvidence",
    "decide_review",
    "escalate_overdue_reviews",
    "expire_enrollments",
    "open_review",
    "process_enrollment",
    "process_qualification_events",
    "read_evidence",
    "recheck_granted",
    "record_booking_event",
    "reinstate_expired_release",
    "resume_processing",
    "start_review",
    "suspend_processing",
]

EVENT_KINDS = frozenset({"booking_completed", "cash_acknowledged", "commission_captured", "commission_reversed",
                         "dispute_changed", "booking_cancelled", "sweep"})


def _now(now: datetime | None) -> datetime:
    return utc_now() if now is None else ensure_aware_utc(now, field="now")


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else ensure_aware_utc(value, field="timestamp")


# --- evidence from the source records ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BookingEvidence:
    booking_id: int
    trip_id: int
    service_type: str
    client_user_id: int
    driver_user_id: int
    created_at: datetime
    completed_at: datetime | None
    cash_confirmed_at: datetime | None
    captured_at: datetime | None
    net_captured_minor: int
    open_dispute: bool
    cancelled_or_refunded: bool
    handover_at: datetime | None
    delivery_at: datetime | None
    pickup_stop_id: int | None
    dropoff_stop_id: int | None
    receiver_key: str | None = None
    cash_status_confirmed: bool = False  # bookings.cash_status = acknowledged
    cash_first_recorded_at: datetime | None = None  # server time the confirmed report was stored (never user input)
    hold_open: bool = False  # the commission hold is still active (commission ``held``): a capture can still happen (Q120)

    @property
    def cash_stamp(self) -> datetime | None:
        """Cash time used for the risk window; a confirmed state without a confirming record falls back to the
        server record, then to completion - such a booking goes to review anyway (``PaymentTiming.UNVERIFIED``)."""
        if not self.cash_status_confirmed:
            return None
        return self.cash_confirmed_at or self.cash_first_recorded_at or self.completed_at

    @property
    def conditions_met_at(self) -> datetime | None:
        """When the *last* of completion, cash confirmation and capture happened (Q110)."""
        stamps = (self.completed_at, self.cash_stamp, self.captured_at)
        return None if any(s is None for s in stamps) else max(stamps)

    def timing(self, deadline: datetime) -> PaymentTiming:
        return payment_timing(deadline=deadline, cash_confirmed=self.cash_status_confirmed,
                              confirmed_at=self.cash_confirmed_at, first_recorded_at=self.cash_first_recorded_at)

    def facts(self, signals: Sequence = ()) -> QualificationFacts:
        return QualificationFacts(
            booking_id=self.booking_id, trip_id=self.trip_id, service_type=ServiceType(self.service_type),
            client_user_id=self.client_user_id, driver_user_id=self.driver_user_id,
            service_completed_at=self.completed_at, cash_confirmed_at=self.cash_stamp,
            commission_captured_at=self.captured_at, net_commission_captured_minor=max(self.net_captured_minor, 0),
            open_dispute=self.open_dispute, cancelled_or_refunded=self.cancelled_or_refunded,
            risk_signals=tuple(signals),
        )


_EVIDENCE_SQL = text(
    """
    SELECT b.id, b.trip_id, b.service_type, b.client_user_id, b.driver_user_id, b.created_at, b.service_status,
           b.completed_at, b.cancelled_at, b.cash_status, b.pickup_stop_id, b.dropoff_stop_id,
           (SELECT max(r.decided_at) FROM cash_receipts r WHERE r.booking_id = b.id
              AND r.status IN ('acknowledged', 'resolved_paid')) AS cash_at,
           (SELECT min(r.created_at) FROM cash_receipts r WHERE r.booking_id = b.id
              AND r.status IN ('acknowledged', 'resolved_paid')) AS cash_recorded_at,
           EXISTS (SELECT 1 FROM wallet_holds h WHERE h.booking_id = b.id AND h.charge_kind = 'commission'
                     AND h.status = 'active') AS hold_open,
           cap.net_minor, cap.captured_at, COALESCE(cap.reversed_minor, 0) AS reversed_minor,
           EXISTS (SELECT 1 FROM disputes_v2 d WHERE d.booking_id = b.id AND d.status IN ('open', 'under_review')) AS disputed,
           (SELECT max(p.accepted_at) FROM booking_proofs p WHERE p.booking_id = b.id
              AND p.proof_kind IN ('pickup_code', 'operator_evidence')) AS handover_at,
           (SELECT max(p.accepted_at) FROM booking_proofs p WHERE p.booking_id = b.id AND p.proof_kind = 'delivery_code') AS delivery_at,
           COALESCE((SELECT v.receiver_phone FROM proposal_versions v WHERE v.id = b.accepted_proposal_version_id),
                    (SELECT d.receiver_phone FROM parcel_listing_details d WHERE d.listing_id = b.request_listing_id)) AS receiver_phone
      FROM bookings b
      LEFT JOIN LATERAL (
            SELECT h.captured_minor - h.reversed_minor AS net_minor, h.reversed_minor, t.created_at AS captured_at
              FROM wallet_holds h
              JOIN ledger_transactions t ON t.id = h.capture_transaction_id
                   AND t.reference_kind = 'commission_capture' AND t.source_type = 'wallet_hold'
                   AND t.source_id = h.id AND t.booking_id = h.booking_id
             WHERE h.booking_id = b.id AND h.charge_kind = 'commission' AND h.status = 'captured'
      ) cap ON true
     WHERE b.id = :booking_id
    """
)


def read_evidence(session: Session, booking_id: int) -> BookingEvidence | None:
    """Everything the decision needs, read from the owning tables (never from an event payload)."""
    row = session.execute(_EVIDENCE_SQL, {"booking_id": booking_id}).mappings().one_or_none()
    if row is None:
        return None
    completed = _aware(row["completed_at"]) if row["service_status"] == "completed" else None
    confirmed = row["cash_status"] == "acknowledged"
    cash_at = _aware(row["cash_at"]) if confirmed else None
    return BookingEvidence(
        booking_id=row["id"], trip_id=row["trip_id"], service_type=row["service_type"],
        client_user_id=row["client_user_id"], driver_user_id=row["driver_user_id"], created_at=_aware(row["created_at"]),
        completed_at=completed, cash_confirmed_at=cash_at, captured_at=_aware(row["captured_at"]),
        net_captured_minor=int(row["net_minor"] or 0), open_dispute=bool(row["disputed"]),
        cancelled_or_refunded=row["cancelled_at"] is not None or int(row["reversed_minor"] or 0) > 0,
        handover_at=_aware(row["handover_at"]), delivery_at=_aware(row["delivery_at"]),
        pickup_stop_id=row["pickup_stop_id"], dropoff_stop_id=row["dropoff_stop_id"],
        receiver_key=_receiver_key(row["receiver_phone"]),
        cash_status_confirmed=confirmed,
        cash_first_recorded_at=_aware(row["cash_recorded_at"]) if confirmed else None,
        hold_open=bool(row["hold_open"]),
    )


def _receiver_key(phone: str | None) -> str | None:
    """In-memory comparison key for "same receiver" (split-shipment check). Never stored, never logged."""
    import hashlib

    normalized = None if phone is None else normalize_phone(phone)
    return None if normalized is None else hashlib.sha256(normalized.encode("ascii")).hexdigest()


# --- intake -------------------------------------------------------------------------------------------------------


def record_booking_event(session: Session, *, booking_id: int, kind: str, occurred_at: datetime | None,
                         now: datetime | None = None) -> bool:
    """Record that something happened to a booking. Idempotent on (kind, booking, occurred_at). Starts a check only.

    Stage 4 calls this from the booking flow; until then the sweep in ``process_qualification_events`` finds the
    same bookings from the source tables, so a missing event never loses a qualification.
    """
    if kind not in EVENT_KINDS:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "kind"})
    occurred = _aware(occurred_at)
    key = f"{kind}:{booking_id}:{'' if occurred is None else occurred.isoformat()}"
    inserted = session.execute(
        pg_insert(PromoQualificationEvent)
        .values(booking_id=booking_id, kind=kind, occurred_at=occurred, received_at=_now(now), dedup_key=key)
        .on_conflict_do_nothing(index_elements=["dedup_key"]).returning(PromoQualificationEvent.id)
    ).scalar()
    return inserted is not None


# --- reviews ------------------------------------------------------------------------------------------------------


def _review_sla(session: Session, campaign_id: int | None, version_id: int | None = None) -> timedelta | None:
    if version_id is None and campaign_id is not None:
        version_id = session.execute(select(PromoCampaign.active_version_id).where(PromoCampaign.id == campaign_id)).scalar()
    seconds = None if version_id is None else session.execute(
        select(PromoCampaignVersion.review_sla_s).where(PromoCampaignVersion.id == version_id)).scalar()
    return None if not seconds else timedelta(seconds=seconds)


def _review_values(*, kind: str, dedup_key: str, reasons: Sequence[str], evidence: Sequence[dict],
                   now: datetime, sla: timedelta | None, **refs: Any) -> dict:
    return dict(
        public_id=uuid.uuid4(), kind=kind, dedup_key=dedup_key[:200], reason_codes=sorted(set(reasons)),
        evidence=list(evidence), risk_ruleset_version=RISK_RULESET_V1.version, status="open", opened_at=now,
        due_at=None if sla is None else review_due_at(now, sla), **refs,
    )


def open_review(session: Session, *, kind: str, dedup_key: str, reasons: Sequence[str], evidence: Sequence[dict],
                now: datetime | None = None, sla: timedelta | None = None, **refs: Any) -> PromoReview:
    """Open a review in the caller's transaction; a retry with the same key returns the existing one.

    ``evidence`` holds references only (``{"table": ..., "id": ...}``) - no phone, name, key or document content.
    """
    now = _now(now)
    values = _review_values(kind=kind, dedup_key=dedup_key, reasons=reasons, evidence=evidence, now=now, sla=sla, **refs)
    inserted = session.execute(
        pg_insert(PromoReview).values(**values).on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(PromoReview.id)
    ).scalar()
    review = session.execute(select(PromoReview).where(PromoReview.dedup_key == values["dedup_key"])).scalar_one()
    if inserted is not None:
        _emit_review_opened(session, review, now)
    return review


def open_review_autonomously(session: Session, **kwargs: Any) -> int:
    """Persist a review in its own short transaction so a rolled-back caller cannot lose it (ADR-0023 §17 T3).

    Used where the caller's command is refused (and its transaction rolled back) *because* a person must look,
    e.g. an enrollment stopped by a protected-identity match. Touches only ``promo_reviews`` and the outbox.
    """
    with Session(bind=session.get_bind()) as own:
        # Q122: its own connection, so it can never commit the caller's reservations. Its FK checks take KEY SHARE
        # (compatible with the caller's FOR NO KEY UPDATE locks); a dedup-key or row conflict with the caller's own
        # uncommitted work would be an app-level wait the database cannot detect - lock_timeout turns it into an error.
        own.execute(text("SET LOCAL lock_timeout = '5s'"))
        review = open_review(own, **kwargs)
        own.commit()
        return review.id


def _emit_review_opened(session: Session, review: PromoReview, now: datetime) -> None:
    from app.modules.platform.service import enqueue_event

    enqueue_event(session, EventEnvelope(
        event_type=EventType.PROMO_REVIEW_OPENED, aggregate_type="promo_review",
        aggregate_public_id=format_public_id(PublicIdPrefix.PROMO_REVIEW, review.public_id), aggregate_version=1,
        occurred_at=now, payload={"review_kind": review.kind, "reason_codes": list(review.reason_codes),
                                  "due_at": None if review.due_at is None else review.due_at.isoformat()},
    ), aggregate_id=review.id, dedup_key=f"promo.review_opened:{review.id}")


def _lock_review(session: Session, review_id: int) -> PromoReview:
    review = session.execute(select(PromoReview).where(PromoReview.id == review_id).with_for_update(key_share=True)
                             .execution_options(populate_existing=True)).scalar_one_or_none()
    if review is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return review


def start_review(session: Session, *, review_id: int, actor_user_id: int,
                 actor_capabilities: Collection[Capability | str], note: str | None = None,
                 now: datetime | None = None) -> PromoReview:
    """Operator (``promo.fraud_review``) takes a review; a note goes to the audit trail. No decision."""
    promo_service._require_capability(actor_capabilities, Capability.PROMO_FRAUD_REVIEW)
    now = _now(now)
    review = _lock_review(session, review_id)
    if review.status not in ("open", "under_review"):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "promo_review", "from": review.status})
    review.status, review.assigned_to, review.updated_at = "under_review", actor_user_id, now
    review.version += 1
    session.flush()
    promo_service._audit(session, actor_user_id, "promo_reviews", review.id, "review_started", {}, note)
    return review


def decide_review(session: Session, *, review_id: int, decision: str, actor_user_id: int,
                  actor_capabilities: Collection[Capability | str], note: str, expected_version: int,
                  now: datetime | None = None) -> PromoReview:
    """Admin+ (``promo.fraud_decide``) approves or rejects. Approval never creates a reward by itself: it only clears
    the reviewed reasons; the next processing run re-checks eligibility and the money invariants before granting.
    Rejection releases what is still only promised, or reverses what is unspent after a grant."""
    promo_service._require_capability(actor_capabilities, Capability.PROMO_FRAUD_DECIDE)
    if decision not in ("approve", "reject"):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "decision"})
    note = promo_service._require_text(note, "note")
    now = _now(now)
    unlocked = session.get(PromoReview, review_id)
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    enrollment = None
    if unlocked.enrollment_id is not None:
        enrollment = _lock_enrollment(session, unlocked.enrollment_id)
    review = _lock_review(session, review_id)
    if review.status not in ("open", "under_review"):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "promo_review", "from": review.status})
    if review.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": review.version})
    review.status = "approved" if decision == "approve" else "rejected"
    review.decided_by, review.decided_at, review.decision_note, review.updated_at = actor_user_id, now, note, now
    review.version += 1
    session.flush()
    if review.qualification_id is not None:
        qualification = session.execute(select(PromoQualification).where(PromoQualification.id == review.qualification_id)
                                        .with_for_update(key_share=True)).scalar_one()
        if decision == "approve" and review.kind in ("qualification_risk", "party_not_active"):
            qualification.cleared_review_id = review.id
            qualification.version += 1
        elif decision == "reject" and review.kind in ("qualification_risk", "party_not_active") and qualification.status != "granted":
            qualification.status = "rejected"
            qualification.version += 1
            session.flush()
            _release_milestone(session, enrollment, qualification.milestone, reason=f"review {review.id} rejected",
                               actor_user_id=actor_user_id, now=now)
            _settle_enrollment(session, enrollment, now=now, rejected=True)
        elif decision == "reject" and review.kind == "post_grant_recheck":
            for lot in _lots_of(session, enrollment.id, qualification.milestone):
                promo_service.reverse_lot(session, lot_id=lot.id, actor_user_id=actor_user_id,
                                          actor_capabilities=actor_capabilities, reason=note, now=now)
        elif decision == "approve" and review.kind == "post_grant_recheck":
            # Q122: spending resumes only when no other post-grant review of this reward is still open
            others = session.execute(select(PromoReview.id).where(
                PromoReview.qualification_id == qualification.id, PromoReview.kind == "post_grant_recheck",
                PromoReview.id != review.id, PromoReview.status.in_(("open", "under_review")))).first()
            if others is None:
                for lot in _lots_of(session, enrollment.id, qualification.milestone):
                    if lot.status == PromoRewardStatus.PENDING_REVIEW.value:
                        promo_service.make_lot_available(session, lot_id=lot.id, actor_user_id=actor_user_id,
                                                         actor_capabilities=actor_capabilities, reason=note, now=now)
        session.flush()
    if review.kind == "cancel_fault" and decision == "reject":
        # Q129: the admin decided the cancel was the holder's own fault - only the unspent grace extension goes
        for item in review.evidence or ():
            if item.get("table") == "promo_redemptions":
                promo_service.withdraw_restoration(session, redemption_id=int(item["id"]), actor_user_id=actor_user_id,
                                                   actor_capabilities=actor_capabilities, reason=note, now=now)
    # "restoration_uncovered" (Q127): the decision records a person's judgement; it moves no value by itself
    promo_service._audit(session, actor_user_id, "promo_reviews", review.id, f"review_{review.status}",
                         {"kind": review.kind, "reasons": list(review.reason_codes)}, note)
    return review


def escalate_overdue_reviews(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """Past the SLA: mark escalated and tell staff. Never approves, rejects, grants or forfeits anything."""
    from app.modules.platform.service import enqueue_event

    now = _now(now)
    rows = session.execute(
        select(PromoReview).where(PromoReview.status.in_(("open", "under_review")), PromoReview.due_at <= now,
                                  PromoReview.escalated_at.is_(None))
        .order_by(PromoReview.id).limit(limit).with_for_update(skip_locked=True, key_share=True)
    ).scalars().all()
    for review in rows:
        review.escalated_at, review.updated_at = now, now
        review.version += 1
        enqueue_event(session, EventEnvelope(
            event_type=EventType.PROMO_REVIEW_ESCALATED, aggregate_type="promo_review",
            aggregate_public_id=format_public_id(PublicIdPrefix.PROMO_REVIEW, review.public_id),
            aggregate_version=review.version, occurred_at=now,
            payload={"review_kind": review.kind, "due_at": review.due_at.isoformat()},
        ), aggregate_id=review.id, dedup_key=f"promo.review_escalated:{review.id}")
        promo_service._audit(session, None, "promo_reviews", review.id, "review_escalated", {})
    session.flush()
    return len(rows)


# --- processing ---------------------------------------------------------------------------------------------------


@dataclass
class _Outcome:
    milestone: int
    status: str  # waiting | review | qualified
    bookings: list[int] = field(default_factory=list)
    conditions_met_at: datetime | None = None
    ready_at: datetime | None = None
    reasons: list[str] = field(default_factory=list)


def _lock_enrollment(session: Session, enrollment_id: int) -> PromoEnrollment:
    enrollment = session.execute(select(PromoEnrollment).where(PromoEnrollment.id == enrollment_id)
                                 .with_for_update(key_share=True).execution_options(populate_existing=True)).scalar_one_or_none()
    if enrollment is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return enrollment


def _candidate_booking_ids(session: Session, enrollment: PromoEnrollment) -> list[int]:
    party = "driver_user_id" if enrollment.family == "driver_acquisition" else "client_user_id"
    service_filter = "" if enrollment.family == "driver_acquisition" else "AND service_type = :service"
    return list(session.execute(text(
        f"SELECT id FROM bookings WHERE {party} = :u {service_filter} AND created_at >= :since ORDER BY id"),
        {"u": enrollment.referee_user_id, "service": enrollment.service_type,
         "since": enrollment.enrolled_at - timedelta(minutes=1)}).scalars())


@dataclass(frozen=True)
class _Judged:
    evidence: BookingEvidence
    result: Any  # QualificationResult
    awaiting_capture: bool  # in time; only the platform's capture is missing and still possible (Q120)
    unverified_cash: bool  # confirmed, but the payment's real time is unclear -> review (Q120)

    @property
    def ready(self) -> bool:
        return not self.awaiting_capture and self.result.verdict is QualificationVerdict.QUALIFIED


def _judge(evidence: BookingEvidence, enrollment: PromoEnrollment, now: datetime) -> _Judged | None:
    """One candidate booking against the enrollment's deadline (Q120). ``None`` = does not count."""
    deadline = ensure_aware_utc(enrollment.qualification_deadline, field="deadline")
    if not service_in_time(evidence.completed_at, deadline):
        return None
    timing = evidence.timing(deadline)
    if timing in (PaymentTiming.MISSING, PaymentTiming.LATE):
        return None
    result = evaluate_qualification(evidence.facts(), now=now, referrer_user_id=enrollment.referrer_user_id)
    waiting_for_capture = awaiting_capture(result, hold_open=evidence.hold_open)
    if result.verdict is QualificationVerdict.NOT_ELIGIBLE and not waiting_for_capture:
        return None
    return _Judged(evidence, result, waiting_for_capture, timing is PaymentTiming.UNVERIFIED)


def _evaluate(session: Session, enrollment: PromoEnrollment, version: PromoCampaignVersion, kind: PromoCampaignKind,
              evidences: list[BookingEvidence], now: datetime) -> list[_Outcome]:
    judged = [j for j in (_judge(e, enrollment, now) for e in evidences) if j is not None]
    if kind is PromoCampaignKind.REFERRAL_DRIVER_DRIVER:
        linked = {enrollment.referrer_user_id, enrollment.referee_user_id}
        progress = milestone_progress(
            MilestoneEvidence(trip_id=j.evidence.trip_id, booking_id=j.evidence.booking_id,
                              client_user_id=j.evidence.client_user_id, qualified=j.ready,
                              client_linked_to_referral=j.evidence.client_user_id in linked)
            for j in judged)
        reached = milestones_reached(progress, tuple(version.milestone_thresholds or ()),
                                     min_distinct_clients=version.min_distinct_clients or 0)
        counted = [j for j in judged if j.ready and j.evidence.client_user_id not in linked]
        reasons = sorted({CASH_TIME_UNVERIFIED} if any(j.unverified_cash for j in counted) else set())
        return [_Outcome(milestone=m, status="review" if reasons else "qualified",
                         bookings=sorted({j.evidence.booking_id for j in counted}),
                         conditions_met_at=max((j.evidence.conditions_met_at for j in counted), default=None),
                         ready_at=max((j.result.ready_at for j in counted if j.result.ready_at), default=None),
                         reasons=reasons) for m in reached]

    service_type = ServiceType(enrollment.service_type)
    required = REQUIRED_QUALIFYING_SERVICES[service_type]
    if service_type is ServiceType.PARCEL:
        # Q113: an independent shipment is its own booking with its own handover and delivery proof (its capture
        # may still be pending - Q120 - but a booking without both proofs never counts)
        judged = [j for j in judged if j.evidence.handover_at and j.evidence.delivery_at]
    if len(judged) < required:
        return []
    progress = client_referral_progress(service_type, [
        ServiceEvidence(booking_id=j.evidence.booking_id, trip_id=j.evidence.trip_id,
                        client_user_id=j.evidence.client_user_id, qualified=True, booked_at=j.evidence.created_at,
                        pickup_stop_id=j.evidence.pickup_stop_id, dropoff_stop_id=j.evidence.dropoff_stop_id,
                        receiver_key=j.evidence.receiver_key)
        for j in judged])
    far_future = datetime.max.replace(tzinfo=now.tzinfo)
    # captured bookings first (by when their conditions were met), then those still waiting for the capture
    chosen = sorted(judged, key=lambda j: (j.evidence.conditions_met_at or far_future, j.evidence.booking_id))[:required]
    reasons = {reason for j in chosen if j.result.verdict is QualificationVerdict.REVIEW for reason in j.result.reasons}
    if any(j.unverified_cash for j in chosen):
        reasons.add(CASH_TIME_UNVERIFIED)
    if progress.risk_signals:  # a shipment that looks split for the reward: a person looks, it is not excluded
        reasons.update(assess_risk(progress.risk_signals).reasons)
    pending_capture = any(j.awaiting_capture for j in chosen)
    status = "review" if reasons else (
        "waiting" if pending_capture or any(j.result.verdict is QualificationVerdict.WAIT for j in chosen) else "qualified")
    stamps = [j.evidence.conditions_met_at for j in chosen]
    readies = [j.result.ready_at for j in chosen]
    return [_Outcome(milestone=0, status=status, bookings=[j.evidence.booking_id for j in chosen],
                     conditions_met_at=None if pending_capture or None in stamps else max(stamps),
                     ready_at=None if pending_capture or None in readies else max(readies), reasons=sorted(reasons))]


@dataclass(frozen=True)
class ProgressView:
    """Stage 5, read-only: where the referee stands. ``done`` counts only services that fully count now; one still
    waiting for the capture, the risk window or a person is ``in_review`` - never shown as done. Numbers are the
    campaign version's own values (never a marketing text in the app)."""

    unit: str  # "service" | "distinct_trip"
    required: int
    done: int
    in_review: int
    milestones: tuple[tuple[int, bool], ...]  # driver campaigns: (threshold, reached by done)

    @property
    def remaining(self) -> int:
        return max(0, self.required - self.done - self.in_review)


def progress_for(session: Session, enrollment: PromoEnrollment, now: datetime | None = None) -> ProgressView | None:
    """The referee's progress on one enrollment, from the same evidence and rules the grant uses (no writes)."""
    now = _now(now)
    campaign = session.get(PromoCampaign, enrollment.campaign_id)
    version = session.get(PromoCampaignVersion, enrollment.campaign_version_id)
    if campaign is None or version is None:
        return None
    judged = [j for j in (
        _judge(e, enrollment, now) for e in (read_evidence(session, booking_id)
                                             for booking_id in _candidate_booking_ids(session, enrollment))
        if e is not None) if j is not None]
    if PromoCampaignKind(campaign.kind) is PromoCampaignKind.REFERRAL_DRIVER_DRIVER:
        linked = {enrollment.referrer_user_id, enrollment.referee_user_id}
        unlinked = [j for j in judged if j.evidence.client_user_id not in linked]
        done_trips = {j.evidence.trip_id for j in unlinked if j.ready}
        pending_trips = {j.evidence.trip_id for j in unlinked if not j.ready} - done_trips
        thresholds = tuple(version.milestone_thresholds or ())
        return ProgressView(unit="distinct_trip", required=max(thresholds, default=0), done=len(done_trips),
                            in_review=len(pending_trips),
                            milestones=tuple((t, len(done_trips) >= t) for t in thresholds))
    service_type = ServiceType(enrollment.service_type)
    if service_type is ServiceType.PARCEL:
        judged = [j for j in judged if j.evidence.handover_at and j.evidence.delivery_at]
    ready = [j for j in judged if j.ready and j.result.verdict is QualificationVerdict.QUALIFIED]
    return ProgressView(unit="service", required=REQUIRED_QUALIFYING_SERVICES[service_type], done=len(ready),
                        in_review=len(judged) - len(ready), milestones=())


def _qualification_row(session: Session, enrollment_id: int, milestone: int, now: datetime) -> PromoQualification:
    row = session.execute(select(PromoQualification).where(PromoQualification.enrollment_id == enrollment_id,
                                                           PromoQualification.milestone == milestone)
                          .with_for_update(key_share=True).execution_options(populate_existing=True)).scalar_one_or_none()
    if row is not None:
        return row
    session.execute(pg_insert(PromoQualification).values(
        public_id=uuid.uuid4(), enrollment_id=enrollment_id, milestone=milestone, status="waiting",
        created_at=now, updated_at=now).on_conflict_do_nothing(index_elements=["enrollment_id", "milestone"]))
    return session.execute(select(PromoQualification).where(PromoQualification.enrollment_id == enrollment_id,
                                                            PromoQualification.milestone == milestone)
                           .with_for_update(key_share=True).execution_options(populate_existing=True)).scalar_one()


def _lots_of(session: Session, enrollment_id: int, milestone: int) -> list[PromoLot]:
    return list(session.execute(
        select(PromoLot).join(PromoObligation, PromoObligation.id == PromoLot.obligation_id)
        .where(PromoObligation.enrollment_id == enrollment_id, PromoObligation.milestone == milestone)
        .order_by(PromoLot.id)).scalars())


def _obligations(session: Session, enrollment_id: int, milestone: int | None = None,
                 status: str | None = PromoObligationStatus.PROMISED.value) -> list[PromoObligation]:
    query = select(PromoObligation).where(PromoObligation.enrollment_id == enrollment_id)
    if milestone is not None:
        query = query.where(PromoObligation.milestone == milestone)
    if status is not None:
        query = query.where(PromoObligation.status == status)
    return list(session.execute(query.order_by(PromoObligation.id)).scalars())


def _users_active(session: Session, *user_ids: int) -> bool:
    statuses = session.execute(text("SELECT status FROM users WHERE id = ANY(:ids)"), {"ids": list(user_ids)}).scalars().all()
    return len(statuses) == len(set(user_ids)) and all(status == "active" for status in statuses)


def _advance_attribution(session: Session, attribution_id: int, target: str, command: str, now: datetime) -> None:
    attribution = session.execute(select(ReferralAttribution).where(ReferralAttribution.id == attribution_id)
                                  .with_for_update(key_share=True)).scalar_one()
    if attribution.status == target or not REFERRAL_ATTRIBUTION.is_allowed_by(attribution.status, target, command):
        return
    attribution.status, attribution.updated_at = target, now
    attribution.version += 1


def _grant_milestone(session: Session, enrollment: PromoEnrollment, qualification: PromoQualification,
                     now: datetime) -> list[PromoLot]:
    from app.modules.platform.service import enqueue_event

    lots = []
    for obligation in _obligations(session, enrollment.id, qualification.milestone):
        lot = promo_service.grant_obligation(session, obligation_id=obligation.id, now=now)
        lots.append(lot)
        enqueue_event(session, EventEnvelope(
            event_type=EventType.PROMO_REWARD_GRANTED, aggregate_type="promo_lot",
            aggregate_public_id=format_public_id(PublicIdPrefix.PROMO_LOT, lot.public_id), aggregate_version=lot.version,
            occurred_at=now, payload={
                "enrollment_id": format_public_id(PublicIdPrefix.PROMO_ENROLLMENT, enrollment.public_id),
                "instrument": lot.instrument, "reward_amount_minor": lot.amount_minor, "currency": lot.currency,
                "milestone": obligation.milestone, "side": obligation.side},
        ), aggregate_id=lot.id, dedup_key=f"promo.reward_granted:{lot.id}")
    qualification.status, qualification.granted_at, qualification.updated_at = "granted", now, now
    qualification.version += 1
    session.flush()
    promo_service._audit(session, None, "promo_qualifications", qualification.id, "reward_granted",
                         {"lots": [lot.id for lot in lots], "milestone": qualification.milestone})
    return lots


def _release_milestone(session: Session, enrollment: PromoEnrollment, milestone: int | None, *, reason: str,
                       actor_user_id: int | None, now: datetime) -> None:
    for obligation in _obligations(session, enrollment.id, milestone):
        promo_service.release_obligation(session, obligation_id=obligation.id, reason=reason,
                                         actor_user_id=actor_user_id, now=now)


def _settle_enrollment(session: Session, enrollment: PromoEnrollment, *, now: datetime, rejected: bool = False) -> None:
    """Close the enrollment once nothing is promised any more; attribution follows."""
    if enrollment.status != "promised" or _obligations(session, enrollment.id):
        return
    granted = bool(_obligations(session, enrollment.id, status=PromoObligationStatus.GRANTED.value))
    target = "granted" if granted else "released"
    PROMO_ENROLLMENT.assert_transition("promised", target, "grant" if granted else "release")
    enrollment.status, enrollment.decided_at, enrollment.updated_at = target, now, now
    enrollment.version += 1
    session.flush()
    if granted:
        _advance_attribution(session, enrollment.attribution_id, ReferralAttributionStatus.QUALIFIED.value, "qualify", now)
    elif rejected:
        _advance_attribution(session, enrollment.attribution_id, ReferralAttributionStatus.REJECTED.value, "reject", now)
    else:
        _advance_attribution(session, enrollment.attribution_id, ReferralAttributionStatus.EXPIRED.value, "expire", now)


def process_enrollment(session: Session, *, enrollment_id: int, now: datetime | None = None) -> str:
    """Re-read the evidence of one enrollment and move it forward. Idempotent; safe under parallel workers."""
    now = _now(now)
    unlocked = session.get(PromoEnrollment, enrollment_id)
    if unlocked is None or unlocked.status != "promised":
        return "settled"
    campaign = session.get(PromoCampaign, unlocked.campaign_id)
    if campaign.processing_suspended_at is not None:
        return "suspended"  # an operational stop: nothing is released, deleted or granted
    booking_ids = _candidate_booking_ids(session, unlocked)
    if booking_ids:  # bookings first in the lock order; a concurrent dispute/refund serialises with us
        session.execute(text("SELECT id FROM bookings WHERE id = ANY(:ids) ORDER BY id FOR SHARE"), {"ids": booking_ids})
    promo_service._lock_campaign(session, campaign.id, share=True)
    enrollment = _lock_enrollment(session, enrollment_id)
    if enrollment.status != "promised":
        return "settled"
    version = session.get(PromoCampaignVersion, enrollment.campaign_version_id)
    evidences = [e for e in (read_evidence(session, b) for b in booking_ids) if e is not None]
    outcomes = _evaluate(session, enrollment, version, PromoCampaignKind(campaign.kind), evidences, now)
    result = "pending"
    for outcome in outcomes:
        qualification = _qualification_row(session, enrollment.id, outcome.milestone, now)
        if qualification.status in ("granted", "rejected"):
            continue
        _advance_attribution(session, enrollment.attribution_id, ReferralAttributionStatus.QUALIFYING.value,
                             "candidate_event", now)
        qualification.evidence_booking_ids = outcome.bookings
        qualification.conditions_met_at, qualification.ready_at = outcome.conditions_met_at, outcome.ready_at
        qualification.risk_ruleset_version, qualification.updated_at = RISK_RULESET_V1.version, now
        reasons = list(outcome.reasons)
        cleared = session.get(PromoReview, qualification.cleared_review_id) if qualification.cleared_review_id else None
        if cleared is not None and set(reasons) <= set(cleared.reason_codes):
            reasons = []
        if not reasons and outcome.status == "qualified" and not _users_active(
                session, enrollment.referee_user_id, enrollment.referrer_user_id):
            reasons = ["party_not_active"]
            if cleared is not None and "party_not_active" in cleared.reason_codes:
                reasons = ["party_not_active_still"]  # an approval never bypasses the live check
        qualification.reason_codes = reasons
        if reasons:
            qualification.status = "review"
            qualification.version += 1
            session.flush()
            kind = "party_not_active" if reasons[0].startswith("party_not_active") else "qualification_risk"
            open_review(session, kind=kind, dedup_key=f"{kind}:{qualification.id}:{','.join(reasons)}", reasons=reasons,
                        evidence=[{"table": "bookings", "id": b} for b in outcome.bookings], now=now,
                        sla=_review_sla(session, None, enrollment.campaign_version_id), campaign_id=enrollment.campaign_id,
                        attribution_id=enrollment.attribution_id, enrollment_id=enrollment.id,
                        qualification_id=qualification.id)
            result = "review"
            continue
        if outcome.status == "waiting" or outcome.ready_at is None or now < outcome.ready_at:
            # Q110/Q120: 48 h after the last condition, and never before a real positive capture; the right is
            # already formed and the reserve stays
            qualification.status = "waiting"
            qualification.version += 1
            session.flush()
            result = "waiting"
            continue
        qualification.status = "qualified"
        qualification.version += 1
        session.flush()
        _grant_milestone(session, enrollment, qualification, now)
        result = "granted"
    enrollment.last_checked_at = now
    session.flush()
    _settle_enrollment(session, enrollment, now=now)
    return result


def _pending_in_time(session: Session, enrollment: PromoEnrollment, now: datetime) -> bool:
    """Is there a right formed in time that a person or the risk window is still deciding?"""
    live = session.execute(select(PromoQualification.id).where(
        PromoQualification.enrollment_id == enrollment.id,
        PromoQualification.status.in_(("waiting", "review", "qualified")))).first()
    if live is not None:
        return True
    reviews = session.execute(select(PromoReview.id).where(PromoReview.enrollment_id == enrollment.id,
                                                           PromoReview.status.in_(("open", "under_review")))).first()
    if reviews is not None:
        return True
    deadline = ensure_aware_utc(enrollment.qualification_deadline, field="deadline")
    for booking_id in _candidate_booking_ids(session, enrollment):
        evidence = read_evidence(session, booking_id)
        if evidence is None or not service_in_time(evidence.completed_at, deadline):
            continue
        if evidence.timing(deadline) in (PaymentTiming.MISSING, PaymentTiming.LATE):
            continue  # the client's own payment condition was not met in time (Q120)
        result = evaluate_qualification(evidence.facts(), now=now, referrer_user_id=enrollment.referrer_user_id)
        waiting = {"open_dispute"} | (CAPTURE_PENDING if evidence.hold_open else set())
        if result.verdict is not QualificationVerdict.NOT_ELIGIBLE or set(result.reasons) <= waiting:
            # in time; only a dispute, the platform's capture or the risk window is open: not ours to take away
            return True
    return False


def expire_enrollments(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """Past the qualification deadline: release what can no longer be earned; keep what is being decided."""
    now = _now(now)
    ids = session.execute(select(PromoEnrollment.id).where(PromoEnrollment.status == "promised",
                                                           PromoEnrollment.qualification_deadline < now)
                          .order_by(PromoEnrollment.id).limit(limit)).scalars().all()
    handled = 0
    for enrollment_id in ids:
        savepoint = session.begin_nested()
        try:
            process_enrollment(session, enrollment_id=enrollment_id, now=now)
            enrollment = _lock_enrollment(session, enrollment_id)
            campaign = session.get(PromoCampaign, enrollment.campaign_id)
            if enrollment.status == "promised" and campaign.processing_suspended_at is None \
                    and not _pending_in_time(session, enrollment, now):
                _release_milestone(session, enrollment, None, reason="qualification deadline passed",
                                   actor_user_id=None, now=now)
                _settle_enrollment(session, enrollment, now=now)
                handled += 1
        except (DomainError, DBAPIError):
            savepoint.rollback()
            continue
        savepoint.commit()
    return handled


def process_qualification_events(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """Worker: claim pending intake events (SKIP LOCKED), then sweep promised enrollments oldest-checked first.

    A crash before commit leaves the events unprocessed and they are claimed again; after commit every effect is
    keyed (qualification per enrollment+milestone, lot per obligation, event dedup), so a re-run creates nothing.
    """
    now = _now(now)
    handled = 0
    events = session.execute(
        select(PromoQualificationEvent).where(PromoQualificationEvent.processed_at.is_(None))
        .order_by(PromoQualificationEvent.id).limit(limit).with_for_update(skip_locked=True)
    ).scalars().all()
    for event in events:
        parties = session.execute(text("SELECT client_user_id, driver_user_id FROM bookings WHERE id = :b"),
                                  {"b": event.booking_id}).one()
        enrollment_ids = session.execute(select(PromoEnrollment.id).where(
            PromoEnrollment.status == "promised", PromoEnrollment.referee_user_id.in_(list(parties)))).scalars().all()
        failed = None
        for enrollment_id in enrollment_ids:
            failed = _process_isolated(session, enrollment_id, now) or failed
        event.attempts += 1
        if failed is None:
            event.processed_at = now
        else:
            event.last_error = failed[:200]
        handled += 1
    session.flush()
    remaining = max(limit - handled, 0)
    if remaining:
        due = session.execute(select(PromoEnrollment.id).where(PromoEnrollment.status == "promised")
                              .order_by(PromoEnrollment.last_checked_at.asc().nullsfirst(), PromoEnrollment.id)
                              .limit(remaining)).scalars().all()
        for enrollment_id in due:
            _process_isolated(session, enrollment_id, now)
            handled += 1
    return handled


def _process_isolated(session: Session, enrollment_id: int, now: datetime) -> str | None:
    savepoint = session.begin_nested()
    try:
        process_enrollment(session, enrollment_id=enrollment_id, now=now)
    except (DomainError, DBAPIError) as exc:
        savepoint.rollback()
        return type(exc).__name__
    savepoint.commit()
    return None


def recheck_granted(session: Session, *, limit: int = 100, now: datetime | None = None) -> int:
    """After a grant: a refund, reversal, cancellation or new dispute on the evidence opens a review. Nothing is
    reversed automatically and nothing becomes a debt on anyone's real balance."""
    now = _now(now)
    rows = session.execute(text(
        """
        SELECT q.id AS qualification_id, q.enrollment_id, e.campaign_id, e.attribution_id, b.id AS booking_id
          FROM promo_qualifications q
          JOIN promo_enrollments e ON e.id = q.enrollment_id
          JOIN LATERAL jsonb_array_elements_text(q.evidence_booking_ids) ev(id) ON true
          JOIN bookings b ON b.id = ev.id::bigint
         WHERE q.status = 'granted'
           AND (b.cancelled_at IS NOT NULL
                OR EXISTS (SELECT 1 FROM disputes_v2 d WHERE d.booking_id = b.id AND d.status IN ('open', 'under_review'))
                OR EXISTS (SELECT 1 FROM wallet_holds h WHERE h.booking_id = b.id AND h.reversed_minor > 0))
           AND NOT EXISTS (SELECT 1 FROM promo_reviews r WHERE r.dedup_key = 'post_grant_recheck:' || q.id || ':' || b.id)
         ORDER BY q.id LIMIT :limit
        """), {"limit": limit}).mappings().all()
    for row in rows:
        # Q122: the not-yet-reserved part of this reward stops being spendable while a person looks (lots before
        # reviews in the lock order); reservations already made settle with their bookings
        qualification = session.get(PromoQualification, row["qualification_id"])
        for lot in _lots_of(session, row["enrollment_id"], qualification.milestone):
            promo_service.flag_lot_for_review(session, lot_id=lot.id, reason="post_grant_recheck", now=now)
        open_review(session, kind="post_grant_recheck",
                    dedup_key=f"post_grant_recheck:{row['qualification_id']}:{row['booking_id']}",
                    reasons=["evidence_changed_after_grant"], evidence=[{"table": "bookings", "id": row["booking_id"]}],
                    now=now, sla=_review_sla(session, row["campaign_id"]), campaign_id=row["campaign_id"],
                    attribution_id=row["attribution_id"], enrollment_id=row["enrollment_id"],
                    qualification_id=row["qualification_id"], booking_id=row["booking_id"])
    return len(rows)


# --- reinstatement and processing stop ------------------------------------------------------------------------


def reinstate_expired_release(session: Session, *, release_transaction_id: int, actor_user_id: int,
                              actor_capabilities: Collection[Capability | str], reason: str,
                              now: datetime | None = None) -> PromoLot:
    """Give back value that expired (admin+). A new ``reinstate`` ledger row points at the exact expiry release,
    never more than it, at most once; the budget must have room (checked under the budget lock). Idempotent."""
    promo_service._require_capability(actor_capabilities, Capability.PROMO_FRAUD_DECIDE)
    reason = promo_service._require_text(reason, "reason")
    now = _now(now)
    original = session.get(PromoLedgerTransaction, release_transaction_id)
    if original is None or original.kind != "release_granted" or not original.reference_key.startswith("release_granted:expiry"):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "not_an_expiry_release"})
    lot = promo_service._lock_lot(session, original.lot_id)
    done = session.execute(select(PromoLedgerTransaction.id).where(
        PromoLedgerTransaction.kind == "reinstate", PromoLedgerTransaction.reinstates_id == original.id)).first()
    if done is not None:
        return lot
    if original.amount_minor > lot.expired_minor:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "more_than_expired"})
    version = session.get(PromoCampaignVersion, session.get(PromoObligation, lot.obligation_id).campaign_version_id)
    row = PromoLedgerTransaction(public_id=uuid.uuid4(), campaign_id=lot.campaign_id, kind="reinstate",
                                 amount_minor=original.amount_minor, reference_key=f"reinstate:{original.id}",
                                 lot_id=lot.id, reinstates_id=original.id, actor_user_id=actor_user_id, reason=reason)
    try:
        # budget room is checked by the ledger trigger (no negative, no borrowing); never partial (Q122)
        promo_service._flush_translating(session, row)
    except DomainError as exc:
        if exc.code is not ErrorCode.PROMO_BUDGET_EXHAUSTED:
            raise
        # Q122: an approved reinstatement is not erased by a technical refusal. It stays as an unfulfilled,
        # already-overdue review (escalated by the job) in its own transaction, and the refusal is returned.
        review_id = open_review_autonomously(
            session, kind="reinstate_unfulfilled", dedup_key=f"reinstate_unfulfilled:{original.id}",
            reasons=["budget_exhausted"], evidence=[{"table": "promo_ledger_transactions", "id": original.id}],
            now=now, sla=timedelta(seconds=1), campaign_id=lot.campaign_id)
        raise DomainError(ErrorCode.PROMO_BUDGET_EXHAUSTED,
                          details={**(exc.details or {}), "unfulfilled_review": review_id}) from exc
    lot.expired_minor -= original.amount_minor
    if lot.status == PromoRewardStatus.EXPIRED.value:
        lot.status = PromoRewardStatus.AVAILABLE.value
    lot.expires_at = now + timedelta(seconds=version.restoration_grace_s or 0)
    lot.version += 1
    lot.updated_at = now
    session.flush()
    promo_service._audit(session, actor_user_id, "promo_lots", lot.id, "reward_reinstated",
                         {"reinstates": original.id, "amount_minor": original.amount_minor}, reason)
    return lot


def suspend_processing(session: Session, *, campaign_id: int, actor_user_id: int,
                       actor_capabilities: Collection[Capability | str], reason: str,
                       now: datetime | None = None) -> PromoCampaign:
    """Operational safety stop: qualification/grant/expiry processing pauses; no promise or bonus is deleted."""
    promo_service._require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    campaign = promo_service._lock_campaign(session, campaign_id)
    campaign.processing_suspended_at = _now(now)
    campaign.processing_suspend_reason = promo_service._require_text(reason, "reason")
    session.flush()
    promo_service._audit(session, actor_user_id, "promo_campaigns", campaign.id, "processing_suspended", {}, reason)
    return campaign


def resume_processing(session: Session, *, campaign_id: int, actor_user_id: int,
                      actor_capabilities: Collection[Capability | str], reason: str) -> PromoCampaign:
    promo_service._require_capability(actor_capabilities, Capability.PROMO_CAMPAIGN_MANAGE)
    campaign = promo_service._lock_campaign(session, campaign_id)
    campaign.processing_suspended_at = None
    campaign.processing_suspend_reason = None
    session.flush()
    promo_service._audit(session, actor_user_id, "promo_campaigns", campaign.id, "processing_resumed", {}, reason)
    return campaign


def risk_window() -> timedelta:
    return QUALIFICATION_RISK_WINDOW
