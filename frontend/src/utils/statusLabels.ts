import type { BidStatus } from "../types/bid";
import type { DriverRouteStatus, DriverVerificationStatus } from "../types/driver";
import type { OrderStatus } from "../types/order";

export const orderStatusLabels: Record<OrderStatus, string> = {
  draft: "Qoralama",
  published: "E'lon qilingan",
  bidding: "Takliflar bor",
  accepted: "Haydovchi tanlangan",
  picked_up: "Olib ketildi",
  in_transit: "Yo'lda",
  delivered: "Yetkazildi",
  confirmed: "Tasdiqlandi",
  cancelled: "Bekor qilingan",
  disputed: "Nizo ochilgan",
};

export const driverVerificationLabels: Record<DriverVerificationStatus, string> = {
  new: "Profil va hujjatlarni to'ldiring",
  pending: "Hujjatlar ko'rib chiqilmoqda",
  approved: "Profil tasdiqlangan",
  rejected: "Hujjatlar rad etildi",
  blocked: "Profil bloklangan",
};

export const routeStatusLabels: Record<DriverRouteStatus, string> = {
  available: "Faol",
  unavailable: "Faol emas",
  busy: "Band",
};

export const bidStatusLabels: Record<BidStatus, string> = {
  active: "Faol",
  accepted: "Qabul qilingan",
  closed: "Yopilgan",
  rejected: "Rad etilgan",
  expired: "Muddati tugagan",
};
