/** Client-side v2 marketplace calls (A8): stops, listings, offers, proposals. Types come from the contract. */
import { newIdempotencyKey, v2Request, v2RequestFull, type Schemas, type V2Result } from "./http";

export type ListingCreate = Schemas["ListingCreate"];
export type ListingDTO = Schemas["ListingDTO"];
export type ListingOfferDTO = Schemas["ListingOfferDTO"];
export type ProposalThreadDTO = Schemas["ProposalThreadDTO"];
export type StopRefDTO = Schemas["StopRefDTO"];
/** A private upload this viewer is allowed to render: short-lived signed URL, never a public bucket path. */
export type MediaRefDTO = Schemas["MediaRefDTO"];
/** Q88: a direction end marked on the map - `route_offset_m` says how far it sits from the confirmed road. */
export type MapPointDTO = Schemas["PointEndDTO"];
export type CorridorDTO = Schemas["CorridorDTO"];
export type FeedItemDTO = Schemas["FeedItemDTO"];
export type AcceptRequest = Schemas["AcceptRequest"];
export type ListingCommand = Schemas["ListingCommand"];
export type ListingCancel = Schemas["ListingCancel"];
export type ProposalDecision = Schemas["ProposalDecision"];
export type BookingClientDTO = Schemas["BookingClientDTO"];
export type BookingDTO = Schemas["BookingDTO"];
export type AnyBooking = BookingClientDTO | BookingDTO;

export type EffectiveFlagsDTO = Schemas["EffectiveFlagsDTO"];

/**
 * F1: which stage-2 services this viewer may actually use, resolved for a corridor.
 *
 * The client asks instead of assuming: a service is off until it is switched on per corridor (Q5), and
 * `passenger_enabled` stays off in production until the legal review (K7/Q7). A screen that a flag closes must
 * be unreachable, not merely unlinked.
 */
export function effectiveFlags(corridorId?: string) {
  return v2Request<EffectiveFlagsDTO>("/feature-flags/effective", { query: corridorId ? { corridor_id: corridorId } : {} });
}

export type DirectionPreviewDTO = Schemas["DirectionPreviewDTO"];

/**
 * Q88: can ELCHI carry someone between these two marked places, and along which road?
 *
 * Asked as soon as both pins are set, so the person learns "not on an ELCHI route yet" while they can still
 * move one - not after filling in a price. A `409 ROUTE_MISMATCH` is the product's no-route state, not a bug.
 */
export function previewDirection(params: {
  origin_lat: number;
  origin_lng: number;
  origin_district_id: string;
  destination_lat: number;
  destination_lng: number;
  destination_district_id: string;
}) {
  return v2Request<DirectionPreviewDTO>("/directions/preview", { query: params });
}

export function listCorridors() {
  return v2Request<CorridorDTO[]>("/corridors");
}

export type StopDTO = Schemas["StopDTO"];

/** Stops of one corridor (the picker source); `/stops/search` is a free-text search across regions. */
export function listCorridorStops(corridorId: string) {
  return v2Request<StopDTO[]>(`/corridors/${corridorId}/stops`);
}

export function searchStops(params: { q?: string; region_id?: string; limit?: number } = {}) {
  return v2Request<StopDTO[]>("/stops/search", { query: params });
}

export type RegionDTO = Schemas["RegionDTO"];
export type DistrictDTO = Schemas["DistrictDTO"];
export type CorridorDistrictDTO = Schemas["CorridorDistrictDTO"];

/** G1. `requires_district` says whether the picker asks for a district here (false for Tashkent city). */
export function listRegions() {
  return v2Request<RegionDTO[]>("/regions");
}

/** G16: the district catalogue of a region - the second step of the direction picker. */
export function listDistricts(params: { region_id?: string; q?: string; limit?: number } = {}) {
  return v2Request<DistrictDTO[]>("/districts", { query: params });
}

/**
 * G17: the districts this direction really passes, in travel order.
 *
 * `on_confirmed_route` is the honest part: true = a confirmed route of the corridor stops there, so a listing
 * in that district can be served without leaving the agreed road; false = the corridor owns a stop there but
 * no confirmed route reaches it yet, and the screen must not call it "on your way".
 */
export function listCorridorDistricts(corridorId: string) {
  return v2Request<CorridorDistrictDTO[]>(`/corridors/${corridorId}/districts`);
}

export type RouteVersionDTO = Schemas["RouteVersionDTO"];

/**
 * G18: the confirmed roads of a corridor - what a driver plans a trip on.
 *
 * `POST /routes/preview` builds a *new* road and needs the routing provider, which is off until the legal
 * review (Q24/Q46). Reading roads that were confirmed earlier needs no provider, so the supply side keeps
 * working in the configuration production actually runs in.
 */
export function listCorridorRoutes(corridorId: string, limit = 20) {
  return v2Request<RouteVersionDTO[]>(`/corridors/${corridorId}/routes`, { query: { limit } });
}

export function listMyListings(params: { status?: string; cursor?: string; limit?: number } = {}) {
  return v2Request<ListingDTO[]>("/me/listings", { query: params });
}

export function getListing(listingId: string) {
  return v2Request<ListingDTO>(`/listings/${listingId}`);
}

/** L1: a draft listing. Returns the envelope too, so the caller can show masked-contact warnings (Q43). */
export function createListing(body: ListingCreate, idempotencyKey: string): Promise<V2Result<ListingDTO>> {
  return v2RequestFull<ListingDTO>("/listings", { method: "POST", body, idempotencyKey });
}

export function publishListing(listingId: string, expectedVersion: number) {
  const body: ListingCommand = { expected_version: expectedVersion };
  return v2Request<ListingDTO>(`/listings/${listingId}/publish`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

/** `reason_code` is a required machine code (`^[a-z][a-z0-9_]{2,63}$`); the free text goes to `comment`. */
export function cancelListing(listingId: string, expectedVersion: number, reasonCode: string, comment?: string) {
  const body: ListingCancel = { expected_version: expectedVersion, reason_code: reasonCode, comment: comment ?? null };
  return v2Request<ListingDTO>(`/listings/${listingId}/cancel`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

/** P9: the anonymous list of current competing offers on my request (Q40) - no name, phone or plate. */
export function listListingOffers(listingId: string) {
  return v2Request<ListingOfferDTO[]>(`/listings/${listingId}/offers`);
}

export function listListingProposals(listingId: string) {
  return v2Request<ProposalThreadDTO[]>(`/listings/${listingId}/proposals`);
}

export function getProposal(threadId: string) {
  return v2Request<ProposalThreadDTO>(`/proposals/${threadId}`);
}

/** P8: accept the current version. The booking is the answer; a stale version is refused by the server (AC04). */
export function acceptProposal(threadId: string, body: AcceptRequest, idempotencyKey: string) {
  return v2RequestFull<AnyBooking>(`/proposals/${threadId}/accept`, { method: "POST", body, idempotencyKey });
}

export type ProposalCounter = Schemas["ProposalCounter"];

/**
 * P6: answer a proposal with different terms instead of only accepting or refusing it.
 *
 * The two-sided price agreement is the product (spec §5.3): every correction creates a new immutable version,
 * the previous one becomes `superseded`, and each side may revise the price a limited number of times
 * (`price_revisions_left` on the current version).
 */
export function counterProposal(threadId: string, body: ProposalCounter) {
  return v2RequestFull<ProposalThreadDTO>(`/proposals/${threadId}/counter`, {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

/** P7: take back your own current version; an accepted thread can no longer be withdrawn. */
export function withdrawProposal(threadId: string, expectedRevision: number) {
  return v2Request<ProposalThreadDTO>(`/proposals/${threadId}/withdraw`, {
    method: "POST",
    body: { expected_revision: expectedRevision },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function rejectProposal(threadId: string, expectedRevision: number, reasonCode?: string) {
  const body: ProposalDecision = { expected_revision: expectedRevision, reason_code: reasonCode ?? null };
  return v2Request<ProposalThreadDTO>(`/proposals/${threadId}/reject`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

/**
 * The client's half of the two-sided auction: the driver trip offers that serve this direction.
 *
 * ELCHI is a marketplace both ways round (Q92). The driver publishes a journey with their own starting price
 * and the client answers it with theirs, exactly as the client publishes a request and the driver answers that.
 * This is the same `/feed` the driver uses, asked from the other side - the server ranks it for a client
 * (`_client_components`) and hides offers from drivers this person cannot deal with.
 *
 * Each end is a stop or a district, like `requestsFeed`: a district widens the question from "this exact stop"
 * to "anywhere in this district", still answered on verified stops and the confirmed route order.
 */
export function offersFeed(params: {
  service_type?: string;
  origin_stop_id?: string;
  destination_stop_id?: string;
  origin_district_id?: string;
  destination_district_id?: string;
  date_from?: string;
  date_to?: string;
  seats?: number;
  limit?: number;
  /** The near misses, as their own `alternative` group - the client's half of the same widening. */
  include_alternatives?: boolean;
}) {
  const from = params.date_from ?? new Date().toISOString();
  const to = params.date_to ?? new Date(Date.now() + 14 * 24 * 3600 * 1000).toISOString();
  return v2RequestFull<FeedItemDTO[]>("/feed", {
    query: {
      side: "offers",
      service_type: params.service_type ?? "parcel",
      date_from: from,
      date_to: to,
      origin_stop_id: params.origin_stop_id,
      destination_stop_id: params.destination_stop_id,
      origin_district_id: params.origin_district_id,
      destination_district_id: params.destination_district_id,
      seats: params.seats,
      limit: params.limit,
      include_alternatives: params.include_alternatives ?? true,
    },
  });
}

export type MatchDTO = Schemas["MatchDTO"];

/**
 * M2: what can serve **this** listing, ranked.
 *
 * Different from `/feed` in what it is asked with. The feed takes two ends the person just typed; this takes a
 * listing they already published, so the ranking is against the terms they actually committed to - their
 * window, their seat count, their price - and the client does not re-enter any of it. Only the owner may ask;
 * anyone else gets 404.
 *
 * Q88: a listing whose ends are places on the map is answered here too. It used to return an empty page,
 * because the absent stop ids were passed straight to the matcher.
 */
export function listingMatches(
  listingId: string,
  params: { sort?: string; limit?: number; cursor?: string; include_alternatives?: boolean } = {},
) {
  // Same reasoning as the feed: the near misses come back as their own group, after everything that really
  // matches, so a published offer with no takers still shows its owner where to look.
  const query = { ...params, include_alternatives: params.include_alternatives ?? true };
  return v2RequestFull<MatchDTO[]>(`/listings/${listingId}/matches`, { query });
}

export function feed(params: {
  side: string;
  service_type?: string;
  corridor_id?: string;
  origin_stop_id?: string;
  destination_stop_id?: string;
  origin_district_id?: string;
  destination_district_id?: string;
  origin_region_id?: string;
  destination_region_id?: string;
  limit?: number;
}) {
  return v2RequestFull<FeedItemDTO[]>("/feed", { query: params });
}
