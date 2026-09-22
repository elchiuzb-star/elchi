/**
 * Opening a place in a real map app.
 *
 * Yandex Maps, to match the map the app itself draws: sending a person from a Yandex map to a Google one
 * changes the labels, the transliteration and the road names mid-task.
 */
export type LatLng = {
  lat: number;
  lng: number;
};

export { createMapsSearchUrl, createMapsDirectionsUrl } from "../components/maps/yandex";

export function hasLocation(lat?: number | string | null, lng?: number | string | null): boolean {
  return lat !== null && lat !== undefined && lng !== null && lng !== undefined;
}

export function hasCoordinates(lat?: number | string | null, lng?: number | string | null): boolean {
  return hasLocation(lat, lng);
}
