"""Trust & support contract (wave 3, A12): dispute hooks for bookings, Q45 strike/review rules, reputation
(spec §8.2, §9.5, §11, §16, §17.2-§17.3; AC26, AC36; Q7, Q45, Q66, Q74).

Pure: stdlib + contracts only. Values marked "(pilot)" are integrator defaults awaiting user confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.contracts.enums import DisputeType, RatingBucket, ReputationLabel, ServiceType
from app.contracts.timeutil import ensure_aware_utc

# --- disputes (STATE_MACHINES §8) -----------------------------------------------------------------------------------

# Open disputes of these types delay the completion capture (STATE_MACHINES §8, AC20, AC26).
BLOCKING_DISPUTE_TYPES: frozenset[DisputeType] = frozenset(
    {DisputeType.SERVICE, DisputeType.COMMISSION, DisputeType.PAYMENT, DisputeType.DELIVERY}
)
DISPUTE_ESCALATE_AFTER = timedelta(hours=48)  # §9.5
DISPUTE_DESCRIPTION_MAX_LENGTH = 2000


class BlockingDisputeProbe(Protocol):
    """``bookings.service.set_blocking_dispute_probe(probe)`` (A4 signature ``Callable[[Session, int], bool]``).

    True when the booking (internal id) has a ``disputes_v2`` row of a :data:`BLOCKING_DISPUTE_TYPES` type in status
    ``open``/``under_review``. Read-only, no lock beyond the caller's booking lock, never commits. Once registered,
    ``bookings.service.dispute_state`` returns ``open``/``clear`` instead of ``unavailable`` (Q74 fallback ends).
    """

    def __call__(self, session: Any, booking_id: int) -> bool: ...


class PaymentDisputeOpener(Protocol):
    """``bookings.service.set_payment_dispute_opener(opener)`` (A4 signature
    ``Callable[[Session, Booking, CashReceipt, int, str], int | None]``).

    Called by A4 inside ``contest_cash_receipt`` after the booking is locked and the receipt is ``contested``: inserts a
    ``disputes_v2`` row (type ``payment``, ``cash_receipt_id``) and returns its internal id, stored in
    ``cash_receipts.dispute_id``. Must not change booking/receipt status, must not commit; an already open payment
    dispute returns the existing id (idempotent) instead of raising.
    """

    def __call__(self, session: Any, booking: Any, receipt: Any, actor_user_id: int, comment: str) -> int | None: ...


# --- Q45 contact-filter strikes and review signals --------------------------------------------------------------------

CONTACT_FILTER_STRIKE_WINDOW = timedelta(days=7)  # (pilot)
CONTACT_FILTER_FREE_HITS = 1  # (pilot) the first hit in the window is a warning only; each further hit is a strike
STRIKE_REVIEW_WINDOW = timedelta(days=30)  # (pilot)
STRIKES_FOR_REVIEW = 3  # (pilot) strikes in the window open one contact_filter_strikes review item
QUICK_CANCEL_AFTER_CHAT_WINDOW = timedelta(hours=1)  # (pilot) cancel within this after a chat contact-filter hit
REPEATED_PAIR_CANCEL_WINDOW = timedelta(days=30)  # (pilot)
REPEATED_PAIR_CANCEL_THRESHOLD = 2  # (pilot) cancelled bookings of the same client+driver pair in the window
# Review item evidence carries ids and counters only (no text, phone, name or coordinates).
TRUST_REVIEW_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {"booking_ids", "chat_thread_ids", "source_event_ids", "hit_count", "strike_count", "cancel_count", "window_days"}
)


def hit_is_strike(prior_hits_in_window: int) -> bool:
    """A contact-filter hit becomes a strike when earlier hits of the actor in the window reach the free allowance."""
    if prior_hits_in_window < 0:
        raise ValueError("prior_hits_in_window must be >= 0")
    return prior_hits_in_window >= CONTACT_FILTER_FREE_HITS


def strikes_need_review(strikes_in_window: int) -> bool:
    return strikes_in_window >= STRIKES_FOR_REVIEW


def is_quick_cancel_after_chat(last_contact_filter_hit_at: datetime | None, cancelled_at: datetime) -> bool:
    if last_contact_filter_hit_at is None:
        return False
    delta = ensure_aware_utc(cancelled_at) - ensure_aware_utc(last_contact_filter_hit_at)
    return timedelta(0) <= delta <= QUICK_CANCEL_AFTER_CHAT_WINDOW


def is_repeated_pair_cancellation(cancelled_in_window: int) -> bool:
    return cancelled_in_window >= REPEATED_PAIR_CANCEL_THRESHOLD


# --- support / SOS (§16) --------------------------------------------------------------------------------------------

SUPPORT_MESSAGE_MAX_LENGTH = 2000
# §16: the API never states or implies a 24/7 operator or a response time; contacts/hours come from configuration
# (user supplied). Without configuration the support contact DTO says ``available: false``.
SUPPORT_PROMISES_RESPONSE_TIME = False


# --- reputation (§8.2, AC36) ----------------------------------------------------------------------------------------

RATING_PRIOR = 4.5  # §8.2 internal ranking prior only; never shown to users
RATING_PRIOR_WEIGHT = 10  # m
COMPLETION_PRIOR = 0.90  # §8.2 assumption, not a statistic

# U6 (user decision 17.09.2026, option A). Thresholds for the *displayed* bucket - unrelated to RATING_PRIOR,
# which stays an internal ranking correction and is never shown. Below the minimum count there is no bucket
# judgement at all: the driver is "new", which is the truth, rather than an average of one rating.
RATING_BUCKET_MIN_COUNT = 3
RATING_BUCKET_GOOD_FROM = 4.0
RATING_BUCKET_MIXED_FROM = 3.0
ON_TIME_PRIOR = 0.90
RATING_PUBLISH_AFTER = timedelta(days=7)  # §17.2: published when both rated or after 7 days


@dataclass(frozen=True, slots=True)
class ReputationSummary:
    """A12 export ``trust_support.service.reputation_summaries`` for A5 ranking and DTO labels (no fake rating)."""

    user_id: int
    service_type: ServiceType
    rating_count: int = 0
    rating_sum: int = 0  # sum of integer stars
    completed_bookings: int = 0
    completed_trips: int = 0
    eligible_resolved: int = 0
    on_time_count: int = 0

    @property
    def label(self) -> ReputationLabel:
        return ReputationLabel.RATED if self.rating_count > 0 else ReputationLabel.NEW_VERIFIED

    @property
    def average_rating(self) -> float | None:
        """Shown value; ``None`` without ratings (S2: n=0 -> null)."""
        return None if self.rating_count == 0 else self.rating_sum / self.rating_count

    @property
    def rating_bucket(self) -> RatingBucket:
        """U6: the group shown to a client, always beside :attr:`rating_count`.

        Never derived from :attr:`adjusted_rating` - that value contains the 4.5 prior and would hand a brand
        new driver a "good" badge it did not earn (§8.2). Too few ratings is its own answer, not a zero.
        """
        if self.rating_count < RATING_BUCKET_MIN_COUNT:
            return RatingBucket.NEW_VERIFIED
        average = self.average_rating
        if average is None:  # unreachable while the count is positive; kept so a future change cannot invent one
            return RatingBucket.NEW_VERIFIED
        if average >= RATING_BUCKET_GOOD_FROM:
            return RatingBucket.GOOD
        if average >= RATING_BUCKET_MIXED_FROM:
            return RatingBucket.MIXED
        return RatingBucket.LOW

    @property
    def adjusted_rating(self) -> float:
        """Internal ranking value ``(n*avg + m*prior)/(n+m)`` (§8.2); never displayed."""
        return (self.rating_sum + RATING_PRIOR_WEIGHT * RATING_PRIOR) / (self.rating_count + RATING_PRIOR_WEIGHT)

    @property
    def completion_ratio(self) -> float:
        """``C = (completed + 10*prior) / (eligible_resolved + 10)`` (§8.2)."""
        return (self.completed_bookings + 10 * COMPLETION_PRIOR) / (self.eligible_resolved + 10)
