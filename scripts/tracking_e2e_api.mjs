// End-to-end GPS flow over HTTPS + WSS through the Vite dev proxy, against the synthetic elchi_ui_tracking DB.
// driver2: K1 web session -> K2 batches; client: K8 WebSocket; checks marker, spoof handling. SYNTHETIC data.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0"; // throwaway self-signed dev cert
const BASE = process.env.ELCHI_E2E_BASE ?? "https://127.0.0.1:5175";
const OUT = pathToFileURL(path.resolve(process.env.ELCHI_E2E_OUT ?? ".") + path.sep); // adr26_world.json lives here
const world = JSON.parse(fs.readFileSync(new URL("adr26_world.json", OUT)));
const driver = world.driver2.token;
const client = world.client.token;
const bookingId = world.booking;
const results = [];
const check = (name, ok, extra = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${extra ? " - " + extra : ""}`);
};

async function api(path, token, { method = "GET", body, key } = {}) {
  const headers = { Authorization: `Bearer ${token}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  const res = await fetch(`${BASE}/api/v2${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: res.status, json: await res.json().catch(() => null) };
}

const booking = await api(`/bookings/${bookingId}`, driver);
check("driver2 reads the booking over HTTPS", booking.status === 200, `status=${booking.status} ${booking.json?.data?.service_status}`);
const tripId = booking.json.data.trip_id;

let session = await api("/tracking/sessions", driver, {
  method: "POST", key: crypto.randomUUID(),
  body: { trip_id: tripId, device_id: "web-e2e", platform: "web", app_version: "mobile-web/e2e" },
});
if (session.status !== 201) console.log("K1 answer:", JSON.stringify(session.json));
check("K1 opens a web writer session", session.status === 201, `status=${session.status}`);
const sid = session.json.data.id;

// client subscribes over WSS before any point exists
const messages = [];
const ws = new WebSocket(`${BASE.replace("https", "wss")}/api/v2/ws`);
const opened = new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
ws.onmessage = (event) => messages.push(JSON.parse(event.data));
let closeCode = null;
ws.onclose = (event) => { closeCode = event.code; };
await opened;
ws.send(JSON.stringify({ action: "subscribe", booking_id: bookingId, access_token: client }));
const waitFor = async (predicate, ms = 15000) => {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    const hit = messages.find(predicate);
    if (hit) return hit;
    await new Promise((r) => setTimeout(r, 200));
  }
  return null;
};
const first = await waitFor((m) => m.type === "tracking.point");
check("client receives a K8 push over WSS", Boolean(first), first ? `window=${first.data.window?.reason} freshness=${first.data.freshness}` : `close=${closeCode}`);

// honest driving: three points 10 s apart, ~30 m/s, device speed matches
const t0 = Date.now() - 30_000;
const honest = [0, 1, 2].map((i) => ({
  seq: i, captured_at: new Date(t0 + i * 10_000).toISOString(), lat: 39.6542 + 0.0027 * i, lng: 66.9597,
  accuracy_m: 8, speed_mps: 29, heading_deg: 0, battery_pct: 64, is_mock: false,
}));
let ack = await api(`/tracking/sessions/${sid}/points:batch`, driver, { method: "POST", body: { points: honest } });
check("K2 accepts honest points (ACK after commit)", ack.status === 200 && ack.json.data.accepted_seqs.length === 3, JSON.stringify(ack.json?.data));
const live = await waitFor((m) => m.type === "tracking.point" && m.data.last_point && Math.abs(m.data.last_point.lat - honest[2].lat) < 1e-6, 12000);
check("the client's marker moves to the driver's last point", Boolean(live), live ? `lat=${live.data.last_point.lat} freshness=${live.data.freshness}` : "");

// spoof-like points: zero accuracy, a 111 km teleport, device says standing while moving 300 m in 10 s
const s0 = t0 + 30_000;
const spoof = [
  { seq: 3, captured_at: new Date(s0).toISOString(), lat: 39.70, lng: 66.9597, accuracy_m: 0, is_mock: false },
  { seq: 4, captured_at: new Date(s0 + 5_000).toISOString(), lat: 40.66, lng: 66.9597, accuracy_m: 5, is_mock: false },
];
ack = await api(`/tracking/sessions/${sid}/points:batch`, driver, { method: "POST", body: { points: spoof } });
check("K2 stores spoof-like points (flagged, not refused)", ack.status === 200 && ack.json.data.accepted_seqs.length === 2);
await new Promise((r) => setTimeout(r, 7000));
const after = messages.filter((m) => m.type === "tracking.point" && m.data.last_point).at(-1);
check("spoofed points never move the client's marker", after && Math.abs(after.data.last_point.lat - honest[2].lat) < 1e-6, `lat=${after?.data.last_point.lat}`);

const wrong = await api(`/bookings/${bookingId}/tracking`, world.client_new.token);
check("a stranger cannot read the booking's tracking", wrong.status === 404, `status=${wrong.status}`);

ws.close();
fs.writeFileSync(new URL("e2e_session.json", OUT), JSON.stringify({ sid, tripId }));
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
