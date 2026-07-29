import type { Bid, BidPayload } from "./bid";

export type DriverVerificationStatus = "new" | "pending" | "approved" | "rejected" | "blocked";
export type DriverRouteStatus = "available" | "unavailable" | "busy";
export type DriverDocumentType = "passport" | "selfie" | "license" | "car_document" | "car_photo";
export type DriverOrderAction = "picked_up" | "in_transit" | "delivered";

export type DriverProfile = {
  id: number;
  user?: {
    id: number;
    phone: string;
    full_name?: string | null;
    status: string;
  };
  full_name?: string | null;
  car_model?: string | null;
  car_color?: string | null;
  plate_number?: string | null;
  plate_number_normalized?: string | null;
  verification_status: DriverVerificationStatus;
  is_available: boolean;
  rating: number;
  total_orders: number;
  completed_orders: number;
  cancelled_orders: number;
  dispute_count: number;
  created_at?: string;
  updated_at?: string;
};

export type DriverProfileUpdate = Pick<DriverProfile, "full_name" | "car_model" | "car_color" | "plate_number">;

export type DriverRoute = {
  id: number;
  from_city: unknown;
  to_city: unknown;
  from_district?: unknown;
  to_district?: unknown;
  from_district_id?: number | null;
  to_district_id?: number | null;
  status: DriverRouteStatus;
  created_at?: string;
};

export type DriverRouteCreate = {
  from_city_id: number;
  to_city_id: number;
  from_district_id?: number | null;
  to_district_id?: number | null;
};

export type DriverFeedOrder = {
  id: number;
  order_number?: string;
  from_city?: unknown;
  to_city?: unknown;
  from_district?: unknown;
  to_district?: unknown;
  pickup_area?: string | null;
  dropoff_area?: string | null;
  suggested_price?: number | null;
  client_price?: number | null;
  cargo_photo_url?: string | null;
  final_price?: number | string | null;
  gross_income?: number | string | null;
  system_fee?: number | string | null;
  driver_income?: number | string | null;
  system_fee_rate?: number | string | null;
  pickup_lat?: number | string | null;
  pickup_lng?: number | string | null;
  dropoff_lat?: number | string | null;
  dropoff_lng?: number | string | null;
  status: string;
  my_bid?: unknown;
  bids?: Bid[];
  delivered_at?: string;
  confirmed_at?: string;
  created_at?: string;
};

export type DriverDocumentPayload = {
  document_type: DriverDocumentType;
  file_url: string;
  mime_type?: string;
  size_bytes?: number;
};

/** A document the driver has uploaded (GET /driver/documents). */
export type DriverDocumentStatus = "pending" | "approved" | "rejected";

export type DriverDocument = {
  document_id: number;
  driver_id: number;
  document_type: DriverDocumentType;
  file_url: string;
  status: DriverDocumentStatus;
  rejection_reason?: string | null;
};

export type DriverBidPayload = BidPayload;
