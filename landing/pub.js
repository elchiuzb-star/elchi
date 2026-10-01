/* Elchi landing — helpers shared by the public pages (/e/<token>, /t/<token>). No framework, no build.
 * Everything the server returns is written with textContent, never as HTML. */
(function () {
	"use strict";

	var cfg = window.ELCHI_CONFIG || {};
	var TZ = "Asia/Tashkent";

	/** True on a developer machine; the ?api= override works only there (see config.js). */
	function isLocalHost(host) {
		return /^(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)$/.test(host);
	}

	function apiBase() {
		var base = cfg.API_BASE || "https://api.elchigo.uz";
		if (isLocalHost(location.hostname)) {
			var override = new URLSearchParams(location.search).get("api");
			if (override && /^https?:\/\/[^/?#]+$/.test(override.replace(/\/$/, ""))) base = override;
		}
		return base.replace(/\/$/, "");
	}

	/** The token after `/e/` or `/t/`, or "" when the address has none. */
	function tokenFrom(prefix) {
		var rest = location.pathname.split(prefix)[1] || "";
		try {
			return decodeURIComponent(rest.split(/[/?#]/)[0]).trim();
		} catch (e) {
			return "";
		}
	}

	/**
	 * GET {API}/api/v2{path} without credentials. Resolves to {status, data}; status 0 = no answer (network, CORS,
	 * timeout). `data` is the envelope's `data` on 2xx, otherwise null.
	 */
	function getV2(path, timeoutMs) {
		var ctrl = "AbortController" in window ? new AbortController() : null;
		var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, timeoutMs || 12000) : null;
		return fetch(apiBase() + "/api/v2" + path, {
			method: "GET",
			credentials: "omit",
			cache: "no-store",
			referrerPolicy: "no-referrer",
			headers: { Accept: "application/json" },
			signal: ctrl ? ctrl.signal : undefined
		}).then(function (res) {
			if (timer) clearTimeout(timer);
			if (!res.ok) return { status: res.status, data: null };
			return res.json().then(function (body) {
				return { status: res.status, data: body && body.data ? body.data : null };
			}, function () {
				return { status: 0, data: null };
			});
		}, function () {
			if (timer) clearTimeout(timer);
			return { status: 0, data: null };
		});
	}

	function parts(iso) {
		var d = new Date(iso);
		if (isNaN(d.getTime())) return null;
		var out = {};
		new Intl.DateTimeFormat("en-GB", {
			timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
			hour: "2-digit", minute: "2-digit", hourCycle: "h23"
		}).formatToParts(d).forEach(function (p) { out[p.type] = p.value; });
		return out;
	}

	/** "2026-09-29" -> "29.09.2026". */
	function dateText(value) {
		var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
		return m ? m[3] + "." + m[2] + "." + m[1] : "—";
	}

	/** Departure window in Tashkent time: "09:00 – 18:00", or with dates when it crosses midnight. */
	function windowText(startIso, endIso) {
		var a = parts(startIso), b = parts(endIso);
		if (!a) return "—";
		var from = a.hour + ":" + a.minute;
		if (!b) return from;
		var to = b.hour + ":" + b.minute;
		if (a.day === b.day && a.month === b.month && a.year === b.year) return from + " – " + to;
		return a.day + "." + a.month + " " + from + " – " + b.day + "." + b.month + " " + to;
	}

	/** Integer minor units -> "150 000 so'm" (no floating point). */
	function money(minor, currency) {
		if (typeof minor !== "number" || !isFinite(minor)) return "—";
		var neg = minor < 0;
		var abs = Math.abs(Math.trunc(minor));
		var major = String(Math.trunc(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
		var cents = abs % 100;
		var unit = !currency || currency === "UZS" ? "so'm" : currency;
		var text = major + (cents ? "," + (cents < 10 ? "0" : "") + cents : "") + " " + unit;
		return neg ? "−" + text : text;
	}

	/** Minutes or hours since an ISO time, in Uzbek. */
	function ago(iso, now) {
		var t = Date.parse(iso);
		if (isNaN(t)) return "—";
		var minutes = Math.max(0, Math.floor(((now || Date.now()) - t) / 60000));
		if (minutes < 1) return "1 daqiqadan kam";
		if (minutes < 60) return minutes + " daqiqa oldin";
		var hours = Math.floor(minutes / 60);
		var rest = minutes % 60;
		return hours + " soat" + (rest ? " " + rest + " daqiqa" : "") + " oldin";
	}

	function el(id) { return document.getElementById(id); }

	function show(id, on) {
		var node = el(id);
		if (node) node.hidden = !on;
	}

	function text(id, value) {
		var node = el(id);
		if (node) node.textContent = value;
	}

	window.ElchiPub = {
		config: cfg, apiBase: apiBase, tokenFrom: tokenFrom, getV2: getV2, dateText: dateText,
		windowText: windowText, money: money, ago: ago, el: el, show: show, text: text
	};

	var yr = document.getElementById("yr");
	if (yr) yr.textContent = new Date().getFullYear();
})();
