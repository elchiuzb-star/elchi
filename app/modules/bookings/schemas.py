"""Request bodies and DTOs of the bookings API (API_V2_CONTRACT §8, P8, T9, T10).

Two booking views exist on purpose (Q16, N2): ``BookingDTO`` for the driver and staff carries the commission
status and fee block; ``BookingClientDTO`` has no commission/fee keys at all (not merely null).
Phones follow Q44 (``contact`` block): null until the service starts, hidden again 24 h after a terminal state;
the parcel sender's phone never reaches the driver; the receiver's only after pickup.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, model_validator

from app.modules.marketplace.schemas import PointEndDTO
from app.modules.marketplace.schemas import ParcelCategoryDTO
from app.contracts.dto import BookingVehicleDisclosureDTO, ContractModel, MediaRefDTO, UtcDateTime, VersionedCommand
from app.contracts.enums import (
    ActorSide,
    CashCollectionStatus,
    CommissionStatus,
    FaultSide,
    Currency,
    PaymentMethod,
    PriceBasis,
    ProofKind,
    ServiceType,
)
from app.modules.trips.schemas import StopRefDTO

# --- requests ---------------------------------------------------------------------------------------------------


class PromoConsentInput(ContractModel):
    """The client's explicit confirmation of the discount it was shown (Q104, ADR-0023 §18). The server recomputes
    the terms; these numbers must match them exactly or the command is refused with ``PROMO_QUOTE_STALE``. They are
    never used as amounts."""

    passenger_bonus_minor: StrictInt = Field(ge=0, description="P - passenger bonus the client agrees to spend.")
    cash_due_minor: StrictInt = Field(ge=0, description="F_cash - cash the client will hand the driver (F - P).")


class PromoDriverAckInput(ContractModel):
    """Q125: the driver confirms the new driver-side numbers of an amendment it was shown. Checked against the
    server's recomputation (``PROMO_QUOTE_STALE`` otherwise); never used as amounts."""

    cash_to_collect_minor: StrictInt = Field(ge=0, description="F_cash - cash the driver will collect.")
    commission_charged_minor: StrictInt = Field(ge=0, description="C_net - commission charged from the balance.")


class AcceptRequest(ContractModel):
    proposal_version_id: str = Field(min_length=4, max_length=64, description="prv_... id of the current version.")
    expected_listing_version: StrictInt | None = Field(
        default=None, ge=1, description="Q54: the listing's terms_version the accepting party saw (ListingDTO.terms_version)."
    )
    expected_listing_terms_version: StrictInt | None = Field(default=None, ge=1, description="Additive alias (Q54).")
    promo_consent: PromoConsentInput | None = Field(
        default=None,
        description="Referral stage 4: the client accepting a version confirms the passenger bonus it was shown. "
        "Needs a client declaring X-Elchi-Client-Features: promo_cash_v1.",
    )
    promo_driver_ack: PromoDriverAckInput | None = Field(
        default=None,
        description="Q123 (clarified): the driver accepting a version sends the cash to collect and the commission "
        "charged it was shown; a different server result (e.g. credit no longer fits) refuses this attempt with the "
        "new numbers (PROMO_QUOTE_STALE driver_terms_changed) instead of charging more behind its back.",
    )

    @model_validator(mode="after")
    def _one_terms_version(self) -> "AcceptRequest":
        values = {v for v in (self.expected_listing_version, self.expected_listing_terms_version) if v is not None}
        if len(values) != 1:
            raise ValueError("give expected_listing_version or expected_listing_terms_version (equal if both)")
        return self

    @property
    def terms_version(self) -> int:
        return int(self.expected_listing_terms_version or self.expected_listing_version)  # type: ignore[arg-type]


class BookingCancel(VersionedCommand):
    reason_code: str = Field(min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=500)


class ContactAttemptInput(ContractModel):
    at: UtcDateTime
    channel: str = Field(min_length=1, max_length=32, description="chat | quick_reply | arrived_signal | other")


class BookingActionRequest(VersionedCommand):
    code: str | None = Field(default=None, pattern=r"^\d{4,8}$", description="Proof code received from the code owner.")
    evidence_file_ids: list[str] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=500)
    contact_attempts: list[ContactAttemptInput] = Field(default_factory=list, max_length=20)
    observed_at: UtcDateTime | None = None


class FeeDecision(ContractModel):
    mode: Literal["capture", "release", "partial"]
    amount_minor: StrictInt | None = Field(default=None, gt=0)


class OperatorBookingCommandRequest(VersionedCommand):
    reason: str = Field(min_length=1, max_length=500)
    evidence_file_ids: list[str] = Field(default_factory=list, max_length=10)
    fee_decision: FeeDecision | None = None
    proof_kind: ProofKind | None = Field(default=None, description="Wave 2.1: required for reissue_proof_code.")
    cancel_fault_side: FaultSide | None = Field(
        default=None,
        description="Q129, cancel only: the cause the operator decided (client, driver, platform, none = justified), "
        "with the reason as its basis. Absent: no fault is recorded and the promo cause stays undetermined (review).",
    )


class ProofReissueRequest(ContractModel):
    """B5a ``POST /bookings/{booking_id}/codes/{kind}/reissue`` (wave 2.1, BR blocker 3)."""

    reason: str | None = Field(default=None, max_length=500)


class CashReceiptReport(VersionedCommand):
    amount_minor: StrictInt = Field(gt=0)
    reported_at: UtcDateTime
    note: str | None = Field(default=None, max_length=500)


class CashReceiptDecision(ContractModel):
    expected_version: StrictInt = Field(ge=1, description="Version of the cash receipt.")
    comment: str | None = Field(default=None, max_length=500)


class AmendmentChanges(ContractModel):
    quantity: StrictInt | None = Field(default=None, ge=1)
    unit_price_minor: StrictInt | None = Field(default=None, gt=0)
    pickup_stop_id: str | None = None
    dropoff_stop_id: str | None = None
    pickup_window_start: UtcDateTime | None = None
    pickup_window_end: UtcDateTime | None = None


class AmendmentCreate(VersionedCommand):
    changes: AmendmentChanges
    reason: str = Field(min_length=1, max_length=500)
    promo_consent: PromoConsentInput | None = Field(
        default=None, description="Q116: a client proposing a change to a discounted booking confirms the new terms."
    )
    promo_driver_ack: PromoDriverAckInput | None = Field(
        default=None, description="Q125: a driver proposing a change that moves its cash or commission confirms them."
    )


class AmendmentDecision(ContractModel):
    expected_version: StrictInt = Field(ge=1, description="Version of the amendment.")


class AmendmentAccept(AmendmentDecision):
    promo_consent: PromoConsentInput | None = Field(
        default=None, description="Q116: a client accepting a change to a discounted booking confirms the new terms."
    )
    promo_driver_ack: PromoDriverAckInput | None = Field(
        default=None, description="Q125: a driver accepting a change that moves its cash or commission confirms them."
    )


class AmendmentPromoConfirmation(ContractModel):
    """Q126: the proposer of an open amendment confirms its promo terms again from its current session."""

    promo_consent: PromoConsentInput | None = None
    promo_driver_ack: PromoDriverAckInput | None = None


class TripActionRequest(VersionedCommand):
    reason: str | None = Field(default=None, max_length=500)
    evidence_file_ids: list[str] = Field(default_factory=list, max_length=10)


# --- booking views ------------------------------------------------------------------------------------------------


class BookingStopDTO(ContractModel):
    # Q88: a booking end is a verified stop or the agreed map point, never both.
    stop: StopRefDTO | None = None
    point: PointEndDTO | None = None
    occurrence_seq: int
    planned_arrival_at: UtcDateTime | None = None
    window_start: UtcDateTime | None = None
    window_end: UtcDateTime | None = None


class BookingVehicleDTO(BookingVehicleDisclosureDTO):
    """Q64: masked plate + make/model + colour after accept; ``plate_number`` only when
    ``disclosure.full_plate_visible`` (trip boarding or <= 30 min before this booking's pickup); never for a booking
    cancelled / no_show before the service started. Staff views carry the full plate (audited)."""


class BookingDriverDTO(ContractModel):
    id: str
    display_name: str
    vehicle: BookingVehicleDTO
    contact_phone: str | None = None


class BookingClientPartyDTO(ContractModel):
    id: str
    display_name: str
    contact_phone: str | None = None


class ParcelContactsDTO(ContractModel):
    receiver_name: str | None = None
    receiver_phone: str | None = None


class BookingContactDTO(ContractModel):
    phones_visible: bool
    visible_from: UtcDateTime | None = None
    visible_until: UtcDateTime | None = None
    chat_thread_id: str | None = Field(default=None, description="A7 (wave 3).")
    support_available: bool = True


class BookingFeeDTO(ContractModel):
    policy_id: str
    policy_kind: str
    fee_bps: int
    commission_minor: int
    net_minor: int


class BookingPromoClientDTO(ContractModel):
    """What the client pays on a discounted booking (Q103): no commission, credit, cost or formula."""

    view: Literal["client"] = "client"
    fare_minor: int
    passenger_discount_minor: int
    cash_due_minor: int
    currency: Currency


class BookingPromoDriverDTO(ContractModel):
    """What the driver collects and is charged on a discounted booking (Q103)."""

    view: Literal["driver"] = "driver"
    fare_minor: int
    passenger_discount_minor: int
    cash_to_collect_minor: int
    base_commission_minor: int
    passenger_discount_covered_minor: int
    driver_credit_minor: int
    commission_charged_minor: int
    driver_keeps_minor: int
    currency: Currency


# Money terms of an amendment to a discounted booking: the role's own object (Q16) - the client's has no commission keys.
AmendmentPromoDTO = Annotated[BookingPromoClientDTO | BookingPromoDriverDTO, Field(discriminator="view")]

class NoShowReviewDTO(ContractModel):
    status: str
    reported_at: UtcDateTime
    decided_at: UtcDateTime | None = None


class CustodyCaseDTO(ContractModel):
    status: str
    reason_code: str
    opened_at: UtcDateTime
    resolved_at: UtcDateTime | None = None


class BookingCancelledDTO(ContractModel):
    by_side: ActorSide
    reason_code: str
    fault_side: str | None = None
    at: UtcDateTime


class BookingListingIdsDTO(ContractModel):
    request: str | None = None
    supply: str | None = None


class BookingPolicyVersionsDTO(ContractModel):
    listing_version: int
    listing_terms_version: int
    cancellation_policy: str


class BookingClientDTO(ContractModel):
    """Client view: no commission status, no fee, no wallet fields (Q16)."""

    id: str
    viewer_side: str
    service_type: ServiceType
    service_status: str
    cash_status: CashCollectionStatus
    # Q140 (ADR-0026): the agreed parcel size category and its limits (frozen on the booking).
    parcel_category: ParcelCategoryDTO | None = None
    quantity_amendable: bool = Field(
        default=False,
        description="Q145 (ADR-0026): whether an amendment may change the quantity. False for every booking made on a "
                    "client request (D9) and for parcels; the unit price can still be amended by agreement.")
    version: int
    trip_id: str
    listing_ids: BookingListingIdsDTO
    accepted_proposal_version_id: str
    quantity: int
    price_basis: PriceBasis
    unit_price_minor: int
    total_minor: int
    currency: Currency
    payment_method: PaymentMethod
    pickup: BookingStopDTO
    dropoff: BookingStopDTO
    driver: BookingDriverDTO | None = None
    client: BookingClientPartyDTO | None = None
    parcel_contacts: ParcelContactsDTO | None = None
    parcel_photo: MediaRefDTO | None = Field(
        default=None,
        description=(
            "Q6: the cargo photo of the request this booking came from - a short-lived signed link for the "
            "sender, the assigned driver and staff. Absent for a passenger booking or when none was uploaded."
        ),
    )
    contact: BookingContactDTO
    no_show_review: NoShowReviewDTO | None = None
    custody_case: CustodyCaseDTO | None = None
    cash_receipt: CashReceiptDTO | None = Field(
        default=None,
        description=(
            "The newest cash acknowledgement on this booking, so the other side can answer it after a reload. "
            "It records that cash changed hands between two people - ELCHI neither receives nor settles the fare."
        ),
    )
    policy_versions: BookingPolicyVersionsDTO
    cancellation_policy_summary: str
    cancelled: BookingCancelledDTO | None = None
    promo: BookingPromoClientDTO | None = Field(
        default=None,
        description="Referral stage 4: present only on a discounted booking. The client hands the driver "
        "cash_due_minor, not total_minor.",
    )
    created_at: UtcDateTime
    updated_at: UtcDateTime


class BookingDTO(BookingClientDTO):
    """Driver and staff view (adds the commission snapshot)."""

    commission_status: CommissionStatus
    fee: BookingFeeDTO
    promo: BookingPromoDriverDTO | None = Field(  # type: ignore[assignment]
        default=None,
        description="Referral stage 4: present only on a discounted booking. Collect cash_to_collect_minor; the real "
        "balance is charged commission_charged_minor.",
    )


class BookingCodeDTO(ContractModel):
    kind: ProofKind
    code: str
    valid_until: UtcDateTime | None = None


class BookingCodesDTO(ContractModel):
    booking_id: str
    codes: list[BookingCodeDTO]


class CashReceiptDTO(ContractModel):
    id: str
    booking_id: str
    booking_version: int
    reported_by_side: str
    amount_minor: int
    currency: Currency
    status: str
    reported_at: UtcDateTime
    decided_at: UtcDateTime | None = None
    dispute_id: str | None = None
    version: int


class AmendmentDTO(ContractModel):
    id: str
    booking_id: str
    status: str
    author_side: str
    changes: dict[str, Any]
    new_quantity: int
    new_unit_price_minor: int
    new_total_minor: int
    fee_delta_minor: int | None = Field(default=None, description="Driver and staff only (Q16).")
    promo: AmendmentPromoDTO | None = Field(default=None, description="Referral stage 4: discounted booking only.")
    expires_at: UtcDateTime
    version: int


class ManifestItemDTO(ContractModel):
    booking_id: str
    service_type: ServiceType
    service_status: str
    seats: int | None = None
    parcel_summary: str | None = None
    client_first_name: str
    contact_phone: str | None = None


class ManifestStopDTO(ContractModel):
    seq: int
    # Q88: a booking end is a verified stop or the agreed map point, never both.
    stop: StopRefDTO | None = None
    point: PointEndDTO | None = None
    planned_arrival_at: UtcDateTime
    pickups: list[ManifestItemDTO]
    dropoffs: list[ManifestItemDTO]


class TripManifestDTO(ContractModel):
    trip_id: str
    trip_version: int
    stops: list[ManifestStopDTO]
