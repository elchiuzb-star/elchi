"""Corridor price bands (decision Q42): pure selection and checks, no I/O.

A band is an operator-configured floor/ceiling for one corridor and service type, either for one
segment (origin stop -> destination stop) or corridor-wide. Amounts are integer minor units:
passenger bands are per seat (``per_seat``), parcel bands are the delivery total (``total``).

Precedence: an active segment band for the exact (origin, destination) wins over the active
corridor-wide band; with neither, there is no band (``None``) and no price limit applies.
Marketplace enforcement (proposal submit/counter) is A1's; geo only resolves and compares.

Q53 operating model: corridor-wide bands are loose safety limits (catch obvious typos and abuse);
exact segment bands set the real price range for a segment. G13 warns the operator when a
corridor-wide floor exceeds the lowest active segment floor (``service.price_band_warnings``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.contracts.enums import PriceBasis, ServiceType
from app.contracts.errors import DomainError, ErrorCode

PRICE_BAND_BASIS: dict[ServiceType, PriceBasis] = {
    ServiceType.PASSENGER: PriceBasis.PER_SEAT,
    ServiceType.PARCEL: PriceBasis.TOTAL,
}


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int")
    return value


@dataclass(frozen=True, slots=True)
class PriceBand:
    corridor_id: int
    service_type: ServiceType
    origin_stop_id: int | None
    destination_stop_id: int | None
    floor_minor: int
    ceiling_minor: int
    is_active: bool
    version: int
    currency: str = "UZS"
    #: Q90: an ordinary band advises; only an admin-imposed abuse/safety limit refuses a price.
    enforced: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_type", ServiceType(self.service_type))
        _positive_int(self.corridor_id, "corridor_id")
        _positive_int(self.floor_minor, "floor_minor")
        _positive_int(self.ceiling_minor, "ceiling_minor")
        _positive_int(self.version, "version")
        if self.floor_minor > self.ceiling_minor:
            raise ValueError("floor_minor must not exceed ceiling_minor")
        if (self.origin_stop_id is None) != (self.destination_stop_id is None):
            raise ValueError("a segment band needs both origin and destination stops")
        if self.origin_stop_id is not None and self.origin_stop_id == self.destination_stop_id:
            raise ValueError("segment origin and destination must differ")

    @property
    def price_basis(self) -> PriceBasis:
        return PRICE_BAND_BASIS[self.service_type]

    @property
    def scope(self) -> str:
        return "corridor" if self.origin_stop_id is None else "segment"


def select_price_band(
    bands: Iterable[PriceBand],
    *,
    corridor_id: int,
    service_type: ServiceType,
    origin_stop_id: int | None,
    destination_stop_id: int | None,
) -> PriceBand | None:
    """Segment band over corridor-wide band; inactive bands and other corridors/services are ignored.

    Q88: a map-point end has no stop id, so there is no segment to look up and the corridor-wide band - the
    broad reference for the whole direction - is what applies. That is a *reference*, not a fare: it feeds the
    ranking score and the advisory warning exactly as it does for a stop pair (Q90).
    """
    service = ServiceType(service_type)
    relevant = [b for b in bands if b.is_active and b.corridor_id == corridor_id and b.service_type is service]
    if origin_stop_id is not None and destination_stop_id is not None:
        segment = [
            b for b in relevant if b.origin_stop_id == origin_stop_id and b.destination_stop_id == destination_stop_id
        ]
        if segment:
            return max(segment, key=lambda b: b.version)
    corridor_wide = [b for b in relevant if b.origin_stop_id is None]
    if corridor_wide:
        return max(corridor_wide, key=lambda b: b.version)
    return None


def price_within_band(band: PriceBand, *, price_basis: PriceBasis, unit_price_minor: int, quantity: int) -> bool:
    """True if the offered price respects the band.

    Passenger bands are per seat: a ``per_seat`` price is compared directly; a ``total`` price for
    ``quantity`` seats is compared with ``floor * quantity .. ceiling * quantity`` (no rounding).
    Parcel bands and prices are totals.
    """
    _positive_int(unit_price_minor, "unit_price_minor")
    _positive_int(quantity, "quantity")
    basis = PriceBasis(price_basis)
    if band.service_type is ServiceType.PASSENGER and basis is PriceBasis.TOTAL:
        return band.floor_minor * quantity <= unit_price_minor <= band.ceiling_minor * quantity
    return band.floor_minor <= unit_price_minor <= band.ceiling_minor


def band_details(band: PriceBand) -> dict:
    """The Q53 contract shape, used both for the warning and for the enforced refusal."""
    return {
        "floor_minor": band.floor_minor,
        "ceiling_minor": band.ceiling_minor,
        "currency": band.currency,
        "price_basis": band.price_basis.value,
        "scope": band.scope,
    }


def evaluate_price_band(
    band: PriceBand | None, *, price_basis: PriceBasis, unit_price_minor: int, quantity: int
) -> dict | None:
    """Q90: how a band answers an offered price - advice, not a verdict.

    Returns ``None`` when there is no band or the price sits inside it. Otherwise it returns the Q53 details
    so the caller can attach a warning; whether that also *refuses* the price is `band.enforced`, and that
    decision belongs to the caller, not here. ELCHI's price is what the two sides agree on: a band that
    silently blocked a counteroffer would turn the auction into a fixed fare.
    """
    if band is None or price_within_band(
        band, price_basis=price_basis, unit_price_minor=unit_price_minor, quantity=quantity
    ):
        return None
    return band_details(band)


def assert_price_within_band(band: PriceBand | None, *, price_basis: PriceBasis, unit_price_minor: int, quantity: int) -> None:
    """Refuse a price only for an **enforced** band (Q90); an ordinary band never blocks a negotiation.

    Kept as the single place that raises ``PRICE_OUT_OF_BAND`` so an admin-imposed abuse/safety limit still
    has one enforcement point (API_V2_CONTRACT §7).
    """
    details = evaluate_price_band(band, price_basis=price_basis, unit_price_minor=unit_price_minor, quantity=quantity)
    if details is None or band is None or not band.enforced:
        return
    raise DomainError(ErrorCode.PRICE_OUT_OF_BAND, details=details)
