/**
 * Staff trust & operations calls (A12 S9-S20, B12/B13, N10, K9, O7) for the admin panel.
 *
 * Every request uses the admin session and a generated type. Commands take the idempotency key from the caller:
 * the screen mints one key per confirmed action and keeps it for a retry of that same action (ADR-0005), so a
 * double submit or a network retry replays the first answer instead of acting twice.
 *
 * The server decides what the caller may do; these wrappers never pre-judge a refusal.
 */
import { newIdempotencyKey, v2AdminRequest, v2AdminRequestFull, type Schemas, type V2Result } from "./http";

export type SupportTicketAdminDTO = Schemas["SupportTicketAdminDTO"];
export type FraudSignalDTO = Schemas["FraudSignalDTO"];
export type FraudSignalCommand = Schemas["FraudSignalCommand"];
export type ReportDTO = Schemas["ReportDTO"];
export type ReportCommand = Schemas["ReportCommand"];
export type UserStrikesDTO = Schemas["UserStrikesDTO"];
export type ChatMessageAdminDTO = Schemas["ChatMessageAdminDTO"];
export type ChatHideRequest = Schemas["ChatHideRequest"];
export type AdminBookingDTO = Schemas["BookingDTO"];
export type AdminBookingQueue = Schemas["AdminBookingQueue"];
export type OperatorBookingCommand = Schemas["OperatorBookingCommand"];
export type OperatorBookingCommandRequest = Schemas["OperatorBookingCommandRequest"];
export type TripTrackingAdminDTO = Schemas["TripTrackingAdminDTO"];
export type ListingOnBehalfBody = Schemas["ListingOnBehalfBody"];
export type AdminListingDTO = Schemas["ListingDTO"];

export const ADMIN_BOOKING_QUEUES: AdminBookingQueue[] = [
  "awaiting_confirmation",
  "no_show_review",
  "custody_case",
  "hold_escalation",
  "finance_review",
];

// --- S17 support tickets (admin shape: user, booking, press count, freshness without coordinates) -----------------

export function listSupportTicketsAdmin(params: { status?: string; kind?: string; limit?: number } = {}) {
  return v2AdminRequest<SupportTicketAdminDTO[]>("/admin/support/tickets", { query: params });
}

// --- S12 fraud signals: a question for a human, never a verdict (§17.3) --------------------------------------------

export function listFraudSignals(params: { status?: string; limit?: number; cursor?: string } = {}) {
  return v2AdminRequest<FraudSignalDTO[]>("/admin/fraud-signals", { query: params });
}

export function reviewFraudSignal(signalId: string, body: FraudSignalCommand, idempotencyKey = newIdempotencyKey()) {
  return v2AdminRequest<FraudSignalDTO>(`/admin/fraud-signals/${encodeURIComponent(signalId)}/review`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

// --- S12b abuse reports: the decision is recorded, no account changes here -----------------------------------------

export function listReports(params: { status?: string; limit?: number; cursor?: string } = {}) {
  return v2AdminRequest<ReportDTO[]>("/admin/reports", { query: params });
}

export function reviewReport(reportId: string, body: ReportCommand, idempotencyKey = newIdempotencyKey()) {
  return v2AdminRequest<ReportDTO>(`/admin/reports/${encodeURIComponent(reportId)}/review`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

// --- S20 strikes (Q45, Q83) -------------------------------------------------------------------------------------

export function userStrikes(userId: string) {
  return v2AdminRequest<UserStrikesDTO>(`/admin/trust/users/${encodeURIComponent(userId)}/strikes`);
}

// --- N10 staff chat view (audited) and moderation ---------------------------------------------------------------

export function adminBookingMessages(bookingId: string, params: { cursor?: string; limit?: number } = {}) {
  return v2AdminRequest<ChatMessageAdminDTO[]>(`/admin/bookings/${encodeURIComponent(bookingId)}/messages`, {
    query: params,
  });
}

/** Q100: the proposal thread is read by staff only; the client never writes there, and this panel never does. */
export function adminProposalMessages(threadId: string, params: { cursor?: string; limit?: number } = {}) {
  return v2AdminRequest<ChatMessageAdminDTO[]>(`/admin/proposals/${encodeURIComponent(threadId)}/messages`, {
    query: params,
  });
}

export function hideChatMessage(messageId: string, body: ChatHideRequest, idempotencyKey = newIdempotencyKey()) {
  return v2AdminRequest<ChatMessageAdminDTO>(`/admin/chat/messages/${encodeURIComponent(messageId)}/hide`, {
    method: "POST",
    body,
    idempotencyKey,
  });
}

// --- B12/B13 operator bookings ------------------------------------------------------------------------------------

export function listAdminBookings(params: { queue: AdminBookingQueue; corridor_id?: string; cursor?: string; limit?: number }) {
  return v2AdminRequest<AdminBookingDTO[]>("/admin/bookings", { query: params });
}

/**
 * B13. The capability per command is the server's (`OPERATOR_COMMAND_CAPABILITY`): `cancel` is admin+
 * (`ops.booking_cancel`, Q10), `finalize_fee` is finance (`finance.fee_finalize`, Q17), the rest `ops.booking_command`.
 * `cancel_fault_side` is sent only with `cancel` (Q129); leaving it out records the cause as undetermined.
 */
export function adminBookingCommand(
  bookingId: string,
  command: OperatorBookingCommand,
  body: OperatorBookingCommandRequest,
  idempotencyKey = newIdempotencyKey(),
): Promise<V2Result<AdminBookingDTO>> {
  return v2AdminRequestFull<AdminBookingDTO>(
    `/admin/bookings/${encodeURIComponent(bookingId)}/commands/${command}`,
    { method: "POST", body, idempotencyKey },
  );
}

// --- K9 trip tracking (ops.view, audited; Q86) ---------------------------------------------------------------------

export function adminTripTracking(tripId: string) {
  return v2AdminRequest<TripTrackingAdminDTO>(`/admin/trips/${encodeURIComponent(tripId)}/tracking`);
}

// --- O7 listing on behalf of a real owner (§20.2) ----------------------------------------------------------------

export function createListingOnBehalf(body: ListingOnBehalfBody, idempotencyKey = newIdempotencyKey()) {
  return v2AdminRequestFull<AdminListingDTO>("/admin/listings/on-behalf", { method: "POST", body, idempotencyKey });
}

// --- ADR-0026 (Q141): the booking-bound operator chat queue -------------------------------------------------------

export type SupportThreadAdminDTO = Schemas["SupportThreadAdminDTO"];
export type SupportThreadCommandName = "assign" | "reply" | "close";

export function listSupportThreadsAdmin(params: { status?: "open" | "closed"; assigned?: "me" | "unassigned"; limit?: number } = {}) {
  return v2AdminRequest<SupportThreadAdminDTO[]>("/admin/support-threads", { query: params });
}

export function getSupportThreadAdmin(threadId: string) {
  return v2AdminRequest<SupportThreadAdminDTO>(`/admin/support-threads/${threadId}`);
}

export type SupportFileLinkDTO = Schemas["SupportFileLinkDTO"];

/** ADR-0026: a short-lived signed link to one evidence file (live staff session + ops.trust_review; audited). */
export function supportThreadFileLink(threadId: string, fileRef: string) {
  return v2AdminRequest<SupportFileLinkDTO>(`/admin/support-threads/${threadId}/files/${encodeURIComponent(fileRef)}`);
}

/** assign (to self by default), reply (a message to the requester) or close. None of them moves money. */
export function supportThreadCommand(
  threadId: string, command: SupportThreadCommandName, body: { expected_version: number; text?: string | null },
  idempotencyKey: string = newIdempotencyKey(),
) {
  return v2AdminRequest<SupportThreadAdminDTO>(`/admin/support-threads/${threadId}/${command}`, {
    method: "POST", body, idempotencyKey,
  });
}
