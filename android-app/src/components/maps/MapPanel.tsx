import { View } from "react-native";
import { useTheme } from "@/theme/ThemeProvider";
import { YandexMap } from "./YandexMap";

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** Read-only Yandex map showing pickup (A) / dropoff (B) with a dashed route line. */
export function MapPanel({
  pickupLat,
  pickupLng,
  dropoffLat,
  dropoffLng,
  height = 176,
  fill = false,
}: {
  pickupLat?: unknown;
  pickupLng?: unknown;
  dropoffLat?: unknown;
  dropoffLng?: unknown;
  height?: number;
  /** Fill the parent (flex:1, no rounding) instead of a fixed rounded panel. */
  fill?: boolean;
}) {
  const { colors } = useTheme();

  const pickup = { lat: num(pickupLat), lng: num(pickupLng) };
  const dropoff = { lat: num(dropoffLat), lng: num(dropoffLng) };

  return (
    <View
      style={
        fill
          ? { flex: 1, overflow: "hidden", backgroundColor: colors.secondary }
          : { height, borderRadius: 14, overflow: "hidden", backgroundColor: colors.secondary }
      }
    >
      <YandexMap mode="route" pickup={pickup} dropoff={dropoff} />
    </View>
  );
}
