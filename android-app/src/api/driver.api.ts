import { apiRequest } from "./http";
import type { Paginated } from "../types/api";
import type { Bid, BidPayload } from "../types/bid";
import type {
  DriverDocument,
  DriverDocumentPayload,
  DriverDocumentType,
  DriverFeedOrder,
  DriverOrderAction,
  DriverProfile,
  DriverProfileUpdate,
  DriverRoute,
  DriverRouteCreate,
  DriverRouteStatus,
} from "../types/driver";
import { uploadFile, type RNFile } from "./files.api";

export function getDriverProfile() {
  return apiRequest<DriverProfile>("/driver/profile");
}

export function updateDriverProfile(payload: DriverProfileUpdate) {
  return apiRequest<DriverProfile>("/driver/profile", { method: "PATCH", body: payload });
}

export async function uploadDriverDocument(documentType: DriverDocumentType, file: RNFile) {
  const uploaded = await uploadFile(file, documentType);
  const payload: DriverDocumentPayload = {
    document_type: documentType,
    file_url: uploaded.file_url,
    mime_type: uploaded.mime_type || file.type || undefined,
    size_bytes: uploaded.size_bytes || file.size,
  };
  return apiRequest<unknown>("/driver/documents", { method: "POST", body: payload });
}

export function submitDriverDocument(payload: DriverDocumentPayload) {
  return apiRequest<unknown>("/driver/documents", { method: "POST", body: payload });
}

/** The driver's uploaded documents, with each document's own review status. */
export function getDriverDocuments() {
  return apiRequest<DriverDocument[]>("/driver/documents");
}

export function setDriverAvailability(isAvailable: boolean) {
  return apiRequest<{ is_available: boolean }>("/driver/availability", {
    method: "PATCH",
    body: { is_available: isAvailable },
  });
}

export function getDriverRoutes(status?: DriverRouteStatus) {
  return apiRequest<DriverRoute[]>(`/driver/routes${status ? `?status=${status}` : ""}`);
}

export function createDriverRoute(payload: DriverRouteCreate) {
  return apiRequest<DriverRoute>("/driver/routes", { method: "POST", body: payload });
}

export function updateDriverRoute(routeId: number, payload: DriverRouteCreate) {
  return apiRequest<DriverRoute>(`/driver/routes/${routeId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function updateDriverRouteStatus(routeId: number, payload: { status: DriverRouteStatus }) {
  return apiRequest<{ route_id: number; status: DriverRouteStatus }>(`/driver/routes/${routeId}/status`, {
    method: "PATCH",
    body: payload,
  });
}

export function disableDriverRoute(routeId: number) {
  return apiRequest<{ route_id: number; status: DriverRouteStatus }>(`/driver/routes/${routeId}`, { method: "DELETE" });
}

export function getDriverFeed(params: { page?: number; limit?: number; status?: string; from_city_id?: number; to_city_id?: number } = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  return apiRequest<Paginated<DriverFeedOrder>>(`/driver/orders/feed${query.size ? `?${query}` : ""}`);
}

export function sendBid(orderId: number, payload: BidPayload) {
  return apiRequest<Bid>(`/driver/orders/${orderId}/bids`, { method: "POST", body: payload });
}

export function updateBid(bidId: number, payload: BidPayload) {
  return apiRequest<Bid>(`/driver/bids/${bidId}`, { method: "PATCH", body: payload });
}

export function rejectOrder(orderId: number, reason?: string) {
  return apiRequest<{ success?: boolean; message?: string }>(`/driver/orders/${orderId}/reject`, {
    method: "POST",
    body: { reason },
  });
}

export function getDriverOrders(params: Parameters<typeof getDriverFeed>[0] = {}) {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.limit) query.set("limit", String(params.limit));
  if (params.status) query.set("status", String(params.status));
  return apiRequest<Paginated<DriverFeedOrder>>(`/driver/orders${query.size ? `?${query}` : ""}`);
}

export function getDriverOrderDetail(orderId: number) {
  return apiRequest<unknown>(`/driver/orders/${orderId}`);
}

export function updateDriverOrderStatus(orderId: number, status: DriverOrderAction) {
  const pathByStatus: Record<DriverOrderAction, string> = {
    picked_up: "picked-up",
    in_transit: "in-transit",
    delivered: "delivered",
  };
  return apiRequest<unknown>(`/driver/orders/${orderId}/${pathByStatus[status]}`, { method: "POST" });
}
