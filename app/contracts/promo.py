"""Promotions & referral financial contract (ADR-0023, Q101-Q110).

Pure functions only: no DB, no network, no settings, no clock. Every parameter a rule needs is an explicit
argument, so the same inputs always give the same answer and the promotions module, the bookings orchestrator,
the simulator and the tests all run one formula.

Money model for a cash-paid booking (all integers, minor units, ADR-0003):

* ``F``  agreed fare (``bookings.total_minor``)
* ``C``  base commission, ``money.commission_minor(F, fee_bps)`` - the only commission formula
* ``P``  Passenger Bonus used on this booking (client consented to exactly this amount, Q104)
* ``H``  Driver Credit used on this booking (applied automatically under the published rule)
* ``O``  approved variable cost + reserves for the booking; ``M`` minimum contribution margin

    F_cash = F - P                   cash the client hands the driver
    C_net  = C - P - H               commission held/captured from the driver's real prepaid balance
    driver keeps F_cash - C_net = F - C + H

So the client's discount never reduces the driver's agreed takings, and Driver Credit adds to them. The
platform funds both out of its own commission. A promo booking must keep ``C_net >= 0`` and
``C_net - O >= M``. That per-booking floor is **not** a guarantee of overall profit: fixed costs, fraud,
refunds and wrong cost estimates sit outside it (ADR-0023 §3).

Promo booking invariants (Q110, Q111), checked by :meth:`PromoQuote.check_invariants`:
``F_cash >= 0``, ``C_net > 0``, ``O >= 0``, ``M > 0`` and ``C_net - O >= M``. They apply only to a booking that
actually uses a discount; a plain booking and an approved 0 % campaign booking (``C = 0``) keep working exactly
as before - they simply get no promo.

Rounding (Q111): ``C`` keeps ``commission_minor``'s half-up rounding. *Limits* derived here round in the
platform's favour - the share-of-commission cap rounds down, the bps part of ``O`` rounds up - so a limit never
exceeds its rule. Rounding never touches an amount a person already agreed to: a consented ``P`` is used exactly
or the accept is refused (``quote_at_accept``); it is never trimmed afterwards. Ledger, screens and the cash
receipt all read the same integers of one :class:`PromoQuote`, so they cannot disagree.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

from app.contracts.enums import (
    PILOT_CAMPAIGN_KINDS,
    ParcelPayer,
    PromoCampaignFamily,
    PromoCampaignKind,
    PromoFault,
    PromoInstrument,
    PromoRiskSignal,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.money import (
    BPS_DENOMINATOR,
    TWO_PERSON_APPROVAL_THRESHOLD_MINOR,
    commission_minor,
    validate_fee_bps,
    validate_minor_amount,
)
from app.contracts.timeutil import ensure_aware_utc

# Bumped whenever the quote formula or the fingerprinted fields change; a consent recorded under another
# version is stale by definition.
PROMO_QUOTE_CONTRACT_VERSION = 1

# Q106: server-side attribution window, from the first verified phone login of the account.
ATTRIBUTION_WINDOW = timedelta(hours=72)
# Q110: decided, not a per-campaign knob. Starts at the latest of completion / cash confirmation / capture.
QUALIFICATION_RISK_WINDOW = timedelta(hours=48)


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    return value


def _floor_div(numerator: int, denominator: int) -> int:
    _require_int(numerator, "numerator")
    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    return numerator // denominator


def _ceil_div(numerator: int, denominator: int) -> int:
    _require_int(numerator, "numerator")
    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    return -(-numerator // denominator)


def _optional_minor(value: int | None, name: str) -> int | None:
    return None if value is None else validate_minor_amount(value, name=name)


def _optional_bps(value: int | None) -> int | None:
    return None if value is None else validate_fee_bps(value)


# --- per-booking margin policy -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromoMarginPolicy:
    """Per-booking financial limits, taken from the approved campaign version (never from client input).

    ``None`` means *not decided*. It is never read as zero: a quote with an unset field refuses with
    ``PROMO_PARAMETERS_UNSET`` and applies no discount (Q105). An explicit ``0`` is a decision and is allowed
    where the field permits it.
    """

    max_discount_share_bps: int | None  # (P + H) <= floor(C * share / 10000); e.g. 5000 in synthetic tests only
    max_discount_per_booking_minor: int | None  # absolute cap on P + H
    passenger_bonus_max_per_booking_minor: int | None
    driver_credit_max_per_booking_minor: int | None
    variable_cost_fixed_minor: int | None  # part of O
    variable_cost_bps: int | None  # part of O, bps of F, rounded up
    min_margin_minor: int | None  # M

    def __post_init__(self) -> None:
        _optional_bps(self.max_discount_share_bps)
        _optional_bps(self.variable_cost_bps)
        for name in (
            "max_discount_per_booking_minor",
            "passenger_bonus_max_per_booking_minor",
            "driver_credit_max_per_booking_minor",
            "variable_cost_fixed_minor",
            "min_margin_minor",
        ):
            _optional_minor(getattr(self, name), name)

    def unset_fields(self) -> tuple[str, ...]:
        return tuple(name for name in self.__slots__ if getattr(self, name) is None)

    def variable_cost_minor(self, fare_minor: int) -> int:
        """O for one booking. Refuses when either part is unset."""
        if self.variable_cost_fixed_minor is None or self.variable_cost_bps is None:
            raise DomainError(ErrorCode.PROMO_PARAMETERS_UNSET, details={"fields": list(self.unset_fields())})
        variable = _ceil_div(validate_minor_amount(fare_minor, name="fare_minor") * self.variable_cost_bps, BPS_DENOMINATOR)
        return self.variable_cost_fixed_minor + variable


# --- client consent (Q104) ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PassengerBonusConsent:
    """What the client agreed to, bound to one proposal version.

    Recorded when the client submits a proposal or accepts a counter. When the driver later accepts without
    the client present, only exactly these terms may be applied (Q104).
    """

    proposal_version_id: str  # public id of the proposal version
    fare_minor: int  # F the consent was given for
    passenger_bonus_minor: int  # P the client agreed to spend
    cash_due_minor: int  # F_cash the client agreed to pay
    quote_fingerprint: str  # fingerprint of the quote shown when consenting
    expires_at: datetime

    def __post_init__(self) -> None:
        validate_minor_amount(self.fare_minor, allow_zero=False, name="fare_minor")
        validate_minor_amount(self.passenger_bonus_minor, allow_zero=False, name="passenger_bonus_minor")
        validate_minor_amount(self.cash_due_minor, name="cash_due_minor")
        if self.fare_minor - self.passenger_bonus_minor != self.cash_due_minor:
            raise ValueError("consent must satisfy cash_due = fare - passenger_bonus")
        ensure_aware_utc(self.expires_at, field="expires_at")


# --- the single quote ------------------------------------------------------------------------------------


class PromoLimitReason(StrEnum):
    """Why P or H is smaller than the holder's available amount. Internal; clients get a generic sentence (Q103)."""

    NO_CONSENT = "no_consent"
    CONSENT_AMOUNT = "consent_amount"
    ZERO_COMMISSION = "zero_commission"
    MARGIN_FLOOR = "margin_floor"
    SHARE_OF_COMMISSION = "share_of_commission"
    PER_BOOKING_CAP = "per_booking_cap"
    INSTRUMENT_CAP = "instrument_cap"
    AVAILABLE_BALANCE = "available_balance"
    PASSENGER_BONUS_PRIORITY = "passenger_bonus_priority"  # H got what was left after the consented P
    INELIGIBLE = "ineligible"  # service type / parcel payer / feature flag / client capability


@dataclass(frozen=True, slots=True)
class PromoQuote:
    fare_minor: int  # F
    fee_bps: int
    base_commission_minor: int  # C
    passenger_bonus_minor: int  # P
    driver_credit_minor: int  # H
    cash_due_minor: int  # F_cash
    net_commission_minor: int  # C_net - the only amount held/captured from the real balance
    variable_cost_minor: int | None  # O (None when no promo is applied and the policy is unset)
    margin_minor: int | None  # C_net - O
    min_margin_minor: int | None = None  # M the quote was built under (internal; never shown to anyone)
    passenger_limit_reasons: tuple[PromoLimitReason, ...] = ()
    driver_limit_reasons: tuple[PromoLimitReason, ...] = ()
    contract_version: int = PROMO_QUOTE_CONTRACT_VERSION

    @property
    def promo_applied(self) -> bool:
        return self.passenger_bonus_minor + self.driver_credit_minor > 0

    @property
    def driver_keeps_minor(self) -> int:
        return self.cash_due_minor - self.net_commission_minor

    @property
    def fingerprint(self) -> str:
        """Stable hash of the money terms a party is asked to agree to (not of the explanations)."""
        parts = (
            self.contract_version,
            self.fare_minor,
            self.fee_bps,
            self.base_commission_minor,
            self.passenger_bonus_minor,
            self.driver_credit_minor,
            self.cash_due_minor,
            self.net_commission_minor,
        )
        return hashlib.sha256("|".join(str(part) for part in parts).encode("ascii")).hexdigest()

    def check_invariants(self) -> None:
        """The identities of ADR-0023 §3; raises ``ValueError`` if any is broken."""
        if self.cash_due_minor != self.fare_minor - self.passenger_bonus_minor:
            raise ValueError("F_cash != F - P")
        if self.net_commission_minor != self.base_commission_minor - self.passenger_bonus_minor - self.driver_credit_minor:
            raise ValueError("C_net != C - P - H")
        if self.cash_due_minor < 0 or self.net_commission_minor < 0:
            raise ValueError("F_cash and C_net must be non-negative")
        if self.driver_keeps_minor != self.fare_minor - self.base_commission_minor + self.driver_credit_minor:
            raise ValueError("driver keeps != F - C + H")
        if self.promo_applied:
            if self.margin_minor is None or self.variable_cost_minor is None or self.min_margin_minor is None:
                raise ValueError("a promo quote must carry O, M and the margin")
            if self.variable_cost_minor < 0:
                raise ValueError("O must be non-negative")
            if self.min_margin_minor <= 0:
                raise ValueError("M must be positive on a promo booking")
            if self.net_commission_minor <= 0:
                raise ValueError("C_net must be positive on a promo booking")
            if self.margin_minor != self.net_commission_minor - self.variable_cost_minor:
                raise ValueError("margin != C_net - O")
            if self.margin_minor < self.min_margin_minor:
                raise ValueError("C_net - O < M")


def _no_promo_quote(
    fare_minor: int, fee_bps: int, base: int, p_reasons: Iterable[PromoLimitReason], h_reasons: Iterable[PromoLimitReason]
) -> PromoQuote:
    return PromoQuote(
        fare_minor=fare_minor,
        fee_bps=fee_bps,
        base_commission_minor=base,
        passenger_bonus_minor=0,
        driver_credit_minor=0,
        cash_due_minor=fare_minor,
        net_commission_minor=base,
        variable_cost_minor=None,
        margin_minor=None,
        passenger_limit_reasons=tuple(p_reasons),
        driver_limit_reasons=tuple(h_reasons),
    )


def quote_promo(
    *,
    fare_minor: int,
    fee_bps: int,
    policy: PromoMarginPolicy | None,
    passenger_bonus_requested_minor: int,
    passenger_bonus_available_minor: int,
    driver_credit_available_minor: int,
) -> PromoQuote:
    """The one server function that combines every discount on a booking (task §5).

    ``passenger_bonus_requested_minor`` is the most the client agreed to spend (0 = no consent). The passenger
    bonus is sized first and kept; Driver Credit fills whatever room is left (Q104). With ``policy=None`` or no
    available amounts the result is the plain booking: ``P = H = 0``, ``C_net = C``.

    Raises ``PROMO_PARAMETERS_UNSET`` when a discount would be applied under an incomplete policy - unset
    values are never read as zero.
    """
    validate_minor_amount(fare_minor, allow_zero=False, name="fare_minor")
    validate_fee_bps(fee_bps)
    requested = validate_minor_amount(passenger_bonus_requested_minor, name="passenger_bonus_requested_minor")
    p_available = validate_minor_amount(passenger_bonus_available_minor, name="passenger_bonus_available_minor")
    h_available = validate_minor_amount(driver_credit_available_minor, name="driver_credit_available_minor")
    base = commission_minor(fare_minor, fee_bps)

    wants_p = requested > 0 and p_available > 0
    wants_h = h_available > 0
    p_reasons: list[PromoLimitReason] = []
    h_reasons: list[PromoLimitReason] = []
    if requested == 0 and p_available > 0:
        p_reasons.append(PromoLimitReason.NO_CONSENT)
    if not (wants_p or wants_h):
        return _no_promo_quote(fare_minor, fee_bps, base, p_reasons, h_reasons)
    if base == 0:
        # A 0 bps booking has no commission to fund a discount from (task §4).
        reasons = [PromoLimitReason.ZERO_COMMISSION]
        return _no_promo_quote(fare_minor, fee_bps, base, reasons if wants_p else p_reasons, reasons if wants_h else [])
    if policy is None or policy.unset_fields():
        raise DomainError(
            ErrorCode.PROMO_PARAMETERS_UNSET,
            details={"fields": list(policy.unset_fields()) if policy is not None else ["policy"]},
        )
    if policy.min_margin_minor <= 0:
        # Q111: M > 0 is required before any discount; 0 is refused like an unset value, never "no floor".
        raise DomainError(ErrorCode.PROMO_PARAMETERS_UNSET, details={"invalid": ["min_margin_minor"]})

    variable_cost = policy.variable_cost_minor(fare_minor)
    margin_room = base - variable_cost - policy.min_margin_minor  # the most P + H may take
    share_cap = _floor_div(base * policy.max_discount_share_bps, BPS_DENOMINATOR)
    total_cap = min(share_cap, policy.max_discount_per_booking_minor, base, max(margin_room, 0))

    def _binding(candidates: Mapping[PromoLimitReason, int], chosen: int) -> list[PromoLimitReason]:
        return [reason for reason, limit in candidates.items() if limit == chosen]

    total_limits = {
        PromoLimitReason.SHARE_OF_COMMISSION: share_cap,
        PromoLimitReason.PER_BOOKING_CAP: policy.max_discount_per_booking_minor,
        PromoLimitReason.MARGIN_FLOOR: max(margin_room, 0),
    }

    p = 0
    if wants_p:
        p_limits = {
            PromoLimitReason.CONSENT_AMOUNT: requested,
            PromoLimitReason.AVAILABLE_BALANCE: p_available,
            PromoLimitReason.INSTRUMENT_CAP: policy.passenger_bonus_max_per_booking_minor,
            **total_limits,
        }
        p = min(requested, p_available, policy.passenger_bonus_max_per_booking_minor, total_cap)
        if p < min(requested, p_available):
            p_reasons.extend(r for r in _binding(p_limits, p) if r is not PromoLimitReason.AVAILABLE_BALANCE)
    h = 0
    if wants_h:
        room = total_cap - p
        h = min(h_available, policy.driver_credit_max_per_booking_minor, room)
        if h < h_available:
            h_limits = {
                PromoLimitReason.INSTRUMENT_CAP: policy.driver_credit_max_per_booking_minor,
                **total_limits,
            }
            h_reasons.extend(_binding(h_limits, h))
            if p > 0 and h == room and room < total_cap:
                h_reasons.append(PromoLimitReason.PASSENGER_BONUS_PRIORITY)

    net = base - p - h
    quote = PromoQuote(
        fare_minor=fare_minor,
        fee_bps=fee_bps,
        base_commission_minor=base,
        passenger_bonus_minor=p,
        driver_credit_minor=h,
        cash_due_minor=fare_minor - p,
        net_commission_minor=net,
        variable_cost_minor=variable_cost,
        margin_minor=net - variable_cost,
        min_margin_minor=policy.min_margin_minor,
        passenger_limit_reasons=tuple(dict.fromkeys(p_reasons)),
        driver_limit_reasons=tuple(dict.fromkeys(h_reasons)),
    )
    quote.check_invariants()
    return quote


# Q119: a stale quote refuses only *this* accept attempt. The user, the listing and the proposal are untouched; the
# client re-quotes and asks for consent again. Nothing about the person or the offer is rejected.
STALE_SCOPE: dict[str, str] = {"scope": "accept_attempt", "action": "requote"}


def record_consent(quote: PromoQuote, *, proposal_version_id: str, expires_at: datetime) -> PassengerBonusConsent:
    """Consent object for the exact quote the client saw. Only a quote that spends passenger bonus needs one."""
    if quote.passenger_bonus_minor <= 0:
        raise ValueError("consent is recorded only for a quote that uses passenger bonus")
    return PassengerBonusConsent(
        proposal_version_id=proposal_version_id,
        fare_minor=quote.fare_minor,
        passenger_bonus_minor=quote.passenger_bonus_minor,
        cash_due_minor=quote.cash_due_minor,
        quote_fingerprint=quote.fingerprint,
        expires_at=expires_at,
    )


def quote_at_accept(
    *,
    consent: PassengerBonusConsent | None,
    proposal_version_id: str,
    now: datetime,
    fare_minor: int,
    fee_bps: int,
    policy: PromoMarginPolicy | None,
    passenger_bonus_available_minor: int,
    driver_credit_available_minor: int,
) -> PromoQuote:
    """Re-quote inside the accept transaction and hold it to the client's consent (Q104, QA #13).

    * No consent: P = 0; Driver Credit may still apply (it never changes what the client pays).
    * Consent present: it must belong to this proposal version and this fare, be unexpired, and the fresh quote
      must spend **exactly** the consented P. Anything else - bonus spent elsewhere, expired, cap changed - is
      ``PROMO_QUOTE_STALE``: the booking is not created with a larger cash amount behind the client's back.
    """
    now = ensure_aware_utc(now, field="now")
    if consent is None:
        return quote_promo(
            fare_minor=fare_minor,
            fee_bps=fee_bps,
            policy=policy,
            passenger_bonus_requested_minor=0,
            passenger_bonus_available_minor=passenger_bonus_available_minor,
            driver_credit_available_minor=driver_credit_available_minor,
        )
    stale: list[str] = []
    if consent.proposal_version_id != proposal_version_id:
        stale.append("proposal_version")
    if consent.fare_minor != fare_minor:
        stale.append("fare")
    if now >= ensure_aware_utc(consent.expires_at, field="expires_at"):
        stale.append("expired")
    if stale:
        raise DomainError(ErrorCode.PROMO_QUOTE_STALE, details={"reasons": stale, **STALE_SCOPE})
    quote = quote_promo(
        fare_minor=fare_minor,
        fee_bps=fee_bps,
        policy=policy,
        passenger_bonus_requested_minor=consent.passenger_bonus_minor,
        passenger_bonus_available_minor=passenger_bonus_available_minor,
        driver_credit_available_minor=driver_credit_available_minor,
    )
    if quote.passenger_bonus_minor != consent.passenger_bonus_minor or quote.cash_due_minor != consent.cash_due_minor:
        raise DomainError(
            ErrorCode.PROMO_QUOTE_STALE,
            details={"reasons": ["passenger_bonus_changed"], "consented_cash_due_minor": consent.cash_due_minor,
                     **STALE_SCOPE},
        )
    return quote


def strictest_margin_policy(policies: Iterable[PromoMarginPolicy]) -> PromoMarginPolicy | None:
    """Lots of **one** campaign granted under several of its versions: every version's limits hold at once, so the
    policy takes the tightest cap and the highest cost and floor (one campaign = one cost basis, Q123).

    Two *different* campaigns on one booking go through :func:`combined_margin_policy` instead.
    An unset field in any policy stays unset (``None``) - it is never replaced by another version's value.
    No policies -> ``None`` (plain booking).
    """
    items = list(policies)
    if not items:
        return None

    def tightest(name: str, pick: Callable[[Iterable[int]], int]) -> int | None:
        values = [getattr(policy, name) for policy in items]
        return None if any(value is None for value in values) else pick(values)

    return PromoMarginPolicy(
        max_discount_share_bps=tightest("max_discount_share_bps", min),
        max_discount_per_booking_minor=tightest("max_discount_per_booking_minor", min),
        passenger_bonus_max_per_booking_minor=tightest("passenger_bonus_max_per_booking_minor", min),
        driver_credit_max_per_booking_minor=tightest("driver_credit_max_per_booking_minor", min),
        variable_cost_fixed_minor=tightest("variable_cost_fixed_minor", max),
        variable_cost_bps=tightest("variable_cost_bps", max),
        min_margin_minor=tightest("min_margin_minor", max),
    )


class CostBasis(StrEnum):
    """Q123: how the O of two combined campaigns relate. Chosen explicitly when the combination is approved."""

    SHARED = "shared"  # both describe the same cost of the same booking: the larger O (and M) is taken
    ADDITIVE = "additive"  # each campaign carries its own extra cost: the O parts are summed, never lost to max()


def combined_margin_policy(
    passenger: PromoMarginPolicy | None,
    driver: PromoMarginPolicy | None,
    cost_basis: CostBasis | str | None,
) -> PromoMarginPolicy | None:
    """Q123: the policy of a booking whose P comes from one campaign and whose H comes from another.

    * one side absent -> the other side's own policy (a single campaign);
    * a combination needs an approved ``cost_basis``; without one this raises ``ValueError`` - an unapproved pair is
      never combined automatically (callers simply do not apply H);
    * the total discount caps (share of C, per booking) take the strictest value; the passenger-bonus cap comes from
      the P campaign and the driver-credit cap from the H campaign;
    * ``shared``: O parts and M take the larger value; ``additive``: the O parts are summed (both costs are real and
      counted once each), M takes the larger value;
    * an unset field on either side stays unset (``None``) and the quote refuses (``PROMO_PARAMETERS_UNSET``).
    """
    if passenger is None or driver is None:
        return passenger or driver
    if cost_basis is None:
        raise ValueError("two campaigns are combined only under an approved cost basis (Q123)")
    basis = CostBasis(cost_basis)

    def both(name: str, pick: Callable[[int, int], int]) -> int | None:
        a, b = getattr(passenger, name), getattr(driver, name)
        return None if a is None or b is None else pick(a, b)

    cost = max if basis is CostBasis.SHARED else (lambda a, b: a + b)
    variable_bps = both("variable_cost_bps", cost)
    if variable_bps is not None and variable_bps > BPS_DENOMINATOR:
        raise ValueError("combined variable cost exceeds 100 % of the fare")
    return PromoMarginPolicy(
        max_discount_share_bps=both("max_discount_share_bps", min),
        max_discount_per_booking_minor=both("max_discount_per_booking_minor", min),
        passenger_bonus_max_per_booking_minor=passenger.passenger_bonus_max_per_booking_minor,
        driver_credit_max_per_booking_minor=driver.driver_credit_max_per_booking_minor,
        variable_cost_fixed_minor=both("variable_cost_fixed_minor", cost),
        variable_cost_bps=variable_bps,
        min_margin_minor=both("min_margin_minor", max),
    )


def campaign_pair(a: int, b: int) -> tuple[int, int]:
    """The stored (low, high) key of an unordered campaign pair (0089)."""
    if a == b:
        raise ValueError("a campaign is not combined with itself")
    return (a, b) if a < b else (b, a)


# --- choosing the one campaign per instrument (Q123, shared by the booking flow and the simulator) ----------------


@dataclass(frozen=True, slots=True)
class FundingSource:
    """The usable value of one campaign for one instrument, as the chooser sees it (no lots, no DB)."""

    campaign_id: int
    available_minor: int
    order_key: tuple  # soonest expiry first, then campaign id - the deterministic tie-break


class DriverCreditOutcome(StrEnum):
    """Q123 (clarified 24.09.2026): why H is what it is on a quote. Internal - never shown to the client."""

    NONE = "none"  # no usable driver credit
    APPLIED = "applied"  # all the usable H of the chosen campaign fits
    PARTIAL = "partial"  # H takes only the room left after P under the combined limits (the "what is left" rule)
    NOT_APPROVED = "not_approved"  # the two campaigns have no approved pairing: they never meet
    WOULD_REDUCE_P = "would_reduce_p"  # combining would lower the consented P: P kept exactly, H not applied


def choose_passenger_source(
    sources: Iterable[FundingSource],
    *,
    fare_minor: int,
    fee_bps: int,
    policy_of: Callable[[FundingSource], PromoMarginPolicy | None],
    requested_minor: int | None = None,
) -> tuple[FundingSource, PromoQuote] | None:
    """Q123: the one campaign that funds P - the largest P on this fare (ties: ``order_key``). ``requested_minor`` is
    what the client agreed to (``None``: all it holds). A campaign whose parameters are unset cannot fund it."""
    best: tuple[FundingSource, PromoQuote] | None = None
    for src in sorted(sources, key=lambda item: item.order_key):
        try:
            quote = quote_promo(fare_minor=fare_minor, fee_bps=fee_bps, policy=policy_of(src),
                                passenger_bonus_requested_minor=src.available_minor if requested_minor is None
                                else requested_minor,
                                passenger_bonus_available_minor=src.available_minor, driver_credit_available_minor=0)
        except DomainError as exc:
            if exc.code is ErrorCode.PROMO_PARAMETERS_UNSET:
                continue
            raise
        if quote.passenger_bonus_minor > 0 and (best is None or quote.passenger_bonus_minor > best[1].passenger_bonus_minor):
            best = (src, quote)
    return best


def choose_driver_source(
    *,
    p_source: FundingSource | None,
    h_sources: Iterable[FundingSource],
    pairing: Callable[[FundingSource | None, FundingSource], tuple[PromoMarginPolicy | None, str | None] | None],
    consent: PassengerBonusConsent | None,
    subject: str,
    now: datetime,
    fare_minor: int,
    fee_bps: int,
) -> tuple[FundingSource | None, str | None, PromoQuote | None, DriverCreditOutcome]:
    """Q123: add Driver Credit from the one campaign giving the most H **without changing the consented P**.

    ``pairing(p, h)`` returns ``(policy, cost_basis)`` or ``None`` when the two campaigns may not meet. Per candidate:
    not approved -> skipped; the combined limits would lower P -> skipped (P is never lowered to make room, and a P
    that no longer fits on its own is the caller's requote); otherwise H takes what is left after P - possibly only a
    part of it (``PARTIAL``). Returns ``(source, cost_basis, quote, outcome)``; ``quote`` is ``None`` when no H applies.
    """
    best: tuple[FundingSource, str | None, PromoQuote] | None = None
    saw_reduce_p = saw_not_approved = False
    candidates = sorted(h_sources, key=lambda item: item.order_key)
    for h_src in candidates:
        paired = pairing(p_source, h_src)
        if paired is None:
            saw_not_approved = True
            continue
        policy, basis = paired
        try:
            quote = quote_at_accept(consent=consent, proposal_version_id=subject, now=now, fare_minor=fare_minor,
                                    fee_bps=fee_bps, policy=policy,
                                    passenger_bonus_available_minor=0 if p_source is None else p_source.available_minor,
                                    driver_credit_available_minor=h_src.available_minor)
        except DomainError as exc:
            if exc.code is ErrorCode.PROMO_QUOTE_STALE and (exc.details or {}).get("reasons") == ["passenger_bonus_changed"]:
                saw_reduce_p = True
                continue
            if exc.code in (ErrorCode.PROMO_QUOTE_STALE, ErrorCode.PROMO_PARAMETERS_UNSET):
                continue  # the consent itself is stale or unset: the caller's P-only quote raises it
            raise
        if quote.driver_credit_minor > 0 and (best is None or quote.driver_credit_minor > best[2].driver_credit_minor):
            best = (h_src, basis, quote)
    if best is not None:
        src, basis, quote = best
        outcome = DriverCreditOutcome.PARTIAL if quote.driver_credit_minor < src.available_minor else DriverCreditOutcome.APPLIED
        return src, basis, quote, outcome
    if saw_reduce_p:
        return None, None, None, DriverCreditOutcome.WOULD_REDUCE_P
    if saw_not_approved:
        return None, None, None, DriverCreditOutcome.NOT_APPROVED
    return None, None, None, DriverCreditOutcome.NONE


# --- the booking's financial snapshot (stage 4, ADR-0023 §18) ------------------------------------------

# ``bookings.terms_snapshot["promo"]`` is written once at accept on every booking made after stage 4. It says
# whether promo terms rows exist for the booking; the terms themselves live in ``promo_booking_terms``.
PROMO_SNAPSHOT_KEY = "promo"


class PromoSnapshotState(StrEnum):
    LEGACY = "legacy"  # booking made before stage 4: P = H = 0, C_net = C (no terms rows)
    PLAIN = "plain"  # stage-4 booking without a discount: P = H = 0, C_net = C
    APPLIED = "applied"  # stage-4 booking with promo terms rows; a missing or broken row is an error


def booking_promo_marker(*, applied: bool) -> dict[str, object]:
    return {"contract_version": PROMO_QUOTE_CONTRACT_VERSION, "applied": bool(applied)}


def promo_snapshot_state(terms_snapshot: Mapping[str, object] | None) -> PromoSnapshotState:
    """Read the marker. Only its *absence* means legacy; a present but malformed marker raises ``ValueError``
    so a broken new snapshot is never mistaken for an old booking (task stage 4)."""
    if not terms_snapshot or PROMO_SNAPSHOT_KEY not in terms_snapshot:
        return PromoSnapshotState.LEGACY
    marker = terms_snapshot[PROMO_SNAPSHOT_KEY]
    if (
        not isinstance(marker, Mapping)
        or set(marker) != {"contract_version", "applied"}
        or not isinstance(marker["applied"], bool)
        or type(marker["contract_version"]) is not int
        or marker["contract_version"] < 1
    ):
        raise ValueError("malformed promo snapshot marker")
    return PromoSnapshotState.APPLIED if marker["applied"] else PromoSnapshotState.PLAIN


def plain_quote(*, fare_minor: int, fee_bps: int) -> PromoQuote:
    """The quote of a booking without a discount (legacy or plain): P = H = 0, F_cash = F, C_net = C."""
    validate_minor_amount(fare_minor, allow_zero=False, name="fare_minor")
    validate_fee_bps(fee_bps)
    return _no_promo_quote(fare_minor, fee_bps, commission_minor(fare_minor, fee_bps), (), ())


def quote_from_terms(
    *,
    fare_minor: int,
    fee_bps: int,
    base_commission_minor: int,
    passenger_bonus_minor: int,
    driver_credit_minor: int,
    cash_due_minor: int,
    net_commission_minor: int,
    variable_cost_minor: int | None,
    min_margin_minor: int | None,
    contract_version: int,
) -> PromoQuote:
    """Rebuild a stored quote and re-check every identity; a stored row that breaks one raises ``ValueError``."""
    if contract_version != PROMO_QUOTE_CONTRACT_VERSION:
        raise ValueError("promo terms of an unknown contract version")
    if commission_minor(fare_minor, fee_bps) != base_commission_minor:
        raise ValueError("stored C does not match F and bps")
    quote = PromoQuote(
        fare_minor=fare_minor,
        fee_bps=fee_bps,
        base_commission_minor=base_commission_minor,
        passenger_bonus_minor=passenger_bonus_minor,
        driver_credit_minor=driver_credit_minor,
        cash_due_minor=cash_due_minor,
        net_commission_minor=net_commission_minor,
        variable_cost_minor=variable_cost_minor,
        margin_minor=None if variable_cost_minor is None else net_commission_minor - variable_cost_minor,
        min_margin_minor=min_margin_minor,
        contract_version=contract_version,
    )
    quote.check_invariants()
    return quote


# --- what each side may see (Q103) ----------------------------------------------------------------------

# Keys a client-facing payload may carry for a promo booking. Commission, C, H, O, M, bps and the formula
# inputs are never among them (Q16, Q103).
CLIENT_PROMO_VIEW_KEYS: frozenset[str] = frozenset({"fare_minor", "passenger_discount_minor", "cash_due_minor", "currency"})
DRIVER_PROMO_VIEW_KEYS: frozenset[str] = frozenset(
    {
        "fare_minor",
        "passenger_discount_minor",
        "cash_to_collect_minor",
        "base_commission_minor",
        "passenger_discount_covered_minor",
        "driver_credit_minor",
        "commission_charged_minor",
        "driver_keeps_minor",
        "currency",
    }
)


def client_view(quote: PromoQuote, currency: str = "UZS") -> dict[str, int | str]:
    return {
        "fare_minor": quote.fare_minor,
        "passenger_discount_minor": quote.passenger_bonus_minor,
        "cash_due_minor": quote.cash_due_minor,
        "currency": currency,
    }


def driver_view(quote: PromoQuote, currency: str = "UZS") -> dict[str, int | str]:
    """Driver sees how much cash to collect, what is charged and how much credit was used (Q103)."""
    return {
        "fare_minor": quote.fare_minor,
        "passenger_discount_minor": quote.passenger_bonus_minor,
        "cash_to_collect_minor": quote.cash_due_minor,
        "base_commission_minor": quote.base_commission_minor,
        "passenger_discount_covered_minor": quote.passenger_bonus_minor,
        "driver_credit_minor": quote.driver_credit_minor,
        "commission_charged_minor": quote.net_commission_minor,
        "driver_keeps_minor": quote.driver_keeps_minor,
        "currency": currency,
    }


# --- eligibility of an instrument for a booking (Q104, Q109) ---------------------------------------------


def lot_usable_for(lot_service_type: ServiceType | str, booking_service_type: ServiceType | str) -> bool:
    """Pilot: a lot is spent only on the service type of the campaign that granted it (Q109)."""
    return ServiceType(lot_service_type) is ServiceType(booking_service_type)


def passenger_bonus_allowed(
    *,
    service_type: ServiceType | str,
    bonus_owner_user_id: int,
    client_user_id: int,
    parcel_payer: ParcelPayer | str | None,
) -> bool:
    """Only the booking's own client may spend a bonus on it; a parcel only when the sender pays (Q104).

    Pilot parcel rule: owner, sender and payer are one person. A receiver-pays parcel never uses the sender's
    bonus, automatically or otherwise.
    """
    if bonus_owner_user_id != client_user_id:
        return False
    if ServiceType(service_type) is ServiceType.PARCEL:
        return parcel_payer is not None and ParcelPayer(parcel_payer) is ParcelPayer.SENDER
    return True


# --- amendment (Q104, QA #4 of the consent set) -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reconfirmation:
    client: bool
    driver: bool

    @property
    def any(self) -> bool:
        return self.client or self.driver


def amendment_reconfirmation(old: PromoQuote, new: PromoQuote) -> Reconfirmation:
    """Which parties must re-accept changed money terms. A cash increase for the client is never silent.

    Client: whenever F, P or F_cash change. Driver: whenever the cash to collect or the commission charged
    changes. A lower fare that lowers the bonus cap and so *raises* F_cash is the case this exists for.
    """
    client = (
        old.fare_minor != new.fare_minor
        or old.passenger_bonus_minor != new.passenger_bonus_minor
        or old.cash_due_minor != new.cash_due_minor
    )
    driver = old.cash_due_minor != new.cash_due_minor or old.net_commission_minor != new.net_commission_minor
    return Reconfirmation(client=client, driver=driver)


# --- legacy / incompatible clients (Q110) ----------------------------------------------------------------

# Declared by the client in a request header. It states what the client can *render*; it grants no authority
# and the server never trusts it for permissions or amounts (Q110).
CLIENT_FEATURES_HEADER = "X-Elchi-Client-Features"
PROMO_CASH_FEATURE = "promo_cash_v1"
_FEATURE_TOKEN_MAX = 32
_FEATURES_MAX = 16

# Commands that show or record the cash amount of a booking; an incompatible client may not run them on a
# promo booking because it would show or record F instead of F_cash.
PROMO_CASH_SENSITIVE_COMMANDS: frozenset[str] = frozenset(
    {"report_cash_receipt", "acknowledge_cash_receipt", "contest_cash_receipt", "create_amendment", "accept_amendment"}
)


def parse_client_features(header_value: str | None) -> frozenset[str]:
    """Comma-separated lowercase tokens; malformed input yields no features (never an error, never a grant)."""
    if not header_value:
        return frozenset()
    tokens = [token.strip().lower() for token in header_value.split(",")]
    valid = [
        token
        for token in tokens
        if token and len(token) <= _FEATURE_TOKEN_MAX and all(ch.isalnum() or ch == "_" for ch in token)
    ]
    return frozenset(valid[:_FEATURES_MAX])


def promo_new_deal_allowed(actor_features: frozenset[str], counterparty_features: frozenset[str] | None) -> bool:
    """A new promo booking needs both sides' clients to render F_cash. Unknown counterparty = not allowed.

    When refused, the booking is still created - as a plain booking without discount - only if the client
    did not consent to one; a consented discount that cannot be applied is ``PROMO_QUOTE_STALE`` (Q104).
    """
    if PROMO_CASH_FEATURE not in actor_features:
        return False
    return counterparty_features is not None and PROMO_CASH_FEATURE in counterparty_features


def promo_booking_command_allowed(features: frozenset[str], command: str, *, booking_has_promo: bool) -> bool:
    """An existing promo booking keeps its discount; an old client just may not run cash commands on it.

    The server answers ``CLIENT_UPGRADE_REQUIRED``; the discount is never removed to suit the old client.
    """
    if not booking_has_promo or command not in PROMO_CASH_SENSITIVE_COMMANDS:
        return True
    return PROMO_CASH_FEATURE in features


def cash_receipt_matches(quote_cash_due_minor: int, reported_amount_minor: int) -> bool:
    """Cash receipts are checked against F_cash, not F (Q110)."""
    return validate_minor_amount(reported_amount_minor, name="reported_amount_minor") == validate_minor_amount(
        quote_cash_due_minor, name="cash_due_minor"
    )


# --- lots: partial use, reserve, consume, expiry, reversal ------------------------------------------------


@dataclass(frozen=True, slots=True)
class LotBalance:
    """Buckets of one bonus lot. ``amount = available + reserved + consumed + expired + reversed`` always."""

    amount_minor: int
    reserved_minor: int = 0
    consumed_minor: int = 0
    expired_minor: int = 0
    reversed_minor: int = 0

    def __post_init__(self) -> None:
        for name in ("amount_minor", "reserved_minor", "consumed_minor", "expired_minor", "reversed_minor"):
            validate_minor_amount(getattr(self, name), name=name)
        if self.amount_minor == 0:
            raise ValueError("a lot must have a positive amount")
        if self.reserved_minor + self.consumed_minor + self.expired_minor + self.reversed_minor > self.amount_minor:
            raise ValueError("lot buckets exceed the lot amount")

    @property
    def available_minor(self) -> int:
        return self.amount_minor - self.reserved_minor - self.consumed_minor - self.expired_minor - self.reversed_minor

    def reserve(self, amount: int) -> LotBalance:
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.available_minor:
            raise ValueError("reservation exceeds the available amount")
        return replace(self, reserved_minor=self.reserved_minor + amount)

    def release(self, amount: int) -> LotBalance:
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.reserved_minor:
            raise ValueError("release exceeds the reserved amount")
        return replace(self, reserved_minor=self.reserved_minor - amount)

    def consume(self, amount: int) -> LotBalance:
        """Reserved -> consumed, once, when the booking's commission is captured."""
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.reserved_minor:
            raise ValueError("consumption exceeds the reserved amount")
        return replace(self, reserved_minor=self.reserved_minor - amount, consumed_minor=self.consumed_minor + amount)

    def expire(self) -> LotBalance:
        """Only the free part expires; a reservation in flight is settled by its booking first."""
        return replace(self, expired_minor=self.expired_minor + self.available_minor)

    def reinstate_expired(self, amount: int) -> LotBalance:
        """Fair restoration (ADR-0023 §7): expired value handed back as available."""
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.expired_minor:
            raise ValueError("reinstatement exceeds the expired amount")
        return replace(self, expired_minor=self.expired_minor - amount)

    def reverse_available(self) -> tuple[LotBalance, int]:
        """Reverse what is still free; returns the reversed amount (it goes back to the budget)."""
        amount = self.available_minor
        return replace(self, reversed_minor=self.reversed_minor + amount), amount


@dataclass(frozen=True, slots=True)
class ReversalPlan:
    reverse_now_minor: int  # free value, removed from the lot and released to the budget
    settle_with_booking_minor: int  # reserved on a live booking; reversed if that reservation is released
    risk_cost_minor: int  # already consumed: stays consumed, reported as risk cost, never a debt (task §13)


def reversal_plan(lot: LotBalance) -> ReversalPlan:
    """Reverse a reward (qualifying service cancelled, fraud confirmed). Never creates real-money debt."""
    return ReversalPlan(
        reverse_now_minor=lot.available_minor,
        settle_with_booking_minor=lot.reserved_minor,
        risk_cost_minor=lot.consumed_minor,
    )


# Which party holds each instrument (Q129: each holder is judged on its own).
INSTRUMENT_HOLDER_SIDE: dict[PromoInstrument, PromoFault] = {
    PromoInstrument.PASSENGER_BONUS: PromoFault.CLIENT,
    PromoInstrument.DRIVER_CREDIT: PromoFault.DRIVER,
}


def holder_at_fault(fault: PromoFault | str, instrument: PromoInstrument | str) -> bool:
    """Q129: only a *decided* cause that is the holder's own takes the extension away. ``platform``, ``none`` and the
    other party's fault never do; ``undetermined`` never does either - a right is not lost by uncertainty."""
    return PromoFault(fault) is INSTRUMENT_HOLDER_SIDE[PromoInstrument(instrument)]


def restored_expiry(
    *,
    lot_expires_at: datetime,
    released_at: datetime,
    fault: PromoFault | str,
    grace: timedelta,
    instrument: PromoInstrument | str = PromoInstrument.PASSENGER_BONUS,
) -> datetime | None:
    """New expiry for value released from a cancelled booking (ADR-0023 §7, Q128, Q129).

    The holder of the instrument (client for a passenger bonus, driver for a driver credit) is judged on its own:
    if the release was not the holder's own decided fault and less than ``grace`` remains (or the lot already expired
    while reserved), the value lives until ``released_at + grace``. The holder's own fault: no extension, the original
    expiry stands (``None`` = keep it).
    """
    expires = ensure_aware_utc(lot_expires_at, field="lot_expires_at")
    released = ensure_aware_utc(released_at, field="released_at")
    if grace <= timedelta(0):
        raise ValueError("grace must be positive")
    if holder_at_fault(fault, instrument):
        return None
    floor = released + grace
    return floor if expires < floor else None


# --- campaign budget: the first protection (task §8) ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BudgetPosition:
    """Campaign budget buckets. One reward's value is in exactly one bucket at a time.

    * ``promised``: maximum rewards promised to enrolled participants not yet qualified
    * ``granted``: granted, not yet spent (includes amounts reserved on live bookings)
    * ``consumed``: spent discounts (cost, counted once)
    * ``released``: cumulative value returned from promised/granted (expired, rejected, reversed) - informative

    ``available_for_new = allocated - promised - granted - consumed``. A reduction of the allocation below the
    committed total is a ``shortfall``: new enrollments stop, existing commitments stand (task §8).
    """

    allocated_minor: int
    promised_minor: int = 0
    granted_minor: int = 0
    consumed_minor: int = 0
    released_minor: int = 0

    def __post_init__(self) -> None:
        for name in ("allocated_minor", "promised_minor", "granted_minor", "consumed_minor", "released_minor"):
            validate_minor_amount(getattr(self, name), name=name)

    @property
    def committed_minor(self) -> int:
        return self.promised_minor + self.granted_minor + self.consumed_minor

    @property
    def available_for_new_minor(self) -> int:
        return max(self.allocated_minor - self.committed_minor, 0)

    @property
    def shortfall_minor(self) -> int:
        return max(self.committed_minor - self.allocated_minor, 0)

    def allocate(self, amount: int) -> BudgetPosition:
        validate_minor_amount(amount, allow_zero=False, name="amount")
        return replace(self, allocated_minor=self.allocated_minor + amount)

    def reducible_minor(self, pending_reinstatements_minor: int = 0) -> int:
        """G14: what a plain reduction may take - ``max(0, B - S - L)``. B = allocated, S = consumed, L = promised +
        granted (the part reserved on bookings is inside granted: counted once) + approved reinstatements still
        waiting for room (they are obligations too, never hidden)."""
        pending = validate_minor_amount(pending_reinstatements_minor, name="pending_reinstatements_minor")
        return max(0, self.allocated_minor - self.consumed_minor - self.promised_minor - self.granted_minor - pending)

    def reduce_allocation(self, amount: int, *, pending_reinstatements_minor: int = 0) -> BudgetPosition:
        """A plain budget reduction: never below spent + outstanding obligations (``B >= S + L``, G14)."""
        validate_minor_amount(amount, allow_zero=False, name="amount")
        reducible = self.reducible_minor(pending_reinstatements_minor)
        if amount > reducible:
            raise DomainError(ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT,
                              details={"requested_minor": amount, "reducible_minor": reducible})
        return replace(self, allocated_minor=self.allocated_minor - amount)

    def record_funding_loss(self, amount: int) -> BudgetPosition:
        """External funding that is really gone (G14): may go below the obligations - a shortfall that stops new
        promises and is escalated - but it never cancels a promise, a bonus or a spend."""
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.allocated_minor:
            raise ValueError("cannot reduce the allocation below zero")
        return replace(self, allocated_minor=self.allocated_minor - amount)

    def promise(self, max_commitment_minor: int) -> BudgetPosition:
        """Enrollment: reserve the maximum of *both* sides' rewards before anything is promised."""
        validate_minor_amount(max_commitment_minor, allow_zero=False, name="max_commitment_minor")
        if max_commitment_minor > self.available_for_new_minor:
            raise DomainError(
                ErrorCode.PROMO_BUDGET_EXHAUSTED,
                details={"required_minor": max_commitment_minor, "available_minor": self.available_for_new_minor},
            )
        return replace(self, promised_minor=self.promised_minor + max_commitment_minor)

    def grant(self, from_promised_minor: int, granted_minor: int) -> BudgetPosition:
        """Qualification: promise -> granted reserve. Any unused part of the promise is released."""
        validate_minor_amount(from_promised_minor, allow_zero=False, name="from_promised_minor")
        validate_minor_amount(granted_minor, name="granted_minor")
        if from_promised_minor > self.promised_minor:
            raise ValueError("grant exceeds the promised reserve")
        if granted_minor > from_promised_minor:
            raise ValueError("a grant can never exceed its promise")
        return replace(
            self,
            promised_minor=self.promised_minor - from_promised_minor,
            granted_minor=self.granted_minor + granted_minor,
            released_minor=self.released_minor + (from_promised_minor - granted_minor),
        )

    def release_promise(self, amount: int) -> BudgetPosition:
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.promised_minor:
            raise ValueError("release exceeds the promised reserve")
        return replace(self, promised_minor=self.promised_minor - amount, released_minor=self.released_minor + amount)

    def consume(self, amount: int) -> BudgetPosition:
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.granted_minor:
            raise ValueError("consumption exceeds the granted reserve")
        return replace(self, granted_minor=self.granted_minor - amount, consumed_minor=self.consumed_minor + amount)

    def release_granted(self, amount: int) -> BudgetPosition:
        """Unspent granted value that expired or was reversed. Consumed value never comes back (task §13)."""
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.granted_minor:
            raise ValueError("release exceeds the granted reserve")
        return replace(self, granted_minor=self.granted_minor - amount, released_minor=self.released_minor + amount)

    def reinstate(self, amount: int) -> BudgetPosition:
        """An approved reinstatement of expired value (Q122): back into ``granted`` as the ledger trigger does
        (``reinstate`` adds to granted; ``released`` stays cumulative). Never partial: refused without room."""
        validate_minor_amount(amount, allow_zero=False, name="amount")
        if amount > self.available_for_new_minor:
            raise DomainError(ErrorCode.PROMO_BUDGET_EXHAUSTED,
                              details={"required_minor": amount, "available_minor": self.available_for_new_minor})
        return replace(self, granted_minor=self.granted_minor + amount)

    def accepts_new_enrollments(self, max_commitment_minor: int) -> bool:
        return self.shortfall_minor == 0 and max_commitment_minor <= self.available_for_new_minor


def enrollment_commitment_minor(reward_amounts_minor: Iterable[int]) -> int:
    """Maximum commitment of one enrollment: every reward either side could earn (all milestones)."""
    total = 0
    for amount in reward_amounts_minor:
        total += validate_minor_amount(amount, name="reward_minor")
    if total == 0:
        raise ValueError("an enrollment must promise something")
    return validate_minor_amount(total, name="commitment_minor")


# --- budget changes: the existing two-person rule (Q17, Q114) -------------------------------------------


def budget_change_requires_second_approver(amount_minor: int) -> bool:
    """Same rule as wallet top-ups/adjustments: strictly above ``TWO_PERSON_APPROVAL_THRESHOLD_MINOR``.

    Minor units (UZS tiyin); exactly the threshold is a single-person change. The requester can never be the
    second approver (enforced in the service and by a DB CHECK).
    """
    return validate_minor_amount(amount_minor, allow_zero=False, name="amount_minor") > TWO_PERSON_APPROVAL_THRESHOLD_MINOR


# --- campaign activation (Q105) ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CampaignTerms:
    """The financial and time terms an immutable campaign version must fix before activation.

    Every field may be ``None`` while the campaign is a draft; activation refuses unless all are set. Review SLA,
    restoration grace and milestone values are configuration: tests use synthetic values, production values are
    not approved yet. The risk window is not here - it is the decided ``QUALIFICATION_RISK_WINDOW`` (Q110).
    """

    kind: PromoCampaignKind
    service_type: ServiceType
    budget_allocated_minor: int | None
    referrer_reward_minor: int | None  # per milestone for driver->driver; see milestone_thresholds
    referee_reward_minor: int | None
    referrer_instrument: PromoInstrument | None
    referee_instrument: PromoInstrument | None
    milestone_thresholds: tuple[int, ...] | None  # e.g. (5, 10) distinct trips; () for single-step campaigns
    min_distinct_clients: int | None  # driver milestones: distinct unlinked clients a threshold also needs
    enrollment_limit: int | None  # max enrollments in this version
    qualification_window: timedelta | None  # from attribution to the qualifying service (not the 72 h window)
    reward_validity: timedelta | None  # how long a granted lot can be spent
    review_sla: timedelta | None
    restoration_grace: timedelta | None
    margin_policy: PromoMarginPolicy | None
    approval_reference: str | None
    extra: Mapping[str, object] = field(default_factory=dict)

    def missing_for_activation(self) -> tuple[str, ...]:
        missing = [
            name
            for name in (
                "budget_allocated_minor",
                "referrer_reward_minor",
                "referee_reward_minor",
                "referrer_instrument",
                "referee_instrument",
                "milestone_thresholds",
                "enrollment_limit",
                "qualification_window",
                "reward_validity",
                "review_sla",
                "restoration_grace",
                "margin_policy",
                "approval_reference",
            )
            if getattr(self, name) is None
        ]
        if self.kind is PromoCampaignKind.REFERRAL_DRIVER_DRIVER and self.min_distinct_clients is None:
            missing.append("min_distinct_clients")
        if self.margin_policy is not None:
            missing.extend(f"margin_policy.{name}" for name in self.margin_policy.unset_fields())
        return tuple(missing)


def validate_activation(terms: CampaignTerms) -> None:
    """Refuse activation of a campaign whose terms are incomplete, zero-valued or not a pilot kind."""
    if PromoCampaignKind(terms.kind) not in PILOT_CAMPAIGN_KINDS:
        raise DomainError(ErrorCode.FEATURE_DISABLED, details={"campaign_kind": str(terms.kind)})
    missing = terms.missing_for_activation()
    if missing:
        raise DomainError(ErrorCode.PROMO_PARAMETERS_UNSET, details={"fields": list(missing)})
    problems: list[str] = []
    if terms.budget_allocated_minor <= 0:
        problems.append("budget_allocated_minor")
    if terms.referrer_reward_minor <= 0 and terms.referee_reward_minor <= 0:
        problems.append("rewards")
    if terms.enrollment_limit <= 0:
        problems.append("enrollment_limit")
    for name in ("qualification_window", "reward_validity", "review_sla", "restoration_grace"):
        if getattr(terms, name) <= timedelta(0):
            problems.append(name)
    if not terms.approval_reference.strip():
        problems.append("approval_reference")
    if terms.margin_policy.min_margin_minor <= 0:
        # Q111: M > 0 keeps C_net >= O + M > 0 on every promo booking; the platform always retains something and
        # the driver's hold is never a zero-amount hold. Not a guarantee of overall profit.
        problems.append("margin_policy.min_margin_minor")
    if terms.kind is PromoCampaignKind.REFERRAL_DRIVER_DRIVER:
        if not terms.milestone_thresholds or list(terms.milestone_thresholds) != sorted(set(terms.milestone_thresholds)):
            problems.append("milestone_thresholds")
        if terms.min_distinct_clients is None or terms.min_distinct_clients <= 0:
            problems.append("min_distinct_clients")
        if terms.referrer_instrument is not PromoInstrument.DRIVER_CREDIT or terms.referee_instrument is not PromoInstrument.DRIVER_CREDIT:
            problems.append("instruments")  # task §6: both driver->driver rewards are Driver Credit
    if terms.kind is PromoCampaignKind.REFERRAL_DRIVER_CLIENT and (
        terms.referrer_instrument is not PromoInstrument.DRIVER_CREDIT
        or terms.referee_instrument is not PromoInstrument.PASSENGER_BONUS
    ):
        problems.append("instruments")
    if terms.kind is PromoCampaignKind.REFERRAL_CLIENT_CLIENT and (
        terms.referrer_instrument is not PromoInstrument.PASSENGER_BONUS
        or terms.referee_instrument is not PromoInstrument.PASSENGER_BONUS
    ):
        problems.append("instruments")
    if problems:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"invalid": sorted(set(problems))})


def max_commitment_for(terms: CampaignTerms) -> int:
    """Both sides' maximum rewards for one enrollment under these terms (milestones multiply the steps)."""
    steps = max(len(terms.milestone_thresholds or ()), 1)
    return enrollment_commitment_minor([terms.referrer_reward_minor * steps, terms.referee_reward_minor * steps])


class DisclosureCode(StrEnum):
    """Conditions shown to a person *before* they join a campaign (Q112). Clients render them as sentences."""

    NOT_CASH = "not_cash"  # a discount right, never money; not transferable
    NEXT_ELIGIBLE_SERVICE = "next_eligible_service"  # the reward is for a later service, not the first one
    REFERRER_SERVICE_EXCLUDED = "referrer_service_excluded"  # the inviter's own service does not qualify
    ANOTHER_DRIVER_QUALIFIES = "another_driver_qualifies"  # ... but a service with another driver does, in time
    QUALIFICATION_DEADLINE = "qualification_deadline"
    REQUIRED_SERVICES = "required_services"
    SERVICE_TYPE_ONLY = "service_type_only"  # spent only on the campaign's service type
    REWARD_VALIDITY = "reward_validity"
    RISK_CHECK = "risk_check"  # 48 h check after the service before the reward becomes available
    ENROLLMENT_LIMIT = "enrollment_limit"
    MILESTONE_UNIT = "milestone_unit"  # what one step of a driver milestone counts (ADR-0023 §17 T2)


def enrollment_disclosures(terms: CampaignTerms) -> dict[DisclosureCode, object]:
    """Everything a participant must see before joining; values are for rendering, codes are stable."""
    disclosures: dict[DisclosureCode, object] = {
        DisclosureCode.NOT_CASH: True,
        DisclosureCode.NEXT_ELIGIBLE_SERVICE: True,
        DisclosureCode.REFERRER_SERVICE_EXCLUDED: True,
        DisclosureCode.ANOTHER_DRIVER_QUALIFIES: True,
        DisclosureCode.SERVICE_TYPE_ONLY: ServiceType(terms.service_type).value,
        DisclosureCode.RISK_CHECK: int(QUALIFICATION_RISK_WINDOW.total_seconds()),
    }
    if terms.qualification_window is not None:
        disclosures[DisclosureCode.QUALIFICATION_DEADLINE] = int(terms.qualification_window.total_seconds())
    if terms.reward_validity is not None:
        disclosures[DisclosureCode.REWARD_VALIDITY] = int(terms.reward_validity.total_seconds())
    if terms.enrollment_limit is not None:
        disclosures[DisclosureCode.ENROLLMENT_LIMIT] = terms.enrollment_limit
    if terms.kind is PromoCampaignKind.REFERRAL_DRIVER_DRIVER:
        disclosures[DisclosureCode.REQUIRED_SERVICES] = tuple(terms.milestone_thresholds or ())
        disclosures[DisclosureCode.MILESTONE_UNIT] = MILESTONE_UNIT
    else:
        disclosures[DisclosureCode.REQUIRED_SERVICES] = REQUIRED_QUALIFYING_SERVICES[ServiceType(terms.service_type)]
    return disclosures


# --- attribution (Q106) -----------------------------------------------------------------------------------


class AttributionOutcome(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"  # the same code again: idempotent, nothing new


def attribution_window_open(*, window_started_at: datetime, now: datetime, first_booking_accepted_at: datetime | None) -> bool:
    """Server clock only. The window starts at the account's first verified phone login and is never renewed.

    Deleting and re-opening an account does not restart it: the promotions module keys the start by the
    protected identity (Q106, Q108), not by the new user row.
    """
    started = ensure_aware_utc(window_started_at, field="window_started_at")
    current = ensure_aware_utc(now, field="now")
    if first_booking_accepted_at is not None:
        return False
    return started <= current < started + ATTRIBUTION_WINDOW


def decide_attribution(
    *,
    referrer_user_id: int,
    referee_user_id: int,
    referrer_identity_keys: frozenset[str],
    referee_identity_keys: frozenset[str],
    existing_referrer_user_id: int | None,
    window_open: bool,
) -> AttributionOutcome:
    """Server-confirmed attribution is single and first-wins (Q106).

    * self: same account, or the protected identity keys overlap (a second account of the same phone/KYC).
    * existing attribution: same referrer -> replay; a different referrer never replaces it.
    """
    if referrer_user_id == referee_user_id or (referrer_identity_keys & referee_identity_keys):
        raise DomainError(ErrorCode.REFERRAL_SELF_REFERRAL)
    if existing_referrer_user_id is not None:
        if existing_referrer_user_id == referrer_user_id:
            return AttributionOutcome.REPLAYED
        raise DomainError(ErrorCode.REFERRAL_ALREADY_ATTRIBUTED)
    if not window_open:
        raise DomainError(ErrorCode.REFERRAL_WINDOW_CLOSED)
    return AttributionOutcome.CREATED


def acquisition_key(identity_key: str, family: str) -> str:
    """Uniqueness key: one protected identity earns one acquisition reward per family (Q106).

    Passenger and parcel client campaigns share ``client_acquisition``; becoming a driver is a separate family.
    """
    if not identity_key or not family:
        raise ValueError("identity_key and family are required")
    return f"acq:{family}:{identity_key}"


def reward_key(*, campaign_version_id: int, attribution_id: int, side: str, milestone: int = 0) -> str:
    """Deterministic grant key: a retried worker or a parallel request lands on the same unique row."""
    if side not in {"referrer", "referee"}:
        raise ValueError("side must be referrer or referee")
    for name, value in (("campaign_version_id", campaign_version_id), ("attribution_id", attribution_id), ("milestone", milestone)):
        _require_int(value, name)
    return f"reward:{campaign_version_id}:{attribution_id}:{side}:{milestone}"


def qualification_event_key(*, kind: str, booking_id: int) -> str:
    """Dedup key of one qualification event (re-delivery of the same booking event is a no-op)."""
    _require_int(booking_id, "booking_id")
    if not kind:
        raise ValueError("kind is required")
    return f"qual:{kind}:{booking_id}"


# --- risk rules: versioned, sourced, correlated (Q113) ----------------------------------------------------


class RiskReliability(StrEnum):
    ELIGIBILITY = "eligibility"  # a definite rule breach (e.g. self-referral) - not a suspicion
    STRONG = "strong"  # hard to produce innocently; still decided by a person
    WEAK = "weak"  # common among honest users (shared IP, family car); context only


class RiskConsequence(StrEnum):
    REJECT = "reject"  # the candidate is not eligible (eligibility breach only); ordinary service is unaffected
    REVIEW = "review"  # a person decides; the reward waits, the user keeps using the service
    CONTEXT = "context"  # alone: nothing; with other *independent* context groups: review
    AUDIT_ONLY = "audit_only"  # recorded, never counts against anyone (e.g. a replayed event is our own retry)


@dataclass(frozen=True, slots=True)
class RiskRule:
    signal: PromoRiskSignal
    source: str  # where the evidence comes from (table / check), so a reviewer can verify it
    reliability: RiskReliability
    consequence: RiskConsequence
    correlation_group: str  # signals in one group are one piece of evidence, never two


@dataclass(frozen=True, slots=True)
class RiskRuleset:
    version: str
    rules: Mapping[PromoRiskSignal, RiskRule]
    independent_context_groups_for_review: int

    def __post_init__(self) -> None:
        missing = set(PromoRiskSignal) - set(self.rules)
        if missing:
            raise ValueError(f"ruleset {self.version} has no rule for {sorted(missing)}")
        for signal, rule in self.rules.items():
            if rule.signal is not signal:
                raise ValueError("rule keyed under the wrong signal")
            if rule.consequence is RiskConsequence.REJECT and rule.reliability is not RiskReliability.ELIGIBILITY:
                raise ValueError("only an eligibility breach may reject; suspicion goes to review")
        if self.independent_context_groups_for_review < 2:
            raise ValueError("one context signal alone must never trigger review")


_S = PromoRiskSignal
_E, _ST, _W = RiskReliability.ELIGIBILITY, RiskReliability.STRONG, RiskReliability.WEAK
_REJECT, _REVIEW, _CONTEXT, _AUDIT = (
    RiskConsequence.REJECT, RiskConsequence.REVIEW, RiskConsequence.CONTEXT, RiskConsequence.AUDIT_ONLY,
)
RISK_RULESET_V1 = RiskRuleset(
    version="2026-09-23.v1",
    independent_context_groups_for_review=2,
    rules={
        rule.signal: rule
        for rule in (
            RiskRule(_S.SELF_REFERRAL, "referral_attributions: referrer = referee", _E, _REJECT, "identity"),
            RiskRule(_S.SELF_DEALING, "bookings: client_user_id = driver_user_id", _E, _REJECT, "identity"),
            RiskRule(_S.IDENTITY_KEY_MATCH, "promo identity HMAC equals an earlier account (may be a recycled number)",
                     _ST, _REVIEW, "identity"),
            RiskRule(_S.KYC_REUSE, "driver documents / vehicles.plate_normalized reused by another account", _ST, _REVIEW, "kyc"),
            RiskRule(_S.LINKED_REFERRAL_CLUSTER, "several referrals qualified through linked accounts", _ST, _REVIEW, "cluster"),
            RiskRule(_S.GPS_TIME_CONFLICT, "tracking evidence contradicts proofs / timestamps", _ST, _REVIEW, "service_evidence"),
            RiskRule(_S.SPLIT_SHIPMENT, "one sender's parcel bookings on one trip, same route/receiver, close in time",
                     _W, _REVIEW, "parcel_split"),
            RiskRule(_S.SHARED_IP, "request IP of referrer and referee", _W, _CONTEXT, "network"),
            RiskRule(_S.SHARED_NETWORK, "same network block derived from that IP", _W, _CONTEXT, "network"),
            RiskRule(_S.SHARED_DEVICE, "communications.device_account_links", _W, _CONTEXT, "device"),
            RiskRule(_S.FAMILY_VEHICLE, "a vehicle shared by referrer and referee drivers", _W, _CONTEXT, "vehicle"),
            RiskRule(_S.RAPID_REREGISTRATION, "several sign-ups from one identity/device in a short time", _W, _CONTEXT, "velocity"),
            RiskRule(_S.REPEATED_PAIR, "trust_support.fraud_signals repeated_pair_bookings", _W, _CONTEXT, "pair"),
            RiskRule(_S.IMPLAUSIBLE_SERVICE, "very short / illogical service for the route", _W, _CONTEXT, "service_shape"),
            RiskRule(_S.PRICE_INFLATION, "agreed price far above the corridor reference (Q90 band)", _W, _CONTEXT, "price"),
            RiskRule(_S.EVENT_REPLAY, "duplicate qualification event key (our own retry)", _W, _AUDIT, "replay"),
        )
    },
)


class RiskOutcome(StrEnum):
    CLEAR = "clear"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    ruleset_version: str
    outcome: RiskOutcome
    reasons: tuple[str, ...]
    context_groups: tuple[str, ...]


def assess_risk(signals: Iterable[PromoRiskSignal | str], ruleset: RiskRuleset = RISK_RULESET_V1) -> RiskAssessment:
    """Signals are not counted: correlated signals (one group) are one piece of evidence (Q113).

    * an eligibility breach rejects the candidate - never the person's ordinary service;
    * a STRONG or REVIEW-rule signal sends the reward to a person;
    * CONTEXT signals need ``independent_context_groups_for_review`` distinct groups; one shared IP (even with
      the network derived from it) is one group and changes nothing.
    """
    observed = {PromoRiskSignal(signal) for signal in signals}
    rules = [ruleset.rules[signal] for signal in sorted(observed)]
    rejects = [rule.signal.value for rule in rules if rule.consequence is RiskConsequence.REJECT]
    if rejects:
        return RiskAssessment(ruleset.version, RiskOutcome.REJECT, tuple(rejects), ())
    reviews = [rule.signal.value for rule in rules if rule.consequence is RiskConsequence.REVIEW]
    groups = tuple(sorted({rule.correlation_group for rule in rules if rule.consequence is RiskConsequence.CONTEXT}))
    if len(groups) >= ruleset.independent_context_groups_for_review:
        reviews.append("independent_context_signals")
    if reviews:
        return RiskAssessment(ruleset.version, RiskOutcome.REVIEW, tuple(reviews), groups)
    return RiskAssessment(ruleset.version, RiskOutcome.CLEAR, (), groups)


# --- qualification (Q109, Q110, Q112) ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualificationFacts:
    """What the service knows about one candidate booking, re-read right before granting."""

    booking_id: int
    trip_id: int
    service_type: ServiceType
    client_user_id: int
    driver_user_id: int
    service_completed_at: datetime | None  # passenger `completed`; parcel delivered **and** completed
    cash_confirmed_at: datetime | None  # cash_status `acknowledged` (evidence of agreement, not bank settlement)
    commission_captured_at: datetime | None
    net_commission_captured_minor: int  # C_net captured from the real prepaid balance
    open_dispute: bool
    cancelled_or_refunded: bool
    risk_signals: tuple[PromoRiskSignal, ...] = ()


class QualificationVerdict(StrEnum):
    NOT_ELIGIBLE = "not_eligible"  # this booking does not count; the referral stays open until its deadline
    WAIT = "wait"  # conditions met, risk window still running
    REVIEW = "review"  # a person decides; neither auto-approve nor auto-reject
    QUALIFIED = "qualified"


@dataclass(frozen=True, slots=True)
class QualificationResult:
    verdict: QualificationVerdict
    reasons: tuple[str, ...] = ()
    ready_at: datetime | None = None
    risk_ruleset_version: str | None = None


def qualification_ready_at(facts: QualificationFacts, risk_window: timedelta = QUALIFICATION_RISK_WINDOW) -> datetime | None:
    """Q110: the risk window starts at the **latest** of completion, cash confirmation and capture."""
    stamps = (facts.service_completed_at, facts.cash_confirmed_at, facts.commission_captured_at)
    if any(stamp is None for stamp in stamps):
        return None
    return max(ensure_aware_utc(stamp, field="stamp") for stamp in stamps) + risk_window


def evaluate_qualification(
    facts: QualificationFacts,
    *,
    now: datetime,
    referrer_user_id: int | None,
    ruleset: RiskRuleset = RISK_RULESET_V1,
) -> QualificationResult:
    """One booking as qualification evidence (Q110). GPS or a driver's "done" tap alone is never enough.

    A booking served by the referrer does not count for either side (Q112). That is a verdict about *this
    booking only*: the attribution stays open and a later service with another driver before the
    qualification deadline still qualifies it (:func:`referral_can_still_qualify`).
    """
    now = ensure_aware_utc(now, field="now")
    reasons: list[str] = []
    if facts.cancelled_or_refunded:
        reasons.append("cancelled_or_refunded")
    if facts.service_completed_at is None:
        reasons.append("service_not_completed")
    if facts.cash_confirmed_at is None:
        reasons.append("cash_not_confirmed")
    if facts.commission_captured_at is None:
        reasons.append("commission_not_captured")
    if validate_minor_amount(facts.net_commission_captured_minor, name="net_commission_captured_minor") <= 0:
        reasons.append("no_net_commission")  # nominal 0% and discounts that took C_net to zero alike
    if facts.open_dispute:
        reasons.append("open_dispute")
    if referrer_user_id is not None and facts.driver_user_id == referrer_user_id:
        reasons.append("served_by_referrer")
    signals = set(facts.risk_signals)
    if facts.client_user_id == facts.driver_user_id:
        signals.add(PromoRiskSignal.SELF_DEALING)
    risk = assess_risk(signals, ruleset)
    if risk.outcome is RiskOutcome.REJECT:
        reasons.extend(risk.reasons)
    if reasons:
        return QualificationResult(QualificationVerdict.NOT_ELIGIBLE, tuple(reasons), None, risk.ruleset_version)
    ready_at = qualification_ready_at(facts)
    if risk.outcome is RiskOutcome.REVIEW:
        return QualificationResult(QualificationVerdict.REVIEW, risk.reasons, ready_at, risk.ruleset_version)
    if now < ready_at:
        return QualificationResult(QualificationVerdict.WAIT, ("risk_window",), ready_at, risk.ruleset_version)
    return QualificationResult(QualificationVerdict.QUALIFIED, (), ready_at, risk.ruleset_version)


def qualification_deadline(enrolled_at: datetime, qualification_window: timedelta) -> datetime:
    """The campaign's qualification period, counted from **enrollment** (joining the campaign) - not from the
    code click and not from the 72 h attribution window (Q106, Q112, Q117). Reward spend validity is a third,
    separate period (the lot's ``expires_at``)."""
    if qualification_window <= timedelta(0):
        raise ValueError("qualification window must be positive")
    return ensure_aware_utc(enrolled_at, field="enrolled_at") + qualification_window


def referral_can_still_qualify(*, now: datetime, deadline: datetime, attribution_status: str) -> bool:
    """A non-counting booking (e.g. served by the referrer) never closes the referral early."""
    open_status = attribution_status in {"attributed", "qualifying"}
    return open_status and ensure_aware_utc(now, field="now") < ensure_aware_utc(deadline, field="deadline")


def review_due_at(opened_at: datetime, sla: timedelta) -> datetime:
    """A review never stays open without a deadline; past it the item escalates (never auto-decides)."""
    if sla <= timedelta(0):
        raise ValueError("review SLA must be positive")
    return ensure_aware_utc(opened_at, field="opened_at") + sla


# --- timeliness inside the qualification period (Q120) ----------------------------------------------------


class PaymentTiming(StrEnum):
    MISSING = "missing"  # the client's payment is not confirmed (yet)
    IN_TIME = "in_time"  # a trusted confirmation exists at or before the deadline
    LATE = "late"  # confirmed, and the first server record of it is after the deadline
    UNVERIFIED = "unverified"  # confirmed after the deadline but recorded before it, or no confirming record: review


# Reasons of ``evaluate_qualification`` that only mean "the platform has not captured yet" (Q120): while the hold
# is still open they make the booking wait, never disqualify it.
CAPTURE_PENDING_REASONS: frozenset[str] = frozenset({"commission_not_captured", "no_net_commission"})
CASH_TIME_UNVERIFIED = "cash_time_unverified"


def service_in_time(completed_at: datetime | None, deadline: datetime) -> bool:
    """The service itself must be completed inside the qualification period (Q120)."""
    return completed_at is not None and ensure_aware_utc(completed_at, field="completed_at") <= ensure_aware_utc(
        deadline, field="deadline"
    )


def payment_timing(
    *,
    deadline: datetime,
    cash_confirmed: bool,
    confirmed_at: datetime | None,
    first_recorded_at: datetime | None,
) -> PaymentTiming:
    """The client's own payment condition, judged from server-stamped records only (Q120).

    ``confirmed_at`` is the server time of the trusted confirmation (counterparty acknowledgement or an admin's
    ``resolve_paid``); ``first_recorded_at`` is the server time the payment report was first stored. A time the
    user typed into a report is never an input: an old claimed date cannot open eligibility. When the payment was
    confirmed only after the deadline but reported before it, its real time cannot be determined - a person
    decides (``UNVERIFIED`` -> review), the booking is neither counted nor thrown away.
    """
    deadline = ensure_aware_utc(deadline, field="deadline")
    if not cash_confirmed:
        return PaymentTiming.MISSING
    if confirmed_at is None:
        return PaymentTiming.UNVERIFIED  # confirmed state without a confirming record
    if ensure_aware_utc(confirmed_at, field="confirmed_at") <= deadline:
        return PaymentTiming.IN_TIME
    if first_recorded_at is not None and ensure_aware_utc(first_recorded_at, field="first_recorded_at") <= deadline:
        return PaymentTiming.UNVERIFIED
    return PaymentTiming.LATE


def awaiting_capture(result: QualificationResult, *, hold_open: bool) -> bool:
    """In time, only the platform's capture is missing and still possible: wait, keep the reserve (Q120)."""
    return (
        hold_open
        and result.verdict is QualificationVerdict.NOT_ELIGIBLE
        and bool(result.reasons)
        and set(result.reasons) <= CAPTURE_PENDING_REASONS
    )


# --- progress: driver milestones, passenger and parcel referrals (task §6, Q109, Q113) --------------------


@dataclass(frozen=True, slots=True)
class MilestoneEvidence:
    trip_id: int
    booking_id: int
    client_user_id: int
    qualified: bool  # evaluate_qualification(...) == QUALIFIED for this booking
    client_linked_to_referral: bool = False  # client is the referrer, the referee, or a linked identity


@dataclass(frozen=True, slots=True)
class MilestoneProgress:
    distinct_trips: int
    distinct_clients: int


def milestone_progress(evidence: Iterable[MilestoneEvidence]) -> MilestoneProgress:
    """Distinct trips with at least one qualified booking from an unlinked client.

    Several bookings on one trip count as one trip; the same client repeatedly counts once toward
    ``distinct_clients``.
    """
    trips: set[int] = set()
    clients: set[int] = set()
    for item in evidence:
        if not item.qualified or item.client_linked_to_referral:
            continue
        trips.add(item.trip_id)
        clients.add(item.client_user_id)
    return MilestoneProgress(distinct_trips=len(trips), distinct_clients=len(clients))


def milestones_reached(progress: MilestoneProgress, thresholds: Iterable[int], *, min_distinct_clients: int) -> tuple[int, ...]:
    """Thresholds met by distinct trips, each also needing ``min(threshold, min_distinct_clients)`` clients."""
    reached = []
    for threshold in thresholds:
        _require_int(threshold, "threshold")
        if progress.distinct_trips >= threshold and progress.distinct_clients >= min(threshold, min_distinct_clients):
            reached.append(threshold)
    return tuple(reached)


# ADR-0023 §17 T2: a driver milestone step is one *distinct trip* with at least one qualified booking of an unlinked client;
# several bookings on one trip are one step. Stated in the campaign disclosures before joining.
MILESTONE_UNIT = "distinct_trip"

# Q109: a passenger client referral needs one qualifying booking; a parcel referral two independent shipments.
REQUIRED_QUALIFYING_SERVICES: dict[ServiceType, int] = {ServiceType.PASSENGER: 1, ServiceType.PARCEL: 2}
# Q113: parcel bookings of one sender closer than this, on one trip with the same route and receiver, look like one
# shipment split for the reward -> review (never an automatic exclusion). Synthetic default; configurable.
SPLIT_SHIPMENT_WINDOW = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class ServiceEvidence:
    """One booking as referral evidence. For parcels every record must exist for it to count (Q113)."""

    booking_id: int
    trip_id: int
    client_user_id: int
    qualified: bool
    booked_at: datetime
    handover_recorded: bool = True  # parcel: this booking's own pickup/handover proof
    delivery_recorded: bool = True  # parcel: this booking's own delivery proof
    commission_captured: bool = True
    pickup_stop_id: int | None = None
    dropoff_stop_id: int | None = None
    receiver_key: str | None = None  # protected receiver identifier; never the phone itself


@dataclass(frozen=True, slots=True)
class ReferralProgress:
    counted: int
    required: int
    risk_signals: tuple[PromoRiskSignal, ...] = ()

    @property
    def complete(self) -> bool:
        return self.counted >= self.required


def client_referral_progress(
    service_type: ServiceType | str,
    evidence: Iterable[ServiceEvidence],
    *,
    split_window: timedelta = SPLIT_SHIPMENT_WINDOW,
) -> ReferralProgress:
    """Counted services toward a client referral.

    One booking is one service however many seats or boxes it carries. A parcel shipment counts when it is its
    own booking with its own handover record, delivery proof and captured commission - two such shipments on one
    trip both count (Q113). Bookings that look like one shipment split in two are flagged for review.
    """
    kind = ServiceType(service_type)
    counted: dict[int, ServiceEvidence] = {}
    for item in evidence:
        if not item.qualified or item.booking_id in counted:
            continue
        if kind is ServiceType.PARCEL and not (item.handover_recorded and item.delivery_recorded and item.commission_captured):
            continue
        counted[item.booking_id] = item
    signals: tuple[PromoRiskSignal, ...] = ()
    if kind is ServiceType.PARCEL and _looks_split(list(counted.values()), split_window):
        signals = (PromoRiskSignal.SPLIT_SHIPMENT,)
    return ReferralProgress(len(counted), REQUIRED_QUALIFYING_SERVICES[kind], signals)


def _looks_split(items: list[ServiceEvidence], window: timedelta) -> bool:
    for index, first in enumerate(items):
        for second in items[index + 1:]:
            same_shipment_shape = (
                first.trip_id == second.trip_id
                and first.client_user_id == second.client_user_id
                and first.pickup_stop_id == second.pickup_stop_id
                and first.dropoff_stop_id == second.dropoff_stop_id
                and first.receiver_key is not None
                and first.receiver_key == second.receiver_key
            )
            gap = abs(ensure_aware_utc(first.booked_at, field="booked_at") - ensure_aware_utc(second.booked_at, field="booked_at"))
            if same_shipment_shape and gap <= window:
                return True
    return False


# --- identity signals (Q108) ------------------------------------------------------------------------------


def identity_match_effect(*, matched_previous_account: bool) -> str:
    """A matching protected phone identifier may be a recycled number: it never blocks the account or ordinary
    service; it only sends the *new-user reward* to review (Q108)."""
    return "review_acquisition_reward" if matched_previous_account else "none"


# --- referral codes (stage 2, Q117) ------------------------------------------------------------------------

# Unambiguous upper-case alphabet (no 0/O, 1/I/L). A code is a public, shareable identifier - not a secret and not
# an access token (ADR-0018 hashing does not apply): knowing one lets a new user say who invited them, nothing more.
# 31^8 ~ 8.5e11 combinations; enumeration is limited by the public-check rate limit (stage 5 contract).
REFERRAL_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
REFERRAL_CODE_LENGTH = 8


def new_referral_code(randbelow: Callable[[int], int] = secrets.randbelow) -> str:
    """A random code from the CSPRNG. Never derived from a phone, a name, KYC data or a user id."""
    return "".join(REFERRAL_CODE_ALPHABET[randbelow(len(REFERRAL_CODE_ALPHABET))] for _ in range(REFERRAL_CODE_LENGTH))


def normalize_referral_code(raw: str | None) -> str | None:
    """What a person typed or a link carried -> canonical code, or ``None`` if it cannot be a code.

    Case, spaces and dashes are forgiven; anything else is not a code. ``None`` is not an error for the caller's
    registration - an invalid code only means "no referral".
    """
    if raw is None:
        return None
    cleaned = "".join(ch for ch in raw.strip().upper() if ch not in " -")
    if len(cleaned) != REFERRAL_CODE_LENGTH or any(ch not in REFERRAL_CODE_ALPHABET for ch in cleaned):
        return None
    return cleaned


def referral_family_for(audience_role: str) -> PromoCampaignFamily:
    """Q106: the referee's audience decides the family. A client becoming a driver is a *driver* acquisition."""
    families = {"client": PromoCampaignFamily.CLIENT_ACQUISITION, "driver": PromoCampaignFamily.DRIVER_ACQUISITION}
    if audience_role not in families:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "audience_role"})
    return families[audience_role]


# campaign kind -> (referrer role, referee audience); the enrollment checks both (Q117)
CAMPAIGN_PARTIES: dict[PromoCampaignKind, tuple[str, str]] = {
    PromoCampaignKind.REFERRAL_CLIENT_CLIENT: ("client", "client"),
    PromoCampaignKind.REFERRAL_DRIVER_CLIENT: ("driver", "client"),
    PromoCampaignKind.REFERRAL_DRIVER_DRIVER: ("driver", "driver"),
}


# --- protected phone identifier (Q108) ---------------------------------------------------------------------

PROMO_IDENTITY_PURPOSE = "promo-identity-key"
PROMO_IDENTITY_KEY_VERSION = 1


def normalize_phone(raw: str) -> str | None:
    """Uzbek mobile number -> ``+998XXXXXXXXX``; ``None`` when it is not one (tombstones, garbage)."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) != 12 or not digits.startswith("998"):
        return None
    return "+" + digits


def identity_digest(key: bytes, normalized_phone: str) -> str:
    """HMAC-SHA256 of the normalised phone. A protected identifier, **not** anonymous data (Q108): whoever holds
    the key can test a phone number against it. The key never leaves process memory."""
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("identity key must be at least 32 bytes")
    if normalize_phone(normalized_phone) != normalized_phone:
        raise ValueError("phone must be normalised first")
    return hmac.new(key, normalized_phone.encode("ascii"), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class IdentityRetentionPolicy:
    """How long a deleted account's protected identifier is kept. ``None`` = not approved (Q108): it is purged at
    deletion, so no new durable anti-fraud data is collected from deleted accounts."""

    after_deletion: timedelta | None = None


def enrollment_allowed(*, is_production: bool, retention: IdentityRetentionPolicy, identity_key_available: bool) -> bool:
    """No fallback (Q108, Q118): without an identity key nobody enrolls, and in production nobody enrolls until the
    retention period and legal basis are approved - protection is never skipped to hand out a reward."""
    if not identity_key_available:
        return False
    return not is_production or retention.after_deletion is not None


# --- enrollment terms (Q117) ----------------------------------------------------------------------------------


def terms_fingerprint(terms: CampaignTerms, *, campaign_version_id: int) -> str:
    """Hash of exactly what a participant agrees to: the version, rewards, instruments, service, milestones,
    deadlines and every disclosure. Stored on the enrollment; a different version or edit means a different hash."""
    _require_int(campaign_version_id, "campaign_version_id")
    disclosures = {code.value: value for code, value in enrollment_disclosures(terms).items()}
    payload = {
        "campaign_version_id": campaign_version_id,
        "kind": PromoCampaignKind(terms.kind).value,
        "service_type": ServiceType(terms.service_type).value,
        "referrer_reward_minor": terms.referrer_reward_minor,
        "referee_reward_minor": terms.referee_reward_minor,
        "referrer_instrument": None if terms.referrer_instrument is None else PromoInstrument(terms.referrer_instrument).value,
        "referee_instrument": None if terms.referee_instrument is None else PromoInstrument(terms.referee_instrument).value,
        "milestone_thresholds": list(terms.milestone_thresholds or ()),
        "min_distinct_clients": terms.min_distinct_clients,
        "disclosures": {key: list(value) if isinstance(value, tuple) else value for key, value in disclosures.items()},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def enrollment_rewards(terms: CampaignTerms) -> list[tuple[str, PromoInstrument, int, int]]:
    """``(side, instrument, amount, milestone)`` for every reward one enrollment may earn - both sides, every step.

    Zero-amount sides are left out (a one-sided campaign). The sum is ``max_commitment_for(terms)``.
    """
    steps = tuple(terms.milestone_thresholds or ()) or (0,)
    rewards: list[tuple[str, PromoInstrument, int, int]] = []
    for milestone in steps:
        if terms.referrer_reward_minor:
            rewards.append(("referrer", PromoInstrument(terms.referrer_instrument), terms.referrer_reward_minor, milestone))
        if terms.referee_reward_minor:
            rewards.append(("referee", PromoInstrument(terms.referee_instrument), terms.referee_reward_minor, milestone))
    return rewards


def request_fingerprint(payload: Mapping[str, object]) -> str:
    """Canonical hash of a command body: the same idempotency key with a different body is a conflict (Q118)."""
    return hashlib.sha256(json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
