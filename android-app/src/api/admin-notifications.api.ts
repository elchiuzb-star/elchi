import { adminApiRequest, query } from "./admin.api";
import type { Paginated } from "../types/api";

export type AdminNotification = {
  id: number;
  type?: string | null;
  title?: string | null;
  message?: string | null;
  order_id?: number | null;
  is_read: boolean;
  created_at?: string | null;
};

export type AdminNotificationFilters = {
  is_read?: string;
  type?: string;
  order_id?: string;
  page?: number;
  limit?: number;
};

export function getAdminNotifications(params: AdminNotificationFilters = {}) {
  return adminApiRequest<Paginated<AdminNotification>>(
    `/notifications${query({
      is_read: params.is_read === "read" ? true : params.is_read === "unread" ? false : undefined,
      type: params.type,
      order_id: params.order_id,
      page: params.page,
      limit: params.limit ?? 20,
    })}`,
  );
}

export function markAdminNotificationRead(notificationId: number) {
  return adminApiRequest<AdminNotification>(`/notifications/${notificationId}/read`, { method: "PATCH" });
}

export function markAllAdminNotificationsRead() {
  return adminApiRequest<{ updated: number }>("/notifications/read-all", { method: "PATCH" });
}
