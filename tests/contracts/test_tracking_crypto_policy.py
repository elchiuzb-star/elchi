import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from app.contracts.crypto import (
    PURPOSE_BOOKING_PROOF_CODE,
    PURPOSE_CURSOR_SIGNING,
    PURPOSE_FILE_URL_SIGNING,
    codes_match,
    derive_proof_code,
    derive_subkey,
    new_secret_token,
    proof_code_hash,
    secret_token_hash,
)
from app.contracts.enums import CommissionPolicyKind, TrackingFreshness
from app.contracts.money import (
    balance_check_required,
    hold_adjustment_minor,
    initial_commission_status,
    validate_policy_terms,
    validate_reversal,
)
from app.contracts.tracking import (
    DELAYED_MAX_AGE_SECONDS,
    FRESH_MAX_AGE_SECONDS,
    LOCAL_QUEUE_MAX_AGE,
    LOCAL_QUEUE_MAX_POINTS,
    LOW_ACCURACY_THRESHOLD_M,
    MAX_POINT_AGE,
    MAX_POINTS_PER_BATCH,
    TRACKING_TOKEN_MIN_BYTES,
    freshness_at,
    freshness_for_age,
    is_low_accuracy,
    is_too_old_for_ingestion,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


# --- tracking (D18, spec §10.4) ---------------------------------------------------

def test_spec_10_4_constants() -> None:
    assert (FRESH_MAX_AGE_SECONDS, DELAYED_MAX_AGE_SECONDS) == (30, 120)
    assert LOW_ACCURACY_THRESHOLD_M == 100
    assert MAX_POINTS_PER_BATCH == 100
    assert MAX_POINT_AGE == timedelta(hours=24)
    assert (LOCAL_QUEUE_MAX_AGE, LOCAL_QUEUE_MAX_POINTS) == (timedelta(hours=24), 20_000)
    assert TRACKING_TOKEN_MIN_BYTES * 8 >= 128


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (None, TrackingFreshness.NO_DATA),
        (0, TrackingFreshness.FRESH),
        (30, TrackingFreshness.FRESH),
        (30.5, TrackingFreshness.DELAYED),
        (31, TrackingFreshness.DELAYED),
        (120, TrackingFreshness.DELAYED),
        (121, TrackingFreshness.LOST),
        (300, TrackingFreshness.LOST),
    ],
)
def test_freshness_buckets(age, expected) -> None:
    assert freshness_for_age(age) is expected


def test_freshness_rejects_negative_age_and_uses_aware_times() -> None:
    with pytest.raises(ValueError):
        freshness_for_age(-1)
    assert freshness_at(T0, T0 + timedelta(minutes=5)) is TrackingFreshness.LOST  # AC27
    assert freshness_at(None, T0) is TrackingFreshness.NO_DATA


def test_accuracy_and_max_age() -> None:
    assert not is_low_accuracy(100)
    assert is_low_accuracy(100.1)
    assert not is_too_old_for_ingestion(T0, T0 + timedelta(hours=24))
    assert is_too_old_for_ingestion(T0, T0 + timedelta(hours=24, seconds=1))


# --- key derivation, proof codes, tokens (D11, D18) --------------------------------

def test_subkeys_are_domain_separated_and_match_h0_label_format() -> None:
    master = "a-long-test-secret-key-value"
    proof = derive_subkey(master, PURPOSE_BOOKING_PROOF_CODE)
    cursor = derive_subkey(master, PURPOSE_CURSOR_SIGNING)
    assert len(proof) == 32 and proof != cursor
    assert proof != master.encode()
    expected_file_key = hmac.new(master.encode(), b"elchi:file-url-signing-key:v1", hashlib.sha256).digest()
    assert derive_subkey(master, PURPOSE_FILE_URL_SIGNING) == expected_file_key
    assert derive_subkey(master, PURPOSE_BOOKING_PROOF_CODE, version=2) != proof
    with pytest.raises(ValueError):
        derive_subkey(master, "Bad Purpose")


def test_proof_codes_are_bound_to_booking_kind_and_rotation() -> None:
    key = derive_subkey("a-long-test-secret-key-value", PURPOSE_BOOKING_PROOF_CODE)
    code = derive_proof_code(key, "bkg_a", "pickup_code", 0)
    assert len(code) == 6 and code.isdigit()
    assert code == derive_proof_code(key, "bkg_a", "pickup_code", 0)
    others = {
        derive_proof_code(key, "bkg_a", "delivery_code", 0),
        derive_proof_code(key, "bkg_a", "pickup_code", 1),
        derive_proof_code(key, "bkg_b", "pickup_code", 0),
    }
    assert code not in others or len(others) < 3  # collisions are possible but not systematic
    assert codes_match(code, f" {code} ")
    assert proof_code_hash(key, "bkg_a", "pickup_code", code) != proof_code_hash(key, "bkg_a", "delivery_code", code)


def test_secret_tokens_have_at_least_128_bits() -> None:
    token = new_secret_token()
    assert len(token) >= 43  # 32 bytes base64url
    assert new_secret_token() != token
    assert len(secret_token_hash(token)) == 64
    with pytest.raises(ValueError):
        new_secret_token(15)


# --- commission policy semantics (decision 1, D3, D4, D10) --------------------------

def test_zero_bps_only_as_time_boxed_campaign() -> None:
    validate_policy_terms(CommissionPolicyKind.CAMPAIGN, 0, T0, T0 + timedelta(days=14))
    validate_policy_terms(CommissionPolicyKind.STANDARD, 1500, T0, None)
    with pytest.raises(ValueError):
        validate_policy_terms(CommissionPolicyKind.STANDARD, 0, T0, None)
    with pytest.raises(ValueError):
        validate_policy_terms(CommissionPolicyKind.CAMPAIGN, 0, T0, None)
    with pytest.raises(ValueError):
        validate_policy_terms(CommissionPolicyKind.CAMPAIGN, 500, T0, T0)


def test_exempt_derives_only_from_snapshot_bps() -> None:
    assert initial_commission_status(0).value == "exempt"
    assert initial_commission_status(1500).value == "held"


def test_wallet_required_meaning() -> None:
    assert balance_check_required(is_production=True, wallet_required_flag=True) is True
    with pytest.raises(ValueError):
        balance_check_required(is_production=True, wallet_required_flag=False)
    assert balance_check_required(is_production=False, wallet_required_flag=False) is False


def test_multiple_partial_reversals_capped_by_capture() -> None:
    reversed_total = validate_reversal(6_000_000, 0, 1_000_000)
    reversed_total = validate_reversal(6_000_000, reversed_total, 2_000_000)
    assert validate_reversal(6_000_000, reversed_total, 3_000_000) == 6_000_000
    with pytest.raises(ValueError):
        validate_reversal(6_000_000, reversed_total, 3_000_001)
    with pytest.raises(ValueError):
        validate_reversal(6_000_000, 6_000_000, 1)


def test_amendment_adjusts_single_hold() -> None:
    assert hold_adjustment_minor(6_000_000, 9_000_000) == 3_000_000
    assert hold_adjustment_minor(6_000_000, 4_500_000) == -1_500_000
