export type RouteTariffCity = {
  id: number;
  name_uz: string;
  name_ru?: string | null;
  region?: string | null;
  is_active?: boolean;
};

export type RouteTariff = {
  id: number;
  from_city_id: number;
  to_city_id: number;
  from_city?: RouteTariffCity | null;
  to_city?: RouteTariffCity | null;
  suggested_price: number | string | null;
  min_price?: number | string | null;
  max_price?: number | string | null;
  currency?: "UZS" | string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
};

export type RouteTariffPayload = {
  from_city_id: number;
  to_city_id: number;
  suggested_price: number;
  min_price?: number | null;
  max_price?: number | null;
  is_active?: boolean;
};

export type RouteTariffUpdatePayload = {
  suggested_price?: number;
  min_price?: number | null;
  max_price?: number | null;
  is_active?: boolean;
};

export type TariffFilters = {
  search?: string;
  from_city_id?: string;
  to_city_id?: string;
  is_active?: string;
  price_from?: string;
  price_to?: string;
  has_reverse?: string;
  page?: number;
  limit?: number;
};
