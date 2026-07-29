import { useEffect, useRef } from "react";
import { Animated, Text, View } from "react-native";
import { Send as PaperPlaneTilt } from "lucide-react-native";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";

/** Brand splash. Auto-advances after ~2.2s (matches the web timing). */
export function SplashScreen({ onDone }: { onDone: () => void }) {
  const { t } = useT();
  const { colors } = useTheme();
  const scale = useRef(new Animated.Value(0.6)).current;
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(scale, { toValue: 1, useNativeDriver: true, friction: 6 }),
      Animated.timing(opacity, { toValue: 1, duration: 400, useNativeDriver: true }),
    ]).start();
    const id = setTimeout(onDone, 2200);
    return () => clearTimeout(id);
  }, [onDone, scale, opacity]);

  return (
    <View className="flex-1 items-center justify-center bg-background" style={{ gap: 20 }}>
      <Animated.View style={{ transform: [{ scale }], opacity }}>
        <View
          style={{
            width: 80,
            height: 80,
            borderRadius: 26,
            backgroundColor: colors.primary,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <PaperPlaneTilt size={32} color={colors.primaryForeground} fill={colors.primaryForeground} />
        </View>
      </Animated.View>

      <Animated.View style={{ opacity }} className="items-center">
        <Text style={{ fontSize: 26, fontWeight: "800", color: colors.foreground }}>elchi</Text>
        <Text className="mt-1.5 text-sm text-muted-foreground">{t("splashTagline")}</Text>
      </Animated.View>

      {/* Route thread: origin ring → dashed line → destination pin */}
      <Animated.View className="mt-2 flex-row items-center" style={{ opacity }}>
        <View
          style={{
            width: 12,
            height: 12,
            borderRadius: 6,
            borderWidth: 2.5,
            borderColor: colors.feruza,
            backgroundColor: colors.background,
          }}
        />
        <View
          style={{
            height: 2,
            width: 96,
            marginHorizontal: 4,
            backgroundColor: colors.primary,
            opacity: 0.6,
          }}
        />
        <View
          style={{
            width: 12,
            height: 12,
            backgroundColor: colors.primary,
            borderRadius: 6,
            borderBottomLeftRadius: 2,
            transform: [{ rotate: "45deg" }],
          }}
        />
      </Animated.View>
    </View>
  );
}
