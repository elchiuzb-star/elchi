/** The rest of the client surface (A8): the in-app inbox, saved searches, ratings and the operator chat (ADR-0026).
 *
 * Push is not wired: the pilot decision is in-app only until a provider ADR (Q82), so this module never registers
 * a device token - the inbox is the delivery channel.
 */
import { newIdempotencyKey, v2Request, v2RequestFull, type Schemas, type V2Result } from "./http";

export type NotificationDTO = Schemas["NotificationDTO"];
export type SavedSearchDTO = Schemas["SavedSearchDTO"];
export type SavedSearchCreate = Schemas["SavedSearchCreate"];
export type RatingCreate = Schemas["RatingCreate"];
export type RatingDTO = Schemas["RatingDTO"];
export type SupportThreadDTO = Schemas["SupportThreadDTO"];
export type SupportMessageDTO = Schemas["SupportMessageDTO"];
export type SupportContactsDTO = Schemas["SupportContactsDTO"];
export type SupportTicketDTO = Schemas["SupportTicketDTO"];
export type SupportTicketCreate = Schemas["SupportTicketCreate"];

/** N4. The server's filter is `unread` (communications/api.py); `unread_only` is kept as this wrapper's name. */
export function notifications(params: { limit?: number; unread_only?: boolean } = {}) {
  return v2Request<NotificationDTO[]>("/notifications", {
    query: { limit: params.limit, unread: params.unread_only || undefined },
  });
}

export function markNotificationRead(notificationId: string) {
  return v2Request<NotificationDTO>(`/notifications/${notificationId}/read`, {
    method: "POST",
    idempotencyKey: newIdempotencyKey(),
  });
}

export function savedSearches() {
  return v2Request<SavedSearchDTO[]>("/me/saved-searches");
}

/** M3: at most SAVED_SEARCH_MAX_PER_USER active searches; the server answers 409 when the limit is reached. */
export function createSavedSearch(body: SavedSearchCreate, idempotencyKey: string) {
  return v2Request<SavedSearchDTO>("/saved-searches", { method: "POST", body, idempotencyKey });
}

export function deleteSavedSearch(savedSearchId: string) {
  return v2Request<Schemas["EmptyDTO"]>(`/saved-searches/${savedSearchId}`, { method: "DELETE" });
}

/** S1: one rating per booking and side; it is published after the rating window (§17.2), not immediately. */
export function rateBooking(bookingId: string, body: RatingCreate, idempotencyKey: string): Promise<V2Result<RatingDTO>> {
  return v2RequestFull<RatingDTO>(`/bookings/${bookingId}/ratings`, { method: "POST", body, idempotencyKey });
}

/**
 * ADR-0026 (Q141): "Shikoyat qilish" - the caller's own operator chat for this booking. The server returns the open
 * thread if there is one (a second tap or a retry never makes another); the other party never sees it.
 */
export function openSupportThread(bookingId: string, text: string | null, idempotencyKey: string) {
  return v2RequestFull<SupportThreadDTO>(`/bookings/${bookingId}/support-thread`, {
    method: "POST", body: { text: text || null }, idempotencyKey,
  });
}

/** The caller's open thread for this booking, or null - so the button can say "continue" instead of "open". */
export function bookingSupportThread(bookingId: string) {
  return v2Request<SupportThreadDTO | null>(`/bookings/${bookingId}/support-thread`);
}

export function mySupportThreads(params: { limit?: number } = {}) {
  return v2Request<SupportThreadDTO[]>("/me/support-threads", { query: params });
}

export function getSupportThread(threadId: string) {
  return v2Request<SupportThreadDTO>(`/support-threads/${threadId}`);
}

export function postSupportMessage(threadId: string, text: string, idempotencyKey: string) {
  return v2RequestFull<SupportThreadDTO>(`/support-threads/${threadId}/messages`, {
    method: "POST", body: { text }, idempotencyKey,
  });
}

/**
 * Who a person can reach, as the server answers it (S13).
 *
 * Deliberately a request rather than a constant. In the pilot there is no answered line: `ELCHI_SUPPORT_PHONE`
 * is empty, so this comes back `available: false` with no number and **no hours** (Q87), and the screen must
 * then show the in-app ticket instead. A phone number and an opening-hours line are promises, and the client
 * is not allowed to make one the operation cannot keep (AGENTS.md section 9).
 */
export function supportContacts() {
  return v2Request<SupportContactsDTO>("/support/contacts");
}

export function createSupportTicket(body: SupportTicketCreate, idempotencyKey: string) {
  return v2Request<SupportTicketDTO>("/support/tickets", { method: "POST", body, idempotencyKey });
}

export function mySupportTickets(params: { limit?: number } = {}) {
  return v2Request<SupportTicketDTO[]>("/me/support/tickets", { query: params });
}
