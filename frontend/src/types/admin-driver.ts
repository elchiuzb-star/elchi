export type AdminDriverStatus = "new" | "pending" | "approved" | "rejected" | "blocked";
export type AdminDriverRouteStatus = "available" | "unavailable" | "busy";
export type AdminDriverDocumentType = "passport" | "selfie" | "license" | "car_document" | "car_photo";
export type AdminDriverDocumentStatus = "pending" | "approved" | "rejected" | "missing";

export type AdminDriverUser = {
  id: number;
  phone: string;
  full_name?: string | null;
  status?: string;
  is_phone_verified?: boolean;
  created_at?: string;
};

export type AdminDriverRef = {
  id: number;
  name_uz?: string | null;
  city_id?: number;
};

export type AdminDriverDocument = {
  id?: number;
  document_type: AdminDriverDocumentType;
  file_url?: string;
  status: AdminDriverDocumentStatus;
  rejection_reason?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  created_at?: string;
};

export type AdminDriverRoute = {
  id: number;
  from_city?: AdminDriverRef | null;
  to_city?: AdminDriverRef | null;
  from_district?: AdminDriverRef | null;
  to_district?: AdminDriverRef | null;
  status: AdminDriverRouteStatus;
  created_at?: string;
};

export type AdminDriver = {
  id: number;
  user?: AdminDriverUser;
  user_id?: number;
  full_name?: string | null;
  phone?: string | null;
  verification_status: AdminDriverStatus;
  is_available: boolean;
  car_model?: string | null;
  car_color?: string | null;
  plate_number?: string | null;
  plate_number_normalized?: string | null;
  rating?: number | string | null;
  total_orders?: number;
  completed_orders?: number;
  cancelled_orders?: number;
  dispute_count?: number;
  documents_count?: number;
  required_documents_count?: number;
  active_routes_count?: number;
  total_routes_count?: number;
  active_orders_count?: number;
  documents?: AdminDriverDocument[];
  routes?: AdminDriverRoute[];
  created_at?: string;
  updated_at?: string;
};

export type AdminDriverFilters = {
  search?: string;
  verification_status?: string;
  is_available?: string;
  city_id?: string;
  district_id?: string;
  has_documents?: string;
  has_active_route?: string;
  created_from?: string;
  created_to?: string;
  page?: number;
  limit?: number;
};
