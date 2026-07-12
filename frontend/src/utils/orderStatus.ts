import type { OrderStatus } from "../types/order";

export const adminOrderStatusLabels: Record<OrderStatus, string> = {
  draft: "Qoralama",
  published: "E'lon qilingan",
  bidding: "Takliflar jarayonida",
  accepted: "Qabul qilingan",
  picked_up: "Olib ketilgan",
  in_transit: "Yo'lda",
  delivered: "Yetkazilgan",
  confirmed: "Tasdiqlangan",
  cancelled: "Bekor qilingan",
  disputed: "Nizoli",
};

export const manualOrderStatuses: OrderStatus[] = [
  "published",
  "bidding",
  "accepted",
  "picked_up",
  "in_transit",
  "delivered",
  "confirmed",
  "cancelled",
  "disputed",
];

export function statusLabel(status?: string | null): string {
  if (!status) return "-";
  return adminOrderStatusLabels[status as OrderStatus] ?? status;
}

export function statusToneClass(status?: string | null): string {
  if (["confirmed", "delivered"].includes(status ?? "")) return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (["published", "bidding", "accepted", "picked_up", "in_transit"].includes(status ?? "")) return "bg-blue-50 text-blue-700 border-blue-200";
  if (["cancelled", "disputed"].includes(status ?? "")) return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-slate-50 text-slate-700 border-slate-200";
}
