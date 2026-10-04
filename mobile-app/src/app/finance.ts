/**
 * Pure rules for the finance staff panel (Q17, Q49, Q69, Q70, Q2, Q28). No I/O, no clock unless passed in.
 *
 * The server is the authority on every one of these decisions; the panel uses them only to avoid offering a button
 * that is certain to be refused (the requester's own approve, a manage action without the capability) and to say
 * *why* a money command was refused in words a finance person can act on.
 */
import { translate } from "../i18n";
import { ApiError } from "../types/api";
import { v2ErrorMessage } from "../utils/v2Errors";

export type Capabilities = ReadonlySet<string>;

export const CAP = {
  reports: "finance.reports",
  topupApprove: "finance.topup_approve",
  adjustment: "finance.adjustment",
  adjustmentApprove: "finance.adjustment_approve",
  policyView: "finance.commission_policy_view",
  policyManage: "finance.commission_policy_manage",
  promoView: "promo.campaign_view",
} as const;

/** The capability that should reveal the finance menu item: every finance tab reads with it. */
export const FINANCE_MENU_CAPABILITY = CAP.reports;

export type FinanceTab = "topups" | "adjustments" | "reports" | "policies";

/**
 * Tabs in the design order (DESIGN-ADMIN-DIFF §11) and the capability that reveals each. Top-uplar needs
 * `finance.topup_approve` (Q69): a queue the admin can never act on is not shown to the admin at all.
 */
export const FINANCE_TABS: Array<[FinanceTab, string]> = [
  ["topups", CAP.topupApprove],
  ["adjustments", CAP.reports],
  ["reports", CAP.reports],
  ["policies", CAP.policyView],
];

export function visibleFinanceTabs(caps: Capabilities): FinanceTab[] {
  return FINANCE_TABS.filter(([, cap]) => caps.has(cap)).map(([tab]) => tab);
}

/**
 * "150 000", "150000", "150 000,50" or "150000.5" so'm -> integer tiyin. Parsed as text, never through a float.
 * Returns null for empty, negative, zero (money commands never take zero) or malformed input.
 */
export function parseSoumToMinor(text: string): number | null {
  const cleaned = text.replace(/[\s ]/g, "");
  const match = /^(\d{1,13})(?:[.,](\d{1,2}))?$/.exec(cleaned);
  if (!match) return null;
  const major = Number(match[1]);
  const minor = match[2] ? Number(match[2].padEnd(2, "0")) : 0;
  const total = major * 100 + minor;
  if (!Number.isSafeInteger(total) || total <= 0) return null;
  return total;
}

/**
 * `<input type="datetime-local">` value, read as Tashkent wall time (UTC+05:00, no DST), -> ISO with an explicit
 * offset (the API refuses naive timestamps, AGENTS §6).
 */
export function tashkentLocalToIso(local: string): string | null {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(local.trim());
  if (!match) return null;
  return `${match[1]}T${match[2]}:${match[3]}:${match[4] ?? "00"}+05:00`;
}

/** Today in Tashkent as YYYY-MM-DD (report date inputs). */
export function tashkentToday(now: Date = new Date()): string {
  const shifted = new Date(now.getTime() + 5 * 3600 * 1000);
  return shifted.toISOString().slice(0, 10);
}

export function daysBefore(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}

// --- who may act on what ------------------------------------------------------------------------------------------

type TopupLike = { status: string; first_approver?: { id: string | null } | null };

export type TopupActions = {
  approve: boolean;
  reject: boolean;
  /** Second step of a large top-up: the approver repeats source and amount from the first approval. */
  secondStep: boolean;
  /** Plain reason when the approve button is not offered although the row is open. */
  note: string | null;
};

export function topupActions(topup: TopupLike, meId: string | null, caps: Capabilities): TopupActions {
  const open = topup.status === "pending" || topup.status === "awaiting_second_approval";
  const may = caps.has(CAP.topupApprove);
  if (!open) return { approve: false, reject: false, secondStep: false, note: null };
  if (!may) return { approve: false, reject: false, secondStep: false, note: translate("admin.finance.topupOnlyFinance") };
  const secondStep = topup.status === "awaiting_second_approval";
  const iApprovedFirst = secondStep && meId !== null && topup.first_approver?.id === meId;
  return {
    approve: !iApprovedFirst,
    reject: true,
    secondStep,
    note: iApprovedFirst ? translate("admin.finance.youApprovedFirst") : null,
  };
}

type AdjustmentLike = { status: string; requested_by: { id: string | null } };

export type AdjustmentActions = { approve: boolean; reject: boolean; withdraw: boolean; note: string | null };

/** Q49: the requester only withdraws; approve/reject belong to a *different* person with `adjustment_approve`. */
export function adjustmentActions(row: AdjustmentLike, meId: string | null, caps: Capabilities): AdjustmentActions {
  if (row.status !== "pending_second_approval") return { approve: false, reject: false, withdraw: false, note: null };
  const mine = meId !== null && row.requested_by.id === meId;
  if (mine) {
    return { approve: false, reject: false, withdraw: caps.has(CAP.adjustment), note: translate("admin.finance.youRequestedAdj") };
  }
  const may = caps.has(CAP.adjustmentApprove);
  // Q69: without the capability the row is simply read-only; no "ask somebody" button.
  return { approve: may, reject: may, withdraw: false, note: may ? null : translate("admin.finance.adjOnlyFinance") };
}

/** `entries` exists only on a posted ledger transaction (201); a request waiting for a second person has none. */
export function isPostedTransaction(value: object): boolean {
  return Array.isArray((value as { entries?: unknown }).entries);
}

// --- labels -------------------------------------------------------------------------------------------------------

export function topupStatusLabel(status: string): string {
  if (status === "pending") return translate("status.pending");
  if (status === "awaiting_second_approval") return translate("admin.finance.status.second");
  if (status === "approved") return translate("status.approved");
  if (status === "rejected") return translate("status.rejected");
  return status;
}

export function topupStatusTone(status: string): "ok" | "warn" | "err" | "gray" {
  return status === "approved" ? "ok" : status === "rejected" ? "err" : "warn";
}

export function adjustmentStatusLabel(status: string): string {
  if (status === "pending_second_approval") return translate("admin.finance.status.second");
  if (status === "posted") return translate("admin.finance.status.posted");
  if (status === "rejected") return translate("status.rejected");
  if (status === "withdrawn") return translate("status.withdrawn");
  return status;
}

export function topupMethodLabel(method: string): string {
  return method === "bank_transfer" ? translate("admin.finance.method.bank") : translate("admin.finance.method.cash");
}

export function sourceTypeLabel(source: string | null | undefined): string {
  return source === "cashier_receipt" ? translate("admin.finance.source.cashier_receipt") : translate("admin.finance.source.bank_statement");
}

export type ReportMeta = { key: FinanceReportKey; title: string; hint: string; kind: MoneyKind };
export type FinanceReportKey = "commission_revenue" | "calculated_commission" | "cash_inflows" | "reversals";

/**
 * What kind of money each report counts. The four are never added into one "Jami" (11c.3): captured commission is
 * income, a hold is not received money, a top-up is a driver's prepaid balance (a liability), and a reversal
 * subtracts from income. The table therefore totals each kind on its own row only.
 */
export type MoneyKind = "income" | "hold" | "prepaid" | "reversal";

export const REPORT_KEYS: Array<[FinanceReportKey, MoneyKind]> = [
  ["commission_revenue", "income"],
  ["calculated_commission", "hold"],
  ["cash_inflows", "prepaid"],
  ["reversals", "reversal"],
];

export function reportMeta(): ReportMeta[] {
  return REPORT_KEYS.map(([key, kind]) => ({
    key,
    kind,
    title: translate(`admin.finance.report.${key}`),
    hint: translate(`admin.finance.reportHint.${key}`),
  }));
}

export function moneyKindLabel(kind: MoneyKind): string {
  return translate(`admin.finance.kindOf.${kind}`);
}

// --- errors -------------------------------------------------------------------------------------------------------

function reasonOf(error: ApiError): string | undefined {
  const details = error.details;
  return typeof details === "object" && details !== null ? (details as { reason?: string }).reason : undefined;
}

export function isStepUp(error: unknown): boolean {
  return error instanceof ApiError && error.code === "FORBIDDEN" && reasonOf(error) === "step_up_required";
}

/** Q48/Q70: production money gate refused the command. Not a bug and not "try again later" — a launch gate. */
export function isGateRefusal(error: unknown): boolean {
  return error instanceof ApiError && error.code === "PRODUCTION_INVARIANTS_FAILED";
}

/**
 * Refusals that are a state of the world, not a failure: the Q48 launch gate, and a day nobody reconciled yet.
 * They are shown as a calm warning, never as a red error with "try again".
 */
export function isCalmRefusal(error: unknown): boolean {
  if (isGateRefusal(error)) return true;
  return error instanceof ApiError && error.code === "NOT_FOUND" && reasonOf(error) === "reconciliation_not_run";
}

export function gateMessage(): string {
  return translate("admin.finance.gate");
}

/** @deprecated the Uzbek text at import time; use `gateMessage()` (follows the active language). */
export const GATE_MESSAGE = gateMessage();

export function financeErrorMessage(error: unknown): string {
  if (isGateRefusal(error)) return gateMessage();
  if (error instanceof ApiError) {
    const reason = reasonOf(error);
    if (error.code === "SECOND_APPROVER_REQUIRED") return translate("admin.finance.err.secondApprover");
    if (error.code === "FORBIDDEN" && reason === "self_approval") return translate("admin.finance.err.selfApproval");
    if (error.code === "FORBIDDEN" && reason === "only_requester_may_withdraw") return translate("admin.finance.err.onlyRequester");
    if (error.code === "VERSION_CONFLICT") return translate("admin.finance.err.versionConflict");
    if (error.code === "VALIDATION_ERROR" && reason === "second_approval_mismatch") return translate("admin.finance.err.secondMismatch");
    if (error.code === "NOT_FOUND" && reason === "reconciliation_not_run") return translate("admin.finance.err.reconNotRun");
    if (error.code === "COMMISSION_POLICY_RETROACTIVE") return translate("admin.finance.err.retroactive");
    if (error.code === "COMMISSION_POLICY_OVERLAP") return translate("admin.finance.err.overlap");
  }
  return v2ErrorMessage(error);
}
