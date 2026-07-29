import { useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { AlertCircle, MapPin, Navigation, Phone } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton } from "@/components/buttons";
import { fmtLocalPhone, localPhone, type OrderDraft } from "@/core/order";

export function ContactsScreen({
  draft,
  onChange,
  onBack,
  onNext,
}: {
  draft: OrderDraft;
  onChange: (d: Partial<OrderDraft>) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const [errs, setErrs] = useState<Record<string, string>>({});

  function validate() {
    const e: Record<string, string> = {};
    if (localPhone(draft.senderPhone).length !== 9) e.senderPhone = t("phoneError");
    if (localPhone(draft.receiverPhone).length !== 9) e.receiverPhone = t("phoneError");
    if (!draft.pickupAddress) e.pickupAddress = "Kiriting";
    if (!draft.dropoffAddress) e.dropoffAddress = "Kiriting";
    setErrs(e);
    return Object.keys(e).length === 0;
  }

  const clearErr = (key: string) => errs[key] && setErrs((p) => ({ ...p, [key]: "" }));
  const draftVal = draft as unknown as Record<string, string>;

  const phoneFields = [
    { label: t("senderPhone"), key: "senderPhone" as const },
    { label: t("receiverPhone"), key: "receiverPhone" as const },
  ];
  const addressFields = [
    { label: t("pickupAddress"), key: "pickupAddress" as const, icon: Navigation },
    { label: t("dropoffAddress"), key: "dropoffAddress" as const, icon: MapPin },
  ];

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("contactsTitle")} />
      <ScrollView contentContainerClassName="p-4 gap-4" keyboardShouldPersistTaps="handled">
        {phoneFields.map(({ label, key }) => (
          <View key={key}>
            <Text className="mb-1.5 text-xs font-medium text-muted-foreground">{label}</Text>
            <View
              className="flex-row items-center rounded-xl border bg-input px-4 py-3"
              style={{ gap: 8, borderColor: errs[key] ? colors.destructive : colors.border }}
            >
              <Phone size={14} color={colors.mutedForeground} />
              <Text className="text-sm text-foreground">+998</Text>
              <TextInput
                keyboardType="number-pad"
                placeholder="XX XXX XX XX"
                placeholderTextColor={colors.mutedForeground}
                value={fmtLocalPhone(draftVal[key])}
                onChangeText={(v) => {
                  onChange({ [key]: localPhone(v) });
                  clearErr(key);
                }}
                className="flex-1 text-sm text-foreground"
              />
            </View>
            {errs[key] ? (
              <View className="mt-1 flex-row items-center" style={{ gap: 4 }}>
                <AlertCircle size={10} color={colors.destructive} />
                <Text style={{ fontSize: 12, color: colors.destructive }}>{errs[key]}</Text>
              </View>
            ) : null}
          </View>
        ))}

        {addressFields.map(({ label, key, icon: Icon }) => (
          <View key={key}>
            <Text className="mb-1.5 text-xs font-medium text-muted-foreground">{label}</Text>
            <View
              className="flex-row items-center rounded-xl border bg-input px-4 py-3"
              style={{ gap: 12, borderColor: errs[key] ? colors.destructive : colors.border }}
            >
              <Icon size={14} color={colors.mutedForeground} />
              <TextInput
                placeholder="Ko'cha, uy raqami"
                placeholderTextColor={colors.mutedForeground}
                value={draftVal[key]}
                onChangeText={(v) => {
                  onChange({ [key]: v });
                  clearErr(key);
                }}
                className="flex-1 text-sm text-foreground"
              />
            </View>
            {errs[key] ? (
              <View className="mt-1 flex-row items-center" style={{ gap: 4 }}>
                <AlertCircle size={10} color={colors.destructive} />
                <Text style={{ fontSize: 12, color: colors.destructive }}>{errs[key]}</Text>
              </View>
            ) : null}
          </View>
        ))}

        <View>
          <Text className="mb-1.5 text-xs font-medium text-muted-foreground">{t("commentOptional")}</Text>
          <TextInput
            multiline
            numberOfLines={2}
            placeholder={t("commentPlaceholder")}
            placeholderTextColor={colors.mutedForeground}
            value={draft.comment}
            onChangeText={(v) => onChange({ comment: v })}
            className="rounded-xl border border-border bg-input px-4 py-3 text-sm text-foreground"
            style={{ minHeight: 64, textAlignVertical: "top" }}
          />
        </View>
      </ScrollView>
      <View className="border-t border-border p-4">
        <PrimaryButton
          label={t("nextBtn")}
          onPress={() => {
            if (validate()) onNext();
          }}
        />
      </View>
    </View>
  );
}
