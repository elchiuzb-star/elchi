"""Allowed state transitions for stage-2 aggregates (spec §11, §22).

This module encodes only *which* (from, to) pairs exist and the command name
that performs them. Guards, actors, side effects, lock order and error codes are
specified in docs/architecture/STATE_MACHINES.md and enforced in the owning
module. Every status write in a v2 module must call
:meth:`StateMachine.assert_transition`.

Deliberate absences and rules (tested in tests/contracts/test_state_machines.py):

* Parcel ``picked_up``/``in_transit`` -> ``cancelled`` does not exist (AC22).
* Passenger ``no_show`` is reachable only through the operator command
  ``confirm_no_show``; the driver's ``report_no_show`` opens a review and does
  not change the booking status (decision 7).
* Dispute resolution never writes a booking/trip status; there is no
  "restore previous status" transition anywhere (spec §11).
* Trip completion has no effect on booking status (AC42); which booking states
  still block completion is decided by :func:`booking_blocks_trip_completion`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from app.contracts.enums import (
    AmendmentStatus,
    CashCollectionStatus,
    CommissionStatus,
    CorridorRolloutState,
    CustodyCaseStatus,
    DisputeStatus,
    ListingStatus,
    NoShowReviewStatus,
    ParcelBookingStatus,
    PassengerBookingStatus,
    ProposalStatus,
    ServiceType,
    SupportTicketStatus,
    TopupStatus,
    TrackingSessionStatus,
    TripStatus,
    TrustReviewStatus,
)
from app.contracts.errors import DomainError, ErrorCode


@dataclass(frozen=True, slots=True)
class Transition:
    source: str
    target: str
    command: str


@dataclass(frozen=True)
class StateMachine:
    name: str
    states: type[StrEnum]
    initial: frozenset[str]
    transitions: tuple[Transition, ...]

    def __post_init__(self) -> None:
        values = {state.value for state in self.states}
        for state in self.initial:
            if state not in values:
                raise ValueError(f"{self.name}: unknown initial state {state}")
        for transition in self.transitions:
            if transition.source not in values or transition.target not in values:
                raise ValueError(f"{self.name}: unknown state in {transition}")

    @property
    def terminal(self) -> frozenset[str]:
        exits = {t.source for t in self.transitions if t.source != t.target}
        return frozenset(state.value for state in self.states if state.value not in exits)

    def is_allowed(self, source: str, target: str) -> bool:
        return any(t.source == source and t.target == target for t in self.transitions)

    def is_allowed_by(self, source: str, target: str, command: str) -> bool:
        return any(t.source == source and t.target == target and t.command == command for t in self.transitions)

    def commands_from(self, source: str) -> frozenset[str]:
        return frozenset(t.command for t in self.transitions if t.source == source)

    def assert_transition(self, source: str, target: str, command: str | None = None) -> None:
        allowed = self.is_allowed(source, target) if command is None else self.is_allowed_by(source, target, command)
        if not allowed:
            raise DomainError(
                ErrorCode.INVALID_STATE_TRANSITION,
                details={"machine": self.name, "from": str(source), "to": str(target), "command": command},
            )


def _t(source: StrEnum, target: StrEnum, command: str) -> Transition:
    return Transition(source.value, target.value, command)


L = ListingStatus
LISTING = StateMachine(
    name="listing",
    states=ListingStatus,
    initial=frozenset({L.DRAFT.value}),
    transitions=(
        _t(L.DRAFT, L.PUBLISHED, "publish"),
        _t(L.DRAFT, L.CANCELLED, "cancel"),
        _t(L.PUBLISHED, L.PAUSED, "pause"),
        _t(L.PAUSED, L.PUBLISHED, "resume"),
        _t(L.PUBLISHED, L.FULFILLED, "system_fulfil"),
        _t(L.FULFILLED, L.PUBLISHED, "system_reopen"),
        _t(L.PUBLISHED, L.EXPIRED, "system_expire"),
        _t(L.PAUSED, L.EXPIRED, "system_expire"),
        _t(L.FULFILLED, L.EXPIRED, "system_expire"),
        _t(L.PUBLISHED, L.CANCELLED, "cancel"),
        _t(L.PAUSED, L.CANCELLED, "cancel"),
        _t(L.FULFILLED, L.CANCELLED, "cancel"),
    ),
)

P = ProposalStatus
PROPOSAL_VERSION = StateMachine(
    name="proposal_version",
    states=ProposalStatus,
    initial=frozenset({P.ACTIVE.value}),
    transitions=(
        _t(P.ACTIVE, P.SUPERSEDED, "counter"),
        _t(P.ACTIVE, P.ACCEPTED, "accept"),
        _t(P.ACTIVE, P.REJECTED, "reject"),
        _t(P.ACTIVE, P.WITHDRAWN, "withdraw"),
        _t(P.ACTIVE, P.EXPIRED, "system_expire"),
    ),
)

TR = TripStatus
TRIP = StateMachine(
    name="trip",
    states=TripStatus,
    initial=frozenset({TR.PLANNED.value}),
    transitions=(
        _t(TR.PLANNED, TR.BOARDING, "start_boarding"),
        _t(TR.PLANNED, TR.CANCELLED, "cancel"),
        _t(TR.BOARDING, TR.IN_PROGRESS, "depart"),
        _t(TR.BOARDING, TR.CANCELLED, "cancel"),
        _t(TR.BOARDING, TR.INTERRUPTED, "interrupt"),
        _t(TR.IN_PROGRESS, TR.COMPLETED, "complete"),
        _t(TR.IN_PROGRESS, TR.INTERRUPTED, "interrupt"),
        _t(TR.INTERRUPTED, TR.IN_PROGRESS, "resume"),
        _t(TR.INTERRUPTED, TR.COMPLETED, "complete"),
        _t(TR.INTERRUPTED, TR.CANCELLED, "cancel"),
    ),
)

PB = PassengerBookingStatus
PASSENGER_BOOKING = StateMachine(
    name="passenger_booking",
    states=PassengerBookingStatus,
    initial=frozenset({PB.CONFIRMED.value}),
    transitions=(
        _t(PB.CONFIRMED, PB.AWAITING_PICKUP, "mark_awaiting_pickup"),
        _t(PB.CONFIRMED, PB.CANCELLED, "cancel"),
        _t(PB.AWAITING_PICKUP, PB.ONBOARD, "board"),
        # Operator-only; the driver's report_no_show opens NO_SHOW_REVIEW instead.
        _t(PB.AWAITING_PICKUP, PB.NO_SHOW, "confirm_no_show"),
        _t(PB.AWAITING_PICKUP, PB.CANCELLED, "cancel"),
        # N3: operator rejects the no-show after the trip is terminal -> the booking is
        # cancelled in the same command with driver fault recorded.
        _t(PB.AWAITING_PICKUP, PB.CANCELLED, "reject_no_show"),
        _t(PB.ONBOARD, PB.ARRIVED, "drop_off"),
        _t(PB.ARRIVED, PB.COMPLETED, "complete"),
        # Wave 2.1: operator B13 command after the 24 h confirmation window (was missing: A4 already used it).
        _t(PB.ARRIVED, PB.COMPLETED, "complete_with_evidence"),
    ),
)

NS = NoShowReviewStatus
NO_SHOW_REVIEW = StateMachine(
    name="no_show_review",
    states=NoShowReviewStatus,
    # Created in `pending` by the driver's report_no_show action.
    initial=frozenset({NS.PENDING.value}),
    transitions=(
        _t(NS.PENDING, NS.CONFIRMED, "confirm_no_show"),
        _t(NS.PENDING, NS.REJECTED, "reject_no_show"),
        _t(NS.PENDING, NS.REJECTED, "system_close_boarded"),
    ),
)

PC = ParcelBookingStatus
PARCEL_BOOKING = StateMachine(
    name="parcel_booking",
    states=ParcelBookingStatus,
    initial=frozenset({PC.CONFIRMED.value}),
    transitions=(
        _t(PC.CONFIRMED, PC.AWAITING_PICKUP, "mark_awaiting_pickup"),
        _t(PC.CONFIRMED, PC.CANCELLED, "cancel"),
        _t(PC.AWAITING_PICKUP, PC.CANCELLED, "cancel"),
        _t(PC.AWAITING_PICKUP, PC.PICKED_UP, "pick_up"),
        _t(PC.PICKED_UP, PC.IN_TRANSIT, "start_transit"),
        _t(PC.PICKED_UP, PC.RETURN_REQUIRED, "require_return"),
        _t(PC.IN_TRANSIT, PC.DELIVERED, "deliver"),
        _t(PC.IN_TRANSIT, PC.DELIVERY_FAILED, "report_delivery_failed"),
        _t(PC.IN_TRANSIT, PC.RETURN_REQUIRED, "require_return"),
        _t(PC.DELIVERY_FAILED, PC.IN_TRANSIT, "retry_delivery"),
        _t(PC.DELIVERY_FAILED, PC.RETURN_REQUIRED, "require_return"),
        _t(PC.RETURN_REQUIRED, PC.RETURNED, "return_to_sender"),
        # Q65 (wave 2.1): `deliver` no longer completes in the same transaction. The sender confirms (`complete`,
        # C) or, DELIVERED_OPERATOR_QUEUE_AFTER later, the booking enters the operator queue and staff complete
        # it with evidence.
        _t(PC.DELIVERED, PC.COMPLETED, "complete"),
        _t(PC.DELIVERED, PC.COMPLETED, "complete_with_evidence"),
    ),
)

CC = CustodyCaseStatus
CUSTODY_CASE = StateMachine(
    name="custody_case",
    states=CustodyCaseStatus,
    # Opened by the system in the same transaction as report_delivery_failed / require_return.
    initial=frozenset({CC.OPEN.value}),
    transitions=(_t(CC.OPEN, CC.RESOLVED, "resolve_custody_case"),),
)

C = CashCollectionStatus
CASH_COLLECTION = StateMachine(
    name="cash_collection",
    states=CashCollectionStatus,
    initial=frozenset({C.UNPAID.value}),
    transitions=(
        _t(C.UNPAID, C.REPORTED_PAID, "report_paid"),
        _t(C.REPORTED_PAID, C.ACKNOWLEDGED, "acknowledge"),
        _t(C.REPORTED_PAID, C.CONTESTED, "contest"),
        _t(C.CONTESTED, C.ACKNOWLEDGED, "resolve_paid"),
        _t(C.CONTESTED, C.UNPAID, "resolve_unpaid"),
    ),
)

CM = CommissionStatus
COMMISSION = StateMachine(
    name="commission",
    states=CommissionStatus,
    # Created directly in one of these states inside the accept transaction:
    # `exempt` only when the snapshotted policy is a 0 bps campaign (decision 1).
    initial=frozenset({CM.EXEMPT.value, CM.HELD.value}),
    transitions=(
        _t(CM.HELD, CM.HELD, "adjust_hold"),
        _t(CM.HELD, CM.CAPTURED, "capture"),
        _t(CM.HELD, CM.RELEASED, "release"),
        _t(CM.CAPTURED, CM.PARTIALLY_REVERSED, "reverse_partial"),
        _t(CM.CAPTURED, CM.REVERSED, "reverse"),
        _t(CM.PARTIALLY_REVERSED, CM.PARTIALLY_REVERSED, "reverse_partial"),
        _t(CM.PARTIALLY_REVERSED, CM.REVERSED, "reverse"),
    ),
)

D = DisputeStatus
DISPUTE = StateMachine(
    name="dispute",
    states=DisputeStatus,
    initial=frozenset({D.OPEN.value}),
    transitions=(
        _t(D.OPEN, D.UNDER_REVIEW, "start_review"),
        _t(D.OPEN, D.RESOLVED, "resolve"),
        _t(D.OPEN, D.REJECTED, "reject"),
        _t(D.UNDER_REVIEW, D.RESOLVED, "resolve"),
        _t(D.UNDER_REVIEW, D.REJECTED, "reject"),
    ),
)

A = AmendmentStatus
AMENDMENT = StateMachine(
    name="amendment",
    states=AmendmentStatus,
    initial=frozenset({A.PROPOSED.value}),
    transitions=(
        _t(A.PROPOSED, A.ACCEPTED, "accept"),
        _t(A.PROPOSED, A.REJECTED, "reject"),
        _t(A.PROPOSED, A.WITHDRAWN, "withdraw"),
        _t(A.PROPOSED, A.EXPIRED, "system_expire"),
    ),
)

TP = TopupStatus
TOPUP = StateMachine(
    name="topup",
    states=TopupStatus,
    initial=frozenset({TP.PENDING.value}),
    transitions=(
        _t(TP.PENDING, TP.APPROVED, "approve"),
        _t(TP.PENDING, TP.AWAITING_SECOND_APPROVAL, "approve_first"),
        _t(TP.AWAITING_SECOND_APPROVAL, TP.APPROVED, "approve_second"),
        _t(TP.PENDING, TP.REJECTED, "reject"),
        _t(TP.AWAITING_SECOND_APPROVAL, TP.REJECTED, "reject"),
    ),
)

TS = TrackingSessionStatus
TRACKING_SESSION = StateMachine(
    name="tracking_session",
    states=TrackingSessionStatus,
    initial=frozenset({TS.ACTIVE.value}),
    transitions=(
        _t(TS.ACTIVE, TS.SUPERSEDED, "supersede"),
        _t(TS.ACTIVE, TS.CLOSED, "close"),
    ),
)

CR = CorridorRolloutState
CORRIDOR_ROLLOUT = StateMachine(
    name="corridor_rollout",
    states=CorridorRolloutState,
    initial=frozenset({CR.DRAFT.value}),
    transitions=(
        _t(CR.DRAFT, CR.INTERNAL, "start_internal"),
        _t(CR.DRAFT, CR.CLOSED, "close"),
        _t(CR.INTERNAL, CR.DRAFT, "return_to_draft"),
        _t(CR.INTERNAL, CR.PILOT, "start_pilot"),
        _t(CR.INTERNAL, CR.CLOSED, "close"),
        _t(CR.PILOT, CR.INTERNAL, "return_to_internal"),
        _t(CR.PILOT, CR.ACTIVE, "activate"),
        _t(CR.PILOT, CR.CLOSED, "close"),
        _t(CR.ACTIVE, CR.PILOT, "return_to_pilot"),
        _t(CR.ACTIVE, CR.CLOSED, "close"),
    ),
)

# Wave 3 (A12, Q45): operator review of trust signals. No automatic ban/fine; `action` records a warning or an
# escalation (an admin blocks eligibility separately through I5).
TRV = TrustReviewStatus
TRUST_REVIEW = StateMachine(
    name="trust_review",
    states=TrustReviewStatus,
    initial=frozenset({TRV.OPEN.value}),
    transitions=(
        _t(TRV.OPEN, TRV.UNDER_REVIEW, "start_review"),
        _t(TRV.OPEN, TRV.DISMISSED, "dismiss"),
        _t(TRV.OPEN, TRV.ACTIONED, "action"),
        _t(TRV.UNDER_REVIEW, TRV.DISMISSED, "dismiss"),
        _t(TRV.UNDER_REVIEW, TRV.ACTIONED, "action"),
    ),
)

# Wave 3 (A12, §16): support and SOS tickets. Acknowledging promises no response time (no 24/7 promise).
ST = SupportTicketStatus
SUPPORT_TICKET = StateMachine(
    name="support_ticket",
    states=SupportTicketStatus,
    initial=frozenset({ST.OPEN.value}),
    transitions=(
        _t(ST.OPEN, ST.ACKNOWLEDGED, "acknowledge"),
        _t(ST.OPEN, ST.RESOLVED, "resolve"),
        _t(ST.ACKNOWLEDGED, ST.RESOLVED, "resolve"),
    ),
)

ALL_MACHINES: tuple[StateMachine, ...] = (
    CORRIDOR_ROLLOUT,
    LISTING,
    PROPOSAL_VERSION,
    TRIP,
    PASSENGER_BOOKING,
    NO_SHOW_REVIEW,
    PARCEL_BOOKING,
    CUSTODY_CASE,
    CASH_COLLECTION,
    COMMISSION,
    DISPUTE,
    AMENDMENT,
    TOPUP,
    TRACKING_SESSION,
    TRUST_REVIEW,
    SUPPORT_TICKET,
)


# --- reject_no_show outcome (Q7, N3) ---------------------------------------------

TRIP_TERMINAL_STATUSES: frozenset[str] = frozenset({TR.COMPLETED.value, TR.CANCELLED.value})


@dataclass(frozen=True, slots=True)
class RejectNoShowOutcome:
    booking_status: str
    fault_side: str | None  # FaultSide value when the booking is cancelled


def reject_no_show_outcome(trip_status: TripStatus | str) -> RejectNoShowOutcome:
    """Result of the operator's ``reject_no_show`` for a passenger booking.

    Trip still running: booking stays ``awaiting_pickup`` (can board or be cancelled).
    Trip terminal: nobody can board any more, so the booking is cancelled in the same
    command with driver fault recorded (the driver's no-show claim was rejected).
    """
    from app.contracts.enums import FaultSide

    status = TripStatus(trip_status).value
    if status in TRIP_TERMINAL_STATUSES:
        return RejectNoShowOutcome(PB.CANCELLED.value, FaultSide.DRIVER.value)
    return RejectNoShowOutcome(PB.AWAITING_PICKUP.value, None)


# --- Trip completion guard (AC42, D1) -------------------------------------------

PASSENGER_SETTLED_FOR_TRIP: frozenset[str] = frozenset(
    {PB.ARRIVED.value, PB.COMPLETED.value, PB.CANCELLED.value, PB.NO_SHOW.value}
)
PARCEL_SETTLED_FOR_TRIP: frozenset[str] = frozenset(
    {PC.DELIVERED.value, PC.COMPLETED.value, PC.CANCELLED.value, PC.RETURNED.value}
)
# Still-open bookings that do not block trip completion because an operator case owns them.
PARCEL_OPEN_WITH_CUSTODY_CASE: frozenset[str] = frozenset({PC.DELIVERY_FAILED.value, PC.RETURN_REQUIRED.value})
PASSENGER_OPEN_WITH_NO_SHOW_REVIEW: frozenset[str] = frozenset({PB.AWAITING_PICKUP.value})


def booking_blocks_trip_completion(
    service_type: ServiceType | str,
    service_status: str,
    *,
    has_open_custody_case: bool = False,
    has_pending_no_show_review: bool = False,
) -> bool:
    """True if this booking prevents ``trip.complete``.

    Completing the trip never changes booking status (AC42). Bookings in
    ``delivery_failed``/``return_required`` with an open custody case, or a
    passenger in ``awaiting_pickup`` with a pending no-show review, stay open
    after the trip completes; the trip then leaves the overlap constraint.
    """
    service = ServiceType(service_type)
    if service is ServiceType.PASSENGER:
        if service_status in PASSENGER_SETTLED_FOR_TRIP:
            return False
        return not (service_status in PASSENGER_OPEN_WITH_NO_SHOW_REVIEW and has_pending_no_show_review)
    if service_status in PARCEL_SETTLED_FOR_TRIP:
        return False
    return not (service_status in PARCEL_OPEN_WITH_CUSTODY_CASE and has_open_custody_case)


# --- Wave 2.1: service start needs a started trip; trip cancel guard (BR blockers 4, 5) --------------------------

# `board` / `pick_up` only while the trip is boarding or on the way (intermediate pickups); never on a `planned`
# trip (-> 409 TRIP_NOT_STARTED). `mark_awaiting_pickup` may still happen on a planned trip.
TRIP_STATUSES_ALLOWING_SERVICE_START: frozenset[str] = frozenset({TR.BOARDING.value, TR.IN_PROGRESS.value})


def service_start_allowed(trip_status: TripStatus | str) -> bool:
    return TripStatus(trip_status).value in TRIP_STATUSES_ALLOWING_SERVICE_START


# A person or parcel is (or was just) in the vehicle: trip `cancel` is refused from ANY trip status
# (409 TRIP_HAS_UNRESOLVED_BOOKINGS, details.bookings[]); operators use interrupt/custody/return flows instead.
PASSENGER_BLOCKS_TRIP_CANCEL: frozenset[str] = frozenset({PB.ONBOARD.value, PB.ARRIVED.value})
PARCEL_BLOCKS_TRIP_CANCEL: frozenset[str] = frozenset(
    {PC.PICKED_UP.value, PC.IN_TRANSIT.value, PC.DELIVERY_FAILED.value, PC.RETURN_REQUIRED.value}
)


def booking_blocks_trip_cancel(service_type: ServiceType | str, service_status: str) -> bool:
    if ServiceType(service_type) is ServiceType.PASSENGER:
        return service_status in PASSENGER_BLOCKS_TRIP_CANCEL
    return service_status in PARCEL_BLOCKS_TRIP_CANCEL


# Q19/Q7: a trip cancel never decides a pending no-show review. While any booking of the trip has a pending review
# the trip cancel is refused with 409 NO_SHOW_REVIEW_PENDING (details.bookings[]); the operator decides the review
# first (confirm_no_show / reject_no_show), then cancels. The review machine has no trip-cancel command.
TRIP_CANCEL_REFUSED_WITH_PENDING_NO_SHOW_REVIEW = True

# Q65: a `delivered` parcel without sender confirmation enters the operator queue (awaiting_confirmation) after this.
DELIVERED_OPERATOR_QUEUE_AFTER = timedelta(hours=24)
