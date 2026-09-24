import { afterEach, describe, expect, it } from "vitest";

import type { TripIntentDTO, TripIntentFitDTO } from "../api/v2/tripIntents.api";
import {
  dayLabel,
  fitBlocks,
  fitNotes,
  intentSummary,
  isExpired,
  endInputFromDto,
  offersAffectedText,
  parcelComplete,
  parcelDiffers,
  pickActive,
  prefillBid,
  priceLine,
  readActiveIntentId,
  updateBody,
  writeActiveIntentId,
} from "./tripIntent";

const NOW = new Date("2026-09-24T06:00:00Z"); // 11:00 in Tashkent
const spaces = (text: string) => text.replace(/\s/g, " ");

function intent(overrides: Partial<TripIntentDTO["current_version"]> = {}, service: "passenger" | "parcel" = "passenger"): TripIntentDTO {
  return {
    id: "tin_synthetic",
    service_type: service,
    status: "active",
    version: 1,
    expired: false,
    current_version: {
      version_no: 1,
      terms_version: 1,
      origin: { stop: null, district: { id: "dst_a", name_uz: "Toshkent" }, lat: null, lng: null, address: null },
      destination: { stop: null, district: { id: "dst_b", name_uz: "Qarshi" }, lat: null, lng: null, address: null },
      window_start: "2026-09-25T07:00:00Z", // ertaga 12:00 Tashkent
      window_end: "2026-09-25T09:00:00Z", // 14:00
      quantity: service === "passenger" ? 3 : 1,
      price_basis: service === "passenger" ? "per_seat" : "total",
      unit_price_minor: service === "passenger" ? 19_000_000 : 3_000_000,
      total_minor: service === "passenger" ? 57_000_000 : 3_000_000,
      currency: "UZS",
      parcel: service === "parcel"
        ? { parcel_type: "box", weight_g: 2_500, length_cm: 30, width_cm: 20, height_cm: 10, receiver: { name: "Olim", phone: "+998900000999" } }
        : null,
      created_at: "2026-09-24T05:00:00Z",
      ...overrides,
    },
    booking_id: null,
    booking_cancelled: false,
    can_reopen: false,
    open_offers: 0,
    offers: [],
    created_at: "2026-09-24T05:00:00Z",
    updated_at: "2026-09-24T05:00:00Z",
  } as TripIntentDTO;
}

describe("saved trip request (ADR-0025)", () => {
  afterEach(() => localStorage.clear());

  it("reads as one short line with the Tashkent day, the window and the people", () => {
    expect(intentSummary(intent(), NOW)).toBe("Toshkent → Qarshi · ertaga 12:00–14:00 · 3 kishi");
    expect(dayLabel("2026-09-24T18:00:00Z", NOW)).toBe("bugun"); // 23:00 Tashkent is still today
    expect(dayLabel("2026-09-24T19:30:00Z", NOW)).toBe("ertaga"); // 00:30 Tashkent is tomorrow
  });

  it("fills three drivers' offers from the one request without typing it again", () => {
    const request = intent();
    const offers = [
      { price_basis: "per_seat", unit_price_minor: 18_000_000, service_type: "passenger" },
      { price_basis: "per_seat", unit_price_minor: 20_000_000, service_type: "passenger" },
      { price_basis: "total", unit_price_minor: 60_000_000, service_type: "passenger" },
    ];
    const filled = offers.map((offer) => prefillBid(request, offer));
    expect(filled.map((f) => f.seats)).toEqual([3, 3, 3]);
    // same unit: the client's own price; another unit: the driver's price, and the screen says so
    expect(filled.map((f) => [f.price, f.priceFromRequest])).toEqual([["190000", true], ["190000", true], ["600000", false]]);
    expect(filled.every((f) => f.weightKg === "" && f.receiverName === "")).toBe(true); // no parcel data on people
  });

  it("keeps passenger and parcel data apart", () => {
    const parcel = prefillBid(intent({}, "parcel"), { price_basis: "total", unit_price_minor: 5_000_000, service_type: "parcel" });
    expect(parcel).toMatchObject({ seats: 1, weightKg: "2.5", lengthCm: "30", widthCm: "20", heightCm: "10",
                                   receiverName: "Olim", receiverPhone: "+998900000999", price: "30000" });
    expect(intentSummary(intent({}, "parcel"), NOW).endsWith("1 jo'natma")).toBe(true);
  });

  it("says the unit: people x price per person = total, or that a price is the total", () => {
    expect(spaces(priceLine("per_seat", 19_000_000, 3))).toBe("3 kishi × 190 000 so'm = 570 000 so'm");
    expect(spaces(priceLine("total", 57_000_000, 3))).toBe("570 000 so'm (jami)");
  });

  it("reports an expired window instead of moving it", () => {
    const past = intent({ window_start: "2026-09-23T07:00:00Z", window_end: "2026-09-23T09:00:00Z" });
    expect(isExpired(past, NOW)).toBe(true);
    expect(past.current_version.window_start).toBe("2026-09-23T07:00:00Z");
    expect(isExpired(intent(), NOW)).toBe(false);
  });

  it("shows what does not match a driver's offer and blocks only what the server would refuse", () => {
    const fit = {
      listing_id: "lst_x", intent_version_no: 1, service_match: true, expired: false,
      time: { status: "outside", minutes_outside: 90 },
      availability: { status: "insufficient", requested: 3, available: 2 },
      origin: { status: "same_district" }, destination: { status: "same_stop" },
      price: { listing_price_basis: "per_seat", listing_unit_price_minor: 20_000_000, listing_total_minor: 60_000_000,
               quantity: 3, intent_price_basis: "per_seat", intent_unit_price_minor: 19_000_000, intent_total_minor: 57_000_000,
               currency: "UZS" },
      blockers: ["capacity_insufficient"],
    } as TripIntentFitDTO;
    expect(fitNotes(fit).map((n) => n.text)).toEqual([
      "Haydovchida 2 ta bo'sh o'rin bor, sizga 3 ta kerak.",
      "Haydovchi vaqti siz tanlagan oraliqdan 1 soat 30 daqiqa farq qiladi.",
      "Olib ketish joyi shu tumanda, lekin boshqa bekatda.",
    ]);
    expect(fitBlocks(fit)).toBe(true);
    expect(fitBlocks({ ...fit, blockers: [] })).toBe(false);
  });

  it("tells the client how many open offers an edit will close", () => {
    expect(offersAffectedText(2)).toContain("2 ta ochiq taklif yopiladi");
  });

  it("remembers the active request per signed-in person only", () => {
    writeActiveIntentId(7, "tin_a");
    expect(readActiveIntentId(7)).toBe("tin_a");
    expect(readActiveIntentId(8)).toBeNull(); // another account never sees it
    writeActiveIntentId(7, null);
    expect(readActiveIntentId(7)).toBeNull();
    expect(readActiveIntentId(null)).toBeNull();
  });

  it("sends a saved end back unchanged: a stop by id, a marked place by district and point", () => {
    const district = { id: "dst_a", name_uz: "T" };
    expect(endInputFromDto({ stop: { id: "stp_1", name_uz: "Bekat" } as never, district, lat: null, lng: null, address: null }))
      .toEqual({ stop_id: "stp_1" });
    expect(endInputFromDto({ stop: null, district, lat: 41.3, lng: 69.2, address: "Uy" }))
      .toEqual({ district_id: "dst_a", lat: 41.3, lng: 69.2, address: "Uy" });
  });

  it("builds an edit that keeps every saved field and changes only what was asked", () => {
    const body = updateBody(intent({}, "parcel"), { window_end: "2026-09-25T10:00:00Z" });
    expect(body).toMatchObject({
      expected_version: 1, acknowledge_open_offers: false, quantity: 1, price_basis: "total",
      unit_price_minor: 3_000_000, window_start: "2026-09-25T07:00:00Z", window_end: "2026-09-25T10:00:00Z",
    });
    expect(body.parcel).toMatchObject({ weight_g: 2_500, receiver: { name: "Olim", phone: "+998900000999" } });
    expect(updateBody(intent(), {}, true).acknowledge_open_offers).toBe(true);
  });

  it("knows when parcel data typed on an offer screen is new for the request", () => {
    const request = intent({}, "parcel");
    const same = { parcelType: "box", weightKg: "2.5", lengthCm: "30", widthCm: "20", heightCm: "10",
                   receiverName: "Olim", receiverPhone: "+998900000999" };
    expect(parcelComplete(request)).toBe(true);
    expect(parcelDiffers(request, same)).toBe(false);
    expect(parcelDiffers(request, { ...same, weightKg: "3" })).toBe(true);
    expect(parcelComplete(intent({ parcel: { parcel_type: "box" } } as never, "parcel"))).toBe(false);
  });

  it("keeps two independent requests apart and returns to the remembered one", () => {
    const a = { ...intent(), id: "tin_a" };
    const b = { ...intent(), id: "tin_b" };
    const closed = { ...intent(), id: "tin_c", status: "closed" } as TripIntentDTO;
    expect(pickActive([a, b], "tin_b")?.id).toBe("tin_b");
    expect(pickActive([a, b], "tin_gone")?.id).toBe("tin_a");
    expect(pickActive([closed], "tin_c")).toBeNull(); // a closed request is never shown as the active one
  });
});
