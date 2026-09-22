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

/**
 * Geocoding goes **through our server**, not straight from the browser to Yandex.
 *
 * The backend already holds a Yandex Geocoder key (`ELCHI_YANDEX_GEOCODER_API_KEY`) and already exposes these
 * two endpoints. Calling Yandex from the client instead would mean a second key shipped inside the JavaScript
 * bundle, and a data flow from every user's device that no document describes. The map *tiles* still need a
 * browser key - there is no way around that - but a name for a pin does not.
 */
export type GeocodeResult = {
  formatted_address: string | null;
  lat: number | null;
  lng: number | null;
  region: string | null;
  district: string | null;
  provider: string;
};

/** A place name for a pin. Throws on a server error; callers fall back to the coordinates. */
export function reverseGeocode(payload: { lat: number; lng: number; language?: string }) {
  return apiRequest<GeocodeResult>("/geo/reverse-geocode", {
    method: "POST",
    body: { lat: payload.lat, lng: payload.lng, language: payload.language ?? "uz" },
  });
}

/**
 * Coordinates for a typed address. The server answers `404 GEOCODE_FAILED` when it finds nothing.
 *
 * `near` biases the answer towards an area (the chosen district) without filtering anything out.
 */
export function geocodeAddress(payload: {
  address: string;
  language?: string;
  near?: { lat: number; lng: number } | null;
  spanDeg?: number;
}) {
  return apiRequest<GeocodeResult>("/geo/geocode", {
    method: "POST",
    body: {
      address: payload.address,
      language: payload.language ?? "uz",
      near_lat: payload.near?.lat ?? null,
      near_lng: payload.near?.lng ?? null,
      span_deg: payload.near ? (payload.spanDeg ?? 0.35) : null,
    },
  });
}

/**
 * Place suggestions for typed text (Yandex Geosuggest, behind our own server).
 *
 * The geocoder answers *addresses*; people type *places* - "10-sonli maktab", a bazaar, a hokimlik.
 * `near`/`span_deg` is the chosen district's centre, and `district` its name: the server lists places inside
 * that district first and everything else after, so the search answers where the person is actually standing
 * without hiding the rest of the country.
 *
 * A suggestion carries no coordinate, only `uri`. `resolvePlace` turns the one that gets picked into a point,
 * so nothing is geocoded until somebody chooses something.
 */
export type PlaceSuggestion = {
  title: string | null;
  subtitle: string | null;
  formatted_address: string | null;
  region: string | null;
  district: string | null;
  locality: string | null;
  distance_m: number | null;
  uri: string;
};

export function suggestPlaces(payload: {
  text: string;
  near?: { lat: number; lng: number } | null;
  spanDeg?: number;
  district?: string | null;
  limit?: number;
  language?: string;
}) {
  return apiRequest<{ results: PlaceSuggestion[] }>("/geo/suggest", {
    method: "POST",
    body: {
      text: payload.text,
      language: payload.language ?? "uz",
      near_lat: payload.near?.lat ?? null,
      near_lng: payload.near?.lng ?? null,
      span_deg: payload.near ? (payload.spanDeg ?? 0.35) : null,
      district: payload.district ?? null,
      limit: payload.limit ?? 10,
    },
  });
}

/** Coordinates for a suggestion the person picked. `404 GEOCODE_FAILED` when the provider cannot place it. */
export function resolvePlace(payload: { uri: string; language?: string }) {
  return apiRequest<GeocodeResult>("/geo/resolve-place", {
    method: "POST",
    body: { uri: payload.uri, language: payload.language ?? "uz" },
  });
}
