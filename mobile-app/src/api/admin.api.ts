import { API_BASE_URL } from "./http";
import { clearAdminAuthStorage, getAdminAccessToken, getAdminRefreshToken, saveAdminTokens } from "../auth/adminTokenStorage";
import { ApiError, type ApiEnvelope, type Paginated } from "../types/api";
import type { AuthRole, AuthUser, TokenResponse } from "../types/auth";

export type AdminRecord = Record<string, unknown>;

/**
 * Staff sign-in (`POST /auth/staff-login`): username + password only.
 *
 * Staff accounts never take the phone + OTP path - the server refuses it with `PASSWORD_LOGIN_REQUIRED` so the OTP
 * flow cannot become a second, weaker way into this panel. Limits mirror `StaffLogin` (app/schemas/auth.py).
 */
export type StaffLoginPayload = {
  username: string;
  password: string;
};

export const STAFF_USERNAME_MIN = 3;
export const STAFF_USERNAME_MAX = 64;
export const STAFF_PASSWORD_MIN = 8;
export const STAFF_PASSWORD_MAX = 72;

export type AdminOrderFilters = {
  status?: string;
  order_number?: string;
  client_phone?: string;
  driver_phone?: string;
  page?: number;
  limit?: number;
};

export type AdminDriverFilters = {
  verification_status?: string;
  is_available?: boolean;
  search?: string;
  phone?: string;
  plate_number?: string;
  page?: number;
  limit?: number;
};

export type AdminCityFilters = {
  search?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
};

export type AdminTariffFilters = {
  from_city_id?: number;
  to_city_id?: number;
  is_active?: boolean;
  page?: number;
  limit?: number;
};

type AdminRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  auth?: boolean;
  retryOnUnauthorized?: boolean;
};

function buildUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function unwrapEnvelope<T>(status: number, body: unknown): T {
  if (body && typeof body === "object" && "success" in body) {
    const envelope = body as ApiEnvelope<T>;
    if (envelope.success) return envelope.data;
    throw new ApiError(status, envelope.error);
  }
  if (status >= 400) {
    throw new ApiError(status, { code: "SERVER_ERROR", message: "Xatolik yuz berdi" });
  }
  return body as T;
}

async function refreshAdminAccessToken(): Promise<boolean> {
  const refreshToken = getAdminRefreshToken();
  if (!refreshToken) {
    clearAdminAuthStorage();
    return false;
  }
  const response = await fetch(buildUrl("/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const raw = await response.json().catch(() => null);
  if (!response.ok) {
    clearAdminAuthStorage();
    return false;
  }
  const data = unwrapEnvelope<TokenResponse>(response.status, raw);
  saveAdminTokens(data.access_token, data.refresh_token, data.user);
  return true;
}

export async function adminApiRequest<T>(path: string, options: AdminRequestOptions = {}): Promise<T> {
  const { body, auth = true, retryOnUnauthorized = true, headers, ...init } = options;
  const requestHeaders = new Headers(headers);

  let requestBody: BodyInit | undefined;
  if (body instanceof FormData) {
    requestBody = body;
  } else if (body !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
    requestBody = JSON.stringify(body);
  }

  if (auth) {
    const token = getAdminAccessToken();
    if (token) requestHeaders.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(buildUrl(path), { ...init, headers: requestHeaders, body: requestBody });

  if (response.status === 401 && auth && retryOnUnauthorized) {
    const refreshed = await refreshAdminAccessToken();
    if (refreshed) return adminApiRequest<T>(path, { ...options, retryOnUnauthorized: false });
  }

  const raw = await response.json().catch(() => null);
  return unwrapEnvelope<T>(response.status, raw);
}

export function query(params: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

export function staffLogin(payload: StaffLoginPayload) {
  return adminApiRequest<TokenResponse>("/auth/staff-login", {
    method: "POST",
    body: { username: payload.username.trim(), password: payload.password },
    auth: false,
    retryOnUnauthorized: false,
  });
}

export function getAdminMe() {
  return adminApiRequest<AuthUser>("/auth/me");
}

export function updateAdminMe(payload: { full_name?: string | null }) {
  return adminApiRequest<AuthUser>("/auth/me", {
    method: "PATCH",
    body: payload,
  });
}

export function listAdminOrders(filters: AdminOrderFilters = {}) {
  return adminApiRequest<Paginated<AdminRecord>>(`/admin/orders${query({ limit: 20, ...filters })}`);
}

export function listAdminDrivers(filters: AdminDriverFilters = {}) {
  return adminApiRequest<Paginated<AdminRecord>>(`/admin/drivers${query({ limit: 20, ...filters })}`);
}

export function approveAdminDriver(driverId: number, note = "Approved from admin panel") {
  return adminApiRequest<AdminRecord>(`/admin/drivers/${driverId}/approve`, {
    method: "POST",
    body: { note },
  });
}

export function rejectAdminDriver(driverId: number, reason = "Rejected from admin panel") {
  return adminApiRequest<AdminRecord>(`/admin/drivers/${driverId}/reject`, {
    method: "POST",
    body: { reason },
  });
}

export function blockAdminDriver(driverId: number, reason = "Blocked from admin panel") {
  return adminApiRequest<AdminRecord>(`/admin/drivers/${driverId}/block`, {
    method: "POST",
    body: { reason },
  });
}

export function listAdminCities(filters: AdminCityFilters = {}) {
  return adminApiRequest<Paginated<AdminRecord>>(`/admin/cities${query({ limit: 100, ...filters })}`);
}

export function createAdminCity(payload: { name_uz: string; name_ru?: string | null; region?: string | null }) {
  return adminApiRequest<AdminRecord>("/admin/cities", {
    method: "POST",
    body: payload,
  });
}

export function updateAdminCity(cityId: number, payload: Partial<{ name_uz: string; name_ru: string | null; region: string | null; is_active: boolean }>) {
  return adminApiRequest<AdminRecord>(`/admin/cities/${cityId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function listAdminTariffs(filters: AdminTariffFilters = {}) {
  return adminApiRequest<Paginated<AdminRecord>>(`/admin/route-tariffs${query({ limit: 100, ...filters })}`);
}

export function createAdminTariff(payload: { from_city_id: number; to_city_id: number; suggested_price: number; min_price?: number | null; max_price?: number | null }) {
  return adminApiRequest<AdminRecord>("/admin/route-tariffs", {
    method: "POST",
    body: payload,
  });
}

export function updateAdminTariff(tariffId: number, payload: Partial<{ suggested_price: number; min_price: number | null; max_price: number | null; is_active: boolean }>) {
  return adminApiRequest<AdminRecord>(`/admin/route-tariffs/${tariffId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function listAdminDisputes(filters: { status?: string; reason?: string; page?: number; limit?: number } = {}) {
  return adminApiRequest<Paginated<AdminRecord>>(`/admin/disputes${query({ limit: 20, ...filters })}`);
}

export function listAdminAuditLogs(filters: {
  search?: string;
  action?: string;
  actor_role?: AuthRole | "system" | "";
  entity_type?: string;
  entity_id?: number | string;
  created_from?: string;
  created_to?: string;
  page?: number;
  limit?: number;
} = {}) {
  return adminApiRequest<Paginated<AdminRecord>>(`/admin/audit-logs${query({ limit: 100, page: 1, ...filters })}`);
}

// --- Staff search and queue counts (ADMIN-BACKEND-CONTRACT §4.1, §5) -------------------------------------------
// The wrappers live in chunk B's `v2/admin-market.api.ts`; re-exported here so the shell has one import point and
// nothing is declared twice.
export {
  opsQueueSummary,
  searchAdminBookings,
  searchAdminTrips,
  searchAdminUsers,
  SEARCH_MIN,
  type AdminTripSearchDTO as AdminTripSearchHit,
  type AdminUserSearchDTO as AdminUserSearchHit,
  type OpsQueueCountDTO as OpsQueueCount,
  type StaffBookingDTO as AdminBookingSearchHit,
} from "./v2/admin-market.api";
import { SEARCH_MIN } from "./v2/admin-market.api";

export const SEARCH_MIN_LENGTH = SEARCH_MIN.users;
/** Booking/trip codes match from the start and need at least 4 characters (§5.3, §5.4). */
export const CODE_SEARCH_MIN_LENGTH = SEARCH_MIN.bookings;

/** §2: super_admin sets or resets a staff member's sign-in name and/or password. */
export function setStaffCredentials(userId: number, payload: { username?: string; password?: string }) {
  return adminApiRequest<AuthUser>(`/admin/users/${userId}/credentials`, {
    method: "PUT",
    body: payload,
  });
}
