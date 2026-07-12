import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GoogleMap, StandaloneSearchBox, useJsApiLoader } from "@react-google-maps/api";
import { ArrowLeft, Search } from "lucide-react";

import { AdvancedMapMarker } from "./AdvancedMapMarker";
import { googleMapsLibraries, googleMapsMapId } from "./googleMapsConfig";
import { validateGeoLocation } from "../../api/geo.api";
import type { City, District } from "../../types/city";

type SelectedLocation = {
  lat: number | null;
  lng: number | null;
  address: string;
};

export type GoogleMapPickerProps = {
  mode: "pickup" | "dropoff";
  city: City;
  district?: District | null;
  initialLat?: number | null;
  initialLng?: number | null;
  initialAddress?: string;
  onConfirm: (location: SelectedLocation) => void;
  onBack: () => void;
};

const defaultCenter = { lat: 41.2995, lng: 69.2401 };

function fallbackAddress(lat: number, lng: number): string {
  return `Tanlangan nuqta: ${lat.toFixed(7)}, ${lng.toFixed(7)}`;
}

function readCoordinate(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function GoogleMapPicker({
  mode,
  city,
  district,
  initialLat,
  initialLng,
  initialAddress,
  onConfirm,
  onBack,
}: GoogleMapPickerProps) {
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
  const title = mode === "pickup" ? "Olib ketish joyini belgilang" : "Yetkazish joyini belgilang";
  const districtCenterLat = readCoordinate(district?.center_lat);
  const districtCenterLng = readCoordinate(district?.center_lng);
  const initialSelectedLat = initialLat ?? districtCenterLat;
  const initialSelectedLng = initialLng ?? districtCenterLng;
  const defaultDistrictAddress = [district?.name_uz, city.name_uz, city.region].filter(Boolean).join(", ");
  const [query, setQuery] = useState(initialAddress ?? defaultDistrictAddress);
  const [manualAddress, setManualAddress] = useState(initialAddress ?? "");
  const [locationWarning, setLocationWarning] = useState(
    district && (districtCenterLat === null || districtCenterLng === null)
      ? "Bu tuman uchun default koordinata topilmadi"
      : "",
  );
  const [isValidatingLocation, setIsValidatingLocation] = useState(false);
  const [selected, setSelected] = useState<SelectedLocation | null>(() => {
    if (initialSelectedLat === null || initialSelectedLat === undefined || initialSelectedLng === null || initialSelectedLng === undefined) return null;
    return {
      lat: Number(initialSelectedLat),
      lng: Number(initialSelectedLng),
      address: initialAddress || defaultDistrictAddress || fallbackAddress(Number(initialSelectedLat), Number(initialSelectedLng)),
    };
  });
  const [mapCenter, setMapCenter] = useState(() => {
    if (initialSelectedLat === null || initialSelectedLat === undefined || initialSelectedLng === null || initialSelectedLng === undefined) {
      return defaultCenter;
    }
    return { lat: Number(initialSelectedLat), lng: Number(initialSelectedLng) };
  });
  const searchBoxRef = useRef<google.maps.places.SearchBox | null>(null);
  const geocoderRef = useRef<google.maps.Geocoder | null>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const geocodedDistrictKeyRef = useRef<string | null>(null);

  const center = useMemo(() => {
    if (selected && selected.lat !== null && selected.lng !== null) return { lat: selected.lat, lng: selected.lng };
    return mapCenter;
  }, [mapCenter, selected]);

  const { isLoaded, loadError } = useJsApiLoader({
    id: "elchi-google-maps",
    googleMapsApiKey: apiKey ?? "",
    libraries: googleMapsLibraries,
  });

  const reverseGeocode = useCallback((lat: number, lng: number) => {
    if (!window.google) {
      setSelected({ lat, lng, address: fallbackAddress(lat, lng) });
      return;
    }
    if (!geocoderRef.current) geocoderRef.current = new window.google.maps.Geocoder();
    geocoderRef.current.geocode({ location: { lat, lng } }, (results, status) => {
      const address = status === "OK" && results?.[0]?.formatted_address
        ? results[0].formatted_address
        : fallbackAddress(lat, lng);
      setSelected({ lat, lng, address });
      setMapCenter({ lat, lng });
      setQuery(address);
    });
  }, []);

  useEffect(() => {
    if (!selected || selected.lat === null || selected.lng === null || !district?.id) {
      if (!district?.id) setLocationWarning("");
      return;
    }
    let isActive = true;
    setIsValidatingLocation(true);
    validateGeoLocation({
      lat: selected.lat,
      lng: selected.lng,
      region_id: city.id,
      district_id: district.id,
    })
      .then((result) => {
        if (!isActive) return;
        setLocationWarning(result.valid ? "" : result.message || "Marker tanlangan viloyat/tumanga mos emas");
      })
      .catch(() => {
        if (!isActive) return;
        setLocationWarning("Marker tanlangan viloyat/tumanga mos emas");
      })
      .finally(() => {
        if (isActive) setIsValidatingLocation(false);
      });
    return () => {
      isActive = false;
    };
  }, [city.id, district?.id, selected?.lat, selected?.lng]);

  useEffect(() => {
    if (!isLoaded) return;
    if (!window.google) return;
    if (!geocoderRef.current) geocoderRef.current = new window.google.maps.Geocoder();

    const searchAddress = [district?.name_uz, city.name_uz, city.region, "Uzbekistan"].filter(Boolean).join(", ");
    if (!searchAddress.trim()) return;
    const hasInitialPoint = initialLat !== null && initialLat !== undefined && initialLng !== null && initialLng !== undefined;
    const shouldFocusDistrict = Boolean(district?.id) && (!hasInitialPoint || !initialAddress || initialAddress === defaultDistrictAddress);
    if (selected && !shouldFocusDistrict) return;

    const geocodeKey = `${city.id}:${district?.id ?? "city"}:${searchAddress}`;
    if (geocodedDistrictKeyRef.current === geocodeKey) return;
    geocodedDistrictKeyRef.current = geocodeKey;

    geocoderRef.current.geocode({ address: searchAddress, region: "UZ" }, (results, status) => {
      const location = status === "OK" ? results?.[0]?.geometry?.location : undefined;
      if (!location) return;
      const nextCenter = { lat: location.lat(), lng: location.lng() };
      const address = results?.[0]?.formatted_address || defaultDistrictAddress || fallbackAddress(nextCenter.lat, nextCenter.lng);
      setMapCenter(nextCenter);
      if (shouldFocusDistrict) {
        setSelected({ lat: nextCenter.lat, lng: nextCenter.lng, address });
        setQuery(address);
      }
      mapRef.current?.panTo(nextCenter);
    });
  }, [city.id, city.name_uz, city.region, defaultDistrictAddress, district?.id, district?.name_uz, initialAddress, initialLat, initialLng, isLoaded, selected]);

  const onPlacesChanged = () => {
    const place = searchBoxRef.current?.getPlaces()?.[0];
    const location = place?.geometry?.location;
    if (!location) return;
    const lat = location.lat();
    const lng = location.lng();
    const address = place.formatted_address || place.name || fallbackAddress(lat, lng);
    setSelected({ lat, lng, address });
    setMapCenter({ lat, lng });
    setQuery(address);
  };

  if (!apiKey) {
    return (
      <div className="absolute inset-0 z-50 flex flex-col bg-white">
        <div className="flex h-14 items-center gap-3 border-b border-[#E5E7EB] px-5">
          <button onClick={onBack} className="flex h-9 w-9 items-center justify-center rounded-full bg-[#F3F4F6]">
            <ArrowLeft size={18} />
          </button>
          <h2 className="text-[17px] font-semibold text-[#111827]">{title}</h2>
        </div>
        <div className="flex flex-1 flex-col justify-center px-6 text-center">
          <p className="text-[18px] font-semibold text-[#111827]">Google Maps API kaliti topilmadi</p>
          <p className="mt-2 text-[14px] leading-6 text-[#6B7280]">Manzilni qo'lda kiriting</p>
          <input
            value={manualAddress}
            onChange={(event) => setManualAddress(event.target.value)}
            placeholder="Manzil"
            className="mt-5 h-[52px] rounded-[12px] border border-[#E5E7EB] px-4 text-[15px] outline-none"
          />
          <div className="mt-4 grid grid-cols-2 gap-3">
            <button onClick={onBack} className="h-[52px] rounded-[14px] bg-[#F3F4F6] text-[15px] font-semibold text-[#6B7280]">
              Bekor qilish
            </button>
            <button
              onClick={() => manualAddress.trim() && onConfirm({ lat: null, lng: null, address: manualAddress.trim() })}
              disabled={!manualAddress.trim()}
              className="h-[52px] rounded-[14px] bg-[#1B4FD8] text-[15px] font-semibold text-white disabled:bg-[#9CA3AF]"
            >
              Tasdiqlash
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="absolute inset-0 z-50 flex flex-col bg-white">
        <div className="flex h-14 items-center gap-3 border-b border-[#E5E7EB] px-5">
          <button onClick={onBack} className="flex h-9 w-9 items-center justify-center rounded-full bg-[#F3F4F6]">
            <ArrowLeft size={18} />
          </button>
          <h2 className="text-[17px] font-semibold text-[#111827]">{title}</h2>
        </div>
        <div className="flex flex-1 flex-col justify-center px-6 text-center">
          <p className="text-[18px] font-semibold text-[#111827]">Xarita yuklanmadi</p>
          <p className="mt-2 text-[14px] leading-6 text-[#6B7280]">Manzilni qo'lda kiriting</p>
          <input
            value={manualAddress}
            onChange={(event) => setManualAddress(event.target.value)}
            placeholder="Manzil"
            className="mt-5 h-[52px] rounded-[12px] border border-[#E5E7EB] px-4 text-[15px] outline-none"
          />
          <div className="mt-4 grid grid-cols-2 gap-3">
            <button onClick={onBack} className="h-[52px] rounded-[14px] bg-[#F3F4F6] text-[15px] font-semibold text-[#6B7280]">
              Bekor qilish
            </button>
            <button
              onClick={() => manualAddress.trim() && onConfirm({ lat: null, lng: null, address: manualAddress.trim() })}
              disabled={!manualAddress.trim()}
              className="h-[52px] rounded-[14px] bg-[#1B4FD8] text-[15px] font-semibold text-white disabled:bg-[#9CA3AF]"
            >
              Tasdiqlash
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-50 flex flex-col bg-[#F7F8FA]">
      <div className="absolute left-4 right-4 top-4 z-10 space-y-3">
        <div className="flex items-center gap-2">
          <button onClick={onBack} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white shadow-lg">
            <ArrowLeft size={18} />
          </button>
          <div className="flex h-11 flex-1 items-center rounded-[14px] bg-white px-4 shadow-lg">
            <p className="truncate text-[15px] font-semibold text-[#111827]">{title}</p>
          </div>
        </div>
        {isLoaded ? (
          <StandaloneSearchBox onLoad={(box) => { searchBoxRef.current = box; }} onPlacesChanged={onPlacesChanged}>
            <label className="flex h-12 items-center gap-3 rounded-[16px] border-2 border-[#38BDF8] bg-white px-4 shadow-lg">
              <Search size={19} color="#6B7280" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Manzil qidirish"
                className="min-w-0 flex-1 bg-transparent text-[15px] text-[#111827] outline-none"
              />
            </label>
          </StandaloneSearchBox>
        ) : (
          <div className="flex h-12 items-center rounded-[16px] bg-white px-4 text-[14px] text-[#6B7280] shadow-lg">
            Xarita yuklanmoqda...
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1">
        {isLoaded && (
          <GoogleMap
            mapContainerStyle={{ width: "100%", height: "100%" }}
            center={center}
            zoom={selected ? 16 : 13}
            onLoad={(map) => {
              mapRef.current = map;
            }}
            onUnmount={() => {
              mapRef.current = null;
            }}
            options={{
              clickableIcons: false,
              fullscreenControl: false,
              mapId: googleMapsMapId,
              mapTypeControl: false,
              streetViewControl: false,
              zoomControl: true,
            }}
            onClick={(event) => {
              const lat = event.latLng?.lat();
              const lng = event.latLng?.lng();
              if (lat === undefined || lng === undefined) return;
              reverseGeocode(lat, lng);
            }}
          >
            {selected && selected.lat !== null && selected.lng !== null && (
              <AdvancedMapMarker
                position={{ lat: selected.lat, lng: selected.lng }}
                draggable
                title="Tanlangan manzil"
                onDragEnd={(position) => reverseGeocode(position.lat, position.lng)}
              />
            )}
          </GoogleMap>
        )}
      </div>
      <div className="rounded-t-[24px] bg-white p-5 shadow-[0_-8px_30px_rgba(15,23,42,0.18)]">
        <p className="text-[12px] font-bold uppercase tracking-wide text-[#9CA3AF]">Tanlangan manzil</p>
        <p className="mt-2 min-h-[44px] text-[15px] leading-6 text-[#111827]">
          {selected?.address ?? "Nuqtani tanlang"}
        </p>
        <p className="mt-1 text-[12px] text-[#6B7280]">
          {selected
            ? selected.lat !== null && selected.lng !== null
              ? `Manzil avtomatik aniqlandi: ${selected.lat.toFixed(6)}, ${selected.lng.toFixed(6)}`
              : "Manzil qo'lda kiritildi"
            : "Nuqtani tanlaganingizdan keyin tizim manzilni o'zi yozadi."}
        </p>
        {isValidatingLocation && <p className="mt-2 text-[12px] text-[#6B7280]">Marker tekshirilmoqda...</p>}
        {locationWarning && <p className="mt-2 text-[12px] font-semibold text-[#DC2626]">{locationWarning}</p>}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <button onClick={onBack} className="h-[52px] rounded-[14px] bg-[#F3F4F6] text-[15px] font-semibold text-[#6B7280]">
            Bekor qilish
          </button>
          <button
            onClick={() => selected && onConfirm(selected)}
            disabled={!selected || Boolean(locationWarning) || isValidatingLocation}
            className="h-[52px] rounded-[14px] bg-[#1B4FD8] text-[15px] font-semibold text-white disabled:bg-[#9CA3AF]"
          >
            Tasdiqlash
          </button>
        </div>
      </div>
    </div>
  );
}
