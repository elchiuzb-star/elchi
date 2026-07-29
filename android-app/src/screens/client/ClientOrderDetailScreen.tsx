import { useState, type ReactNode } from "react";
import { Linking, Pressable, ScrollView, Text, View } from "react-native";
import { Ban, CheckCheck, Eye, Flag, Phone, Star, Truck } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getClientOrder, cancelClientOrder } from "@/api/client-orders.api";
import { useAsync } from "@/data/useApi";
import { usePullRefresh } from "@/data/usePullRefresh";
import { cityName as cityNameOf, toNumber as toNum } from "@/data/format";
import { BackHeader, JourneySpine, SectionLabel, Spinner, StatusBadge } from "@/components/primitives";
import { MapPanel } from "@/components/maps/MapPanel";
import { cargoTypeLabel, fmt } from "@/core/order";

export function ClientOrderDetailScreen({
  orderId,
  onBack,
  onViewBids,
  onConfirmDelivery,
  onRate,
  onDispute,
  onCancelled,
}: {
  orderId: number;
  onBack: () => void;
  onViewBids: () => void;
  onConfirmDelivery: () => void;
  onRate: () => void;
  onDispute: () => void;
  onCancelled: () => void;
}) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const { data: o, loading, reload } = useAsync<any>(() => getClientOrder(orderId), [orderId]);
  const refresh = usePullRefresh(reload);
  const [cancelling, setCancelling] = useState(false);

  if (loading || !o) {
    return (
      <View className="flex-1">
        <BackHeader onBack={onBack} title={`#${orderId}`} />
        <Spinner />
      </View>
    );
  }

  const fromCity = cityNameOf(o.from_city, lang);
  const toCity = cityNameOf(o.to_city, lang);
  const price = toNum(o.final_price ?? o.client_price ?? o.suggested_price);
  const driver = o.assigned_driver;
  const sf = [
    { key: "published", label: t("statusPublished") },
    { key: "bidding", label: t("statusBidding") },
    { key: "accepted", label: t("statusAccepted") },
    { key: "in_transit", label: t("statusInTransit") },
    { key: "delivered", label: t("statusDelivered") },
  ];
  const ci = sf.findIndex((s) => s.key === o.status);
  const parcelTypeLabel = lang === "ru" ? "Тип отправления" : lang === "en" ? "Parcel type" : "Jo'natma turi";

  async function cancel() {
    setCancelling(true);
    try {
      await cancelClientOrder(orderId, "Mijoz tomonidan bekor qilindi");
      onCancelled();
    } catch {
      setCancelling(false);
    }
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={o.order_number || `#${o.id}`} right={<StatusBadge status={o.status} />} />
      <ScrollView contentContainerClassName="p-4 gap-4" refreshControl={refresh}>
        {/* Route + price */}
        <View className="rounded-2xl border border-border bg-card p-4 flex-row" style={{ gap: 12 }}>
          <View className="items-center pt-1">
            <View style={{ width: 14, height: 14, borderRadius: 7, borderWidth: 3, borderColor: colors.feruza, backgroundColor: colors.card }} />
            <View style={{ width: 2, minHeight: 34, flex: 1, marginVertical: 4, backgroundColor: colors.primary, opacity: 0.55 }} />
            <View style={{ width: 16, height: 16, backgroundColor: colors.primary, borderRadius: 8, borderBottomLeftRadius: 3, transform: [{ rotate: "45deg" }] }} />
          </View>
          <View className="flex-1">
            <Text className="text-[15px] font-bold text-foreground">{fromCity}</Text>
            <Text className="mb-4 text-xs text-muted-foreground" numberOfLines={1}>{o.pickup_address || ""}</Text>
            <Text className="text-[15px] font-bold text-foreground">{toCity}</Text>
            <Text className="text-xs text-muted-foreground" numberOfLines={1}>{o.dropoff_address || ""}</Text>
          </View>
          <Text className="text-base font-bold text-foreground">{price > 0 ? fmt(price) : "—"}</Text>
        </View>

        {toNum(o.pickup_lat) !== 0 || toNum(o.dropoff_lat) !== 0 ? (
          <MapPanel pickupLat={o.pickup_lat} pickupLng={o.pickup_lng} dropoffLat={o.dropoff_lat} dropoffLng={o.dropoff_lng} />
        ) : null}

        {o.cargo_type ? (
          <View className="flex-row items-center justify-between rounded-2xl border border-border bg-card p-4">
            <Text className="text-xs text-muted-foreground">{parcelTypeLabel}</Text>
            <Text className="text-sm font-medium text-foreground">{cargoTypeLabel(o.cargo_type, lang)}</Text>
          </View>
        ) : null}

        {!["confirmed", "cancelled"].includes(o.status) ? (
          <View className="rounded-2xl border border-border bg-card p-4">
            <SectionLabel>{t("statusTimeline")}</SectionLabel>
            <JourneySpine steps={sf} current={ci} />
          </View>
        ) : null}

        {driver ? (
          <View className="rounded-2xl border p-4" style={{ borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}0D` }}>
            <Text className="mb-3 text-[10px] uppercase tracking-wide text-muted-foreground">{t("assignedDriver")}</Text>
            <View className="flex-row items-center" style={{ gap: 12 }}>
              <View className="items-center justify-center rounded-2xl" style={{ width: 48, height: 48, backgroundColor: `${colors.primary}26` }}>
                <Truck size={20} color={colors.primary} />
              </View>
              <View className="flex-1">
                <Text className="text-sm font-bold text-foreground">{driver.full_name || "—"}</Text>
                <Text className="text-xs text-muted-foreground">
                  {driver.car_model || ""}
                  {driver.plate_number ? ` · ${driver.plate_number}` : ""}
                </Text>
                <View className="mt-0.5 flex-row items-center" style={{ gap: 4 }}>
                  <Star size={11} color={colors.primary} fill={colors.primary} />
                  <Text className="text-xs text-foreground">{toNum(driver.rating).toFixed(1)}</Text>
                </View>
              </View>
              {driver.phone ? (
                <Pressable
                  onPress={() => Linking.openURL(`tel:${driver.phone}`)}
                  className="items-center justify-center rounded-xl active:opacity-80"
                  style={{ width: 40, height: 40, backgroundColor: `${colors.primary}26` }}
                >
                  <Phone size={16} color={colors.primary} />
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}

        {["published", "bidding"].includes(o.status) ? (
          <View className="rounded-2xl border border-border bg-card p-4">
            <View className="mb-2 flex-row items-center justify-between">
              <Text className="text-sm font-semibold text-foreground">{t("bidsSection")}</Text>
              {o.bids_count > 0 ? (
                <View className="rounded-lg border px-2 py-0.5" style={{ borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}1A` }}>
                  <Text className="text-xs" style={{ color: colors.primary }}>{o.bids_count}</Text>
                </View>
              ) : null}
            </View>
            {!o.bids_count ? (
              <Text className="text-xs text-muted-foreground">{t("waitingBids")}</Text>
            ) : (
              <Pressable
                onPress={onViewBids}
                className="w-full flex-row items-center justify-center rounded-xl border py-2.5 active:opacity-80"
                style={{ gap: 8, borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}1A` }}
              >
                <Eye size={14} color={colors.primary} />
                <Text className="text-sm font-medium" style={{ color: colors.primary }}>{t("viewBids")}</Text>
              </Pressable>
            )}
          </View>
        ) : null}

        <View style={{ gap: 8 }}>
          {o.status === "delivered" ? (
            <ActionButton label={t("confirmDelivery")} icon={<CheckCheck size={16} color="#fff" />} bg={colors.success} onPress={onConfirmDelivery} />
          ) : null}
          {o.status === "confirmed" ? (
            <ActionButton label={t("rateDriverTitle")} icon={<Star size={16} color={colors.primaryForeground} fill={colors.primaryForeground} />} bg={colors.primary} onPress={onRate} />
          ) : null}
          {!["confirmed", "cancelled"].includes(o.status) ? (
            <OutlineButton label={t("openDisputeBtn")} icon={<Flag size={14} color={colors.mutedForeground} />} color={colors.mutedForeground} borderColor={colors.border} onPress={onDispute} />
          ) : null}
          {["published", "bidding", "accepted"].includes(o.status) ? (
            <OutlineButton
              label={t("cancelOrderBtn")}
              icon={<Ban size={14} color={colors.destructive} />}
              color={colors.destructive}
              borderColor={`${colors.destructive}4D`}
              onPress={cancel}
              disabled={cancelling}
            />
          ) : null}
        </View>
      </ScrollView>
    </View>
  );
}

function ActionButton({ label, icon, bg, onPress }: { label: string; icon: ReactNode; bg: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} className="w-full flex-row items-center justify-center rounded-2xl py-3 active:opacity-90" style={{ gap: 8, backgroundColor: bg }}>
      {icon}
      <Text className="text-sm font-semibold text-white">{label}</Text>
    </Pressable>
  );
}

function OutlineButton({
  label,
  icon,
  color,
  borderColor,
  onPress,
  disabled = false,
}: {
  label: string;
  icon: ReactNode;
  color: string;
  borderColor: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      className="w-full flex-row items-center justify-center rounded-2xl border py-3 active:opacity-80"
      style={{ gap: 8, borderColor, opacity: disabled ? 0.6 : 1 }}
    >
      {icon}
      <Text className="text-sm font-medium" style={{ color }}>{label}</Text>
    </Pressable>
  );
}
