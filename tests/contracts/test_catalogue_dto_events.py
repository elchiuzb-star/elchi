from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts.dto import ContractModel, Envelope, ErrorEnvelope, MoneyDTO, PageQuery, UtcDateTime
from app.contracts.enums import (
    ALLOWED_PRICE_BASIS,
    FLAGS_LOCKED_IN_PRODUCTION,
    FLAGS_REQUIRING_APPROVAL_REFERENCE,
    MARKETPLACE_ROLES,
    NEW_BUSINESS_CAPABILITIES,
    OBLIGATION_CAPABILITIES,
    OPERATOR_COMMAND_CAPABILITY,
    PRODUCTION_FLAG_DEFAULTS,
    STAFF_ROLE_CAPABILITIES,
    STAFF_ROLES,
    Capability,
    CashCollectionStatus,
    CommissionStatus,
    DisputeStatus,
    EventType,
    FeatureFlagKey,
    ListingKind,
    ListingStatus,
    OperatorBookingCommand,
    ParcelBookingStatus,
    PassengerBookingStatus,
    PriceBasis,
    ProposalStatus,
    Role,
    ServiceType,
    TripStatus,
    role_combination_allowed,
)
from app.contracts.errors import ERROR_CATALOGUE, DomainError, ErrorCode, http_status_for
from app.contracts.events import EVENT_PAYLOAD_ALLOWLIST, EventEnvelope

OCCURRED = datetime(2026, 9, 13, 7, 45, tzinfo=timezone.utc)


def test_statuses_match_spec_section_11() -> None:
    assert [s.value for s in ListingStatus] == ["draft", "published", "paused", "fulfilled", "expired", "cancelled"]
    assert [s.value for s in ProposalStatus] == ["active", "superseded", "accepted", "rejected", "withdrawn", "expired"]
    assert [s.value for s in TripStatus] == ["planned", "boarding", "in_progress", "completed", "cancelled", "interrupted"]
    assert [s.value for s in PassengerBookingStatus] == [
        "confirmed", "awaiting_pickup", "onboard", "arrived", "completed", "cancelled", "no_show",
    ]
    assert [s.value for s in ParcelBookingStatus] == [
        "confirmed", "awaiting_pickup", "picked_up", "in_transit", "delivered", "completed",
        "cancelled", "return_required", "returned", "delivery_failed",
    ]
    assert [s.value for s in CashCollectionStatus] == ["unpaid", "reported_paid", "acknowledged", "contested"]
    assert [s.value for s in CommissionStatus] == [
        "exempt", "held", "captured", "released", "partially_reversed", "reversed",
    ]
    assert [s.value for s in DisputeStatus] == ["open", "under_review", "resolved", "rejected"]


def test_listing_kinds_and_price_basis() -> None:
    assert {k.value for k in ListingKind} == {"request", "trip_offer"}
    assert {s.value for s in ServiceType} == {"passenger", "parcel"}
    assert len(ALLOWED_PRICE_BASIS) == 4
    assert ALLOWED_PRICE_BASIS[(ListingKind.REQUEST, ServiceType.PARCEL)] == {PriceBasis.TOTAL}


def test_production_flag_defaults_decisions_1_and_5() -> None:
    assert set(PRODUCTION_FLAG_DEFAULTS) == set(FeatureFlagKey)
    for key in (
        FeatureFlagKey.PASSENGER_ENABLED,
        FeatureFlagKey.PARCEL_ENABLED,
        FeatureFlagKey.DRIVER_LISTING_ENABLED,
        FeatureFlagKey.TRACKING_ENABLED,
        FeatureFlagKey.CORRIDOR_MATCHING_ENABLED,
        FeatureFlagKey.CARD_PAYMENTS_ENABLED,
    ):
        assert PRODUCTION_FLAG_DEFAULTS[key] is False
    assert FLAGS_LOCKED_IN_PRODUCTION == {FeatureFlagKey.WALLET_REQUIRED: True}
    assert FeatureFlagKey.PASSENGER_ENABLED in FLAGS_REQUIRING_APPROVAL_REFERENCE


def test_staff_and_marketplace_roles_are_separate_decision_3() -> None:
    assert not (STAFF_ROLES & MARKETPLACE_ROLES)
    assert role_combination_allowed([Role.CLIENT, Role.DRIVER])
    assert role_combination_allowed(["operator"])
    assert not role_combination_allowed([Role.DRIVER, Role.ADMIN])


def test_commission_policy_managed_by_super_admin_only_decision_2() -> None:
    manage = Capability.FINANCE_COMMISSION_POLICY_MANAGE
    view = Capability.FINANCE_COMMISSION_POLICY_VIEW
    assert manage in STAFF_ROLE_CAPABILITIES[Role.SUPER_ADMIN]
    assert manage not in STAFF_ROLE_CAPABILITIES[Role.ADMIN]
    assert manage not in STAFF_ROLE_CAPABILITIES[Role.OPERATOR]
    assert all(view in caps for caps in STAFF_ROLE_CAPABILITIES.values())


def test_operator_cannot_cancel_or_decide_fees() -> None:
    operator = STAFF_ROLE_CAPABILITIES[Role.OPERATOR]
    assert OPERATOR_COMMAND_CAPABILITY[OperatorBookingCommand.CANCEL] not in operator
    assert OPERATOR_COMMAND_CAPABILITY[OperatorBookingCommand.FINALIZE_FEE] not in operator
    assert OPERATOR_COMMAND_CAPABILITY[OperatorBookingCommand.CONFIRM_NO_SHOW] in operator
    assert set(OPERATOR_COMMAND_CAPABILITY) == set(OperatorBookingCommand)


def test_eligibility_block_keeps_obligations_d16() -> None:
    assert not (NEW_BUSINESS_CAPABILITIES & OBLIGATION_CAPABILITIES)
    assert Capability.TRACKING_PUBLISH in OBLIGATION_CAPABILITIES
    assert Capability.TRIP_CREATE in NEW_BUSINESS_CAPABILITIES


def test_every_error_code_is_catalogued() -> None:
    assert set(ERROR_CATALOGUE) == set(ErrorCode)
    assert "FEE_QUOTE_EXPIRED" not in ErrorCode.__members__  # D13: expires with PROPOSAL_EXPIRED
    assert http_status_for(ErrorCode.QUANTITY_MISMATCH) == 409


@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.IDEMPOTENCY_KEY_REUSED,
        ErrorCode.PROPOSAL_CHANGED,
        ErrorCode.CAPACITY_UNAVAILABLE,
        ErrorCode.INSUFFICIENT_COMMISSION_BALANCE,
        ErrorCode.ROUTE_CHANGED,
    ],
)
def test_spec_14_2_conflict_codes_are_409(code: ErrorCode) -> None:
    assert http_status_for(code) == 409


def test_domain_error_body() -> None:
    error = DomainError(ErrorCode.CAPACITY_UNAVAILABLE, details={"segment": "B-C"})
    assert error.http_status == 409
    assert error.to_error_body("req-1") == {
        "code": "CAPACITY_UNAVAILABLE",
        "message": ERROR_CATALOGUE[ErrorCode.CAPACITY_UNAVAILABLE].description,
        "details": {"segment": "B-C"},
        "request_id": "req-1",
    }
    ErrorEnvelope.model_validate({"success": False, "error": error.to_error_body()})


def test_money_dto_is_strict() -> None:
    assert MoneyDTO(amount_minor=40_000_000).currency == "UZS"
    with pytest.raises(ValidationError):
        MoneyDTO(amount_minor=400000.0)
    with pytest.raises(ValidationError):
        MoneyDTO(amount_minor="40000000")
    with pytest.raises(ValidationError):
        MoneyDTO(amount_minor=1, extra_field=1)


def test_envelope_generic_and_page_limits() -> None:
    envelope = Envelope[MoneyDTO].model_validate({"success": True, "data": {"amount_minor": 1, "currency": "UZS"}})
    assert envelope.data.amount_minor == 1
    with pytest.raises(ValidationError):
        PageQuery(limit=101)


class _Window(ContractModel):
    starts_at: UtcDateTime


def test_dto_rejects_naive_datetime() -> None:
    assert _Window(starts_at="2026-09-13T12:45:00+05:00").starts_at.utcoffset() is not None
    with pytest.raises(ValidationError):
        _Window(starts_at="2026-09-13T12:45:00")


def test_every_event_type_has_payload_allowlist_d17() -> None:
    assert set(EVENT_PAYLOAD_ALLOWLIST) == set(EventType)
    forbidden = {"phone", "sender_phone", "receiver_phone", "passport", "full_name", "address", "lat", "lng", "code", "token"}
    for keys in EVENT_PAYLOAD_ALLOWLIST.values():
        assert not (keys & forbidden)
    assert EventType.COMMISSION_POLICY_CREATED.value == "commission.policy.created"


def test_event_envelope_accepts_allowlisted_payload() -> None:
    event = EventEnvelope(
        EventType.BOOKING_ACCEPTED, "booking", "bkg_x", 1, OCCURRED, {"service_type": "parcel", "service_status": "confirmed"}
    )
    assert event.to_dict()["occurred_at"] == "2026-09-13T07:45:00Z"


@pytest.mark.parametrize(
    "payload",
    [
        {"receiver_phone": "+998900000000"},  # not allowlisted
        {"service_type": "parcel", "note": "x"},  # unknown key
        {"trip_id": {"lat": 41.3}},  # nested object
        {"trip_id": 1.5},  # float
    ],
)
def test_event_envelope_rejects_non_allowlisted_payload(payload: dict) -> None:
    with pytest.raises(ValueError):
        EventEnvelope(EventType.BOOKING_ACCEPTED, "booking", "bkg_x", 1, OCCURRED, payload)


def test_event_envelope_rejects_naive_time() -> None:
    with pytest.raises(ValueError):
        EventEnvelope(EventType.BOOKING_ACCEPTED, "booking", "bkg_x", 1, datetime(2026, 9, 13), {})
