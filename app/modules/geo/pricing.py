"""Corridor price bands (decision Q42): pure selection and checks, no I/O.

A band is an operator-configured floor/ceiling for one corridor and service type. Amounts are integer minor
units: passenger bands are per seat (``per_seat``), parcel bands are the delivery total (``total``). With no active
band there is no reference (``None``). Marketplace use (proposal submit/counter) is A1's; geo only resolves and
compares.

ADR-0028 / Q160: bands are corridor-wide only - ELCHI has no stops, so there is no stop pair to price. Legacy
stop-pair rows are frozen history and never read.
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

    @property
    def price_basis(self) -> PriceBasis:
        return PRICE_BAND_BASIS[self.service_type]

    @property
    def scope(self) -> str:
        return "corridor"


def select_price_band(bands: Iterable[PriceBand], *, corridor_id: int, service_type: ServiceType) -> PriceBand | None:
    """The corridor's active band for the service (newest version); inactive bands and other corridors/services are
    ignored. A *reference*, not a fare: it feeds the ranking score and the advisory warning (Q90)."""
    service = ServiceType(service_type)
    relevant = [b for b in bands if b.is_active and b.corridor_id == corridor_id and b.service_type is service]
    return max(relevant, key=lambda b: b.version) if relevant else None


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
