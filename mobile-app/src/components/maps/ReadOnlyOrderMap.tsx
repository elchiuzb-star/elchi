import { MapMarker, YandexMap } from "./YandexMap";
import { TASHKENT, readPoint } from "./yandex";
import { translate } from "../../i18n";

type ReadOnlyOrderMapProps = {
  pickupLat?: number | string | null;
  pickupLng?: number | string | null;
  dropoffLat?: number | string | null;
  dropoffLng?: number | string | null;
};

/** The two ends of an order, shown on a detail screen. Not interactive: it is a picture of what was agreed. */
export function ReadOnlyOrderMap({ pickupLat, pickupLng, dropoffLat, dropoffLng }: ReadOnlyOrderMapProps) {
  const pickup = readPoint(pickupLat, pickupLng);
  const dropoff = readPoint(dropoffLat, dropoffLng);
  if (!pickup && !dropoff) return null;

  return (
    <div className="h-[180px] overflow-hidden rounded-[14px] border border-border">
      <YandexMap
        center={pickup ?? dropoff ?? TASHKENT}
        zoom={12}
        interactive={false}
        style={{ width: "100%", height: "100%" }}
        fallback={(status) => (
          <div className="flex h-full items-center justify-center px-4 text-center text-[13px] text-muted-foreground">
            {status === "missing-key"
              ? translate("maps.keyMissing")
              : status === "loading"
                ? translate("maps.loading")
                : translate("maps.loadFailed")}
          </div>
        )}
      >
        {pickup && <MapMarker point={pickup} label="A" title={translate("maps.pickupPlace")} />}
        {dropoff && <MapMarker point={dropoff} label="B" title={translate("maps.dropoffPlace")} />}
      </YandexMap>
    </div>
  );
}
