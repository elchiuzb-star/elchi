import { useState } from "react";
import { Linking, Pressable, ScrollView, Text, View } from "react-native";
import { ChevronDown, Headphones, Phone } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { BackHeader, SectionLabel } from "@/components/primitives";
import { SUPPORT_PHONE } from "@/core/config";

function FaqItem({ q, a }: { q: string; a: string }) {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <Pressable onPress={() => setOpen((o) => !o)} className="rounded-2xl border border-border bg-card p-4">
      <View className="flex-row items-center justify-between" style={{ gap: 12 }}>
        <Text className="flex-1 text-sm font-semibold text-foreground">{q}</Text>
        <View style={{ transform: [{ rotate: open ? "180deg" : "0deg" }] }}>
          <ChevronDown size={16} color={colors.mutedForeground} />
        </View>
      </View>
      {open ? <Text className="mt-2 text-xs leading-relaxed text-muted-foreground">{a}</Text> : null}
    </Pressable>
  );
}

export function ClientSupportScreen({ onBack }: { onBack: () => void }) {
  const { t } = useT();
  const { colors } = useTheme();
  const faqs = [
    { q: t("faq1q"), a: t("faq1a") },
    { q: t("faq2q"), a: t("faq2a") },
    { q: t("faq3q"), a: t("faq3a") },
  ];
  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("helpTitle")} />
      <ScrollView contentContainerClassName="p-4 gap-5">
        <View
          className="flex-row items-start rounded-2xl border p-4"
          style={{ gap: 12, borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}1A` }}
        >
          <View
            className="items-center justify-center rounded-full"
            style={{ width: 44, height: 44, backgroundColor: `${colors.primary}26` }}
          >
            <Headphones size={20} color={colors.primary} />
          </View>
          <View className="flex-1">
            <Text className="text-sm font-semibold text-foreground">{t("helpContactTitle")}</Text>
            <Text className="mt-0.5 text-xs text-muted-foreground">{t("helpHours")}</Text>
            <Pressable
              onPress={() => Linking.openURL(`tel:${SUPPORT_PHONE}`)}
              className="mt-3 flex-row items-center self-start rounded-xl bg-primary px-4 py-2.5 active:opacity-90"
              style={{ gap: 8 }}
            >
              <Phone size={15} color={colors.primaryForeground} />
              <Text className="text-sm font-semibold text-primary-foreground">{t("helpCallBtn")}</Text>
            </Pressable>
          </View>
        </View>
        <View>
          <SectionLabel>{t("helpFaqTitle")}</SectionLabel>
          <View className="mt-2" style={{ gap: 8 }}>
            {faqs.map((f, i) => (
              <FaqItem key={i} q={f.q} a={f.a} />
            ))}
          </View>
        </View>
      </ScrollView>
    </View>
  );
}
