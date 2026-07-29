import { Pressable, Text, View } from "react-native";
import { ArrowRight, Headphones } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { RouteThread } from "@/components/primitives";
import { MapPanel } from "@/components/maps/MapPanel";
import type { OrderDraft } from "@/core/order";

export function ClientHomeScreen({
  onSelectFrom,
  onSelectTo,
  draft,
  detectingFrom,
  onViewRoute,
  onSupport,
}: {
  onSelectFrom: () => void;
  onSelectTo: () => void;
  draft: OrderDraft;
  detectingFrom?: boolean;
  onViewRoute: () => void;
  onSupport: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();

  return (
    <View className="flex-1 bg-background">
      {/* Route preview map */}
      <MapPanel
        fill
        pickupLat={draft.pickup?.lat}
        pickupLng={draft.pickup?.lng}
        dropoffLat={draft.dropoff?.lat}
        dropoffLng={draft.dropoff?.lng}
      />

      {/* Bottom sheet */}
      <View
        className="rounded-t-[24px] border-t border-border bg-card"
        style={{ shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 20, shadowOffset: { width: 0, height: -8 }, elevation: 12 }}
      >
        <View className="absolute -top-14 right-4">
          <Pressable
            onPress={onSupport}
            accessibilityLabel={t("support")}
            className="h-11 w-11 items-center justify-center rounded-full border border-border bg-card active:opacity-80"
          >
            <Headphones size={19} color={colors.foreground} />
          </Pressable>
        </View>

        <View className="items-center pb-1 pt-3">
          <View style={{ width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border }} />
        </View>
        <View className="px-5 pb-6 pt-2">
          <Text className="mb-4 text-[20px] font-bold text-foreground">{t("sendParcel")}</Text>
          <RouteThread
            from={draft.pickup ? draft.pickup.district || draft.pickup.city.uz : null}
            to={draft.dropoff ? draft.dropoff.district || draft.dropoff.city.uz : null}
            fromLoading={detectingFrom}
            onFrom={onSelectFrom}
            onTo={onSelectTo}
          />
          <Pressable
            onPress={() => {
              if (!draft.pickup) onSelectFrom();
              else if (!draft.dropoff) onSelectTo();
              else onViewRoute();
            }}
            className="mt-5 w-full flex-row items-center justify-center rounded-2xl bg-primary py-3.5 active:opacity-90"
            style={{ gap: 8 }}
          >
            <Text className="text-[15px] font-semibold text-primary-foreground">{t("viewRoute")}</Text>
            <ArrowRight size={17} color={colors.primaryForeground} />
          </Pressable>
        </View>
      </View>
    </View>
  );
}
