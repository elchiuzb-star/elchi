/**
 * K1-K3 and K8: the driver's GPS writer session and the live-tracking WebSocket (spec §10.3, Q148).
 *
 * The web client publishes GPS only while the app is open on the driver's phone (foreground); it is never presented
 * as a background tracker (§10.5). Every type comes from the generated schema (ADR-0010).
 */
import { getAccessToken } from "../../auth/tokenStorage";
import { API_V2_BASE_URL, newIdempotencyKey, v2Request, type Schemas } from "./http";

export type TrackingSessionDTO = Schemas["TrackingSessionDTO"];
export type TrackingSessionCreate = Schemas["TrackingSessionCreate"];
export type TrackingPointIn = Schemas["TrackingPointIn"];
export type PointsBatchIn = Schemas["PointsBatchIn"];
export type PointsBatchAck = Schemas["PointsBatchAck"];
export type BookingTrackingDTO = Schemas["BookingTrackingDTO"];
export type PublicTrackingDTO = Schemas["PublicTrackingDTO"];

/** K1: the trip driver opens the single active writer session; an earlier one (another tab, a restart) is superseded. */
export function createTrackingSession(body: TrackingSessionCreate, idempotencyKey: string = newIdempotencyKey()) {
  return v2Request<TrackingSessionDTO>("/tracking/sessions", { method: "POST", body, idempotencyKey });
}

/** K2: no Idempotency-Key - `(session, seq)` deduplicates a retried batch; the ACK comes after the DB commit. */
export function sendTrackingPoints(sessionId: string, body: PointsBatchIn) {
  return v2Request<PointsBatchAck>(`/tracking/sessions/${encodeURIComponent(sessionId)}/points:batch`, {
    method: "POST",
    body,
  });
}

/** K3: the owner ends the session (idempotent end state). */
export function closeTrackingSession(sessionId: string, idempotencyKey: string = newIdempotencyKey()) {
  return v2Request<TrackingSessionDTO>(`/tracking/sessions/${encodeURIComponent(sessionId)}/close`, {
    method: "POST",
    idempotencyKey,
  });
}

/** K8 address: the v2 base with `ws(s)://`; a relative base resolves against the page. */
export function trackingWebSocketUrl(base: string = API_V2_BASE_URL, page: { href: string } | undefined = globalThis.location): string {
  const absolute = new URL(`${base}/ws`, page?.href ?? "http://127.0.0.1/");
  absolute.protocol = absolute.protocol === "https:" ? "wss:" : "ws:";
  return absolute.toString();
}

/** K8 subscribe frames. The JWT travels in the first frame, never in the URL (it would land in proxy logs). */
export function bookingSubscribeFrame(bookingId: string, accessToken: string | null = getAccessToken()) {
  return { action: "subscribe", booking_id: bookingId, access_token: accessToken ?? "" };
}

export function publicSubscribeFrame(trackingToken: string) {
  return { action: "subscribe", tracking_token: trackingToken };
}
