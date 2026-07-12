import type { City } from "../types/city";
import type { District } from "../types/district";

export function getCityTypeLabel(type?: string | null): string {
  if (type === "city") return "Shahar";
  if (type === "region") return "Viloyat";
  if (type === "republic") return "Respublika";
  return type || "-";
}

export function getRequiresDistrictLabel(value?: boolean | null): string {
  if (value === true) return "Talab qilinadi";
  if (value === false) return "Talab qilinmaydi";
  return "-";
}

export function getActiveStatusLabel(value?: boolean | null): string {
  if (value === true) return "Faol";
  if (value === false) return "Nofaol";
  return "-";
}

export function hasEncodingIssue(value?: string | null): boolean {
  if (!value) return false;
  return /\?{2,}|Р[Ѐ-ӿ]|Ð|�/.test(value);
}

export function cleanLocationText(value?: string | null): string {
  if (!value) return "-";
  return value;
}

export function formatCityDisplayName(city?: City | null): string {
  if (!city) return "-";
  return [city.name_uz, city.region].filter(Boolean).join(", ") || "-";
}

export function formatDistrictDisplayName(district?: District | null): string {
  if (!district) return "-";
  return district.name_uz || "-";
}

export function locationErrorMessage(code?: string): string {
  const messages: Record<string, string> = {
    CITY_ALREADY_EXISTS: "Shahar allaqachon mavjud",
    CITY_NOT_FOUND: "Shahar topilmadi",
    CITY_INACTIVE: "Shahar nofaol",
    DISTRICT_ALREADY_EXISTS: "Bu shaharda tuman allaqachon mavjud",
    DISTRICT_NOT_FOUND: "Tuman topilmadi",
    DISTRICT_INACTIVE: "Tuman nofaol",
    DISTRICT_CITY_MISMATCH: "Tuman tanlangan shaharga tegishli emas",
    VALIDATION_ERROR: "Validatsiya xatosi",
    FORBIDDEN: "Ruxsat yo'q",
    UNAUTHORIZED: "Avtorizatsiya talab qilinadi",
  };
  return code ? messages[code] ?? "Amal bajarilmadi" : "Amal bajarilmadi";
}
