/**
 * Bosh sahifa dashboard (DESIGN-V3-ADMIN-DIFF §2.2): pure numbers for the CSS charts, computed from what
 * `getAdminOverview` already loaded (every page of v1 orders and drivers). No request of its own.
 *
 * Money here is the *calculated* fare and the *calculated* system share of v1 orders; the fare is paid to the driver
 * and ELCHI does not collect it, so callers label it "hisoblangan, tushum emas" (AGENTS §9).
 *
 * Choices for the open designer questions (§99 Summary, 4 and 5):
 * - donut: Tasdiqlangan = `confirmed`; Bekor qilingan = `cancelled`; Nizoli = `disputed`; everything else
 *   (draft, published, bidding, accepted, picked_up, in_transit, delivered-but-not-confirmed) = Jarayonda.
 * - tile deltas: counts compare today with yesterday as a signed difference ("+3"); amounts compare as a ratio
 *   ("+4%"); the average order compares the last 7 days with the 7 before. "Faol yetkazmalar" is a snapshot, so it
 *   shows its count ("41 ta") instead of a delta.
 */
import type { AdminDriver } from "../types/admin-driver";
import type { AdminOrder } from "../types/admin-order";

/** Tashkent has no daylight saving: UTC+5 all year. */
const TASHKENT_OFFSET_MS = 5 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const DEFAULT_SYSTEM_FEE_RATE = 0.15;
const PRICED = new Set(["accepted", "picked_up", "in_transit", "delivered", "confirmed"]);
const ACTIVE = new Set(["accepted", "picked_up", "in_transit"]);

export type DashDelta = { text: string; trend: "up" | "down" | "flat" } | null;

export type DashTile = {
  id: "avgOrder" | "deliveredToday" | "activeDeliveries" | "todayShare";
  value: number;
  /** Seven values, oldest first; today is the last one. */
  spark: number[];
  delta: DashDelta;
  /** Only the snapshot tile: how many orders the amount covers. */
  count?: number;
};

export type OverviewDash = {
  /** Seven Tashkent days, oldest first; `weekday` 0 = Monday. */
  days: Array<{ weekday: number; amount: number }>;
  total7d: number;
  vsLastWeek: DashDelta;
  status: { confirmed: number; inProgress: number; cancelled: number; disputed: number; total: number };
  split: { system: number; drivers: number; total: number; systemPct: number };
  drivers: { approved: number; pending: number; rejected: number; blocked: number; total: number };
  tiles: DashTile[];
};

function num(value: number | string | null | undefined): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

/** Days since the Unix epoch, counted on the Tashkent calendar; `null` for a missing or broken date. */
export function tashkentDay(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return null;
  return Math.floor((time + TASHKENT_OFFSET_MS) / DAY_MS);
}

function incomeOf(order: AdminOrder) {
  const total = num(order.final_price);
  const system = order.system_fee !== undefined && order.system_fee !== null
    ? num(order.system_fee)
    : total * num(order.system_fee_rate ?? DEFAULT_SYSTEM_FEE_RATE);
  const drivers = order.driver_income !== undefined && order.driver_income !== null ? num(order.driver_income) : Math.max(total - system, 0);
  return { total, system, drivers };
}

function isPriced(order: AdminOrder): boolean {
  return PRICED.has(order.status) && num(order.final_price) > 0;
}

/** Signed count difference: "+3", "−2", "0". */
export function countDelta(current: number, previous: number): DashDelta {
  const diff = current - previous;
  return { text: diff > 0 ? `+${diff}` : diff < 0 ? `−${Math.abs(diff)}` : "0", trend: diff > 0 ? "up" : diff < 0 ? "down" : "flat" };
}

/** Ratio difference: "+12%", "−4%"; `null` when there is nothing to compare with. */
export function ratioDelta(current: number, previous: number): DashDelta {
  if (!previous) return null;
  const pct = Math.round(((current - previous) / previous) * 100);
  return { text: pct > 0 ? `+${pct}%` : pct < 0 ? `−${Math.abs(pct)}%` : "0%", trend: pct > 0 ? "up" : pct < 0 ? "down" : "flat" };
}

function series(today: number, length: number, pick: (day: number) => number): number[] {
  return Array.from({ length }, (_, index) => pick(today - (length - 1 - index)));
}

export function buildOverviewDash(orders: AdminOrder[], drivers: AdminDriver[], now: Date = new Date()): OverviewDash {
  const today = Math.floor((now.getTime() + TASHKENT_OFFSET_MS) / DAY_MS);
  const priced = orders.filter(isPriced);

  // Amount per created day (the fare is calculated, not collected).
  const amountByDay = new Map<number, number>();
  const pricedCountByDay = new Map<number, number>();
  for (const order of priced) {
    const day = tashkentDay(order.created_at);
    if (day === null) continue;
    amountByDay.set(day, (amountByDay.get(day) ?? 0) + incomeOf(order).total);
    pricedCountByDay.set(day, (pricedCountByDay.get(day) ?? 0) + 1);
  }
  const amounts14 = series(today, 14, (day) => amountByDay.get(day) ?? 0);
  const last7 = amounts14.slice(7);
  const prev7 = amounts14.slice(0, 7);
  const total7d = last7.reduce((a, b) => a + b, 0);
  const prevTotal = prev7.reduce((a, b) => a + b, 0);
  // 1970-01-01 was a Thursday (Monday-based index 3).
  const days = last7.map((amount, index) => ({ weekday: (today - 6 + index + 3) % 7, amount }));

  const status = { confirmed: 0, inProgress: 0, cancelled: 0, disputed: 0, total: orders.length };
  for (const order of orders) {
    if (order.status === "confirmed") status.confirmed += 1;
    else if (order.status === "cancelled") status.cancelled += 1;
    else if (order.status === "disputed") status.disputed += 1;
    else status.inProgress += 1;
  }

  let system = 0;
  let toDrivers = 0;
  let pricedTotal = 0;
  for (const order of priced) {
    const income = incomeOf(order);
    system += income.system;
    toDrivers += income.drivers;
    pricedTotal += income.total;
  }

  const driverGroups = { approved: 0, pending: 0, rejected: 0, blocked: 0, total: drivers.length };
  for (const driver of drivers) {
    if (driver.verification_status === "approved") driverGroups.approved += 1;
    else if (driver.verification_status === "rejected") driverGroups.rejected += 1;
    else if (driver.verification_status === "blocked") driverGroups.blocked += 1;
    else driverGroups.pending += 1;
  }

  // Tiles.
  const avgSpark = series(today, 7, (day) => {
    const count = pricedCountByDay.get(day) ?? 0;
    return count ? (amountByDay.get(day) ?? 0) / count : 0;
  });
  const avg = (from: number, to: number) => {
    let amount = 0;
    let count = 0;
    for (let day = from; day <= to; day += 1) {
      amount += amountByDay.get(day) ?? 0;
      count += pricedCountByDay.get(day) ?? 0;
    }
    return count ? amount / count : 0;
  };

  const deliveredByDay = new Map<number, number>();
  for (const order of orders) {
    if (!order.delivered_at || !["delivered", "confirmed"].includes(order.status)) continue;
    const day = tashkentDay(order.delivered_at);
    if (day !== null) deliveredByDay.set(day, (deliveredByDay.get(day) ?? 0) + 1);
  }
  const deliveredSpark = series(today, 7, (day) => deliveredByDay.get(day) ?? 0);

  const active = priced.filter((order) => ACTIVE.has(order.status));
  const activeByDay = new Map<number, number>();
  for (const order of active) {
    const day = tashkentDay(order.created_at);
    if (day !== null) activeByDay.set(day, (activeByDay.get(day) ?? 0) + incomeOf(order).total);
  }

  const shareByDay = new Map<number, number>();
  for (const order of priced) {
    const day = tashkentDay(order.confirmed_at ?? order.delivered_at ?? order.updated_at ?? order.created_at);
    if (day !== null) shareByDay.set(day, (shareByDay.get(day) ?? 0) + incomeOf(order).system);
  }
  const shareSpark = series(today, 7, (day) => shareByDay.get(day) ?? 0);

  const tiles: DashTile[] = [
    { id: "avgOrder", value: priced.length ? pricedTotal / priced.length : 0, spark: avgSpark, delta: ratioDelta(avg(today - 6, today), avg(today - 13, today - 7)) },
    { id: "deliveredToday", value: deliveredSpark[6], spark: deliveredSpark, delta: countDelta(deliveredSpark[6], deliveredSpark[5]) },
    {
      id: "activeDeliveries",
      value: active.reduce((sum, order) => sum + incomeOf(order).total, 0),
      spark: series(today, 7, (day) => activeByDay.get(day) ?? 0),
      delta: null,
      count: active.length,
    },
    { id: "todayShare", value: shareSpark[6], spark: shareSpark, delta: ratioDelta(shareSpark[6], shareSpark[5]) },
  ];

  return {
    days,
    total7d,
    vsLastWeek: ratioDelta(total7d, prevTotal),
    status,
    split: { system, drivers: toDrivers, total: pricedTotal, systemPct: pricedTotal ? (system / pricedTotal) * 100 : 0 },
    drivers: driverGroups,
    tiles,
  };
}

/** "1.4" (millions, one decimal) for the bar labels under the "mln so'm" caption. */
export function millions(amount: number): string {
  const value = amount / 1_000_000;
  return value >= 10 ? value.toFixed(0) : value.toFixed(1);
}
