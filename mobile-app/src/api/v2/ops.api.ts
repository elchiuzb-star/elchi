/** Operator-side v2 calls for the admin panel (A9): queues, disputes, tickets, trust reviews and metrics.
 *
 * Every request travels with the admin panel's own session (`audience: "admin"`), and every type comes from the
 * generated contract. The server decides what the caller may do: the panel only reflects the answer, so an
 * operator who lacks `ops.dispute_decide` sees the refusal instead of a button that pretends to work (Q78).
 */
import { newIdempotencyKey, v2AdminRequest, v2AdminRequestFull, type Schemas, type V2Result } from "./http";

export type OpsQueueItemDTO = Schemas["OpsQueueItemDTO"];
export type OpsQueue = Schemas["OpsQueue"];
export type KpiDTO = Schemas["KpiDTO"];
export type SloDTO = Schemas["SloDTO"];
export type DisputeDTO = Schemas["DisputeDTO"];
export type DisputeCommand = Schemas["DisputeCommand"];
export type SupportTicketDTO = Schemas["SupportTicketDTO"];
export type SupportTicketCommand = Schemas["SupportTicketCommand"];
export type TrustReviewDTO = Schemas["TrustReviewDTO"];
export type TrustReviewCommand = Schemas["TrustReviewCommand"];
export type CapabilitiesDTO = Schemas["CapabilitiesDTO"];
export type LegacyOrderViewDTO = Schemas["LegacyOrderViewDTO"];

export const OPS_QUEUES: OpsQueue[] = [
  "awaiting_confirmation",
  "no_show_review",
  "custody_case",
  "hold_escalation",
  "finance_review",
  "dispute",
  "support_ticket",
  "trust_review",
];

/** What this staff member may actually do; the panel hides decision buttons the server would refuse. */
export function capabilities() {
  return v2AdminRequest<CapabilitiesDTO>("/me/capabilities");
}

export function opsQueue(queue: OpsQueue, params: { corridor_id?: string; limit?: number } = {}) {
  return v2AdminRequest<OpsQueueItemDTO[]>(`/admin/ops/queues/${queue}`, { query: params });
}

export function kpi(params: { from?: string; to?: string; corridor_id?: string } = {}) {
  return v2AdminRequest<KpiDTO>("/admin/metrics/kpi", { query: params });
}

export function slo(params: { from?: string; to?: string } = {}) {
  return v2AdminRequest<SloDTO>("/admin/metrics/slo", { query: params });
}

export function listDisputes(params: { status?: string; type?: string; escalated?: boolean; limit?: number } = {}) {
  return v2AdminRequest<DisputeDTO[]>("/admin/disputes", { query: params });
}

/**
 * S8. `start-review` is operator work; `resolve` / `reject` need `ops.dispute_decide` (admin+, Q78) and, for a
 * contested cash receipt, an explicit `cash_outcome` - the server refuses a decision that would leave the money
 * question open.
 */
export function disputeCommand(
  disputeId: string,
  command: "start-review" | "resolve" | "reject",
  body: DisputeCommand,
): Promise<V2Result<DisputeDTO>> {
  return v2AdminRequestFull<DisputeDTO>(`/admin/disputes/${disputeId}/${command}`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

export function listTickets(params: { status?: string; kind?: string; limit?: number } = {}) {
  return v2AdminRequest<SupportTicketDTO[]>("/admin/support/tickets", { query: params });
}

export function ticketCommand(ticketId: string, command: "acknowledge" | "resolve", body: SupportTicketCommand) {
  return v2AdminRequest<SupportTicketDTO>(`/admin/support/tickets/${ticketId}/${command}`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

export function listTrustReviews(params: { status?: string; signal_type?: string; limit?: number } = {}) {
  return v2AdminRequest<TrustReviewDTO[]>("/admin/trust/reviews", { query: params });
}

export function trustReviewCommand(reviewId: string, command: string, body: TrustReviewCommand) {
  return v2AdminRequest<TrustReviewDTO>(`/admin/trust/reviews/${reviewId}/${command}`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

/**
 * O8 (wave 5, Q4). The v1 archive as v2 may *read* it: the server answers from a read-only projection, so there
 * is deliberately no write call here - a v1 order is finished in v1.
 */
export function listLegacyOrders(params: { status?: string; limit?: number; cursor?: string } = {}) {
  return v2AdminRequest<LegacyOrderViewDTO[]>("/admin/legacy-orders", { query: params });
}

// --- corridors and price references (G2, G12-G14) ---------------------------------------------------------

export type CorridorDTO = Schemas["CorridorDTO"];
export type PriceBandDTO = Schemas["PriceBandDTO"];
export type PriceBandUpsert = Schemas["PriceBandUpsert"];
export type PriceBandChangeDTO = Schemas["PriceBandChangeDTO"];

/** G2: the corridors this panel may configure. */
export function listCorridors() {
  return v2AdminRequest<CorridorDTO[]>("/corridors");
}

export function listPriceBands(corridorId: string) {
  return v2AdminRequest<PriceBandDTO[]>(`/admin/corridors/${corridorId}/price-bands`);
}

export function priceBandHistory(corridorId: string, params: { limit?: number } = {}) {
  return v2AdminRequest<PriceBandChangeDTO[]>(`/admin/corridors/${corridorId}/price-bands/history`, { query: params });
}

/**
 * G13: set the price **reference** for one corridor and service type.
 *
 * Q90 is the whole point of the `enforced` field. Left false (the default) the band advises: a proposal outside
 * it succeeds and comes back with `PRICE_OUTSIDE_REFERENCE`, and the number feeds the ranking. Set true it is
 * an abuse/safety limit and the server refuses the price outright - which in a two-sided auction is a serious
 * thing to do, so the screen makes it a deliberate switch with its own explanation rather than a checkbox.
 *
 * Returns the envelope so the caller can surface `CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR` (Q53).
 */
export function setPriceBand(
  corridorId: string,
  serviceType: "passenger" | "parcel",
  body: PriceBandUpsert,
): Promise<V2Result<PriceBandDTO>> {
  return v2AdminRequestFull<PriceBandDTO>(`/admin/corridors/${corridorId}/price-bands/${serviceType}`, {
    method: "PUT",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}
