/* Elchi landing — public page settings (/e/<token>, /t/<token>).
 *
 * Edit the values here; no build step reads this file, the pages load it as is.
 *
 * API_BASE       Backend origin, without /api/v2. The backend must list this site's origins in
 *                ELCHI_CORS_ORIGINS (https://www.elchigo.uz,https://elchigo.uz), or the browser blocks the reads.
 *                Local testing: open the page on localhost / 127.0.0.1 with ?api=http://127.0.0.1:8000 — the
 *                override is ignored on any other host, so a crafted link cannot point the real site at another
 *                server.
 * YANDEX_JS_KEY  Yandex Maps JavaScript API **2.1** key (developer.tech.yandex.ru). It is public by nature (every
 *                visitor's browser receives it), so it MUST be restricted to elchigo.uz / www.elchigo.uz under
 *                "HTTP Referer" in the Yandex developer console. Empty -> the tracking page shows a coordinates card
 *                and no map (never a placeholder map).
 * YANDEX_LANG    Map label language: uz_UZ, ru_RU or en_US.
 * STORE_ANDROID / STORE_IOS
 *                Store pages shown when "Ilovani ochish" finds no installed app. Empty -> the page says the app is
 *                not in the stores yet (true today) instead of linking anywhere.
 */
window.ELCHI_CONFIG = {
	API_BASE: "https://api.elchigo.uz",
	YANDEX_JS_KEY: "3edd1375-5c77-48e9-bda9-c61b69e3d305",
	YANDEX_LANG: "uz_UZ",
	STORE_ANDROID: "",
	STORE_IOS: ""
};
