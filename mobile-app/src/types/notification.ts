export type NotificationItem = {
  id: number;
  type: string;
  title: string;
  message?: string;
  body?: string;
  order_id?: number | null;
  is_read: boolean;
  entity_type?: string | null;
  entity_id?: number | null;
  created_at?: string;
};
