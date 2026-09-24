"""Referral stage-6 simulator (ADR-0023 §20): determinism, accounting identities, budget rules, one formula.

The scenarios are the SYNTHETIC ones in ``docs/referral/simulation/scenarios.json`` shortened to 45 days so the
suite stays fast; nothing here is an approved value.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.contracts.promo import (
    DriverCreditOutcome,
    PassengerBonusConsent,
    PromoMarginPolicy,
    campaign_pair,
    quote_at_accept,
)
from app.modules.promotions.simulation.config import load_scenarios, scenario_from_dict
from app.modules.promotions.simulation.engine import (
    LotView,
    booking_terms,
    run_scenario,
)
from app.modules.promotions.simulation.report import (
    checks,
    lines,
    matched_control,
    programme,
)

CONFIG = Path(__file__).resolve().parents[2] / "docs/referral/simulation/scenarios.json"
NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
POLICY = PromoMarginPolicy(max_discount_share_bps=5_000, max_discount_per_booking_minor=1_500_000,
                           passenger_bonus_max_per_booking_minor=1_000_000, driver_credit_max_per_booking_minor=1_000_000,
                           variable_cost_fixed_minor=100_000, variable_cost_bps=0, min_margin_minor=100_000)
FARE, BPS = 20_000_000, 1_000


@pytest.fixture(scope="module")
def scenarios():
    loaded, _ = load_scenarios(CONFIG)
    return {s.name: replace(s, days=45, snapshots=(30, 45)) for s in loaded}


@pytest.fixture(scope="module")
def runs(scenarios):
    return {name: run_scenario(scenarios[name]) for name in ("medium", "adverse", "zero_budget", "budget_cut",
                                                             "funding_loss", "stress_full_redemption")}


def _last(run: dict) -> dict:
    return run["snapshots"][max(run["snapshots"])]


def test_every_input_is_labelled_synthetic_and_nothing_is_silently_zero(scenarios) -> None:
    assert all(s.synthetic for s in scenarios.values())
    assert all(s.fixed_costs_per_30_days_minor is None for s in scenarios.values())  # unknown, never 0
    raw = {"name": "x", "title": "x", "synthetic": True, "seed": 1, "days": 1, "snapshots": [1]}
    with pytest.raises(KeyError):  # a missing input is an error, not a default
        scenario_from_dict(raw)


def test_the_same_seed_config_and_code_give_the_same_result(scenarios, runs) -> None:
    assert run_scenario(scenarios["medium"]) == runs["medium"]
    assert run_scenario(replace(scenarios["medium"], seed=scenarios["medium"].seed + 1)) != runs["medium"]


@pytest.mark.parametrize("name", ["medium", "adverse", "budget_cut", "stress_full_redemption"])
def test_accounting_identities_hold_on_every_snapshot(scenarios, runs, name: str) -> None:
    for snap in runs[name]["snapshots"].values():
        failed = [label for label, ok in checks(snap, scenarios[name]) if not ok]
        assert failed == [], failed
        total = lines(snap, scenarios[name])
        # C - P - H - reversed = C_net kept: the incentive sits inside C - C_net and is never subtracted twice
        assert total["check_from_c"] == total["net_commission_kept"]
        assert total["operational_margin"] == total["net_commission_kept"] - total["variable_cost"]
        assert total["business_result"] is None  # fixed costs unknown -> no business result


def test_promise_grant_and_spend_are_one_obligation(runs) -> None:
    for snap in runs["medium"]["snapshots"].values():
        for b in snap["budgets"].values():
            # every tiyin is in exactly one stage (promised | granted | consumed | released); never three costs
            assert min(b["promised"], b["granted_unspent"], b["consumed"], b["released"]) >= 0
            assert b["promised"] + b["granted_unspent"] + b["consumed"] <= b["allocated"] or b["shortfall"] > 0
        prog = programme(snap)
        assert prog["incentive_consumed"] == sum(b["consumed"] for b in snap["budgets"].values())


def test_a_zero_budget_makes_no_promise_and_changes_nothing(scenarios, runs) -> None:
    last = _last(runs["zero_budget"])
    assert set(last["not_activated"]) == {str(c.id) for c in scenarios["zero_budget"].campaigns}
    assert last["budgets"] == {}
    assert programme(last)["outstanding_liability"] == 0
    twin = _last(run_scenario(matched_control(scenarios["zero_budget"])))
    assert last["money"] == twin["money"]  # no campaign can promise: no incremental users, no discount


def test_a_plain_reduction_stops_at_spent_plus_obligations_and_the_rest_is_refused(scenarios, runs) -> None:
    """G14: the simulator can no longer do what production forbids - a reduction never makes a shortfall."""
    cut = {str(cid) for cid in scenarios["budget_cut"].budget_cuts}
    for snap in runs["budget_cut"]["snapshots"].values():
        for cid in cut:
            b = snap["budgets"][cid]
            assert b["shortfall"] == 0 and b["peak_shortfall"] == 0
            assert b["allocated"] >= b["committed"]  # B >= S + L (no reinstatement waits in this scenario)
    after = _last(runs["budget_cut"])
    assert all(after["budgets"][cid]["reduce_refused"] > 0 and after["budgets"][cid]["reduce_applied"] > 0 for cid in cut)
    assert sum(after["budgets"][cid]["budget_blocked_enrollments"] for cid in cut) > 0  # no room left: no new promise


def test_a_funding_loss_stops_new_promises_and_keeps_the_existing_ones(scenarios, runs) -> None:
    before, after = runs["funding_loss"]["snapshots"][30], _last(runs["funding_loss"])
    cut = {str(cid) for cid in scenarios["funding_loss"].budget_cuts}
    assert sum(after["budgets"][cid]["budget_blocked_enrollments"] for cid in cut) > 0
    for cid in cut:
        committed_before = before["budgets"][cid]["promised"] + before["budgets"][cid]["granted_unspent"]
        assert committed_before > 0
        b = after["budgets"][cid]
        # nothing already promised disappears: it is still promised, granted, spent or released by its own rule
        assert b["promised"] + b["granted_unspent"] + b["consumed"] + b["released"] >= committed_before


def test_the_stress_run_uses_every_shown_bonus_and_still_reconciles(scenarios, runs) -> None:
    assert scenarios["stress_full_redemption"].full_redemption
    last = _last(runs["stress_full_redemption"])
    assert programme(last)["incentive_consumed"] >= programme(_last(runs["medium"]))["incentive_consumed"]


def test_the_matched_control_is_the_same_world_without_referral(scenarios) -> None:
    control = matched_control(scenarios["variant_A"])
    assert (control.referral_enabled, control.campaigns, control.seed, control.services) == (
        False, (), scenarios["variant_A"].seed, scenarios["variant_A"].services)
    assert control.fingerprint != scenarios["variant_A"].fingerprint
    # a service without a campaign behaves exactly as in the control: every draw is keyed on a stable identity
    ran, twin = _last(run_scenario(scenarios["variant_A"])), _last(run_scenario(control))
    assert ran["money"]["service:parcel"] == twin["money"]["service:parcel"]


# --- one formula: the engine's booking terms are the contract's --------------------------------------------------


def test_booking_terms_are_the_contract_quote() -> None:
    sim = booking_terms(fare_minor=FARE, fee_bps=BPS, p_lots=[LotView(1, 10, 500_000, 1.0)], h_lots=[],
                        policies={10: POLICY}, combinations={}, uses_bonus=True, now=NOW)
    consent = PassengerBonusConsent(proposal_version_id="sim", fare_minor=FARE, passenger_bonus_minor=500_000,
                                    cash_due_minor=FARE - 500_000, quote_fingerprint="", expires_at=NOW.replace(day=6))
    direct = quote_at_accept(consent=consent, proposal_version_id="sim", now=NOW, fare_minor=FARE, fee_bps=BPS,
                             policy=POLICY, passenger_bonus_available_minor=500_000, driver_credit_available_minor=0)
    assert sim.quote == direct
    assert (sim.quote.cash_due_minor, sim.quote.net_commission_minor) == (FARE - 500_000, 2_000_000 - 500_000)
    assert sim.allocations == ((1, 500_000),)


def test_booking_terms_follow_q123_partial_h_and_unpaired_campaigns() -> None:
    h_policy = replace(POLICY, max_discount_per_booking_minor=700_000)
    p_lots, h_lots = [LotView(1, 10, 500_000, 1.0)], [LotView(2, 20, 900_000, 1.0)]
    policies = {10: POLICY, 20: h_policy}
    paired = booking_terms(fare_minor=FARE, fee_bps=BPS, p_lots=p_lots, h_lots=h_lots, policies=policies,
                           combinations={campaign_pair(10, 20): "shared"}, uses_bonus=True, now=NOW)
    assert (paired.quote.passenger_bonus_minor, paired.quote.driver_credit_minor, paired.h_outcome) == (
        500_000, 200_000, DriverCreditOutcome.PARTIAL)  # H takes only the room left; P is untouched
    unpaired = booking_terms(fare_minor=FARE, fee_bps=BPS, p_lots=p_lots, h_lots=h_lots, policies=policies,
                             combinations={}, uses_bonus=True, now=NOW)
    assert (unpaired.quote.passenger_bonus_minor, unpaired.quote.driver_credit_minor, unpaired.h_outcome) == (
        500_000, 0, DriverCreditOutcome.NOT_APPROVED)
    h_only = booking_terms(fare_minor=FARE, fee_bps=BPS, p_lots=[], h_lots=[LotView(2, 20, 300_000, 1.0)],
                           policies=policies, combinations={}, uses_bonus=False, now=NOW)
    assert (h_only.quote.passenger_bonus_minor, h_only.quote.driver_credit_minor, h_only.quote.cash_due_minor) == (
        0, 300_000, FARE)


# --- A6.2: cohort anchors and maturity -----------------------------------------------------------------------------


def test_an_immature_cohort_is_not_yet_evaluable_never_zero(runs) -> None:
    early = runs["medium"]["snapshots"][30]
    for metric in early["cohorts"]:
        assert metric["anchor"] in ("enrollment", "activation", "grant")
        assert {"as_of_day", "denominator", "matured", "immature", "window_days"} <= set(metric)
        if metric["metric"].startswith(("retention_d", "margin_d60")) or metric["metric"].startswith("bonus_"):
            # 30 observed days cannot mature a 30-day window that starts on day >= 0 plus the activation delay
            assert metric["status"] == "hali_baholab_bolmaydi", metric
            assert (metric["numerator"], metric["value_bps"], metric["value_minor"]) == (None, None, None)


def test_a_recently_granted_lot_is_immature_not_unused(scenarios, runs) -> None:
    for day, snap in runs["medium"]["snapshots"].items():
        for service, use in snap["bonus_use"].items():
            assert use["lots_matured"] + use["lots_immature"] == use["lots_granted"]
            assert use["unused_reason_lots"]["not_matured"] <= use["lots_immature"]
            assert use["lots_spent_any_matured"] <= use["lots_matured"]
            assert use["holders_used_any"] <= use["holders_matured"]
            assert use["value_spent_matured_minor"] <= use["value_granted_matured_minor"]
    assert scenarios["medium"].lot_maturity_days == 30


def test_budget_use_is_measured_against_the_limit_at_that_moment_and_a_shortfall_is_its_own_line(runs) -> None:
    cut = _last(runs["funding_loss"])["budgets"]
    for cid in ("1", "3"):
        b = cut[cid]
        assert b["shortfall_since_day"] == 30 and b["peak_shortfall"] > 0
        assert b["funded_committed"] == b["committed"] - b["shortfall"]
        assert b["allocated"] < b["allocated_initial"]
    for b in _last(runs["medium"])["budgets"].values():
        assert b["peak_utilization_bps"] <= 10_000 and b["shortfall"] == 0


def test_joint_stress_applies_every_change_together(scenarios) -> None:
    from app.modules.promotions.simulation.report import (
        COMBINED_STRESS,
        combine,
        scale_incremental,
    )

    base = scenarios["variant_A"]
    joint = combine(base, COMBINED_STRESS)
    assert all(name in joint.name for name in COMBINED_STRESS) and joint.full_redemption
    for service, model in joint.services.items():
        original = base.services[service]
        assert model.repeat_prob == original.repeat_prob / 2
        assert model.incremental_new_per_day == original.incremental_new_per_day / 2
        assert model.dispute_prob == min(1.0, original.dispute_prob * 3)
        assert model.buckets[0].weight == 0.8
    assert scale_incremental(base, 40).services[next(iter(base.services))].incremental_new_per_day == (
        base.services[next(iter(base.services))].incremental_new_per_day * 40 / 100)
    assert combine(base, COMBINED_STRESS).fingerprint != base.fingerprint
    assert replace(base, seed=base.seed + 1).fingerprint != base.fingerprint  # a seed spread is traceable
