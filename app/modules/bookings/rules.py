"""Pure booking rules (spec §9.5, §10.6, §11; STATE_MACHINES §3.1-§7, §9; Q7, Q19, Q44, N3). No I/O.

Everything here is deterministic and unit-tested (tests/modules/bookings). The service module gathers the
facts under the locks of ADR-0017 and calls these functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.contracts.enums import (
    ActorSide,
    BookingAction,
    FaultSide,
    ParcelBookingStatus,
    PassengerBookingStatus,
    ProofKind,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.state_machines import PARCEL_BOOKING, PASSENGER_BOOKING, StateMachine
from app.contracts.timeutil import ensure_aware_utc

PB = PassengerBookingStatus
PC = ParcelBookingStatus

# --- pilot configuration (spec §9.5, §10.6, Q19, Q44) ------------------------------------------------------
BOARDING_WINDOW = timedelta(minutes=60)  # Q19: trip start_boarding opens 60 min before planned start
CONTACT_HIDE_AFTER_TERMINAL = timedelta(hours=24)  # Q44
CONFIRMATION_WINDOW = timedelta(hours=24)  # §9.5: client confirmation, then operator queue
HOLD_ESCALATION_AFTER = timedelta(hours=48)  # §9.5 (A3 sets wallet_holds.escalate_at)
MAX_PROOF_ATTEMPTS = 5  # §11, ADR-0018 (DB CHECK failed_attempts <= 5)
CANCELLATION_POLICY = "pilot_no_penalty_v1"  # §9.5: pilot cancellation penalty is 0
# User-facing copy: the apps show it as it comes, so it is written in the product language (Uzbek), not English.
# The same sentence reaches the client and the driver, so it says nothing about the commission hold (Q16): the
# driver sees the hold being released in their own wallet screens.
CANCELLATION_POLICY_SUMMARY = (
    "Pilotda bekor qilish uchun jarima yo'q; xizmat boshlanishidan oldin bekor qilinsa o'rin bo'shaydi."
)

SERVICE_MACHINES: dict[ServiceType, StateMachine] = {
    ServiceType.PASSENGER: PASSENGER_BOOKING,
    ServiceType.PARCEL: PARCEL_BOOKING,
}

TERMINAL_SERVICE_STATUSES: frozenset[str] = frozenset(
    {PB.COMPLETED.value, PB.CANCELLED.value, PB.NO_SHOW.value, PC.RETURNED.value}
)
# Statuses at which the service has started (Q44: phones revealed from here on).
STARTED_STATUSES: dict[ServiceType, frozenset[str]] = {
    ServiceType.PASSENGER: frozenset({PB.ONBOARD.value, PB.ARRIVED.value, PB.COMPLETED.value}),
    ServiceType.PARCEL: frozenset(
        {
            PC.PICKED_UP.value,
            PC.IN_TRANSIT.value,
            PC.DELIVERED.value,
            PC.DELIVERY_FAILED.value,
            PC.RETURN_REQUIRED.value,
            PC.RETURNED.value,
            PC.COMPLETED.value,
        }
    ),
}
PRE_SERVICE_STATUSES: frozenset[str] = frozenset({PB.CONFIRMED.value, PB.AWAITING_PICKUP.value})
# AC22: a parcel in the driver's custody can never be plainly cancelled.
PARCEL_CUSTODY_STATUSES: frozenset[str] = frozenset(
    {PC.PICKED_UP.value, PC.IN_TRANSIT.value, PC.DELIVERY_FAILED.value, PC.RETURN_REQUIRED.value}
)
# Service outcomes after which the commission may be finalized (captured or released) by an operator.
FEE_FINALIZABLE_STATUSES: frozenset[str] = frozenset(
    {PB.ARRIVED.value, PB.COMPLETED.value, PC.DELIVERED.value, PC.RETURNED.value, PB.NO_SHOW.value}
)

# Participant actions: which side may run them (STATE_MACHINES §4-§5).
ACTION_SIDES: dict[BookingAction, frozenset[ActorSide]] = {
    BookingAction.MARK_AWAITING_PICKUP: frozenset({ActorSide.DRIVER}),
    BookingAction.ARRIVE_AT_PICKUP: frozenset({ActorSide.DRIVER}),
    BookingAction.BOARD: frozenset({ActorSide.DRIVER}),
    BookingAction.DROP_OFF: frozenset({ActorSide.DRIVER}),
    BookingAction.REPORT_NO_SHOW: frozenset({ActorSide.DRIVER}),
    BookingAction.PICK_UP: frozenset({ActorSide.DRIVER}),
    BookingAction.START_TRANSIT: frozenset({ActorSide.DRIVER}),
    BookingAction.DELIVER: frozenset({ActorSide.DRIVER}),
    BookingAction.REPORT_DELIVERY_FAILED: frozenset({ActorSide.DRIVER}),
    BookingAction.RETRY_DELIVERY: frozenset({ActorSide.DRIVER}),
    BookingAction.RETURN_TO_SENDER: frozenset({ActorSide.DRIVER}),
    BookingAction.COMPLETE: frozenset({ActorSide.CLIENT}),
}
ACTION_SERVICES: dict[BookingAction, frozenset[ServiceType]] = {
    BookingAction.MARK_AWAITING_PICKUP: frozenset({ServiceType.PASSENGER, ServiceType.PARCEL}),
    BookingAction.ARRIVE_AT_PICKUP: frozenset({ServiceType.PASSENGER, ServiceType.PARCEL}),
    # Q139 (ADR-0026): the sender no longer confirms a parcel ("qabul qilindi"); only the passenger completes.
    BookingAction.COMPLETE: frozenset({ServiceType.PASSENGER}),
    BookingAction.BOARD: frozenset({ServiceType.PASSENGER}),
    BookingAction.DROP_OFF: frozenset({ServiceType.PASSENGER}),
    BookingAction.REPORT_NO_SHOW: frozenset({ServiceType.PASSENGER}),
    # Q139: the driver's parcel ladder (picked up / in transit / delivered / failed / retry / returned) is retired.
    # The parcel goes on the way with the trip (system) and its outcome is an operator record (B13).
    BookingAction.PICK_UP: frozenset(),
    BookingAction.START_TRANSIT: frozenset(),
    BookingAction.DELIVER: frozenset(),
    BookingAction.REPORT_DELIVERY_FAILED: frozenset(),
    BookingAction.RETRY_DELIVERY: frozenset(),
    BookingAction.RETURN_TO_SENDER: frozenset(),
}
# Actions that need a code from the other party (spec §11: codes are separate per action).
# Q139 (ADR-0026): parcel codes are retired; the passenger boarding code stays.
ACTION_PROOF_KIND: dict[BookingAction, ProofKind] = {
    BookingAction.BOARD: ProofKind.BOARDING_CODE,
}
# Codes shown to the code owner (B5). The driver never sees any of them.
CLIENT_CODE_KINDS: dict[ServiceType, tuple[ProofKind, ...]] = {
    ServiceType.PASSENGER: (ProofKind.BOARDING_CODE,),
    # Q139 (ADR-0026): a parcel carries no codes (legacy rows keep theirs in the table, never shown or asked for).
    ServiceType.PARCEL: (),
}


def service_machine(service_type: ServiceType | str) -> StateMachine:
    return SERVICE_MACHINES[ServiceType(service_type)]


def is_terminal_service_status(status: str) -> bool:
    return status in TERMINAL_SERVICE_STATUSES


def has_started(service_type: ServiceType | str, status: str) -> bool:
    return status in STARTED_STATUSES[ServiceType(service_type)]


def action_target(service_type: ServiceType | str, action: BookingAction, current: str) -> str | None:
    """Target status of a status-changing participant action, ``None`` for signal-only actions."""
    service = ServiceType(service_type)
    action = BookingAction(action)
    if action in (BookingAction.ARRIVE_AT_PICKUP, BookingAction.REPORT_NO_SHOW):
        return None
    targets: dict[BookingAction, str] = {
        BookingAction.MARK_AWAITING_PICKUP: PB.AWAITING_PICKUP.value,
        BookingAction.BOARD: PB.ONBOARD.value,
        BookingAction.DROP_OFF: PB.ARRIVED.value,
        BookingAction.PICK_UP: PC.PICKED_UP.value,
        BookingAction.START_TRANSIT: PC.IN_TRANSIT.value,
        BookingAction.DELIVER: PC.DELIVERED.value,
        BookingAction.REPORT_DELIVERY_FAILED: PC.DELIVERY_FAILED.value,
        BookingAction.RETRY_DELIVERY: PC.IN_TRANSIT.value,
        BookingAction.RETURN_TO_SENDER: PC.RETURNED.value,
        BookingAction.COMPLETE: PB.COMPLETED.value,
    }
    if action not in ACTION_SERVICES or service not in ACTION_SERVICES[action]:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            details={"machine": service_machine(service).name, "from": current, "command": action.value},
        )
    return targets[action]


# --- contact visibility (Q43-Q44, ADR-0020) -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContactVisibility:
    phones_visible: bool
    visible_from: datetime | None
    visible_until: datetime | None


def contact_visibility(
    *, service_started_at: datetime | None, service_terminal_at: datetime | None, now: datetime
) -> ContactVisibility:
    """Phones are hidden before the service starts, revealed at start, hidden again 24 h after a terminal state.

    A booking cancelled before it started never reveals phones (``service_started_at`` stays null).
    """
    now = ensure_aware_utc(now)
    if service_started_at is None:
        return ContactVisibility(False, None, None)
    started = ensure_aware_utc(service_started_at)
    until = None if service_terminal_at is None else ensure_aware_utc(service_terminal_at) + CONTACT_HIDE_AFTER_TERMINAL
    visible = started <= now and (until is None or now < until)
    return ContactVisibility(visible, started, until)


@dataclass(frozen=True, slots=True)
class PhoneDisclosure:
    driver_phone_to_client: bool
    client_phone_to_driver: bool
    receiver_phone_to_driver: bool


def phone_disclosure(service_type: ServiceType | str, visibility: ContactVisibility) -> PhoneDisclosure:
    """Q44: the parcel sender's (client's) phone never reaches the driver; the receiver's only once the service started
    (Q142, ADR-0026: a parcel's service starts when the trip departs - there is no pickup step any more)."""
    service = ServiceType(service_type)
    visible = visibility.phones_visible
    if service is ServiceType.PASSENGER:
        return PhoneDisclosure(visible, visible, False)
    # Parcel: visibility starts with the service (trip depart, Q142), so the receiver phone is shown from then on.
    return PhoneDisclosure(visible, False, visible)


def first_name(full_name: str | None, fallback: str) -> str:
    """Before and during service only the first name is shown (never the surname or phone)."""
    if full_name and full_name.strip():
        return full_name.strip().split()[0][:64]
    return fallback


# --- cancellation (STATE_MACHINES §4-§5, Q19) -----------------------------------------------------------------


def fault_side_for_cancel(side: ActorSide) -> FaultSide:
    """Plain cancel: the initiating side is at fault; an operator cancel records no fault unless decided (N3)."""
    return {
        ActorSide.CLIENT: FaultSide.CLIENT,
        ActorSide.DRIVER: FaultSide.DRIVER,
        ActorSide.OPERATOR: FaultSide.NONE,
        ActorSide.SYSTEM: FaultSide.NONE,
    }[ActorSide(side)]


def ensure_cancellable(service_type: ServiceType | str, status: str) -> None:
    service = ServiceType(service_type)
    if service is ServiceType.PARCEL and status in PARCEL_CUSTODY_STATUSES:
        raise DomainError(ErrorCode.CUSTODY_REQUIRES_RETURN_FLOW, details={"service_status": status})
    service_machine(service).assert_transition(status, PB.CANCELLED.value, "cancel")


def request_listing_reopens(
    *, cancelled_by: ActorSide, listing_expires_at: datetime, departure_window_end: datetime, now: datetime
) -> bool:
    """Q19: only a driver/operator cancel reopens the client's request, and only inside its valid window."""
    if ActorSide(cancelled_by) not in (ActorSide.DRIVER, ActorSide.OPERATOR):
        return False
    now = ensure_aware_utc(now)
    return ensure_aware_utc(listing_expires_at) > now and ensure_aware_utc(departure_window_end) > now


# --- no-show (Q7, spec §11) ------------------------------------------------------------------------------------


def check_no_show_report(
    *,
    arrived_at_pickup_at: datetime | None,
    pickup_window_start: datetime,
    pickup_window_end: datetime,
    wait_minutes: int,
    contact_attempts: int,
    now: datetime,
) -> datetime:
    """Guard for ``report_no_show``; returns ``wait_until``. Raises ``NO_SHOW_NOT_ALLOWED``.

    * the driver recorded ``arrive_at_pickup`` inside the agreed pickup window (a late driver cannot blame
      the client);
    * the announced wait (default 10 min) has passed, counted from arrival or window start, whichever is later;
    * at least one contact attempt is recorded.
    """
    now = ensure_aware_utc(now)
    if arrived_at_pickup_at is None:
        raise DomainError(ErrorCode.NO_SHOW_NOT_ALLOWED, details={"reason": "arrival_not_recorded"})
    arrived = ensure_aware_utc(arrived_at_pickup_at)
    window_start, window_end = ensure_aware_utc(pickup_window_start), ensure_aware_utc(pickup_window_end)
    if arrived > window_end:
        raise DomainError(ErrorCode.NO_SHOW_NOT_ALLOWED, details={"reason": "driver_arrived_late"})
    wait_until = max(arrived, window_start) + timedelta(minutes=max(0, wait_minutes))
    if now < wait_until:
        raise DomainError(ErrorCode.NO_SHOW_NOT_ALLOWED, details={"reason": "wait_time_not_elapsed"})
    if contact_attempts < 1:
        raise DomainError(ErrorCode.NO_SHOW_NOT_ALLOWED, details={"reason": "no_contact_attempt"})
    return wait_until


# --- proofs (spec §11, ADR-0018) --------------------------------------------------------------------------------


def ensure_proof_attempts_left(failed_attempts: int) -> None:
    if failed_attempts >= MAX_PROOF_ATTEMPTS:
        raise DomainError(ErrorCode.PROOF_ATTEMPTS_EXCEEDED, details={"limit": MAX_PROOF_ATTEMPTS})


# --- fee finalization (spec §9.5, AC20, AC26) -------------------------------------------------------------------


def capture_on_completion(*, commission_status: str, blocking_dispute_open: bool) -> bool:
    """Capture in the completion transaction only when a hold exists and no serious dispute is open."""
    return commission_status == "held" and not blocking_dispute_open


def ensure_fee_finalizable(service_status: str) -> None:
    if service_status not in FEE_FINALIZABLE_STATUSES:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            details={"machine": "commission", "command": "finalize_fee", "service_status": service_status},
        )


def boarding_opens_at(planned_start_at: datetime) -> datetime:
    return ensure_aware_utc(planned_start_at) - BOARDING_WINDOW


def quantity_amendable(service_type: ServiceType | str, *, from_request: bool) -> bool:
    """D9/D10 (Q145, ADR-0026): may an agreed booking's quantity be amended?

    A parcel is always one shipment. A booking made on a client request keeps the request's seat count (D9 - requests
    are not split); the client changes the quantity *before* a booking exists by editing the request (Q20 expires the
    open offers, which must be agreed again). Only legacy bookings made on a driver's trip offer (pre-Q138) could move
    the quantity by a two-sided amendment (D10). Unit-price amendments are unaffected.
    """
    return ServiceType(service_type) is ServiceType.PASSENGER and not from_request
