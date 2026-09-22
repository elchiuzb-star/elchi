"""API v2 DTOs of the trust & support module (API_V2_CONTRACT §1 I4, §12 S1-S8, S13-S20).

Q43: no DTO here carries a phone, full name, plate, address or coordinate of a counterparty. Free text is stored
masked (``contact_filter``). Support contacts come from configuration only and never promise a response time (§16).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt

from app.contracts.dto import ContractModel, UtcDateTime
from app.contracts.enums import (
    ActorSide,
    CashResolutionOutcome,
    FraudSignalStatus,
    FraudSignalType,
    ReportReasonCode,
    ReportStatus,
    ReportSubjectType,
    DisputeResolutionCode,
    DisputeStatus,
    DisputeType,
    ReputationLabel,
    ServiceType,
    SupportTicketKind,
    SupportTicketStatus,
    TrackingFreshness,
    TrustReviewDecision,
    TrustReviewStatus,
    TrustSignalType,
)
from app.contracts.trust import DISPUTE_DESCRIPTION_MAX_LENGTH, SUPPORT_MESSAGE_MAX_LENGTH
from app.modules.trust_support.rules import (
    DECISION_NOTE_MAX_LENGTH,
    REPORT_DETAILS_MAX_LENGTH,
    DISPUTE_EVIDENCE_MAX_FILES,
    EVIDENCE_NOTE_MAX_LENGTH,
    RATING_COMMENT_MAX_LENGTH,
)

FileId = str

# --- ratings (S1, S2) ------------------------------------------------------------------------------------------------


class RatingCreate(ContractModel):
    subject_side: Literal["client", "driver"]
    stars: StrictInt = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=RATING_COMMENT_MAX_LENGTH)


class RatingDTO(ContractModel):
    id: str
    booking_id: str
    subject_side: ActorSide
    stars: int
    comment_moderated: str | None = None
    published_at: UtcDateTime | None = None
    created_at: UtcDateTime


class ReputationDTO(ContractModel):
    """``average_rating`` is null without ratings (never an artificial 4.5, §8.2); adjusted rating stays internal."""

    user_id: str
    service_type: ServiceType
    rating_count: int
    average_rating: float | None = None
    label: ReputationLabel
    completed_bookings: int
    completed_trips: int


# --- disputes (S3-S8) ------------------------------------------------------------------------------------------------


class DisputeCreate(ContractModel):
    type: DisputeType
    description: str = Field(min_length=1, max_length=DISPUTE_DESCRIPTION_MAX_LENGTH)
    evidence_file_ids: list[FileId] = Field(default_factory=list, max_length=DISPUTE_EVIDENCE_MAX_FILES)


class DisputeEvidenceCreate(ContractModel):
    note: str | None = Field(default=None, max_length=EVIDENCE_NOTE_MAX_LENGTH)
    file_ids: list[FileId] = Field(default_factory=list, max_length=DISPUTE_EVIDENCE_MAX_FILES)


class DisputeEvidenceDTO(ContractModel):
    """S6. ``file_urls`` (wave 5) are short-lived signed links for the viewer this response is already
    authorized for - the same rule the rest of the private storage follows (``app/utils/file_access.py``):
    the link is the credential, it is minted inside an authorized response and it expires. Without it a
    participant or an operator saw only an opaque id and could not look at the evidence at all."""

    author_side: ActorSide
    note: str | None = None
    file_ids: list[str]
    file_urls: list[str] = []
    created_at: UtcDateTime


class DisputeResolutionDTO(ContractModel):
    code: DisputeResolutionCode | None = None
    text: str | None = None
    decided_at: UtcDateTime | None = None


class DisputeDTO(ContractModel):
    id: str
    booking_id: str
    type: DisputeType
    status: DisputeStatus
    version: int
    opened_by_side: ActorSide
    description: str
    evidence: list[DisputeEvidenceDTO]
    resolution: DisputeResolutionDTO | None = None
    created_at: UtcDateTime
    escalate_at: UtcDateTime
    escalated: bool = False


class DisputeCommand(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    resolution_code: DisputeResolutionCode | None = None
    resolution_text: str | None = Field(default=None, max_length=DECISION_NOTE_MAX_LENGTH)
    reason: str | None = Field(default=None, max_length=DECISION_NOTE_MAX_LENGTH)
    # Wave 3.1: how the decision settles a `contested` cash receipt (STATE_MACHINES §6). Only on resolve/reject of
    # a payment dispute whose receipt is contested; it must agree with a resolution code that already implies one.
    cash_outcome: CashResolutionOutcome | None = None


# --- trust review queue (S18-S20) -----------------------------------------------------------------------------------


class TrustReviewDTO(ContractModel):
    id: str
    subject_user_id: str
    signal_type: TrustSignalType
    status: TrustReviewStatus
    evidence: dict[str, list[str] | int]
    signal_count: int
    last_signal_at: UtcDateTime
    decision: TrustReviewDecision | None = None
    decided_by: str | None = None
    decided_at: UtcDateTime | None = None
    version: int
    created_at: UtcDateTime


class TrustReviewCommand(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    decision: TrustReviewDecision | None = None
    note: str = Field(min_length=1, max_length=DECISION_NOTE_MAX_LENGTH)


class StrikeDTO(ContractModel):
    subject_type: str
    categories: list[str]
    reason_code: str
    occurred_at: UtcDateTime


class UserStrikesDTO(ContractModel):
    user_id: str
    window_days: int
    strikes_in_window: int
    strikes: list[StrikeDTO]


# --- support / SOS (S13-S17) ----------------------------------------------------------------------------------------


class SupportContactsDTO(ContractModel):
    """§16: no 24/7 or response-time promise; without configuration ``available=false``."""

    available: bool
    phone: str | None = None
    hours_text: str | None = None


class SupportTicketCreate(ContractModel):
    kind: SupportTicketKind
    booking_id: str | None = Field(default=None, max_length=64)
    message: str | None = Field(default=None, max_length=SUPPORT_MESSAGE_MAX_LENGTH)


class SupportTicketDTO(ContractModel):
    id: str
    kind: SupportTicketKind
    status: SupportTicketStatus
    booking_id: str | None = None
    message: str | None = None
    version: int
    created_at: UtcDateTime
    acknowledged_at: UtcDateTime | None = None
    resolved_at: UtcDateTime | None = None


class BookingLiveStateDTO(ContractModel):
    """Staff SOS view (A6 ``tracking.service.booking_live_state``): freshness only, no coordinates."""

    window_open: bool
    freshness: TrackingFreshness
    last_captured_at: UtcDateTime | None = None
    driver_arrived_at: UtcDateTime | None = None


class SupportTicketAdminDTO(SupportTicketDTO):
    user_id: str
    press_count: int = 1
    last_pressed_at: UtcDateTime | None = None
    trip_id: str | None = None
    live: BookingLiveStateDTO | None = None


class SupportTicketCommand(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    note: str | None = Field(default=None, max_length=DECISION_NOTE_MAX_LENGTH)


# --- I4 account deletion --------------------------------------------------------------------------------------------


class AccountDeletionRequest(ContractModel):
    reason: str | None = Field(default=None, max_length=500)


class AccountDeletionDTO(ContractModel):
    status: Literal["deleted"]


# --- blocks, reports and fraud signals (S9-S12, §8.1, §17.3) ---------------------------------------------------


class BlockCreate(ContractModel):
    """S9. Blocking is silent: the other side is never told, and no reason is stored (§8.1)."""

    user_id: str


class BlockDTO(ContractModel):
    id: str
    user_id: str = Field(description="The blocked user's public id.")
    created_at: UtcDateTime


class ReportCreate(ContractModel):
    """S11 (§17.3). ``details`` passes the contact filter before it is stored (Q43)."""

    subject_type: ReportSubjectType
    subject_id: str = Field(min_length=3, max_length=64)
    reason_code: ReportReasonCode
    details: str | None = Field(default=None, max_length=REPORT_DETAILS_MAX_LENGTH)


class ReportDTO(ContractModel):
    """The reporter sees their own report; staff see the same shape. No counterparty phone or name (Q43)."""

    id: str
    subject_type: ReportSubjectType
    subject_id: str
    reason_code: ReportReasonCode
    status: ReportStatus
    details: str | None = None
    created_at: UtcDateTime
    reviewed_at: UtcDateTime | None = None
    version: StrictInt


class ReportCommand(ContractModel):
    """S12b: an operator records what they decided; the report itself never changes a booking or a rating."""

    expected_version: StrictInt
    status: Literal["under_review", "dismissed", "actioned"]
    note: str | None = Field(default=None, max_length=DECISION_NOTE_MAX_LENGTH)


class FraudSignalDTO(ContractModel):
    """S12 (§17.3). A question for a human: what was noticed, about whom, with counts - never a verdict."""

    id: str
    signal_type: FraudSignalType
    subject_user_id: str
    status: FraudSignalStatus
    evidence: dict[str, int | list[str]]
    detected_at: UtcDateTime
    reviewed_at: UtcDateTime | None = None
    version: StrictInt


class FraudSignalCommand(ContractModel):
    expected_version: StrictInt
    status: Literal["under_review", "dismissed", "confirmed"]
    note: str | None = Field(default=None, max_length=DECISION_NOTE_MAX_LENGTH)
