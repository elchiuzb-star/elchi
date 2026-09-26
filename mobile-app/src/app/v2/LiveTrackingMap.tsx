/**
 * The live-position card a booking participant (K4/K8) or a recipient link (K7/K8) sees: a map with the vehicle's
 * last trusted point, how old that point is, and its accuracy.
 *
 * Honesty rules (§9, §10.4): the dot is coloured "live" only while the point is fresh on the server **and** on this
 * device's clock; a delayed or lost signal is named with the time of the last point; no point means no dot. The
 * subject is the vehicle carrying the booking - the driver's phone - never "the parcel" (§10.3).
 */
import { MapMarker, MapVehicleDot, YandexMap } from "../../components/maps/YandexMap";
import { effectiveFreshness, type Freshness } from "../gpsOutbox";
import { translate } from "../../i18n";
import { formatDateTime } from "../../utils/v2Format";
import { cls } from "../ui/mobile";

type LastPoint = { lat: number; lng: number; accuracy_m: number; low_accuracy: boolean; captured_at: string };

const TONE: Record<Freshness, string> = {
  fresh: "bg-success",
  delayed: "bg-amber-500",
  lost: "bg-destructive",
  no_data: "bg-slate-400",
};

const FRESHNESS_KEY = {
  fresh: "liveTracking.freshness.fresh",
  delayed: "liveTracking.freshness.delayed",
  lost: "liveTracking.freshness.lost",
  no_data: "liveTracking.freshness.no_data",
} as const;

export function freshnessText(freshness: Freshness): string {
  return translate(FRESHNESS_KEY[freshness]);
}

/** The map alone: the vehicle's dot (and the pickup pin when known); coordinates as text without a map key. */
export function VehicleMap(props: { point: { lat: number; lng: number }; live: boolean; pickup?: { lat: number; lng: number } | null }) {
  const { point } = props;
  return (
    <div className="h-[220px] overflow-hidden rounded-[14px] border border-border" data-testid="vehicle-map">
      <YandexMap
        center={{ lat: point.lat, lng: point.lng }}
        zoom={14}
        interactive={false}
        style={{ width: "100%", height: "100%" }}
        fallback={(status) => (
          <div className="flex h-full flex-col items-center justify-center gap-1 px-4 text-center text-[13px] text-muted-foreground">
            <span>
              {status === "missing-key"
                ? translate("maps.keyMissing")
                : status === "loading"
                  ? translate("maps.loading")
                  : translate("maps.loadFailed")}
            </span>
            <span className="font-mono text-foreground">
              {point.lat.toFixed(5)}, {point.lng.toFixed(5)}
            </span>
          </div>
        )}
      >
        {props.pickup && <MapMarker point={props.pickup} label="A" title={translate("maps.pickupPlace")} />}
        <MapVehicleDot point={{ lat: point.lat, lng: point.lng }} live={props.live} title={translate("liveTracking.vehicle")} />
      </YandexMap>
    </div>
  );
}

export function LiveTrackingMap(props: {
  data: { freshness: Freshness; last_point?: LastPoint | null };
  /** The agreed pickup point, when the screen knows it. */
  pickup?: { lat: number; lng: number } | null;
  transport?: "idle" | "ws" | "poll";
  now?: Date;
}) {
  const point = props.data.last_point ?? null;
  const freshness = effectiveFreshness(props.data, props.now ?? new Date());
  const live = freshness === "fresh";

  return (
    <div className="space-y-2" data-testid="live-tracking">
      <div className="flex items-center gap-2 text-[14px] font-medium text-foreground">
        {/* The one thing allowed to pulse, and only while the fix really is current (AC27/AC28). */}
        <span className={cls("h-2.5 w-2.5 shrink-0 rounded-full", TONE[freshness], live && "el-live-dot")} />
        <span data-testid="live-freshness">{freshnessText(freshness)}</span>
      </div>

      {point ? (
        <>
          <VehicleMap point={point} live={live} pickup={props.pickup} />
          <p className="text-[13px] text-muted-foreground" data-testid="live-last-point">
            {translate("liveTracking.lastPoint", { time: formatDateTime(point.captured_at) })}
            {" · "}±{point.accuracy_m} m{point.low_accuracy ? ` · ${translate("liveTracking.lowAccuracy")}` : ""}
          </p>
          {(freshness === "delayed" || freshness === "lost") && (
            <p className="text-[13px] leading-5 text-muted-foreground" data-testid="live-stale">
              {translate(freshness === "lost" ? "liveTracking.lostHint" : "liveTracking.delayedHint")}
            </p>
          )}
        </>
      ) : (
        <p className="text-[13px] leading-5 text-muted-foreground" data-testid="live-no-point">
          {translate("liveTracking.noPoint")}
        </p>
      )}

      <p className="text-[12px] leading-5 text-muted-foreground">
        {translate("liveTracking.source")}
        {props.transport === "poll" ? ` ${translate("liveTracking.polling")}` : ""}
      </p>
    </div>
  );
}
