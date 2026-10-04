import { listAdminDisputes, opsQueueSummary, type AdminRecord, type OpsQueueCount } from "./admin.api";
import { opsQueue, type OpsQueue } from "./v2/ops.api";
import { listFraudSignals, listSupportThreadsAdmin } from "./v2/admin-trust.api";
import { financeReport, type FinanceReportName } from "./v2/admin-finance.api";
import { ApiError } from "../types/api";
import type { MessageKey } from "../i18n";
import { getAdminCities } from "./admin-cities.api";
import { getAdminDistricts } from "./admin-districts.api";
import { getAdminDrivers } from "./admin-drivers.api";
import { getAdminOrders } from "./admin-orders.api";
import { getAdminTariffs } from "./admin-tariffs.api";
import type { AdminDriver } from "../types/admin-driver";
import type { AdminOrder } from "../types/admin-order";
import type { Paginated } from "../types/api";
import type { City } from "../types/city";
import type { District } from "../types/district";
import type { RouteTariff } from "../types/tariff";

export type AdminOverviewData = {
  orders: AdminOrder[];
  drivers: AdminDriver[];
  cities: City[];
  districts: District[];
  tariffs: RouteTariff[];
  disputes: AdminRecord[];
  /** Sources that could not be read, as dictionary keys (the panel says them in the reader's language). */
  warnings: MessageKey[];
  finance: {
    pricedOrders: number;
    completedOrders: number;
    activePricedOrders: number;
    totalOrderAmount: number;
    systemProfit: number;
    driverIncome: number;
    completedOrderAmount: number;
    completedSystemProfit: number;
    completedDriverIncome: number;
    activeOrderAmount: number;
    activeSystemProfit: number;
    todayOrderAmount: number;
    todaySystemProfit: number;
    averageOrderAmount: number;
    averageSystemProfit: number;
  };
  stats: {
    totalOrders: number;
    publishedOrders: number;
    activeDeliveries: number;
    deliveredToday: number;
    confirmedOrders: number;
    pendingDrivers: number;
    approvedDrivers: number;
    openDisputes: number;
    activeCities: number;
    districtIssues: number;
    activeTariffs: number;
    missingTariffs: number;
  };
};

const DEFAULT_SYSTEM_FEE_RATE = 0.15;
const PRICED_STATUSES = new Set(["accepted", "picked_up", "in_transit", "delivered", "confirmed"]);
const COMPLETED_STATUSES = new Set(["delivered", "confirmed"]);
const ACTIVE_PRICED_STATUSES = new Set(["accepted", "picked_up", "in_transit"]);

function moneyNumber(value: number | string | null | undefined): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

async function guarded<T>(label: MessageKey, loader: () => Promise<T>, warnings: MessageKey[], fallback: T): Promise<T> {
  try {
    return await loader();
  } catch {
    warnings.push(label);
    return fallback;
  }
}

async function collectPages<T>(loader: (page: number, limit: number) => Promise<Paginated<T>>, limit = 100): Promise<Paginated<T>> {
  const firstPage = await loader(1, limit);
  const items = [...(firstPage.items ?? [])];
  const totalPages = firstPage.pagination?.total_pages ?? 1;

  for (let page = 2; page <= totalPages; page += 1) {
    const nextPage = await loader(page, limit);
    items.push(...(nextPage.items ?? []));
  }

  return {
    items,
    pagination: {
      page: 1,
      limit,
      total: firstPage.pagination?.total ?? items.length,
      total_pages: totalPages,
    },
  };
}

function isToday(value?: string | null): boolean {
  if (!value) return false;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
}

export async function getAdminOverview(): Promise<AdminOverviewData> {
  const warnings: MessageKey[] = [];
  const [ordersData, driversData, citiesData, districtsData, tariffsData, disputesData] = await Promise.all([
    guarded("admin.overview.src.orders", () => collectPages<AdminOrder>((page, limit) => getAdminOrders({ page, limit })), warnings, { items: [] }),
    guarded("admin.overview.src.drivers", () => collectPages<AdminDriver>((page, limit) => getAdminDrivers({ page, limit })), warnings, { items: [] }),
    guarded("admin.overview.src.cities", () => collectPages<City>((page, limit) => getAdminCities({ page, limit })), warnings, { items: [] }),
    guarded("admin.overview.src.districts", () => collectPages<District>((page, limit) => getAdminDistricts({ page, limit })), warnings, { items: [] }),
    guarded("admin.overview.src.tariffs", () => collectPages<RouteTariff>((page, limit) => getAdminTariffs({ page, limit })), warnings, { items: [] }),
    guarded("admin.overview.src.disputes", () => collectPages<AdminRecord>((page, limit) => listAdminDisputes({ page, limit })), warnings, { items: [] }),
  ]);

  const orders = ordersData.items ?? [];
  const drivers = driversData.items ?? [];
  const cities = citiesData.items ?? [];
  const districts = districtsData.items ?? [];
  const tariffs = tariffsData.items ?? [];
  const disputes = disputesData.items ?? [];
  const activeCityIds = cities.filter((city) => city.is_active !== false).map((city) => city.id);
  const activeTariffs = tariffs.filter((tariff) => tariff.is_active !== false);
  const tariffKeys = new Set(activeTariffs.map((tariff) => `${tariff.from_city_id}:${tariff.to_city_id}`));
  let missingTariffs = 0;
  activeCityIds.forEach((fromId) => {
    activeCityIds.forEach((toId) => {
      if (fromId !== toId && !tariffKeys.has(`${fromId}:${toId}`)) missingTariffs += 1;
    });
  });

  const districtIssues = cities.filter(
    (city) => city.is_active !== false && city.requires_district && (city.active_districts_count ?? city.districts_count ?? 0) === 0,
  ).length;
  const pricedOrders = orders.filter((order) => PRICED_STATUSES.has(order.status) && moneyNumber(order.final_price) > 0);
  const completedOrders = pricedOrders.filter((order) => COMPLETED_STATUSES.has(order.status));
  const activePricedOrders = pricedOrders.filter((order) => ACTIVE_PRICED_STATUSES.has(order.status));
  const todayPricedOrders = pricedOrders.filter((order) => isToday(order.confirmed_at ?? order.delivered_at ?? order.updated_at ?? order.created_at));
  const incomeOf = (order: AdminOrder) => {
    const total = moneyNumber(order.final_price);
    const systemFee = order.system_fee !== undefined && order.system_fee !== null
      ? moneyNumber(order.system_fee)
      : total * moneyNumber(order.system_fee_rate ?? DEFAULT_SYSTEM_FEE_RATE);
    const driverIncome = order.driver_income !== undefined && order.driver_income !== null
      ? moneyNumber(order.driver_income)
      : Math.max(total - systemFee, 0);
    return { total, systemFee, driverIncome };
  };
  const sum = (items: AdminOrder[], selector: (income: ReturnType<typeof incomeOf>) => number) => items.reduce((total, order) => total + selector(incomeOf(order)), 0);
  const totalOrderAmount = sum(pricedOrders, (income) => income.total);
  const systemProfit = sum(pricedOrders, (income) => income.systemFee);
  const driverIncome = sum(pricedOrders, (income) => income.driverIncome);
  const completedOrderAmount = sum(completedOrders, (income) => income.total);
  const completedSystemProfit = sum(completedOrders, (income) => income.systemFee);

  return {
    orders,
    drivers,
    cities,
    districts,
    tariffs,
    disputes,
    warnings,
    finance: {
      pricedOrders: pricedOrders.length,
      completedOrders: completedOrders.length,
      activePricedOrders: activePricedOrders.length,
      totalOrderAmount,
      systemProfit,
      driverIncome,
      completedOrderAmount,
      completedSystemProfit,
      completedDriverIncome: sum(completedOrders, (income) => income.driverIncome),
      activeOrderAmount: sum(activePricedOrders, (income) => income.total),
      activeSystemProfit: sum(activePricedOrders, (income) => income.systemFee),
      todayOrderAmount: sum(todayPricedOrders, (income) => income.total),
      todaySystemProfit: sum(todayPricedOrders, (income) => income.systemFee),
      averageOrderAmount: pricedOrders.length ? totalOrderAmount / pricedOrders.length : 0,
      averageSystemProfit: pricedOrders.length ? systemProfit / pricedOrders.length : 0,
    },
    stats: {
      totalOrders: orders.length,
      publishedOrders: orders.filter((order) => ["published", "bidding"].includes(order.status)).length,
      activeDeliveries: orders.filter((order) => ["accepted", "picked_up", "in_transit"].includes(order.status)).length,
      deliveredToday: orders.filter((order) => order.status === "delivered" && isToday(order.delivered_at ?? order.updated_at)).length,
      confirmedOrders: orders.filter((order) => order.status === "confirmed").length,
      pendingDrivers: drivers.filter((driver) => ["new", "pending"].includes(driver.verification_status)).length,
      approvedDrivers: drivers.filter((driver) => driver.verification_status === "approved").length,
      openDisputes: disputes.filter((dispute) => !["resolved", "closed", "cancelled"].includes(String(dispute.status ?? ""))).length,
      activeCities: cities.filter((city) => city.is_active !== false).length,
      districtIssues,
      activeTariffs: activeTariffs.length,
      missingTariffs,
    },
  };
}


// --- v2 queue tiles (DESIGN-ADMIN-DIFF §3.4/§3.5) ------------------------------------------------------------------

export type V2TileId = "finance_review" | "no_show_review" | "fraud" | "support_threads" | "disputes";

/** A count the panel can show honestly: `capped` means "at least `count`" (shown as "50+"). */
export type V2TileCount = { count: number; capped: boolean };

export type V2QueueCounts = Partial<Record<V2TileId, V2TileCount>>;

/** Page size used when a queue has to be counted by reading it (no summary endpoint yet). */
export const QUEUE_COUNT_PAGE = 50;

function counted(items: unknown[], limit = QUEUE_COUNT_PAGE): V2TileCount {
  return { count: items.length, capped: items.length >= limit };
}

/** A refusal (403) or a missing route (404) hides the tile; anything else is a real failure worth a warning. */
function isHidden(error: unknown): boolean {
  return error instanceof ApiError && [401, 403, 404, 405].includes(error.status);
}

/**
 * The v2 tiles a role may read. Finance reads only the money queue (`finance_review`); the trust tiles need
 * `ops.view` + trust capabilities that finance does not hold, so they are not even asked for.
 *
 * Counts come from `GET /admin/ops/queues/summary` (ADMIN-BACKEND-CONTRACT §4.1) when it exists, and otherwise
 * from reading up to {@link QUEUE_COUNT_PAGE} items - capped counts are flagged, never shown as exact.
 */
export async function getV2QueueCounts(role: string): Promise<{ counts: V2QueueCounts; failed: boolean }> {
  const financeOnly = role === "finance";
  const counts: V2QueueCounts = {};
  let failed = false;
  let summary: OpsQueueCount[] | null = null;
  try {
    summary = await opsQueueSummary();
  } catch {
    summary = null; // older backend: fall back to reading the queues
  }
  const fromSummary = (queue: string): V2TileCount | undefined => {
    const row = summary?.find((item) => item.queue === queue);
    return row ? { count: row.capped ? row.cap : row.count, capped: row.capped } : undefined;
  };
  const queueCount = async (queue: OpsQueue): Promise<V2TileCount> =>
    fromSummary(queue) ?? counted(await opsQueue(queue, { limit: QUEUE_COUNT_PAGE }));

  const jobs: Array<[V2TileId, () => Promise<V2TileCount>]> = [["finance_review", () => queueCount("finance_review")]];
  if (!financeOnly) {
    jobs.push(
      ["no_show_review", () => queueCount("no_show_review")],
      ["fraud", async () => counted(await listFraudSignals({ status: "open", limit: QUEUE_COUNT_PAGE }))],
      ["support_threads", async () =>
        fromSummary("support_thread") ?? counted(await listSupportThreadsAdmin({ status: "open", assigned: "unassigned", limit: QUEUE_COUNT_PAGE }))],
      ["disputes", () => queueCount("dispute")],
    );
  }
  const settled = await Promise.allSettled(jobs.map(([, job]) => job()));
  settled.forEach((result, index) => {
    const id = jobs[index][0];
    if (result.status === "fulfilled") counts[id] = result.value;
    else if (!isHidden(result.reason)) failed = true;
  });
  return { counts, failed };
}

export function formatTileCount(tile: V2TileCount | undefined): string {
  if (!tile) return "-";
  return tile.capped ? `${tile.count}+` : String(tile.count);
}

// --- finance money tiles (contract §1.2: finance reads v2 reports, never v1 orders) --------------------------------

export type FinanceMoneyTile = { report: FinanceReportName; amountMinor: number; count: number; todayMinor: number };

export const FINANCE_OVERVIEW_REPORTS: FinanceReportName[] = ["calculated_commission", "commission_revenue", "cash_inflows", "reversals"];
export const FINANCE_OVERVIEW_DAYS = 30;

/** `YYYY-MM-DD` of a moment in Tashkent, the zone the reports bucket days in. */
export function tashkentDay(moment: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit" }).format(moment);
}

/**
 * The last {@link FINANCE_OVERVIEW_DAYS} days of the v2 money reports, with today's figure from the same rows. A
 * report the server cannot produce (403/404/503) is left out rather than shown as zero - zero would be a claim.
 */
export async function getFinanceMoney(now = new Date()): Promise<{ tiles: FinanceMoneyTile[]; from: string; to: string }> {
  const to = tashkentDay(now);
  const from = tashkentDay(new Date(now.getTime() - (FINANCE_OVERVIEW_DAYS - 1) * 86_400_000));
  const settled = await Promise.allSettled(FINANCE_OVERVIEW_REPORTS.map((report) => financeReport(report, { from, to })));
  const tiles: FinanceMoneyTile[] = [];
  settled.forEach((result, index) => {
    if (result.status !== "fulfilled") return;
    const dto = result.value;
    tiles.push({
      report: FINANCE_OVERVIEW_REPORTS[index],
      amountMinor: dto.totals.amount_minor,
      count: dto.totals.count,
      todayMinor: dto.rows.filter((row) => row.date === to).reduce((sum, row) => sum + row.amount_minor, 0),
    });
  });
  return { tiles, from, to };
}
