import type { AuthUser } from "../types/auth";
import type { AdminDriver, AdminDriverDocument, AdminDriverDocumentType, AdminDriverStatus } from "../types/admin-driver";

export const requiredDriverDocuments: AdminDriverDocumentType[] = ["passport", "selfie", "license", "car_document", "car_photo"];

export const driverDocumentLabels: Record<AdminDriverDocumentType, string> = {
  passport: "Pasport",
  selfie: "Selfi",
  license: "Haydovchilik guvohnomasi",
  car_document: "Avtomobil hujjati",
  car_photo: "Avtomobil rasmi",
};

export const driverVerificationLabels: Record<AdminDriverStatus, string> = {
  new: "Yangi",
  pending: "Tekshiruv kutilmoqda",
  approved: "Tasdiqlangan",
  rejected: "Rad etilgan",
  blocked: "Bloklangan",
};

export function getDriverVerificationLabel(status?: string | null): string {
  if (!status) return "-";
  return driverVerificationLabels[status as AdminDriverStatus] ?? status;
}

export function getDriverVerificationBadgeClass(status?: string | null): string {
  if (status === "approved") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "pending" || status === "new") return "border-blue-200 bg-blue-50 text-blue-700";
  if (status === "rejected" || status === "blocked") return "border-rose-200 bg-rose-50 text-rose-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

export function getAvailabilityLabel(isAvailable?: boolean, verificationStatus?: string | null): string {
  if (verificationStatus !== "approved") return "O'chirilgan";
  return isAvailable ? "Mavjud" : "Mavjud emas";
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

export function getMissingDriverDocuments(documents: AdminDriverDocument[] = []): AdminDriverDocumentType[] {
  const uploaded = new Set(documents.map((document) => document.document_type));
  return requiredDriverDocuments.filter((documentType) => !uploaded.has(documentType));
}
