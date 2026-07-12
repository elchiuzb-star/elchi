import { useJsApiLoader } from "@react-google-maps/api";
import { googleMapsLibraries } from "./googleMapsConfig";

export const GOOGLE_MAPS_API_KEY = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined) || "";

/** Shared Google Maps JS loader — one id/libraries set for the whole app. */
export function useMapsLoader() {
  const { isLoaded, loadError } = useJsApiLoader({
    id: "elchi-google-maps",
    googleMapsApiKey: GOOGLE_MAPS_API_KEY,
    libraries: googleMapsLibraries,
  });
  return { isLoaded, loadError, hasKey: Boolean(GOOGLE_MAPS_API_KEY) };
}

export function toPoint(
  lat?: number | string | null,
  lng?: number | string | null,
): google.maps.LatLngLiteral | null {
  if (lat === null || lat === undefined || lat === "" || lng === null || lng === undefined || lng === "") return null;
  const parsedLat = Number(lat);
  const parsedLng = Number(lng);
  if (!Number.isFinite(parsedLat) || !Number.isFinite(parsedLng)) return null;
  return { lat: parsedLat, lng: parsedLng };
}

let geocoder: google.maps.Geocoder | null = null;

export type GeocodedRegion = {
  location: google.maps.LatLngLiteral;
  bounds?: google.maps.LatLngBoundsLiteral;
};

/** Geocode a city/district name to its centre and viewport (used to focus + bias the picker). */
export function geocodeRegion(query: string): Promise<GeocodedRegion | null> {
  return new Promise((resolve) => {
    if (!window.google?.maps || !query.trim()) {
      resolve(null);
      return;
    }
    if (!geocoder) geocoder = new window.google.maps.Geocoder();
    geocoder.geocode(
      { address: query, componentRestrictions: { country: "uz" }, language: "uz" },
      (results, status) => {
        if (status !== "OK" || !results?.length) {
          resolve(null);
          return;
        }
        // Prefer the most specific match (smallest viewport) so a city/district wins over its region.
        const vpArea = (r: google.maps.GeocoderResult) => {
          const vp = r.geometry.viewport;
          if (!vp) return Number.POSITIVE_INFINITY;
          const ne = vp.getNorthEast();
          const sw = vp.getSouthWest();
          return Math.abs(ne.lat() - sw.lat()) * Math.abs(ne.lng() - sw.lng());
        };
        const best = results.reduce((a, b) => (vpArea(b) < vpArea(a) ? b : a));
        const loc = best.geometry.location;
        const vp = best.geometry.viewport;
        resolve({
          location: { lat: loc.lat(), lng: loc.lng() },
          bounds: vp
            ? { north: vp.getNorthEast().lat(), east: vp.getNorthEast().lng(), south: vp.getSouthWest().lat(), west: vp.getSouthWest().lng() }
            : undefined,
        });
      },
    );
  });
}

/** Reverse-geocode lat/lng -> formatted address using the Google JS Geocoder. */
export function reverseGeocode(lat: number, lng: number, language = "uz"): Promise<string> {
  return new Promise((resolve) => {
    if (!window.google?.maps) {
      resolve(`${lat.toFixed(6)}, ${lng.toFixed(6)}`);
      return;
    }
    if (!geocoder) geocoder = new window.google.maps.Geocoder();
    geocoder.geocode({ location: { lat, lng }, language }, (results, status) => {
      if (status === "OK" && results?.[0]?.formatted_address) resolve(results[0].formatted_address);
      else resolve(`${lat.toFixed(6)}, ${lng.toFixed(6)}`);
    });
  });
}
