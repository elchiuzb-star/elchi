"""DTOs for M1-M5 (API_V2_CONTRACT §6 + "Wave 3 (A5)" block).

Privacy (Q43): ``listing`` is A1's ``ListingPublicDTO`` (no owner name, phone, plate, address); reputation carries only
label, counts and the shown average (``null`` without ratings - never a default 4.5, §8.2/AC36).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.contracts.dto import (
    ApiWarning,
    ContractModel,
    EmptyDTO,
    FeedMatchDTO,
    FeedPageMeta,
    FeedReputationDTO,
    PageMeta,
    TripAvailabilitySummaryDTO,
    UtcDateTime,
)
from app.contracts.enums import FeedSide, MatchGroup, MatchReason, MatchType, ReputationLabel, ServiceType
from app.contracts.feed import MATCH_SCOPE_CONFIRMED_STOPS
from app.modules.marketplace.schemas import ListingPublicDTO

# Wave 3.1: FeedMatchDTO, FeedReputationDTO, TripAvailabilitySummaryDTO and FeedPageMeta are the contract's
# (app/contracts/dto.py) and are re-exported here; FeedItemDTO / MatchDTO stay module-owned because they embed
# A1's ListingPublicDTO. A change to a re-exported DTO belongs in the contract (AGENTS §1).


class FeedItemDTO(ContractModel):
    listing: ListingPublicDTO
    match: FeedMatchDTO
    group: MatchGroup
    ready_to_accept: bool
    labels: list[str]
    reputation: FeedReputationDTO
    comparable_total_minor: int | None = Field(
        default=None, description="Total for the requested quantity (per_seat x seats); null when not comparable."
    )


class MatchDTO(ContractModel):
    listing: ListingPublicDTO
    trip_availability_summary: TripAvailabilitySummaryDTO | None = None
    match: FeedMatchDTO
    ranking_version: str
    group: MatchGroup
    ready_to_accept: bool
    labels: list[str]
    reputation: FeedReputationDTO
    comparable_total_minor: int | None = None


class FeedEnvelope(ContractModel):
    success: Literal[True] = True
    data: list[FeedItemDTO]
    message: str | None = None
    meta: FeedPageMeta
    warnings: list[ApiWarning] | None = None


class MatchEnvelope(ContractModel):
    success: Literal[True] = True
    data: list[MatchDTO]
    message: str | None = None
    meta: FeedPageMeta
    warnings: list[ApiWarning] | None = None


class SavedSearchCreate(ContractModel):
    service_type: ServiceType
    side: FeedSide
    origin_stop_id: str | None = None
    origin_region_id: str | None = None
    #: Wave 10: the district is the direction unit everywhere except Tashkent city.
    origin_district_id: str | None = None
    destination_stop_id: str | None = None
    destination_region_id: str | None = None
    destination_district_id: str | None = None
    time_window_start: UtcDateTime
    time_window_end: UtcDateTime
    quantity: StrictInt = Field(default=1, ge=1, le=60)
    notify: StrictBool = True

    @model_validator(mode="after")
    def _ends_and_window(self) -> SavedSearchCreate:
        for end in ("origin", "destination"):
            given = [
                getattr(self, f"{end}_{kind}_id") for kind in ("stop", "region", "district")
                if getattr(self, f"{end}_{kind}_id") is not None
            ]
            if len(given) != 1:
                raise ValueError(f"exactly one of {end}_stop_id / {end}_district_id / {end}_region_id is required")
        if self.time_window_end <= self.time_window_start:
            raise ValueError("time_window_end must be after time_window_start")
        return self


class SavedSearchDTO(ContractModel):
    id: str
    service_type: ServiceType
    side: FeedSide
    origin_stop_id: str | None = None
    origin_region_id: str | None = None
    origin_district_id: str | None = None
    destination_stop_id: str | None = None
    destination_region_id: str | None = None
    destination_district_id: str | None = None
    time_window_start: UtcDateTime
    time_window_end: UtcDateTime
    quantity: int
    notify: bool
    last_notified_at: UtcDateTime | None = None
    created_at: UtcDateTime


