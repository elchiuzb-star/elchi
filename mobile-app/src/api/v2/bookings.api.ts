/** Client-side v2 booking calls (A8): my bookings, proof codes, tracking, chat, share links, support. */
import { newIdempotencyKey, v2Request, v2RequestFull, type Schemas } from "./http";
import type { AnyBooking } from "./marketplace.api";

export type BookingTrackingDTO = Schemas["BookingTrackingDTO"];
export type BookingCodesDTO = Schemas["BookingCodesDTO"];
export type ChatMessageDTO = Schemas["ChatMessageDTO"];
export type ChatMessageCreate = Schemas["ChatMessageCreate"];
export type ShareLinkDTO = Schemas["ShareLinkDTO"];
export type ShareLinkCreate = Schemas["ShareLinkCreate"];
export type SupportContactsDTO = Schemas["SupportContactsDTO"];
export type SupportTicketDTO = Schemas["SupportTicketDTO"];
export type PublicListingPageDTO = Schemas["PublicListingPageDTO"];
export type BookingCancel = Schemas["BookingCancel"];
export type SupportTicketCreate = Schemas["SupportTicketCreate"];
export type AmendmentCreate = Schemas["AmendmentCreate"];
export type AmendmentDTO = Schemas["AmendmentDTO"];
export type NotificationDTO = Schemas["NotificationDTO"];

export function listMyBookings(params: { role?: string; status?: string; limit?: number } = {}) {
  return v2Request<AnyBooking[]>("/me/bookings", { query: params });
}

export function getBooking(bookingId: string) {
  return v2Request<AnyBooking>(`/bookings/${bookingId}`);
}

/** B5: the proof codes the client shows the driver (boarding / delivery). Never sent through chat (Q65). */
export function getBookingCodes(bookingId: string) {
  return v2Request<BookingCodesDTO>(`/bookings/${bookingId}/codes`);
}

/** K4: the live-location window of this booking. `last_point` is null when there is no trusted point (AC27). */
export function getBookingTracking(bookingId: string) {
  return v2Request<BookingTrackingDTO>(`/bookings/${bookingId}/tracking`);
}

/** B7: `reason_code` is the machine code the policy is applied to; the user's words go to `comment`. */
export function cancelBooking(bookingId: string, expectedVersion: number, reasonCode: string, comment?: string) {
  const body: BookingCancel = { expected_version: expectedVersion, reason_code: reasonCode, comment: comment ?? null };
  return v2Request<AnyBooking>(`/bookings/${bookingId}/cancel`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

/**
 * B6: the client closes the service - a passenger confirms the ride after the drop-off, a sender confirms the
 * delivery (Q65: the receiver may not). `ACTION_SIDES` gives this action to the client only, so no other side
 * ever gets this button.
 */
export function completeBooking(bookingId: string, expectedVersion: number) {
  const body: Schemas["BookingActionRequest"] = { expected_version: expectedVersion };
  const action: Schemas["BookingAction"] = "complete";
  return v2Request<AnyBooking>(`/bookings/${bookingId}/actions/${action}`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

/**
 * B9: ask the other side to change the booking (quantity, window, stops, unit price). The answer carries the new
 * amounts and the fee delta; nothing changes until the counterpart accepts (AC42).
 */
export function proposeAmendment(bookingId: string, body: AmendmentCreate, idempotencyKey: string) {
  return v2Request<AmendmentDTO>(`/bookings/${bookingId}/amendments`, { method: "POST", body, idempotencyKey });
}

/** B9 read side: the booking's amendments, newest first - this is how the other side finds one to answer. */
export function listAmendments(bookingId: string, params: { limit?: number } = {}) {
  return v2Request<AmendmentDTO[]>(`/bookings/${bookingId}/amendments`, { query: params });
}

/** B10/B11: answer a proposed change. `accept` returns the changed booking, the others the closed amendment. */
export function acceptAmendment(amendmentId: string, expectedVersion: number) {
  const body: Schemas["AmendmentDecision"] = { expected_version: expectedVersion };
  return v2Request<AnyBooking>(`/amendments/${amendmentId}/accept`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function decideAmendment(amendmentId: string, decision: "reject" | "withdraw", expectedVersion: number) {
  const body: Schemas["AmendmentDecision"] = { expected_version: expectedVersion };
  const options = { method: "POST" as const, body, idempotencyKey: newIdempotencyKey() };
  // Two literal paths rather than one built from `decision`: what this client calls stays greppable and is
  // checked against the served contract (tests/test_mobile_v2_client_contract.py).
  return decision === "reject"
    ? v2Request<AmendmentDTO>(`/amendments/${amendmentId}/reject`, options)
    : v2Request<AmendmentDTO>(`/amendments/${amendmentId}/withdraw`, options);
}

export function listMessages(bookingId: string, params: { limit?: number; cursor?: string } = {}) {
  return v2Request<ChatMessageDTO[]>(`/bookings/${bookingId}/messages`, { query: params });
}

/** N6: free text is filtered server-side; the answer's warnings say when something was masked (Q43). */
export function sendMessage(bookingId: string, body: ChatMessageCreate, idempotencyKey: string) {
  return v2RequestFull<ChatMessageDTO>(`/bookings/${bookingId}/messages`, { method: "POST", body, idempotencyKey });
}

export type CashReceiptDTO = Schemas["CashReceiptDTO"];

/**
 * B10: one side records that the fare was handed over in cash.
 *
 * This is an acknowledgement between two people, not a payment ELCHI processed: the money never touches the
 * platform, and this call moves no balance. It exists so the other side can confirm or contest it, and so the
 * operator queue has something to look at when they disagree (§9, Q78).
 */
export function reportCashReceipt(
  bookingId: string,
  body: { expected_version: number; amount_minor: number; reported_at: string; note?: string | null },
  idempotencyKey: string,
) {
  return v2Request<CashReceiptDTO>(`/bookings/${bookingId}/cash-receipts`, { method: "POST", body, idempotencyKey });
}

/** B10b: the counterpart answers - `acknowledge` closes it, `contest` sends it to the operator queue. */
export function decideCashReceipt(
  bookingId: string,
  receiptId: string,
  decision: "acknowledge" | "contest",
  expectedVersion: number,
  comment?: string,
) {
  // Both routes are written out in full rather than interpolated: `${decision}` would make the call opaque to
  // the guard that checks every client path against the served routes (tests/test_mobile_v2_client_contract.py).
  const options = {
    method: "POST" as const,
    body: { expected_version: expectedVersion, comment: comment ?? null },
    idempotencyKey: newIdempotencyKey(),
  };
  return decision === "acknowledge"
    ? v2Request<CashReceiptDTO>(`/bookings/${bookingId}/cash-receipts/${receiptId}/acknowledge`, options)
    : v2Request<CashReceiptDTO>(`/bookings/${bookingId}/cash-receipts/${receiptId}/contest`, options);
}

export function createShareLink(listingId: string, body: ShareLinkCreate, idempotencyKey: string) {
  return v2Request<ShareLinkDTO>(`/listings/${listingId}/share-links`, { method: "POST", body, idempotencyKey });
}

export function supportContacts() {
  return v2Request<SupportContactsDTO>("/support/contacts");
}

export function createSupportTicket(body: SupportTicketCreate, idempotencyKey: string) {
  return v2Request<SupportTicketDTO>("/support/tickets", { method: "POST", body, idempotencyKey });
}

export function listNotifications(params: { limit?: number; unread_only?: boolean } = {}) {
  return v2Request<NotificationDTO[]>("/notifications", { query: params });
}

/** O3: the public page of a shared listing. No token in the app's storage, no auth header. */
export function publicListingPage(token: string) {
  return v2Request<PublicListingPageDTO>(`/public/listings/${encodeURIComponent(token)}`, { auth: false });
}
