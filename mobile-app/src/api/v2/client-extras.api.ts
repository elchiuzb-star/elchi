/** The rest of the client surface (A8): the in-app inbox, saved searches, ratings and disputes.
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
export type DisputeDTO = Schemas["DisputeDTO"];
export type DisputeCreate = Schemas["app__modules__trust_support__schemas__DisputeCreate"];
export type DisputeEvidenceCreate = Schemas["DisputeEvidenceCreate"];
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

export function myDisputes(params: { limit?: number } = {}) {
  return v2Request<DisputeDTO[]>("/me/disputes", { query: params });
}

export function openDispute(bookingId: string, body: DisputeCreate, idempotencyKey: string): Promise<V2Result<DisputeDTO>> {
  return v2RequestFull<DisputeDTO>(`/bookings/${bookingId}/disputes`, { method: "POST", body, idempotencyKey });
}

/** S5: one dispute as its participant sees it - the evidence both sides added and the decision, if any. */
export function getDispute(disputeId: string) {
  return v2Request<DisputeDTO>(`/disputes/${disputeId}`);
}

export function addDisputeEvidence(disputeId: string, body: DisputeEvidenceCreate, idempotencyKey: string) {
  return v2RequestFull<DisputeDTO>(`/disputes/${disputeId}/evidence`, { method: "POST", body, idempotencyKey });
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
