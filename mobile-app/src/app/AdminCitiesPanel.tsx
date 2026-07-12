import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  ChevronLeft,
  ChevronRight,
  Edit,
  Eye,
  MapPin,
  Plus,
  RefreshCw,
  Search,
  ToggleLeft,
  X,
} from "lucide-react";

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
import { ApiError } from "../types/api";
import type { AuthUser } from "../types/auth";
import type { City } from "../types/city";
import type { District } from "../types/district";
import { formatAdminDate, formatShortAdminDate } from "../utils/date";
import {
  cleanLocationText,
  formatCityDisplayName,
  formatDistrictDisplayName,
  getActiveStatusLabel,
  getCityTypeLabel,
  getRequiresDistrictLabel,
  hasEncodingIssue,
  locationErrorMessage,
} from "../utils/locationLabels";

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

function Button(props: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "neutral" | "primary" | "danger";
}) {
  const tone = props.tone ?? "neutral";
  const className =
    tone === "primary"
      ? "border-blue-600 bg-blue-600 text-white hover:bg-blue-700"
      : tone === "danger"
        ? "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50";
  return (
    <button
      type="button"
      disabled={props.disabled}
      onClick={props.onClick}
      className={`inline-flex h-10 items-center justify-center gap-2 rounded-md border px-3 text-sm font-semibold transition ${className} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

function Badge({ children, className }: { children: React.ReactNode; className: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${className}`}>{children}</span>;
}

function activeBadge(active?: boolean) {
  return <Badge className={active ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-600"}>{getActiveStatusLabel(active)}</Badge>;
}

function typeBadge(type?: string) {
  return <Badge className="border-blue-200 bg-blue-50 text-blue-700">{getCityTypeLabel(type)}</Badge>;
}

function requiredBadge(value?: boolean) {
  return <Badge className={value ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-slate-50 text-slate-600"}>{getRequiresDistrictLabel(value)}</Badge>;
}

function Input(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-slate-700">
      {props.label}
      <input
        value={props.value}
        type={props.type ?? "text"}
        placeholder={props.placeholder}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-950 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      />
    </label>
  );
}

function Select(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-slate-700">
      {props.label}
      <select
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-950 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      >
        {props.children}
      </select>
    </label>
  );
}

function CheckField(props: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex h-10 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700">
      <input type="checkbox" checked={props.checked} onChange={(event) => props.onChange(event.target.checked)} />
      {props.label}
    </label>
  );
}

function ModalShell(props: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/40 p-4">
      <section className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h3 className="text-base font-bold text-slate-950">{props.title}</h3>
          <button onClick={props.onClose} className="rounded-md p-1 text-slate-500 hover:bg-slate-100" aria-label="Yopish">
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
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-1 text-sm font-semibold text-slate-950">{children || "-"}</div>
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
  const valid = props.form.name_uz.trim().length > 0 && !props.duplicate;
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        {props.duplicate && <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">City already exists</p>}
        <div className="grid gap-3 md:grid-cols-2">
          <Input label="Nomi uz" value={props.form.name_uz} onChange={(name_uz) => props.onChange({ ...props.form, name_uz })} />
          <Input label="Nomi ru" value={props.form.name_ru} onChange={(name_ru) => props.onChange({ ...props.form, name_ru })} />
          <Input label="Viloyat" value={props.form.region} onChange={(region) => props.onChange({ ...props.form, region })} />
          <Select label="Tur" value={props.form.type} onChange={(type) => props.onChange({ ...props.form, type: type as CityForm["type"] })}>
            <option value="city">Shahar</option>
            <option value="region">Viloyat</option>
            <option value="republic">Respublika</option>
          </Select>
          <Input label="Ko'rsatish tartibi" value={props.form.display_order} type="number" onChange={(display_order) => props.onChange({ ...props.form, display_order })} />
          <div className="grid gap-2 pt-6">
            <CheckField label="Tuman talab qilinadi" checked={props.form.requires_district} onChange={(requires_district) => props.onChange({ ...props.form, requires_district })} />
            <CheckField label="Faol" checked={props.form.is_active} onChange={(is_active) => props.onChange({ ...props.form, is_active })} />
          </div>
        </div>
        <div className="rounded-md border border-blue-100 bg-blue-50 p-3 text-xs text-blue-700">Toshkent shahri odatda Shahar turi va tuman talab qilinmaydigan hudud sifatida sozlanadi.</div>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>Bekor qilish</Button>
          <Button tone="primary" disabled={props.busy || !valid} onClick={props.onSubmit}>Saqlash</Button>
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
  const valid = Number(props.form.city_id) > 0 && props.form.name_uz.trim().length > 0 && !props.duplicate;
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        {props.duplicate && <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">Bu hududda tuman allaqachon mavjud</p>}
        <Select label="Hudud" value={props.form.city_id} onChange={(city_id) => props.onChange({ ...props.form, city_id })}>
          <option value="">Hududni tanlang</option>
          {props.cities.map((city) => <option key={city.id} value={city.id}>{formatCityDisplayName(city)}</option>)}
        </Select>
        <div className="grid gap-3 md:grid-cols-2">
          <Input label="Nomi uz" value={props.form.name_uz} onChange={(name_uz) => props.onChange({ ...props.form, name_uz })} />
          <Input label="Nomi ru" value={props.form.name_ru} onChange={(name_ru) => props.onChange({ ...props.form, name_ru })} />
          <Input label="Ko'rsatish tartibi" value={props.form.display_order} type="number" onChange={(display_order) => props.onChange({ ...props.form, display_order })} />
          <div className="pt-6"><CheckField label="Faol" checked={props.form.is_active} onChange={(is_active) => props.onChange({ ...props.form, is_active })} /></div>
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>Bekor qilish</Button>
          <Button tone="primary" disabled={props.busy || !valid} onClick={props.onSubmit}>Saqlash</Button>
        </div>
      </div>
    </ModalShell>
  );
}

function ConfirmModal(props: {
  title: string;
  message: string;
  submitLabel: string;
  tone?: "primary" | "danger";
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm font-medium text-amber-800">{props.message}</p>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>Bekor qilish</Button>
          <Button tone={props.tone ?? "danger"} disabled={props.busy} onClick={props.onConfirm}>{props.submitLabel}</Button>
        </div>
      </div>
    </ModalShell>
  );
}

function citySearchText(city: City): string {
  return [city.name_uz, city.name_ru, city.region, city.type].filter(Boolean).join(" ").toLowerCase();
}

function CityDrawer(props: {
  city: City;
  districts: District[];
  districtError?: string | null;
  busy: boolean;
  canMutate: boolean;
  cities: City[];
  onClose: () => void;
  onRefresh: () => void;
  onAddDistrict: () => void;
  onEditDistrict: (district: District) => void;
  onToggleDistrict: (district: District) => void;
}) {
  const [tab, setTab] = useState<"info" | "districts" | "tariffs" | "orders" | "audit">("info");
  const city = props.city;
  return (
    <>
      <div className="fixed inset-0 z-50 bg-slate-950/30" onClick={props.onClose} />
      <aside className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-3xl flex-col border-l border-slate-200 bg-slate-50 shadow-2xl">
        <header className="border-b border-slate-200 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-slate-950">{formatCityDisplayName(city)}</h2>
                {typeBadge(city.type)}
                {requiredBadge(city.requires_district)}
                {activeBadge(city.is_active)}
              </div>
              <p className="mt-1 text-sm text-slate-500">Yaratilgan {formatAdminDate(city.created_at)} · Yangilangan {formatAdminDate(city.updated_at)}</p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button onClick={props.onRefresh}><RefreshCw size={15} /> Yangilash</Button>
              <Button onClick={props.onClose}><X size={15} /> Yopish</Button>
            </div>
          </div>
          <div className="mt-4 flex gap-2 border-b border-slate-200">
            {[
              ["info", "Hudud ma'lumotlari"],
              ["districts", "Tumanlar"],
              ["tariffs", "Yo'nalish tariflari"],
              ["orders", "So'nggi buyurtmalar"],
              ["audit", "Audit"],
            ].map(([key, label]) => (
              <button key={key} onClick={() => setTab(key as typeof tab)} className={`border-b-2 px-3 py-2 text-sm font-semibold ${tab === key ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-950"}`}>{label}</button>
            ))}
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {tab === "info" && (
            <section className="grid gap-3 md:grid-cols-3">
              <DetailItem label="Nomi uz">{cleanLocationText(city.name_uz)}</DetailItem>
              <DetailItem label="Nomi ru">{hasEncodingIssue(city.name_ru) ? <Badge className="border-amber-200 bg-amber-50 text-amber-700">Kodlash muammosi</Badge> : cleanLocationText(city.name_ru)}</DetailItem>
              <DetailItem label="Viloyat">{cleanLocationText(city.region)}</DetailItem>
              <DetailItem label="Tur">{typeBadge(city.type)}</DetailItem>
              <DetailItem label="Tuman talab qilinadi">{requiredBadge(city.requires_district)}</DetailItem>
              <DetailItem label="Faol">{activeBadge(city.is_active)}</DetailItem>
              <DetailItem label="Ko'rsatish tartibi">{city.display_order ?? "-"}</DetailItem>
              <DetailItem label="Tumanlar">{city.active_districts_count ?? 0} active / {city.districts_count ?? 0} total</DetailItem>
            </section>
          )}
          {tab === "districts" && (
            <section className="grid gap-4">
              {city.requires_district && !props.districts.length && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm font-medium text-amber-800">
                  This city requires districts, but no districts are added yet.
                </div>
              )}
              <div className="flex justify-between gap-3">
                <div>
                  <h3 className="font-bold text-slate-950">Districts</h3>
                  <p className="text-sm text-slate-500">Districts are used for matching accuracy.</p>
                </div>
                <Button disabled={!props.canMutate} tone="primary" onClick={props.onAddDistrict}><Plus size={15} /> Add district</Button>
              </div>
              {props.districtError && <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">{props.districtError}</p>}
              <div className="max-w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
                <div className="min-w-0 overflow-x-auto">
                <table className="w-full min-w-[620px] text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      {["Nomi uz", "Nomi ru", "Faol", "Yaratilgan", "Amallar"].map((label) => <th key={label} className="px-4 py-3 font-semibold">{label}</th>)}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {props.districts.length ? props.districts.map((district) => (
                      <tr key={district.id}>
                        <td className="px-4 py-3 font-semibold text-slate-950">{formatDistrictDisplayName(district)}</td>
                        <td className="px-4 py-3">{hasEncodingIssue(district.name_ru) ? <Badge className="border-amber-200 bg-amber-50 text-amber-700">Kodlash muammosi</Badge> : cleanLocationText(district.name_ru)}</td>
                        <td className="px-4 py-3">{activeBadge(district.is_active)}</td>
                        <td className="px-4 py-3">{formatShortAdminDate(district.created_at)}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-2">
                            <Button disabled={!props.canMutate} onClick={() => props.onEditDistrict(district)}><Edit size={14} /> Tahrirlash</Button>
                            <Button disabled={!props.canMutate} tone={district.is_active ? "danger" : "primary"} onClick={() => props.onToggleDistrict(district)}>{district.is_active ? "Faolsizlantirish" : "Faollashtirish"}</Button>
                          </div>
                        </td>
                      </tr>
                    )) : (
                      <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-500">Districts not found</td></tr>
                    )}
                  </tbody>
                </table>
                </div>
              </div>
            </section>
          )}
          {tab === "tariffs" && <div className="rounded-lg border border-slate-200 bg-white p-5 text-sm text-slate-600">Bu hudud ishlatilgan yo'nalish tariflari Tariflar modulida mavjud.</div>}
          {tab === "orders" && <div className="rounded-lg border border-slate-200 bg-white p-5 text-sm text-slate-600">Bu hudud ishlatilgan so'nggi buyurtmalar Buyurtmalar modulida mavjud.</div>}
          {tab === "audit" && <div className="rounded-lg border border-slate-200 bg-white p-5 text-sm text-slate-600">Audit yozuvlari Audit jurnali modulida mavjud.</div>}
        </div>
      </aside>
    </>
  );
}

export function AdminCitiesPanel({ user }: Props) {
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
      setError(err instanceof ApiError ? locationErrorMessage(err.code) : "Hududlarni yuklab bo'lmadi");
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
      setDistrictError(err instanceof ApiError ? locationErrorMessage(err.code) : "Tumanlarni yuklab bo'lmadi");
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
      setError(err instanceof ApiError ? locationErrorMessage(err.code) : "Hududni yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadCities();
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
      ["Jami hududlar", visibleCities.length, Building2],
      ["Faol hududlar", visibleCities.filter((city) => city.is_active).length, ToggleLeft],
      ["Nofaol hududlar", visibleCities.filter((city) => !city.is_active).length, X],
      ["Tuman talab qilinadi", visibleCities.filter((city) => city.requires_district).length, MapPin],
      ["Jami tumanlar", totalDistricts, MapPin],
      ["Tuman qo'shilmagan hududlar", visibleCities.filter((city) => city.requires_district && !city.districts_count).length, AlertTriangle],
    ] as const;
  }, [visibleCities]);

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
      setError(err instanceof ApiError ? locationErrorMessage(err.code) : err instanceof Error ? err.message : "Amal bajarilmadi");
    } finally {
      setBusy(false);
    }
  }

  const cityDuplicate = cityModal
    ? cities.some((city) => city.name_uz.trim().toLowerCase() === cityModal.form.name_uz.trim().toLowerCase() && city.id !== cityModal.city?.id)
    : false;
  const districtDuplicate = districtModal
    ? districts.some((district) => district.name_uz.trim().toLowerCase() === districtModal.form.name_uz.trim().toLowerCase() && district.id !== districtModal.district?.id)
    : false;

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-slate-950">Cities</h2>
          <p className="mt-1 text-sm text-slate-500">Moslashtirish uchun shaharlar, viloyatlar, tumanlar va faollikni boshqaring.</p>
        </div>
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void loadCities()}><RefreshCw size={16} /> Yangilash</Button>
          <Button tone="primary" disabled={!canMutate} onClick={() => setCityModal({ mode: "create", form: emptyCityForm })}><Plus size={16} /> Hudud qo'shish</Button>
        </div>
      </section>

      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">{error}</div>}
      {!canMutate && <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-600">Hudud yoki tuman yaratish/tahrirlash uchun ruxsat yo'q.</div>}

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {summary.map(([label, value, Icon]) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
              <Icon size={16} className="text-slate-400" />
            </div>
            <p className="mt-3 text-2xl font-bold text-slate-950">{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 lg:grid-cols-4 xl:grid-cols-6">
          <Input label="Qidirish" value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder="Nom, viloyat yoki tur" />
          <Select label="Tur" value={draftFilters.type ?? ""} onChange={(type) => setDraftFilters({ ...draftFilters, type })}>
            <option value="">Barchasi</option>
            <option value="city">Shahar</option>
            <option value="region">Viloyat</option>
            <option value="republic">Respublika</option>
          </Select>
          <Select label="Faollik holati" value={draftFilters.is_active ?? ""} onChange={(is_active) => setDraftFilters({ ...draftFilters, is_active })}>
            <option value="">Barchasi</option>
            <option value="active">Faol</option>
            <option value="inactive">Nofaol</option>
          </Select>
          <Select label="Tuman talab qilinadi" value={draftFilters.requires_district ?? ""} onChange={(requires_district) => setDraftFilters({ ...draftFilters, requires_district })}>
            <option value="">Barchasi</option>
            <option value="required">Talab qilinadi</option>
            <option value="not_required">Talab qilinmaydi</option>
          </Select>
          <Select label="Tumanlari bor" value={draftFilters.has_districts ?? ""} onChange={(has_districts) => setDraftFilters({ ...draftFilters, has_districts })}>
            <option value="">Barchasi</option>
            <option value="yes">Tumanlari bor</option>
            <option value="no">Tumanlar yo'q</option>
          </Select>
          <Select label="Limit" value={String(draftFilters.limit ?? 20)} onChange={(limit) => setDraftFilters({ ...draftFilters, limit: Number(limit), page: 1 })}>
            {[10, 20, 50, 100].map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button onClick={clearFilters}>Filtrlarni tozalash</Button>
          <Button tone="primary" disabled={busy} onClick={applyFilters}>Filtrlarni qo'llash</Button>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[1020px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                {["ID", "Nomi uz", "Nomi ru", "Viloyat", "Tur", "Tuman talab qilinadi", "Tumanlar", "Faol", "Yaratilgan", "Amallar"].map((label) => (
                  <th key={label} className="px-4 py-3 font-semibold">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {busy && !cities.length ? Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={10} className="px-4 py-3"><div className="h-8 animate-pulse rounded bg-slate-100" /></td></tr>
              )) : visibleCities.length ? visibleCities.map((city) => (
                <tr key={city.id} className="cursor-pointer hover:bg-slate-50" onClick={() => void openCity(city.id)}>
                  <td className="px-4 py-3 font-semibold text-slate-700">#{city.id}</td>
                  <td className="px-4 py-3 font-bold text-slate-950">{cleanLocationText(city.name_uz)}</td>
                  <td className="px-4 py-3">{hasEncodingIssue(city.name_ru) ? <Badge className="border-amber-200 bg-amber-50 text-amber-700">Kodlash muammosi</Badge> : cleanLocationText(city.name_ru)}</td>
                  <td className="px-4 py-3">{cleanLocationText(city.region)}</td>
                  <td className="px-4 py-3">{typeBadge(city.type)}</td>
                  <td className="px-4 py-3">{requiredBadge(city.requires_district)}</td>
                  <td className="px-4 py-3">
                    <p>{city.districts_count ?? 0} districts</p>
                    {city.requires_district && !city.active_districts_count && <p className="text-xs font-semibold text-amber-700">Tumanlar yo'q</p>}
                  </td>
                  <td className="px-4 py-3">{activeBadge(city.is_active)}</td>
                  <td className="px-4 py-3">{formatShortAdminDate(city.created_at)}</td>
                  <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => void openCity(city.id)}><Eye size={14} /> Ko'rish</Button>
                      <Button disabled={!canMutate} onClick={() => setCityModal({ mode: "edit", city, form: {
                        name_uz: city.name_uz,
                        name_ru: city.name_ru ?? "",
                        region: city.region ?? "",
                        type: (city.type as CityForm["type"]) || "region",
                        requires_district: city.requires_district ?? true,
                        display_order: String(city.display_order ?? 1000),
                        is_active: city.is_active ?? true,
                      } })}><Edit size={14} /> Tahrirlash</Button>
                      <Button disabled={!canMutate} tone={city.is_active ? "danger" : "primary"} onClick={() => setConfirm({
                        title: city.is_active ? "Hudud faolsizlantirilsinmi?" : "Hudud faollashtirilsinmi?",
                        message: city.is_active ? "Bu hudud yangi buyurtmalar va yo'nalishlarda mavjud bo'lmaydi. Mavjud buyurtmalar o'chirilmaydi." : "Bu hudud yangi buyurtmalar va yo'nalishlarda mavjud bo'ladi.",
                        submit: city.is_active ? "Faolsizlantirish" : "Faollashtirish",
                        tone: city.is_active ? "danger" : "primary",
                        action: async () => { city.is_active ? await deactivateCity(city.id) : await activateCity(city.id); await afterCityChange(city.id); },
                      })}>{city.is_active ? "Faolsizlantirish" : "Faollashtirish"}</Button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan={10} className="px-4 py-14 text-center text-slate-500">Cities not found</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
          <span>Sahifa {filters.page ?? 1} / {totalPages || 1} · jami {total}</span>
          <div className="flex gap-2">
            <Button disabled={busy || (filters.page ?? 1) <= 1} onClick={() => setPage(Math.max(1, (filters.page ?? 1) - 1))}><ChevronLeft size={15} /> Oldingi</Button>
            <Button disabled={busy || (filters.page ?? 1) >= (totalPages || 1)} onClick={() => setPage((filters.page ?? 1) + 1)}>Keyingi <ChevronRight size={15} /></Button>
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
          cities={cities}
          onClose={() => setSelectedCity(null)}
          onRefresh={() => void openCity(selectedCity.id)}
          onAddDistrict={() => setDistrictModal({ mode: "create", form: { ...emptyDistrictForm, city_id: String(selectedCity.id) } })}
          onEditDistrict={(district) => setDistrictModal({ mode: "edit", district, form: {
            city_id: String(district.city_id),
            name_uz: district.name_uz,
            name_ru: district.name_ru ?? "",
            display_order: String(district.display_order ?? 1000),
            is_active: district.is_active,
          } })}
          onToggleDistrict={(district) => setConfirm({
            title: district.is_active ? "Tuman faolsizlantirilsinmi?" : "Tuman faollashtirilsinmi?",
            message: district.is_active ? "Bu tuman yangi buyurtmalar va yo'nalishlarda mavjud bo'lmaydi. Mavjud buyurtmalar o'chirilmaydi. Tuman mavjud buyurtma yoki yo'nalishlarda ishlatilgan bo'lishi mumkin." : "Bu tuman yangi buyurtmalar va yo'nalishlarda mavjud bo'ladi.",
            submit: district.is_active ? "Faolsizlantirish" : "Faollashtirish",
            tone: district.is_active ? "danger" : "primary",
            action: async () => { district.is_active ? await deactivateDistrict(district.id) : await activateDistrict(district.id); await afterCityChange(selectedCity.id); },
          })}
        />
      )}

      {cityModal && (
        <CityModal
          title={cityModal.mode === "create" ? "Hudud qo'shish" : "Hududni tahrirlash"}
          form={cityModal.form}
          busy={busy}
          duplicate={cityDuplicate}
          onChange={(form) => setCityModal({ ...cityModal, form })}
          onClose={() => setCityModal(null)}
          onSubmit={() => void run(async () => {
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
          })}
        />
      )}

      {districtModal && (
        <DistrictModal
          title={districtModal.mode === "create" ? "Tuman qo'shish" : "Tumanni tahrirlash"}
          form={districtModal.form}
          cities={cities}
          busy={busy}
          duplicate={districtDuplicate}
          onChange={(form) => setDistrictModal({ ...districtModal, form })}
          onClose={() => setDistrictModal(null)}
          onSubmit={() => void run(async () => {
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
          })}
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
          onConfirm={() => void run(async () => {
            const action = confirm.action;
            setConfirm(null);
            await action();
          })}
        />
      )}
    </div>
  );
}
