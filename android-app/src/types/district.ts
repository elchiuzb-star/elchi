export type District = {
  id: number;
  city_id: number;
  name_uz: string;
  name_ru?: string | null;
  is_active: boolean;
  display_order?: number | null;
  center_lat?: number | string | null;
  center_lng?: number | string | null;
  created_at?: string;
  updated_at?: string;
};
