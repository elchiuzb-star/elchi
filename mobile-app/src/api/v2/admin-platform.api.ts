/**
 * Staff platform configuration (F1-F4 flags, G7-G11 corridors/stops, N8/N9 outbox, R5.2 parcel policy, O8/§10.8).
 *
 * Every command takes the Idempotency-Key of one user action from the caller (`newIdempotencyKey()` once per
 * confirmed click), so a retry after a timeout replays the first answer instead of writing twice. The two versioned
 * PATCH endpoints (corridor, stop) are protected by `expected_version`; the key is sent there too and is simply not
 * read by the server. Paths are written out in full so the client-contract test can check them.
 */
import { v2AdminRequest, v2AdminRequestFull, type Schemas } from "./http";

export type FeatureFlagKey = Schemas["FeatureFlagKey"];
export type FlagScopeType = Schemas["FlagScopeType"];
export type FlagValueDTO = Schemas["FlagValueDTO"];
export type FlagChangeDTO = Schemas["FlagChangeDTO"];
export type FlagValueUpsert = Schemas["FlagValueUpsert"];
export type CorridorAdminDTO = Schemas["CorridorAdminDTO"];
export type CorridorCreate = Schemas["CorridorCreate"];
export type CorridorPatch = Schemas["CorridorPatch"];
export type CorridorRolloutState = Schemas["CorridorRolloutState"];
export type StopCreate = Schemas["StopCreate"];
export type StopPatch = Schemas["StopPatch"];
export type AdminStopDTO = Schemas["AdminStopDTO"];
export type StopDTO = Schemas["StopDTO"];
export type Q47ViolationDTO = Schemas["Q47ViolationDTO"];
export type OutboxEventAdminDTO = Schemas["OutboxEventAdminDTO"];
export type ParcelPolicyVersionDTO = Schemas["ParcelPolicyVersionDTO"];
export type ParcelPolicyVersionCreate = Schemas["ParcelPolicyVersionCreate"];
export type ParcelPolicyItemCreate = Schemas["ParcelPolicyItemCreate"];
export type ParcelPolicyDTO = Schemas["ParcelPolicyDTO"];
export type ProviderQuotaDTO = Schemas["ProviderQuotaDTO"];
export type ParcelCategoryVersionDTO = Schemas["ParcelCategoryVersionDTO"];
export type ParcelCategoryVersionCreate = Schemas["ParcelCategoryVersionCreate"];
export type ParcelCategoryItemInput = Schemas["ParcelCategoryItemInput"];
export type LegacyOrderViewDTO = Schemas["LegacyOrderViewDTO"];
export type RegionDTO = Schemas["RegionDTO"];
export type DistrictDTO = Schemas["DistrictDTO"];

type PageMeta = { next_cursor?: string | null } | null | undefined;

function nextCursor(meta: unknown): string | null {
  return ((meta as PageMeta)?.next_cursor as string | null | undefined) ?? null;
}

// --- feature flags (F2-F4) ------------------------------------------------------------------------------------------

/** F2: every stored scope row. A flag with no row resolves to its production default (see `adminPlatform.ts`). */
export function adminFeatureFlags(params: { flag_key?: FeatureFlagKey; scope_type?: FlagScopeType } = {}) {
  return v2AdminRequest<FlagValueDTO[]>("/admin/feature-flags", { query: params });
}

export async function adminFeatureFlagHistory(flagKey: FeatureFlagKey, params: { cursor?: string | null; limit?: number } = {}) {
  const result = await v2AdminRequestFull<FlagChangeDTO[]>(`/admin/feature-flags/${flagKey}/history`, { query: params });
  return { items: result.data, nextCursor: nextCursor(result.meta) };
}

/**
 * F3: set one scope row. `expected_version` is null only for a scope that has no row yet. Production refusals come
 * back as errors: 503 PRODUCTION_INVARIANTS_FAILED (Q48 gate, Q56), 403 FORBIDDEN (super_admin required, Q5),
 * APPROVAL_REFERENCE_REQUIRED (Q5), FLAG_LOCKED_IN_ENVIRONMENT (Q1), VALIDATION_ERROR support_contact_not_configured (Q87).
 */
export function adminSetFeatureFlag(
  flagKey: FeatureFlagKey,
  scopeType: FlagScopeType,
  scopeRef: string,
  body: FlagValueUpsert,
  idempotencyKey: string,
) {
  return v2AdminRequest<FlagValueDTO>(
    `/admin/feature-flags/${flagKey}/scopes/${scopeType}/${encodeURIComponent(scopeRef)}`,
    { method: "PUT", body, idempotencyKey },
  );
}

// --- corridors and stops (G7-G11, F1 Q47 check) ---------------------------------------------------------------------

export async function adminCorridors(params: { cursor?: string | null; limit?: number } = {}) {
  const result = await v2AdminRequestFull<CorridorAdminDTO[]>("/admin/corridors", { query: params });
  return { items: result.data, nextCursor: nextCursor(result.meta) };
}

export function adminCreateCorridor(body: CorridorCreate, idempotencyKey: string) {
  return v2AdminRequest<CorridorAdminDTO>("/admin/corridors", { method: "POST", body, idempotencyKey });
}

export function adminPatchCorridor(corridorId: string, body: CorridorPatch, idempotencyKey: string) {
  return v2AdminRequest<CorridorAdminDTO>(`/admin/corridors/${corridorId}`, { method: "PATCH", body, idempotencyKey });
}

export function adminCreateStop(corridorId: string, body: StopCreate, idempotencyKey: string) {
  return v2AdminRequest<AdminStopDTO>(`/admin/corridors/${corridorId}/stops`, { method: "POST", body, idempotencyKey });
}

export function adminPatchStop(stopId: string, body: StopPatch, idempotencyKey: string) {
  return v2AdminRequest<AdminStopDTO>(`/admin/stops/${stopId}`, { method: "PATCH", body, idempotencyKey });
}

/**
 * G3 (public read): the *active* stops of a pilot/active corridor; a draft/internal corridor answers 404 here.
 */
export function corridorPublicStops(corridorId: string) {
  return v2AdminRequest<StopDTO[]>(`/corridors/${corridorId}/stops`);
}

/** Staff list: every stop of the corridor (inactive ones and draft corridors too) with the version a PATCH needs. */
export function adminCorridorStops(corridorId: string) {
  return v2AdminRequest<AdminStopDTO[]>(`/admin/corridors/${corridorId}/stops`);
}

/** F1: pilot/active corridors that already break Q47 (>= 2 active stops, each with meeting evidence). */
export function adminQ47Violations() {
  return v2AdminRequest<Q47ViolationDTO[]>("/admin/geo/checks/q47");
}

export function adminRegions() {
  return v2AdminRequest<RegionDTO[]>("/regions");
}

export function adminDistricts(regionId: string) {
  return v2AdminRequest<DistrictDTO[]>("/districts", { query: { region_id: regionId, limit: 500 } });
}

// --- outbox (N8/N9) -------------------------------------------------------------------------------------------------

export async function adminOutbox(params: { state?: "failed" | "dead"; cursor?: string | null; limit?: number } = {}) {
  const result = await v2AdminRequestFull<OutboxEventAdminDTO[]>("/admin/outbox", { query: params });
  return { items: result.data, nextCursor: nextCursor(result.meta) };
}

export function adminRetryOutbox(eventId: string, reason: string, idempotencyKey: string) {
  return v2AdminRequest<OutboxEventAdminDTO>(`/admin/outbox/${eventId}/retry`, {
    method: "POST",
    body: { reason },
    idempotencyKey,
  });
}

// --- parcel prohibited-items policy (R5.2) --------------------------------------------------------------------------

export function adminParcelPolicies() {
  return v2AdminRequest<ParcelPolicyVersionDTO[]>("/admin/parcel-policies");
}

/** The version clients see now (items with sources) - or `approved: false` when none is confirmed. */
export function activeParcelPolicy() {
  return v2AdminRequest<ParcelPolicyDTO>("/parcel-policy");
}

export function adminCreateParcelPolicy(body: ParcelPolicyVersionCreate, idempotencyKey: string) {
  return v2AdminRequest<ParcelPolicyVersionDTO>("/admin/parcel-policies", { method: "POST", body, idempotencyKey });
}

/** A second super_admin approves; the author is refused (FORBIDDEN author_cannot_confirm_own_policy). */
export function adminConfirmParcelPolicy(policyId: string, expectedVersion: number, idempotencyKey: string) {
  return v2AdminRequest<ParcelPolicyVersionDTO>(`/admin/parcel-policies/${policyId}/confirm`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

// --- parcel size categories (Q140, ADR-0026) ----------------------------------------------------------------------

/** Every catalog version, newest first. A draft applies to nobody; a synthetic one never passes production. */
export function adminParcelCategoryVersions() {
  return v2AdminRequest<ParcelCategoryVersionDTO[]>("/admin/parcel-categories");
}

export function adminCreateParcelCategoryVersion(body: ParcelCategoryVersionCreate, idempotencyKey: string) {
  return v2AdminRequest<ParcelCategoryVersionDTO>("/admin/parcel-categories", { method: "POST", body, idempotencyKey });
}

/** A second super_admin activates the draft; bookings keep the category item they were agreed on. */
export function adminConfirmParcelCategoryVersion(versionId: string, expectedVersion: number, idempotencyKey: string) {
  return v2AdminRequest<ParcelCategoryVersionDTO>(`/admin/parcel-categories/${versionId}/confirm`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

// --- system state (§10.8, O8) ---------------------------------------------------------------------------------------

export function adminProviderQuota(day?: string) {
  return v2AdminRequest<ProviderQuotaDTO[]>("/admin/metrics/provider-quota", { query: { day } });
}

export function adminLegacyOrder(legacyOrderNumber: string) {
  return v2AdminRequest<LegacyOrderViewDTO>(`/admin/legacy-orders/${encodeURIComponent(legacyOrderNumber)}`);
}
