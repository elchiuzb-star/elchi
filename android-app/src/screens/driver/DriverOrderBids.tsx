import { Text, View } from "react-native";
import { Star, Truck } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getDriverOrderDetail } from "@/api/driver.api";
import { useAsync } from "@/data/useApi";
import { toNumber as toNum } from "@/data/format";
import { fmt } from "@/core/order";

/** Shows all active bids on an order so a driver can size up the competition —
 *  both before bidding (to price competitively) and after. */
export function DriverOrderBids({ orderId }: { orderId: number }) {
  const { t } = useT();
  const { colors } = useTheme();
  const { data: o } = useAsync<any>(() => getDriverOrderDetail(orderId), [orderId]);
  const bids: any[] = Array.isArray(o?.bids) ? o.bids : [];
  const myBid = o?.my_bid;
  // Hide only when there's genuinely nothing to compare (no bids and you
  // haven't bid). Otherwise show the field, including competitors' offers.
  if (!bids.length && !myBid) return null;
  const lowest = bids.length ? Math.min(...bids.map((b) => toNum(b.price))) : 0;

  return (
    <View className="rounded-2xl border border-border bg-card p-4">
      <View className="mb-3 flex-row items-center justify-between">
        <Text className="text-xs uppercase tracking-wide text-muted-foreground">{t("otherBids")}</Text>
        <Text className="text-[11px] text-muted-foreground">
          {bids.length} {t("bidsCountLabel")}
        </Text>
      </View>
      {bids.length === 0 ? (
        <Text className="text-xs text-muted-foreground">{t("noBidsForOrder")}</Text>
      ) : (
        <View style={{ gap: 8 }}>
          {bids.map((b: any) => {
            const mine = Boolean(b.is_mine);
            const price = toNum(b.price);
            const isLowest = price === lowest;
            return (
              <View
                key={b.id}
                className="flex-row items-center rounded-xl border p-3"
                style={{ gap: 12, borderColor: mine ? colors.primary : colors.border, backgroundColor: mine ? `${colors.primary}0D` : `${colors.secondary}4D` }}
              >
                <View
                  className="items-center justify-center rounded-full"
                  style={{ width: 32, height: 32, backgroundColor: mine ? `${colors.primary}26` : colors.secondary }}
                >
                  <Truck size={14} color={mine ? colors.primary : colors.mutedForeground} />
                </View>
                <View className="min-w-0 flex-1">
                  <View className="flex-row items-center" style={{ gap: 6 }}>
                    <Text className="text-sm font-medium text-foreground" numberOfLines={1}>
                      {mine ? t("yourBid") : b.driver?.full_name || "—"}
                    </Text>
                    {isLowest ? (
                      <View className="rounded px-1.5 py-0.5" style={{ backgroundColor: `${colors.success}26` }}>
                        <Text className="text-[9px] font-semibold uppercase" style={{ color: colors.success }}>{t("lowestBid")}</Text>
                      </View>
                    ) : null}
                  </View>
                  <View className="mt-0.5 flex-row items-center" style={{ gap: 8 }}>
                    {b.driver?.car_model ? <Text className="text-[11px] text-muted-foreground">{b.driver.car_model}</Text> : null}
                    {toNum(b.driver?.rating) > 0 ? (
                      <View className="flex-row items-center" style={{ gap: 2 }}>
                        <Star size={9} color={colors.warning} fill={colors.warning} />
                        <Text className="text-[11px] text-muted-foreground">{toNum(b.driver.rating).toFixed(1)}</Text>
                      </View>
                    ) : null}
                  </View>
                </View>
                <Text className="text-sm font-bold" style={{ color: mine ? colors.primary : colors.foreground }}>{fmt(price)}</Text>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}
