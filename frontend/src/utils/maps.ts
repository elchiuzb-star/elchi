export type LatLng = {
  lat: number;
  lng: number;
};

export function createGoogleMapsSearchUrl(lat: number, lng: number): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${lat},${lng}`)}`;
}

export function createGoogleMapsDirectionsUrl(destinationLat: number, destinationLng: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${destinationLat},${destinationLng}`)}`;
}

export function hasLocation(lat?: number | string | null, lng?: number | string | null): boolean {
  return lat !== null && lat !== undefined && lng !== null && lng !== undefined;
}

export function hasCoordinates(lat?: number | string | null, lng?: number | string | null): boolean {
  return hasLocation(lat, lng);
}
