/** ADR-0027: the driver's direction ("where from -> where to") and what the system does with it.
 *
 * The driver names two ends only. Trips, stops, the departure time and the corridor are the server's: the first
 * offer from a direction plans the trip around the client's pickup time, later offers ride on it, an empty trip
 * follows the next client, and a trip already on the road still takes pickups ahead of the car (Q150-Q154).
 */
import { newIdempotencyKey, v2AdminRequest, v2Request, v2RequestFull, type Schemas } from "./http";

export type DriverDirectionDTO = Schemas["DriverDirectionDTO"];
export type AdminDriverDirectionDTO = Schemas["AdminDriverDirectionDTO"];
export type DriverDirectionCreate = Schemas["DriverDirectionCreate"];
export type DriverDirectionPatch = Schemas["DriverDirectionPatch"];
export type DirectionRequestsDTO = Schemas["DirectionRequestsDTO"];
export type DirectionRequestItemDTO = Schemas["DirectionRequestItemDTO"];
export type DirectionOfferDTO = Schemas["DirectionOfferDTO"];
export type DirectionOfferCreate = Schemas["DirectionOfferCreate"];
export type DirectionTripRefDTO = Schemas["DirectionTripRefDTO"];

export function listMyDirections() {
  return v2Request<DriverDirectionDTO[]>("/me/driver-directions");
}

/** DD1. `409 ROUTE_MISMATCH` is the product's "no ELCHI road here yet", not a fault. */
export function createDirection(body: DriverDirectionCreate) {
  return v2Request<DriverDirectionDTO>("/driver-directions", { method: "POST", body, idempotencyKey: newIdempotencyKey() });
}

export function patchDirection(directionId: string, body: DriverDirectionPatch) {
  return v2Request<DriverDirectionDTO>(`/driver-directions/${directionId}`, { method: "PATCH", body });
}

/** DD5: requests along the direction, grouped by how the driver's trip meets them (fit). */
export function directionRequests(directionId: string, params: { service_type: string; date_from: string; date_to: string }) {
  return v2Request<DirectionRequestsDTO>(`/driver-directions/${directionId}/requests`, { query: params });
}

/** DD6: the system takes, re-times or plans the trip, then sends an ordinary offer. */
export function offerFromDirection(directionId: string, body: DirectionOfferCreate, idempotencyKey: string) {
  return v2RequestFull<DirectionOfferDTO>(`/driver-directions/${directionId}/offers`, { method: "POST", body, idempotencyKey });
}

/** DD7 (staff, read-only). */
export function adminListDirections(params: { driver_id?: string; limit?: number } = {}) {
  return v2AdminRequest<AdminDriverDirectionDTO[]>("/admin/driver-directions", { query: params });
}
