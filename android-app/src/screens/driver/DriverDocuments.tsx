import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { AlertCircle, CheckCircle2, Clock, Plus } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { getDriverDocuments, uploadDriverDocument } from "@/api/driver.api";
import type { RNFile } from "@/api/files.api";
import type { DriverDocument, DriverDocumentType } from "@/types/driver";
import { useAsync } from "@/data/useApi";
import { usePullRefresh } from "@/data/usePullRefresh";
import { BackHeader, StatusBadge } from "@/components/primitives";

const DRIVER_DOC_DEFS: { type: DriverDocumentType; label: string }[] = [
  { type: "passport", label: "Passport" },
  { type: "selfie", label: "Selfie" },
  { type: "license", label: "Driver License" },
  { type: "car_document", label: "Car Document" },
  { type: "car_photo", label: "Car Photo" },
];

/** Per-document UI state: what the driver has uploaded and how it was reviewed. */
type DocState = "missing" | "pending" | "approved" | "rejected";

export function DriverDocuments({ onBack, onUploaded }: { onBack: () => void; onUploaded: () => void }) {
  const { t } = useT();
  const { colors } = useTheme();
  const [busy, setBusy] = useState<DriverDocumentType | null>(null);
  const [err, setErr] = useState("");

  // Each document carries its own review status — fetch them so a freshly
  // uploaded file is reflected on its own row (not the driver-level status).
  const { data: documents, reload } = useAsync<DriverDocument[]>(() => getDriverDocuments(), []);
  const refresh = usePullRefresh(reload);
  const byType = new Map<string, DriverDocument>((documents ?? []).map((d) => [d.document_type, d]));

  // A successful reload means the server IS reachable, so a lingering
  // "can't connect" error from an earlier failed upload is now stale — clear it.
  useEffect(() => {
    if (documents) setErr("");
  }, [documents]);

  const uploadedCount = DRIVER_DOC_DEFS.filter((d) => byType.has(d.type)).length;
  const allUploaded = uploadedCount === DRIVER_DOC_DEFS.length;

  async function upload(type: DriverDocumentType) {
    setErr("");
    try {
      // Per SDK 57 docs: no permission request is needed to launch the image library.
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
      if (result.canceled || !result.assets?.[0]) return;
      const asset = result.assets[0];
      const file: RNFile = {
        uri: asset.uri,
        name: asset.fileName || `${type}_${Date.now()}.jpg`,
        type: asset.mimeType || "image/jpeg",
        size: asset.fileSize,
      };
      setBusy(type);
      await uploadDriverDocument(type, file);
      reload(); // refresh this screen so the uploaded row updates immediately
      onUploaded(); // refresh driver profile (verification status)
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("documents")} />
      <ScrollView contentContainerClassName="p-4 gap-3" refreshControl={refresh}>
        {/* Progress banner — turns positive once everything is in. */}
        <View
          className="flex-row items-center rounded-2xl border p-3"
          style={{
            gap: 8,
            borderColor: allUploaded ? `${colors.success}33` : `${colors.warning}33`,
            backgroundColor: allUploaded ? `${colors.success}0D` : `${colors.warning}0D`,
          }}
        >
          {allUploaded ? (
            <CheckCircle2 size={14} color={colors.success} />
          ) : (
            <AlertCircle size={14} color={colors.warning} />
          )}
          <Text className="flex-1 text-xs" style={{ color: allUploaded ? colors.success : colors.warning }}>
            {t("uploadAllDocs")} · {uploadedCount}/{DRIVER_DOC_DEFS.length}
          </Text>
        </View>

        {err ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
          </View>
        ) : null}

        {DRIVER_DOC_DEFS.map((doc) => {
          const existing = byType.get(doc.type);
          const state: DocState = existing ? (existing.status as DocState) : "missing";
          const Icon = state === "approved" ? CheckCircle2 : state === "pending" ? Clock : AlertCircle;
          const iconColor =
            state === "approved" ? colors.success : state === "pending" ? colors.warning : colors.destructive;

          return (
            <View key={doc.type} className="rounded-2xl border border-border bg-card p-4">
              <View className="mb-3 flex-row items-center justify-between">
                <View className="flex-row items-center" style={{ gap: 8 }}>
                  <Icon size={16} color={iconColor} />
                  <Text className="text-sm font-semibold text-foreground">{doc.label}</Text>
                </View>
                <StatusBadge status={state} />
              </View>

              {existing?.rejection_reason ? (
                <Text className="mb-2 text-xs" style={{ color: colors.destructive }}>
                  {existing.rejection_reason}
                </Text>
              ) : null}

              <Pressable
                onPress={() => upload(doc.type)}
                className="w-full flex-row items-center justify-center rounded-xl border border-dashed py-2.5 active:opacity-80"
                style={{ gap: 6, borderColor: `${colors.primary}4D`, backgroundColor: `${colors.primary}0D` }}
              >
                {busy === doc.type ? (
                  <ActivityIndicator size="small" color={colors.primary} />
                ) : (
                  <>
                    <Plus size={12} color={colors.primary} />
                    <Text className="text-xs font-medium" style={{ color: colors.primary }}>
                      {existing ? `${t("changePhoto")} · ${doc.label}` : `${t("upload")} ${doc.label}`}
                    </Text>
                  </>
                )}
              </Pressable>
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}
