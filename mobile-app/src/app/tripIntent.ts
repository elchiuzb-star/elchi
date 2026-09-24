/**
 * ADR-0025: the saved trip/parcel request on the client. Pure helpers (no React, no network) so the screen logic is
 * testable: the short summary, the price line with an explicit unit, the bid prefill, the fit notes and the
 * per-user storage of which request is active.
 *
 * Rules kept here on purpose:
 * - a driver's advertised price and the client's own offer are shown apart, never merged;
 * - an expired window is reported, never moved to "tomorrow" silently;
 * - a driver whose seats, time or stop do not match is shown as a difference, the request is never adapted to it.
 */
import type { TripIntentDTO, TripIntentFitDTO } from "../api/v2/tripIntents.api";
import { translate } from "../i18n";
import { formatMinor } from "../utils/v2Format";

const DISPLAY_TZ = "Asia/Tashkent";

type End = TripIntentDTO["current_version"]["origin"];

export function endName(end: End): string {
  return end.stop?.name_uz ?? end.district?.name_uz ?? end.address ?? translate("intentFit.markedPlace");
}

function dayKey(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: DISPLAY_TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function timeOf(date: Date): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: DISPLAY_TZ, hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

/** "bugun" / "ertaga" / "25.09" - by the Tashkent calendar day, not the device's. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const today = dayKey(now);
  const tomorrow = dayKey(new Date(now.getTime() + 24 * 3600 * 1000));
  const key = dayKey(date);
  if (key === today) return translate("intentFit.today");
  if (key === tomorrow) return translate("intentFit.tomorrow");
  const [, month, day] = key.split("-");
  return `${day}.${month}`;
}

export function quantityLabel(intent: Pick<TripIntentDTO, "service_type" | "current_version">): string {
  return intent.service_type === "passenger" ? translate("intentFit.people", { count: intent.current_version.quantity }) : translate("intentFit.oneParcel");
}

/** "Toshkent → Qarshi · ertaga 12:00–14:00 · 3 kishi" */
export function intentSummary(intent: TripIntentDTO, now: Date = new Date()): string {
  const v = intent.current_version;
  const start = new Date(v.window_start);
  const end = new Date(v.window_end);
  const sameDay = dayKey(start) === dayKey(end);
  const when = sameDay
    ? `${dayLabel(v.window_start, now)} ${timeOf(start)}–${timeOf(end)}`
    : `${dayLabel(v.window_start, now)} ${timeOf(start)} – ${dayLabel(v.window_end, now)} ${timeOf(end)}`;
  return `${endName(v.origin)} → ${endName(v.destination)} · ${when} · ${quantityLabel(intent)}`;
}

export function isExpired(intent: Pick<TripIntentDTO, "current_version">, now: Date = new Date()): boolean {
  return new Date(intent.current_version.window_end).getTime() <= now.getTime();
}

/** "3 kishi × 190 000 so'm = 570 000 so'm" - the unit is always said; a total price says it is the total. */
export function priceLine(priceBasis: string, unitMinor: number, quantity: number, unitWord = translate("intentFit.personUnit")): string {
  if (priceBasis === "per_seat") {
    const total = unitMinor * quantity;
    return `${quantity} ${unitWord} × ${formatMinor(unitMinor)} = ${formatMinor(total)}`;
  }
  return translate("intentFit.priceLineTotal", { total: formatMinor(unitMinor) });
}

export type OfferLike = { price_basis: string; unit_price_minor: number; service_type: string };

export type BidPrefill = {
  seats: number;
  price: string;
  priceFromRequest: boolean;
  weightKg: string;
  lengthCm: string;
  widthCm: string;
  heightCm: string;
  receiverName: string;
  receiverPhone: string;
};

/**
 * What a driver's offer screen starts with. The request's own price hint is used only when it is in the same unit as
 * the driver's offer; otherwise the field starts from the driver's price and says so (`priceFromRequest=false`).
 */
export function prefillBid(intent: TripIntentDTO | null, offer: OfferLike): BidPrefill {
  const v = intent?.current_version;
  const parcel = v?.parcel ?? null;
  const sameUnit = Boolean(v && v.price_basis && v.unit_price_minor && v.price_basis === offer.price_basis);
  return {
    seats: intent && intent.service_type === "passenger" && v ? v.quantity : 1,
    price: String(Math.round((sameUnit ? (v!.unit_price_minor as number) : offer.unit_price_minor) / 100)),
    priceFromRequest: sameUnit,
    weightKg: parcel?.weight_g ? String(parcel.weight_g / 1000) : "",
    lengthCm: parcel?.length_cm ? String(parcel.length_cm) : "",
    widthCm: parcel?.width_cm ? String(parcel.width_cm) : "",
    heightCm: parcel?.height_cm ? String(parcel.height_cm) : "",
    receiverName: parcel?.receiver?.name ?? "",
    receiverPhone: parcel?.receiver?.phone ?? "",
  };
}

export type FitNote = { tone: "warn" | "block"; text: string };

function minutesText(minutes: number): string {
  if (minutes < 60) return translate("intentFit.minutes", { minutes });
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? translate("intentFit.hoursMinutes", { hours, minutes: rest }) : translate("intentFit.hours", { hours });
}

/** Differences between the request and one driver's offer, in the client's words. Nothing is changed to fit. */
export function fitNotes(fit: TripIntentFitDTO): FitNote[] {
  const notes: FitNote[] = [];
  if (!fit.service_match) notes.push({ tone: "block", text: translate("intentFit.otherService") });
  if (fit.expired) notes.push({ tone: "block", text: translate("intentFit.expired") });
  if (fit.availability.status === "insufficient") {
    notes.push({
      tone: "block",
      text: fit.availability.available !== null && fit.availability.available !== undefined
        ? translate("intentFit.seatsShort", { available: fit.availability.available, requested: fit.availability.requested })
        : translate("intentFit.parcelNoRoom"),
    });
  }
  if (fit.time.status === "outside") {
    notes.push({ tone: "warn", text: translate("intentFit.timeOutside", { difference: minutesText(fit.time.minutes_outside) }) });
  }
  const endNote = (status: string, end: "origin" | "destination") => {
    if (status === "same_district") {
      notes.push({ tone: "warn", text: end === "origin" ? translate("intentFit.originSameDistrict") : translate("intentFit.destinationSameDistrict") });
    }
    if (status === "different") {
      notes.push({ tone: "warn", text: end === "origin" ? translate("intentFit.originDifferent") : translate("intentFit.destinationDifferent") });
    }
  };
  endNote(fit.origin.status, "origin");
  endNote(fit.destination.status, "destination");
  return notes;
}

export function fitBlocks(fit: TripIntentFitDTO | null): boolean {
  return Boolean(fit && (fit.blockers?.length ?? 0) > 0);
}

/** What happens to open offers if the client saves this edit (the server decides; this only prepares the words). */
export function offersAffectedText(openOffers: number): string {
  return openOffers === 1
    ? translate("intentFit.offersAffectedOne")
    : translate("intentFit.offersAffected", { count: openOffers });
}

// --- which request is active, per signed-in person ------------------------------------------------------------

const STORAGE_PREFIX = "elchi.tripIntent.active.";

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function storageKey(userId: string | number): string {
  return `${STORAGE_PREFIX}${userId}`;
}

export function readActiveIntentId(userId: string | number | null | undefined): string | null {
  if (userId === null || userId === undefined || userId === "") return null;
  try {
    return storage()?.getItem(storageKey(userId)) ?? null;
  } catch {
    return null;
  }
}

export function writeActiveIntentId(userId: string | number | null | undefined, intentId: string | null): void {
  if (userId === null || userId === undefined || userId === "") return;
  try {
    const store = storage();
    if (!store) return;
    if (intentId) store.setItem(storageKey(userId), intentId);
    else store.removeItem(storageKey(userId));
  } catch {
    /* a private window: the request still lives on the server, only the shortcut is lost */
  }
}

// --- building request bodies ----------------------------------------------------------------------------------

type EndInput = { stop_id?: string | null; district_id?: string | null; lat?: number | null; lng?: number | null; address?: string | null };

/** The saved end, sent back unchanged: a verified stop by id, a marked place by district + point. */
export function endInputFromDto(end: End): EndInput {
  if (end.stop) return { stop_id: end.stop.id };
  return { district_id: end.district?.id ?? null, lat: end.lat ?? null, lng: end.lng ?? null, address: end.address ?? null };
}

/** An ISO instant as the value of a `datetime-local` input in the device's zone (the input has no zone). */
export function isoToLocalInput(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export type ParcelFields = {
  parcelType: string;
  weightKg: string;
  lengthCm: string;
  widthCm: string;
  heightCm: string;
  receiverName: string;
  receiverPhone: string;
};

/** Parcel fields as the API wants them; an empty field stays unset (the request may be completed later). */
export function parcelInput(fields: ParcelFields) {
  const positive = (value: string, scale = 1) => {
    const n = Math.round(Number(value) * scale);
    return Number.isFinite(n) && n > 0 ? n : null;
  };
  const name = fields.receiverName.trim();
  const phone = fields.receiverPhone.trim();
  return {
    parcel_type: fields.parcelType || null,
    weight_g: positive(fields.weightKg, 1000),
    length_cm: positive(fields.lengthCm),
    width_cm: positive(fields.widthCm),
    height_cm: positive(fields.heightCm),
    receiver: name && phone ? { name, phone } : null,
  };
}

/** Everything a driver's offer needs from a parcel request (Q79: the receiver too). */
export function parcelComplete(intent: TripIntentDTO | null): boolean {
  const parcel = intent?.current_version.parcel;
  return Boolean(parcel && parcel.parcel_type && parcel.weight_g && parcel.length_cm && parcel.width_cm
    && parcel.height_cm && parcel.receiver?.name && parcel.receiver?.phone);
}

/** True when the bid screen's parcel fields say something other than the saved request. */
export function parcelDiffers(intent: TripIntentDTO | null, fields: ParcelFields): boolean {
  const saved = intent?.current_version.parcel ?? null;
  const next = parcelInput(fields);
  return (saved?.parcel_type ?? null) !== next.parcel_type
    || (saved?.weight_g ?? null) !== next.weight_g
    || (saved?.length_cm ?? null) !== next.length_cm
    || (saved?.width_cm ?? null) !== next.width_cm
    || (saved?.height_cm ?? null) !== next.height_cm
    || (saved?.receiver?.name ?? null) !== (next.receiver?.name ?? null)
    || (saved?.receiver?.phone ?? null) !== (next.receiver?.phone ?? null);
}

/** The body of an edit that keeps every saved field and changes only `patch`. */
export function updateBody(intent: TripIntentDTO, patch: Record<string, unknown> = {}, acknowledge = false) {
  const v = intent.current_version;
  return {
    expected_version: intent.version,
    acknowledge_open_offers: acknowledge,
    origin: endInputFromDto(v.origin),
    destination: endInputFromDto(v.destination),
    window_start: v.window_start,
    window_end: v.window_end,
    quantity: v.quantity,
    price_basis: v.price_basis ?? null,
    unit_price_minor: v.unit_price_minor ?? null,
    parcel: v.parcel
      ? {
          parcel_type: v.parcel.parcel_type ?? null,
          weight_g: v.parcel.weight_g ?? null,
          length_cm: v.parcel.length_cm ?? null,
          width_cm: v.parcel.width_cm ?? null,
          height_cm: v.parcel.height_cm ?? null,
          receiver: v.parcel.receiver ?? null,
        }
      : null,
    ...patch,
  };
}

/** Which request the screen should show: the remembered one if it is still live, else the newest live one. */
export function pickActive(intents: TripIntentDTO[], rememberedId: string | null): TripIntentDTO | null {
  const live = intents.filter((item) => item.status !== "closed");
  return live.find((item) => item.id === rememberedId) ?? live.find((item) => item.status === "active") ?? live[0] ?? null;
}
