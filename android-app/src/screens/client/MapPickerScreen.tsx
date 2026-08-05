import { useRef, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";
import { MapPin, Navigation, Search } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton } from "@/components/buttons";
import { YandexMap, type YandexMapHandle } from "@/components/maps/YandexMap";
import { geocodeAddress } from "@/api/geo.api";
import type { CityInfo } from "@/core/order";

export type PickedLocation = { address: string; lat: number | null; lng: number | null };

const DEFAULT = { latitude: 41.3111, longitude: 69.2797 };

/**
 * Drag the map under the fixed centre pin to place the pickup/dropoff point; the
 * map centre becomes the saved lat/lng. The address stays editable (reverse
 * geocoding needs a server key and is optional for the MVP).
 */
export function MapPickerScreen({
  city,
  district,
  centerLat,
  centerLng,
  onBack,
  onConfirm,
}: {
  city: CityInfo;
  district?: string;
  centerLat?: number | null;
  centerLng?: number | null;
  onBack: () => void;
  onConfirm: (loc: PickedLocation) => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const title = district ? `${district}, ${city.uz}` : city.uz;
  const start = {
    latitude: centerLat ?? DEFAULT.latitude,
    longitude: centerLng ?? DEFAULT.longitude,
  };
  const centerRef = useRef(start);
  const mapRef = useRef<YandexMapHandle>(null);
  const [address, setAddress] = useState(district ? `${district}, ${city.uz}` : city.uz);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  function onCenterChange(lat: number, lng: number) {
    centerRef.current = { latitude: lat, longitude: lng };
  }

  async function handleSearch() {
    const q = query.trim();
    if (q.length < 2) return;
    setSearching(true);
    setSearchError("");
    try {
      // Bias the query to the chosen area, otherwise a bare street name can
      // resolve to a same-named street in another city.
      const scoped = district ? `${city.uz}, ${district}, ${q}` : `${city.uz}, ${q}`;
      const res = await geocodeAddress(scoped);
      if (res?.lat == null || res?.lng == null) {
        setSearchError(t("mapSearchNotFound"));
        return;
      }
      // Move the map; the fixed pin means the new centre becomes the picked
      // point, and onCenterChange updates centerRef as the map settles.
      mapRef.current?.setCenter(res.lat, res.lng);
      centerRef.current = { latitude: res.lat, longitude: res.lng };
      setAddress(res.formatted_address || scoped);
    } catch {
      setSearchError(t("mapSearchNotFound"));
    } finally {
      setSearching(false);
    }
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={title} />

      {/* Search the chosen area instead of dragging across the whole map. */}
      <View className="px-4 pb-3">
        <View
          className="flex-row items-center rounded-xl border border-border bg-input px-4"
          style={{ gap: 10, height: 46 }}
        >
          <Search size={15} color={colors.mutedForeground} />
          <TextInput
            value={query}
            onChangeText={(v) => {
              setQuery(v);
              if (searchError) setSearchError("");
            }}
            onSubmitEditing={handleSearch}
            returnKeyType="search"
            placeholder={t("mapSearchPlaceholder")}
            placeholderTextColor={colors.mutedForeground}
            className="flex-1 text-sm text-foreground"
          />
          {searching ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : query.trim().length >= 2 ? (
            <Pressable onPress={handleSearch} hitSlop={8}>
              <Text style={{ fontSize: 12, fontWeight: "600", color: colors.primary }}>
                {t("mapSearchCta")}
              </Text>
            </Pressable>
          ) : null}
        </View>
        {searchError ? (
          <Text style={{ marginTop: 6, fontSize: 11, color: colors.destructive }}>
            {searchError}
          </Text>
        ) : null}
      </View>

      <View style={{ height: 260 }}>
        <YandexMap
          ref={mapRef}
          mode="picker"
          center={{ lat: start.latitude, lng: start.longitude }}
          onCenterChange={onCenterChange}
        />
        {/* Fixed centre pin (the map moves beneath it). */}
        <View pointerEvents="none" style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center" }}>
          <MapPin size={40} color={colors.primary} fill={colors.primary} />
          <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: colors.primary, marginTop: -4 }} />
        </View>
      </View>

      <View className="flex-1 p-4" style={{ gap: 12 }}>
        <Text className="text-xs font-medium text-muted-foreground">Manzil</Text>
        <View className="flex-row items-center rounded-xl border border-border bg-input px-4 py-3" style={{ gap: 12 }}>
          <Navigation size={14} color={colors.mutedForeground} />
          <TextInput
            value={address}
            onChangeText={setAddress}
            placeholder="Manzil"
            placeholderTextColor={colors.mutedForeground}
            className="flex-1 text-sm text-foreground"
            multiline
          />
        </View>
      </View>

      <View className="border-t border-border p-4">
        <PrimaryButton
          label={t("confirmLocation")}
          onPress={() =>
            onConfirm({
              address: address.trim(),
              lat: centerRef.current.latitude,
              lng: centerRef.current.longitude,
            })
          }
        />
      </View>
    </View>
  );
}
