import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import { View } from "react-native";
import { WebView, type WebViewMessageEvent } from "react-native-webview";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { YANDEX_JS_API_KEY } from "@/core/config";

export type LatLng = { lat: number; lng: number };

/** Imperative controls for the picker. The picker's document is intentionally
 *  stable (see the useMemo deps below), so moving it has to go through here
 *  rather than through a prop change, which would remount the WebView. */
export type YandexMapHandle = { setCenter: (lat: number, lng: number, zoom?: number) => void };

// A stable origin for the WebView document. If the Yandex JS API key is later
// restricted by HTTP Referer, whitelist this exact value in the Yandex console.
const WEBVIEW_ORIGIN = "https://elchi.uz";

// Tashkent centre — fallback when nothing is provided.
const DEFAULT: LatLng = { lat: 41.3111, lng: 69.2797 };

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** Yandex Maps JS API language tag. The JS API has no Uzbek UI locale, so uz
 *  falls back to Latin (en_US); ru keeps Cyrillic. */
function yandexLang(lang: string): string {
  return lang === "ru" ? "ru_RU" : "en_US";
}

function buildHtml(opts: {
  apiKey: string;
  lang: string;
  mode: "route" | "picker";
  center: LatLng;
  pickup: LatLng | null;
  dropoff: LatLng | null;
  accent: string;
  feruza: string;
}): string {
  const { apiKey, lang, mode, center, pickup, dropoff, accent, feruza } = opts;
  const points = JSON.stringify({ pickup, dropoff });
  const interactive = mode === "picker";
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<style>
  html, body, #map { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }
  body { background: #e9edf2; }
</style>
<script src="https://api-maps.yandex.ru/2.1/?apikey=${apiKey}&lang=${lang}"></script>
</head>
<body>
<div id="map"></div>
<script>
  var MODE = "${mode}";
  var INTERACTIVE = ${interactive};
  var CENTER = [${center.lat}, ${center.lng}];
  var POINTS = ${points};
  var ACCENT = "${accent}";
  var FERUZA = "${feruza}";

  function send(obj) {
    if (window.ReactNativeWebView) {
      window.ReactNativeWebView.postMessage(JSON.stringify(obj));
    }
  }

  function pin(coords, color, label) {
    return new ymaps.Placemark(coords, { iconContent: label }, {
      preset: "islands#circleIcon",
      iconColor: color,
    });
  }

  function init() {
    var map = new ymaps.Map("map", {
      center: CENTER,
      zoom: MODE === "picker" ? 15 : 11,
      controls: INTERACTIVE ? ["zoomControl", "geolocationControl"] : [],
    }, { suppressMapOpenBlock: true, yandexMapDisablePoiInteractivity: true });

    // The WebView often reaches its final size AFTER the map inits (e.g. when
    // navigating back to a screen). Refit the map to its container on resize,
    // plus a couple of delayed refits for late layout passes — otherwise the
    // map renders in a small square with blank space around it.
    window.__ymap = map;
    var refit = function () { try { map.container.fitToViewport(); } catch (e) {} };
    window.addEventListener("resize", refit);
    setTimeout(refit, 300);
    setTimeout(refit, 1000);

    if (!INTERACTIVE) {
      map.behaviors.disable(["drag", "scrollZoom", "dblClickZoom", "multiTouch"]);
    }

    if (MODE === "route") {
      var coords = [];
      if (POINTS.pickup) {
        var a = [POINTS.pickup.lat, POINTS.pickup.lng];
        map.geoObjects.add(pin(a, FERUZA, "A"));
        coords.push(a);
      }
      if (POINTS.dropoff) {
        var b = [POINTS.dropoff.lat, POINTS.dropoff.lng];
        map.geoObjects.add(pin(b, ACCENT, "B"));
        coords.push(b);
      }
      if (coords.length === 2) {
        var line = new ymaps.Polyline(coords, {}, {
          strokeColor: ACCENT, strokeWidth: 3, strokeStyle: "shortdash",
        });
        map.geoObjects.add(line);
        map.setBounds(map.geoObjects.getBounds(), { checkZoomRange: true, zoomMargin: 48 });
      } else if (coords.length === 1) {
        map.setCenter(coords[0], 13);
      }
    }

    if (MODE === "picker") {
      // The centre pin is a fixed RN overlay; report the map centre as it moves.
      var report = function () {
        var c = map.getCenter();
        send({ type: "center", lat: c[0], lng: c[1] });
      };
      map.events.add("actionend", report);
      map.events.add("boundschange", report);
      report();
    }

    send({ type: "ready" });
  }

  if (window.ymaps) {
    ymaps.ready(init);
  } else {
    send({ type: "error", message: "yandex-load-failed" });
  }
</script>
</body>
</html>`;
}

/**
 * Yandex Maps rendered in a WebView (the JS API — react-native-maps has no
 * Yandex provider). Two modes:
 *   - "route": read-only A→B preview with a dashed line.
 *   - "picker": interactive; the map moves under a fixed RN centre pin and the
 *     centre coordinates are reported via onCenterChange.
 */
export const YandexMap = forwardRef<
  YandexMapHandle,
  {
    mode: "route" | "picker";
    pickup?: LatLng | null;
    dropoff?: LatLng | null;
    center?: LatLng | null;
    onCenterChange?: (lat: number, lng: number) => void;
  }
>(function YandexMap({ mode, pickup, dropoff, center, onCenterChange }, ref) {
  const { lang } = useT();
  const { colors } = useTheme();
  const webRef = useRef<WebView>(null);

  useImperativeHandle(ref, () => ({
    setCenter(lat: number, lng: number, zoom = 16) {
      // window.__ymap is set during init(); guarded in case the map is not
      // ready yet. The trailing `true;` avoids a warning on Android.
      webRef.current?.injectJavaScript(
        `try { if (window.__ymap) window.__ymap.setCenter([${lat}, ${lng}], ${zoom}); } catch (e) {} true;`,
      );
    },
  }));

  const p = pickup && (num(pickup.lat) !== 0 || num(pickup.lng) !== 0) ? pickup : null;
  const d = dropoff && (num(dropoff.lat) !== 0 || num(dropoff.lng) !== 0) ? dropoff : null;
  const c = center && (num(center.lat) !== 0 || num(center.lng) !== 0) ? center : p ?? DEFAULT;

  const html = useMemo(
    () =>
      buildHtml({
        apiKey: YANDEX_JS_API_KEY,
        lang: yandexLang(lang),
        mode,
        center: c,
        pickup: p,
        dropoff: d,
        accent: colors.primary,
        feruza: colors.feruza,
      }),
    // Route previews remount when endpoints change; the picker keeps a stable
    // document (its centre is reported outward, never pushed back in).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, lang, colors.primary, colors.feruza, mode === "route" ? p?.lat : null, mode === "route" ? p?.lng : null, mode === "route" ? d?.lat : null, mode === "route" ? d?.lng : null],
  );

  function onMessage(event: WebViewMessageEvent) {
    try {
      const msg = JSON.parse(event.nativeEvent.data);
      if (msg.type === "center" && onCenterChange) onCenterChange(msg.lat, msg.lng);
    } catch {
      /* ignore malformed messages */
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.secondary }}>
      <WebView
        ref={webRef}
        originWhitelist={["*"]}
        source={{ html, baseUrl: WEBVIEW_ORIGIN }}
        onMessage={onMessage}
        javaScriptEnabled
        domStorageEnabled
        scrollEnabled={false}
        overScrollMode="never"
        androidLayerType="hardware"
        // Route previews shouldn't intercept touches meant for the sheet above.
        pointerEvents={mode === "picker" ? "auto" : "none"}
        style={{ flex: 1, backgroundColor: "transparent" }}
      />
    </View>
  );
});
