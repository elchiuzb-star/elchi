import { apiRequest } from "./http";
import type { Paginated } from "../types/api";
import type { NotificationItem } from "../types/notification";

export function getNotifications(params: { page?: number; limit?: number; is_read?: boolean } = {}) {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.limit) query.set("limit", String(params.limit));
  if (params.is_read !== undefined) query.set("is_read", String(params.is_read));
  return apiRequest<Paginated<NotificationItem>>(`/notifications${query.size ? `?${query}` : ""}`);
}

export function markNotificationRead(notificationId: number) {
  return apiRequest<NotificationItem>(`/notifications/${notificationId}/read`, { method: "PATCH" });
}
