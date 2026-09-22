import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, MapPin, Search } from "../../app/ui/icons";

import { CentrePin, YandexMap, useYandexMapsStatus } from "./YandexMap";
import { TASHKENT, type LatLng } from "./yandex";
import { geocodeAddress, reverseGeocode, validateGeoLocation } from "../../api/geo.api";
import type { City, District } from "../../types/city";

/**
 * The v1 order form's address picker: a place inside a chosen region/district.
 *
 * It differs from `MapPointPicker` (the Q88 one) in what it is answering. There, the place *is* the direction
 * end and the server decides whether a route serves it. Here the region and district were already chosen, and
 * this only pins the street address inside them - so it asks the backend `validateGeoLocation` whether the pin
 * really falls in the district the person picked, and says so plainly when it does not.
 *
 * Both are Yandex Maps JS API v3; neither invents an address it was not given.
 */
type SelectedLocation = {
  lat: number | null;
  lng: number | null;
  address: string;
};

export type MapAddressPickerProps = {
  mode: "pickup" | "dropoff";
  city: City;
  district?: District | null;
  initialLat?: number | null;
  initialLng?: number | null;
  initialAddress?: string;
  onConfirm: (location: SelectedLocation) => void;
  onBack: () => void;
};

function readCoordinate(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function coordinateLabel(point: LatLng): string {
  return `Tanlangan nuqta: ${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}`;
}

export function MapAddressPicker({
  mode,
  city,
  district,
  initialLat,
  initialLng,
  initialAddress,
  onConfirm,
  onBack,
}: MapAddressPickerProps) {
  const status = useYandexMapsStatus();
  const title = mode === "pickup" ? "Olib ketish joyini belgilang" : "Yetkazish joyini belgilang";
  const districtLabel = [district?.name_uz, city.name_uz, city.region].filter(Boolean).join(", ");

  const start = useMemo<LatLng>(() => {
    const lat = initialLat ?? readCoordinate(district?.center_lat);
    const lng = initialLng ?? readCoordinate(district?.center_lng);
    return lat !== null && lng !== null ? { lat, lng } : TASHKENT;
  }, [initialLat, initialLng, district?.center_lat, district?.center_lng]);

  const [settled, setSettled] = useState<LatLng>(start);
  const [target, setTarget] = useState<LatLng>(start);
  const [address, setAddress] = useState<string>(initialAddress || districtLabel || "");
  const [manualAddress, setManualAddress] = useState(initialAddress ?? "");
  const [query, setQuery] = useState("");
  const [searchMiss, setSearchMiss] = useState(false);
  const [locationWarning, setLocationWarning] = useState(
    district && (readCoordinate(district.center_lat) === null || readCoordinate(district.center_lng) === null)
      ? "Bu tuman uchun default koordinata topilmadi"
      : "",
  );
  const [validating, setValidating] = useState(false);
  const searching = useRef(false);

  /** Name the pin, debounced, through our own backend. When it cannot answer the coordinates stand in. */
  useEffect(() => {
    if (status !== "ready") return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void reverseGeocode({ lat: settled.lat, lng: settled.lng })
        .then((found) => {
          if (!cancelled && found.formatted_address) setAddress(found.formatted_address);
        })
        .catch(() => undefined);
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [settled.lat, settled.lng, status]);

  /** The backend owns the region/district boundaries, so it is asked rather than guessed at. */
  useEffect(() => {
    if (!district?.id) {
      setLocationWarning("");
      return;
    }
    let active = true;
    setValidating(true);
    validateGeoLocation({ lat: settled.lat, lng: settled.lng, region_id: city.id, district_id: district.id })
      .then((result) => {
        if (active) setLocationWarning(result.valid ? "" : result.message || "Marker tanlangan viloyat/tumanga mos emas");
      })
      .catch(() => {
        if (active) setLocationWarning("Marker tanlangan viloyat/tumanga mos emas");
      })
      .finally(() => {
        if (active) setValidating(false);
      });
    return () => {
      active = false;
    };
  }, [city.id, district?.id, settled.lat, settled.lng]);

  async function runSearch() {
    if (searching.current || !query.trim()) return;
    searching.current = true;
    setSearchMiss(false);
    try {
      const address = [query, district?.name_uz, city.name_uz].filter(Boolean).join(", ");
      const hit = await geocodeAddress({ address }).catch(() => null);
      if (!hit || hit.lat === null || hit.lng === null) {
        setSearchMiss(true);
        return;
      }
      const point = { lat: hit.lat, lng: hit.lng };
      setTarget(point);
      setSettled(point);
      setAddress(hit.formatted_address ?? address);
    } finally {
      searching.current = false;
    }
  }

  // Without a map the address can still be typed - the v1 order needs an address string, not a pin.
  if (status === "missing-key" || status === "error") {
    return (
      <div className="absolute inset-0 z-50 flex flex-col bg-card">
        <div className="flex h-14 items-center gap-3 border-b border-border px-5">
          <button type="button" aria-label="Orqaga" onClick={onBack} className="el-press flex h-9 w-9 items-center justify-center rounded-full bg-muted">
            <ArrowLeft size={18} />
          </button>
          <h2 className="text-[17px] font-semibold text-foreground">{title}</h2>
        </div>
        <div className="flex flex-1 flex-col justify-center px-6 text-center">
          <p className="text-[18px] font-semibold text-foreground">
            {status === "missing-key" ? "Xarita kaliti kiritilmagan" : "Xarita yuklanmadi"}
          </p>
          <p className="mt-2 text-[14px] leading-6 text-muted-foreground">Manzilni qo'lda kiriting</p>
          <input
            value={manualAddress}
            onChange={(event) => setManualAddress(event.target.value)}
            placeholder="Manzil"
            className="el-focus mt-5 h-[52px] rounded-[12px] border-[1.5px] border-border px-4 text-[15px] outline-none"
          />
          <div className="mt-4 grid grid-cols-2 gap-3">
            <button onClick={onBack} className="el-press h-[52px] rounded-[14px] bg-muted text-[15px] font-semibold text-muted-foreground">
              Bekor qilish
            </button>
            <button
              disabled={!manualAddress.trim()}
              onClick={() => onConfirm({ lat: null, lng: null, address: manualAddress.trim() })}
              className="el-press h-[52px] rounded-[14px] bg-primary text-[15px] font-semibold text-primary-foreground disabled:bg-slate-400"
            >
              Saqlash
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-50 flex flex-col bg-card">
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-5">
        <button type="button" aria-label="Orqaga" onClick={onBack} className="el-press flex h-9 w-9 items-center justify-center rounded-full bg-muted">
          <ArrowLeft size={18} />
        </button>
        <h2 className="min-w-0 flex-1 truncate text-[17px] font-semibold text-foreground">{title}</h2>
      </div>

      <div className="relative min-h-0 flex-1">
        <YandexMap
          center={target}
          zoom={initialLat !== null && initialLat !== undefined ? 16 : 13}
          onCenterSettled={setSettled}
          style={{ width: "100%", height: "100%" }}
          fallback={() => (
            <div className="flex h-full items-center justify-center bg-muted text-[14px] text-muted-foreground">
              Xarita yuklanmoqda...
            </div>
          )}
        />
        {status === "ready" && <CentrePin />}
        {status === "ready" && (
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
                  if (event.key === "Enter") void runSearch();
                }}
                placeholder="Manzil yoki joy nomi"
                className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none"
              />
            </label>
            {searchMiss && (
              <p className="mt-2 rounded-[10px] bg-card/95 px-3 py-2 text-[12px] text-muted-foreground shadow-sm">
                Bu nom bo'yicha joy topilmadi — xaritani qo'lda suring.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 space-y-3 border-t border-border bg-card px-5 py-4">
        <div className="rounded-[14px] border border-border bg-slate-50 p-4">
          <p className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <MapPin size={13} color="var(--primary)" /> Tanlangan joy
          </p>
          <p className="mt-1 text-[15px] font-semibold leading-6 text-foreground">
            {address || coordinateLabel(settled)}
          </p>
        </div>
        {locationWarning && (
          <p className="rounded-[12px] bg-warning/14 px-4 py-3 text-[13px] leading-5 text-warning">{locationWarning}</p>
        )}
        <button
          disabled={validating}
          onClick={() => onConfirm({ lat: settled.lat, lng: settled.lng, address: address || coordinateLabel(settled) })}
          className="el-press flex h-[52px] w-full items-center justify-center rounded-[14px] bg-primary text-[16px] font-semibold text-primary-foreground disabled:bg-slate-400"
        >
          {validating ? "Tekshirilmoqda..." : "Shu joyni tanlash"}
        </button>
      </div>
    </div>
  );
}
