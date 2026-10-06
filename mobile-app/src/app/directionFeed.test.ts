import { describe, expect, it } from "vitest";

import { ApiError } from "../types/api";
import {
  clockTime,
  dayClock,
  directionEndName,
  feedRange,
  groupDirectionItems,
  isDuplicateDirection,
  isNoRoad,
  isPickupPassed,
  timeProposalEta,
  timeProposalTooFar,
} from "./directionFeed";

const item = (id: string, fit: "fits_trip" | "no_trip" | "time_differs") =>
  ({ listing: { id } as never, match_type: "exact", fit, pickup_eta: null, suggested_departure_at: null, my_thread_id: null }) as never;

describe("groupDirectionItems", () => {
  it("cuts the page into the three answers and keeps the server's order inside each", () => {
    const groups = groupDirectionItems([item("a", "no_trip"), item("b", "fits_trip"), item("c", "time_differs"), item("d", "fits_trip")]);
    expect(groups.fits.map((i: { listing: { id: string } }) => i.listing.id)).toEqual(["b", "d"]);
    expect(groups.fresh.map((i: { listing: { id: string } }) => i.listing.id)).toEqual(["a"]);
    expect(groups.otherTime.map((i: { listing: { id: string } }) => i.listing.id)).toEqual(["c"]);
  });
});

describe("feedRange", () => {
  const now = new Date("2026-10-06T08:30:00Z"); // 13:30 in Tashkent

  it("today runs from now to Tashkent midnight", () => {
    expect(feedRange("today", now)).toEqual({ date_from: "2026-10-06T08:30:00.000Z", date_to: "2026-10-06T19:00:00.000Z" });
  });

  it("tomorrow is the whole next Tashkent day", () => {
    expect(feedRange("tomorrow", now)).toEqual({ date_from: "2026-10-06T19:00:00.000Z", date_to: "2026-10-07T19:00:00.000Z" });
  });

  it("a week is seven days from now - inside the server's 14-day limit", () => {
    expect(feedRange("week", now).date_to).toBe("2026-10-13T08:30:00.000Z");
  });
});

describe("clockTime and directionEndName", () => {
  it("shows Tashkent wall time", () => {
    expect(clockTime("2026-10-06T17:04:13Z")).toBe("22:04");
    expect(clockTime(null)).toBe("-");
    expect(dayClock("2026-10-06T19:30:00Z")).toBe("07.10 00:30"); // past midnight in Tashkent: the next day
  });

  it("names the district, or the region of a city without districts", () => {
    const base = { region_id: "reg_1", region_name_uz: "Toshkent shahri", region_name_ru: "г. Ташкент", district_id: null, district_name_uz: null, district_name_ru: null };
    expect(directionEndName(base)).toBe("Toshkent shahri");
    expect(directionEndName({ ...base, district_id: "dst_1", district_name_uz: "Qarshi", district_name_ru: "Карши" }, true)).toBe("Карши");
  });
});

describe("server answers the screens act on", () => {
  it("reads the car's ETA from a time conflict", () => {
    const err = new ApiError(409, { code: "TIME_WINDOW_CONFLICT", message: "x", details: { reason: "trip_time_differs", eta: "2026-10-06T17:04:13+00:00" } });
    expect(timeProposalEta(err)).toBe("2026-10-06T17:04:13+00:00");
    expect(timeProposalEta(new ApiError(409, { code: "ROUTE_MISMATCH", message: "x" }))).toBeNull();
    // Q157: beyond the limits the screen must not offer the ETA as a proposal; it says why instead
    const far = new ApiError(409, { code: "TIME_WINDOW_CONFLICT", message: "x", details: { eta: "2026-10-06T18:43:13+00:00", time_proposal_possible: false } });
    expect(timeProposalEta(far)).toBeNull();
    expect(timeProposalTooFar(far)).toEqual({ early: 3, late: 12 });
    const tooFar = new ApiError(409, { code: "TIME_WINDOW_CONFLICT", message: "x", details: { reason: "time_proposal_too_far", max_early_minutes: 120, max_late_minutes: 600 } });
    expect(timeProposalTooFar(tooFar)).toEqual({ early: 2, late: 10 });
    expect(timeProposalTooFar(err)).toBeNull();
  });

  it("tells no-road, duplicate and passed-pickup apart", () => {
    expect(isNoRoad(new ApiError(409, { code: "ROUTE_MISMATCH", message: "x" }))).toBe(true);
    expect(isDuplicateDirection(new ApiError(400, { code: "VALIDATION_ERROR", message: "x", details: { reason: "direction_exists" } }))).toBe(true);
    expect(isDuplicateDirection(new ApiError(400, { code: "VALIDATION_ERROR", message: "x", details: { reason: "district_required" } }))).toBe(false);
    expect(isPickupPassed(new ApiError(409, { code: "BOOKING_CUTOFF_PASSED", message: "x", details: { reason: "pickup_passed" } }))).toBe(true);
  });
});
