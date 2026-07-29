import { Pressable, Text, View } from "react-native";
import { ChevronRight as CaretRight, Package, Truck } from "lucide-react-native";
import type { Role } from "@/core/types";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { ElchiLogo } from "@/components/ElchiLogo";
import { BackButton } from "@/components/buttons";

/** Pick client vs driver. (Admin is web-only and excluded from this app.) */
export function RoleSelectScreen({
  onSelect,
  onBack,
}: {
  onSelect: (r: Role) => void;
  onBack: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();

  const roles: { id: Role; Icon: typeof Package; title: string; desc: string }[] = [
    { id: "client", Icon: Package, title: t("roleClient"), desc: t("roleClientDesc") },
    { id: "driver", Icon: Truck, title: t("roleDriver"), desc: t("roleDriverDesc") },
  ];

  return (
    <View className="flex-1 bg-background px-5 pb-8 pt-10">
      <BackButton onPress={onBack} />

      <View className="mt-6">
        <ElchiLogo size={36} />
      </View>

      <View className="mb-8 mt-6">
        <Text style={{ fontSize: 22, fontWeight: "700", color: colors.foreground }}>
          {t("roleTitle")}
        </Text>
        <Text className="mt-1.5 text-sm text-muted-foreground">{t("roleDesc")}</Text>
      </View>

      <View className="flex-1" style={{ gap: 12 }}>
        {roles.map(({ id, Icon, title, desc }) => (
          <Pressable
            key={id}
            onPress={() => onSelect(id)}
            className="flex-row items-center rounded-2xl border border-border bg-card p-5 active:opacity-90"
            style={{ gap: 16 }}
          >
            <View
              className="items-center justify-center rounded-2xl"
              style={{ width: 56, height: 56, backgroundColor: `${colors.primary}1A` }}
            >
              <Icon size={26} color={colors.primary} />
            </View>
            <View className="flex-1">
              <Text style={{ fontSize: 16, fontWeight: "700", color: colors.foreground }}>
                {title}
              </Text>
              <Text className="mt-0.5 text-sm text-muted-foreground">{desc}</Text>
            </View>
            <CaretRight size={18} color={colors.mutedForeground} />
          </Pressable>
        ))}
      </View>

      <Text className="mt-4 text-center text-xs text-muted-foreground">
        Elchi · UZ · {new Date().getFullYear()}
      </Text>
    </View>
  );
}
