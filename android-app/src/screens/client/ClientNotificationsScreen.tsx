import { Pressable, ScrollView, Text, View } from "react-native";
import { Bell, ChevronLeft } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { markNotificationRead } from "@/api/notifications.api";
import { shortDate as fmtDate } from "@/data/format";
import { usePullRefresh } from "@/data/usePullRefresh";
import { EmptyState, Spinner } from "@/components/primitives";

export function ClientNotificationsScreen({
  notifs,
  loading,
  reload,
  onBack,
}: {
  notifs: any[];
  loading: boolean;
  reload: () => void | Promise<unknown>;
  onBack?: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const refresh = usePullRefresh(reload);
  const unread = notifs.filter((n) => !n.is_read).length;

  async function readOne(id: number) {
    try {
      await markNotificationRead(id);
      reload();
    } catch {
      /* ignore */
    }
  }
  async function readAll() {
    try {
      await Promise.all(notifs.filter((n) => !n.is_read).map((n) => markNotificationRead(n.id)));
      reload();
    } catch {
      /* ignore */
    }
  }

  return (
    <View className="flex-1">
      <View className={`flex-row items-center justify-between p-4 pb-2 pt-5 ${onBack ? "" : "pl-14"}`}>
        <View className="min-w-0 flex-1 flex-row items-center" style={{ gap: 10 }}>
          {onBack ? (
            <Pressable onPress={onBack} className="h-9 w-9 items-center justify-center rounded-full bg-secondary active:opacity-80">
              <ChevronLeft size={18} color={colors.foreground} />
            </Pressable>
          ) : null}
          <View className="min-w-0">
            <Text className="text-[22px] font-extrabold text-foreground">{t("notifications")}</Text>
            {unread > 0 ? <Text className="mt-0.5 text-xs text-muted-foreground">{unread} ta o'qilmagan</Text> : null}
          </View>
        </View>
        {unread > 0 ? (
          <Pressable onPress={readAll}>
            <Text className="text-xs font-medium" style={{ color: colors.primary }}>{t("markAllRead")}</Text>
          </Pressable>
        ) : null}
      </View>

      {loading ? (
        <Spinner />
      ) : notifs.length === 0 ? (
        <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: "center" }} refreshControl={refresh}>
          <EmptyState icon={Bell} title={t("noNotifications")} desc={t("noNotifDesc")} />
        </ScrollView>
      ) : (
        <ScrollView refreshControl={refresh}>
          {notifs.map((n) => (
            <Pressable
              key={n.id}
              onPress={() => readOne(n.id)}
              className="flex-row items-start border-b border-border px-4 py-4"
              style={{ gap: 12, backgroundColor: !n.is_read ? `${colors.primary}0D` : "transparent" }}
            >
              <View
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 5,
                  marginTop: 6,
                  backgroundColor: !n.is_read ? colors.primary : "transparent",
                  borderWidth: !n.is_read ? 0 : 1,
                  borderColor: colors.border,
                }}
              />
              <View className="min-w-0 flex-1">
                <View className="mb-0.5 flex-row items-center justify-between">
                  <Text
                    className="flex-1 text-sm font-semibold"
                    style={{ color: !n.is_read ? colors.foreground : colors.mutedForeground }}
                    numberOfLines={1}
                  >
                    {n.title || n.type}
                  </Text>
                  <Text className="ml-2 text-[10px] text-muted-foreground">{fmtDate(n.created_at)}</Text>
                </View>
                <Text className="text-xs leading-relaxed text-muted-foreground">{n.message || n.body || ""}</Text>
                {n.order_id ? <Text className="mt-1 text-[10px]" style={{ color: colors.primary }}>#{n.order_id}</Text> : null}
              </View>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}
