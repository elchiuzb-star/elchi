/**
 * Tariflar (v1 suggested route prices; design "Elchi Admin" → Tariflar + overlay `tariff`).
 *
 * v1 only: a tariff is the suggested price for new v1 orders, per direction. In the v2 auction the two sides agree
 * the price (Q90) — the panel says so and points to «Narx referensi». Existing orders keep their copied price.
 * Create, edit and (de)activate only for admin and super_admin. Props are unchanged (`user`).
 */
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, DollarSign, Edit, Plus, RefreshCw, Route, X } from "./ui/icons";

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
import { translate, translateDynamic } from "../i18n";
import { useT } from "../i18n/react";
import { ApiError } from "../types/api";
import type { AuthUser } from "../types/auth";
import type { City } from "../types/city";
import type { RouteTariff, RouteTariffPayload, TariffFilters } from "../types/tariff";
import { formatAdminDate, formatShortAdminDate } from "../utils/date";
import { formatUZS } from "../utils/money";

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

function routeText(tariff: Pick<RouteTariff, "from_city" | "to_city">): string {
  return `${tariff.from_city?.name_uz ?? "-"} → ${tariff.to_city?.name_uz ?? "-"}`;
}

function activeLabel(active?: boolean | null): string {
  return active ? translate("admin.cities.active") : translate("admin.cities.inactive");
}

function tariffError(code?: string): string {
  return (code ? translateDynamic(`admin.tariffs.err.${code}`) : undefined) ?? translate("admin.cities.err.fallback");
}

/** Same rules as utils/tariffLabels `validateTariffPriceRange`, in the active language. */
function priceProblem(form: TariffForm): string | null {
  const suggested = form.suggested_price === "" ? null : Number(form.suggested_price);
  const min = form.min_price === "" ? null : Number(form.min_price);
  const max = form.max_price === "" ? null : Number(form.max_price);
  if (suggested === null || Number.isNaN(suggested)) return translate("admin.tariffs.v.suggestedRequired");
  if (suggested < 0 || (min !== null && min < 0) || (max !== null && max < 0)) return translate("admin.tariffs.v.negative");
  if (min !== null && min > suggested) return translate("admin.tariffs.v.minAbove");
  if (max !== null && suggested > max) return translate("admin.tariffs.v.maxBelow");
  return null;
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

function activeBadge(active?: boolean) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${active ? "border-success/25 bg-success/12 text-success" : "border-border bg-muted text-secondary-foreground"}`}>
      {activeLabel(active)}
    </span>
  );
}

function Input(props: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string; error?: string | null; disabled?: boolean }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <input
        value={props.value}
        type={props.type ?? "text"}
        placeholder={props.placeholder}
        disabled={props.disabled}
        aria-label={props.label}
        onChange={(event) => props.onChange(event.target.value)}
        className={`h-10 rounded-[10px] border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:bg-muted ${props.error ? "border-destructive/40" : "border-border"}`}
      />
      {props.error && <span className="text-xs font-medium text-destructive">{props.error}</span>}
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

function CitySelect(props: { label: string; value: string; cities: City[]; onChange: (value: string) => void; allowInactive?: boolean; disabled?: boolean; emptyLabel: string }) {
  const t = useT();
  const [search, setSearch] = useState("");
  const options = props.cities.filter((city) => {
    const text = [city.name_uz, city.name_ru, city.region].filter(Boolean).join(" ").toLowerCase();
    return text.includes(search.trim().toLowerCase());
  });
  if (props.disabled) {
    const city = props.cities.find((c) => String(c.id) === props.value);
    return <Input label={props.label} value={city?.name_uz ?? props.value} onChange={() => undefined} disabled />;
  }
  return (
    <div className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      <span>{props.label}</span>
      <input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={t("admin.tariffs.searchCity")}
        aria-label={`${props.label}: ${t("admin.tariffs.searchCity")}`}
        className="h-9 rounded-[10px] border border-border bg-card px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
      />
      <select
        value={props.value}
        aria-label={props.label}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
      >
        <option value="">{props.emptyLabel}</option>
        {options.map((city) => (
          <option key={city.id} value={city.id} disabled={!props.allowInactive && city.is_active === false}>
            {[city.name_uz, city.region, activeLabel(city.is_active !== false)].filter(Boolean).join(" / ")}
          </option>
        ))}
      </select>
    </div>
  );
}

function ModalShell(props: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-foreground/40 p-4">
      <section role="dialog" aria-modal="true" aria-label={props.title} className={`w-full ${props.wide ? "max-w-xl" : "max-w-lg"} rounded-[12px] border border-border bg-card shadow-xl`}>
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
  if (isCreate && !form.from_city_id) errors.from_city_id = translate("admin.tariffs.v.from");
  if (isCreate && !form.to_city_id) errors.to_city_id = translate("admin.tariffs.v.to");
  if (isCreate && form.from_city_id && form.to_city_id && form.from_city_id === form.to_city_id) errors.to_city_id = translate("admin.tariffs.err.SAME_CITY_ROUTE");
  errors.suggested_price = priceProblem(form);
  return errors;
}

/** Design overlay `tariff`: note, locked direction on edit, prices, active, and the price preview min – suggested – max. */
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
  const t = useT();
  const errors = validationFor(props.form, props.isCreate);
  const hasErrors = Object.values(errors).some(Boolean) || props.duplicate;
  const preview = [props.form.min_price, props.form.suggested_price, props.form.max_price]
    .map((value) => (value === "" ? "—" : formatUZS(value).replace(/\s*so'm$/, "")))
    .join(" – ");
  return (
    <ModalShell title={props.title} onClose={props.onClose} wide>
      <div className="grid gap-4 p-5">
        {props.duplicate && <p className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{t("admin.tariffs.err.ROUTE_TARIFF_ALREADY_EXISTS")}</p>}
        <div className="rounded-[10px] border border-primary/20 bg-accent p-3 text-xs text-primary">{t("admin.tariffs.editNote")}</div>
        <div className="grid gap-3 md:grid-cols-2">
          <CitySelect label={t("admin.tariffs.from")} emptyLabel={t("admin.cities.chooseCity")} disabled={!props.isCreate} value={props.form.from_city_id} cities={props.cities} onChange={(from_city_id) => props.onChange({ ...props.form, from_city_id })} />
          <CitySelect label={t("admin.tariffs.to")} emptyLabel={t("admin.cities.chooseCity")} disabled={!props.isCreate} value={props.form.to_city_id} cities={props.cities} onChange={(to_city_id) => props.onChange({ ...props.form, to_city_id })} />
          <Input label={t("admin.tariffs.suggestedReq")} type="number" value={props.form.suggested_price} onChange={(suggested_price) => props.onChange({ ...props.form, suggested_price })} error={errors.suggested_price} />
          <Input label={t("admin.tariffs.colMin")} type="number" value={props.form.min_price} onChange={(min_price) => props.onChange({ ...props.form, min_price })} />
          <Input label={t("admin.tariffs.colMax")} type="number" value={props.form.max_price} onChange={(max_price) => props.onChange({ ...props.form, max_price })} />
          <div className="pt-6">
            <CheckField label={t("admin.cities.active")} checked={props.form.is_active} onChange={(is_active) => props.onChange({ ...props.form, is_active })} />
          </div>
        </div>
        {(errors.from_city_id || errors.to_city_id) && <p className="text-xs text-destructive">{errors.from_city_id ?? errors.to_city_id}</p>}
        <div className="rounded-[12px] border border-border bg-muted/40 p-3 text-sm text-secondary-foreground">
          <span className="text-muted-foreground">{t("admin.tariffs.preview")}: </span>
          <span className="font-semibold text-foreground">{t("admin.tariffs.previewValue", { range: preview })}</span>
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button tone="primary" disabled={props.busy || hasErrors} onClick={props.onSubmit}>
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

function tariffSearchText(tariff: RouteTariff): string {
  return [tariff.id, tariff.from_city?.name_uz, tariff.to_city?.name_uz, routeText(tariff)].filter(Boolean).join(" ").toLowerCase();
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
  const t = useT();
  const reverseExists = Boolean(props.reverseTariff);
  return (
    <>
      {/* The scrim is decoration: it closes the drawer as a convenience; the drawer has a real close button. */}
      <div className="fixed inset-0 z-50 bg-foreground/30" role="presentation" onClick={props.onClose} />
      <aside role="dialog" aria-modal="true" aria-label={routeText(props.tariff)} className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-2xl flex-col border-l border-border bg-background shadow-2xl">
        <header className="border-b border-border bg-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-foreground">{routeText(props.tariff)}</h2>
                {activeBadge(props.tariff.is_active)}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{t("admin.tariffs.drawerSub")}</p>
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
            <div className="mt-4 flex flex-wrap gap-2">
              <Button disabled={props.busy} onClick={props.onEdit}>
                <Edit size={15} /> {t("admin.cities.edit")}
              </Button>
              <Button disabled={props.busy} tone={props.tariff.is_active ? "danger" : "primary"} onClick={props.onToggle}>
                {props.tariff.is_active ? t("admin.cities.deactivate") : t("admin.cities.activate")}
              </Button>
            </div>
          )}
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="grid min-w-0 gap-5">
            <section className="grid gap-3 md:grid-cols-2">
              <DetailItem label="ID">{props.tariff.id}</DetailItem>
              <DetailItem label={t("admin.tariffs.currency")}>{props.tariff.currency ?? "UZS"}</DetailItem>
              <DetailItem label={t("admin.tariffs.from")}>{props.tariff.from_city?.name_uz ?? "-"}</DetailItem>
              <DetailItem label={t("admin.tariffs.to")}>{props.tariff.to_city?.name_uz ?? "-"}</DetailItem>
              <DetailItem label={t("admin.tariffs.colSuggested")}>{formatUZS(props.tariff.suggested_price)}</DetailItem>
              <DetailItem label={t("admin.tariffs.colMin")}>{formatUZS(props.tariff.min_price)}</DetailItem>
              <DetailItem label={t("admin.tariffs.colMax")}>{formatUZS(props.tariff.max_price)}</DetailItem>
              <DetailItem label={t("admin.cities.active")}>{activeBadge(props.tariff.is_active)}</DetailItem>
              <DetailItem label={t("admin.cities.created")}>{formatAdminDate(props.tariff.created_at)}</DetailItem>
              <DetailItem label={t("admin.tariffs.updated")}>{formatAdminDate(props.tariff.updated_at)}</DetailItem>
            </section>
            <section className="rounded-[12px] border border-border bg-card p-4">
              <p className="text-sm font-bold text-foreground">{t("admin.tariffs.reverseCheck")}</p>
              <p className={`mt-2 text-sm font-semibold ${reverseExists ? "text-success" : "text-warning"}`}>
                {reverseExists ? t("admin.tariffs.reverseFound") : t("admin.tariffs.reverseMissing")}
              </p>
              {props.reverseTariff && (
                <p className="mt-1 text-sm text-secondary-foreground">
                  {routeText(props.reverseTariff)} · {formatUZS(props.reverseTariff.suggested_price)}
                </p>
              )}
              <p className="mt-3 text-xs text-muted-foreground">{t("admin.tariffs.reverseInfo")}</p>
            </section>
            <section className="rounded-[12px] border border-border bg-card p-4 text-sm text-secondary-foreground">{t("admin.tariffs.auditElsewhere")}</section>
          </div>
        </div>
      </aside>
    </>
  );
}

export function AdminTariffsPanel({ user }: Props) {
  const t = useT();
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
      setError(err instanceof ApiError ? tariffError(err.code) : t("admin.tariffs.loadFailed"));
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
      setError(err instanceof ApiError ? tariffError(err.code) : t("admin.tariffs.loadOneFailed"));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadTariffs();
    void getAdminCities({ is_active: "active", limit: 100 })
      .then((response) => setCities(response.items ?? []))
      .catch(() => setCities([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const noReverse = visibleTariffs.filter((tariff) => !hasReverse(tariff, tariffs)).length;
    return [
      [t("admin.tariffs.total"), visibleTariffs.length, Route, false],
      [t("admin.cities.active"), active.length, DollarSign, false],
      [t("admin.cities.inactive"), visibleTariffs.length - active.length, X, false],
      [t("admin.tariffs.noReverse"), noReverse, AlertTriangle, noReverse > 0],
      [t("admin.tariffs.avg"), formatUZS(average), DollarSign, false],
      [t("admin.tariffs.max"), formatUZS(highest), DollarSign, false],
    ] as const;
  }, [tariffs, visibleTariffs, t]);

  const duplicateActive =
    modal?.mode === "create" && modal.form.is_active
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
      setError(err instanceof ApiError ? tariffError(err.code) : err instanceof Error ? err.message : t("admin.cities.err.fallback"));
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
      title: tariff.is_active ? t("admin.tariffs.confirmDeactivate") : t("admin.tariffs.confirmActivate"),
      message: tariff.is_active ? t("admin.tariffs.deactivateEffect") : t("admin.tariffs.activateEffect"),
      submit: tariff.is_active ? t("admin.cities.deactivate") : t("admin.cities.activate"),
      tone: tariff.is_active ? "danger" : "primary",
      action: async () => {
        if (tariff.is_active) await deactivateTariff(tariff.id);
        else await activateTariff(tariff.id);
        await refreshAfterChange(tariff.id);
      },
    });
  }

  const columns = ["ID", t("admin.tariffs.route"), t("admin.tariffs.colSuggested"), t("admin.tariffs.colMin"), t("admin.tariffs.colMax"), t("admin.cities.active"), t("admin.tariffs.updated"), ""];

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.tariffs.title")}</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t("admin.tariffs.subtitle")}</p>
        </div>
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void loadTariffs()}>
            <RefreshCw size={16} /> {t("support.refresh")}
          </Button>
          {canMutate && (
            <Button tone="primary" onClick={() => setModal({ mode: "create", form: emptyForm })}>
              <Plus size={16} /> {t("admin.tariffs.add")}
            </Button>
          )}
        </div>
      </section>

      {error && <div role="alert" className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">{error}</div>}
      {!canMutate && <div className="rounded-[12px] border border-border bg-card px-4 py-3 text-sm font-medium text-secondary-foreground">{t("admin.tariffs.readOnly")}</div>}

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {summary.map(([label, value, Icon, warn]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
              <Icon size={16} className="text-muted-foreground" />
            </div>
            <p className={`mt-3 text-2xl font-bold ${warn ? "text-warning" : "text-foreground"}`}>{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="grid gap-3 lg:grid-cols-4 xl:grid-cols-4">
          <Input label={t("location.search")} value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder={t("admin.tariffs.searchPh")} />
          <CitySelect label={t("admin.tariffs.from")} emptyLabel={t("admin.cities.all")} value={draftFilters.from_city_id ?? ""} cities={cities} allowInactive onChange={(from_city_id) => setDraftFilters({ ...draftFilters, from_city_id })} />
          <CitySelect label={t("admin.tariffs.to")} emptyLabel={t("admin.cities.all")} value={draftFilters.to_city_id ?? ""} cities={cities} allowInactive onChange={(to_city_id) => setDraftFilters({ ...draftFilters, to_city_id })} />
          <Select label={t("admin.tariffs.hasReverse")} value={draftFilters.has_reverse ?? ""} onChange={(has_reverse) => setDraftFilters({ ...draftFilters, has_reverse })}>
            <option value="">{t("admin.cities.any")}</option>
            <option value="yes">{t("admin.tariffs.reverseYes")}</option>
            <option value="no">{t("admin.tariffs.reverseNo")}</option>
          </Select>
          <Select label={t("admin.cities.activity")} value={draftFilters.is_active ?? ""} onChange={(is_active) => setDraftFilters({ ...draftFilters, is_active })}>
            <option value="">{t("admin.cities.all")}</option>
            <option value="active">{t("admin.cities.active")}</option>
            <option value="inactive">{t("admin.cities.inactive")}</option>
          </Select>
          <Input label={t("admin.tariffs.priceFrom")} type="number" value={draftFilters.price_from ?? ""} onChange={(price_from) => setDraftFilters({ ...draftFilters, price_from })} />
          <Input label={t("admin.tariffs.priceTo")} type="number" value={draftFilters.price_to ?? ""} onChange={(price_to) => setDraftFilters({ ...draftFilters, price_to })} />
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
          <table className="w-full min-w-[820px] border-collapse text-left text-sm">
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
              {busy && !tariffs.length ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <tr key={index}>
                    <td colSpan={8} className="px-4 py-3">
                      <div className="h-8 animate-pulse rounded bg-background" />
                    </td>
                  </tr>
                ))
              ) : visibleTariffs.length ? (
                visibleTariffs.map((tariff) => (
                  <tr key={tariff.id} className="cursor-pointer hover:bg-muted/40" onClick={() => void openTariff(tariff.id)}>
                    <td className="px-4 py-3 font-semibold text-secondary-foreground">{tariff.id}</td>
                    <td className="px-4 py-3 font-bold text-foreground">{routeText(tariff)}</td>
                    <td className="px-4 py-3">{formatUZS(tariff.suggested_price)}</td>
                    <td className="px-4 py-3">{formatUZS(tariff.min_price)}</td>
                    <td className="px-4 py-3">{formatUZS(tariff.max_price)}</td>
                    <td className="px-4 py-3">{activeBadge(tariff.is_active)}</td>
                    <td className="px-4 py-3">{formatShortAdminDate(tariff.updated_at)}</td>
                    <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                      {canMutate ? (
                        <button type="button" className="inline-flex items-center gap-1 text-sm font-semibold text-primary" onClick={() => openEdit(tariff)}>
                          <Edit size={14} /> {t("admin.cities.edit")}
                        </button>
                      ) : (
                        <button type="button" className="text-sm font-semibold text-primary" onClick={() => void openTariff(tariff.id)}>
                          {t("admin.cities.view")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="px-4 py-14 text-center text-muted-foreground">
                    {t("admin.tariffs.notFound")}
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
          title={modal.mode === "create" ? t("admin.tariffs.add") : t("admin.tariffs.editTitle")}
          form={modal.form}
          cities={cities}
          busy={busy}
          isCreate={modal.mode === "create"}
          duplicate={duplicateActive}
          onChange={(form) => setModal({ ...modal, form })}
          onClose={() => setModal(null)}
          onSubmit={() =>
            void run(async () => {
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
