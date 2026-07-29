import * as Location from "expo-location";
import { reverseGeocode } from "@/api/geo.api";
import { getCities } from "@/api/cities.api";
import { getDistricts } from "@/api/districts.api";
import { toUiCity } from "@/data/cities";
import type { LocationPoint } from "@/core/order";

/**
 * Detect the client's current pickup point from GPS.
 *
 * Flow: ask for foreground location permission → read the device position →
 * let the backend resolve those coordinates to a known city/district (nearest
 * district center). The city id is required for a valid order, so a point the
 * server cannot map to a city yields null and the field stays empty.
 *
 * Returns null (never throws) whenever detection can't complete — permission
 * denied, location off, network error — so the caller simply falls back to the
 * manual "select city" flow.
 */
async function readCoords(): Promise<{ latitude: number; longitude: number } | null> {
  // A cached fix is instant and enough for city-level detection.
  const last = await Location.getLastKnownPositionAsync();
  if (last) return last.coords;
  // Otherwise take a fresh fix. High accuracy targets the GPS provider (the one
  // emulators actually feed); cap the wait so a stuck fix can't hang the field.
  const fresh = await Promise.race([
    Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }),
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 12000)),
  ]);
  return fresh ? fresh.coords : null;
}

export async function detectCurrentPickup(): Promise<LocationPoint | null> {
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") return null;

    const coords = await readCoords();
    if (!coords) return null;
    const { latitude, longitude } = coords;

    const geo = await reverseGeocode(latitude, longitude);
    if (!geo.detected_region_id) return null;

    const cities = await getCities({ limit: 100 });
    const cityRaw = cities.find((c) => c.id === geo.detected_region_id);
    if (!cityRaw) return null;
    const city = toUiCity(cityRaw);

    // Prefer our own district name over Google's (which comes back localized/
    // Cyrillic); fall back to the detected label if the id isn't in our data.
    // (limit is capped at 100 server-side; no city has more districts than that.)
    let districtName: string | undefined = geo.district ?? undefined;
    const districtId = geo.detected_district_id ?? null;
    if (city.dist && districtId) {
      const districts = await getDistricts(city.id, { limit: 100 }).catch(() => []);
      const match = districts.find((d) => d.id === districtId);
      if (match) districtName = match.name_uz;
    }

    return {
      city,
      district: city.dist ? districtName : undefined,
      districtId: city.dist ? districtId : null,
      address: geo.formatted_address || "",
      lat: latitude,
      lng: longitude,
    };
  } catch {
    return null;
  }
}
