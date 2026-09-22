"""Money arithmetic for stage 2 (spec §9.4, ADR-0003).

* Amounts are integers in minor units (UZS: 1 so'm = 100 tiyin). Never float.
* Rates are integer basis points (15% = 1500 bps).
* ``commission_minor = round_half_up(total_minor * fee_bps / 10000)`` is the
  only commission formula; every module must call :func:`commission_minor`.
* Legacy ``Numeric(12, 2)`` so'm values and ``Numeric(5, 4)`` rates convert
  exactly through :class:`decimal.Decimal`; inexact values raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from datetime import datetime

from app.contracts.enums import CommissionPolicyKind, CommissionStatus, Currency
from app.contracts.timeutil import ensure_aware_utc

MINOR_UNITS_PER_MAJOR: dict[Currency, int] = {Currency.UZS: 100}
# Q17 two-person rule: top-ups/adjustments strictly above this need a second, different
# staff approver. Pilot decision (integration pass 1): a contract constant (changes go
# through the integrator + audit trail in git/ADR); a staff-managed audited setting is a
# post-pilot option. Must equal app.modules.wallet.service.LARGE_AMOUNT_THRESHOLD_MINOR.
TWO_PERSON_APPROVAL_THRESHOLD_MINOR = 100_000_000  # 1 000 000 so'm
BPS_DENOMINATOR = 10_000
MIN_FEE_BPS = 0
MAX_FEE_BPS = 10_000
# PostgreSQL BIGINT upper bound; amounts above it cannot be stored.
MAX_MINOR_AMOUNT = 9_223_372_036_854_775_807


def _require_int(value: object, name: str) -> int:
    # bool is a subclass of int and float silently loses precision: reject both.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    return value


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer division rounding halves away from zero.

    Matches ``Decimal.quantize(..., rounding=ROUND_HALF_UP)`` for both signs,
    so reversals of a rounded amount mirror the original.
    """
    _require_int(numerator, "numerator")
    _require_int(denominator, "denominator")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    quotient, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return quotient if numerator >= 0 else -quotient


def validate_minor_amount(amount_minor: int, *, allow_zero: bool = True, name: str = "amount_minor") -> int:
    _require_int(amount_minor, name)
    if amount_minor < 0 or (amount_minor == 0 and not allow_zero):
        raise ValueError(f"{name} must be {'non-negative' if allow_zero else 'positive'}")
    if amount_minor > MAX_MINOR_AMOUNT:
        raise ValueError(f"{name} exceeds BIGINT range")
    return amount_minor


def validate_fee_bps(fee_bps: int) -> int:
    _require_int(fee_bps, "fee_bps")
    if not MIN_FEE_BPS <= fee_bps <= MAX_FEE_BPS:
        raise ValueError(f"fee_bps must be between {MIN_FEE_BPS} and {MAX_FEE_BPS}")
    return fee_bps


def total_minor(unit_price_minor: int, quantity: int) -> int:
    """Server-side total, e.g. 2 x 20_000_000 = 40_000_000 (spec §14.1)."""
    validate_minor_amount(unit_price_minor, allow_zero=False, name="unit_price_minor")
    _require_int(quantity, "quantity")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    return validate_minor_amount(unit_price_minor * quantity, name="total_minor")


def commission_minor(total_amount_minor: int, fee_bps: int) -> int:
    """The single commission formula (spec §9.4)."""
    validate_minor_amount(total_amount_minor, name="total_minor")
    validate_fee_bps(fee_bps)
    return round_half_up_div(total_amount_minor * fee_bps, BPS_DENOMINATOR)


def net_after_commission_minor(total_amount_minor: int, fee_bps: int) -> int:
    """Driver's transport revenue after commission; never called "profit" (spec §8.4)."""
    return total_amount_minor - commission_minor(total_amount_minor, fee_bps)


def _to_decimal(value: Decimal | int | str, name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{name} must be Decimal, int or str, not {type(value).__name__}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a valid decimal: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def major_to_minor(amount_major: Decimal | int | str, currency: Currency = Currency.UZS) -> int:
    """Exact conversion of a legacy major-unit amount (e.g. ``Decimal('60000.00')``)."""
    scaled = _to_decimal(amount_major, "amount_major") * MINOR_UNITS_PER_MAJOR[currency]
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{amount_major!r} has more precision than {currency} minor units")
    return int(scaled)


def minor_to_major(amount_minor: int, currency: Currency = Currency.UZS) -> Decimal:
    """For legacy v1 adapters and reports only; v2 APIs expose minor units."""
    _require_int(amount_minor, "amount_minor")
    return Decimal(amount_minor) / Decimal(MINOR_UNITS_PER_MAJOR[currency])


def legacy_rate_to_bps(rate: Decimal | int | str) -> int:
    """``Decimal('0.1500')`` (orders.system_fee_rate) -> 1500 bps, exactly."""
    scaled = _to_decimal(rate, "rate") * BPS_DENOMINATOR
    if scaled != scaled.to_integral_value():
        raise ValueError(f"rate {rate!r} is not representable in whole basis points")
    return validate_fee_bps(int(scaled))


def percent_to_bps(percent: Decimal | int | str) -> int:
    """Admin input ``15`` or ``'12.5'`` -> 1500 / 1250 bps, exactly."""
    scaled = _to_decimal(percent, "percent") * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(f"percent {percent!r} is not representable in whole basis points")
    return validate_fee_bps(int(scaled))


def bps_to_percent(fee_bps: int) -> Decimal:
    return Decimal(validate_fee_bps(fee_bps)) / Decimal(100)


def validate_policy_terms(
    kind: CommissionPolicyKind,
    fee_bps: int,
    effective_from: datetime,
    effective_to: datetime | None,
) -> None:
    """Decision 1: 0 bps exists only as an explicit, time-boxed campaign.

    * ``standard`` policies must charge (fee_bps > 0) and may be open-ended.
    * ``campaign`` policies must have ``effective_to`` (time-boxed).
    Retroactivity (``effective_from < now``) is checked by the wallet service.
    """
    kind = CommissionPolicyKind(kind)
    validate_fee_bps(fee_bps)
    start = ensure_aware_utc(effective_from, field="effective_from")
    end = None if effective_to is None else ensure_aware_utc(effective_to, field="effective_to")
    if end is not None and end <= start:
        raise ValueError("effective_to must be after effective_from")
    if kind is CommissionPolicyKind.STANDARD and fee_bps == 0:
        raise ValueError("0 bps is allowed only as a time-boxed campaign policy")
    if kind is CommissionPolicyKind.CAMPAIGN and end is None:
        raise ValueError("campaign policies must be time-boxed (effective_to required)")


def initial_commission_status(snapshot_fee_bps: int) -> CommissionStatus:
    """``exempt`` only for a 0 bps snapshot; never derived from wallet_required."""
    return CommissionStatus.EXEMPT if validate_fee_bps(snapshot_fee_bps) == 0 else CommissionStatus.HELD


def balance_check_required(*, is_production: bool, wallet_required_flag: bool) -> bool:
    """Meaning of ``wallet_required`` (decision 1, spec §9.2).

    Production: always True; a False flag there is a configuration error.
    Outside production: False skips only the balance-sufficiency check. The fee
    is still computed from the real policy, snapshotted and held.
    """
    if is_production:
        if not wallet_required_flag:
            raise ValueError("wallet_required cannot be false in production")
        return True
    return wallet_required_flag


def remaining_reversible_minor(captured_minor: int, reversed_minor: int) -> int:
    validate_minor_amount(captured_minor, name="captured_minor")
    validate_minor_amount(reversed_minor, name="reversed_minor")
    if reversed_minor > captured_minor:
        raise ValueError("reversed_minor already exceeds captured_minor")
    return captured_minor - reversed_minor


def validate_reversal(captured_minor: int, reversed_minor: int, amount_minor: int) -> int:
    """Check one more (partial) reversal under the wallet lock (D4).

    Returns the new cumulative reversed amount; raises if it would exceed the
    captured commission. Multiple partial reversals are allowed.
    """
    validate_minor_amount(amount_minor, allow_zero=False, name="amount_minor")
    if amount_minor > remaining_reversible_minor(captured_minor, reversed_minor):
        raise ValueError("reversal exceeds captured commission")
    return reversed_minor + amount_minor


def hold_adjustment_minor(current_hold_minor: int, new_commission_minor: int) -> int:
    """Delta applied to the single existing hold when an amendment changes the total (D10).

    Positive: hold grows (balance check applies). Negative: part of the hold is released.
    """
    validate_minor_amount(current_hold_minor, name="current_hold_minor")
    validate_minor_amount(new_commission_minor, name="new_commission_minor")
    return new_commission_minor - current_hold_minor


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: Currency = Currency.UZS

    def __post_init__(self) -> None:
        _require_int(self.amount_minor, "amount_minor")
        if abs(self.amount_minor) > MAX_MINOR_AMOUNT:
            raise ValueError("amount_minor exceeds BIGINT range")
        if not isinstance(self.currency, Currency):
            raise TypeError("currency must be a Currency")

    def __add__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def _check_same_currency(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError("can only combine Money with Money")
        if other.currency != self.currency:
            raise ValueError("currency mismatch")
