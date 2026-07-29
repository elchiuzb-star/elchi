import { apiRequest } from "./http";
import type { AuthUser, RequestOtpPayload, TokenResponse, VerifyOtpPayload } from "../types/auth";

export function requestOtp(payload: RequestOtpPayload) {
  return apiRequest<{ otp_sent: boolean; phone: string; dev_otp?: string }>("/auth/request-otp", {
    method: "POST",
    body: payload,
    auth: false,
  });
}

export function verifyOtp(payload: VerifyOtpPayload) {
  return apiRequest<TokenResponse>("/auth/verify-otp", {
    method: "POST",
    body: payload,
    auth: false,
  });
}

export function refreshToken(refreshTokenValue: string) {
  return apiRequest<TokenResponse>("/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshTokenValue },
    auth: false,
  });
}

export function logout(refreshTokenValue?: string | null) {
  return apiRequest<{ success?: boolean; message?: string }>("/auth/logout", {
    method: "POST",
    body: refreshTokenValue ? { refresh_token: refreshTokenValue } : {},
  });
}

export function getMe() {
  return apiRequest<AuthUser>("/auth/me");
}
