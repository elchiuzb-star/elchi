import { describe, expect, it } from "vitest";

import type { AdminDriver } from "../types/admin-driver";
import type { AdminOrder } from "../types/admin-order";
import { buildOverviewDash, countDelta, millions, ratioDelta, tashkentDay } from "./overviewDash";

// 2026-10-07 10:00 Tashkent (05:00 UTC), a Wednesday.
const NOW = new Date("2026-10-07T05:00:00Z");

function order(partial: Partial<AdminOrder> & { status: string }): AdminOrder {
  return { id: Math.floor(Math.random() * 1e9), final_price: 0, ...partial } as unknown as AdminOrder;
}

function driver(verification_status: AdminDriver["verification_status"]): AdminDriver {
  return { id: Math.floor(Math.random() * 1e9), verification_status, is_available: true } as AdminDriver;
}

describe("tashkentDay", () => {
  it("counts the day on the Tashkent calendar, not UTC", () => {
    // 20:00 UTC on the 6th is already 01:00 on the 7th in Tashkent.
    expect(tashkentDay("2026-10-06T20:00:00Z")).toBe(tashkentDay("2026-10-07T05:00:00Z"));
    expect(tashkentDay("2026-10-06T18:00:00Z")).toBe((tashkentDay("2026-10-07T05:00:00Z") ?? 0) - 1);
    expect(tashkentDay(null)).toBeNull();
    expect(tashkentDay("not a date")).toBeNull();
  });
});

describe("deltas", () => {
  it("count deltas are signed differences", () => {
    expect(countDelta(5, 2)).toEqual({ text: "+3", trend: "up" });
    expect(countDelta(1, 3)).toEqual({ text: "−2", trend: "down" });
    expect(countDelta(2, 2)).toEqual({ text: "0", trend: "flat" });
  });
  it("ratio deltas are percentages and absent with nothing to compare", () => {
    expect(ratioDelta(112, 100)).toEqual({ text: "+12%", trend: "up" });
    expect(ratioDelta(96, 100)).toEqual({ text: "−4%", trend: "down" });
    expect(ratioDelta(10, 0)).toBeNull();
  });
  it("millions keep one decimal under 10", () => {
    expect(millions(1_450_000)).toBe("1.4");
    expect(millions(12_600_000)).toBe("13");
  });
});

describe("buildOverviewDash", () => {
  const orders: AdminOrder[] = [
    // this week (priced)
    order({ status: "confirmed", final_price: 1_000_000, system_fee: 100_000, created_at: "2026-10-07T03:00:00Z", delivered_at: "2026-10-07T04:00:00Z" }),
    order({ status: "in_transit", final_price: 500_000, created_at: "2026-10-06T08:00:00Z" }),
    order({ status: "delivered", final_price: 300_000, created_at: "2026-10-01T08:00:00Z", delivered_at: "2026-10-06T08:00:00Z" }),
    // last week (priced)
    order({ status: "confirmed", final_price: 1_500_000, created_at: "2026-09-28T08:00:00Z" }),
    // not priced
    order({ status: "bidding", created_at: "2026-10-07T03:00:00Z" }),
    order({ status: "draft", created_at: "2026-10-07T03:00:00Z" }),
    order({ status: "cancelled", final_price: 900_000, created_at: "2026-10-05T03:00:00Z" }),
    order({ status: "disputed", created_at: "2026-10-05T03:00:00Z" }),
  ];
  const drivers = [driver("approved"), driver("approved"), driver("new"), driver("pending"), driver("rejected"), driver("blocked")];
  const dash = buildOverviewDash(orders, drivers, NOW);

  it("buckets seven Tashkent days ending today, Monday-based", () => {
    expect(dash.days).toHaveLength(7);
    expect(dash.days[6]).toEqual({ weekday: 2, amount: 1_000_000 }); // Wednesday
    expect(dash.days[5]).toEqual({ weekday: 1, amount: 500_000 });
    expect(dash.days[0].amount).toBe(300_000); // Thursday 1 Oct
    expect(dash.total7d).toBe(1_800_000);
  });

  it("compares the week with the previous 7 days", () => {
    expect(dash.vsLastWeek).toEqual({ text: "+20%", trend: "up" });
  });

  it("groups v1 statuses for the donut", () => {
    expect(dash.status).toEqual({ confirmed: 2, inProgress: 4, cancelled: 1, disputed: 1, total: 8 });
  });

  it("splits the calculated amount between system and drivers", () => {
    // 100k explicit + 15% default of 500k, 300k, 1.5m
    expect(dash.split.system).toBe(100_000 + 75_000 + 45_000 + 225_000);
    expect(dash.split.total).toBe(3_300_000);
    expect(dash.split.drivers).toBe(3_300_000 - dash.split.system);
  });

  it("groups drivers by verification", () => {
    expect(dash.drivers).toEqual({ approved: 2, pending: 2, rejected: 1, blocked: 1, total: 6 });
  });

  it("builds four tiles with seven-bar sparklines", () => {
    const byId = Object.fromEntries(dash.tiles.map((tile) => [tile.id, tile]));
    expect(dash.tiles.every((tile) => tile.spark.length === 7)).toBe(true);
    expect(byId.deliveredToday.value).toBe(1);
    expect(byId.deliveredToday.delta).toEqual({ text: "0", trend: "flat" });
    expect(byId.activeDeliveries.count).toBe(1);
    expect(byId.activeDeliveries.value).toBe(500_000);
    expect(byId.activeDeliveries.delta).toBeNull();
    expect(byId.todayShare.value).toBe(100_000);
  });

  it("is empty-safe", () => {
    const empty = buildOverviewDash([], [], NOW);
    expect(empty.total7d).toBe(0);
    expect(empty.vsLastWeek).toBeNull();
    expect(empty.split.systemPct).toBe(0);
  });
});
