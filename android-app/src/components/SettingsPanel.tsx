import { useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, Text, View } from "react-native";
import {
  Bell,
  ChevronRight,
  FileText,
  Info,
  LogOut,
  Monitor,
  Moon,
  Package,
  Shield,
  Sun,
  ToggleLeft,
  ToggleRight,
  Trash2,
  TrendingUp,
  Vibrate,
} from "@/components/icons";
import { deleteOwnAccount } from "@/api/auth.api";
import { getUzbekErrorMessage } from "@/utils/errors";
import { useT, type Lang, type TKey } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import type { ThemeMode } from "@/core/types";
import { BackHeader, IconTile, SectionLabel } from "@/components/primitives";

export function SettingsPanel({
  onBack,
  themeMode,
  onThemeChange,
  lang,
  onLangChange,
  onLogout,
  notifKeys,
}: {
  onBack: () => void;
  themeMode: ThemeMode;
  onThemeChange: (m: ThemeMode) => void;
  lang: Lang;
  onLangChange: (l: Lang) => void;
  onLogout: () => void;
  notifKeys: { a: TKey; ad: TKey; b: TKey; bd: TKey };
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const [na, setNa] = useState(true);
  const [nb, setNb] = useState(true);
  const [np, setNp] = useState(false);
  const [vib, setVib] = useState(true);

  const themeOpts: { id: ThemeMode; icon: typeof Sun; label: string; desc: string }[] = [
    { id: "light", icon: Sun, label: t("lightTheme"), desc: t("alwaysLight") },
    { id: "dark", icon: Moon, label: t("darkTheme"), desc: t("alwaysDark") },
    { id: "system", icon: Monitor, label: t("systemTheme"), desc: t("followsDevice") },
  ];
  const langs: { id: Lang; code: string; label: string }[] = [
    { id: "uz", code: "UZ", label: "O'zbek" },
    { id: "ru", code: "RU", label: "Русский" },
    { id: "en", code: "EN", label: "English" },
  ];
  const toggles = [
    { label: t(notifKeys.a), val: na, set: setNa, icon: Package },
    { label: t(notifKeys.b), val: nb, set: setNb, icon: Bell },
    { label: t("promotions"), val: np, set: setNp, icon: TrendingUp },
    { label: t("vibration"), val: vib, set: setVib, icon: Vibrate },
  ];
  const [deleting, setDeleting] = useState(false);

  // Two-step: the alert spells out what is erased and what is retained, so
  // "delete" is never a surprise. Confirmation is deliberately destructive-styled.
  function confirmDelete() {
    Alert.alert(t("deleteAccount"), t("deleteAccountConfirm"), [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("deleteAccountAction"),
        style: "destructive",
        onPress: async () => {
          setDeleting(true);
          try {
            await deleteOwnAccount();
            // The account is gone; the session must not linger.
            onLogout();
          } catch (e) {
            Alert.alert(t("deleteAccount"), getUzbekErrorMessage(e));
          } finally {
            setDeleting(false);
          }
        },
      },
    ]);
  }

  const accountLinks = [
    { icon: Shield, label: t("privacySecurity") },
    { icon: FileText, label: t("termsOfService") },
    { icon: Info, label: t("aboutElchi") },
  ];

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("settings")} />
      <ScrollView contentContainerClassName="p-4 gap-5 pb-8">
        {/* Appearance */}
        <View>
          <SectionLabel>{t("appearance")}</SectionLabel>
          <View className="rounded-2xl border border-border bg-card p-4">
            <View className="flex-row" style={{ gap: 8 }}>
              {themeOpts.map(({ id, icon: Icon, label, desc }) => {
                const act = themeMode === id;
                return (
                  <Pressable
                    key={id}
                    onPress={() => onThemeChange(id)}
                    className="flex-1 items-center rounded-xl border px-2 py-3"
                    style={{ gap: 6, borderColor: act ? colors.primary : colors.border, backgroundColor: act ? `${colors.primary}1A` : `${colors.secondary}80` }}
                  >
                    <Icon size={20} color={act ? colors.primary : colors.mutedForeground} />
                    <Text className="text-xs font-semibold" style={{ color: act ? colors.primary : colors.foreground }}>
                      {label}
                    </Text>
                    <Text className="text-center text-[9px] leading-tight text-muted-foreground">{desc}</Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        </View>

        {/* Language */}
        <View>
          <SectionLabel>{t("language")}</SectionLabel>
          <View className="flex-row rounded-2xl border border-border bg-card p-3" style={{ gap: 8 }}>
            {langs.map(({ id, code, label }) => {
              const act = lang === id;
              return (
                <Pressable
                  key={id}
                  onPress={() => onLangChange(id)}
                  className="flex-1 items-center rounded-xl border py-2.5"
                  style={{ gap: 6, borderColor: act ? colors.primary : colors.border, backgroundColor: act ? `${colors.primary}1A` : `${colors.secondary}80` }}
                >
                  <Text
                    className="rounded-md px-1.5 py-0.5 text-[11px] font-bold"
                    style={{
                      color: act ? colors.primaryForeground : colors.mutedForeground,
                      backgroundColor: act ? colors.primary : colors.muted,
                      overflow: "hidden",
                    }}
                  >
                    {code}
                  </Text>
                  <Text className="text-[11px] font-semibold" style={{ color: act ? colors.primary : colors.foreground }}>
                    {label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        {/* Notifications */}
        <View>
          <SectionLabel>{t("notifications2")}</SectionLabel>
          <View className="overflow-hidden rounded-2xl border border-border bg-card">
            {toggles.map(({ label, val, set, icon: Icon }, i) => (
              <View
                key={label}
                className="flex-row items-center px-4 py-3.5"
                style={{ gap: 12, borderTopWidth: i > 0 ? 1 : 0, borderColor: colors.border }}
              >
                <IconTile icon={Icon} size={15} />
                <Text className="flex-1 text-sm font-medium text-foreground">{label}</Text>
                <Pressable onPress={() => set(!val)}>
                  {val ? <ToggleRight size={34} color={colors.primary} /> : <ToggleLeft size={34} color={colors.mutedForeground} />}
                </Pressable>
              </View>
            ))}
          </View>
        </View>

        {/* Account */}
        <View>
          <SectionLabel>{t("account")}</SectionLabel>
          <View className="overflow-hidden rounded-2xl border border-border bg-card">
            {accountLinks.map(({ icon: Icon, label }, i) => (
              <Pressable
                key={label}
                className="flex-row items-center px-4 py-3.5 active:bg-secondary"
                style={{ gap: 12, borderTopWidth: i > 0 ? 1 : 0, borderColor: colors.border }}
              >
                <IconTile icon={Icon} size={15} />
                <Text className="flex-1 text-sm font-medium text-foreground">{label}</Text>
                <ChevronRight size={16} color={colors.mutedForeground} />
              </Pressable>
            ))}
          </View>
        </View>

        <View className="overflow-hidden rounded-2xl border border-border bg-card">
          <Pressable onPress={onLogout} className="flex-row items-center px-4 py-3.5 active:opacity-80" style={{ gap: 12 }}>
            <IconTile icon={LogOut} size={15} tone="danger" />
            <Text className="flex-1 text-sm font-medium" style={{ color: colors.destructive }}>{t("logOut")}</Text>
          </Pressable>

          {/* Account deletion must be reachable from inside the app — both
              stores reject "email us to delete". */}
          <Pressable
            onPress={confirmDelete}
            disabled={deleting}
            className="flex-row items-center px-4 py-3.5 active:opacity-80"
            style={{ gap: 12, borderTopWidth: 1, borderColor: colors.border }}
          >
            <IconTile icon={Trash2} size={15} tone="danger" />
            <Text className="flex-1 text-sm font-medium" style={{ color: colors.destructive }}>
              {t("deleteAccount")}
            </Text>
            {deleting ? <ActivityIndicator size="small" color={colors.destructive} /> : null}
          </Pressable>
        </View>

        <Text className="px-1 text-[11px] leading-4 text-muted-foreground">
          {t("deleteAccountHint")}
        </Text>

        <Text className="text-center text-[10px] text-muted-foreground">{t("version")}</Text>
      </ScrollView>
    </View>
  );
}
