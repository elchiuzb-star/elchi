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
