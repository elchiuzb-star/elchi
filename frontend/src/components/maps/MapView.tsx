import { useCallback, useEffect, useState } from "react";
import { GoogleMap, Polyline } from "@react-google-maps/api";
import { AdvancedMapMarker } from "./AdvancedMapMarker";
import { googleMapsMapId } from "./googleMapsConfig";
import { useMapsLoader, toPoint } from "./useMapsLoader";
import { ROUTE_END, gradientSegments } from "./routeStyle";

const TASHKENT = { lat: 41.2995, lng: 69.2401 };

/** Smooth quadratic-bezier curve between two points — fallback when Directions is unavailable. */
function curvedPath(a: google.maps.LatLngLiteral, b: google.maps.LatLngLiteral, segments = 32): google.maps.LatLngLiteral[] {
  const mid = { lat: (a.lat + b.lat) / 2, lng: (a.lng + b.lng) / 2 };
  const dLat = b.lat - a.lat;
  const dLng = b.lng - a.lng;
  const curvature = 0.18;
  const ctrl = { lat: mid.lat - dLng * curvature, lng: mid.lng + dLat * curvature };
  const points: google.maps.LatLngLiteral[] = [];
  for (let i = 0; i <= segments; i += 1) {
    const t = i / segments;
    const inv = 1 - t;
    points.push({
      lat: inv * inv * a.lat + 2 * inv * t * ctrl.lat + t * t * b.lat,
      lng: inv * inv * a.lng + 2 * inv * t * ctrl.lng + t * t * b.lng,
    });
  }
  return points;
}

type MapViewProps = {
  pickupLat?: number | string | null;
  pickupLng?: number | string | null;
  dropoffLat?: number | string | null;
  dropoffLng?: number | string | null;
  userLat?: number | string | null;
  userLng?: number | string | null;
  className?: string;
  height?: number | string;
  onReady?: (map: google.maps.Map) => void;
};

/** Read-only Google Map with pickup (A) and dropoff (B) markers. */
export function MapView({ pickupLat, pickupLng, dropoffLat, dropoffLng, userLat, userLng, className = "", height = "100%", onReady }: MapViewProps) {
  const { isLoaded, loadError, hasKey } = useMapsLoader();
  const pickup = toPoint(pickupLat, pickupLng);
  const dropoff = toPoint(dropoffLat, dropoffLng);
  const user = toPoint(userLat, userLng);
  const [routePath, setRoutePath] = useState<google.maps.LatLngLiteral[] | null>(null);

  // Draw the road route between pickup (A) and dropoff (B); fall back to a smooth curve.
  useEffect(() => {
    if (!isLoaded || !pickup || !dropoff) { setRoutePath(null); return; }
    let cancelled = false;
    const service = new google.maps.DirectionsService();
    service.route(
      { origin: pickup, destination: dropoff, travelMode: google.maps.TravelMode.DRIVING },
      (result, status) => {
        if (cancelled) return;
        if (status === "OK" && result?.routes?.[0]?.overview_path?.length) {
          setRoutePath(result.routes[0].overview_path.map((p) => ({ lat: p.lat(), lng: p.lng() })));
        } else {
          setRoutePath(curvedPath(pickup, dropoff));
        }
      },
    );
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, pickup?.lat, pickup?.lng, dropoff?.lat, dropoff?.lng]);

  const onLoad = useCallback((map: google.maps.Map) => {
    if (pickup && dropoff) {
      const bounds = new window.google.maps.LatLngBounds();
      bounds.extend(pickup);
      bounds.extend(dropoff);
      map.fitBounds(bounds, 60);
    } else if (pickup || dropoff) {
      map.setCenter((pickup ?? dropoff)!);
      map.setZoom(14);
    }
    onReady?.(map);
  }, [pickup, dropoff, onReady]);

  const fallback = (msg: string) => (
    <div className={`flex items-center justify-center bg-secondary/60 text-xs text-muted-foreground ${className}`} style={{ height }}>{msg}</div>
  );
  if (!hasKey) return fallback("Google Maps API kaliti sozlanmagan");
  if (loadError) return fallback("Xarita yuklanmadi");
  if (!isLoaded) return (
    <div className={`flex items-center justify-center bg-secondary/60 ${className}`} style={{ height }}>
      <span className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/>
    </div>
  );

  return (
    <div className={className} style={{ height }}>
      <GoogleMap
        mapContainerStyle={{ width: "100%", height: "100%" }}
        center={pickup ?? dropoff ?? TASHKENT}
        zoom={12}
        onLoad={onLoad}
        options={{
          clickableIcons: false,
          fullscreenControl: false,
          mapTypeControl: false,
          streetViewControl: false,
          mapId: googleMapsMapId,
          gestureHandling: "greedy",
        }}
      >
        {routePath && (
          <>
            <Polyline path={routePath} options={{ strokeColor: ROUTE_END, strokeOpacity: 0.16, strokeWeight: 12, clickable: false, zIndex: 1 }} />
            {gradientSegments(routePath).map((seg, i) => (
              <Polyline key={i} path={seg.path} options={{ strokeColor: seg.color, strokeOpacity: 1, strokeWeight: 5, clickable: false, zIndex: 2 }} />
            ))}
          </>
        )}
        {pickup && <AdvancedMapMarker position={pickup} variant="origin" title="Olib ketish joyi" />}
        {dropoff && <AdvancedMapMarker position={dropoff} variant="destination" title="Yetkazish joyi" />}
        {user && <AdvancedMapMarker position={user} title="Mening joylashuvim" />}
      </GoogleMap>
    </div>
  );
}
