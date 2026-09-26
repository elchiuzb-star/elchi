// Real-browser check of the driver's GPS publisher (Q148) through Chrome DevTools Protocol - no extra packages.
// Scenarios: HTTP page on a LAN IP (not a secure context), permission denied, permission granted later (auto
// resume), emulated GPS movement reaching the client's tracking API. SYNTHETIC data on elchi_ui_tracking.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
const HERE = pathToFileURL(path.resolve(process.env.ELCHI_E2E_OUT ?? ".") + path.sep); // adr26_world.json lives here
const SECURE = process.env.ELCHI_E2E_BASE ?? "https://127.0.0.1:5175";
const INSECURE = process.env.ELCHI_E2E_INSECURE_BASE ?? "http://192.168.0.104:5176"; // plain HTTP on a LAN IP
const world = JSON.parse(fs.readFileSync(new URL("adr26_world.json", HERE)));
const results = [];
const check = (name, ok, extra = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${extra ? " - " + extra : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = new URL("chrome-profile/", HERE);
fs.rmSync(profile, { recursive: true, force: true });
const chrome = spawn(process.env.ELCHI_E2E_CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe", [
  "--headless=new", "--remote-debugging-port=9333", "--ignore-certificate-errors", "--no-first-run",
  `--user-data-dir=${decodeURIComponent(profile.pathname).replace(/^\//, "")}`, "--window-size=420,900", "about:blank",
]);
let version;
for (let i = 0; i < 50 && !version; i += 1) {
  await sleep(200);
  version = await fetch("http://127.0.0.1:9333/json/version").then((r) => r.json()).catch(() => null);
}
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let nextId = 1;
const pending = new Map();
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  }
};
const send = (method, params = {}, sessionId) =>
  new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });

const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const page = (method, params) => send(method, params, sessionId);
await page("Page.enable");
await page("Runtime.enable");
const evaluate = async (expression) =>
  (await page("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
const barTitle = () => evaluate(`document.querySelector('[data-testid="driver-tracking-title"]')?.textContent ?? null`);
const barText = () => evaluate(`document.querySelector('[data-testid="driver-tracking-bar"]')?.innerText ?? null`);
const waitTitle = async (predicate, ms = 20000) => {
  const until = Date.now() + ms;
  let last = null;
  while (Date.now() < until) {
    last = await barTitle();
    if (last && predicate(last)) return last;
    await sleep(300);
  }
  return last;
};
const openAsDriver = async (origin) => {
  await page("Page.navigate", { url: origin });
  await sleep(1500);
  await evaluate(`localStorage.clear(); localStorage.setItem("elchi_access_token", ${JSON.stringify(world.driver2.token)}); true`);
  await page("Page.navigate", { url: origin });
};
const screenshot = async (name) => {
  const { data } = await page("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(new URL(name, HERE), Buffer.from(data, "base64"));
};

try {
  // 1. HTTP page on a LAN address: the browser gives no location, the bar says HTTPS is needed
  await openAsDriver(INSECURE);
  await waitTitle((t) => t.length > 0);
  const secureFlag = await evaluate("window.isSecureContext");
  await evaluate(`[...document.querySelectorAll('[data-testid="driver-tracking-bar"] button')].find(b => b.textContent === "Yoqish")?.click(); true`);
  const insecureTitle = await waitTitle((t) => t.includes("HTTPS"));
  check("HTTP page on a LAN IP: not a secure context, the bar asks for HTTPS", secureFlag === false && insecureTitle?.includes("HTTPS"), insecureTitle);
  await screenshot("shot-1-insecure.png");

  // 2. HTTPS page, site blocked: no session is opened, the driver is told how to allow it
  await send("Browser.setPermission", { permission: { name: "geolocation" }, setting: "denied", origin: SECURE });
  await openAsDriver(SECURE);
  const idle = await waitTitle((t) => t.length > 0);
  await evaluate(`[...document.querySelectorAll('[data-testid="driver-tracking-bar"] button')].find(b => b.textContent === "Yoqish")?.click(); true`);
  const denied = await waitTitle((t) => t === "Joylashuvga ruxsat berilmagan");
  check("HTTPS + blocked site: the bar says permission is denied", denied === "Joylashuvga ruxsat berilmagan", `idle="${idle}"`);
  await screenshot("shot-2-denied.png");

  // 3. The driver allows it in the browser: publishing resumes by itself with the emulated GPS
  await page("Emulation.setGeolocationOverride", { latitude: 39.6600, longitude: 66.9600, accuracy: 9 });
  await send("Browser.setPermission", { permission: { name: "geolocation" }, setting: "granted", origin: SECURE });
  const sending = await waitTitle((t) => t === "Joylashuv yuborilmoqda", 30000);
  check("permission granted later: resumes on its own and says 'sending'", sending === "Joylashuv yuborilmoqda", sending);
  const bar = await barText();
  check("no 'GPS faol' claim; foreground-only note shown", !/GPS faol/.test(bar) && /faqat ilova ochiq/.test(bar));
  await screenshot("shot-3-sending.png");

  // 4. The car moves: the client's tracking API follows the browser's position
  const clientView = async () => {
    const res = await fetch(`${SECURE}/api/v2/bookings/${world.booking}/tracking`, {
      headers: { Authorization: `Bearer ${world.client.token}` },
    });
    return (await res.json()).data;
  };
  let view = null;
  for (let i = 0; i < 30; i += 1) {
    view = await clientView();
    if (view?.last_point && Math.abs(view.last_point.lat - 39.66) < 1e-6) break;
    await sleep(1000);
  }
  check("client sees the browser's first position", Math.abs(view?.last_point?.lat - 39.66) < 1e-6, JSON.stringify(view?.last_point));
  // drive realistically: ~300 m after 12 s (~25 m/s)
  await sleep(Math.max(0, Date.parse(view.last_point.captured_at) + 12_000 - Date.now()));
  await page("Emulation.setGeolocationOverride", { latitude: 39.6627, longitude: 66.9600, accuracy: 9 });
  for (let i = 0; i < 40; i += 1) {
    view = await clientView();
    if (view?.last_point && Math.abs(view.last_point.lat - 39.6627) < 1e-6) break;
    await sleep(1000);
  }
  check("client sees the car move (~300 m later)", Math.abs(view?.last_point?.lat - 39.6627) < 1e-6,
    `lat=${view?.last_point?.lat} freshness=${view?.freshness}`);

  // 5. a spoofed teleport (~110 km a few seconds later) is stored but never moves the client's marker
  await sleep(3000);
  await page("Emulation.setGeolocationOverride", { latitude: 40.6627, longitude: 66.9600, accuracy: 9 });
  await sleep(25000);
  view = await clientView();
  check("a teleport from the browser never moves the client's marker", Math.abs(view?.last_point?.lat - 39.6627) < 1e-6,
    `lat=${view?.last_point?.lat}`);
  await screenshot("shot-4-after-teleport.png");
} finally {
  ws.close();
  chrome.kill();
}
const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} browser checks passed`);
process.exit(failed ? 1 : 0);
