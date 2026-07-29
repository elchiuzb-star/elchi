import { useEffect } from "react";
import { Text, View } from "react-native";
import { Eye, Home, Send } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { PrimaryButton, SecondaryButton } from "@/components/buttons";
import { haptics } from "@/core/haptics";

export function OrderSuccessScreen({ onViewOrder, onHome }: { onViewOrder: () => void; onHome: () => void }) {
  const { t } = useT();
  const { colors } = useTheme();
  useEffect(() => haptics.success(), []);
  return (
    <View className="flex-1 items-center justify-center bg-background px-8">
      <View
        className="mb-6 items-center justify-center rounded-full"
        style={{ width: 112, height: 112, backgroundColor: `${colors.primary}14`, borderWidth: 2, borderColor: colors.primary }}
      >
        <Send size={42} color={colors.primary} fill={colors.primary} />
      </View>
      <Text className="mb-2 text-center text-[24px] font-extrabold text-foreground">{t("orderPublished")}</Text>
      <Text className="mb-10 text-center text-sm leading-relaxed text-muted-foreground">
        {t("orderPublishedDesc")}
      </Text>
      <View className="w-full" style={{ gap: 12 }}>
        <PrimaryButton
          label={t("viewMyOrder")}
          onPress={onViewOrder}
          leftIcon={<Eye size={16} color={colors.primaryForeground} />}
        />
        <View className="flex-row items-center justify-center">
          <SecondaryButton label={t("backHome")} onPress={onHome} />
        </View>
      </View>
    </View>
  );
}
