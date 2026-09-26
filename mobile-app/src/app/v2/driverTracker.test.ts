/**
 * Q148 publisher state machine, driven through fake geolocation, API, storage and timers. SYNTHETIC data.
 *
 * Covers: K1 with `platform=web`, the first point sent at once, points kept across a network failure, the server
 * ending the session (superseded / closed), a refused batch not blocking the queue, permission denied, a reload
 * delivering an earlier run's points before the new session, and stop closing the session.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../types/api";
import type { PointsBatchAck, PointsBatchIn, TrackingSessionDTO } from "../../api/v2/tracking.api";
import { emptyOutbox, enqueue, serializeOutbox } from "../gpsOutbox";
import { DriverTracker, OUTBOX_STORAGE_KEY, type TrackerDeps } from "./driverTracker";

vi.mock("../../api/v2/tracking.api", () => ({
  closeTrackingSession: vi.fn(),
  createTrackingSession: vi.fn(),
  sendTrackingPoints: vi.fn(),
}));

const T0 = Date.parse("2026-09-25T08:00:00Z");

type Harness = {
  tracker: DriverTracker;
  deps: TrackerDeps;
  emit(offsetS: number, patch?: Partial<GeolocationCoordinates>): void;
  fail(code: number): void;
  tick(): void;
  sent: Array<{ sessionId: string; body: PointsBatchIn }>;
  store: Map<string, string>;
  clock: { now: number };
};

function session(id: string): TrackingSessionDTO {
  return { id, status: "active", last_seq: null, started_at: new Date(T0).toISOString(), recommended_interval_s: 10 };
}

function ackAll(body: PointsBatchIn, status: PointsBatchAck["session_status"] = "active"): PointsBatchAck {
  return { accepted_seqs: body.points.map((p) => p.seq), duplicate_seqs: [], rejected: [], session_status: status };
}

function harness(overrides: Partial<TrackerDeps> = {}): Harness {
  const store = new Map<string, string>();
  const clock = { now: T0 };
  let onFix: PositionCallback | null = null;
  let onError: PositionErrorCallback | null | undefined = null;
  let interval: (() => void) | null = null;
  const sent: Harness["sent"] = [];
  const deps: TrackerDeps = {
    geolocation: {
      watchPosition: vi.fn((success: PositionCallback, error?: PositionErrorCallback | null) => {
        onFix = success;
        onError = error;
        return 7;
      }),
      clearWatch: vi.fn(),
    },
    api: {
      create: vi.fn(async () => session("trs_new")),
      send: vi.fn(async (sessionId: string, body: PointsBatchIn) => {
        sent.push({ sessionId, body });
        return ackAll(body);
      }),
      close: vi.fn(async () => ({ ...session("trs_new"), status: "closed" as const })),
    },
    storage: {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => void store.set(key, value),
      removeItem: (key) => void store.delete(key),
    },
    now: () => clock.now,
    setInterval: vi.fn((handler: () => void) => {
      interval = handler;
      return 1;
    }),
    clearInterval: vi.fn(),
    deviceId: () => "web-device",
    appVersion: "mobile-web/test",
    ...overrides,
  };
  const tracker = new DriverTracker(deps);
  return {
    tracker,
    deps,
    sent,
    store,
    clock,
    emit(offsetS, patch = {}) {
      clock.now = T0 + offsetS * 1000;
      onFix?.({
        timestamp: clock.now,
        coords: { latitude: 41.3, longitude: 69.24, accuracy: 10, speed: 12, heading: 90, altitude: null, altitudeAccuracy: null, ...patch },
      } as GeolocationPosition);
    },
    fail(code) {
      onError?.({ code, message: "x", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 } as GeolocationPositionError);
    },
    tick() {
      interval?.();
    },
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => vi.clearAllMocks());

describe("DriverTracker", () => {
  it("opens a web writer session and sends the first point at once", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    expect(h.deps.api.create).toHaveBeenCalledWith({
      trip_id: "trp_1",
      device_id: "web-device",
      platform: "web",
      app_version: "mobile-web/test",
    });
    expect(h.tracker.getSnapshot().phase).toBe("active");
    h.emit(0);
    await settle();
    expect(h.sent).toHaveLength(1);
    expect(h.sent[0]).toMatchObject({ sessionId: "trs_new", body: { points: [{ seq: 0, accuracy_m: 10, speed_mps: 12, is_mock: false }] } });
    expect(h.tracker.getSnapshot()).toMatchObject({ queued: 0, lastSentAt: T0 });
  });

  it("keeps points through a network failure and sends them when it is back", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    (h.deps.api.send as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    h.emit(0);
    await settle();
    expect(h.tracker.getSnapshot()).toMatchObject({ queued: 1, offline: true });
    h.emit(10);
    h.tick();
    await settle();
    expect(h.sent.at(-1)?.body.points.map((p) => p.seq)).toEqual([0, 1]);
    expect(h.tracker.getSnapshot()).toMatchObject({ queued: 0, offline: false });
  });

  it("stops when another device takes over, without closing that device's session", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    (h.deps.api.send as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new ApiError(409, { code: "TRACKING_SESSION_SUPERSEDED", message: "x" }),
    );
    h.emit(0);
    await settle();
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "ended", endReason: "superseded" });
    expect(h.deps.geolocation?.clearWatch).toHaveBeenCalledWith(7);
    expect(h.deps.api.close).not.toHaveBeenCalled();
    expect(h.store.has(OUTBOX_STORAGE_KEY)).toBe(false);
  });

  it("stops when the server answers that the session is closed (the trip ended)", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    (h.deps.api.send as ReturnType<typeof vi.fn>).mockImplementationOnce(async (_s: string, body: PointsBatchIn) => ackAll(body, "closed"));
    h.emit(0);
    await settle();
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "ended", endReason: "closed" });
  });

  it("drops a batch the server refuses as a whole and counts it", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    (h.deps.api.send as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new ApiError(422, { code: "VALIDATION_ERROR", message: "x" }));
    h.emit(0);
    await settle();
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "active", queued: 0, dropped: 1 });
  });

  it("says so when location permission is denied", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    h.fail(1);
    await settle();
    expect(h.tracker.getSnapshot().phase).toBe("permission_denied");
    expect(h.deps.geolocation?.clearWatch).toHaveBeenCalled();
  });

  it("is unavailable without a geolocation API (no session is opened)", async () => {
    const h = harness({ geolocation: null });
    await h.tracker.start("trp_1");
    expect(h.tracker.getSnapshot().phase).toBe("unavailable");
    expect(h.deps.api.create).not.toHaveBeenCalled();
  });

  it("after a reload delivers the earlier run's points to its own session before opening a new one", async () => {
    const h = harness();
    let leftover = emptyOutbox("trp_1", "trs_old");
    leftover = enqueue(leftover, { lat: 41.3, lng: 69.2, accuracy: 8, speed: null, heading: null, timestamp: T0 - 20_000 }, T0);
    h.store.set(OUTBOX_STORAGE_KEY, serializeOutbox(leftover));
    const order: string[] = [];
    (h.deps.api.send as ReturnType<typeof vi.fn>).mockImplementation(async (sessionId: string, body: PointsBatchIn) => {
      order.push(`send:${sessionId}`);
      return ackAll(body);
    });
    (h.deps.api.create as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      order.push("create");
      return session("trs_new");
    });
    await h.tracker.start("trp_1");
    expect(order).toEqual(["send:trs_old", "create"]);
  });

  it("moves points the earlier session could not take into the new session", async () => {
    const h = harness();
    let leftover = emptyOutbox("trp_1", "trs_old");
    leftover = enqueue(leftover, { lat: 41.3, lng: 69.2, accuracy: 8, speed: null, heading: null, timestamp: T0 - 20_000 }, T0);
    h.store.set(OUTBOX_STORAGE_KEY, serializeOutbox(leftover));
    (h.deps.api.send as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new ApiError(409, { code: "TRACKING_SESSION_SUPERSEDED", message: "x" }),
    );
    await h.tracker.start("trp_1");
    await settle();
    expect(h.sent.at(-1)).toMatchObject({ sessionId: "trs_new", body: { points: [{ seq: 0, captured_at: "2026-09-25T07:59:40.000Z" }] } });
  });

  it("stop delivers what is queued, closes the session and forgets the outbox", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    (h.deps.api.send as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new TypeError("offline"));
    h.emit(0);
    await settle();
    await h.tracker.stop();
    expect(h.sent.at(-1)?.body.points).toHaveLength(1);
    expect(h.deps.api.close).toHaveBeenCalledWith("trs_new");
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "ended", endReason: "stopped" });
    expect(h.store.has(OUTBOX_STORAGE_KEY)).toBe(false);
  });

  it("a K1 refusal is shown with its code and nothing is watched", async () => {
    const h = harness();
    (h.deps.api.create as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new ApiError(409, { code: "INVALID_STATE_TRANSITION", message: "x" }),
    );
    await h.tracker.start("trp_1");
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "error", errorCode: "INVALID_STATE_TRANSITION" });
    expect(h.deps.geolocation?.watchPosition).not.toHaveBeenCalled();
  });
});

describe("DriverTracker on a real phone's conditions", () => {
  it("refuses to start on a page that is not HTTPS, and opens no session", async () => {
    const h = harness({ secureContext: false });
    await h.tracker.start("trp_1");
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "unavailable", unavailableReason: "insecure" });
    expect(h.deps.api.create).not.toHaveBeenCalled();
  });

  it("does not open a session when the site is blocked, and resumes by itself once allowed", async () => {
    let onChange: (() => void) | null = null;
    const status = { state: "denied" as PermissionState, addEventListener: (_: "change", listener: () => void) => (onChange = listener) };
    const h = harness({ permissions: { query: async () => status } });
    await h.tracker.start("trp_1");
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "permission_denied", permission: "denied" });
    expect(h.deps.api.create).not.toHaveBeenCalled();
    status.state = "granted";
    onChange!();
    await settle();
    expect(h.deps.api.create).toHaveBeenCalledTimes(1);
    expect(h.tracker.getSnapshot()).toMatchObject({ phase: "active", permission: "granted" });
  });

  it("stops watching when permission is revoked mid-trip, after sending what is queued", async () => {
    let onChange: (() => void) | null = null;
    const status = { state: "granted" as PermissionState, addEventListener: (_: "change", listener: () => void) => (onChange = listener) };
    const h = harness({ permissions: { query: async () => status } });
    await h.tracker.start("trp_1");
    h.emit(0);
    await settle();
    status.state = "denied";
    onChange!();
    await settle();
    expect(h.tracker.getSnapshot().phase).toBe("permission_denied");
    expect(h.deps.geolocation?.clearWatch).toHaveBeenCalled();
    expect(h.sent).toHaveLength(1);
  });

  it("puts the battery level on each point and reports a low, unplugged battery", async () => {
    const h = harness({ battery: async () => ({ level: 0.14, charging: false }) });
    await h.tracker.start("trp_1");
    await settle();
    h.emit(0);
    await settle();
    expect(h.sent[0].body.points[0].battery_pct).toBe(14);
    expect(h.tracker.getSnapshot().battery).toEqual({ pct: 14, charging: false });
  });

  it("asks once for a position when a standing phone stops firing watchPosition", async () => {
    const getCurrentPosition = vi.fn();
    const h = harness();
    (h.deps.geolocation as { getCurrentPosition?: unknown }).getCurrentPosition = getCurrentPosition;
    await h.tracker.start("trp_1");
    h.emit(0);
    await settle();
    h.clock.now = T0 + 10_000;
    h.tick();
    expect(getCurrentPosition).not.toHaveBeenCalled();
    h.clock.now = T0 + 30_000;
    h.tick();
    h.tick();
    expect(getCurrentPosition).toHaveBeenCalledTimes(1); // not again while the first answer is pending
  });

  it("names a gap and its cause: a locked screen vs a phone that gave no position", async () => {
    let hidden = false;
    let onVisibility: (() => void) | null = null;
    const h = harness({
      events: {
        isHidden: () => hidden,
        onVisibilityChange: (listener) => ((onVisibility = listener), () => undefined),
        onOnline: () => () => undefined,
      },
    });
    await h.tracker.start("trp_1");
    h.emit(0);
    hidden = true;
    onVisibility!();
    hidden = false;
    onVisibility!();
    h.emit(300); // five minutes later, after the screen came back
    expect(h.tracker.getSnapshot().lastGap).toEqual({ from: T0, to: T0 + 300_000, cause: "background" });
    h.emit(310);
    h.emit(500); // visible the whole time: the phone itself went quiet
    expect(h.tracker.getSnapshot()).toMatchObject({ gapCount: 2, lastGap: { cause: "no_fix" } });
  });
});

describe("DriverTracker sampling", () => {
  it("sends the car's last position when it stops right after a kept fix", async () => {
    const h = harness();
    await h.tracker.start("trp_1");
    h.emit(0);
    await settle();
    h.emit(4, { latitude: 41.3027 }); // moved 300 m, only 4 s after the kept fix: held back
    await settle();
    expect(h.sent.flatMap((b) => b.body.points)).toHaveLength(1);
    h.clock.now = T0 + 10_000;
    h.tick(); // no further callback from the standing phone - the tick records the held-back fix
    await settle();
    const points = h.sent.flatMap((b) => b.body.points);
    expect(points.at(-1)).toMatchObject({ seq: 1, lat: 41.3027 });
    h.tick();
    await settle();
    expect(h.sent.flatMap((b) => b.body.points)).toHaveLength(2); // recorded once
  });
});
