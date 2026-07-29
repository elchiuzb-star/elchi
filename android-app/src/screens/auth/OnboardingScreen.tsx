import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { ArrowRight, MapPin, Route as Path, Shield } from "lucide-react-native";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { ElchiLogo } from "@/components/ElchiLogo";
import { PrimaryButton } from "@/components/buttons";

/** Three-slide intro carousel (tap dots or Next to advance). */
export function OnboardingScreen({ onContinue }: { onContinue: () => void }) {
  const { t } = useT();
  const { colors } = useTheme();
  const [idx, setIdx] = useState(0);

  const slides = [
    { Icon: Path, title: t("onboardingTitle"), desc: t("onboardingDesc") },
    {
      Icon: MapPin,
      title: "Viloyatlararo yetkazish",
      desc: "Toshkent, Samarqand, Buxoro, Farg'ona va boshqa shaharlar o'rtasida",
    },
    {
      Icon: Shield,
      title: "Ishonchli qo'llarda",
      desc: "Tasdiqlangan haydovchilar, narx takliflari va yetkazuv tasdig'i",
    },
  ];
  const s = slides[idx];
  const last = idx === slides.length - 1;

  return (
    <View className="flex-1 bg-background px-6 pb-8 pt-12">
      <ElchiLogo size={36} />

      <View className="flex-1 items-center justify-center" style={{ gap: 24 }}>
        <View
          className="items-center justify-center rounded-3xl"
          style={{ width: 96, height: 96, backgroundColor: `${colors.primary}1A` }}
        >
          <s.Icon size={44} color={colors.primary} />
        </View>
        <View className="items-center">
          <Text
            className="mb-2.5 text-center"
            style={{ fontSize: 22, fontWeight: "700", color: colors.foreground }}
          >
            {s.title}
          </Text>
          <Text className="max-w-xs text-center text-sm leading-relaxed text-muted-foreground">
            {s.desc}
          </Text>
        </View>

        <View className="flex-row justify-center" style={{ gap: 6 }}>
          {slides.map((_, i) => (
            <Pressable
              key={i}
              onPress={() => setIdx(i)}
              accessibilityLabel={`${i + 1}`}
              style={{
                height: 6,
                width: i === idx ? 24 : 6,
                borderRadius: 3,
                backgroundColor: colors.primary,
                opacity: i === idx ? 1 : 0.3,
              }}
            />
          ))}
        </View>
      </View>

      <PrimaryButton
        label={last ? t("onboardingCta") : t("nextBtn")}
        onPress={() => (last ? onContinue() : setIdx((i) => i + 1))}
        rightIcon={<ArrowRight size={18} color={colors.primaryForeground} />}
      />
      {!last && (
        <Pressable onPress={onContinue} className="mt-3 w-full py-1">
          <Text className="text-center text-sm text-muted-foreground">{t("onboardingCta")}</Text>
        </Pressable>
      )}
    </View>
  );
}
