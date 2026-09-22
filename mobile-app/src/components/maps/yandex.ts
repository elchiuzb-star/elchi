/**
 * Yandex Maps for the Elchi client.
 *
 * **Which SDK.** `mobile-app` is a web client (Vite + react-dom), so the SDK that applies here is the Yandex
 * Maps **JavaScript API**, loaded from `api-maps.yandex.ru`. "MapKit SDK" is the *native* Android/iOS library;
 * it has no web build, and the native app in this repo (`android-app/`) is frozen. Same provider, same
 * account, same key management - different artefact.
 *
 * **Which version, and why it is a setting.** Yandex issues a JavaScript API key for one version of the API.
 * The account behind this app holds a **v2.1** key: `api-maps.yandex.ru/v3/` answers `403 Invalid api key` for
 * it, while `2.1` loads and draws tiles. So `2.1` is the default here. Set `VITE_YANDEX_MAPS_VERSION=v3` once a
 * v3 key exists and nothing else in the app changes - which is what the adapter below is for.
 *
 * **One key in the browser.** Only the map tiles need a key on the client (`VITE_YANDEX_MAPS_API_KEY`, which
 * should be domain-restricted). Geocoding goes through our own backend, which already holds the Geocoder key -
 * see `src/api/geo.api.ts`. Without the tile key every map here degrades to the text it was drawn over (a stop
 * list, an address, coordinates) rather than to a grey box.
 *
 * **Coordinates.** The two versions disagree: v2.1 speaks `[latitude, longitude]`, v3 speaks the reverse. The
 * rest of this app - and the whole backend - speaks `{lat, lng}`, and only the adapters below ever convert, so
 * the order can be wrong in exactly one place per version instead of in every component.
 */

/** What the rest of the app passes around. */
export type LatLng = { lat: number; lng: number };
/** What Yandex v3 expects: longitude first. */
export type LngLat = [number, number];
/** What Yandex v2.1 expects: latitude first. */
export type LatLngPair = [number, number];

export const TASHKENT: LatLng = { lat: 41.2995, lng: 69.2401 };

export function toLngLat(point: LatLng): LngLat {
  return [point.lng, point.lat];
}

export function fromLngLat(point: LngLat): LatLng {
  return { lat: point[1], lng: point[0] };
}

export function toLatLngPair(point: LatLng): LatLngPair {
  return [point.lat, point.lng];
}

export function readPoint(lat?: number | string | null, lng?: number | string | null): LatLng | null {
  if (lat === null || lat === undefined || lat === "" || lng === null || lng === undefined || lng === "") return null;
  const parsedLat = Number(lat);
  const parsedLng = Number(lng);
  if (!Number.isFinite(parsedLat) || !Number.isFinite(parsedLng)) return null;
  return { lat: parsedLat, lng: parsedLng };
}

export const MAPS_API_KEY = ((import.meta.env.VITE_YANDEX_MAPS_API_KEY as string | undefined) || "").trim();
/** `uz_UZ` where it is available; Yandex falls back on its own for tiles it has no Uzbek labels for. */
const LANG = ((import.meta.env.VITE_YANDEX_MAPS_LANG as string | undefined) || "uz_UZ").trim();

export type MapsVersion = "2.1" | "v3";

/** Defaults to the version this account's key is issued for; `v3` is one env line away. */
export const MAPS_VERSION: MapsVersion =
  ((import.meta.env.VITE_YANDEX_MAPS_VERSION as string | undefined) || "").trim() === "v3" ? "v3" : "2.1";

export type MapsStatus = "missing-key" | "loading" | "ready" | "error";

// --- the surface the React layer talks to ----------------------------------------------------------------
//
// `YandexMap.tsx` knows these types and nothing about Yandex. Everything version-specific - class names,
// coordinate order, how a pin is built, how a map is torn down - lives in one of the two adapters below.

export interface MarkerHandle {
  move(point: LatLng): void;
  remove(): void;
}

export interface LineHandle {
  remove(): void;
}

export interface MapHandle {
  setView(center: LatLng, zoom: number): void;
  /** `element` is a styled DOM node; v3 mounts it as-is, v2.1 re-renders it through a layout class. */
  addMarker(point: LatLng, element: HTMLElement, title?: string): MarkerHandle;
  addLine(points: LatLng[], color: string): LineHandle;
  destroy(): void;
}

export interface CreateMapOptions {
  center: LatLng;
  zoom: number;
  /** False for a preview map: one that pans under a finger steals the page's scroll. */
  interactive: boolean;
  /** Fires after the map settles following a user gesture - the point-picker reads the centre from it. */
  onCenterSettled?: (center: LatLng) => void;
}

export interface MapsApi {
  version: MapsVersion;
  create(container: HTMLElement, options: CreateMapOptions): MapHandle;
}

// --- v2.1 ------------------------------------------------------------------------------------------------

interface Y21GeoObject {
  geometry: { setCoordinates: (coordinates: LatLngPair) => void };
}

interface Y21Map {
  setCenter: (center: LatLngPair, zoom?: number, options?: Record<string, unknown>) => void;
  getCenter: () => LatLngPair;
  destroy: () => void;
  geoObjects: { add: (object: unknown) => void; remove: (object: unknown) => void };
  events: { add: (type: string, handler: () => void) => void };
}

interface Ymaps21 {
  ready: (callback: () => void) => void;
  Map: new (
    container: HTMLElement | string,
    state: Record<string, unknown>,
    options?: Record<string, unknown>,
  ) => Y21Map;
  Placemark: new (
    coordinates: LatLngPair,
    properties: Record<string, unknown>,
    options: Record<string, unknown>,
  ) => Y21GeoObject;
  Polyline: new (
    geometry: LatLngPair[],
    properties: Record<string, unknown>,
    options: Record<string, unknown>,
  ) => unknown;
  templateLayoutFactory: { createClass: (template: string) => unknown };
}

function buildV21(ymaps: Ymaps21): MapsApi {
  return {
    version: "2.1",
    create(container, options) {
      const map = new ymaps.Map(container, {
        center: toLatLngPair(options.center),
        zoom: options.zoom,
        controls: [],
        // v2.1 takes the behaviour list as map state; an empty list is a map that cannot be dragged or zoomed.
        ...(options.interactive ? {} : { behaviors: [] }),
      });

      if (options.onCenterSettled) {
        map.events.add("actionend", () => {
          const centre = map.getCenter();
          options.onCenterSettled?.({ lat: centre[0], lng: centre[1] });
        });
      }

      return {
        setView(center, zoom) {
          map.setCenter(toLatLngPair(center), zoom, { duration: 220 });
        },
        addMarker(point, element, title) {
          // v2.1 draws a custom pin from a layout class, not from a node handed to it. The node is still built
          // in React-land (one styling rule for both versions); here it is rendered as its own markup, which
          // v2.1 inserts into the page DOM - so `var(--primary)` still resolves against the theme.
          const layout = ymaps.templateLayoutFactory.createClass(element.outerHTML);
          const placemark = new ymaps.Placemark(
            toLatLngPair(point),
            { hintContent: title ?? "" },
            { iconLayout: layout, iconOffset: [0, 0] },
          );
          map.geoObjects.add(placemark);
          return {
            move(next) {
              placemark.geometry.setCoordinates(toLatLngPair(next));
            },
            remove() {
              map.geoObjects.remove(placemark);
            },
          };
        },
        addLine(points, color) {
          const line = new ymaps.Polyline(points.map(toLatLngPair), {}, { strokeColor: color, strokeWidth: 4 });
          map.geoObjects.add(line);
          return {
            remove() {
              map.geoObjects.remove(line);
            },
          };
        },
        destroy() {
          map.destroy();
        },
      };
    },
  };
}

// --- v3 --------------------------------------------------------------------------------------------------

export interface YMapEntity {
  update?: (props: Record<string, unknown>) => void;
}

export interface YMapInstance {
  addChild: (child: unknown) => void;
  removeChild: (child: unknown) => void;
  setLocation: (location: Record<string, unknown>) => void;
  destroy: () => void;
}

export interface Ymaps3 {
  ready: Promise<void>;
  YMap: new (element: HTMLElement, props: Record<string, unknown>) => YMapInstance;
  YMapDefaultSchemeLayer: new (props: Record<string, unknown>) => unknown;
  YMapDefaultFeaturesLayer: new (props: Record<string, unknown>) => unknown;
  YMapMarker: new (props: Record<string, unknown>, element?: HTMLElement) => YMapEntity;
  YMapFeature: new (props: Record<string, unknown>) => YMapEntity;
  YMapListener: new (props: Record<string, unknown>) => YMapEntity;
}

function buildV3(api: Ymaps3): MapsApi {
  return {
    version: "v3",
    create(container, options) {
      const map = new api.YMap(container, {
        location: { center: toLngLat(options.center), zoom: options.zoom },
        behaviors: options.interactive ? undefined : [],
      });
      map.addChild(new api.YMapDefaultSchemeLayer({}));
      map.addChild(new api.YMapDefaultFeaturesLayer({}));

      if (options.onCenterSettled) {
        map.addChild(
          new api.YMapListener({
            onActionEnd: (event: { location?: { center?: LngLat } }) => {
              const centre = event?.location?.center;
              if (centre) options.onCenterSettled?.(fromLngLat(centre));
            },
          }),
        );
      }

      return {
        setView(center, zoom) {
          map.setLocation({ center: toLngLat(center), zoom, duration: 220 });
        },
        addMarker(point, element, title) {
          element.title = title ?? "";
          const marker = new api.YMapMarker({ coordinates: toLngLat(point) }, element);
          map.addChild(marker);
          return {
            move(next) {
              marker.update?.({ coordinates: toLngLat(next) });
            },
            remove() {
              map.removeChild(marker);
            },
          };
        },
        addLine(points, color) {
          const feature = new api.YMapFeature({
            geometry: { type: "LineString", coordinates: points.map(toLngLat) },
            style: { stroke: [{ color, width: 4 }] },
          });
          map.addChild(feature);
          return {
            remove() {
              map.removeChild(feature);
            },
          };
        },
        destroy() {
          map.destroy();
        },
      };
    },
  };
}

// --- loading ---------------------------------------------------------------------------------------------

declare global {
  interface Window {
    ymaps?: Ymaps21;
    ymaps3?: Ymaps3;
  }
}

let loader: Promise<MapsApi> | null = null;

function injectScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("the Yandex Maps script could not be loaded"));
    document.head.appendChild(script);
  });
}

function whenV21Ready(api: Ymaps21): Promise<MapsApi> {
  // v2.1 signals readiness through a callback, not a promise.
  return new Promise<MapsApi>((resolve) => api.ready(() => resolve(buildV21(api))));
}

function loadV3(): Promise<MapsApi> {
  if (window.ymaps3) {
    const api = window.ymaps3;
    return api.ready.then(() => buildV3(api));
  }
  return injectScript(`https://api-maps.yandex.ru/v3/?apikey=${encodeURIComponent(MAPS_API_KEY)}&lang=${encodeURIComponent(LANG)}`).then(
    () => {
      const api = window.ymaps3;
      if (!api) throw new Error("ymaps3 did not appear after the script loaded");
      return api.ready.then(() => buildV3(api));
    },
  );
}

function loadV21(): Promise<MapsApi> {
  if (window.ymaps) return whenV21Ready(window.ymaps);
  return injectScript(`https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(MAPS_API_KEY)}&lang=${encodeURIComponent(LANG)}`).then(
    () => {
      const api = window.ymaps;
      if (!api) throw new Error("ymaps did not appear after the script loaded");
      return whenV21Ready(api);
    },
  );
}

/**
 * Load the SDK once per page and resolve with the version-independent adapter.
 *
 * Repeated calls share the same promise: several maps can mount at once (the home canvas and a picker) and
 * inserting the script twice makes Yandex throw.
 */
export function loadYandexMaps(): Promise<MapsApi> {
  if (!MAPS_API_KEY) return Promise.reject(new Error("missing-key"));
  if (loader) return loader;

  loader = MAPS_VERSION === "v3" ? loadV3() : loadV21();

  // A failed load must not be cached: the next screen should be able to try again (a flaky network is not a
  // permanently broken key).
  loader.catch(() => {
    loader = null;
  });
  return loader;
}

// --- geocoding -------------------------------------------------------------------------------------------

/**
 * Turning a pin into an address (and back) is **not** done here.
 *
 * The backend already owns a Yandex Geocoder key and exposes `/geo/reverse-geocode` and `/geo/geocode`, so the
 * client asks our server. That keeps exactly one Yandex key in the browser - the one the map tiles cannot work
 * without - and keeps the geocoding data flow the one that `docs/ops/EXTERNAL_DATA_FLOWS.md` already
 * describes (server → Yandex), instead of opening a second, undocumented one from every user's device.
 *
 * See `src/api/geo.api.ts`.
 */

/** The honest fallback when the geocoder has nothing to say: the coordinates themselves, clearly labelled. */
export function coordinateLabel(point: LatLng): string {
  return `Tanlangan nuqta: ${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}`;
}

// --- deep links ------------------------------------------------------------------------------------------

export function createMapsSearchUrl(lat: number, lng: number): string {
  return `https://yandex.uz/maps/?pt=${encodeURIComponent(`${lng},${lat}`)}&z=16&l=map`;
}

export function createMapsDirectionsUrl(destinationLat: number, destinationLng: number): string {
  return `https://yandex.uz/maps/?rtext=~${encodeURIComponent(`${destinationLat},${destinationLng}`)}&rtt=auto`;
}

/**
 * Resolve a theme token to a literal colour.
 *
 * Everywhere in the DOM a `var(--primary)` simply works, so screens use the token directly. The map is the
 * exception: geometry is drawn by the SDK into its own renderer, which never sees the stylesheet and would
 * silently draw nothing for a `var()`. So the few values that cross into the renderer are resolved here, at
 * call time, which also means they follow a theme switch on the next render rather than freezing at import.
 */
export function cssColor(token: string, fallback: string): string {
  if (typeof window === "undefined" || typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return value || fallback;
}
