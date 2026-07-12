import { adminApiRequest, query } from "./admin.api";
import type { Paginated } from "../types/api";
import type { AdminClient, AdminClientFilters } from "../types/admin-client";

function cleanFilters(params: AdminClientFilters): Record<string, string | number | boolean | undefined> {
  return {
    search: params.search,
    status: params.status,
    is_phone_verified:
      params.is_phone_verified === "verified"
        ? true
        : params.is_phone_verified === "unverified"
          ? false
          : undefined,
    page: params.page,
    limit: params.limit,
  };
}

export function getAdminClients(params: AdminClientFilters = {}) {
  return adminApiRequest<Paginated<AdminClient>>(`/admin/clients${query({ limit: 20, page: 1, ...cleanFilters(params) })}`);
}

export function getAdminClientDetail(userId: number) {
  return adminApiRequest<AdminClient>(`/admin/clients/${userId}`);
}

export function blockAdminClient(userId: number, reason?: string) {
  return adminApiRequest<AdminClient>(`/admin/clients/${userId}/block`, {
    method: "POST",
    body: { reason },
  });
}

export function unblockAdminClient(userId: number, reason?: string) {
  return adminApiRequest<AdminClient>(`/admin/clients/${userId}/unblock`, {
    method: "POST",
    body: { reason },
  });
}
