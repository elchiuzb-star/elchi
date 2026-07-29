import type { ReactNode } from "react";
import { View } from "react-native";
import { SafeAreaView, type Edge } from "react-native-safe-area-context";

/**
 * Full-screen container with the themed background and safe-area insets.
 * Replaces the web app's simulated "phone frame" — on-device the screen *is*
 * the phone, so we only need safe-area padding.
 */
export function Screen({
  children,
  edges = ["top", "bottom"],
  className = "",
}: {
  children: ReactNode;
  edges?: Edge[];
  className?: string;
}) {
  return (
    <SafeAreaView edges={edges} className="flex-1 bg-background">
      <View className={`flex-1 ${className}`}>{children}</View>
    </SafeAreaView>
  );
}
