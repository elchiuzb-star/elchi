import { adminApiRequest, query } from "./admin.api";
import type { Paginated } from "../types/api";
import type { AdminDriver, AdminDriverDocument, AdminDriverFilters, AdminDriverRoute } from "../types/admin-driver";

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
  // TODO: Replace this detail fallback when backend adds GET /admin/drivers/{driver_id}/documents.
  const driver = await getAdminDriverDetail(driverId);
  return driver.documents ?? [];
}

export async function getAdminDriverRoutes(driverId: number) {
  // TODO: Replace this detail fallback when backend adds GET /admin/drivers/{driver_id}/routes.
  const driver = await getAdminDriverDetail(driverId);
  return driver.routes ?? [];
}

export async function getAdminDriverOrders(_driverId: number) {
  // TODO: Wire to GET /admin/drivers/{driver_id}/orders when backend adds it.
  return [];
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

export async function unblockDriver(_driverId: number, _payload: { reason: string }) {
  // TODO: Backend does not expose POST /admin/drivers/{driver_id}/unblock yet.
  throw new Error("Unblock is not supported by backend yet");
}

export async function getDriverAuditLogs(_driverId: number) {
  // TODO: Wire to GET /admin/drivers/{driver_id}/audit-logs when backend adds it.
  return [];
}

export type AdminDriverVehiclePayload = {
  full_name?: string | null;
  car_model?: string | null;
  car_color?: string | null;
  plate_number?: string | null;
};

export function updateDriverVehicle(driverId: number, payload: AdminDriverVehiclePayload) {
  return adminApiRequest<AdminDriver>(`/admin/drivers/${driverId}/vehicle`, {
    method: "PATCH",
    body: payload,
  });
}

export type { AdminDriver, AdminDriverDocument, AdminDriverRoute };
