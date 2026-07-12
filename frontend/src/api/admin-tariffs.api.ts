import { adminApiRequest, query } from "./admin.api";
import type { Paginated } from "../types/api";
import type { RouteTariff, RouteTariffPayload, RouteTariffUpdatePayload, TariffFilters } from "../types/tariff";

function cleanFilters(params: TariffFilters): Record<string, string | number | boolean | undefined> {
  return {
    from_city_id: params.from_city_id,
    to_city_id: params.to_city_id,
    is_active: params.is_active === "active" ? true : params.is_active === "inactive" ? false : undefined,
    page: params.page,
    limit: params.limit,
  };
}

export function getAdminTariffs(params: TariffFilters = {}) {
  return adminApiRequest<Paginated<RouteTariff>>(`/admin/route-tariffs${query({ limit: 20, page: 1, ...cleanFilters(params) })}`);
}

export function getAdminTariffDetail(tariffId: number) {
  return adminApiRequest<RouteTariff>(`/admin/route-tariffs/${tariffId}`);
}

export function createTariff(payload: RouteTariffPayload) {
  const { is_active: _isActive, ...body } = payload;
  return adminApiRequest<RouteTariff>("/admin/route-tariffs", {
    method: "POST",
    body,
  });
}

export function updateTariff(tariffId: number, payload: RouteTariffUpdatePayload) {
  return adminApiRequest<RouteTariff>(`/admin/route-tariffs/${tariffId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function activateTariff(tariffId: number) {
  return updateTariff(tariffId, { is_active: true });
}

export function deactivateTariff(tariffId: number) {
  return updateTariff(tariffId, { is_active: false });
}

export async function getReverseTariff(fromCityId: number, toCityId: number) {
  const response = await getAdminTariffs({
    from_city_id: String(toCityId),
    to_city_id: String(fromCityId),
    is_active: "active",
    limit: 1,
  });
  return response.items[0] ?? null;
}
