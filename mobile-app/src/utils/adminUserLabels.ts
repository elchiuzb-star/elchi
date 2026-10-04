/**
 * Words the admin panel says about staff and v1 objects, in the reader's language.
 *
 * Every label goes through the dictionary (`i18n/screens/adminShell.ts`); a raw value (`super_admin`, `active`,
 * `in_transit`) is only shown when the dictionary has no entry for it, so an operator can still report it.
 */
import { ApiError } from "../types/api";
import { translate, translateDynamic, type MessageKey } from "../i18n";
import type { StaffUserRole, StaffUserStatus } from "../types/admin-user";

const ROLE_KEYS: Record<string, MessageKey> = {
  operator: "support.operator",
  admin: "admin.role.admin",
  super_admin: "admin.role.superAdmin",
  finance: "admin.role.finance",
  client: "admin.role.client",
  driver: "admin.common.driver",
  system: "admin.role.system",
};

export function adminRoleLabel(role?: StaffUserRole | string | null): string {
  if (!role) return "-";
  const key = ROLE_KEYS[role];
  return key ? translate(key) : role;
}

const STATUS_KEYS: Record<string, MessageKey> = {
  active: "admin.common.active",
  blocked: "admin.common.blocked",
  inactive: "admin.common.inactive",
};

export function adminStatusLabel(status?: StaffUserStatus | null): string {
  if (!status) return "-";
  const key = STATUS_KEYS[status];
  return key ? translate(key) : status;
}

export function adminUserStatusClass(status?: StaffUserStatus | null): string {
  if (status === "active") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "blocked") return "border-rose-200 bg-rose-50 text-rose-700";
  if (status === "inactive") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

/** Role badge tone, as in the design: super_admin and admin blue, finance navy, operator grey. */
export function adminRoleBadgeClass(role?: string | null): string {
  if (role === "finance") return "border-primary bg-primary text-primary-foreground";
  if (role === "admin" || role === "super_admin") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

/** "Ha" / "Yo'q" in the reader's language. */
export function yesNo(value: boolean | null | undefined): string {
  return translate(value ? "admin.common.yes" : "common.none");
}

/**
 * Staff-management refusals. A staff-specific sentence first (they talk about *the employee*), then the shared
 * error map, and only then the server's own message - which at least carries the reason.
 */
export function adminUserErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error && error.message ? error.message : translate("admin.common.actionFailed");
  return translateDynamic(`admin.staff.err.${error.code}`) ?? translateDynamic(`error.${error.code}`) ?? error.message;
}

/** A refused v1 admin request, in words: 403 is "no access", a known code its sentence, else the server's reason. */
export function adminErrorMessage(error: unknown, fallback: MessageKey = "admin.common.actionFailed"): string {
  if (error instanceof ApiError) {
    if (error.status === 403 && (error.code === "FORBIDDEN" || error.code === "ROLE_NOT_ALLOWED")) return translate("error.FORBIDDEN");
    return translateDynamic(`error.${error.code}`) ?? (error.message || translate(fallback));
  }
  if (error instanceof TypeError) return translate("error.offline");
  return translate(fallback);
}

// --- v1 order statuses, as the admin reads them -------------------------------------------------------------------

const ORDER_STATUS_KEYS: Record<string, MessageKey> = {
  draft: "status.draft",
  published: "status.published",
  bidding: "admin.orders.bids",
  accepted: "admin.orders.accepted",
  picked_up: "status.picked_up",
  in_transit: "admin.orders.inTransit",
  delivered: "admin.orders.delivered",
  confirmed: "status.approved",
  cancelled: "status.cancelled",
  disputed: "admin.orders.disputed",
};

export function adminOrderStatusLabel(status?: string | null): string {
  if (!status) return "-";
  const key = ORDER_STATUS_KEYS[status];
  return key ? translate(key) : status;
}

const BID_STATUS_KEYS: Record<string, MessageKey> = {
  active: "admin.common.active",
  pending: "status.pending",
  accepted: "admin.orders.accepted",
  rejected: "status.rejected",
  withdrawn: "status.withdrawn",
  cancelled: "status.cancelled",
  expired: "admin.bidStatus.expired",
};

export function adminBidStatusLabel(status?: string | null): string {
  if (!status) return "-";
  const key = BID_STATUS_KEYS[status];
  return key ? translate(key) : status;
}

const DISPUTE_STATUS_KEYS: Record<string, MessageKey> = {
  open: "admin.common.open_",
  under_review: "admin.common.underReview",
  resolved: "admin.disputeStatus.resolved",
  rejected: "status.rejected",
  closed: "admin.disputeStatus.closed",
  cancelled: "status.cancelled",
};

export function adminDisputeStatusLabel(status?: string | null): string {
  if (!status) return "-";
  const key = DISPUTE_STATUS_KEYS[status];
  return key ? translate(key) : status;
}

export function adminDisputeStatusClass(status?: string | null): string {
  if (status === "open") return "border-amber-200 bg-amber-50 text-amber-700";
  if (status === "under_review") return "border-blue-200 bg-blue-50 text-blue-700";
  if (status === "resolved") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "rejected") return "border-rose-200 bg-rose-50 text-rose-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

/** `ALLOWED_DISPUTE_REASONS` (app/services/dispute_service.py). */
const DISPUTE_REASON_KEYS: Record<string, MessageKey> = {
  delayed: "admin.disputeReason.delayed",
  lost: "admin.disputeReason.lost",
  damaged: "admin.disputeReason.damaged",
  receiver_denied: "admin.disputeReason.receiver_denied",
  wrong_address: "admin.disputeReason.wrong_address",
  payment_issue: "admin.disputeReason.payment_issue",
  prohibited_item: "admin.disputeReason.prohibited_item",
  other: "admin.disputeReason.other",
};

/** v1 dispute reasons are free text or a code; a known code is said in words, free text is shown as written. */
export function adminDisputeReasonLabel(reason?: string | null): string {
  if (!reason) return "-";
  const key = DISPUTE_REASON_KEYS[reason];
  return key ? translate(key) : reason;
}

const PAYMENT_KEYS: Record<string, MessageKey> = {
  cash: "admin.orders.cash",
  unpaid: "admin.orders.unpaid",
  paid: "admin.orders.paid",
  paid_manual: "admin.orders.paidManual",
};

export function adminPaymentLabel(value?: string | null): string {
  if (!value) return "-";
  const key = PAYMENT_KEYS[value];
  return key ? translate(key) : value;
}
