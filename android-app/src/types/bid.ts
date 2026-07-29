export type BidStatus = "active" | "accepted" | "closed" | "rejected" | "expired";

export type Bid = {
  id?: number;
  bid_id?: number;
  order_id?: number;
  price: number;
  comment?: string | null;
  status: BidStatus;
  created_at?: string;
  is_mine?: boolean;
  driver?: {
    id?: number | null;
    full_name?: string | null;
    car_model?: string | null;
    plate_number?: string | null;
    rating?: number | string | null;
    completed_orders?: number;
  };
};

export type BidPayload = {
  price: number;
  comment?: string | null;
};
