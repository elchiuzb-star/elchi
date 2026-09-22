/**
 * A small declarative wrapper over the imperative Yandex Maps API.
 *
 * Yandex ships no official React binding, and adding an unvetted community one would put a third party between
 * this app and the map for no gain. Instead the imperative lifecycle is confined here: `YandexMap` owns the map
 * handle and hands it to its children through context, and `MapMarker` / `MapLine` attach and detach themselves
 * the way React components expect to.
 *
 * This file talks only to the version-independent adapter in `./yandex` (`MapsApi`, `MapHandle`), so which SDK
 * version is actually loaded - v2.1 today, v3 when a v3 key exists - is not a concern of any component.
 *
 * Every map in this app renders **something** without a key: the caller passes `fallback`, because a grey box
 * is not a state a person can act on, and the screens here always have the underlying facts (an address, a
 * stop list) to show instead.
 */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import {
  MAPS_API_KEY,
  cssColor,
  loadYandexMaps,
  type LatLng,
  type LineHandle,
  type MapHandle,
  type MapsStatus,
  type MarkerHandle,
} from "./yandex";

const MapContext = createContext<MapHandle | null>(null);

export function useYandexMapsStatus(): MapsStatus {
  const [status, setStatus] = useState<MapsStatus>(MAPS_API_KEY ? "loading" : "missing-key");
  useEffect(() => {
    if (!MAPS_API_KEY) return;
    let active = true;
    loadYandexMaps()
      .then(() => active && setStatus("ready"))
      .catch(() => active && setStatus("error"));
    return () => {
      active = false;
    };
  }, []);
  return status;
}

export interface YandexMapProps {
  center: LatLng;
  zoom: number;
  children?: ReactNode;
  className?: string;
  style?: React.CSSProperties;
  /** Shown instead of the map when there is no key or the script did not load. */
  fallback: (status: Exclude<MapsStatus, "ready">) => ReactNode;
  /** Pan/zoom off: a preview map that scrolls under a finger steals the page's scroll. */
  interactive?: boolean;
  /** Fires after the map settles following a user gesture - the point-picker reads the centre from it. */
  onCenterSettled?: (center: LatLng) => void;
}

export function YandexMap(props: YandexMapProps) {
  const holder = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapHandle | null>(null);
  const [map, setMap] = useState<MapHandle | null>(null);
  const status = useYandexMapsStatus();
  const settledRef = useRef(props.onCenterSettled);
  settledRef.current = props.onCenterSettled;

  useEffect(() => {
    if (status !== "ready" || !holder.current || mapRef.current) return;
    let cancelled = false;

    void loadYandexMaps().then((api) => {
      if (cancelled || !holder.current || mapRef.current) return;
      const handle = api.create(holder.current, {
        center: props.center,
        zoom: props.zoom,
        interactive: props.interactive !== false,
        onCenterSettled: settledRef.current ? (centre) => settledRef.current?.(centre) : undefined,
      });
      mapRef.current = handle;
      setMap(handle);
    });

    return () => {
      cancelled = true;
    };
  }, [status]);

  // Unmount is its own effect so that a re-render never tears the map down and rebuilds it.
  useEffect(
    () => () => {
      mapRef.current?.destroy();
      mapRef.current = null;
    },
    [],
  );

  useEffect(() => {
    mapRef.current?.setView(props.center, props.zoom);
  }, [props.center.lat, props.center.lng, props.zoom]);

  if (status !== "ready") return <>{props.fallback(status)}</>;

  return (
    <div ref={holder} className={props.className} style={props.style}>
      {map ? <MapContext.Provider value={map}>{props.children}</MapContext.Provider> : null}
    </div>
  );
}

/** A numbered/lettered pin in the product's primary colour. */
export function MapMarker({ point, label, title }: { point: LatLng; label?: string; title?: string }) {
  const map = useContext(MapContext);
  const markerRef = useRef<MarkerHandle | null>(null);

  useEffect(() => {
    if (!map) return;
    const element = document.createElement("div");
    element.style.cssText =
      "transform:translate(-50%,-100%);display:flex;align-items:center;justify-content:center;" +
      // A real DOM node on the page, so the theme variables resolve here exactly as they do in JSX.
      "width:28px;height:28px;border-radius:50% 50% 50% 2px;rotate:45deg;background:var(--primary);" +
      "border:2px solid var(--card);box-shadow:0 2px 6px rgba(15,23,42,.35);" +
      "color:var(--primary-foreground);font:600 12px/1 Inter,sans-serif;";
    if (label) {
      const glyph = document.createElement("span");
      glyph.textContent = label;
      glyph.style.cssText = "rotate:-45deg;";
      element.appendChild(glyph);
    }
    const marker = map.addMarker(point, element, title);
    markerRef.current = marker;
    return () => {
      marker.remove();
      markerRef.current = null;
    };
  }, [map, label, title]);

  useEffect(() => {
    markerRef.current?.move(point);
  }, [point.lat, point.lng]);

  return null;
}

/** A route line. The points come from the server's geometry; this never invents one. */
export function MapLine({ points, color }: { points: LatLng[]; color?: string }) {
  const map = useContext(MapContext);
  // Resolved, not a `var()`: the line is drawn by the SDK, which cannot read the stylesheet.
  const stroke = color ?? cssColor("--primary", "#2258E6");

  useEffect(() => {
    if (!map || points.length < 2) return;
    let line: LineHandle | null = map.addLine(points, stroke);
    return () => {
      line?.remove();
      line = null;
    };
  }, [map, stroke, points]);

  return null;
}

/** The fixed centre pin of a point picker: the map moves under it, the pin does not move (Q88 picker). */
export function CentrePin() {
  return (
    <div className="pointer-events-none absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-full">
      <div className="h-7 w-7 rotate-45 rounded-[50%_50%_50%_2px] border-2 border-card bg-primary shadow-[0_2px_6px_rgba(15,23,42,0.35)]" />
    </div>
  );
}
