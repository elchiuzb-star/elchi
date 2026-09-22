import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Crosshair, MapPin, Search } from "../../app/ui/icons";

import { cls } from "../../app/ui/mobile";
import { CentrePin, YandexMap, useYandexMapsStatus } from "../maps/YandexMap";
import { TASHKENT, type LatLng } from "../maps/yandex";
import { resolvePlace, reverseGeocode, suggestPlaces, type PlaceSuggestion } from "../../api/geo.api";
import type { StopOption } from "./stops";

/**
 * "Joyni belgilang" - the client marks a place on the map instead of picking a verified stop (Q88).
 *
 * The pin sits at the centre of the viewport and the map moves under it: there is nothing to aim at with a
 * fingertip, and the chosen place is always exactly what the person is looking at. The address underneath is
 * reverse-geocoded, so the confirmation reads like a place ("Samarqand, Registon ko'chasi") rather than like a
 * coordinate - but the coordinate is what is sent, because that is what the route projection needs.
 *
 * What this screen deliberately does **not** do is decide whether the place is servable. Only the server knows
 * which corridors exist, which routes are confirmed and how far off the road each corridor tolerates. The
 * screen explains the rule and shows the server's answer; it never pre-judges it.
 *
 * The address comes from our own backend (`/geo/reverse-geocode`, Yandex behind it). When it cannot answer the
 * line falls back to the coordinates - the place can still be marked, which is the part that matters.
 */
export type MarkedPoint = {
  lat: number;
  lng: number;
  address: string | null;
};

type MapPointPickerProps = {
  title: string;
  /** Where the map opens: the district the person chose, or their previous pick when re-editing. */
  initial?: MarkedPoint | null;
  /**
   * Where the camera opens when nothing has been marked yet, and how closely that point is known.
   *
   * Without it every picker opened over Tashkent, so somebody choosing Urgut had to drag the map across the
   * country before they could drop a pin. It is a *viewport* only - the pin still has to be placed, and the
   * server still decides whether the place is on a confirmed route (Q88).
   *
   * `scope` decides the zoom, and it is not cosmetic. A district centre is the town, so the map can open
   * close in. A region centre is the provincial capital, which may be a hundred kilometres from the district
   * the person actually chose; opening close in on it would look like the map had found their town. `null`
   * when the catalogue knows neither, and the country view is then the honest starting point.
   */
  districtCenter?: { lat: number; lng: number; scope: "district" | "region" } | null;
  districtName?: string;
  /**
   * The chosen district on its own ("Kasbi"), not the "district, region" line above the sheet.
   *
   * It is what makes the search answer where the person actually is: the server lists places inside this
   * district first. Nothing is hidden - a school one district over still appears, just below.
   */
  searchDistrict?: string | null;
  /** Metres: what this corridor tolerates, explained in the person's own terms. Null until the server says. */
  maxOffsetM?: number | null;
  /** Set when the server refused the *previous* pick; shown so the person knows what to change. */
  routeError?: string | null;
  busy?: boolean;
  /**
   * Verified stops in the chosen district, when the catalogue has any.
   *
   * Offered, never required. A stop is a meeting place an operator checked, and picking one gives the listing
   * an `exact` match instead of a projected one (Q88) - but only six districts have one, so the map is the
   * flow and these are a shortcut inside it.
   */
  stops?: StopOption[];
  onSelectStop?: (option: StopOption) => void;
  onConfirm: (point: MarkedPoint) => void;
  onBack: () => void;
};

function coordinateLabel(lat: number, lng: number): string {
  return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

export function MapPointPicker({
  title,
  initial,
  districtCenter,
  districtName,
  searchDistrict,
  maxOffsetM,
  routeError,
  busy,
  stops,
  onSelectStop,
  onConfirm,
  onBack,
}: MapPointPickerProps) {
  const status = useYandexMapsStatus();
  const start = useMemo<LatLng>(
    () => (initial ? { lat: initial.lat, lng: initial.lng } : districtCenter ?? TASHKENT),
    [initial, districtCenter?.lat, districtCenter?.lng],
  );
  const startZoom = initial ? 16 : districtCenter?.scope === "district" ? 12 : districtCenter ? 9 : 6;

  /**
   * Is the camera position a stand-in rather than a place?
   *
   * The camera opens on the chosen district when the catalogue has its centre. 65 of the 170 districts have
   * none, and for those it opens on the provincial capital instead - which is a *different district*. Left
   * alone, the screen then offered that capital as "the chosen place": pick Kasbi, confirm, and the pin is in
   * Qarshi. So when the opening position is only a region, it is a view and not an answer, and the person has
   * to put the pin somewhere before this screen will hand anything back.
   */
  const standingIn = !initial && districtCenter?.scope === "region";

  /** Where the pin is. `settled` is the map's own centre after a gesture; `target` re-centres the map. */
  const [settled, setSettled] = useState<LatLng>(start);
  /** True once the pin is somewhere the person put it - by panning, searching, or re-editing an old pick. */
  const [placed, setPlaced] = useState(!standingIn);
  const [target, setTarget] = useState<LatLng>(start);
  const [address, setAddress] = useState<string | null>(initial?.address ?? null);
  const [looking, setLooking] = useState(false);
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [searchMiss, setSearchMiss] = useState(false);
  const [resolving, setResolving] = useState(false);

  /**
   * Where the search looks first.
   *
   * The chosen district's centre when the catalogue has it, otherwise wherever the map is now. Either way it
   * is a *preference*: the server ranks by it, it does not filter by it.
   */
  const searchNear = useMemo(
    () =>
      districtCenter?.scope === "district"
        ? { lat: districtCenter.lat, lng: districtCenter.lng }
        : { lat: settled.lat, lng: settled.lng },
    [districtCenter?.lat, districtCenter?.lng, districtCenter?.scope, settled.lat, settled.lng],
  );

  /**
   * Name the centre, debounced: one lookup per rest, not per frame of panning.
   *
   * Only a real geocoder answer becomes a name. When the provider is not configured the server replies
   * `provider: "local"` with the nearest district it can find - and that search runs over the legacy
   * catalogue, whose coordinates are the generated lattice wave 17.1 found (`district_center()`). It once
   * labelled a pin standing in Qarshi "Kitob". A wrong place name is worse than no place name, so a local
   * answer is treated as no answer and the coordinates are shown instead, which is exactly as true.
   */
  useEffect(() => {
    let cancelled = false;
    setLooking(true);
    const timer = window.setTimeout(() => {
      void reverseGeocode({ lat: settled.lat, lng: settled.lng })
        .then((found) => {
          if (!cancelled) setAddress(found.provider === "local" ? null : (found.formatted_address ?? null));
        })
        .catch(() => {
          if (!cancelled) setAddress(null);
        })
        .finally(() => {
          if (!cancelled) setLooking(false);
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [settled.lat, settled.lng]);

  /**
   * Suggest as the person types, debounced.
   *
   * A school, a bazaar or a hokimlik is not an address, so this asks the suggest service rather than the
   * geocoder - and asks it from inside the chosen district, which is what puts "10-sonli maktab" in Kasbi
   * above the six others with the same name elsewhere in the country.
   */
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      setSuggestions([]);
      setSearchMiss(false);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void suggestPlaces({ text, near: searchNear, district: searchDistrict ?? null, limit: 8 })
        .then((answer) => {
          if (cancelled) return;
          setSuggestions(answer.results);
          setSearchMiss(answer.results.length === 0);
        })
        .catch(() => {
          if (cancelled) return;
          setSuggestions([]);
          setSearchMiss(true);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, searchDistrict, searchNear.lat, searchNear.lng]);

  /** A suggestion carries no coordinate - it is resolved only when somebody picks it. */
  async function pickSuggestion(item: PlaceSuggestion) {
    if (resolving) return;
    setResolving(true);
    try {
      const hit = await resolvePlace({ uri: item.uri }).catch(() => null);
      if (!hit || hit.lat === null || hit.lng === null) {
        setSearchMiss(true);
        return;
      }
      const point = { lat: hit.lat, lng: hit.lng };
      setTarget(point);
      setSettled(point);
      setPlaced(true);
      setAddress(hit.formatted_address ?? item.title ?? null);
      setQuery("");
      setSuggestions([]);
    } finally {
      setResolving(false);
    }
  }

  const radiusHint =
    maxOffsetM == null
      ? "Joy ELCHI yo'nalishidagi yo'ldan uzoq bo'lmasligi kerak."
      : `Joy haydovchi yuradigan yo'ldan ${Math.round(maxOffsetM / 1000)} km dan uzoq bo'lmasligi kerak — haydovchi yo'lidan chiqmasdan sizni ola bilishi uchun.`;

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-card">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-5">
        <button
          type="button"
          onClick={onBack}
          aria-label="Orqaga"
          className="el-press flex h-10 w-10 items-center justify-center rounded-full bg-muted"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-[17px] font-bold text-foreground">{title}</h1>
      </header>

      <div className="relative min-h-0 flex-1">
        <YandexMap
          center={target}
          zoom={startZoom}
          onCenterSettled={(centre) => {
            setSettled(centre);
            setPlaced(true);
          }}
          style={{ width: "100%", height: "100%" }}
          fallback={(state) => (
            <div className="flex h-full flex-col items-center justify-center gap-3 bg-muted px-8 text-center">
              <MapPin size={30} color="color-mix(in srgb, var(--foreground) 42%, var(--background))" />
              <p className="text-[14px] leading-6 text-muted-foreground">
                {state === "loading"
                  ? "Xarita yuklanmoqda..."
                  : state === "missing-key"
                    ? // Only offered when the camera really is on the chosen district. It used to be said
                      // unconditionally, which is how a pin standing in the provincial capital was offered as
                      // "the centre of Kasbi".
                      standingIn
                      ? "Xarita kaliti sozlanmagan va bu tumanning markazi katalogda yo'q — joyni belgilay olmaysiz."
                      : "Xarita kaliti sozlanmagan — joyni tuman markazidan tasdiqlashingiz mumkin."
                    : "Xarita yuklanmadi — internetni tekshirib qayta urinib ko'ring."}
              </p>
            </div>
          )}
        />
        {status === "ready" && (
          <>
            {/* The pin is fixed to the centre: the map moves, the target does not. */}
            <CentrePin />
            <div className="absolute inset-x-0 top-0 p-4">
              <label className="el-focus flex h-12 items-center gap-3 rounded-[16px] border-[1.5px] border-border bg-card px-4 shadow-sm">
                <Search size={19} color="var(--muted-foreground)" />
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setSearchMiss(false);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && suggestions.length > 0) void pickSuggestion(suggestions[0]);
                  }}
                  placeholder="Manzil yoki joy nomi"
                  className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none"
                />
              </label>
              {suggestions.length > 0 && (
                <ul className="mt-2 max-h-[240px] overflow-y-auto rounded-[14px] border border-border bg-card shadow-lg">
                  {suggestions.map((item) => {
                    // Marked, not filtered: the person can see at a glance which hits are in the district
                    // they chose and which are somewhere else, and still pick either.
                    const here = Boolean(
                      searchDistrict && item.district && item.district.toLowerCase().includes(searchDistrict.toLowerCase()),
                    );
                    return (
                      <li key={item.uri}>
                        <button
                          type="button"
                          disabled={resolving}
                          onClick={() => void pickSuggestion(item)}
                          className="el-press flex w-full items-start gap-3 border-b border-border px-3.5 py-2.5 text-left last:border-b-0 disabled:opacity-60"
                        >
                          <MapPin size={15} color={here ? "var(--primary)" : "var(--muted-foreground)"} className="mt-0.5 shrink-0" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[14px] font-semibold text-foreground">{item.title}</span>
                            <span className="block truncate text-[12px] text-muted-foreground">
                              {item.subtitle || item.formatted_address || ""}
                            </span>
                          </span>
                          {item.distance_m != null && (
                            <span className={cls("shrink-0 text-[11px] font-medium", here ? "text-primary" : "text-slate-400")}>
                              {item.distance_m < 1000
                                ? `${item.distance_m} m`
                                : `${Math.round(item.distance_m / 1000)} km`}
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              {searchMiss && suggestions.length === 0 && (
                <p className="mt-2 rounded-[10px] bg-card/95 px-3 py-2 text-[12px] leading-5 text-muted-foreground shadow-sm">
                  Bu nom bo'yicha joy topilmadi — xaritani qo'lda suring.
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => setTarget({ ...settled })}
              aria-label="Markazga qaytish"
              className="el-press absolute bottom-4 right-4 flex h-11 w-11 items-center justify-center rounded-full bg-card text-primary shadow-lg"
            >
              <Crosshair size={20} />
            </button>
          </>
        )}
      </div>

      <section className="shrink-0 space-y-3 border-t border-border bg-card px-5 py-4">
        {districtName && <p className="truncate text-[13px] font-semibold text-muted-foreground">{districtName}</p>}

        {stops && stops.length > 0 && onSelectStop && (
          <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
            {stops.map((option) => (
              <button
                key={option.stop.id}
                type="button"
                onClick={() => onSelectStop(option)}
                className="el-press flex shrink-0 items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3 py-1.5 text-[13px] font-semibold text-primary"
              >
                <MapPin size={14} />
                {option.stop.name_uz}
              </button>
            ))}
          </div>
        )}
        <div className="rounded-[14px] border border-border bg-slate-50 p-4">
          <p className="text-[12px] text-muted-foreground">{placed ? "Tanlangan joy" : "Joy belgilanmagan"}</p>
          <p
            className={cls(
              "mt-1 text-[15px] leading-6",
              placed ? "font-semibold text-foreground" : "text-muted-foreground",
            )}
          >
            {!placed
              ? `${districtName || "Tuman"} xaritada ochilmadi — joyni o'zingiz belgilang`
              : looking
                ? "Manzil aniqlanmoqda..."
                : address || coordinateLabel(settled.lat, settled.lng)}
          </p>
          {placed && !looking && address && (
            <p className="mt-0.5 text-[12px] text-slate-400">{coordinateLabel(settled.lat, settled.lng)}</p>
          )}
        </div>

        {routeError ? (
          <p className="rounded-[12px] bg-destructive/10 px-4 py-3 text-[13px] leading-5 text-destructive">{routeError}</p>
        ) : !placed ? (
          /* Said plainly, because the camera is somewhere else than the name above it: this district has no
             coordinate in the catalogue yet, so the map opened on the province. */
          <p className="rounded-[12px] bg-warning/14 px-4 py-3 text-[13px] leading-5 text-warning">
            Bu tumanning markazi katalogda hali yo'q, shuning uchun xarita viloyat bo'yicha ochildi. Xaritani
            surib yoki qidiruvdan foydalanib o'z joyingizni belgilang.
          </p>
        ) : (
          <p className="text-[12px] leading-5 text-muted-foreground">{radiusHint}</p>
        )}

        <button
          type="button"
          disabled={busy || !placed}
          onClick={() => onConfirm({ lat: settled.lat, lng: settled.lng, address })}
          className="el-press flex h-[52px] w-full items-center justify-center rounded-[14px] bg-primary px-4 text-[16px] font-semibold text-primary-foreground disabled:bg-slate-400"
        >
          {busy ? "Tekshirilmoqda..." : "Shu joyni tanlash"}
        </button>
      </section>
    </main>
  );
}
