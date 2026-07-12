import type { OrderStatus } from "./order";

export type AdminOrderRef = {
  id: number;
  name_uz?: string | null;
  full_name?: string | null;
  phone?: string | null;
};

export type AdminOrderDriver = {
  id: number;
  phone?: string | null;
  full_name?: string | null;
  car_model?: string | null;
  car_color?: string | null;
  plate_number?: string | null;
  rating?: number | string | null;
  completed_orders?: number;
  verification_status?: string | null;
};

export type AdminOrderBid = {
  id: number;
  driver_id?: number;
  driver_name?: string | null;
  driver_phone?: string | null;
  car_model?: string | null;
  car_color?: string | null;
  plate_number?: string | null;
  driver_rating?: number | string | null;
  price: number | string;
  comment?: string | null;
  status: string;
  created_at?: string;
};

export type AdminStatusHistoryItem = {
  old_status?: string | null;
  new_status: string;
  changed_by?: string | null;
  changed_by_role?: string | null;
  reason?: string | null;
  created_at?: string;
};

export type AdminOrderDispute = {
  id: number;
  reason?: string | null;
  status?: string | null;
  previous_order_status?: string | null;
  opened_by?: string | null;
  created_at?: string;
  resolution?: string | null;
};

export type AdminOrder = {
  id: number;
  order_number?: string;
  code?: string;
  status: OrderStatus;
  from_city?: AdminOrderRef | null;
  from_city_id?: number | string | null;
  from_district?: AdminOrderRef | null;
  from_district_id?: number | string | null;
  to_city?: AdminOrderRef | null;
  to_city_id?: number | string | null;
  to_district?: AdminOrderRef | null;
  to_district_id?: number | string | null;
  pickup_address?: string | null;
  pickup_lat?: number | string | null;
  pickup_lng?: number | string | null;
  dropoff_address?: string | null;
  dropoff_lat?: number | string | null;
  dropoff_lng?: number | string | null;
  client?: AdminOrderRef | null;
  client_phone?: string | null;
  sender_phone?: string | null;
  receiver_phone?: string | null;
  cargo_photo_url?: string | null;
  comment?: string | null;
  suggested_price?: number | string | null;
  final_price?: number | string | null;
  system_fee_rate?: number | string | null;
  system_fee?: number | string | null;
  driver_income?: number | string | null;
  payment_method?: "cash" | string;
  payment_status?: string | null;
  bids_count?: number;
  bids?: AdminOrderBid[];
  accepted_bid?: { id: number; price: number | string; status: string } | null;
  assigned_driver?: AdminOrderDriver | null;
  status_history?: AdminStatusHistoryItem[];
  dispute?: AdminOrderDispute | null;
  published_at?: string | null;
  accepted_at?: string | null;
  picked_up_at?: string | null;
  in_transit_at?: string | null;
  delivered_at?: string | null;
  confirmed_at?: string | null;
  cancelled_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type AdminOrderFilters = {
  search?: string;
  status?: string;
  from_city_id?: string;
  from_district_id?: string;
  to_city_id?: string;
  to_district_id?: string;
  assigned_driver?: string;
  created_from?: string;
  created_to?: string;
  has_bids?: string;
  has_dispute?: string;
  page?: number;
  limit?: number;
};

export type AdminOrderStatusPayload = {
  status: string;
  reason: string;
};

export type AdminAssignDriverPayload = {
  driver_id: number;
  final_price: number;
  reason: string;
};

export type AdminCancelOrderPayload = {
  reason: string;
};
