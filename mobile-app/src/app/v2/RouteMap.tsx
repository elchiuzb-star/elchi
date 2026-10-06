/**
 * The chosen direction on a map: the confirmed road and the traveller's own two places, A and B.
 *
 * Why it matters (spec §6.1, §6.2): an administrative name is not a road. The driver agrees to a **confirmed
 * route version**, and the client's pickup only works if it sits on that road. Showing the line and the two marked
 * places is how a person can check that before agreeing to anything.
 *
 * Rules this component keeps:
 * * it draws **only** what the server sent and what the person marked - the encoded geometry of a confirmed route
 *   and the A/B points. It never interpolates a road between two city centres the way the v1 preview map did;
 * * Q158 (ADR-0027): ELCHI works point A -> point B, so the route's internal nodes are never drawn or listed;
 * * without a map key (or with the map blocked) it degrades to the two places in words instead of an empty box;
 * * it never claims live position. A driver's live marker belongs to the tracking screen (§10.6).
 */
import { useMemo } from "react";
import { boundsOf, decodePolyline, type LatLng } from "../../utils/polyline";
import { MapLine, MapMarker, useYandexMapsStatus, YandexMap } from "../../components/maps/YandexMap";
import { COLORS } from "../ui/mobile";
import { translate } from "../../i18n";

/** One of the traveller's own ends: where it is and what to call it (an address or a district). */
export type RouteMapPoint = { lat: number; lng: number; name: string };

const CONTAINER = { width: "100%", height: 240, borderRadius: 12, overflow: "hidden" as const };
const TASHKENT: LatLng = { lat: 41.2995, lng: 69.2401 };

export function RouteMap({
  geometryPolyline,
  pointA,
  pointB,
  note,
}: {
  /** `RouteVersionDTO.geometry_polyline`; empty string is fine - the two places still draw. */
  geometryPolyline?: string | null;
  pointA?: RouteMapPoint | null;
  pointB?: RouteMapPoint | null;
  note?: string;
}) {
  const status = useYandexMapsStatus();

  const path = useMemo(() => decodePolyline(geometryPolyline || ""), [geometryPolyline]);
  const ends = useMemo(
    () => [
      pointA ? { key: "A", point: pointA } : null,
      pointB ? { key: "B", point: pointB } : null,
    ].filter((entry): entry is { key: string; point: RouteMapPoint } => Boolean(entry)),
    [pointA, pointB],
  );
  const center = useMemo(() => {
    const box = boundsOf(path.length ? path : ends.map((entry) => ({ lat: entry.point.lat, lng: entry.point.lng })));
    if (!box) return TASHKENT;
    return { lat: (box.north + box.south) / 2, lng: (box.east + box.west) / 2 };
  }, [path, ends]);

  const list = (
    <ol style={{ margin: "8px 0 0", paddingLeft: 0, listStyle: "none", fontSize: 13, color: COLORS.text }}>
      {ends.map((entry) => (
        <li key={entry.key} style={{ fontWeight: 600 }}>
          {entry.key} · <span style={{ fontWeight: 400 }}>{entry.point.name}</span>
        </li>
      ))}
    </ol>
  );

  const listOnly = (message: string) => (
    <div style={{ border: `1px dashed ${COLORS.line}`, borderRadius: 12, padding: 12, fontSize: 13, color: COLORS.muted }}>
      {message}
      {list}
    </div>
  );

  if (status !== "ready") {
    return (
      <div>
        {listOnly(
          status === "loading"
            ? translate("routeMap.loading")
            : status === "missing-key"
              ? translate("routeMap.missingKey")
              : translate("routeMap.failedList"),
        )}
        {note ? <p style={{ fontSize: 12, color: COLORS.muted, margin: "6px 0 0" }}>{note}</p> : null}
      </div>
    );
  }

  return (
    <div>
      <YandexMap center={center} zoom={7} style={CONTAINER} fallback={(state) => listOnly(state === "loading" ? translate("routeMap.loading") : translate("routeMap.failed"))}>
        {path.length > 1 ? <MapLine points={path} color={COLORS.primary} /> : null}
        {ends.map((entry) => (
          <MapMarker
            key={entry.key}
            point={{ lat: entry.point.lat, lng: entry.point.lng }}
            label={entry.key}
            title={`${entry.key} · ${entry.point.name}`}
          />
        ))}
      </YandexMap>
      {list}
      {note ? <p style={{ fontSize: 12, color: COLORS.muted, margin: "6px 0 0" }}>{note}</p> : null}
    </div>
  );
}
