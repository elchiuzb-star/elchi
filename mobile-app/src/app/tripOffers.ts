/**
 * Which services a trip can still be advertised for.
 *
 * One journey carries both a taxi offer and a parcel offer (Q92), and the database says so: the uniqueness
 * index behind a trip offer is `(trip_id, service_type)`, not `trip_id`. So the rule is "one open offer per
 * service", and a cancelled or expired offer frees its service again - that is the index's own predicate,
 * `status NOT IN ('cancelled', 'expired')`, mirrored here.
 *
 * It lives in its own module because getting it wrong is silent on screen: the publish form used to open on
 * "passenger" whatever the trip already advertised, so a driver adding the second offer filled in the whole
 * form and met `DUPLICATE_LISTING` on send. Nothing about that is visible until the last tap, which is exactly
 * the kind of rule that should be asserted directly rather than through a rendered screen.
 *
 * Pure: no React, no API, no formatting.
 */
export type OfferService = "passenger" | "parcel";

/** The two statuses the unique index excludes; anything else occupies its service. */
export function isOpenOffer(status: string): boolean {
  return status !== "cancelled" && status !== "expired";
}

export function offerableServices(
  tripListings: readonly { service_type: string; status: string }[],
  options: { passengerEnabled: boolean },
): OfferService[] {
  const taken = new Set(tripListings.filter((listing) => isOpenOffer(listing.status)).map((l) => l.service_type));
  // Passenger is a rollout gate, not a model change (Q91): when the flag is off the mode is simply not offered.
  const offerable: OfferService[] = options.passengerEnabled ? ["passenger", "parcel"] : ["parcel"];
  return offerable.filter((service) => !taken.has(service));
}
