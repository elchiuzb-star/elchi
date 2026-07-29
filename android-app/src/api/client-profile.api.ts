import { apiRequest } from "./http";

export type ClientProfile = {
  id: number;
  user_id: number;
  phone: string;
  full_name?: string | null;
  role: "client";
  status: string;
  is_phone_verified: boolean;
  created_at?: string;
  updated_at?: string;
};

export function getClientProfile() {
  return apiRequest<ClientProfile>("/client/profile");
}

export function updateClientProfile(fullName: string) {
  return apiRequest<ClientProfile>("/client/profile", {
    method: "PATCH",
    body: { full_name: fullName },
  });
}
