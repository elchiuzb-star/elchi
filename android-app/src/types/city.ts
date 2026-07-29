export type City = {
  id: number;
  name_uz: string;
  name_ru?: string | null;
  region?: string | null;
  type?: "city" | "region" | "republic" | string;
  requires_district?: boolean;
  display_order?: number;
  is_active?: boolean;
  districts_count?: number;
  active_districts_count?: number;
  created_at?: string;
  updated_at?: string;
};

export type District = {
  id: number;
  city_id: number;
  name_uz: string;
  name_ru?: string | null;
  is_active?: boolean;
  display_order?: number;
  center_lat?: number | string | null;
  center_lng?: number | string | null;
  created_at?: string;
  updated_at?: string;
};

export type SuggestedPrice = {
  from_city_id: number;
  to_city_id: number;
  from_city?: City | null;
  to_city?: City | null;
  suggested_price: number | null;
  min_price?: number | null;
  max_price?: number | null;
  currency?: "UZS";
  is_active: boolean;
};
