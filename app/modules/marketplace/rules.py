"""Pure listing and proposal rules (spec §5.1-5.4; D9; AC01, AC04, AC05, AC43). No I/O."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.contracts.enums import ALLOWED_PRICE_BASIS, ActorSide, ListingKind, PriceBasis, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.money import total_minor
from app.contracts.timeutil import ensure_aware_utc

LISTING_TIMEZONE = "Asia/Tashkent"
PROPOSAL_MAX_TTL = timedelta(hours=2)
PROPOSAL_NEAR_DEPARTURE_TTL = timedelta(minutes=10)
MAX_PRICE_REVISIONS_PER_SIDE = 3
PROPOSAL_MESSAGE_MAX_LENGTH = 500

# ADR-0027 Q154: new business on a trip that is boarding or on the way, while the pickup is still ahead.
MID_TRIP_BOOKING_ENABLED = True
MID_TRIP_MIN_LEAD = timedelta(minutes=15)  # the scheduled pickup is at least this far in the future
MID_TRIP_MIN_AHEAD_M = 2_000  # a fresh GPS fix is at least this far before the pickup along the road
MID_TRIP_GPS_MAX_AGE = timedelta(minutes=10)  # an older fix says nothing about where the car is now
MID_TRIP_GPS_MAX_OFFSET_M = 50_000  # a fix this far off the road is not on the trip at all; ignored
MID_TRIP_PROPOSAL_TTL = timedelta(minutes=10)


def ensure_price_basis_allowed(kind: ListingKind, service_type: ServiceType, price_basis: PriceBasis) -> None:
    allowed = ALLOWED_PRICE_BASIS[(ListingKind(kind), ServiceType(service_type))]
    if PriceBasis(price_basis) not in allowed:
        raise DomainError(
            ErrorCode.PRICE_BASIS_NOT_ALLOWED,
            details={"price_basis": str(price_basis), "allowed": sorted(item.value for item in allowed)},
        )


def compute_total_minor(price_basis: PriceBasis, unit_price_minor: int, quantity: int) -> int:
    """Server-side total (spec §14.1): ``per_seat`` multiplies, ``total`` is the whole price."""
    if PriceBasis(price_basis) is PriceBasis.PER_SEAT:
        return total_minor(unit_price_minor, quantity)
    total_minor(unit_price_minor, 1)  # validates a positive integer amount
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive int")
    return unit_price_minor


def listing_quantity(
    kind: ListingKind, service_type: ServiceType, *, seat_count: int | None, trip_seat_capacity: int | None
) -> int:
    kind, service_type = ListingKind(kind), ServiceType(service_type)
    if service_type is ServiceType.PARCEL:
        return 1
    if kind is ListingKind.REQUEST:
        if not seat_count or seat_count < 1:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "passenger request needs seat_count", details={"field": "passenger"})
        return seat_count
    if not trip_seat_capacity or trip_seat_capacity < 1:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR, "passenger trip offer needs a trip with seats", details={"field": "trip_id"}
        )
    return trip_seat_capacity


def check_proposal_quantity(
    *, listing_kind: ListingKind, service_type: ServiceType, listing_quantity: int, quantity: int
) -> None:
    """D9: a request is never split; a parcel is one shipment.

    ``trip_offer`` passenger proposals only need ``quantity >= 1`` here; the
    remaining seats on the segment are checked against trip capacity.
    """
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "quantity"})
    if ServiceType(service_type) is ServiceType.PARCEL:
        if quantity != 1:
            raise DomainError(ErrorCode.QUANTITY_MISMATCH, details={"required_quantity": 1, "quantity": quantity})
        return
    if ListingKind(listing_kind) is ListingKind.REQUEST and quantity != listing_quantity:
        raise DomainError(
            ErrorCode.QUANTITY_MISMATCH, details={"required_quantity": listing_quantity, "quantity": quantity}
        )


def proposal_expires_at(
    *,
    now: datetime,
    departure_at: datetime,
    booking_cutoff_at: datetime,
    listing_expires_at: datetime | None = None,
) -> datetime:
    """``min(now + (2 h if departure is more than 2 h away else 10 min), cutoff, listing expiry)``."""
    now = ensure_aware_utc(now)
    departure_at = ensure_aware_utc(departure_at, field="departure_at")
    cutoff = ensure_aware_utc(booking_cutoff_at, field="booking_cutoff_at")
    if now >= cutoff:
        raise DomainError(ErrorCode.BOOKING_CUTOFF_PASSED)
    ttl = PROPOSAL_MAX_TTL if departure_at - now > PROPOSAL_MAX_TTL else PROPOSAL_NEAR_DEPARTURE_TTL
    candidates = [now + ttl, cutoff]
    if listing_expires_at is not None:
        listing_expiry = ensure_aware_utc(listing_expires_at, field="listing_expires_at")
        if listing_expiry <= now:
            raise DomainError(ErrorCode.LISTING_NOT_OPEN, details={"reason": "listing_expired"})
        candidates.append(listing_expiry)
    return min(candidates)


def moving_trip_proposal_expires_at(
    *, now: datetime, pickup_eta: datetime, listing_expires_at: datetime | None = None
) -> datetime:
    """Q154: a proposal on a trip already boarding or on the way lives ``min(now + 10 min, ETA - 15 min, listing expiry)``."""
    now = ensure_aware_utc(now)
    candidates = [now + MID_TRIP_PROPOSAL_TTL, ensure_aware_utc(pickup_eta) - MID_TRIP_MIN_LEAD]
    if listing_expires_at is not None:
        candidates.append(ensure_aware_utc(listing_expires_at))
    expires = min(candidates)
    if expires <= now:
        raise DomainError(ErrorCode.BOOKING_CUTOFF_PASSED, details={"reason": "pickup_passed"})
    return expires


def time_proposal_in_range(
    *, request_start: datetime, request_end: datetime, pickup_at: datetime, max_early: timedelta, max_late: timedelta
) -> bool:
    """ADR-0027 Q157: a driver's proposed pickup time is at most ``max_early`` before the client's window starts and at
    most ``max_late`` after it ends (asymmetric - leaving hours earlier than asked is rarely usable on intercity trips).

    Client asked 07:55-08:55, limits 3 h / 12 h -> any pickup from 04:55 to 20:55 may be proposed; 23:43 the evening
    before may not. ``pickup_at`` is the car's ETA (the middle of the proposed window)."""
    pickup_at = ensure_aware_utc(pickup_at)
    return ensure_aware_utc(request_start) - max_early <= pickup_at <= ensure_aware_utc(request_end) + max_late


def next_price_revision_count(current: int, *, price_changed: bool) -> int:
    """Each side may change the price at most 3 times in one negotiation (spec §5.3)."""
    if not price_changed:
        return current
    if current >= MAX_PRICE_REVISIONS_PER_SIDE:
        raise DomainError(ErrorCode.NEGOTIATION_LIMIT_REACHED, details={"limit": MAX_PRICE_REVISIONS_PER_SIDE})
    return current + 1


def proposer_side(listing_kind: ListingKind) -> ActorSide:
    """Requests are answered by drivers, trip offers by clients (spec §5.1)."""
    return ActorSide.DRIVER if ListingKind(listing_kind) is ListingKind.REQUEST else ActorSide.CLIENT


def counterparty(side: ActorSide) -> ActorSide:
    side = ActorSide(side)
    if side is ActorSide.CLIENT:
        return ActorSide.DRIVER
    if side is ActorSide.DRIVER:
        return ActorSide.CLIENT
    raise ValueError("only client/driver sides negotiate")


def parcel_volume_ml(length_cm: int, width_cm: int, height_cm: int) -> int:
    """1 cm³ = 1 ml (D14 units)."""
    return length_cm * width_cm * height_cm


def display_name(full_name: str | None) -> str:
    """First name only in public/negotiation views; never phone or surname."""
    if full_name and full_name.strip():
        return full_name.strip().split()[0][:64]
    return "Elchi"
