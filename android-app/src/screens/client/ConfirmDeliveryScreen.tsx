import { useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { AlertCircle, CheckCheck, CreditCard } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { getClientOrder, confirmClientOrder } from "@/api/client-orders.api";
import { useAsync } from "@/data/useApi";
import { cityName as cityNameOf, toNumber as toNum } from "@/data/format";
import { BackHeader } from "@/components/primitives";
import { fmt } from "@/core/order";
import { haptics } from "@/core/haptics";

export function ConfirmDeliveryScreen({
  orderId,
  onBack,
  onConfirm,
}: {
  orderId: number;
  onBack: () => void;
  onConfirm: () => void;
}) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const { data: o } = useAsync<any>(() => getClientOrder(orderId), [orderId]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const price = toNum(o?.final_price ?? o?.client_price ?? o?.suggested_price);

  async function go() {
    setLoading(true);
    setErr("");
    try {
      await confirmClientOrder(orderId);
      haptics.success();
      onConfirm();
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
      setLoading(false);
    }
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("confirmDeliveryTitle")} />
      <View className="flex-1 p-4" style={{ gap: 16 }}>
        <View
          className="items-center rounded-2xl border p-5"
          style={{ borderColor: `${colors.success}33`, backgroundColor: `${colors.success}0D` }}
        >
          <View className="mb-3 items-center justify-center rounded-full" style={{ width: 64, height: 64, backgroundColor: `${colors.success}26` }}>
            <CheckCheck size={28} color={colors.success} />
          </View>
          <Text className="mb-1 text-base font-bold text-foreground">
            {cityNameOf(o?.from_city, lang)} → {cityNameOf(o?.to_city, lang)}
          </Text>
          <Text className="text-sm text-muted-foreground">{t("statusDelivered")}</Text>
        </View>

        <View className="rounded-2xl border border-border bg-card p-4">
          <View className="mb-3 flex-row items-center" style={{ gap: 12 }}>
            <CreditCard size={16} color={colors.primary} />
            <Text className="text-sm font-semibold text-foreground">{t("paymentNote")}</Text>
          </View>
          <Text className="text-sm text-muted-foreground">{t("cashNote")}</Text>
          <View className="mt-3 flex-row items-center justify-between border-t border-border pt-3">
            <Text className="text-xs text-muted-foreground">Jami to'lov</Text>
            <Text className="text-base font-bold text-foreground">{price > 0 ? fmt(price) : "—"}</Text>
          </View>
        </View>

        {err ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
          </View>
        ) : null}
      </View>
      <View className="border-t border-border p-4">
        <Pressable
          onPress={go}
          disabled={loading}
          className="w-full flex-row items-center justify-center rounded-2xl py-3.5 active:opacity-90"
          style={{ gap: 8, backgroundColor: colors.success, opacity: loading ? 0.7 : 1 }}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <CheckCheck size={16} color="#fff" />
              <Text className="text-sm font-semibold text-white">{t("confirmBtn")}</Text>
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}
