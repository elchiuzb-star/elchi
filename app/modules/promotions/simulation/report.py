"""Turns simulation runs into numbers people can read - and checks the accounting while doing it.

Money lines (per scope):
* ``net_commission_kept = C_net captured - commission reversed`` - what the platform keeps from real balances;
* ``check_from_c = C - P - H - reversed`` must equal it (the incentive is inside C - C_net, never subtracted twice);
* ``operational_margin = net_commission_kept - O`` (O = variable cost of every served booking, one line);
* ``business_result = operational_margin - extra marketing - fixed costs`` only when fixed costs are known;
  unknown fixed costs make the business result "unknown", never a number computed with zero.
The client's cash to the driver (F_cash) and the fare (F) are shown as volumes, never as platform revenue; driver
top-ups do not appear at all (they are prepaid money, not earned commission).
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from .config import Scenario

TOTAL = "total:all"


def money(snapshot: dict[str, Any], scope: str = TOTAL) -> dict[str, int]:
    return snapshot["money"].get(scope, {})


def lines(snapshot: dict[str, Any], scenario: Scenario, scope: str = TOTAL) -> dict[str, Any]:
    m = money(snapshot, scope)
    get = lambda key: m.get(key, 0)
    kept = get("net_commission") - get("commission_reversed")
    from_c = get("commission_gross") - get("passenger_bonus") - get("driver_credit") - get("commission_reversed")
    op_margin = kept - get("variable_cost")
    days = snapshot["day"]
    fixed = None if scenario.fixed_costs_per_30_days_minor is None else scenario.fixed_costs_per_30_days_minor * days // 30
    business = None if fixed is None else op_margin - scenario.extra_marketing_minor - fixed
    return {
        "served": get("served"), "cancelled": get("cancelled"), "unserved_orders": get("unserved_orders"),
        "captured": get("captured"), "fee_released": get("fee_released"),
        "fare_volume": get("fare"), "cash_client_to_driver": get("cash_to_driver"),
        "commission_gross": get("commission_gross"), "passenger_bonus": get("passenger_bonus"),
        "driver_credit": get("driver_credit"), "net_commission_captured": get("net_commission"),
        "commission_reversed": get("commission_reversed"), "net_commission_kept": kept,
        "check_from_c": from_c, "variable_cost": get("variable_cost"), "operational_margin": op_margin,
        "negative_margin_bookings": get("negative_margin"), "discounted_bookings": get("discounted"),
        "uncovered_reviews": get("uncovered_reviews"),
        "extra_marketing": scenario.extra_marketing_minor, "fixed_costs": fixed, "business_result": business,
        "buckets": {k.removeprefix("bucket_"): v for k, v in m.items() if k.startswith("bucket_")},
    }


def programme(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Incentive and budget across campaigns: consumed once, outstanding liability, peak commitment."""
    budgets = snapshot["budgets"]
    consumed = sum(b["consumed"] for b in budgets.values())
    liability = sum(b["promised"] + b["granted_unspent"] for b in budgets.values())
    allocated = sum(b["allocated"] for b in budgets.values())
    peak = sum(b["peak_committed"] for b in budgets.values())
    fraud_loss = sum(snapshot["money"].get(f"campaign:{cid}", {}).get("fraud_loss", 0) for cid in budgets)
    return {"allocated": allocated, "incentive_consumed": consumed, "outstanding_liability": liability,
            "peak_committed": peak, "peak_utilization_bps": (peak * 10_000 // allocated) if allocated else None,
            "budget_blocked_enrollments": sum(b["budget_blocked_enrollments"] for b in budgets.values()),
            "fraud_loss_inside_consumed": fraud_loss,
            "reinstate_unfulfilled": sum(b["reinstate_unfulfilled"] for b in budgets.values()),
            "shortfall": sum(b["shortfall"] for b in budgets.values())}


def checks(snapshot: dict[str, Any], scenario: Scenario) -> list[tuple[str, bool]]:
    """Accounting invariants, each on its own - a failure is shown, never smoothed."""
    out = []
    for scope in [k for k in snapshot["money"] if k.split(":")[0] in ("total", "service", "corridor")]:
        row = lines(snapshot, scenario, scope)
        out.append((f"{scope}: C - P - H - reversed = C_net kept", row["check_from_c"] == row["net_commission_kept"]))
    booking_incentive = lines(snapshot, scenario)["passenger_bonus"] + lines(snapshot, scenario)["driver_credit"]
    out.append(("consumed P+H on captured bookings = budget consumed (counted once)",
                booking_incentive == programme(snapshot)["incentive_consumed"]))
    for cid, b in snapshot["budgets"].items():
        ledger = snapshot["money"].get(f"campaign:{cid}", {})
        out.append((f"campaign {cid}: budget consumed = lot consumption", b["consumed"] == ledger.get("consumed", 0)))
        out.append((f"campaign {cid}: committed within allocation or shown as shortfall",
                    b["promised"] + b["granted_unspent"] + b["consumed"] <= b["allocated"] or b["shortfall"] > 0))
    return out


def cac(snapshot: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    """Cost per person with the numerator's parts and each denominator named - never one blended number."""
    prog = programme(snapshot)
    numerator = prog["incentive_consumed"] + prog["outstanding_liability"] + scenario.extra_marketing_minor
    users = snapshot["users"]
    denominators = {
        "attributed": sum(u["attributed"] for u in users.values()),
        "enrolled_referees": sum(u["enrolled_referees"] for u in users.values()),
        "activated_referees": sum(u["activated_referees"] for u in users.values()),
        "activated_incremental_ASSUMPTION": sum(u["activated_incremental"] for u in users.values()),
    }
    return {"numerator": {"incentive_consumed": prog["incentive_consumed"],
                          "outstanding_liability": prog["outstanding_liability"],
                          "extra_marketing": scenario.extra_marketing_minor, "total": numerator},
            "per": {name: (numerator // value if value else None) for name, value in denominators.items()},
            "denominators": denominators}


# --- sensitivity: which assumption breaks a variant ----------------------------------------------------------------

PERTURBATIONS: dict[str, str] = {
    "no_incremental_users": "referral referralsiz ham kelmaydigan hech kimni olib kelmaydi",
    "half_incremental_users": "qo'shimcha foydalanuvchilar taxmini ikki baravar kam",
    "half_repeat": "takroriy buyurtmalar ikki baravar kam",
    "triple_disputes": "nizolar va reversal'lar uch baravar",
    "full_redemption": "berilgan har bir bonus ishlatiladi (stress)",
    "low_fares": "buyurtmalarning ko'pi past narx guruhida",
}


def perturb(scenario: Scenario, name: str) -> Scenario:
    services = copy.deepcopy(scenario.services)
    for service, model in list(services.items()):
        if name == "no_incremental_users":
            model = replace(model, incremental_new_per_day=0.0)
        elif name == "half_incremental_users":
            model = replace(model, incremental_new_per_day=model.incremental_new_per_day / 2)
        elif name == "half_repeat":
            model = replace(model, repeat_prob=model.repeat_prob / 2)
        elif name == "triple_disputes":
            model = replace(model, dispute_prob=min(1.0, model.dispute_prob * 3),
                            reversal_prob=min(1.0, model.reversal_prob * 3))
        elif name == "low_fares":
            weights = [0.8, 0.15, 0.05][: len(model.buckets)]
            model = replace(model, buckets=tuple(replace(b, weight=w) for b, w in zip(model.buckets, weights)))
        elif name == "full_redemption":
            model = replace(model, bonus_use_prob=1.0)
        services[service] = model
    return replace(scenario, name=f"{scenario.name}+{name}", services=services,
                   full_redemption=scenario.full_redemption or name == "full_redemption")


COMBINED_STRESS = ("half_repeat", "triple_disputes", "low_fares", "full_redemption", "half_incremental_users")


def combine(scenario: Scenario, names: tuple[str, ...]) -> Scenario:
    """Every named assumption change applied *together* (a separate pass of each is not a joint pass)."""
    for name in names:
        scenario = perturb(scenario, name)
    return scenario


def scale_incremental(scenario: Scenario, factor_pct: int) -> Scenario:
    """The incremental-users assumption scaled to ``factor_pct`` % (break-even search by simulation)."""
    services = {svc: replace(model, incremental_new_per_day=model.incremental_new_per_day * factor_pct / 100)
                for svc, model in scenario.services.items()}
    return replace(scenario, name=f"{scenario.name}+incremental_{factor_pct}pct", services=services)


def liability(snapshot: dict[str, Any], service: str | None = None) -> int:
    """Promised + granted-unspent of the campaigns of ``service`` (all when None): future P/H not yet spent."""
    return sum(b["promised"] + b["granted_unspent"] for b in snapshot["budgets"].values()
               if service is None or b["service"] == service)


def matched_control(scenario: Scenario) -> Scenario:
    """The same people, prices, corridors and behaviour with referral off and no campaign: the only honest baseline
    for "what did the programme change" - a global control would mix behaviour assumptions with the referral effect."""
    return replace(scenario, name=f"{scenario.name}~control", referral_enabled=False, campaigns=(), budget_cuts={},
                   pilot_variant=False)


def fmt(minor: int | None) -> str:
    if minor is None:
        return "noma'lum"
    return f"{minor / 100:,.0f}".replace(",", " ")
