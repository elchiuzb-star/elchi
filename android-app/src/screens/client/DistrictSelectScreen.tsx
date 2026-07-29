import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { ChevronRight, Search } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { useDistricts } from "@/data/cities";
import { BackHeader, EmptyState, Spinner } from "@/components/primitives";
import { asCoord, type CityInfo } from "@/core/order";

export type PickedDistrict = { id: number; name: string; lat: number | null; lng: number | null };

export function DistrictSelectScreen({
  city,
  onBack,
  onSelect,
}: {
  city: CityInfo;
  onBack: () => void;
  onSelect: (d: PickedDistrict) => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const { districts, loading } = useDistricts(city.id);
  const [q, setQ] = useState("");
  const filtered = districts.filter((d) => d.name_uz.toLowerCase().includes(q.toLowerCase()));

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("chooseDistrict")} />
      <View className="p-4 pb-2">
        <View className="flex-row items-center rounded-xl border border-border bg-input px-3 py-2.5" style={{ gap: 8 }}>
          <Search size={14} color={colors.mutedForeground} />
          <TextInput
            autoFocus
            placeholder={t("searchDistrict")}
            placeholderTextColor={colors.mutedForeground}
            value={q}
            onChangeText={setQ}
            className="flex-1 text-sm text-foreground"
          />
        </View>
      </View>
      {loading ? (
        <Spinner />
      ) : filtered.length === 0 ? (
        <EmptyState icon={Search} title={t("noDistricts")} />
      ) : (
        <ScrollView keyboardShouldPersistTaps="handled">
          {filtered.map((d) => (
            <Pressable
              key={d.id}
              onPress={() =>
                onSelect({ id: d.id, name: d.name_uz, lat: asCoord(d.center_lat), lng: asCoord(d.center_lng) })
              }
              className="flex-row items-center border-b border-border px-4 py-3.5 active:bg-secondary"
              style={{ gap: 12 }}
            >
              <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: colors.primary }} />
              <Text className="flex-1 text-sm font-medium text-foreground">{d.name_uz}</Text>
              <ChevronRight size={14} color={colors.mutedForeground} />
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}
