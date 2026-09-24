/**
 * Pure rules for the finance staff panel (Q17, Q49, Q69, Q70, Q2, Q28). No I/O, no clock unless passed in.
 *
 * The server is the authority on every one of these decisions; the panel uses them only to avoid offering a button
 * that is certain to be refused (the requester's own approve, a manage action without the capability) and to say
 * *why* a money command was refused in words a finance person can act on.
 */
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
  if (!may) {
    return { approve: false, reject: false, secondStep: false, note: "Top-upni faqat faol moliya xodimi yoki super admin tasdiqlaydi." };
  }
  const secondStep = topup.status === "awaiting_second_approval";
  const iApprovedFirst = secondStep && meId !== null && topup.first_approver?.id === meId;
  return {
    approve: !iApprovedFirst,
    reject: true,
    secondStep,
    note: iApprovedFirst ? "Siz birinchi tasdiqlagansiz — ikkinchi tasdiqni boshqa moliya xodimi beradi." : null,
  };
}

type AdjustmentLike = { status: string; requested_by: { id: string | null } };

export type AdjustmentActions = { approve: boolean; reject: boolean; withdraw: boolean; note: string | null };

/** Q49: the requester only withdraws; approve/reject belong to a *different* person with `adjustment_approve`. */
export function adjustmentActions(row: AdjustmentLike, meId: string | null, caps: Capabilities): AdjustmentActions {
  if (row.status !== "pending_second_approval") return { approve: false, reject: false, withdraw: false, note: null };
  const mine = meId !== null && row.requested_by.id === meId;
  if (mine) {
    return {
      approve: false,
      reject: false,
      withdraw: caps.has(CAP.adjustment),
      note: "Siz so'ragansiz — tasdiqlash yoki rad etishni boshqa moliya xodimi qiladi.",
    };
  }
  const may = caps.has(CAP.adjustmentApprove);
  return {
    approve: may,
    reject: may,
    withdraw: false,
    note: may ? null : "Tasdiqlash uchun «finance.adjustment_approve» ruxsati kerak.",
  };
}

/** `entries` exists only on a posted ledger transaction (201); a request waiting for a second person has none. */
export function isPostedTransaction(value: object): boolean {
  return Array.isArray((value as { entries?: unknown }).entries);
}

// --- labels -------------------------------------------------------------------------------------------------------

export const TOPUP_STATUS: Record<string, string> = {
  pending: "kutilmoqda",
  awaiting_second_approval: "ikkinchi tasdiq kutilmoqda",
  approved: "tasdiqlangan (balansga o'tgan)",
  rejected: "rad etilgan",
};

export const ADJUSTMENT_STATUS: Record<string, string> = {
  pending_second_approval: "ikkinchi tasdiq kutilmoqda",
  posted: "o'tkazilgan",
  rejected: "rad etilgan",
  withdrawn: "qaytarib olingan",
};

export const REPORTS: Array<[string, string, string]> = [
  ["commission_revenue", "Undirilgan komissiya", "Haqiqatda capture qilingan komissiya (ledger)."],
  [
    "calculated_commission",
    "Hisoblangan komissiya (hold)",
    "Bronlarda band qilingan summa. Bu tushgan pul emas — capture bo'lmaguncha daromad hisoblanmaydi.",
  ],
  ["cash_inflows", "Tasdiqlangan top-uplar", "Moliya xodimi bank/kassa hujjati bilan tasdiqlagan tushumlar."],
  ["reversals", "Komissiya qaytarishlari", "Capture qilingan komissiyaning qaytarilgan qismi."],
];

export function label(map: Record<string, string>, value: string): string {
  return map[value] ?? value;
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

export const GATE_MESSAGE =
  "Production pul himoyasi (Q48) hali o'tmagan: top-up tasdiqlash va kredit tuzatishlar bloklangan. Bu xato emas — " +
  "DB rollari ajratilib, balans himoyasi va seed stavka tasdiqlangach ochiladi. Hech qanday pul o'tkazilmadi.";

export function financeErrorMessage(error: unknown): string {
  if (isGateRefusal(error)) return GATE_MESSAGE;
  if (error instanceof ApiError) {
    const reason = reasonOf(error);
    if (error.code === "SECOND_APPROVER_REQUIRED") {
      return "Ikkinchi tasdiqni boshqa xodim berishi kerak: so'rovchi yoki birinchi tasdiqlovchi o'zi tasdiqlay olmaydi.";
    }
    if (error.code === "FORBIDDEN" && reason === "self_approval") return "O'z top-upingizni tasdiqlay olmaysiz.";
    if (error.code === "FORBIDDEN" && reason === "only_requester_may_withdraw") {
      return "So'rovni faqat uni yuborgan xodim qaytarib oladi.";
    }
    if (error.code === "VERSION_CONFLICT") return "Yozuv boshqa xodim tomonidan o'zgartirilgan. Ro'yxat yangilandi — qayta ko'rib chiqing.";
    if (error.code === "VALIDATION_ERROR" && reason === "second_approval_mismatch") {
      return "Ikkinchi tasdiqdagi manba turi, hujjat raqami yoki summa birinchi tasdiqdagisi bilan mos emas.";
    }
    if (error.code === "NOT_FOUND" && reason === "reconciliation_not_run") {
      return "Bu kun uchun solishtiruv hali ishga tushirilmagan. Natija yo'q — bu «hammasi mos» degani emas.";
    }
    if (error.code === "COMMISSION_POLICY_RETROACTIVE") return "Siyosat o'tgan vaqtdan boshlana yoki tugay olmaydi.";
    if (error.code === "COMMISSION_POLICY_OVERLAP") return "Shu doirada bu davrda boshqa siyosat amal qiladi.";
  }
  return v2ErrorMessage(error);
}
