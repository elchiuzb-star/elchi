import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  Ban,
  Car,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Eye,
  FileText,
  RefreshCw,
  Route,
  Search,
  Truck,
  User,
  X,
} from "./ui/icons";

import {
  approveDriver,
  blockDriver,
  getAdminDriverDetail,
  getAdminDrivers,
  rejectDriver,
} from "../api/admin-drivers.api";
import { getCities } from "../api/cities.api";
import { getDistricts } from "../api/districts.api";
import { ApiError } from "../types/api";
import type { AdminDriver, AdminDriverDocument, AdminDriverFilters } from "../types/admin-driver";
import type { AuthUser } from "../types/auth";
import type { City, District } from "../types/city";
import { formatAdminDate, formatShortAdminDate } from "../utils/date";
import {
  canApproveDriver,
  canBlockDriver,
  canRejectDriver,
  driverDocumentLabels,
  getAvailabilityBadgeClass,
  getAvailabilityLabel,
  getDriverVerificationBadgeClass,
  getDriverVerificationLabel,
  getMissingDriverDocuments,
  requiredDriverDocuments,
} from "../utils/driverStatus";

type DriversPanelProps = {
  user: AuthUser;
};

type DriverTab = {
  key: string;
  label: string;
  status?: string;
};

const driverTabs: DriverTab[] = [
  { key: "all", label: "Barchasi" },
  { key: "new", label: "Yangi", status: "new" },
  { key: "pending", label: "Ko'rib chiqish kutilmoqda", status: "pending" },
  { key: "approved", label: "Tasdiqlangan", status: "approved" },
  { key: "rejected", label: "Rad etilgan", status: "rejected" },
  { key: "blocked", label: "Bloklangan", status: "blocked" },
];

const rejectReasons = ["Hujjatlar aniq emas", "Majburiy hujjatlar yetishmaydi", "Transport ma'lumotlari noto'g'ri", "Boshqa"];

function Button(props: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "neutral" | "primary" | "danger";
  type?: "button" | "submit";
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
      type={props.type ?? "button"}
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold transition ${className} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

function Input(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <input
        value={props.value}
        type={props.type ?? "text"}
        placeholder={props.placeholder}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
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

function Badge({ children, className }: { children: React.ReactNode; className: string }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${className}`}>{children}</span>;
}

function value(value?: string | number | boolean | null) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function driverName(driver: AdminDriver) {
  return driver.full_name ?? driver.user?.full_name ?? "Profil to'liq emas";
}

function driverPhone(driver: AdminDriver) {
  return driver.phone ?? driver.user?.phone ?? "-";
}

function routeName(route: NonNullable<AdminDriver["routes"]>[number]) {
  const from = [route.from_city?.name_uz, route.from_district?.name_uz].filter(Boolean).join(" / ");
  const to = [route.to_city?.name_uz, route.to_district?.name_uz].filter(Boolean).join(" / ");
  return `${from || "-"} → ${to || "-"}`;
}

function searchableText(driver: AdminDriver) {
  return [
    driver.id,
    driverName(driver),
    driverPhone(driver),
    driver.plate_number,
    driver.car_model,
    driver.verification_status,
    ...(driver.routes ?? []).flatMap((route) => [route.from_city?.name_uz, route.to_city?.name_uz, route.from_district?.name_uz, route.to_district?.name_uz]),
  ].filter(Boolean).join(" ").toLowerCase();
}

function DetailItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-[12px] border border-border bg-card p-3">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-1 text-sm font-semibold text-foreground">{children || "-"}</div>
    </div>
  );
}

function ModalShell(props: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-foreground/40 p-4">
      <section className="w-full max-w-md rounded-[12px] border border-border bg-card shadow-xl">
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

function ApproveModal(props: {
  driver: AdminDriver;
  busy: boolean;
  onClose: () => void;
  onSubmit: (comment: string) => void;
}) {
  const [comment, setComment] = useState("");
  const missing = getMissingDriverDocuments(props.driver.documents);
  return (
    <ModalShell title="Haydovchini tasdiqlash" onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <div className="rounded-[10px] border border-border bg-slate-50 p-3 text-sm">
          <p className="font-bold text-foreground">{driverName(props.driver)}</p>
          <p className="text-muted-foreground">{driverPhone(props.driver)}</p>
        </div>
        {missing.length ? (
          <div className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm text-warning">
            <p className="font-bold">Majburiy hujjatlar yetishmaydi</p>
            <p className="mt-1">Yetishmayapti: {missing.map((item) => driverDocumentLabels[item]).join(", ")}</p>
          </div>
        ) : (
          <div className="rounded-[10px] border border-success/25 bg-success/12 p-3 text-sm font-medium text-success">Barcha majburiy hujjatlar yuklangan.</div>
        )}
        <Input label="Izoh" value={comment} onChange={setComment} placeholder="Ixtiyoriy izoh" />
        <p className="text-xs text-muted-foreground">Tasdiqlash haydovchini avtomatik faol qilmaydi.</p>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>Bekor qilish</Button>
          <Button tone="primary" disabled={props.busy} onClick={() => props.onSubmit(comment)}>Tasdiqlash</Button>
        </div>
      </div>
    </ModalShell>
  );
}

function ReasonModal(props: {
  title: string;
  warning?: string;
  busy: boolean;
  suggestions?: string[];
  tone?: "danger" | "primary";
  submitLabel: string;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        {props.warning && <div className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm font-medium text-warning">{props.warning}</div>}
        {props.suggestions && (
          <div className="flex flex-wrap gap-2">
            {props.suggestions.map((suggestion) => (
              <button key={suggestion} onClick={() => setReason(suggestion)} className="el-press rounded-full border border-border px-3 py-1 text-xs font-semibold text-secondary-foreground hover:bg-slate-50">
                {suggestion}
              </button>
            ))}
          </div>
        )}
        <Input label="Sabab" value={reason} onChange={setReason} placeholder="Sabab kiritish shart" />
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>Bekor qilish</Button>
          <Button tone={props.tone ?? "danger"} disabled={props.busy || !reason.trim()} onClick={() => props.onSubmit(reason)}>{props.submitLabel}</Button>
        </div>
      </div>
    </ModalShell>
  );
}

function isImageFile(url?: string) {
  return Boolean(url?.split("?")[0].match(/\.(png|jpe?g|webp|gif)$/i));
}

function isPdfFile(url?: string) {
  return Boolean(url?.split("?")[0].match(/\.pdf$/i));
}

function DocumentPreviewModal({ document, onClose }: { document: AdminDriverDocument; onClose: () => void }) {
  const url = document.file_url;
  const title = driverDocumentLabels[document.document_type];
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-foreground/70 p-4">
      <section className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-[12px] border border-border bg-card shadow-2xl">
        <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h3 className="text-base font-bold text-foreground">{title}</h3>
            <p className="text-xs text-muted-foreground">{document.created_at ? `Yuklangan ${formatAdminDate(document.created_at)}` : "Yuklangan fayl"}</p>
          </div>
          <div className="flex items-center gap-2">
            {url && <a href={url} target="_blank" rel="noreferrer" className="rounded-[10px] border border-border px-3 py-2 text-sm font-semibold text-secondary-foreground hover:bg-slate-50">Yangi oynada ochish</a>}
            <button onClick={onClose} className="el-press rounded-[10px] p-2 text-muted-foreground hover:bg-muted" aria-label="Yopish">
              <X size={18} />
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-auto bg-background p-4">
          {!url ? (
            <div className="rounded-[12px] border border-border bg-card p-10 text-center text-sm text-muted-foreground">Fayl yuklanmagan</div>
          ) : isImageFile(url) ? (
            <img src={url} alt={title} className="mx-auto max-h-[76vh] max-w-full rounded-[10px] bg-card object-contain shadow-sm" />
          ) : isPdfFile(url) ? (
            <iframe src={url} title={title} className="h-[76vh] w-full rounded-[10px] border border-border bg-card" />
          ) : (
            <div className="rounded-[12px] border border-border bg-card p-10 text-center">
              <FileText size={36} className="mx-auto text-slate-400" />
              <p className="mt-3 text-sm font-semibold text-secondary-foreground">Bu fayl turini panel ichida ko'rsatib bo'lmadi.</p>
              <a href={url} target="_blank" rel="noreferrer" className="mt-4 inline-flex rounded-[10px] bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary">Faylni ochish</a>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function DocumentCard({ document, onPreview }: { document: AdminDriverDocument; onPreview: (document: AdminDriverDocument) => void }) {
  const isImage = isImageFile(document.file_url);
  return (
    <div className="rounded-[12px] border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-bold text-foreground">{driverDocumentLabels[document.document_type]}</p>
          <p className="mt-1 text-xs text-muted-foreground">{document.created_at ? `Yuklangan ${formatAdminDate(document.created_at)}` : "Yuklanmagan"}</p>
        </div>
        <Badge className={document.status === "approved" ? "border-success/25 bg-success/12 text-success" : document.status === "rejected" ? "border-destructive/25 bg-destructive/10 text-destructive" : "border-blue-200 bg-accent text-primary"}>
          {document.status}
        </Badge>
      </div>
      {isImage && document.file_url && (
        <button type="button" onClick={() => onPreview(document)} className="el-press mt-3 block w-full overflow-hidden rounded-[10px] border border-border text-left hover:border-blue-300">
          <img src={document.file_url} alt={document.document_type} className="h-28 w-full object-cover" />
        </button>
      )}
      {document.file_url ? (
        <button type="button" onClick={() => onPreview(document)} className="el-press mt-3 inline-flex text-sm font-semibold text-primary hover:underline">Hujjatni ko'rish</button>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">Yuklanmagan</p>
      )}
      {document.rejection_reason && <p className="mt-2 text-sm text-destructive">Reason: {document.rejection_reason}</p>}
    </div>
  );
}

function DriverDrawer(props: {
  driver: AdminDriver;
  user: AuthUser;
  busy: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onApprove: (comment: string) => void;
  onReject: (reason: string) => void;
  onBlock: (reason: string) => void;
}) {
  const [tab, setTab] = useState<"overview" | "documents" | "routes" | "orders" | "audit">("overview");
  const [modal, setModal] = useState<"approve" | "reject" | "block" | null>(null);
  const [previewDocument, setPreviewDocument] = useState<AdminDriverDocument | null>(null);
  const driver = props.driver;
  const yuklanganDocuments = new Map((driver.documents ?? []).map((document) => [document.document_type, document]));
  const documents = requiredDriverDocuments.map((documentType) => yuklanganDocuments.get(documentType) ?? { document_type: documentType, status: "missing" as const });
  return (
    <>
      {/* The scrim is decoration: it closes the drawer as a convenience, and the drawer itself carries the
          dialog semantics and a real close button. Marking it presentational keeps a screen reader from
          announcing a clickable region with no name. */}
      <div className="fixed inset-0 z-50 bg-foreground/30" role="presentation" onClick={props.onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-3xl flex-col border-l border-border bg-slate-50 shadow-2xl"
      >
        <header className="border-b border-border bg-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-foreground">{driverName(driver)}</h2>
                <Badge className={getDriverVerificationBadgeClass(driver.verification_status)}>{getDriverVerificationLabel(driver.verification_status)}</Badge>
                <Badge className={getAvailabilityBadgeClass(driver.is_available, driver.verification_status)}>{getAvailabilityLabel(driver.is_available, driver.verification_status)}</Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{driverPhone(driver)} · Yaratilgan {formatAdminDate(driver.created_at)} · Yangilangan {formatAdminDate(driver.updated_at)}</p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button onClick={props.onRefresh}><RefreshCw size={15} /> Yangilash</Button>
              <Button onClick={props.onClose}><X size={15} /> Yopish</Button>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {canApproveDriver(driver, props.user) && <Button tone="primary" disabled={props.busy} onClick={() => setModal("approve")}><BadgeCheck size={15} /> Tasdiqlash</Button>}
            {canRejectDriver(driver, props.user) && <Button disabled={props.busy} onClick={() => setModal("reject")}><X size={15} /> Rad etish</Button>}
            {canBlockDriver(driver, props.user) && <Button tone="danger" disabled={props.busy} onClick={() => setModal("block")}><Ban size={15} /> Bloklash</Button>}
            {!["admin", "super_admin"].includes(props.user.role) && <span className="rounded-[10px] bg-background px-3 py-2 text-sm font-semibold text-muted-foreground">Amallar uchun ruxsat yo'q</span>}
          </div>
          <div className="mt-4 flex gap-2 border-b border-border">
            {[
              ["overview", "Umumiy"],
              ["documents", "Hujjatlar"],
              ["routes", "Yo'nalishlar"],
              ["orders", "Buyurtmalar"],
              ["audit", "Audit"],
            ].map(([key, label]) => (
              <button key={key} onClick={() => setTab(key as typeof tab)} className={`el-press border-b-2 px-3 py-2 text-sm font-semibold ${tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{label}</button>
            ))}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {tab === "overview" && (
            <div className="grid min-w-0 gap-5">
              <section className="grid gap-3 md:grid-cols-3">
                <DetailItem label="To'liq ism">{value(driverName(driver))}</DetailItem>
                <DetailItem label="Telefon">{value(driverPhone(driver))}</DetailItem>
                <DetailItem label="Avtomobil modeli">{value(driver.car_model)}</DetailItem>
                <DetailItem label="Avtomobil rangi">{value(driver.car_color)}</DetailItem>
                <DetailItem label="Davlat raqami">{value(driver.plate_number)}</DetailItem>
                <DetailItem label="Normallashtirilgan raqam">{value(driver.plate_number_normalized)}</DetailItem>
                <DetailItem label="Reyting">{value(driver.rating)}</DetailItem>
                <DetailItem label="Jami buyurtmalar">{value(driver.total_orders)}</DetailItem>
                <DetailItem label="Yakunlangan buyurtmalar">{value(driver.completed_orders)}</DetailItem>
                <DetailItem label="Bekor qilingan buyurtmalar">{value(driver.cancelled_orders)}</DetailItem>
                <DetailItem label="Nizolar">{value(driver.dispute_count)}</DetailItem>
                <DetailItem label="Mavjudlik">{getAvailabilityLabel(driver.is_available, driver.verification_status)}</DetailItem>
              </section>
              <section className="grid gap-3 md:grid-cols-4">
                <DetailItem label="Hujjatlar">{driver.documents_count ?? 0}/{driver.required_documents_count ?? 5} yuklangan</DetailItem>
                <DetailItem label="Yo'nalishlar">{driver.active_routes_count ?? 0} faol / {driver.total_routes_count ?? 0} jami</DetailItem>
                <DetailItem label="Biriktirilgan faol buyurtmalar">{driver.active_orders_count ?? 0}</DetailItem>
                <DetailItem label="Bloklash qoidasi">{driver.verification_status === "blocked" ? "Mavjudlik o'chirilgan" : "Oddiy"}</DetailItem>
              </section>
            </div>
          )}

          {tab === "documents" && (
            <section className="grid gap-3 md:grid-cols-2">
              {documents.map((document) => <DocumentCard key={document.document_type} document={document} onPreview={setPreviewDocument} />)}
            </section>
          )}

          {tab === "routes" && (
            <section className="grid gap-3">
              {(driver.routes ?? []).length ? (driver.routes ?? []).map((route) => (
                <div key={route.id} className="rounded-[12px] border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-bold text-foreground">{routeName(route)}</p>
                    <Badge className={route.status === "available" ? "border-success/25 bg-success/12 text-success" : route.status === "busy" ? "border-blue-200 bg-accent text-primary" : "border-border bg-slate-50 text-secondary-foreground"}>{route.status}</Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">Created {formatAdminDate(route.created_at)} · Reverse route is not automatic.</p>
                </div>
              )) : <div className="rounded-[12px] border border-border bg-card p-10 text-center text-sm text-muted-foreground">Yo'nalishlar yo'q</div>}
            </section>
          )}

          {tab === "orders" && (
            <section className="grid gap-3 md:grid-cols-4">
              <DetailItem label="Biriktirilgan faol buyurtmalar">{driver.active_orders_count ?? 0}</DetailItem>
              <DetailItem label="Yakunlangan buyurtmalar">{driver.completed_orders ?? 0}</DetailItem>
              <DetailItem label="Bekor qilingan buyurtmalar">{driver.cancelled_orders ?? 0}</DetailItem>
              <DetailItem label="Nizolar">{driver.dispute_count ?? 0}</DetailItem>
              <div className="md:col-span-4 rounded-[12px] border border-border bg-card p-5 text-sm text-secondary-foreground">Biriktirilgan so'nggi buyurtmalar endpointi hali mavjud emas.</div>
            </section>
          )}

          {tab === "audit" && (
            <div className="rounded-[12px] border border-border bg-card p-5 text-sm text-secondary-foreground">Audit yozuvlari Audit jurnali modulida mavjud. Haydovchiga alohida audit endpointi hali mavjud emas.</div>
          )}
        </div>
      </aside>

      {modal === "approve" && <ApproveModal driver={driver} busy={props.busy} onClose={() => setModal(null)} onSubmit={(comment) => { setModal(null); props.onApprove(comment); }} />}
      {modal === "reject" && <ReasonModal title="Haydovchini rad etish" suggestions={rejectReasons} busy={props.busy} submitLabel="Rad etish" onClose={() => setModal(null)} onSubmit={(reason) => { setModal(null); props.onReject(reason); }} />}
      {modal === "block" && <ReasonModal title="Haydovchini bloklash" warning="Haydovchini bloklash mavjudlik va yo'nalishlarni o'chiradi. Faol buyurtmalar qo'lda hal qilinishi kerak bo'lishi mumkin." busy={props.busy} submitLabel="Haydovchini bloklash" onClose={() => setModal(null)} onSubmit={(reason) => { setModal(null); props.onBlock(reason); }} />}
      {previewDocument && <DocumentPreviewModal document={previewDocument} onClose={() => setPreviewDocument(null)} />}
    </>
  );
}

export function AdminDriversPanel({ user }: DriversPanelProps) {
  const [drivers, setDrivers] = useState<AdminDriver[]>([]);
  const [selectedDriver, setSelectedDriver] = useState<AdminDriver | null>(null);
  const [cities, setCities] = useState<City[]>([]);
  const [districts, setDistricts] = useState<District[]>([]);
  const [filters, setFilters] = useState<AdminDriverFilters>({ page: 1, limit: 20 });
  const [draftFilters, setDraftFilters] = useState<AdminDriverFilters>({ page: 1, limit: 20 });
  const [activeTab, setActiveTab] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  async function loadDrivers(nextFilters = filters) {
    setBusy(true);
    setError(null);
    try {
      const response = await getAdminDrivers(nextFilters);
      setDrivers(response.items ?? []);
      setTotal(response.pagination?.total ?? response.items.length);
      setTotalPages(response.pagination?.total_pages ?? 1);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "Ruxsat yo'q" : err instanceof Error ? err.message : "Haydovchilarni yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  async function openDriver(driverId: number) {
    setBusy(true);
    setError(null);
    try {
      setSelectedDriver(await getAdminDriverDetail(driverId));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "Ruxsat yo'q" : err instanceof Error ? err.message : "Haydovchi tafsilotlarini yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadDrivers();
    void getCities({ limit: 100 }).then(setCities).catch(() => setCities([]));
  }, []);

  useEffect(() => {
    const id = Number(draftFilters.city_id);
    if (!id) {
      setDistricts([]);
      return;
    }
    void getDistricts(id, { limit: 100 }).then(setDistricts).catch(() => setDistricts([]));
  }, [draftFilters.city_id]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = { ...filters, search: draftFilters.search, page: 1 };
      if ((draftFilters.search ?? "") !== (filters.search ?? "")) {
        setFilters(next);
        void loadDrivers(next);
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [draftFilters.search]);

  const visibleDrivers = useMemo(() => {
    const q = (filters.search ?? "").trim().toLowerCase();
    return drivers.filter((driver) => {
      if (q && !searchableText(driver).includes(q)) return false;
      if (filters.city_id && !(driver.routes ?? []).some((route) => String(route.from_city?.id) === filters.city_id || String(route.to_city?.id) === filters.city_id)) return false;
      if (filters.district_id && !(driver.routes ?? []).some((route) => String(route.from_district?.id) === filters.district_id || String(route.to_district?.id) === filters.district_id)) return false;
      if (filters.has_documents === "yes" && (driver.documents_count ?? 0) < (driver.required_documents_count ?? 5)) return false;
      if (filters.has_documents === "no" && (driver.documents_count ?? 0) >= (driver.required_documents_count ?? 5)) return false;
      if (filters.has_active_route === "yes" && !(Number(driver.active_routes_count ?? 0) > 0)) return false;
      if (filters.has_active_route === "no" && Number(driver.active_routes_count ?? 0) > 0) return false;
      if (filters.created_from && new Date(driver.created_at ?? 0) < new Date(filters.created_from)) return false;
      if (filters.created_to && new Date(driver.created_at ?? 0) > new Date(`${filters.created_to}T23:59:59`)) return false;
      return true;
    });
  }, [drivers, filters]);

  const summary = useMemo(() => {
    const count = (status: string) => visibleDrivers.filter((driver) => driver.verification_status === status).length;
    return [
      ["Jami haydovchilar", visibleDrivers.length, Truck],
      ["Yangi", count("new"), User],
      ["Ko'rib chiqish kutilmoqda", count("pending"), ClipboardList],
      ["Tasdiqlangan", count("approved"), BadgeCheck],
      ["Rad etilgan", count("rejected"), X],
      ["Bloklangan", count("blocked"), Ban],
      ["Mavjud haydovchilar", visibleDrivers.filter((driver) => driver.verification_status === "approved" && driver.is_available).length, Car],
    ] as const;
  }, [visibleDrivers]);

  function applyFilters() {
    const tab = driverTabs.find((item) => item.key === activeTab);
    const next = {
      ...draftFilters,
      page: 1,
      verification_status: tab?.status ?? draftFilters.verification_status,
    };
    setFilters(next);
    void loadDrivers(next);
  }

  function clearFilters() {
    const next = { page: 1, limit: filters.limit ?? 20 };
    setActiveTab("all");
    setDraftFilters(next);
    setFilters(next);
    void loadDrivers(next);
  }

  function changeTab(tab: DriverTab) {
    setActiveTab(tab.key);
    const next = { ...filters, page: 1, verification_status: tab.status };
    setDraftFilters((current) => ({ ...current, verification_status: tab.status, page: 1 }));
    setFilters(next);
    void loadDrivers(next);
  }

  function setPage(page: number) {
    const next = { ...filters, page };
    setFilters(next);
    setDraftFilters((current) => ({ ...current, page }));
    void loadDrivers(next);
  }

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      if (selectedDriver) setSelectedDriver(await getAdminDriverDetail(selectedDriver.id));
      await loadDrivers();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "Ruxsat yo'q" : err instanceof Error ? err.message : "Amal bajarilmadi");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Haydovchilar</h2>
          <p className="mt-1 text-sm text-muted-foreground">Haydovchi profillari, hujjatlari, yo'nalishlari va tekshiruvini boshqaring</p>
        </div>
        <Button disabled={busy} onClick={() => void loadDrivers()}><RefreshCw size={16} /> Yangilash</Button>
      </section>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">{error}</div>}

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-7">
        {summary.map(([label, count, Icon]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
              <Icon size={16} className="text-slate-400" />
            </div>
            <p className="mt-3 text-2xl font-bold text-foreground">{count}</p>
          </div>
        ))}
      </section>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="mb-4 flex flex-wrap gap-2">
          {driverTabs.map((tab) => (
            <button key={tab.key} onClick={() => changeTab(tab)} className={`el-press rounded-[10px] border px-3 py-2 text-sm font-semibold ${activeTab === tab.key ? "border-primary bg-accent text-primary" : "border-border bg-card text-secondary-foreground hover:bg-slate-50"}`}>{tab.label}</button>
          ))}
        </div>
        <div className="grid gap-3 lg:grid-cols-4 xl:grid-cols-6">
          <Input label="Qidirish" value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder="Ism, telefon yoki raqam" />
          <Select label="Tekshiruv holati" value={draftFilters.verification_status ?? ""} onChange={(verification_status) => setDraftFilters({ ...draftFilters, verification_status })}>
            <option value="">Barchasi</option>
            {driverTabs.filter((tab) => tab.status).map((tab) => <option key={tab.key} value={tab.status}>{tab.label}</option>)}
          </Select>
          <Select label="Mavjudlik" value={draftFilters.is_available ?? ""} onChange={(is_available) => setDraftFilters({ ...draftFilters, is_available })}>
            <option value="">Istalgan</option>
            <option value="available">Mavjud</option>
            <option value="unavailable">Mavjud emas</option>
          </Select>
          <Select label="Hudud" value={draftFilters.city_id ?? ""} onChange={(city_id) => setDraftFilters({ ...draftFilters, city_id, district_id: "" })}>
            <option value="">Barchasi</option>
            {cities.map((city) => <option key={city.id} value={city.id}>{city.name_uz}</option>)}
          </Select>
          <Select label="Tuman" value={draftFilters.district_id ?? ""} onChange={(district_id) => setDraftFilters({ ...draftFilters, district_id })}>
            <option value="">Barchasi</option>
            {districts.map((district) => <option key={district.id} value={district.id}>{district.name_uz}</option>)}
          </Select>
          <Select label="Hujjatlari bor" value={draftFilters.has_documents ?? ""} onChange={(has_documents) => setDraftFilters({ ...draftFilters, has_documents })}>
            <option value="">Istalgan</option>
            <option value="yes">To'liq</option>
            <option value="no">Yetishmaydi</option>
          </Select>
          <Select label="Faol yo'nalishi bor" value={draftFilters.has_active_route ?? ""} onChange={(has_active_route) => setDraftFilters({ ...draftFilters, has_active_route })}>
            <option value="">Istalgan</option>
            <option value="yes">Ha</option>
            <option value="no">Yo'q</option>
          </Select>
          <Input label="Sanadan" value={draftFilters.created_from ?? ""} onChange={(created_from) => setDraftFilters({ ...draftFilters, created_from })} type="date" />
          <Input label="Sanagacha" value={draftFilters.created_to ?? ""} onChange={(created_to) => setDraftFilters({ ...draftFilters, created_to })} type="date" />
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
          <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                {["Haydovchi", "Telefon", "Transport", "Raqam", "Tekshiruv", "Mavjudlik", "Hujjatlar", "Yo'nalishlar", "Buyurtmalar", "Yaratilgan", "Amallar"].map((label) => (
                  <th key={label} className="px-4 py-3 font-semibold">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {busy && !drivers.length ? Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={11} className="px-4 py-3"><div className="h-8 animate-pulse rounded bg-background" /></td></tr>
              )) : visibleDrivers.length ? visibleDrivers.map((driver) => (
                <tr key={driver.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <p className="font-bold text-foreground">{driverName(driver)}</p>
                    <p className="text-xs text-muted-foreground">Haydovchi #{driver.id}</p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-semibold text-secondary-foreground">{driverPhone(driver)}</p>
                    {driver.user?.is_phone_verified && <p className="text-xs text-success">Tasdiqlangan</p>}
                  </td>
                  <td className="px-4 py-3">
                    <p>{value(driver.car_model)}</p>
                    <p className="text-xs text-muted-foreground">{value(driver.car_color)}</p>
                  </td>
                  <td className="px-4 py-3 font-semibold text-secondary-foreground">{value(driver.plate_number)}</td>
                  <td className="px-4 py-3"><Badge className={getDriverVerificationBadgeClass(driver.verification_status)}>{getDriverVerificationLabel(driver.verification_status)}</Badge></td>
                  <td className="px-4 py-3"><Badge className={getAvailabilityBadgeClass(driver.is_available, driver.verification_status)}>{getAvailabilityLabel(driver.is_available, driver.verification_status)}</Badge></td>
                  <td className="px-4 py-3">{driver.documents_count ?? 0}/{driver.required_documents_count ?? 5} yuklangan</td>
                  <td className="px-4 py-3">{driver.active_routes_count ?? 0} faol / {driver.total_routes_count ?? 0} jami</td>
                  <td className="px-4 py-3">Faol: {driver.active_orders_count ?? 0} · Yakunlangan: {driver.completed_orders ?? 0}</td>
                  <td className="px-4 py-3">{formatShortAdminDate(driver.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => void openDriver(driver.id)}><Eye size={15} /> Ko'rish</Button>
                      {canApproveDriver(driver, user) && <Button tone="primary" disabled={busy} onClick={() => void openDriver(driver.id).then(() => undefined)}><BadgeCheck size={15} /> Tasdiqlash</Button>}
                    </div>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={11} className="px-4 py-14 text-center">
                    <Truck size={32} className="mx-auto text-slate-300" />
                    <p className="mt-3 font-semibold text-secondary-foreground">Haydovchilar topilmadi</p>
                    <p className="mt-1 text-sm text-muted-foreground">Filtrlarni tozalab yoki ro'yxatni yangilab ko'ring.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm text-secondary-foreground">
          <span>Page {filters.page ?? 1} of {totalPages || 1} · {total} jami</span>
          <div className="flex gap-2">
            <Button disabled={busy || (filters.page ?? 1) <= 1} onClick={() => setPage(Math.max(1, (filters.page ?? 1) - 1))}><ChevronLeft size={15} /> Oldingi</Button>
            <Button disabled={busy || (filters.page ?? 1) >= (totalPages || 1)} onClick={() => setPage((filters.page ?? 1) + 1)}>Keyingi <ChevronRight size={15} /></Button>
          </div>
        </footer>
      </section>

      {selectedDriver && (
        <DriverDrawer
          driver={selectedDriver}
          user={user}
          busy={busy}
          onClose={() => setSelectedDriver(null)}
          onRefresh={() => void openDriver(selectedDriver.id)}
          onApprove={(comment) => void mutate(() => approveDriver(selectedDriver.id, { comment }))}
          onReject={(reason) => void mutate(() => rejectDriver(selectedDriver.id, { reason }))}
          onBlock={(reason) => void mutate(() => blockDriver(selectedDriver.id, { reason }))}
        />
      )}
    </div>
  );
}
