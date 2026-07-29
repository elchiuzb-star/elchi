import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { ChevronLeft as CaretLeft } from "lucide-react-native";
import { useTheme } from "@/theme/ThemeProvider";

/** Primary full-width CTA with optional leading/trailing icons and a spinner. */
export function PrimaryButton({
  label,
  onPress,
  loading = false,
  disabled = false,
  leftIcon,
  rightIcon,
}: {
  label: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}) {
  const { colors } = useTheme();
  const isDisabled = disabled || loading;
  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      className="w-full flex-row items-center justify-center rounded-2xl bg-primary py-4 active:opacity-90"
      style={{ gap: 8, opacity: isDisabled ? 0.6 : 1 }}
    >
      {loading ? (
        <ActivityIndicator color={colors.primaryForeground} />
      ) : (
        <>
          {leftIcon}
          <Text className="text-base font-semibold text-primary-foreground">{label}</Text>
          {rightIcon}
        </>
      )}
    </Pressable>
  );
}

/** Secondary full-width button (bordered, neutral surface). */
export function SecondaryButton({
  label,
  onPress,
  disabled = false,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      className="w-full items-center justify-center rounded-2xl border border-border bg-secondary py-4 active:opacity-80"
      style={{ opacity: disabled ? 0.6 : 1 }}
    >
      <Text className="text-sm font-semibold text-foreground">{label}</Text>
    </Pressable>
  );
}

/** Round back button used at the top-left of auth/detail screens. */
export function BackButton({ onPress }: { onPress: () => void }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityLabel="Ortga"
      className="h-9 w-9 items-center justify-center rounded-xl bg-secondary active:opacity-80"
    >
      <CaretLeft size={18} color={colors.foreground} />
    </Pressable>
  );
}

/** Spacer that keeps content clear of the very bottom edge. */
export function BottomBar({ children }: { children: ReactNode }) {
  return <View className="px-5 pb-2 pt-3">{children}</View>;
}
