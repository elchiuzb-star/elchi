import type { AuthUser, MobileRole } from "../types/auth";

export function canAccessRole(user: AuthUser | null, role: MobileRole): boolean {
  return user?.role === role;
}

export function getHomeScreenForRole(role: MobileRole): "client" | "driver" {
  return role;
}
