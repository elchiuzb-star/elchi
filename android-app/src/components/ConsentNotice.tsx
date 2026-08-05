import { Text, View } from "react-native";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";

/**
 * Consent notice shown on the last screen before an account is created, for
 * both client and driver. Continuing is the act of agreeing — there is no
 * checkbox to tick — so this must stay visible next to the primary action.
 *
 * The policy names are deliberately NOT tappable yet: opening a URL needs the
 * ExpoLinking native module, which is not in this build, and the hosted policy
 * pages do not exist yet either. Once both are true, install expo-linking,
 * rebuild the APK, and wrap the two names in a Text with an onPress.
 */
export function ConsentNotice() {
  const { t } = useT();
  const { colors } = useTheme();

  const emphasis = { color: colors.foreground, fontWeight: "600" as const };

  return (
    <View className="mt-4 px-2">
      <Text
        style={{ fontSize: 11, lineHeight: 16, textAlign: "center", color: colors.mutedForeground }}
      >
        {t("consentPrefix")}
        <Text style={emphasis}>{t("consentPrivacy")}</Text>
        {t("consentAnd")}
        <Text style={emphasis}>{t("consentTerms")}</Text>
        {t("consentSuffix")}
      </Text>
    </View>
  );
}
