import { GoogleMap, MarkerF, PolylineF, useJsApiLoader } from "@react-google-maps/api";

import { googleMapsLibraries, googleMapsMapId } from "./googleMapsConfig";

type RoutePreviewMapProps = {
  fromCity: unknown;
  toCity: unknown;
};

type CityPoint = {
  name: string;
  lat: number;
  lng: number;
  terms: string[];
};

const fallbackCenter = { lat: 41.2995, lng: 69.2401 };

const cityPoints: CityPoint[] = [
  { name: "Toshkent", lat: 41.2995, lng: 69.2401, terms: ["toshkent", "tashkent"] },
  { name: "Samarqand", lat: 39.6542, lng: 66.9597, terms: ["samarqand", "samarkand"] },
  { name: "Buxoro", lat: 39.7747, lng: 64.4286, terms: ["buxoro", "bukhara"] },
  { name: "Andijon", lat: 40.7821, lng: 72.3442, terms: ["andijon", "andijan"] },
  { name: "Namangan", lat: 41.0011, lng: 71.6683, terms: ["namangan"] },
  { name: "Farg'ona", lat: 40.3894, lng: 71.7843, terms: ["fargona", "farg'ona", "fergana"] },
  { name: "Qashqadaryo", lat: 38.8610, lng: 65.7847, terms: ["qashqadaryo", "qarshi", "kashkadarya"] },
  { name: "Surxondaryo", lat: 37.2242, lng: 67.2783, terms: ["surxondaryo", "termiz", "surkhandarya"] },
  { name: "Navoiy", lat: 40.1039, lng: 65.3688, terms: ["navoiy", "navoi"] },
  { name: "Jizzax", lat: 40.1158, lng: 67.8422, terms: ["jizzax", "jizzakh"] },
  { name: "Sirdaryo", lat: 40.4897, lng: 68.7842, terms: ["sirdaryo", "guliston", "syrdarya"] },
  { name: "Xorazm", lat: 41.5500, lng: 60.6333, terms: ["xorazm", "urganch", "khorezm"] },
  { name: "Qoraqalpog'iston", lat: 42.4619, lng: 59.6166, terms: ["qoraqalpogiston", "qoraqalpog'iston", "nukus", "karakalpakstan"] },
];

function normalize(value: string) {
  return value
    .toLowerCase()
    .replace(/[`']/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function readCityParts(city: unknown): string[] {
  if (!city) return [];
  if (typeof city === "string") return [city];
  if (typeof city !== "object") return [];

  const record = city as Record<string, unknown>;
  return ["name_uz", "name_ru", "region", "name"].map((key) => record[key]).filter((value): value is string => typeof value === "string");
}

function resolveCityPoint(city: unknown) {
  const text = normalize(readCityParts(city).join(" "));
  if (!text) return null;
  return cityPoints.find((point) => point.terms.some((term) => text.includes(normalize(term)))) ?? null;
}

function midpoint(from: google.maps.LatLngLiteral, to: google.maps.LatLngLiteral) {
  return {
    lat: (from.lat + to.lat) / 2,
    lng: (from.lng + to.lng) / 2,
  };
}

function zoomForDistance(from: google.maps.LatLngLiteral, to: google.maps.LatLngLiteral) {
  const distance = Math.max(Math.abs(from.lat - to.lat), Math.abs(from.lng - to.lng));
  if (distance > 8) return 5;
  if (distance > 4) return 6;
  return 7;
}

export function RoutePreviewMap({ fromCity, toCity }: RoutePreviewMapProps) {
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
  const from = resolveCityPoint(fromCity);
  const to = resolveCityPoint(toCity);
  const fromPosition = from ? { lat: from.lat, lng: from.lng } : null;
  const toPosition = to ? { lat: to.lat, lng: to.lng } : null;
  const hasRoute = Boolean(fromPosition && toPosition);

  const { isLoaded, loadError } = useJsApiLoader({
    id: "elchi-google-maps",
    googleMapsApiKey: apiKey ?? "",
    libraries: googleMapsLibraries,
  });

  if (!apiKey) {
    return (
      <div className="flex h-[148px] items-center justify-center bg-[#EEF2FF] px-4 text-center text-[13px] font-medium text-[#1B4FD8]">
        Google Maps API kaliti topilmadi
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex h-[148px] items-center justify-center bg-[#FEE2E2] px-4 text-center text-[13px] font-medium text-[#DC2626]">
        Xarita yuklanmadi. Google API key, Map ID va referrer sozlamalarini tekshiring.
      </div>
    );
  }

  if (!isLoaded) {
    return <div className="h-[148px] animate-pulse bg-[#E0F2FE]" />;
  }

  const center = hasRoute ? midpoint(fromPosition!, toPosition!) : fromPosition ?? toPosition ?? fallbackCenter;
  const zoom = hasRoute ? zoomForDistance(fromPosition!, toPosition!) : 6;

  return (
    <GoogleMap
      mapContainerStyle={{ width: "100%", height: "148px" }}
      center={center}
      zoom={zoom}
      options={{
        clickableIcons: false,
        fullscreenControl: false,
        gestureHandling: "none",
        keyboardShortcuts: false,
        mapId: googleMapsMapId,
        mapTypeControl: false,
        streetViewControl: false,
        zoomControl: false,
      }}
    >
      {fromPosition && <MarkerF position={fromPosition} label="A" title={from?.name ?? "Qayerdan"} />}
      {toPosition && <MarkerF position={toPosition} label="B" title={to?.name ?? "Qayerga"} />}
      {hasRoute && (
        <PolylineF
          path={[fromPosition!, toPosition!]}
          options={{
            geodesic: true,
            strokeColor: "#1B4FD8",
            strokeOpacity: 0.9,
            strokeWeight: 4,
          }}
        />
      )}
    </GoogleMap>
  );
}
