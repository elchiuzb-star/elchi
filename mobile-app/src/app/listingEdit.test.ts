import { describe, expect, it } from "vitest";

import { formFromListing, ownerListingActions, planListingPatch, windowEditable, type EditableListing } from "./listingEdit";

const NOW = new Date("2026-09-24T08:00:00Z").getTime();

const request: EditableListing = {
  status: "published",
  kind: "request",
  unit_price_minor: 30_000_000,
  comment: "Katta sumka bor",
  departure_window_start: "2026-09-25T04:00:00Z",
  departure_window_end: "2026-09-25T13:00:00Z",
};

describe("owner actions", () => {
  it("pauses a published listing and resumes a paused one", () => {
    expect(ownerListingActions("published")).toEqual({ canPause: true, canResume: false, canEdit: true });
    expect(ownerListingActions("paused")).toEqual({ canPause: false, canResume: true, canEdit: true });
    expect(ownerListingActions("draft")).toEqual({ canPause: false, canResume: false, canEdit: true });
    expect(ownerListingActions("fulfilled").canEdit).toBe(false);
  });

  it("lets only a request's owner move the window (a trip offer's comes from its trip)", () => {
    expect(windowEditable({ kind: "request" })).toBe(true);
    expect(windowEditable({ kind: "trip_offer" })).toBe(false);
  });
});

describe("planListingPatch (Q20)", () => {
  it("sends nothing when nothing changed", () => {
    const plan = planListingPatch(request, formFromListing(request), NOW);
    expect(plan).toMatchObject({ empty: true, material: false, invalid: null });
  });

  it("treats a new unit price or comment as non-material", () => {
    const form = { ...formFromListing(request), price: "320000", comment: "  " };
    const plan = planListingPatch(request, form, NOW);
    expect(plan.body).toEqual({ unit_price_minor: 32_000_000, comment: null });
    expect(plan.material).toBe(false);
  });

  it("treats a moved window on a live listing as material and sends both ends", () => {
    const form = { ...formFromListing(request), windowEnd: formFromListing({ ...request, departure_window_end: "2026-09-25T15:00:00Z" }).windowEnd };
    const plan = planListingPatch(request, form, NOW);
    expect(plan.material).toBe(true);
    expect(plan.body.departure_window_start).toBe("2026-09-25T04:00:00.000Z");
    expect(plan.body.departure_window_end).toBe("2026-09-25T15:00:00.000Z");
  });

  it("does not warn about expiring offers on a draft, which has none", () => {
    const draft = { ...request, status: "draft" };
    const form = { ...formFromListing(draft), windowEnd: formFromListing({ ...draft, departure_window_end: "2026-09-25T15:00:00Z" }).windowEnd };
    expect(planListingPatch(draft, form, NOW).material).toBe(false);
  });

  it("refuses a window that ends before it starts or has passed, and a missing price", () => {
    const base = formFromListing(request);
    expect(planListingPatch(request, { ...base, windowEnd: base.windowStart }, NOW).invalid).toBe("window_order");
    expect(planListingPatch(request, { ...base, windowStart: "" }, NOW).invalid).toBe("window_incomplete");
    expect(planListingPatch(request, { ...base, price: "0" }, NOW).invalid).toBe("price");
    const later = new Date("2026-09-26T00:00:00Z").getTime();
    expect(planListingPatch(request, base, later).invalid).toBe("window_past");
  });

  it("never sends a window for a trip offer", () => {
    const offer = { ...request, kind: "trip_offer" };
    const plan = planListingPatch(offer, { ...formFromListing(offer), windowStart: "", price: "250000" }, NOW);
    expect(plan.invalid).toBeNull();
    expect(plan.body).toEqual({ unit_price_minor: 25_000_000 });
  });
});
