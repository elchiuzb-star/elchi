// Mapping helpers that adapt backend payloads onto the shapes the
// presentational screens expect.

export type CityLike = { id?: number; name_uz?: string; name_ru?: string } | null | undefined;
export type DistrictLike = { id?: number; name_uz?: string; name_ru?: string } | null | undefined;

export function cityName(city: CityLike, lang = "uz"): string {
  if (!city) return "";
  if (lang === "ru" && city.name_ru) return city.name_ru;
  return city.name_uz ?? "";
}

export function districtName(district: DistrictLike, lang = "uz"): string {
  if (!district) return "";
  if (lang === "ru" && district.name_ru) return district.name_ru;
  return district.name_uz ?? "";
}

export function toNumber(value: number | string | null | undefined): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

/** Relative-ish date label for compact cards. */
export function shortDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const time = date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `Bugun, ${time}`;
  if (date.toDateString() === yesterday.toDateString()) return `Kecha, ${time}`;
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

/** Map backend driver route status -> the UI's active/inactive badge. */
export function routeUiStatus(status?: string): "active" | "inactive" {
  return status === "available" ? "active" : "inactive";
}

/** Map backend driver verification_status -> the UI's approved/pending/new. */
export function driverUiStatus(status?: string): "approved" | "pending" | "new" {
  if (status === "approved") return "approved";
  if (status === "pending") return "pending";
  return "new";
}
