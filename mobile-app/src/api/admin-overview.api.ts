import { listAdminAuditLogs, listAdminDisputes, type AdminRecord } from "./admin.api";
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
  audits: AdminRecord[];
  warnings: string[];
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

async function guarded<T>(label: string, loader: () => Promise<T>, warnings: string[], fallback: T): Promise<T> {
  try {
    return await loader();
  } catch {
    warnings.push(`${label} data could not be loaded`);
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
  const warnings: string[] = [];
  const [ordersData, driversData, citiesData, districtsData, tariffsData, disputesData, auditsData] = await Promise.all([
    guarded("Orders", () => collectPages<AdminOrder>((page, limit) => getAdminOrders({ page, limit })), warnings, { items: [] }),
    guarded("Drivers", () => collectPages<AdminDriver>((page, limit) => getAdminDrivers({ page, limit })), warnings, { items: [] }),
    guarded("Cities", () => collectPages<City>((page, limit) => getAdminCities({ page, limit })), warnings, { items: [] }),
    guarded("Districts", () => collectPages<District>((page, limit) => getAdminDistricts({ page, limit })), warnings, { items: [] }),
    guarded("Tariffs", () => collectPages<RouteTariff>((page, limit) => getAdminTariffs({ page, limit })), warnings, { items: [] }),
    guarded("Disputes", () => collectPages<AdminRecord>((page, limit) => listAdminDisputes({ page, limit })), warnings, { items: [] }),
    guarded("Audit logs", () => listAdminAuditLogs({ limit: 20 }), warnings, { items: [] }),
  ]);

  const orders = ordersData.items ?? [];
  const drivers = driversData.items ?? [];
  const cities = citiesData.items ?? [];
  const districts = districtsData.items ?? [];
  const tariffs = tariffsData.items ?? [];
  const disputes = disputesData.items ?? [];
  const audits = auditsData.items ?? [];
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
    audits,
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
