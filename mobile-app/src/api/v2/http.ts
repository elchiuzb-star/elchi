/**
 * Typed `/api/v2` client (ADR-0010).
 *
 * Thin wrapper over the existing v1 fetch/refresh layer: the envelope, the error class and the token storage are
 * shared, only the base URL and the types differ. Every request and response type comes from `generated/v2.ts`;
 * nothing here re-declares a DTO by hand (spec §12).
 */
import { clearAdminAuthStorage, getAdminAccessToken, getAdminRefreshToken, saveAdminTokens } from "../../auth/adminTokenStorage";
import { clearAuthStorage, getAccessToken, getRefreshToken, saveTokens } from "../../auth/tokenStorage";
import { ApiError, type ApiEnvelope } from "../../types/api";
import type { TokenResponse } from "../../types/auth";
import type { components, paths } from "../generated/v2";

/** v2 lives next to v1 on the same host: `.../api/v1` -> `.../api/v2` unless VITE_API_V2_BASE_URL is set. */
const V1_BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");
export const API_V2_BASE_URL = (import.meta.env.VITE_API_V2_BASE_URL || V1_BASE.replace(/\/api\/v1$/, "/api/v2")).replace(
  /\/$/,
  "",
);

export type Schemas = components["schemas"];
export type V2Path = keyof paths;

/** The `data` of a v2 envelope, with `meta`/`warnings` when the endpoint returns them. */
export type Envelope<T> = { success: true; data: T; message?: string | null; meta?: unknown; warnings?: ApiWarning[] | null };
export type ApiWarning = Schemas["ApiWarning"];

/** The client app and the admin panel keep separate sessions; a request says which one it belongs to. */
export type Audience = "client" | "admin";

type RequestOptions = {
  audience?: Audience;
  /** `PUT` is only used by G13, the versioned price-reference upsert. */
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Command endpoints are idempotent per key (ADR-0005); a retry with the same key replays the first answer. */
  idempotencyKey?: string;
  auth?: boolean;
  signal?: AbortSignal;
  retryOnUnauthorized?: boolean;
};

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_V2_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return url;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  return search.size ? `${url}?${search}` : url;
}

/** A random idempotency key for one user action (the caller keeps it across retries of that action). */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

async function refreshAccessToken(audience: Audience): Promise<boolean> {
  const refreshToken = audience === "admin" ? getAdminRefreshToken() : getRefreshToken();
  const forget = audience === "admin" ? clearAdminAuthStorage : clearAuthStorage;
  if (!refreshToken) {
    forget();
    return false;
  }
  // Auth stays on v1 (ADR-0006): the same JWT is accepted by v2.
  const response = await fetch(`${V1_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const raw = (await response.json().catch(() => null)) as ApiEnvelope<TokenResponse> | null;
  if (!response.ok || !raw || !("success" in raw) || !raw.success) {
    forget();
    return false;
  }
  if (audience === "admin") saveAdminTokens(raw.data.access_token, raw.data.refresh_token, raw.data.user);
  else saveTokens(raw.data.access_token, raw.data.refresh_token, raw.data.user);
  return true;
}

export type V2Result<T> = { data: T; warnings: ApiWarning[]; meta: unknown };

/** Raw request: returns data plus the envelope's `warnings`/`meta`; throws `ApiError` on a v2 error body. */
export async function v2RequestFull<T>(path: string, options: RequestOptions = {}): Promise<V2Result<T>> {
  const { audience = "client", method = "GET", body, query, idempotencyKey, auth = true, signal, retryOnUnauthorized = true } = options;
  const headers = new Headers();
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  // Q110: this client renders F_cash wherever a discounted booking shows money. A rendering capability the server
  // uses to decide whether a promo deal may be shown here - never an authority, never MFA evidence.
  if (audience === "client") headers.set("X-Elchi-Client-Features", "promo_cash_v1");
  if (auth) {
    const token = audience === "admin" ? getAdminAccessToken() : getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(buildUrl(path, query), {
    method,
    headers,
    signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && auth && retryOnUnauthorized && (await refreshAccessToken(audience))) {
    return v2RequestFull<T>(path, { ...options, retryOnUnauthorized: false });
  }

  const raw = (await response.json().catch(() => null)) as ApiEnvelope<T> | null;
  if (raw && typeof raw === "object" && "success" in raw) {
    if (raw.success) {
      const envelope = raw as Envelope<T>;
      return { data: envelope.data, warnings: envelope.warnings ?? [], meta: envelope.meta };
    }
    throw new ApiError(response.status, raw.error);
  }
  throw new ApiError(response.status, {
    code: response.ok ? "SERVER_ERROR" : "SERVER_ERROR",
    message: "Xatolik yuz berdi",
  });
}

export async function v2Request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const result = await v2RequestFull<T>(path, options);
  return result.data;
}

/** Same request, but with the admin panel's session (A9 operator screens). */
export function v2AdminRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return v2Request<T>(path, { ...options, audience: "admin" });
}

export function v2AdminRequestFull<T>(path: string, options: RequestOptions = {}): Promise<V2Result<T>> {
  return v2RequestFull<T>(path, { ...options, audience: "admin" });
}
