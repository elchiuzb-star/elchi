/**
 * Finance staff calls for the admin panel (W5-W20, Q17, Q49, Q55, Q69, Q70, Q2, Q28).
 *
 * Every request travels with the admin session and every type comes from the generated contract. The server
 * decides who may do what (capability, MFA step-up, second approver, Q48 gate); this layer only carries the
 * request. Commands take the Idempotency-Key from the caller: the panel keeps one key per user action, so a retry
 * after a timeout replays the first answer instead of posting money twice (ADR-0005). Paths are written out in
 * full so tests/test_mobile_v2_client_contract.py can check them.
 */
import { v2AdminRequest, v2AdminRequestFull, type Schemas, type V2Result } from "./http";

export type TopupAdminDTO = Schemas["TopupAdminDTO"];
export type TopupStatus = Schemas["TopupStatus"];
export type TopupApprove = Schemas["TopupApprove"];
export type TopupReject = Schemas["TopupReject"];
export type LedgerAdjustmentDTO = Schemas["LedgerAdjustmentDTO"];
export type LedgerAdjustmentCreate = Schemas["LedgerAdjustmentCreate"];
export type LedgerTransactionDTO = Schemas["LedgerTransactionDTO"];
export type AdjustmentApprove = Schemas["AdjustmentApprove"];
export type AdjustmentReject = Schemas["AdjustmentReject"];
export type AdjustmentWithdraw = Schemas["AdjustmentWithdraw"];
export type CommissionPolicyDTO = Schemas["CommissionPolicyDTO"];
export type CommissionPolicyCreate = Schemas["CommissionPolicyCreate"];
export type CommissionPolicyEnd = Schemas["CommissionPolicyEnd"];
export type CommissionPolicyConfirm = Schemas["CommissionPolicyConfirm"];
export type CommissionPolicyKind = Schemas["CommissionPolicyKind"];
export type FinanceReportDTO = Schemas["FinanceReportDTO"];
export type ReconciliationDTO = Schemas["ReconciliationDTO"];
export type SplitAdjustmentSignalDTO = Schemas["SplitAdjustmentSignalDTO"];
export type PromoReportDTO = Schemas["PromoReportDTO"];
export type MeDTO = Schemas["MeDTO"];

/** Adjustment list filter: the contract names map to the stored ones on the server. */
export type AdjustmentStatusFilter = "pending" | "approved" | "rejected" | "withdrawn";
export type FinanceReportName = "commission_revenue" | "calculated_commission" | "cash_inflows" | "reversals";
export type PromoReportGroupBy = "service" | "corridor" | "campaign_version" | "cohort";

/** Cursor pages: `meta.next_cursor` is null on the last page. */
export type Page<T> = { items: T[]; nextCursor: string | null };

function page<T>(result: V2Result<T[]>): Page<T> {
  const meta = result.meta as { next_cursor?: string | null } | null | undefined;
  return { items: result.data, nextCursor: meta?.next_cursor ?? null };
}

/** Who I am in `usr_` form: the panel hides approve/reject of my own request (the server refuses it anyway). */
export function financeMe() {
  return v2AdminRequest<MeDTO>("/me");
}

// --- top-ups (W5-W8) ----------------------------------------------------------------------------------------------

export async function listTopups(params: { status?: TopupStatus; cursor?: string | null; limit?: number } = {}) {
  return page(await v2AdminRequestFull<TopupAdminDTO[]>("/admin/topups", { query: params }));
}

/**
 * Approves against a bank statement or cashier receipt. A large amount becomes `awaiting_second_approval` and a
 * *different* finance person repeats the same source and amount; the screenshot alone is never money (§9.2).
 */
export function approveTopup(topupId: string, body: TopupApprove, idempotencyKey: string) {
  return v2AdminRequest<TopupAdminDTO>(`/admin/topups/${encodeURIComponent(topupId)}/approve`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

export function rejectTopup(topupId: string, body: TopupReject, idempotencyKey: string) {
  return v2AdminRequest<TopupAdminDTO>(`/admin/topups/${encodeURIComponent(topupId)}/reject`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

// --- ledger adjustments (W16-W18) ---------------------------------------------------------------------------------

export async function listAdjustments(
  params: { status?: AdjustmentStatusFilter; wallet_id?: string; cursor?: string | null; limit?: number } = {},
) {
  return page(await v2AdminRequestFull<LedgerAdjustmentDTO[]>("/admin/ledger/adjustments", { query: params }));
}

export function getAdjustment(adjustmentId: string) {
  return v2AdminRequest<LedgerAdjustmentDTO>(`/admin/ledger/adjustments/${encodeURIComponent(adjustmentId)}`);
}

/**
 * A small adjustment posts at once (201, a ledger transaction); a large one waits for a second person (202, the
 * request). The two shapes are told apart by `entries`, which only a transaction has.
 */
export function createAdjustment(body: LedgerAdjustmentCreate, idempotencyKey: string) {
  return v2AdminRequest<LedgerTransactionDTO | LedgerAdjustmentDTO>("/admin/ledger/adjustments", {
    method: "POST",
    body,
    idempotencyKey,
  });
}

export function approveAdjustment(adjustmentId: string, body: AdjustmentApprove, idempotencyKey: string) {
  return v2AdminRequest<LedgerTransactionDTO>(`/admin/ledger/adjustments/${encodeURIComponent(adjustmentId)}/approve`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

export function rejectAdjustment(adjustmentId: string, body: AdjustmentReject, idempotencyKey: string) {
  return v2AdminRequest<LedgerAdjustmentDTO>(`/admin/ledger/adjustments/${encodeURIComponent(adjustmentId)}/reject`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

/** Q49: only the requester withdraws; nobody else can close it that way. */
export function withdrawAdjustment(adjustmentId: string, body: AdjustmentWithdraw, idempotencyKey: string) {
  return v2AdminRequest<LedgerAdjustmentDTO>(`/admin/ledger/adjustments/${encodeURIComponent(adjustmentId)}/withdraw`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

// --- commission policies (W11-W15, W19; Q2: manage is super_admin only) --------------------------------------------

export async function listCommissionPolicies(
  params: { active_at?: string; kind?: CommissionPolicyKind; cursor?: string | null; limit?: number } = {},
) {
  return page(await v2AdminRequestFull<CommissionPolicyDTO[]>("/admin/commission-policies", { query: params }));
}

export function getCommissionPolicy(policyId: string) {
  return v2AdminRequest<CommissionPolicyDTO>(`/admin/commission-policies/${encodeURIComponent(policyId)}`);
}

export function createCommissionPolicy(body: CommissionPolicyCreate, idempotencyKey: string) {
  return v2AdminRequest<CommissionPolicyDTO>("/admin/commission-policies", { method: "POST", body, idempotencyKey });
}

/** Q28: super_admin confirms the migration-seeded global rate once; until then production quote/hold stay blocked. */
export function confirmCommissionPolicy(policyId: string, body: CommissionPolicyConfirm, idempotencyKey: string) {
  return v2AdminRequest<CommissionPolicyDTO>(`/admin/commission-policies/${encodeURIComponent(policyId)}/confirm`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

export function endCommissionPolicy(policyId: string, body: CommissionPolicyEnd, idempotencyKey: string) {
  return v2AdminRequest<CommissionPolicyDTO>(`/admin/commission-policies/${encodeURIComponent(policyId)}/end`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

// --- reconciliation and reports (W9-W10, W20) ---------------------------------------------------------------------

/** Reads a stored run only; a day nobody reconciled is 404 `reconciliation_not_run`, not "all fine". */
export function financeReconciliation(date?: string) {
  return v2AdminRequest<ReconciliationDTO>("/admin/finance/reconciliation", { query: { date } });
}

export function financeReport(report: FinanceReportName, params: { from: string; to: string }) {
  return v2AdminRequest<FinanceReportDTO>(`/admin/finance/reports/${report}`, { query: params });
}

export function splitAdjustmentSignals(params: { from: string; to: string }) {
  return v2AdminRequest<SplitAdjustmentSignalDTO[]>("/admin/finance/signals/split-adjustments", { query: params });
}

export function promoReport(params: { from: string; to: string; group_by?: PromoReportGroupBy }) {
  return v2AdminRequest<PromoReportDTO>("/admin/promo/report", { query: params });
}
