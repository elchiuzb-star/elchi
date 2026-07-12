import { GoogleMap, useJsApiLoader } from "@react-google-maps/api";

import { AdvancedMapMarker } from "./AdvancedMapMarker";
import { googleMapsLibraries, googleMapsMapId } from "./googleMapsConfig";

type ReadOnlyOrderMapProps = {
  pickupLat?: number | string | null;
  pickupLng?: number | string | null;
  dropoffLat?: number | string | null;
  dropoffLng?: number | string | null;
};

const defaultCenter = { lat: 41.2995, lng: 69.2401 };
function toPoint(lat?: number | string | null, lng?: number | string | null) {
  if (lat === null || lat === undefined || lng === null || lng === undefined) return null;
  const parsedLat = Number(lat);
  const parsedLng = Number(lng);
  if (!Number.isFinite(parsedLat) || !Number.isFinite(parsedLng)) return null;
  return { lat: parsedLat, lng: parsedLng };
}

export function ReadOnlyOrderMap({ pickupLat, pickupLng, dropoffLat, dropoffLng }: ReadOnlyOrderMapProps) {
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
  const pickup = toPoint(pickupLat, pickupLng);
  const dropoff = toPoint(dropoffLat, dropoffLng);
  const { isLoaded, loadError } = useJsApiLoader({
    id: "elchi-google-maps",
    googleMapsApiKey: apiKey ?? "",
    libraries: googleMapsLibraries,
  });

  if (!pickup && !dropoff) return null;
  if (!apiKey) {
    return <p className="text-[13px] text-[#6B7280]">Google Maps API kaliti topilmadi</p>;
  }
  if (loadError) {
    return <p className="text-[13px] text-[#DC2626]">Xarita yuklanmadi</p>;
  }
  if (!isLoaded) {
    return <p className="text-[13px] text-[#6B7280]">Xarita yuklanmoqda...</p>;
  }

  return (
    <div className="h-[180px] overflow-hidden rounded-[14px] border border-[#E5E7EB]">
      <GoogleMap
        mapContainerStyle={{ width: "100%", height: "100%" }}
        center={pickup ?? dropoff ?? defaultCenter}
        zoom={12}
        options={{
          clickableIcons: false,
          fullscreenControl: false,
          mapTypeControl: false,
          mapId: googleMapsMapId,
          streetViewControl: false,
        }}
      >
        {pickup && <AdvancedMapMarker position={pickup} label="A" title="Olib ketish joyi" />}
        {dropoff && <AdvancedMapMarker position={dropoff} label="B" title="Yetkazish joyi" />}
      </GoogleMap>
    </div>
  );
}
