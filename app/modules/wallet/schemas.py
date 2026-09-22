"""API v2 DTOs for wallet, top-ups, ledger and commission policies (API_V2_CONTRACT §9)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import Field, StrictInt

from app.contracts.dto import ContractModel, UtcDateTime, VersionedCommand
from app.contracts.enums import CommissionPolicyKind, Currency, ServiceType, TopupStatus

TopupMethod = Literal["bank_transfer", "cash_desk"]
SourceType = Literal["bank_statement", "cashier_receipt"]
Direction = Literal["debit", "credit"]


class WalletDTO(ContractModel):
    id: str
    currency: Currency
    posted_balance_minor: StrictInt
    held_minor: StrictInt
    available_minor: StrictInt
    pending_topups_minor: StrictInt
    as_of: UtcDateTime


class LedgerReferenceDTO(ContractModel):
    type: str
    id: str


class LedgerLineDTO(ContractModel):
    transaction_id: str
    occurred_at: UtcDateTime
    kind: Literal["topup", "commission_capture", "reversal", "adjustment"]
    direction: Direction
    amount_minor: StrictInt
    balance_after_minor: StrictInt
    reference: LedgerReferenceDTO


class TopupCreate(ContractModel):
    amount_minor: StrictInt = Field(gt=0)
    method: TopupMethod
    payer_reference: str | None = Field(default=None, max_length=128)
    evidence_file_id: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=500)


class TopupDTO(ContractModel):
    id: str
    status: TopupStatus
    amount_minor: StrictInt
    method: TopupMethod
    created_at: UtcDateTime
    decided_at: UtcDateTime | None = None


class UserRefDTO(ContractModel):
    id: str | None


class TopupEvidenceDTO(ContractModel):
    payer_reference: str | None
    evidence_file_id: str | None
    note: str | None
    source_type: SourceType | None
    source_reference: str | None
    received_amount_minor: StrictInt | None
    received_at: UtcDateTime | None


class TopupAdminDTO(TopupDTO):
    driver: UserRefDTO
    evidence: TopupEvidenceDTO
    first_approver: UserRefDTO | None = None
    second_approver: UserRefDTO | None = None
    version: StrictInt


class TopupApprove(VersionedCommand):
    source_type: SourceType
    source_reference: str = Field(min_length=1, max_length=128)
    received_amount_minor: StrictInt = Field(gt=0)
    received_at: UtcDateTime
    note: str | None = Field(default=None, max_length=500)


class TopupReject(VersionedCommand):
    reason: str = Field(min_length=1, max_length=500)


class LedgerAdjustmentCreate(ContractModel):
    wallet_id: str
    amount_minor: StrictInt = Field(gt=0)
    direction: Direction
    reason: str = Field(min_length=1, max_length=500)
    evidence_file_ids: list[str] = Field(default_factory=list, max_length=20)
    booking_id: str | None = None
    reversal_of_transaction_id: str | None = None


class LedgerEntryDTO(ContractModel):
    account_code: str
    direction: Direction
    amount_minor: StrictInt


class LedgerTransactionDTO(ContractModel):
    id: str
    reference: str
    entries: list[LedgerEntryDTO]
    reversal_of: str | None = None
    created_by: UserRefDTO | None = None
    second_approver: UserRefDTO | None = None
    created_at: UtcDateTime


class LedgerAdjustmentDTO(ContractModel):
    """W8 answer when the amount needs a second approver (202), and W16 request view."""

    id: str
    status: Literal["pending_second_approval", "posted", "rejected", "withdrawn"]
    wallet_id: str
    direction: Direction
    amount_minor: StrictInt
    reason: str
    requested_by: UserRefDTO
    approved_by: UserRefDTO | None = None
    rejected_by: UserRefDTO | None = None
    reject_reason: str | None = None
    decided_at: UtcDateTime | None = None
    # Seconds since creation while pending (finance queue age, wave 1.6); null once decided.
    pending_age_seconds: StrictInt | None = None
    version: StrictInt
    transaction: LedgerTransactionDTO | None = None
    created_at: UtcDateTime


class AdjustmentApprove(VersionedCommand):
    note: str | None = Field(default=None, max_length=500)


class AdjustmentReject(VersionedCommand):
    reason: str = Field(min_length=1, max_length=500)


class AdjustmentWithdraw(VersionedCommand):
    reason: str | None = Field(default=None, max_length=500)


class SplitAdjustmentSignalDTO(ContractModel):
    """Decision 30: possible splitting of adjustments around the two-person threshold (signal only)."""

    wallet_id: str
    requested_by: UserRefDTO
    window_start: UtcDateTime
    window_end: UtcDateTime
    count: StrictInt
    amount_minor: StrictInt
    adjustment_ids: list[str]


class FinanceReportRowDTO(ContractModel):
    date: date
    corridor: str | None = None
    amount_minor: StrictInt
    count: StrictInt


class FinanceReportTotalsDTO(ContractModel):
    amount_minor: StrictInt
    count: StrictInt


class FinanceReportPeriodDTO(ContractModel):
    from_: date = Field(alias="from")
    to: date


class FinanceReportDTO(ContractModel):
    report: str
    period: dict[str, date]
    rows: list[FinanceReportRowDTO]
    totals: FinanceReportTotalsDTO


class ReconciliationDTO(ContractModel):
    date: date
    wallets_checked: StrictInt
    mismatches: list[dict[str, Any]]
    unbalanced_transactions: list[dict[str, Any]]
    overdraft_wallets: list[dict[str, Any]]
    orphan_postings: list[dict[str, Any]] = Field(default_factory=list)


class FeeQuoteDTO(ContractModel):
    policy_id: str
    policy_kind: CommissionPolicyKind
    fee_bps: StrictInt
    commission_minor: StrictInt
    net_minor: StrictInt
    valid_until: UtcDateTime | None = None


class CommissionPolicyScope(ContractModel):
    corridor_id: str | None = None
    service_type: ServiceType | None = None


class CommissionPolicyCreate(ContractModel):
    kind: CommissionPolicyKind
    scope: CommissionPolicyScope = Field(default_factory=CommissionPolicyScope)
    fee_bps: StrictInt = Field(ge=0, le=10_000)
    effective_from: UtcDateTime
    effective_to: UtcDateTime | None = None
    campaign_name: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class CommissionPolicyEnd(VersionedCommand):
    effective_to: UtcDateTime
    reason: str = Field(min_length=1, max_length=500)


class CommissionPolicyConfirm(VersionedCommand):
    reason: str = Field(min_length=1, max_length=500)


class CommissionPolicyDTO(ContractModel):
    id: str
    kind: CommissionPolicyKind
    scope: CommissionPolicyScope
    fee_bps: StrictInt
    fee_percent: str
    effective_from: UtcDateTime
    effective_to: UtcDateTime | None = None
    campaign_name: str | None = None
    reason: str
    created_by: UserRefDTO | None = None
    created_at: UtcDateTime
    version: StrictInt
    is_active_now: bool
    # Decision 28: False only for the migration seed until a super_admin confirms it (W19).
    is_confirmed: bool
