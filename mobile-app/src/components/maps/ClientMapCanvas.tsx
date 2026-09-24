import { useMemo } from "react";

import { boundsOf, decodePolyline, type LatLng } from "../../utils/polyline";
import { MapLine, MapMarker, YandexMap } from "./YandexMap";
import { TASHKENT, readPoint } from "./yandex";
import { translate } from "../../i18n";

type ClientMapCanvasProps = {
  pickupLat?: number | string | null;
  pickupLng?: number | string | null;
  dropoffLat?: number | string | null;
  dropoffLng?: number | string | null;
  /**
   * The confirmed road this direction resolved onto, encoded (`DirectionPreviewDTO.route_polyline`).
   *
   * It is the **whole** corridor, often two thousand kilometres of it, so it is clipped below to the part
   * between the two marked places. Drawing all of it would answer a question nobody asked and would make
   * the two markers disappear into a country-wide line.
   */
  routePolyline?: string | null;
};

/** Index of the path vertex closest to a point. Squared degrees are enough to rank candidates. */
function nearestIndex(path: LatLng[], point: LatLng): number {
  let best = 0;
  let bestDistance = Infinity;
  path.forEach((vertex, index) => {
    const distance = (vertex.lat - point.lat) ** 2 + (vertex.lng - point.lng) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  return best;
}

/**
 * The stretch of road between the two marked places, with the places themselves at its ends.
 *
 * The clip is by nearest vertex rather than a true projection: this is the line under a sheet, and a vertex
 * either side of the exact projection is invisible at this scale. What it must never do is draw a road the
 * trip does not use, which is why it is clipped at all.
 */
function legPath(path: LatLng[], pickup: LatLng | null, dropoff: LatLng | null): LatLng[] {
  if (path.length < 2 || !pickup || !dropoff) return [];
  const from = nearestIndex(path, pickup);
  const to = nearestIndex(path, dropoff);
  const [start, end] = from <= to ? [from, to] : [to, from];
  const middle = path.slice(start, end + 1);
  if (!middle.length) return [pickup, dropoff];
  return from <= to ? [pickup, ...middle, dropoff] : [pickup, ...middle.reverse(), dropoff];
}

/** Rough web-mercator fit: the zoom at which a span still fits the viewport. */
function zoomForSpan(latSpan: number, lngSpan: number): number {
  const span = Math.max(latSpan, lngSpan / 1.6, 0.0005);
  const zoom = Math.log2(360 / span) - 0.4;
  return Math.max(4, Math.min(15, zoom));
}

/** The map behind the client's home sheet. Decorative until two places are marked - never load-bearing. */
export function ClientMapCanvas({
  pickupLat,
  pickupLng,
  dropoffLat,
  dropoffLng,
  routePolyline,
}: ClientMapCanvasProps) {
  const pickup = readPoint(pickupLat, pickupLng);
  const dropoff = readPoint(dropoffLat, dropoffLng);

  const leg = useMemo(
    () => legPath(decodePolyline(routePolyline || ""), pickup, dropoff),
    [routePolyline, pickup?.lat, pickup?.lng, dropoff?.lat, dropoff?.lng],
  );

  const view = useMemo(() => {
    const points = leg.length ? leg : [pickup, dropoff].filter((item): item is LatLng => item !== null);
    const box = boundsOf(points);
    if (!box) return { center: pickup ?? dropoff ?? TASHKENT, zoom: pickup || dropoff ? 14 : 12 };
    return {
      center: { lat: (box.north + box.south) / 2, lng: (box.east + box.west) / 2 },
      zoom: zoomForSpan(box.north - box.south, box.east - box.west),
    };
  }, [leg, pickup?.lat, pickup?.lng, dropoff?.lat, dropoff?.lng]);

  return (
    <YandexMap
      center={view.center}
      zoom={view.zoom}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      fallback={(status) =>
        status === "loading" ? (
          <div className="absolute inset-0 bg-accent" />
        ) : (
          <div className="absolute inset-0 bg-border">
            <div className="absolute inset-0 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--feruza)_16%,var(--card))_0%,var(--background)_45%,var(--accent)_100%)]" />
            <div className="absolute left-5 right-5 top-24 rounded-[18px] bg-card/90 p-4 shadow-lg">
              <p className="text-[15px] font-semibold text-foreground">
                {status === "missing-key" ? translate("maps.keyMissing") : translate("maps.loadFailed")}
              </p>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                {translate("maps.manualFallbackHint")}
              </p>
            </div>
          </div>
        )
      }
    >
      {leg.length > 1 && <MapLine points={leg} />}
      {pickup && <MapMarker point={pickup} label="A" title={translate("maps.pickupPlace")} />}
      {dropoff && <MapMarker point={dropoff} label="B" title={translate("maps.dropoffPlace")} />}
    </YandexMap>
  );
}
