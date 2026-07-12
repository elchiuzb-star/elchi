import { adminApiRequest, query } from "./admin.api";
import type { Paginated } from "../types/api";
import type { District } from "../types/district";

export type AdminDistrictFilters = {
  city_id?: number | string;
  search?: string;
  is_active?: string;
  page?: number;
  limit?: number;
};

export type DistrictPayload = {
  city_id: number;
  name_uz: string;
  name_ru?: string | null;
  display_order?: number;
  is_active?: boolean;
};

function cleanFilters(params: AdminDistrictFilters): Record<string, string | number | boolean | undefined> {
  return {
    city_id: params.city_id,
    search: params.search,
    is_active: params.is_active === "active" ? true : params.is_active === "inactive" ? false : undefined,
    page: params.page,
    limit: params.limit,
  };
}

export function getAdminDistricts(params: AdminDistrictFilters = {}) {
  return adminApiRequest<Paginated<District>>(`/admin/districts${query({ limit: 20, page: 1, ...cleanFilters(params) })}`);
}

export function getCityDistricts(cityId: number, params: AdminDistrictFilters = {}) {
  return getAdminDistricts({ ...params, city_id: cityId });
}

export function createDistrict(payload: DistrictPayload) {
  return adminApiRequest<District>("/admin/districts", {
    method: "POST",
    body: payload,
  });
}

export function updateDistrict(districtId: number, payload: Partial<DistrictPayload>) {
  return adminApiRequest<District>(`/admin/districts/${districtId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function activateDistrict(districtId: number) {
  return updateDistrict(districtId, { is_active: true });
}

export function deactivateDistrict(districtId: number) {
  return updateDistrict(districtId, { is_active: false });
}
