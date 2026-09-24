"""The simulation engine: a day-by-day walk through code -> attribution -> enrollment -> qualification -> grant ->
spend, with cancels, disputes, reversals, late capture, reviews, expiry, grace and reinstatement.

Money never has a second formula here. Every amount comes from ``app.contracts.promo``:
``choose_passenger_source`` / ``choose_driver_source`` / ``quote_at_accept`` (the same chooser the booking flow uses),
``combined_margin_policy``, ``LotBalance`` (a lot's buckets), ``BudgetPosition`` (promise -> grant -> consume as one
obligation), ``restored_expiry`` (fair restoration per holder), ``evaluate_qualification`` (48 h risk window,
served-by-referrer), ``milestone_progress`` / ``milestones_reached``. The engine only decides *what happens* (with
seeded random streams); it never decides *how much*.

Accounting rules (checked by ``report.checks`` on every snapshot):
* one booking: F_cash = F - P, C_net = C - P - H (from the quote); P and H are never subtracted again from C_net;
* the programme's incentive cost is the consumed P + H - already the gap between C and C_net;
* driver top-ups are not revenue, and the client's cash to the driver is not platform revenue;
* O (variable cost per served booking) is one line; nothing inside it is added again.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.contracts.enums import (
    PromoCampaignKind,
    PromoFault,
    PromoInstrument,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.promo import (
    REQUIRED_QUALIFYING_SERVICES,
    BudgetPosition,
    CampaignTerms,
    DriverCreditOutcome,
    FundingSource,
    LotBalance,
    MilestoneEvidence,
    PassengerBonusConsent,
    PromoMarginPolicy,
    PromoQuote,
    QualificationFacts,
    QualificationVerdict,
    campaign_pair,
    choose_driver_source,
    choose_passenger_source,
    combined_margin_policy,
    enrollment_rewards,
    evaluate_qualification,
    max_commitment_for,
    milestone_progress,
    milestones_reached,
    passenger_bonus_allowed,
    plain_quote,
    quote_at_accept,
    restored_expiry,
    service_in_time,
    validate_activation,
)

from .config import CampaignModel, Scenario

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)  # a synthetic start; nothing depends on the calendar
FAMILY = {PromoCampaignKind.REFERRAL_CLIENT_CLIENT: "client_acquisition",
          PromoCampaignKind.REFERRAL_DRIVER_CLIENT: "client_acquisition",
          PromoCampaignKind.REFERRAL_DRIVER_DRIVER: "driver_acquisition"}


# --- one booking's terms: the production chooser, nothing else -------------------------------------------------------


@dataclass(frozen=True)
class LotView:
    lot_id: int
    campaign_id: int
    available_minor: int
    expires_order: float  # soonest-expiring first (the production tie-break)


@dataclass(frozen=True)
class BookingTerms:
    quote: PromoQuote
    h_outcome: DriverCreditOutcome
    allocations: tuple[tuple[int, int], ...]  # (lot_id, amount) for P and H
    passenger_campaign_id: int | None
    driver_campaign_id: int | None
    cost_basis: str | None


def _sources(lots: list[LotView]) -> tuple[list[FundingSource], dict[int, list[LotView]]]:
    by_campaign: dict[int, list[LotView]] = defaultdict(list)
    for lot in sorted(lots, key=lambda item: (item.expires_order, item.lot_id)):
        by_campaign[lot.campaign_id].append(lot)
    sources = [FundingSource(cid, sum(lot.available_minor for lot in rows), (rows[0].expires_order, cid))
               for cid, rows in by_campaign.items()]
    return sources, by_campaign


def _allocate(rows: list[LotView], amount: int) -> list[tuple[int, int]]:
    plan, left = [], amount
    for lot in rows:
        take = min(left, lot.available_minor)
        if take > 0:
            plan.append((lot.lot_id, take))
            left -= take
    if left:
        raise ValueError("allocation exceeds the usable lots")  # the chooser never quotes more than is available
    return plan


def booking_terms(*, fare_minor: int, fee_bps: int, p_lots: list[LotView], h_lots: list[LotView],
                  policies: dict[int, PromoMarginPolicy], combinations: dict[tuple[int, int], str],
                  uses_bonus: bool, now: datetime) -> BookingTerms:
    """The money terms of one booking exactly as ``promotions.booking.prepare_accept`` decides them (client accepts
    with a fresh consent; the driver's capable app). Used by the engine and by the PG comparison test."""
    p_sources, p_rows = _sources(p_lots)
    h_sources, h_rows = _sources(h_lots)
    p_src = consent = None
    if uses_bonus and p_sources:
        best = choose_passenger_source(p_sources, fare_minor=fare_minor, fee_bps=fee_bps,
                                       policy_of=lambda src: policies[src.campaign_id])
        if best is not None:
            p_src, p_quote = best
            consent = PassengerBonusConsent(proposal_version_id="sim", fare_minor=fare_minor,
                                            passenger_bonus_minor=p_quote.passenger_bonus_minor,
                                            cash_due_minor=p_quote.cash_due_minor, quote_fingerprint="",
                                            expires_at=now + timedelta(days=1))

    def pairing(p: FundingSource | None, h: FundingSource):
        if p is None or p.campaign_id == h.campaign_id:
            return policies[h.campaign_id], None
        basis = combinations.get(campaign_pair(p.campaign_id, h.campaign_id))
        if basis is None:
            return None
        return combined_margin_policy(policies[p.campaign_id], policies[h.campaign_id], basis), basis

    h_src, basis, quote, outcome = choose_driver_source(
        p_source=p_src, h_sources=h_sources, pairing=pairing, consent=consent, subject="sim", now=now,
        fare_minor=fare_minor, fee_bps=fee_bps)
    if quote is None:
        try:
            quote = quote_at_accept(consent=consent, proposal_version_id="sim", now=now, fare_minor=fare_minor,
                                    fee_bps=fee_bps, policy=None if p_src is None else policies[p_src.campaign_id],
                                    passenger_bonus_available_minor=0 if p_src is None else p_src.available_minor,
                                    driver_credit_available_minor=0)
        except DomainError as exc:
            if exc.code is not ErrorCode.PROMO_PARAMETERS_UNSET:
                raise
            quote, p_src = plain_quote(fare_minor=fare_minor, fee_bps=fee_bps), None
    allocations: list[tuple[int, int]] = []
    if quote.passenger_bonus_minor:
        allocations += _allocate(p_rows[p_src.campaign_id], quote.passenger_bonus_minor)
    if quote.driver_credit_minor:
        allocations += _allocate(h_rows[h_src.campaign_id], quote.driver_credit_minor)
    return BookingTerms(quote, outcome, tuple(allocations),
                        p_src.campaign_id if quote.passenger_bonus_minor else None,
                        h_src.campaign_id if quote.driver_credit_minor else None,
                        basis if quote.passenger_bonus_minor and quote.driver_credit_minor else None)


# --- state ------------------------------------------------------------------------------------------------------------


@dataclass
class Lot:
    id: int
    owner: int
    instrument: PromoInstrument
    service: ServiceType
    campaign_id: int
    enrollment_id: int
    balance: LotBalance
    expires_at: datetime
    granted_at: datetime
    available_from: datetime  # production rule: the spend period starts when the holder can spend
    status: str = "available"  # available | expired | reversed
    restored_from: datetime | None = None
    restored_until: datetime | None = None
    first_spend_at: datetime | None = None
    bookings_used: int = 0
    fraud: bool = False
    spends: list[tuple[datetime, int]] = field(default_factory=list)  # (capture time, amount) - consumed only
    expired_at: datetime | None = None


@dataclass
class Booking:
    id: int
    service: ServiceType
    corridor: str
    day: int
    client: int
    driver: int
    fare_bucket: str
    terms: BookingTerms
    variable_cost_minor: int
    status: str = "served"  # served | cancelled
    capture_day: int | None = None
    captured: bool = False
    fee_released: bool = False
    dispute_open: bool = False
    reversed_minor: int = 0
    linked_client: bool = False
    key: str = ""  # the person's tag + order number: stable across a scenario and its matched control


@dataclass
class Person:
    id: int
    service: ServiceType
    arrived_day: int
    attributed: bool
    incremental: bool
    rng: random.Random
    next_order_day: int | None = None
    orders: int = 0
    enrollment: int | None = None
    unserved: int = 0
    captured_bookings: int = 0
    tag: str = ""  # service:day:index - the same person in every scenario (ids are not)
    attempts: list[tuple[int, str]] = field(default_factory=list)  # (day, outcome): unserved | cancelled | p_applied | no_bonus |
    # receiver_pays | not_chosen | no_room - what happened to an order and to the holder's bonus on it
    activated_day: int | None = None  # service day of the first booking whose commission was captured


@dataclass
class Enrollment:
    id: int
    campaign: CampaignModel
    terms: CampaignTerms
    referee: int
    referrer: int
    referee_is_driver: bool
    referrer_is_driver: bool
    enrolled_day: int
    promised_left: int
    deadline: datetime
    status: str = "promised"  # promised | granted | released | rejected
    review_until_day: int | None = None
    review_reject: bool = False
    granted_milestones: set[int] = field(default_factory=set)
    review_wait_days: int = 0


@dataclass
class Driver:
    id: int
    capable: bool
    referee_enrollment: int | None = None


class _Ledger:
    """Cumulative money and counters by (dimension, key). Kept as integers; the report divides."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def add(self, keys: list[tuple[str, str]], **values: int) -> None:
        for key in keys:
            row = self.data[key]
            for name, value in values.items():
                row[name] += value

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {f"{dim}:{key}": dict(row) for (dim, key), row in sorted(self.data.items())}


class Simulation:
    def __init__(self, scenario: Scenario) -> None:
        self.s = scenario
        self.budget: dict[int, BudgetPosition] = {}
        self.terms: dict[int, CampaignTerms] = {}
        self.policies: dict[int, PromoMarginPolicy] = {}
        self.peak_committed: dict[int, int] = defaultdict(int)
        self.peak_shortfall: dict[int, int] = defaultdict(int)
        self.peak_utilization_bps: dict[int, int] = defaultdict(int)  # committed / allocation *at that moment*
        self.shortfall_since_day: dict[int, int] = {}
        self.budget_changes: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.budget_blocked: dict[int, int] = defaultdict(int)
        self.reinstated: dict[int, int] = defaultdict(int)
        self.reinstate_unfulfilled: dict[int, int] = defaultdict(int)
        self.not_activated: dict[int, str] = {}
        for c in scenario.campaigns:
            terms = CampaignTerms(
                kind=c.kind, service_type=c.service, budget_allocated_minor=c.budget_minor,
                referrer_reward_minor=c.referrer_reward_minor, referee_reward_minor=c.referee_reward_minor,
                referrer_instrument=c.referrer_instrument, referee_instrument=c.referee_instrument,
                milestone_thresholds=c.milestones, min_distinct_clients=c.min_distinct_clients,
                enrollment_limit=10**9, qualification_window=timedelta(days=c.qualification_days),
                reward_validity=timedelta(days=c.validity_days), review_sla=timedelta(hours=c.review_sla_hours),
                restoration_grace=timedelta(days=c.grace_days), margin_policy=c.policy,
                approval_reference="SIMULATION-ONLY")
            try:
                validate_activation(terms)  # the same activation gate as production (unset or zero -> refuse)
            except DomainError as exc:
                if (exc.details or {}).get("invalid") != ["budget_allocated_minor"]:
                    raise  # anything else is a broken scenario, not a result
                self.not_activated[c.id] = "budget_allocated_minor"  # zero budget: the campaign never starts
                continue
            self.terms[c.id] = terms
            self.policies[c.id] = c.policy
            self.budget[c.id] = BudgetPosition(allocated_minor=c.budget_minor)
        self.campaigns = {c.id: c for c in scenario.campaigns if c.id not in self.not_activated}
        self.combinations = {campaign_pair(a, b): basis for a, b, basis in scenario.combinations}
        self.cost_policy = PromoMarginPolicy(None, None, None, None, scenario.variable_cost_fixed_minor,
                                             scenario.variable_cost_bps, None)
        self.people: dict[int, Person] = {}
        self.drivers: dict[int, Driver] = {}
        self.enrollments: dict[int, Enrollment] = {}
        self.lots: dict[int, Lot] = {}
        self.bookings: list[Booking] = []
        self.by_client: dict[int, list[Booking]] = defaultdict(list)
        self.by_driver: dict[int, list[Booking]] = defaultdict(list)
        self.captures: dict[int, list[Booking]] = defaultdict(list)
        self.reversals: dict[int, list[Booking]] = defaultdict(list)
        self.fraud_checks: dict[int, list[int]] = defaultdict(list)
        self.cancel_reviews: dict[int, list[int]] = defaultdict(list)
        self.ledger = _Ledger()
        self.snapshots: dict[int, dict[str, Any]] = {}
        self.events: dict[str, int] = defaultdict(int)
        self._ids = iter(range(1, 10**9))
        rng = random.Random(f"{scenario.seed}:drivers")
        for _ in range(scenario.drivers.pool_size):
            self._new_driver(rng)

    # --- helpers ------------------------------------------------------------------------------------------------

    def _rng(self, tag: str) -> random.Random:
        return random.Random(f"{self.s.seed}:{tag}")

    @staticmethod
    def _poisson(rng: random.Random, lam: float) -> int:
        if lam <= 0:
            return 0
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1

    @staticmethod
    def _pick(rng: random.Random, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        roll, acc = rng.random() * total, 0.0
        for key, weight in weights.items():
            acc += weight
            if roll <= acc:
                return key
        return next(reversed(weights))

    def _new_driver(self, rng: random.Random) -> Driver:
        driver = Driver(id=next(self._ids), capable=rng.random() < self.s.drivers.capable_app_share)
        self.drivers[driver.id] = driver
        return driver

    def _now(self, day: int) -> datetime:
        return T0 + timedelta(days=day, hours=3)

    def _track_budget(self, cid: int, day: int | None = None) -> None:
        pos = self.budget[cid]
        self.peak_committed[cid] = max(self.peak_committed[cid], pos.committed_minor)
        self.peak_shortfall[cid] = max(self.peak_shortfall[cid], pos.shortfall_minor)
        if pos.allocated_minor:
            self.peak_utilization_bps[cid] = max(self.peak_utilization_bps[cid],
                                                 pos.committed_minor * 10_000 // pos.allocated_minor)
        if pos.shortfall_minor and day is not None:
            self.shortfall_since_day.setdefault(cid, day)

    # --- the day loop -------------------------------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        for day in range(self.s.days):
            now = self._now(day)
            self._budget_cuts(day)
            self._expire_lots(day, now)
            self._decide_cancel_reviews(day, now)
            self._arrivals(day)
            self._driver_arrivals(day)
            self._orders(day, now)
            self._settle(day, now)
            self._qualify(day, now)
            self._fraud(day, now)
            if day + 1 in self.s.snapshots:
                self.snapshots[day + 1] = self._snapshot(day + 1, now)
        return {"scenario": self.s.name, "snapshots": self.snapshots}

    def _budget_cuts(self, day: int) -> None:
        """Two different production operations (G14): a plain ``reduce`` takes at most ``max(0, B - S - L)`` - the
        rest of the request is refused, exactly as ``request_budget_change`` refuses it; a ``funding_loss`` (external
        funding really gone, recorded with evidence) may leave a shortfall that stops new promises."""
        for cid, cut in self.s.budget_cuts.items():
            if cut["day"] != day or cid not in self.budget:
                continue
            requested, position = cut["amount_minor"], self.budget[cid]
            if cut.get("kind", "reduce") == "funding_loss":
                amount = min(requested, position.allocated_minor)
                if amount:
                    self.budget[cid] = position.record_funding_loss(amount)
                self.budget_changes[cid]["funding_loss"] += amount
            else:
                amount = min(requested, position.reducible_minor(self.reinstate_unfulfilled[cid]))
                if amount:
                    self.budget[cid] = position.reduce_allocation(
                        amount, pending_reinstatements_minor=self.reinstate_unfulfilled[cid])
                self.budget_changes[cid]["reduce_applied"] += amount
                self.budget_changes[cid]["reduce_refused"] += requested - amount
            self._track_budget(cid, day)

    def _arrivals(self, day: int) -> None:
        for service, model in self.s.services.items():
            rng = self._rng(f"arrive:{service.value}:{day}")
            base = self._poisson(rng, model.base_new_per_day)
            # referral can only bring someone while a campaign of this service can still promise (zero budget or a
            # cut budget: nothing to invite with, so no incremental arrivals and no new attribution)
            active = any(c.service is service and self._can_promise(c) for c in self.campaigns.values())
            extra = self._poisson(self._rng(f"incremental:{service.value}:{day}"), model.incremental_new_per_day) if (
                self.s.referral_enabled and active) else 0
            for index in range(base + extra):
                incremental = index >= base
                roll = self._rng(f"attributed:{service.value}:{day}:{index}").random()
                attributed = self.s.referral_enabled and active and (incremental or roll < model.attributed_share_of_base)
                tag = f"{service.value}:{day}:{index}"
                person = Person(id=10_000_000 + next(self._ids), service=service, arrived_day=day, attributed=attributed,
                                incremental=incremental, rng=self._rng(f"person:{tag}"), tag=tag)
                self.people[person.id] = person
                keys = [("service", service.value)]
                self.ledger.add(keys, arrived=1, arrived_incremental=int(incremental), attributed=int(attributed))
                if person.rng.random() < model.first_order_prob:
                    low, high = model.first_order_delay_days
                    person.next_order_day = day + person.rng.randint(low, high)
                enroll_rng = self._rng(f"enroll:{tag}")  # its own stream: base people act alike in every scenario
                if attributed and enroll_rng.random() < model.enrollment_rate:
                    self._enroll_client(person, day, enroll_rng)

    def _can_promise(self, campaign: CampaignModel) -> bool:
        return self.budget[campaign.id].accepts_new_enrollments(max_commitment_for(self.terms[campaign.id]))

    def _campaign_for(self, rng: random.Random, service: ServiceType, kinds: set[PromoCampaignKind]) -> CampaignModel | None:
        options = {str(c.id): c.invite_share for c in self.campaigns.values() if c.service is service and c.kind in kinds}
        return None if not options else self.campaigns[int(self._pick(rng, options))]

    def _enroll(self, campaign: CampaignModel, referee: int, referrer: int, day: int, *, referee_is_driver: bool,
                referrer_is_driver: bool) -> Enrollment | None:
        commitment = max_commitment_for(self.terms[campaign.id])
        position = self.budget[campaign.id]
        if not position.accepts_new_enrollments(commitment):
            self.budget_blocked[campaign.id] += 1  # no new promise; earlier ones stand
            return None
        self.budget[campaign.id] = position.promise(commitment)
        self._track_budget(campaign.id)
        enrollment = Enrollment(
            id=next(self._ids), campaign=campaign, terms=self.terms[campaign.id], referee=referee, referrer=referrer,
            referee_is_driver=referee_is_driver, referrer_is_driver=referrer_is_driver, enrolled_day=day,
            promised_left=commitment, deadline=self._now(day) + timedelta(days=campaign.qualification_days))
        self.enrollments[enrollment.id] = enrollment
        return enrollment

    def _enroll_client(self, person: Person, day: int, rng: random.Random) -> None:
        campaign = self._campaign_for(rng, person.service, {PromoCampaignKind.REFERRAL_CLIENT_CLIENT,
                                                                    PromoCampaignKind.REFERRAL_DRIVER_CLIENT})
        if campaign is None:
            return
        if campaign.kind is PromoCampaignKind.REFERRAL_DRIVER_CLIENT:
            referrer, referrer_is_driver = rng.choice(sorted(self.drivers)), True
        else:
            others = [p.id for p in self.people.values() if p.service is person.service and p.id != person.id]
            if not others:
                return
            referrer, referrer_is_driver = rng.choice(others), False
        enrollment = self._enroll(campaign, person.id, referrer, day, referee_is_driver=False,
                                  referrer_is_driver=referrer_is_driver)
        if enrollment is not None:
            person.enrollment = enrollment.id
            self.ledger.add([("service", person.service.value), ("campaign", str(campaign.id))], enrolled=1)

    def _driver_arrivals(self, day: int) -> None:
        if not self.s.referral_enabled:
            return
        options = [c for c in self.campaigns.values()
                   if c.kind is PromoCampaignKind.REFERRAL_DRIVER_DRIVER and self._can_promise(c)]
        if not options:  # no driver->driver campaign that can still promise: referral brings no driver
            return
        rng = self._rng(f"driver-arrive:{day}")
        for _ in range(self._poisson(rng, self.s.drivers.referred_per_day)):
            driver = self._new_driver(rng)
            if rng.random() >= self.s.drivers.enrollment_rate:
                continue
            campaign = rng.choice(options)
            referrer = rng.choice([d for d in sorted(self.drivers) if d != driver.id])
            enrollment = self._enroll(campaign, driver.id, referrer, day, referee_is_driver=True, referrer_is_driver=True)
            if enrollment is not None:
                driver.referee_enrollment = enrollment.id
                self.ledger.add([("campaign", str(campaign.id))], enrolled=1)

    # --- orders ---------------------------------------------------------------------------------------------------

    def _usable(self, owner: int, instrument: PromoInstrument, service: ServiceType, now: datetime) -> list[LotView]:
        return [LotView(lot.id, lot.campaign_id, lot.balance.available_minor, lot.expires_at.timestamp())
                for lot in self.lots.values()
                if lot.owner == owner and lot.instrument is instrument and lot.service is service
                and lot.status == "available" and lot.expires_at > now and lot.balance.available_minor > 0]

    @staticmethod
    def _span(u: float, bounds: tuple[int, int]) -> int:
        low, high = bounds
        return min(high, low + int(u * (high - low + 1)))

    @staticmethod
    def _choose(u: float, weights: list[float]) -> int:
        total, acc = sum(weights), 0.0
        for index, weight in enumerate(weights):
            acc += weight
            if u * total <= acc:
                return index
        return len(weights) - 1

    def _orders(self, day: int, now: datetime) -> None:
        """Every order draws the same 16 numbers in the same order, used or not: the base behaviour of a person is
        identical in a scenario and in its matched control - only what the programme changes can differ."""
        for person in [p for p in self.people.values() if p.next_order_day == day]:
            model = self.s.services[person.service]
            u = [person.rng.random() for _ in range(16)]
            if person.orders + 1 < model.max_orders and u[0] < model.repeat_prob:
                person.next_order_day = day + self._span(u[1], model.repeat_interval_days)
            else:
                person.next_order_day = None
            corridor = self.s.corridors[self._choose(u[2], [c.traffic_share for c in self.s.corridors])]
            if u[3] > corridor.driver_availability:
                person.unserved += 1
                person.attempts.append((day, "unserved"))
                self.ledger.add([("service", person.service.value), ("corridor", corridor.id)], unserved_orders=1)
                continue
            enrollment = self.enrollments.get(person.enrollment) if person.enrollment else None
            if enrollment and enrollment.referrer_is_driver and not enrollment.referee_is_driver and (
                    u[4] < model.referrer_serves_prob):
                driver = self.drivers[enrollment.referrer]
            else:
                ids = sorted(self.drivers)
                driver = self.drivers[ids[min(len(ids) - 1, int(u[5] * len(ids)))]]
            bucket = model.buckets[self._choose(u[6], [b.weight for b in model.buckets])]
            payer = "sender" if person.service is not ServiceType.PARCEL or u[7] < model.sender_pays_share else "receiver"
            allowed = passenger_bonus_allowed(service_type=person.service, bonus_owner_user_id=person.id,
                                              client_user_id=person.id,
                                              parcel_payer=payer if person.service is ServiceType.PARCEL else None)
            uses_bonus = self.s.full_redemption or u[8] < model.bonus_use_prob
            p_lots = self._usable(person.id, PromoInstrument.PASSENGER_BONUS, person.service, now)
            terms = booking_terms(
                fare_minor=bucket.fare_minor, fee_bps=model.fee_bps, p_lots=p_lots,
                h_lots=self._usable(driver.id, PromoInstrument.DRIVER_CREDIT, person.service, now) if driver.capable else [],
                policies=self.policies, combinations=self.combinations, uses_bonus=uses_bonus and allowed, now=now)
            for lot_id, amount in terms.allocations:
                lot = self.lots[lot_id]
                lot.balance = lot.balance.reserve(amount)
            had_bonus = bool(p_lots)
            outcome = ("p_applied" if terms.quote.passenger_bonus_minor else "no_bonus" if not had_bonus
                       else "receiver_pays" if not allowed else "not_chosen" if not uses_bonus else "no_room")
            booking = Booking(id=next(self._ids), service=person.service, corridor=corridor.id, day=day,
                              client=person.id, driver=driver.id, fare_bucket=bucket.label, terms=terms,
                              variable_cost_minor=self.cost_policy.variable_cost_minor(bucket.fare_minor),
                              linked_client=driver.referee_enrollment is not None
                              and u[9] < self.s.drivers.linked_client_prob, key=f"{person.tag}#{person.orders}")
            self.bookings.append(booking)
            self.by_client[booking.client].append(booking)
            self.by_driver[booking.driver].append(booking)
            person.orders += 1
            self.events[f"h_outcome:{terms.h_outcome.value}"] += 1
            if u[10] < model.cancel_prob:
                faults = list(model.cancel_fault)
                fault = PromoFault(faults[self._choose(u[11], [model.cancel_fault[f] for f in faults])])
                booking.status = "cancelled"
                person.attempts.append((day, "cancelled"))
                self._release(booking, fault, now)
                self.ledger.add(self._keys(booking), cancelled=1)
                continue
            person.attempts.append((day, outcome))
            self.ledger.add(self._keys(booking), served=1, fare=bucket.fare_minor,
                            variable_cost=booking.variable_cost_minor, **{f"bucket_{bucket.label}": 1})
            booking.capture_day = day + self._span(u[12], model.capture_delay_days)
            if u[13] < model.dispute_prob:
                booking.dispute_open = True
                booking.capture_day += self._span(u[14], model.review_delay_days)
                booking.fee_released = u[15] < model.dispute_release_prob
            self.captures[booking.capture_day].append(booking)

    def _keys(self, booking: Booking) -> list[tuple[str, str]]:
        return [("service", booking.service.value), ("corridor", booking.corridor), ("total", "all")]

    # --- settlement -------------------------------------------------------------------------------------------------

    def _release(self, booking: Booking, fault: PromoFault, now: datetime) -> None:
        """Reservations back to their lots under fair restoration per holder (the ``_return_to_lot`` rules)."""
        for lot_id, amount in booking.terms.allocations:
            lot = self.lots[lot_id]
            lot.balance = lot.balance.release(amount)
            campaign = self.campaigns[lot.campaign_id]
            if lot.status == "reversed":
                lot.balance, freed = lot.balance.reverse_available()
                if freed:
                    self.budget[lot.campaign_id] = self.budget[lot.campaign_id].release_granted(freed)
                continue
            new_expiry = restored_expiry(lot_expires_at=lot.expires_at, released_at=now, fault=fault,
                                         grace=timedelta(days=campaign.grace_days), instrument=lot.instrument)
            if new_expiry is not None:
                lot.restored_from, lot.restored_until = lot.expires_at, new_expiry
                lot.expires_at, lot.status = new_expiry, "available"
                if fault is PromoFault.UNDETERMINED:
                    self.cancel_reviews[booking.day + 3].append(lot.id)
                    self.events["cancel_fault_reviews"] += 1
            elif now >= lot.expires_at:
                self._expire_free(lot)

    def _expire_free(self, lot: Lot) -> None:
        free = lot.balance.available_minor
        lot.balance, lot.status = lot.balance.expire(), "expired"
        lot.expired_at = lot.expired_at or lot.expires_at
        if free:
            self.budget[lot.campaign_id] = self.budget[lot.campaign_id].release_granted(free)
            self.ledger.add([("campaign", str(lot.campaign_id))], bonus_expired=free)
            self._maybe_reinstate(lot, free)

    def _maybe_reinstate(self, lot: Lot, amount: int) -> None:
        if self.s.reinstate_prob <= 0 or self._rng(f"reinstate:{lot.id}:{lot.balance.expired_minor}").random() >= self.s.reinstate_prob:
            return
        try:
            self.budget[lot.campaign_id] = self.budget[lot.campaign_id].reinstate(amount)
        except DomainError:
            self.reinstate_unfulfilled[lot.campaign_id] += amount  # never partial (Q122): stays escalated
            return
        lot.balance = lot.balance.reinstate_expired(amount)
        lot.status = "available"
        lot.expires_at = lot.expires_at + timedelta(days=self.campaigns[lot.campaign_id].grace_days)
        self.reinstated[lot.campaign_id] += amount
        self._track_budget(lot.campaign_id)

    def _settle(self, day: int, now: datetime) -> None:
        for booking in self.captures.pop(day, []):
            booking.dispute_open = False
            if booking.fee_released:
                self._release(booking, PromoFault.UNDETERMINED, now)  # a finance release names no cause (Q129)
                self.ledger.add(self._keys(booking), fee_released=1)
                continue
            q = booking.terms.quote
            for lot_id, amount in booking.terms.allocations:
                lot = self.lots[lot_id]
                lot.balance = lot.balance.consume(amount)
                lot.bookings_used += 1
                lot.first_spend_at = lot.first_spend_at or now
                lot.spends.append((now, amount))
                self.budget[lot.campaign_id] = self.budget[lot.campaign_id].consume(amount)
                self.ledger.add([("campaign", str(lot.campaign_id))], consumed=amount,
                                consumed_fraud=amount if lot.fraud else 0)
            booking.captured = True
            client = self.people[booking.client]
            client.captured_bookings += 1
            client.activated_day = booking.day if client.activated_day is None else min(client.activated_day, booking.day)
            self.ledger.add(self._keys(booking), captured=1, commission_gross=q.base_commission_minor,
                            passenger_bonus=q.passenger_bonus_minor, driver_credit=q.driver_credit_minor,
                            net_commission=q.net_commission_minor, cash_to_driver=q.cash_due_minor,
                            discounted=int(q.passenger_bonus_minor > 0),
                            negative_margin=int(q.net_commission_minor - booking.variable_cost_minor < 0))
            model = self.s.services[booking.service]
            rng = self._rng(f"reversal:{booking.key}")
            if rng.random() < model.reversal_prob:
                self.reversals[day + rng.randint(1, 10)].append(booking)
        for booking in self.reversals.pop(day, []):
            model = self.s.services[booking.service]
            amount = booking.terms.quote.net_commission_minor * model.reversal_share_bps // 10_000
            if amount > 0:
                booking.reversed_minor += amount  # real money back to the driver; the bonus is not restored (Q127)
                self.ledger.add(self._keys(booking), commission_reversed=amount,
                                uncovered_reviews=int(booking.terms.quote.promo_applied))

    def _decide_cancel_reviews(self, day: int, now: datetime) -> None:
        for lot_id in self.cancel_reviews.pop(day, []):
            lot = self.lots[lot_id]
            model = self.s.services[lot.service]
            if self._rng(f"cancel-review:{lot_id}:{day}").random() >= model.review_reject_prob:
                continue
            # the holder's own cause after all: only the unspent extension goes (``withdraw_restoration``)
            if lot.status == "available" and lot.restored_until is not None and lot.expires_at == lot.restored_until:
                lot.expires_at = max(now, lot.restored_from)
                if lot.expires_at <= now:
                    self._expire_free(lot)

    def _expire_lots(self, day: int, now: datetime) -> None:
        for lot in self.lots.values():
            if lot.status == "available" and lot.expires_at <= now and not self.s.full_redemption:
                self._expire_free(lot)

    # --- qualification and grant ----------------------------------------------------------------------------------

    def _facts(self, booking: Booking) -> QualificationFacts:
        done = self._now(booking.day)
        captured = self._now(booking.capture_day) if booking.captured else None
        return QualificationFacts(
            booking_id=booking.id, trip_id=booking.day * 100_000 + booking.driver, service_type=booking.service,
            client_user_id=booking.client, driver_user_id=booking.driver, service_completed_at=done,
            cash_confirmed_at=done, commission_captured_at=captured,
            net_commission_captured_minor=booking.terms.quote.net_commission_minor - booking.reversed_minor
            if booking.captured else 0,
            open_dispute=booking.dispute_open, cancelled_or_refunded=booking.status != "served" or booking.fee_released)

    def _qualify(self, day: int, now: datetime) -> None:
        for enrollment in self.enrollments.values():
            if enrollment.status != "promised":
                continue
            if enrollment.referee_is_driver:
                self._driver_milestones(enrollment, now)
            else:
                self._client_qualification(enrollment, day, now)
            if enrollment.status == "promised" and now > enrollment.deadline and not self._waiting(enrollment, now):
                self._release_promise(enrollment, "released")

    def _waiting(self, enrollment: Enrollment, now: datetime) -> bool:
        """Q120: a service done in time whose capture or review is still pending keeps the reserve."""
        if enrollment.review_until_day is not None:
            return True
        return any(b.status == "served" and not b.captured and not b.fee_released
                   and service_in_time(self._now(b.day), enrollment.deadline) for b in self.by_client[enrollment.referee])

    def _client_qualification(self, enrollment: Enrollment, day: int, now: datetime) -> None:
        if enrollment.review_until_day is not None:
            if day < enrollment.review_until_day:
                return
            enrollment.review_until_day = None
            if enrollment.review_reject:
                self._release_promise(enrollment, "rejected")
                return
            self._grant(enrollment, 0, now)
            return
        required = REQUIRED_QUALIFYING_SERVICES[enrollment.campaign.service]
        qualifying = 0
        for booking in self.by_client[enrollment.referee]:
            if not service_in_time(self._now(booking.day), enrollment.deadline):
                continue
            result = evaluate_qualification(self._facts(booking), now=now,
                                            referrer_user_id=enrollment.referrer if enrollment.referrer_is_driver else None)
            if result.verdict is QualificationVerdict.QUALIFIED:
                qualifying += 1
        if qualifying < required:
            return
        model = self.s.services[enrollment.campaign.service]
        rng = self._rng(f"review:{enrollment.id}")
        if rng.random() < model.review_prob:
            low, high = model.review_delay_days
            wait = rng.randint(low, high)
            enrollment.review_until_day, enrollment.review_wait_days = day + wait, wait
            enrollment.review_reject = rng.random() < model.review_reject_prob
            self.events["qualification_reviews"] += 1
            return
        self._grant(enrollment, 0, now)

    def _driver_milestones(self, enrollment: Enrollment, now: datetime) -> None:
        evidence = []
        for booking in (b for b in self.by_driver[enrollment.referee] if b.captured):
            result = evaluate_qualification(self._facts(booking), now=now, referrer_user_id=enrollment.referrer)
            evidence.append(MilestoneEvidence(trip_id=self._facts(booking).trip_id, booking_id=booking.id,
                                              client_user_id=booking.client,
                                              qualified=result.verdict is QualificationVerdict.QUALIFIED
                                              and service_in_time(self._now(booking.day), enrollment.deadline),
                                              client_linked_to_referral=booking.linked_client))
        reached = milestones_reached(milestone_progress(evidence), enrollment.campaign.milestones,
                                     min_distinct_clients=enrollment.campaign.min_distinct_clients or 0)
        for milestone in reached:
            if milestone not in enrollment.granted_milestones:
                self._grant(enrollment, milestone, now)
        if set(enrollment.campaign.milestones) <= enrollment.granted_milestones:
            enrollment.status = "granted"

    def _grant(self, enrollment: Enrollment, milestone: int, now: datetime) -> None:
        campaign = enrollment.campaign
        for side, instrument, amount, step in enrollment_rewards(enrollment.terms):
            if step != milestone:
                continue
            self.budget[campaign.id] = self.budget[campaign.id].grant(amount, amount)  # one obligation, next stage
            enrollment.promised_left -= amount
            owner = enrollment.referee if side == "referee" else enrollment.referrer
            lot = Lot(id=next(self._ids), owner=owner, instrument=instrument, service=campaign.service,
                      campaign_id=campaign.id, enrollment_id=enrollment.id, balance=LotBalance(amount_minor=amount),
                      expires_at=now + timedelta(days=10**4 if self.s.full_redemption else campaign.validity_days),
                      granted_at=now, available_from=now)  # the sim reviews before the grant: spendable at once
            self.lots[lot.id] = lot
            self.ledger.add([("campaign", str(campaign.id))], granted=amount, **{f"granted_{side}": amount})
            model = self.s.services[campaign.service]
            rng = self._rng(f"fraud:{lot.id}")
            if rng.random() < model.post_grant_fraud_prob:
                self.fraud_checks[int((now - T0).days) + rng.randint(3, 10)].append(lot.id)
        enrollment.granted_milestones.add(milestone)
        if not campaign.milestones:
            enrollment.status = "granted"
            self.ledger.add([("campaign", str(campaign.id))], qualified=1, review_wait_days=enrollment.review_wait_days)

    def _release_promise(self, enrollment: Enrollment, status: str) -> None:
        if enrollment.promised_left > 0:
            self.budget[enrollment.campaign.id] = self.budget[enrollment.campaign.id].release_promise(enrollment.promised_left)
            enrollment.promised_left = 0
        enrollment.status = status
        self.ledger.add([("campaign", str(enrollment.campaign.id))], **{f"enrollments_{status}": 1})

    def _fraud(self, day: int, now: datetime) -> None:
        for lot_id in self.fraud_checks.pop(day, []):
            lot = self.lots[lot_id]
            if lot.status == "reversed":
                continue
            lot.fraud = True  # spent before this = risk cost (never a debt, never back to the budget)
            lot.balance, freed = lot.balance.reverse_available()
            lot.status = "reversed"
            if freed:
                self.budget[lot.campaign_id] = self.budget[lot.campaign_id].release_granted(freed)
            self.ledger.add([("campaign", str(lot.campaign_id))], fraud_reversed_unspent=freed,
                            fraud_loss=lot.balance.consumed_minor)

    # --- snapshot ----------------------------------------------------------------------------------------------------

    def _snapshot(self, day: int, now: datetime) -> dict[str, Any]:
        for cid in self.budget:
            self._track_budget(cid)
        budgets = {}
        for cid, pos in self.budget.items():
            lots = [lot for lot in self.lots.values() if lot.campaign_id == cid]
            budgets[str(cid)] = {
                "service": self.campaigns[cid].service.value, "family": FAMILY[self.campaigns[cid].kind],
                "kind": self.campaigns[cid].kind.value, "source": self.campaigns[cid].budget_source,
                "allocated": pos.allocated_minor, "promised": pos.promised_minor, "granted_unspent": pos.granted_minor,
                "consumed": pos.consumed_minor, "released": pos.released_minor, "shortfall": pos.shortfall_minor,
                "peak_committed": self.peak_committed[cid], "budget_blocked_enrollments": self.budget_blocked[cid],
                "allocated_initial": self.campaigns[cid].budget_minor, "committed": pos.committed_minor,
                "funded_committed": pos.committed_minor - pos.shortfall_minor,
                "peak_shortfall": self.peak_shortfall[cid], "peak_utilization_bps": self.peak_utilization_bps[cid],
                "shortfall_since_day": self.shortfall_since_day.get(cid),
                "reducible": pos.reducible_minor(self.reinstate_unfulfilled[cid]),
                "reduce_applied": self.budget_changes[cid]["reduce_applied"],
                "reduce_refused": self.budget_changes[cid]["reduce_refused"],
                "funding_loss": self.budget_changes[cid]["funding_loss"],
                "reinstated": self.reinstated[cid], "reinstate_unfulfilled": self.reinstate_unfulfilled[cid],
                "reserved_on_bookings": sum(lot.balance.reserved_minor for lot in lots),
                "restored_by_grace_available": sum(lot.balance.available_minor for lot in lots
                                                   if lot.restored_until and lot.status == "available"),
            }
        users: dict[str, dict[str, Any]] = {}
        for service in self.s.services:
            people = [p for p in self.people.values() if p.service is service]
            referees = {e.referee for e in self.enrollments.values() if not e.referee_is_driver and e.campaign.service is service}
            ref_lots = [lot for lot in self.lots.values() if lot.service is service and lot.instrument is PromoInstrument.PASSENGER_BONUS]
            spent_lots = [lot for lot in ref_lots if lot.balance.consumed_minor > 0]
            waits = [(lot.first_spend_at - lot.granted_at).days for lot in spent_lots if lot.first_spend_at]
            discounted = [b for b in self.bookings if b.service is service and b.captured and b.terms.quote.passenger_bonus_minor > 0]
            users[service.value] = {
                "arrived": len(people), "arrived_incremental": sum(p.incremental for p in people),
                "attributed": sum(p.attributed for p in people), "enrolled_referees": len(referees),
                "activated": sum(p.captured_bookings > 0 for p in people),
                "activated_incremental": sum(p.captured_bookings > 0 and p.incremental for p in people),
                "activated_referees": sum(self.people[r].captured_bookings > 0 for r in referees if r in self.people),
                "referees_with_unserved_orders": sum(self.people[r].unserved > 0 for r in referees if r in self.people),
                "bonus_lots_granted": len(ref_lots), "bonus_lots_spent_any": len(spent_lots),
                "bonus_granted_minor": sum(lot.balance.amount_minor for lot in ref_lots),
                "bonus_spent_minor": sum(lot.balance.consumed_minor for lot in ref_lots),
                "bonus_expired_minor": sum(lot.balance.expired_minor for lot in ref_lots),
                "bonus_unspent_open_minor": sum(lot.balance.available_minor + lot.balance.reserved_minor
                                                for lot in ref_lots if lot.status == "available"),
                "avg_days_grant_to_first_spend": round(sum(waits) / len(waits), 1) if waits else None,
                "avg_bookings_to_spend_lot": round(sum(lot.bookings_used for lot in spent_lots) / len(spent_lots), 2)
                if spent_lots else None,
                "avg_discount_minor": sum(b.terms.quote.passenger_bonus_minor for b in discounted) // len(discounted)
                if discounted else None,
            }
        enroll = [e for e in self.enrollments.values()]
        reviews = [e.review_wait_days for e in enroll if e.review_wait_days]
        cohorts = cohort_metrics(self, day, now)
        bonus_use = {service.value: bonus_use_analysis(self, service, day, now) for service in self.s.services}
        return {
            "day": day, "money": self.ledger.snapshot(), "budgets": budgets, "users": users,
            "not_activated": {str(k): v for k, v in self.not_activated.items()},
            "events": dict(self.events),
            "avg_review_wait_days": round(sum(reviews) / len(reviews), 1) if reviews else None,
            "cohorts": cohorts, "bonus_use": bonus_use,
            "enrollments": {status: sum(e.status == status for e in enroll)
                            for status in ("promised", "granted", "released", "rejected")},
        }


# --- A6.2: cohort metrics with explicit anchors and maturity ------------------------------------------------------------

NOT_YET = "hali_baholab_bolmaydi"  # too few matured observations: never shown as 0


def _metric(*, metric: str, anchor: str, service: ServiceType, group: str, as_of_day: int, window_days: int | None,
            denominator: str, matured: int, immature: int, numerator: int | None, minimum: int,
            value_minor: int | None = None) -> dict[str, Any]:
    ok = matured >= minimum and matured > 0
    return {"metric": metric, "anchor": anchor, "service": service.value, "group": group, "as_of_day": as_of_day,
            "window_days": window_days, "denominator": denominator, "matured": matured, "immature": immature,
            "numerator": numerator if ok else None,
            "value_bps": (numerator * 10_000 // matured) if ok and numerator is not None and value_minor is None else None,
            "value_minor": value_minor if ok else None, "status": "ok" if ok else NOT_YET, "minimum": minimum}


def cohort_metrics(sim: Simulation, as_of_day: int, now: datetime) -> list[dict[str, Any]]:
    """Every metric names its anchor and counts only observations whose whole window has passed.

    * ``qualification_rate`` - anchor **enrollment**: granted / enrollments older than qualification window + the
      longest capture/review tail; enrollments younger than that are *immature* (not failures).
    * ``retention_d30`` / ``retention_d60`` - anchor **activation** (service day of the first captured booking):
      another served order within N days. Activated less than N days ago = immature, never "did not return".
    * ``margin_d60`` - anchor **activation**: C_net kept - O of the person's captured bookings in 60 days, average per
      matured activated person (minor units). Immature people are not "zero revenue".
    * ``bonus_first_spend_d30`` / ``bonus_value_spent_d30`` - anchor **grant** (the lot's ``available_from``): a lot
      spendable for fewer than 30 days is immature, never "unused".
    Too few matured observations -> ``hali_baholab_bolmaydi`` (no value), never 0.
    """
    minimum = sim.s.min_matured_observations
    last = as_of_day - 1  # the snapshot closes day ``as_of_day - 1``: nothing later is observed
    rows: list[dict[str, Any]] = []
    for service, model in sim.s.services.items():
        people = [p for p in sim.people.values() if p.service is service]
        referee_ids = {e.referee for e in sim.enrollments.values() if not e.referee_is_driver and e.campaign.service is service}
        groups = {"referee": [p for p in people if p.id in referee_ids],
                  "organic": [p for p in people if not p.attributed], "all": people}
        # qualification (anchor: enrollment)
        client_enrollments = [e for e in sim.enrollments.values() if not e.referee_is_driver and e.campaign.service is service]
        if client_enrollments:
            tail = model.capture_delay_days[1] + model.review_delay_days[1] * 2 + 2  # capture + dispute + review + 48 h
            window = max(e.campaign.qualification_days for e in client_enrollments) + tail
            matured = [e for e in client_enrollments if e.enrolled_day + e.campaign.qualification_days + tail <= last]
            rows.append(_metric(metric="qualification_rate", anchor="enrollment", service=service, group="referee",
                                as_of_day=as_of_day, window_days=window,
                                denominator="enrollments whose qualification window + capture/review tail has passed",
                                matured=len(matured), immature=len(client_enrollments) - len(matured),
                                numerator=sum(e.status == "granted" for e in matured), minimum=minimum))
        for n in (30, 60):
            for group, members in groups.items():
                active = [p for p in members if p.activated_day is not None]
                matured = [p for p in active if p.activated_day + n <= last]
                returned = sum(any(outcome not in ("unserved", "cancelled") and p.activated_day < day <= p.activated_day + n
                                   for day, outcome in p.attempts) for p in matured)
                rows.append(_metric(metric=f"retention_d{n}", anchor="activation", service=service, group=group,
                                    as_of_day=as_of_day, window_days=n,
                                    denominator=f"people activated at least {n} days before the as-of day",
                                    matured=len(matured), immature=len(active) - len(matured), numerator=returned,
                                    minimum=minimum))
        for group, members in groups.items():
            active = [p for p in members if p.activated_day is not None]
            matured = [p for p in active if p.activated_day + 60 <= last]
            total = 0
            for p in matured:
                for b in sim.by_client[p.id]:
                    if b.captured and b.day <= p.activated_day + 60:
                        total += b.terms.quote.net_commission_minor - b.reversed_minor - b.variable_cost_minor
            rows.append(_metric(metric="margin_d60", anchor="activation", service=service, group=group,
                                as_of_day=as_of_day, window_days=60,
                                denominator="people activated at least 60 days before the as-of day",
                                matured=len(matured), immature=len(active) - len(matured), numerator=None,
                                minimum=minimum, value_minor=(total // len(matured)) if matured else None))
        lots = [lot for lot in sim.lots.values() if lot.service is service and lot.instrument is PromoInstrument.PASSENGER_BONUS]
        window = sim.s.lot_maturity_days
        matured = [lot for lot in lots if (now - lot.available_from).days >= window]
        spent = sum(any(at <= lot.available_from + timedelta(days=window) for at, _ in lot.spends) for lot in matured)
        rows.append(_metric(metric=f"bonus_first_spend_d{window}", anchor="grant", service=service, group="bonus_lots",
                            as_of_day=as_of_day, window_days=window,
                            denominator=f"passenger-bonus lots spendable for at least {window} days",
                            matured=len(matured), immature=len(lots) - len(matured), numerator=spent, minimum=minimum))
        granted = sum(lot.balance.amount_minor for lot in matured)
        used = sum(amount for lot in matured for at, amount in lot.spends if at <= lot.available_from + timedelta(days=window))
        row = _metric(metric=f"bonus_value_spent_d{window}", anchor="grant", service=service, group="bonus_value",
                      as_of_day=as_of_day, window_days=window,
                      denominator=f"granted value of lots spendable for at least {window} days (minor units)",
                      matured=len(matured), immature=len(lots) - len(matured), numerator=used, minimum=minimum)
        if row["status"] == "ok":
            row["value_bps"] = used * 10_000 // granted if granted else None
            row["denominator_minor"] = granted
        rows.append(row)
    return rows


# --- why a passenger bonus was not used (per lot; users and value shown separately) --------------------------------

UNUSED_REASONS = ("not_matured", "reserved_awaiting_capture", "client_did_not_return", "no_driver_found",
                  "no_room_in_commission", "receiver_pays", "client_did_not_choose", "order_cancelled", "reversed_fraud")


def _why_unused(sim: Simulation, lot: Lot, now: datetime) -> str:
    if lot.status == "reversed":
        return "reversed_fraud"
    if lot.balance.reserved_minor:
        return "reserved_awaiting_capture"
    end = min(now, lot.expired_at or lot.expires_at)
    if lot.status == "available" and (now - lot.available_from).days < sim.s.lot_maturity_days:
        return "not_matured"
    start_day, end_day = (lot.available_from - T0).days, (end - T0).days
    seen = {outcome for day, outcome in sim.people[lot.owner].attempts if start_day <= day <= end_day} \
        if lot.owner in sim.people else set()
    for outcome, reason in (("no_room", "no_room_in_commission"), ("receiver_pays", "receiver_pays"),
                            ("not_chosen", "client_did_not_choose"), ("cancelled", "order_cancelled"),
                            ("unserved", "no_driver_found")):
        if outcome in seen:
            return reason
    return "client_did_not_return"


def bonus_use_analysis(sim: Simulation, service: ServiceType, as_of_day: int, now: datetime) -> dict[str, Any]:
    """Lots, holders and value kept apart; unused lots get one reason (the closest the holder came to using it)."""
    lots = [lot for lot in sim.lots.values() if lot.service is service and lot.instrument is PromoInstrument.PASSENGER_BONUS]
    matured = [lot for lot in lots if lot.status != "available" or (now - lot.available_from).days >= sim.s.lot_maturity_days]
    reasons = dict.fromkeys(UNUSED_REASONS, 0)
    reasons_expired = dict.fromkeys(UNUSED_REASONS, 0)
    for lot in lots:
        if lot.balance.consumed_minor:
            continue
        reason = _why_unused(sim, lot, now)
        reasons[reason] += 1
        if lot.status == "expired":
            reasons_expired[reason] += 1
    holders = {lot.owner for lot in matured}
    holders_used = {lot.owner for lot in matured if lot.balance.consumed_minor}
    in_review = [e for e in sim.enrollments.values()
                 if e.campaign.service is service and not e.referee_is_driver and e.review_until_day is not None]
    return {
        "as_of_day": as_of_day, "maturity_days": sim.s.lot_maturity_days,
        "lots_granted": len(lots), "lots_matured": len(matured), "lots_immature": len(lots) - len(matured),
        "lots_spent_any_matured": sum(lot.balance.consumed_minor > 0 for lot in matured),
        "lots_spent_full_matured": sum(lot.balance.consumed_minor == lot.balance.amount_minor for lot in matured),
        "holders_matured": len(holders), "holders_used_any": len(holders_used),
        "value_granted_matured_minor": sum(lot.balance.amount_minor for lot in matured),
        "value_spent_matured_minor": sum(lot.balance.consumed_minor for lot in matured),
        "value_expired_minor": sum(lot.balance.expired_minor for lot in lots),
        "value_open_minor": sum(lot.balance.available_minor + lot.balance.reserved_minor for lot in lots
                                if lot.status == "available"),
        "unused_reason_lots": reasons, "unused_reason_lots_expired": reasons_expired,
        "enrollments_in_review": len(in_review),
        "enrollments_in_review_promised_minor": sum(e.promised_left for e in in_review),
        "bookings_per_spent_lot": round(sum(lot.bookings_used for lot in matured if lot.balance.consumed_minor)
                                        / max(1, sum(lot.balance.consumed_minor > 0 for lot in matured)), 2),
    }


def run_scenario(scenario: Scenario) -> dict[str, Any]:
    return Simulation(scenario).run()
