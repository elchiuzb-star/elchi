"""Vehicle and trip DTOs (API_V2_CONTRACT §4: T1-T8). Units: g, ml, cm, m integers."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt, model_validator

from app.contracts.dto import ContractModel, UtcDateTime, VersionedCommand
from app.contracts.enums import ListingKind, ListingStatus, ServiceType, TripStatus


class StopRefDTO(ContractModel):
    id: str = Field(description="Opaque stop id (stp_...).")
    name_uz: str
    name_ru: str | None = None


# --- vehicles --------------------------------------------------------------------------


class VehicleCreate(ContractModel):
    plate_number: str = Field(min_length=2, max_length=32)
    make_model: str = Field(min_length=1, max_length=120)
    color: str = Field(min_length=1, max_length=64)
    seat_capacity: StrictInt = Field(ge=1, le=60, description="Passenger seats excluding the driver.")
    baggage_capacity_ml: StrictInt | None = Field(default=None, gt=0)
    cargo_max_weight_g: StrictInt | None = Field(default=None, gt=0)
    cargo_max_volume_ml: StrictInt | None = Field(default=None, gt=0)
    document_file_ids: list[str] = Field(default_factory=list, max_length=10)


class VehicleDTO(ContractModel):
    id: str
    plate_number: str
    plate_masked: str
    make_model: str
    color: str
    seat_capacity: int
    baggage_capacity_ml: int | None
    cargo_max_weight_g: int | None
    cargo_max_volume_ml: int | None
    document_file_ids: list[str]
    verification_status: str
    version: int
    created_at: UtcDateTime


class VehicleVerifyRequest(VersionedCommand):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _reject_needs_reason(self) -> VehicleVerifyRequest:
        if self.decision == "reject" and not (self.reason and self.reason.strip()):
            raise ValueError("reason is required when rejecting a vehicle")
        return self


# --- trips ----------------------------------------------------------------------------------


class TripStopInput(ContractModel):
    stop_id: str
    seq: StrictInt = Field(ge=1, le=50)
    planned_arrival_at: UtcDateTime
    dwell_minutes: StrictInt = Field(default=0, ge=0, le=240)


def _check_stop_sequence(stops: list[TripStopInput] | None) -> None:
    if stops is None:
        return
    if [stop.seq for stop in stops] != list(range(1, len(stops) + 1)):
        raise ValueError("stops must be listed with seq 1..n in order")


class TripCreate(ContractModel):
    vehicle_id: str
    route_version_id: str
    stops: list[TripStopInput] = Field(min_length=2, max_length=50)
    planned_start_at: UtcDateTime
    planned_end_at: UtcDateTime
    seat_capacity: StrictInt = Field(ge=0, le=60)
    baggage_capacity_ml: StrictInt | None = Field(default=None, ge=0)
    cargo_capacity_weight_g: StrictInt | None = Field(default=None, ge=0)
    cargo_capacity_volume_ml: StrictInt | None = Field(default=None, ge=0)
    max_detour_minutes: StrictInt = Field(ge=0, le=240)
    max_detour_m: StrictInt = Field(ge=0, le=200_000)
    pickup_wait_minutes: StrictInt = Field(default=10, ge=0, le=60)
    booking_cutoff_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def _validate(self) -> TripCreate:
        _check_stop_sequence(self.stops)
        return self


class TripStopDTO(ContractModel):
    seq: int
    stop: StopRefDTO
    planned_arrival_at: UtcDateTime
    dwell_minutes: int
    eta_arrival_at: UtcDateTime | None = None


class TripVehicleDTO(ContractModel):
    id: str
    make_model: str
    color: str
    plate_masked: str
    seat_capacity: int


class TripListingRefDTO(ContractModel):
    id: str
    kind: ListingKind
    service_type: ServiceType
    status: ListingStatus


class OpenCasesDTO(ContractModel):
    no_show_reviews: int
    custody_cases: int


class TripDTO(ContractModel):
    id: str
    status: TripStatus
    version: int
    vehicle: TripVehicleDTO
    route_version_id: str
    stops: list[TripStopDTO]
    planned_start_at: UtcDateTime
    planned_end_at: UtcDateTime
    timezone: str
    seat_capacity: int
    baggage_capacity_ml: int
    cargo_capacity_weight_g: int
    cargo_capacity_volume_ml: int
    max_detour_minutes: int
    max_detour_m: int
    detour_used_minutes: int = Field(description="Deprecated: ceil(detour_used_s / 60).")
    detour_used_s: int
    detour_used_m: int
    pickup_wait_minutes: int
    booking_cutoff_at: UtcDateTime
    listings: list[TripListingRefDTO]
    open_cases: OpenCasesDTO | None = Field(
        default=None, description="Owned by the bookings module (A4); null until bookings exist."
    )
    created_at: UtcDateTime


class TripPublicVehicleDTO(ContractModel):
    """Pre-accept vehicle view (R2, Q43): class and seats only; no make/model, colour or plate."""

    vehicle_class: str
    seat_capacity: int


class TripPublicStopDTO(ContractModel):
    seq: int
    stop: StopRefDTO
    planned_arrival_at: UtcDateTime


class TripPublicDTO(ContractModel):
    id: str
    status: TripStatus
    vehicle: TripPublicVehicleDTO
    stops: list[TripPublicStopDTO]
    planned_start_at: UtcDateTime
    planned_end_at: UtcDateTime
    timezone: str


class TripPatch(VersionedCommand):
    planned_start_at: UtcDateTime | None = None
    planned_end_at: UtcDateTime | None = None
    stops: list[TripStopInput] | None = Field(default=None, min_length=2, max_length=50)
    max_detour_minutes: StrictInt | None = Field(default=None, ge=0, le=240)
    max_detour_m: StrictInt | None = Field(default=None, ge=0, le=200_000)

    @model_validator(mode="after")
    def _validate(self) -> TripPatch:
        _check_stop_sequence(self.stops)
        return self


class SegmentAvailabilityDTO(ContractModel):
    from_seq: int
    to_seq: int
    from_stop_id: str
    to_stop_id: str
    seats_remaining: int
    baggage_remaining_ml: int
    cargo_remaining_weight_g: int
    cargo_remaining_volume_ml: int


class TripAvailabilityDTO(ContractModel):
    trip_id: str
    trip_version: int
    computed_at: UtcDateTime
    segments: list[SegmentAvailabilityDTO] = Field(description="Computed remaining capacity; not a reservation.")
