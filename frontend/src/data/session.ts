// Unified auth/session helpers bridging the new UI's role model
// ("client" | "driver" | "admin") onto the backend OTP auth + the two
// separate token stores (mobile vs. admin) used by the API layer.

import { requestOtp as mobileRequestOtp, verifyOtp as mobileVerifyOtp, logout as mobileLogout, getMe } from "../api/auth.api";
import {
  saveTokens,
  clearAuthStorage,
  getAccessToken,
  getRefreshToken,
  getStoredUser,
} from "../auth/tokenStorage";
import { staffLogin, getAdminMe } from "../api/admin.api";
import {
  saveAdminTokens,
  clearAdminAuthStorage,
  getAdminAccessToken,
  getStoredAdminUser,
} from "../auth/adminTokenStorage";
import { ApiError } from "../types/api";
import type { AuthUser, StaffRole } from "../types/auth";
import { normalizeUzPhone } from "../utils/phone";

export type UiRole = "client" | "driver" | "admin";

const STAFF_ROLE_ORDER: StaffRole[] = ["super_admin", "admin", "operator"];
const resolvedStaffRole = new Map<string, StaffRole>();

export type OtpRequestResult = { devOtp?: string };

/** Request an OTP. Clients and drivers only — the backend rejects staff roles here. */
export async function sessionRequestOtp(role: Exclude<UiRole, "admin">, rawPhone: string): Promise<OtpRequestResult> {
  const res = await mobileRequestOtp({ phone: normalizeUzPhone(rawPhone), role });
  return { devOtp: res.dev_otp };
}

/** Verify the OTP and persist tokens. Clients and drivers only. */
export async function sessionVerifyOtp(role: Exclude<UiRole, "admin">, rawPhone: string, otp: string): Promise<AuthUser> {
  const res = await mobileVerifyOtp({ phone: normalizeUzPhone(rawPhone), role, otp });
  saveTokens(res.access_token, res.refresh_token, res.user);
  return res.user;
}

/** Staff sign-in with username + password. Persists into the admin token store. */
export async function sessionStaffLogin(username: string, password: string): Promise<AuthUser> {
  const res = await staffLogin({ username, password });
  saveAdminTokens(res.access_token, res.refresh_token, res.user);
  return res.user;
}

export function isSessionActive(role: UiRole): boolean {
  return role === "admin" ? Boolean(getAdminAccessToken()) : Boolean(getAccessToken());
}

export function sessionUser(role: UiRole): AuthUser | null {
  return role === "admin" ? getStoredAdminUser() : getStoredUser();
}

export function sessionPhone(role: UiRole): string {
  return sessionUser(role)?.phone ?? "";
}

/** Validate the stored token against the backend and confirm the role matches. */
export async function sessionRefreshMe(role: UiRole): Promise<AuthUser | null> {
  try {
    if (role === "admin") {
      const me = await getAdminMe();
      if (!["operator", "admin", "super_admin"].includes(me.role)) return null;
      return me;
    }
    const me = await getMe();
    if (me.role !== role) return null;
    return me;
  } catch {
    return null;
  }
}

export async function sessionLogout(role: UiRole): Promise<void> {
  if (role === "admin") {
    clearAdminAuthStorage();
    return;
  }
  try {
    await mobileLogout(getRefreshToken());
  } catch {
    // ignore network/logout errors — clear locally regardless
  } finally {
    clearAuthStorage();
  }
}
