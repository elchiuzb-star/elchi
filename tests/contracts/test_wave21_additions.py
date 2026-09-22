"""Wave 2.1 contract additions (15.09.2026, Q59-Q73, wave 2 BR review)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.contracts import db_errors, detour, disclosure, proofs
from app.contracts.contact_filter import ContactCategory, scan
from app.contracts.dto import BookingVehicleDisclosureDTO
from app.contracts.enums import (
    AMENITY_VALUES,
    OPERATOR_COMMAND_CAPABILITY,
    PARCEL_TYPE_VALUES,
    AdminBookingQueue,
    Capability,
    CommissionReviewReason,
    EventType,
    FeatureFlagKey,
    OperatorBookingCommand,
    ParcelType,
    ProofKind,
    V2_SERVICE_FLAGS,
)
from app.contracts.errors import WARNING_CATALOGUE, ErrorCode, WarningCode, http_status_for
from app.contracts.events import EVENT_AUDIENCES, EVENT_PAYLOAD_ALLOWLIST, EventAudience, payload_for_audience
from app.contracts.state_machines import (
    DELIVERED_OPERATOR_QUEUE_AFTER,
    PARCEL_BOOKING,
    PASSENGER_BOOKING,
    booking_blocks_trip_cancel,
    service_start_allowed,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.TRIP_NOT_STARTED, 409),
        (ErrorCode.TRIP_STOPS_LOCKED, 409),
        (ErrorCode.PROOF_REISSUE_LIMITED, 429),
        (ErrorCode.INTEGRITY_CONFLICT, 409),
        (ErrorCode.VEHICLE_NOT_ELIGIBLE, 409),  # Q61 reuses the existing code
    ],
)
def test_wave21_error_codes(code: ErrorCode, status: int) -> None:
    assert http_status_for(code) == status


def test_delivery_code_warning_is_catalogued_q65() -> None:
    assert WarningCode.DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY in WARNING_CATALOGUE


def test_reissue_operator_command_capability() -> None:
    assert OPERATOR_COMMAND_CAPABILITY[OperatorBookingCommand.REISSUE_PROOF_CODE] is Capability.OPS_BOOKING_COMMAND


def test_wave21_events() -> None:
    assert EventType.BOOKING_PROOF_CODE_REISSUED.value == "booking.proof_code.reissued"
    assert "code" not in EVENT_PAYLOAD_ALLOWLIST[EventType.BOOKING_PROOF_CODE_REISSUED]
    review = EventType.COMMISSION_FINANCE_REVIEW_REQUIRED
    assert EVENT_AUDIENCES[review] == frozenset({EventAudience.STAFF})
    assert payload_for_audience(review, {"booking_id": "bkg_x"}, EventAudience.CLIENT) is None
    assert payload_for_audience(review, {"booking_id": "bkg_x"}, EventAudience.DRIVER) is None


def test_q68_strict_enums_keep_values_in_use() -> None:
    assert {"box", "documents"} <= PARCEL_TYPE_VALUES
    assert ParcelType("box") is ParcelType.BOX
    assert "air_conditioning" in AMENITY_VALUES
    assert all(value == value.lower() and " " not in value for value in PARCEL_TYPE_VALUES | AMENITY_VALUES)


def test_admin_queues_cover_a4_queues_q66() -> None:
    from app.modules.bookings.service import ADMIN_QUEUES

    assert set(ADMIN_QUEUES) <= {queue.value for queue in AdminBookingQueue}
    assert AdminBookingQueue.FINANCE_REVIEW.value == "finance_review"
    assert CommissionReviewReason.DISPUTE_MODULE_UNAVAILABLE.value == "dispute_module_unavailable"
    # wave 3.1 (W3-6): migration 0062 widened ck_bookings_finance_review with this value.
    assert CommissionReviewReason.DISPUTE_RESOLVED.value == "dispute_resolved"
    assert {r.value for r in CommissionReviewReason} == {"dispute_module_unavailable", "dispute_resolved"}


def test_v2_service_flags_match_geo_q72() -> None:
    from app.modules.geo.service import V2_SERVICE_FLAGS as GEO_FLAGS

    assert {FeatureFlagKey(flag) for flag in GEO_FLAGS} == set(V2_SERVICE_FLAGS)
    assert FeatureFlagKey.WALLET_REQUIRED not in V2_SERVICE_FLAGS


def test_operator_complete_with_evidence_transitions() -> None:
    assert PASSENGER_BOOKING.is_allowed_by("arrived", "completed", "complete_with_evidence")
    assert PARCEL_BOOKING.is_allowed_by("delivered", "completed", "complete_with_evidence")
    assert PARCEL_BOOKING.is_allowed_by("delivered", "completed", "complete")  # sender confirmation (Q65)
    assert DELIVERED_OPERATOR_QUEUE_AFTER == timedelta(hours=24)


@pytest.mark.parametrize(("status", "allowed"), [("planned", False), ("boarding", True), ("in_progress", True),
                                                 ("interrupted", False), ("completed", False), ("cancelled", False)])
def test_service_start_needs_started_trip(status: str, allowed: bool) -> None:
    assert service_start_allowed(status) is allowed


def test_trip_cancel_blocked_by_people_or_parcels_inside() -> None:
    assert booking_blocks_trip_cancel("passenger", "onboard")
    assert not booking_blocks_trip_cancel("passenger", "awaiting_pickup")
    assert booking_blocks_trip_cancel("parcel", "picked_up")
    assert booking_blocks_trip_cancel("parcel", "delivery_failed")
    assert not booking_blocks_trip_cancel("parcel", "confirmed")


def test_detour_rejected_in_pilot_q62() -> None:
    assert detour.DETOUR_INSERTION_ENABLED is False
    assert detour.DETOUR_NOT_AVAILABLE_REASON == "detour_not_available"


# --- Q64 disclosure -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("plate", ["01 A 123 BC", "01A123BC", "30x777aa", "AB1", "ABCD", "ABCDE"])
def test_mask_plate_number_matches_trips_rule(plate: str) -> None:
    from app.modules.trips.rules import mask_plate

    normalized = disclosure.normalize_plate_number(plate)
    assert disclosure.mask_plate_number(plate) == mask_plate(normalized)
    assert disclosure.mask_plate_number("01 A 123 BC") == "01****BC"


def test_full_plate_visibility_q64() -> None:
    pickup = NOW + timedelta(hours=2)
    assert not disclosure.full_plate_visible(trip_status="planned", pickup_at=pickup, now=NOW)
    assert disclosure.full_plate_visible(trip_status="boarding", pickup_at=pickup, now=NOW)
    assert disclosure.full_plate_visible(trip_status="planned", pickup_at=NOW + timedelta(minutes=30), now=NOW)
    assert not disclosure.full_plate_visible(trip_status="in_progress", pickup_at=NOW + timedelta(minutes=31), now=NOW)
    assert disclosure.full_plate_visible(trip_status="in_progress", pickup_at=NOW - timedelta(minutes=5), now=NOW)
    assert disclosure.full_plate_visible_from(pickup) == pickup - timedelta(minutes=30)


def test_vehicle_disclosure_dto_q64() -> None:
    dto = BookingVehicleDisclosureDTO(vehicle_class="car", seat_capacity=4, make_model="Cobalt", color="oq",
                                      plate_masked="01****BC")
    assert dto.plate_number is None and dto.plate_number_visible_from is None
    with pytest.raises(ValidationError):
        BookingVehicleDisclosureDTO(vehicle_class="car", seat_capacity=4, make_model="x", color="y",
                                    plate_masked="z", phone="+998901234567")
    from app.modules.bookings.schemas import BookingVehicleDTO

    assert set(BookingVehicleDTO.model_fields) <= set(BookingVehicleDisclosureDTO.model_fields)


# --- proof reissue ------------------------------------------------------------------------------------------


def test_reissue_decision_limits() -> None:
    assert proofs.reissue_decision([], NOW).allowed
    assert proofs.reissue_decision([], NOW).reissues_left == proofs.PROOF_REISSUE_MAX_IN_WINDOW - 1
    too_soon = proofs.reissue_decision([NOW - timedelta(seconds=30)], NOW)
    assert not too_soon.allowed and too_soon.retry_after_s == 90
    spaced = [NOW - timedelta(hours=h) for h in (1, 2, 3)]
    full = proofs.reissue_decision(spaced, NOW)
    assert not full.allowed and full.reissues_left == 0
    assert full.retry_after_s == int(timedelta(hours=21).total_seconds())
    old = [NOW - timedelta(hours=25)] * 5
    assert proofs.reissue_decision(old, NOW).allowed
    assert ProofKind.OPERATOR_EVIDENCE not in proofs.REISSUABLE_PROOF_KINDS
    assert proofs.PROOF_CODE_MAX_FAILED_ATTEMPTS == 5


# --- Q65 chat code masking ----------------------------------------------------------------------------------


def test_proof_codes_masked_only_when_requested() -> None:
    text = "kod 482913 ni ayting"
    assert not scan(text).has_contact
    result = scan(text, mask_proof_codes=True)
    assert result.categories == {ContactCategory.PROOF_CODE}
    assert "482913" not in result.masked_text


@pytest.mark.parametrize("text", ["narxi 150 000 so'm", "150 000", "150000 so'm", "3 kishi, 12:30 da"])
def test_proof_code_masking_keeps_amounts(text: str) -> None:
    assert ContactCategory.PROOF_CODE not in scan(text, mask_proof_codes=True).categories


def test_proof_code_masking_catches_spaced_and_keeps_phones() -> None:
    assert scan("48 29 13", mask_proof_codes=True).categories == {ContactCategory.PROOF_CODE}
    assert scan("+998 90 123 45 67", mask_proof_codes=True).categories == {ContactCategory.PHONE}


# --- DB error mapping ---------------------------------------------------------------------------------------


def test_db_error_mapping_precedence() -> None:
    m = db_errors.map_db_error
    assert m(sqlstate="23001", constraint="trip_stops_locked").code is ErrorCode.TRIP_STOPS_LOCKED
    assert m(sqlstate="23514", message="feature_flag_values: enabling passenger_enabled in production is refused").code \
        is ErrorCode.PRODUCTION_INVARIANTS_FAILED
    assert m(sqlstate="23505", constraint="uq_something_else").code is ErrorCode.INTEGRITY_CONFLICT
    assert m(sqlstate="55P03").code is ErrorCode.SERVICE_UNAVAILABLE
    assert m(sqlstate="08006").reason == "database_unavailable"
    assert m(sqlstate=None, connection_lost=True).code is ErrorCode.SERVICE_UNAVAILABLE
    assert m(sqlstate="XX000") == db_errors.DEFAULT_DB_ERROR_RULE
    assert m(sqlstate=None).code is ErrorCode.SERVER_ERROR


def test_every_db_rule_uses_a_catalogued_code() -> None:
    rules = list(db_errors.CONSTRAINT_RULES.values()) + [r for _, r in db_errors.MESSAGE_PREFIX_RULES]
    rules += list(db_errors.SQLSTATE_RULES.values()) + list(db_errors.SQLSTATE_CLASS_RULES.values())
    assert all(isinstance(rule.code, ErrorCode) and rule.reason for rule in rules)
