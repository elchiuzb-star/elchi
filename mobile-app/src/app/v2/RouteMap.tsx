/**
 * The chosen direction on a map: the confirmed road and its verified stops.
 *
 * Why it matters (spec §6.1, §6.2): an administrative name is not a road. The driver agrees to a **confirmed
 * route version**, and the client's pickup only works if it sits on that road. Showing the line and the stops
 * is how a person can check that before agreeing to anything.
 *
 * Three rules this component keeps:
 * * it draws **only** what the server sent - the encoded geometry of a confirmed route and the coordinates of
 *   verified stops. It never interpolates a road between two city centres the way the v1 preview map did;
 * * without a map key (or with the map blocked) it degrades to the ordered stop list instead of an empty grey
 *   box - the order of the stops is the part the traveller actually needs;
 * * it never claims live position. A driver's live marker belongs to the tracking screen, inside the access
 *   window (§10.6).
 */
import { useMemo } from "react";
import type { StopDTO } from "../../api/v2/marketplace.api";
import { boundsOf, decodePolyline, type LatLng } from "../../utils/polyline";
import { MapLine, MapMarker, useYandexMapsStatus, YandexMap } from "../../components/maps/YandexMap";
import { COLORS } from "../ui/mobile";

export type RouteMapStop = { stop_id: string; seq: number };

const CONTAINER = { width: "100%", height: 240, borderRadius: 12, overflow: "hidden" as const };
const TASHKENT: LatLng = { lat: 41.2995, lng: 69.2401 };

function stopPoints(stops: StopDTO[], order: RouteMapStop[]): Array<{ stop: StopDTO; seq: number }> {
  const byId = new Map(stops.map((stop) => [stop.id, stop]));
  return order
    .map((entry) => ({ stop: byId.get(entry.stop_id), seq: entry.seq }))
    .filter((entry): entry is { stop: StopDTO; seq: number } => Boolean(entry.stop))
    .sort((a, b) => a.seq - b.seq);
}

export function RouteMap({
  geometryPolyline,
  stops,
  routeStops,
  highlight,
  note,
}: {
  /** `RouteVersionDTO.geometry_polyline`; empty string is fine - the stops still draw. */
  geometryPolyline?: string | null;
  /** The corridor's stops (`GET /corridors/{id}/stops`), used for coordinates and names. */
  stops: StopDTO[];
  /** The route's stop order (`RouteVersionDTO.stops`). */
  routeStops: RouteMapStop[];
  /** Stop ids to mark as the traveller's own pickup/dropoff. */
  highlight?: { originStopId?: string; destinationStopId?: string };
  note?: string;
}) {
  const status = useYandexMapsStatus();

  const path = useMemo(() => decodePolyline(geometryPolyline || ""), [geometryPolyline]);
  const ordered = useMemo(() => stopPoints(stops, routeStops), [stops, routeStops]);
  const markerPoints = useMemo(
    () => ordered.map((entry) => ({ lat: entry.stop.point.lat, lng: entry.stop.point.lng })),
    [ordered],
  );
  const center = useMemo(() => {
    const box = boundsOf(path.length ? path : markerPoints);
    if (!box) return TASHKENT;
    return { lat: (box.north + box.south) / 2, lng: (box.east + box.west) / 2 };
  }, [path, markerPoints]);

  const list = (
    <ol style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13, color: COLORS.text }}>
      {ordered.map((entry) => {
        const isEnd =
          entry.stop.id === highlight?.originStopId || entry.stop.id === highlight?.destinationStopId;
        return (
          <li key={entry.stop.id} style={{ fontWeight: isEnd ? 600 : 400 }}>
            {entry.stop.name_uz}
            <span style={{ color: COLORS.muted }}> · {entry.stop.district.name_uz}</span>
          </li>
        );
      })}
    </ol>
  );

  const listOnly = (message: string) => (
    <div
      style={{
        border: `1px dashed ${COLORS.line}`,
        borderRadius: 12,
        padding: 12,
        fontSize: 13,
        color: COLORS.muted,
      }}
    >
      {message}
      {list}
    </div>
  );

  if (status !== "ready") {
    return (
      <div>
        {listOnly(
          status === "loading"
            ? "Xarita yuklanmoqda..."
            : status === "missing-key"
              ? "Xarita kaliti kiritilmagan — yo'nalish bekatlar ro'yxati bilan ko'rsatilmoqda."
              : "Xarita yuklanmadi — yo'nalish bekatlar ro'yxati bilan ko'rsatilmoqda.",
        )}
        {note ? <p style={{ fontSize: 12, color: COLORS.muted, margin: "6px 0 0" }}>{note}</p> : null}
      </div>
    );
  }

  return (
    <div>
      <YandexMap center={center} zoom={7} style={CONTAINER} fallback={(state) => listOnly(state === "loading" ? "Xarita yuklanmoqda..." : "Xarita yuklanmadi.")}>
        {path.length > 1 ? <MapLine points={path} color={COLORS.primary} /> : null}
        {ordered.map((entry) => (
          <MapMarker
            key={entry.stop.id}
            point={{ lat: entry.stop.point.lat, lng: entry.stop.point.lng }}
            label={String(entry.seq)}
            title={`${entry.seq}. ${entry.stop.name_uz} · ${entry.stop.district.name_uz}`}
          />
        ))}
      </YandexMap>
      {list}
      {note ? <p style={{ fontSize: 12, color: COLORS.muted, margin: "6px 0 0" }}>{note}</p> : null}
    </div>
  );
}
