import { Text, View } from "react-native";
import { Send as PaperPlaneTilt } from "lucide-react-native";
import { useTheme } from "@/theme/ThemeProvider";

/** The Elchi mark: a paper-plane seal in a rounded square + "elchi" wordmark. */
export function ElchiLogo({ size = 40 }: { size?: number }) {
  const { colors } = useTheme();
  return (
    <View className="flex-row items-center" style={{ gap: 10 }}>
      <View
        style={{
          width: size,
          height: size,
          borderRadius: size * 0.4,
          backgroundColor: colors.primary,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <PaperPlaneTilt
          size={size * 0.46}
          color={colors.primaryForeground}
          fill={colors.primaryForeground}
        />
      </View>
      <Text
        style={{ fontSize: 24, fontWeight: "800", color: colors.foreground, lineHeight: 26 }}
      >
        elchi
      </Text>
    </View>
  );
}
