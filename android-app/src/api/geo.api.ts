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

export type ReverseGeocodeResponse = {
  formatted_address: string;
  lat: number;
  lng: number;
  region?: string | null;
  district?: string | null;
  detected_region_id?: number | null;
  detected_district_id?: number | null;
  provider?: string;
};

/** Resolve raw GPS coordinates to a known city/district (server picks the nearest). */
export function reverseGeocode(lat: number, lng: number, language = "uz") {
  return apiRequest<ReverseGeocodeResponse>("/geo/reverse-geocode", {
    method: "POST",
    body: { lat, lng, language },
  });
}

export type GeocodeResponse = {
  formatted_address?: string | null;
  lat?: number | null;
  lng?: number | null;
  region?: string | null;
  district?: string | null;
  provider?: string;
};

/** Resolve a typed address to coordinates. The Yandex key stays server-side. */
export function geocodeAddress(address: string, language = "uz") {
  return apiRequest<GeocodeResponse>("/geo/geocode", {
    method: "POST",
    body: { address, language },
  });
}
