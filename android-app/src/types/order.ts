export type OrderStatus =
  | "draft"
  | "published"
  | "bidding"
  | "accepted"
  | "picked_up"
  | "in_transit"
  | "delivered"
  | "confirmed"
  | "cancelled"
  | "disputed";

export type CreateOrderPayload = {
  from_city_id: number;
  to_city_id: number;
  from_district_id?: number | null;
  to_district_id?: number | null;
  pickup_address: string;
  dropoff_address: string;
  pickup_lat?: number | null;
  pickup_lng?: number | null;
  dropoff_lat?: number | null;
  dropoff_lng?: number | null;
  sender_phone: string;
  receiver_phone: string;
  cargo_type?: string | null;
  cargo_photo_url?: string | null;
  client_price?: number | null;
  comment?: string | null;
};

export type OrderDraft = {
  from_city_id?: string;
  from_city_name?: string;
  from_city_requires_district?: boolean;
  from_district_id?: string | null;
  from_district_name?: string | null;
  to_city_id?: string;
  to_city_name?: string;
  to_city_requires_district?: boolean;
  to_district_id?: string | null;
  to_district_name?: string | null;
  pickup_address?: string;
  dropoff_address?: string;
  pickup_lat?: number | null;
  pickup_lng?: number | null;
  dropoff_lat?: number | null;
  dropoff_lng?: number | null;
  sender_phone?: string;
  receiver_phone?: string;
  cargo_photo_url?: string;
  comment?: string;
};

export type ClientOrder = {
  id: number;
  order_number?: string;
  from_city?: unknown;
  to_city?: unknown;
  from_district?: unknown;
  to_district?: unknown;
  status: OrderStatus;
  suggested_price?: number | null;
  client_price?: number | null;
  final_price?: number | null;
  bids_count?: number;
  cargo_photo_url?: string | null;
  pickup_lat?: number | string | null;
  pickup_lng?: number | string | null;
  dropoff_lat?: number | string | null;
  dropoff_lng?: number | string | null;
  created_at?: string;
};

export type RatingPayload = {
  rating: number;
  comment?: string | null;
};
