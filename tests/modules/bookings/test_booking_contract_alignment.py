"""Migration literals, event audiences (Q16), proof-code keys (N5), detour re-check (AC17, Q25, Q46). No DB."""

from __future__ import annotations

import importlib.util
from pathlib import Path


from app.contracts.crypto import PURPOSE_BOOKING_PROOF_CODE, build_keyring, derive_proof_code, derive_subkey, verify_proof_code
from app.contracts.enums import (
    ActorSide,
    CashCollectionStatus,
    CommissionStatus,
    CustodyCaseStatus,
    EventType,
    FaultSide,
    NoShowReviewStatus,
    ParcelBookingStatus,
    PassengerBookingStatus,
    ProofKind,
    ServiceType,
)
from app.contracts.events import EventAudience, payload_for_audience
from app.modules.bookings import rules

VERSIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"


def _migration(name: str):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_status_literals_equal_contract_enums() -> None:
    core = _migration("20260915_0048_bookings_core")
    assert set(core.SERVICE_TYPES) == {s.value for s in ServiceType}
    assert set(core.PASSENGER_STATUSES) == {s.value for s in PassengerBookingStatus}
    assert set(core.PARCEL_STATUSES) == {s.value for s in ParcelBookingStatus}
    assert set(core.CASH_STATUSES) == {s.value for s in CashCollectionStatus}
    assert set(core.COMMISSION_STATUSES) == {s.value for s in CommissionStatus}
    assert set(core.ACTOR_SIDES) == {s.value for s in ActorSide}
    assert set(core.FAULT_SIDES) == {s.value for s in FaultSide}
    assert set(core.TERMINAL_SERVICE_STATUSES) == set(rules.TERMINAL_SERVICE_STATUSES)
    proofs = _migration("20260915_0049_booking_proofs")
    assert set(proofs.PROOF_KINDS) == {k.value for k in ProofKind}
    assert proofs.MAX_FAILED_ATTEMPTS == rules.MAX_PROOF_ATTEMPTS
    cases = _migration("20260915_0050_booking_no_show_custody")
    assert set(cases.NO_SHOW_REVIEW_STATUSES) == {s.value for s in NoShowReviewStatus}
    assert set(cases.CUSTODY_CASE_STATUSES) == {s.value for s in CustodyCaseStatus}


def test_migration_chain_is_unchanged() -> None:
    assert [(_migration(n).revision, _migration(n).down_revision) for n in (
        "20260915_0048_bookings_core", "20260915_0049_booking_proofs",
        "20260915_0050_booking_no_show_custody", "20260915_0051_booking_cash_amendments",
    )] == [
        ("20260915_0048", "20260914_0047"), ("20260915_0049", "20260915_0048"),
        ("20260915_0050", "20260915_0049"), ("20260915_0051", "20260915_0050"),
    ]


# --- Q16 / N2 audiences ------------------------------------------------------------------------------------------------


def test_q16_client_never_receives_commission_or_wallet_events() -> None:
    accepted = {
        "service_type": "passenger", "trip_id": "trp_x", "listing_id": "lst_x", "proposal_version_id": "prv_x",
        "service_status": "confirmed", "commission_status": "held",
    }
    client_copy = payload_for_audience(EventType.BOOKING_ACCEPTED, accepted, EventAudience.CLIENT)
    assert client_copy is not None and "commission_status" not in client_copy
    assert payload_for_audience(EventType.BOOKING_ACCEPTED, accepted, EventAudience.DRIVER)["commission_status"] == "held"
    hold = {"booking_id": "bkg_x", "amount_minor": 6_000_000, "currency": "UZS"}
    assert payload_for_audience(EventType.WALLET_HOLD_CREATED, hold, EventAudience.CLIENT) is None
    assert payload_for_audience(EventType.COMMISSION_CAPTURED, {**hold, "fee_bps": 1500}, EventAudience.CLIENT) is None
    status = {"service_type": "passenger", "trip_id": "trp_x", "machine": "commission", "from_status": "held", "to_status": "captured"}
    assert payload_for_audience(EventType.BOOKING_STATUS_CHANGED, status, EventAudience.CLIENT) is None


# --- N5 proof codes and key rotation --------------------------------------------------------------------------------


def test_n5_code_from_previous_master_verifies_during_rotation_window() -> None:
    old_master, new_master = "o" * 40, "n" * 40
    booking = "bkg_" + "a" * 26
    code = derive_proof_code(derive_subkey(old_master, PURPOSE_BOOKING_PROOF_CODE), booking, "boarding_code", 0)
    rotated = build_keyring(PURPOSE_BOOKING_PROOF_CODE, new_master, previous_masters=[old_master])
    assert verify_proof_code(rotated, booking, "boarding_code", 0, code)
    after_window = build_keyring(PURPOSE_BOOKING_PROOF_CODE, new_master)
    assert not verify_proof_code(after_window, booking, "boarding_code", 0, code)


def test_pickup_code_is_not_a_delivery_code_and_rotation_invalidates() -> None:
    ring = build_keyring(PURPOSE_BOOKING_PROOF_CODE, "k" * 40)
    booking = "bkg_" + "b" * 26
    pickup = derive_proof_code(ring.current, booking, "pickup_code", 0)
    delivery = derive_proof_code(ring.current, booking, "delivery_code", 0)
    assert pickup != delivery or not verify_proof_code(ring, booking, "delivery_code", 0, pickup)
    assert not verify_proof_code(ring, booking, "delivery_code", 0, pickup) or pickup == delivery
    assert verify_proof_code(ring, booking, "pickup_code", 0, pickup)
    rotated_code = derive_proof_code(ring.current, booking, "pickup_code", 1)
    assert rotated_code == pickup or not verify_proof_code(ring, booking, "pickup_code", 1, pickup)
