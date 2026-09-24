/**
 * What a participant may do with a booking after accept: cancel it, get a new proof code, rate the other side,
 * open a dispute.
 *
 * Pure on purpose (like `auction.ts`): the server is the authority for every one of these and refuses anything
 * this module lets through, but a button that is certain to be refused teaches nothing. The sets below mirror
 * the server's own rules and name them, so a drift is a failing test rather than a confusing screen.
 */

export type BookingSide = "client" | "driver";

/**
 * `state_machines.PASSENGER_BOOKING` / `PARCEL_BOOKING`: `cancel` leaves only these two states. Once the
 * passenger is on board or the parcel is picked up, a cancellation is the return flow or a dispute, not this.
 */
export const CANCELLABLE_STATUSES: readonly string[] = ["confirmed", "awaiting_pickup"];

export function canCancelBooking(serviceStatus: string): boolean {
  return CANCELLABLE_STATUSES.includes(serviceStatus);
}

/**
 * Q7/Q19: while a reported no-show waits for the operator, only the operator may cancel. The booking DTO carries
 * the review, so the screen says so before the person tries - the server refuses either way.
 */
export function cancelBlockedByReview(review: { status: string } | null | undefined): boolean {
  return review?.status === "pending";
}

/**
 * The machine codes a participant cancels with (`BookingCancel.reason_code`, 1-64 chars). The person's own words
 * travel separately in `comment`. `other` is always last, so the list never forces a wrong reason.
 */
export const CANCEL_REASONS: Record<BookingSide, readonly string[]> = {
  client: ["plans_changed", "found_other_option", "driver_unreachable", "other"],
  driver: ["trip_changed", "vehicle_problem", "client_unreachable", "other"],
};

/**
 * Why the server refused a cancel, as a dictionary key - or null when the generic error text is the right one.
 *
 * `NO_SHOW_REVIEW_PENDING` is the case that matters (Q7/Q19): while an operator reviews a reported no-show only
 * the operator may cancel, and the person has to be told that, not "something went wrong".
 */
export function cancelRefusalKey(error: { code?: string } | null | undefined): string | null {
  switch (error?.code) {
    case "NO_SHOW_REVIEW_PENDING":
      return "bookingCancel.refused.noShowPending";
    case "CUSTODY_REQUIRES_RETURN_FLOW":
      return "bookingCancel.refused.custody";
    case "INVALID_STATE_TRANSITION":
      return "bookingCancel.refused.tooLate";
    case "VERSION_CONFLICT":
      return "bookingCancel.refused.changed";
    default:
      return null;
  }
}

/** ADR-0025: the saved request a cancelled booking came from - the one "Qayta qidirish" belongs to. */
export function intentOfBooking<T extends { booking_id?: string | null }>(intents: readonly T[], bookingId: string): T | null {
  return intents.find((intent) => intent.booking_id === bookingId) ?? null;
}

/** The terminal service states: after these no code is reissued (`rules.is_terminal_service_status`). */
const TERMINAL_STATUSES: readonly string[] = ["completed", "cancelled", "no_show", "returned"];

/**
 * B5a: may the code owner ask for a new code of this kind now?
 *
 * The owner is always the client (`rules.CLIENT_CODE_KINDS`), so a driver never gets this button. The return code
 * exists only while a parcel has to come back.
 */
export function canReissueCode(side: BookingSide, kind: string, serviceStatus: string): boolean {
  if (side !== "client") return false;
  if (TERMINAL_STATUSES.includes(serviceStatus)) return false;
  if (kind === "return_code") return serviceStatus === "return_required";
  return ["boarding_code", "pickup_code", "delivery_code"].includes(kind);
}

export interface ReissueWait {
  /** Seconds until the next self-service reissue is allowed. */
  retryAfterS: number;
  /** Self-service reissues still left in the 24 h window (Q75: 3). */
  reissuesLeft: number | null;
}

/** `429 PROOF_REISSUE_LIMITED` carries `details {retry_after_s, reissues_left}`; anything else is not a wait. */
export function reissueWait(error: { code?: string; details?: unknown } | null | undefined): ReissueWait | null {
  if (error?.code !== "PROOF_REISSUE_LIMITED") return null;
  const details = (error.details ?? {}) as { retry_after_s?: unknown; reissues_left?: unknown };
  const retry = Number(details.retry_after_s);
  const left = Number(details.reissues_left);
  return {
    retryAfterS: Number.isFinite(retry) && retry > 0 ? Math.ceil(retry) : 0,
    reissuesLeft: Number.isFinite(left) && left >= 0 ? Math.floor(left) : null,
  };
}

/** A wait as whole minutes and seconds, for a sentence ("1 daqiqa 20 soniya", "5 soat"). */
export function waitParts(seconds: number): { hours: number; minutes: number; seconds: number } {
  const total = Math.max(0, Math.ceil(seconds));
  return { hours: Math.floor(total / 3600), minutes: Math.floor((total % 3600) / 60), seconds: total % 60 };
}

/** S1: a participant rates the other side, never themselves (`subject_must_be_counterparty`). */
export function counterpartSide(side: BookingSide): BookingSide {
  return side === "client" ? "driver" : "client";
}

/**
 * S1: only a completed booking is rated. The 7-day window (§17.2) is the server's to check - the booking DTO does
 * not carry its completion time, and `RATING_NOT_ALLOWED` says so when it has passed.
 */
export function canRate(serviceStatus: string): boolean {
  return serviceStatus === "completed";
}

/**
 * S3: which dispute types a side may open. `commission` is the driver's alone - the client never sees commission
 * (Q16, `CLIENT_HIDDEN_DISPUTE_TYPES`).
 */
export function disputeTypesFor(side: BookingSide): string[] {
  const shared = ["service", "no_show", "payment", "delivery", "safety", "other"];
  return side === "driver" ? [...shared.slice(0, 3), "commission", ...shared.slice(3)] : shared;
}

/**
 * Where "Muammo haqida xabar berish" is offered. The server accepts a dispute in any state; a freshly confirmed
 * booking has nothing to dispute yet, so the button waits until something has happened.
 */
export function canOpenDispute(serviceStatus: string): boolean {
  return serviceStatus !== "confirmed";
}
