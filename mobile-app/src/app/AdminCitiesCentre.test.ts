import { describe, expect, it } from "vitest";

import { districtCentreValid, districtFormToPayload } from "./AdminCitiesPanel";

const base = { city_id: "4", name_uz: "Chilonzor", name_ru: "", display_order: "1000", is_active: true };

describe("district centre (Q160)", () => {
  it("accepts both fields or neither, in range", () => {
    expect(districtCentreValid({ center_lat: "", center_lng: "" })).toBe(true);
    expect(districtCentreValid({ center_lat: "41.2856", center_lng: "69.2034" })).toBe(true);
    expect(districtCentreValid({ center_lat: "41,2856", center_lng: "69,2034" })).toBe(true);
    expect(districtCentreValid({ center_lat: "41.28", center_lng: "" })).toBe(false);
    expect(districtCentreValid({ center_lat: "95", center_lng: "69" })).toBe(false);
    expect(districtCentreValid({ center_lat: "abc", center_lng: "69" })).toBe(false);
  });

  it("sends the centre only when both are filled, so an edit never clears it", () => {
    expect(districtFormToPayload({ ...base, center_lat: "41,2856", center_lng: "69.2034" })).toMatchObject({ center_lat: 41.2856, center_lng: 69.2034 });
    const payload = districtFormToPayload({ ...base, center_lat: "", center_lng: "" });
    expect("center_lat" in payload).toBe(false);
    expect("center_lng" in payload).toBe(false);
  });
});
