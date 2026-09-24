import { MapLine, MapMarker, YandexMap } from "./YandexMap";
import { TASHKENT, type LatLng } from "./yandex";
import { translate } from "../../i18n";

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

const fallbackCenter = TASHKENT;

const cityPoints: CityPoint[] = [
  { get name() { return translate("maps.city.tashkent"); }, lat: 41.2995, lng: 69.2401, terms: ["toshkent", "tashkent"] },
  { get name() { return translate("maps.city.samarkand"); }, lat: 39.6542, lng: 66.9597, terms: ["samarqand", "samarkand"] },
  { get name() { return translate("maps.city.bukhara"); }, lat: 39.7747, lng: 64.4286, terms: ["buxoro", "bukhara"] },
  { get name() { return translate("maps.city.andijan"); }, lat: 40.7821, lng: 72.3442, terms: ["andijon", "andijan"] },
  { get name() { return translate("maps.city.namangan"); }, lat: 41.0011, lng: 71.6683, terms: ["namangan"] },
  // i18n-ignore: search aliases, not display text
  { get name() { return translate("maps.city.fergana"); }, lat: 40.3894, lng: 71.7843, terms: ["fargona", "farg'ona", "fergana"] },
  { get name() { return translate("maps.city.kashkadarya"); }, lat: 38.8610, lng: 65.7847, terms: ["qashqadaryo", "qarshi", "kashkadarya"] },
  { get name() { return translate("maps.city.surkhandarya"); }, lat: 37.2242, lng: 67.2783, terms: ["surxondaryo", "termiz", "surkhandarya"] },
  { get name() { return translate("maps.city.navoi"); }, lat: 40.1039, lng: 65.3688, terms: ["navoiy", "navoi"] },
  { get name() { return translate("maps.city.jizzakh"); }, lat: 40.1158, lng: 67.8422, terms: ["jizzax", "jizzakh"] },
  { get name() { return translate("maps.city.syrdarya"); }, lat: 40.4897, lng: 68.7842, terms: ["sirdaryo", "guliston", "syrdarya"] },
  { get name() { return translate("maps.city.khorezm"); }, lat: 41.5500, lng: 60.6333, terms: ["xorazm", "urganch", "khorezm"] },
  // i18n-ignore: search aliases, not display text
  { get name() { return translate("maps.city.karakalpakstan"); }, lat: 42.4619, lng: 59.6166, terms: ["qoraqalpogiston", "qoraqalpog'iston", "nukus", "karakalpakstan"] },
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

function midpoint(from: LatLng, to: LatLng) {
  return {
    lat: (from.lat + to.lat) / 2,
    lng: (from.lng + to.lng) / 2,
  };
}

function zoomForDistance(from: LatLng, to: LatLng) {
  const distance = Math.max(Math.abs(from.lat - to.lat), Math.abs(from.lng - to.lng));
  if (distance > 8) return 5;
  if (distance > 4) return 6;
  return 7;
}

export function RoutePreviewMap({ fromCity, toCity }: RoutePreviewMapProps) {
  const from = resolveCityPoint(fromCity);
  const to = resolveCityPoint(toCity);
  const fromPosition = from ? { lat: from.lat, lng: from.lng } : null;
  const toPosition = to ? { lat: to.lat, lng: to.lng } : null;
  const hasRoute = Boolean(fromPosition && toPosition);
  const center = hasRoute ? midpoint(fromPosition!, toPosition!) : fromPosition ?? toPosition ?? fallbackCenter;
  const zoom = hasRoute ? zoomForDistance(fromPosition!, toPosition!) : 6;

  return (
    <YandexMap
      center={center}
      zoom={zoom}
      interactive={false}
      style={{ width: "100%", height: 148 }}
      fallback={(status) =>
        status === "loading" ? (
          <div className="h-[148px] animate-pulse bg-accent" />
        ) : (
          <div className="flex h-[148px] items-center justify-center bg-accent px-4 text-center text-[13px] font-medium text-primary">
            {status === "missing-key" ? translate("maps.keyMissing") : translate("maps.loadFailed")}
          </div>
        )
      }
    >
      {fromPosition && <MapMarker point={fromPosition} label="A" title={from?.name ?? translate("maps.from")} />}
      {toPosition && <MapMarker point={toPosition} label="B" title={to?.name ?? translate("maps.to")} />}
      {/*
        A straight line between two city centres is a *direction indicator*, not a road - which is why it is
        only drawn on this v1 preview and never on the v2 route map, where the server's confirmed geometry is
        the only thing allowed on screen.
      */}
      {hasRoute && <MapLine points={[fromPosition!, toPosition!]} />}
    </YandexMap>
  );
}
