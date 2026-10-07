import { describe, expect, it } from "vitest";

import { bookingCounterparty, canShareListing, canShareTracking } from "./safetyMounts";

describe("bookingCounterparty", () => {
  const booking = {
    client: { id: "usr_client", display_name: "Ali" },
    driver: { id: "usr_driver", display_name: "Vali" },
  };

  it("gives the client the driver and the driver the client", () => {
    expect(bookingCounterparty(booking, "client")).toEqual({ userId: "usr_driver", name: "Vali" });
    expect(bookingCounterparty(booking, "driver")).toEqual({ userId: "usr_client", name: "Ali" });
  });

  it("returns null when the DTO does not carry the other person", () => {
    expect(bookingCounterparty({ client: booking.client, driver: null }, "client")).toBeNull();
    expect(bookingCounterparty({ driver: booking.driver }, "driver")).toBeNull();
    expect(bookingCounterparty({ client: { id: "", display_name: "x" } }, "driver")).toBeNull();
  });
});

describe("canShareTracking", () => {
  it("is open while the booking runs", () => {
    for (const status of ["confirmed", "awaiting_pickup", "onboard", "picked_up", "in_transit", "delivered"]) {
      expect(canShareTracking(status)).toBe(true);
    }
  });

  it("is closed after a terminal state", () => {
    for (const status of ["completed", "cancelled", "no_show", "returned"]) {
      expect(canShareTracking(status)).toBe(false);
    }
  });
});

describe("canShareListing", () => {
  it("allows only published and paused listings", () => {
    expect(canShareListing("published")).toBe(true);
    expect(canShareListing("paused")).toBe(true);
    for (const status of ["draft", "fulfilled", "expired", "cancelled"]) expect(canShareListing(status)).toBe(false);
  });
});
