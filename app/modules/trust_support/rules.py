"""Pure trust & support rules (no DB, no I/O). Contract values come from ``app.contracts.trust``.

Pilot constants that are not in the contract are marked "(pilot, A12)" and listed in the A12 report.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from app.contracts import trust
from app.contracts.enums import (
    ActorSide,
    DisputeResolutionCode,
    DisputeStatus,
    DisputeType,
    ParcelBookingStatus,
    PassengerBookingStatus,
    SupportTicketKind,
    TrustReviewDecision,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import ensure_aware_utc

ACTIVE_DISPUTE_STATUSES: frozenset[str] = frozenset({DisputeStatus.OPEN.value, DisputeStatus.UNDER_REVIEW.value})
TERMINAL_DISPUTE_STATUSES: frozenset[str] = frozenset({DisputeStatus.RESOLVED.value, DisputeStatus.REJECTED.value})
BLOCKING_DISPUTE_TYPE_VALUES: frozenset[str] = frozenset(item.value for item in trust.BLOCKING_DISPUTE_TYPES)

# Q16: a commission dispute is between the driver and the platform; clients never open or see one.
CLIENT_HIDDEN_DISPUTE_TYPES: frozenset[str] = frozenset({DisputeType.COMMISSION.value})
# S8 "+ finance.adjustment for a financial decision".
FINANCIAL_RESOLUTION_CODES: frozenset[str] = frozenset({DisputeResolutionCode.COMMISSION_ADJUSTED.value})

DISPUTE_EVIDENCE_MAX_FILES = 10  # (pilot, A12)
EVIDENCE_NOTE_MAX_LENGTH = 1000  # (pilot, A12)
RATING_COMMENT_MAX_LENGTH = 500  # (pilot, A12)
DECISION_NOTE_MAX_LENGTH = 1000  # (pilot, A12)

# --- S11 reports and §17.3 fraud signals (wave 6) --------------------------------------------------------------
REPORT_DETAILS_MAX_LENGTH = 2000
# A report is cheap to file and expensive to review: the pilot limit keeps one user from flooding the queue.
REPORT_RATE_LIMIT = 10
REPORT_RATE_WINDOW = timedelta(days=1)
# §17.3 "bir qurilmadan ko'p akkaunt signali": how many distinct accounts on one device raise a signal.
SHARED_DEVICE_MIN_ACCOUNTS = 2
# "g'ayritabiiy safar ketma-ketligi": the same client-driver pair completing this many bookings inside the window.
REPEATED_PAIR_MIN_BOOKINGS = 5
REPEATED_PAIR_WINDOW = timedelta(days=30)

# S14 RATE_LIMITED (pilot, A12): support tickets per user per window. SOS is never rate limited (BR M3): repeat
# presses are deduplicated onto the open SOS ticket.
SUPPORT_TICKET_RATE_WINDOW = timedelta(hours=1)
SUPPORT_TICKET_RATE_LIMIT = 5
assert SupportTicketKind.SOS.value == "sos"

# §17.2: a completed booking can be rated for this long; ratings are published when both sides rated or it ends.
RATING_WINDOW = trust.RATING_PUBLISH_AFTER
COMPLETED_STATUS = PassengerBookingStatus.COMPLETED.value  # same value for parcels
assert COMPLETED_STATUS == ParcelBookingStatus.COMPLETED.value

STRIKE_REASON_CONTACT_FILTER = "contact_filter"
PARTICIPANT_SIDES: frozenset[str] = frozenset({ActorSide.CLIENT.value, ActorSide.DRIVER.value})


def dispute_visible_to_side(dispute_type: str, side: str) -> bool:
    return not (side == ActorSide.CLIENT.value and dispute_type in CLIENT_HIDDEN_DISPUTE_TYPES)


def dispute_blocks_capture(dispute_type: str, status: str) -> bool:
    return dispute_type in BLOCKING_DISPUTE_TYPE_VALUES and status in ACTIVE_DISPUTE_STATUSES


def dispute_escalate_at(opened_at: datetime) -> datetime:
    return ensure_aware_utc(opened_at) + trust.DISPUTE_ESCALATE_AFTER


def rating_window_open(completed_at: datetime | None, now: datetime) -> bool:
    if completed_at is None:
        return False
    return ensure_aware_utc(now) < ensure_aware_utc(completed_at) + RATING_WINDOW


def rating_publish_due(completed_at: datetime | None, now: datetime) -> bool:
    """Unpublished ratings of a booking are published once the rating window has ended (§17.2)."""
    return completed_at is not None and not rating_window_open(completed_at, now)


def counterpart_side(side: str) -> str:
    if side == ActorSide.CLIENT.value:
        return ActorSide.DRIVER.value
    if side == ActorSide.DRIVER.value:
        return ActorSide.CLIENT.value
    raise ValueError(f"not a participant side: {side}")


def review_decision_for(command: str, decision: str | None) -> str | None:
    """S19 decision validation (STATE_MACHINES §12.1). Returns the stored decision (None for start_review)."""
    if command == "start_review":
        if decision is not None:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "decision", "reason": "not_allowed"})
        return None
    if command == "dismiss":
        if decision not in (None, TrustReviewDecision.NO_VIOLATION.value):
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "decision", "reason": "dismiss_requires_no_violation"})
        return TrustReviewDecision.NO_VIOLATION.value
    if command == "action":
        allowed = {TrustReviewDecision.WARNING_ISSUED.value, TrustReviewDecision.ESCALATED_TO_ADMIN.value}
        if decision not in allowed:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "decision", "reason": "action_requires_decision"})
        return decision
    raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "command"})


def merge_evidence(current: Mapping[str, Any] | None, update: Mapping[str, Any]) -> dict[str, Any]:
    """Merge Q45 review evidence: id lists are unioned (order kept), counters take the newest value.

    Only ``trust.TRUST_REVIEW_EVIDENCE_KEYS`` are accepted; values are ids and integers (no text, phone, coordinates).
    """
    merged: dict[str, Any] = dict(current or {})
    for key, value in update.items():
        if key not in trust.TRUST_REVIEW_EVIDENCE_KEYS:
            raise ValueError(f"evidence key not allowed: {key}")
        if isinstance(value, (list, tuple)):
            items = [str(item) for item in value]
            existing = [str(item) for item in merged.get(key, [])]
            merged[key] = existing + [item for item in items if item not in existing]
        elif isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"evidence value must be an int or an id list: {key}")
        else:
            merged[key] = value
    return merged


def strikes_in_window(strike_times: Iterable[datetime], at: datetime) -> int:
    start = ensure_aware_utc(at) - trust.STRIKE_REVIEW_WINDOW
    return sum(1 for moment in strike_times if start <= ensure_aware_utc(moment) <= ensure_aware_utc(at))
