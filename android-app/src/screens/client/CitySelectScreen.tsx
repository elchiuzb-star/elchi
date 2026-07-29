import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { ChevronRight, MapPin, Search } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { useCities } from "@/data/cities";
import { BackHeader, EmptyState, Spinner } from "@/components/primitives";
import type { CityInfo } from "@/core/order";

export function CitySelectScreen({
  title,
  onBack,
  onSelect,
}: {
  title: string;
  onBack: () => void;
  onSelect: (c: CityInfo) => void;
}) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const { cities, loading } = useCities();
  const [q, setQ] = useState("");
  const filtered = cities.filter((c) =>
    [c.uz, c.ru, c.en].some((n) => n.toLowerCase().includes(q.toLowerCase())),
  );
  const name = (c: CityInfo) => (lang === "ru" ? c.ru : c.uz);

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={title} />
      <View className="p-4 pb-2">
        <View className="flex-row items-center rounded-xl border border-border bg-input px-3 py-2.5" style={{ gap: 8 }}>
          <Search size={14} color={colors.mutedForeground} />
          <TextInput
            autoFocus
            placeholder={t("searchCity")}
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
        <EmptyState icon={Search} title={t("noResults")} />
      ) : (
        <ScrollView keyboardShouldPersistTaps="handled">
          {filtered.map((c) => (
            <Pressable
              key={c.id}
              onPress={() => onSelect(c)}
              className="flex-row items-center border-b border-border px-4 py-3.5 active:bg-secondary"
              style={{ gap: 12 }}
            >
              <MapPin size={14} color={colors.primary} />
              <View className="flex-1">
                <Text className="text-sm font-medium text-foreground">{name(c)}</Text>
                {c.dist ? <Text className="text-[10px] text-muted-foreground">Tumanlar mavjud</Text> : null}
              </View>
              {c.dist ? <ChevronRight size={14} color={colors.mutedForeground} /> : null}
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}
