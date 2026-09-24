/**
 * Safety, sharing and trust calls for the self-contained v2 panels (blocks, reports, tracking grants, share links,
 * the public tracking page, reputation, parcel policy, driver trip detail, stop search, referral code check).
 *
 * Wrappers that already exist elsewhere are re-exported here so every panel imports from one module; nothing is
 * re-declared by hand - every type comes from the generated schema (ADR-0010).
 */
import { newIdempotencyKey, v2Request, v2RequestFull, type Schemas } from "./http";

export { createShareLink } from "./bookings.api";
export { getTrip, tripAvailability, tripManifest } from "./driver.api";
export { searchStops } from "./marketplace.api";
export { checkReferralCode } from "./promo.api";

export type BlockDTO = Schemas["BlockDTO"];
export type ReportCreate = Schemas["ReportCreate"];
export type ReportDTO = Schemas["ReportDTO"];
export type ReportReasonCode = Schemas["ReportReasonCode"];
export type ReportSubjectType = Schemas["ReportSubjectType"];
export type ReportStatus = Schemas["ReportStatus"];
export type TrackingGrantDTO = Schemas["TrackingGrantDTO"];
export type ShareLinkDTO = Schemas["ShareLinkDTO"];
export type ShareLinkChannel = Schemas["ShareLinkChannel"];
export type PublicTrackingDTO = Schemas["PublicTrackingDTO"];
export type TrackingFreshness = Schemas["TrackingFreshness"];
export type ReputationDTO = Schemas["ReputationDTO"];
export type ParcelPolicyDTO = Schemas["ParcelPolicyDTO"];
export type ParcelPolicyItemDTO = Schemas["ParcelPolicyItemDTO"];
export type ServiceType = Schemas["ServiceType"];
export type ReferralCodeCheckDTO = Schemas["ReferralCodeCheckDTO"];
export type StopDTO = Schemas["StopDTO"];
export type TripDTO = Schemas["TripDTO"];
export type TripAvailabilityDTO = Schemas["TripAvailabilityDTO"];
export type TripManifestDTO = Schemas["TripManifestDTO"];
export type ManifestItemDTO = Schemas["ManifestItemDTO"];

// --- S9/S10 blocks: silent, the other side is never told -----------------------------------------------------------

export function listBlocks() {
  return v2Request<BlockDTO[]>("/blocks");
}

export function blockUser(userId: string, idempotencyKey: string = newIdempotencyKey()) {
  return v2Request<BlockDTO>("/blocks", { method: "POST", body: { user_id: userId }, idempotencyKey });
}

/** Idempotent on the server: removing a block that is not there is a success. */
export function unblockUser(userId: string) {
  return v2Request<Record<string, never>>(`/blocks/${encodeURIComponent(userId)}`, { method: "DELETE" });
}

// --- S11 reports: `details` passes the server contact filter, warnings come back in the envelope (Q43) --------------

export function createReport(body: ReportCreate, idempotencyKey: string = newIdempotencyKey()) {
  return v2RequestFull<ReportDTO>("/reports", { method: "POST", body, idempotencyKey });
}

/** Cursor page; `meta.next_cursor` is null on the last page. */
export function listMyReports(cursor?: string | null, limit = 20) {
  return v2RequestFull<ReportDTO[]>("/me/reports", { query: { cursor: cursor ?? undefined, limit } });
}

// --- K5/K7 tracking grants: `url` carries the token and is returned exactly once ------------------------------------

/** Q83 pilot bounds (`TRACKING_GRANT_MIN_TTL`/`MAX_TTL`); the server re-checks them. */
export const TRACKING_GRANT_MIN_MINUTES = 15;
export const TRACKING_GRANT_MAX_MINUTES = 24 * 60;

export function createTrackingGrant(bookingId: string, ttlMinutes: number, idempotencyKey: string = newIdempotencyKey()) {
  return v2Request<TrackingGrantDTO>(`/bookings/${bookingId}/tracking-grants`, {
    method: "POST",
    body: { scope: "recipient_link", ttl_minutes: ttlMinutes },
    idempotencyKey,
  });
}

export function revokeTrackingGrant(bookingId: string, grantId: string) {
  return v2Request<Record<string, never>>(`/bookings/${bookingId}/tracking-grants/${grantId}`, { method: "DELETE" });
}

/** No session; every failure (unknown, revoked, expired, closed window) is the same 404. */
export function publicTracking(token: string) {
  return v2Request<PublicTrackingDTO>(`/public/tracking/${encodeURIComponent(token)}`, { auth: false });
}

// --- O1 listing share links -----------------------------------------------------------------------------------------

export const SHARE_LINK_MAX_HOURS = 336;

export function revokeShareLink(shareLinkId: string) {
  return v2Request<Record<string, never>>(`/share-links/${shareLinkId}`, { method: "DELETE" });
}

// --- S2 reputation, §5.2 parcel policy ------------------------------------------------------------------------------

export function userReputation(userId: string, serviceType: ServiceType) {
  return v2Request<ReputationDTO>(`/users/${encodeURIComponent(userId)}/reputation`, { query: { service_type: serviceType } });
}

/** Readable without a session: a sender must see it before describing a parcel. */
export function parcelPolicy() {
  return v2Request<ParcelPolicyDTO>("/parcel-policy", { auth: false });
}
