import { useCallback, useEffect, useRef, useState } from "react";
import { GoogleMap, StandaloneSearchBox } from "@react-google-maps/api";
import { CaretLeft as ChevronLeft, MagnifyingGlass as Search, MapPin, Crosshair as Locate } from "@phosphor-icons/react";
import { googleMapsMapId } from "./googleMapsConfig";
import { useMapsLoader, reverseGeocode, geocodeRegion } from "./useMapsLoader";

const TASHKENT = { lat: 41.2995, lng: 69.2401 };

export type PickedLocation = { lat: number; lng: number; address: string };

type LocationPickerProps = {
  title: string;
  initialCenter?: { lat: number; lng: number } | null;
  regionQuery?: string;
  initialAddress?: string;
  onBack: () => void;
  onConfirm: (location: PickedLocation) => void;
};

/**
 * Full-screen Google Maps picker with a fixed centre pin: the user drags the map
 * under the pin and the address is reverse-geocoded from the map centre.
 */
export function LocationPicker({ title, initialCenter, regionQuery, initialAddress, onBack, onConfirm }: LocationPickerProps) {
  const { isLoaded, loadError, hasKey } = useMapsLoader();
  const start = initialCenter ?? TASHKENT;
  // Bias address search towards the selected city/district (~35 km box around its centre as a start).
  const BIAS_DEG = 0.35;
  const initialBounds: google.maps.LatLngBoundsLiteral | undefined = initialCenter
    ? { north: start.lat + BIAS_DEG, south: start.lat - BIAS_DEG, east: start.lng + BIAS_DEG, west: start.lng - BIAS_DEG }
    : undefined;
  const [center, setCenter] = useState(start);
  const [address, setAddress] = useState(initialAddress ?? "");
  const [resolving, setResolving] = useState(false);
  const [searchBounds, setSearchBounds] = useState<google.maps.LatLngBoundsLiteral | undefined>(initialBounds);
  const mapRef = useRef<google.maps.Map | null>(null);
  const searchRef = useRef<google.maps.places.SearchBox | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resolve = useCallback((lat: number, lng: number) => {
    setResolving(true);
    reverseGeocode(lat, lng).then((addr) => { setAddress(addr); setResolving(false); });
  }, []);

  // On open: focus the map on the selected region and bias search to its exact viewport.
  useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;
    if (initialCenter && !address) resolve(start.lat, start.lng);
    if (regionQuery) {
      geocodeRegion(regionQuery).then((region) => {
        if (cancelled || !region) {
          if (!initialCenter && !address) resolve(start.lat, start.lng);
          return;
        }
        // Bias search to the region: use its viewport, or a box around its centre.
        const box: google.maps.LatLngBoundsLiteral = {
          north: region.location.lat + 0.12, south: region.location.lat - 0.12,
          east: region.location.lng + 0.12, west: region.location.lng - 0.12,
        };
        setSearchBounds(region.bounds ?? box);
        if (!initialCenter) {
          setCenter(region.location);
          mapRef.current?.panTo(region.location);
          mapRef.current?.setZoom(13);
          resolve(region.location.lat, region.location.lng);
        }
      });
    } else if (!initialCenter && !address) {
      resolve(start.lat, start.lng);
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded]);

  const onIdle = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const c = map.getCenter();
    if (!c) return;
    const lat = c.lat(); const lng = c.lng();
    setCenter({ lat, lng });
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => resolve(lat, lng), 350);
  }, [resolve]);

  const onPlaces = useCallback(() => {
    const places = searchRef.current?.getPlaces();
    if (!places?.length) return;
    // Prefer the first result that falls inside the selected city/district area.
    const inside = searchBounds
      ? places.find((p) => {
          const l = p.geometry?.location;
          return (
            l &&
            l.lat() <= searchBounds.north && l.lat() >= searchBounds.south &&
            l.lng() <= searchBounds.east && l.lng() >= searchBounds.west
          );
        })
      : undefined;
    const place = inside ?? places[0];
    const loc = place.geometry?.location;
    if (!loc) return;
    const next = { lat: loc.lat(), lng: loc.lng() };
    setCenter(next);
    setAddress(place.formatted_address || place.name || "");
    mapRef.current?.panTo(next);
    mapRef.current?.setZoom(16);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchBounds?.north, searchBounds?.south, searchBounds?.east, searchBounds?.west]);

  function locateMe() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      const next = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      setCenter(next);
      mapRef.current?.panTo(next);
      mapRef.current?.setZoom(16);
      resolve(next.lat, next.lng);
    });
  }

  // Graceful fallback (no key / load error): manual address entry.
  if (!hasKey || loadError) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-3 p-4 border-b border-border flex-shrink-0">
          <button onClick={onBack} className="p-2 rounded-xl bg-secondary"><ChevronLeft size={18} className="text-foreground"/></button>
          <h1 className="text-base font-semibold text-foreground flex-1">{title}</h1>
        </div>
        <div className="flex-1 flex flex-col justify-center px-6 text-center gap-4">
          <p className="text-sm text-muted-foreground">{loadError ? "Xarita yuklanmadi" : "Google Maps API kaliti sozlanmagan"}. Manzilni qo'lda kiriting.</p>
          <input value={address} onChange={(e)=>setAddress(e.target.value)} placeholder="Manzil" className="bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground outline-none focus:border-primary/60"/>
          <button onClick={()=>address.trim()&&onConfirm({ lat: center.lat, lng: center.lng, address: address.trim() })} disabled={!address.trim()} className="w-full bg-primary text-white rounded-2xl py-3 text-sm font-semibold disabled:opacity-50">Tasdiqlash</button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full relative">
      <div className="absolute inset-0">
        {isLoaded ? (
          <GoogleMap
            mapContainerStyle={{ width: "100%", height: "100%" }}
            center={start}
            zoom={initialCenter ? 14 : 12}
            onLoad={(m)=>{ mapRef.current = m; }}
            onUnmount={()=>{ mapRef.current = null; }}
            onIdle={onIdle}
            options={{ clickableIcons: false, fullscreenControl: false, mapTypeControl: false, streetViewControl: false, zoomControl: false, mapId: googleMapsMapId, gestureHandling: "greedy" }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-secondary/60"><span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/></div>
        )}
      </div>

      {/* Top bar + search */}
      <div className="relative z-10 flex items-center gap-3 p-4">
        <button onClick={onBack} className="p-2 rounded-xl bg-card border border-border shadow"><ChevronLeft size={18} className="text-foreground"/></button>
        {isLoaded && (
          <StandaloneSearchBox onLoad={(b)=>{ searchRef.current = b; }} onPlacesChanged={onPlaces} bounds={searchBounds}>
            <div className="flex-1 bg-card border border-border rounded-xl px-3 py-2 flex items-center gap-2 shadow">
              <Search size={13} className="text-muted-foreground"/>
              <input className="flex-1 bg-transparent text-sm text-foreground outline-none" placeholder="Manzil qidirish" />
            </div>
          </StandaloneSearchBox>
        )}
      </div>

      {/* Centre pin */}
      <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none" style={{ paddingBottom: 190 }}>
        <div className="flex flex-col items-center -mt-6">
          <div className="w-10 h-10 rounded-full bg-primary border-4 border-white shadow-xl flex items-center justify-center"><MapPin size={18} className="text-white"/></div>
          <div className="w-2 h-2 bg-primary/40 rounded-full mt-0.5"/>
        </div>
      </div>

      <button onClick={locateMe} className="absolute right-4 bottom-52 z-10 w-10 h-10 rounded-xl bg-card border border-border shadow flex items-center justify-center"><Locate size={16} className="text-primary"/></button>

      {/* Bottom sheet */}
      <div className="absolute bottom-0 left-0 right-0 z-20 bg-background rounded-t-[28px] border-t border-border p-5">
        <div className="flex justify-center mb-3"><div className="w-10 h-1 rounded-full bg-border"/></div>
        <p className="text-[10px] text-muted-foreground font-mono uppercase tracking-wide mb-1">Manzilni tasdiqlash</p>
        <div className="flex items-start gap-2 mb-4 min-h-[40px]">
          <MapPin size={14} className="text-primary mt-0.5 flex-shrink-0"/>
          <p className="text-sm font-semibold text-foreground">{resolving ? "Manzil aniqlanmoqda…" : (address || "Xaritani suring")}</p>
        </div>
        <button onClick={()=>onConfirm({ lat: center.lat, lng: center.lng, address: address || `${center.lat.toFixed(6)}, ${center.lng.toFixed(6)}` })} disabled={resolving} className="w-full bg-primary text-white rounded-2xl py-3 text-sm font-semibold disabled:opacity-60">Manzilni tasdiqlash</button>
      </div>
    </div>
  );
}
