import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { Bell, ChevronRight, CheckCircle2, LogOut, Package, Settings, User } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { getMe } from "@/api/auth.api";
import { updateClientProfile } from "@/api/client-profile.api";
import { useAsync } from "@/data/useApi";
import { usePullRefresh } from "@/data/usePullRefresh";
import { IconTile, StatusBadge } from "@/components/primitives";

export type ClientStats = { active: number; bids: number; completed: number };

export function ClientProfileScreen({
  phone,
  onOrders,
  onNotifications,
  onSettings,
  onLogout,
  stats,
  onRefresh,
}: {
  phone: string;
  onOrders: () => void;
  onNotifications: () => void;
  onSettings: () => void;
  onLogout: () => void;
  stats: ClientStats;
  onRefresh?: () => void | Promise<unknown>;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const { data: me, reload } = useAsync<any>(() => getMe(), []);
  const refresh = usePullRefresh(() => Promise.all([reload(), onRefresh?.()]));
  const [name, setName] = useState("");
  useEffect(() => {
    if (me?.full_name) setName(me.full_name);
  }, [me]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveErr, setSaveErr] = useState("");

  async function save() {
    setSaving(true);
    setSaveErr("");
    try {
      await updateClientProfile(name);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setSaveErr(getUzbekErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  const links = [
    { icon: Package, label: t("myOrdersLink"), action: onOrders },
    { icon: Bell, label: t("notificationsLink"), action: onNotifications },
    { icon: Settings, label: t("settings"), action: onSettings },
  ];

  return (
    <ScrollView contentContainerClassName="p-4 gap-4 pb-6" refreshControl={refresh}>
      <Text className="pl-14 pt-1 text-[22px] font-extrabold text-foreground">{t("clientProfile")}</Text>

      <View className="rounded-2xl border border-border bg-card p-5">
        <View className="flex-row items-center" style={{ gap: 16 }}>
          <View className="items-center justify-center rounded-2xl" style={{ width: 64, height: 64, backgroundColor: `${colors.primary}26` }}>
            <User size={28} color={colors.primary} />
          </View>
          <View style={{ gap: 4 }}>
            <Text className="text-[18px] font-bold text-foreground">{name || "—"}</Text>
            <Text className="text-sm text-muted-foreground">{phone}</Text>
            <StatusBadge status="active" />
          </View>
        </View>
        <View className="mt-4 flex-row border-t border-border pt-4">
          {[
            { label: t("activeStat"), value: String(stats.active) },
            { label: t("bidsStat"), value: String(stats.bids) },
            { label: t("completedStat"), value: String(stats.completed) },
          ].map(({ label, value }) => (
            <View key={label} className="flex-1 items-center">
              <Text className="text-lg font-bold text-foreground">{value}</Text>
              <Text className="text-[10px] text-muted-foreground">{label}</Text>
            </View>
          ))}
        </View>
      </View>

      <View className="rounded-2xl border border-border bg-card p-4">
        <Text className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("personalData")}</Text>
        <Text className="mb-1.5 text-xs text-muted-foreground">{t("fullNameLabel")}</Text>
        <View className="flex-row" style={{ gap: 8 }}>
          <TextInput
            value={name}
            onChangeText={setName}
            className="flex-1 rounded-xl border border-border bg-input px-4 py-3 text-sm text-foreground"
            placeholderTextColor={colors.mutedForeground}
          />
          <Pressable
            onPress={save}
            disabled={saving}
            className="items-center justify-center rounded-xl px-4"
            style={{
              backgroundColor: saved ? `${colors.success}26` : colors.primary,
              borderWidth: saved ? 1 : 0,
              borderColor: `${colors.success}4D`,
            }}
          >
            {saving ? (
              <ActivityIndicator color={colors.primaryForeground} />
            ) : saved ? (
              <CheckCircle2 size={16} color={colors.success} />
            ) : (
              <Text className="text-sm font-medium text-primary-foreground">{t("saveProfile")}</Text>
            )}
          </Pressable>
        </View>
        {saveErr ? <Text className="mt-2 text-sm" style={{ color: colors.destructive }}>{saveErr}</Text> : null}
      </View>

      <View className="overflow-hidden rounded-2xl border border-border bg-card">
        {links.map(({ icon: Icon, label, action }, i) => (
          <Pressable
            key={label}
            onPress={action}
            className="flex-row items-center px-4 py-3 active:bg-secondary"
            style={{ gap: 12, borderTopWidth: i > 0 ? 1 : 0, borderColor: colors.border }}
          >
            <IconTile icon={Icon} size={15} />
            <Text className="flex-1 text-sm text-foreground">{label}</Text>
            <ChevronRight size={16} color={colors.mutedForeground} />
          </Pressable>
        ))}
        <Pressable
          onPress={onLogout}
          className="flex-row items-center border-t border-border px-4 py-3 active:opacity-80"
          style={{ gap: 12 }}
        >
          <IconTile icon={LogOut} size={15} tone="danger" />
          <Text className="flex-1 text-sm" style={{ color: colors.destructive }}>{t("logOut")}</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}
