import { ApiError } from "../types/api";
import type { StaffUserRole, StaffUserStatus } from "../types/admin-user";

export function adminRoleLabel(role?: StaffUserRole | string | null): string {
  if (role === "super_admin") return "Super administrator";
  if (role === "admin") return "Administrator";
  if (role === "operator") return "Operator";
  return role || "-";
}

export function adminStatusLabel(status?: StaffUserStatus | null): string {
  if (status === "active") return "Faol";
  if (status === "blocked") return "Bloklangan";
  if (status === "inactive") return "Nofaol";
  return status || "-";
}

export function adminUserStatusClass(status?: StaffUserStatus | null): string {
  if (status === "active") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "blocked") return "border-rose-200 bg-rose-50 text-rose-700";
  if (status === "inactive") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

export function adminUserErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : "Amal bajarilmadi";
  const map: Record<string, string> = {
    FORBIDDEN: "Bu xodim amali uchun ruxsatingiz yo'q.",
    UNAUTHORIZED: "Sessiya muddati tugagan. Qayta kiring.",
    VALIDATION_ERROR: "Forma maydonlarini tekshirib, qayta urinib ko'ring.",
    USER_NOT_FOUND: "Xodim topilmadi.",
    USER_ALREADY_EXISTS: "Bu foydalanuvchi allaqachon mavjud.",
    ROLE_NOT_ALLOWED: "Bu xodim roliga bu yerda ruxsat berilmagan.",
    PHONE_ALREADY_EXISTS: "Bu telefon raqam boshqa akkauntga tegishli.",
    ALREADY_EXISTS: "Bu telefon raqam boshqa akkauntga tegishli.",
    USER_BLOCKED: "Bu xodim akkaunti bloklangan.",
    SERVER_ERROR: "Server xatosi. Qayta urinib ko'ring.",
  };
  return map[error.code] ?? error.message;
}
