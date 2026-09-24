"""Scenario inputs for the referral simulator. Every value is an *assumption* unless a file says otherwise.

A scenario is read from JSON (``docs/referral/simulation/scenarios.json``). Nothing here is a production value: a
file must say ``"synthetic": true`` until real data replaces an input, and the report prints that label on every
result. Loading never fills an absent value with zero - a missing key is an error, and an unknown cost is ``null``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.contracts.enums import PromoCampaignKind, PromoInstrument, ServiceType
from app.contracts.promo import PromoMarginPolicy


@dataclass(frozen=True)
class PriceBucket:
    label: str  # low | mid | high
    fare_minor: int
    weight: float


@dataclass(frozen=True)
class ServiceModel:
    service: ServiceType
    fee_bps: int  # the commission policy rate (synthetic)
    buckets: tuple[PriceBucket, ...]
    base_new_per_day: float  # people who would come anyway (no referral needed)
    attributed_share_of_base: float  # of those, how many arrive holding a code (attribution is not causation)
    incremental_new_per_day: float  # ASSUMPTION: people who come *because of* referral (0 in the control)
    enrollment_rate: float  # attributed people who join a campaign
    first_order_prob: float
    first_order_delay_days: tuple[int, int]
    repeat_prob: float
    repeat_interval_days: tuple[int, int]
    max_orders: int
    cancel_prob: float  # before service
    cancel_fault: dict[str, float]  # client | driver | platform | none | undetermined -> weight
    dispute_prob: float
    dispute_release_prob: float  # a dispute ends with the fee released (no capture)
    reversal_prob: float  # a captured commission is later partly reversed
    reversal_share_bps: int
    capture_delay_days: tuple[int, int]  # completion -> capture (finance review, Q74)
    review_prob: float  # a qualification goes to a person
    review_delay_days: tuple[int, int]
    review_reject_prob: float
    post_grant_fraud_prob: float  # a granted reward later reversed as fraud (unspent part back, spent part = risk cost)
    referrer_serves_prob: float  # driver->client campaigns: the referring driver serves the referee (does not count)
    bonus_use_prob: float  # the client ticks "use my bonus" when one is shown
    sender_pays_share: float = 1.0  # parcel: receiver-pays parcels never use the sender's bonus (Q104)


@dataclass(frozen=True)
class CorridorModel:
    id: str
    traffic_share: float
    driver_availability: float  # probability an order finds a suitable driver at all


@dataclass(frozen=True)
class CampaignModel:
    id: int
    kind: PromoCampaignKind
    service: ServiceType
    referrer_reward_minor: int
    referee_reward_minor: int
    referrer_instrument: PromoInstrument
    referee_instrument: PromoInstrument
    milestones: tuple[int, ...]
    min_distinct_clients: int | None
    qualification_days: int
    validity_days: int
    grace_days: int
    review_sla_hours: int
    policy: PromoMarginPolicy
    budget_minor: int
    budget_source: str  # where the allocation comes from - an explicit parameter, never future revenue
    invite_share: float  # share of this service's attributed people routed to this campaign


@dataclass(frozen=True)
class DriverModel:
    pool_size: int
    referred_per_day: float  # new drivers arriving with a driver's code
    enrollment_rate: float
    linked_client_prob: float  # a client of a referee driver is linked to the referral (never counts)
    capable_app_share: float  # drivers whose app renders H and C_net (Q124/Q126)


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    synthetic: bool
    seed: int
    days: int
    snapshots: tuple[int, ...]
    referral_enabled: bool
    variable_cost_fixed_minor: int  # per served booking - the same meaning as O's fixed part
    variable_cost_bps: int
    fixed_costs_per_30_days_minor: int | None  # None = unknown: no business result is computed, never "0"
    extra_marketing_minor: int  # non-incentive marketing spend of the programme (explicit)
    corridors: tuple[CorridorModel, ...]
    services: dict[ServiceType, ServiceModel]
    campaigns: tuple[CampaignModel, ...]
    combinations: tuple[tuple[int, int, str], ...]
    drivers: DriverModel
    full_redemption: bool = False  # stress: every shown bonus is used and nothing expires unused
    reinstate_prob: float = 0.0  # an expired release that an admin reinstates (Q122)
    experiment: str | None = None  # a comparison that departs from an approved rule - never the base model
    pilot_variant: bool = False  # offered for review (with sensitivity runs), never a production tariff
    # campaign -> {day, amount_minor, kind}: kind ``reduce`` (capped at B - S - L, G14) or ``funding_loss``
    budget_cuts: dict[int, dict[str, Any]] = field(default_factory=dict)
    min_matured_observations: int = 1  # cohort metric shown only with at least this many matured observations
    lot_maturity_days: int = 30  # a bonus lot is judged "unused" only after this many spendable days
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def fingerprint(self) -> str:
        name, _, control = self.name.partition("~")  # "~control": the same scenario with referral switched off
        base, _, derived = name.partition("+")  # a sensitivity run: the base scenario plus its perturbation
        raw = {"scenario": _raw_cache.get(base), "perturbation": derived or None, "matched": control or None,
               "seed": self.seed, "days": self.days}
        return hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:16]


_raw_cache: dict[str, Any] = {}


def _pair(value: list[int]) -> tuple[int, int]:
    low, high = value
    if low > high:
        raise ValueError(f"range {value} is inverted")
    return int(low), int(high)


def _policy(raw: dict[str, Any]) -> PromoMarginPolicy:
    return PromoMarginPolicy(**{key: raw[key] for key in (
        "max_discount_share_bps", "max_discount_per_booking_minor", "passenger_bonus_max_per_booking_minor",
        "driver_credit_max_per_booking_minor", "variable_cost_fixed_minor", "variable_cost_bps", "min_margin_minor")})


def _service(name: str, raw: dict[str, Any]) -> ServiceModel:
    return ServiceModel(
        service=ServiceType(name), fee_bps=raw["fee_bps"],
        buckets=tuple(PriceBucket(b["label"], b["fare_minor"], b["weight"]) for b in raw["price_buckets"]),
        base_new_per_day=raw["base_new_per_day"], attributed_share_of_base=raw["attributed_share_of_base"],
        incremental_new_per_day=raw["incremental_new_per_day"], enrollment_rate=raw["enrollment_rate"],
        first_order_prob=raw["first_order_prob"], first_order_delay_days=_pair(raw["first_order_delay_days"]),
        repeat_prob=raw["repeat_prob"], repeat_interval_days=_pair(raw["repeat_interval_days"]),
        max_orders=raw["max_orders"], cancel_prob=raw["cancel_prob"], cancel_fault=dict(raw["cancel_fault"]),
        dispute_prob=raw["dispute_prob"], dispute_release_prob=raw["dispute_release_prob"],
        reversal_prob=raw["reversal_prob"], reversal_share_bps=raw["reversal_share_bps"],
        capture_delay_days=_pair(raw["capture_delay_days"]), review_prob=raw["review_prob"],
        review_delay_days=_pair(raw["review_delay_days"]), review_reject_prob=raw["review_reject_prob"],
        post_grant_fraud_prob=raw["post_grant_fraud_prob"], referrer_serves_prob=raw["referrer_serves_prob"],
        bonus_use_prob=raw["bonus_use_prob"], sender_pays_share=raw.get("sender_pays_share", 1.0),
    )


def scenario_from_dict(raw: dict[str, Any], defaults: dict[str, Any] | None = None) -> Scenario:
    """``defaults`` (the file's shared block) is deep-merged under the scenario; the scenario wins."""
    merged = _merge(defaults or {}, raw)
    campaigns = [dict(c) for c in merged.get("campaigns", ())]
    if "campaign_ids" in merged:  # a scenario picks some of the shared campaigns ...
        campaigns = [c for c in campaigns if c["id"] in set(merged["campaign_ids"])]
    overrides = merged.get("campaign_overrides", {})  # ... and changes some of their values
    merged["campaigns"] = [_merge(c, overrides.get(str(c["id"]), {})) for c in campaigns]
    _raw_cache[merged["name"]] = merged
    return Scenario(
        name=merged["name"], title=merged["title"], synthetic=bool(merged["synthetic"]), seed=int(merged["seed"]),
        days=int(merged["days"]), snapshots=tuple(merged["snapshots"]), referral_enabled=bool(merged["referral_enabled"]),
        variable_cost_fixed_minor=merged["variable_cost"]["fixed_minor"],
        variable_cost_bps=merged["variable_cost"]["bps"],
        fixed_costs_per_30_days_minor=merged["fixed_costs_per_30_days_minor"],
        extra_marketing_minor=merged["extra_marketing_minor"],
        corridors=tuple(CorridorModel(c["id"], c["traffic_share"], c["driver_availability"]) for c in merged["corridors"]),
        services={ServiceType(k): _service(k, v) for k, v in merged["services"].items()},
        campaigns=tuple(CampaignModel(
            id=c["id"], kind=PromoCampaignKind(c["kind"]), service=ServiceType(c["service"]),
            referrer_reward_minor=c["referrer_reward_minor"], referee_reward_minor=c["referee_reward_minor"],
            referrer_instrument=PromoInstrument(c["referrer_instrument"]),
            referee_instrument=PromoInstrument(c["referee_instrument"]), milestones=tuple(c.get("milestones", ())),
            min_distinct_clients=c.get("min_distinct_clients"), qualification_days=c["qualification_days"],
            validity_days=c["validity_days"], grace_days=c["grace_days"], review_sla_hours=c["review_sla_hours"],
            policy=_policy(c["policy"]), budget_minor=c["budget_minor"], budget_source=c["budget_source"],
            invite_share=c["invite_share"]) for c in merged.get("campaigns", ()) if merged["referral_enabled"]),
        combinations=tuple((a, b, basis) for a, b, basis in merged.get("combinations", ())),
        drivers=DriverModel(**merged["drivers"]), full_redemption=bool(merged.get("full_redemption", False)),
        reinstate_prob=float(merged.get("reinstate_prob", 0.0)), experiment=merged.get("experiment"),
        pilot_variant=bool(merged.get("pilot_variant", False)),
        budget_cuts={int(k): _budget_cut(v) for k, v in merged.get("budget_cuts", {}).items()},
        min_matured_observations=int(merged["cohort"]["min_matured_observations"]),
        lot_maturity_days=int(merged["cohort"]["lot_maturity_days"]),
        notes=tuple(merged.get("notes", ())),
    )


def _budget_cut(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw.get("kind", "reduce")
    if kind not in ("reduce", "funding_loss"):
        raise ValueError(f"budget cut kind {kind!r}: reduce | funding_loss")
    return {"day": int(raw["day"]), "amount_minor": int(raw["amount_minor"]), "kind": kind}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return out


def load_scenarios(path: str | Path) -> tuple[list[Scenario], dict[str, Any]]:
    """All scenarios of a file (in file order) and the file's raw content (for the report)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    return [scenario_from_dict(item, defaults) for item in raw["scenarios"]], raw
