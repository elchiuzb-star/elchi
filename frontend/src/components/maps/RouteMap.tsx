import { useEffect, useRef, useState } from "react";
import { GoogleMap, Polyline } from "@react-google-maps/api";
import { AdvancedMapMarker } from "./AdvancedMapMarker";
import { googleMapsMapId } from "./googleMapsConfig";
import { useMapsLoader } from "./useMapsLoader";
import { ROUTE_END, gradientSegments, sampleLine } from "./routeStyle";

const UZBEKISTAN = { lat: 41.3775, lng: 64.5853 };

const geocodeCache = new Map<string, google.maps.LatLngLiteral | null>();

function geocodeName(name: string): Promise<google.maps.LatLngLiteral | null> {
  return new Promise((resolve) => {
    if (!name) { resolve(null); return; }
    if (geocodeCache.has(name)) { resolve(geocodeCache.get(name) ?? null); return; }
    if (!window.google?.maps) { resolve(null); return; }
    const geocoder = new window.google.maps.Geocoder();
    geocoder.geocode({ address: `${name}, Uzbekistan`, region: "UZ" }, (results, status) => {
      const loc = status === "OK" ? results?.[0]?.geometry?.location : undefined;
      const point = loc ? { lat: loc.lat(), lng: loc.lng() } : null;
      geocodeCache.set(name, point);
      resolve(point);
    });
  });
}

type RouteMapProps = {
  fromName?: string | null;
  toName?: string | null;
  /** Optional exact coordinates that skip geocoding. */
  fromPoint?: google.maps.LatLngLiteral | null;
  toPoint?: google.maps.LatLngLiteral | null;
  className?: string;
  height?: number | string;
  interactive?: boolean;
};

/** Read-only map that draws a route between two cities (geocoded by name). */
export function RouteMap({ fromName, toName, fromPoint, toPoint, className = "", height = "100%", interactive = false }: RouteMapProps) {
  const { isLoaded, loadError, hasKey } = useMapsLoader();
  const [from, setFrom] = useState<google.maps.LatLngLiteral | null>(fromPoint ?? null);
  const [to, setTo] = useState<google.maps.LatLngLiteral | null>(toPoint ?? null);
  const mapRef = useRef<google.maps.Map | null>(null);

  useEffect(() => {
    if (fromPoint) { setFrom(fromPoint); return; }
    if (isLoaded && fromName) geocodeName(fromName).then(setFrom);
  }, [isLoaded, fromName, fromPoint]);

  useEffect(() => {
    if (toPoint) { setTo(toPoint); return; }
    if (isLoaded && toName) geocodeName(toName).then(setTo);
  }, [isLoaded, toName, toPoint]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (from && to) {
      const bounds = new window.google.maps.LatLngBounds();
      bounds.extend(from);
      bounds.extend(to);
      map.fitBounds(bounds, 48);
    } else if (from || to) {
      map.setCenter((from ?? to)!);
      map.setZoom(9);
    }
  }, [from, to]);

  if (!hasKey || loadError || !isLoaded) {
    return <div className={`bg-[#1a2234] ${className}`} style={{ height }} />;
  }

  return (
    <div className={className} style={{ height }}>
      <GoogleMap
        mapContainerStyle={{ width: "100%", height: "100%" }}
        center={from ?? to ?? UZBEKISTAN}
        zoom={from || to ? 9 : 6}
        onLoad={(m) => { mapRef.current = m; }}
        onUnmount={() => { mapRef.current = null; }}
        options={{
          disableDefaultUI: true,
          clickableIcons: false,
          gestureHandling: interactive ? "greedy" : "none",
          keyboardShortcuts: false,
          mapId: googleMapsMapId,
        }}
      >
        {from && to && (
          <>
            <Polyline path={[from, to]} options={{ geodesic: true, strokeColor: ROUTE_END, strokeOpacity: 0.16, strokeWeight: 10, clickable: false, zIndex: 1 }} />
            {gradientSegments(sampleLine(from, to)).map((seg, i) => (
              <Polyline key={i} path={seg.path} options={{ strokeColor: seg.color, strokeOpacity: 1, strokeWeight: 4, clickable: false, zIndex: 2 }} />
            ))}
          </>
        )}
        {from && <AdvancedMapMarker position={from} variant="origin" title={fromName ?? "From"} />}
        {to && <AdvancedMapMarker position={to} variant="destination" title={toName ?? "To"} />}
      </GoogleMap>
    </div>
  );
}
