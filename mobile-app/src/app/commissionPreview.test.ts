import { describe, expect, it } from "vitest";

import { bidTotalMinor, bpsPercent } from "./commissionPreview";

describe("bidTotalMinor (marketplace.rules.compute_total_minor)", () => {
  it("multiplies a per-seat price by the seats", () => {
    expect(bidTotalMinor("per_seat", 15_000_000, 3)).toBe(45_000_000);
  });

  it("takes a total price as the whole price", () => {
    expect(bidTotalMinor("total", 20_000_000, 1)).toBe(20_000_000);
  });

  it("quotes nothing for an empty or broken input", () => {
    expect(bidTotalMinor("per_seat", 0, 2)).toBe(0);
    expect(bidTotalMinor("per_seat", 100, 0)).toBe(0);
    expect(bidTotalMinor("total", 1.5, 1)).toBe(0);
  });
});

describe("bpsPercent", () => {
  it("writes basis points as a percentage", () => {
    expect(bpsPercent(1000)).toBe("10");
    expect(bpsPercent(750)).toBe("7.5");
    expect(bpsPercent(0)).toBe("0");
  });
});
