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
import { requestAdminOtp, verifyAdminOtp, getAdminMe } from "../api/admin.api";
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

/** Request an OTP for the given UI role. Returns the dev OTP when the backend is in development mode. */
export async function sessionRequestOtp(role: UiRole, rawPhone: string): Promise<OtpRequestResult> {
  const phone = normalizeUzPhone(rawPhone);
  if (role !== "admin") {
    const res = await mobileRequestOtp({ phone, role });
    return { devOtp: res.dev_otp };
  }
  // Admin: auto-detect the staff role that matches this phone.
  let lastError: unknown = null;
  for (const staffRole of STAFF_ROLE_ORDER) {
    try {
      const res = await requestAdminOtp({ phone, role: staffRole });
      resolvedStaffRole.set(phone, staffRole);
      return { devOtp: res.dev_otp };
    } catch (error) {
      lastError = error;
      if (error instanceof ApiError && (error.code === "ROLE_MISMATCH" || error.code === "FORBIDDEN")) {
        continue; // try the next staff role
      }
      throw error;
    }
  }
  throw lastError ?? new Error("Staff user not found");
}

/** Verify the OTP and persist tokens into the correct store for this role. */
export async function sessionVerifyOtp(role: UiRole, rawPhone: string, otp: string): Promise<AuthUser> {
  const phone = normalizeUzPhone(rawPhone);
  if (role !== "admin") {
    const res = await mobileVerifyOtp({ phone, role, otp });
    saveTokens(res.access_token, res.refresh_token, res.user);
    return res.user;
  }
  const staffRole = resolvedStaffRole.get(phone) ?? "admin";
  const res = await verifyAdminOtp({ phone, role: staffRole, otp });
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
