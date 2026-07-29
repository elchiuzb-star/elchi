import { useEffect, useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { AlertCircle, CheckCircle2, ImageIcon, Send } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { getSuggestedPrice } from "@/api/cities.api";
import { useAsync } from "@/data/useApi";
import { toNumber as toNum } from "@/data/format";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton, SecondaryButton } from "@/components/buttons";
import { cargoTypeLabel, fmt, type OrderDraft } from "@/core/order";

function RouteMini({ draft }: { draft: OrderDraft }) {
  const { colors } = useTheme();
  return (
    <View className="flex-row" style={{ gap: 12 }}>
      <View className="items-center pt-1">
        <View style={{ width: 14, height: 14, borderRadius: 7, borderWidth: 3, borderColor: colors.feruza, backgroundColor: colors.card }} />
        <View style={{ width: 2, minHeight: 30, flex: 1, marginVertical: 4, backgroundColor: colors.primary, opacity: 0.55 }} />
        <View style={{ width: 16, height: 16, backgroundColor: colors.primary, borderRadius: 8, borderBottomLeftRadius: 3, transform: [{ rotate: "45deg" }] }} />
      </View>
      <View className="flex-1">
        <Text className="text-[15px] font-bold text-foreground">
          {draft.pickup?.city.uz}
          {draft.pickup?.district ? ` · ${draft.pickup.district}` : ""}
        </Text>
        <Text className="mb-3 text-xs text-muted-foreground" numberOfLines={1}>
          {draft.pickupAddress || draft.pickup?.address}
        </Text>
        <Text className="text-[15px] font-bold text-foreground">
          {draft.dropoff?.city.uz}
          {draft.dropoff?.district ? ` · ${draft.dropoff.district}` : ""}
        </Text>
        <Text className="text-xs text-muted-foreground" numberOfLines={1}>
          {draft.dropoffAddress || draft.dropoff?.address}
        </Text>
      </View>
    </View>
  );
}

export function OrderReviewScreen({
  draft,
  onChange,
  onBack,
  onPublish,
}: {
  draft: OrderDraft;
  onChange: (d: Partial<OrderDraft>) => void;
  onBack: () => void;
  onPublish: () => Promise<void>;
}) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const fromId = draft.pickup?.city.id;
  const toId = draft.dropoff?.city.id;
  const { data: tariff } = useAsync<any>(
    () => (fromId && toId ? getSuggestedPrice(fromId, toId) : Promise.resolve(null)),
    [fromId, toId],
  );
  const price = toNum(tariff?.suggested_price);
  const minPrice = toNum(tariff?.min_price);
  const maxPrice = toNum(tariff?.max_price);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (price > 0 && !draft.clientPrice) onChange({ clientPrice: String(price) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [price]);

  const clientPriceNum = toNum(draft.clientPrice);
  const priceOutOfRange =
    clientPriceNum > 0 && ((minPrice > 0 && clientPriceNum < minPrice) || (maxPrice > 0 && clientPriceNum > maxPrice));

  async function go() {
    if (priceOutOfRange) {
      setErr(clientPriceNum < minPrice ? t("priceTooLow") : t("priceTooHigh"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await onPublish();
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
      setBusy(false);
    }
  }

  const parcelTypeLabel = lang === "ru" ? "Тип отправления" : lang === "en" ? "Parcel type" : "Jo'natma turi";

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("reviewTitle")} />
      <ScrollView contentContainerClassName="p-4 gap-3">
        <View className="rounded-2xl border border-border bg-card p-4">
          <RouteMini draft={draft} />
        </View>

        <View
          className="rounded-2xl border p-4"
          style={{ gap: 12, borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}0D` }}
        >
          <View className="flex-row items-center justify-between">
            <Text className="text-xs text-muted-foreground">{t("suggestedPrice")}</Text>
            <Text className="text-sm font-bold text-foreground">{price > 0 ? fmt(price) : "—"}</Text>
          </View>
          {minPrice > 0 || maxPrice > 0 ? (
            <Text className="text-[11px] text-muted-foreground">
              {t("priceRangeHint")}: {minPrice > 0 ? fmt(minPrice) : "—"} – {maxPrice > 0 ? fmt(maxPrice) : "—"}
            </Text>
          ) : null}
          <View className="border-t pt-1" style={{ borderColor: `${colors.primary}26` }}>
            <Text className="mb-2 text-xs font-medium text-foreground">{t("yourPrice")}</Text>
            <View
              className="flex-row items-center rounded-xl border bg-card px-3 py-2.5"
              style={{ gap: 8, borderColor: priceOutOfRange ? colors.destructive : colors.border }}
            >
              <TextInput
                keyboardType="number-pad"
                value={draft.clientPrice}
                onChangeText={(v) => {
                  onChange({ clientPrice: v.replace(/[^\d]/g, "") });
                  if (err) setErr("");
                }}
                placeholder={price > 0 ? String(price) : "0"}
                placeholderTextColor={colors.mutedForeground}
                className="flex-1 text-lg font-bold text-foreground"
              />
              <Text className="text-sm text-muted-foreground">so'm</Text>
            </View>
          </View>
        </View>

        {draft.cargoType ? (
          <View className="flex-row items-center justify-between rounded-2xl border border-border bg-card p-4">
            <Text className="text-xs text-muted-foreground">{parcelTypeLabel}</Text>
            <Text className="text-sm font-medium text-foreground">{cargoTypeLabel(draft.cargoType, lang)}</Text>
          </View>
        ) : null}

        <View className="rounded-2xl border border-border bg-card p-4" style={{ gap: 8 }}>
          <Text className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">{t("contactDetails")}</Text>
          {[
            { label: t("sender"), value: draft.senderPhone },
            { label: t("receiver"), value: draft.receiverPhone },
          ].map(({ label, value }) => (
            <View key={label} className="flex-row items-center justify-between">
              <Text className="text-xs text-muted-foreground">{label}</Text>
              <Text className="text-sm text-foreground">{value}</Text>
            </View>
          ))}
          {draft.comment ? (
            <View className="border-t border-border pt-2">
              <Text className="text-xs text-muted-foreground">{t("comment")}</Text>
              <Text className="mt-0.5 text-sm text-foreground">{draft.comment}</Text>
            </View>
          ) : null}
        </View>

        {draft.hasPhoto ? (
          <View className="flex-row items-center rounded-2xl border border-border bg-card p-4" style={{ gap: 12 }}>
            <ImageIcon size={16} color={colors.primary} />
            <Text className="flex-1 text-sm font-medium text-foreground">{t("cargoPhotoTitle")}</Text>
            <CheckCircle2 size={16} color={colors.success} />
          </View>
        ) : null}

        {err ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
          </View>
        ) : null}
      </ScrollView>

      <View className="flex-row border-t border-border p-4" style={{ gap: 12 }}>
        <View className="flex-1">
          <SecondaryButton label={t("editOrder")} onPress={onBack} />
        </View>
        <View style={{ flex: 2 }}>
          <PrimaryButton
            label={t("publishOrder")}
            onPress={go}
            loading={busy}
            leftIcon={<Send size={14} color={colors.primaryForeground} />}
          />
        </View>
      </View>
    </View>
  );
}
