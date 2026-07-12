import type { RouteTariff, RouteTariffPayload, RouteTariffUpdatePayload } from "../types/tariff";

function cityName(city?: RouteTariff["from_city"]): string {
  return city?.name_uz ?? "-";
}

export function formatTariffRoute(tariff: Pick<RouteTariff, "from_city" | "to_city">): string {
  return `${cityName(tariff.from_city)} -> ${cityName(tariff.to_city)}`;
}

export function getTariffActiveLabel(isActive?: boolean | null): string {
  if (isActive === true) return "Faol";
  if (isActive === false) return "Nofaol";
  return "-";
}

export function getTariffActiveBadgeClass(isActive?: boolean | null): string {
  return isActive ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-600";
}

export function getReverseRouteLabel(hasReverse: boolean): string {
  return hasReverse ? "Qaytish tarifi mavjud" : "Qaytish tarifi topilmadi";
}

export function validateTariffPriceRange(payload: Partial<RouteTariffPayload & RouteTariffUpdatePayload>): string | null {
  const suggested = payload.suggested_price;
  const min = payload.min_price;
  const max = payload.max_price;
  if (suggested === undefined || suggested === null || Number.isNaN(Number(suggested))) return "Tavsiya narx kiritilishi shart.";
  if (Number(suggested) < 0) return "Tavsiya narx 0 yoki undan katta bo'lishi kerak.";
  if (min !== undefined && min !== null && Number(min) < 0) return "Minimal narx 0 yoki undan katta bo'lishi kerak.";
  if (max !== undefined && max !== null && Number(max) < 0) return "Maksimal narx 0 yoki undan katta bo'lishi kerak.";
  if (min !== undefined && min !== null && Number(min) > Number(suggested)) return "Minimal narx tavsiya narxdan katta bo'lishi mumkin emas.";
  if (max !== undefined && max !== null && Number(suggested) > Number(max)) return "Tavsiya narx maksimal narxdan katta bo'lishi mumkin emas.";
  return null;
}

export function tariffErrorMessage(code?: string): string {
  const messages: Record<string, string> = {
    ROUTE_TARIFF_ALREADY_EXISTS: "Bu yo'nalish uchun faol tarif allaqachon mavjud.",
    ROUTE_TARIFF_NOT_FOUND: "Tarif topilmadi.",
    INVALID_PRICE_RANGE: "Narx oralig'i noto'g'ri.",
    SAME_CITY_ROUTE: "Boshlanish va borish shahri bir xil bo'lishi mumkin emas.",
    CITY_NOT_FOUND: "Shahar topilmadi.",
    CITY_INACTIVE: "Tanlangan shahar nofaol.",
    VALIDATION_ERROR: "Validatsiya xatosi.",
    FORBIDDEN: "Ruxsat yo'q.",
    UNAUTHORIZED: "Qayta tizimga kiring.",
  };
  return code ? messages[code] ?? "Amal bajarilmadi." : "Amal bajarilmadi.";
}
