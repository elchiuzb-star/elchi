export type StaffUserRole = "operator" | "admin" | "super_admin";
export type StaffUserStatus = "active" | "blocked" | "inactive" | string;

export type AdminStaffUser = {
  id: number;
  phone: string;
  full_name?: string | null;
  role: StaffUserRole;
  status: StaffUserStatus;
  is_phone_verified: boolean;
  last_login_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AdminStaffUserFilters = {
  search?: string;
  role?: string;
  status?: string;
  is_phone_verified?: string;
  created_from?: string;
  created_to?: string;
  page?: number;
  limit?: number;
};

export type AdminStaffUserCreatePayload = {
  phone: string;
  role: "operator" | "admin";
  full_name?: string | null;
};

export type AdminStaffUserUpdatePayload = {
  full_name?: string | null;
  role?: "operator" | "admin";
  status?: "active" | "blocked" | "inactive";
};
