import { useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { AlertCircle, Lock } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { updateDriverProfile } from "@/api/driver.api";
import type { UiDriverData } from "@/data/driver";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton } from "@/components/buttons";

export function DriverEditProfile({
  data,
  onBack,
  onSaved,
}: {
  data: UiDriverData;
  onBack: () => void;
  onSaved: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const locked = data.status === "approved"; // vehicle details locked after approval
  const [fullName, setFullName] = useState(data.name);
  const [model, setModel] = useState(data.car.model === "—" ? "" : data.car.model);
  const [color, setColor] = useState(data.car.color === "—" ? "" : data.car.color);
  const [plate, setPlate] = useState(data.car.plate === "—" ? "" : data.car.plate);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setErr("");
    try {
      await updateDriverProfile(
        locked
          ? { full_name: fullName || null }
          : { full_name: fullName || null, car_model: model || null, car_color: color || null, plate_number: plate || null },
      );
      onSaved();
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
      setSaving(false);
    }
  }

  const fields = [
    { label: t("fullName"), value: fullName, set: setFullName, editable: true },
    { label: t("carModel"), value: model, set: setModel, editable: !locked },
    { label: t("carColor"), value: color, set: setColor, editable: !locked },
    { label: t("plateNumber"), value: plate, set: setPlate, editable: !locked },
  ];

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("editProfile")} />
      <ScrollView contentContainerClassName="p-4 gap-4">
        {locked ? (
          <View className="flex-row items-start rounded-xl border border-border bg-secondary px-3 py-2.5" style={{ gap: 8 }}>
            <Lock size={13} color={colors.mutedForeground} />
            <Text className="flex-1 text-xs leading-relaxed text-muted-foreground">{t("vehicleLockedNote")}</Text>
          </View>
        ) : null}
        {fields.map(({ label, value, set, editable }) => (
          <View key={label}>
            <View className="mb-1.5 flex-row items-center" style={{ gap: 4 }}>
              <Text className="text-xs text-muted-foreground">{label}</Text>
              {!editable ? <Lock size={10} color={colors.mutedForeground} /> : null}
            </View>
            <TextInput
              value={value}
              editable={editable}
              onChangeText={set}
              placeholderTextColor={colors.mutedForeground}
              className="rounded-xl border border-border bg-input px-4 py-3 text-sm text-foreground"
              style={{ opacity: editable ? 1 : 0.6 }}
            />
          </View>
        ))}
        {err ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
          </View>
        ) : null}
        <PrimaryButton label={t("saveChanges")} onPress={save} loading={saving} />
      </ScrollView>
    </View>
  );
}
