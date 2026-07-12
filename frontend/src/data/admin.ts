import { getAdminOverview } from "../api/admin-overview.api";
import { getAdminOrders } from "../api/admin-orders.api";
import { getAdminDrivers } from "../api/admin-drivers.api";
import { getAdminClients } from "../api/admin-clients.api";
import { getAdminCities } from "../api/admin-cities.api";
import { getAdminTariffs } from "../api/admin-tariffs.api";
import { getAdminUsers } from "../api/admin-users.api";
import { listAdminDisputes, listAdminAuditLogs } from "../api/admin.api";
import { getAdminNotifications } from "../api/admin-notifications.api";
import { toNumber } from "./format";

export function adminDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const a = (o: unknown) => o as Record<string, any>;

/**
 * Coerce a person-ish value to a display string. The backend serializes actors/clients
 * as nested objects like {id, role, phone, full_name}; rendering one directly crashes React.
 * Returns "" when nothing usable is found so callers can apply their own default.
 */
function personText(...vals: unknown[]): string {
  for (const v of vals) {
    if (v == null || v === "") continue;
    if (typeof v === "string") return v;
    if (typeof v === "object") {
      const o = v as Record<string, any>;
      const s = o.full_name || o.phone || o.name;
      if (s) return String(s);
      continue;
    }
    return String(v);
  }
  return "";
}

export function mapOrderRow(raw: any) {
  return {
    id: raw.id,
    code: raw.order_number || `#${raw.id}`,
    from: raw.from_city?.name_uz || raw.from_city || "—",
    to: raw.to_city?.name_uz || raw.to_city || "—",
    client: personText(raw.client, raw.client_phone) || "—",
    driver: raw.assigned_driver?.full_name || "—",
    price: toNumber(raw.final_price ?? raw.suggested_price),
    status: raw.status,
    payment: raw.payment_status || "pending",
    date: adminDate(raw.created_at),
  };
}

export function mapDriverRow(raw: any) {
  return {
    id: raw.id,
    name: raw.user?.full_name || raw.full_name || "—",
    phone: raw.user?.phone || raw.phone || "—",
    car: raw.car_model || "—",
    color: raw.car_color || "—",
    plate: raw.plate_number || "—",
    status: raw.verification_status,
    avail: Boolean(raw.is_available),
    docs: raw.documents_count ?? 0,
    routes: raw.active_routes_count ?? raw.total_routes_count ?? 0,
    orders: raw.completed_orders ?? raw.total_orders ?? 0,
    rating: toNumber(raw.rating) || 0,
    created: adminDate(raw.created_at),
  };
}

export function mapClientRow(raw: any) {
  return {
    id: raw.id,
    name: raw.full_name || "—",
    phone: raw.phone,
    status: raw.status,
    verified: Boolean(raw.is_phone_verified),
    orders: raw.orders_count ?? 0,
    active: raw.active_orders_count ?? 0,
    last: adminDate(raw.last_order_at),
    created: adminDate(raw.created_at),
  };
}

export function mapRegionRow(raw: any) {
  return {
    id: raw.id,
    uz: raw.name_uz,
    ru: raw.name_ru || raw.name_uz,
    type: raw.type || "city",
    dist: Boolean(raw.requires_district),
    districts: raw.active_districts_count ?? raw.districts_count ?? 0,
    active: raw.is_active !== false,
  };
}

export function mapTariffRow(raw: any) {
  return {
    id: raw.id,
    from: raw.from_city?.name_uz || "—",
    to: raw.to_city?.name_uz || "—",
    suggested: toNumber(raw.suggested_price),
    min: toNumber(raw.min_price),
    max: toNumber(raw.max_price),
    currency: raw.currency || "UZS",
    active: raw.is_active !== false,
    created: adminDate(raw.created_at),
    from_city_id: raw.from_city_id,
    to_city_id: raw.to_city_id,
  };
}

export function mapDisputeRow(raw0: any) {
  const raw = a(raw0);
  return {
    id: Number(raw.id),
    orderId: raw.order_number || (raw.order_id ? `#${raw.order_id}` : "—"),
    reason: raw.reason || "—",
    status: raw.status || "open",
    openedBy: personText(raw.opened_by_name, raw.opened_by, raw.client_name) || "—",
    created: adminDate(raw.created_at),
    resolution: raw.resolution || raw.resolution_note || "",
  };
}

export function mapStaffRow(raw: any) {
  return {
    id: raw.id,
    name: raw.full_name || "—",
    phone: raw.phone,
    role: raw.role,
    status: raw.status,
    verified: Boolean(raw.is_phone_verified),
    created: adminDate(raw.created_at),
    lastLogin: adminDate(raw.last_login_at),
  };
}

export function mapAuditRow(raw0: any) {
  const raw = a(raw0);
  return {
    id: Number(raw.id),
    actor: personText(raw.actor_name, raw.actor, raw.user_name) || "system",
    role: raw.actor_role || raw.role || "system",
    action: raw.action || "—",
    entity: raw.entity_type || raw.entity || "—",
    entityId: raw.entity_id ?? "",
    created: adminDate(raw.created_at),
  };
}

export function mapNotifRow(raw: any) {
  return {
    id: raw.id,
    recipient: personText(raw.recipient, raw.recipient_name, raw.user) || "—",
    type: raw.type || "system",
    title: raw.title || "—",
    message: raw.message || "",
    channel: raw.channel || "push",
    read: Boolean(raw.is_read),
    date: adminDate(raw.created_at),
  };
}

export function overviewToMetrics(ov: any) {
  const f = ov?.finance ?? {};
  const s = ov?.stats ?? {};
  return {
    totalRevenue: f.totalOrderAmount ?? 0,
    platformProfit: f.systemProfit ?? 0,
    driverEarnings: f.driverIncome ?? 0,
    avgOrderValue: f.averageOrderAmount ?? 0,
    totalOrders: s.totalOrders ?? 0,
    publishedBidding: s.publishedOrders ?? 0,
    activeDeliveries: s.activeDeliveries ?? 0,
    deliveredToday: s.deliveredToday ?? 0,
    confirmed: s.confirmedOrders ?? 0,
    pendingDrivers: s.pendingDrivers ?? 0,
    approvedDrivers: s.approvedDrivers ?? 0,
    openDisputes: s.openDisputes ?? 0,
    activeCities: s.activeCities ?? 0,
    activeTariffs: s.activeTariffs ?? 0,
    missingTariffs: s.missingTariffs ?? 0,
    todayProfit: f.todaySystemProfit ?? 0,
  };
}

export {
  getAdminOverview, getAdminOrders, getAdminDrivers, getAdminClients,
  getAdminCities, getAdminTariffs, getAdminUsers, listAdminDisputes,
  listAdminAuditLogs, getAdminNotifications,
};
