export type MobileRole = "client" | "driver";
export type StaffRole = "operator" | "admin" | "super_admin";
export type AuthRole = MobileRole | StaffRole;

export type AuthUser = {
  id: number;
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
