import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { AlertCircle } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { getUzbekErrorMessage } from "@/utils/errors";
import { createDriverRoute } from "@/api/driver.api";
import { useCities, useDistricts } from "@/data/cities";
import { BackHeader } from "@/components/primitives";
import { PrimaryButton } from "@/components/buttons";
import { SelectField, type SelectOption } from "@/components/SelectField";

export function DriverAddRoute({ onBack, onSaved }: { onBack: () => void; onSaved: () => void }) {
  const { t } = useT();
  const { colors } = useTheme();
  const { cities } = useCities();
  const [fromCity, setFromCity] = useState<number | "">("");
  const [toCity, setToCity] = useState<number | "">("");
  const [fromDist, setFromDist] = useState<number | "">("");
  const [toDist, setToDist] = useState<number | "">("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  const fromCityObj = cities.find((c) => c.id === fromCity);
  const toCityObj = cities.find((c) => c.id === toCity);
  const { districts: fromDistricts } = useDistricts(fromCityObj?.dist ? fromCity || null : null);
  const { districts: toDistricts } = useDistricts(toCityObj?.dist ? toCity || null : null);

  const cityOpts: SelectOption[] = cities.map((c) => ({ value: c.id, label: c.uz }));
  const fromDistOpts: SelectOption[] = fromDistricts.map((d) => ({ value: d.id, label: d.name_uz }));
  const toDistOpts: SelectOption[] = toDistricts.map((d) => ({ value: d.id, label: d.name_uz }));

  async function save() {
    if (!fromCity || !toCity) {
      setErr(t("phoneError"));
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await createDriverRoute({
        from_city_id: Number(fromCity),
        to_city_id: Number(toCity),
        from_district_id: fromDist ? Number(fromDist) : null,
        to_district_id: toDist ? Number(toDist) : null,
      });
      onSaved();
    } catch (e) {
      setErr(getUzbekErrorMessage(e));
      setSaving(false);
    }
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("addRoute")} />
      <ScrollView contentContainerClassName="p-4 gap-4">
        <SelectField
          label={t("fromCity")}
          value={fromCity}
          options={cityOpts}
          placeholder={t("selectCity")}
          onChange={(v) => {
            setFromCity(Number(v));
            setFromDist("");
          }}
        />
        {fromCityObj?.dist && fromDistOpts.length > 0 ? (
          <SelectField label={t("fromDistrict")} value={fromDist} options={fromDistOpts} placeholder="—" onChange={(v) => setFromDist(Number(v))} />
        ) : null}

        <SelectField
          label={t("toCity")}
          value={toCity}
          options={cityOpts}
          placeholder={t("selectCity")}
          onChange={(v) => {
            setToCity(Number(v));
            setToDist("");
          }}
        />
        {toCityObj?.dist && toDistOpts.length > 0 ? (
          <SelectField label={t("toDistrict")} value={toDist} options={toDistOpts} placeholder="—" onChange={(v) => setToDist(Number(v))} />
        ) : null}

        {err ? (
          <View className="flex-row items-center" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{err}</Text>
          </View>
        ) : null}
      </ScrollView>
      <View className="border-t border-border p-4">
        <PrimaryButton label={t("saveRoute")} onPress={save} loading={saving} />
      </View>
    </View>
  );
}
