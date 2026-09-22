/**
 * Google encoded-polyline decoder (the format `RouteVersionDTO.geometry_polyline` uses).
 *
 * Written here rather than pulled from the Maps SDK on purpose: the route line must draw even when the map
 * itself cannot load (no API key, offline, quota spent), because the stop list and the shape of the road are
 * information the driver needs and the map is only one way of showing it.
 *
 * Algorithm: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
 */
export type LatLng = { lat: number; lng: number };

export function decodePolyline(encoded: string, precision = 5): LatLng[] {
  if (!encoded) return [];
  const factor = 10 ** precision;
  const points: LatLng[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    let result = 0;
    let shift = 0;
    let byte: number;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lat += result & 1 ? ~(result >> 1) : result >> 1;

    result = 0;
    shift = 0;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lng += result & 1 ? ~(result >> 1) : result >> 1;

    points.push({ lat: lat / factor, lng: lng / factor });
  }
  return points;
}

/** Bounding box of a path, used to frame the map on the whole route instead of one marker. */
export function boundsOf(points: LatLng[]): { north: number; south: number; east: number; west: number } | null {
  if (points.length === 0) return null;
  return points.reduce(
    (box, point) => ({
      north: Math.max(box.north, point.lat),
      south: Math.min(box.south, point.lat),
      east: Math.max(box.east, point.lng),
      west: Math.min(box.west, point.lng),
    }),
    { north: points[0].lat, south: points[0].lat, east: points[0].lng, west: points[0].lng },
  );
}
