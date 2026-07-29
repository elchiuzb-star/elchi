import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { AlertCircle, Camera, CheckCircle2 } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { uploadFile, type RNFile } from "@/api/files.api";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton } from "@/components/buttons";
import { CARGO_TYPES, type OrderDraft } from "@/core/order";

export function CargoPhotoScreen({
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
  const { t, lang } = useT();
  const { colors } = useTheme();
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");

  async function pickAndUpload() {
    setErr("");
    try {
      // Per SDK 57 docs: no permission request is needed to launch the image library.
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        quality: 0.7,
      });
      if (result.canceled || !result.assets?.[0]) return;
      const asset = result.assets[0];
      const file: RNFile = {
        uri: asset.uri,
        name: asset.fileName || `cargo_${Date.now()}.jpg`,
        type: asset.mimeType || "image/jpeg",
        size: asset.fileSize,
      };
      setUploading(true);
      const res = await uploadFile(file, "cargo_photo");
      onChange({ hasPhoto: true, cargoPhotoUrl: res.file_url });
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
    } finally {
      setUploading(false);
    }
  }

  function next() {
    if (!draft.cargoType) {
      setErr(lang === "ru" ? "Выберите тип отправления" : lang === "en" ? "Select a parcel type" : "Jo'natma turini tanlang");
      return;
    }
    setErr("");
    onNext();
  }

  const typeLabel = lang === "ru" ? "Тип отправления" : lang === "en" ? "Parcel type" : "Jo'natma turi";
  const photoOptional = lang === "ru" ? "необязательно" : lang === "en" ? "optional" : "ixtiyoriy";

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("cargoPhotoTitle")} />
      <ScrollView contentContainerClassName="p-4 gap-5">
        <View>
          <Text className="mb-2 text-xs font-medium text-muted-foreground">{typeLabel} *</Text>
          <View className="flex-row flex-wrap" style={{ gap: 8 }}>
            {CARGO_TYPES.map((ct) => {
              const act = draft.cargoType === ct.id;
              const Icon = ct.icon;
              return (
                <Pressable
                  key={ct.id}
                  onPress={() => {
                    onChange({ cargoType: ct.id });
                    if (err) setErr("");
                  }}
                  className="items-center rounded-xl border py-3"
                  style={{
                    width: "31.5%",
                    gap: 6,
                    borderColor: act ? colors.primary : colors.border,
                    backgroundColor: act ? `${colors.primary}1A` : colors.card,
                  }}
                >
                  <Icon size={18} color={act ? colors.primary : colors.mutedForeground} />
                  <Text
                    className="text-center text-[11px] font-medium"
                    style={{ color: act ? colors.primary : colors.foreground }}
                  >
                    {lang === "ru" ? ct.ru : lang === "en" ? ct.en : ct.uz}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View>
          <Text className="mb-2 text-xs font-medium text-muted-foreground">
            {t("cargoPhotoTitle")} · {photoOptional}
          </Text>
          {draft.hasPhoto ? (
            <View
              className="flex-row items-center rounded-2xl border p-4"
              style={{ gap: 8, borderColor: `${colors.success}4D`, backgroundColor: `${colors.success}10` }}
            >
              <CheckCircle2 size={16} color={colors.success} />
              <Text className="flex-1 text-sm font-medium" style={{ color: colors.success }}>
                {t("photoUploaded")}
              </Text>
              <Pressable
                onPress={() => onChange({ hasPhoto: false, cargoPhotoUrl: null })}
                className="rounded-lg border border-border px-2.5 py-1"
              >
                <Text className="text-xs text-muted-foreground">{t("changePhoto")}</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable
              onPress={pickAndUpload}
              disabled={uploading}
              className="items-center rounded-2xl border-2 border-dashed border-border bg-secondary p-8"
              style={{ gap: 12 }}
            >
              {uploading ? (
                <ActivityIndicator color={colors.primary} />
              ) : (
                <>
                  <View
                    className="items-center justify-center rounded-2xl"
                    style={{ width: 56, height: 56, backgroundColor: `${colors.primary}1A` }}
                  >
                    <Camera size={26} color={colors.primary} />
                  </View>
                  <View className="items-center">
                    <Text className="text-sm font-semibold text-foreground">{t("uploadPhoto")}</Text>
                    <Text className="mt-1 text-xs text-muted-foreground">{t("photoDesc")}</Text>
                  </View>
                </>
              )}
            </Pressable>
          )}
        </View>

        {err ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
          </View>
        ) : null}
      </ScrollView>
      <View className="border-t border-border p-4">
        <PrimaryButton label={t("nextBtn")} onPress={next} />
      </View>
    </View>
  );
}
