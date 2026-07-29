import { adminApiRequest, query } from "./admin.api";
import type { Paginated } from "../types/api";
import type {
  AdminStaffUser,
  AdminStaffUserCreatePayload,
  AdminStaffUserFilters,
  AdminStaffUserUpdatePayload,
} from "../types/admin-user";

function cleanFilters(params: AdminStaffUserFilters): Record<string, string | number | boolean | undefined> {
  return {
    search: params.search,
    role: params.role,
    status: params.status,
    created_from: params.created_from,
    created_to: params.created_to,
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

export function getAdminUsers(params: AdminStaffUserFilters = {}) {
  return adminApiRequest<Paginated<AdminStaffUser>>(`/admin/users${query({ limit: 20, page: 1, ...cleanFilters(params) })}`);
}

export function getAdminUserDetail(userId: number) {
  return adminApiRequest<AdminStaffUser>(`/admin/users/${userId}`);
}

export function createStaffUser(payload: AdminStaffUserCreatePayload) {
  return adminApiRequest<AdminStaffUser>("/admin/users", {
    method: "POST",
    body: payload,
  });
}

export function updateStaffUser(userId: number, payload: AdminStaffUserUpdatePayload) {
  return adminApiRequest<AdminStaffUser>(`/admin/users/${userId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function blockStaffUser(userId: number, reason: string) {
  return adminApiRequest<AdminStaffUser>(`/admin/users/${userId}/block`, {
    method: "POST",
    body: { reason },
  });
}

export function unblockStaffUser(userId: number, reason: string) {
  return adminApiRequest<AdminStaffUser>(`/admin/users/${userId}/unblock`, {
    method: "POST",
    body: { reason },
  });
}
