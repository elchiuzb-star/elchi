/**
 * The driver's GPS status, shown above every driver screen while a trip is running (spec §10.3-§10.5, Q148).
 *
 * It says exactly what is happening and nothing more: "sending" only while this phone gave a position in the last
 * 30 seconds; waiting points are counted; points that will never arrive are counted; a hidden tab is called out,
 * because a browser may stop giving positions then. There is no "GPS faol" badge (§10.5) - the web client is a
 * foreground publisher, and the note under the status says so.
 */
import { useEffect, useState, useSyncExternalStore } from "react";

import { FRESH_MAX_AGE_SECONDS } from "../gpsOutbox";
import { translate } from "../../i18n";
import { formatTime } from "../../utils/v2Format";
import { cls } from "../ui/mobile";
import { LOW_BATTERY_PCT, driverTracker, type DriverTracker, type TrackerSnapshot } from "./driverTracker";

/** A visible page with no position for this long gets the "check GPS / battery saver" hint. */
const STALLED_AFTER_S = 60;

const ERROR_KEY: Record<string, "driverTracking.error.disabled" | "driverTracking.error.notRunning" | "driverTracking.error.network"> = {
  FEATURE_DISABLED: "driverTracking.error.disabled",
  INVALID_STATE_TRANSITION: "driverTracking.error.notRunning",
  NETWORK_ERROR: "driverTracking.error.network",
};

function useTracker(tracker: DriverTracker): TrackerSnapshot {
  return useSyncExternalStore(tracker.subscribe, tracker.getSnapshot, tracker.getSnapshot);
}

/** Re-render every few seconds so "sending" turns into "waiting" when the phone goes quiet. */
function useNow(periodMs: number, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), periodMs);
    return () => window.clearInterval(timer);
  }, [periodMs, active]);
  return now;
}

function Button(props: { children: string; onClick: () => void; tone?: "primary" | "plain" }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className={cls(
        "el-press h-8 shrink-0 rounded-[10px] px-3 text-[12px] font-semibold",
        props.tone === "primary" ? "bg-primary text-primary-foreground" : "border border-border bg-card text-foreground",
      )}
    >
      {props.children}
    </button>
  );
}

export function DriverTrackingBar(props: { tripId: string | null; tracker?: DriverTracker }) {
  const tracker = props.tracker ?? driverTracker();
  const state = useTracker(tracker);
  const now = useNow(5_000, state.phase === "active");
  const tripId = props.tripId ?? state.tripId;
  const start = () => tripId && void tracker.start(tripId);

  // Nothing to say: no running trip and no publisher that just ended with a reason worth reading.
  const quietEnd = state.phase === "ended" && (state.endReason === "stopped" || state.endReason === "trip_finished");
  if (!props.tripId && (state.phase === "idle" || quietEnd)) return null;

  let dot = "bg-slate-400";
  let title: string;
  const notes: string[] = [];
  let action: { label: string; run: () => void; tone?: "primary" | "plain" } | null = null;

  switch (state.phase) {
    case "idle":
      title = translate("driverTracking.idle");
      notes.push(translate("driverTracking.idleHint"));
      // The browser shows its own question on the first start; the driver should know to answer "Allow".
      if (state.permission !== "granted") notes.push(translate("driverTracking.permissionPrompt"));
      action = { label: translate("driverTracking.start"), run: start, tone: "primary" };
      break;
    case "starting":
      title = translate("driverTracking.starting");
      break;
    case "active": {
      const ageS = state.lastFixAt === null ? null : (now - state.lastFixAt) / 1000;
      const sending = ageS !== null && ageS <= FRESH_MAX_AGE_SECONDS;
      dot = sending ? "bg-success el-live-dot" : "bg-amber-500";
      title = sending
        ? translate("driverTracking.sending")
        : state.lastFixAt === null
          ? translate("driverTracking.waitingFirstFix")
          : translate("driverTracking.waitingFix", { time: formatTime(new Date(state.lastFixAt).toISOString()) });
      if (state.lastSentAt !== null) {
        notes.push(translate("driverTracking.lastSent", { time: formatTime(new Date(state.lastSentAt).toISOString()) }));
      }
      if (state.lastAccuracyM !== null && state.lastAccuracyM > 100) {
        notes.push(translate("driverTracking.lowAccuracy", { meters: String(state.lastAccuracyM) }));
      }
      if (state.queued > 0 && state.offline) notes.push(translate("driverTracking.queuedOffline", { count: String(state.queued) }));
      if (state.hidden) notes.push(translate("driverTracking.hidden"));
      if (!state.hidden && ageS !== null && ageS > STALLED_AFTER_S) notes.push(translate("driverTracking.stalled"));
      if (state.lastGap) {
        notes.push(
          translate(state.lastGap.cause === "background" ? "driverTracking.gapBackground" : "driverTracking.gapNoFix", {
            from: formatTime(new Date(state.lastGap.from).toISOString()),
            to: formatTime(new Date(state.lastGap.to).toISOString()),
          }),
        );
      }
      if (state.battery && !state.battery.charging && state.battery.pct <= LOW_BATTERY_PCT) {
        notes.push(translate("driverTracking.lowBattery", { pct: String(state.battery.pct) }));
      }
      if (!state.wakeLock) notes.push(translate("driverTracking.noWakeLock"));
      action = { label: translate("driverTracking.stop"), run: () => void tracker.stop() };
      break;
    }
    case "permission_denied":
      dot = "bg-destructive";
      title = translate("driverTracking.permissionDenied");
      notes.push(translate("driverTracking.permissionHint"));
      action = { label: translate("driverTracking.retry"), run: start, tone: "primary" };
      break;
    case "unavailable":
      dot = "bg-destructive";
      title = translate(state.unavailableReason === "insecure" ? "driverTracking.insecure" : "driverTracking.unavailable");
      break;
    case "error":
      dot = "bg-destructive";
      title = translate(ERROR_KEY[state.errorCode ?? ""] ?? "driverTracking.error.generic");
      action = { label: translate("driverTracking.retry"), run: start, tone: "primary" };
      break;
    case "ended":
    default:
      title =
        state.endReason === "superseded"
          ? translate("driverTracking.superseded")
          : state.endReason === "unauthorized"
            ? translate("driverTracking.unauthorized")
            : state.endReason === "closed"
              ? translate("driverTracking.closed")
              : translate("driverTracking.stopped");
      if (props.tripId) {
        action = {
          label: translate(state.endReason === "superseded" ? "driverTracking.takeOver" : "driverTracking.start"),
          run: start,
          tone: "primary",
        };
      }
      break;
  }
  if (state.dropped > 0) notes.push(translate("driverTracking.dropped", { count: String(state.dropped) }));

  return (
    <div className="shrink-0 border-b border-border bg-card px-5 py-2" data-testid="driver-tracking-bar" role="status">
      <div className="flex items-center gap-3">
        <span className={cls("h-2.5 w-2.5 shrink-0 rounded-full", dot)} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold leading-5 text-foreground" data-testid="driver-tracking-title">{title}</p>
          {notes.map((note) => (
            <p key={note} className="text-[11px] leading-4 text-muted-foreground">{note}</p>
          ))}
          {(state.phase === "active" || state.phase === "idle") && (
            <p className="text-[11px] leading-4 text-muted-foreground">{translate("driverTracking.foregroundOnly")}</p>
          )}
        </div>
        {action && <Button onClick={action.run} tone={action.tone}>{action.label}</Button>}
      </div>
    </div>
  );
}
