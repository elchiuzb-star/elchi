"""Promotions & referral financial contract (ADR-0023, Q101-Q110).

Every amount here is SYNTHETIC test data. None of it is a tariff, a reward size, a budget or an O/M value -
those are decided after the stage-6 simulation. The tests prove the calculation model, not marketing numbers.

`QA #n` refers to the numbered scenarios of docs/referral/ELCHI_REFERRAL_TASK.md §16 at the contract level;
the transactional/concurrent halves of the same scenarios are PostgreSQL tests in later stages.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts.enums import (
    PILOT_CAMPAIGN_KINDS,
    ParcelPayer,
    PromoCampaignKind,
    PromoFault,
    PromoInstrument,
    PromoRiskSignal,
    ServiceType,
)
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.money import TWO_PERSON_APPROVAL_THRESHOLD_MINOR, commission_minor
from app.contracts.promo import (
    ATTRIBUTION_WINDOW,
    CLIENT_PROMO_VIEW_KEYS,
    DRIVER_PROMO_VIEW_KEYS,
    PROMO_CASH_FEATURE,
    QUALIFICATION_RISK_WINDOW,
    RISK_RULESET_V1,
    AttributionOutcome,
    BudgetPosition,
    CampaignTerms,
    DisclosureCode,
    LotBalance,
    MilestoneEvidence,
    MilestoneProgress,
    PromoLimitReason,
    PromoMarginPolicy,
    QualificationFacts,
    QualificationVerdict,
    RiskConsequence,
    RiskOutcome,
    RiskReliability,
    RiskRule,
    RiskRuleset,
    ServiceEvidence,
    acquisition_key,
    amendment_reconfirmation,
    assess_risk,
    attribution_window_open,
    budget_change_requires_second_approver,
    cash_receipt_matches,
    client_referral_progress,
    client_view,
    decide_attribution,
    driver_view,
    enrollment_commitment_minor,
    enrollment_disclosures,
    evaluate_qualification,
    identity_match_effect,
    lot_usable_for,
    max_commitment_for,
    milestone_progress,
    milestones_reached,
    parse_client_features,
    passenger_bonus_allowed,
    promo_booking_command_allowed,
    promo_new_deal_allowed,
    qualification_deadline,
    qualification_event_key,
    quote_at_accept,
    quote_promo,
    record_consent,
    referral_can_still_qualify,
    restored_expiry,
    reversal_plan,
    review_due_at,
    reward_key,
    validate_activation,
)
from app.contracts.state_machines import (
    PROMO_CAMPAIGN,
    PROMO_ENROLLMENT,
    PROMO_MACHINES,
    PROMO_OBLIGATION,
    PROMO_REDEMPTION,
    PROMO_REWARD,
    REFERRAL_ATTRIBUTION,
)

SOM = 100  # minor units per so'm
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)

# SYNTHETIC policy: 50% share cap is the task's "test configuration only" example.
SYNTH_POLICY = PromoMarginPolicy(
    max_discount_share_bps=5_000,
    max_discount_per_booking_minor=15_000 * SOM,
    passenger_bonus_max_per_booking_minor=10_000 * SOM,
    driver_credit_max_per_booking_minor=10_000 * SOM,
    variable_cost_fixed_minor=1_000 * SOM,
    variable_cost_bps=0,
    min_margin_minor=1_000 * SOM,
)


def _quote(fare_som: int, fee_bps: int, *, p_req: int = 0, p_avail: int = 0, h_avail: int = 0, policy=SYNTH_POLICY):
    return quote_promo(
        fare_minor=fare_som * SOM,
        fee_bps=fee_bps,
        policy=policy,
        passenger_bonus_requested_minor=p_req * SOM,
        passenger_bonus_available_minor=p_avail * SOM,
        driver_credit_available_minor=h_avail * SOM,
    )


# --- the money model --------------------------------------------------------------------------------------


def test_task_worked_example_synthetic() -> None:
    # task §4 illustration: F 200 000, C 20 000, P 5 000, H 3 000 so'm (synthetic, not a tariff)
    q = _quote(200_000, 1_000, p_req=5_000, p_avail=5_000, h_avail=3_000)
    assert q.base_commission_minor == 20_000 * SOM
    assert q.passenger_bonus_minor == 5_000 * SOM
    assert q.driver_credit_minor == 3_000 * SOM
    assert q.cash_due_minor == 195_000 * SOM
    assert q.net_commission_minor == 12_000 * SOM
    assert q.driver_keeps_minor == 183_000 * SOM


@pytest.mark.parametrize("fare_som", [1, 7, 999, 50_000, 123_457, 200_000, 1_000_000])
@pytest.mark.parametrize("fee_bps", [1, 333, 1_000, 1_500, 10_000])
@pytest.mark.parametrize("p_avail,h_avail", [(0, 0), (5_000, 0), (0, 5_000), (5_000, 3_000), (50_000, 50_000)])
def test_identities_hold_everywhere(fare_som: int, fee_bps: int, p_avail: int, h_avail: int) -> None:
    """QA #10/#11: F_cash = F-P, C_net = C-P-H >= 0, driver keeps F-C+H, margin floor, combined share cap."""
    q = _quote(fare_som, fee_bps, p_req=p_avail, p_avail=p_avail, h_avail=h_avail)
    q.check_invariants()
    c = commission_minor(fare_som * SOM, fee_bps)
    assert q.base_commission_minor == c
    # the client's discount never lowers what the driver keeps below F - C
    assert q.driver_keeps_minor >= q.fare_minor - c
    assert q.driver_keeps_minor == q.fare_minor - c + q.driver_credit_minor
    assert q.passenger_bonus_minor + q.driver_credit_minor <= c * SYNTH_POLICY.max_discount_share_bps // 10_000
    assert q.passenger_bonus_minor + q.driver_credit_minor <= SYNTH_POLICY.max_discount_per_booking_minor
    if q.promo_applied:
        assert q.margin_minor >= SYNTH_POLICY.min_margin_minor
        assert q.net_commission_minor - q.variable_cost_minor >= SYNTH_POLICY.min_margin_minor


def test_passenger_bonus_has_priority_and_credit_takes_the_rest() -> None:
    # C = 20 000; share cap 10 000; P consented 8 000 -> H gets only 2 000 of its 9 000
    q = _quote(200_000, 1_000, p_req=8_000, p_avail=8_000, h_avail=9_000)
    assert q.passenger_bonus_minor == 8_000 * SOM
    assert q.driver_credit_minor == 2_000 * SOM
    assert PromoLimitReason.PASSENGER_BONUS_PRIORITY in q.driver_limit_reasons


def test_consent_caps_the_bonus_even_with_more_available() -> None:
    q = _quote(200_000, 1_000, p_req=3_000, p_avail=9_000)
    assert q.passenger_bonus_minor == 3_000 * SOM


def test_no_consent_means_no_passenger_bonus() -> None:
    q = _quote(200_000, 1_000, p_req=0, p_avail=9_000, h_avail=1_000)
    assert q.passenger_bonus_minor == 0
    assert q.cash_due_minor == q.fare_minor
    assert PromoLimitReason.NO_CONSENT in q.passenger_limit_reasons
    assert q.driver_credit_minor == 1_000 * SOM


def test_zero_commission_creates_no_subsidy() -> None:
    """QA #12: a 0 bps booking funds nothing; the bonus stays with its owner."""
    q = _quote(200_000, 0, p_req=5_000, p_avail=5_000, h_avail=5_000)
    assert (q.passenger_bonus_minor, q.driver_credit_minor) == (0, 0)
    assert q.net_commission_minor == 0 and q.cash_due_minor == q.fare_minor
    assert PromoLimitReason.ZERO_COMMISSION in q.passenger_limit_reasons


def test_small_commission_below_cost_plus_margin_creates_no_subsidy() -> None:
    """QA #12: C 1 500 so'm, O 1 000 + M 1 000 -> no room; nothing is pushed onto the driver or the balance."""
    q = _quote(15_000, 1_000, p_req=5_000, p_avail=5_000, h_avail=5_000)
    assert q.base_commission_minor == 1_500 * SOM
    assert (q.passenger_bonus_minor, q.driver_credit_minor) == (0, 0)
    assert q.net_commission_minor == q.base_commission_minor
    assert PromoLimitReason.MARGIN_FLOOR in q.passenger_limit_reasons


def test_partial_use_when_commission_is_short_keeps_the_rest_of_the_bonus() -> None:
    # C 4 000; room = 4 000 - 1 000 - 1 000 = 2 000 (share cap is also 2 000)
    q = _quote(40_000, 1_000, p_req=5_000, p_avail=5_000)
    assert q.passenger_bonus_minor == 2_000 * SOM
    lot = LotBalance(amount_minor=5_000 * SOM).reserve(q.passenger_bonus_minor)
    assert lot.available_minor == 3_000 * SOM  # shown to the client in advance, not lost


def test_unset_parameters_are_never_zero() -> None:
    unset = replace(SYNTH_POLICY, min_margin_minor=None)
    with pytest.raises(DomainError) as exc:
        _quote(200_000, 1_000, p_req=5_000, p_avail=5_000, policy=unset)
    assert exc.value.code is ErrorCode.PROMO_PARAMETERS_UNSET
    assert "min_margin_minor" in exc.value.details["fields"]
    with pytest.raises(DomainError):
        _quote(200_000, 1_000, h_avail=1_000, policy=None)


def test_promotions_off_leaves_the_plain_booking_untouched() -> None:
    """QA #23: no bonus, no policy -> exactly today's booking (C_net = C, F_cash = F)."""
    q = _quote(200_000, 1_500, policy=None)
    assert not q.promo_applied
    assert q.net_commission_minor == commission_minor(200_000 * SOM, 1_500)
    assert q.cash_due_minor == 200_000 * SOM


def test_caps_round_in_the_platforms_favour() -> None:
    # C = 2 931 minor on 29 310 minor at 10%; share 50% = 1 465.5 -> floor 1 465
    policy = replace(SYNTH_POLICY, variable_cost_fixed_minor=0, min_margin_minor=1, variable_cost_bps=0)
    q = quote_promo(
        fare_minor=29_310, fee_bps=1_000, policy=policy,
        passenger_bonus_requested_minor=10_000, passenger_bonus_available_minor=10_000, driver_credit_available_minor=0,
    )
    assert q.passenger_bonus_minor == 1_465
    cost = replace(SYNTH_POLICY, variable_cost_fixed_minor=0, variable_cost_bps=1).variable_cost_minor(10_001)
    assert cost == 2  # 1.0001 rounded up


def test_zero_margin_is_refused_like_an_unset_value() -> None:
    """Q111: M > 0 before any discount; M = 0 never means "no floor"."""
    with pytest.raises(DomainError) as exc:
        _quote(200_000, 1_000, p_req=5_000, p_avail=5_000, policy=replace(SYNTH_POLICY, min_margin_minor=0))
    assert exc.value.code is ErrorCode.PROMO_PARAMETERS_UNSET
    assert exc.value.details["invalid"] == ["min_margin_minor"]


def test_zero_margin_policy_does_not_break_plain_or_zero_percent_bookings() -> None:
    """Q111: the promo floor applies to promo bookings only."""
    zero_m = replace(SYNTH_POLICY, min_margin_minor=0)
    assert not _quote(200_000, 1_500, policy=zero_m).promo_applied  # nothing to spend -> plain booking
    assert _quote(200_000, 0, p_req=5_000, p_avail=5_000, policy=zero_m).net_commission_minor == 0  # approved 0 %


def test_promo_quote_invariants_reject_a_tampered_value() -> None:
    q = _quote(200_000, 1_000, p_req=5_000, p_avail=5_000)
    for broken in (
        replace(q, min_margin_minor=0),
        replace(q, variable_cost_minor=-1, margin_minor=q.net_commission_minor + 1),
        replace(q, margin_minor=q.min_margin_minor - 1, variable_cost_minor=q.net_commission_minor - q.min_margin_minor + 1),
    ):
        with pytest.raises(ValueError):
            broken.check_invariants()


def test_float_inputs_are_rejected() -> None:
    with pytest.raises(TypeError):
        quote_promo(fare_minor=100.0, fee_bps=1_000, policy=SYNTH_POLICY, passenger_bonus_requested_minor=0,
                    passenger_bonus_available_minor=0, driver_credit_available_minor=0)


# --- consent and stale quotes (Q104, QA #13) --------------------------------------------------------------


def _consented(fare_som: int = 200_000, p: int = 5_000):
    q = _quote(fare_som, 1_000, p_req=p, p_avail=p)
    return q, record_consent(q, proposal_version_id="pv_1", expires_at=NOW + timedelta(minutes=30))


def _accept(consent, *, fare_som=200_000, p_avail=5_000, h_avail=0, now=NOW, version="pv_1"):
    return quote_at_accept(
        consent=consent, proposal_version_id=version, now=now, fare_minor=fare_som * SOM, fee_bps=1_000,
        policy=SYNTH_POLICY, passenger_bonus_available_minor=p_avail * SOM, driver_credit_available_minor=h_avail * SOM,
    )


def test_driver_accept_applies_exactly_the_consented_terms() -> None:
    quote, consent = _consented()
    accepted = _accept(consent, p_avail=50_000, h_avail=1_000)
    assert accepted.passenger_bonus_minor == consent.passenger_bonus_minor
    assert accepted.cash_due_minor == consent.cash_due_minor == quote.cash_due_minor
    assert accepted.driver_credit_minor == 1_000 * SOM  # credit may join; the client's cash does not move


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"now": NOW + timedelta(minutes=30)}, "expired"),
        ({"fare_som": 190_000}, "fare"),
        ({"version": "pv_2"}, "proposal_version"),
        ({"p_avail": 4_000}, "passenger_bonus_changed"),  # bonus partly spent elsewhere meanwhile
    ],
)
def test_stale_consent_never_raises_the_cash_silently(kwargs, reason) -> None:
    _, consent = _consented()
    with pytest.raises(DomainError) as exc:
        _accept(consent, **kwargs)
    assert exc.value.code is ErrorCode.PROMO_QUOTE_STALE
    assert reason in exc.value.details["reasons"]


def test_consent_is_recorded_only_for_a_bonus_quote() -> None:
    q = _quote(200_000, 1_000)
    with pytest.raises(ValueError):
        record_consent(q, proposal_version_id="pv_1", expires_at=NOW)


def test_quote_fingerprint_binds_money_terms() -> None:
    a = _quote(200_000, 1_000, p_req=5_000, p_avail=5_000)
    b = _quote(200_000, 1_000, p_req=4_000, p_avail=5_000)
    assert a.fingerprint == _quote(200_000, 1_000, p_req=5_000, p_avail=9_000).fingerprint
    assert a.fingerprint != b.fingerprint


# --- amendment (Q104) -------------------------------------------------------------------------------------


def test_amendment_that_lowers_the_fare_and_raises_cash_needs_client_reconfirmation() -> None:
    old = _quote(200_000, 1_000, p_req=8_000, p_avail=8_000)
    new = _quote(100_000, 1_000, p_req=8_000, p_avail=8_000)  # C 10 000 -> cap 5 000 -> P drops
    assert new.passenger_bonus_minor < old.passenger_bonus_minor
    # the fare fell by 100 000 but the bonus fell by 3 000: cash still falls here ...
    assert new.cash_due_minor < old.cash_due_minor
    recon = amendment_reconfirmation(old, new)
    assert recon.client and recon.driver


def test_amendment_where_cash_rises_is_flagged_for_the_client() -> None:
    old = _quote(200_000, 1_000, p_req=8_000, p_avail=8_000)
    # same fare, but the bonus can no longer be applied in full (e.g. re-quoted under a smaller share cap)
    tighter = replace(SYNTH_POLICY, max_discount_share_bps=2_000)
    new = _quote(200_000, 1_000, p_req=8_000, p_avail=8_000, policy=tighter)
    assert new.cash_due_minor > old.cash_due_minor
    assert amendment_reconfirmation(old, new).client


def test_unchanged_terms_need_no_reconfirmation() -> None:
    q = _quote(200_000, 1_000, p_req=5_000, p_avail=5_000)
    assert not amendment_reconfirmation(q, q).any


# --- who sees what (Q103) ---------------------------------------------------------------------------------


def test_client_view_never_contains_commission_terms() -> None:
    q = _quote(200_000, 1_000, p_req=5_000, p_avail=5_000, h_avail=3_000)
    view = client_view(q)
    assert set(view) == CLIENT_PROMO_VIEW_KEYS
    for forbidden in ("commission", "fee_bps", "credit", "margin", "cost", "base"):
        assert not any(forbidden in key for key in view)
    assert view["cash_due_minor"] == view["fare_minor"] - view["passenger_discount_minor"]


def test_driver_view_explains_cash_commission_and_credit() -> None:
    q = _quote(200_000, 1_000, p_req=5_000, p_avail=5_000, h_avail=3_000)
    view = driver_view(q)
    assert set(view) == DRIVER_PROMO_VIEW_KEYS
    assert view["cash_to_collect_minor"] == 195_000 * SOM
    assert view["commission_charged_minor"] == 12_000 * SOM
    assert view["driver_credit_minor"] == 3_000 * SOM
    assert view["driver_keeps_minor"] == 183_000 * SOM
    assert "margin" not in " ".join(view)  # O and M stay internal for the driver too


# --- eligibility --------------------------------------------------------------------------------------------


def test_parcel_bonus_only_when_the_sender_pays_and_owns_the_bonus() -> None:
    kw = {"service_type": ServiceType.PARCEL, "bonus_owner_user_id": 1, "client_user_id": 1}
    assert passenger_bonus_allowed(**kw, parcel_payer=ParcelPayer.SENDER)
    assert not passenger_bonus_allowed(**kw, parcel_payer=ParcelPayer.RECEIVER)
    assert not passenger_bonus_allowed(**kw, parcel_payer=None)
    assert not passenger_bonus_allowed(service_type=ServiceType.PASSENGER, bonus_owner_user_id=2, client_user_id=1, parcel_payer=None)


def test_no_cross_service_spending_in_the_pilot() -> None:
    assert lot_usable_for(ServiceType.PARCEL, ServiceType.PARCEL)
    assert not lot_usable_for(ServiceType.PARCEL, ServiceType.PASSENGER)
    assert not lot_usable_for("passenger", "parcel")


# --- legacy clients (Q110, QA #21) ------------------------------------------------------------------------


def test_feature_header_parsing_is_lenient_and_grants_nothing() -> None:
    assert parse_client_features(None) == frozenset()
    assert parse_client_features(" PROMO_CASH_V1 , x ") == {PROMO_CASH_FEATURE, "x"}
    assert parse_client_features("admin;drop table") == frozenset()
    assert len(parse_client_features(",".join(f"f{i}" for i in range(100)))) == 16


def test_new_promo_deal_needs_both_clients_to_render_the_cash_amount() -> None:
    new = frozenset({PROMO_CASH_FEATURE})
    assert promo_new_deal_allowed(new, new)
    assert not promo_new_deal_allowed(new, frozenset())
    assert not promo_new_deal_allowed(new, None)  # counterparty client unknown
    assert not promo_new_deal_allowed(frozenset(), new)


def test_old_client_keeps_the_discount_but_cannot_run_cash_commands() -> None:
    old = frozenset()
    assert not promo_booking_command_allowed(old, "report_cash_receipt", booking_has_promo=True)
    assert not promo_booking_command_allowed(old, "accept_amendment", booking_has_promo=True)
    assert promo_booking_command_allowed(old, "board", booking_has_promo=True)
    assert promo_booking_command_allowed(old, "report_cash_receipt", booking_has_promo=False)


def test_cash_receipt_is_checked_against_cash_due() -> None:
    q = _quote(200_000, 1_000, p_req=5_000, p_avail=5_000)
    assert cash_receipt_matches(q.cash_due_minor, 195_000 * SOM)
    assert not cash_receipt_matches(q.cash_due_minor, 200_000 * SOM)


# --- lots (QA #9, #15, #16) -------------------------------------------------------------------------------


def test_partial_spend_expiry_and_release_add_up() -> None:
    lot = LotBalance(amount_minor=10_000)
    lot = lot.reserve(3_000).reserve(2_000)
    lot = lot.consume(3_000).release(2_000)
    assert (lot.available_minor, lot.reserved_minor, lot.consumed_minor) == (7_000, 0, 3_000)
    lot = lot.reserve(1_000).expire()  # the reserved 1 000 is settled by its booking, not expired
    assert (lot.expired_minor, lot.reserved_minor, lot.available_minor) == (6_000, 1_000, 0)
    lot = lot.release(1_000).reinstate_expired(6_000)
    assert lot.available_minor == 7_000
    total = lot.available_minor + lot.reserved_minor + lot.consumed_minor + lot.expired_minor + lot.reversed_minor
    assert total == lot.amount_minor


def test_one_bonus_cannot_be_reserved_twice() -> None:
    """QA #9 (arithmetic half): the second reservation sees what the first took."""
    lot = LotBalance(amount_minor=5_000).reserve(5_000)
    with pytest.raises(ValueError):
        lot.reserve(1)


def test_consumption_happens_once() -> None:
    lot = LotBalance(amount_minor=5_000).reserve(5_000).consume(5_000)
    with pytest.raises(ValueError):
        lot.consume(5_000)


def test_reversal_of_spent_bonus_is_risk_cost_not_debt() -> None:
    """QA #16: consumed value is never charged back to anyone's real balance."""
    lot = LotBalance(amount_minor=10_000).reserve(4_000).consume(4_000).reserve(1_000)
    plan = reversal_plan(lot)
    assert (plan.reverse_now_minor, plan.settle_with_booking_minor, plan.risk_cost_minor) == (5_000, 1_000, 4_000)
    reversed_lot, amount = lot.reverse_available()
    assert amount == 5_000 and reversed_lot.consumed_minor == 4_000


def test_fair_restoration_after_a_release() -> None:
    expires = NOW + timedelta(hours=1)
    released = NOW + timedelta(hours=2)
    grace = timedelta(days=7)
    assert restored_expiry(lot_expires_at=expires, released_at=released, fault=PromoFault.DRIVER, grace=grace) == released + grace
    assert restored_expiry(lot_expires_at=expires, released_at=released, fault=PromoFault.PLATFORM, grace=grace) == released + grace
    assert restored_expiry(lot_expires_at=expires, released_at=released, fault=PromoFault.CLIENT, grace=grace) is None
    far = NOW + timedelta(days=60)
    assert restored_expiry(lot_expires_at=far, released_at=released, fault=PromoFault.DRIVER, grace=grace) is None


# --- budget (QA #6, #7, #8, #24) --------------------------------------------------------------------------


def test_two_sided_promise_is_reserved_in_full() -> None:
    """QA #6: both rewards count before anything is promised."""
    assert enrollment_commitment_minor([3_000, 2_000]) == 5_000
    budget = BudgetPosition(allocated_minor=9_000).promise(5_000)
    assert budget.available_for_new_minor == 4_000
    with pytest.raises(DomainError) as exc:
        budget.promise(5_000)
    assert exc.value.code is ErrorCode.PROMO_BUDGET_EXHAUSTED


def test_sequential_enrollments_never_exceed_the_budget() -> None:
    """QA #7 (arithmetic half; the concurrent half is a PG test under the budget row lock)."""
    budget = BudgetPosition(allocated_minor=10_000)
    accepted = 0
    for _ in range(10):
        try:
            budget = budget.promise(3_000)
            accepted += 1
        except DomainError:
            pass
    assert accepted == 3 and budget.committed_minor <= budget.allocated_minor


def test_reserve_moves_promise_to_granted_to_consumed_once() -> None:
    budget = BudgetPosition(allocated_minor=10_000).promise(5_000)
    budget = budget.grant(from_promised_minor=5_000, granted_minor=4_000)  # 1 000 of the promise unused
    assert (budget.promised_minor, budget.granted_minor, budget.released_minor) == (0, 4_000, 1_000)
    budget = budget.consume(1_500).release_granted(500)
    assert (budget.granted_minor, budget.consumed_minor) == (2_000, 1_500)
    assert budget.committed_minor == 3_500 and budget.available_for_new_minor == 6_500
    with pytest.raises(ValueError):
        budget.grant(from_promised_minor=1, granted_minor=1)  # nothing left promised: no double reserve


def test_budget_shortfall_stops_new_enrollments_but_keeps_commitments() -> None:
    """QA #8 and task §8: a funding loss never cancels what was promised or granted (G14: only a recorded
    funding loss can go below the obligations; a plain reduction cannot)."""
    budget = BudgetPosition(allocated_minor=10_000).promise(4_000).grant(4_000, 4_000).promise(5_000)
    budget = budget.record_funding_loss(3_000)
    assert budget.shortfall_minor == 2_000
    assert budget.granted_minor == 4_000 and budget.promised_minor == 5_000
    assert not budget.accepts_new_enrollments(1)
    with pytest.raises(DomainError):
        budget.promise(1)
    # granted value still spends
    assert budget.consume(4_000).consumed_minor == 4_000


def test_milestone_commitment_counts_every_step_for_both_sides() -> None:
    terms = _terms(PromoCampaignKind.REFERRAL_DRIVER_DRIVER, milestones=(5, 10), instruments=(PromoInstrument.DRIVER_CREDIT,) * 2)
    assert max_commitment_for(terms) == (3_000 + 2_000) * 2


# --- activation (Q105) --------------------------------------------------------------------------------------


def _terms(kind=PromoCampaignKind.REFERRAL_CLIENT_CLIENT, *, milestones=(), instruments=(PromoInstrument.PASSENGER_BONUS,) * 2, **overrides):
    base = dict(
        kind=kind, service_type=ServiceType.PASSENGER, budget_allocated_minor=1_000_000,
        referrer_reward_minor=3_000, referee_reward_minor=2_000,
        referrer_instrument=instruments[0], referee_instrument=instruments[1], milestone_thresholds=milestones,
        min_distinct_clients=3 if kind is PromoCampaignKind.REFERRAL_DRIVER_DRIVER else None,
        enrollment_limit=100, qualification_window=timedelta(days=30), reward_validity=timedelta(days=60),
        review_sla=timedelta(hours=72), restoration_grace=timedelta(days=7),
        margin_policy=SYNTH_POLICY, approval_reference="SYNTHETIC-TEST",
    )
    base.update(overrides)
    return CampaignTerms(**base)


def test_complete_synthetic_terms_activate() -> None:
    validate_activation(_terms())


def test_unset_terms_block_activation() -> None:
    with pytest.raises(DomainError) as exc:
        validate_activation(_terms(budget_allocated_minor=None, margin_policy=replace(SYNTH_POLICY, variable_cost_bps=None)))
    assert exc.value.code is ErrorCode.PROMO_PARAMETERS_UNSET
    assert {"budget_allocated_minor", "margin_policy.variable_cost_bps"} <= set(exc.value.details["fields"])


def test_activation_requires_a_positive_minimum_margin() -> None:
    with pytest.raises(DomainError) as exc:
        validate_activation(_terms(margin_policy=replace(SYNTH_POLICY, min_margin_minor=0)))
    assert "margin_policy.min_margin_minor" in exc.value.details["invalid"]


def test_non_pilot_kinds_cannot_activate() -> None:
    assert PromoCampaignKind.CASHBACK not in PILOT_CAMPAIGN_KINDS
    with pytest.raises(DomainError) as exc:
        validate_activation(_terms(PromoCampaignKind.CASHBACK))
    assert exc.value.code is ErrorCode.FEATURE_DISABLED


def test_instruments_match_the_flow() -> None:
    with pytest.raises(DomainError):
        validate_activation(_terms(PromoCampaignKind.REFERRAL_DRIVER_DRIVER, milestones=(5, 10)))  # bonus, not credit
    validate_activation(_terms(PromoCampaignKind.REFERRAL_DRIVER_CLIENT,
                               instruments=(PromoInstrument.DRIVER_CREDIT, PromoInstrument.PASSENGER_BONUS)))


def test_driver_milestone_campaign_needs_distinct_client_rule() -> None:
    credit = (PromoInstrument.DRIVER_CREDIT,) * 2
    validate_activation(_terms(PromoCampaignKind.REFERRAL_DRIVER_DRIVER, milestones=(5, 10), instruments=credit))
    with pytest.raises(DomainError) as exc:
        validate_activation(_terms(PromoCampaignKind.REFERRAL_DRIVER_DRIVER, milestones=(5, 10), instruments=credit,
                                   min_distinct_clients=None))
    assert "min_distinct_clients" in exc.value.details["fields"]


def test_risk_window_is_the_decided_48_hours_not_a_campaign_knob() -> None:
    """Q110: decided once; campaign terms cannot shorten it."""
    assert QUALIFICATION_RISK_WINDOW == timedelta(hours=48)
    assert "risk_window" not in CampaignTerms.__slots__


def test_conditions_are_disclosed_before_joining() -> None:
    """Q112: the referrer-service rule and the way to still qualify are shown up front."""
    shown = enrollment_disclosures(_terms())
    assert shown[DisclosureCode.REFERRER_SERVICE_EXCLUDED] is True
    assert shown[DisclosureCode.ANOTHER_DRIVER_QUALIFIES] is True
    assert shown[DisclosureCode.NEXT_ELIGIBLE_SERVICE] is True and shown[DisclosureCode.NOT_CASH] is True
    assert shown[DisclosureCode.QUALIFICATION_DEADLINE] == 30 * 24 * 3600
    assert shown[DisclosureCode.RISK_CHECK] == 48 * 3600
    assert shown[DisclosureCode.REQUIRED_SERVICES] == 1
    parcel = enrollment_disclosures(_terms(service_type=ServiceType.PARCEL))
    assert parcel[DisclosureCode.REQUIRED_SERVICES] == 2 and parcel[DisclosureCode.SERVICE_TYPE_ONLY] == "parcel"


def test_budget_changes_use_the_existing_two_person_threshold() -> None:
    """Q114: same constant, same boundary as wallet top-ups/adjustments (strictly above; minor units)."""
    assert TWO_PERSON_APPROVAL_THRESHOLD_MINOR == 100_000_000  # 1 000 000 so'm
    assert not budget_change_requires_second_approver(TWO_PERSON_APPROVAL_THRESHOLD_MINOR)
    assert budget_change_requires_second_approver(TWO_PERSON_APPROVAL_THRESHOLD_MINOR + 1)
    with pytest.raises(ValueError):
        budget_change_requires_second_approver(0)


def test_campaign_terms_are_immutable_values() -> None:
    """QA #22 (contract half): a version is a frozen value; new terms are a new version, pinned per enrollment."""
    terms = _terms()
    with pytest.raises(FrozenInstanceError):
        terms.referee_reward_minor = 1  # type: ignore[misc]


# --- attribution (Q106, QA #1, #2) ------------------------------------------------------------------------


def _attr(**overrides):
    kw = dict(referrer_user_id=1, referee_user_id=2, referrer_identity_keys=frozenset({"h1"}),
              referee_identity_keys=frozenset({"h2"}), existing_referrer_user_id=None, window_open=True)
    kw.update(overrides)
    return decide_attribution(**kw)


def test_self_referral_is_refused() -> None:
    for overrides in ({"referee_user_id": 1}, {"referee_identity_keys": frozenset({"h1"})}):
        with pytest.raises(DomainError) as exc:
            _attr(**overrides)
        assert exc.value.code is ErrorCode.REFERRAL_SELF_REFERRAL


def test_attribution_is_first_wins_and_replay_is_idempotent() -> None:
    assert _attr() is AttributionOutcome.CREATED
    assert _attr(existing_referrer_user_id=1, window_open=False) is AttributionOutcome.REPLAYED
    with pytest.raises(DomainError) as exc:
        _attr(referrer_user_id=3, referrer_identity_keys=frozenset({"h3"}), existing_referrer_user_id=1)
    assert exc.value.code is ErrorCode.REFERRAL_ALREADY_ATTRIBUTED


def test_attribution_window_is_72_hours_and_closes_at_first_booking() -> None:
    assert ATTRIBUTION_WINDOW == timedelta(hours=72)
    start = NOW
    assert attribution_window_open(window_started_at=start, now=start + timedelta(hours=71, minutes=59), first_booking_accepted_at=None)
    assert not attribution_window_open(window_started_at=start, now=start + timedelta(hours=72), first_booking_accepted_at=None)
    assert not attribution_window_open(window_started_at=start, now=start + timedelta(hours=1), first_booking_accepted_at=start)
    with pytest.raises(DomainError) as exc:
        _attr(window_open=False)
    assert exc.value.code is ErrorCode.REFERRAL_WINDOW_CLOSED


def test_acquisition_is_unique_per_identity_and_family() -> None:
    # passenger and parcel client campaigns share one family -> one "new client" reward per person
    assert acquisition_key("h2", "client_acquisition") == acquisition_key("h2", "client_acquisition")
    assert acquisition_key("h2", "client_acquisition") != acquisition_key("h2", "driver_acquisition")


def test_recycled_phone_match_only_reviews_the_new_user_reward() -> None:
    assert identity_match_effect(matched_previous_account=True) == "review_acquisition_reward"
    assert identity_match_effect(matched_previous_account=False) == "none"


def test_grant_and_event_keys_are_deterministic() -> None:
    """QA #5/#20 (contract half): a retried or parallel worker computes the same unique key."""
    a = reward_key(campaign_version_id=7, attribution_id=11, side="referee")
    assert a == reward_key(campaign_version_id=7, attribution_id=11, side="referee")
    assert a != reward_key(campaign_version_id=7, attribution_id=11, side="referrer")
    assert reward_key(campaign_version_id=7, attribution_id=11, side="referrer", milestone=5) != reward_key(
        campaign_version_id=7, attribution_id=11, side="referrer", milestone=10)
    assert qualification_event_key(kind="booking_captured", booking_id=3) == "qual:booking_captured:3"
    with pytest.raises(ValueError):
        reward_key(campaign_version_id=7, attribution_id=11, side="both")


# --- qualification (Q109, Q110, QA #3, #4, #18) ------------------------------------------------------------


def _facts(**overrides) -> QualificationFacts:
    kw = dict(booking_id=1, trip_id=1, service_type=ServiceType.PASSENGER, client_user_id=2, driver_user_id=9,
              service_completed_at=NOW, cash_confirmed_at=NOW + timedelta(hours=1),
              commission_captured_at=NOW + timedelta(minutes=5), net_commission_captured_minor=12_000,
              open_dispute=False, cancelled_or_refunded=False)
    kw.update(overrides)
    return QualificationFacts(**kw)


def _evaluate(facts, now=NOW + timedelta(hours=50), referrer=1):
    return evaluate_qualification(facts, now=now, referrer_user_id=referrer)


def test_qualified_after_the_risk_window_from_the_latest_condition() -> None:
    facts = _facts()
    assert _evaluate(facts, now=NOW + timedelta(hours=48, minutes=30)).verdict is QualificationVerdict.WAIT
    result = _evaluate(facts, now=NOW + timedelta(hours=49))
    assert result.verdict is QualificationVerdict.QUALIFIED
    assert result.ready_at == NOW + timedelta(hours=49)  # cash confirmation was the last condition


def test_registration_alone_never_qualifies() -> None:
    """QA #3: nothing happened yet -> not eligible."""
    facts = _facts(service_completed_at=None, cash_confirmed_at=None, commission_captured_at=None, net_commission_captured_minor=0)
    assert _evaluate(facts).verdict is QualificationVerdict.NOT_ELIGIBLE


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"cancelled_or_refunded": True}, "cancelled_or_refunded"),
        ({"cash_confirmed_at": None}, "cash_not_confirmed"),
        ({"commission_captured_at": None}, "commission_not_captured"),
        ({"net_commission_captured_minor": 0}, "no_net_commission"),  # 0% or discounted to zero
        ({"open_dispute": True}, "open_dispute"),
        ({"driver_user_id": 1}, "served_by_referrer"),
    ],
)
def test_ineligible_services_give_nothing(overrides, reason) -> None:
    """QA #4."""
    result = _evaluate(_facts(**overrides))
    assert result.verdict is QualificationVerdict.NOT_ELIGIBLE
    assert reason in result.reasons


def test_shared_ip_alone_is_not_fraud() -> None:
    """QA #18: one shared IP - even with the network derived from it - is one piece of context, not a verdict."""
    ip = (PromoRiskSignal.SHARED_IP,)
    assert _evaluate(_facts(risk_signals=ip)).verdict is QualificationVerdict.QUALIFIED
    correlated = (PromoRiskSignal.SHARED_IP, PromoRiskSignal.SHARED_NETWORK)
    assert _evaluate(_facts(risk_signals=correlated)).verdict is QualificationVerdict.QUALIFIED


def test_independent_context_or_strong_evidence_goes_to_a_person() -> None:
    independent = (PromoRiskSignal.SHARED_IP, PromoRiskSignal.SHARED_DEVICE)
    result = _evaluate(_facts(risk_signals=independent))
    assert result.verdict is QualificationVerdict.REVIEW and "independent_context_signals" in result.reasons
    strong = _evaluate(_facts(risk_signals=(PromoRiskSignal.KYC_REUSE,)))
    assert strong.verdict is QualificationVerdict.REVIEW
    assert strong.risk_ruleset_version == RISK_RULESET_V1.version


def test_eligibility_breach_rejects_the_candidate_only() -> None:
    result = _evaluate(_facts(client_user_id=9))  # client == driver
    assert result.verdict is QualificationVerdict.NOT_ELIGIBLE and "self_dealing" in result.reasons
    assert assess_risk([PromoRiskSignal.SELF_REFERRAL]).outcome is RiskOutcome.REJECT


def test_replayed_event_never_counts_against_anyone() -> None:
    assert assess_risk([PromoRiskSignal.EVENT_REPLAY, PromoRiskSignal.SHARED_IP]).outcome is RiskOutcome.CLEAR


def test_every_signal_has_a_versioned_sourced_rule() -> None:
    """Q113: source, reliability and consequence are written down for every signal."""
    assert set(RISK_RULESET_V1.rules) == set(PromoRiskSignal)
    for rule in RISK_RULESET_V1.rules.values():
        assert rule.source and rule.correlation_group
        if rule.consequence is RiskConsequence.REJECT:
            assert rule.reliability is RiskReliability.ELIGIBILITY
    assert RISK_RULESET_V1.rules[PromoRiskSignal.SHARED_IP].correlation_group == \
        RISK_RULESET_V1.rules[PromoRiskSignal.SHARED_NETWORK].correlation_group


def test_a_ruleset_cannot_let_suspicion_reject_or_one_signal_review() -> None:
    rules = dict(RISK_RULESET_V1.rules)
    rules[PromoRiskSignal.SHARED_IP] = RiskRule(PromoRiskSignal.SHARED_IP, "ip", RiskReliability.WEAK, RiskConsequence.REJECT, "network")
    with pytest.raises(ValueError):
        RiskRuleset("bad", rules, 2)
    with pytest.raises(ValueError):
        RiskRuleset("bad", dict(RISK_RULESET_V1.rules), 1)


def test_review_has_a_deadline() -> None:
    assert review_due_at(NOW, timedelta(hours=72)) == NOW + timedelta(hours=72)
    with pytest.raises(ValueError):
        review_due_at(NOW, timedelta(0))


def test_many_bookings_on_one_trip_are_one_milestone_trip() -> None:
    """QA #17."""
    evidence = [MilestoneEvidence(trip_id=1, booking_id=b, client_user_id=100 + b, qualified=True) for b in range(4)]
    evidence += [MilestoneEvidence(trip_id=2, booking_id=9, client_user_id=100, qualified=True)]
    evidence += [MilestoneEvidence(trip_id=3, booking_id=10, client_user_id=555, qualified=True, client_linked_to_referral=True)]
    evidence += [MilestoneEvidence(trip_id=4, booking_id=11, client_user_id=556, qualified=False)]
    progress = milestone_progress(evidence)
    assert progress == MilestoneProgress(distinct_trips=2, distinct_clients=4)


def test_milestones_need_distinct_clients_too() -> None:
    assert milestones_reached(MilestoneProgress(10, 10), (5, 10), min_distinct_clients=5) == (5, 10)
    assert milestones_reached(MilestoneProgress(10, 2), (5, 10), min_distinct_clients=5) == ()
    assert milestones_reached(MilestoneProgress(6, 5), (5, 10), min_distinct_clients=5) == (5,)


def _shipment(booking_id, trip_id=1, *, minutes=0, receiver="r1", pickup=10, dropoff=20, **overrides):
    kw = dict(booking_id=booking_id, trip_id=trip_id, client_user_id=2, qualified=True,
              booked_at=NOW + timedelta(minutes=minutes), pickup_stop_id=pickup, dropoff_stop_id=dropoff,
              receiver_key=receiver)
    kw.update(overrides)
    return ServiceEvidence(**kw)


def test_two_boxes_in_one_booking_are_one_shipment() -> None:
    progress = client_referral_progress(ServiceType.PARCEL, [_shipment(1), _shipment(1)])
    assert (progress.counted, progress.required, progress.complete) == (1, 2, False)


def test_two_real_shipments_on_one_trip_both_count() -> None:
    """Q113: one car does not merge two independent shipments."""
    progress = client_referral_progress(ServiceType.PARCEL, [_shipment(1, receiver="r1"), _shipment(2, receiver="r2", minutes=5)])
    assert progress.complete and progress.risk_signals == ()
    later = client_referral_progress(ServiceType.PARCEL, [_shipment(1), _shipment(2, minutes=240)])
    assert later.complete and later.risk_signals == ()


def test_a_shipment_split_for_the_reward_goes_to_review_not_exclusion() -> None:
    progress = client_referral_progress(ServiceType.PARCEL, [_shipment(1), _shipment(2, minutes=10)])
    assert progress.counted == 2
    assert progress.risk_signals == (PromoRiskSignal.SPLIT_SHIPMENT,)
    assert assess_risk(progress.risk_signals).outcome is RiskOutcome.REVIEW


@pytest.mark.parametrize("missing", ["handover_recorded", "delivery_recorded", "commission_captured"])
def test_a_shipment_without_its_own_records_does_not_count(missing) -> None:
    progress = client_referral_progress(ServiceType.PARCEL, [_shipment(1), _shipment(2, trip_id=2, **{missing: False})])
    assert progress.counted == 1


def test_passenger_referral_needs_one_booking() -> None:
    assert client_referral_progress(ServiceType.PASSENGER, [_shipment(1)]).complete


def test_referrer_served_booking_does_not_close_the_referral() -> None:
    """Q112: the first booking was with the inviting driver - it does not count, but the referral stays open."""
    attributed_at = NOW - timedelta(days=5)
    deadline = qualification_deadline(attributed_at, timedelta(days=30))
    first = _evaluate(_facts(booking_id=1, driver_user_id=1), referrer=1)
    assert first.verdict is QualificationVerdict.NOT_ELIGIBLE and first.reasons == ("served_by_referrer",)
    assert referral_can_still_qualify(now=NOW, deadline=deadline, attribution_status="attributed")
    second = _evaluate(_facts(booking_id=2, driver_user_id=9), referrer=1)
    assert second.verdict is QualificationVerdict.QUALIFIED
    assert not referral_can_still_qualify(now=deadline, deadline=deadline, attribution_status="attributed")


def test_attribution_window_and_qualification_period_are_different_things() -> None:
    attributed_at = NOW
    assert qualification_deadline(attributed_at, timedelta(days=30)) - attributed_at != ATTRIBUTION_WINDOW


# --- lifecycles ---------------------------------------------------------------------------------------------


def test_promo_lifecycles_are_separate_and_terminal_where_money_is_final() -> None:
    assert len(PROMO_MACHINES) == 6
    assert REFERRAL_ATTRIBUTION.terminal == {"qualified", "expired"}
    assert PROMO_ENROLLMENT.terminal == {"granted", "released"}
    assert PROMO_OBLIGATION.terminal == {"granted", "released"}
    assert PROMO_REWARD.terminal == {"exhausted", "reversed"}
    assert PROMO_REDEMPTION.terminal == {"consumed", "released"}
    assert PROMO_CAMPAIGN.terminal == {"closed"}


def test_consumed_value_never_becomes_spendable_again() -> None:
    assert not PROMO_REDEMPTION.is_allowed("consumed", "reserved")
    assert not PROMO_REWARD.is_allowed("exhausted", "available")
    assert not PROMO_REWARD.is_allowed("reversed", "available")


def test_pause_does_not_touch_rewards_and_a_campaign_cannot_restart_from_closed() -> None:
    assert PROMO_CAMPAIGN.is_allowed_by("active", "paused", "budget_exhausted")
    assert not PROMO_CAMPAIGN.is_allowed("closed", "active")
    # no promo machine mentions booking or commission states
    promo_states = {state.value for m in PROMO_MACHINES for state in m.states}
    assert not promo_states & {"held", "captured", "completed", "cancelled"}


def test_weak_signal_never_rejects_automatically() -> None:
    commands = {t.command for t in REFERRAL_ATTRIBUTION.transitions if t.target == "rejected"}
    assert commands == {"reject"}  # a person's decision; there is no automatic fraud_reject


# --- G14: a plain reduction never goes below spent + outstanding obligations ------------------------------------------


def test_g14_reduction_stops_exactly_at_spent_plus_obligations() -> None:
    budget = BudgetPosition(allocated_minor=10_000).promise(4_000).grant(4_000, 4_000).consume(1_500).promise(2_000)
    # S = 1 500, L = promised 2 000 + granted 2 500 (reserved-on-bookings is inside granted) -> reducible 4 000
    assert budget.reducible_minor() == 4_000
    at_floor = budget.reduce_allocation(4_000)
    assert at_floor.allocated_minor == at_floor.committed_minor == 6_000 and at_floor.shortfall_minor == 0
    with pytest.raises(DomainError) as exc:
        budget.reduce_allocation(4_001)
    assert exc.value.code is ErrorCode.PROMO_BUDGET_BELOW_COMMITMENT
    assert exc.value.details == {"requested_minor": 4_001, "reducible_minor": 4_000}


def test_g14_pending_approved_reinstatements_are_obligations_too() -> None:
    budget = BudgetPosition(allocated_minor=10_000).promise(4_000)
    assert budget.reducible_minor(pending_reinstatements_minor=1_000) == 5_000
    with pytest.raises(DomainError):
        budget.reduce_allocation(5_001, pending_reinstatements_minor=1_000)
    assert budget.reducible_minor(pending_reinstatements_minor=7_000) == 0  # never negative


def test_g14_a_funding_loss_is_apart_and_cancels_nothing() -> None:
    budget = BudgetPosition(allocated_minor=10_000).promise(8_000).grant(3_000, 3_000).consume(1_000)
    lost = budget.record_funding_loss(9_000)
    assert (lost.shortfall_minor, lost.promised_minor, lost.granted_minor, lost.consumed_minor) == (7_000, 5_000, 2_000, 1_000)
    assert not lost.accepts_new_enrollments(1) and lost.reducible_minor() == 0
    with pytest.raises(ValueError):
        budget.record_funding_loss(10_001)
