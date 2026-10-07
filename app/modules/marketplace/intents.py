"""Saved trip/parcel requests - trip intents (ADR-0025).

A client's private, reusable request: the route, time window, quantity, optional price hint and parcel data it would
otherwise type again on every driver's offer. It is **not** a public listing and sends nothing by itself; offers made
from it are ordinary proposal threads that remember it (``proposal_threads.trip_intent_id``), and at most one of them
can become a booking (accept-time check under the intent lock + ``uq_bookings_trip_intent_binding``).

Lock order (ADR-0017 + ADR-0025 §9): ``... proposal_threads -> trip_intents -> bookings``. Accept and counter take the
intent after the thread. Edit / close / book close the request's open offers with ``SKIP LOCKED`` (they never wait for a
thread lock, so there is no inversion); a thread they skip is refused at accept/counter by the terms check and closed by
the ``marketplace.close_stale_intent_threads`` sweep. No function here commits (AGENTS §4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.contracts.enums import (
    PriceBasis,
    ServiceType,
    TripIntentStatus,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import (
    PublicIdPrefix,
    format_public_id,
    parse_public_id,
)
from app.contracts.state_machines import TRIP_INTENT
from app.contracts.timeutil import ensure_aware_utc, utc_now
from app.modules.marketplace.models import (
    Listing,
    ProposalThread,
    TripIntent,
    TripIntentVersion,
)
from app.modules.marketplace.rules import compute_total_minor

REASON_BOOKED = "trip_intent_booked"  # technical: another offer of the same request became the booking
REASON_CHANGED = "trip_intent_changed"  # the client changed route / time / quantity / parcel after the offer
REASON_CLOSED = "trip_intent_closed"  # the client ended the request
THREAD_OPEN = "open"


def intent_public_id(intent: TripIntent) -> str:
    return format_public_id(PublicIdPrefix.TRIP_INTENT, intent.public_id)


def _now(now: datetime | None) -> datetime:
    return ensure_aware_utc(now) if now is not None else utc_now()


# --- terms: resolve, compare ------------------------------------------------------------------------------------
# --- reads ---------------------------------------------------------------------------------------------------------


def _by_public_id(session: Session, public_id: str) -> TripIntent:
    try:
        value = parse_public_id(public_id, PublicIdPrefix.TRIP_INTENT)
    except (DomainError, ValueError):
        raise DomainError(ErrorCode.NOT_FOUND) from None
    intent = session.execute(select(TripIntent).where(TripIntent.public_id == value)).scalar_one_or_none()
    if intent is None:
        raise DomainError(ErrorCode.NOT_FOUND)
    return intent


def get_own_intent(session: Session, public_id: str, owner_user_id: int) -> TripIntent:
    """The caller's own request - another person's answers 404 like an unknown id."""
    intent = _by_public_id(session, public_id)
    if intent.owner_user_id != owner_user_id:
        raise DomainError(ErrorCode.NOT_FOUND)
    return intent


def list_own_intents(session: Session, owner_user_id: int, *, status: str | None = None, limit: int = 20) -> list[TripIntent]:
    query = select(TripIntent).where(TripIntent.owner_user_id == owner_user_id)
    if status is not None:
        query = query.where(TripIntent.status == TripIntentStatus(status).value)
    return list(session.execute(query.order_by(TripIntent.id.desc()).limit(limit)).scalars())


def current_version(session: Session, intent: TripIntent) -> TripIntentVersion:
    return session.execute(select(TripIntentVersion).where(
        TripIntentVersion.intent_id == intent.id, TripIntentVersion.version_no == intent.current_version_no)).scalar_one()


def _lock(session: Session, intent_id: int, *, share: bool = False) -> TripIntent:
    query = select(TripIntent).where(TripIntent.id == intent_id).execution_options(populate_existing=True)
    query = query.with_for_update(read=True) if share else query.with_for_update(key_share=True)
    return session.execute(query).scalar_one()


def is_expired(session: Session, intent: TripIntent, now: datetime | None = None) -> bool:
    return ensure_aware_utc(current_version(session, intent).window_end) <= _now(now)


def open_thread_count(session: Session, intent: TripIntent) -> int:
    return int(session.execute(select(func.count(ProposalThread.id)).where(
        ProposalThread.trip_intent_id == intent.id, ProposalThread.state == THREAD_OPEN)).scalar_one())


# --- lifecycle ---------------------------------------------------------------------------------------------------


def create_intent(session: Session, *, owner_user_id: int, data: Any, now: datetime | None = None) -> TripIntent:
    """A new private request (version 1). Touches no listing, offer, referral attribution or booking history."""
    now = _now(now)
    # Q138 (ADR-0026): saved requests answered driver listings, which are retired - history stays readable and
    # closable, but nothing new is created, edited, reopened or compared.
    raise DomainError(ErrorCode.TRIP_INTENT_RETIRED)


def edit_intent(session: Session, *, intent_public_id: str, owner_user_id: int, data: Any,
                now: datetime | None = None) -> TripIntent:
    """A new version. A material change (ends, window, quantity, parcel, receiver) bumps ``terms_version`` and closes
    the request's open offers - only after the client acknowledged how many (409 ``TRIP_INTENT_OFFERS_AFFECTED``)."""
    now = _now(now)
    # Q138 (ADR-0026): saved requests answered driver listings, which are retired - history stays readable and
    # closable, but nothing new is created, edited, reopened or compared.
    raise DomainError(ErrorCode.TRIP_INTENT_RETIRED)


def close_intent(session: Session, *, intent_public_id: str, owner_user_id: int, expected_version: int,
                 now: datetime | None = None) -> TripIntent:
    now = _now(now)
    intent = _lock(session, get_own_intent(session, intent_public_id, owner_user_id).id)
    if intent.version != expected_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT, details={"current_version": intent.version})
    TRIP_INTENT.assert_transition(intent.status, TripIntentStatus.CLOSED.value, "close")
    # booked -> closed keeps the history in bookings.trip_intent_id; the CHECK ties booking_id to status booked
    intent.status, intent.closed_reason, intent.booking_id = TripIntentStatus.CLOSED.value, "client_closed", None
    intent.version += 1
    intent.updated_at = now
    session.flush()
    close_open_threads(session, intent, reason=REASON_CLOSED, now=now)
    return intent


def _booking_status(session: Session, booking_id: int) -> str | None:
    return session.execute(text("SELECT service_status FROM bookings WHERE id = :b"), {"b": booking_id}).scalar()


def reopen_intent(session: Session, *, intent_public_id: str, owner_user_id: int, expected_version: int,
                  now: datetime | None = None) -> TripIntent:
    """Explicit "search again" after the booking was cancelled. A new version with a new ``terms_version``: none of the
    old offers can ever be accepted again, and none is reopened."""
    now = _now(now)
    # Q138 (ADR-0026): saved requests answered driver listings, which are retired - history stays readable and
    # closable, but nothing new is created, edited, reopened or compared.
    raise DomainError(ErrorCode.TRIP_INTENT_RETIRED)


def close_open_threads(session: Session, intent: TripIntent, *, reason: str, now: datetime,
                       keep_thread_id: int | None = None) -> int:
    """Close the request's open offers without waiting for any thread lock (``SKIP LOCKED``). A system expiry of the
    proposal (``proposal.expired`` via the outbox): no client fault, no strike, no rating."""
    from app.modules.marketplace import service as mp

    query = (select(ProposalThread)
             .where(ProposalThread.trip_intent_id == intent.id, ProposalThread.state == THREAD_OPEN)
             .order_by(ProposalThread.id)
             .with_for_update(key_share=True, skip_locked=True)
             .execution_options(populate_existing=True))
    closed = 0
    for thread in session.execute(query).scalars().all():
        if thread.id == keep_thread_id or thread.state != THREAD_OPEN:
            continue
        listing = mp.get_listing(session, thread.listing_id)
        mp._expire_thread(session, listing, thread, mp.current_version(session, thread, for_update=True),
                          reason=reason, now=now)
        closed += 1
    return closed


def close_stale_intent_threads(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """Worker sweep: open offers of a request that is booked or closed, or whose terms moved on (the ones a command
    skipped because they were locked). The accept/counter checks refuse them anyway; this only tidies them up."""
    from app.modules.marketplace import service as mp

    now = _now(now)
    rows = session.execute(
        select(ProposalThread, TripIntent)
        .join(TripIntent, TripIntent.id == ProposalThread.trip_intent_id)
        .where(ProposalThread.state == THREAD_OPEN,
               (TripIntent.status != TripIntentStatus.ACTIVE.value)
               | (ProposalThread.trip_intent_terms_version != TripIntent.terms_version))
        .order_by(ProposalThread.id)
        .limit(limit)
        .with_for_update(of=ProposalThread, key_share=True, skip_locked=True)
    ).all()
    for thread, intent in rows:
        reason = {TripIntentStatus.BOOKED.value: REASON_BOOKED,
                  TripIntentStatus.CLOSED.value: REASON_CLOSED}.get(intent.status, REASON_CHANGED)
        mp._expire_thread(session, mp.get_listing(session, thread.listing_id), thread,
                          mp.current_version(session, thread, for_update=True), reason=reason, now=now)
    return len(rows)


# --- offers made from a request -----------------------------------------------------------------------------------


def prepare_for_proposal(session: Session, *, ref: Any, owner_user_id: int, listing: Listing, data: Any,
                         now: datetime) -> tuple[TripIntent, TripIntentVersion]:
    """Checks before the thread is written: owner, active, current terms, same service, not expired, and the offer's
    quantity / parcel demand are the request's (the client's data is never adapted to a driver silently)."""
    intent = get_own_intent(session, ref.id, owner_user_id)
    if intent.status != TripIntentStatus.ACTIVE.value:
        raise DomainError(ErrorCode.TRIP_INTENT_BOOKED, details={"status": intent.status})
    version = session.execute(select(TripIntentVersion).where(
        TripIntentVersion.intent_id == intent.id, TripIntentVersion.version_no == ref.version_no)).scalar_one_or_none()
    if version is None:
        raise DomainError(ErrorCode.NOT_FOUND, details={"field": "trip_intent.version_no"})
    if version.terms_version != intent.terms_version:
        raise DomainError(ErrorCode.TRIP_INTENT_CHANGED, details={"current_version_no": intent.current_version_no})
    if listing.service_type != intent.service_type:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          details={"field": "trip_intent", "reason": "trip_intent_service_mismatch"})
    if ensure_aware_utc(version.window_end) <= now:
        raise DomainError(ErrorCode.TRIP_INTENT_EXPIRED)
    if data.quantity != version.quantity:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={
            "field": "quantity", "reason": "trip_intent_quantity_mismatch", "required_quantity": version.quantity})
    if intent.service_type == ServiceType.PARCEL.value:
        needed = (version.weight_g, version.length_cm, version.width_cm, version.height_cm, version.receiver_name)
        if any(value is None for value in needed):
            raise DomainError(ErrorCode.VALIDATION_ERROR,
                              details={"field": "trip_intent", "reason": "trip_intent_parcel_incomplete"})
        parcel = data.parcel
        sent = None if parcel is None else (
            parcel.weight_g, parcel.length_cm, parcel.width_cm, parcel.height_cm,
            None if parcel.parcel_type is None else parcel.parcel_type.value,
            None if parcel.receiver is None else (parcel.receiver.name.strip(), parcel.receiver.phone.strip()))
        wanted = (version.weight_g, version.length_cm, version.width_cm, version.height_cm, version.parcel_type,
                  (version.receiver_name, version.receiver_phone))
        if sent != wanted:
            raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel", "reason": "trip_intent_parcel_mismatch"})
    elif data.parcel is not None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel", "reason": "passenger_request_has_no_parcel"})
    return intent, version


def verify_thread_intent(session: Session, thread: ProposalThread, *, for_accept: bool) -> TripIntent | None:
    """Under the thread lock (lock order threads -> trip_intents): the request must still be active and on the same
    terms the offer was made against. Accept takes the row lock the booking will update; submit/counter share it."""
    if thread.trip_intent_id is None:
        return None
    intent = _lock(session, thread.trip_intent_id, share=not for_accept)
    if intent.status != TripIntentStatus.ACTIVE.value:
        raise DomainError(ErrorCode.TRIP_INTENT_BOOKED, details={"status": intent.status})
    if thread.trip_intent_terms_version != intent.terms_version:
        raise DomainError(ErrorCode.TRIP_INTENT_CHANGED, details={"current_version_no": intent.current_version_no})
    return intent


def assert_counter_keeps_request(thread: ProposalThread, data: Any, current_quantity: int) -> None:
    """A counter on an offer made from a request negotiates price and time - not what the client asked for."""
    if thread.trip_intent_id is None:
        return
    if data.quantity is not None and data.quantity != current_quantity:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "quantity", "reason": "trip_intent_quantity_fixed"})
    if data.parcel is not None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "parcel", "reason": "trip_intent_parcel_fixed"})


def bind_booking(session: Session, intent: TripIntent, *, booking_id: int, accepted_thread_id: int,
                 now: datetime) -> None:
    """In the accept transaction, after the booking row: the request is booked and its other offers close."""
    TRIP_INTENT.assert_transition(intent.status, TripIntentStatus.BOOKED.value, "book")
    intent.status, intent.booking_id = TripIntentStatus.BOOKED.value, booking_id
    intent.version += 1
    intent.updated_at = now
    session.flush()
    close_open_threads(session, intent, reason=REASON_BOOKED, now=now, keep_thread_id=accepted_thread_id)


# --- advisory fit -------------------------------------------------------------------------------------------------


def fit(session: Session, intent: TripIntent, listing: Listing, *, now: datetime | None = None) -> dict[str, Any]:
    """Read-only comparison of one driver offer with the request (nothing is reserved; submit/accept decide)."""
    # Q138 (ADR-0026): saved requests answered driver listings, which are retired - history stays readable and
    # closable, but nothing new is created, edited, reopened or compared.
    raise DomainError(ErrorCode.TRIP_INTENT_RETIRED)


# --- DTO builders (owner view) -----------------------------------------------------------------------------------


def _end_dto(session: Session, row: TripIntentVersion, prefix: str) -> dict[str, Any]:
    """A saved end as history (Q160: no stop - the district and the marked place)."""
    from app.modules.geo.schemas import DistrictRefDTO
    from app.modules.geo.service import districts_by_ids

    district_id = getattr(row, f"{prefix}_district_id")
    district = districts_by_ids(session, [district_id]).get(district_id) if district_id else None
    lat, lng = getattr(row, f"{prefix}_lat"), getattr(row, f"{prefix}_lng")
    return {"district": DistrictRefDTO(id=district.api_id, name_uz=district.name_uz) if district else None,
            "lat": None if lat is None else float(lat), "lng": None if lng is None else float(lng),
            "address": getattr(row, f"{prefix}_address")}


def intent_dto(session: Session, intent: TripIntent, *, now: datetime | None = None) -> dict[str, Any]:
    from app.modules.marketplace import service as mp

    now = _now(now)
    version = current_version(session, intent)
    total = None if version.price_basis is None else compute_total_minor(
        PriceBasis(version.price_basis), version.unit_price_minor, version.quantity)
    parcel = None
    if intent.service_type == ServiceType.PARCEL.value:
        receiver = None if version.receiver_name is None else {"name": version.receiver_name, "phone": version.receiver_phone}
        parcel = {"parcel_type": version.parcel_type, "weight_g": version.weight_g, "length_cm": version.length_cm,
                  "width_cm": version.width_cm, "height_cm": version.height_cm, "receiver": receiver}
    threads = session.execute(select(ProposalThread).where(ProposalThread.trip_intent_id == intent.id)
                              .order_by(ProposalThread.id.desc()).limit(50)).scalars().all()
    booking_ids = {row.proposal_thread_id: row.public_id for row in session.execute(
        text("SELECT proposal_thread_id, public_id FROM bookings WHERE trip_intent_id = :i"), {"i": intent.id})}
    offers = [{
        "thread_id": mp.thread_public_id(thread),
        "listing_id": mp.listing_public_id(mp.get_listing(session, thread.listing_id)),
        "state": thread.state, "closed_reason": thread.closed_reason,
        "terms_current": thread.trip_intent_terms_version == intent.terms_version,
        "booking_id": format_public_id(PublicIdPrefix.BOOKING, booking_ids[thread.id]) if thread.id in booking_ids else None,
    } for thread in threads]
    booking_public = None
    booking_cancelled = False
    if intent.booking_id is not None:
        booking_public = session.execute(text("SELECT public_id FROM bookings WHERE id = :b"),
                                         {"b": intent.booking_id}).scalar()
        booking_cancelled = _booking_status(session, intent.booking_id) == "cancelled"
    return {
        "id": intent_public_id(intent), "service_type": intent.service_type, "status": intent.status,
        "version": intent.version, "expired": ensure_aware_utc(version.window_end) <= now,
        "current_version": {
            "version_no": version.version_no, "terms_version": version.terms_version,
            "origin": _end_dto(session, version, "origin"), "destination": _end_dto(session, version, "destination"),
            "window_start": ensure_aware_utc(version.window_start), "window_end": ensure_aware_utc(version.window_end),
            "quantity": version.quantity, "price_basis": version.price_basis,
            "unit_price_minor": version.unit_price_minor, "total_minor": total, "parcel": parcel,
            "created_at": ensure_aware_utc(version.created_at),
        },
        "booking_id": None if booking_public is None else format_public_id(PublicIdPrefix.BOOKING, booking_public),
        "booking_cancelled": booking_cancelled,
        "can_reopen": intent.status == TripIntentStatus.BOOKED.value and booking_cancelled,
        "open_offers": sum(1 for offer in offers if offer["state"] == THREAD_OPEN),
        "offers": offers,
        "created_at": ensure_aware_utc(intent.created_at), "updated_at": ensure_aware_utc(intent.updated_at),
    }


def retire_intent(session: Session, intent_id: int, *, now: datetime | None = None) -> bool:
    """Q138 (ADR-0026, worker): close an ``active`` saved request - the driver listings it answered are retired.

    Technical closure (reason ``driver_listing_retired``): no client fault, no penalty, open offers expire through the
    outbox (``SKIP LOCKED``; the stale-thread sweep catches any it skipped). A booked request keeps its booking link.
    """
    now = _now(now)
    intent = _lock(session, intent_id)
    if intent.status != TripIntentStatus.ACTIVE.value:
        return False
    TRIP_INTENT.assert_transition(intent.status, TripIntentStatus.CLOSED.value, "close")
    intent.status, intent.closed_reason, intent.booking_id = TripIntentStatus.CLOSED.value, "driver_listing_retired", None
    intent.version += 1
    intent.updated_at = now
    session.flush()
    close_open_threads(session, intent, reason="driver_listing_retired", now=now)
    return True
