"""API v2 DTOs for geo (G1-G11) and feature flags (F1-F4); see docs/architecture/API_V2_CONTRACT.md §2-3."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.contracts.dto import ContractModel, UtcDateTime
from app.contracts.enums import Currency, FeatureFlagKey, FlagScopeType, PriceBasis, ServiceType


# Promoted to app.contracts.enums in integration pass 1 (A0a); re-exported for existing imports.
from app.contracts.enums import CorridorRolloutState  # noqa: E402,F401


class PointDTO(ContractModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class RegionDTO(ContractModel):
    id: str
    code: str
    name_uz: str
    name_ru: str | None = None
    requires_district: bool = Field(
        default=True,
        description=(
            "Direction selection asks for a district in this region (wave 10). False for Tashkent city, where "
            "the city itself is the unit."
        ),
    )
    #: Where the picker's map opens when this region is chosen and no district centre applies (wave 17).
    #:
    #: The case this exists for is Tashkent city: the city *is* the direction unit, so there is no
    #: district to take a centre from, and without this the map opened on the whole country. Advisory -
    #: a camera position, never an input to matching, capacity or price.
    center_lat: float | None = None
    center_lng: float | None = None


class RegionRefDTO(ContractModel):
    id: str
    code: str
    name_uz: str


class DistrictRefDTO(ContractModel):
    id: str
    name_uz: str


class DistrictDTO(ContractModel):
    """G16: a district as a direction unit (wave 10)."""

    id: str
    region: RegionRefDTO
    name_uz: str
    name_ru: str | None = None
    is_active: bool = True
    #: Where the picker's map opens when this district is chosen (wave 17).
    #:
    #: Advisory, and deliberately so: §2 of the specification rejects deciding a route by district, and Q88
    #: projects a marked point onto a confirmed route. This pair is a camera position, nothing more - it is
    #: never sent back as an input and no server-side decision reads it. Absent for a district nobody has
    #: placed yet, and the client then opens on the region instead of pretending to know.
    center_lat: float | None = None
    center_lng: float | None = None
    stops_count: int = Field(
        description=(
            "Active stops of publicly visible corridors in this district. 0 means the place can be named but "
            "no verified stop serves it yet - the client says so instead of promising a ride."
        )
    )


class CorridorDistrictDTO(ContractModel):
    """G17: one district a corridor passes, in travel order."""

    district: DistrictDTO
    sequence: int
    stops_count: int = Field(description="Active stops of this corridor inside the district.")
    on_confirmed_route: bool = Field(
        description=(
            "A confirmed route version of this corridor really stops in the district. False = the corridor "
            "owns a stop there, but no confirmed road reaches it yet (spec 6.1: proximity is not a route)."
        )
    )


class StopDTO(ContractModel):
    id: str
    name_uz: str
    name_ru: str | None = None
    district: DistrictRefDTO
    point: PointDTO
    meeting_note: str | None = None
    is_active: bool


class AdminStopDTO(StopDTO):
    corridor_id: str
    meeting_photo_file_id: str | None = None
    meeting_photo_url: str | None = None  # short-lived signed URL (H0 file access)
    sequence_hint: int
    version: int


class CorridorDTO(ContractModel):
    id: str
    name: str
    origin_region: RegionRefDTO
    destination_region: RegionRefDTO
    enabled_services: list[ServiceType]
    stops_count: int


class CorridorConfigDTO(ContractModel):
    revision: int
    search_radius_m: int
    default_max_detour_minutes: int
    default_max_detour_m: int


class CorridorAdminDTO(CorridorDTO):
    rollout_state: CorridorRolloutState
    config_version: int
    config: CorridorConfigDTO
    version: int
    updated_at: datetime


class CorridorCreate(ContractModel):
    name: str = Field(min_length=1, max_length=120)
    origin_region_id: str = Field(min_length=1, max_length=64)
    destination_region_id: str = Field(min_length=1, max_length=64)
    default_max_detour_minutes: StrictInt = Field(ge=0, le=240)
    default_max_detour_m: StrictInt = Field(ge=0, le=200_000)
    search_radius_m: StrictInt = Field(ge=100, le=50_000)


class CorridorPatch(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    rollout_state: CorridorRolloutState | None = None
    default_max_detour_minutes: StrictInt | None = Field(default=None, ge=0, le=240)
    default_max_detour_m: StrictInt | None = Field(default=None, ge=0, le=200_000)
    search_radius_m: StrictInt | None = Field(default=None, ge=100, le=50_000)

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> CorridorPatch:
        for name in ("name", "rollout_state", "default_max_detour_minutes", "default_max_detour_m", "search_radius_m"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class StopCreate(ContractModel):
    name_uz: str = Field(min_length=1, max_length=120)
    name_ru: str | None = Field(default=None, max_length=120)
    district_id: str = Field(min_length=1, max_length=64)
    point: PointDTO
    meeting_note: str | None = Field(default=None, max_length=500)
    meeting_photo_file_id: str | None = Field(default=None, min_length=1, max_length=128)
    sequence_hint: StrictInt = Field(default=0, ge=0, le=100_000)
    is_active: StrictBool = False


class StopPatch(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    name_uz: str | None = Field(default=None, min_length=1, max_length=120)
    name_ru: str | None = Field(default=None, max_length=120)
    district_id: str | None = Field(default=None, min_length=1, max_length=64)
    point: PointDTO | None = None
    meeting_note: str | None = Field(default=None, max_length=500)
    meeting_photo_file_id: str | None = Field(default=None, min_length=1, max_length=128)
    sequence_hint: StrictInt | None = Field(default=None, ge=0, le=100_000)
    is_active: StrictBool | None = None

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> StopPatch:
        for name in ("name_uz", "district_id", "point", "sequence_hint", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class RoutePreviewRequest(ContractModel):
    stop_ids: list[str] = Field(min_length=2, max_length=25)
    departure_at: UtcDateTime


class RouteVersionStopDTO(ContractModel):
    stop_id: str
    seq: int
    cumulative_distance_m: int
    cumulative_duration_s: int


class RouteVersionDTO(ContractModel):
    id: str
    status: Literal["draft", "confirmed"]
    stops: list[RouteVersionStopDTO]
    distance_m: int
    duration_s: int
    geometry_polyline: str
    provider: str
    provider_version: str
    is_estimate: bool
    attribution: str  # provider attribution to display with the route (BR #16)


class EffectiveFlagValuesDTO(ContractModel):
    passenger_enabled: bool
    parcel_enabled: bool
    driver_listing_enabled: bool
    tracking_enabled: bool


class EffectiveFlagsDTO(ContractModel):
    corridor_id: str | None = None
    flags: EffectiveFlagValuesDTO


class FlagValueUpsert(ContractModel):
    expected_version: StrictInt | None = Field(default=None, ge=1)
    enabled: StrictBool
    approval_reference: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class FlagValueDTO(ContractModel):
    id: str
    flag_key: FeatureFlagKey
    scope_type: FlagScopeType
    scope_ref: str
    enabled: bool
    approval_reference: str | None = None
    version: int
    updated_by: str | None = None
    updated_at: datetime


class FlagChangeDTO(ContractModel):
    scope_type: FlagScopeType
    scope_ref: str
    version: int
    old_enabled: bool | None = None
    new_enabled: bool
    actor: str | None = None
    reason: str
    approval_reference: str | None = None
    changed_at: datetime


MAX_MINOR = 9_000_000_000_000_000


class PriceBandUpsert(ContractModel):
    """Q42. Omit both stop ids for the corridor-wide band; send both for a segment band."""

    expected_version: StrictInt | None = Field(default=None, ge=1)
    origin_stop_id: str | None = Field(default=None, min_length=1, max_length=64)
    destination_stop_id: str | None = Field(default=None, min_length=1, max_length=64)
    floor_minor: StrictInt = Field(gt=0, le=MAX_MINOR)
    ceiling_minor: StrictInt = Field(gt=0, le=MAX_MINOR)
    is_active: StrictBool = True
    #: Q90: false (the default) means the band advises - it warns and ranks, and never refuses a negotiated
    #: price. True is an abuse/safety limit an admin deliberately imposes, and that one does refuse.
    enforced: StrictBool = False
    reason: str = Field(min_length=1, max_length=500)


class PriceBandDTO(ContractModel):
    corridor_id: str
    service_type: ServiceType
    price_basis: PriceBasis
    origin_stop_id: str | None = None
    destination_stop_id: str | None = None
    floor_minor: int
    ceiling_minor: int
    currency: Currency
    is_active: bool
    #: Q90: whether this band refuses a price or only advises about it.
    enforced: bool = False
    version: int
    reason: str
    updated_by: str | None = None
    updated_at: datetime


class PriceBandChangeDTO(ContractModel):
    service_type: ServiceType
    origin_stop_id: str | None = None
    destination_stop_id: str | None = None
    version: int
    old_floor_minor: int | None = None
    old_ceiling_minor: int | None = None
    old_is_active: bool | None = None
    new_floor_minor: int
    new_ceiling_minor: int
    new_is_active: bool
    actor: str | None = None
    reason: str
    changed_at: datetime


class Q47ViolationDTO(ContractModel):
    """F1: a pilot/active corridor that already violates Q47 (repair runbook: app.modules.geo.checks)."""

    corridor_id: str
    name: str
    rollout_state: CorridorRolloutState
    active_stops: int
    stops_missing_evidence: list[str]
    reasons: list[str]
