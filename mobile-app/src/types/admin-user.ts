export type StaffUserRole = "operator" | "admin" | "super_admin" | "finance";
/** Roles a super_admin may give in the staff panel (ADMIN-BACKEND-CONTRACT §1.3/§2); super_admin is never created here. */
export type AssignableStaffRole = "operator" | "admin" | "finance";
export type StaffUserStatus = "active" | "blocked" | "inactive" | string;

export type AdminStaffUser = {
  id: number;
  phone: string;
  full_name?: string | null;
  role: StaffUserRole;
  status: StaffUserStatus;
  is_phone_verified: boolean;
  /** v2 public id (`usr_...`), used by the MFA activate/reset commands (contract §5.1). */
  public_id?: string | null;
  username?: string | null;
  has_password?: boolean;
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
  role: AssignableStaffRole;
  full_name?: string | null;
  /** Sent together with `password` or not at all (contract §2). */
  username?: string;
  password?: string;
};

export type AdminStaffUserUpdatePayload = {
  full_name?: string | null;
  role?: AssignableStaffRole;
  status?: "active" | "blocked" | "inactive";
};
