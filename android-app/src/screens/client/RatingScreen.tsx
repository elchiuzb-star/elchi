import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { AlertCircle, Star, ThumbsUp, Truck } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { T } from "@/i18n/translations";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { rateClientOrder } from "@/api/client-orders.api";
import { haptics } from "@/core/haptics";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton } from "@/components/buttons";

export function RatingScreen({
  orderId,
  onBack,
  onSubmit,
}: {
  orderId: number;
  onBack: () => void;
  onSubmit: () => void;
}) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const labels = T[lang].ratingLabels as string[];
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState("");

  async function go() {
    if (!stars) return;
    setLoading(true);
    setErr("");
    try {
      await rateClientOrder(orderId, { rating: stars, comment: comment || null });
      haptics.success();
      setLoading(false);
      setDone(true);
      setTimeout(onSubmit, 1800);
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
      setLoading(false);
    }
  }

  if (done) {
    return (
      <View className="flex-1 items-center justify-center bg-background px-8">
        <View className="mb-4 items-center justify-center rounded-full" style={{ width: 80, height: 80, backgroundColor: `${colors.primary}26` }}>
          <ThumbsUp size={36} color={colors.primary} fill={colors.primary} />
        </View>
        <Text className="mb-2 text-center text-[24px] font-extrabold text-foreground">{t("ratingSuccess")}</Text>
        <Text className="text-center text-sm text-muted-foreground">Bahoingiz uchun rahmat!</Text>
      </View>
    );
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("rateDriverTitle")} />
      <View className="flex-1 items-center p-6" style={{ gap: 24 }}>
        <View className="items-center justify-center rounded-2xl" style={{ width: 80, height: 80, backgroundColor: `${colors.primary}26` }}>
          <Truck size={36} color={colors.primary} />
        </View>
        <View className="items-center">
          <Text className="mb-4 text-center text-sm font-medium text-muted-foreground">{t("ratingDesc")}</Text>
          <View className="flex-row justify-center" style={{ gap: 12 }}>
            {[1, 2, 3, 4, 5].map((s) => (
              <Pressable key={s} onPress={() => setStars(s)}>
                <Star
                  size={36}
                  color={s <= stars ? colors.primary : colors.border}
                  fill={s <= stars ? colors.primary : "transparent"}
                />
              </Pressable>
            ))}
          </View>
          {stars > 0 ? <Text className="mt-3 text-center text-sm font-medium text-foreground">{labels[stars]}</Text> : null}
        </View>
        <View className="w-full">
          <Text className="mb-1.5 text-xs font-medium text-muted-foreground">{t("addComment")}</Text>
          <TextInput
            multiline
            numberOfLines={3}
            placeholder="Izoh..."
            placeholderTextColor={colors.mutedForeground}
            value={comment}
            onChangeText={setComment}
            className="rounded-xl border border-border bg-input px-4 py-3 text-sm text-foreground"
            style={{ minHeight: 84, textAlignVertical: "top" }}
          />
        </View>
        {err ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
          </View>
        ) : null}
      </View>
      <View className="border-t border-border p-4">
        <PrimaryButton
          label={t("submitRating")}
          onPress={go}
          loading={loading}
          disabled={!stars}
          leftIcon={<Star size={14} color={colors.primaryForeground} fill={colors.primaryForeground} />}
        />
      </View>
    </View>
  );
}
