import { apiRequest } from "./http";
import type { Paginated } from "../types/api";
import type { City, SuggestedPrice } from "../types/city";

type CityListResponse = Paginated<City> | City[];

export async function getCities(params: { search?: string; page?: number; limit?: number } = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.page) query.set("page", String(params.page));
  if (params.limit) query.set("limit", String(params.limit));
  const data = await apiRequest<CityListResponse>(`/cities${query.size ? `?${query}` : ""}`, { auth: false });
  return Array.isArray(data) ? data : data.items;
}

export function getSuggestedPrice(fromCityId: number, toCityId: number) {
  return apiRequest<SuggestedPrice>(`/route-tariffs/suggested-price?from_city_id=${fromCityId}&to_city_id=${toCityId}`);
}
