import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { ArrowRight, Package } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { listClientOrders } from "@/api/client-orders.api";
import { useAsync } from "@/data/useApi";
import { usePullRefresh } from "@/data/usePullRefresh";
import { toNumber as toNum, shortDate as fmtDate } from "@/data/format";
import { EmptyState, Spinner, StatusBadge } from "@/components/primitives";
import { fmt } from "@/core/order";

type Tab = "all" | "active" | "completed" | "cancelled";

export function ClientOrdersScreen({
  onOrderDetail,
  onCreateOrder,
}: {
  onOrderDetail: (id: number) => void;
  onCreateOrder: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>("all");
  const { data, loading, reload } = useAsync<any>(() => listClientOrders({ limit: 50 }), []);
  const refresh = usePullRefresh(reload);
  const orders: any[] = data?.items ?? [];
  const filtered = orders.filter((o) => {
    if (tab === "all") return true;
    if (tab === "active") return ["published", "bidding", "accepted", "picked_up", "in_transit"].includes(o.status);
    if (tab === "completed") return ["delivered", "confirmed"].includes(o.status);
    return o.status === "cancelled";
  });
  const tabs: { id: Tab; label: string }[] = [
    { id: "all", label: t("allOrders") },
    { id: "active", label: t("activeOrders") },
    { id: "completed", label: t("completedOrders") },
    { id: "cancelled", label: t("cancelledOrders") },
  ];

  return (
    <View className="flex-1">
      <View className="p-4 pb-2 pt-5">
        <Text className="mb-3 pl-14 text-[22px] font-extrabold text-foreground">{t("myOrders")}</Text>
        <View className="flex-row rounded-xl bg-secondary p-1" style={{ gap: 4 }}>
          {tabs.map((tp) => {
            const active = tab === tp.id;
            return (
              <Pressable
                key={tp.id}
                onPress={() => setTab(tp.id)}
                className="flex-1 items-center rounded-lg py-1.5"
                style={{ backgroundColor: active ? colors.card : "transparent" }}
              >
                <Text
                  className="text-[11px] font-medium"
                  style={{ color: active ? colors.foreground : colors.mutedForeground }}
                  numberOfLines={1}
                >
                  {tp.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {loading ? (
        <Spinner />
      ) : filtered.length === 0 ? (
        <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: "center" }} refreshControl={refresh}>
          <EmptyState
            icon={Package}
            title={t("noOrdersYet")}
            desc={t("noOrdersDesc")}
            action={
              <Pressable onPress={onCreateOrder} className="rounded-xl bg-primary px-5 py-2.5 active:opacity-90">
                <Text className="text-sm font-medium text-primary-foreground">{t("createOrder")}</Text>
              </Pressable>
            }
          />
        </ScrollView>
      ) : (
        <ScrollView contentContainerClassName="p-4 gap-3" refreshControl={refresh}>
          {filtered.map((o) => {
            const price = toNum(o.final_price ?? o.client_price ?? o.suggested_price);
            const cancelled = o.status === "cancelled";
            return (
              <Pressable
                key={o.id}
                onPress={() => onOrderDetail(o.id)}
                className="rounded-2xl border bg-card p-4 active:opacity-90"
                style={{
                  borderColor: cancelled ? `${colors.destructive}47` : colors.border,
                  backgroundColor: cancelled ? `${colors.destructive}0D` : colors.card,
                }}
              >
                <View className="mb-2 flex-row items-center justify-between">
                  <Text className="text-xs text-muted-foreground">{o.order_number || `#${o.id}`}</Text>
                  <StatusBadge status={o.status} />
                </View>
                <View className="mb-1 flex-row items-center" style={{ gap: 8 }}>
                  <Text
                    className="text-[15px] font-bold"
                    style={{ color: cancelled ? colors.mutedForeground : colors.foreground, textDecorationLine: cancelled ? "line-through" : "none" }}
                  >
                    {o.from_city}
                  </Text>
                  <ArrowRight size={14} color={cancelled ? colors.destructive : colors.primary} />
                  <Text
                    className="text-[15px] font-bold"
                    style={{ color: cancelled ? colors.mutedForeground : colors.foreground, textDecorationLine: cancelled ? "line-through" : "none" }}
                  >
                    {o.to_city}
                  </Text>
                </View>
                <Text className="mb-3 text-xs text-muted-foreground">
                  {o.from_district?.name_uz || ""}
                  {o.to_district ? ` → ${o.to_district?.name_uz || ""}` : ""}
                </Text>
                <View
                  className="flex-row items-center justify-between border-t pt-3"
                  style={{ borderColor: cancelled ? `${colors.destructive}2E` : colors.border }}
                >
                  <Text className="text-sm font-bold" style={{ color: cancelled ? colors.mutedForeground : colors.foreground }}>
                    {price > 0 ? fmt(price) : "—"}
                  </Text>
                  <View className="flex-row items-center" style={{ gap: 8 }}>
                    {!cancelled && o.bids_count > 0 ? (
                      <View className="rounded-lg border px-2 py-0.5" style={{ borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}1A` }}>
                        <Text className="text-xs" style={{ color: colors.primary }}>
                          {o.bids_count} {t("bidsStat")}
                        </Text>
                      </View>
                    ) : null}
                    <Text className="text-xs text-muted-foreground">{fmtDate(o.created_at)}</Text>
                  </View>
                </View>
              </Pressable>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}
