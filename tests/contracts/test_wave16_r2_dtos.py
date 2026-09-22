"""Wave 1.6 final integration: pre-accept DTOs carry no identity (R1/R2, Q40, Q43), vehicle class, adjustment statuses."""

import pytest

from app.contracts.enums import (
    LEDGER_ADJUSTMENT_TERMINAL,
    LedgerAdjustmentStatus,
    VehicleClass,
    vehicle_class_for_seat_capacity,
)

IDENTITY_FIELD_MARKERS = (
    "phone",
    "name",
    "photo",
    "plate",
    "make_model",
    "color",
    "colour",
    "user_id",
    "driver_id",
    "client_id",
    "trip_id",
    "thread_id",
    "version_id",
    "address",
    "passport",
    "email",
)


def _identity_fields(model) -> list[str]:  # noqa: ANN001
    return [name for name in model.model_fields if any(marker in name for marker in IDENTITY_FIELD_MARKERS)]


def test_listing_offer_dto_carries_no_identity_fields() -> None:
    from app.modules.marketplace.schemas import ListingOfferDTO

    assert _identity_fields(ListingOfferDTO) == []
    assert "id" not in ListingOfferDTO.model_fields
    assert {"label", "is_mine", "vehicle_class", "seat_capacity", "rating_bucket", "completed_bookings"} <= set(
        ListingOfferDTO.model_fields
    )
    # reputation is never defaulted (§8.2: no artificial rating)
    assert ListingOfferDTO.model_fields["rating_bucket"].default is None
    assert ListingOfferDTO.model_fields["completed_bookings"].default is None


def test_public_listing_and_trip_vehicle_dtos_carry_no_identity_fields() -> None:
    from app.modules.marketplace.schemas import ListingPublicDTO
    from app.modules.trips.schemas import TripPublicDTO, TripPublicVehicleDTO

    assert "owner_display_name" not in ListingPublicDTO.model_fields
    assert set(TripPublicVehicleDTO.model_fields) == {"vehicle_class", "seat_capacity"}
    assert _identity_fields(TripPublicDTO) == []


def test_proposal_party_identity_is_optional_and_null_by_default() -> None:
    from app.modules.marketplace.schemas import ProposalPartyDTO

    for field in ("id", "display_name", "reputation"):
        assert not ProposalPartyDTO.model_fields[field].is_required()
        assert ProposalPartyDTO.model_fields[field].default is None
    assert {"side", "label"} <= {name for name, info in ProposalPartyDTO.model_fields.items() if info.is_required()}


@pytest.mark.parametrize("seats", range(1, 21))
def test_vehicle_class_contract_matches_trips_rule(seats: int) -> None:
    from app.modules.trips.rules import vehicle_class

    assert vehicle_class(seats) == vehicle_class_for_seat_capacity(seats).value


def test_vehicle_class_values() -> None:
    assert {c.value for c in VehicleClass} == {"car", "minivan", "minibus"}
    assert vehicle_class_for_seat_capacity(4) is VehicleClass.CAR
    assert vehicle_class_for_seat_capacity(7) is VehicleClass.MINIVAN
    assert vehicle_class_for_seat_capacity(8) is VehicleClass.MINIBUS


def test_ledger_adjustment_statuses_q49() -> None:
    assert LedgerAdjustmentStatus.WITHDRAWN in LEDGER_ADJUSTMENT_TERMINAL
    assert LedgerAdjustmentStatus.PENDING_SECOND_APPROVAL not in LEDGER_ADJUSTMENT_TERMINAL
    assert {s.value for s in LedgerAdjustmentStatus} == {"pending_second_approval", "posted", "rejected", "withdrawn"}
