import { useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { AlertCircle, Flag } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { T } from "@/i18n/translations";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { openClientDispute } from "@/api/client-orders.api";
import { haptics } from "@/core/haptics";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton } from "@/components/buttons";

export function DisputeScreen({ orderId, onBack }: { orderId: number; onBack: () => void }) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const reasons = (T[lang].disputeReasons as string).split("|");
  const [sel, setSel] = useState("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  async function go() {
    if (!sel) {
      setErr(t("disputeErrorEmpty"));
      return;
    }
    setLoading(true);
    setErr("");
    try {
      await openClientDispute(orderId, { reason: sel, comment: comment || null });
      haptics.warning();
      setLoading(false);
      setDone(true);
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
      setLoading(false);
    }
  }

  if (done) {
    return (
      <View className="flex-1 items-center justify-center bg-background px-8">
        <View className="mb-4 items-center justify-center rounded-full" style={{ width: 80, height: 80, backgroundColor: `${colors.warning}26` }}>
          <Flag size={36} color={colors.warning} fill={colors.warning} />
        </View>
        <Text className="mb-2 text-center text-[24px] font-extrabold text-foreground">{t("disputeSuccess")}</Text>
        <Text className="mb-8 text-center text-sm text-muted-foreground">{t("disputeSuccessDesc")}</Text>
        <Pressable onPress={onBack} className="rounded-2xl bg-primary px-8 py-3 active:opacity-90">
          <Text className="text-sm font-semibold text-primary-foreground">{t("back")}</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("disputeTitle")} />
      <ScrollView contentContainerClassName="p-4 gap-4">
        <View>
          <Text className="mb-2 text-xs font-medium text-muted-foreground">{t("disputeReason")}</Text>
          <View style={{ gap: 8 }}>
            {reasons.map((r) => {
              const active = sel === r;
              return (
                <Pressable
                  key={r}
                  onPress={() => {
                    setSel(r);
                    setErr("");
                  }}
                  className="flex-row items-center rounded-xl border px-4 py-3"
                  style={{ gap: 12, borderColor: active ? colors.primary : colors.border, backgroundColor: active ? `${colors.primary}1A` : colors.card }}
                >
                  <View
                    style={{
                      width: 16,
                      height: 16,
                      borderRadius: 8,
                      borderWidth: 2,
                      borderColor: active ? colors.primary : colors.border,
                      backgroundColor: active ? colors.primary : "transparent",
                    }}
                  />
                  <Text className="text-sm font-medium text-foreground">{r}</Text>
                </Pressable>
              );
            })}
          </View>
          {err ? (
            <View className="mt-2 flex-row items-center" style={{ gap: 4 }}>
              <AlertCircle size={11} color={colors.destructive} />
              <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
            </View>
          ) : null}
        </View>
        <View>
          <Text className="mb-1.5 text-xs font-medium text-muted-foreground">{t("disputeComment")}</Text>
          <TextInput
            multiline
            numberOfLines={4}
            placeholder={t("disputeReasonPlaceholder")}
            placeholderTextColor={colors.mutedForeground}
            value={comment}
            onChangeText={setComment}
            className="rounded-xl border border-border bg-input px-4 py-3 text-sm text-foreground"
            style={{ minHeight: 100, textAlignVertical: "top" }}
          />
        </View>
      </ScrollView>
      <View className="border-t border-border p-4">
        <PrimaryButton
          label={t("submitDispute")}
          onPress={go}
          loading={loading}
          leftIcon={<Flag size={14} color={colors.primaryForeground} />}
        />
      </View>
    </View>
  );
}
