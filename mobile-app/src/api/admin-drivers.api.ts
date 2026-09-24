import { adminApiRequest, query, type AdminRecord } from "./admin.api";
import type { Paginated } from "../types/api";
import type { AdminDriver, AdminDriverDocument, AdminDriverFilters, AdminDriverRoute } from "../types/admin-driver";
import type { AdminOrder } from "../types/admin-order";

/** Result of POST /admin/drivers/{driver_id}/unblock. */
export type AdminDriverUnblockResult = {
  driver_id: number;
  verification_status: AdminDriver["verification_status"];
  user_status: string;
  is_available: boolean;
  reason: string;
  emergency: boolean;
  /** The v2 eligibility block is lifted separately (v2 admin eligibility command); true while it still applies. */
  v2_eligibility_blocked: boolean;
  warning: string | null;
};

/** The per-driver lists are small; one page of the maximum size covers them. */
const DRIVER_LIST_PAGE = { page: 1, limit: 100 };

function cleanFilters(params: AdminDriverFilters): Record<string, string | number | boolean | undefined> {
  return {
    verification_status: params.verification_status,
    is_available: params.is_available === "available" ? true : params.is_available === "unavailable" ? false : undefined,
    search: params.search,
    page: params.page,
    limit: params.limit,
  };
}

export function getAdminDrivers(params: AdminDriverFilters = {}) {
  return adminApiRequest<Paginated<AdminDriver>>(`/admin/drivers${query({ limit: 20, page: 1, ...cleanFilters(params) })}`);
}

export function getAdminDriverDetail(driverId: number) {
  return adminApiRequest<AdminDriver>(`/admin/drivers/${driverId}`);
}

export async function getAdminDriverDocuments(driverId: number) {
  const page = await adminApiRequest<Paginated<AdminDriverDocument>>(`/admin/drivers/${driverId}/documents${query(DRIVER_LIST_PAGE)}`);
  return page.items ?? [];
}

export async function getAdminDriverRoutes(driverId: number) {
  const page = await adminApiRequest<Paginated<AdminDriverRoute>>(`/admin/drivers/${driverId}/routes${query(DRIVER_LIST_PAGE)}`);
  return page.items ?? [];
}

export async function getAdminDriverOrders(driverId: number) {
  const page = await adminApiRequest<Paginated<AdminOrder>>(`/admin/drivers/${driverId}/orders${query(DRIVER_LIST_PAGE)}`);
  return page.items ?? [];
}

/**
 * Q94: the other end of the driver-side lock. The car is entered once by the driver and can only be changed
 * here, by an operator or an admin, which is what "murojaat qiling" on the driver screen actually points at.
 * Without this call that sentence is a dead end.
 */
export function updateDriverVehicle(
  driverId: number,
  payload: { full_name?: string; car_model?: string; plate_number?: string; car_color?: string },
) {
  return adminApiRequest<AdminDriver>(`/admin/drivers/${driverId}/vehicle`, {
    method: "PATCH",
    body: payload,
  });
}

export function approveDriver(driverId: number, payload: { comment?: string | null } = {}) {
  return adminApiRequest<AdminDriver>(`/admin/drivers/${driverId}/approve`, {
    method: "POST",
    body: payload,
  });
}

export function rejectDriver(driverId: number, payload: { reason: string }) {
  return adminApiRequest<AdminDriver>(`/admin/drivers/${driverId}/reject`, {
    method: "POST",
    body: payload,
  });
}

export function blockDriver(driverId: number, payload: { reason: string }) {
  return adminApiRequest<AdminDriver>(`/admin/drivers/${driverId}/block`, {
    method: "POST",
    body: payload,
  });
}

export function unblockDriver(driverId: number, payload: { reason: string }) {
  return adminApiRequest<AdminDriverUnblockResult>(`/admin/drivers/${driverId}/unblock`, {
    method: "POST",
    body: payload,
  });
}

/** Admin/super_admin only (like /admin/audit-logs); operators get 403. */
export async function getDriverAuditLogs(driverId: number) {
  const page = await adminApiRequest<Paginated<AdminRecord>>(`/admin/drivers/${driverId}/audit-logs${query(DRIVER_LIST_PAGE)}`);
  return page.items ?? [];
}

export type { AdminDriver, AdminDriverDocument, AdminDriverRoute };
