import type { ComponentType, ReactNode } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { ChevronLeft, ChevronRight } from "@/components/icons";

type IconType = ComponentType<{ size?: number; color?: string }>;
type Tone = "muted" | "primary" | "feruza" | "success" | "danger";

/** Calm 36×36 icon container — one quiet accent per tone. */
export function IconTile({ icon: Icon, size = 16, tone = "muted" }: { icon: IconType; size?: number; tone?: Tone }) {
  const { colors } = useTheme();
  const map: Record<Tone, { bg: string; fg: string }> = {
    muted: { bg: colors.secondary, fg: colors.mutedForeground },
    primary: { bg: `${colors.primary}1A`, fg: colors.primary },
    feruza: { bg: `${colors.feruza}24`, fg: colors.feruza },
    success: { bg: `${colors.success}24`, fg: colors.success },
    danger: { bg: `${colors.destructive}1A`, fg: colors.destructive },
  };
  const { bg, fg } = map[tone];
  return (
    <View
      style={{ width: 36, height: 36, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: bg }}
    >
      <Icon size={size} color={fg} />
    </View>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <Text className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </Text>
  );
}

export function Spinner({ size = "small" }: { size?: "small" | "large" }) {
  const { colors } = useTheme();
  return (
    <View className="items-center justify-center py-16">
      <ActivityIndicator size={size} color={colors.primary} />
    </View>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  desc,
  action,
}: {
  icon: IconType;
  title: string;
  desc?: string;
  action?: ReactNode;
}) {
  const { colors } = useTheme();
  return (
    <View className="items-center justify-center px-8 py-16">
      <View
        className="mb-4 items-center justify-center rounded-2xl bg-secondary"
        style={{ width: 64, height: 64 }}
      >
        <Icon size={26} color={colors.mutedForeground} />
      </View>
      <Text className="text-sm font-semibold text-foreground">{title}</Text>
      {desc ? (
        <Text className="mt-1 max-w-[240px] text-center text-xs leading-relaxed text-muted-foreground">
          {desc}
        </Text>
      ) : null}
      {action ? <View className="mt-5">{action}</View> : null}
    </View>
  );
}

export function BackHeader({
  onBack,
  title,
  right,
}: {
  onBack: () => void;
  title: string;
  right?: ReactNode;
}) {
  const { colors } = useTheme();
  return (
    <View className="flex-row items-center border-b border-border p-4" style={{ gap: 12 }}>
      <Pressable
        onPress={onBack}
        accessibilityLabel="Ortga"
        className="h-9 w-9 items-center justify-center rounded-xl bg-secondary active:opacity-80"
      >
        <ChevronLeft size={18} color={colors.foreground} />
      </Pressable>
      <Text className="flex-1 text-[17px] font-bold text-foreground" numberOfLines={1}>
        {title}
      </Text>
      {right}
    </View>
  );
}

type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";

export function StatusBadge({ status }: { status: string }) {
  const { t } = useT();
  const { colors } = useTheme();
  const map: Record<string, { label: string; tone: StatusTone }> = {
    published: { label: t("statusPublished"), tone: "info" },
    bidding: { label: t("statusBidding"), tone: "warning" },
    accepted: { label: t("statusAccepted"), tone: "info" },
    picked_up: { label: t("statusAccepted"), tone: "info" },
    in_transit: { label: t("statusInTransit"), tone: "info" },
    delivered: { label: t("statusDelivered"), tone: "success" },
    confirmed: { label: t("statusConfirmed"), tone: "success" },
    cancelled: { label: t("statusCancelled"), tone: "danger" },
    active: { label: t("statusActive"), tone: "success" },
    inactive: { label: t("statusInactive"), tone: "neutral" },
    approved: { label: t("statusApproved"), tone: "success" },
    pending: { label: t("statusPending"), tone: "warning" },
    rejected: { label: t("admTabRejected"), tone: "danger" },
    missing: { label: t("statusMissing"), tone: "danger" },
    new: { label: t("statusNew"), tone: "neutral" },
    draft: { label: t("statusDraft"), tone: "neutral" },
  };
  const d = map[status] ?? { label: status, tone: "neutral" as StatusTone };

  const toneColor: Record<StatusTone, string> = {
    success: colors.success,
    warning: colors.warning,
    danger: colors.destructive,
    info: colors.info,
    neutral: colors.mutedForeground,
  };
  const c = toneColor[d.tone];
  const bg = d.tone === "neutral" ? colors.muted : `${c}24`;

  return (
    <View
      className="flex-row items-center self-start rounded-full border px-2.5 py-0.5"
      style={{ gap: 6, backgroundColor: bg, borderColor: `${c}4D` }}
    >
      <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: c }} />
      <Text style={{ fontSize: 10, fontWeight: "600", color: c }}>{d.label}</Text>
    </View>
  );
}

/** The signature route spine: hollow feruza origin → dashed thread → filled diamond. */
export function ThreadSpine({ minHeight = 20 }: { minHeight?: number }) {
  const { colors } = useTheme();
  return (
    <View className="items-center self-stretch pt-1.5">
      <View
        style={{
          width: 14,
          height: 14,
          borderRadius: 7,
          borderWidth: 3,
          borderColor: colors.feruza,
          backgroundColor: colors.card,
        }}
      />
      <View style={{ width: 2, flex: 1, minHeight, marginVertical: 6, backgroundColor: colors.primary, opacity: 0.55 }} />
      <View
        style={{
          width: 16,
          height: 16,
          backgroundColor: colors.primary,
          borderRadius: 8,
          borderBottomLeftRadius: 3,
          transform: [{ rotate: "45deg" }],
        }}
      />
    </View>
  );
}

export function RouteThread({
  from,
  to,
  onFrom,
  onTo,
  fromLoading,
}: {
  from: string | null;
  to: string | null;
  onFrom: () => void;
  onTo: () => void;
  fromLoading?: boolean;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const Row = ({ label, value, onPress, loading }: { label: string; value: string | null; onPress: () => void; loading?: boolean }) => (
    <Pressable onPress={onPress} className="flex-row items-center justify-between py-2.5 active:opacity-70">
      <View className="min-w-0 flex-1">
        <Text className="text-[11px] text-muted-foreground">{label}</Text>
        {loading && !value ? (
          <View className="flex-row items-center" style={{ gap: 6 }}>
            <ActivityIndicator size="small" color={colors.mutedForeground} />
            <Text className="text-[15px] text-muted-foreground" numberOfLines={1}>{t("detectingLocation")}</Text>
          </View>
        ) : (
          <Text
            className={`text-[15px] ${value ? "font-medium text-foreground" : "text-muted-foreground"}`}
            numberOfLines={1}
          >
            {value ?? t("chooseCity")}
          </Text>
        )}
      </View>
      <ChevronRight size={16} color={colors.mutedForeground} />
    </Pressable>
  );
  return (
    <View className="flex-row" style={{ gap: 12 }}>
      <ThreadSpine />
      <View className="flex-1">
        <Row label={t("whereFrom")} value={from} onPress={onFrom} loading={fromLoading} />
        <View className="h-px bg-border" />
        <Row label={t("whereTo")} value={to} onPress={onTo} />
      </View>
    </View>
  );
}

/** Route thread as a status timeline — a bead per stage. */
export function JourneySpine({
  steps,
  current,
}: {
  steps: { key: string; label: string; time?: string }[];
  current: number;
}) {
  const { colors } = useTheme();
  return (
    <View>
      {steps.map((s, i) => {
        const done = i < current;
        const now = i === current;
        const last = i === steps.length - 1;
        const nodeColor = done ? colors.primary : now ? colors.feruza : `${colors.primary}73`;
        return (
          <View key={s.key} className="flex-row" style={{ gap: 12 }}>
            <View className="items-center" style={{ width: 18 }}>
              <View
                style={{
                  width: last ? 15 : 14,
                  height: last ? 15 : 14,
                  marginTop: 4,
                  borderRadius: last ? 7 : 7,
                  borderBottomLeftRadius: last ? 2 : 7,
                  transform: last ? [{ rotate: "45deg" }] : [],
                  backgroundColor: done || now ? nodeColor : colors.card,
                  borderWidth: done ? 0 : 2,
                  borderColor: nodeColor,
                }}
              />
              {!last ? (
                <View style={{ width: 2, flex: 1, minHeight: 20, backgroundColor: done ? colors.primary : `${colors.primary}66` }} />
              ) : null}
            </View>
            <View className="flex-1 pb-4">
              <Text
                className={`text-sm ${now ? "font-semibold text-foreground" : done ? "text-foreground" : "text-muted-foreground"}`}
              >
                {s.label}
              </Text>
              {s.time ? <Text className="mt-0.5 text-[11px] text-muted-foreground">{s.time}</Text> : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}
