export type MobileRole = "client" | "driver";
/** Q17: `finance` is a staff role of its own (top-up approval, finalize_fee, finance reports). */
export type StaffRole = "operator" | "admin" | "super_admin" | "finance";
export const STAFF_ROLES: readonly StaffRole[] = ["operator", "admin", "super_admin", "finance"];

export function isStaffRole(role: unknown): role is StaffRole {
  return typeof role === "string" && (STAFF_ROLES as readonly string[]).includes(role);
}
export type AuthRole = MobileRole | StaffRole;

export type AuthUser = {
  id: number;
  /** v2 public id (`usr_...`), when the server sends it (staff list / me). */
  public_id?: string | null;
  /** Staff sign-in name (`/auth/staff-login`); absent for client and driver accounts. */
  username?: string | null;
  phone: string;
  full_name?: string | null;
  role: AuthRole;
  status: string;
  is_phone_verified: boolean;
};

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in?: number;
  user: AuthUser;
};

export type RequestOtpPayload = {
  phone: string;
  role: MobileRole;
};

export type VerifyOtpPayload = RequestOtpPayload & {
  otp: string;
};
