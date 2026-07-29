export type AdminClient = {
  id: number;
  profile_id?: number | null;
  phone: string;
  full_name?: string | null;
  role: "client";
  status: string;
  is_phone_verified: boolean;
  orders_count: number;
  active_orders_count: number;
  completed_orders_count: number;
  cancelled_orders_count: number;
  last_order_at?: string | null;
  last_login_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AdminClientFilters = {
  search?: string;
  status?: string;
  is_phone_verified?: string;
  page?: number;
  limit?: number;
};
