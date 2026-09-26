/** Q148 outbox rules: contract-shaped points, sampling, queue limits, ACK handling, storage. SYNTHETIC data. */
import { describe, expect, it } from "vitest";

import {
  LOCAL_QUEUE_MAX_AGE_MS,
  LOCAL_QUEUE_MAX_POINTS,
  MAX_POINTS_PER_BATCH,
  adoptPoints,
  applyAck,
  dropBatch,
  effectiveFreshness,
  emptyOutbox,
  enqueue,
  nextBatch,
  parseOutbox,
  prune,
  serializeOutbox,
  shouldRecord,
  toTrackingPoint,
  trackableTrip,
  type GeoFix,
} from "./gpsOutbox";

const T0 = Date.parse("2026-09-25T08:00:00Z");

function fix(offsetS: number, patch: Partial<GeoFix> = {}): GeoFix {
  return { lat: 41.3, lng: 69.24, accuracy: 12.4, speed: null, heading: null, timestamp: T0 + offsetS * 1000, ...patch };
}

describe("toTrackingPoint", () => {
  it("rounds to the contract's integer units and keeps degrees as they are", () => {
    expect(toTrackingPoint(fix(0, { speed: 13.6, heading: 359.7 }), 4)).toEqual({
      seq: 4,
      captured_at: "2026-09-25T08:00:00.000Z",
      lat: 41.3,
      lng: 69.24,
      accuracy_m: 12,
      speed_mps: 14,
      heading_deg: 0,
      is_mock: false,
    });
  });

  it("leaves out what the browser could not measure instead of sending a guess", () => {
    const point = toTrackingPoint(fix(0, { speed: Number.NaN, heading: null }), 0)!;
    expect("speed_mps" in point).toBe(false);
    expect("heading_deg" in point).toBe(false);
    // a device speed above the contract bound would fail the whole batch - it is dropped, the point is kept
    expect("speed_mps" in toTrackingPoint(fix(0, { speed: 150 }), 0)!).toBe(false);
  });

  it("skips a fix the server would refuse as invalid", () => {
    expect(toTrackingPoint(fix(0, { accuracy: 20_000 }), 0)).toBeNull();
    expect(toTrackingPoint(fix(0, { lat: 91 }), 0)).toBeNull();
    expect(toTrackingPoint(fix(0, { lng: Number.NaN }), 0)).toBeNull();
  });
});

describe("shouldRecord", () => {
  it("keeps one fix per ~10 s while moving and per ~30 s while standing", () => {
    expect(shouldRecord(null, fix(0))).toBe(true);
    expect(shouldRecord(fix(0), fix(5, { speed: 12 }))).toBe(false);
    expect(shouldRecord(fix(0), fix(10, { speed: 12 }))).toBe(true);
    expect(shouldRecord(fix(0), fix(15))).toBe(false); // standing still
    expect(shouldRecord(fix(0), fix(30))).toBe(true);
    expect(shouldRecord(fix(0), fix(12, { lat: 41.301 }))).toBe(true); // ~111 m moved without a speed reading
  });

  it("drops a replayed older fix", () => {
    expect(shouldRecord(fix(40), fix(20))).toBe(false);
  });
});

describe("the queue", () => {
  it("numbers points per session and does not spend a seq on a skipped fix", () => {
    let box = emptyOutbox("trp_1", "trs_1");
    box = enqueue(box, fix(0), T0);
    box = enqueue(box, fix(10, { accuracy: 50_000 }), T0);
    box = enqueue(box, fix(20), T0);
    expect(box.points.map((p) => p.seq)).toEqual([0, 1]);
    expect(box.nextSeq).toBe(2);
  });

  it("drops points older than 24 h and above 20 000, oldest first, and counts them", () => {
    let box = emptyOutbox("trp_1", "trs_1");
    box = enqueue(box, fix(0), T0);
    box = prune(box, T0 + LOCAL_QUEUE_MAX_AGE_MS + 1000);
    expect(box.points).toHaveLength(0);
    expect(box.dropped).toBe(1);

    const many = Array.from({ length: LOCAL_QUEUE_MAX_POINTS + 5 }, (_, i) => toTrackingPoint(fix(i), i)!);
    const full = prune({ ...emptyOutbox("t", "s"), nextSeq: many.length, points: many }, T0);
    expect(full.points).toHaveLength(LOCAL_QUEUE_MAX_POINTS);
    expect(full.points[0].seq).toBe(5);
    expect(full.dropped).toBe(5);
  });

  it("sends at most 100 points per batch", () => {
    const points = Array.from({ length: 250 }, (_, i) => toTrackingPoint(fix(i), i)!);
    expect(nextBatch({ ...emptyOutbox("t", "s"), points })).toHaveLength(MAX_POINTS_PER_BATCH);
  });

  it("removes accepted, duplicate and rejected seqs; rejected ones count as missing history", () => {
    const points = [0, 1, 2, 3].map((i) => toTrackingPoint(fix(i * 10), i)!);
    const box = applyAck(
      { ...emptyOutbox("t", "s"), nextSeq: 4, points },
      { accepted_seqs: [0], duplicate_seqs: [1], rejected: [{ seq: 2, reason: "future_timestamp" }] },
    );
    expect(box.points.map((p) => p.seq)).toEqual([3]);
    expect(box.dropped).toBe(1);
  });

  it("drops a whole refused batch so it cannot block the rest", () => {
    const points = [0, 1, 2].map((i) => toTrackingPoint(fix(i * 10), i)!);
    const box = dropBatch({ ...emptyOutbox("t", "s"), points }, points.slice(0, 2));
    expect(box.points.map((p) => p.seq)).toEqual([2]);
    expect(box.dropped).toBe(2);
  });

  it("renumbers an earlier session's undelivered points into the new session, in capture order", () => {
    const earlier = { ...emptyOutbox("trp_1", "old"), nextSeq: 9, points: [toTrackingPoint(fix(20), 8)!, toTrackingPoint(fix(10), 7)!], dropped: 1 };
    const box = adoptPoints(emptyOutbox("trp_1", "new"), earlier, T0);
    expect(box.points.map((p) => [p.seq, p.captured_at])).toEqual([
      [0, "2026-09-25T08:00:10.000Z"],
      [1, "2026-09-25T08:00:20.000Z"],
    ]);
    expect(box.nextSeq).toBe(2);
    expect(box.dropped).toBe(1);
  });
});

describe("storage", () => {
  it("round-trips a queue", () => {
    let box = emptyOutbox("trp_1", "trs_1");
    box = enqueue(box, fix(0, { speed: 10, heading: 90 }), T0);
    box = enqueue(box, fix(10), T0);
    expect(parseOutbox(serializeOutbox(box))).toEqual(box);
  });

  it("discards anything malformed rather than half-trusting it", () => {
    expect(parseOutbox(null)).toBeNull();
    expect(parseOutbox("{not json")).toBeNull();
    expect(parseOutbox(JSON.stringify({ v: 2 }))).toBeNull();
    expect(parseOutbox(JSON.stringify({ v: 1, trip: "t", session: "s", next: 1, dropped: 0, points: [[0, T0, 99, 0, 5, null, null]] }))).toBeNull();
  });
});

describe("viewer freshness", () => {
  const now = new Date(T0 + 60_000);
  const at = (ageS: number) => ({ captured_at: new Date(now.getTime() - ageS * 1000).toISOString() });

  it("never upgrades the server's bucket, and ages a point on this device's clock", () => {
    expect(effectiveFreshness({ freshness: "fresh", last_point: at(5) }, now)).toBe("fresh");
    expect(effectiveFreshness({ freshness: "fresh", last_point: at(60) }, now)).toBe("delayed");
    expect(effectiveFreshness({ freshness: "fresh", last_point: at(600) }, now)).toBe("lost");
    expect(effectiveFreshness({ freshness: "lost", last_point: at(5) }, now)).toBe("lost");
    expect(effectiveFreshness({ freshness: "fresh", last_point: null }, now)).toBe("no_data");
  });
});

describe("trackableTrip", () => {
  it("picks a running trip only", () => {
    const trips = [
      { id: "a", status: "planned", planned_start_at: "2026-09-25T06:00:00Z" },
      { id: "b", status: "in_progress", planned_start_at: "2026-09-25T09:00:00Z" },
      { id: "c", status: "boarding", planned_start_at: "2026-09-25T07:00:00Z" },
      { id: "d", status: "completed", planned_start_at: "2026-09-25T05:00:00Z" },
    ];
    expect(trackableTrip(trips)?.id).toBe("c");
    expect(trackableTrip(trips.filter((t) => t.id === "a" || t.id === "d"))).toBeNull();
  });
});

describe("battery on points", () => {
  it("carries the battery level and survives storage; older 7-slot entries still load", () => {
    let box = emptyOutbox("trp_1", "trs_1");
    box = enqueue(box, fix(0, { battery: 63.6 }), T0);
    expect(box.points[0].battery_pct).toBe(64);
    expect(parseOutbox(serializeOutbox(box))).toEqual(box);
    const legacy = JSON.stringify({ v: 1, trip: "t", session: "s", next: 1, dropped: 0, points: [[0, T0, 41.3, 69.2, 5, null, null]] });
    expect(parseOutbox(legacy)?.points[0]).not.toHaveProperty("battery_pct");
    expect(toTrackingPoint(fix(0, { battery: 140 }), 0)).not.toHaveProperty("battery_pct");
  });
});
