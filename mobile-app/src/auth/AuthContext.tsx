import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { getMe, logout as logoutRequest, requestOtp as requestOtpApi, verifyOtp } from "../api/auth.api";
import { clearAuthStorage, getAccessToken, getRefreshToken, getStoredUser, saveTokens, saveUser } from "./tokenStorage";
import { ApiError } from "../types/api";
import type { AuthUser, MobileRole, RequestOtpPayload } from "../types/auth";
import { normalizeUzPhone } from "../utils/phone";

type AuthContextValue = {
  user: AuthUser | null;
  role: MobileRole | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  accessToken: string | null;
  requestOtp: (payload: RequestOtpPayload) => Promise<void>;
  loginWithOtp: (payload: RequestOtpPayload & { otp: string }) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<AuthUser | null>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser());
  const [accessToken, setAccessToken] = useState<string | null>(() => getAccessToken());
  const [isLoading, setIsLoading] = useState(true);

  const refreshMe = useCallback(async () => {
    if (!getAccessToken()) {
      clearAuthStorage();
      setUser(null);
      setAccessToken(null);
      return null;
    }
    try {
      const currentUser = await getMe();
      saveUser(currentUser);
      setUser(currentUser);
      setAccessToken(getAccessToken());
      return currentUser;
    } catch {
      clearAuthStorage();
      setUser(null);
      setAccessToken(null);
      return null;
    }
  }, []);

  useEffect(() => {
    void refreshMe().finally(() => setIsLoading(false));
  }, [refreshMe]);

  const requestOtp = useCallback(async (payload: RequestOtpPayload) => {
    if (!["client", "driver"].includes(payload.role)) {
      throw new Error("Mobil ilovada bu rolga ruxsat yo'q");
    }
    try {
      await requestOtpApi({ ...payload, phone: normalizeUzPhone(payload.phone) });
    } catch (error) {
      if (error instanceof ApiError && error.code === "OTP_RESEND_TOO_SOON") {
        return;
      }
      throw error;
    }
  }, []);

  const loginWithOtp = useCallback(async (payload: RequestOtpPayload & { otp: string }) => {
    if (!["client", "driver"].includes(payload.role)) {
      throw new Error("Mobil ilovada bu rolga ruxsat yo'q");
    }
    const response = await verifyOtp({
      phone: normalizeUzPhone(payload.phone),
      role: payload.role,
      otp: payload.otp,
    });
    saveTokens(response.access_token, response.refresh_token, response.user);
    setAccessToken(response.access_token);
    setUser(response.user);
    return response.user;
  }, []);

  const logout = useCallback(async () => {
    const refreshToken = getRefreshToken();
    try {
      await logoutRequest(refreshToken);
    } finally {
      clearAuthStorage();
      setUser(null);
      setAccessToken(null);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      role: user?.role === "client" || user?.role === "driver" ? user.role : null,
      isAuthenticated: Boolean(user && accessToken),
      isLoading,
      accessToken,
      requestOtp,
      loginWithOtp,
      logout,
      refreshMe,
    }),
    [accessToken, isLoading, loginWithOtp, logout, refreshMe, requestOtp, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth AuthProvider ichida ishlatilishi kerak");
  }
  return context;
}
