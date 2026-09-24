"""Request bodies and DTOs of the promotions API (referral stage 5, ADR-0023 §16, §19).

Money is in minor units with a currency. A client-facing object never carries a commission, a driver credit, a cost,
a margin or a rate (Q16, Q103). A bonus is shown as a *discount right*: nothing here is a withdrawable balance.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, StrictInt

from app.contracts.dto import ContractModel, UtcDateTime
from app.contracts.enums import Currency, PromoInstrument, ServiceType

Audience = Literal["client", "driver"]


# --- client ---------------------------------------------------------------------------------------------------------


class ReferralCodeDTO(ContractModel):
    code: str
    share_url: str | None = Field(
        default=None, description="Only when a link host is configured. Even then the link may not work yet: DNS, "
        "certificate and App Links are verified separately (link_status).")
    link_status: Literal["not_configured", "configured_unverified"]


class ReferralCodeCheckDTO(ContractModel):
    """The only thing a public code check says (ADR-0023 §16): usable or not - never who owns it."""

    valid: bool


class AttributionRequest(ContractModel):
    code: str = Field(min_length=1, max_length=32)
    audience: Audience


class AttributionDTO(ContractModel):
    id: str
    audience: Audience
    status: str
    attributed_at: UtcDateTime
    window_ends_at: UtcDateTime


class DisclosureDTO(ContractModel):
    """Conditions shown before joining (Q112). ``code`` is stable; the client renders the sentence."""

    code: str
    value: Any


class EnrollmentOfferDTO(ContractModel):
    campaign_id: str
    campaign_name: str
    service_type: ServiceType
    attribution_id: str
    version_no: int
    terms_fingerprint: str
    disclosures: list[DisclosureDTO]
    parcel_sender_pays_only: bool = Field(
        description="Parcel campaigns: the bonus is used only when the sender pays (Q104).")


class EnrollmentRequest(ContractModel):
    attribution_id: str = Field(min_length=4, max_length=64)
    campaign_id: str = Field(min_length=4, max_length=64)
    version_no: StrictInt = Field(ge=1)
    terms_fingerprint: str = Field(min_length=64, max_length=64)


class MilestoneDTO(ContractModel):
    threshold: int
    reached: bool


class ProgressDTO(ContractModel):
    """Stage 5, the referee's own progress: services (or distinct trips) that fully count, those still being checked
    (waiting for the commission capture, the 48 h window or a person) and what is left. A service being checked is
    never counted as done. The numbers are the campaign version's own values."""

    unit: Literal["service", "distinct_trip"]
    required: int
    done: int
    in_review: int
    remaining: int
    milestones: list[MilestoneDTO] = Field(default_factory=list)


class EnrollmentDTO(ContractModel):
    id: str
    campaign_id: str
    campaign_name: str
    service_type: ServiceType
    side: Literal["referee", "referrer"]
    status: str
    qualification_status: str | None = Field(
        default=None, description="waiting | review | qualified | granted | rejected; null before the first "
        "qualifying service is seen.")
    enrolled_at: UtcDateTime
    qualification_deadline: UtcDateTime
    progress: ProgressDTO | None = Field(
        default=None, description="Referee side only (the referrer never sees the other person's activity).")


class InvitedCountsDTO(ContractModel):
    """People who joined with my code, by status - counts only, never who."""

    attributed: int = 0
    qualifying: int = 0
    qualified: int = 0
    expired: int = 0
    rejected: int = 0


class MyReferralsDTO(ContractModel):
    attributions: list[AttributionDTO]
    enrollments: list[EnrollmentDTO]
    invited: InvitedCountsDTO


class PromoBucketDTO(ContractModel):
    """One instrument on one service type. Not money: cannot be withdrawn, transferred or paid out."""

    instrument: PromoInstrument
    service_type: ServiceType
    available_minor: int
    reserved_minor: int = Field(description="Held for a booking that is not finished yet.")
    under_review_minor: int = Field(description="Not spendable while a person checks it.")
    consumed_minor: int
    expired_minor: int
    reversed_minor: int
    next_expiry_at: UtcDateTime | None = None
    currency: Currency = Currency.UZS


class PromoLotDTO(ContractModel):
    id: str
    instrument: PromoInstrument
    service_type: ServiceType
    status: str
    amount_minor: int
    available_minor: int
    reserved_minor: int
    consumed_minor: int
    expired_minor: int
    available_from: UtcDateTime | None = None
    expires_at: UtcDateTime
    currency: Currency = Currency.UZS


class PromoBalanceDTO(ContractModel):
    buckets: list[PromoBucketDTO]
    lots: list[PromoLotDTO]


# --- staff ----------------------------------------------------------------------------------------------------------


class BudgetDTO(ContractModel):
    allocated_minor: int
    promised_minor: int
    granted_minor: int
    consumed_minor: int
    released_minor: int
    available_for_new_minor: int
    shortfall_minor: int
    pending_reinstatements_minor: int = Field(default=0, description="Approved reinstatements waiting for room (in L).")
    reducible_minor: int = Field(default=0, description="max(0, B - S - L): the most a plain reduction may take (G14).")
    currency: Currency = Currency.UZS


class CampaignVersionDTO(ContractModel):
    version_no: int
    referrer_reward_minor: int | None = None
    referee_reward_minor: int | None = None
    referrer_instrument: PromoInstrument | None = None
    referee_instrument: PromoInstrument | None = None
    milestone_thresholds: list[int] | None = None
    min_distinct_clients: int | None = None
    enrollment_limit: int | None = None
    qualification_window_s: int | None = None
    reward_validity_s: int | None = None
    review_sla_s: int | None = None
    restoration_grace_s: int | None = None
    max_discount_share_bps: int | None = None
    max_discount_per_booking_minor: int | None = None
    passenger_bonus_max_per_booking_minor: int | None = None
    driver_credit_max_per_booking_minor: int | None = None
    variable_cost_fixed_minor: int | None = None
    variable_cost_bps: int | None = None
    min_margin_minor: int | None = None
    approval_reference: str | None = None
    missing_for_activation: list[str]
    created_at: UtcDateTime


class CombinationDTO(ContractModel):
    """Q123: an approved pairing of two campaigns on one booking (P from one, H from the other)."""

    id: str
    campaign_ids: list[str]
    cost_basis: Literal["shared", "additive"]
    status: Literal["active", "revoked"]
    reason: str
    created_at: UtcDateTime
    revoked_at: UtcDateTime | None = None
    version: int


class CombinationCreate(ContractModel):
    other_campaign_id: str = Field(min_length=4, max_length=64)
    cost_basis: Literal["shared", "additive"] = Field(
        description="shared: both O describe the same booking cost (the larger counts); additive: each campaign has "
        "its own extra cost (both count). Chosen explicitly - there is no default.")
    reason: str = Field(min_length=1, max_length=500)


class CombinationRevoke(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class CampaignDTO(ContractModel):
    id: str
    name: str
    kind: str
    family: str
    service_type: ServiceType
    status: str
    version: int
    active_version_no: int | None = None
    processing_suspended_at: UtcDateTime | None = None
    processing_suspend_reason: str | None = None
    budget: BudgetDTO
    versions: list[CampaignVersionDTO] = Field(default_factory=list)
    combinations: list[CombinationDTO] = Field(default_factory=list)


class CampaignCreate(ContractModel):
    kind: str = Field(min_length=1, max_length=32)
    service_type: ServiceType
    name: str = Field(min_length=1, max_length=120)


class CampaignVersionCreate(ContractModel):
    """Every value is a proposal by staff; ``null`` stays *not decided* and blocks activation (Q105)."""

    referrer_reward_minor: StrictInt | None = Field(default=None, gt=0)
    referee_reward_minor: StrictInt | None = Field(default=None, gt=0)
    referrer_instrument: PromoInstrument | None = None
    referee_instrument: PromoInstrument | None = None
    milestone_thresholds: list[StrictInt] | None = None
    min_distinct_clients: StrictInt | None = Field(default=None, ge=0)
    enrollment_limit: StrictInt | None = Field(default=None, gt=0)
    qualification_window_s: StrictInt | None = Field(default=None, gt=0)
    reward_validity_s: StrictInt | None = Field(default=None, gt=0)
    review_sla_s: StrictInt | None = Field(default=None, gt=0)
    restoration_grace_s: StrictInt | None = Field(default=None, ge=0)
    max_discount_share_bps: StrictInt | None = Field(default=None, ge=0, le=10_000)
    max_discount_per_booking_minor: StrictInt | None = Field(default=None, ge=0)
    passenger_bonus_max_per_booking_minor: StrictInt | None = Field(default=None, ge=0)
    driver_credit_max_per_booking_minor: StrictInt | None = Field(default=None, ge=0)
    variable_cost_fixed_minor: StrictInt | None = Field(default=None, ge=0)
    variable_cost_bps: StrictInt | None = Field(default=None, ge=0, le=10_000)
    min_margin_minor: StrictInt | None = Field(default=None, ge=0)
    approval_reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class CampaignCommand(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    version_no: StrictInt | None = Field(default=None, ge=1, description="activate: which version.")


class ProcessingCommand(ContractModel):
    reason: str = Field(min_length=1, max_length=500)


class BudgetRequestCreate(ContractModel):
    kind: Literal["allocate", "reduce_allocation", "funding_loss"] = Field(
        description="reduce_allocation never goes below spent + outstanding obligations (B >= S + L, G14); "
        "funding_loss records external funding that is really gone - evidence_reference required, may leave a "
        "shortfall, pauses the campaign, cancels nothing.")
    amount_minor: StrictInt = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    evidence_reference: str | None = Field(default=None, max_length=200)


class BudgetRequestDecision(ContractModel):
    expected_version: StrictInt = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500, description="Required to reject.")


class BudgetRequestDTO(ContractModel):
    id: str
    campaign_id: str
    kind: str
    amount_minor: int
    currency: Currency = Currency.UZS
    reason: str
    evidence_reference: str | None = None
    status: str
    requested_by_me: bool
    needs_second_approver: bool
    decided_at: UtcDateTime | None = None
    version: int
    created_at: UtcDateTime


class ReviewDTO(ContractModel):
    id: str
    kind: str
    status: str
    reason_codes: list[str]
    evidence: list[dict]
    campaign_id: str | None = None
    opened_at: UtcDateTime
    due_at: UtcDateTime | None = None
    escalated_at: UtcDateTime | None = None
    assigned_to_me: bool
    decision_note: str | None = None
    decided_at: UtcDateTime | None = None
    version: int


class ReviewStart(ContractModel):
    note: str | None = Field(default=None, max_length=1000)


class ReviewDecision(ContractModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=1000)
    expected_version: StrictInt = Field(ge=1)


class ReconciliationIssueDTO(ContractModel):
    kind: str
    detail: dict


# --- operational report (A6.2): real rows only, never simulator output ---------------------------------------------


class PromoReportPeriodDTO(ContractModel):
    start_at: UtcDateTime
    end_at: UtcDateTime
    end_exclusive: bool = True
    day_bounds: Literal["UTC"] = "UTC"


class PromoReportCohortDTO(ContractModel):
    anchor: Literal["enrollment_week_asia_tashkent"]
    week_start: str
    observed_days: int
    matured_d30: bool = Field(description="Every enrollment of the week has been observed for 30 days.")
    matured_d60: bool


class PromoReportValuesDTO(ContractModel):
    """``None`` = the metric does not apply to this grouping (never "0")."""

    enrollments: int | None = None
    enrollments_granted: int | None = None
    enrollments_open: int | None = None
    enrollments_released: int | None = None
    promised_minor: int | None = None
    granted_passenger_bonus_minor: int | None = None
    granted_driver_credit_minor: int | None = None
    spent_passenger_bonus_minor: int | None = None
    spent_driver_credit_minor: int | None = None
    expired_minor: int | None = None
    promo_bookings: int | None = None
    base_commission_minor: int | None = None
    passenger_bonus_minor: int | None = None
    driver_credit_minor: int | None = None
    net_commission_agreed_minor: int | None = None
    net_commission_captured_minor: int | None = None
    commission_reversed_minor: int | None = None
    net_commission_kept_minor: int | None = None
    promised_open_minor: int | None = None
    promised_in_review_minor: int | None = None
    granted_unspent_minor: int | None = None
    reserved_on_bookings_minor: int | None = None
    lots_pending_review_minor: int | None = None
    outstanding_liability_minor: int | None = None
    pending_review_minor: int | None = None


class PromoReportRowDTO(ContractModel):
    key: str = Field(description="service type, corridor id, campaign id/version, enrollment week or no_enrollment")
    values: PromoReportValuesDTO
    cohort: PromoReportCohortDTO | None = None


class PromoReportBudgetDTO(ContractModel):
    campaign_id: str
    service_type: ServiceType
    kind: str
    status: str
    allocated_minor: int
    promised_minor: int
    granted_unspent_minor: int = Field(description="Granted and not yet spent; includes reserved_on_bookings_minor.")
    reserved_on_bookings_minor: int
    consumed_minor: int
    released_minor: int
    committed_minor: int
    outstanding_liability_minor: int
    shortfall_minor: int
    funded_commitment_minor: int
    available_for_new_minor: int
    pending_reinstatements_minor: int
    reducible_minor: int = Field(description="max(0, B - S - L): the most a plain reduction may take (G14).")
    pending_review_minor: int
    alerts: list[Literal["budget_shortfall"]]


class PromoReportDTO(ContractModel):
    data_source: Literal["operational"] = Field(description="Real rows. Simulator results are never served here.")
    currency: Currency = Currency.UZS
    amount_unit: Literal["minor"] = "minor"
    group_by: Literal["service", "corridor", "campaign_version", "cohort"]
    generated_at: UtcDateTime
    period: PromoReportPeriodDTO
    period_basis: dict[str, str]
    rows: list[PromoReportRowDTO]
    budgets: list[PromoReportBudgetDTO] = Field(description="State as of generated_at, whatever the period.")
