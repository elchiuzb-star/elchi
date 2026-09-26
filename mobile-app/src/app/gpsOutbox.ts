/**
 * The driver's GPS outbox (spec §10.3-§10.4, Q148) - pure: no DOM, no network, no clock of its own.
 *
 * A browser fix becomes a contract point (`TrackingPointIn`: integer units, WGS84 degrees), goes into a local queue
 * with a per-session `seq`, leaves in batches of at most `MAX_POINTS_PER_BATCH`, and is removed only by the server's
 * ACK. Nothing here invents a point: a fix the contract would refuse is skipped, never "corrected" into a new place,
 * and points the queue had to drop are counted so the screen can say that history is missing (§10.4).
 *
 * The numbers mirror `app/contracts/tracking.py`; `tests/test_mobile_gps_constants.py` fails when they drift.
 */
import type { PointsBatchAck, TrackingPointIn } from "../api/v2/tracking.api";

// --- mirrored contract values (app/contracts/tracking.py) ------------------------------------------------------
export const MAX_POINTS_PER_BATCH = 100;
export const LOCAL_QUEUE_MAX_POINTS = 20_000;
export const LOCAL_QUEUE_MAX_AGE_MS = 24 * 3600 * 1000;
export const MAX_ACCURACY_M = 10_000;
export const MAX_SPEED_MPS_INPUT = 100;
/** §10.3 send targets: moving ~10 s, waiting 30-60 s (app configuration, not an OS guarantee). */
export const SEND_INTERVAL_MOVING_SECONDS = 10;
export const SEND_INTERVAL_WAITING_SECONDS = 30;
/** §10.4 freshness buckets. */
export const FRESH_MAX_AGE_SECONDS = 30;
export const DELAYED_MAX_AGE_SECONDS = 120;

/** Below this the car is treated as standing (waiting cadence). */
const MOVING_SPEED_MPS = 1;
const MOVING_DISTANCE_M = 25;

/** What the browser gives us, already unwrapped from `GeolocationPosition`. */
export type GeoFix = {
  lat: number;
  lng: number;
  accuracy: number;
  speed: number | null;
  heading: number | null;
  /** Epoch milliseconds of the fix (the device clock). */
  timestamp: number;
  /** Battery level 0-100 at the time of the fix, when the browser exposes it (Battery Status API). */
  battery?: number | null;
};

export function fixFromPosition(position: {
  coords: { latitude: number; longitude: number; accuracy: number; speed: number | null; heading: number | null };
  timestamp: number;
}): GeoFix {
  const { latitude, longitude, accuracy, speed, heading } = position.coords;
  return { lat: latitude, lng: longitude, accuracy, speed, heading, timestamp: position.timestamp };
}

const finite = (value: number | null | undefined): value is number => typeof value === "number" && Number.isFinite(value);

/**
 * The contract point for one fix, or `null` when the server would refuse it as `invalid` - a single bad field fails
 * the whole batch (422), so such a fix is skipped here rather than sent. Optional fields the browser cannot measure
 * are left out; `is_mock` is `false` because a browser cannot tell - it is not a claim that the fix was checked.
 */
export function toTrackingPoint(fix: GeoFix, seq: number): TrackingPointIn | null {
  if (!finite(fix.lat) || !finite(fix.lng) || fix.lat < -90 || fix.lat > 90 || fix.lng < -180 || fix.lng > 180) return null;
  if (!finite(fix.accuracy) || fix.accuracy < 0 || fix.accuracy > MAX_ACCURACY_M) return null;
  if (!finite(fix.timestamp) || fix.timestamp <= 0) return null;
  const point: TrackingPointIn = {
    seq,
    captured_at: new Date(fix.timestamp).toISOString(),
    lat: fix.lat,
    lng: fix.lng,
    accuracy_m: Math.round(fix.accuracy),
    is_mock: false,
  };
  if (finite(fix.speed) && fix.speed >= 0) {
    const speed = Math.round(fix.speed);
    if (speed <= MAX_SPEED_MPS_INPUT) point.speed_mps = speed;
  }
  if (finite(fix.heading) && fix.heading >= 0) point.heading_deg = Math.round(fix.heading) % 360;
  if (finite(fix.battery) && fix.battery >= 0 && fix.battery <= 100) point.battery_pct = Math.round(fix.battery);
  return point;
}

/** Great-circle distance in metres (same formula as the server's `rules.distance_m`). */
export function distanceM(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const rad = Math.PI / 180;
  const dphi = (b.lat - a.lat) * rad;
  const dlmb = (b.lng - a.lng) * rad;
  const h = Math.sin(dphi / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dlmb / 2) ** 2;
  return 2 * 6_371_008.8 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * Sampling: `watchPosition` may fire every second; the queue keeps one fix per ~10 s while moving and per ~30 s
 * while standing (§10.3). A fix older than the last kept one is dropped (the browser replaying a cached position).
 */
export function shouldRecord(previous: GeoFix | null, next: GeoFix): boolean {
  if (!previous) return true;
  const elapsedMs = next.timestamp - previous.timestamp;
  if (elapsedMs <= 0) return false;
  const moving = (finite(next.speed) && next.speed >= MOVING_SPEED_MPS) || distanceM(previous, next) >= MOVING_DISTANCE_M;
  const interval = moving ? SEND_INTERVAL_MOVING_SECONDS : SEND_INTERVAL_WAITING_SECONDS;
  return elapsedMs >= interval * 1000;
}

// --- the queue ------------------------------------------------------------------------------------------------

export type Outbox = {
  tripId: string;
  sessionId: string;
  nextSeq: number;
  points: TrackingPointIn[];
  /** Points the queue dropped (too old or over the size limit) or the server refused: history that does not exist. */
  dropped: number;
};

export function emptyOutbox(tripId: string, sessionId: string): Outbox {
  return { tripId, sessionId, nextSeq: 0, points: [], dropped: 0 };
}

/** Enforce §10.4: at most 24 hours and 20 000 points; the oldest go first and are counted. */
export function prune(outbox: Outbox, nowMs: number): Outbox {
  const cutoff = nowMs - LOCAL_QUEUE_MAX_AGE_MS;
  let points = outbox.points.filter((point) => Date.parse(point.captured_at) >= cutoff);
  if (points.length > LOCAL_QUEUE_MAX_POINTS) points = points.slice(points.length - LOCAL_QUEUE_MAX_POINTS);
  const dropped = outbox.dropped + (outbox.points.length - points.length);
  return points.length === outbox.points.length ? outbox : { ...outbox, points, dropped };
}

/** Add one fix under the next `seq`; a fix the contract would refuse is skipped without using a `seq`. */
export function enqueue(outbox: Outbox, fix: GeoFix, nowMs: number): Outbox {
  const point = toTrackingPoint(fix, outbox.nextSeq);
  if (!point) return outbox;
  return prune({ ...outbox, nextSeq: outbox.nextSeq + 1, points: [...outbox.points, point] }, nowMs);
}

export function nextBatch(outbox: Outbox): TrackingPointIn[] {
  return outbox.points.slice(0, MAX_POINTS_PER_BATCH);
}

/**
 * Remove what the server answered for. Accepted and duplicate points are stored; rejected ones (`too_old`,
 * `future_timestamp`, `invalid`, `payload_conflict`) would be rejected again on every retry, so they leave the queue
 * too and are counted as missing history.
 */
export function applyAck(outbox: Outbox, ack: Pick<PointsBatchAck, "accepted_seqs" | "duplicate_seqs" | "rejected">): Outbox {
  const answered = new Set<number>([...ack.accepted_seqs, ...ack.duplicate_seqs, ...ack.rejected.map((item) => item.seq)]);
  if (!answered.size) return outbox;
  return {
    ...outbox,
    points: outbox.points.filter((point) => !answered.has(point.seq)),
    dropped: outbox.dropped + ack.rejected.length,
  };
}

/**
 * Carry points an earlier session could not take (network down, the session already replaced) into a new session of
 * the same trip. `seq` is per session, so they are renumbered in capture order; the points themselves are unchanged.
 */
export function adoptPoints(outbox: Outbox, earlier: Outbox, nowMs: number): Outbox {
  const ordered = [...earlier.points].sort((a, b) => Date.parse(a.captured_at) - Date.parse(b.captured_at));
  const points = [...outbox.points];
  let nextSeq = outbox.nextSeq;
  for (const point of ordered) points.push({ ...point, seq: nextSeq++ });
  return prune({ ...outbox, nextSeq, points, dropped: outbox.dropped + earlier.dropped }, nowMs);
}

/** A batch the server refused as a whole (422): drop exactly those points so one bad point cannot block the queue. */
export function dropBatch(outbox: Outbox, batch: TrackingPointIn[]): Outbox {
  const seqs = new Set(batch.map((point) => point.seq));
  const points = outbox.points.filter((point) => !seqs.has(point.seq));
  return { ...outbox, points, dropped: outbox.dropped + (outbox.points.length - points.length) };
}

// --- storage: compact tuples, so a full queue stays well under the browser's ~5 MB --------------------------------

/** `[seq, captured_ms, lat, lng, accuracy, speed, heading, battery?]` - the 8th slot is optional (older entries). */
type StoredPoint = [number, number, number, number, number, number | null, number | null, (number | null)?];
type StoredOutbox = { v: 1; trip: string; session: string; next: number; dropped: number; points: StoredPoint[] };

export function serializeOutbox(outbox: Outbox): string {
  const stored: StoredOutbox = {
    v: 1,
    trip: outbox.tripId,
    session: outbox.sessionId,
    next: outbox.nextSeq,
    dropped: outbox.dropped,
    points: outbox.points.map((p) => [
      p.seq,
      Date.parse(p.captured_at),
      p.lat,
      p.lng,
      p.accuracy_m,
      p.speed_mps ?? null,
      p.heading_deg ?? null,
      p.battery_pct ?? null,
    ]),
  };
  return JSON.stringify(stored);
}

/** `null` for anything that is not a well-formed stored outbox (a corrupt entry is discarded, never half-trusted). */
export function parseOutbox(raw: string | null): Outbox | null {
  if (!raw) return null;
  try {
    const stored = JSON.parse(raw) as StoredOutbox;
    if (stored?.v !== 1 || typeof stored.trip !== "string" || typeof stored.session !== "string") return null;
    if (!Number.isInteger(stored.next) || !Array.isArray(stored.points)) return null;
    const points: TrackingPointIn[] = [];
    for (const item of stored.points) {
      if (!Array.isArray(item) || (item.length !== 7 && item.length !== 8)) return null;
      const [seq, at, lat, lng, accuracy, speed, heading, battery] = item;
      const point = toTrackingPoint({ lat, lng, accuracy, speed, heading, timestamp: at, battery }, seq);
      if (!point || !Number.isInteger(seq) || seq < 0) return null;
      points.push(point);
    }
    return {
      tripId: stored.trip,
      sessionId: stored.session,
      nextSeq: stored.next,
      points,
      dropped: Number.isInteger(stored.dropped) ? stored.dropped : 0,
    };
  } catch {
    return null;
  }
}

// --- what the screens show -------------------------------------------------------------------------------------

export type Freshness = "fresh" | "delayed" | "lost" | "no_data";

const RANK: Record<Freshness, number> = { fresh: 0, delayed: 1, lost: 2, no_data: 3 };

/** §10.4 bucket of a point's age on this device's clock. */
export function freshnessForAge(ageSeconds: number | null): Freshness {
  if (ageSeconds === null) return "no_data";
  if (ageSeconds <= FRESH_MAX_AGE_SECONDS) return "fresh";
  if (ageSeconds <= DELAYED_MAX_AGE_SECONDS) return "delayed";
  return "lost";
}

/**
 * The freshness a viewer is shown: the server's bucket, only ever made *worse* by the point's age on this device -
 * a screen left open never keeps saying "live" after the driver's phone went quiet.
 */
export function effectiveFreshness(
  data: { freshness: Freshness; last_point?: { captured_at: string } | null },
  now: Date = new Date(),
): Freshness {
  if (!data.last_point) return "no_data";
  const age = Math.max(0, (now.getTime() - Date.parse(data.last_point.captured_at)) / 1000);
  const local = freshnessForAge(age);
  return RANK[local] > RANK[data.freshness] ? local : data.freshness;
}

/** Trip statuses in which the server accepts a writer session (`rules.PUBLISHABLE_TRIP_STATUSES`). */
export const PUBLISHABLE_TRIP_STATUSES: ReadonlySet<string> = new Set(["boarding", "in_progress", "interrupted"]);

/** The driver's trip that should be publishing now: a running one, the earliest planned start first. */
export function trackableTrip<T extends { id: string; status: string; planned_start_at?: string | null }>(trips: readonly T[]): T | null {
  const running = trips.filter((trip) => PUBLISHABLE_TRIP_STATUSES.has(trip.status));
  running.sort((a, b) => Date.parse(a.planned_start_at ?? "") - Date.parse(b.planned_start_at ?? ""));
  return running[0] ?? null;
}
