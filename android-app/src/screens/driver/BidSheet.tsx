import { useEffect, useState } from "react";
import { Modal, Pressable, Text, TextInput, View } from "react-native";
import { AlertCircle, CheckCircle2, Send, X } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { sendBid, updateBid } from "@/api/driver.api";
import type { UiFeedOrder } from "@/data/driver";
import { groupNum } from "@/core/order";
import { haptics } from "@/core/haptics";

type BidState = "form" | "loading" | "success";

export function BidSheet({
  order,
  onSubmitted,
  onClose,
}: {
  order: UiFeedOrder;
  onSubmitted: () => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const editing = order.hasBid && order.bidId != null;
  const updatesLeft = order.bidUpdatesLeft ?? 3;
  const exhausted = editing && updatesLeft <= 0;

  const [price, setPrice] = useState(editing && order.bidPrice ? groupNum(order.bidPrice) : "");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [st, setSt] = useState<BidState>("form");

  const num = parseInt(price.replace(/\D/g, ""), 10) || 0;
  const net = num > 0 ? Math.round(num * 0.85) : 0; // 15% system commission

  function hp(raw: string) {
    const d = raw.replace(/\D/g, "");
    setPrice(d ? groupNum(parseInt(d, 10)) : "");
    if (err) setErr("");
  }

  async function go() {
    if (!price || num === 0) {
      setErr(num === 0 && price ? t("bidSheetErrorZero") : t("bidSheetErrorEmpty"));
      return;
    }
    setSt("loading");
    try {
      if (editing) await updateBid(order.bidId!, { price: num, comment: note || null });
      else await sendBid(order.id, { price: num, comment: note || null });
      setSt("success");
      onSubmitted();
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
      setSt("form");
    }
  }

  useEffect(() => {
    if (st === "success") {
      haptics.success();
      const id = setTimeout(onClose, 2200);
      return () => clearTimeout(id);
    }
  }, [st, onClose]);

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable onPress={onClose} className="flex-1 justify-end" style={{ backgroundColor: "rgba(0,0,0,0.55)" }}>
        <Pressable onPress={() => {}} className="rounded-t-[28px] border-t border-border bg-card">
          <View className="items-center pb-1 pt-3">
            <View style={{ width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border }} />
          </View>

          {st === "success" ? (
            <View className="items-center px-6 py-10" style={{ gap: 12 }}>
              <View className="items-center justify-center rounded-full" style={{ width: 64, height: 64, backgroundColor: `${colors.success}26` }}>
                <CheckCircle2 size={32} color={colors.success} />
              </View>
              <Text className="text-lg font-bold text-foreground">{t("bidSheetSuccess")}</Text>
              <Text className="text-center text-sm text-muted-foreground">{t("bidSheetSuccessDesc")}</Text>
              <Text className="text-xs text-muted-foreground">
                {order.from} → {order.to} · {groupNum(num)} so'm
              </Text>
            </View>
          ) : (
            <View className="px-5 pb-7 pt-2">
              <View className="mb-5 flex-row items-center justify-between">
                <Text className="text-lg font-bold text-foreground">{editing ? t("bidChangePrice") : t("bidSheetTitle")}</Text>
                <Pressable onPress={onClose} className="h-8 w-8 items-center justify-center rounded-full bg-secondary">
                  <X size={14} color={colors.foreground} />
                </Pressable>
              </View>

              {/* Route summary */}
              <View className="mb-4 rounded-2xl border border-border bg-background p-4">
                <Text className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">{t("bidSheetRoute")}</Text>
                <View className="flex-row items-center" style={{ gap: 12 }}>
                  <View className="items-center" style={{ gap: 4 }}>
                    <View style={{ width: 10, height: 10, borderRadius: 5, borderWidth: 2, borderColor: colors.feruza, backgroundColor: colors.card }} />
                    <View style={{ width: 2, height: 20, backgroundColor: colors.primary, opacity: 0.6 }} />
                    <View style={{ width: 10, height: 10, backgroundColor: colors.primary, borderRadius: 5, borderBottomLeftRadius: 2, transform: [{ rotate: "45deg" }] }} />
                  </View>
                  <View className="flex-1">
                    <Text className="text-sm font-semibold text-foreground">{order.from}</Text>
                    <Text className="mb-1 text-[11px] text-muted-foreground">{order.pickup}</Text>
                    <Text className="text-sm font-semibold text-foreground">{order.to}</Text>
                    <Text className="text-[11px] text-muted-foreground">{order.dropoff}</Text>
                  </View>
                  <View className="items-end">
                    <Text className="mb-0.5 text-[10px] text-muted-foreground">{t("bidSheetSuggestedPrice")}</Text>
                    <Text className="text-base font-bold text-foreground">{groupNum(order.price)}</Text>
                    <Text className="text-[10px] text-muted-foreground">so'm</Text>
                  </View>
                </View>
              </View>

              {/* Price input */}
              <View className="mb-3">
                <Text className="mb-1.5 text-xs font-medium text-muted-foreground">{t("bidSheetYourPrice")} *</Text>
                <View
                  className="flex-row items-center rounded-xl border bg-input px-4 py-3"
                  style={{ gap: 12, borderColor: err ? colors.destructive : colors.border }}
                >
                  <Text className="text-sm text-muted-foreground">so'm</Text>
                  <TextInput
                    keyboardType="number-pad"
                    autoFocus
                    placeholder={t("bidSheetPricePlaceholder")}
                    placeholderTextColor={colors.mutedForeground}
                    value={price}
                    onChangeText={hp}
                    className="flex-1 text-sm font-bold text-foreground"
                  />
                </View>
                {err ? (
                  <View className="mt-1.5 flex-row items-center" style={{ gap: 4 }}>
                    <AlertCircle size={11} color={colors.destructive} />
                    <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
                  </View>
                ) : editing ? (
                  <Text className="mt-1.5 text-[11px]" style={{ color: exhausted ? colors.destructive : colors.mutedForeground }}>
                    {exhausted ? t("bidNoChangesLeft") : t("bidChangesLeft").replace("{n}", String(updatesLeft))}
                  </Text>
                ) : null}
              </View>

              {num > 0 ? (
                <View
                  className="mb-3 flex-row items-center justify-between rounded-xl border px-4 py-2.5"
                  style={{ borderColor: `${colors.success}33`, backgroundColor: `${colors.success}0D` }}
                >
                  <View>
                    <Text className="text-xs font-medium" style={{ color: colors.success }}>{t("bidSheetNetEst")}</Text>
                    <Text className="text-[10px] text-muted-foreground">{t("bidSheetCommissionNote")}</Text>
                  </View>
                  <Text className="text-base font-bold" style={{ color: colors.success }}>{groupNum(net)}</Text>
                </View>
              ) : null}

              <View className="mb-5">
                <Text className="mb-1.5 text-xs font-medium text-muted-foreground">{t("bidSheetNote")}</Text>
                <TextInput
                  multiline
                  placeholder={t("bidSheetNotePlaceholder")}
                  placeholderTextColor={colors.mutedForeground}
                  value={note}
                  onChangeText={setNote}
                  className="rounded-xl border border-border bg-input px-4 py-3 text-sm text-foreground"
                  style={{ minHeight: 60, textAlignVertical: "top" }}
                />
              </View>

              <View className="flex-row" style={{ gap: 12 }}>
                <Pressable onPress={onClose} className="flex-1 items-center rounded-2xl border border-border bg-secondary py-3">
                  <Text className="text-sm font-semibold text-foreground">{t("bidSheetCancel")}</Text>
                </Pressable>
                <Pressable
                  onPress={go}
                  disabled={st === "loading" || exhausted}
                  className="flex-row items-center justify-center rounded-2xl bg-primary py-3"
                  style={{ flex: 2, gap: 8, opacity: st === "loading" || exhausted ? 0.5 : 1 }}
                >
                  <Send size={14} color={colors.primaryForeground} />
                  <Text className="text-sm font-semibold text-primary-foreground">{editing ? t("bidChangePrice") : t("bidSheetSubmit")}</Text>
                </Pressable>
              </View>
            </View>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}
