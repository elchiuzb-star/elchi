// Build a Yandex Maps directions deep-link (A → B) for the "Open in Maps"
// action. Opens the Yandex Maps app when installed, else the web map.
// Yandex route points use "lat,lon" in rtext; a single point uses "lon,lat" in pt.
export function mapsDirectionsUrl(pLat: unknown, pLng: unknown, dLat: unknown, dLng: unknown): string | null {
  const num = (v: unknown) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  const hasP = num(pLat) !== 0 || num(pLng) !== 0;
  const hasD = num(dLat) !== 0 || num(dLng) !== 0;

  if (hasP && hasD) {
    const rtext = `${num(pLat)},${num(pLng)}~${num(dLat)},${num(dLng)}`;
    return `https://yandex.com/maps/?rtext=${encodeURIComponent(rtext)}&rtt=auto`;
  }
  // Only one endpoint known → drop a pin there (pt is longitude,latitude).
  if (hasD) return `https://yandex.com/maps/?pt=${num(dLng)},${num(dLat)}&z=15&l=map`;
  if (hasP) return `https://yandex.com/maps/?pt=${num(pLng)},${num(pLat)}&z=15&l=map`;
  return null;
}
