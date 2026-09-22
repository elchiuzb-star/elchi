"""Bookings domain API (A4): the atomic accept orchestrator and the booking lifecycle.

Public functions take the caller's ``Session`` and never commit (ADR-0001); the v2 runner commits once.
Every status write goes through ``app.contracts.state_machines`` (``assert_transition(..., command=...)``).

Global lock order (ADR-0017, STATE_MACHINES §0.2) - modes in parentheses:

* accept:   users client+driver (FOR NO KEY UPDATE, id ASC) -> trip (FOR NO KEY UPDATE) -> listings request+supply
            (FOR NO KEY UPDATE, id ASC) -> thread + current version (FOR NO KEY UPDATE) -> trip segments (reserve,
            under the trip lock) -> [other open threads of the listing, behind the listing lock] -> booking insert
            -> allocations insert -> wallet (FOR UPDATE, A3) -> hold insert
* cancel:   trip -> listings -> booking -> (pending no-show review, read) -> wallet -> hold
* actions:  booking -> proofs / reviews / custody cases -> wallet (complete -> capture)
* no-show:  trip -> listings -> booking -> no_show_review -> wallet
* trip ops: trip -> listings -> threads -> bookings (id ASC) -> children -> wallets
* cash:     booking -> cash_receipt
* amendment accept: trip -> booking -> amendment -> wallet

Signatures other modules may rely on (read-side hooks, functions only):

* ``blocking_state_for_user(session, user_id, *, lock=False) -> BookingBlockingState``      (N4, v1 deletion)
* ``driver_v2_obligations(session, driver_user_id) -> DriverV2Obligations``                (Q15, v1 block_driver)
* ``trip_has_active_allocations(session, trip_id) -> bool``                                (A1 N6, patch_trip)
* ``trip_has_allocations(session, trip_id) -> bool``                                       (A1: segment rewrite)
* ``count_active_bookings_on_corridor(session, corridor_id) -> int`` + ``register_geo_hooks()`` (A2 counter)
* ``booking_public_id_for_proposal_version(session, proposal_version_id) -> str | None``   (A1 thread DTO)
* ``set_blocking_dispute_probe(fn)`` / ``set_payment_dispute_opener(fn)``                  (A12 wiring)
* ``set_chat_thread_lookup(fn)`` / ``chat_thread_public_id(session, booking_id)``          (A7 wiring, wave 5)

Scheduled functions for the A10a worker (wave 2.1; no commit - the task wrapper commits/rolls back):

* ``expire_due_amendments(session, *, now=None, limit=200) -> int``              (B9-B11 TTL, lock booking -> amendment)
* ``emit_confirmation_overdue_signals(session, *, now=None, limit=200) -> int``  (§9.5 arrived 24 h, Q65 delivered 24 h)
* ``emit_hold_escalation_signals(session, *, now=None, limit=200) -> int``       (§9.5 active hold past escalate_at)
Both signal functions are deduplicated per booking / hold through ``outbox_events.dedup_key``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import proofs as proof_policy
from app.contracts.crypto import PROOF_CODE_KEY_VERSION, derive_proof_code, proof_code_hash, verify_proof_code
from app.contracts.detour import DETOUR_INSERTION_ENABLED, DETOUR_NOT_AVAILABLE_REASON
from app.contracts.detour import DetourQuote as ContractDetourQuote
from app.contracts.detour import total_detour_seconds
from app.contracts.enums import (
    OPERATOR_COMMAND_CAPABILITY,
    ActorSide,
    AdminBookingQueue,
    CommissionReviewReason,
    BookingAction,
    Capability,
    CashCollectionStatus,
    CashResolutionOutcome,
    CommissionStatus,
    CustodyCaseStatus,
    EventType,
    FaultSide,
    FeatureFlagKey,
    ListingKind,
    ListingStatus,
    NoShowReviewStatus,
    OperatorBookingCommand,
    ParcelBookingStatus,
    ParcelPayer,
    PassengerBookingStatus,
    ProofKind,
    ServiceType,
    TripStatus,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.events import EventEnvelope
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.money import commission_minor, initial_commission_status, total_minor as money_total_minor
from app.contracts.state_machines import (
    AMENDMENT,
    CASH_COLLECTION,
    COMMISSION,
    CUSTODY_CASE,
    DELIVERED_OPERATOR_QUEUE_AFTER,
    NO_SHOW_REVIEW,
    TRIP,
    TRIP_CANCEL_REFUSED_WITH_PENDING_NO_SHOW_REVIEW,
    booking_blocks_trip_cancel,
    booking_blocks_trip_completion,
    reject_no_show_outcome,
    service_start_allowed,
)
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.core.config import proof_code_keyring
from app.models import AuditLog
from app.modules.bookings import rules
from app.modules.bookings.models import (
    Booking,
    BookingAllocation,
    BookingAmendment,
    BookingProof,
    BookingProofAttempt,
    BookingProofReissue,
    BookingStatusHistory,
    CashReceipt,
    CustodyCase,
    NoShowReview,
)
from app.modules.identity import service as identity_service
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.models import Listing, ProposalThread, ProposalVersion
from app.modules.marketplace.rules import check_proposal_quantity
from app.modules.platform import service as platform_service
from app.modules.trips import service as trips_service
from app.modules.trips.models import Trip
from app.modules.trips.rules import ResourceDemand
from app.modules.wallet import service as wallet_service

PB = PassengerBookingStatus
PC = ParcelBookingStatus

__all__ = [
    "ActionInput",
    "BookingBlockingState",
    "DriverV2Obligations",
    "ProofFailure",
    "ViewerRole",
    "accept_amendment",
    "accept_proposal",
    "acknowledge_cash_receipt",
    "admin_queue",
    "blocking_state_for_user",
    "booking_codes",
    "booking_public_id",
    "booking_public_id_for_proposal_version",
    "cancel_booking",
    "contest_cash_receipt",
    "count_active_bookings_on_corridor",
    "create_amendment",
    "decide_amendment",
    "driver_v2_obligations",
    "emit_confirmation_overdue_signals",
    "emit_hold_escalation_signals",
    "evaluate_detour_quotes",
    "expire_due_amendments",
    "get_booking_by_public_id",
    "get_booking_for_viewer",
    "list_user_bookings",
    "lock_booking",
    "mark_finance_review_after_dispute",
    "operator_command",
    "perform_action",
    "record_failed_proof_attempts",
    "record_staff_contact_view",
    "register_geo_hooks",
    "reissue_proof_code",
    "report_cash_receipt",
    "resolve_contested_cash_receipt",
    "chat_thread_public_id",
    "set_blocking_dispute_probe",
    "set_chat_thread_lookup",
    "set_payment_dispute_opener",
    "trip_action",
    "trip_has_active_allocations",
    "trip_has_allocations",
    "trip_manifest",
]

REQUEST_BINDING_INDEX = "uq_bookings_request_listing_binding"
ACCEPTED_VERSION_UNIQUE = "uq_bookings_accepted_proposal_version"
PENDING_REVIEW_INDEX = "uq_no_show_reviews_pending"
OPEN_CUSTODY_INDEX = "uq_custody_cases_open"
OPEN_RECEIPT_INDEX = "uq_cash_receipts_open"
PROPOSED_AMENDMENT_INDEX = "uq_booking_amendments_proposed"

SERVICE_FLAG: dict[ServiceType, FeatureFlagKey] = {
    ServiceType.PASSENGER: FeatureFlagKey.PASSENGER_ENABLED,
    ServiceType.PARCEL: FeatureFlagKey.PARCEL_ENABLED,
}
OPEN_LISTING_STATUSES = (ListingStatus.PUBLISHED.value, ListingStatus.PAUSED.value, ListingStatus.FULFILLED.value)
AMENDMENT_TTL = timedelta(hours=2)
ADMIN_QUEUES = tuple(queue.value for queue in AdminBookingQueue)  # incl. finance_review (Q66)
SIGNAL_BATCH_LIMIT = 200


class ViewerRole:
    CLIENT = "client"
    DRIVER = "driver"
    STAFF = "staff"


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


def booking_public_id(booking: Booking) -> str:
    return format_public_id(PublicIdPrefix.BOOKING, booking.public_id)


# --- hooks for A12 (disputes) and A2 (corridor counter) -----------------------------------------------------

BlockingDisputeProbe = Callable[[Session, int], bool]
PaymentDisputeOpener = Callable[[Session, Booking, CashReceipt, int, str], int | None]
_blocking_dispute_probe: BlockingDisputeProbe | None = None
_payment_dispute_opener: PaymentDisputeOpener | None = None


def set_blocking_dispute_probe(probe: BlockingDisputeProbe | None) -> None:
    """A12 registers ``probe(session, booking_id) -> bool``: an open service/commission/payment/delivery dispute."""
    global _blocking_dispute_probe
    _blocking_dispute_probe = probe


def set_payment_dispute_opener(opener: PaymentDisputeOpener | None) -> None:
    """A12 registers ``opener(session, booking, receipt, actor_user_id, comment) -> dispute id`` (AC26)."""
    global _payment_dispute_opener
    _payment_dispute_opener = opener


ChatThreadLookup = Callable[[Session, int], str | None]
_chat_thread_lookup: ChatThreadLookup | None = None


def set_chat_thread_lookup(lookup: ChatThreadLookup | None) -> None:
    """A7 registers ``lookup(session, booking_id) -> chat thread public id | None`` (wave 5 follow-up).

    Read-only on purpose: opening a booking must not create a thread, and a booking whose chat has never been
    used keeps ``chat_thread_id = null`` - the client then opens the thread through N6 with the booking id.
    """
    global _chat_thread_lookup
    _chat_thread_lookup = lookup


def chat_thread_public_id(session: Session, booking_id: int) -> str | None:
    """The existing chat thread of a booking, or ``None`` when communications is not wired or no thread exists."""
    if _chat_thread_lookup is None:
        return None
    return _chat_thread_lookup(session, booking_id)


DisputeState = Literal["open", "clear", "unavailable"]


def dispute_state(session: Session, booking_id: int) -> DisputeState:
    """Serious-dispute check before a completion capture (AC20, AC26, Q66, Q74).

    * probe registered (A12, wave 3): ``open`` (capture delayed) / ``clear`` (capture);
    * no probe - whether or not a ``disputes_v2`` table exists - ``unavailable`` (Q74): the service completes, the
      commission stays held and goes to the ``finance_review`` queue; finance captures with ``finalize_fee``.
    """
    if _blocking_dispute_probe is not None:
        return "open" if _blocking_dispute_probe(session, booking_id) else "clear"
    return "unavailable"


def blocking_dispute_open(session: Session, booking_id: int) -> bool:
    """Compatibility reader: an unavailable dispute check counts as blocking (no capture)."""
    return dispute_state(session, booking_id) != "clear"


def count_active_bookings_on_corridor(session: Session, corridor_id: int) -> int:
    """Non-terminal bookings on a corridor (A2 ``set_active_booking_counter``, STATE_MACHINES §10)."""
    return int(
        session.execute(
            select(func.count(Booking.id)).where(
                Booking.corridor_id == corridor_id,
                Booking.service_status.not_in(sorted(rules.TERMINAL_SERVICE_STATUSES)),
            )
        ).scalar_one()
    )


def register_geo_hooks() -> None:
    """Integrator: call once at start-up (``app.api.v2.router.configure_v2_ports``)."""
    from app.modules.geo import service as geo_service

    geo_service.set_active_booking_counter(count_active_bookings_on_corridor)


# --- small readers -------------------------------------------------------------------------------------------


def resolve_booking_id(session: Session, public_id: str) -> int:
    value = parse_public_id(public_id, PublicIdPrefix.BOOKING)
    booking_id = session.execute(select(Booking.id).where(Booking.public_id == value)).scalar_one_or_none()
    if booking_id is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return booking_id


def get_booking(session: Session, booking_id: int) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return booking


def get_booking_by_public_id(session: Session, public_id: str) -> Booking:
    return get_booking(session, resolve_booking_id(session, public_id))


def lock_booking(session: Session, booking_id: int) -> Booking:
    """Bookings group of the lock order; ``FOR NO KEY UPDATE`` (children insert with FOR KEY SHARE)."""
    booking = session.execute(
        select(Booking).where(Booking.id == booking_id).with_for_update(key_share=True).execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if booking is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return booking


def participant_side(booking: Booking, user_id: int) -> ActorSide | None:
    if user_id == booking.client_user_id:
        return ActorSide.CLIENT
    if user_id == booking.driver_user_id:
        return ActorSide.DRIVER
    return None


def get_booking_for_viewer(session: Session, booking_public_id_value: str, viewer_user_id: int) -> tuple[Booking, str]:
    booking = get_booking_by_public_id(session, booking_public_id_value)
    side = participant_side(booking, viewer_user_id)
    if side is ActorSide.CLIENT:
        return booking, ViewerRole.CLIENT
    if side is ActorSide.DRIVER:
        return booking, ViewerRole.DRIVER
    if identity_service.get_capabilities(session, viewer_user_id).has(Capability.OPS_VIEW):
        return booking, ViewerRole.STAFF
    raise DomainError(ErrorCode.NOT_FOUND)


def pending_no_show_review(session: Session, booking_id: int, *, lock: bool = False) -> NoShowReview | None:
    stmt = select(NoShowReview).where(NoShowReview.booking_id == booking_id, NoShowReview.status == NoShowReviewStatus.PENDING.value)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return session.execute(stmt).scalar_one_or_none()


def open_custody_case(session: Session, booking_id: int, *, lock: bool = False) -> CustodyCase | None:
    stmt = select(CustodyCase).where(CustodyCase.booking_id == booking_id, CustodyCase.status == CustodyCaseStatus.OPEN.value)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return session.execute(stmt).scalar_one_or_none()


def latest_no_show_review(session: Session, booking_id: int) -> NoShowReview | None:
    return session.execute(
        select(NoShowReview).where(NoShowReview.booking_id == booking_id).order_by(NoShowReview.id.desc()).limit(1)
    ).scalar_one_or_none()


def latest_cash_receipt(session: Session, booking_id: int) -> CashReceipt | None:
    """The receipt a participant would act on next: the newest one, whatever its status."""
    return session.execute(
        select(CashReceipt).where(CashReceipt.booking_id == booking_id).order_by(CashReceipt.id.desc()).limit(1)
    ).scalar_one_or_none()


def latest_custody_case(session: Session, booking_id: int) -> CustodyCase | None:
    return session.execute(
        select(CustodyCase).where(CustodyCase.booking_id == booking_id).order_by(CustodyCase.id.desc()).limit(1)
    ).scalar_one_or_none()


def active_allocations(session: Session, booking_id: int) -> list[BookingAllocation]:
    return list(
        session.execute(
            select(BookingAllocation)
            .where(BookingAllocation.booking_id == booking_id, BookingAllocation.active.is_(True))
            .order_by(BookingAllocation.segment_from_seq)
        ).scalars()
    )


def booking_public_id_for_proposal_version(session: Session, proposal_version_id: int) -> str | None:
    value = session.execute(
        select(Booking.public_id).where(Booking.accepted_proposal_version_id == proposal_version_id)
    ).scalar_one_or_none()
    return None if value is None else format_public_id(PublicIdPrefix.BOOKING, value)


# --- history and events --------------------------------------------------------------------------------------


def _history(
    session: Session,
    booking: Booking,
    *,
    machine: str,
    from_status: str | None,
    to_status: str,
    command: str,
    actor_user_id: int | None,
    side: ActorSide,
    reason: str | None = None,
) -> None:
    session.add(
        BookingStatusHistory(
            booking_id=booking.id,
            machine=machine,
            from_status=from_status,
            to_status=to_status,
            command=command,
            actor_user_id=actor_user_id,
            actor_side=ActorSide(side).value,
            reason=reason,
        )
    )


def _trip_public_id(session: Session, trip_id: int) -> str:
    return trips_service.trip_public_id(trips_service.get_trip(session, trip_id))


def _emit(session: Session, booking: Booking, event_type: EventType, payload: dict[str, Any], now: datetime) -> None:
    platform_service.enqueue_event(
        session,
        EventEnvelope(event_type, "booking", booking_public_id(booking), booking.version, now, payload),
        aggregate_id=booking.id,
    )


def _emit_status_changed(
    session: Session, booking: Booking, *, machine: str, from_status: str | None, to_status: str, now: datetime
) -> None:
    _emit(
        session,
        booking,
        EventType.BOOKING_STATUS_CHANGED,
        {
            "service_type": booking.service_type,
            "trip_id": _trip_public_id(session, booking.trip_id),
            "machine": machine,
            "from_status": from_status,
            "to_status": to_status,
        },
        now,
    )


def _touch(booking: Booking, now: datetime) -> None:
    booking.version += 1
    booking.updated_at = now


def _set_service_status(
    session: Session,
    booking: Booking,
    *,
    target: str,
    command: str,
    actor_user_id: int | None,
    side: ActorSide,
    now: datetime,
    reason: str | None = None,
    emit: bool = True,
) -> str:
    previous = booking.service_status
    rules.service_machine(booking.service_type).assert_transition(previous, target, command)
    booking.service_status = target
    if target in rules.STARTED_STATUSES[ServiceType(booking.service_type)] and booking.service_started_at is None:
        booking.service_started_at = now  # Q44: phones revealed from the start of the service
    if rules.is_terminal_service_status(target):
        booking.service_terminal_at = now  # Q44: phones hidden 24 h after this
    _history(
        session, booking, machine="service", from_status=previous, to_status=target, command=command,
        actor_user_id=actor_user_id, side=side, reason=reason,
    )
    if emit:
        _emit_status_changed(session, booking, machine="service", from_status=previous, to_status=target, now=now)
    return previous


def _set_commission_status(
    session: Session, booking: Booking, *, target: CommissionStatus, command: str, actor_user_id: int | None, side: ActorSide
) -> None:
    previous = booking.commission_status
    COMMISSION.assert_transition(previous, target.value, command)
    booking.commission_status = target.value
    _history(
        session, booking, machine="commission", from_status=previous, to_status=target.value, command=command,
        actor_user_id=actor_user_id, side=side,
    )


# ==============================================================================================================
# Accept (P8, spec §15)
# ==============================================================================================================


def _supply_listing_id(session: Session, listing: Listing, trip_id: int) -> int | None:
    if listing.kind == ListingKind.TRIP_OFFER.value:
        return listing.id
    for candidate in marketplace_service.listings_for_trip(session, trip_id):
        if (
            candidate.kind == ListingKind.TRIP_OFFER.value
            and candidate.service_type == listing.service_type
            and candidate.status in OPEN_LISTING_STATUSES
        ):
            return candidate.id
    return None


def _offer_span(session: Session, trip_id: int, listing: Listing) -> tuple[int, int] | None:
    return trips_service.occurrence_seqs_for_stops(session, trip_id, listing.origin_stop_id, listing.destination_stop_id)


def _offer_has_capacity(session: Session, trip_id: int, listing: Listing) -> bool:
    """A trip offer stays open while some segment of its span still has the service's resource (§1 system_fulfil)."""
    span = _offer_span(session, trip_id, listing)
    if span is None:
        return False
    loads = [load for load in trips_service.get_segment_loads(session, trip_id) if span[0] <= load.from_seq < span[1]]
    if listing.service_type == ServiceType.PASSENGER.value:
        return any(load.seat_capacity - load.seats_used > 0 for load in loads)
    return any(
        load.cargo_capacity_weight_g - load.cargo_used_weight_g > 0
        and load.cargo_capacity_volume_ml - load.cargo_used_volume_ml > 0
        for load in loads
    )


def _trip_route_context(session: Session, trip: Trip):  # noqa: ANN202 - geo TripRouteContext
    from app.modules.geo.types import OccurrenceTiming, TripRouteContext

    from app.modules.trips.ports import get_geo_port

    occurrences = trips_service.list_occurrences(session, trip.id)
    route = get_geo_port().route_versions_by_ids(session, [trip.route_version_id]).get(trip.route_version_id)
    if route is None:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "route_version_missing"})
    return TripRouteContext(
        route_version_id=trip.route_version_id,
        trip_version=trip.version,
        occurrences=tuple(
            OccurrenceTiming(o.seq, o.stop_id, ensure_aware_utc(o.planned_arrival_at), o.dwell_minutes) for o in occurrences
        ),
        max_detour_minutes=trip.max_detour_minutes,
        max_detour_m=trip.max_detour_m,
        detour_used_s=trip.detour_used_s,
        detour_used_m=trip.detour_used_m,
        pickup_wait_minutes=trip.pickup_wait_minutes,
        route_version_public_id=route.public_id,
    )


def evaluate_detour_quotes(
    context: Any,
    quotes: Sequence[Any],
    existing_windows: Sequence[Any],
    *,
    production: bool,
    now: datetime,
) -> Any:
    """Detour re-check under the trip lock, without any router call (spec §15, AC17, Q25, Q46). Pure.

    * production: no routing provider exists (Q46) -> a detour quote fails closed (``ROUTE_CHANGED``);
    * every quote must belong to the locked route/trip version and be unexpired (``validate_detour_quotes``);
    * the trip's cumulative detour budget in seconds and metres must hold (AC17, ``DETOUR_LIMIT_EXCEEDED``);
    * no existing booking window may break (``TIME_WINDOW_CONFLICT``).
    Returns geo's ``TimelineChange`` (new occurrence timeline + ``seq_map``).
    """
    from app.modules.geo import matching

    if not quotes:
        return None
    if production:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "detour_not_available_in_production"})
    matching.validate_detour_quotes(list(quotes), context, now=now)
    added_s = total_detour_seconds(tuple(quotes))
    added_m = sum(int(quote.extra_m) for quote in quotes)
    if not matching.cumulative_detour_allowed(
        detour_used_s=context.detour_used_s,
        detour_used_m=context.detour_used_m,
        added_s=added_s,
        added_m=added_m,
        max_detour_minutes=context.max_detour_minutes,
        max_detour_m=context.max_detour_m,
    ):
        raise DomainError(
            ErrorCode.DETOUR_LIMIT_EXCEEDED,
            details={"detour_used_s": context.detour_used_s, "added_s": added_s, "max_detour_s": context.max_detour_s},
        )
    return matching.verify_existing_windows(context, list(existing_windows), list(quotes))


def _version_detour_quotes(version: ProposalVersion) -> tuple[ContractDetourQuote, ...]:
    """Detour quotes snapshotted on the proposal version (A1 request: ``proposal_versions.detour_quotes``).

    A1 currently accepts only existing trip stops at submit/counter (no detour), so versions carry none.
    """
    return tuple(getattr(version, "detour_quotes", None) or ())


def accept_proposal(
    session: Session,
    *,
    thread_public_id: str,
    actor_user_id: int,
    proposal_version_public_id: str,
    expected_listing_version: int,
    now: datetime | None = None,
) -> Booking:
    """P8: ``active -> accepted`` + booking ``confirmed`` + allocations + hold (or exempt), in one transaction."""
    now = _now(now)
    # Unlocked reads only locate the rows; everything is re-read under the locks below.
    thread = marketplace_service.get_thread_by_public_id(session, thread_public_id)
    if marketplace_service.actor_side(thread, actor_user_id) is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    requested = marketplace_service.get_version_by_public_id(session, proposal_version_public_id)
    if requested.thread_id != thread.id:
        raise DomainError(ErrorCode.NOT_FOUND)
    listing = marketplace_service.get_listing(session, thread.listing_id)
    if thread.trip_id is None:
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": "thread_without_trip"})
    trip_id = thread.trip_id
    request_id = listing.id if listing.kind == ListingKind.REQUEST.value else None
    supply_id = _supply_listing_id(session, listing, trip_id)
    client_id, driver_id = thread.client_user_id, thread.driver_user_id

    # 1. users (FOR NO KEY UPDATE, id ASC): serialises with the admin eligibility block (AC41).
    identity_service.lock_user_eligibility(session, [client_id, driver_id], mode="update")
    # 2. trip (FOR NO KEY UPDATE): the physical capacity source.
    trip = trips_service.lock_trip(session, trip_id)
    # 3. listings (FOR NO KEY UPDATE, id ASC).
    locked_listings = {row.id: row for row in marketplace_service.lock_listings(session, [i for i in (request_id, supply_id) if i])}
    listing = locked_listings[listing.id]
    # 4. thread and its current version (FOR NO KEY UPDATE).
    thread = marketplace_service.lock_thread(session, thread.id)
    version = marketplace_service.current_version(session, thread, for_update=True)

    side = marketplace_service.actor_side(thread, actor_user_id)
    if thread.state != marketplace_service.THREAD_OPEN:
        raise DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "thread_not_open", "state": thread.state})
    if version is None or version.id != requested.id:
        raise DomainError(
            ErrorCode.PROPOSAL_CHANGED, details={"reason": "not_current_version", "current_revision": version.revision if version else None}
        )
    if version.status != "active":
        code = ErrorCode.PROPOSAL_EXPIRED if version.status == "expired" else ErrorCode.PROPOSAL_CHANGED
        raise DomainError(code, details={"status": version.status})
    if side is ActorSide(version.author_side):
        raise DomainError(ErrorCode.NOT_PROPOSAL_RECIPIENT)  # AC05: the author never accepts its own version
    if listing.service_type == ServiceType.PARCEL.value:
        # §5.2: a new parcel booking needs an approved prohibited-items policy (fail-closed in production).
        # Only the *new* obligation is gated; everything already accepted keeps running to its end.
        marketplace_service.assert_parcel_policy_ready(session)
    if ensure_aware_utc(version.expires_at) <= now:
        raise DomainError(ErrorCode.PROPOSAL_EXPIRED)  # the frozen fee quote expires with it (AC43)
    # Q54: the agreement is compared on the listing's *terms* version (listings.version counts every edit).
    if expected_listing_version != listing.terms_version:
        raise DomainError(
            ErrorCode.PROPOSAL_CHANGED,
            details={"reason": "listing_terms_version_mismatch", "current_listing_terms_version": listing.terms_version},
        )
    if version.listing_terms_version != listing.terms_version:
        raise DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "listing_terms_changed"})
    if listing.status != ListingStatus.PUBLISHED.value:
        raise DomainError(ErrorCode.LISTING_NOT_OPEN, details={"status": listing.status})
    if ensure_aware_utc(listing.expires_at) <= now or ensure_aware_utc(listing.departure_window_end) <= now:
        raise DomainError(ErrorCode.LISTING_NOT_OPEN, details={"reason": "listing_expired"})
    if trip.status != TripStatus.PLANNED.value or ensure_aware_utc(trip.booking_cutoff_at) <= now:
        raise DomainError(ErrorCode.BOOKING_CUTOFF_PASSED, details={"trip_status": trip.status})
    if version.route_version_id != trip.route_version_id:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "route_version_changed"})
    # Not raw trip.version (card §1.4): the same occurrences must still exist and the pickup ETA window must still
    # meet the agreed pickup window (the proposal validated it against the timeline of its time).
    pickup_seq, dropoff_seq = version.pickup_occurrence_seq, version.dropoff_occurrence_seq
    occurrences = {o.seq: o for o in trips_service.list_occurrences(session, trip.id)}
    if pickup_seq is None or dropoff_seq is None or pickup_seq not in occurrences or dropoff_seq not in occurrences:
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "occurrences_changed"})
    if version.pickup_point is None and version.dropoff_point is None:
        if (
            occurrences[pickup_seq].stop_id != version.pickup_stop_id
            or occurrences[dropoff_seq].stop_id != version.dropoff_stop_id
        ):
            raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "occurrences_changed"})
    elif marketplace_service.point_segment_for_trip(session, listing, trip) != (pickup_seq, dropoff_seq):
        # Q88: a point end has no stop id to compare, so the places are re-projected onto the trip as it
        # stands now. Different segments means the road moved under the agreement.
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "point_segments_changed"})
    from app.contracts.timeutil import windows_intersect
    from app.modules.geo.matching import eta_window

    pickup_occ = occurrences[pickup_seq]
    eta_start, eta_end = eta_window(pickup_occ.planned_arrival_at, pickup_occ.dwell_minutes, pickup_wait_minutes=trip.pickup_wait_minutes)
    if not windows_intersect(eta_start, eta_end, version.pickup_window_start, version.pickup_window_end):
        raise DomainError(ErrorCode.ROUTE_CHANGED, details={"reason": "schedule_changed"})

    # Eligibility re-checked under the users lock (Q21, D16, AC41).
    identity_service.ensure_driver_eligible(session, driver_id, now=now)
    # Q61: the trip's vehicle must still be approved - only NEW bookings are refused (read under the trip lock).
    trips_service.assert_vehicle_eligible_for_new_booking(session, trip.vehicle_id)
    identity_service.require_capability(
        identity_service.get_capabilities(session, client_id, now=now), Capability.PROPOSAL_SUBMIT_AS_CLIENT
    )

    service = ServiceType(listing.service_type)
    from app.modules.geo import service as geo_service

    flags = geo_service.snapshot_flags(session, corridor_id=listing.corridor_id)
    if not flags.get(SERVICE_FLAG[service].value, False):
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"flag": SERVICE_FLAG[service].value})
    if listing.kind == ListingKind.TRIP_OFFER.value and not flags.get(FeatureFlagKey.DRIVER_LISTING_ENABLED.value, False):
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"flag": FeatureFlagKey.DRIVER_LISTING_ENABLED.value})

    if listing.kind == ListingKind.REQUEST.value:
        check_proposal_quantity(
            listing_kind=ListingKind.REQUEST, service_type=service, listing_quantity=listing.quantity, quantity=version.quantity
        )  # D9: a request is never split

    # Q62: detour insertion and the AC13 re-check are deferred in the pilot (Q46) - refused in EVERY environment,
    # before any measurement is evaluated.
    if _version_detour_quotes(version) and not DETOUR_INSERTION_ENABLED:
        raise DomainError(ErrorCode.ROUTE_MISMATCH, details={"reason": DETOUR_NOT_AVAILABLE_REASON})

    fee_status = initial_commission_status(version.fee_bps)
    if commission_minor(version.total_minor, version.fee_bps) != version.commission_minor:
        raise DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "fee_quote_inconsistent"})
    if fee_status is CommissionStatus.EXEMPT:
        wallet_service.require_money_invariants(session, new_business=True)  # N1/Q48 also for exempt bookings

    # 5. capacity on every segment [pickup, dropoff) under the trip lock (AC07, AC10-AC12).
    demand = marketplace_service.version_demand(version, service_type=service)
    if not demand.is_empty:
        trips_service.reserve(session, trip.id, pickup_seq, dropoff_seq, demand)

    listing_version_at_accept = listing.version
    # 6. marketplace: accept this version; the demand's other versions expire; listings fulfil (§2, §1).
    marketplace_service.accept_version(session, listing=listing, thread=thread, version=version, now=now)
    if request_id is not None:
        marketplace_service.close_open_threads(session, listing=listing, reason="demand_fulfilled", now=now)
        marketplace_service.fulfil_listing(session, listing=listing, now=now)
    supply = locked_listings.get(supply_id) if supply_id is not None else None
    if supply is not None and supply.status == ListingStatus.PUBLISHED.value and not _offer_has_capacity(session, trip.id, supply):
        marketplace_service.close_open_threads(session, listing=supply, reason="capacity_gone", now=now)
        marketplace_service.fulfil_listing(session, listing=supply, now=now)

    # 7. booking + allocations + history.
    booking = Booking(
        public_id=new_public_uuid(),
        service_type=service.value,
        service_status=PB.CONFIRMED.value,
        cash_status=CashCollectionStatus.UNPAID.value,
        commission_status=fee_status.value,
        client_user_id=client_id,
        driver_user_id=driver_id,
        trip_id=trip.id,
        corridor_id=listing.corridor_id,
        request_listing_id=request_id,
        supply_listing_id=supply_id,
        proposal_thread_id=thread.id,
        accepted_proposal_version_id=version.id,
        route_version_id=trip.route_version_id,
        trip_version=trip.version,
        pickup_stop_id=version.pickup_stop_id,
        dropoff_stop_id=version.dropoff_stop_id,
        # Q88: the accepted places are copied, not re-derived. A booking is the frozen agreement - if the
        # client later edits the listing, or an operator moves a stop, what was agreed must not move with it.
        pickup_point=version.pickup_point,
        dropoff_point=version.dropoff_point,
        pickup_district_id=version.pickup_district_id,
        dropoff_district_id=version.dropoff_district_id,
        pickup_address=version.pickup_address,
        dropoff_address=version.dropoff_address,
        pickup_route_offset_m=version.pickup_route_offset_m,
        dropoff_route_offset_m=version.dropoff_route_offset_m,
        pickup_occurrence_seq=pickup_seq,
        dropoff_occurrence_seq=dropoff_seq,
        pickup_window_start=ensure_aware_utc(version.pickup_window_start),
        pickup_window_end=ensure_aware_utc(version.pickup_window_end),
        quantity=version.quantity,
        seats=demand.seats,
        baggage_ml=demand.baggage_ml,
        cargo_weight_g=demand.cargo_weight_g,
        cargo_volume_ml=demand.cargo_volume_ml,
        price_basis=version.price_basis,
        unit_price_minor=version.unit_price_minor,
        total_minor=version.total_minor,
        currency=version.currency,
        payment_method=listing.payment_method,
        fee_policy_id=version.fee_policy_id,
        fee_bps=version.fee_bps,
        commission_minor=version.commission_minor,
        listing_version=listing_version_at_accept,
        listing_terms_version=version.listing_terms_version,
        terms_snapshot={
            "flags": dict(sorted(flags.items())),
            "proposal": {"revision": version.revision, "author_side": version.author_side, "trip_version": version.trip_version},
            "listing": {"kind": listing.kind, "version": listing_version_at_accept, "terms_version": version.listing_terms_version},
            "fee": {"fee_policy_id": version.fee_policy_id, "fee_bps": version.fee_bps, "commission_minor": version.commission_minor},
            "cancellation_policy": rules.CANCELLATION_POLICY,
            "pickup_wait_minutes": trip.pickup_wait_minutes,
            "boarding_window_minutes": int(rules.BOARDING_WINDOW.total_seconds() // 60),
            "detour_quotes": [],
        },
        version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(booking)
    _flush_or_translate(
        session,
        {
            REQUEST_BINDING_INDEX: lambda: DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "demand_already_booked"}),
            ACCEPTED_VERSION_UNIQUE: lambda: DomainError(ErrorCode.PROPOSAL_CHANGED, details={"reason": "version_already_accepted"}),
        },
    )
    if not demand.is_empty:
        for seq in range(pickup_seq, dropoff_seq):
            session.add(
                BookingAllocation(
                    booking_id=booking.id,
                    trip_id=trip.id,
                    segment_from_seq=seq,
                    seats=demand.seats,
                    baggage_ml=demand.baggage_ml,
                    cargo_weight_g=demand.cargo_weight_g,
                    cargo_volume_ml=demand.cargo_volume_ml,
                    active=True,
                )
            )
    actor_side_value = side or ActorSide.SYSTEM
    _history(session, booking, machine="service", from_status=None, to_status=PB.CONFIRMED.value, command="accept",
             actor_user_id=actor_user_id, side=actor_side_value)
    _history(session, booking, machine="cash", from_status=None, to_status=CashCollectionStatus.UNPAID.value, command="accept",
             actor_user_id=actor_user_id, side=actor_side_value)
    _history(session, booking, machine="commission", from_status=None, to_status=fee_status.value,
             command="hold_fee" if fee_status is CommissionStatus.HELD else "mark_exempt", actor_user_id=None, side=ActorSide.SYSTEM)
    session.flush()

    # 8. money last (wallet group): hold with the frozen policy snapshot (AC19, AC43); 0 bps -> exempt, no hold (D3).
    if fee_status is CommissionStatus.HELD:
        wallet_service.hold_fee(
            session,
            booking_id=booking.id,
            booking_public_id=booking_public_id(booking),
            driver_user_id=driver_id,
            total_minor=booking.total_minor,
            fee_bps=booking.fee_bps,
            corridor_id=booking.corridor_id,
            wallet_required=bool(flags.get(FeatureFlagKey.WALLET_REQUIRED.value, True)),
            fee_policy_id=booking.fee_policy_id,
            now=now,
        )

    # 9. outbox (same transaction; audiences are filtered at dispatch, Q16/N2).
    _emit(
        session,
        booking,
        EventType.BOOKING_ACCEPTED,
        {
            "service_type": booking.service_type,
            "trip_id": trips_service.trip_public_id(trip),
            "listing_id": marketplace_service.listing_public_id(listing),
            "proposal_version_id": marketplace_service.version_public_id(version),
            "service_status": booking.service_status,
            "commission_status": booking.commission_status,
        },
        now,
    )
    return booking


# ==============================================================================================================
# Release contract, fee release, cancellation (B3, AC21, AC22, Q19, N3)
# ==============================================================================================================


def _release_allocations(session: Session, booking: Booking, trip_id: int, now: datetime) -> bool:
    """ADR-0017 §11: flip ``active`` true -> false under the trip lock and release once, only on that flip."""
    rows = session.execute(
        update(BookingAllocation)
        .where(BookingAllocation.booking_id == booking.id, BookingAllocation.active.is_(True))
        .values(active=False, released_at=now)
        .returning(
            BookingAllocation.segment_from_seq,
            BookingAllocation.seats,
            BookingAllocation.baggage_ml,
            BookingAllocation.cargo_weight_g,
            BookingAllocation.cargo_volume_ml,
        )
        .execution_options(synchronize_session=False)
    ).all()
    if not rows:
        return False
    rows = sorted(rows, key=lambda row: row.segment_from_seq)
    first = rows[0]
    demand = ResourceDemand(
        seats=first.seats, baggage_ml=first.baggage_ml, cargo_weight_g=first.cargo_weight_g, cargo_volume_ml=first.cargo_volume_ml
    )
    seqs = [row.segment_from_seq for row in rows]
    if seqs != list(range(seqs[0], seqs[0] + len(seqs))) or any(
        (row.seats, row.baggage_ml, row.cargo_weight_g, row.cargo_volume_ml)
        != (demand.seats, demand.baggage_ml, demand.cargo_weight_g, demand.cargo_volume_ml)
        for row in rows
    ):
        raise RuntimeError(f"booking {booking.id} allocations are not one contiguous uniform span")
    trips_service.release(session, trip_id, seqs[0], seqs[-1] + 1, demand)
    return True


def _release_fee(session: Session, booking: Booking, *, actor_user_id: int | None, side: ActorSide, command: str = "release") -> None:
    if booking.commission_status != CommissionStatus.HELD.value:
        return  # exempt stays exempt; captured/released are final here
    wallet_service.release_fee(session, booking_id=booking.id)
    _set_commission_status(session, booking, target=CommissionStatus.RELEASED, command=command, actor_user_id=actor_user_id, side=side)


def _listing_effects_after_cancel(
    session: Session, booking: Booking, listings: dict[int, Listing], *, side: ActorSide, actor_user_id: int | None, now: datetime
) -> None:
    if booking.request_listing_id is not None:
        request = listings.get(booking.request_listing_id)
        if request is not None and request.status == ListingStatus.FULFILLED.value:
            if side is ActorSide.CLIENT:
                marketplace_service.cancel_listing_for_booking(
                    session, listing=request, actor_user_id=actor_user_id, reason_code="booking_cancelled_by_client", now=now
                )
            elif rules.request_listing_reopens(
                cancelled_by=side,
                listing_expires_at=request.expires_at,
                departure_window_end=request.departure_window_end,
                now=now,
            ):
                marketplace_service.reopen_listing(session, listing=request, now=now)  # Q19 + client notified by listing/booking events
    if booking.supply_listing_id is not None:
        supply = listings.get(booking.supply_listing_id)
        if (
            supply is not None
            and supply.status == ListingStatus.FULFILLED.value
            and ensure_aware_utc(supply.expires_at) > now
            and ensure_aware_utc(supply.departure_window_end) > now
            and _offer_has_capacity(session, booking.trip_id, supply)
        ):
            marketplace_service.reopen_listing(session, listing=supply, now=now)


def _cancel_locked(
    session: Session,
    booking: Booking,
    *,
    trip: Trip,
    listings: dict[int, Listing],
    side: ActorSide,
    actor_user_id: int | None,
    reason_code: str,
    comment: str | None,
    fault_side: FaultSide,
    command: str,
    now: datetime,
) -> None:
    """One transaction (AC21): status, allocations release, fee release, listing effects, event."""
    _set_service_status(
        session, booking, target=PB.CANCELLED.value, command=command, actor_user_id=actor_user_id, side=side,
        now=now, reason=reason_code, emit=False,
    )
    booking.cancelled_at = now
    booking.cancelled_by_side = side.value
    booking.cancelled_by_user_id = actor_user_id
    booking.cancel_reason_code = reason_code[:64]
    booking.cancel_comment = comment
    booking.fault_side = fault_side.value
    _touch(booking, now)
    session.flush()
    _release_allocations(session, booking, trip.id, now)
    _release_fee(session, booking, actor_user_id=actor_user_id, side=side)
    session.flush()
    _listing_effects_after_cancel(session, booking, listings, side=side, actor_user_id=actor_user_id, now=now)
    _emit(
        session,
        booking,
        EventType.BOOKING_CANCELLED,
        {
            "service_type": booking.service_type,
            "trip_id": trips_service.trip_public_id(trip),
            "cancelled_by_side": side.value,
            "reason_code": reason_code[:64],
        },
        now,
    )


def _lock_booking_scope(session: Session, booking_id: int) -> tuple[Trip, dict[int, Listing], Booking]:
    """trip -> listings -> booking, then re-check the parents did not change (ADR-0017 §4)."""
    snapshot = get_booking(session, booking_id)
    trip = trips_service.lock_trip(session, snapshot.trip_id)
    listing_ids = [i for i in (snapshot.request_listing_id, snapshot.supply_listing_id) if i is not None]
    listings = {row.id: row for row in marketplace_service.lock_listings(session, listing_ids)}
    booking = lock_booking(session, booking_id)
    if booking.trip_id != trip.id:  # pragma: no cover - agreement columns are immutable (DB guard)
        raise DomainError(ErrorCode.VERSION_CONFLICT)
    return trip, listings, booking


def cancel_booking(
    session: Session,
    *,
    booking_public_id_value: str,
    actor_user_id: int,
    expected_version: int,
    reason_code: str,
    comment: str | None = None,
    as_operator: bool = False,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
) -> Booking:
    """B3 (client, driver) and B13 ``cancel`` (``ops.booking_cancel``, admin+). The comment passes the Q43 filter."""
    now = _now(now)
    if comment is not None:
        comment = marketplace_service.filter_free_text(
            session, actor_user_id=actor_user_id, field="comment", text=comment, warnings=warnings
        )
    snapshot = get_booking_by_public_id(session, booking_public_id_value)
    if as_operator:
        caps = identity_service.get_capabilities(session, actor_user_id, now=now)
        if not caps.has(Capability.OPS_BOOKING_CANCEL):
            raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.OPS_BOOKING_CANCEL.value})
        side = ActorSide.OPERATOR
    else:
        participant = participant_side(snapshot, actor_user_id)
        if participant is None:
            raise DomainError(ErrorCode.NOT_FOUND)
        side = participant
    if not (reason_code or "").strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason_code"})
    trip, listings, booking = _lock_booking_scope(session, snapshot.id)
    _check_version(booking.version, expected_version)
    if pending_no_show_review(session, booking.id) is not None and side is not ActorSide.OPERATOR:
        raise DomainError(ErrorCode.NO_SHOW_REVIEW_PENDING)  # Q19: only an operator cancels during a review
    rules.ensure_cancellable(booking.service_type, booking.service_status)
    _cancel_locked(
        session, booking, trip=trip, listings=listings, side=side, actor_user_id=actor_user_id, reason_code=reason_code.strip(),
        comment=comment, fault_side=rules.fault_side_for_cancel(side), command="cancel", now=now,
    )
    if as_operator:
        session.add(
            AuditLog(
                actor_id=actor_user_id, entity_type="booking", entity_id=None, action="booking_cancel_by_operator",
                details={"booking_id": booking_public_id(booking), "reason_code": reason_code.strip()},
            )
        )
        session.flush()
    return booking


# ==============================================================================================================
# Participant actions and proofs (B4, spec §11, ADR-0018 N5)
# ==============================================================================================================


@dataclass(frozen=True, slots=True)
class ActionInput:
    expected_version: int
    code: str | None = None
    evidence_file_ids: Sequence[str] = ()
    note: str | None = None
    contact_attempts: Sequence[dict[str, Any]] = ()
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProofFailure:
    """A wrong code. Recorded AFTER the savepoint rollback of the 4xx (see ``record_failed_proof_attempts``)."""

    booking_id: int
    proof_kind: str
    code_rotation: int
    actor_user_id: int


def _proof_keyring():  # noqa: ANN202 - KeyRing
    return proof_code_keyring()


def _proof_row(session: Session, booking: Booking, kind: ProofKind, *, lock: bool) -> BookingProof:
    stmt = select(BookingProof).where(BookingProof.booking_id == booking.id, BookingProof.proof_kind == kind.value)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    proof = session.execute(stmt).scalar_one_or_none()
    if proof is None:
        proof = BookingProof(
            booking_id=booking.id, proof_kind=kind.value, code_rotation=0, key_version=PROOF_CODE_KEY_VERSION, failed_attempts=0
        )
        session.add(proof)
        session.flush()  # the caller holds the booking lock, so concurrent creation is serialized
    return proof


def _verify_code(
    session: Session,
    booking: Booking,
    kind: ProofKind,
    *,
    code: str | None,
    actor_user_id: int,
    now: datetime,
    failures: list[ProofFailure] | None,
) -> BookingProof:
    proof = _proof_row(session, booking, kind, lock=True)
    if proof.accepted_at is not None:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "proof_already_accepted", "proof_kind": kind.value})
    rules.ensure_proof_attempts_left(proof.failed_attempts)
    if not code or not code.strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "code"})
    keyring = _proof_keyring()
    if not verify_proof_code(keyring, booking_public_id(booking), kind.value, proof.code_rotation, code.strip()):
        if failures is not None:
            failures.append(ProofFailure(booking.id, kind.value, proof.code_rotation, actor_user_id))
        raise DomainError(
            ErrorCode.PROOF_INVALID,
            details={"proof_kind": kind.value, "attempts_left": max(0, rules.MAX_PROOF_ATTEMPTS - proof.failed_attempts - 1)},
        )
    proof.accepted_at = now
    proof.actor_user_id = actor_user_id
    proof.code_hash = proof_code_hash(keyring.current, booking_public_id(booking), kind.value, code.strip())
    proof.updated_at = now
    session.add(
        BookingProofAttempt(
            booking_id=booking.id, proof_kind=kind.value, code_rotation=proof.code_rotation, actor_user_id=actor_user_id, succeeded=True
        )
    )
    session.flush()
    return proof


def record_failed_proof_attempts(session: Session, failures: Sequence[ProofFailure]) -> None:
    """Persist wrong-code attempts in the same transaction after the command's savepoint was rolled back.

    The domain 4xx (``PROOF_INVALID``) rolls back its savepoint (ADR-0005), which would also undo an attempt
    counter written inside it; the v2 runner calls this afterwards so the attempt limit is real (spec §11).
    Lock order: booking -> proof.
    """
    for failure in failures:
        booking = lock_booking(session, failure.booking_id)
        proof = _proof_row(session, booking, ProofKind(failure.proof_kind), lock=True)
        if proof.accepted_at is None and proof.code_rotation == failure.code_rotation:
            proof.failed_attempts = min(rules.MAX_PROOF_ATTEMPTS, proof.failed_attempts + 1)
            proof.updated_at = utc_now()
        session.add(
            BookingProofAttempt(
                booking_id=failure.booking_id,
                proof_kind=failure.proof_kind,
                code_rotation=failure.code_rotation,
                actor_user_id=failure.actor_user_id,
                succeeded=False,
            )
        )
    session.flush()


def booking_codes(session: Session, *, booking_public_id_value: str, viewer_user_id: int) -> list[tuple[ProofKind, str]]:
    """B5: codes are recomputed for their owner only (the client/sender); the driver never receives a code."""
    booking = get_booking_by_public_id(session, booking_public_id_value)
    side = participant_side(booking, viewer_user_id)
    if side is None:
        if identity_service.get_capabilities(session, viewer_user_id).has(Capability.OPS_VIEW):
            raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "codes_are_for_the_code_owner"})
        raise DomainError(ErrorCode.NOT_FOUND)
    if side is not ActorSide.CLIENT:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "driver_cannot_see_codes"})
    if rules.is_terminal_service_status(booking.service_status):
        return []
    keyring = _proof_keyring()
    proofs = {
        row.proof_kind: row
        for row in session.execute(select(BookingProof).where(BookingProof.booking_id == booking.id)).scalars()
    }
    result: list[tuple[ProofKind, str]] = []
    for kind in rules.CLIENT_CODE_KINDS[ServiceType(booking.service_type)]:
        row = proofs.get(kind.value)
        if row is not None and row.accepted_at is not None:
            continue
        if kind is ProofKind.RETURN_CODE and booking.service_status != PC.RETURN_REQUIRED.value:
            continue
        rotation = row.code_rotation if row is not None else 0
        result.append((kind, derive_proof_code(keyring.current, booking_public_id(booking), kind.value, rotation)))
    return result


def _reissuable_kind(proof_kind: ProofKind | str | None) -> ProofKind:
    try:
        kind = ProofKind(proof_kind) if proof_kind is not None else None
    except ValueError:
        kind = None
    if kind is None or kind not in proof_policy.REISSUABLE_PROOF_KINDS:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "proof_kind", "reason": "not_reissuable"})
    return kind


def _reissue_locked(
    session: Session,
    booking: Booking,
    kind: ProofKind,
    *,
    actor_user_id: int,
    side: ActorSide,
    reason: str | None,
    self_service: bool,
    now: datetime,
) -> str:
    """Rotation + 1 (the old code stops verifying), failed attempts reset, history + audit + event (never the code).

    The caller holds the booking lock (booking -> proof). Self-service is rate-limited by ``proofs.reissue_decision``.
    """
    service = ServiceType(booking.service_type)
    if kind not in rules.CLIENT_CODE_KINDS[service]:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "proof_kind", "reason": "not_a_code_of_this_service"})
    if rules.is_terminal_service_status(booking.service_status):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "booking_terminal", "service_status": booking.service_status})
    if kind is ProofKind.RETURN_CODE and booking.service_status != PC.RETURN_REQUIRED.value:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "return_not_required", "proof_kind": kind.value})
    proof = _proof_row(session, booking, kind, lock=True)
    if proof.accepted_at is not None:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "proof_already_accepted", "proof_kind": kind.value})
    if self_service:
        previous = session.execute(
            select(BookingProofReissue.created_at).where(
                BookingProofReissue.booking_id == booking.id,
                BookingProofReissue.proof_kind == kind.value,
                BookingProofReissue.self_service.is_(True),
            )
        ).scalars().all()
        decision = proof_policy.reissue_decision(previous, now)
        if not decision.allowed:
            raise DomainError(ErrorCode.PROOF_REISSUE_LIMITED, details=decision.error_details())
    from_rotation = proof.code_rotation
    proof.code_rotation = from_rotation + 1
    proof.failed_attempts = 0
    proof.key_version = PROOF_CODE_KEY_VERSION
    proof.updated_at = now
    session.add(
        BookingProofReissue(
            booking_id=booking.id, proof_kind=kind.value, from_rotation=from_rotation, to_rotation=proof.code_rotation,
            actor_user_id=actor_user_id, actor_side=side.value, self_service=self_service, reason=reason, created_at=now,
        )
    )
    _history(session, booking, machine="proof", from_status=f"rotation_{from_rotation}", to_status=f"rotation_{proof.code_rotation}",
             command="reissue_proof_code", actor_user_id=actor_user_id, side=side, reason=reason)
    session.add(
        AuditLog(actor_id=actor_user_id, entity_type="booking", entity_id=None, action="booking_proof_code_reissued",
                 details={"booking_id": booking_public_id(booking), "proof_kind": kind.value, "from_rotation": from_rotation,
                          "to_rotation": proof.code_rotation, "actor_side": side.value, "self_service": self_service,
                          "reason": reason})
    )
    session.flush()
    _emit(session, booking, EventType.BOOKING_PROOF_CODE_REISSUED,
          {"service_type": booking.service_type, "proof_kind": kind.value, "code_rotation": proof.code_rotation,
           "requested_by_side": side.value}, now)
    return derive_proof_code(_proof_keyring().current, booking_public_id(booking), kind.value, proof.code_rotation)


def reissue_proof_code(
    session: Session,
    *,
    booking_public_id_value: str,
    actor_user_id: int,
    proof_kind: ProofKind | str,
    reason: str | None = None,
    now: datetime | None = None,
    warnings: list[dict] | None = None,
) -> tuple[Booking, ProofKind, str]:
    """B5a self-service reissue by the code owner (passenger: boarding; sender: pickup/delivery/return).

    Driver -> 403; staff -> 403 (operators use B13 ``reissue_proof_code``); stranger -> 404; accepted proof -> 409
    ``INVALID_STATE_TRANSITION``; over the limit -> 429 ``PROOF_REISSUE_LIMITED`` (``details {retry_after_s,
    reissues_left}``). Returns the new code for its owner only.
    """
    now = _now(now)
    kind = _reissuable_kind(proof_kind)
    snapshot = get_booking_by_public_id(session, booking_public_id_value)
    side = participant_side(snapshot, actor_user_id)
    if side is None:
        if identity_service.get_capabilities(session, actor_user_id, now=now).has(Capability.OPS_VIEW):
            raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "operators_use_reissue_proof_code_command"})
        raise DomainError(ErrorCode.NOT_FOUND)
    if side is not ActorSide.CLIENT:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "driver_cannot_reissue_codes"})
    if reason is not None and reason.strip():
        reason = marketplace_service.filter_free_text(
            session, actor_user_id=actor_user_id, field="reason", text=reason.strip(), warnings=warnings
        )
    else:
        reason = None
    booking = lock_booking(session, snapshot.id)
    code = _reissue_locked(session, booking, kind, actor_user_id=actor_user_id, side=side, reason=reason,
                           self_service=True, now=now)
    return booking, kind, code


def _require_driver_operate(session: Session, booking: Booking, actor_user_id: int, now: datetime) -> None:
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    if not caps.has(Capability.TRIP_OPERATE):  # obligation capability: kept during an eligibility block (D16)
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.TRIP_OPERATE.value})


def _open_custody(session: Session, booking: Booking, *, reason_code: str, actor_user_id: int | None, side: ActorSide, now: datetime) -> CustodyCase:
    case = open_custody_case(session, booking.id, lock=True)
    if case is not None:
        return case
    case = CustodyCase(booking_id=booking.id, status=CustodyCaseStatus.OPEN.value, opened_reason_code=reason_code[:64],
                       opened_by=actor_user_id, opened_at=now)
    session.add(case)
    _flush_or_translate(session, {OPEN_CUSTODY_INDEX: lambda: DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "custody_case_open"})})
    _history(session, booking, machine="custody_case", from_status=None, to_status=CustodyCaseStatus.OPEN.value,
             command=reason_code[:48], actor_user_id=actor_user_id, side=side)
    _emit(
        session, booking, EventType.BOOKING_CUSTODY_CASE_OPENED,
        {"trip_id": _trip_public_id(session, booking.trip_id), "service_status": booking.service_status, "reason_code": reason_code[:64]},
        now,
    )
    return case


def _resolve_custody(session: Session, booking: Booking, *, actor_user_id: int | None, side: ActorSide, note: str | None, now: datetime) -> bool:
    case = open_custody_case(session, booking.id, lock=True)
    if case is None:
        return False
    CUSTODY_CASE.assert_transition(case.status, CustodyCaseStatus.RESOLVED.value, "resolve_custody_case")
    case.status = CustodyCaseStatus.RESOLVED.value
    case.resolved_by = actor_user_id
    case.resolved_at = now
    case.resolution_note = note
    case.updated_at = now
    _history(session, booking, machine="custody_case", from_status=CustodyCaseStatus.OPEN.value,
             to_status=CustodyCaseStatus.RESOLVED.value, command="resolve_custody_case", actor_user_id=actor_user_id, side=side)
    session.flush()
    return True


def _complete(session: Session, booking: Booking, *, command: str, actor_user_id: int | None, side: ActorSide, now: datetime,
              reason: str | None = None) -> None:
    """``arrived|delivered -> completed``; capture in the same transaction unless a serious dispute is open (AC20).

    Q66: when the dispute check is unavailable the service still completes, the commission stays ``held`` and the
    booking enters the ``finance_review`` queue (staff event ``commission.finance_review_required``); finance closes it
    with ``finalize_fee``.
    """
    _set_service_status(session, booking, target=PB.COMPLETED.value, command=command, actor_user_id=actor_user_id,
                        side=side, now=now, reason=reason, emit=False)
    booking.completed_at = now
    _touch(booking, now)
    session.flush()
    state = dispute_state(session, booking.id) if booking.commission_status == CommissionStatus.HELD.value else "clear"
    if rules.capture_on_completion(commission_status=booking.commission_status, blocking_dispute_open=state != "clear"):
        wallet_service.capture_fee(session, booking_id=booking.id, actor_user_id=actor_user_id)
        _set_commission_status(session, booking, target=CommissionStatus.CAPTURED, command="capture",
                               actor_user_id=None, side=ActorSide.SYSTEM)
        session.flush()
    elif state == "unavailable":
        reason_code = CommissionReviewReason.DISPUTE_MODULE_UNAVAILABLE
        booking.finance_review_reason = reason_code.value
        booking.finance_review_at = now
        session.flush()
        _emit(session, booking, EventType.COMMISSION_FINANCE_REVIEW_REQUIRED,
              {"booking_id": booking_public_id(booking), "reason_code": reason_code.value,
               "amount_minor": booking.commission_minor, "currency": booking.currency}, now)
    _emit(
        session, booking, EventType.BOOKING_COMPLETED,
        {"service_type": booking.service_type, "trip_id": _trip_public_id(session, booking.trip_id),
         "commission_status": booking.commission_status},
        now,
    )


def perform_action(
    session: Session,
    *,
    booking_public_id_value: str,
    actor_user_id: int,
    action: BookingAction | str,
    data: ActionInput,
    now: datetime | None = None,
    proof_failures: list[ProofFailure] | None = None,
) -> Booking:
    """B4 participant actions (STATE_MACHINES §4-§5)."""
    now = _now(now)
    try:
        action = BookingAction(action)
    except ValueError:
        raise DomainError(ErrorCode.NOT_FOUND) from None
    snapshot = get_booking_by_public_id(session, booking_public_id_value)
    side = participant_side(snapshot, actor_user_id)
    if side is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if side not in rules.ACTION_SIDES[action]:
        raise DomainError(ErrorCode.FORBIDDEN, details={"action": action.value, "side": side.value})
    if side is ActorSide.DRIVER:
        _require_driver_operate(session, snapshot, actor_user_id, now)
    service = ServiceType(snapshot.service_type)
    rules.action_target(service, action, snapshot.service_status)  # rejects actions of the other service

    booking = lock_booking(session, snapshot.id)
    _check_version(booking.version, data.expected_version)
    status = booking.service_status

    if action is BookingAction.ARRIVE_AT_PICKUP:
        if status not in rules.PRE_SERVICE_STATUSES:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"from": status, "command": action.value})
        if booking.arrived_at_pickup_at is None:
            booking.arrived_at_pickup_at = ensure_aware_utc(data.observed_at) if data.observed_at else now
            _touch(booking, now)
            session.flush()
            # Wave 3 (Q44 "Keldim"): once per booking, allowlisted payload only (no coordinates, phones or names).
            _emit(session, booking, EventType.BOOKING_DRIVER_ARRIVED,
                  {"service_type": booking.service_type, "trip_id": _trip_public_id(session, booking.trip_id),
                   "arrived_at": ensure_aware_utc(booking.arrived_at_pickup_at).isoformat()}, now)
        session.flush()
        return booking

    if action is BookingAction.REPORT_NO_SHOW:
        if status != PB.AWAITING_PICKUP.value:
            raise DomainError(ErrorCode.NO_SHOW_NOT_ALLOWED, details={"reason": "not_awaiting_pickup", "service_status": status})
        if pending_no_show_review(session, booking.id) is not None:
            raise DomainError(ErrorCode.NO_SHOW_REVIEW_PENDING)
        trip = trips_service.get_trip(session, booking.trip_id)
        wait_until = rules.check_no_show_report(
            arrived_at_pickup_at=booking.arrived_at_pickup_at,
            pickup_window_start=booking.pickup_window_start,
            pickup_window_end=booking.pickup_window_end,
            wait_minutes=trip.pickup_wait_minutes,
            contact_attempts=len(data.contact_attempts),
            now=now,
        )
        session.add(
            NoShowReview(
                booking_id=booking.id,
                status=NoShowReviewStatus.PENDING.value,
                reported_by=actor_user_id,
                arrived_at=ensure_aware_utc(booking.arrived_at_pickup_at),
                wait_until=wait_until,
                contact_attempts=[dict(item) for item in data.contact_attempts],
                evidence_file_ids=list(data.evidence_file_ids),
                note=data.note,
            )
        )
        _flush_or_translate(session, {PENDING_REVIEW_INDEX: lambda: DomainError(ErrorCode.NO_SHOW_REVIEW_PENDING)})
        _history(session, booking, machine="no_show_review", from_status=None, to_status=NoShowReviewStatus.PENDING.value,
                 command="report_no_show", actor_user_id=actor_user_id, side=side)
        _touch(booking, now)
        session.flush()
        _emit(session, booking, EventType.BOOKING_NO_SHOW_REPORTED,
              {"trip_id": trips_service.trip_public_id(trip), "review_status": NoShowReviewStatus.PENDING.value}, now)
        return booking

    target = rules.action_target(service, action, status)
    assert target is not None
    if action in (BookingAction.BOARD, BookingAction.PICK_UP):
        # BR blocker 4: the service starts only on a started trip. Checked before the code, so no attempt is counted.
        trip = trips_service.get_trip(session, booking.trip_id)
        if not service_start_allowed(trip.status):
            raise DomainError(ErrorCode.TRIP_NOT_STARTED, details={"trip_status": trip.status, "command": action.value})
    if action is BookingAction.PICK_UP and parcel_receiver_for(session, booking) is None:
        # W21-4 (wave 3.1): a parcel is never picked up without a receiver - A1 asks the client for it on the
        # proposal (trip offers) or at publish (requests), so this is the last line, not the normal path.
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "receiver", "reason": "receiver_required"})
    if action is BookingAction.MARK_AWAITING_PICKUP:
        trip = trips_service.get_trip(session, booking.trip_id)
        if trip.status not in (TripStatus.PLANNED.value, TripStatus.BOARDING.value):
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "trip", "from": trip.status})

    proof_kind = rules.ACTION_PROOF_KIND.get(action)
    if proof_kind is not None:
        rules.service_machine(service).assert_transition(status, target, action.value)  # state before code
        _verify_code(session, booking, proof_kind, code=data.code, actor_user_id=actor_user_id, now=now, failures=proof_failures)

    if action is BookingAction.COMPLETE:
        _complete(session, booking, command="complete", actor_user_id=actor_user_id, side=side, now=now)
        return booking

    _set_service_status(session, booking, target=target, command=action.value, actor_user_id=actor_user_id, side=side, now=now,
                        reason=data.note)
    if action in (BookingAction.DROP_OFF, BookingAction.DELIVER):
        booking.service_ended_at = now
    _touch(booking, now)
    session.flush()

    if action is BookingAction.BOARD:
        review = pending_no_show_review(session, booking.id, lock=True)
        if review is not None:  # the client did show up: the report closes (STATE_MACHINES §4)
            NO_SHOW_REVIEW.assert_transition(review.status, NoShowReviewStatus.REJECTED.value, "system_close_boarded")
            review.status = NoShowReviewStatus.REJECTED.value
            review.decided_at = now
            review.decision_command = "system_close_boarded"
            review.updated_at = now
            _history(session, booking, machine="no_show_review", from_status=NoShowReviewStatus.PENDING.value,
                     to_status=NoShowReviewStatus.REJECTED.value, command="system_close_boarded", actor_user_id=None, side=ActorSide.SYSTEM)
    if action in (BookingAction.BOARD, BookingAction.PICK_UP):
        _emit(session, booking, EventType.BOOKING_STARTED,
              {"service_type": booking.service_type, "trip_id": _trip_public_id(session, booking.trip_id), "service_status": booking.service_status}, now)
    if action is BookingAction.REPORT_DELIVERY_FAILED:
        _open_custody(session, booking, reason_code="delivery_failed", actor_user_id=actor_user_id, side=side, now=now)
    if action is BookingAction.RETURN_TO_SENDER:
        _resolve_custody(session, booking, actor_user_id=None, side=ActorSide.SYSTEM, note="returned_with_code", now=now)
    if action is BookingAction.DELIVER:
        _resolve_custody(session, booking, actor_user_id=None, side=ActorSide.SYSTEM, note="delivered_with_code", now=now)
        # Q65: `delivered` does not complete: the sender confirms (B4 complete) or, DELIVERED_OPERATOR_QUEUE_AFTER later,
        # the booking is in the operator queue (complete_with_evidence). No capture here; the version grew once.
    session.flush()
    return booking


# ==============================================================================================================
# Operator commands (B13; Q7, N3, D1, AC42, Q17)
# ==============================================================================================================


def operator_command(
    session: Session,
    *,
    booking_public_id_value: str,
    actor_user_id: int,
    command: OperatorBookingCommand | str,
    expected_version: int,
    reason: str,
    evidence_file_ids: Sequence[str] = (),
    fee_mode: Literal["capture", "release", "partial"] | None = None,
    proof_kind: ProofKind | str | None = None,
    now: datetime | None = None,
) -> Booking:
    now = _now(now)
    try:
        command = OperatorBookingCommand(command)
    except ValueError:
        raise DomainError(ErrorCode.NOT_FOUND) from None
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    required = OPERATOR_COMMAND_CAPABILITY[command]
    if not caps.has(required):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": required.value})
    reason = (reason or "").strip()
    if not reason:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    if command is OperatorBookingCommand.REISSUE_PROOF_CODE:
        # BR blocker 3: operator reissue - reason required, audited, not rate-limited; the code is never returned.
        kind = _reissuable_kind(proof_kind)
        booking = lock_booking(session, get_booking_by_public_id(session, booking_public_id_value).id)
        _check_version(booking.version, expected_version)
        _reissue_locked(session, booking, kind, actor_user_id=actor_user_id, side=ActorSide.OPERATOR, reason=reason,
                        self_service=False, now=now)
        return booking
    if command is OperatorBookingCommand.CANCEL:
        return cancel_booking(
            session, booking_public_id_value=booking_public_id_value, actor_user_id=actor_user_id,
            expected_version=expected_version, reason_code="operator_cancel", comment=reason, as_operator=True, now=now,
        )
    snapshot = get_booking_by_public_id(session, booking_public_id_value)
    side = ActorSide.OPERATOR

    if command in (OperatorBookingCommand.CONFIRM_NO_SHOW, OperatorBookingCommand.REJECT_NO_SHOW):
        trip, listings, booking = _lock_booking_scope(session, snapshot.id)
        _check_version(booking.version, expected_version)
        review = pending_no_show_review(session, booking.id, lock=True)
        if review is None:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "no_show_review", "command": command.value})
        if command is OperatorBookingCommand.CONFIRM_NO_SHOW:
            NO_SHOW_REVIEW.assert_transition(review.status, NoShowReviewStatus.CONFIRMED.value, "confirm_no_show")
            _set_service_status(session, booking, target=PB.NO_SHOW.value, command="confirm_no_show", actor_user_id=actor_user_id,
                                side=side, now=now, reason=reason)
            review.status = NoShowReviewStatus.CONFIRMED.value
            _decide_review(session, booking, review, command="confirm_no_show", actor_user_id=actor_user_id, reason=reason, now=now)
            _touch(booking, now)
            session.flush()
            _release_allocations(session, booking, trip.id, now)
            _release_fee(session, booking, actor_user_id=actor_user_id, side=side)  # pilot: no penalty (D2)
        else:
            outcome = reject_no_show_outcome(trip.status)
            NO_SHOW_REVIEW.assert_transition(review.status, NoShowReviewStatus.REJECTED.value, "reject_no_show")
            review.status = NoShowReviewStatus.REJECTED.value
            _decide_review(session, booking, review, command="reject_no_show", actor_user_id=actor_user_id, reason=reason, now=now)
            if outcome.booking_status == PB.CANCELLED.value:
                # N3: the trip is over, nobody can board: cancel now with driver fault.
                _cancel_locked(session, booking, trip=trip, listings=listings, side=side, actor_user_id=actor_user_id,
                               reason_code="no_show_rejected", comment=reason, fault_side=FaultSide(outcome.fault_side),
                               command="reject_no_show", now=now)
            else:
                _touch(booking, now)
        _audit_operator(session, booking, command, actor_user_id, reason)
        session.flush()
        return booking

    booking = lock_booking(session, snapshot.id)
    _check_version(booking.version, expected_version)
    service = ServiceType(booking.service_type)

    if command is OperatorBookingCommand.COMPLETE_WITH_EVIDENCE:
        proof = _proof_row(session, booking, ProofKind.OPERATOR_EVIDENCE, lock=True)
        if proof.accepted_at is None:
            proof.accepted_at = now
            proof.actor_user_id = actor_user_id
            proof.evidence_file_ids = list(evidence_file_ids)
            proof.note = reason
            proof.updated_at = now
        _complete(session, booking, command="complete_with_evidence", actor_user_id=actor_user_id, side=side, now=now, reason=reason)
    elif command is OperatorBookingCommand.DROP_OFF:
        if service is not ServiceType.PASSENGER:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"command": command.value, "service_type": service.value})
        _set_service_status(session, booking, target=PB.ARRIVED.value, command="drop_off", actor_user_id=actor_user_id,
                            side=side, now=now, reason=reason)
        booking.service_ended_at = now
        _touch(booking, now)
    elif command is OperatorBookingCommand.REQUIRE_RETURN:
        if service is not ServiceType.PARCEL:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"command": command.value, "service_type": service.value})
        _set_service_status(session, booking, target=PC.RETURN_REQUIRED.value, command="require_return",
                            actor_user_id=actor_user_id, side=side, now=now, reason=reason)
        _touch(booking, now)
        session.flush()
        _open_custody(session, booking, reason_code="return_required", actor_user_id=actor_user_id, side=side, now=now)
    elif command is OperatorBookingCommand.RETURN_TO_SENDER:
        if service is not ServiceType.PARCEL:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"command": command.value, "service_type": service.value})
        _set_service_status(session, booking, target=PC.RETURNED.value, command="return_to_sender",
                            actor_user_id=actor_user_id, side=side, now=now, reason=reason)
        _touch(booking, now)
        session.flush()
        _resolve_custody(session, booking, actor_user_id=actor_user_id, side=side, note=reason, now=now)
    elif command is OperatorBookingCommand.RESOLVE_CUSTODY_CASE:
        if booking.service_status not in (PC.DELIVERED.value, PC.COMPLETED.value, PC.RETURNED.value):
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                              details={"machine": "custody_case", "command": command.value, "service_status": booking.service_status})
        if not _resolve_custody(session, booking, actor_user_id=actor_user_id, side=side, note=reason, now=now):
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "custody_case", "reason": "no_open_case"})
        _touch(booking, now)
    elif command is OperatorBookingCommand.FINALIZE_FEE:
        # Q17: finance.fee_finalize was required above; A3's capture/release are capability-free building blocks.
        rules.ensure_fee_finalizable(booking.service_status)
        if booking.commission_status != CommissionStatus.HELD.value:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                              details={"machine": "commission", "from": booking.commission_status, "command": "finalize_fee"})
        if fee_mode in ("capture", "release") and dispute_state(session, booking.id) == "open":
            # BR M2 (§9.5, AC26): no money decision (capture or release) while a blocking dispute is open; the dispute
            # decision comes first. No probe registered ("unavailable") keeps the Q74 manual finance path.
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION,
                              details={"machine": "commission", "command": "finalize_fee", "reason": "blocking_dispute_open"})
        if fee_mode == "capture":
            wallet_service.capture_fee(session, booking_id=booking.id, actor_user_id=actor_user_id)
            _set_commission_status(session, booking, target=CommissionStatus.CAPTURED, command="capture",
                                   actor_user_id=actor_user_id, side=side)
        elif fee_mode == "release":
            _release_fee(session, booking, actor_user_id=actor_user_id, side=side)
        else:
            raise DomainError(ErrorCode.VALIDATION_ERROR,
                              details={"field": "fee_decision.mode", "reason": "capture_or_release; partial goes through reversals (W8/W16)"})
        _touch(booking, now)
    else:  # pragma: no cover - every command is handled above
        raise DomainError(ErrorCode.NOT_FOUND)
    _audit_operator(session, booking, command, actor_user_id, reason)
    session.flush()
    return booking


def _decide_review(session: Session, booking: Booking, review: NoShowReview, *, command: str, actor_user_id: int, reason: str, now: datetime) -> None:
    review.decided_by = actor_user_id
    review.decided_at = now
    review.decision_command = command
    review.decision_reason = reason
    review.updated_at = now
    _history(session, booking, machine="no_show_review", from_status=NoShowReviewStatus.PENDING.value, to_status=review.status,
             command=command, actor_user_id=actor_user_id, side=ActorSide.OPERATOR, reason=reason)
    session.flush()


def _audit_operator(session: Session, booking: Booking, command: OperatorBookingCommand, actor_user_id: int, reason: str) -> None:
    session.add(
        AuditLog(actor_id=actor_user_id, entity_type="booking", entity_id=None, action=f"booking_{command.value}",
                 details={"booking_id": booking_public_id(booking), "reason": reason, "version": booking.version})
    )


# ==============================================================================================================
# Trip actions and manifest (T9, T10; AC42, D1)
# ==============================================================================================================

TRIP_ACTION_TARGET: dict[str, TripStatus] = {
    "start_boarding": TripStatus.BOARDING,
    "depart": TripStatus.IN_PROGRESS,
    "complete": TripStatus.COMPLETED,
    "interrupt": TripStatus.INTERRUPTED,
    "resume": TripStatus.IN_PROGRESS,
    "cancel": TripStatus.CANCELLED,
}
REASON_REQUIRED_TRIP_ACTIONS = frozenset({"interrupt", "resume", "cancel"})


def _trip_bookings(session: Session, trip_id: int, *, lock: bool) -> list[Booking]:
    stmt = select(Booking).where(Booking.trip_id == trip_id).order_by(Booking.id)
    if lock:
        stmt = stmt.with_for_update(key_share=True).execution_options(populate_existing=True)
    return list(session.execute(stmt).scalars())


def _unresolved_for_completion(session: Session, bookings: Sequence[Booking]) -> list[str]:
    blocked = []
    for booking in bookings:
        if booking_blocks_trip_completion(
            booking.service_type,
            booking.service_status,
            has_open_custody_case=open_custody_case(session, booking.id) is not None,
            has_pending_no_show_review=pending_no_show_review(session, booking.id) is not None,
        ):
            blocked.append(booking_public_id(booking))
    return blocked


def trip_action(
    session: Session,
    *,
    trip_public_id_value: str,
    actor_user_id: int,
    action: str,
    expected_version: int,
    reason: str | None = None,
    now: datetime | None = None,
) -> Trip:
    """T9. Trip completion never changes a booking status (AC42)."""
    now = _now(now)
    if action not in TRIP_ACTION_TARGET:
        raise DomainError(ErrorCode.NOT_FOUND)
    target = TRIP_ACTION_TARGET[action]
    snapshot = trips_service.get_trip_by_public_id(session, trip_public_id_value)
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    is_driver = snapshot.driver_user_id == actor_user_id
    if is_driver:
        if not caps.has(Capability.TRIP_OPERATE):
            raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.TRIP_OPERATE.value})
        side = ActorSide.DRIVER
    else:
        operator_caps = {"cancel": Capability.OPS_BOOKING_CANCEL}
        needed = operator_caps.get(action, Capability.OPS_BOOKING_COMMAND)
        if action not in ("interrupt", "resume", "complete", "cancel") or not caps.has(needed):
            if caps.has(Capability.OPS_VIEW):
                raise DomainError(ErrorCode.FORBIDDEN, details={"capability": needed.value})
            raise DomainError(ErrorCode.NOT_FOUND)
        side = ActorSide.OPERATOR
    reason = (reason or "").strip() or None
    if (action in REASON_REQUIRED_TRIP_ACTIONS or (side is ActorSide.OPERATOR and action == "complete")) and not reason:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})

    trip = trips_service.lock_trip(session, snapshot.id)
    if trip.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": trip.version})
    TRIP.assert_transition(trip.status, target.value, action)
    if action == "complete" and trip.status == TripStatus.INTERRUPTED.value and side is not ActorSide.OPERATOR:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "operator_completes_interrupted_trip"})
    if action == "start_boarding" and now < rules.boarding_opens_at(trip.planned_start_at):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "boarding_window_not_open",
                                                                       "opens_at": rules.boarding_opens_at(trip.planned_start_at).isoformat()})

    listings: dict[int, Listing] = {}
    if action == "cancel":
        listing_ids = sorted({row.id for row in marketplace_service.listings_for_trip(session, trip.id)}
                             | {i for b in _trip_bookings(session, trip.id, lock=False) for i in (b.request_listing_id, b.supply_listing_id) if i})
        listings = {row.id: row for row in marketplace_service.lock_listings(session, listing_ids)}
        marketplace_service.expire_threads_for_trip(session, trip.id, reason="trip_cancelled", now=now)
    bookings = _trip_bookings(session, trip.id, lock=True)

    if action == "start_boarding":
        previous = trips_service.transition_trip(session, trip=trip, target=target, command=action, reason=reason, now=now)
        for booking in bookings:
            if booking.service_status == PB.CONFIRMED.value:
                _set_service_status(session, booking, target=PB.AWAITING_PICKUP.value, command="mark_awaiting_pickup",
                                    actor_user_id=None, side=ActorSide.SYSTEM, now=now)
                _touch(booking, now)
    elif action == "depart":
        pending = [booking_public_id(b) for b in bookings if b.service_status == PB.CONFIRMED.value]
        if pending:
            raise DomainError(ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS, details={"bookings": pending, "reason": "bookings_still_confirmed"})
        previous = trips_service.transition_trip(session, trip=trip, target=target, command=action, reason=reason, now=now)
    elif action == "complete":
        blocked = _unresolved_for_completion(session, bookings)
        if blocked:
            raise DomainError(ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS, details={"bookings": blocked})
        previous = trips_service.transition_trip(session, trip=trip, target=target, command=action, reason=reason, now=now)
    elif action == "cancel":
        # BR blocker 4: a person or parcel in (or just out of) the vehicle blocks the cancel from ANY trip status.
        busy = [booking_public_id(b) for b in bookings if booking_blocks_trip_cancel(b.service_type, b.service_status)]
        if busy:
            raise DomainError(ErrorCode.TRIP_HAS_UNRESOLVED_BOOKINGS, details={"bookings": busy, "reason": "service_in_progress"})
        _refuse_trip_cancel_with_pending_no_show_review(session, bookings)
        for booking in bookings:
            if booking.service_status in rules.PRE_SERVICE_STATUSES:
                _cancel_locked(session, booking, trip=trip, listings=listings, side=side, actor_user_id=actor_user_id,
                               reason_code="trip_cancelled", comment=reason,
                               fault_side=FaultSide.DRIVER if side is ActorSide.DRIVER else FaultSide.NONE, command="cancel", now=now)
        for listing in listings.values():
            if listing.trip_id == trip.id and listing.kind == ListingKind.TRIP_OFFER.value and listing.status in OPEN_LISTING_STATUSES:
                marketplace_service.cancel_listing_for_booking(session, listing=listing, actor_user_id=actor_user_id, reason_code="trip_cancelled", now=now)
        previous = trips_service.transition_trip(session, trip=trip, target=target, command=action, reason=reason, now=now)
    else:  # interrupt, resume: bookings unchanged
        previous = trips_service.transition_trip(session, trip=trip, target=target, command=action, reason=reason, now=now)

    if trip.status in (TripStatus.COMPLETED.value, TripStatus.CANCELLED.value):
        _close_tracking_sessions(session, trip.id, now)  # wave 3: A6 sessions end with the trip (same transaction)
    platform_service.enqueue_event(
        session,
        EventEnvelope(EventType.TRIP_STATUS_CHANGED, "trip", trips_service.trip_public_id(trip), trip.version, now,
                      {"from_status": previous, "to_status": trip.status, "reason_code": action}),
        aggregate_id=trip.id,
    )
    if side is ActorSide.OPERATOR:
        session.add(AuditLog(actor_id=actor_user_id, entity_type="trip", entity_id=None, action=f"trip_{action}_by_operator",
                             details={"trip_id": trips_service.trip_public_id(trip), "reason": reason}))
    session.flush()
    return trip


def _refuse_trip_cancel_with_pending_no_show_review(session: Session, bookings: Sequence[Booking]) -> None:
    """Q19/Q7, BR blocker 5 (integrator interpretation, STATE_MACHINES §11): a trip cancel NEVER decides a pending
    no-show review. While any booking of the trip has one, the cancel is refused (409 NO_SHOW_REVIEW_PENDING,
    ``details.bookings[]``); the operator first runs ``confirm_no_show`` / ``reject_no_show``, then cancels."""
    if not TRIP_CANCEL_REFUSED_WITH_PENDING_NO_SHOW_REVIEW:  # pragma: no cover - contract constant
        return
    pending = [booking_public_id(b) for b in bookings if pending_no_show_review(session, b.id) is not None]
    if pending:
        raise DomainError(ErrorCode.NO_SHOW_REVIEW_PENDING, details={"bookings": pending})


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    booking: Booking
    client_first_name: str
    contact_phone: str | None


def trip_manifest(session: Session, *, trip_public_id_value: str, viewer_user_id: int, now: datetime | None = None) -> tuple[Trip, list[ManifestEntry]]:
    """T10: the driver (or staff) sees who is picked up and dropped where; phones follow Q44."""
    now = _now(now)
    trip = trips_service.get_trip_by_public_id(session, trip_public_id_value)
    caps = identity_service.get_capabilities(session, viewer_user_id, now=now)
    if trip.driver_user_id == viewer_user_id:
        if not caps.has(Capability.TRIP_OPERATE):
            raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.TRIP_OPERATE.value})
    elif not caps.has(Capability.OPS_VIEW):
        raise DomainError(ErrorCode.NOT_FOUND)
    entries: list[ManifestEntry] = []
    users = identity_service.user_refs(session, {b.client_user_id for b in _trip_bookings(session, trip.id, lock=False)})
    for booking in _trip_bookings(session, trip.id, lock=False):
        if booking.service_status == PB.CANCELLED.value:
            continue
        visibility = rules.contact_visibility(service_started_at=booking.service_started_at,
                                              service_terminal_at=booking.service_terminal_at, now=now)
        disclosure = rules.phone_disclosure(booking.service_type, visibility)
        phone = None
        if booking.service_type == ServiceType.PASSENGER.value and disclosure.client_phone_to_driver:
            phone = identity_service.get_user_summary(session, booking.client_user_id).phone
        elif booking.service_type == ServiceType.PARCEL.value and disclosure.receiver_phone_to_driver:
            receiver = parcel_receiver_for(session, booking)
            phone = receiver[1] if receiver is not None else None
        entries.append(ManifestEntry(booking, rules.first_name(users.get(booking.client_user_id, ("", None))[1], "Mijoz"), phone))
    return trip, entries


def _parcel_details_for(session: Session, booking: Booking):  # noqa: ANN202 - ParcelListingDetails | None
    if booking.request_listing_id is None:
        return None
    return marketplace_service.get_parcel_details(session, booking.request_listing_id)


def parcel_receiver_for(session: Session, booking: Booking) -> tuple[str, str] | None:
    """``(name, phone)`` of a parcel's receiver: request parcels from the listing details, trip-offer parcels from the
    accepted proposal version (A1 ``marketplace.service.parcel_receiver``). Callers apply Q44 (driver: after pickup)."""
    if booking.service_type != ServiceType.PARCEL.value:
        return None
    details = _parcel_details_for(session, booking)
    if details is not None:
        return (details.receiver_name, details.receiver_phone) if details.receiver_phone else None
    version = session.get(ProposalVersion, booking.accepted_proposal_version_id)
    return marketplace_service.parcel_receiver(version) if version is not None else None


# ==============================================================================================================
# Cash receipts (B6-B8, AC26)
# ==============================================================================================================


def _cash_payer_side(session: Session, booking: Booking) -> ActorSide | None:
    """Who pays cash: the passenger client; for a parcel the sender (client) unless the receiver pays."""
    if booking.service_type == ServiceType.PARCEL.value:
        parcel = _parcel_details_for(session, booking)
        if parcel is not None and parcel.payer == ParcelPayer.RECEIVER.value:
            return None  # the receiver has no account: only the driver reports
    return ActorSide.CLIENT


def report_cash_receipt(
    session: Session,
    *,
    booking_public_id_value: str,
    actor_user_id: int,
    expected_version: int,
    amount_minor: int,
    reported_at: datetime,
    note: str | None = None,
    now: datetime | None = None,
) -> tuple[Booking, CashReceipt]:
    now = _now(now)
    snapshot = get_booking_by_public_id(session, booking_public_id_value)
    side = participant_side(snapshot, actor_user_id)
    if side is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    booking = lock_booking(session, snapshot.id)
    _check_version(booking.version, expected_version)
    if side is ActorSide.CLIENT and _cash_payer_side(session, booking) is not ActorSide.CLIENT:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "not_the_payer"})
    if not rules.has_started(booking.service_type, booking.service_status):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "cash_collection", "reason": "service_not_started"})
    if amount_minor != booking.total_minor and not (note or "").strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "note", "reason": "amount_differs_from_total"})
    previous = booking.cash_status
    CASH_COLLECTION.assert_transition(previous, CashCollectionStatus.REPORTED_PAID.value, "report_paid")
    receipt = CashReceipt(
        public_id=new_public_uuid(), booking_id=booking.id, reported_by_side=side.value, reported_by_user_id=actor_user_id,
        amount_minor=amount_minor, currency=booking.currency, status=CashCollectionStatus.REPORTED_PAID.value,
        reported_at=ensure_aware_utc(reported_at), note=note, version=1,
    )
    session.add(receipt)
    _flush_or_translate(session, {OPEN_RECEIPT_INDEX: lambda: DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"reason": "receipt_open"})})
    booking.cash_status = CashCollectionStatus.REPORTED_PAID.value
    _history(session, booking, machine="cash", from_status=previous, to_status=booking.cash_status, command="report_paid",
             actor_user_id=actor_user_id, side=side)
    _touch(booking, now)
    session.flush()
    _emit_status_changed(session, booking, machine="cash", from_status=previous, to_status=booking.cash_status, now=now)
    return booking, receipt


def _receipt_for_decision(
    session: Session, booking_public_id_value: str, receipt_public_id: str, actor_user_id: int, expected_version: int
) -> tuple[Booking, CashReceipt, ActorSide]:
    snapshot = get_booking_by_public_id(session, booking_public_id_value)
    side = participant_side(snapshot, actor_user_id)
    if side is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    value = parse_public_id(receipt_public_id, PublicIdPrefix.CASH_RECEIPT)
    receipt_id = session.execute(
        select(CashReceipt.id).where(CashReceipt.public_id == value, CashReceipt.booking_id == snapshot.id)
    ).scalar_one_or_none()
    if receipt_id is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    booking = lock_booking(session, snapshot.id)  # booking -> receipt (child re-read under the parent lock)
    receipt = session.execute(
        select(CashReceipt).where(CashReceipt.id == receipt_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    _check_version(receipt.version, expected_version)
    if receipt.reported_by_side == side.value:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "counterparty_decides"})
    return booking, receipt, side


def acknowledge_cash_receipt(
    session: Session, *, booking_public_id_value: str, receipt_public_id: str, actor_user_id: int, expected_version: int,
    comment: str | None = None, now: datetime | None = None,
) -> tuple[Booking, CashReceipt]:
    now = _now(now)
    booking, receipt, side = _receipt_for_decision(session, booking_public_id_value, receipt_public_id, actor_user_id, expected_version)
    previous = booking.cash_status
    CASH_COLLECTION.assert_transition(previous, CashCollectionStatus.ACKNOWLEDGED.value, "acknowledge")
    receipt.status = CashCollectionStatus.ACKNOWLEDGED.value
    receipt.decided_by_user_id = actor_user_id
    receipt.decided_at = now
    receipt.decision_comment = comment
    receipt.version += 1
    receipt.updated_at = now
    booking.cash_status = CashCollectionStatus.ACKNOWLEDGED.value
    _history(session, booking, machine="cash", from_status=previous, to_status=booking.cash_status, command="acknowledge",
             actor_user_id=actor_user_id, side=side)
    _touch(booking, now)
    session.flush()
    _emit_status_changed(session, booking, machine="cash", from_status=previous, to_status=booking.cash_status, now=now)
    return booking, receipt


def contest_cash_receipt(
    session: Session, *, booking_public_id_value: str, receipt_public_id: str, actor_user_id: int, expected_version: int,
    comment: str | None, now: datetime | None = None,
) -> tuple[Booking, CashReceipt]:
    """``reported_paid -> contested``; the service status never changes (AC26). A12's opener creates the dispute."""
    now = _now(now)
    if not (comment or "").strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "comment"})
    booking, receipt, side = _receipt_for_decision(session, booking_public_id_value, receipt_public_id, actor_user_id, expected_version)
    previous = booking.cash_status
    CASH_COLLECTION.assert_transition(previous, CashCollectionStatus.CONTESTED.value, "contest")
    receipt.status = CashCollectionStatus.CONTESTED.value
    receipt.decided_by_user_id = actor_user_id
    receipt.decided_at = now
    receipt.decision_comment = comment
    receipt.version += 1
    receipt.updated_at = now
    booking.cash_status = CashCollectionStatus.CONTESTED.value
    _history(session, booking, machine="cash", from_status=previous, to_status=booking.cash_status, command="contest",
             actor_user_id=actor_user_id, side=side, reason=comment)
    _touch(booking, now)
    session.flush()
    if _payment_dispute_opener is not None:
        receipt.dispute_id = _payment_dispute_opener(session, booking, receipt, actor_user_id, comment.strip())
        session.flush()
    _emit_status_changed(session, booking, machine="cash", from_status=previous, to_status=booking.cash_status, now=now)
    return booking, receipt


CASH_RESOLUTION: dict[str, tuple[str, str, str]] = {
    # CashResolutionOutcome -> (command, booking cash_status, cash_receipts.status)   STATE_MACHINES §6, AC26
    CashResolutionOutcome.PAID.value: ("resolve_paid", CashCollectionStatus.ACKNOWLEDGED.value, "resolved_paid"),
    CashResolutionOutcome.UNPAID.value: ("resolve_unpaid", CashCollectionStatus.UNPAID.value, "resolved_unpaid"),
}


def resolve_contested_cash_receipt(
    session: Session,
    *,
    booking_id: int,
    outcome: Literal["paid", "unpaid"],
    actor_user_id: int,
    reason: str,
    now: datetime | None = None,
) -> tuple[Booking, CashReceipt]:
    """STATE_MACHINES §6 ``contested -> acknowledged`` (``resolve_paid``) / ``contested -> unpaid`` (``resolve_unpaid``).

    Called by A12 as part of the ``payment`` dispute decision (§8 "separate commands"): deciding a dispute is
    admin+ (``ops.dispute_decide``, wave 3.1 / v1 Q13-Q38 parity). The service status never changes (AC26);
    ``unpaid`` lets the payer report again.
    Lock order: booking -> cash receipt (call with the booking already locked or before locking dispute rows).
    Audit row + ``booking.status_changed`` (machine ``cash``, allowlisted). No commit.
    Errors: ``FORBIDDEN``, ``VALIDATION_ERROR`` (reason/outcome), ``NOT_FOUND``, ``INVALID_STATE_TRANSITION`` (not contested).
    """
    now = _now(now)
    if outcome not in CASH_RESOLUTION:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "outcome"})
    reason = (reason or "").strip()
    if not reason:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    if not identity_service.get_capabilities(session, actor_user_id, now=now).has(Capability.OPS_DISPUTE_DECIDE):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.OPS_DISPUTE_DECIDE.value})
    command, cash_target, receipt_target = CASH_RESOLUTION[outcome]
    booking = lock_booking(session, booking_id)
    receipt = session.execute(
        select(CashReceipt)
        .where(CashReceipt.booking_id == booking.id, CashReceipt.status == CashCollectionStatus.CONTESTED.value)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    previous = booking.cash_status
    if receipt is None:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "cash_collection", "from": previous, "command": command})
    CASH_COLLECTION.assert_transition(previous, cash_target, command)
    receipt.status = receipt_target
    receipt.decided_by_user_id = actor_user_id
    receipt.decided_at = now
    receipt.decision_comment = reason
    receipt.version += 1
    receipt.updated_at = now
    booking.cash_status = cash_target
    _history(session, booking, machine="cash", from_status=previous, to_status=cash_target, command=command,
             actor_user_id=actor_user_id, side=ActorSide.OPERATOR, reason=reason)
    _touch(booking, now)
    session.add(AuditLog(actor_id=actor_user_id, entity_type="booking", entity_id=None, action=f"booking_cash_{command}",
                         details={"booking_id": booking_public_id(booking),
                                  "cash_receipt_id": format_public_id(PublicIdPrefix.CASH_RECEIPT, receipt.public_id),
                                  "reason": reason, "version": booking.version}))
    session.flush()
    _emit_status_changed(session, booking, machine="cash", from_status=previous, to_status=cash_target, now=now)
    return booking, receipt


# ==============================================================================================================
# Amendments (B9-B11; spec §5.3(7), D9, D10, Q19) - pilot scope: quantity and unit price
# ==============================================================================================================


def _amendment_terms(booking: Booking, changes: dict[str, Any]) -> tuple[int, int, int]:
    unsupported = sorted(set(changes) - {"quantity", "unit_price_minor"})
    if unsupported:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          details={"fields": unsupported, "reason": "pilot_amends_quantity_and_unit_price_only"})
    quantity = int(changes.get("quantity", booking.quantity))
    unit = int(changes.get("unit_price_minor", booking.unit_price_minor))
    if booking.service_type == ServiceType.PARCEL.value and quantity != 1:
        raise DomainError(ErrorCode.QUANTITY_MISMATCH, details={"required_quantity": 1, "quantity": quantity})
    if booking.request_listing_id is not None and quantity != booking.quantity:
        raise DomainError(ErrorCode.QUANTITY_MISMATCH, details={"required_quantity": booking.quantity, "quantity": quantity})  # D9
    if quantity == booking.quantity and unit == booking.unit_price_minor:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"reason": "no_change"})
    total = money_total_minor(unit, quantity) if booking.price_basis == "per_seat" else money_total_minor(unit, 1)
    return quantity, unit, total


def create_amendment(
    session: Session, *, booking_public_id_value: str, actor_user_id: int, expected_version: int, changes: dict[str, Any],
    reason: str, now: datetime | None = None, warnings: list[dict] | None = None,
) -> BookingAmendment:
    now = _now(now)
    snapshot = get_booking_by_public_id(session, booking_public_id_value)
    side = participant_side(snapshot, actor_user_id)
    if side is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    if not (reason or "").strip():
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    reason = marketplace_service.filter_free_text(session, actor_user_id=actor_user_id, field="reason", text=reason, warnings=warnings) or ""
    booking = lock_booking(session, snapshot.id)
    _check_version(booking.version, expected_version)
    if booking.service_status not in rules.PRE_SERVICE_STATUSES:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={"machine": "amendment", "service_status": booking.service_status})
    quantity, unit, total = _amendment_terms(booking, changes)
    new_commission = commission_minor(total, booking.fee_bps)
    amendment = BookingAmendment(
        public_id=new_public_uuid(), booking_id=booking.id, booking_version=booking.version, author_side=side.value,
        author_user_id=actor_user_id, status="proposed", changes=dict(changes), new_quantity=quantity, new_unit_price_minor=unit,
        new_total_minor=total, fee_delta_minor=new_commission - booking.commission_minor, reason=reason.strip(),
        expires_at=now + AMENDMENT_TTL, version=1,
    )
    session.add(amendment)
    _flush_or_translate(session, {PROPOSED_AMENDMENT_INDEX: lambda: DomainError(ErrorCode.AMENDMENT_CONFLICT, details={"reason": "amendment_open"})})
    _history(session, booking, machine="amendment", from_status=None, to_status="proposed", command="create",
             actor_user_id=actor_user_id, side=side, reason=reason.strip())
    # Wave 5: tell the counterparty there is something to answer (payload without the commission, Q16).
    _emit(
        session, booking, EventType.BOOKING_AMENDMENT_REQUESTED,
        {
            "amendment_id": format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id),
            "service_type": booking.service_type,
            "author_side": side.value,
            "new_quantity": amendment.new_quantity,
            "new_total_minor": amendment.new_total_minor,
            "currency": booking.currency,
            "expires_at": ensure_aware_utc(amendment.expires_at).isoformat(),
        },
        now,
    )
    session.flush()
    return amendment


def list_booking_amendments(
    session: Session, *, booking_public_id_value: str, actor_user_id: int, limit: int = 20
) -> tuple[Booking, list[BookingAmendment]]:
    """B9 read side: the amendments of one booking, newest first.

    Without it the counterpart cannot answer a proposed change - it would have to be told the amendment id out of
    band. Participants only: staff read amendments through the ops surfaces.
    """
    booking = get_booking_by_public_id(session, booking_public_id_value)
    if participant_side(booking, actor_user_id) is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    rows = session.execute(
        select(BookingAmendment)
        .where(BookingAmendment.booking_id == booking.id)
        .order_by(BookingAmendment.created_at.desc(), BookingAmendment.id.desc())
        .limit(limit)
    ).scalars()
    return booking, list(rows)


def _amendment_scope(session: Session, amendment_public_id: str, actor_user_id: int) -> tuple[BookingAmendment, Booking, ActorSide]:
    value = parse_public_id(amendment_public_id, PublicIdPrefix.AMENDMENT)
    unlocked = session.execute(select(BookingAmendment).where(BookingAmendment.public_id == value)).scalar_one_or_none()
    if unlocked is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    booking = get_booking(session, unlocked.booking_id)
    side = participant_side(booking, actor_user_id)
    if side is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return unlocked, booking, side


def _lock_amendment(session: Session, amendment_id: int, booking_id: int) -> BookingAmendment:
    amendment = session.execute(
        select(BookingAmendment).where(BookingAmendment.id == amendment_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    if amendment.booking_id != booking_id:  # pragma: no cover - immutable
        raise DomainError(ErrorCode.VERSION_CONFLICT)
    return amendment


def accept_amendment(
    session: Session, *, amendment_public_id: str, actor_user_id: int, expected_version: int, now: datetime | None = None
) -> Booking:
    """B10 (D10): trip -> booking -> amendment -> wallet; the single hold changes; allocations re-reserved."""
    now = _now(now)
    unlocked, snapshot, side = _amendment_scope(session, amendment_public_id, actor_user_id)
    # BR L3 / Q61: extra capacity is new business. The amendment content is immutable and the booking version is
    # re-checked below, so the unlocked comparison decides whether the users lock (first lock group) is needed.
    grows = snapshot.service_type == ServiceType.PASSENGER.value and unlocked.new_quantity > snapshot.quantity
    if grows:
        identity_service.lock_user_eligibility(session, [snapshot.driver_user_id], mode="update")
    trip = trips_service.lock_trip(session, snapshot.trip_id)
    booking = lock_booking(session, snapshot.id)
    amendment = _lock_amendment(session, unlocked.id, booking.id)
    if grows:
        identity_service.ensure_driver_eligible(session, booking.driver_user_id, now=now)
        trips_service.assert_vehicle_eligible_for_new_booking(session, trip.vehicle_id)
    _check_version(amendment.version, expected_version)
    if amendment.author_side == side.value:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "counterparty_accepts"})
    AMENDMENT.assert_transition(amendment.status, "accepted", "accept")
    if ensure_aware_utc(amendment.expires_at) <= now:
        raise DomainError(ErrorCode.AMENDMENT_CONFLICT, details={"reason": "amendment_expired"})
    if booking.version != amendment.booking_version or booking.service_status not in rules.PRE_SERVICE_STATUSES:
        raise DomainError(ErrorCode.AMENDMENT_CONFLICT, details={"reason": "booking_changed"})
    if trip.status != TripStatus.PLANNED.value:
        raise DomainError(ErrorCode.AMENDMENT_CONFLICT, details={"reason": "trip_not_planned"})

    # Q60 (0056): the amount/resource columns of the booking may change only after the amendment row is accepted in
    # this transaction, so the amendment status is flushed first.
    amendment.status = "accepted"
    amendment.decided_by_user_id = actor_user_id
    amendment.decided_at = now
    amendment.version += 1
    amendment.updated_at = now
    session.flush()

    if amendment.new_quantity != booking.quantity and booking.service_type == ServiceType.PASSENGER.value:
        _release_allocations(session, booking, trip.id, now)
        demand = ResourceDemand(seats=amendment.new_quantity, baggage_ml=booking.baggage_ml,
                                cargo_weight_g=booking.cargo_weight_g, cargo_volume_ml=booking.cargo_volume_ml)
        trips_service.reserve(session, trip.id, booking.pickup_occurrence_seq, booking.dropoff_occurrence_seq, demand)
        session.flush()
        for seq in range(booking.pickup_occurrence_seq, booking.dropoff_occurrence_seq):
            session.add(BookingAllocation(booking_id=booking.id, trip_id=trip.id, segment_from_seq=seq, seats=demand.seats,
                                          baggage_ml=demand.baggage_ml, cargo_weight_g=demand.cargo_weight_g,
                                          cargo_volume_ml=demand.cargo_volume_ml, active=True))
        booking.seats = demand.seats
    booking.quantity = amendment.new_quantity
    booking.unit_price_minor = amendment.new_unit_price_minor
    booking.total_minor = amendment.new_total_minor
    booking.commission_minor = commission_minor(amendment.new_total_minor, booking.fee_bps)
    _touch(booking, now)
    session.flush()
    _history(session, booking, machine="amendment", from_status="proposed", to_status="accepted", command="accept",
             actor_user_id=actor_user_id, side=side)
    if booking.commission_status == CommissionStatus.HELD.value:
        wallet_service.adjust_hold(session, booking_id=booking.id, new_total_minor=booking.total_minor, fee_bps=booking.fee_bps,
                                   corridor_id=booking.corridor_id,
                                   wallet_required=bool(booking.terms_snapshot.get("flags", {}).get(FeatureFlagKey.WALLET_REQUIRED.value, True)))
        _history(session, booking, machine="commission", from_status=CommissionStatus.HELD.value, to_status=CommissionStatus.HELD.value,
                 command="adjust_hold", actor_user_id=None, side=ActorSide.SYSTEM)
    session.flush()
    return booking


def decide_amendment(
    session: Session, *, amendment_public_id: str, actor_user_id: int, expected_version: int, decision: Literal["reject", "withdraw"],
    now: datetime | None = None,
) -> BookingAmendment:
    now = _now(now)
    unlocked, snapshot, side = _amendment_scope(session, amendment_public_id, actor_user_id)
    booking = lock_booking(session, snapshot.id)
    amendment = _lock_amendment(session, unlocked.id, booking.id)
    _check_version(amendment.version, expected_version)
    is_author = amendment.author_side == side.value
    if (decision == "withdraw") != is_author:
        raise DomainError(ErrorCode.FORBIDDEN, details={"reason": "author_withdraws_counterparty_rejects"})
    target = "withdrawn" if decision == "withdraw" else "rejected"
    AMENDMENT.assert_transition(amendment.status, target, decision)
    amendment.status = target
    amendment.decided_by_user_id = actor_user_id
    amendment.decided_at = now
    amendment.version += 1
    amendment.updated_at = now
    _history(session, booking, machine="amendment", from_status="proposed", to_status=target, command=decision,
             actor_user_id=actor_user_id, side=side)
    _emit(
        session, booking, EventType.BOOKING_AMENDMENT_DECIDED,
        {
            "amendment_id": format_public_id(PublicIdPrefix.AMENDMENT, amendment.public_id),
            "service_type": booking.service_type,
            "author_side": amendment.author_side,
            "status": target,
        },
        now,
    )
    session.flush()
    return amendment


# ==============================================================================================================
# Lists, admin queues (B2, B12)
# ==============================================================================================================


def list_user_bookings(
    session: Session, user_id: int, *, role: str | None, status: str | None, before: tuple[datetime, int] | None, limit: int
) -> list[Booking]:
    stmt = select(Booking)
    if role == ViewerRole.CLIENT:
        stmt = stmt.where(Booking.client_user_id == user_id)
    elif role == ViewerRole.DRIVER:
        stmt = stmt.where(Booking.driver_user_id == user_id)
    else:
        stmt = stmt.where(or_(Booking.client_user_id == user_id, Booking.driver_user_id == user_id))
    if status:
        stmt = stmt.where(Booking.service_status == status)
    if before is not None:
        moment, booking_id = before
        stmt = stmt.where(or_(Booking.created_at < moment, (Booking.created_at == moment) & (Booking.id < booking_id)))
    return list(session.execute(stmt.order_by(Booking.created_at.desc(), Booking.id.desc()).limit(limit)).scalars())


def admin_queue(
    session: Session, *, actor_user_id: int, queue: str, corridor_id: int | None, after_id: int | None, limit: int,
    now: datetime | None = None,
) -> list[Booking]:
    """B12 operator queues. ``awaiting_confirmation`` is the 24 h no-confirmation signal and ``hold_escalation``
    the 48 h escalation signal of spec §9.5 (read-side queues; A7/A12 consume, no automatic capture)."""
    now = _now(now)
    if queue not in ADMIN_QUEUES:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "queue"})
    caps = identity_service.get_capabilities(session, actor_user_id, now=now)
    if not (caps.has(Capability.OPS_VIEW) or (queue == AdminBookingQueue.FINANCE_REVIEW.value and caps.has(Capability.FINANCE_REPORTS))):
        raise DomainError(ErrorCode.FORBIDDEN, details={"capability": Capability.OPS_VIEW.value})
    stmt = select(Booking)
    if queue == AdminBookingQueue.AWAITING_CONFIRMATION.value:
        stmt = stmt.where(_awaiting_confirmation_filter(now))
    elif queue == AdminBookingQueue.FINANCE_REVIEW.value:
        stmt = stmt.where(Booking.finance_review_reason.is_not(None), Booking.commission_status == CommissionStatus.HELD.value)
    elif queue == "no_show_review":
        stmt = stmt.where(
            select(NoShowReview.id).where(NoShowReview.booking_id == Booking.id, NoShowReview.status == "pending").exists()
        )
    elif queue == "custody_case":
        stmt = stmt.where(select(CustodyCase.id).where(CustodyCase.booking_id == Booking.id, CustodyCase.status == "open").exists())
    else:
        from app.modules.wallet.models import WalletHold  # read-only view of A3's escalation deadline

        stmt = stmt.where(
            select(WalletHold.id)
            .where(WalletHold.booking_id == Booking.id, WalletHold.status == "active", WalletHold.escalate_at <= now)
            .exists()
        )
    if corridor_id is not None:
        stmt = stmt.where(Booking.corridor_id == corridor_id)
    if after_id is not None:
        stmt = stmt.where(Booking.id > after_id)
    return list(session.execute(stmt.order_by(Booking.id).limit(limit)).scalars())


# ==============================================================================================================
# Read-side hooks for other owners (N4, Q15, A1 N6)
# ==============================================================================================================


@dataclass(frozen=True, slots=True)
class BookingBlockingState:
    """Read-only v2 booking facts that block account deletion (N4, ADR-0006 D5)."""

    active_bookings_as_client: int
    active_bookings_as_driver: int
    pending_no_show_reviews: int
    open_custody_cases: int
    open_cash_receipts: int
    held_commission_bookings: int = 0
    booking_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocks_deletion(self) -> bool:
        return bool(
            self.active_bookings_as_client or self.active_bookings_as_driver or self.pending_no_show_reviews
            or self.open_custody_cases or self.open_cash_receipts or self.held_commission_bookings
        )

    def as_details(self) -> dict[str, int]:
        return {
            "active_bookings": self.active_bookings_as_client + self.active_bookings_as_driver,
            "active_bookings_as_client": self.active_bookings_as_client,
            "active_bookings_as_driver": self.active_bookings_as_driver,
            "pending_no_show_reviews": self.pending_no_show_reviews,
            "open_custody_cases": self.open_custody_cases,
            "open_cash_receipts": self.open_cash_receipts,
            "held_commission_bookings": self.held_commission_bookings,
        }


def blocking_state_for_user(session: Session, user_id: int, *, lock: bool = False) -> BookingBlockingState:
    """N4: open v2 obligations of a user as client or driver. Read-only; ``lock`` takes ``FOR SHARE`` on those bookings
    (call after the v1 deletion's ``users`` lock, so accept - which starts with ``users`` - cannot interleave).
    Returns an empty state when the bookings table is absent (legacy SQLite suite), like the wallet helper."""
    if not platform_service.table_exists(session, Booking.__tablename__):
        return BookingBlockingState(0, 0, 0, 0, 0)
    open_filter = Booking.service_status.not_in(sorted(rules.TERMINAL_SERVICE_STATUSES))
    related = or_(Booking.client_user_id == user_id, Booking.driver_user_id == user_id)
    stmt = select(Booking.id, Booking.public_id, Booking.client_user_id, Booking.driver_user_id, Booking.service_status,
                  Booking.commission_status, Booking.cash_status).where(
        related, or_(open_filter, Booking.commission_status == CommissionStatus.HELD.value,
                     Booking.cash_status.in_([CashCollectionStatus.REPORTED_PAID.value, CashCollectionStatus.CONTESTED.value]))
    ).order_by(Booking.id)
    if lock:
        stmt = stmt.with_for_update(read=True)
    rows = session.execute(stmt).all()
    ids = [row.id for row in rows]
    reviews = custody = receipts = 0
    if ids:
        reviews = int(session.execute(select(func.count(NoShowReview.id)).where(NoShowReview.booking_id.in_(ids), NoShowReview.status == "pending")).scalar_one())
        custody = int(session.execute(select(func.count(CustodyCase.id)).where(CustodyCase.booking_id.in_(ids), CustodyCase.status == "open")).scalar_one())
        receipts = int(session.execute(select(func.count(CashReceipt.id)).where(CashReceipt.booking_id.in_(ids), CashReceipt.status.in_(["reported_paid", "contested"]))).scalar_one())
    terminal = rules.TERMINAL_SERVICE_STATUSES
    return BookingBlockingState(
        active_bookings_as_client=sum(1 for r in rows if r.client_user_id == user_id and r.service_status not in terminal),
        active_bookings_as_driver=sum(1 for r in rows if r.driver_user_id == user_id and r.service_status not in terminal),
        pending_no_show_reviews=reviews,
        open_custody_cases=custody,
        open_cash_receipts=receipts,
        held_commission_bookings=sum(1 for r in rows if r.commission_status == CommissionStatus.HELD.value),
        booking_ids=tuple(format_public_id(PublicIdPrefix.BOOKING, r.public_id) for r in rows),
    )


@dataclass(frozen=True, slots=True)
class DriverV2Obligations:
    """Q15: v1 ``block_driver`` of a driver with v2 business applies only the v2 eligibility block."""

    active_trip_ids: tuple[str, ...]
    active_booking_count: int

    @property
    def has_active_v2_business(self) -> bool:
        return bool(self.active_trip_ids or self.active_booking_count)


def driver_v2_obligations(session: Session, driver_user_id: int) -> DriverV2Obligations:
    """Q15 (H1 v1 ``block_driver``). Read-only; empty when the v2 tables are absent (legacy SQLite / v1-only DB)."""
    if not (platform_service.table_exists(session, Booking.__tablename__) and platform_service.table_exists(session, "trips")):
        return DriverV2Obligations((), 0)
    active_bookings = int(
        session.execute(
            select(func.count(Booking.id)).where(
                Booking.driver_user_id == driver_user_id, Booking.service_status.not_in(sorted(rules.TERMINAL_SERVICE_STATUSES))
            )
        ).scalar_one()
    )
    return DriverV2Obligations(tuple(trips_service.active_trip_public_ids(session, driver_user_id)), active_bookings)


def trip_has_active_allocations(session: Session, trip_id: int) -> bool:
    """A1 N6: ``trips.patch_trip`` must refuse a stops change while this is true."""
    return session.execute(
        select(BookingAllocation.id).where(BookingAllocation.trip_id == trip_id, BookingAllocation.active.is_(True)).limit(1)
    ).first() is not None


blocking_bookings_for_user = blocking_state_for_user  # name used by the A4 card (N4)


def trip_has_allocations(session: Session, trip_id: int) -> bool:
    """Q63 (A1 ``patch_trip`` stops): any booking ever allocated on the trip, released rows included. Read-only."""
    return session.execute(select(BookingAllocation.id).where(BookingAllocation.trip_id == trip_id).limit(1)).first() is not None


# ==============================================================================================================
# Staff contact audit (B1, B12) and scheduled functions for the A10a worker (Q65, §9.5)
# ==============================================================================================================


def record_staff_contact_view(
    session: Session, *, actor_user_id: int, booking_ids: Sequence[str], surface: str, fields: Sequence[str]
) -> None:
    """``audit_logs`` row ``booking_contacts_viewed`` when a staff response shows phones / full plates.

    Only public booking ids and the field names are stored - never a phone or plate value. No commit.
    """
    if not booking_ids or not fields:
        return
    session.add(
        AuditLog(actor_id=actor_user_id, entity_type="booking", entity_id=None, action="booking_contacts_viewed",
                 details={"booking_ids": list(booking_ids), "surface": surface, "fields": sorted(set(fields))})
    )
    session.flush()


def _awaiting_confirmation_filter(now: datetime):  # noqa: ANN202 - SQL expression
    """Passenger ``arrived`` 24 h (§9.5) and parcel ``delivered`` 24 h without sender confirmation (Q65)."""
    return or_(
        (Booking.service_status == PB.ARRIVED.value) & (Booking.service_ended_at <= now - rules.CONFIRMATION_WINDOW),
        (Booking.service_status == PC.DELIVERED.value) & (Booking.service_ended_at <= now - DELIVERED_OPERATOR_QUEUE_AFTER),
    )


def expire_due_amendments(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """Worker (A10a): ``proposed -> expired`` (``system_expire``) for amendments past ``expires_at``. Returns the count.

    Lock order booking -> amendment, bookings in id order; re-checked under the lock. No commit (the task commits).
    """
    now = _now(now)
    due = session.execute(
        select(BookingAmendment.id, BookingAmendment.booking_id)
        .where(BookingAmendment.status == "proposed", BookingAmendment.expires_at <= now)
        .order_by(BookingAmendment.id)
        .limit(limit)
    ).all()
    expired = 0
    for amendment_id, booking_id in sorted(due, key=lambda row: (row.booking_id, row.id)):
        booking = lock_booking(session, booking_id)
        amendment = _lock_amendment(session, amendment_id, booking.id)
        if amendment.status != "proposed" or ensure_aware_utc(amendment.expires_at) > now:
            continue
        AMENDMENT.assert_transition(amendment.status, "expired", "system_expire")
        amendment.status = "expired"
        amendment.decided_at = now
        amendment.version += 1
        amendment.updated_at = now
        _history(session, booking, machine="amendment", from_status="proposed", to_status="expired", command="system_expire",
                 actor_user_id=None, side=ActorSide.SYSTEM)
        session.flush()
        expired += 1
    return expired


TRACKING_SERVICE_MODULE = "app.modules.tracking.service"


def _close_tracking_sessions(session: Session, trip_id: int, now: datetime) -> None:
    """Wave 3: a completed/cancelled trip closes its A6 tracking sessions in the same transaction (no commit).

    Lazy import - A6 ships ``close_sessions_for_trip(session, trip_id, *, now=None) -> int`` in parallel; until it is
    importable the hook is skipped with a log line (the trip transition itself never depends on tracking)."""
    import importlib
    import logging

    try:
        close = getattr(importlib.import_module(TRACKING_SERVICE_MODULE), "close_sessions_for_trip", None)
    except ImportError:
        close = None
    if close is None:
        logging.getLogger(__name__).info("tracking close_sessions_for_trip not available; skipped for trip %s", trip_id)
        return
    close(session, trip_id, now=now)


def mark_finance_review_after_dispute(session: Session, *, booking_id: int, reason: str, now: datetime | None = None) -> None:
    """U8 hook for A12: after a blocking dispute is resolved, put a finished booking whose commission is still ``held``
    into the B12 ``finance_review`` queue (staff event ``commission.finance_review_required``). No automatic capture -
    finance decides with ``finalize_fee``. Idempotent (already queued -> no-op, no second event). No commit.

    Lock: takes the booking row (bookings group); call it before locking dispute rows (ADR-0017 order).
    Raises ``VALIDATION_ERROR`` (empty reason), ``NOT_FOUND``, ``INVALID_STATE_TRANSITION`` (not finished or not held).
    Q84 / wave 3.1: the stored reason code is ``CommissionReviewReason.DISPUTE_RESOLVED`` (0062 widened the CHECK); the
    caller's free-text ``reason`` (dispute id, resolution code) goes to the status history, never to the event.
    """
    now = _now(now)
    reason = (reason or "").strip()
    if not reason:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "reason"})
    booking = lock_booking(session, booking_id)
    if booking.service_status not in rules.FEE_FINALIZABLE_STATUSES or booking.commission_status != CommissionStatus.HELD.value:
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, details={
            "machine": "commission", "command": "finance_review_after_dispute",
            "service_status": booking.service_status, "commission_status": booking.commission_status})
    if booking.finance_review_reason is not None:
        return
    reason_code = CommissionReviewReason.DISPUTE_RESOLVED
    booking.finance_review_reason = reason_code.value
    booking.finance_review_at = now
    _history(session, booking, machine="commission", from_status=CommissionStatus.HELD.value, to_status=CommissionStatus.HELD.value,
             command="finance_review_after_dispute", actor_user_id=None, side=ActorSide.SYSTEM, reason=reason)
    session.flush()
    _emit(session, booking, EventType.COMMISSION_FINANCE_REVIEW_REQUIRED,
          {"booking_id": booking_public_id(booking), "reason_code": reason_code.value,
           "amount_minor": booking.commission_minor, "currency": booking.currency}, now)


def _not_signalled(event_type: EventType, id_column):  # noqa: ANN001, ANN202 - SQL expression
    """Excludes rows already signalled (``outbox_events.dedup_key = '<event>:<id>'``) IN SQL, so a batch limit never
    starves new due rows behind old signalled ones (A10a review). Read-only lookup of the platform outbox."""
    from app.modules.platform.models import OutboxEvent

    return ~select(OutboxEvent.id).where(OutboxEvent.dedup_key == func.concat(f"{event_type.value}:", id_column)).exists()


def emit_confirmation_overdue_signals(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """Worker (A10a): staff event ``booking.confirmation_overdue`` once per booking (dedup key) for passenger ``arrived``
    and parcel ``delivered`` bookings unconfirmed for 24 h (§9.5, Q65) - the same set as the B12
    ``awaiting_confirmation`` queue. Writes only outbox rows; no commit. Returns the number emitted."""
    now = _now(now)
    candidates = session.execute(
        select(Booking)
        .where(_awaiting_confirmation_filter(now), _not_signalled(EventType.BOOKING_CONFIRMATION_OVERDUE, Booking.id))
        .order_by(Booking.id)
        .limit(limit)
    ).scalars().all()
    emitted = 0
    for booking in candidates:
        key = f"{EventType.BOOKING_CONFIRMATION_OVERDUE.value}:{booking.id}"
        window = DELIVERED_OPERATOR_QUEUE_AFTER if booking.service_status == PC.DELIVERED.value else rules.CONFIRMATION_WINDOW
        platform_service.enqueue_event(
            session,
            EventEnvelope(EventType.BOOKING_CONFIRMATION_OVERDUE, "booking", booking_public_id(booking), booking.version, now, {
                "booking_id": booking_public_id(booking),
                "trip_id": _trip_public_id(session, booking.trip_id),
                "service_type": booking.service_type,
                "service_status": booking.service_status,
                "overdue_since": (ensure_aware_utc(booking.service_ended_at) + window).isoformat(),
            }),
            aggregate_id=booking.id,
            dedup_key=key,
        )
        emitted += 1
    return emitted


def emit_hold_escalation_signals(session: Session, *, now: datetime | None = None, limit: int = SIGNAL_BATCH_LIMIT) -> int:
    """Worker (A10a): staff event ``wallet.hold.escalation_due`` once per active hold past ``escalate_at`` (48 h, §9.5).
    Read-only on A3's holds; writes only outbox rows; no automatic capture; no commit. Returns the number emitted."""
    from app.modules.wallet.models import WalletHold  # read-only view of A3's escalation deadline

    now = _now(now)
    candidates = session.execute(
        select(WalletHold, Booking)
        .join(Booking, Booking.id == WalletHold.booking_id)
        .where(WalletHold.status == "active", WalletHold.escalate_at.is_not(None), WalletHold.escalate_at <= now,
               _not_signalled(EventType.WALLET_HOLD_ESCALATION_DUE, WalletHold.id))
        .order_by(WalletHold.id)
        .limit(limit)
    ).all()
    emitted = 0
    for hold, booking in candidates:
        key = f"{EventType.WALLET_HOLD_ESCALATION_DUE.value}:{hold.id}"
        public = booking_public_id(booking)
        platform_service.enqueue_event(
            session,
            EventEnvelope(EventType.WALLET_HOLD_ESCALATION_DUE, "booking", public, booking.version, now, {
                "booking_id": public,
                "hold_id": f"{public}:{hold.charge_kind}",
                "amount_minor": hold.amount_minor,
                "currency": hold.currency,
                "escalate_at": ensure_aware_utc(hold.escalate_at).isoformat(),
            }),
            aggregate_id=booking.id,
            dedup_key=key,
        )
        emitted += 1
    return emitted
