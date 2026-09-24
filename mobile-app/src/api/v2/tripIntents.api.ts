/**
 * ADR-0025: the client's saved trip/parcel request. Private to the signed-in person (the server takes the owner from
 * the session); it publishes nothing and sends nothing to a driver by itself.
 */
import { newIdempotencyKey, v2Request, v2RequestFull, type Schemas } from "./http";

export type TripIntentDTO = Schemas["TripIntentDTO"];
export type TripIntentCreate = Schemas["TripIntentCreate"];
export type TripIntentUpdate = Schemas["TripIntentUpdate"];
export type TripIntentFitDTO = Schemas["TripIntentFitDTO"];
export type TripIntentVersionDTO = Schemas["TripIntentVersionDTO"];

export function createTripIntent(body: TripIntentCreate, idempotencyKey: string = newIdempotencyKey()) {
  return v2RequestFull<TripIntentDTO>("/me/trip-intents", { method: "POST", body, idempotencyKey });
}

export function listTripIntents(status?: "active" | "booked" | "closed") {
  return v2Request<TripIntentDTO[]>("/me/trip-intents", { query: status ? { status } : {} });
}

export function getTripIntent(intentId: string) {
  return v2Request<TripIntentDTO>(`/me/trip-intents/${intentId}`);
}

/** A material change answers 409 TRIP_INTENT_OFFERS_AFFECTED first; resend with `acknowledge_open_offers: true`. */
export function editTripIntent(intentId: string, body: TripIntentUpdate, idempotencyKey: string = newIdempotencyKey()) {
  return v2RequestFull<TripIntentDTO>(`/me/trip-intents/${intentId}`, { method: "PATCH", body, idempotencyKey });
}

export function closeTripIntent(intentId: string, expectedVersion: number) {
  return v2Request<TripIntentDTO>(`/me/trip-intents/${intentId}/close`, {
    method: "POST", body: { expected_version: expectedVersion }, idempotencyKey: newIdempotencyKey(),
  });
}

/** Explicit "search again" after the booking made from it was cancelled; the old offers stay closed. */
export function reopenTripIntent(intentId: string, expectedVersion: number) {
  return v2Request<TripIntentDTO>(`/me/trip-intents/${intentId}/reopen`, {
    method: "POST", body: { expected_version: expectedVersion }, idempotencyKey: newIdempotencyKey(),
  });
}

/** Advisory comparison with one driver offer; reserves nothing. */
export function tripIntentFit(intentId: string, listingId: string) {
  return v2Request<TripIntentFitDTO>(`/me/trip-intents/${intentId}/fit`, { query: { listing_id: listingId } });
}
