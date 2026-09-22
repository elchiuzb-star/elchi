import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  DollarSign,
  Edit,
  Eye,
  Plus,
  RefreshCw,
  Route,
  Search,
  X,
} from "./ui/icons";

import {
  activateTariff,
  createTariff,
  deactivateTariff,
  getAdminTariffDetail,
  getAdminTariffs,
  getReverseTariff,
  updateTariff,
} from "../api/admin-tariffs.api";
import { getAdminCities } from "../api/admin-cities.api";
import { ApiError } from "../types/api";
import type { AuthUser } from "../types/auth";
import type { City } from "../types/city";
import type { RouteTariff, RouteTariffPayload, TariffFilters } from "../types/tariff";
import { formatAdminDate, formatShortAdminDate } from "../utils/date";
import { formatUZS } from "../utils/money";
import {
  formatTariffRoute,
  getReverseRouteLabel,
  getTariffActiveBadgeClass,
  getTariffActiveLabel,
  tariffErrorMessage,
  validateTariffPriceRange,
} from "../utils/tariffLabels";

type Props = {
  user: AuthUser;
};

type TariffForm = {
  from_city_id: string;
  to_city_id: string;
  suggested_price: string;
  min_price: string;
  max_price: string;
  is_active: boolean;
};

const emptyForm: TariffForm = {
  from_city_id: "",
  to_city_id: "",
  suggested_price: "",
  min_price: "",
  max_price: "",
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
      ? "border-primary bg-primary text-primary-foreground hover:bg-primary"
      : tone === "danger"
        ? "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/25"
        : "border-border bg-card text-secondary-foreground hover:bg-slate-50";
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
  return <Badge className={getTariffActiveBadgeClass(active)}>{getTariffActiveLabel(active)}</Badge>;
}

function Input(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  error?: string | null;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <input
        value={props.value}
        type={props.type ?? "text"}
        placeholder={props.placeholder}
        onChange={(event) => props.onChange(event.target.value)}
        className={`h-10 rounded-[10px] border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100 ${props.error ? "border-destructive/40" : "border-border"}`}
      />
      {props.error && <span className="text-xs font-medium text-destructive">{props.error}</span>}
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
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <select
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
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

function CitySelect(props: {
  label: string;
  value: string;
  cities: City[];
  onChange: (value: string) => void;
  allowInactive?: boolean;
  disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const options = props.cities.filter((city) => {
    const text = [city.name_uz, city.name_ru, city.region].filter(Boolean).join(" ").toLowerCase();
    return text.includes(search.trim().toLowerCase());
  });
  return (
    <div className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      <span>{props.label}</span>
      <input
        value={search}
        disabled={props.disabled}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Hududni qidirish"
        className="h-9 rounded-[10px] border border-border bg-card px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
      />
      <select
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
      >
        <option value="">Hududni tanlang</option>
        {options.map((city) => (
          <option key={city.id} value={city.id} disabled={!props.allowInactive && city.is_active === false}>
            {[city.name_uz, city.region, city.is_active === false ? "Nofaol" : "Faol"].filter(Boolean).join(" / ")}
          </option>
        ))}
      </select>
    </div>
  );
}

function ModalShell(props: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-foreground/40 p-4">
      <section className="w-full max-w-xl rounded-[12px] border border-border bg-card shadow-xl">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-base font-bold text-foreground">{props.title}</h3>
          <button onClick={props.onClose} className="el-press rounded-[10px] p-1 text-muted-foreground hover:bg-muted" aria-label="Yopish">
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

function toPayload(form: TariffForm): RouteTariffPayload {
  return {
    from_city_id: Number(form.from_city_id),
    to_city_id: Number(form.to_city_id),
    suggested_price: Number(form.suggested_price),
    min_price: form.min_price === "" ? null : Number(form.min_price),
    max_price: form.max_price === "" ? null : Number(form.max_price),
    is_active: form.is_active,
  };
}

function validationFor(form: TariffForm, isCreate: boolean): Record<string, string | null> {
  const errors: Record<string, string | null> = {};
  if (isCreate && !form.from_city_id) errors.from_city_id = "Boshlanish hududini kiritish shart.";
  if (isCreate && !form.to_city_id) errors.to_city_id = "Borish hududini kiritish shart.";
  if (isCreate && form.from_city_id && form.to_city_id && form.from_city_id === form.to_city_id) errors.to_city_id = "Boshlanish va borish hududi bir xil bo'lmasligi kerak.";
  const priceError = validateTariffPriceRange({
    suggested_price: form.suggested_price === "" ? undefined : Number(form.suggested_price),
    min_price: form.min_price === "" ? null : Number(form.min_price),
    max_price: form.max_price === "" ? null : Number(form.max_price),
  });
  if (priceError) errors.suggested_price = priceError;
  return errors;
}

function TariffModal(props: {
  title: string;
  form: TariffForm;
  cities: City[];
  busy: boolean;
  isCreate: boolean;
  duplicate?: boolean;
  onChange: (form: TariffForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const errors = validationFor(props.form, props.isCreate);
  const hasErrors = Object.values(errors).some(Boolean) || props.duplicate;
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        {props.duplicate && <p className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">Active tariff already exists for this route.</p>}
        <div className="rounded-[10px] border border-blue-100 bg-accent p-3 text-xs text-primary">
          Tariffs are direction-based. Reverse direction must be added separately. Existing orders keep their copied suggested price.
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <CitySelect label="Qayerdan" disabled={!props.isCreate} value={props.form.from_city_id} cities={props.cities} onChange={(from_city_id) => props.onChange({ ...props.form, from_city_id })} />
          <CitySelect label="Qayerga" disabled={!props.isCreate} value={props.form.to_city_id} cities={props.cities} onChange={(to_city_id) => props.onChange({ ...props.form, to_city_id })} />
          <Input label="Tavsiya narx" type="number" value={props.form.suggested_price} onChange={(suggested_price) => props.onChange({ ...props.form, suggested_price })} error={errors.suggested_price} />
          <Input label="Minimal narx" type="number" value={props.form.min_price} onChange={(min_price) => props.onChange({ ...props.form, min_price })} />
          <Input label="Maksimal narx" type="number" value={props.form.max_price} onChange={(max_price) => props.onChange({ ...props.form, max_price })} />
          <div className="pt-6"><CheckField label="Faol" checked={props.form.is_active} onChange={(is_active) => props.onChange({ ...props.form, is_active })} /></div>
        </div>
        <div className="rounded-[12px] border border-border bg-slate-50 p-3 text-sm text-secondary-foreground">
          <p className="font-bold text-foreground">Narx ko'rinishi</p>
          <p>Tavsiya narx: {formatUZS(props.form.suggested_price)}</p>
          <p>Minimal: {props.form.min_price ? formatUZS(props.form.min_price) : "Minimal narx belgilanmagan"}</p>
          <p>Maksimal: {props.form.max_price ? formatUZS(props.form.max_price) : "Maksimal narx belgilanmagan"}</p>
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>Bekor qilish</Button>
          <Button tone="primary" disabled={props.busy || hasErrors} onClick={props.onSubmit}>Saqlash</Button>
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
        <p className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm font-medium text-warning">{props.message}</p>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>Bekor qilish</Button>
          <Button tone={props.tone ?? "danger"} disabled={props.busy} onClick={props.onConfirm}>{props.submitLabel}</Button>
        </div>
      </div>
    </ModalShell>
  );
}

function tariffSearchText(tariff: RouteTariff): string {
  return [tariff.id, tariff.from_city?.name_uz, tariff.to_city?.name_uz, formatTariffRoute(tariff)].filter(Boolean).join(" ").toLowerCase();
}

function hasReverse(tariff: RouteTariff, tariffs: RouteTariff[]) {
  return tariffs.some((item) => item.from_city_id === tariff.to_city_id && item.to_city_id === tariff.from_city_id && item.is_active);
}

function TariffDrawer(props: {
  tariff: RouteTariff;
  reverseTariff: RouteTariff | null;
  busy: boolean;
  canMutate: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onEdit: () => void;
  onToggle: () => void;
}) {
  const reverseExists = Boolean(props.reverseTariff);
  return (
    <>
      {/* The scrim is decoration: it closes the drawer as a convenience, and the drawer itself carries the
          dialog semantics and a real close button. Marking it presentational keeps a screen reader from
          announcing a clickable region with no name. */}
      <div className="fixed inset-0 z-50 bg-foreground/30" role="presentation" onClick={props.onClose} />
      <aside className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-2xl flex-col border-l border-border bg-slate-50 shadow-2xl">
        <header className="border-b border-border bg-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-foreground">{formatTariffRoute(props.tariff)}</h2>
                {activeBadge(props.tariff.is_active)}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">Yo'nalishga bog'liq tarif · teskari yo'nalish alohida</p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button onClick={props.onRefresh}><RefreshCw size={15} /> Yangilash</Button>
              <Button onClick={props.onClose}><X size={15} /> Yopish</Button>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button disabled={!props.canMutate || props.busy} onClick={props.onEdit}><Edit size={15} /> Tahrirlash</Button>
            <Button disabled={!props.canMutate || props.busy} tone={props.tariff.is_active ? "danger" : "primary"} onClick={props.onToggle}>
              {props.tariff.is_active ? "Faolsizlantirish" : "Faollashtirish"}
            </Button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="grid min-w-0 gap-5">
            <section className="grid gap-3 md:grid-cols-2">
              <DetailItem label="Tarif ID">#{props.tariff.id}</DetailItem>
              <DetailItem label="Valyuta">{props.tariff.currency ?? "UZS"}</DetailItem>
              <DetailItem label="Qayerdan">{props.tariff.from_city?.name_uz ?? "-"}</DetailItem>
              <DetailItem label="Qayerga">{props.tariff.to_city?.name_uz ?? "-"}</DetailItem>
              <DetailItem label="Tavsiya narx">{formatUZS(props.tariff.suggested_price)}</DetailItem>
              <DetailItem label="Minimal narx">{formatUZS(props.tariff.min_price)}</DetailItem>
              <DetailItem label="Maksimal narx">{formatUZS(props.tariff.max_price)}</DetailItem>
              <DetailItem label="Faol">{activeBadge(props.tariff.is_active)}</DetailItem>
              <DetailItem label="Yaratilgan">{formatAdminDate(props.tariff.created_at)}</DetailItem>
              <DetailItem label="Yangilangan">{formatAdminDate(props.tariff.updated_at)}</DetailItem>
            </section>
            <section className="rounded-[12px] border border-border bg-card p-4">
              <p className="text-sm font-bold text-foreground">Reverse route check</p>
              <p className={`mt-2 text-sm font-semibold ${reverseExists ? "text-success" : "text-warning"}`}>{getReverseRouteLabel(reverseExists)}</p>
              {props.reverseTariff && <p className="mt-1 text-sm text-secondary-foreground">{formatTariffRoute(props.reverseTariff)} · {formatUZS(props.reverseTariff.suggested_price)}</p>}
              <p className="mt-3 text-xs text-muted-foreground">This is informational only. Reverse route is not created automatically.</p>
            </section>
            <section className="rounded-[12px] border border-border bg-card p-4 text-sm text-secondary-foreground">
              Audit yozuvlari Audit jurnali modulida mavjud. Bu tarif ishlatilgan so'nggi buyurtmalar backendda hali ochilmagan.
            </section>
          </div>
        </div>
      </aside>
    </>
  );
}

export function AdminTariffsPanel({ user }: Props) {
  const [tariffs, setTariffs] = useState<RouteTariff[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [selectedTariff, setSelectedTariff] = useState<RouteTariff | null>(null);
  const [reverseTariff, setReverseTariff] = useState<RouteTariff | null>(null);
  const [filters, setFilters] = useState<TariffFilters>({ page: 1, limit: 20 });
  const [draftFilters, setDraftFilters] = useState<TariffFilters>({ page: 1, limit: 20 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [modal, setModal] = useState<{ mode: "create" | "edit"; tariff?: RouteTariff; form: TariffForm } | null>(null);
  const [confirm, setConfirm] = useState<{ title: string; message: string; submit: string; tone?: "primary" | "danger"; action: () => Promise<unknown> } | null>(null);
  const canMutate = user.role === "admin" || user.role === "super_admin";

  async function loadTariffs(nextFilters = filters) {
    setBusy(true);
    setError(null);
    try {
      const response = await getAdminTariffs(nextFilters);
      setTariffs(response.items ?? []);
      setTotal(response.pagination?.total ?? response.items.length);
      setTotalPages(response.pagination?.total_pages ?? 1);
    } catch (err) {
      setError(err instanceof ApiError ? tariffErrorMessage(err.code) : "Tariflarni yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  async function openTariff(tariffId: number) {
    setBusy(true);
    setError(null);
    try {
      const tariff = await getAdminTariffDetail(tariffId);
      setSelectedTariff(tariff);
      setReverseTariff(await getReverseTariff(tariff.from_city_id, tariff.to_city_id).catch(() => null));
    } catch (err) {
      setError(err instanceof ApiError ? tariffErrorMessage(err.code) : "Tarifni yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadTariffs();
    void getAdminCities({ is_active: "active", limit: 100 }).then((response) => setCities(response.items ?? [])).catch(() => setCities([]));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((draftFilters.search ?? "") !== (filters.search ?? "")) {
        const next = { ...filters, search: draftFilters.search, page: 1 };
        setFilters(next);
        void loadTariffs(next);
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [draftFilters.search]);

  const visibleTariffs = useMemo(() => {
    const q = (filters.search ?? "").trim().toLowerCase();
    return tariffs.filter((tariff) => {
      if (q && !tariffSearchText(tariff).includes(q)) return false;
      const price = Number(tariff.suggested_price ?? 0);
      if (filters.price_from && price < Number(filters.price_from)) return false;
      if (filters.price_to && price > Number(filters.price_to)) return false;
      if (filters.has_reverse === "yes" && !hasReverse(tariff, tariffs)) return false;
      if (filters.has_reverse === "no" && hasReverse(tariff, tariffs)) return false;
      return true;
    });
  }, [filters, tariffs]);

  const summary = useMemo(() => {
    const active = visibleTariffs.filter((tariff) => tariff.is_active);
    const prices = visibleTariffs.map((tariff) => Number(tariff.suggested_price)).filter(Number.isFinite);
    const average = prices.length ? Math.round(prices.reduce((sum, price) => sum + price, 0) / prices.length) : null;
    const highest = prices.length ? Math.max(...prices) : null;
    return [
      ["Jami tariflar", visibleTariffs.length, Route],
      ["Faol tariflar", active.length, DollarSign],
      ["Nofaol tariflar", visibleTariffs.filter((tariff) => !tariff.is_active).length, X],
      ["Teskari tarifi yo'q yo'nalishlar", visibleTariffs.filter((tariff) => !hasReverse(tariff, tariffs)).length, AlertTriangle],
      ["O'rtacha tavsiya narx", formatUZS(average), DollarSign],
      ["Eng yuqori tavsiya narx", formatUZS(highest), DollarSign],
    ] as const;
  }, [tariffs, visibleTariffs]);

  const duplicateActive = modal?.mode === "create" && modal.form.is_active
    ? tariffs.some((tariff) => tariff.is_active && String(tariff.from_city_id) === modal.form.from_city_id && String(tariff.to_city_id) === modal.form.to_city_id)
    : false;

  function applyFilters() {
    const next = { ...draftFilters, page: 1 };
    setFilters(next);
    void loadTariffs(next);
  }

  function clearFilters() {
    const next = { page: 1, limit: filters.limit ?? 20 };
    setDraftFilters(next);
    setFilters(next);
    void loadTariffs(next);
  }

  function setPage(page: number) {
    const next = { ...filters, page };
    setFilters(next);
    setDraftFilters((current) => ({ ...current, page }));
    void loadTariffs(next);
  }

  async function refreshAfterChange(tariffId?: number) {
    await loadTariffs();
    if (tariffId ?? selectedTariff?.id) await openTariff(tariffId ?? selectedTariff!.id);
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? tariffErrorMessage(err.code) : err instanceof Error ? err.message : "Amal bajarilmadi");
    } finally {
      setBusy(false);
    }
  }

  function openEdit(tariff: RouteTariff) {
    setModal({
      mode: "edit",
      tariff,
      form: {
        from_city_id: String(tariff.from_city_id),
        to_city_id: String(tariff.to_city_id),
        suggested_price: String(tariff.suggested_price ?? ""),
        min_price: tariff.min_price === null || tariff.min_price === undefined ? "" : String(tariff.min_price),
        max_price: tariff.max_price === null || tariff.max_price === undefined ? "" : String(tariff.max_price),
        is_active: tariff.is_active,
      },
    });
  }

  function askToggle(tariff: RouteTariff) {
    setConfirm({
      title: tariff.is_active ? "Tarif faolsizlantirilsinmi?" : "Tarif faollashtirilsinmi?",
      message: tariff.is_active
        ? "Bu yo'nalish narxi yangi buyurtmalarda ishlatilmaydi. Mavjud buyurtmalar o'zgarmaydi."
        : "Bu yo'nalish narxi yangi buyurtmalar uchun mavjud bo'ladi. Backend takroriy faol tariflarni rad etadi.",
      submit: tariff.is_active ? "Faolsizlantirish" : "Faollashtirish",
      tone: tariff.is_active ? "danger" : "primary",
      action: async () => {
        tariff.is_active ? await deactivateTariff(tariff.id) : await activateTariff(tariff.id);
        await refreshAfterChange(tariff.id);
      },
    });
  }

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Tariflar</h2>
          <p className="mt-1 text-sm text-muted-foreground">Yangi buyurtmalar uchun hududdan hududga tavsiya narxlarini boshqaring.</p>
        </div>
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void loadTariffs()}><RefreshCw size={16} /> Yangilash</Button>
          <Button tone="primary" disabled={!canMutate} onClick={() => setModal({ mode: "create", form: emptyForm })}><Plus size={16} /> Tarif qo'shish</Button>
        </div>
      </section>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">{error}</div>}
      {!canMutate && <div className="rounded-[12px] border border-border bg-card px-4 py-3 text-sm font-medium text-secondary-foreground">Tarif yaratish yoki tahrirlash uchun ruxsat yo'q.</div>}

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {summary.map(([label, value, Icon]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
              <Icon size={16} className="text-slate-400" />
            </div>
            <p className="mt-3 text-2xl font-bold text-foreground">{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 lg:grid-cols-4 xl:grid-cols-7">
          <Input label="Qidirish" value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder="Yo'nalish, hudud yoki ID" />
          <CitySelect label="Qayerdan" value={draftFilters.from_city_id ?? ""} cities={cities} allowInactive onChange={(from_city_id) => setDraftFilters({ ...draftFilters, from_city_id })} />
          <CitySelect label="Qayerga" value={draftFilters.to_city_id ?? ""} cities={cities} allowInactive onChange={(to_city_id) => setDraftFilters({ ...draftFilters, to_city_id })} />
          <Select label="Faollik holati" value={draftFilters.is_active ?? ""} onChange={(is_active) => setDraftFilters({ ...draftFilters, is_active })}>
            <option value="">Barchasi</option>
            <option value="active">Faol</option>
            <option value="inactive">Nofaol</option>
          </Select>
          <Input label="Narxdan" type="number" value={draftFilters.price_from ?? ""} onChange={(price_from) => setDraftFilters({ ...draftFilters, price_from })} />
          <Input label="Narxgacha" type="number" value={draftFilters.price_to ?? ""} onChange={(price_to) => setDraftFilters({ ...draftFilters, price_to })} />
          <Select label="Teskari yo'nalish bor" value={draftFilters.has_reverse ?? ""} onChange={(has_reverse) => setDraftFilters({ ...draftFilters, has_reverse })}>
            <option value="">Istalgan</option>
            <option value="yes">Teskari bor</option>
            <option value="no">Teskari yo'q</option>
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

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                {["ID", "Yo'nalish", "Qayerdan", "Qayerga", "Tavsiya narx", "Minimal narx", "Maksimal narx", "Valyuta", "Faol", "Yaratilgan", "Yangilangan", "Amallar"].map((label) => (
                  <th key={label} className="px-4 py-3 font-semibold">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {busy && !tariffs.length ? Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={12} className="px-4 py-3"><div className="h-8 animate-pulse rounded bg-background" /></td></tr>
              )) : visibleTariffs.length ? visibleTariffs.map((tariff) => (
                <tr key={tariff.id} className="cursor-pointer hover:bg-slate-50" onClick={() => void openTariff(tariff.id)}>
                  <td className="px-4 py-3 font-semibold text-secondary-foreground">#{tariff.id}</td>
                  <td className="px-4 py-3 font-bold text-foreground">{formatTariffRoute(tariff)}</td>
                  <td className="px-4 py-3">{tariff.from_city?.name_uz ?? "-"}</td>
                  <td className="px-4 py-3">{tariff.to_city?.name_uz ?? "-"}</td>
                  <td className="px-4 py-3">{formatUZS(tariff.suggested_price)}</td>
                  <td className="px-4 py-3">{formatUZS(tariff.min_price)}</td>
                  <td className="px-4 py-3">{formatUZS(tariff.max_price)}</td>
                  <td className="px-4 py-3">{tariff.currency ?? "UZS"}</td>
                  <td className="px-4 py-3">{activeBadge(tariff.is_active)}</td>
                  <td className="px-4 py-3">{formatShortAdminDate(tariff.created_at)}</td>
                  <td className="px-4 py-3">{formatShortAdminDate(tariff.updated_at)}</td>
                  <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => void openTariff(tariff.id)}><Eye size={14} /> Ko'rish</Button>
                      <Button disabled={!canMutate} onClick={() => openEdit(tariff)}><Edit size={14} /> Tahrirlash</Button>
                      <Button disabled={!canMutate} tone={tariff.is_active ? "danger" : "primary"} onClick={() => askToggle(tariff)}>{tariff.is_active ? "Faolsizlantirish" : "Faollashtirish"}</Button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan={12} className="px-4 py-14 text-center text-muted-foreground">Tariflar topilmadi</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm text-secondary-foreground">
          <span>Sahifa {filters.page ?? 1} / {totalPages || 1} · jami {total}</span>
          <div className="flex gap-2">
            <Button disabled={busy || (filters.page ?? 1) <= 1} onClick={() => setPage(Math.max(1, (filters.page ?? 1) - 1))}><ChevronLeft size={15} /> Oldingi</Button>
            <Button disabled={busy || (filters.page ?? 1) >= (totalPages || 1)} onClick={() => setPage((filters.page ?? 1) + 1)}>Keyingi <ChevronRight size={15} /></Button>
          </div>
        </footer>
      </section>

      {selectedTariff && (
        <TariffDrawer
          tariff={selectedTariff}
          reverseTariff={reverseTariff}
          busy={busy}
          canMutate={canMutate}
          onClose={() => setSelectedTariff(null)}
          onRefresh={() => void openTariff(selectedTariff.id)}
          onEdit={() => openEdit(selectedTariff)}
          onToggle={() => askToggle(selectedTariff)}
        />
      )}

      {modal && (
        <TariffModal
          title={modal.mode === "create" ? "Tarif qo'shish" : "Tarifni tahrirlash"}
          form={modal.form}
          cities={cities}
          busy={busy}
          isCreate={modal.mode === "create"}
          duplicate={duplicateActive}
          onChange={(form) => setModal({ ...modal, form })}
          onClose={() => setModal(null)}
          onSubmit={() => void run(async () => {
            const payload = toPayload(modal.form);
            if (modal.mode === "create") {
              const created = await createTariff(payload);
              if (payload.is_active === false) await deactivateTariff(created.id);
              setModal(null);
              await refreshAfterChange(created.id);
            } else if (modal.tariff) {
              await updateTariff(modal.tariff.id, {
                suggested_price: payload.suggested_price,
                min_price: payload.min_price,
                max_price: payload.max_price,
                is_active: payload.is_active,
              });
              setModal(null);
              await refreshAfterChange(modal.tariff.id);
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
