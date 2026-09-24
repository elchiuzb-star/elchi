"""The stage-6 simulator against the real PostgreSQL service flow (ADR-0023 §20).

The simulator never has a second formula: ``simulation.engine.booking_terms`` must give exactly the terms that
``bookings.service.accept_proposal`` writes to ``promo_booking_terms`` and ``promo_redemptions`` - P, H, F_cash,
C_net, O, M, the campaigns and the lots - for the same lots, policies and pairings. Budget stages (promise -> grant)
must move ``promo_budgets`` exactly as ``BudgetPosition`` moves in the simulator. SYNTHETIC values only.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from app.contracts.enums import PromoCampaignKind, PromoInstrument
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.promo import BudgetPosition, PromoMarginPolicy, campaign_pair
from app.contracts.timeutil import utc_now
from app.modules.promotions import service as promo_service
from app.modules.promotions.simulation.engine import LotView, booking_terms
from tests.pg.bookings.conftest import BW, bw  # noqa: F401
from tests.pg.promotions.booking_world import BPS, FARE, H_LOT, P_LOT, PW, use_policy
from tests.pg.promotions.conftest import SYNTH_POLICY
from tests.pg.promotions.referral_world import Ref, enable_promotions

pytestmark = pytest.mark.pg

DRIVER_CLIENT = PromoCampaignKind.REFERRAL_DRIVER_CLIENT


@pytest.fixture
def pw(bw: BW, promo) -> PW:  # noqa: F811
    enable_promotions(promo.pg_db)
    use_policy(bw, BPS)
    return PW(bw, Ref(promo))


# case -> (P lot or None, H lot or None, H campaign policy changes, pairing basis or None)
CASES = {
    "p_only": (P_LOT, None, {}, None),
    "h_only": (None, H_LOT, {}, None),
    "p_and_h_shared": (P_LOT, H_LOT, {}, "shared"),
    "p_and_h_never_paired": (P_LOT, H_LOT, {}, None),
    "h_partial_after_p": (P_LOT, 900_000, {"max_discount_per_booking_minor": 700_000}, "shared"),
    "additive_cost": (P_LOT, H_LOT, {"variable_cost_fixed_minor": 1_200_000}, "additive"),
    "p_capped_by_policy": (2_000_000, None, {}, None),
}


def _view(pw: PW, lot_id: int) -> LotView:
    row = pw.lot_row(lot_id)
    available = (row["amount_minor"] - row["reserved_minor"] - row["consumed_minor"] - row["expired_minor"]
                 - row["reversed_minor"])
    return LotView(lot_id, row["campaign_id"], available, row["expires_at"].timestamp())


@pytest.mark.parametrize("case", list(CASES))
def test_simulator_booking_terms_equal_the_real_accept(pw: PW, case: str) -> None:
    p_amount, h_amount, h_policy, basis = CASES[case]
    client, driver = pw.ref.client(), pw.bw.w.driver_id
    policies: dict[int, PromoMarginPolicy] = {}
    p_lot = h_lot = None
    if p_amount is not None:
        p_lot = pw.lot(client, PromoInstrument.PASSENGER_BONUS, p_amount)
        policies[pw.lot_row(p_lot)["campaign_id"]] = SYNTH_POLICY
    if h_amount is not None:
        policy = replace(SYNTH_POLICY, **h_policy)
        campaign = pw.ref.campaign(kind=DRIVER_CLIENT, margin_policy=policy)
        h_lot = pw.lot(driver, PromoInstrument.DRIVER_CREDIT, h_amount, campaign=campaign)
        policies[campaign] = policy
    combinations = {}
    if basis is not None:
        pw.combine(p_lot, h_lot, basis)
        combinations[campaign_pair(*(pw.lot_row(lot)["campaign_id"] for lot in (p_lot, h_lot)))] = basis

    sim = booking_terms(fare_minor=FARE, fee_bps=BPS, p_lots=[_view(pw, p_lot)] if p_lot else [],
                        h_lots=[_view(pw, h_lot)] if h_lot else [], policies=policies, combinations=combinations,
                        uses_bonus=p_lot is not None, now=utc_now())
    q = sim.quote
    _, ref = pw.offer(client, driver)
    # the client consents to exactly what the simulator predicts the client's card shows
    consent = (q.passenger_bonus_minor, q.cash_due_minor) if q.passenger_bonus_minor else None
    booking = pw.accept(ref, client, consent=consent)

    rows = pw.terms(booking.id)
    if not q.promo_applied:
        assert rows == [] or (rows[0]["passenger_bonus_minor"], rows[0]["driver_credit_minor"]) == (0, 0)
        return
    [row] = rows
    assert (row["passenger_bonus_minor"], row["driver_credit_minor"], row["cash_due_minor"],
            row["net_commission_minor"], row["variable_cost_minor"], row["min_margin_minor"]) == (
        q.passenger_bonus_minor, q.driver_credit_minor, q.cash_due_minor, q.net_commission_minor,
        q.variable_cost_minor, q.min_margin_minor), case
    assert (row["passenger_campaign_id"], row["driver_campaign_id"], row["combination_cost_basis"]) == (
        sim.passenger_campaign_id, sim.driver_campaign_id, sim.cost_basis), case
    assert sorted((lot, amount) for lot, amount, _, _ in pw.redemptions(booking.id)) == sorted(sim.allocations), case
    # the identities the report checks, on the real row
    assert row["cash_due_minor"] == FARE - row["passenger_bonus_minor"]
    assert row["net_commission_minor"] == FARE * BPS // 10_000 - row["passenger_bonus_minor"] - row["driver_credit_minor"]
    assert pw.ref.promo.issues() == []


def test_budget_stages_move_the_database_exactly_as_the_simulator(pw: PW) -> None:
    """promise -> grant is one obligation: the DB budget cache (written only by the ledger trigger) and the
    simulator's BudgetPosition agree after every step, and both refuse a promise the allocation cannot hold."""
    allocation = 1_000_000
    campaign = pw.ref.campaign(allocate_minor=allocation)
    sim = BudgetPosition(allocated_minor=allocation)

    def same() -> None:
        db = pw.ref.promo.budget(campaign)
        assert (db.allocated_minor, db.promised_minor, db.granted_minor, db.consumed_minor, db.released_minor) == (
            sim.allocated_minor, sim.promised_minor, sim.granted_minor, sim.consumed_minor, sim.released_minor)

    client = pw.ref.client()
    specs = [promo_service.RewardSpec(client, "referee", PromoInstrument.PASSENGER_BONUS, 400_000,
                                      f"sim:{uuid.uuid4().hex}") for _ in range(2)]
    obligations = pw.ref.promo.promise(campaign, specs)
    sim = sim.promise(sum(spec.amount_minor for spec in specs))  # one enrollment reserves both sides at once
    same()
    with pw.db.session() as s:
        promo_service.grant_obligation(s, obligation_id=obligations[0])
        s.commit()
    sim = sim.grant(400_000, 400_000)
    same()

    # 200 000 left: a 400 000 promise is refused by both, and nothing moves
    with pytest.raises(DomainError) as contract_exc:
        sim.promise(400_000)
    with pytest.raises(DomainError) as db_exc:
        pw.ref.promo.promise(campaign, [promo_service.RewardSpec(client, "referee", PromoInstrument.PASSENGER_BONUS,
                                                                 400_000, f"sim:{uuid.uuid4().hex}")])
    assert contract_exc.value.code is db_exc.value.code is ErrorCode.PROMO_BUDGET_EXHAUSTED
    same()
    assert pw.ref.promo.issues(campaign) == []
