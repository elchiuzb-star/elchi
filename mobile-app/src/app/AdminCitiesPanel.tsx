/**
 * Hududlar (v1 cities and districts; design "Elchi Admin" → Hududlar + overlay `city`).
 *
 * Read for every staff role that reaches the panel; create, edit and (de)activate only for admin and super_admin
 * (the v1 routes refuse the operator anyway). Deactivating never deletes: existing orders keep their region.
 * Props are unchanged (`user`), AdminApp mounts `<AdminCitiesPanel user={user} />`.
 */
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Building2, ChevronLeft, ChevronRight, Edit, Eye, MapPin, Plus, RefreshCw, ToggleLeft, X } from "./ui/icons";

import {
  activateCity,
  createCity,
  deactivateCity,
  getAdminCities,
  getAdminCityDetail,
  updateCity,
  type AdminCityFilters,
  type CityPayload,
} from "../api/admin-cities.api";
import {
  activateDistrict,
  createDistrict,
  deactivateDistrict,
  getCityDistricts,
  updateDistrict,
  type DistrictPayload,
} from "../api/admin-districts.api";
import { translate, translateDynamic } from "../i18n";
import { useT } from "../i18n/react";
import { ApiError } from "../types/api";
import type { AuthUser } from "../types/auth";
import type { City } from "../types/city";
import type { District } from "../types/district";
import { formatAdminDate, formatShortAdminDate } from "../utils/date";
import { cleanLocationText, formatCityDisplayName, formatDistrictDisplayName, hasEncodingIssue } from "../utils/locationLabels";

type Props = {
  user: AuthUser;
};

type CityForm = {
  name_uz: string;
  name_ru: string;
  region: string;
  type: "city" | "region" | "republic";
  requires_district: boolean;
  display_order: string;
  is_active: boolean;
};

type DistrictForm = {
  city_id: string;
  name_uz: string;
  name_ru: string;
  display_order: string;
  is_active: boolean;
};

const emptyCityForm: CityForm = {
  name_uz: "",
  name_ru: "",
  region: "",
  type: "region",
  requires_district: true,
  display_order: "1000",
  is_active: true,
};

const emptyDistrictForm: DistrictForm = {
  city_id: "",
  name_uz: "",
  name_ru: "",
  display_order: "1000",
  is_active: true,
};

function typeLabel(type?: string | null): string {
  if (type === "city" || type === "region" || type === "republic") return translate(`admin.cities.type.${type}`);
  return type || "-";
}

function activeLabel(active?: boolean | null): string {
  return active ? translate("admin.cities.active") : translate("admin.cities.inactive");
}

/** v1 location error codes in the active language (utils/locationLabels keeps the Uzbek-only v1 copy). */
function locationError(code?: string): string {
  return (code ? translateDynamic(`admin.cities.err.${code}`) : undefined) ?? translate("admin.cities.err.fallback");
}

function Button(props: { children: React.ReactNode; onClick?: () => void; disabled?: boolean; tone?: "neutral" | "primary" | "danger" }) {
  const tone = props.tone ?? "neutral";
  const className =
    tone === "primary"
      ? "border-primary bg-primary text-primary-foreground hover:bg-primary"
      : tone === "danger"
        ? "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/25"
        : "border-border bg-card text-secondary-foreground hover:bg-muted";
  return (
    <button
      type="button"
      disabled={props.disabled}
      onClick={props.onClick}
      className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold transition ${className} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

function Badge({ children, className }: { children: React.ReactNode; className: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${className}`}>{children}</span>;
}

function activeBadge(active?: boolean) {
  return <Badge className={active ? "border-success/25 bg-success/12 text-success" : "border-border bg-muted text-secondary-foreground"}>{activeLabel(active)}</Badge>;
}

function typeBadge(type?: string) {
  return <Badge className="border-primary/20 bg-accent text-primary">{typeLabel(type)}</Badge>;
}

function requiredBadge(value?: boolean) {
  return (
    <Badge className={value ? "border-warning/28 bg-warning/14 text-warning" : "border-border bg-muted text-secondary-foreground"}>
      {value ? translate("admin.cities.required") : translate("admin.cities.notRequired")}
    </Badge>
  );
}

function encodingBadge() {
  return <Badge className="border-warning/28 bg-warning/14 text-warning">{translate("admin.cities.encoding")}</Badge>;
}

function Input(props: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <input
        value={props.value}
        type={props.type ?? "text"}
        placeholder={props.placeholder}
        aria-label={props.label}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
      />
    </label>
  );
}

function Select(props: { label: string; value: string; onChange: (value: string) => void; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <select
        value={props.value}
        aria-label={props.label}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
      >
        {props.children}
      </select>
    </label>
  );
}

function CheckField(props: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex h-10 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground">
      <input type="checkbox" checked={props.checked} onChange={(event) => props.onChange(event.target.checked)} />
      {props.label}
    </label>
  );
}

function ModalShell(props: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-foreground/40 p-4">
      <section role="dialog" aria-modal="true" aria-label={props.title} className="w-full max-w-lg rounded-[12px] border border-border bg-card shadow-xl">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-base font-bold text-foreground">{props.title}</h3>
          <button onClick={props.onClose} className="el-press rounded-[10px] p-1 text-muted-foreground hover:bg-muted" aria-label={translate("common.close")}>
            <X size={18} />
          </button>
        </header>
        {props.children}
      </section>
    </div>
  );
}

function DetailItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-[12px] border border-border bg-card p-3">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-1 text-sm font-semibold text-foreground">{children || "-"}</div>
    </div>
  );
}

function cityFormToPayload(form: CityForm): CityPayload {
  return {
    name_uz: form.name_uz.trim(),
    name_ru: form.name_ru.trim() || null,
    region: form.region.trim() || null,
    type: form.type,
    requires_district: form.requires_district,
    display_order: Number(form.display_order || 1000),
    is_active: form.is_active,
  };
}

function districtFormToPayload(form: DistrictForm): DistrictPayload {
  return {
    city_id: Number(form.city_id),
    name_uz: form.name_uz.trim(),
    name_ru: form.name_ru.trim() || null,
    display_order: Number(form.display_order || 1000),
    is_active: form.is_active,
  };
}

function CityModal(props: {
  title: string;
  form: CityForm;
  busy: boolean;
  duplicate: boolean;
  onChange: (form: CityForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const t = useT();
  const valid = props.form.name_uz.trim().length > 0 && !props.duplicate;
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        {props.duplicate && <p className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{t("admin.cities.duplicate")}</p>}
        <div className="grid gap-3 md:grid-cols-2">
          <Input label={t("admin.cities.nameUz")} value={props.form.name_uz} onChange={(name_uz) => props.onChange({ ...props.form, name_uz })} />
          <Input label={t("admin.cities.nameRu")} value={props.form.name_ru} onChange={(name_ru) => props.onChange({ ...props.form, name_ru })} />
          <Input label={t("admin.cities.region")} value={props.form.region} onChange={(region) => props.onChange({ ...props.form, region })} />
          <Select label={t("admin.cities.type")} value={props.form.type} onChange={(type) => props.onChange({ ...props.form, type: type as CityForm["type"] })}>
            <option value="city">{t("admin.cities.type.city")}</option>
            <option value="region">{t("admin.cities.type.region")}</option>
            <option value="republic">{t("admin.cities.type.republic")}</option>
          </Select>
          <Input label={t("admin.cities.displayOrder")} value={props.form.display_order} type="number" onChange={(display_order) => props.onChange({ ...props.form, display_order })} />
          <div className="grid gap-2 pt-6">
            <CheckField label={t("admin.cities.requiresDistrict")} checked={props.form.requires_district} onChange={(requires_district) => props.onChange({ ...props.form, requires_district })} />
            <CheckField label={t("admin.cities.active")} checked={props.form.is_active} onChange={(is_active) => props.onChange({ ...props.form, is_active })} />
          </div>
        </div>
        <div className="rounded-[10px] border border-primary/20 bg-accent p-3 text-xs text-primary">{t("admin.cities.tashkentHint")}</div>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button tone="primary" disabled={props.busy || !valid} onClick={props.onSubmit}>
            {t("common.save")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function DistrictModal(props: {
  title: string;
  form: DistrictForm;
  cities: City[];
  busy: boolean;
  duplicate: boolean;
  onChange: (form: DistrictForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const t = useT();
  const valid = Number(props.form.city_id) > 0 && props.form.name_uz.trim().length > 0 && !props.duplicate;
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        {props.duplicate && <p className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{t("admin.cities.districtDuplicate")}</p>}
        <Select label={t("admin.cities.cityField")} value={props.form.city_id} onChange={(city_id) => props.onChange({ ...props.form, city_id })}>
          <option value="">{t("admin.cities.chooseCity")}</option>
          {props.cities.map((city) => (
            <option key={city.id} value={city.id}>
              {formatCityDisplayName(city)}
            </option>
          ))}
        </Select>
        <div className="grid gap-3 md:grid-cols-2">
          <Input label={t("admin.cities.nameUz")} value={props.form.name_uz} onChange={(name_uz) => props.onChange({ ...props.form, name_uz })} />
          <Input label={t("admin.cities.nameRu")} value={props.form.name_ru} onChange={(name_ru) => props.onChange({ ...props.form, name_ru })} />
          <Input label={t("admin.cities.displayOrder")} value={props.form.display_order} type="number" onChange={(display_order) => props.onChange({ ...props.form, display_order })} />
          <div className="pt-6">
            <CheckField label={t("admin.cities.active")} checked={props.form.is_active} onChange={(is_active) => props.onChange({ ...props.form, is_active })} />
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button tone="primary" disabled={props.busy || !valid} onClick={props.onSubmit}>
            {t("common.save")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function ConfirmModal(props: { title: string; message: string; submitLabel: string; tone?: "primary" | "danger"; busy: boolean; onClose: () => void; onConfirm: () => void }) {
  const t = useT();
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <p className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm font-medium text-warning">{props.message}</p>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button tone={props.tone ?? "danger"} disabled={props.busy} onClick={props.onConfirm}>
            {props.submitLabel}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function citySearchText(city: City): string {
  return [city.name_uz, city.name_ru, city.region, city.type].filter(Boolean).join(" ").toLowerCase();
}

type DrawerTab = "info" | "districts" | "tariffs" | "orders" | "audit";

function CityDrawer(props: {
  city: City;
  districts: District[];
  districtError?: string | null;
  busy: boolean;
  canMutate: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onEditCity: () => void;
  onToggleCity: () => void;
  onAddDistrict: () => void;
  onEditDistrict: (district: District) => void;
  onToggleDistrict: (district: District) => void;
}) {
  const t = useT();
  const [tab, setTab] = useState<DrawerTab>("info");
  const city = props.city;
  const missingDistricts = Boolean(city.requires_district) && !props.districts.length;
  const sub = city.requires_district ? t("admin.cities.drawerSub", { type: typeLabel(city.type) }) : typeLabel(city.type);
  return (
    <>
      {/* The scrim is decoration: it closes the drawer as a convenience, and the drawer itself carries the
          dialog semantics and a real close button. */}
      <div className="fixed inset-0 z-50 bg-foreground/30" role="presentation" onClick={props.onClose} />
      <aside role="dialog" aria-modal="true" aria-label={formatCityDisplayName(city)} className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-3xl flex-col border-l border-border bg-background shadow-2xl">
        <header className="border-b border-border bg-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-foreground">{formatCityDisplayName(city)}</h2>
                {activeBadge(city.is_active)}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{sub}</p>
              <p className="text-xs text-muted-foreground">
                {t("admin.cities.createdUpdated", { created: formatAdminDate(city.created_at), updated: formatAdminDate(city.updated_at) })}
              </p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button onClick={props.onRefresh}>
                <RefreshCw size={15} /> {t("support.refresh")}
              </Button>
              <Button onClick={props.onClose}>
                <X size={15} /> {t("common.close")}
              </Button>
            </div>
          </div>
          {props.canMutate && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button disabled={props.busy} onClick={props.onEditCity}>
                <Edit size={14} /> {t("admin.cities.edit")}
              </Button>
              <Button disabled={props.busy} tone={city.is_active ? "danger" : "primary"} onClick={props.onToggleCity}>
                {city.is_active ? t("admin.cities.deactivate") : t("admin.cities.activate")}
              </Button>
            </div>
          )}
          <div className="mt-4 flex gap-2 overflow-x-auto border-b border-border" role="tablist">
            {(["info", "districts", "tariffs", "orders", "audit"] as DrawerTab[]).map((key) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`el-press shrink-0 border-b-2 px-3 py-2 text-sm font-semibold ${tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
              >
                {t(`admin.cities.drawer.${key}`)}
              </button>
            ))}
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {missingDistricts && tab !== "districts" && (
            <div className="mb-4 rounded-[12px] border border-warning/28 bg-warning/14 p-3 text-sm font-medium text-warning">{t("admin.cities.needsDistrictWarn")}</div>
          )}
          {tab === "info" && (
            <section className="grid gap-3 md:grid-cols-3">
              <DetailItem label={t("admin.cities.nameUz")}>{cleanLocationText(city.name_uz)}</DetailItem>
              <DetailItem label={t("admin.cities.nameRu")}>{hasEncodingIssue(city.name_ru) ? encodingBadge() : cleanLocationText(city.name_ru)}</DetailItem>
              <DetailItem label={t("admin.cities.region")}>{cleanLocationText(city.region)}</DetailItem>
              <DetailItem label={t("admin.cities.type")}>{typeBadge(city.type)}</DetailItem>
              <DetailItem label={t("admin.cities.requiresDistrict")}>{requiredBadge(city.requires_district)}</DetailItem>
              <DetailItem label={t("admin.cities.active")}>{activeBadge(city.is_active)}</DetailItem>
              <DetailItem label={t("admin.cities.displayOrder")}>{city.display_order ?? "-"}</DetailItem>
              <DetailItem label={t("admin.cities.districts")}>
                {t("admin.cities.activeOfTotal", { active: city.active_districts_count ?? 0, total: city.districts_count ?? 0 })}
              </DetailItem>
            </section>
          )}
          {tab === "districts" && (
            <section className="grid gap-4">
              {missingDistricts && <div className="rounded-[12px] border border-warning/28 bg-warning/14 p-4 text-sm font-medium text-warning">{t("admin.cities.needsDistrictWarn")}</div>}
              <div className="flex justify-between gap-3">
                <div>
                  <h3 className="font-bold text-foreground">{t("admin.cities.districts")}</h3>
                  <p className="text-sm text-muted-foreground">{t("admin.cities.districtsHint")}</p>
                </div>
                {props.canMutate && (
                  <Button tone="primary" onClick={props.onAddDistrict}>
                    <Plus size={15} /> {t("admin.cities.addDistrict")}
                  </Button>
                )}
              </div>
              {props.districtError && <p className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{props.districtError}</p>}
              <div className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card">
                <div className="min-w-0 overflow-x-auto">
                  <table className="w-full min-w-[620px] text-left text-sm">
                    <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                      <tr>
                        {[t("admin.cities.nameUz"), t("admin.cities.nameRu"), t("admin.cities.active"), t("admin.cities.created"), ""].map((label, index) => (
                          <th key={index} className="px-4 py-3 font-semibold">
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-muted">
                      {props.districts.length ? (
                        props.districts.map((district) => (
                          <tr key={district.id}>
                            <td className="px-4 py-3 font-semibold text-foreground">{formatDistrictDisplayName(district)}</td>
                            <td className="px-4 py-3">{hasEncodingIssue(district.name_ru) ? encodingBadge() : cleanLocationText(district.name_ru)}</td>
                            <td className="px-4 py-3">{activeBadge(district.is_active)}</td>
                            <td className="px-4 py-3">{formatShortAdminDate(district.created_at)}</td>
                            <td className="px-4 py-3">
                              {props.canMutate && (
                                <div className="flex flex-wrap gap-2">
                                  <Button onClick={() => props.onEditDistrict(district)}>
                                    <Edit size={14} /> {t("admin.cities.edit")}
                                  </Button>
                                  <Button tone={district.is_active ? "danger" : "primary"} onClick={() => props.onToggleDistrict(district)}>
                                    {district.is_active ? t("admin.cities.deactivate") : t("admin.cities.activate")}
                                  </Button>
                                </div>
                              )}
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} className="px-4 py-10 text-center text-muted-foreground">
                            {t("admin.cities.noDistrictsFound")}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}
          {tab === "tariffs" && <div className="rounded-[12px] border border-border bg-card p-5 text-sm text-secondary-foreground">{t("admin.cities.tariffsElsewhere")}</div>}
          {tab === "orders" && <div className="rounded-[12px] border border-border bg-card p-5 text-sm text-secondary-foreground">{t("admin.cities.ordersElsewhere")}</div>}
          {tab === "audit" && <div className="rounded-[12px] border border-border bg-card p-5 text-sm text-secondary-foreground">{t("admin.cities.auditElsewhere")}</div>}
        </div>
      </aside>
    </>
  );
}

export function AdminCitiesPanel({ user }: Props) {
  const t = useT();
  const [cities, setCities] = useState<City[]>([]);
  const [selectedCity, setSelectedCity] = useState<City | null>(null);
  const [districts, setDistricts] = useState<District[]>([]);
  const [filters, setFilters] = useState<AdminCityFilters>({ page: 1, limit: 20 });
  const [draftFilters, setDraftFilters] = useState<AdminCityFilters>({ page: 1, limit: 20 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [districtError, setDistrictError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [cityModal, setCityModal] = useState<{ mode: "create" | "edit"; city?: City; form: CityForm } | null>(null);
  const [districtModal, setDistrictModal] = useState<{ mode: "create" | "edit"; district?: District; form: DistrictForm } | null>(null);
  const [confirm, setConfirm] = useState<{ title: string; message: string; submit: string; tone?: "primary" | "danger"; action: () => Promise<unknown> } | null>(null);
  const canMutate = user.role === "admin" || user.role === "super_admin";

  async function loadCities(nextFilters = filters) {
    setBusy(true);
    setError(null);
    try {
      const response = await getAdminCities(nextFilters);
      setCities(response.items ?? []);
      setTotal(response.pagination?.total ?? response.items.length);
      setTotalPages(response.pagination?.total_pages ?? 1);
    } catch (err) {
      setError(err instanceof ApiError ? locationError(err.code) : t("admin.cities.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function loadDistricts(cityId: number) {
    setDistrictError(null);
    try {
      const response = await getCityDistricts(cityId, { limit: 100 });
      setDistricts(response.items ?? []);
    } catch (err) {
      setDistrictError(err instanceof ApiError ? locationError(err.code) : t("admin.cities.districtsFailed"));
    }
  }

  async function openCity(cityId: number) {
    setBusy(true);
    setError(null);
    try {
      const city = await getAdminCityDetail(cityId);
      setSelectedCity(city);
      await loadDistricts(city.id);
    } catch (err) {
      setError(err instanceof ApiError ? locationError(err.code) : t("admin.cities.cityFailed"));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadCities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((draftFilters.search ?? "") !== (filters.search ?? "")) {
        const next = { ...filters, search: draftFilters.search, page: 1 };
        setFilters(next);
        void loadCities(next);
      }
    }, 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftFilters.search]);

  const visibleCities = useMemo(() => {
    const q = (filters.search ?? "").trim().toLowerCase();
    return cities.filter((city) => {
      if (q && !citySearchText(city).includes(q)) return false;
      if (filters.type && city.type !== filters.type) return false;
      if (filters.requires_district === "required" && city.requires_district !== true) return false;
      if (filters.requires_district === "not_required" && city.requires_district !== false) return false;
      if (filters.has_districts === "yes" && !(Number(city.districts_count ?? 0) > 0)) return false;
      if (filters.has_districts === "no" && Number(city.districts_count ?? 0) > 0) return false;
      return true;
    });
  }, [cities, filters]);

  const summary = useMemo(() => {
    const totalDistricts = visibleCities.reduce((sum, city) => sum + Number(city.districts_count ?? 0), 0);
    return [
      [t("admin.cities.total"), visibleCities.length, Building2, false],
      [t("admin.cities.active"), visibleCities.filter((city) => city.is_active).length, ToggleLeft, false],
      [t("admin.cities.inactive"), visibleCities.filter((city) => !city.is_active).length, X, false],
      [t("admin.cities.requiresDistrict"), visibleCities.filter((city) => city.requires_district).length, MapPin, false],
      [t("admin.cities.totalDistricts"), totalDistricts, MapPin, false],
      [t("admin.cities.noDistricts"), visibleCities.filter((city) => city.requires_district && !city.districts_count).length, AlertTriangle, true],
    ] as const;
  }, [visibleCities, t]);

  function applyFilters() {
    const next = { ...draftFilters, page: 1 };
    setFilters(next);
    void loadCities(next);
  }

  function clearFilters() {
    const next = { page: 1, limit: filters.limit ?? 20 };
    setDraftFilters(next);
    setFilters(next);
    void loadCities(next);
  }

  function setPage(page: number) {
    const next = { ...filters, page };
    setFilters(next);
    setDraftFilters((current) => ({ ...current, page }));
    void loadCities(next);
  }

  async function afterCityChange(cityId?: number) {
    await loadCities();
    if (cityId ?? selectedCity?.id) await openCity(cityId ?? selectedCity!.id);
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? locationError(err.code) : err instanceof Error ? err.message : t("admin.cities.err.fallback"));
    } finally {
      setBusy(false);
    }
  }

  function editCity(city: City) {
    setCityModal({
      mode: "edit",
      city,
      form: {
        name_uz: city.name_uz,
        name_ru: city.name_ru ?? "",
        region: city.region ?? "",
        type: (city.type as CityForm["type"]) || "region",
        requires_district: city.requires_district ?? true,
        display_order: String(city.display_order ?? 1000),
        is_active: city.is_active ?? true,
      },
    });
  }

  function toggleCity(city: City) {
    setConfirm({
      title: city.is_active ? t("admin.cities.confirmDeactivate") : t("admin.cities.confirmActivate"),
      message: city.is_active ? t("admin.cities.deactivateEffect") : t("admin.cities.activateEffect"),
      submit: city.is_active ? t("admin.cities.deactivate") : t("admin.cities.activate"),
      tone: city.is_active ? "danger" : "primary",
      action: async () => {
        if (city.is_active) await deactivateCity(city.id);
        else await activateCity(city.id);
        await afterCityChange(city.id);
      },
    });
  }

  const cityDuplicate = cityModal
    ? cities.some((city) => city.name_uz.trim().toLowerCase() === cityModal.form.name_uz.trim().toLowerCase() && city.id !== cityModal.city?.id)
    : false;
  const districtDuplicate = districtModal
    ? districts.some((district) => district.name_uz.trim().toLowerCase() === districtModal.form.name_uz.trim().toLowerCase() && district.id !== districtModal.district?.id)
    : false;

  const columns = ["ID", t("admin.cities.nameUz"), t("admin.cities.nameRu"), t("admin.cities.region"), t("admin.cities.type"), t("admin.cities.districts"), t("admin.cities.active"), ""];

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.cities.title")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("admin.cities.subtitle")}</p>
        </div>
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void loadCities()}>
            <RefreshCw size={16} /> {t("support.refresh")}
          </Button>
          {canMutate && (
            <Button tone="primary" onClick={() => setCityModal({ mode: "create", form: emptyCityForm })}>
              <Plus size={16} /> {t("admin.cities.add")}
            </Button>
          )}
        </div>
      </section>

      {error && <div role="alert" className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">{error}</div>}
      {!canMutate && <div className="rounded-[12px] border border-border bg-card px-4 py-3 text-sm font-medium text-secondary-foreground">{t("admin.cities.readOnly")}</div>}

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {summary.map(([label, value, Icon, warn]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
              <Icon size={16} className="text-muted-foreground" />
            </div>
            <p className={`mt-3 text-2xl font-bold ${warn && value > 0 ? "text-warning" : "text-foreground"}`}>{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 lg:grid-cols-4 xl:grid-cols-6">
          <Input label={t("location.search")} value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder={t("admin.cities.searchPh")} />
          <Select label={t("admin.cities.type")} value={draftFilters.type ?? ""} onChange={(type) => setDraftFilters({ ...draftFilters, type })}>
            <option value="">{t("admin.cities.all")}</option>
            <option value="city">{t("admin.cities.type.city")}</option>
            <option value="region">{t("admin.cities.type.region")}</option>
            <option value="republic">{t("admin.cities.type.republic")}</option>
          </Select>
          <Select label={t("admin.cities.activity")} value={draftFilters.is_active ?? ""} onChange={(is_active) => setDraftFilters({ ...draftFilters, is_active })}>
            <option value="">{t("admin.cities.all")}</option>
            <option value="active">{t("admin.cities.active")}</option>
            <option value="inactive">{t("admin.cities.inactive")}</option>
          </Select>
          <Select label={t("admin.cities.requiresDistrict")} value={draftFilters.requires_district ?? ""} onChange={(requires_district) => setDraftFilters({ ...draftFilters, requires_district })}>
            <option value="">{t("admin.cities.any")}</option>
            <option value="required">{t("admin.cities.required")}</option>
            <option value="not_required">{t("admin.cities.notRequired")}</option>
          </Select>
          <Select label={t("admin.cities.hasDistricts")} value={draftFilters.has_districts ?? ""} onChange={(has_districts) => setDraftFilters({ ...draftFilters, has_districts })}>
            <option value="">{t("admin.cities.any")}</option>
            <option value="yes">{t("admin.cities.hasDistricts")}</option>
            <option value="no">{t("admin.cities.noDistrictsRow")}</option>
          </Select>
          <Select label={t("admin.cities.limit")} value={String(draftFilters.limit ?? 20)} onChange={(limit) => setDraftFilters({ ...draftFilters, limit: Number(limit), page: 1 })}>
            {[10, 20, 50, 100].map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button onClick={clearFilters}>{t("admin.cities.clearFilters")}</Button>
          <Button tone="primary" disabled={busy} onClick={applyFilters}>
            {t("admin.cities.applyFilters")}
          </Button>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-left text-sm">
            <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                {columns.map((label, index) => (
                  <th key={index} className="px-4 py-3 font-semibold">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {busy && !cities.length ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <tr key={index}>
                    <td colSpan={8} className="px-4 py-3">
                      <div className="h-8 animate-pulse rounded bg-background" />
                    </td>
                  </tr>
                ))
              ) : visibleCities.length ? (
                visibleCities.map((city) => {
                  const count = Number(city.districts_count ?? 0);
                  return (
                    <tr key={city.id} className="cursor-pointer hover:bg-muted/40" onClick={() => void openCity(city.id)}>
                      <td className="px-4 py-3 font-semibold text-secondary-foreground">{city.id}</td>
                      <td className="px-4 py-3 font-bold text-foreground">{cleanLocationText(city.name_uz)}</td>
                      <td className="px-4 py-3">{hasEncodingIssue(city.name_ru) ? encodingBadge() : cleanLocationText(city.name_ru)}</td>
                      <td className="px-4 py-3">{hasEncodingIssue(city.region) ? encodingBadge() : cleanLocationText(city.region)}</td>
                      <td className="px-4 py-3">{typeLabel(city.type)}</td>
                      <td className={`whitespace-nowrap px-4 py-3 ${count === 0 && city.requires_district ? "font-semibold text-warning" : ""}`}>
                        {count > 0 ? t("admin.cities.districtCount", { count }) : t("admin.cities.noDistrictsRow")}
                      </td>
                      <td className="px-4 py-3">{activeBadge(city.is_active)}</td>
                      <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                        <button type="button" className="inline-flex items-center gap-1 text-sm font-semibold text-primary" onClick={() => void openCity(city.id)}>
                          <Eye size={14} /> {t("admin.cities.view")}
                        </button>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={8} className="px-4 py-14 text-center text-muted-foreground">
                    {t("admin.cities.notFound")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm text-secondary-foreground">
          <span>{t("admin.cities.pageOf", { page: filters.page ?? 1, pages: totalPages || 1, total })}</span>
          <div className="flex gap-2">
            <Button disabled={busy || (filters.page ?? 1) <= 1} onClick={() => setPage(Math.max(1, (filters.page ?? 1) - 1))}>
              <ChevronLeft size={15} /> {t("admin.cities.prev")}
            </Button>
            <Button disabled={busy || (filters.page ?? 1) >= (totalPages || 1)} onClick={() => setPage((filters.page ?? 1) + 1)}>
              {t("admin.cities.next")} <ChevronRight size={15} />
            </Button>
          </div>
        </footer>
      </section>

      {selectedCity && (
        <CityDrawer
          city={selectedCity}
          districts={districts}
          districtError={districtError}
          busy={busy}
          canMutate={canMutate}
          onClose={() => setSelectedCity(null)}
          onRefresh={() => void openCity(selectedCity.id)}
          onEditCity={() => editCity(selectedCity)}
          onToggleCity={() => toggleCity(selectedCity)}
          onAddDistrict={() => setDistrictModal({ mode: "create", form: { ...emptyDistrictForm, city_id: String(selectedCity.id) } })}
          onEditDistrict={(district) =>
            setDistrictModal({
              mode: "edit",
              district,
              form: {
                city_id: String(district.city_id),
                name_uz: district.name_uz,
                name_ru: district.name_ru ?? "",
                display_order: String(district.display_order ?? 1000),
                is_active: district.is_active,
              },
            })
          }
          onToggleDistrict={(district) =>
            setConfirm({
              title: district.is_active ? t("admin.cities.confirmDistrictDeactivate") : t("admin.cities.confirmDistrictActivate"),
              message: district.is_active ? t("admin.cities.districtDeactivateEffect") : t("admin.cities.districtActivateEffect"),
              submit: district.is_active ? t("admin.cities.deactivate") : t("admin.cities.activate"),
              tone: district.is_active ? "danger" : "primary",
              action: async () => {
                if (district.is_active) await deactivateDistrict(district.id);
                else await activateDistrict(district.id);
                await afterCityChange(selectedCity.id);
              },
            })
          }
        />
      )}

      {cityModal && (
        <CityModal
          title={cityModal.mode === "create" ? t("admin.cities.add") : t("admin.cities.editTitle")}
          form={cityModal.form}
          busy={busy}
          duplicate={cityDuplicate}
          onChange={(form) => setCityModal({ ...cityModal, form })}
          onClose={() => setCityModal(null)}
          onSubmit={() =>
            void run(async () => {
              const payload = cityFormToPayload(cityModal.form);
              if (cityModal.mode === "create") {
                const city = await createCity(payload);
                setCityModal(null);
                await afterCityChange(city.id);
              } else if (cityModal.city) {
                await updateCity(cityModal.city.id, payload);
                setCityModal(null);
                await afterCityChange(cityModal.city.id);
              }
            })
          }
        />
      )}

      {districtModal && (
        <DistrictModal
          title={districtModal.mode === "create" ? t("admin.cities.addDistrict") : t("admin.cities.editDistrictTitle")}
          form={districtModal.form}
          cities={cities}
          busy={busy}
          duplicate={districtDuplicate}
          onChange={(form) => setDistrictModal({ ...districtModal, form })}
          onClose={() => setDistrictModal(null)}
          onSubmit={() =>
            void run(async () => {
              const payload = districtFormToPayload(districtModal.form);
              if (districtModal.mode === "create") {
                await createDistrict(payload);
                setDistrictModal(null);
                await afterCityChange(payload.city_id);
              } else if (districtModal.district) {
                await updateDistrict(districtModal.district.id, payload);
                setDistrictModal(null);
                await afterCityChange(payload.city_id);
              }
            })
          }
        />
      )}

      {confirm && (
        <ConfirmModal
          title={confirm.title}
          message={confirm.message}
          submitLabel={confirm.submit}
          tone={confirm.tone}
          busy={busy}
          onClose={() => setConfirm(null)}
          onConfirm={() =>
            void run(async () => {
              const action = confirm.action;
              setConfirm(null);
              await action();
            })
          }
        />
      )}
    </div>
  );
}
