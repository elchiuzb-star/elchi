import { useState } from "react";
import { Text, TextInput, View } from "react-native";
import { Send as PaperPlaneTilt, Package, Truck, CircleAlert as WarningCircle } from "lucide-react-native";
import type { Role } from "@/core/types";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { BackButton, PrimaryButton } from "@/components/buttons";
import { ConsentNotice } from "@/components/ConsentNotice";

function fmtPhone(raw: string): string {
  const d = raw.replace(/\D/g, "").slice(0, 12);
  if (d.length <= 3) return `+${d}`;
  if (d.length <= 5) return `+${d.slice(0, 3)} ${d.slice(3)}`;
  if (d.length <= 8) return `+${d.slice(0, 3)} ${d.slice(3, 5)} ${d.slice(5)}`;
  if (d.length <= 10) return `+${d.slice(0, 3)} ${d.slice(3, 5)} ${d.slice(5, 8)} ${d.slice(8)}`;
  return `+${d.slice(0, 3)} ${d.slice(3, 5)} ${d.slice(5, 8)} ${d.slice(8, 10)} ${d.slice(10)}`;
}

export function PhoneScreen({
  role,
  onSubmit,
  onBack,
}: {
  role: Role;
  onSubmit: (phone: string) => Promise<void> | void;
  onBack: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const [phone, setPhone] = useState("+998 ");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function handleChange(v: string) {
    if (!v.startsWith("+998")) {
      setPhone("+998 ");
      return;
    }
    setPhone(fmtPhone(v));
    if (error) setError("");
  }

  async function handleSubmit() {
    const d = phone.replace(/\D/g, "");
    if (d.length < 12) {
      setError(t("phoneError"));
      return;
    }
    setLoading(true);
    try {
      await onSubmit(phone);
    } catch (e) {
      setError(getUzbekErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  const RoleIcon = role === "driver" ? Truck : Package;

  return (
    <View className="flex-1 bg-background px-5 pb-8 pt-10">
      <BackButton onPress={onBack} />

      <View className="mb-6 mt-6 flex-row items-center" style={{ gap: 8 }}>
        <View
          className="items-center justify-center rounded-xl"
          style={{ width: 32, height: 32, backgroundColor: `${colors.primary}26` }}
        >
          <RoleIcon size={15} color={colors.primary} />
        </View>
        <Text className="text-xs text-muted-foreground">
          {t("as")}{" "}
          <Text style={{ fontWeight: "600", color: colors.foreground }}>
            {t(role === "driver" ? "roleDriver" : "roleClient")}
          </Text>
        </Text>
      </View>

      <Text style={{ fontSize: 22, fontWeight: "700", color: colors.foreground }}>
        {t("phoneTitle")}
      </Text>
      <Text className="mb-8 mt-1.5 text-sm text-muted-foreground">{t("phoneDesc")}</Text>

      <View className="flex-1">
        <Text className="mb-2 text-xs text-muted-foreground">{t("phoneLabel")}</Text>
        <View
          className="mb-2 flex-row items-center rounded-2xl px-4 py-4"
          style={{
            gap: 12,
            backgroundColor: colors.input,
            borderWidth: 1,
            borderColor: error ? colors.destructive : colors.border,
          }}
        >
          <Text
            style={{
              fontSize: 11,
              fontWeight: "700",
              color: colors.primary,
              backgroundColor: `${colors.primary}1A`,
              borderRadius: 8,
              paddingHorizontal: 8,
              paddingVertical: 4,
              overflow: "hidden",
            }}
          >
            UZ
          </Text>
          <TextInput
            autoFocus
            keyboardType="phone-pad"
            placeholder="+998 XX XXX XX XX"
            placeholderTextColor={colors.mutedForeground}
            value={phone}
            onChangeText={handleChange}
            style={{ flex: 1, fontSize: 18, fontWeight: "700", color: colors.foreground }}
          />
        </View>
        {error ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <WarningCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{error}</Text>
          </View>
        ) : null}
      </View>

      <PrimaryButton
        label={t("phoneCta")}
        onPress={handleSubmit}
        loading={loading}
        leftIcon={<PaperPlaneTilt size={16} color={colors.primaryForeground} />}
      />

      {/* Tapping the button above is the act of consenting, so the notice has to
          sit next to it — same screen for both client and driver. */}
      <ConsentNotice />
    </View>
  );
}
