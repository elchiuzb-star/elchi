"""Referral stage-2 pure rules (ADR-0023, Q106/Q108/Q117/Q118/Q119). SYNTHETIC values only."""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts.crypto import PURPOSE_PATTERN
from app.contracts.enums import PromoCampaignFamily, PromoCampaignKind, PromoInstrument, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.promo import (
    ATTRIBUTION_WINDOW,
    PROMO_IDENTITY_PURPOSE,
    REFERRAL_CODE_ALPHABET,
    REFERRAL_CODE_LENGTH,
    STALE_SCOPE,
    CampaignTerms,
    IdentityRetentionPolicy,
    PromoMarginPolicy,
    enrollment_allowed,
    enrollment_rewards,
    identity_digest,
    max_commitment_for,
    new_referral_code,
    normalize_phone,
    normalize_referral_code,
    qualification_deadline,
    quote_at_accept,
    quote_promo,
    record_consent,
    referral_family_for,
    request_fingerprint,
    terms_fingerprint,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
POLICY = PromoMarginPolicy(5_000, 1_500_000, 1_000_000, 1_000_000, 100_000, 0, 100_000)


def _terms(**overrides) -> CampaignTerms:  # noqa: ANN003
    base = dict(kind=PromoCampaignKind.REFERRAL_CLIENT_CLIENT, service_type=ServiceType.PASSENGER,
                budget_allocated_minor=10_000_000, referrer_reward_minor=300_000, referee_reward_minor=200_000,
                referrer_instrument=PromoInstrument.PASSENGER_BONUS, referee_instrument=PromoInstrument.PASSENGER_BONUS,
                milestone_thresholds=(), min_distinct_clients=None, enrollment_limit=100,
                qualification_window=timedelta(days=30), reward_validity=timedelta(days=60),
                review_sla=timedelta(hours=72), restoration_grace=timedelta(days=7), margin_policy=POLICY,
                approval_reference="SYNTHETIC")
    base.update(overrides)
    return CampaignTerms(**base)


# --- codes -------------------------------------------------------------------------------------------------------


def test_codes_are_random_from_an_unambiguous_alphabet() -> None:
    codes = {new_referral_code() for _ in range(2_000)}
    assert len(codes) == 2_000  # 31^8 space: collisions in 2 000 draws would be a generator bug
    for code in codes:
        assert len(code) == REFERRAL_CODE_LENGTH and set(code) <= set(REFERRAL_CODE_ALPHABET)
    assert not set("01OIL") & set(REFERRAL_CODE_ALPHABET)


def test_code_uses_the_csprng_not_user_data() -> None:
    """The only input is a random source; there is no parameter through which a phone or an id could enter."""
    draws = iter([0] * REFERRAL_CODE_LENGTH)
    assert new_referral_code(lambda n: next(draws)) == REFERRAL_CODE_ALPHABET[0] * REFERRAL_CODE_LENGTH
    import inspect

    assert inspect.signature(new_referral_code).parameters["randbelow"].default is secrets.randbelow


@pytest.mark.parametrize("raw,expected", [
    (" ab2c-3d4e ", "AB2C3D4E"), ("ab2c3d4e", "AB2C3D4E"), ("AB2C3D4", None), ("AB2C3D4E5", None),
    ("AB0C3D4E", None), ("", None), (None, None), ("AB2C;3D4", None),
])
def test_invalid_input_is_simply_no_code(raw, expected) -> None:
    assert normalize_referral_code(raw) == expected


# --- families, windows, deadlines ------------------------------------------------------------------------------


def test_audience_decides_the_family() -> None:
    assert referral_family_for("client") is PromoCampaignFamily.CLIENT_ACQUISITION
    assert referral_family_for("driver") is PromoCampaignFamily.DRIVER_ACQUISITION
    with pytest.raises(DomainError):
        referral_family_for("operator")


def test_three_periods_are_separate() -> None:
    """Attribution window (72 h from sign-up), qualification period (from enrollment), spend validity (lot)."""
    signed_up = NOW
    enrolled = NOW + timedelta(hours=70)
    deadline = qualification_deadline(enrolled, timedelta(days=30))
    assert deadline == enrolled + timedelta(days=30)
    assert deadline != signed_up + ATTRIBUTION_WINDOW + timedelta(days=30)


# --- protected identity (Q108) -------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("+998 90 123-45-67", "+998901234567"), ("901234567", "+998901234567"), ("998901234567", "+998901234567"),
    ("deleted:123", None), ("+7 900 123 45 67", None), ("12345", None),
])
def test_phone_normalisation(raw, expected) -> None:
    assert normalize_phone(raw) == expected


def test_digest_is_keyed_and_stable() -> None:
    key_a, key_b = b"a" * 32, b"b" * 32
    phone = "+998901234567"
    assert identity_digest(key_a, phone) == identity_digest(key_a, phone)
    assert identity_digest(key_a, phone) != identity_digest(key_b, phone)
    assert phone not in identity_digest(key_a, phone) and len(identity_digest(key_a, phone)) == 64
    with pytest.raises(ValueError):
        identity_digest(b"short", phone)
    with pytest.raises(ValueError):
        identity_digest(key_a, "90 123 45 67")  # must be normalised first
    assert PURPOSE_PATTERN.match(PROMO_IDENTITY_PURPOSE)


def test_no_fallback_without_identity_protection() -> None:
    """Q108/Q118: no key -> no enrollment anywhere; production additionally needs an approved retention period."""
    unapproved, approved = IdentityRetentionPolicy(), IdentityRetentionPolicy(timedelta(days=365))
    assert not enrollment_allowed(is_production=False, retention=approved, identity_key_available=False)
    assert enrollment_allowed(is_production=False, retention=unapproved, identity_key_available=True)
    assert not enrollment_allowed(is_production=True, retention=unapproved, identity_key_available=True)
    assert enrollment_allowed(is_production=True, retention=approved, identity_key_available=True)


# --- enrollment terms (Q117) ---------------------------------------------------------------------------------------


def test_terms_fingerprint_pins_version_and_every_term() -> None:
    base = terms_fingerprint(_terms(), campaign_version_id=1)
    assert base == terms_fingerprint(_terms(), campaign_version_id=1)
    assert base != terms_fingerprint(_terms(), campaign_version_id=2)
    for change in ({"referee_reward_minor": 199_999}, {"service_type": ServiceType.PARCEL},
                   {"qualification_window": timedelta(days=29)}, {"reward_validity": timedelta(days=59)}):
        assert terms_fingerprint(_terms(**change), campaign_version_id=1) != base
    # the budget is not a term the participant accepts
    assert terms_fingerprint(_terms(budget_allocated_minor=1), campaign_version_id=1) == base


def test_enrollment_rewards_cover_both_sides_and_every_step() -> None:
    single = enrollment_rewards(_terms())
    assert [(side, amount) for side, _, amount, _ in single] == [("referrer", 300_000), ("referee", 200_000)]
    credit = (PromoInstrument.DRIVER_CREDIT,) * 2
    driver = _terms(kind=PromoCampaignKind.REFERRAL_DRIVER_DRIVER, milestone_thresholds=(5, 10), min_distinct_clients=3,
                    referrer_instrument=credit[0], referee_instrument=credit[1])
    rewards = enrollment_rewards(driver)
    assert len(rewards) == 4 and {m for *_, m in rewards} == {5, 10}
    assert sum(amount for _, _, amount, _ in rewards) == max_commitment_for(driver)
    one_sided = enrollment_rewards(_terms(referrer_reward_minor=0))
    assert [side for side, *_ in one_sided] == ["referee"]


def test_request_fingerprint_separates_different_bodies() -> None:
    a = request_fingerprint({"campaign_id": 1, "terms": "x"})
    assert a == request_fingerprint({"terms": "x", "campaign_id": 1})
    assert a != request_fingerprint({"campaign_id": 2, "terms": "x"})


# --- Q119: a stale quote refuses only the attempt ------------------------------------------------------------------


def test_stale_quote_refuses_only_this_accept_attempt() -> None:
    q = quote_promo(fare_minor=20_000_000, fee_bps=1_000, policy=POLICY, passenger_bonus_requested_minor=500_000,
                    passenger_bonus_available_minor=500_000, driver_credit_available_minor=0)
    consent = record_consent(q, proposal_version_id="pv", expires_at=NOW + timedelta(minutes=5))
    with pytest.raises(DomainError) as exc:
        quote_at_accept(consent=consent, proposal_version_id="pv", now=NOW, fare_minor=20_000_000, fee_bps=1_000,
                        policy=POLICY, passenger_bonus_available_minor=100_000, driver_credit_available_minor=0)
    assert exc.value.code is ErrorCode.PROMO_QUOTE_STALE
    assert {k: exc.value.details[k] for k in STALE_SCOPE} == {"scope": "accept_attempt", "action": "requote"}
    # the same proposal can be accepted after a fresh quote and consent
    fresh = quote_promo(fare_minor=20_000_000, fee_bps=1_000, policy=POLICY, passenger_bonus_requested_minor=100_000,
                        passenger_bonus_available_minor=100_000, driver_credit_available_minor=0)
    again = record_consent(fresh, proposal_version_id="pv", expires_at=NOW + timedelta(minutes=5))
    ok = quote_at_accept(consent=again, proposal_version_id="pv", now=NOW, fare_minor=20_000_000, fee_bps=1_000,
                         policy=replace(POLICY), passenger_bonus_available_minor=100_000, driver_credit_available_minor=0)
    assert ok.passenger_bonus_minor == 100_000
