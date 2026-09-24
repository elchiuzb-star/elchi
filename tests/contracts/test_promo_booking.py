"""Pure contract of the stage-4 booking integration (ADR-0023 §18, Q104, Q110, Q116, Q120). SYNTHETIC numbers only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.contracts.promo import (
    CASH_TIME_UNVERIFIED,
    PROMO_SNAPSHOT_KEY,
    PaymentTiming,
    PromoMarginPolicy,
    PromoSnapshotState,
    QualificationResult,
    QualificationVerdict,
    amendment_reconfirmation,
    awaiting_capture,
    booking_promo_marker,
    payment_timing,
    plain_quote,
    promo_snapshot_state,
    quote_from_terms,
    quote_promo,
    service_in_time,
    strictest_margin_policy,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
DEADLINE = T0 + timedelta(days=30)
POLICY = PromoMarginPolicy(
    max_discount_share_bps=5_000, max_discount_per_booking_minor=1_500_000,
    passenger_bonus_max_per_booking_minor=1_000_000, driver_credit_max_per_booking_minor=1_000_000,
    variable_cost_fixed_minor=100_000, variable_cost_bps=0, min_margin_minor=100_000,
)


# --- the synthetic example (task stage 4) -----------------------------------------------------------------------


def test_synthetic_example_numbers() -> None:
    quote = quote_promo(fare_minor=20_000_000, fee_bps=1_000, policy=POLICY, passenger_bonus_requested_minor=500_000,
                        passenger_bonus_available_minor=500_000, driver_credit_available_minor=300_000)
    assert (quote.cash_due_minor, quote.net_commission_minor, quote.driver_keeps_minor) == (19_500_000, 1_200_000, 18_300_000)
    again = quote_from_terms(fare_minor=20_000_000, fee_bps=1_000, base_commission_minor=2_000_000,
                             passenger_bonus_minor=500_000, driver_credit_minor=300_000, cash_due_minor=19_500_000,
                             net_commission_minor=1_200_000, variable_cost_minor=100_000, min_margin_minor=100_000,
                             contract_version=1)
    assert again.fingerprint == quote.fingerprint


def test_a_stored_row_that_breaks_an_identity_is_refused() -> None:
    with pytest.raises(ValueError):
        quote_from_terms(fare_minor=20_000_000, fee_bps=1_000, base_commission_minor=2_000_000,
                         passenger_bonus_minor=500_000, driver_credit_minor=300_000, cash_due_minor=20_000_000,  # F, not F_cash
                         net_commission_minor=1_200_000, variable_cost_minor=100_000, min_margin_minor=100_000,
                         contract_version=1)
    with pytest.raises(ValueError):  # C does not match F and bps
        quote_from_terms(fare_minor=20_000_000, fee_bps=1_000, base_commission_minor=2_100_000,
                         passenger_bonus_minor=0, driver_credit_minor=0, cash_due_minor=20_000_000,
                         net_commission_minor=2_100_000, variable_cost_minor=None, min_margin_minor=None,
                         contract_version=1)


# --- marker: legacy vs broken ------------------------------------------------------------------------------------


def test_only_an_absent_marker_is_legacy() -> None:
    assert promo_snapshot_state({"flags": {}}) is PromoSnapshotState.LEGACY
    assert promo_snapshot_state(None) is PromoSnapshotState.LEGACY
    assert promo_snapshot_state({PROMO_SNAPSHOT_KEY: booking_promo_marker(applied=False)}) is PromoSnapshotState.PLAIN
    assert promo_snapshot_state({PROMO_SNAPSHOT_KEY: booking_promo_marker(applied=True)}) is PromoSnapshotState.APPLIED
    for broken in ({}, {"applied": "true", "contract_version": 1}, {"applied": True}, None, [],
                   {"applied": True, "contract_version": 0}, {"applied": True, "contract_version": 1, "extra": 1}):
        with pytest.raises(ValueError):
            promo_snapshot_state({PROMO_SNAPSHOT_KEY: broken})


def test_plain_quote_is_p_h_zero() -> None:
    quote = plain_quote(fare_minor=20_000_000, fee_bps=1_000)
    assert (quote.passenger_bonus_minor, quote.driver_credit_minor, quote.cash_due_minor, quote.net_commission_minor) == (
        0, 0, 20_000_000, 2_000_000)
    assert plain_quote(fare_minor=20_000_000, fee_bps=0).net_commission_minor == 0


# --- several campaigns on one booking -----------------------------------------------------------------------------


def test_strictest_policy_keeps_every_campaigns_limits_and_never_fills_an_unset_value() -> None:
    other = PromoMarginPolicy(
        max_discount_share_bps=3_000, max_discount_per_booking_minor=2_000_000,
        passenger_bonus_max_per_booking_minor=400_000, driver_credit_max_per_booking_minor=2_000_000,
        variable_cost_fixed_minor=50_000, variable_cost_bps=100, min_margin_minor=200_000,
    )
    combined = strictest_margin_policy([POLICY, other])
    assert combined == PromoMarginPolicy(3_000, 1_500_000, 400_000, 1_000_000, 100_000, 100, 200_000)
    unset = PromoMarginPolicy(None, 1, 1, 1, 1, 1, 1)
    assert strictest_margin_policy([POLICY, unset]).max_discount_share_bps is None
    assert strictest_margin_policy([]) is None


# --- amendments (Q116): F down can raise F_cash above "F minus the old discount" ---------------------------------------


def test_lower_fare_lowers_the_discount_and_needs_both_confirmations() -> None:
    old = quote_promo(fare_minor=20_000_000, fee_bps=1_000, policy=POLICY, passenger_bonus_requested_minor=500_000,
                      passenger_bonus_available_minor=500_000, driver_credit_available_minor=300_000)
    new = quote_promo(fare_minor=8_000_000, fee_bps=1_000, policy=POLICY, passenger_bonus_requested_minor=500_000,
                      passenger_bonus_available_minor=500_000, driver_credit_available_minor=300_000)
    assert (new.passenger_bonus_minor, new.driver_credit_minor, new.cash_due_minor) == (400_000, 0, 7_600_000)
    assert new.cash_due_minor > new.fare_minor - old.passenger_bonus_minor  # the client pays more than it would assume
    reconfirm = amendment_reconfirmation(old, new)
    assert reconfirm.client and reconfirm.driver


# --- Q120: timeliness --------------------------------------------------------------------------------------------------


def test_service_must_be_completed_inside_the_period() -> None:
    assert service_in_time(DEADLINE, DEADLINE)
    assert not service_in_time(DEADLINE + timedelta(seconds=1), DEADLINE)
    assert not service_in_time(None, DEADLINE)


@pytest.mark.parametrize(
    ("confirmed", "confirmed_at", "recorded_at", "expected"),
    [
        (False, None, None, PaymentTiming.MISSING),
        (True, DEADLINE, DEADLINE, PaymentTiming.IN_TIME),
        (True, DEADLINE + timedelta(hours=1), DEADLINE - timedelta(hours=1), PaymentTiming.UNVERIFIED),  # unclear
        (True, DEADLINE + timedelta(hours=1), DEADLINE + timedelta(minutes=30), PaymentTiming.LATE),
        (True, None, DEADLINE - timedelta(days=1), PaymentTiming.UNVERIFIED),  # confirmed state, no confirming record
    ],
)
def test_payment_time_comes_from_server_records_only(confirmed, confirmed_at, recorded_at, expected) -> None:  # noqa: ANN001
    assert payment_timing(deadline=DEADLINE, cash_confirmed=confirmed, confirmed_at=confirmed_at,
                          first_recorded_at=recorded_at) is expected


def test_only_a_missing_capture_with_an_open_hold_waits() -> None:
    missing = QualificationResult(QualificationVerdict.NOT_ELIGIBLE, ("commission_not_captured", "no_net_commission"))
    assert awaiting_capture(missing, hold_open=True)
    assert not awaiting_capture(missing, hold_open=False)  # released / exempt: no capture will ever come
    other = QualificationResult(QualificationVerdict.NOT_ELIGIBLE, ("commission_not_captured", "served_by_referrer"))
    assert not awaiting_capture(other, hold_open=True)


def test_late_platform_capture_does_not_disqualify_an_in_time_service() -> None:
    """Q120 through the module's own judge: completion and cash inside the period, capture after it."""
    from app.modules.promotions.qualification import BookingEvidence, _judge

    enrollment = SimpleNamespace(qualification_deadline=DEADLINE, referrer_user_id=99)
    evidence = BookingEvidence(
        booking_id=1, trip_id=1, service_type="passenger", client_user_id=2, driver_user_id=3, created_at=T0,
        completed_at=DEADLINE - timedelta(days=1), cash_confirmed_at=DEADLINE - timedelta(days=1),
        captured_at=DEADLINE + timedelta(days=3), net_captured_minor=1_200_000, open_dispute=False,
        cancelled_or_refunded=False, handover_at=None, delivery_at=None, pickup_stop_id=None, dropoff_stop_id=None,
        cash_status_confirmed=True, cash_first_recorded_at=DEADLINE - timedelta(days=1), hold_open=False,
    )
    judged = _judge(evidence, enrollment, now=DEADLINE + timedelta(days=6))
    assert judged is not None and judged.ready and not judged.unverified_cash
    assert judged.result.ready_at == DEADLINE + timedelta(days=5)  # 48 h after the (late) capture, not before
    waiting = _judge(evidence.__class__(**{**evidence.__dict__, "captured_at": None, "net_captured_minor": 0,
                                           "hold_open": True}), enrollment, now=DEADLINE + timedelta(days=6))
    assert waiting is not None and waiting.awaiting_capture and not waiting.ready
    late_cash = evidence.__class__(**{**evidence.__dict__, "cash_confirmed_at": DEADLINE + timedelta(hours=1),
                                      "cash_first_recorded_at": DEADLINE + timedelta(minutes=5)})
    assert _judge(late_cash, enrollment, now=DEADLINE + timedelta(days=6)) is None  # the client's own condition late
    unclear = evidence.__class__(**{**evidence.__dict__, "cash_confirmed_at": DEADLINE + timedelta(hours=1)})
    assert _judge(unclear, enrollment, now=DEADLINE + timedelta(days=6)).unverified_cash  # -> review
    assert CASH_TIME_UNVERIFIED == "cash_time_unverified"


def test_client_promo_objects_have_no_commission_keys_and_driver_objects_match_the_driver_view() -> None:
    """Q16/Q103: one object per role - the client's promo objects carry only CLIENT_PROMO_VIEW_KEYS (no null
    commission keys), the driver's exactly DRIVER_PROMO_VIEW_KEYS."""
    from app.contracts.promo import CLIENT_PROMO_VIEW_KEYS, DRIVER_PROMO_VIEW_KEYS
    from app.modules.bookings.schemas import BookingClientDTO, BookingPromoClientDTO, BookingPromoDriverDTO
    from app.modules.marketplace.schemas import ProposalPromoClientDTO, ProposalPromoDriverDTO

    for model in (BookingPromoClientDTO, ProposalPromoClientDTO):
        assert set(model.model_fields) - {"view"} == CLIENT_PROMO_VIEW_KEYS
    for model in (BookingPromoDriverDTO, ProposalPromoDriverDTO):
        assert set(model.model_fields) - {"view"} == DRIVER_PROMO_VIEW_KEYS
    assert BookingClientDTO.model_fields["promo"].annotation == BookingPromoClientDTO | None


# --- T4 decisions (Q123, Q129) -------------------------------------------------------------------------------------


def test_q123_combination_needs_an_approved_basis_and_never_loses_a_cost() -> None:
    from dataclasses import replace

    from app.contracts.promo import CostBasis, campaign_pair, combined_margin_policy

    driver_side = replace(POLICY, variable_cost_fixed_minor=1_200_000, variable_cost_bps=50,
                          max_discount_per_booking_minor=400_000, passenger_bonus_max_per_booking_minor=0,
                          driver_credit_max_per_booking_minor=250_000, min_margin_minor=150_000)
    assert combined_margin_policy(POLICY, None, None) is POLICY  # one campaign: its own policy
    assert combined_margin_policy(None, driver_side, None) is driver_side
    with pytest.raises(ValueError):  # an unapproved pair is never combined automatically
        combined_margin_policy(POLICY, driver_side, None)
    shared = combined_margin_policy(POLICY, driver_side, CostBasis.SHARED)
    additive = combined_margin_policy(POLICY, driver_side, "additive")
    for combined in (shared, additive):
        assert combined.max_discount_per_booking_minor == 400_000  # the strictest total cap
        assert combined.passenger_bonus_max_per_booking_minor == POLICY.passenger_bonus_max_per_booking_minor  # P's own
        assert combined.driver_credit_max_per_booking_minor == 250_000  # H's own
        assert combined.min_margin_minor == 150_000
    assert (shared.variable_cost_fixed_minor, shared.variable_cost_bps) == (1_200_000, 50)  # the same cost: the larger
    assert (additive.variable_cost_fixed_minor, additive.variable_cost_bps) == (1_300_000, 50)  # separate costs: both
    unset = replace(driver_side, variable_cost_bps=None)
    assert combined_margin_policy(POLICY, unset, "shared").variable_cost_bps is None  # never filled from the other side
    assert campaign_pair(9, 4) == (4, 9)
    with pytest.raises(ValueError):
        campaign_pair(4, 4)


def test_q129_each_holder_is_judged_on_its_own_cause() -> None:
    from app.contracts.enums import PromoFault, PromoInstrument
    from app.contracts.promo import holder_at_fault, restored_expiry

    expires, released, grace = T0, T0 + timedelta(hours=1), timedelta(days=7)
    p, h = PromoInstrument.PASSENGER_BONUS, PromoInstrument.DRIVER_CREDIT
    assert holder_at_fault(PromoFault.CLIENT, p) and not holder_at_fault(PromoFault.CLIENT, h)
    assert holder_at_fault(PromoFault.DRIVER, h) and not holder_at_fault(PromoFault.DRIVER, p)
    for cause in (PromoFault.PLATFORM, PromoFault.NONE, PromoFault.UNDETERMINED):  # nobody loses a right by these
        for instrument in (p, h):
            assert not holder_at_fault(cause, instrument)
            assert restored_expiry(lot_expires_at=expires, released_at=released, fault=cause, grace=grace,
                                   instrument=instrument) == released + grace
    assert restored_expiry(lot_expires_at=expires, released_at=released, fault=PromoFault.CLIENT, grace=grace,
                           instrument=h) == released + grace  # the client's cancel does not cost the driver its credit
    assert restored_expiry(lot_expires_at=expires, released_at=released, fault=PromoFault.DRIVER, grace=grace,
                           instrument=h) is None


def test_q123_clarified_the_chooser_separates_partial_h_from_pairs_that_never_meet() -> None:
    from dataclasses import replace

    from app.contracts.promo import DriverCreditOutcome, FundingSource, choose_driver_source, combined_margin_policy

    p_src = FundingSource(1, 500_000, (0, 1))
    fare, bps = 20_000_000, 1_000  # C = 2 000 000; SYNTHETIC

    def run(h_available: int, *, h_policy=POLICY, approved: bool = True):  # noqa: ANN001, ANN202
        def pairing(_p, _h):  # noqa: ANN001, ANN202
            return (combined_margin_policy(POLICY, h_policy, "shared"), "shared") if approved else None

        return choose_driver_source(p_source=p_src, h_sources=[FundingSource(2, h_available, (0, 2))], pairing=pairing,
                                    consent=None, subject="v", now=T0, fare_minor=fare, fee_bps=bps)

    # consent=None keeps these pure: P comes from the consent in the real flow; here no consented P is at stake
    src, basis, quote, outcome = run(300_000)
    assert outcome is DriverCreditOutcome.APPLIED and quote.driver_credit_minor == 300_000 and basis == "shared"
    src, basis, quote, outcome = run(900_000, h_policy=replace(POLICY, driver_credit_max_per_booking_minor=400_000))
    assert outcome is DriverCreditOutcome.PARTIAL and quote.driver_credit_minor == 400_000  # what is left, not all
    assert run(300_000, approved=False)[3] is DriverCreditOutcome.NOT_APPROVED
    assert choose_driver_source(p_source=p_src, h_sources=[], pairing=lambda p, h: None, consent=None, subject="v",
                                now=T0, fare_minor=fare, fee_bps=bps)[3] is DriverCreditOutcome.NONE


def test_q123_clarified_combining_never_lowers_a_consented_p() -> None:
    from dataclasses import replace

    from app.contracts.promo import (
        DriverCreditOutcome, FundingSource, PassengerBonusConsent, choose_driver_source, combined_margin_policy)

    consent = PassengerBonusConsent(proposal_version_id="v", fare_minor=20_000_000, passenger_bonus_minor=500_000,
                                    cash_due_minor=19_500_000, quote_fingerprint="", expires_at=T0 + timedelta(days=1))
    tight = replace(POLICY, max_discount_per_booking_minor=400_000)  # the H campaign's total cap is below the agreed P
    result = choose_driver_source(
        p_source=FundingSource(1, 500_000, (0, 1)), h_sources=[FundingSource(2, 300_000, (0, 2))],
        pairing=lambda p, h: (combined_margin_policy(POLICY, tight, "shared"), "shared"), consent=consent, subject="v",
        now=T0, fare_minor=20_000_000, fee_bps=1_000)
    assert result == (None, None, None, DriverCreditOutcome.WOULD_REDUCE_P)
    # with room left after P, H takes only that room - partial, and P stays exactly as agreed
    roomy = replace(POLICY, max_discount_per_booking_minor=700_000)
    src, basis, quote, outcome = choose_driver_source(
        p_source=FundingSource(1, 500_000, (0, 1)), h_sources=[FundingSource(2, 300_000, (0, 2))],
        pairing=lambda p, h: (combined_margin_policy(POLICY, roomy, "shared"), "shared"), consent=consent, subject="v",
        now=T0, fare_minor=20_000_000, fee_bps=1_000)
    assert outcome is DriverCreditOutcome.PARTIAL
    assert (quote.passenger_bonus_minor, quote.driver_credit_minor) == (500_000, 200_000)
