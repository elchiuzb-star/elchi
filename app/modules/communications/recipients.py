"""Per-user recipients of an outbox event (WAVE1_CARDS "Wave 3" A7 item 3; N2/Q16; ADR-0019 §9).

Read-only: other modules' tables are only read here (AGENTS §4). Concrete audience copies are built by the
dispatcher with ``events.payload_for_audience``; this module only decides WHO and in WHICH audience.

* ``booking``          -> client (client) + driver (driver)
* ``listing``          -> owner (request -> client, trip_offer -> driver)
* ``proposal_thread``  -> both parties + eligible drivers with another open thread on the same request listing
                          (``competing_driver``)
* ``trip``             -> driver + clients of the trip's non-terminal bookings
* ``wallet``/``topup`` -> driver
* ``user``             -> that user in the most restrictive marketplace audience (``client``)
* ``chat_thread``      -> the other party
* ``saved_search``     -> owner (side ``requests`` -> driver, ``offers`` -> client)
* anything else with a ``booking_id`` payload key -> the booking's parties
Staff-only events are not delivered per user (staff read them through N1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.contracts.communications import DispatchedEvent
from app.contracts.enums import ActorSide, ListingKind
from app.contracts.errors import DomainError
from app.contracts.events import EventAudience
from app.contracts.ids import PublicIdPrefix, format_public_id, parse_public_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Recipient:
    user_id: int
    audience: EventAudience
    link: str | None = None


def _side_audience(side: ActorSide | str) -> EventAudience:
    return EventAudience.DRIVER if ActorSide(side) is ActorSide.DRIVER else EventAudience.CLIENT


def _booking(session: Session, event: DispatchedEvent, public_id: str | None = None):  # noqa: ANN202 - Booking | None
    from app.modules.bookings import service as bookings_service

    try:
        if public_id is not None:
            return bookings_service.get_booking_by_public_id(session, public_id)
        if event.aggregate_id is not None:
            return bookings_service.get_booking(session, event.aggregate_id)
        return bookings_service.get_booking_by_public_id(session, event.aggregate_public_id)
    except DomainError:
        return None


def _booking_parties(session: Session, event: DispatchedEvent, public_id: str | None = None) -> list[Recipient]:
    booking = _booking(session, event, public_id)
    if booking is None:
        return []
    link = f"/bookings/{format_public_id(PublicIdPrefix.BOOKING, booking.public_id)}"
    return [
        Recipient(booking.client_user_id, EventAudience.CLIENT, link),
        Recipient(booking.driver_user_id, EventAudience.DRIVER, link),
    ]


def _listing(session: Session, event: DispatchedEvent) -> list[Recipient]:
    from app.modules.marketplace import service as marketplace_service

    try:
        listing = (
            marketplace_service.get_listing(session, event.aggregate_id)
            if event.aggregate_id is not None
            else marketplace_service.get_listing_by_public_id(session, event.aggregate_public_id)
        )
    except DomainError:
        return []
    audience = EventAudience.DRIVER if listing.kind == ListingKind.TRIP_OFFER.value else EventAudience.CLIENT
    return [Recipient(listing.owner_user_id, audience, f"/listings/{marketplace_service.listing_public_id(listing)}")]


def _competing_drivers(session: Session, thread) -> list[Recipient]:  # noqa: ANN001
    from app.modules.identity import service as identity_service
    from app.modules.marketplace import service as marketplace_service
    from app.modules.marketplace.models import ProposalThread

    listing = marketplace_service.get_listing(session, thread.listing_id)
    if listing.kind != ListingKind.REQUEST.value:
        return []
    driver_ids = session.execute(
        select(ProposalThread.driver_user_id)
        .where(
            ProposalThread.listing_id == thread.listing_id,
            ProposalThread.state == "open",
            ProposalThread.driver_user_id.not_in([thread.client_user_id, thread.driver_user_id]),
        )
        .distinct()
        .order_by(ProposalThread.driver_user_id)
    ).scalars()
    link = f"/listings/{marketplace_service.listing_public_id(listing)}"
    result = []
    for driver_id in driver_ids:
        try:
            eligible = identity_service.get_capabilities(session, driver_id).driver_eligible
        except DomainError:
            eligible = False
        if eligible:  # Q21: blocked/ineligible drivers do not see the listing's offers
            result.append(Recipient(driver_id, EventAudience.COMPETING_DRIVER, link))
    return result


def _proposal_thread(session: Session, event: DispatchedEvent) -> list[Recipient]:
    from app.modules.marketplace import service as marketplace_service
    from app.modules.marketplace.models import ProposalThread

    try:
        thread = (
            session.get(ProposalThread, event.aggregate_id)
            if event.aggregate_id is not None
            else marketplace_service.get_thread_by_public_id(session, event.aggregate_public_id)
        )
    except DomainError:
        thread = None
    if thread is None:
        return []
    link = f"/proposals/{marketplace_service.thread_public_id(thread)}"
    parties = [
        Recipient(thread.client_user_id, EventAudience.CLIENT, link),
        Recipient(thread.driver_user_id, EventAudience.DRIVER, link),
    ]
    return parties + _competing_drivers(session, thread)


def _booking_live_state_fn():  # noqa: ANN202 - Callable | None
    """A6 export ``tracking.service.booking_live_state`` (lazy; tolerated when missing)."""
    try:
        from app.modules.tracking import service as tracking_service

        return tracking_service.booking_live_state
    except (ImportError, AttributeError):
        logger.warning("tracking.service.booking_live_state unavailable; trip tracking events not delivered to clients")
        return None


def _tracking_window_open(session: Session, live_state, booking_id: int) -> bool:  # noqa: ANN001
    if live_state is None:
        return False
    try:
        return bool(live_state(session, booking_id).window.is_open)
    except DomainError:
        return False


def _trip(session: Session, event: DispatchedEvent) -> list[Recipient]:
    from app.modules.bookings.models import Booking
    from app.modules.bookings.rules import TERMINAL_SERVICE_STATUSES
    from app.modules.trips import service as trips_service

    try:
        trip = (
            trips_service.get_trip(session, event.aggregate_id)
            if event.aggregate_id is not None
            else trips_service.get_trip_by_public_id(session, event.aggregate_public_id)
        )
    except DomainError:
        return []
    result = [Recipient(trip.driver_user_id, EventAudience.DRIVER, f"/trips/{trips_service.trip_public_id(trip)}")]
    rows = session.execute(
        select(Booking.id, Booking.client_user_id, Booking.public_id)
        .where(Booking.trip_id == trip.id, Booking.service_status.not_in(sorted(TERMINAL_SERVICE_STATUSES)))
        .order_by(Booking.id)
    ).all()
    tracking_scoped = event.event_type.value.startswith("tracking.")
    live_state = _booking_live_state_fn() if tracking_scoped else None
    for booking_id, client_user_id, public_id in rows:
        # BR L1: a client hears about tracking (e.g. tracking.stale) only while its booking's tracking window is open
        # (§10.6, AC44, U1); without A6's reader nothing is delivered to clients.
        if tracking_scoped and not _tracking_window_open(session, live_state, booking_id):
            continue
        result.append(
            Recipient(client_user_id, EventAudience.CLIENT, f"/bookings/{format_public_id(PublicIdPrefix.BOOKING, public_id)}")
        )
    return result


def _wallet(session: Session, event: DispatchedEvent) -> list[Recipient]:
    from app.modules.wallet.models import TopupRequest, WalletAccount

    model = WalletAccount if event.aggregate_type == "wallet" else TopupRequest
    prefix = PublicIdPrefix.WALLET if model is WalletAccount else PublicIdPrefix.TOPUP
    if event.aggregate_id is not None:
        row = session.get(model, event.aggregate_id)
    else:
        try:
            value = parse_public_id(event.aggregate_public_id, prefix)
        except DomainError:
            return []
        row = session.execute(select(model).where(model.public_id == value)).scalar_one_or_none()
    return [] if row is None else [Recipient(row.driver_user_id, EventAudience.DRIVER, "/wallet")]


def _user(session: Session, event: DispatchedEvent) -> list[Recipient]:
    from app.modules.identity import service as identity_service

    user_id = event.aggregate_id
    if user_id is None:
        try:
            user_id = identity_service.resolve_user_id(session, event.aggregate_public_id)
        except DomainError:
            return []
    return [Recipient(user_id, EventAudience.CLIENT, None)]


def _chat_thread(session: Session, event: DispatchedEvent) -> list[Recipient]:
    from app.modules.communications.models import ChatThread

    thread = session.get(ChatThread, event.aggregate_id) if event.aggregate_id is not None else None
    if thread is None:
        try:
            value = parse_public_id(event.aggregate_public_id, PublicIdPrefix.CHAT_THREAD)
        except DomainError:
            return []
        thread = session.execute(select(ChatThread).where(ChatThread.public_id == value)).scalar_one_or_none()
    if thread is None:
        return []
    if thread.proposal_thread_id is not None:
        from app.modules.marketplace import service as marketplace_service
        from app.modules.marketplace.models import ProposalThread

        parent = session.get(ProposalThread, thread.proposal_thread_id)
        link = f"/proposals/{marketplace_service.thread_public_id(parent)}/messages"
    else:
        from app.modules.bookings.models import Booking

        parent = session.get(Booking, thread.booking_id)
        link = f"/bookings/{format_public_id(PublicIdPrefix.BOOKING, parent.public_id)}/messages"
    author_side = event.payload.get("author_side")
    parties = [
        Recipient(parent.client_user_id, EventAudience.CLIENT, link),
        Recipient(parent.driver_user_id, EventAudience.DRIVER, link),
    ]
    return [r for r in parties if author_side is None or r.audience != _side_audience(author_side)]


def _saved_search(session: Session, event: DispatchedEvent) -> list[Recipient]:
    """A5 owns ``saved_searches`` (0061, written in parallel): read only, tolerate its absence."""
    from app.modules.platform.service import table_exists

    if not table_exists(session, "saved_searches"):
        return []
    columns = set(
        session.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'saved_searches'")
        ).scalars()
    )
    owner_column = next((name for name in ("user_id", "owner_user_id") if name in columns), None)
    if owner_column is None:
        logger.warning("saved_searches has no owner column; saved_search event not delivered")
        return []
    if event.aggregate_id is not None:
        owner = session.execute(text(f"SELECT {owner_column} FROM saved_searches WHERE id = :id"), {"id": event.aggregate_id}).scalar()
    else:
        try:
            value = parse_public_id(event.aggregate_public_id, PublicIdPrefix.SAVED_SEARCH)
        except DomainError:
            return []
        owner = session.execute(text(f"SELECT {owner_column} FROM saved_searches WHERE public_id = :p"), {"p": value}).scalar()
    if owner is None:
        return []
    audience = EventAudience.DRIVER if event.payload.get("side") == "requests" else EventAudience.CLIENT
    listing_id = event.payload.get("listing_id")
    return [Recipient(int(owner), audience, f"/listings/{listing_id}" if listing_id else None)]


_RESOLVERS = {
    "booking": lambda session, event: _booking_parties(session, event),
    "listing": _listing,
    "proposal_thread": _proposal_thread,
    "trip": _trip,
    "wallet": _wallet,
    "topup": _wallet,
    "user": _user,
    "chat_thread": _chat_thread,
    "saved_search": _saved_search,
}


def resolve_recipients(session: Session, event: DispatchedEvent) -> list[Recipient]:
    """Distinct recipients (first audience wins for a user listed twice). Unknown aggregates -> ``booking_id`` or none."""
    resolver = _RESOLVERS.get(event.aggregate_type)
    if resolver is not None:
        candidates = resolver(session, event)
    elif isinstance(event.payload.get("booking_id"), str):
        candidates = _booking_parties(session, event, event.payload["booking_id"])
    else:
        candidates = []
    seen: set[int] = set()
    result: list[Recipient] = []
    for recipient in candidates:
        if recipient.user_id in seen:
            continue
        seen.add(recipient.user_id)
        result.append(recipient)
    return result
