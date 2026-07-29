import { adminApiRequest } from "./admin.api";

export type AdminSystemSettings = {
  driver_commission_rate: number | string;
  driver_commission_percent: number | string;
  is_default: boolean;
  updated_at?: string | null;
  updated_by_user_id?: number | null;
};

export function getAdminSystemSettings() {
  return adminApiRequest<AdminSystemSettings>("/admin/settings");
}

export function updateDriverCommission(driver_commission_percent: number) {
  return adminApiRequest<AdminSystemSettings>("/admin/settings/driver-commission", {
    method: "PATCH",
    body: { driver_commission_percent },
  });
}
