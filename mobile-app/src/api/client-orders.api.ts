import { apiRequest } from "./http";
import type { Paginated } from "../types/api";
import type { Bid } from "../types/bid";
import type { ClientOrder, CreateOrderPayload, RatingPayload } from "../types/order";

export function createClientOrder(payload: CreateOrderPayload) {
  const body = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined && value !== null && value !== ""),
  );
  return apiRequest<ClientOrder>("/client/orders", { method: "POST", body });
}

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

export function updateClientOrder(orderId: number, payload: Partial<CreateOrderPayload>) {
  const body = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined && value !== null && value !== ""),
  );
  return apiRequest<ClientOrder>(`/client/orders/${orderId}`, { method: "PATCH", body });
}

export function publishClientOrder(orderId: number) {
  return apiRequest<ClientOrder>(`/client/orders/${orderId}/publish`, { method: "POST" });
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
