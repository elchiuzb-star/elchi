/**
 * Referral and bonus rules the screens need, in one pure module (referral stage 5, ADR-0023 §19).
 *
 * The server decides every amount. This module only picks which server number to show, builds the consent body
 * from what the person *explicitly* chose, and turns stable codes into sentences in the person's language - so the rules can be tested
 * directly instead of through a rendered screen (the same reason `auction.ts` exists).
 *
 * Nothing here computes a discount. A bonus is a *discount right*, never money: the words "balans", "pul",
 * "yechib olish" are not used for it.
 */
import type { Schemas } from "../api/v2/http";
import { translate } from "../i18n";

export type ProposalPromoClientDTO = Schemas["ProposalPromoClientDTO"];
export type ProposalPromoDriverDTO = Schemas["ProposalPromoDriverDTO"];
export type BookingPromoClientDTO = Schemas["BookingPromoClientDTO"];
export type BookingPromoDriverDTO = Schemas["BookingPromoDriverDTO"];
export type PromoBucketDTO = Schemas["PromoBucketDTO"];
export type EnrollmentOfferDTO = Schemas["EnrollmentOfferDTO"];
export type DisclosureDTO = Schemas["DisclosureDTO"];

/** What this app can render (Q110). A rendering capability, never an authority. */
export const CLIENT_FEATURES = "promo_cash_v1";

// --- which amount is the cash one ------------------------------------------------------------------------------

type WithPromo = {
  total_minor: number;
  promo?: BookingPromoClientDTO | BookingPromoDriverDTO | null;
};

/** The cash that changes hands: F_cash on a discounted booking, the fare otherwise. Never the fare when a discount
 * applies - an app that showed F there would ask the client for money it does not owe. */
export function cashDueMinor(booking: WithPromo): number {
  const promo = booking.promo;
  if (!promo) return booking.total_minor;
  return promo.view === "client" ? promo.cash_due_minor : promo.cash_to_collect_minor;
}

export interface MoneyLine {
  label: string;
  minor: number;
  emphasis?: boolean;
  negative?: boolean;
}

/** Client lines: fare, bonus discount, cash to hand over. No commission, credit or rate (Q16, Q103).
 * `agreed` = a booking; otherwise an offer that nobody has accepted yet. */
export function clientMoneyLines(promo: BookingPromoClientDTO | ProposalPromoClientDTO, agreed = true): MoneyLine[] {
  return [
    { label: agreed ? translate("promo.line.agreedPrice") : translate("promo.line.offerPrice"), minor: promo.fare_minor },
    { label: translate("promo.line.bonusDiscount"), minor: promo.passenger_discount_minor, negative: true },
    { label: translate("promo.line.cashToDriver"), minor: promo.cash_due_minor, emphasis: true },
  ];
}

/** Driver lines: cash to collect, what the platform covers, credit used, what is charged, what stays. */
export function driverMoneyLines(promo: BookingPromoDriverDTO | ProposalPromoDriverDTO, agreed = true): MoneyLine[] {
  return [
    { label: agreed ? translate("promo.line.agreedPrice") : translate("promo.line.offerPrice"), minor: promo.fare_minor },
    { label: translate("promo.line.cashFromClient"), minor: promo.cash_to_collect_minor, emphasis: true },
    { label: translate("promo.line.discountCovered"), minor: promo.passenger_discount_covered_minor },
    { label: translate("disputeType.commission"), minor: promo.base_commission_minor },
    {
      label: agreed ? translate("promo.line.creditUsed") : translate("promo.line.creditToUse"),
      minor: promo.driver_credit_minor,
      negative: true,
    },
    { label: translate("promo.line.chargedFromBalance"), minor: promo.commission_charged_minor },
    { label: translate("promo.line.youKeep"), minor: promo.driver_keeps_minor, emphasis: true },
  ];
}

// --- consent -----------------------------------------------------------------------------------------------------

export interface ConsentChoice {
  /** The person ticked "use my bonus". Always starts false: there is no pre-filled or hidden consent. */
  useBonus: boolean;
  /** The server preview the person was looking at when they ticked it. */
  shown: ProposalPromoClientDTO | null;
}

export const NO_CONSENT: ConsentChoice = { useBonus: false, shown: null };

/** The `promo_consent` body, or `undefined` when the person did not explicitly choose to use the bonus. */
export function consentBody(choice: ConsentChoice): { passenger_bonus_minor: number; cash_due_minor: number } | undefined {
  if (!choice.useBonus || !choice.shown || choice.shown.passenger_discount_minor <= 0) return undefined;
  return { passenger_bonus_minor: choice.shown.passenger_discount_minor, cash_due_minor: choice.shown.cash_due_minor };
}

/** A new preview for a different price invalidates the tick: the person agrees again to the new numbers. */
export function withPreview(choice: ConsentChoice, preview: ProposalPromoClientDTO | null): ConsentChoice {
  const same =
    choice.shown !== null &&
    preview !== null &&
    choice.shown.fare_minor === preview.fare_minor &&
    choice.shown.passenger_discount_minor === preview.passenger_discount_minor &&
    choice.shown.cash_due_minor === preview.cash_due_minor;
  return { useBonus: same ? choice.useBonus : false, shown: preview };
}

type CodedError = { code?: string } | null | undefined;

/** The server refused the numbers the person agreed to: show the new ones and ask again (Q104, Q119). */
export function needsRequote(error: CodedError): boolean {
  return error?.code === "PROMO_QUOTE_STALE" || error?.code === "PROMO_CONSENT_REQUIRED";
}

type DetailedError = { code?: string; details?: Record<string, unknown> | null } | null | undefined;

/**
 * Q126: the *other* side's confirmation no longer holds (its session ended, its app changed) - this person cannot fix
 * it by requoting; the other side confirms again from its app. The offer itself is unchanged.
 */
export function counterpartyMustReconfirm(error: DetailedError): boolean {
  const reasons = error?.code === "PROMO_QUOTE_STALE" ? (error.details?.reasons as unknown) : null;
  return Array.isArray(reasons) && reasons.some((r) => r === "counterparty_confirmation_stale" || r === "counterparty_client_outdated");
}

/** Q125: the driver is asked to confirm its new cash and commission before a change is sent or accepted. */
export function driverAckRequested(error: DetailedError): { cash_to_collect_minor: number; commission_charged_minor: number } | null {
  const d = error?.code === "PROMO_CONSENT_REQUIRED" ? error.details : null;
  if (!d || d.party !== "driver") return null;
  const cash = Number(d.cash_to_collect_minor);
  const charged = Number(d.commission_charged_minor);
  return Number.isFinite(cash) && Number.isFinite(charged) ? { cash_to_collect_minor: cash, commission_charged_minor: charged } : null;
}

// --- why there is no discount (stage 5) ----------------------------------------------------------------------------

/** Plain categories from the server (never a rate, a limit, a formula or a risk rule - Q103).
 * Getters: each sentence is looked up when read, so it follows a language switch. */
export const NO_DISCOUNT_TEXT: Record<string, string> = {
  get service_not_eligible() { return translate("promo.noDiscount.serviceNotEligible"); },
  get bonus_expired() { return translate("promo.noDiscount.bonusExpired"); },
  get bonus_reserved() { return translate("promo.noDiscount.bonusReserved"); },
  get bonus_on_hold() { return translate("promo.noDiscount.bonusOnHold"); },
  get no_campaign() { return translate("promo.noDiscount.noCampaign"); },
  get client_update_required() { return translate("promo.noDiscount.clientUpdateRequired"); },
  get trip_terms() { return translate("promo.noDiscount.tripTerms"); },
};

export function noDiscountText(reason: string | null | undefined): string | null {
  return reason ? (NO_DISCOUNT_TEXT[reason] ?? null) : null;
}

// --- amendments: a lower fare can still mean more cash (Q125) --------------------------------------------------------

/**
 * The client's explanation when a change moves its cash. A lower fare with a smaller discount can *raise* the cash it
 * pays - that case is said out loud, never left for the person to notice. `null` when the cash does not change.
 */
export function amendmentCashNote(
  before: { fare_minor: number; passenger_discount_minor: number; cash_due_minor: number },
  after: { fare_minor: number; passenger_discount_minor: number; cash_due_minor: number },
): string | null {
  if (after.cash_due_minor === before.cash_due_minor) return null;
  const smallerDiscount = after.passenger_discount_minor < before.passenger_discount_minor;
  if (after.fare_minor < before.fare_minor && after.cash_due_minor > before.cash_due_minor) {
    return translate("promo.amendment.cashRisesDespiteLowerFare");
  }
  if (after.fare_minor < before.fare_minor && smallerDiscount) {
    return translate("promo.amendment.discountAlsoSmaller");
  }
  if (after.fare_minor > before.fare_minor) {
    return translate("promo.amendment.fareRose");
  }
  return translate("promo.amendment.cashChanges");
}

// --- referral progress (stage 5 milestone view) ------------------------------------------------------------------------

export type ProgressDTO = Schemas["ProgressDTO"];

/** Which progress row this is - a stable discriminator, since `label` follows the language. */
export type ProgressRowKind = "done" | "in_review" | "remaining";

/** Done, being checked, left - a service that is still being checked is never shown as done. */
export function progressRows(progress: ProgressDTO): { kind: ProgressRowKind; label: string; value: string; hint?: string }[] {
  const trips = progress.unit === "distinct_trip";
  const count = (n: number) =>
    trips ? translate("promo.progress.countTrips", { count: n }) : translate("promo.progress.countServices", { count: n });
  const doneValues = { done: progress.done, required: progress.required };
  return [
    {
      kind: "done",
      label: translate("driverProfile.completed"),
      value: trips ? translate("promo.progress.doneTrips", doneValues) : translate("promo.progress.doneServices", doneValues),
    },
    {
      kind: "in_review",
      label: translate("docState.pending"),
      value: count(progress.in_review),
      hint: translate("promo.progress.inReviewHint"),
    },
    { kind: "remaining", label: translate("promo.progress.remaining"), value: count(progress.remaining) },
  ];
}

export function needsUpgrade(error: CodedError): boolean {
  return error?.code === "CLIENT_UPGRADE_REQUIRED";
}

// --- disclosures and states --------------------------------------------------------------------------------------

function days(seconds: unknown): string {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "";
  const d = Math.round(value / 86400);
  if (d >= 1) return translate("promo.duration.days", { count: d });
  return translate("promo.duration.hours", { count: Math.round(value / 3600) });
}

const SERVICE: Record<string, string> = {
  get passenger() { return translate("promo.service.passenger"); },
  get parcel() { return translate("promo.service.parcel"); },
};

/** Stable disclosure codes (Q112) as sentences. Shown before joining; never a promise that joining pays. */
export function disclosureText(item: DisclosureDTO): string | null {
  switch (item.code) {
    case "not_cash":
      return translate("promo.disclosure.notCash");
    case "next_eligible_service":
      return translate("promo.disclosure.nextEligibleService");
    case "referrer_service_excluded":
      return translate("promo.disclosure.referrerServiceExcluded");
    case "another_driver_qualifies":
      return translate("promo.disclosure.anotherDriverQualifies");
    case "qualification_deadline":
      return translate("promo.disclosure.qualificationDeadline", { duration: days(item.value) });
    case "required_services": {
      const value = item.value;
      if (Array.isArray(value)) return translate("promo.disclosure.milestones", { steps: value.join(", ") });
      return translate("promo.disclosure.requiredServices", { count: String(value) });
    }
    case "service_type_only":
      return translate("promo.disclosure.serviceTypeOnly", { service: SERVICE[String(item.value)] ?? String(item.value) });
    case "reward_validity":
      return translate("promo.disclosure.rewardValidity", { duration: days(item.value) });
    case "risk_check":
      return translate("promo.disclosure.riskCheck", { duration: days(item.value) });
    case "enrollment_limit":
      return translate("promo.disclosure.enrollmentLimit");
    case "milestone_unit":
      return translate("promo.disclosure.milestoneUnit");
    default:
      return null;
  }
}

/** A function, not a constant: the sentence follows the language the person picked. */
export function parcelPayerRule(): string {
  return translate("promo.parcelPayerRule");
}

// Getters: each label is looked up when read, so it follows a language switch.
export const QUALIFICATION_LABELS: Record<string, string> = {
  get waiting() { return translate("promo.qualification.waiting"); },
  get review() { return translate("promo.qualification.review"); },
  get qualified() { return translate("promo.qualification.qualified"); },
  get granted() { return translate("notification.promo.reward_granted.title"); },
  get rejected() { return translate("amendment.rejected"); },
};

export const ENROLLMENT_LABELS: Record<string, string> = {
  get promised() { return translate("promo.enrollment.promised"); },
  get granted() { return translate("notification.promo.reward_granted.title"); },
  get released() { return translate("promo.enrollment.released"); },
  get rejected() { return translate("amendment.rejected"); },
};

export const INSTRUMENT_LABELS: Record<string, string> = {
  get passenger_bonus() { return translate("promo.instrument.passengerBonus"); },
  get driver_credit() { return translate("promo.instrument.driverCredit"); },
};

/** The five states of a discount right, in the order a person reads them. None of them is withdrawable money. */
export function bucketRows(bucket: PromoBucketDTO): { label: string; minor: number; hint?: string }[] {
  return [
    { label: translate("promo.bucket.available"), minor: bucket.available_minor },
    { label: translate("promo.bucket.reserved"), minor: bucket.reserved_minor, hint: translate("promo.bucket.reservedHint") },
    { label: translate("docState.pending"), minor: bucket.under_review_minor, hint: translate("promo.bucket.underReviewHint") },
    { label: translate("promo.bucket.consumed"), minor: bucket.consumed_minor },
    { label: translate("promo.bucket.expired"), minor: bucket.expired_minor + bucket.reversed_minor },
  ];
}

// --- referral code from a link, kept across login --------------------------------------------------------------

const ALPHABET = /^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{8}$/;
const PENDING_KEY = "elchi_pending_referral_code";

/** Same normalisation as the server: trim, upper-case, drop spaces and dashes. `null` when it cannot be a code. */
export function normalizeCode(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const value = raw.replace(/[\s-]/g, "").toUpperCase();
  return ALPHABET.test(value) ? value : null;
}

/** `/r/<code>` -> code. Anything else -> null. */
export function codeFromPath(pathname: string): string | null {
  const match = /^\/r\/([^/?#]+)\/?$/.exec(pathname);
  return match ? normalizeCode(decodeURIComponent(match[1])) : null;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Keep a code from a link through the login screens. The *first* code wins: a later link does not replace it
 * (the server keeps the first attribution anyway, Q106). */
export function rememberCode(code: string): void {
  const store = storage();
  if (!store) return;
  try {
    if (!store.getItem(PENDING_KEY)) store.setItem(PENDING_KEY, code);
  } catch {
    /* private mode: the person can still type the code */
  }
}

export function pendingCode(): string | null {
  try {
    return storage()?.getItem(PENDING_KEY) ?? null;
  } catch {
    return null;
  }
}

export function forgetCode(): void {
  try {
    storage()?.removeItem(PENDING_KEY);
  } catch {
    /* nothing to forget */
  }
}

// --- one key per user action, surviving a timeout or an app restart ---------------------------------------------

const ACTION_PREFIX = "elchi_action_key:";

/**
 * The Idempotency-Key of one user action (e.g. "accept:<thread>:<version>"). A retry after a timeout, a double tap
 * or reopening the app sends the *same* key, so the server replays the first answer instead of acting twice.
 */
export function actionKey(scope: string, make: () => string): string {
  const store = storage();
  const name = ACTION_PREFIX + scope;
  try {
    const existing = store?.getItem(name);
    if (existing) return existing;
    const key = make();
    store?.setItem(name, key);
    return key;
  } catch {
    return make();
  }
}

/** The action finished (or definitively failed): the next attempt is a new action with a new key. */
export function finishAction(scope: string): void {
  try {
    storage()?.removeItem(ACTION_PREFIX + scope);
  } catch {
    /* ignore */
  }
}
