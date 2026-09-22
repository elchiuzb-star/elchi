/**
 * The legacy v1 parcel order, as a client still touches it.
 *
 * Creating and editing are deliberately absent (wave 13): new orders are v2 listings, so a pre-cutover v1 order
 * only has to be readable and closeable. Leaving `POST`/`PATCH` helpers here would invite a second creation
 * path and let one business object be mutated by both engines (Q4).
 */
import { apiRequest } from "./http";
import type { Paginated } from "../types/api";
import type { Bid } from "../types/bid";
import type { ClientOrder, RatingPayload } from "../types/order";

export function listClientOrders(params: { status?: string; page?: number; limit?: number } = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.page) query.set("page", String(params.page));
  if (params.limit) query.set("limit", String(params.limit));
  return apiRequest<Paginated<ClientOrder>>(`/client/orders${query.size ? `?${query}` : ""}`);
}

export function getClientOrder(orderId: number) {
  return apiRequest<ClientOrder>(`/client/orders/${orderId}`);
}

export function listClientOrderBids(orderId: number) {
  return apiRequest<Bid[]>(`/client/orders/${orderId}/bids`);
}

export function selectDriver(orderId: number, bidId: number) {
  return apiRequest<ClientOrder>(`/client/orders/${orderId}/select-driver`, {
    method: "POST",
    body: { bid_id: bidId },
  });
}

export function confirmClientOrder(orderId: number) {
  return apiRequest<ClientOrder>(`/client/orders/${orderId}/confirm`, { method: "POST" });
}

export function rateClientOrder(orderId: number, payload: RatingPayload) {
  return apiRequest<unknown>(`/client/orders/${orderId}/rating`, { method: "POST", body: payload });
}

export function cancelClientOrder(orderId: number, reason: string) {
  return apiRequest<ClientOrder>(`/client/orders/${orderId}/cancel`, { method: "POST", body: { reason } });
}

export function openClientDispute(orderId: number, payload: { reason: string; comment?: string | null }) {
  return apiRequest<unknown>(`/orders/${orderId}/disputes`, { method: "POST", body: payload });
}
