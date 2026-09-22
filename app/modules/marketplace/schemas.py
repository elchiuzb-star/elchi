"""Listing and proposal DTOs (API_V2_CONTRACT §5 L1-L8, §7 P1-P7).

Money is integer minor units; the server computes every total (spec §14.1).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.contracts.dto import ContractModel, MediaRefDTO, UtcDateTime, VersionedCommand
from app.modules.geo.schemas import DistrictRefDTO
from app.contracts.enums import (
    ActorSide,
    Amenity,
    Currency,
    ListingKind,
    ListingStatus,
    ParcelPayer,
    ParcelType,
    PaymentMethod,
    PriceBasis,
    ProposalStatus,
    RatingBucket,
    ServiceType,
)
from app.modules.marketplace.rules import LISTING_TIMEZONE, PROPOSAL_MESSAGE_MAX_LENGTH
from app.modules.trips.schemas import StopRefDTO

REASON_CODE_PATTERN = r"^[a-z][a-z0-9_]{2,63}$"




# --- listing details ---------------------------------------------------------------------


class BaggageDetails(ContractModel):
    pieces: StrictInt = Field(default=0, ge=0, le=20)
    total_weight_g: StrictInt = Field(default=0, ge=0, le=500_000)
    total_volume_ml: StrictInt | None = Field(default=None, ge=0)


class PassengerDetails(ContractModel):
    seat_count: StrictInt = Field(ge=1, le=8)
    adults: StrictInt = Field(ge=1, le=8)
    children: StrictInt = Field(default=0, ge=0, le=7)
    child_seat_required: StrictBool = False
    baggage: BaggageDetails = Field(default_factory=BaggageDetails)
    special_assistance: str | None = Field(default=None, max_length=500)
    amenities: list[Amenity] = Field(default_factory=list, max_length=20, description="Q68: strict enum.")

    @model_validator(mode="after")
    def _party_size(self) -> PassengerDetails:
        if self.adults + self.children != self.seat_count:
            raise ValueError("adults + children must equal seat_count")
        return self


class ContactDetails(ContractModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=5, max_length=32)


class ParcelDetails(ContractModel):
    """Request fields and trip-offer limits; completeness per kind is checked at publish."""

    parcel_type: ParcelType | None = Field(default=None, description="Q68: strict enum.")
    weight_g: StrictInt | None = Field(default=None, gt=0)
    length_cm: StrictInt | None = Field(default=None, gt=0)
    width_cm: StrictInt | None = Field(default=None, gt=0)
    height_cm: StrictInt | None = Field(default=None, gt=0)
    fragile: StrictBool = False
    declared_value_minor: StrictInt | None = Field(default=None, ge=0, description="Not insurance (spec §5.2).")
    photo_file_id: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Write: the reference `POST /api/v1/files/upload` returned for a `cargo_photo`, which must belong "
            "to the person attaching it. Read: the storage key, and only for a viewer allowed to see the photo "
            "(Q6) - it grants no access on its own."
        ),
    )
    photo: MediaRefDTO | None = Field(
        default=None,
        description="Response-only: a short-lived signed link, present only for the owner, the assigned driver and staff (Q6).",
    )
    payer: ParcelPayer | None = None
    sender: ContactDetails | None = None
    receiver: ContactDetails | None = None
    pickup_window_start: UtcDateTime | None = None
    pickup_window_end: UtcDateTime | None = None
    dropoff_window_start: UtcDateTime | None = None
    dropoff_window_end: UtcDateTime | None = None
    max_weight_g: StrictInt | None = Field(default=None, gt=0)
    max_volume_ml: StrictInt | None = Field(default=None, gt=0)
    max_dimension_cm: StrictInt | None = Field(default=None, gt=0)
    accepted_parcel_types: list[ParcelType] = Field(default_factory=list, max_length=20, description="Q68: strict enum.")

    @model_validator(mode="after")
    def _windows(self) -> ParcelDetails:
        for start, end in (
            (self.pickup_window_start, self.pickup_window_end),
            (self.dropoff_window_start, self.dropoff_window_end),
        ):
            if (start is None) != (end is None):
                raise ValueError("a window needs both start and end")
            if start is not None and end is not None and end <= start:
                raise ValueError("window end must be after start")
        return self


# --- listings -------------------------------------------------------------------------------


class PointEndInput(ContractModel):
    """Q88: a direction end marked on the map instead of picked from the stop catalogue.

    ``district_id`` is **advisory**: it says which administrative unit the person thought they were in, so an
    operator can file and search the booking. It is never used to decide whether the ride is possible - no
    district in the catalogue has a boundary polygon, so a containment check would be a lie. What decides
    validity is the projection onto the corridor's confirmed route (`geo.project_point_on_route`).
    """

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    district_id: str = Field(min_length=1, max_length=64, description="Advisory: where the person marked it.")
    address: str | None = Field(default=None, max_length=500, description="Reverse-geocoded, shown back to both sides.")


class PointEndDTO(ContractModel):
    """A point end as it is read back, with what the server worked out about it."""

    lat: float
    lng: float
    district: DistrictRefDTO | None = None
    address: str | None = None
    route_offset_m: int | None = Field(
        default=None, description="How far the marked place sits from the confirmed road, in metres."
    )


class DirectionPreviewDTO(ContractModel):
    """What the server can promise about two marked places, before anything is created (Q88).

    This exists so the client never has to guess. Which corridors exist, which of their routes are confirmed
    and how far off the road each one tolerates are all server facts; the screen asks and renders the answer,
    including the answer "no route serves these two places".
    """

    corridor_id: str
    corridor_name: str
    route_version_id: str
    route_polyline: str = Field(description="Encoded polyline of the confirmed road, for the preview map.")
    distance_m: int = Field(description="The whole confirmed road, end to end - not what this person travels.")
    duration_s: int = Field(description="Driving time over the whole confirmed road.")
    #: What the screen shows. A corridor can be 2 316 km long while the leg between the two marked places is
    #: 450 km, and quoting the corridor as "your trip" is simply a wrong number in front of a price.
    leg_distance_m: int = Field(description="Road distance between the two marked places, along the route.")
    leg_duration_s: int = Field(description="Driving time between the two marked places, along the route.")
    max_point_offset_m: int = Field(description="What this corridor tolerates; the screen explains it.")
    origin: PointEndDTO
    destination: PointEndDTO
    districts_on_route: list[str] = Field(default_factory=list, description="Names, in travel order.")


class ListingCreate(ContractModel):
    kind: ListingKind
    service_type: ServiceType
    # Q88: each end is a verified stop **or** a map point - exactly one of the two (CHECK in migration 0076).
    origin_stop_id: str | None = None
    destination_stop_id: str | None = None
    origin_point: PointEndInput | None = None
    destination_point: PointEndInput | None = None
    departure_window_start: UtcDateTime
    departure_window_end: UtcDateTime
    timezone: str = Field(default=LISTING_TIMEZONE, pattern=r"^Asia/Tashkent$")
    price_basis: PriceBasis
    unit_price_minor: StrictInt = Field(gt=0)
    currency: Currency = Currency.UZS
    payment_method: PaymentMethod = PaymentMethod.CASH
    expires_at: UtcDateTime | None = None
    comment: str | None = Field(default=None, max_length=1000)
    trip_id: str | None = None
    passenger: PassengerDetails | None = None
    parcel: ParcelDetails | None = None

    @model_validator(mode="after")
    def _shape(self) -> ListingCreate:
        if self.departure_window_end <= self.departure_window_start:
            raise ValueError("departure_window_end must be after departure_window_start")
        for end in ("origin", "destination"):
            stop, point = getattr(self, f"{end}_stop_id"), getattr(self, f"{end}_point")
            if (stop is None) == (point is None):
                raise ValueError(f"{end} must be exactly one of {end}_stop_id or {end}_point")
        if self.origin_stop_id is not None and self.origin_stop_id == self.destination_stop_id:
            raise ValueError("origin and destination stops must differ")
        if self.origin_point is not None and self.destination_point is not None:
            same = (self.origin_point.lat, self.origin_point.lng) == (self.destination_point.lat, self.destination_point.lng)
            if same:
                raise ValueError("origin and destination points must differ")
        if self.kind is ListingKind.TRIP_OFFER and (self.origin_point or self.destination_point):
            # A trip offer is the driver's own route; its ends are the stops the trip actually calls at.
            raise ValueError("a trip offer is published on verified stops, not on map points")
        if self.kind is ListingKind.TRIP_OFFER and not self.trip_id:
            raise ValueError("trip_id is required for trip_offer listings")
        if self.kind is ListingKind.REQUEST and self.trip_id:
            raise ValueError("request listings do not reference a trip")
        if self.service_type is ServiceType.PASSENGER:
            if self.parcel is not None:
                raise ValueError("parcel details are only allowed for parcel listings")
            if self.kind is ListingKind.REQUEST and self.passenger is None:
                raise ValueError("passenger details are required for passenger requests")
            if self.kind is ListingKind.TRIP_OFFER and self.passenger is not None:
                raise ValueError("passenger trip offers take seats from the trip")
        elif self.passenger is not None:
            raise ValueError("passenger details are only allowed for passenger listings")
        return self


class ListingOwnerDTO(ContractModel):
    id: str
    display_name: str


class ListingDTO(ContractModel):
    id: str
    kind: ListingKind
    service_type: ServiceType
    status: ListingStatus
    version: int
    terms_version: int = Field(description="Bumped only by proposal-invalidating edits; send it on accept (Q54).")
    owner: ListingOwnerDTO
    corridor_id: str
  # Q88: exactly one of the two is set - a verified stop, or the place the client marked on the map.
    origin_stop: StopRefDTO | None = None
    destination_stop: StopRefDTO | None = None
    origin_point: PointEndDTO | None = None
    destination_point: PointEndDTO | None = None
    departure_window_start: UtcDateTime
    departure_window_end: UtcDateTime
    timezone: str
    price_basis: PriceBasis
    unit_price_minor: int
    quantity: int
    total_minor: int = Field(description="Server-computed total in minor units.")
    currency: Currency
    payment_method: PaymentMethod
    expires_at: UtcDateTime
    trip_id: str | None
    passenger: PassengerDetails | None
    parcel: ParcelDetails | None
    comment: str | None
    published_at: UtcDateTime | None
    created_at: UtcDateTime


class ListingPublicDTO(ContractModel):
    """No phone, home address, exact GPS or photo (spec §10.6)."""

    id: str
    kind: ListingKind
    service_type: ServiceType
    status: ListingStatus
  # Q88: exactly one of the two is set - a verified stop, or the place the client marked on the map.
    origin_stop: StopRefDTO | None = None
    destination_stop: StopRefDTO | None = None
    origin_point: PointEndDTO | None = None
    destination_point: PointEndDTO | None = None
    departure_window_start: UtcDateTime
    departure_window_end: UtcDateTime
    timezone: str
    price_basis: PriceBasis
    unit_price_minor: int
    quantity: int
    total_minor: int
    currency: Currency
    reputation: dict[str, Any] | None = Field(default=None, description="Owned by trust_support (A12); null until then.")
    parcel_type: ParcelType | None = None
    trip_id: str | None = None
    published_at: UtcDateTime | None = None


class ListingPatch(VersionedCommand):
    origin_stop_id: str | None = None
    destination_stop_id: str | None = None
    departure_window_start: UtcDateTime | None = None
    departure_window_end: UtcDateTime | None = None
    price_basis: PriceBasis | None = None
    unit_price_minor: StrictInt | None = Field(default=None, gt=0)
    expires_at: UtcDateTime | None = None
    comment: str | None = Field(default=None, max_length=1000)
    passenger: PassengerDetails | None = None
    parcel: ParcelDetails | None = None


class ListingCommand(VersionedCommand):
    pass


class ListingCancel(VersionedCommand):
    reason_code: str = Field(pattern=REASON_CODE_PATTERN)
    comment: str | None = Field(default=None, max_length=1000)


# --- proposals ------------------------------------------------------------------------------


class ProposalBaggage(ContractModel):
    """Passenger baggage for a trip-offer proposal (request proposals use the request details)."""

    pieces: StrictInt = Field(default=0, ge=0, le=20)
    total_weight_g: StrictInt = Field(default=0, ge=0, le=500_000)
    total_volume_ml: StrictInt = Field(default=0, ge=0, le=5_000_000)


class ProposalParcel(ContractModel):
    """Parcel on a parcel trip-offer proposal; checked against the offer limits and trip cargo capacity."""

    parcel_type: ParcelType | None = Field(default=None, description="Q68: strict enum.")
    weight_g: StrictInt = Field(gt=0, le=1_000_000)
    length_cm: StrictInt = Field(gt=0, le=500)
    width_cm: StrictInt = Field(gt=0, le=500)
    height_cm: StrictInt = Field(gt=0, le=500)
    volume_ml: StrictInt | None = Field(default=None, gt=0, description="Defaults to length x width x height (1 cm3 = 1 ml).")
    receiver: ContactDetails | None = Field(
        default=None,
        description="Receiver of a trip-offer parcel; stored on the version, shown only to the proposing client (Q43/Q44).",
    )


def _one_demand_kind(baggage: ProposalBaggage | None, parcel: ProposalParcel | None) -> None:
    if baggage is not None and parcel is not None:
        raise ValueError("send either baggage (passenger) or parcel, not both")


class ProposalCreate(ContractModel):
    trip_id: str | None = Field(default=None, description="Required when a driver answers a request.")
    # Q88: omitted when the listing's ends are map points - the proposal inherits them. A driver cannot move
    # the place the client marked, so there is nothing to send.
    pickup_stop_id: str | None = None
    dropoff_stop_id: str | None = None
    pickup_window_start: UtcDateTime
    pickup_window_end: UtcDateTime
    quantity: StrictInt = Field(ge=1, le=60)
    price_basis: PriceBasis
    unit_price_minor: StrictInt = Field(gt=0)
    message: str | None = Field(default=None, max_length=PROPOSAL_MESSAGE_MAX_LENGTH)
    baggage: ProposalBaggage | None = None
    parcel: ProposalParcel | None = None

    @model_validator(mode="after")
    def _shape(self) -> ProposalCreate:
        _one_demand_kind(self.baggage, self.parcel)
        if self.pickup_window_end <= self.pickup_window_start:
            raise ValueError("pickup_window_end must be after pickup_window_start")
        if self.pickup_stop_id is not None and self.pickup_stop_id == self.dropoff_stop_id:
            raise ValueError("pickup and dropoff stops must differ")
        if (self.pickup_stop_id is None) != (self.dropoff_stop_id is None):
            raise ValueError("send both stop ids or neither (a point-ended listing supplies both)")
        return self


class ProposalCounter(ContractModel):
    expected_revision: StrictInt = Field(ge=1)
    pickup_stop_id: str | None = None
    dropoff_stop_id: str | None = None
    pickup_window_start: UtcDateTime | None = None
    pickup_window_end: UtcDateTime | None = None
    quantity: StrictInt | None = Field(default=None, ge=1, le=60)
    unit_price_minor: StrictInt | None = Field(default=None, gt=0)
    message: str | None = Field(default=None, max_length=PROPOSAL_MESSAGE_MAX_LENGTH)
    baggage: ProposalBaggage | None = None
    parcel: ProposalParcel | None = None

    @model_validator(mode="after")
    def _has_change(self) -> ProposalCounter:
        _one_demand_kind(self.baggage, self.parcel)
        changes = (
            self.pickup_stop_id,
            self.dropoff_stop_id,
            self.pickup_window_start,
            self.pickup_window_end,
            self.quantity,
            self.unit_price_minor,
            self.baggage,
            self.parcel,
        )
        if all(value is None for value in changes):
            raise ValueError("a counter proposal must change at least one term")
        if (self.pickup_window_start is None) != (self.pickup_window_end is None):
            raise ValueError("pickup window needs both start and end")
        return self


class ProposalDecision(ContractModel):
    expected_revision: StrictInt = Field(ge=1)
    reason_code: str | None = Field(default=None, pattern=REASON_CODE_PATTERN)


class FeeQuoteDTO(ContractModel):
    policy_id: str
    policy_kind: str
    fee_bps: int
    commission_minor: int
    net_minor: int
    valid_until: UtcDateTime = Field(description="Equals the proposal version expires_at (AC43).")


class ProposalDemandDTO(ContractModel):
    """Resource snapshot of the version (no identity data; safe for both sides)."""

    baggage_ml: int
    cargo_weight_g: int
    cargo_volume_ml: int
    parcel_length_cm: int | None = None
    parcel_width_cm: int | None = None
    parcel_height_cm: int | None = None


class PriceRevisionsLeftDTO(ContractModel):
    client: int
    driver: int


class ProposalVersionDTO(ContractModel):
    id: str
    revision: int
    author_side: ActorSide
    status: ProposalStatus
    status_reason: str | None
  # Q88: exactly one of the two is set - a verified stop, or the place the client marked on the map.
    pickup_stop: StopRefDTO | None = None
    dropoff_stop: StopRefDTO | None = None
    pickup_point: PointEndDTO | None = None
    dropoff_point: PointEndDTO | None = None
    pickup_window_start: UtcDateTime
    pickup_window_end: UtcDateTime
    quantity: int
    price_basis: PriceBasis
    unit_price_minor: int
    total_minor: int
    currency: Currency
    expires_at: UtcDateTime
    created_at: UtcDateTime
    message: str | None
    demand: ProposalDemandDTO
    fee_quote: FeeQuoteDTO | None = Field(default=None, description="Only shown to the driver side.")
    price_revisions_left: PriceRevisionsLeftDTO
    receiver: ContactDetails | None = Field(
        default=None, description="Trip-offer parcel receiver; only the client side sees it (Q43/Q44), never the driver."
    )


class ProposalPartyDTO(ContractModel):
    """A negotiation party. Before accept no identity is exchanged (R2, Q43): only the side and an
    anonymous label ("Haydovchi #N" / "Mijoz"). Identity fields stay null until a booking exists (A4)."""

    side: ActorSide
    label: str
    id: str | None = None
    display_name: str | None = None
    reputation: dict[str, Any] | None = None


class ProposalThreadDTO(ContractModel):
    id: str
    listing_id: str
    trip_id: str | None
    state: str
    client: ProposalPartyDTO
    driver: ProposalPartyDTO
    current_version: ProposalVersionDTO | None
    versions: list[ProposalVersionDTO] | None = None
    booking_id: str | None = Field(default=None, description="Set by the bookings module (A4) after accept.")


class ListingOfferDTO(ContractModel):
    """One anonymized competing offer on a client request (R1, ADR-0019).

    Never carries a name, photo, plate, phone, make/model, user/driver/trip id or client counters.
    """

    label: str = Field(description='Stable per listing, e.g. "Haydovchi #2"; not derived from any id.')
    is_mine: bool
    response_pending: bool = Field(default=False, description="The client countered; the offer awaits this driver's answer.")
    revision: int
    quantity: int
    price_basis: PriceBasis
    unit_price_minor: int
    total_minor: int
    currency: Currency
  # Q88: exactly one of the two is set - a verified stop, or the place the client marked on the map.
    pickup_stop: StopRefDTO | None = None
    dropoff_stop: StopRefDTO | None = None
    pickup_point: PointEndDTO | None = None
    dropoff_point: PointEndDTO | None = None
    pickup_window_start: UtcDateTime
    pickup_window_end: UtcDateTime
    vehicle_class: str
    seat_capacity: int
    rating_bucket: RatingBucket | None = Field(
        default=None,
        description=(
            "U6 (option A): trust *group*, never a number - new_verified / good / mixed / low. Below "
            "RATING_BUCKET_MIN_COUNT ratings it is new_verified, which is the truth about a new driver rather "
            "than an invented score. Always read together with rating_count."
        ),
    )
    rating_count: int = Field(
        default=0,
        description="How many ratings the bucket is based on; 0 means none, and the UI must show it beside the bucket.",
    )
    completed_bookings: int | None = Field(default=None, description="Completed bookings behind the bucket.")
    updated_at: UtcDateTime
