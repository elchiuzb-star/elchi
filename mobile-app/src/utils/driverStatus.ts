import { translate, type MessageKey } from "../i18n";
import type { AuthUser } from "../types/auth";
import type { AdminDriver, AdminDriverDocument, AdminDriverDocumentType, AdminDriverStatus } from "../types/admin-driver";

export const requiredDriverDocuments: AdminDriverDocumentType[] = ["passport", "selfie", "license", "car_document", "car_photo"];

const DOCUMENT_KEYS: Record<AdminDriverDocumentType, MessageKey> = {
  passport: "docType.passport",
  selfie: "docType.selfie",
  license: "docType.license",
  car_document: "docType.car_document",
  car_photo: "docType.car_photo",
};

/** The document's name in the reader's language. */
export function driverDocumentLabel(documentType: AdminDriverDocumentType | string): string {
  const key = DOCUMENT_KEYS[documentType as AdminDriverDocumentType];
  return key ? translate(key) : documentType;
}

const VERIFICATION_KEYS: Record<AdminDriverStatus, MessageKey> = {
  new: "app.driverVerification.new",
  pending: "admin.drivers.pending",
  approved: "status.approved",
  rejected: "status.rejected",
  blocked: "admin.common.blocked",
};

export function getDriverVerificationLabel(status?: string | null): string {
  if (!status) return "-";
  const key = VERIFICATION_KEYS[status as AdminDriverStatus];
  return key ? translate(key) : status;
}

const DOCUMENT_STATE_KEYS: Record<string, MessageKey> = {
  approved: "docState.approved",
  pending: "docState.pending",
  rejected: "docState.rejected",
  missing: "docState.missing",
};

/** Document review state: Tasdiqlangan / Tekshiruvda / Rad etilgan / Yuklanmagan (design §17.5). */
export function driverDocumentStateLabel(status?: string | null): string {
  const key = DOCUMENT_STATE_KEYS[status ?? "missing"];
  return key ? translate(key) : String(status);
}

export function driverDocumentStateClass(status?: string | null): string {
  if (status === "approved") return "border-success/25 bg-success/12 text-success";
  if (status === "rejected") return "border-destructive/25 bg-destructive/10 text-destructive";
  if (status === "pending") return "border-warning/28 bg-warning/14 text-warning";
  return "border-border bg-slate-50 text-secondary-foreground";
}

export function getDriverVerificationBadgeClass(status?: string | null): string {
  if (status === "approved") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "pending" || status === "new") return "border-blue-200 bg-blue-50 text-blue-700";
  if (status === "rejected" || status === "blocked") return "border-rose-200 bg-rose-50 text-rose-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

export function getAvailabilityLabel(isAvailable?: boolean, verificationStatus?: string | null): string {
  if (verificationStatus !== "approved") return translate("admin.drivers.availabilityOff");
  return translate(isAvailable ? "admin.drivers.isAvailable" : "admin.drivers.unavailable");
}

export function getAvailabilityBadgeClass(isAvailable?: boolean, verificationStatus?: string | null): string {
  if (verificationStatus !== "approved") return "border-slate-200 bg-slate-50 text-slate-500";
  return isAvailable ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700";
}

export function canApproveDriver(driver: AdminDriver, currentUser: AuthUser): boolean {
  return ["admin", "super_admin"].includes(currentUser.role) && !["approved", "blocked"].includes(driver.verification_status);
}

export function canRejectDriver(driver: AdminDriver, currentUser: AuthUser): boolean {
  return ["admin", "super_admin"].includes(currentUser.role) && !["approved", "blocked", "rejected"].includes(driver.verification_status);
}

export function canBlockDriver(driver: AdminDriver, currentUser: AuthUser): boolean {
  return ["admin", "super_admin"].includes(currentUser.role) && driver.verification_status !== "blocked";
}

/** Design §17.3: "Blokdan chiqarish" for a blocked driver, gated like blocking (admin+, admin_drivers.py unblock). */
export function canUnblockDriver(driver: AdminDriver, currentUser: AuthUser): boolean {
  return ["admin", "super_admin"].includes(currentUser.role) && driver.verification_status === "blocked";
}

/** Q94: operators may correct the vehicle as well as admins; finance and others may not. */
export function canEditDriverVehicle(currentUser: AuthUser): boolean {
  return ["operator", "admin", "super_admin"].includes(currentUser.role);
}

export function getMissingDriverDocuments(documents: AdminDriverDocument[] = []): AdminDriverDocumentType[] {
  const uploaded = new Set(documents.map((document) => document.document_type));
  return requiredDriverDocuments.filter((documentType) => !uploaded.has(documentType));
}
