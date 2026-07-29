import { useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { Inbox, Star, Truck } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { listClientOrderBids, selectDriver } from "@/api/client-orders.api";
import { useAsync } from "@/data/useApi";
import { usePullRefresh } from "@/data/usePullRefresh";
import { toNumber as toNum } from "@/data/format";
import { BackHeader, EmptyState, Spinner } from "@/components/primitives";
import { PrimaryButton, SecondaryButton } from "@/components/buttons";
import { fmt, groupNum } from "@/core/order";

export function ClientBidsScreen({
  orderId,
  onBack,
  onSelectDriver,
}: {
  orderId: number;
  onBack: () => void;
  onSelectDriver: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const { data, loading, reload } = useAsync<any[]>(() => listClientOrderBids(orderId), [orderId]);
  const refresh = usePullRefresh(reload);
  const bids: any[] = data ?? [];
  const [sel, setSel] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirm() {
    if (!sel) return;
    setBusy(true);
    try {
      await selectDriver(orderId, sel.id);
      setSel(null);
      onSelectDriver();
    } catch {
      setBusy(false);
    }
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("driverOffers")} />
      {loading ? (
        <Spinner />
      ) : bids.length === 0 ? (
        <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: "center" }} refreshControl={refresh}>
          <EmptyState icon={Inbox} title={t("noBids")} desc={t("waitingBids")} />
        </ScrollView>
      ) : (
        <ScrollView contentContainerClassName="p-4 gap-3" refreshControl={refresh}>
          {bids.map((b, i) => {
            const top = i === 0;
            return (
              <View
                key={b.id}
                className="rounded-2xl border bg-card p-4"
                style={{ borderColor: top ? `${colors.primary}4D` : colors.border, backgroundColor: top ? `${colors.primary}0D` : colors.card }}
              >
                {top ? (
                  <View className="mb-2 flex-row items-center" style={{ gap: 4 }}>
                    <Star size={10} color={colors.primary} fill={colors.primary} />
                    <Text className="text-[10px] font-semibold" style={{ color: colors.primary }}>Top taklif</Text>
                  </View>
                ) : null}
                <View className="mb-3 flex-row items-center" style={{ gap: 12 }}>
                  <View className="items-center justify-center rounded-xl bg-secondary" style={{ width: 44, height: 44 }}>
                    <Truck size={18} color={colors.mutedForeground} />
                  </View>
                  <View className="flex-1">
                    <Text className="text-sm font-bold text-foreground">{b.driver?.full_name || "—"}</Text>
                    <Text className="text-xs text-muted-foreground">
                      {b.driver?.car_model || ""}
                      {b.driver?.plate_number ? ` · ${b.driver.plate_number}` : ""}
                    </Text>
                    <View className="mt-0.5 flex-row items-center" style={{ gap: 8 }}>
                      <View className="flex-row items-center" style={{ gap: 2 }}>
                        <Star size={10} color={colors.primary} fill={colors.primary} />
                        <Text className="text-xs text-foreground">{toNum(b.driver?.rating).toFixed(1)}</Text>
                      </View>
                      <Text className="text-xs text-muted-foreground">· {b.driver?.completed_orders || 0} {t("completed")}</Text>
                    </View>
                  </View>
                  <View className="items-end">
                    <Text className="text-lg font-bold text-foreground">{groupNum(toNum(b.price))}</Text>
                    <Text className="text-[10px] text-muted-foreground">so'm</Text>
                  </View>
                </View>
                <Pressable
                  onPress={() => setSel(b)}
                  className="w-full items-center rounded-xl py-2.5 active:opacity-90"
                  style={{ backgroundColor: top ? colors.primary : colors.secondary, borderWidth: top ? 0 : 1, borderColor: colors.border }}
                >
                  <Text className="text-sm font-semibold" style={{ color: top ? colors.primaryForeground : colors.foreground }}>
                    {t("selectDriver")}
                  </Text>
                </Pressable>
              </View>
            );
          })}
        </ScrollView>
      )}

      {/* Confirm sheet */}
      <Modal visible={!!sel} transparent animationType="slide" onRequestClose={() => setSel(null)}>
        <View className="flex-1 justify-end" style={{ backgroundColor: "rgba(0,0,0,0.5)" }}>
          <View className="rounded-t-[28px] border-t border-border bg-card p-5">
            <View className="mb-4 items-center">
              <View style={{ width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border }} />
            </View>
            <View className="mb-4 flex-row items-center" style={{ gap: 12 }}>
              <View className="items-center justify-center rounded-2xl" style={{ width: 48, height: 48, backgroundColor: `${colors.primary}26` }}>
                <Truck size={20} color={colors.primary} />
              </View>
              <View className="flex-1">
                <Text className="text-base font-bold text-foreground">{sel?.driver?.full_name || "—"}</Text>
                <Text className="text-xs text-muted-foreground">
                  {sel?.driver?.car_model || ""}
                  {sel?.driver?.plate_number ? ` · ${sel.driver.plate_number}` : ""}
                </Text>
              </View>
              <Text className="text-lg font-bold text-foreground">{fmt(toNum(sel?.price))}</Text>
            </View>
            <Text className="mb-1 text-sm font-semibold text-foreground">{t("confirmDriverTitle")}</Text>
            <Text className="mb-5 text-xs text-muted-foreground">{t("confirmDriverDesc")}</Text>
            <View className="flex-row" style={{ gap: 12 }}>
              <View className="flex-1">
                <SecondaryButton label={t("bidSheetCancel")} onPress={() => setSel(null)} />
              </View>
              <View style={{ flex: 2 }}>
                <PrimaryButton label={t("confirmSelectDriver")} onPress={confirm} loading={busy} />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}
