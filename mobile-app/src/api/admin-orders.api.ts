import { adminApiRequest, query, type AdminRecord } from "./admin.api";
import type { Paginated } from "../types/api";
import type {
  AdminAssignDriverPayload,
  AdminCancelOrderPayload,
  AdminOrder,
  AdminOrderBid,
  AdminOrderFilters,
  AdminOrderStatusPayload,
  AdminStatusHistoryItem,
} from "../types/admin-order";

function cleanFilters(params: AdminOrderFilters): Record<string, string | number | boolean | undefined> {
  return {
    status: params.status,
    from_city_id: params.from_city_id,
    to_city_id: params.to_city_id,
    order_number: params.search,
    created_from: params.created_from,
    created_to: params.created_to,
    page: params.page,
    limit: params.limit,
  };
}

export function getAdminOrders(params: AdminOrderFilters = {}) {
  return adminApiRequest<Paginated<AdminOrder>>(`/admin/orders${query({ limit: 20, page: 1, ...cleanFilters(params) })}`);
}

export function getAdminOrderDetail(orderId: number) {
  return adminApiRequest<AdminOrder>(`/admin/orders/${orderId}`);
}

export async function getAdminOrderBids(orderId: number) {
  const order = await getAdminOrderDetail(orderId);
  return order.bids ?? [];
}

export async function getAdminOrderStatusHistory(orderId: number) {
  const order = await getAdminOrderDetail(orderId);
  return order.status_history ?? [];
}

export function manualUpdateOrderStatus(orderId: number, payload: AdminOrderStatusPayload) {
  return adminApiRequest<AdminStatusHistoryItem>(`/admin/orders/${orderId}/status`, {
    method: "PATCH",
    body: payload,
  });
}

export function manualAssignDriver(orderId: number, payload: AdminAssignDriverPayload) {
  return adminApiRequest<AdminOrder>(`/admin/orders/${orderId}/assign-driver`, {
    method: "POST",
    body: payload,
  });
}

export function cancelAdminOrder(orderId: number, payload: AdminCancelOrderPayload) {
  return adminApiRequest<AdminOrder>(`/admin/orders/${orderId}/cancel`, {
    method: "POST",
    body: payload,
  });
}

/** Drivers the manual assignment would accept (approved, active, available route, review pairing). */
export async function getEligibleDriversForOrder(orderId: number, params: { search?: string } = {}) {
  const drivers = await adminApiRequest<Paginated<AdminRecord> & { assignable?: boolean }>(
    `/admin/orders/${orderId}/eligible-drivers${query({ search: params.search, page: 1, limit: 100 })}`,
  );
  return (drivers.items ?? []) as AdminRecord[];
}

export type { AdminOrder, AdminOrderBid };
