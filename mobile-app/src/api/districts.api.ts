import { apiRequest } from "./http";
import type { Paginated } from "../types/api";
import type { District } from "../types/city";

type DistrictListResponse = Paginated<District> | District[];

export async function getDistricts(cityId: number, params: { search?: string; page?: number; limit?: number } = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.page) query.set("page", String(params.page));
  if (params.limit) query.set("limit", String(params.limit));
  const data = await apiRequest<DistrictListResponse>(`/cities/${cityId}/districts${query.size ? `?${query}` : ""}`, { auth: false });
  return Array.isArray(data) ? data : data.items;
}
