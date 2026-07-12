import { useCallback, useEffect, useState } from "react";
import {
  getDriverProfile, getDriverRoutes, getDriverFeed, getDriverOrders,
} from "../api/driver.api";
import { getUzbekErrorMessage } from "../utils/errors";
import { cityName, districtName, toNumber, shortDate, routeUiStatus, driverUiStatus } from "./format";
import type { DriverFeedOrder, DriverProfile } from "../types/driver";

export type UiDriverData = {
  name: string;
  phone: string;
  status: "approved" | "pending" | "new";
  available: boolean;
  rating: number;
  completedOrders: number;
  totalOrders: number;
  disputes: number;
  car: { model: string; color: string; plate: string };
  netIncome: number;
};

export type UiRoute = {
  id: number;
  from: string; fromDistrict: string;
  to: string; toDistrict: string;
  status: "active" | "inactive";
  from_city_id?: number; to_city_id?: number;
};

export type UiFeedOrder = {
  id: number; code: string; from: string; to: string; status: string;
  price: number; pickup: string; dropoff: string; date: string;
  hasBid: boolean; bidId?: number; bidPrice?: number; bidUpdatesLeft?: number;
};

export type UiActiveOrder = {
  id: number; code: string; from: string; to: string; status: string;
  gross: number; commission: number; net: number;
  pickup: string; dropoff: string; sender: string; receiver: string;
  comment: string; date: string; cargoType: string;
  pickupLat: number | string | null; pickupLng: number | string | null;
  dropoffLat: number | string | null; dropoffLng: number | string | null;
};

export type UiEarning = { id: number; code: string; from: string; to: string; date: string; net: number };

const lang = "uz";

function mapFeedOrder(o: DriverFeedOrder): UiFeedOrder {
  const myBid = (o.my_bid ?? null) as { id?: number; price?: number; price_updates_left?: number } | null;
  return {
    id: o.id,
    code: o.order_number ?? `#${o.id}`,
    from: cityName(o.from_city as never, lang),
    to: cityName(o.to_city as never, lang),
    status: o.status,
    price: toNumber(o.client_price ?? o.suggested_price ?? o.final_price),
    pickup: o.pickup_area || districtName(o.from_district as never, lang) || "",
    dropoff: o.dropoff_area || districtName(o.to_district as never, lang) || "",
    date: shortDate(o.created_at),
    hasBid: Boolean(myBid),
    bidId: myBid?.id,
    bidPrice: myBid?.price !== undefined ? toNumber(myBid.price) : undefined,
    bidUpdatesLeft: myBid?.price_updates_left,
  };
}

function mapActiveOrder(o: Record<string, unknown>): UiActiveOrder {
  const gross = toNumber((o.gross_income ?? o.final_price) as never);
  const net = toNumber((o.driver_income ?? null) as never) || gross;
  const fee = toNumber((o.system_fee ?? null) as never) || Math.max(gross - net, 0);
  return {
    id: Number(o.id),
    code: (o.order_number as string) ?? `#${o.id}`,
    from: cityName(o.from_city as never, lang),
    to: cityName(o.to_city as never, lang),
    status: (o.status as string) ?? "accepted",
    gross, commission: fee, net,
    pickup: (o.pickup_address as string) || "",
    dropoff: (o.dropoff_address as string) || "",
    sender: (o.sender_phone as string) || "",
    receiver: (o.receiver_phone as string) || "",
    comment: (o.comment as string) || "",
    date: shortDate(o.created_at as string),
    cargoType: (o.cargo_type as string) || "",
    pickupLat: (o.pickup_lat as never) ?? null,
    pickupLng: (o.pickup_lng as never) ?? null,
    dropoffLat: (o.dropoff_lat as never) ?? null,
    dropoffLng: (o.dropoff_lng as never) ?? null,
  };
}

const COMPLETED = new Set(["delivered", "confirmed"]);
const ACTIVE_ASSIGNED = new Set(["accepted", "picked_up", "in_transit", "delivered"]);

export function useDriverData() {
  const [profile, setProfile] = useState<DriverProfile | null>(null);
  const [routes, setRoutes] = useState<UiRoute[]>([]);
  const [feed, setFeed] = useState<UiFeedOrder[]>([]);
  const [assigned, setAssigned] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [profileRes, routesRes, feedRes, ordersRes] = await Promise.all([
        getDriverProfile(),
        getDriverRoutes().catch(() => []),
        getDriverFeed({ limit: 50 }).catch(() => ({ items: [] })),
        getDriverOrders({ limit: 50 }).catch(() => ({ items: [] })),
      ]);
      setProfile(profileRes);
      setRoutes(
        (routesRes as Record<string, unknown>[]).map((r) => ({
          id: Number(r.id),
          from: cityName(r.from_city as never, lang),
          fromDistrict: districtName(r.from_district as never, lang),
          to: cityName(r.to_city as never, lang),
          toDistrict: districtName(r.to_district as never, lang),
          status: routeUiStatus(r.status as string),
          from_city_id: (r.from_city as { id?: number } | null)?.id,
          to_city_id: (r.to_city as { id?: number } | null)?.id,
        })),
      );
      setFeed((feedRes.items ?? []).map(mapFeedOrder));
      setAssigned((ordersRes.items ?? []) as Record<string, unknown>[]);
    } catch (err) {
      setError(getUzbekErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const assignedUi = assigned.map(mapActiveOrder);
  const completed = assignedUi.filter((o) => COMPLETED.has(o.status));
  const netIncome = completed.reduce((sum, o) => sum + o.net, 0);
  const activeOrder = assignedUi.find((o) => ACTIVE_ASSIGNED.has(o.status)) ?? assignedUi[0] ?? null;
  const recentEarnings: UiEarning[] = completed
    .slice(0, 6)
    .map((o) => ({ id: o.id, code: o.code, from: o.from, to: o.to, date: o.date, net: o.net }));

  const driverData: UiDriverData = {
    name: profile?.user?.full_name || profile?.full_name || "Haydovchi",
    phone: profile?.user?.phone || "",
    status: driverUiStatus(profile?.verification_status),
    available: Boolean(profile?.is_available),
    rating: toNumber(profile?.rating) || 0,
    completedOrders: profile?.completed_orders ?? 0,
    totalOrders: profile?.total_orders ?? 0,
    disputes: profile?.dispute_count ?? 0,
    car: {
      model: profile?.car_model || "—",
      color: profile?.car_color || "—",
      plate: profile?.plate_number || "—",
    },
    netIncome,
  };

  return { driverData, profile, routes, feed, activeOrder, recentEarnings, netIncome, loading, error, reload: load, setRoutes, setFeed };
}
