import { adminApiRequest, query } from "./admin.api";
import type { Paginated } from "../types/api";
import type { City } from "../types/city";

export type AdminCityFilters = {
  search?: string;
  type?: string;
  is_active?: string;
  requires_district?: string;
  has_districts?: string;
  page?: number;
  limit?: number;
};

export type CityPayload = {
  name_uz: string;
  name_ru?: string | null;
  region?: string | null;
  type: "city" | "region" | "republic";
  requires_district: boolean;
  display_order?: number;
  is_active?: boolean;
};

function cleanFilters(params: AdminCityFilters): Record<string, string | number | boolean | undefined> {
  return {
    search: params.search,
    is_active: params.is_active === "active" ? true : params.is_active === "inactive" ? false : undefined,
    page: params.page,
    limit: params.limit,
  };
}

export function getAdminCities(params: AdminCityFilters = {}) {
  return adminApiRequest<Paginated<City>>(`/admin/cities${query({ limit: 20, page: 1, ...cleanFilters(params) })}`);
}

export function getAdminCityDetail(cityId: number) {
  return adminApiRequest<City>(`/admin/cities/${cityId}`);
}

export function createCity(payload: CityPayload) {
  return adminApiRequest<City>("/admin/cities", {
    method: "POST",
    body: payload,
  });
}

export function updateCity(cityId: number, payload: Partial<CityPayload>) {
  return adminApiRequest<City>(`/admin/cities/${cityId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function activateCity(cityId: number) {
  return updateCity(cityId, { is_active: true });
}

export function deactivateCity(cityId: number) {
  return updateCity(cityId, { is_active: false });
}
