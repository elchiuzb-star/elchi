/**
 * v2 display helpers (ADR-0010 §8): minor units -> so'm, UTC -> Asia/Tashkent. One place, no ad-hoc formatting.
 *
 * Money is integer minor units (1 so'm = 100 tiyin, AGENTS §6): never parsed into a float for arithmetic, only
 * formatted for display. The commission rate is never computed in the client (K5).
 */

const DISPLAY_TZ = "Asia/Tashkent";

export function formatMinor(amountMinor: number | null | undefined, currency = "UZS"): string {
  if (amountMinor === null || amountMinor === undefined || !Number.isFinite(amountMinor)) return "-";
  const negative = amountMinor < 0;
  const absolute = Math.abs(Math.trunc(amountMinor));
  const major = Math.trunc(absolute / 100);
  const minor = absolute % 100;
  const grouped = major.toLocaleString("ru-RU").replace(/ /g, " ");
  const suffix = currency === "UZS" ? "so'm" : currency;
  const text = minor === 0 ? `${grouped} ${suffix}` : `${grouped},${String(minor).padStart(2, "0")} ${suffix}`;
  return negative ? `-${text}` : text;
}

/** `2 x 200 000 so'm = 400 000 so'm` (AC01): the unit, the quantity and the total are all visible. */
export function formatPriceBreakdown(params: {
  price_basis: string;
  unit_price_minor: number;
  quantity: number;
  total_minor: number;
  currency?: string;
}): string {
  const { price_basis, unit_price_minor, quantity, total_minor, currency = "UZS" } = params;
  if (price_basis === "total" || quantity <= 1) return formatMinor(total_minor, currency);
  return `${quantity} x ${formatMinor(unit_price_minor, currency)} = ${formatMinor(total_minor, currency)}`;
}

export function priceBasisLabel(basis: string): string {
  return basis === "per_seat" ? "o'rin uchun" : basis === "per_kg" ? "kg uchun" : "jami";
}

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "-";
  return new Intl.DateTimeFormat("uz-UZ", {
    timeZone: DISPLAY_TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatDate(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "-";
  return new Intl.DateTimeFormat("uz-UZ", { timeZone: DISPLAY_TZ, day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
}

export function formatTime(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "-";
  return new Intl.DateTimeFormat("uz-UZ", { timeZone: DISPLAY_TZ, hour: "2-digit", minute: "2-digit" }).format(date);
}

export function formatWindow(start: string | null | undefined, end: string | null | undefined): string {
  const from = parse(start);
  const to = parse(end);
  if (!from) return "-";
  if (!to) return formatDateTime(start);
  return `${formatDate(start)} ${formatTime(start)}-${formatTime(end)}`;
}

/** Minutes since a UTC timestamp, for "x daqiqa oldin" labels; null when the value is missing. */
export function minutesSince(value: string | null | undefined, now: Date = new Date()): number | null {
  const date = parse(value);
  if (!date) return null;
  return Math.max(0, Math.round((now.getTime() - date.getTime()) / 60000));
}

/** Freshness of the last trusted GPS point; `null` means there is none - the UI says so instead of guessing. */
export function freshnessLabel(freshness: string | null | undefined): string {
  switch (freshness) {
    case "live":
      return "Jonli";
    case "recent":
      return "Yaqinda yangilandi";
    case "delayed":
      return "Kechikmoqda";
    case "lost":
      return "Signal yo'q";
    default:
      return "Ma'lumot yo'q";
  }
}
