import { clearAuthStorage, getAccessToken, getRefreshToken, saveTokens } from "../auth/tokenStorage";
import { ApiError, type ApiEnvelope } from "../types/api";
import type { TokenResponse } from "../types/auth";

const API_BASE_URL = (process.env.EXPO_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  auth?: boolean;
  retryOnUnauthorized?: boolean;
};

export function buildUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export function unwrapEnvelope<T>(status: number, body: unknown): T {
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

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    clearAuthStorage();
    return false;
  }

  const response = await fetch(buildUrl("/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const raw = await response.json().catch(() => null);
  if (!response.ok) {
    clearAuthStorage();
    return false;
  }
  const data = unwrapEnvelope<TokenResponse>(response.status, raw);
  saveTokens(data.access_token, data.refresh_token, data.user);
  return true;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
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
    const token = getAccessToken();
    if (token) requestHeaders.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(buildUrl(path), {
    ...init,
    headers: requestHeaders,
    body: requestBody,
  });

  if (response.status === 401 && auth && retryOnUnauthorized) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return apiRequest<T>(path, { ...options, retryOnUnauthorized: false });
    }
  }

  const raw = await response.json().catch(() => null);
  return unwrapEnvelope<T>(response.status, raw);
}

export { API_BASE_URL };
