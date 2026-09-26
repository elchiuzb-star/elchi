/**
 * The driver's GPS publisher (spec §10.3, Q148): browser fixes -> local outbox -> `points:batch`, for one running trip.
 *
 * Foreground only. A web page keeps receiving positions while it is open with the screen on; a hidden tab, a locked
 * phone or a closed browser stops it, and the screen says so instead of claiming "GPS faol" (§10.5). The Screen Wake
 * Lock API is asked for while publishing so the phone does not lock itself mid-trip - where it exists.
 *
 * Lifecycle:
 *   start(trip)  - flush what an earlier run left in storage to its own session, open a new writer session (K1 -
 *                  a restarted device gets a new session, §10.4), then watch the position and send every
 *                  `recommended_interval_s`. Points wait in the outbox across network failures and page reloads.
 *   stop()       - the driver ends it: last flush, K3, forget the outbox.
 *   finishTrip() - the trip is completing: flush first (so the last kilometres are not lost), then the server
 *                  closes the session itself as part of `complete`.
 * The server may end the session on its own - another device took over (`superseded`) or the trip ended
 * (`closed`); the publisher stops and says which.
 *
 * All browser and network access comes through `TrackerDeps`, so the whole state machine runs in unit tests.
 */
import {
  adoptPoints,
  applyAck,
  dropBatch,
  emptyOutbox,
  enqueue,
  fixFromPosition,
  nextBatch,
  parseOutbox,
  prune,
  serializeOutbox,
  shouldRecord,
  type GeoFix,
  type Outbox,
} from "../gpsOutbox";
import {
  closeTrackingSession,
  createTrackingSession,
  sendTrackingPoints,
  type PointsBatchAck,
  type PointsBatchIn,
  type TrackingSessionCreate,
  type TrackingSessionDTO,
} from "../../api/v2/tracking.api";
import { ApiError } from "../../types/api";

export type TrackerPhase =
  | "idle"
  | "starting"
  | "active"
  | "permission_denied"
  | "unavailable"
  | "error"
  | "ended";

export type PermissionStateLike = "granted" | "prompt" | "denied";
export type TrackerPermission = PermissionStateLike | "unknown";

/** A stretch without any fix: the screen was locked / the app in the background, or the phone gave no position. */
export type TrackerGap = { from: number; to: number; cause: "background" | "no_fix" };

/** Why a publisher is no longer running. */
export type TrackerEndReason = "stopped" | "superseded" | "closed" | "trip_finished" | "unauthorized";

export type TrackerSnapshot = {
  phase: TrackerPhase;
  tripId: string | null;
  sessionId: string | null;
  /** Points waiting for the server's ACK. */
  queued: number;
  /** Points that will never reach the server (queue limits, server refusals) - missing history, said out loud. */
  dropped: number;
  /** Device time of the last fix the browser gave us, and its accuracy. */
  lastFixAt: number | null;
  lastAccuracyM: number | null;
  /** Local time of the last successful ACK. */
  lastSentAt: number | null;
  /** The tab is hidden: the browser may stop delivering positions. */
  hidden: boolean;
  /** The last send failed for a transient reason (no network, 5xx); points are kept. */
  offline: boolean;
  wakeLock: boolean;
  /** Browser location permission for this site (`unknown` where the Permissions API is missing). */
  permission: TrackerPermission;
  /** Why publishing is impossible here: a page not served over HTTPS, or no Geolocation API at all. */
  unavailableReason: "insecure" | "unsupported" | null;
  /** Battery level and charging state (Battery Status API; `null` where the browser does not expose it). */
  battery: { pct: number; charging: boolean } | null;
  /** The last stretch without positions longer than `GAP_THRESHOLD_MS`, and how many there were. */
  lastGap: TrackerGap | null;
  gapCount: number;
  errorCode: string | null;
  endReason: TrackerEndReason | null;
};

type WakeLockSentinelLike = { release(): Promise<void>; addEventListener?(type: "release", listener: () => void): void };
type PermissionStatusLike = {
  state: PermissionStateLike;
  addEventListener?(type: "change", listener: () => void): void;
};
type BatteryLike = {
  level: number;
  charging: boolean;
  addEventListener?(type: "levelchange" | "chargingchange", listener: () => void): void;
};

export type TrackerDeps = {
  geolocation: (Pick<Geolocation, "watchPosition" | "clearWatch"> & Partial<Pick<Geolocation, "getCurrentPosition">>) | null;
  /** `window.isSecureContext`: browsers expose location only to HTTPS (or localhost) pages. Default true. */
  secureContext?: boolean;
  permissions?: { query(): Promise<PermissionStatusLike> } | null;
  battery?: (() => Promise<BatteryLike>) | null;
  api: {
    create(body: TrackingSessionCreate): Promise<TrackingSessionDTO>;
    send(sessionId: string, body: PointsBatchIn): Promise<PointsBatchAck>;
    close(sessionId: string): Promise<TrackingSessionDTO>;
  };
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  now(): number;
  setInterval(handler: () => void, ms: number): number;
  clearInterval(id: number): void;
  /** Page visibility and connectivity events; absent in tests that do not need them. */
  events?: {
    isHidden(): boolean;
    onVisibilityChange(listener: () => void): () => void;
    onOnline(listener: () => void): () => void;
  };
  wakeLock?: { request(type: "screen"): Promise<WakeLockSentinelLike> } | null;
  deviceId(): string;
  appVersion: string;
};

export const OUTBOX_STORAGE_KEY = "elchi.tracking.outbox";
const DEVICE_ID_KEY = "elchi.device_id";
/** Cap on batches sent back-to-back in one flush (a long offline stretch drains over several ticks). */
const MAX_BATCHES_PER_FLUSH = 20;
/**
 * A standing phone may stop firing `watchPosition` (the spec only promises a callback on change); after this long
 * without a fix, a visible page asks once with `getCurrentPosition`, so a waiting car still reports every ~30 s.
 */
export const HEARTBEAT_AFTER_MS = 25_000;
/** No position for longer than this is a gap worth telling the driver about (screen lock, battery saver, GPS off). */
export const GAP_THRESHOLD_MS = 90_000;
/** At or below this level, without a charger, Android's battery saver is likely to throttle location. */
export const LOW_BATTERY_PCT = 20;

const INITIAL: TrackerSnapshot = {
  phase: "idle",
  tripId: null,
  sessionId: null,
  queued: 0,
  dropped: 0,
  lastFixAt: null,
  lastAccuracyM: null,
  lastSentAt: null,
  hidden: false,
  offline: false,
  wakeLock: false,
  permission: "unknown",
  unavailableReason: null,
  battery: null,
  lastGap: null,
  gapCount: 0,
  errorCode: null,
  endReason: null,
};

/** A failure after which retrying the same request is pointless. */
function sessionEnd(error: unknown): TrackerEndReason | null {
  if (!(error instanceof ApiError)) return null;
  if (error.code === "TRACKING_SESSION_SUPERSEDED") return "superseded";
  if (error.code === "TRACKING_SESSION_CLOSED" || error.status === 404) return "closed";
  if (error.status === 401) return "unauthorized";
  return null;
}

function transient(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status >= 500 || error.status === 429 || error.status === 408;
}

export class DriverTracker {
  private snapshot: TrackerSnapshot = INITIAL;
  private readonly listeners = new Set<() => void>();
  private outbox: Outbox | null = null;
  private lastRecorded: GeoFix | null = null;
  private watchId: number | null = null;
  private timer: number | null = null;
  private intervalMs = 10_000;
  private flushing: Promise<void> | null = null;
  private sentinel: WakeLockSentinelLike | null = null;
  private unsubscribers: Array<() => void> = [];
  /** Listeners that live as long as the tracker (permission, battery), not just one run. */
  private permissionStatus: PermissionStatusLike | null = null;
  private batteryWatched = false;
  /** The page was hidden at some point since the last fix: a following gap is the background's doing. */
  private hiddenSinceLastFix = false;
  private heartbeatPending = false;
  /** The newest fix sampling held back (see `recordPending`). */
  private pendingFix: GeoFix | null = null;
  /** Bumped on every start/stop, so a late answer from an older run cannot touch the current one. */
  private generation = 0;

  constructor(private readonly deps: TrackerDeps) {}

  // --- store interface (useSyncExternalStore) -------------------------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): TrackerSnapshot => this.snapshot;

  private update(patch: Partial<TrackerSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  private syncQueue(): void {
    this.update({ queued: this.outbox?.points.length ?? 0, dropped: this.outbox?.dropped ?? 0 });
  }

  // --- commands -----------------------------------------------------------------------------------------------

  /** Whether this trip is already being published (or is on its way to be). */
  isRunning(tripId?: string): boolean {
    const { phase } = this.snapshot;
    const running = phase === "starting" || phase === "active";
    return running && (tripId === undefined || this.snapshot.tripId === tripId);
  }

  async start(tripId: string): Promise<void> {
    if (this.isRunning(tripId)) return;
    if (this.isRunning()) await this.stop();
    const generation = ++this.generation;
    const kept = { permission: this.snapshot.permission, battery: this.snapshot.battery };
    if (this.deps.secureContext === false || !this.deps.geolocation) {
      const unavailableReason = this.deps.secureContext === false ? "insecure" : "unsupported";
      this.update({ ...INITIAL, ...kept, phase: "unavailable", unavailableReason, tripId });
      return;
    }
    this.update({ ...INITIAL, ...kept, phase: "starting", tripId, hidden: this.deps.events?.isHidden() ?? false });
    void this.watchBattery();
    // A site the driver has blocked would only get an error from `watchPosition`: say so before opening a session.
    const permission = await this.watchPermission();
    if (generation !== this.generation) return;
    if (permission === "denied") {
      this.update({ phase: "permission_denied" });
      return;
    }

    // Whatever an earlier run of this app left behind belongs to that run's session: deliver it there first, while
    // that session is still the active one (the K1 below supersedes it). What it could not take moves to the new
    // session of the same trip; storage is only overwritten once the new session exists.
    const stored = parseOutbox(this.read());
    const leftover = stored ? await this.drainLeftover(stored) : null;
    if (generation !== this.generation) return;

    let session: TrackingSessionDTO;
    try {
      session = await this.deps.api.create({
        trip_id: tripId,
        device_id: this.deps.deviceId(),
        platform: "web",
        app_version: this.deps.appVersion,
      });
    } catch (error) {
      if (generation !== this.generation) return;
      this.update({ phase: "error", errorCode: error instanceof ApiError ? error.code : "NETWORK_ERROR" });
      return;
    }
    if (generation !== this.generation) return;

    const fresh = emptyOutbox(tripId, session.id);
    this.outbox = leftover && leftover.tripId === tripId ? adoptPoints(fresh, leftover, this.deps.now()) : fresh;
    this.lastRecorded = null;
    this.pendingFix = null;
    this.intervalMs = Math.max(5, session.recommended_interval_s || 10) * 1000;
    this.persist();
    this.update({ phase: "active", sessionId: session.id, errorCode: null });
    this.syncQueue();
    if (this.outbox.points.length) void this.flush();

    this.watchId = this.deps.geolocation.watchPosition(
      (position) => this.onFix(generation, fixFromPosition(position)),
      (error) => this.onGeoError(generation, error),
      { enableHighAccuracy: true, maximumAge: 5_000, timeout: 30_000 },
    );
    this.hiddenSinceLastFix = this.snapshot.hidden;
    this.timer = this.deps.setInterval(() => {
      this.recordPending();
      this.heartbeat(generation);
      void this.flush();
    }, this.intervalMs);
    const events = this.deps.events;
    if (events) {
      this.unsubscribers.push(
        events.onVisibilityChange(() => {
          const hidden = events.isHidden();
          if (hidden) this.hiddenSinceLastFix = true;
          this.update({ hidden });
          if (!hidden) {
            void this.acquireWakeLock();
            void this.flush();
          }
        }),
        events.onOnline(() => void this.flush()),
      );
    }
    void this.acquireWakeLock();
  }

  /** The driver ends publishing: deliver what is queued, close the session, forget the outbox. */
  async stop(): Promise<void> {
    const sessionId = this.snapshot.sessionId;
    const wasActive = this.snapshot.phase === "active";
    if (wasActive) await this.flush();
    this.teardown();
    this.generation += 1;
    if (wasActive && sessionId) {
      try {
        await this.deps.api.close(sessionId);
      } catch {
        // The server closes the session with the trip anyway; the local stop stands.
      }
    }
    this.clearStorage();
    this.outbox = null;
    this.update({ phase: "ended", endReason: "stopped", queued: 0 });
  }

  /** Called right before the trip's `complete`: the last points go out while the session still accepts them. */
  async finishTrip(): Promise<void> {
    if (this.snapshot.phase === "active") await this.flush();
    this.end("trip_finished");
  }

  /** Back to the untouched state (logout). Queued points stay in storage for the next start on this device. */
  reset(): void {
    this.teardown();
    this.generation += 1;
    this.outbox = null;
    this.snapshot = INITIAL;
    this.listeners.forEach((listener) => listener());
  }

  // --- internals ----------------------------------------------------------------------------------------------

  private onFix(generation: number, fix: GeoFix): void {
    if (generation !== this.generation || !this.outbox) return;
    this.heartbeatPending = false;
    const previous = this.snapshot.lastFixAt;
    const patch: Partial<TrackerSnapshot> = {
      lastFixAt: previous === null ? fix.timestamp : Math.max(previous, fix.timestamp),
      lastAccuracyM: Number.isFinite(fix.accuracy) ? Math.round(fix.accuracy) : null,
    };
    // Screen lock, battery saver, GPS switched off: the history really has a hole there - name it, never fill it.
    if (previous !== null && fix.timestamp - previous > GAP_THRESHOLD_MS) {
      patch.lastGap = { from: previous, to: fix.timestamp, cause: this.hiddenSinceLastFix ? "background" : "no_fix" };
      patch.gapCount = this.snapshot.gapCount + 1;
    }
    this.hiddenSinceLastFix = this.snapshot.hidden;
    this.update(patch);
    fix = { ...fix, battery: this.snapshot.battery?.pct ?? null };
    if (!shouldRecord(this.lastRecorded, fix)) {
      // Too soon after the last kept fix - but it may be the car's final position before it stops (a standing phone
      // may not fire again). Keep the newest one; the next tick records it.
      if (!this.lastRecorded || fix.timestamp > this.lastRecorded.timestamp) this.pendingFix = fix;
      return;
    }
    this.record(fix);
  }

  private record(fix: GeoFix): void {
    if (!this.outbox) return;
    this.pendingFix = null;
    const first = this.lastRecorded === null;
    const before = this.outbox.nextSeq;
    this.outbox = enqueue(this.outbox, fix, this.deps.now());
    if (this.outbox.nextSeq === before) return; // a fix the contract would refuse: skipped, not sent
    this.lastRecorded = fix;
    this.persist();
    this.syncQueue();
    // The first point goes out at once, so a client does not wait a whole interval for the car to appear.
    if (first) void this.flush();
  }

  /** On each tick: the newest fix that sampling held back goes into the queue (one per interval at most). */
  private recordPending(): void {
    const pending = this.pendingFix;
    if (pending && (!this.lastRecorded || pending.timestamp > this.lastRecorded.timestamp)) this.record(pending);
    else this.pendingFix = null;
  }

  private onGeoError(generation: number, error: GeolocationPositionError): void {
    if (generation !== this.generation) return;
    if (error.code === 1 /* PERMISSION_DENIED */) {
      // Without permission there will be no position at all; queued points still go out.
      void this.flush().finally(() => {
        if (generation !== this.generation) return;
        this.teardown();
        this.update({ phase: "permission_denied" });
      });
    }
    // POSITION_UNAVAILABLE / TIMEOUT: the watch keeps running; the age of the last fix tells the story.
  }

  /** One `getCurrentPosition` when a visible page has had no fix for a while (a standing car, a lazy provider). */
  private heartbeat(generation: number): void {
    const geolocation = this.deps.geolocation;
    if (!geolocation?.getCurrentPosition || this.heartbeatPending || this.snapshot.hidden) return;
    const last = this.snapshot.lastFixAt;
    if (last !== null && this.deps.now() - last < HEARTBEAT_AFTER_MS) return;
    this.heartbeatPending = true;
    geolocation.getCurrentPosition(
      (position) => this.onFix(generation, fixFromPosition(position)),
      (error) => {
        this.heartbeatPending = false;
        this.onGeoError(generation, error);
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20_000 },
    );
  }

  /** Permission state now, and one listener for changes (revoked mid-trip, or granted after a denial). */
  private async watchPermission(): Promise<TrackerPermission> {
    if (!this.deps.permissions) return "unknown";
    try {
      const status = this.permissionStatus ?? (await this.deps.permissions.query());
      if (!this.permissionStatus) {
        this.permissionStatus = status;
        status.addEventListener?.("change", () => this.onPermissionChange(status.state));
      }
      this.update({ permission: status.state });
      return status.state;
    } catch {
      return "unknown";
    }
  }

  private onPermissionChange(state: PermissionStateLike): void {
    this.update({ permission: state });
    const { phase, tripId } = this.snapshot;
    if (state === "denied" && (phase === "active" || phase === "starting")) {
      const generation = this.generation;
      void this.flush().finally(() => {
        if (generation !== this.generation) return;
        this.teardown();
        this.update({ phase: "permission_denied" });
      });
    }
    // The driver fixed it in the browser settings: pick up where the denial stopped us.
    if (state === "granted" && phase === "permission_denied" && tripId) void this.start(tripId);
  }

  private async watchBattery(): Promise<void> {
    if (!this.deps.battery || this.batteryWatched) return;
    this.batteryWatched = true;
    try {
      const battery = await this.deps.battery();
      const read = () => this.update({ battery: { pct: Math.round(battery.level * 100), charging: battery.charging } });
      read();
      battery.addEventListener?.("levelchange", read);
      battery.addEventListener?.("chargingchange", read);
    } catch {
      // Not exposed (Firefox, Safari, iOS): the bar simply has no battery line.
    }
  }

  /** Send queued batches until the queue is empty, the server ends the session, or the network fails. */
  flush(): Promise<void> {
    if (this.flushing) return this.flushing;
    this.flushing = this.flushOnce().finally(() => {
      this.flushing = null;
    });
    return this.flushing;
  }

  private async flushOnce(): Promise<void> {
    const generation = this.generation;
    for (let round = 0; round < MAX_BATCHES_PER_FLUSH; round += 1) {
      if (!this.outbox || generation !== this.generation) return;
      this.outbox = prune(this.outbox, this.deps.now());
      const batch = nextBatch(this.outbox);
      if (!batch.length) {
        this.syncQueue();
        return;
      }
      const sessionId = this.outbox.sessionId;
      let ack: PointsBatchAck;
      try {
        ack = await this.deps.api.send(sessionId, { points: batch });
      } catch (error) {
        if (generation !== this.generation || !this.outbox) return;
        const reason = sessionEnd(error);
        if (reason) {
          this.end(reason);
          return;
        }
        if (transient(error)) {
          this.update({ offline: true });
          return;
        }
        // 422 and friends: this batch will never be accepted; drop it so it cannot block the rest.
        this.outbox = dropBatch(this.outbox, batch);
        this.persist();
        this.syncQueue();
        continue;
      }
      if (generation !== this.generation || !this.outbox) return;
      this.outbox = applyAck(this.outbox, ack);
      this.persist();
      this.update({ lastSentAt: this.deps.now(), offline: false });
      this.syncQueue();
      if (ack.session_status !== "active") {
        this.end(ack.session_status === "superseded" ? "superseded" : "closed");
        return;
      }
    }
  }

  /**
   * Best effort: an earlier run's points go to that run's session. Returns what is still undelivered (the network
   * failed, or that session no longer accepts points); per-point refusals are counted as missing history.
   */
  private async drainLeftover(leftover: Outbox): Promise<Outbox> {
    let outbox = prune(leftover, this.deps.now());
    for (let round = 0; round < MAX_BATCHES_PER_FLUSH && outbox.points.length; round += 1) {
      const batch = nextBatch(outbox);
      try {
        const ack = await this.deps.api.send(outbox.sessionId, { points: batch });
        outbox = applyAck(outbox, ack);
        if (ack.session_status !== "active") break;
      } catch (error) {
        if (!transient(error) && !sessionEnd(error)) {
          outbox = dropBatch(outbox, batch);
          continue;
        }
        break;
      }
    }
    return outbox;
  }

  private end(reason: TrackerEndReason): void {
    this.teardown();
    this.generation += 1;
    this.clearStorage();
    const dropped = (this.outbox?.dropped ?? 0) + (this.outbox?.points.length ?? 0);
    this.outbox = null;
    this.update({ phase: "ended", endReason: reason, queued: 0, dropped, offline: false });
  }

  private teardown(): void {
    if (this.watchId !== null) this.deps.geolocation?.clearWatch(this.watchId);
    this.watchId = null;
    if (this.timer !== null) this.deps.clearInterval(this.timer);
    this.timer = null;
    this.unsubscribers.forEach((unsubscribe) => unsubscribe());
    this.unsubscribers = [];
    const sentinel = this.sentinel;
    this.sentinel = null;
    if (sentinel) void sentinel.release().catch(() => undefined);
    if (this.snapshot.wakeLock) this.update({ wakeLock: false });
  }

  private async acquireWakeLock(): Promise<void> {
    if (!this.deps.wakeLock || this.sentinel || this.snapshot.phase !== "active") return;
    try {
      const sentinel = await this.deps.wakeLock.request("screen");
      if (this.snapshot.phase !== "active") {
        void sentinel.release().catch(() => undefined);
        return;
      }
      this.sentinel = sentinel;
      sentinel.addEventListener?.("release", () => {
        if (this.sentinel === sentinel) this.sentinel = null;
        this.update({ wakeLock: false });
      });
      this.update({ wakeLock: true });
    } catch {
      // Refused (battery saver, hidden tab) or unsupported: publishing goes on, the screen may lock.
      this.update({ wakeLock: false });
    }
  }

  private read(): string | null {
    try {
      return this.deps.storage?.getItem(OUTBOX_STORAGE_KEY) ?? null;
    } catch {
      return null;
    }
  }

  private persist(): void {
    if (!this.outbox) return;
    try {
      this.deps.storage?.setItem(OUTBOX_STORAGE_KEY, serializeOutbox(this.outbox));
    } catch {
      // Storage full or blocked: the queue still lives in memory for as long as the page does.
    }
  }

  private clearStorage(): void {
    try {
      this.deps.storage?.removeItem(OUTBOX_STORAGE_KEY);
    } catch {
      // Nothing to clean up that could be read back.
    }
  }
}

// --- the app's one publisher -------------------------------------------------------------------------------------

function safeStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

/** A random, non-identifying id for this browser install (K1 `device_id`); not a secret, not a fingerprint. */
export function browserDeviceId(storage: Pick<Storage, "getItem" | "setItem"> | null = safeStorage()): string {
  try {
    const known = storage?.getItem(DEVICE_ID_KEY);
    if (known) return known;
    const fresh = `web-${crypto.randomUUID()}`;
    storage?.setItem(DEVICE_ID_KEY, fresh);
    return fresh;
  } catch {
    return `web-${crypto.randomUUID()}`;
  }
}

function browserDeps(): TrackerDeps {
  const hasWindow = typeof window !== "undefined";
  const nav = typeof navigator !== "undefined" ? navigator : undefined;
  const wakeLock = (nav as (Navigator & { wakeLock?: TrackerDeps["wakeLock"] }) | undefined)?.wakeLock ?? null;
  const permissions = nav?.permissions?.query
    ? { query: () => nav.permissions.query({ name: "geolocation" }) as Promise<PermissionStatusLike> }
    : null;
  const getBattery = (nav as (Navigator & { getBattery?: () => Promise<BatteryLike> }) | undefined)?.getBattery;
  return {
    geolocation: nav && "geolocation" in nav ? nav.geolocation : null,
    secureContext: hasWindow ? window.isSecureContext !== false : true,
    permissions,
    battery: getBattery && nav ? () => getBattery.call(nav) : null,
    api: {
      create: (body) => createTrackingSession(body),
      send: (sessionId, body) => sendTrackingPoints(sessionId, body),
      close: (sessionId) => closeTrackingSession(sessionId),
    },
    storage: safeStorage(),
    now: () => Date.now(),
    setInterval: (handler, ms) => window.setInterval(handler, ms),
    clearInterval: (id) => window.clearInterval(id),
    events: hasWindow
      ? {
          isHidden: () => document.visibilityState === "hidden",
          onVisibilityChange: (listener) => {
            document.addEventListener("visibilitychange", listener);
            return () => document.removeEventListener("visibilitychange", listener);
          },
          onOnline: (listener) => {
            window.addEventListener("online", listener);
            return () => window.removeEventListener("online", listener);
          },
        }
      : undefined,
    wakeLock,
    deviceId: () => browserDeviceId(),
    appVersion: `mobile-web/${(import.meta.env.VITE_APP_VERSION as string | undefined) || "dev"}`,
  };
}

let shared: DriverTracker | null = null;

/** The single publisher of this page: it outlives screen changes, so switching tabs in the app does not stop it. */
export function driverTracker(): DriverTracker {
  shared ??= new DriverTracker(browserDeps());
  return shared;
}
