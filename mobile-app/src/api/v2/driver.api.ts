/** Driver-side v2 calls (A9): trips, manifest, service actions, offers on client requests and the wallet.
 *
 * GPS is not published from here: the web client is a viewer only, the background tracker is the Android app
 * (ADR-0010 §1, spec §10.5). The wallet screens show the real hold and the pending top-up separately, because a
 * top-up request is not money yet (§9.2).
 */
import { newIdempotencyKey, v2Request, v2RequestFull, type Schemas, type V2Result } from "./http";
import type { AnyBooking, FeedItemDTO, ProposalThreadDTO } from "./marketplace.api";

export type TripDTO = Schemas["TripDTO"];
export type TripManifestDTO = Schemas["TripManifestDTO"];
export type TripAvailabilityDTO = Schemas["TripAvailabilityDTO"];
export type TripActionRequest = Schemas["TripActionRequest"];
export type BookingActionRequest = Schemas["BookingActionRequest"];
export type WalletDTO = Schemas["WalletDTO"];
export type TopupDTO = Schemas["TopupDTO"];
export type TopupCreate = Schemas["TopupCreate"];
export type LedgerLineDTO = Schemas["LedgerLineDTO"];
export type VehicleDTO = Schemas["VehicleDTO"];
export type ProposalCreate = Schemas["ProposalCreate"];

export function listMyTrips(params: { status?: string; limit?: number } = {}) {
  return v2Request<TripDTO[]>("/me/trips", { query: params });
}

export function getTrip(tripId: string) {
  return v2Request<TripDTO>(`/trips/${tripId}`);
}

/** T10: who is on board at which stop - the driver's working list. */
export function tripManifest(tripId: string) {
  return v2Request<TripManifestDTO>(`/trips/${tripId}/manifest`);
}

/** Remaining seats and cargo per segment (AC07/AC10); the server recomputes it, the screen only shows it. */
export function tripAvailability(tripId: string) {
  return v2Request<TripAvailabilityDTO>(`/trips/${tripId}/availability`);
}

export function tripAction(tripId: string, action: string, body: TripActionRequest) {
  return v2Request<TripDTO>(`/trips/${tripId}/actions/${action}`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

/** B3-B6: board / pick up / arrive / deliver. A proof code travels in `code`; a wrong code is counted server-side. */
export function bookingAction(bookingId: string, action: string, body: BookingActionRequest): Promise<V2Result<AnyBooking>> {
  return v2RequestFull<AnyBooking>(`/bookings/${bookingId}/actions/${action}`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

export type VehicleCreate = Schemas["VehicleCreate"];
export type TopupMethod = Schemas["TopupCreate"]["method"];
export type TripCreate = Schemas["TripCreate"];

/**
 * The driver registers a car. It becomes usable only after staff verify it (spec S17.1), so the screen says
 * "tekshiruvda" instead of pretending the car is ready.
 */
export function createVehicle(body: VehicleCreate) {
  return v2Request<VehicleDTO>("/vehicles", { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

/**
 * Plan a trip on one of the corridor's confirmed roads (`GET /corridors/{id}/routes`).
 *
 * The road is chosen from the catalogue rather than built with `POST /routes/preview`, because the routing
 * provider stays off until the legal review (Q24/Q46) and a driver must still be able to publish a trip.
 */
export function createTrip(body: TripCreate) {
  return v2Request<TripDTO>("/trips", { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function listMyVehicles() {
  return v2Request<VehicleDTO[]>("/me/vehicles");
}

export function listMyProposals(params: { state?: string; limit?: number } = {}) {
  return v2Request<ProposalThreadDTO[]>("/me/proposals", { query: params });
}

/**
 * M1 driver side: open client requests this driver may answer (Q21 hides what they cannot).
 *
 * Each end is one of a stop or a district (wave 10). A district end widens the question from "this exact
 * stop" to "anywhere in this district", which is how a driver who picked Toshkent -> Qarshi also sees the
 * requests of the districts along the way: the server still answers on verified stops and the confirmed route
 * order, so nothing is recommended merely because it is administratively nearby (spec §6.1).
 */
export function requestsFeed(params: {
  origin_stop_id?: string;
  destination_stop_id?: string;
  origin_district_id?: string;
  destination_district_id?: string;
  service_type?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  /** §6.4/§8.2: also return the near misses, as their own `alternative` group, ranked below every result. */
  include_alternatives?: boolean;
}) {
  // The feed is always a concrete question: one service, one route, one date range - the server refuses anything
  // vaguer (§6.6: no country-wide mixed list, exactly one end per side).
  const from = params.date_from ?? new Date().toISOString();
  const to = params.date_to ?? new Date(Date.now() + 14 * 24 * 3600 * 1000).toISOString();
  return v2RequestFull<FeedItemDTO[]>("/feed", {
    query: {
      side: "requests",
      service_type: params.service_type ?? "passenger",
      date_from: from,
      date_to: to,
      origin_stop_id: params.origin_stop_id,
      destination_stop_id: params.destination_stop_id,
      origin_district_id: params.origin_district_id,
      destination_district_id: params.destination_district_id,
      limit: params.limit,
      // Asked for by default. A driver whose own route is empty is exactly the one who needs somewhere to
      // look, and the alternatives cost nothing when there are none: the server sorts them last, so they can
      // only ever appear after the real matches.
      include_alternatives: params.include_alternatives ?? true,
    },
  });
}

/** P3: the driver offers a price on a client's request; the server checks the trip, capacity and the price band. */
export function submitProposal(listingId: string, body: ProposalCreate, idempotencyKey: string) {
  return v2RequestFull<ProposalThreadDTO>(`/listings/${listingId}/proposals`, { method: "POST", body, idempotencyKey });
}

export function wallet() {
  return v2Request<WalletDTO>("/wallet");
}

export function walletTransactions(params: { limit?: number } = {}) {
  return v2Request<LedgerLineDTO[]>("/wallet/transactions", { query: params });
}

export function listTopups(params: { status?: string; limit?: number } = {}) {
  return v2Request<TopupDTO[]>("/wallet/topups", { query: params });
}

/** W2: a top-up *request*; it becomes money only when finance approves it (§9.2), and the screen says so. */
export function createTopup(body: TopupCreate, idempotencyKey: string) {
  return v2Request<TopupDTO>("/wallet/topups", { method: "POST", body, idempotencyKey });
}
