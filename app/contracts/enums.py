"""Stage-2 domain enums.

Sources: spec §5.1 (listing kinds), §5.2 (price basis, parcel payer), §6.4
(match types), §9 (cash/commission), §10.4 (tracking freshness), §11 (state
machines), §12 (roles and capabilities), §15 (events), §20.3 (feature flags),
and user decisions of 2026-09-13 (docs/architecture/adr/).

String values are part of the public API v2 contract and of DB CHECK
constraints. Never rename a value. Adding a value is a contract change.
"""

from collections.abc import Iterable
from enum import StrEnum


class ListingKind(StrEnum):
    REQUEST = "request"
    TRIP_OFFER = "trip_offer"


class ServiceType(StrEnum):
    PASSENGER = "passenger"
    PARCEL = "parcel"


class PriceBasis(StrEnum):
    """How a quoted amount relates to the quantity.

    ``per_seat``: passenger price per person; total = unit x seat_count.
    ``total``: one amount for the whole service (parcel delivery, or a
    passenger request priced as a whole).
    """

    PER_SEAT = "per_seat"
    TOTAL = "total"


class Currency(StrEnum):
    UZS = "UZS"


class PaymentMethod(StrEnum):
    """Pilot fare payment. Card payments are a later stage (spec §9.6)."""

    CASH = "cash"


class ParcelPayer(StrEnum):
    SENDER = "sender"
    RECEIVER = "receiver"


class ActorSide(StrEnum):
    """Who performed or initiated a command (cancellation, proof, report)."""

    CLIENT = "client"
    DRIVER = "driver"
    OPERATOR = "operator"
    SYSTEM = "system"


class Role(StrEnum):
    """Stored roles (legacy ``users.role`` and new ``user_roles.role``)."""

    CLIENT = "client"
    DRIVER = "driver"
    OPERATOR = "operator"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    # Decision Q17: dedicated finance staff role (top-up approval, fee finalization,
    # adjustment approval, finance reports). super_admin acts until it is wired.
    FINANCE = "finance"


MARKETPLACE_ROLES: frozenset[Role] = frozenset({Role.CLIENT, Role.DRIVER})
STAFF_ROLES: frozenset[Role] = frozenset({Role.OPERATOR, Role.ADMIN, Role.SUPER_ADMIN, Role.FINANCE})


def role_combination_allowed(roles: Iterable[Role | str]) -> bool:
    """Staff and marketplace accounts are separate (decision 3, ADR-0007)."""
    values = {Role(role) for role in roles}
    return not (values & STAFF_ROLES and values & MARKETPLACE_ROLES)


class Capability(StrEnum):
    """Server-computed permissions (ADR-0007). Never trusted from a token."""

    # marketplace: new business (lost on eligibility block/expiry, D16)
    LISTING_CREATE_REQUEST = "listing.create_request"
    LISTING_CREATE_TRIP_OFFER = "listing.create_trip_offer"
    PROPOSAL_SUBMIT_AS_CLIENT = "proposal.submit_as_client"
    PROPOSAL_SUBMIT_AS_DRIVER = "proposal.submit_as_driver"
    TRIP_CREATE = "trip.create"
    # marketplace: existing obligations (kept on eligibility block/expiry, D16)
    TRIP_OPERATE = "trip.operate"
    TRACKING_PUBLISH = "tracking.publish"
    WALLET_VIEW_OWN = "wallet.view_own"
    WALLET_TOPUP_REQUEST = "wallet.topup_request"
    # staff
    OPS_VIEW = "ops.view"
    OPS_BOOKING_COMMAND = "ops.booking_command"
    OPS_BOOKING_CANCEL = "ops.booking_cancel"
    OPS_DISPUTE_RESOLVE = "ops.dispute_resolve"
    # Wave 3.1: deciding a v2 dispute (resolve / reject, and the cash outcome that belongs to the decision) is
    # admin+, like v1 (Q13, Q38). ops.dispute_resolve stays the operator's "work the dispute" capability:
    # see it, add evidence, start the review, leave a note.
    OPS_DISPUTE_DECIDE = "ops.dispute_decide"
    OPS_CORRIDOR_MANAGE = "ops.corridor_manage"
    OPS_FEATURE_FLAG_MANAGE = "ops.feature_flag_manage"
    OPS_DRIVER_ELIGIBILITY_MANAGE = "ops.driver_eligibility_manage"
    FINANCE_TOPUP_APPROVE = "finance.topup_approve"
    FINANCE_ADJUSTMENT = "finance.adjustment"
    FINANCE_REPORTS = "finance.reports"
    FINANCE_COMMISSION_POLICY_VIEW = "finance.commission_policy_view"
    FINANCE_COMMISSION_POLICY_MANAGE = "finance.commission_policy_manage"
    STAFF_MANAGE = "staff.manage"
    # §5.2 (wave 7): drafting and approving the prohibited/restricted items policy. super_admin only - what may
    # be carried is a legal/business decision, not an operator convenience.
    PLATFORM_POLICY_MANAGE = "platform.policy_manage"
    #: ADR-0021: activate somebody else's second factor. Never grants approval of one's own.
    STAFF_MFA_APPROVE = "staff.mfa_approve"
    # Q17 additions: fee finalization and the second (different-person) approval of
    # large adjustments/top-ups are separate from creating an adjustment.
    FINANCE_FEE_FINALIZE = "finance.fee_finalize"
    FINANCE_ADJUSTMENT_APPROVE = "finance.adjustment_approve"
    # Wave 3 (A12/A7, Q45, §16): trust review queue decisions, chat moderation, support/SOS handling (operator+).
    OPS_TRUST_REVIEW = "ops.trust_review"
    # Promotions (ADR-0023 §12, Q105). Operators review and comment; they never change budgets or reward amounts.
    PROMO_CAMPAIGN_VIEW = "promo.campaign_view"
    PROMO_CAMPAIGN_MANAGE = "promo.campaign_manage"  # create, version, activate, pause, close (super_admin)
    PROMO_BUDGET_ALLOCATE = "promo.budget_allocate"  # allocate / reduce and second-approve large changes
    PROMO_FRAUD_REVIEW = "promo.fraud_review"  # start a review, add a note
    PROMO_FRAUD_DECIDE = "promo.fraud_decide"  # release / reject / reverse after review (admin+)


# Requires current eligibility (approved driver / active account, not blocked,
# documents valid). Losing eligibility removes only these (D16).
NEW_BUSINESS_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.LISTING_CREATE_REQUEST,
        # Q138 (ADR-0026): LISTING_CREATE_TRIP_OFFER is kept as a value for history, granted to nobody.
        Capability.PROPOSAL_SUBMIT_AS_CLIENT,
        Capability.PROPOSAL_SUBMIT_AS_DRIVER,
        Capability.TRIP_CREATE,
    }
)

# Kept by a driver who has an assigned non-terminal trip/booking even after an
# eligibility block or document expiry: tracking, proofs, support (§9.2, §10).
OBLIGATION_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.TRIP_OPERATE,
        Capability.TRACKING_PUBLISH,
        Capability.WALLET_VIEW_OWN,
        Capability.WALLET_TOPUP_REQUEST,
    }
)

_OPERATOR_CAPS = frozenset(
    {
        Capability.OPS_VIEW,
        Capability.OPS_BOOKING_COMMAND,
        Capability.OPS_DISPUTE_RESOLVE,
        Capability.FINANCE_COMMISSION_POLICY_VIEW,
        Capability.OPS_TRUST_REVIEW,
        Capability.PROMO_CAMPAIGN_VIEW,
        Capability.PROMO_FRAUD_REVIEW,
    }
)
_ADMIN_CAPS = _OPERATOR_CAPS | frozenset(
    {
        Capability.PROMO_FRAUD_DECIDE,
        Capability.OPS_DISPUTE_DECIDE,
        Capability.OPS_BOOKING_CANCEL,
        Capability.OPS_CORRIDOR_MANAGE,
        Capability.OPS_FEATURE_FLAG_MANAGE,
        Capability.OPS_DRIVER_ELIGIBILITY_MANAGE,
        Capability.FINANCE_REPORTS,
    }
)
# Q17: the finance role owns money decisions. Large adjustments/top-ups need a second,
# DIFFERENT staff member holding FINANCE_ADJUSTMENT_APPROVE (enforced by the wallet
# service, not by capability alone). Commission policy management stays super_admin (Q2).
_FINANCE_CAPS = frozenset(
    {
        Capability.OPS_VIEW,
        Capability.FINANCE_TOPUP_APPROVE,
        Capability.FINANCE_ADJUSTMENT,
        Capability.FINANCE_ADJUSTMENT_APPROVE,
        Capability.FINANCE_FEE_FINALIZE,
        Capability.FINANCE_REPORTS,
        Capability.FINANCE_COMMISSION_POLICY_VIEW,
        Capability.PROMO_CAMPAIGN_VIEW,
        Capability.PROMO_BUDGET_ALLOCATE,
    }
)
# super_admin acts for finance until the finance role is wired (Q17).
_SUPER_ADMIN_CAPS = _ADMIN_CAPS | _FINANCE_CAPS | frozenset(
    {
        Capability.FINANCE_COMMISSION_POLICY_MANAGE,
        Capability.STAFF_MANAGE,
        Capability.PLATFORM_POLICY_MANAGE,
        Capability.STAFF_MFA_APPROVE,
        Capability.PROMO_CAMPAIGN_MANAGE,
    }
)

STAFF_ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.OPERATOR: _OPERATOR_CAPS,
    Role.ADMIN: _ADMIN_CAPS,
    Role.SUPER_ADMIN: _SUPER_ADMIN_CAPS,
    Role.FINANCE: _FINANCE_CAPS,
}


class ListingStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    PAUSED = "paused"
    FULFILLED = "fulfilled"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ProposalStatus(StrEnum):
    """Status of one immutable proposal version."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class TripStatus(StrEnum):
    PLANNED = "planned"
    BOARDING = "boarding"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class PassengerBookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    AWAITING_PICKUP = "awaiting_pickup"
    ONBOARD = "onboard"
    ARRIVED = "arrived"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class ParcelBookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    AWAITING_PICKUP = "awaiting_pickup"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RETURN_REQUIRED = "return_required"
    RETURNED = "returned"
    DELIVERY_FAILED = "delivery_failed"


class NoShowReviewStatus(StrEnum):
    """Driver report -> operator decision (decision 7)."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class CustodyCaseStatus(StrEnum):
    """Operator case for a parcel still in custody after delivery failure/return (D1)."""

    OPEN = "open"
    RESOLVED = "resolved"


class FaultSide(StrEnum):
    """Who is at fault for a cancellation/no-show (spec §8.2 reliability stats, N3)."""

    CLIENT = "client"
    DRIVER = "driver"
    PLATFORM = "platform"
    NONE = "none"  # justified cancellation: road closure, operator-approved reason


class CashCollectionStatus(StrEnum):
    UNPAID = "unpaid"
    REPORTED_PAID = "reported_paid"
    ACKNOWLEDGED = "acknowledged"
    CONTESTED = "contested"


class CashResolutionOutcome(StrEnum):
    """How a payment dispute settles a ``contested`` cash receipt (STATE_MACHINES §6, wave 3.1).

    ``paid`` -> ``contested -> acknowledged`` (``resolve_paid``); ``unpaid`` -> ``contested -> unpaid``
    (``resolve_unpaid``, so the payer can report again). It is the decision's own field, not money movement.
    """

    PAID = "paid"
    UNPAID = "unpaid"


class CommissionStatus(StrEnum):
    EXEMPT = "exempt"
    HELD = "held"
    CAPTURED = "captured"
    RELEASED = "released"
    PARTIALLY_REVERSED = "partially_reversed"
    REVERSED = "reversed"


class DisputeStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class DisputeType(StrEnum):
    SERVICE = "service"
    NO_SHOW = "no_show"
    PAYMENT = "payment"
    DELIVERY = "delivery"
    COMMISSION = "commission"
    SAFETY = "safety"
    OTHER = "other"


class AmendmentStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class TopupStatus(StrEnum):
    PENDING = "pending"
    AWAITING_SECOND_APPROVAL = "awaiting_second_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class TrackingSessionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CLOSED = "closed"


class TrackingFreshness(StrEnum):
    """UI freshness buckets (spec §10.4): <=30 s, 31-120 s, >120 s ("aloqa uzilgan").

    ``tracking.stale`` (spec §15 event name) is emitted when a trip enters ``lost``.
    Thresholds live in ``app.contracts.tracking``.
    """

    FRESH = "fresh"
    DELAYED = "delayed"
    LOST = "lost"
    NO_DATA = "no_data"


class MatchType(StrEnum):
    EXACT = "exact"
    ON_ROUTE = "on_route"
    DETOUR = "detour"
    ALTERNATIVE = "alternative"


class MatchReason(StrEnum):
    """Stable reason codes explaining a match decision (spec §6.4, §8; FeedItemDTO.match.reasons).

    Promoted from ``app.modules.geo.types`` (A2) in integration pass 1; geo re-exports it.
    """

    FULL_ROUTE = "full_route"
    INTERMEDIATE_SEGMENT = "intermediate_segment"
    PICKUP_AT_STOP = "pickup_at_stop"
    DROPOFF_AT_STOP = "dropoff_at_stop"
    PICKUP_DETOUR = "pickup_detour"
    DROPOFF_DETOUR = "dropoff_detour"
    NEARBY_STOP = "nearby_stop"
    TIME_DIFFERS = "time_differs"
    SAME_STOP = "same_stop"
    PICKUP_NOT_ON_ROUTE = "pickup_not_on_route"
    DROPOFF_NOT_ON_ROUTE = "dropoff_not_on_route"
    REVERSE_DIRECTION = "reverse_direction"
    DETOUR_ORDER_UNKNOWN = "detour_order_unknown"
    TIME_WINDOW_MISMATCH = "time_window_mismatch"
    DETOUR_LIMIT_EXCEEDED = "detour_limit_exceeded"
    ROUTING_UNAVAILABLE = "routing_unavailable"


class CorridorRolloutState(StrEnum):
    """``service_corridors.rollout_state`` (DATA_MODEL §1.3; STATE_MACHINES §10).

    Promoted from ``app.modules.geo.schemas`` (A2) in integration pass 1; geo re-exports it.
    """

    DRAFT = "draft"
    INTERNAL = "internal"
    PILOT = "pilot"
    ACTIVE = "active"
    CLOSED = "closed"


class BookingAction(StrEnum):
    """Participant actions: ``POST /api/v2/bookings/{id}/actions/{action}``."""

    # shared
    MARK_AWAITING_PICKUP = "mark_awaiting_pickup"
    ARRIVE_AT_PICKUP = "arrive_at_pickup"
    COMPLETE = "complete"
    # passenger
    BOARD = "board"
    DROP_OFF = "drop_off"
    REPORT_NO_SHOW = "report_no_show"  # opens a review; does not change service status
    # parcel
    PICK_UP = "pick_up"
    START_TRANSIT = "start_transit"
    DELIVER = "deliver"
    REPORT_DELIVERY_FAILED = "report_delivery_failed"
    RETRY_DELIVERY = "retry_delivery"
    RETURN_TO_SENDER = "return_to_sender"


class OperatorBookingCommand(StrEnum):
    """Staff commands: ``POST /api/v2/admin/bookings/{id}/commands/{command}``."""

    CONFIRM_NO_SHOW = "confirm_no_show"
    REJECT_NO_SHOW = "reject_no_show"
    COMPLETE_WITH_EVIDENCE = "complete_with_evidence"
    DROP_OFF = "drop_off"
    REQUIRE_RETURN = "require_return"
    RETURN_TO_SENDER = "return_to_sender"
    RESOLVE_CUSTODY_CASE = "resolve_custody_case"
    FINALIZE_FEE = "finalize_fee"
    CANCEL = "cancel"
    # Wave 2.1 (BR blocker 3): invalidate the current code of one proof kind and issue a new rotation
    # (``app.contracts.proofs``); the code owner can also do it self-service, rate-limited.
    REISSUE_PROOF_CODE = "reissue_proof_code"
    # Q139 (ADR-0026): parcel outcome recorded by staff (no delivery code, no receiver confirmation).
    MARK_DELIVERED = "mark_delivered"


OPERATOR_COMMAND_CAPABILITY: dict[OperatorBookingCommand, Capability] = {
    OperatorBookingCommand.REISSUE_PROOF_CODE: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.MARK_DELIVERED: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.CONFIRM_NO_SHOW: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.REJECT_NO_SHOW: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.COMPLETE_WITH_EVIDENCE: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.DROP_OFF: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.REQUIRE_RETURN: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.RETURN_TO_SENDER: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.RESOLVE_CUSTODY_CASE: Capability.OPS_BOOKING_COMMAND,
    OperatorBookingCommand.FINALIZE_FEE: Capability.FINANCE_FEE_FINALIZE,  # Q17 (was FINANCE_ADJUSTMENT)
    OperatorBookingCommand.CANCEL: Capability.OPS_BOOKING_CANCEL,
}


class ProofKind(StrEnum):
    BOARDING_CODE = "boarding_code"
    PICKUP_CODE = "pickup_code"
    DELIVERY_CODE = "delivery_code"
    RETURN_CODE = "return_code"
    OPERATOR_EVIDENCE = "operator_evidence"


class CommissionPolicyKind(StrEnum):
    STANDARD = "standard"  # fee_bps > 0, open-ended allowed
    CAMPAIGN = "campaign"  # time-boxed; the only kind that may be 0 bps (decision 1)


class ChargeKind(StrEnum):
    COMMISSION = "commission"


class FeatureFlagKey(StrEnum):
    """Spec §20.3 flags.

    There is deliberately no legacy v1 write kill switch: v1 cutover is not part
    of stage 2 (decision 4, ADR-0006).
    """

    PASSENGER_ENABLED = "passenger_enabled"
    PARCEL_ENABLED = "parcel_enabled"
    DRIVER_LISTING_ENABLED = "driver_listing_enabled"
    CORRIDOR_MATCHING_ENABLED = "corridor_matching_enabled"
    WALLET_REQUIRED = "wallet_required"
    TRACKING_ENABLED = "tracking_enabled"
    CARD_PAYMENTS_ENABLED = "card_payments_enabled"
    # Q101/ADR-0023: referral bonuses and credits. OFF in production; never turns any other flag on.
    PROMOTIONS_ENABLED = "promotions_enabled"


class FlagScopeType(StrEnum):
    """Scope precedence, most specific first: cohort > corridor > region > country."""

    COHORT = "cohort"
    CORRIDOR = "corridor"
    REGION = "region"
    COUNTRY = "country"


class EngineVersion(StrEnum):
    V1 = "v1"
    V2 = "v2"


class VehicleClass(StrEnum):
    """Coarse, non-identifying vehicle class shown before accept (R2, Q43, Q40)."""

    CAR = "car"
    MINIVAN = "minivan"
    MINIBUS = "minibus"


def vehicle_class_for_seat_capacity(seat_capacity: int) -> VehicleClass:
    """Derived from passenger seats only (never make/model/plate): <=4 car, <=7 minivan, else minibus."""
    if seat_capacity <= 4:
        return VehicleClass.CAR
    if seat_capacity <= 7:
        return VehicleClass.MINIVAN
    return VehicleClass.MINIBUS


class LedgerAdjustmentStatus(StrEnum):
    """``ledger_adjustment_requests.status`` (A3, Q17, Q49)."""

    PENDING_SECOND_APPROVAL = "pending_second_approval"
    POSTED = "posted"
    REJECTED = "rejected"  # only by a different user holding finance.adjustment_approve
    WITHDRAWN = "withdrawn"  # only by the requester


LEDGER_ADJUSTMENT_TERMINAL: frozenset[LedgerAdjustmentStatus] = frozenset(
    {LedgerAdjustmentStatus.POSTED, LedgerAdjustmentStatus.REJECTED, LedgerAdjustmentStatus.WITHDRAWN}
)


class EventType(StrEnum):
    """Outbox event types (spec §15 plus lifecycle events implied elsewhere).

    Allowed payload keys per type: ``app.contracts.events.EVENT_PAYLOAD_ALLOWLIST``.
    """

    LISTING_PUBLISHED = "listing.published"
    LISTING_EXPIRED = "listing.expired"
    LISTING_CANCELLED = "listing.cancelled"
    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_SUPERSEDED = "proposal.superseded"
    PROPOSAL_WITHDRAWN = "proposal.withdrawn"
    PROPOSAL_REJECTED = "proposal.rejected"
    PROPOSAL_EXPIRED = "proposal.expired"
    BOOKING_ACCEPTED = "booking.accepted"
    BOOKING_CANCELLED = "booking.cancelled"
    BOOKING_STARTED = "booking.started"
    BOOKING_STATUS_CHANGED = "booking.status_changed"
    BOOKING_COMPLETED = "booking.completed"
    BOOKING_NO_SHOW_REPORTED = "booking.no_show_reported"
    BOOKING_CUSTODY_CASE_OPENED = "booking.custody_case_opened"
    TRIP_STATUS_CHANGED = "trip.status_changed"
    WALLET_HOLD_CREATED = "wallet.hold.created"
    WALLET_HOLD_ADJUSTED = "wallet.hold.adjusted"
    WALLET_HOLD_RELEASED = "wallet.hold.released"
    COMMISSION_CAPTURED = "commission.captured"
    COMMISSION_REVERSED = "commission.reversed"
    COMMISSION_POLICY_CREATED = "commission.policy.created"
    COMMISSION_POLICY_ENDED = "commission.policy.ended"
    TOPUP_APPROVED = "wallet.topup.approved"
    TRACKING_STALE = "tracking.stale"
    DISPUTE_OPENED = "dispute.opened"
    DISPUTE_RESOLVED = "dispute.resolved"
    # Q43/Q45 contact filter (staff-only; never carries the matched text)
    CONTACT_FILTER_HIT = "trust.contact_filter.hit"
    CONTACT_STRIKE_RECORDED = "trust.contact_strike.recorded"
    # Wave 2 (§9.5) operator signals, staff-only: client confirmation overdue (24h), wallet hold escalation (48h)
    BOOKING_CONFIRMATION_OVERDUE = "booking.confirmation_overdue"
    WALLET_HOLD_ESCALATION_DUE = "wallet.hold.escalation_due"
    # Wave 2.1: proof code reissued (all participants; no code in payload); Q66 commission kept held for finance
    # review because the dispute module (A12) is absent (staff only).
    BOOKING_PROOF_CODE_REISSUED = "booking.proof_code.reissued"
    COMMISSION_FINANCE_REVIEW_REQUIRED = "commission.finance_review_required"
    # Wave 3 (16.09.2026). Payloads never carry text, phones, names, coordinates or codes (§15).
    CHAT_MESSAGE_CREATED = "chat.message.created"  # A7
    BOOKING_DRIVER_ARRIVED = "booking.driver_arrived"  # A4 `arrive_at_pickup` ("Keldim", Q44)
    TRACKING_WINDOW_OPENED = "tracking.window_opened"  # A6 (AC44)
    SAVED_SEARCH_MATCHED = "saved_search.matched"  # A5 (§6.6)
    TRUST_REVIEW_OPENED = "trust.review.opened"  # A12 (Q45), staff only
    TRUST_WARNING_ISSUED = "trust.warning_issued"  # A12 (Q45), to the warned user
    SUPPORT_TICKET_OPENED = "support.ticket.opened"  # A12 (§16), staff only
    SUPPORT_SOS_RAISED = "support.sos.raised"  # A12 (§16), staff only
    # Wave 5 (A4/A7 follow-up): the counterparty learns about an open change request instead of finding it by
    # chance when opening the booking. Never carries the commission (Q16).
    BOOKING_AMENDMENT_REQUESTED = "booking.amendment_requested"
    BOOKING_AMENDMENT_DECIDED = "booking.amendment_decided"
    SUPPORT_TICKET_STATUS_CHANGED = "support.ticket.status_changed"  # A12, to the requester
    # ADR-0026 (Q141): the booking-bound operator chat. Payloads carry ids only - never the text.
    SUPPORT_THREAD_OPENED = "support.thread.opened"  # staff only (the operator queue)
    SUPPORT_THREAD_REPLIED = "support.thread.replied"  # to the requester only (staff wrote or closed the thread)
    RATING_PUBLISHED = "rating.published"  # A12 (§17.2)
    DISPUTE_ESCALATION_DUE = "dispute.escalation_due"  # A12 (§9.5, 48 h), staff only
    # referral stage 3 (ADR-0023): staff only until the stage-5 client shows rewards
    PROMO_REWARD_GRANTED = "promo.reward_granted"
    PROMO_REVIEW_OPENED = "promo.review_opened"
    PROMO_REVIEW_ESCALATED = "promo.review_escalated"


# Author role per listing kind (spec §5.1). Capability checks use this.
LISTING_AUTHOR_ROLE: dict[ListingKind, Role] = {
    ListingKind.REQUEST: Role.CLIENT,
    ListingKind.TRIP_OFFER: Role.DRIVER,
}

# Allowed price bases per (kind, service). Parcel is always a total price;
# spec §5.2: "yetkazish narxi 70 000 so'm".
ALLOWED_PRICE_BASIS: dict[tuple[ListingKind, ServiceType], frozenset[PriceBasis]] = {
    (ListingKind.REQUEST, ServiceType.PASSENGER): frozenset({PriceBasis.PER_SEAT, PriceBasis.TOTAL}),
    (ListingKind.REQUEST, ServiceType.PARCEL): frozenset({PriceBasis.TOTAL}),
    (ListingKind.TRIP_OFFER, ServiceType.PASSENGER): frozenset({PriceBasis.PER_SEAT}),
    (ListingKind.TRIP_OFFER, ServiceType.PARCEL): frozenset({PriceBasis.TOTAL}),
}

# Production defaults (decision 5, spec §20.3): every new service is OFF until
# enabled per corridor. Evaluated only when no scoped flag row exists.
# Non-production environments may override via seed.
PRODUCTION_FLAG_DEFAULTS: dict[FeatureFlagKey, bool] = {
    FeatureFlagKey.PASSENGER_ENABLED: False,
    FeatureFlagKey.PARCEL_ENABLED: False,
    FeatureFlagKey.DRIVER_LISTING_ENABLED: False,
    FeatureFlagKey.CORRIDOR_MATCHING_ENABLED: False,
    FeatureFlagKey.WALLET_REQUIRED: True,
    FeatureFlagKey.TRACKING_ENABLED: False,
    FeatureFlagKey.CARD_PAYMENTS_ENABLED: False,
    FeatureFlagKey.PROMOTIONS_ENABLED: False,
}

# Flags whose value is fixed in production; any scoped row with another value
# is rejected (decision 1: wallet_required cannot be false in production).
FLAGS_LOCKED_IN_PRODUCTION: dict[FeatureFlagKey, bool] = {
    FeatureFlagKey.WALLET_REQUIRED: True,
}

# Flags whose production enablement requires super_admin plus a recorded
# legal/business approval reference (decision 5, K7, spec §17.7).
FLAGS_REQUIRING_APPROVAL_REFERENCE: frozenset[FeatureFlagKey] = frozenset(
    {FeatureFlagKey.PASSENGER_ENABLED, FeatureFlagKey.CARD_PAYMENTS_ENABLED, FeatureFlagKey.PROMOTIONS_ENABLED}
)

# v2 service flags gated by Q48/Q56 and guarded by Q72 (mirrors app.modules.geo.service.V2_SERVICE_FLAGS and 0053).
V2_SERVICE_FLAGS: frozenset[FeatureFlagKey] = frozenset(
    {
        FeatureFlagKey.PASSENGER_ENABLED,
        FeatureFlagKey.PARCEL_ENABLED,
        FeatureFlagKey.DRIVER_LISTING_ENABLED,
        FeatureFlagKey.CORRIDOR_MATCHING_ENABLED,
        FeatureFlagKey.TRACKING_ENABLED,
        FeatureFlagKey.CARD_PAYMENTS_ENABLED,
    }
)

# Q72 (wave 2.1): enabling a v2 service flag is accepted by the DB (0057) only when the transaction carries this
# marker, set with ``SET LOCAL elchi.flag_change_source = 'admin_api'`` by geo.service.set_flag_value. A psql
# session or a migration without it cannot turn a flag ON (turning OFF stays possible).
FLAG_CHANGE_SOURCE_SETTING = "elchi.flag_change_source"
FLAG_CHANGE_SOURCE_ADMIN_API = "admin_api"


# --- wave 2.1 (15.09.2026) -------------------------------------------------------------------------------------


class ParcelType(StrEnum):
    """Q68: strict parcel type (``parcel_listing_details.parcel_type`` / ``accepted_parcel_types``).

    Integrator pilot list (``box`` and ``documents`` were already used); the product owner may extend it -
    adding a value is a contract change (DB CHECK in A1 0054).
    """

    DOCUMENTS = "documents"
    BOX = "box"
    BAG = "bag"
    ELECTRONICS = "electronics"
    CLOTHING = "clothing"
    OTHER = "other"


class Amenity(StrEnum):
    """Q68: strict passenger amenity (``passenger_listing_details.amenities``); integrator pilot list."""

    AIR_CONDITIONING = "air_conditioning"
    PHONE_CHARGER = "phone_charger"
    NO_SMOKING = "no_smoking"
    PETS_ALLOWED = "pets_allowed"
    LARGE_TRUNK = "large_trunk"
    WIFI = "wifi"


PARCEL_TYPE_VALUES: frozenset[str] = frozenset(item.value for item in ParcelType)
AMENITY_VALUES: frozenset[str] = frozenset(item.value for item in Amenity)


class AdminBookingQueue(StrEnum):
    """B12 ``GET /admin/bookings?queue=`` (A4 ``ADMIN_QUEUES``).

    ``awaiting_confirmation`` also holds parcels ``delivered`` for 24 h without sender confirmation (Q65);
    ``finance_review`` holds completed bookings whose commission stayed ``held`` for finance review (Q66).
    """

    AWAITING_CONFIRMATION = "awaiting_confirmation"
    NO_SHOW_REVIEW = "no_show_review"
    CUSTODY_CASE = "custody_case"
    HOLD_ESCALATION = "hold_escalation"
    FINANCE_REVIEW = "finance_review"


class CommissionReviewReason(StrEnum):
    """Why a completed booking's commission was not captured and went to the finance queue (Q66, U8)."""

    DISPUTE_MODULE_UNAVAILABLE = "dispute_module_unavailable"
    # wave 3.1 (0062): a blocking dispute was resolved after completion, so finance decides with finalize_fee.
    DISPUTE_RESOLVED = "dispute_resolved"
    # Q144 (ADR-0026, 0093): a parcel completed by staff while the completion rule (D-1) is open - finance captures
    PARCEL_STAFF_COMPLETION = "parcel_staff_completion"


# --- wave 3 (16.09.2026): tracking (A6), communications (A7), trust & support (A12), feed (A5) -----------------


# --- wave 4 (16.09.2026): operations and growth (A13) ------------------------------------------------------------


class ShareLinkChannel(StrEnum):
    """O1 (§20.2). The channel only picks the share text; nothing is posted anywhere on the user's behalf."""

    TELEGRAM = "telegram"
    GENERIC = "generic"


class OpsQueue(StrEnum):
    """O4 operator queues, aggregated from the owning modules (no queue table of its own, §16)."""

    AWAITING_CONFIRMATION = "awaiting_confirmation"  # A4 bookings
    NO_SHOW_REVIEW = "no_show_review"  # A4
    CUSTODY_CASE = "custody_case"  # A4
    HOLD_ESCALATION = "hold_escalation"  # A4
    FINANCE_REVIEW = "finance_review"  # A4 (Q66/Q84)
    DISPUTE = "dispute"  # A12 open / under review
    SUPPORT_TICKET = "support_ticket"  # A12 open tickets and SOS
    SUPPORT_THREAD = "support_thread"  # ADR-0026 (Q141): open booking-bound operator chats
    TRUST_REVIEW = "trust_review"  # A12 Q45 review queue
    # wave 6 (§16 operator panel): the three lists the spec names that had no queue yet. All read-only views of
    # existing rows - the operator acts through the owning module's own command, never from the queue itself.
    UNANSWERED_LISTING = "unanswered_listing"  # published, departure close, still without a single proposal
    STALE_TRACKING = "stale_tracking"  # running trip whose last GPS point is older than the delayed threshold
    INELIGIBLE_DRIVER_TRIP = "ineligible_driver_trip"  # trip near departure whose driver is no longer eligible


class KpiMetric(StrEnum):
    """§20.4 daily metrics. Only metrics this system really measures are listed; a metric we cannot compute
    honestly (e.g. ``search_with_match_rate`` - feed searches are not logged) is absent, never zero."""

    LISTINGS_PUBLISHED = "listings_published"
    LISTING_TO_BOOKING = "listing_to_booking"
    OFFER_WITHIN_TARGET = "offer_within_target"  # listings with a valid proposal inside OFFER_TARGET (>= 70 %)
    BOOKING_COMPLETION = "booking_completion"  # completed / confirmed bookings (>= 90 %)
    DRIVER_FAULT_CANCEL = "driver_fault_cancel"  # driver-fault cancellations / confirmed bookings (<= 5 %)
    REPEAT_CLIENT = "repeat_client"  # clients with more than one booking / clients with a booking
    # wave 6: measurable once the feed counts its searches (§20.4) and once the first offer is timed.
    SEARCH_WITH_MATCH_RATE = "search_with_match_rate"  # searches that found something / searches
    TIME_TO_FIRST_VALID_OFFER = "time_to_first_valid_offer"  # mean seconds to the first proposal (not a ratio)
    # wave 7: measurable from the confirmed route distance and from the ledger.
    BOOKED_SEAT_KM_RATIO = "booked_seat_km_ratio"  # booked seat-metres / offered seat-metres
    SEAT_KM_ROUTE_COVERAGE = "seat_km_route_coverage"  # trips with a usable distance / eligible trips
    NET_COMMISSION_PER_CORRIDOR = "net_commission_per_corridor"  # captured minus reversed, in minor units


class TrackingEvidenceReason(StrEnum):
    """Why raw GPS of a trip is kept past the 7-day retention (M1, migration 0063)."""

    DISPUTE = "dispute"


class TrackingEvidenceSource(StrEnum):
    """The kind of business row that holds the evidence (``source_type``; no FK across modules)."""

    DISPUTE = "dispute"


class ClientPlatform(StrEnum):
    """Device platform of a tracking session (K1) or push device (N2). Web/PWA is never a background tracker (§10.5)."""

    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class TrackingWindowReason(StrEnum):
    """Why live location is (not) visible for a booking (``app.contracts.tracking.tracking_window``; §10.6, AC44)."""

    OPEN = "open"
    NOT_YET_OPEN = "not_yet_open"  # passenger: more than 30 min before pickup
    PARCEL_NOT_PICKED_UP = "parcel_not_picked_up"  # parcel: from pickup until delivery only
    BOOKING_FINISHED = "booking_finished"  # arrived/delivered/terminal
    TRIP_FINISHED = "trip_finished"  # trip completed/cancelled


class TrackingQualityFlag(StrEnum):
    """``tracking_points.quality_flags`` (§10.4). A flagged point is stored; only trusted points move the marker."""

    LOW_ACCURACY = "low_accuracy"  # accuracy_m > LOW_ACCURACY_THRESHOLD_M (still trusted, shown as low confidence)
    MOCK_LOCATION = "mock_location"  # not trusted
    IMPLAUSIBLE_SPEED = "implausible_speed"  # not trusted
    OUT_OF_ORDER = "out_of_order"  # older than the live point: history only (AC28)


class TrackingPointRejectReason(StrEnum):
    """``PointsBatchAck.rejected[].reason`` (K2)."""

    TOO_OLD = "too_old"  # > tracking.MAX_POINT_AGE
    FUTURE_TIMESTAMP = "future_timestamp"  # > tracking.MAX_FUTURE_SKEW ahead of the server clock
    INVALID = "invalid"
    PAYLOAD_CONFLICT = "payload_conflict"  # same (session, seq) with a different payload hash


class TrackingGrantScope(StrEnum):
    RECIPIENT_LINK = "recipient_link"


class ChatThreadKind(StrEnum):
    PROPOSAL = "proposal"  # proposal thread chat, read-only once the thread is no longer open
    BOOKING = "booking"


class ChatModerationStatus(StrEnum):
    VISIBLE = "visible"  # contact info is already masked at write time (Q43)
    HIDDEN_BY_STAFF = "hidden_by_staff"


class QuickReplyCode(StrEnum):
    """§16 / ADR-0020 quick replies. A quick reply never changes agreed terms (§16)."""

    PRICE_AGREED = "price_agreed"  # "Narxga roziman" - not an accept
    CLARIFY_STOP = "clarify_stop"  # "Bekatni aniqlashtirish"
    ARRIVING_IN_5_MIN = "arriving_in_5_min"  # "5 daqiqada yetaman"
    AT_STOP = "at_stop"  # "Bekatdaman"


class NotificationChannel(StrEnum):
    """ADR-0012 §9. Real push providers need a dependency decision (WAVE1_CARDS "Wave 3", U3)."""

    IN_APP = "in_app"
    WEB_PUSH = "web_push"
    FCM = "fcm"


class NotificationDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"  # will retry (communications.OUTBOX_RETRY_SCHEDULE)
    DEAD = "dead"  # attempts exhausted
    SKIPPED = "skipped"  # audience refused, no device/consent, or no longer relevant (expired/cancelled listing)


class FeedSide(StrEnum):
    REQUESTS = "requests"
    OFFERS = "offers"


class FeedSort(StrEnum):
    RECOMMENDED = "recommended"
    CHEAPEST = "cheapest"
    TIME = "time"
    RATING = "rating"


class MatchGroup(StrEnum):
    PRIMARY = "primary"
    ALTERNATIVE = "alternative"


class ReputationLabel(StrEnum):
    """S2: a driver without ratings is "new, documents verified" - never an artificial 4.5 (§8.2)."""

    NEW_VERIFIED = "new_verified"
    RATED = "rated"


class RatingBucket(StrEnum):
    """U6 (user decision 17.09.2026, option A): the short trust signal a client sees on a competing offer.

    A *group*, never a number: one five-star rating must not look like two hundred of them (§8.2). The count of
    ratings is always shown next to it, and a driver with too few ratings is "new", not "average" and not zero.
    """

    NEW_VERIFIED = "new_verified"  # fewer than RATING_BUCKET_MIN_COUNT ratings - no judgement, no invented score
    GOOD = "good"
    MIXED = "mixed"
    LOW = "low"


class DisputeResolutionCode(StrEnum):
    """S8 ``resolve``. The code only records the decision; money/service changes are separate commands (§11)."""

    SERVICE_CONFIRMED = "service_confirmed"
    SERVICE_NOT_PROVIDED = "service_not_provided"
    PAID_CONFIRMED = "paid_confirmed"
    UNPAID_CONFIRMED = "unpaid_confirmed"
    COMMISSION_ADJUSTED = "commission_adjusted"
    NO_ACTION = "no_action"
    OTHER = "other"


class TrustSignalType(StrEnum):
    """Q45 operator review queue signals (A12). No automatic ban or fine in the pilot."""

    CONTACT_FILTER_STRIKES = "contact_filter_strikes"
    QUICK_CANCEL_AFTER_CHAT = "quick_cancel_after_chat"
    REPEATED_PAIR_CANCELLATIONS = "repeated_pair_cancellations"


class TrustReviewStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    DISMISSED = "dismissed"
    ACTIONED = "actioned"


class ReportSubjectType(StrEnum):
    """S11 (§17.3). What a report is about; the id is always the subject's public id."""

    USER = "user"
    LISTING = "listing"
    BOOKING = "booking"
    CHAT_MESSAGE = "chat_message"


class ReportReasonCode(StrEnum):
    """S11 reason codes. A free-text ``details`` may add context, but the code is what the queue sorts on."""

    OFF_PLATFORM_CONTACT = "off_platform_contact"
    FRAUD_SUSPICION = "fraud_suspicion"
    UNSAFE_BEHAVIOUR = "unsafe_behaviour"
    NO_SHOW = "no_show"
    PRICE_PRESSURE = "price_pressure"
    PROHIBITED_ITEM = "prohibited_item"
    HARASSMENT = "harassment"
    OTHER = "other"


class ReportStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    DISMISSED = "dismissed"
    ACTIONED = "actioned"


class FraudSignalType(StrEnum):
    """§17.3 signals. Each one is a *question for a human*, never an automatic judgement."""

    SHARED_DEVICE_ACCOUNTS = "shared_device_accounts"  # several accounts push-registered from one device
    SELF_DEALING_DEVICE = "self_dealing_device"  # the client and the driver of one booking share a device
    REPEATED_PAIR_BOOKINGS = "repeated_pair_bookings"  # the same pair keeps booking each other


class FraudSignalStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    DISMISSED = "dismissed"
    CONFIRMED = "confirmed"


class TrustReviewDecision(StrEnum):
    NO_VIOLATION = "no_violation"  # dismiss
    WARNING_ISSUED = "warning_issued"  # action: in-app warning (trust.warning_issued)
    ESCALATED_TO_ADMIN = "escalated_to_admin"  # action: an admin may block eligibility separately (I5)


class SupportTicketKind(StrEnum):
    SUPPORT = "support"
    SOS = "sos"


class SupportTicketStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


# --- Promotions & referral (ADR-0023, Q101-Q110) ---------------------------------
# Three kinds of value are never mixed: the driver's real prepaid balance (wallet
# module, real money), Passenger Bonus and Driver Credit (promotions module, rights
# to a discount - never cash, never transferable, never converted into real balance).


class PromoInstrument(StrEnum):
    PASSENGER_BONUS = "passenger_bonus"  # client's right to a cash-fare discount on a later eligible service
    DRIVER_CREDIT = "driver_credit"  # driver's right to pay less commission on a later eligible booking


class PromoCampaignKind(StrEnum):
    """What a campaign rewards. Only ``PILOT_CAMPAIGN_KINDS`` may be activated in the pilot (ADR-0023 §2)."""

    REFERRAL_CLIENT_CLIENT = "referral_client_client"
    REFERRAL_DRIVER_DRIVER = "referral_driver_driver"
    REFERRAL_DRIVER_CLIENT = "referral_driver_client"
    # extension points: the structure exists, activation is refused until a later decision
    CASHBACK = "cashback"
    REACTIVATION = "reactivation"
    CORRIDOR_BONUS = "corridor_bonus"
    LOYALTY = "loyalty"


PILOT_CAMPAIGN_KINDS: frozenset[PromoCampaignKind] = frozenset(
    {
        PromoCampaignKind.REFERRAL_CLIENT_CLIENT,
        PromoCampaignKind.REFERRAL_DRIVER_DRIVER,
        PromoCampaignKind.REFERRAL_DRIVER_CLIENT,
    }
)


class PromoCampaignFamily(StrEnum):
    """Uniqueness scope for acquisition rewards (Q106): one identity earns a family's reward once.

    Passenger and parcel referral campaigns share ``CLIENT_ACQUISITION`` so a person is a "new client" once,
    whichever service they start with. Reactivation is a separate family (it does not consume acquisition).
    """

    CLIENT_ACQUISITION = "client_acquisition"
    DRIVER_ACQUISITION = "driver_acquisition"
    REACTIVATION = "reactivation"
    LOYALTY = "loyalty"


class TripIntentStatus(StrEnum):
    """ADR-0025: a client's private, reusable trip/parcel request (never a public listing, never sent by itself)."""

    ACTIVE = "active"  # offers may be sent from it; at most one live booking can come out of it
    BOOKED = "booked"  # one offer became a booking; the other offers of this request are closed
    CLOSED = "closed"  # the client ended it; nothing is sent or accepted from it any more


class PromoCampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"  # accepts new enrollments
    PAUSED = "paused"  # no new enrollments; existing promises and granted rewards are honoured
    CLOSED = "closed"  # no new enrollments ever; existing promises and rewards are still honoured


class ReferralAttributionStatus(StrEnum):
    ATTRIBUTED = "attributed"
    QUALIFYING = "qualifying"  # a candidate event exists; risk window / checks running
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PromoEnrollmentStatus(StrEnum):
    """The promise reserve for one attribution (both sides' maximum rewards)."""

    PROMISED = "promised"
    GRANTED = "granted"  # every reward of the promise became a grant (promise -> granted reserve)
    RELEASED = "released"  # promise released back to the budget (expired / rejected / closed unmet)


class PromoRewardStatus(StrEnum):
    """One beneficiary's grant (a bonus lot). Referrer and referee rewards are separate rows."""

    PENDING_REVIEW = "pending_review"
    AVAILABLE = "available"
    EXHAUSTED = "exhausted"  # fully consumed
    EXPIRED = "expired"
    REVERSED = "reversed"


class PromoRedemptionStatus(StrEnum):
    RESERVED = "reserved"  # held for one booking inside the accept transaction
    CONSUMED = "consumed"  # the booking's commission was captured; counted as cost once
    RELEASED = "released"  # booking cancelled / not captured; amount returns to the lot


class PromoFault(StrEnum):
    """Why a reservation was released, for fair restoration (ADR-0023 §7). Q129: the *cause*, not who pressed the
    button - an operator cancel names its cause; each value holder is judged separately (``restored_expiry``)."""

    CLIENT = "client"  # the client caused it (own cancel, a client no-show confirmed by an operator)
    DRIVER = "driver"  # the driver caused it
    PLATFORM = "platform"  # the platform caused it (system failure, service withdrawn) - a decided cause
    NONE = "none"  # justified, nobody at fault (e.g. road closure recorded by an operator)
    UNDETERMINED = "undetermined"  # cause not decided or disputed: nobody loses a right by it, a person reviews


class PromoRiskSignal(StrEnum):
    """Referral risk signals (ADR-0023 §10, Q113). Rules - source, reliability, consequence, correlation group -
    live in the versioned ``promo.RISK_RULESET_*``; a signal is evidence for a person, not a verdict."""

    SELF_REFERRAL = "self_referral"
    SELF_DEALING = "self_dealing"
    IDENTITY_KEY_MATCH = "identity_key_match"
    KYC_REUSE = "kyc_reuse"
    LINKED_REFERRAL_CLUSTER = "linked_referral_cluster"
    GPS_TIME_CONFLICT = "gps_time_conflict"
    SPLIT_SHIPMENT = "split_shipment"
    SHARED_IP = "shared_ip"
    SHARED_NETWORK = "shared_network"
    SHARED_DEVICE = "shared_device"
    FAMILY_VEHICLE = "family_vehicle"
    RAPID_REREGISTRATION = "rapid_reregistration"
    REPEATED_PAIR = "repeated_pair"
    IMPLAUSIBLE_SERVICE = "implausible_service"
    PRICE_INFLATION = "price_inflation"
    EVENT_REPLAY = "event_replay"


class PromoObligationStatus(StrEnum):
    """One beneficiary's promised reward: the budget reserve, then the grant (Q115)."""

    PROMISED = "promised"
    GRANTED = "granted"
    RELEASED = "released"


class PromoLedgerKind(StrEnum):
    """Immutable promo ledger movements between budget buckets (ADR-0023 §6, §8)."""

    ALLOCATE = "allocate"  # funding -> allocated
    REDUCE_ALLOCATION = "reduce_allocation"  # allocated -> funding; never below spent + obligations (G14, 0090)
    FUNDING_LOSS = "funding_loss"  # external funding really gone: may create a shortfall; cancels nothing (G14)
    PROMISE = "promise"  # available -> promised (both sides' maximum, before anything is promised)
    RELEASE_PROMISE = "release_promise"  # promised -> released (expired / rejected / unused part of a grant)
    GRANT = "grant"  # promised -> granted (a lot exists)
    CONSUME = "consume"  # granted -> consumed (a redemption was captured; counted as cost once)
    RELEASE_GRANTED = "release_granted"  # granted -> released (unspent lot value expired or reversed)
    REINSTATE = "reinstate"  # available -> granted (fair restoration of expired value; needs budget room)


class PromoBudgetRequestStatus(StrEnum):
    """Large budget changes wait for a second, different finance approver (Q17 threshold, Q114)."""

    PENDING = "pending"
    POSTED = "posted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
