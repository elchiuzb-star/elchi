/**
 * "Can a driver publish both a taxi and a parcel offer on one trip?" - asserted, not assumed.
 *
 * The answer is yes, and the only thing that made it feel otherwise was the client opening the form on a
 * service the trip already advertised. These tests pin the rule the database enforces, so the screen and the
 * index cannot drift apart again.
 */
import { describe, expect, it } from "vitest";

import { isOpenOffer, offerableServices } from "./tripOffers";

const ON = { passengerEnabled: true };
const OFF = { passengerEnabled: false };

describe("offerableServices", () => {
  it("offers both on a trip that advertises nothing yet", () => {
    expect(offerableServices([], ON)).toEqual(["passenger", "parcel"]);
  });

  it("still offers the parcel side once the taxi offer exists", () => {
    // The whole point: one trip, two offers. This is the tap that used to end in DUPLICATE_LISTING.
    expect(offerableServices([{ service_type: "passenger", status: "published" }], ON)).toEqual(["parcel"]);
  });

  it("still offers the taxi side once the parcel offer exists", () => {
    expect(offerableServices([{ service_type: "parcel", status: "published" }], ON)).toEqual(["passenger"]);
  });

  it("offers nothing when the trip already advertises both", () => {
    const both = [
      { service_type: "passenger", status: "published" },
      { service_type: "parcel", status: "draft" },
    ];
    expect(offerableServices(both, ON)).toEqual([]);
  });

  it("counts a draft as taken, because the index does", () => {
    // uq_listings_open_trip_offer excludes only cancelled and expired - a draft holds its service.
    expect(offerableServices([{ service_type: "parcel", status: "draft" }], OFF)).toEqual([]);
  });

  it.each(["cancelled", "expired"])("frees the service again after %s", (status) => {
    expect(offerableServices([{ service_type: "parcel", status }], OFF)).toEqual(["parcel"]);
  });

  it("never offers passenger while the flag is off (Q91: the gate is the entry point, not the model)", () => {
    expect(offerableServices([], OFF)).toEqual(["parcel"]);
    expect(offerableServices([{ service_type: "parcel", status: "published" }], OFF)).toEqual([]);
  });
});

describe("isOpenOffer", () => {
  it.each([
    ["draft", true],
    ["published", true],
    ["paused", true],
    ["cancelled", false],
    ["expired", false],
  ])("%s -> %s", (status, expected) => {
    expect(isOpenOffer(status)).toBe(expected);
  });
});
