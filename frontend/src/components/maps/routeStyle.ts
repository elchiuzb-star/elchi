export const ROUTE_START = "#3B82F6"; // blue at the origin
export const ROUTE_END = "#0A1C63";   // dark blue at the destination

export function hexLerp(a: string, b: string, t: number): string {
  const ai = parseInt(a.slice(1), 16);
  const bi = parseInt(b.slice(1), 16);
  const ch = (shift: number) => {
    const av = (ai >> shift) & 255;
    const bv = (bi >> shift) & 255;
    return Math.round(av + (bv - av) * t);
  };
  return `#${((1 << 24) + (ch(16) << 16) + (ch(8) << 8) + ch(0)).toString(16).slice(1)}`;
}

/** Evenly sample a straight line between two points (for gradient rendering). */
export function sampleLine(from: google.maps.LatLngLiteral, to: google.maps.LatLngLiteral, points = 40): google.maps.LatLngLiteral[] {
  const path: google.maps.LatLngLiteral[] = [];
  for (let i = 0; i <= points; i += 1) {
    const t = i / points;
    path.push({ lat: from.lat + (to.lat - from.lat) * t, lng: from.lng + (to.lng - from.lng) * t });
  }
  return path;
}

/** Split a path into contiguous colour-graded chunks so the line fades start → end. */
export function gradientSegments(path: google.maps.LatLngLiteral[]): { path: google.maps.LatLngLiteral[]; color: string }[] {
  const n = path.length;
  if (n < 2) return [];
  const chunks = Math.min(40, n - 1);
  const step = (n - 1) / chunks;
  const segments: { path: google.maps.LatLngLiteral[]; color: string }[] = [];
  for (let i = 0; i < chunks; i += 1) {
    const a = Math.round(i * step);
    const b = Math.round((i + 1) * step);
    segments.push({
      path: path.slice(a, b + 1),
      color: hexLerp(ROUTE_START, ROUTE_END, chunks === 1 ? 1 : i / (chunks - 1)),
    });
  }
  return segments;
}
