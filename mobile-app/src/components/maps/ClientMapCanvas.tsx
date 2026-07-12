import { GoogleMap, useJsApiLoader } from "@react-google-maps/api";

import { AdvancedMapMarker } from "./AdvancedMapMarker";
import { googleMapsLibraries, googleMapsMapId } from "./googleMapsConfig";

type ClientMapCanvasProps = {
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

export function ClientMapCanvas({ pickupLat, pickupLng, dropoffLat, dropoffLng }: ClientMapCanvasProps) {
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
  const pickup = toPoint(pickupLat, pickupLng);
  const dropoff = toPoint(dropoffLat, dropoffLng);
  const center = pickup ?? dropoff ?? defaultCenter;
  const { isLoaded, loadError } = useJsApiLoader({
    id: "elchi-google-maps",
    googleMapsApiKey: apiKey ?? "",
    libraries: googleMapsLibraries,
  });

  if (!apiKey || loadError) {
    return (
      <div className="absolute inset-0 bg-[#E5E7EB]">
        <div className="absolute inset-0 bg-[linear-gradient(135deg,#E0F2FE_0%,#F8FAFC_45%,#DBEAFE_100%)]" />
        <div className="absolute left-5 right-5 top-24 rounded-[18px] bg-white/90 p-4 shadow-lg">
          <p className="text-[15px] font-semibold text-[#111827]">
            {!apiKey ? "Google Maps API kaliti topilmadi" : "Xarita yuklanmadi"}
          </p>
          <p className="mt-1 text-[13px] leading-5 text-[#6B7280]">
            Shahar va manzilni qo'lda kiritib ham buyurtma yaratish mumkin.
          </p>
        </div>
      </div>
    );
  }

  if (!isLoaded) {
    return <div className="absolute inset-0 bg-[#EFF6FF]" />;
  }

  return (
    <GoogleMap
      mapContainerStyle={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      center={center}
      zoom={pickup || dropoff ? 14 : 13}
      options={{
        clickableIcons: false,
        fullscreenControl: false,
        mapTypeControl: false,
        mapId: googleMapsMapId,
        streetViewControl: false,
        zoomControl: false,
      }}
    >
      {pickup && <AdvancedMapMarker position={pickup} label="A" title="Olib ketish joyi" />}
      {dropoff && <AdvancedMapMarker position={dropoff} label="B" title="Yetkazish joyi" />}
    </GoogleMap>
  );
}
