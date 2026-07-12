import { apiRequest } from "./http";

export type GeoValidateLocationResponse = {
  valid: boolean;
  detected_region_id?: number | null;
  detected_district_id?: number | null;
  message: string;
};

export function validateGeoLocation(payload: {
  lat: number;
  lng: number;
  region_id: number;
  district_id?: number | null;
}) {
  return apiRequest<GeoValidateLocationResponse>("/geo/validate-location", { method: "POST", body: payload });
}
