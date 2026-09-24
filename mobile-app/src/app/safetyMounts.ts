/**
 * Where the safety, sharing and reputation panels may appear - pure rules, so the screens stay a thin mount.
 *
 * Q43: before accept no DTO carries the other person's id, so nothing here ever derives one. The only place a
 * counterparty id exists is the booking (`driver` for the client, `client` for the driver).
 */

export type BookingSide = "client" | "driver";

interface PartyRef {
  id: string;
  display_name: string;
}

/** The other person on a booking, as the booking DTO names them; `null` when the DTO does not carry them. */
export function bookingCounterparty(
  booking: { client?: PartyRef | null; driver?: PartyRef | null },
  side: BookingSide,
): { userId: string; name: string } | null {
  const party = side === "client" ? booking.driver : booking.client;
  if (!party?.id) return null;
  return { userId: party.id, name: party.display_name };
}

/** The server's terminal service states (`rules.TERMINAL_SERVICE_STATUSES`): no new tracking link after these. */
const TERMINAL_SERVICE_STATUSES: readonly string[] = ["completed", "cancelled", "no_show", "returned"];

/** K5: a live-tracking link for family is offered only while the booking is still running. */
export function canShareTracking(serviceStatus: string): boolean {
  return !TERMINAL_SERVICE_STATUSES.includes(serviceStatus);
}

/** O1: the server shares only an open listing (`SHAREABLE_LISTING_STATUSES`: published, paused). */
export function canShareListing(status: string): boolean {
  return status === "published" || status === "paused";
}

/** Driver trip planning: the routes of the chosen corridor that pass through the stop the driver searched for. */
export function routesThroughStop<R extends { stops: ReadonlyArray<{ stop_id: string }> }>(
  routes: readonly R[],
  stopId: string | null | undefined,
): R[] {
  if (!stopId) return [...routes];
  return routes.filter((route) => route.stops.some((stop) => stop.stop_id === stopId));
}
