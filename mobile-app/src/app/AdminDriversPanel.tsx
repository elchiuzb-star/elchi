/**
 * Haydovchilar (v1, DESIGN-ADMIN-DIFF §17): driver profiles, documents, routes, orders and the verification
 * decisions. Approve / reject / block / unblock are admin+ on the server; the operator may only correct the
 * vehicle (Q94) - the buttons follow the same split so nobody is offered an action the server would refuse.
 */
import { useEffect, useMemo, useState } from "react";
import {
  BadgeCheck,
  Ban,
  Car,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Eye,
  FileText,
  RefreshCw,
  Truck,
  Unlock,
  User,
  X,
} from "./ui/icons";

import {
  approveDriver,
  blockDriver,
  getAdminDriverDetail,
  getAdminDriverOrders,
  getAdminDrivers,
  rejectDriver,
  unblockDriver,
  updateDriverVehicle,
} from "../api/admin-drivers.api";
import { getCities } from "../api/cities.api";
import { getDistricts } from "../api/districts.api";
import type { MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import type { AdminDriver, AdminDriverDocument, AdminDriverFilters } from "../types/admin-driver";
import type { AdminOrder } from "../types/admin-order";
import type { AuthUser } from "../types/auth";
import type { City, District } from "../types/city";
import { adminErrorMessage, adminOrderStatusLabel } from "../utils/adminUserLabels";
import {
  canApproveDriver,
  canBlockDriver,
  canEditDriverVehicle,
  canRejectDriver,
  canUnblockDriver,
  driverDocumentLabel,
  driverDocumentStateClass,
  driverDocumentStateLabel,
  getAvailabilityBadgeClass,
  getAvailabilityLabel,
  getDriverVerificationBadgeClass,
  getDriverVerificationLabel,
  getMissingDriverDocuments,
  requiredDriverDocuments,
} from "../utils/driverStatus";
import { formatAdminMoney } from "../utils/money";
import { statusToneClass } from "../utils/orderStatus";
import { formatDate, formatDateTime } from "../utils/v2Format";

type DriversPanelProps = {
  user: AuthUser;
  /** From the global search or the overview: a name/phone to search, or `id:<driver_id>` to open that driver. */
  initialSearch?: string;
};

type DriverTab = {
  key: string;
  label: MessageKey;
  status?: string;
};

const driverTabs: DriverTab[] = [
  { key: "all", label: "admin.common.all" },
  { key: "new", label: "app.driverVerification.new", status: "new" },
  { key: "pending", label: "admin.drivers.pending", status: "pending" },
  { key: "approved", label: "status.approved", status: "approved" },
  { key: "rejected", label: "status.rejected", status: "rejected" },
  { key: "blocked", label: "admin.common.blocked", status: "blocked" },
];

const rejectReasons: MessageKey[] = [
  "admin.drivers.rejectReason.unclear",
  "admin.drivers.missingDocs",
  "admin.drivers.rejectReason.vehicle",
  "admin.drivers.rejectReason.other",
];

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

function TextArea(props: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {props.label}
      <textarea
        value={props.value}
        rows={3}
        placeholder={props.placeholder}
        onChange={(event) => props.onChange(event.target.value)}
        className="min-h-[84px] rounded-[10px] border border-border bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
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

function driverName(driver: AdminDriver, fallback: string) {
  return driver.full_name ?? driver.user?.full_name ?? fallback;
}

function driverPhone(driver: AdminDriver) {
  return driver.phone ?? driver.user?.phone ?? "-";
}

function routeName(route: NonNullable<AdminDriver["routes"]>[number]) {
  const from = [route.from_city?.name_uz, route.from_district?.name_uz].filter(Boolean).join(" / ");
  const to = [route.to_city?.name_uz, route.to_district?.name_uz].filter(Boolean).join(" / ");
  return `${from || "-"} → ${to || "-"}`;
}

const ROUTE_STATUS_KEYS: Record<string, MessageKey> = {
  available: "admin.drivers.isAvailable",
  unavailable: "admin.drivers.unavailable",
  busy: "admin.drivers.routeBusy",
};

function searchableText(driver: AdminDriver) {
  return [
    driver.id,
    driver.full_name,
    driver.user?.full_name,
    driverPhone(driver),
    driver.plate_number,
    driver.car_model,
    driver.verification_status,
    ...(driver.routes ?? []).flatMap((route) => [route.from_city?.name_uz, route.to_city?.name_uz, route.from_district?.name_uz, route.to_district?.name_uz]),
  ].filter(Boolean).join(" ").toLowerCase();
}

/** `id:<n>` opens that driver; anything else is a search text. */
export function parseDriverTarget(initial?: string): { openId: number | null; search: string } {
  const match = /^id:(\d+)$/.exec(initial ?? "");
  if (match) return { openId: Number(match[1]), search: "" };
  return { openId: null, search: initial ?? "" };
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
  const t = useT();
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-foreground/40 p-4">
      <section role="dialog" aria-modal="true" aria-label={props.title} className="w-full max-w-md rounded-[12px] border border-border bg-card shadow-xl">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-base font-bold text-foreground">{props.title}</h3>
          <button type="button" onClick={props.onClose} className="el-press rounded-[10px] p-1 text-muted-foreground hover:bg-muted" aria-label={t("common.close")}>
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
  const t = useT();
  const [comment, setComment] = useState("");
  const missing = getMissingDriverDocuments(props.driver.documents);
  return (
    <ModalShell title={t("admin.drivers.approveTitle")} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <div className="rounded-[10px] border border-border bg-slate-50 p-3 text-sm">
          <p className="font-bold text-foreground">{driverName(props.driver, t("admin.drivers.profileIncomplete"))}</p>
          <p className="text-muted-foreground">{driverPhone(props.driver)}</p>
        </div>
        {missing.length ? (
          <div className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm text-warning">
            <p className="font-bold">{t("admin.drivers.missingDocs")}</p>
            <p className="mt-1">{t("admin.drivers.missingList", { list: missing.map((item) => driverDocumentLabel(item)).join(", ") })}</p>
          </div>
        ) : (
          <div className="rounded-[10px] border border-success/25 bg-success/12 p-3 text-sm font-medium text-success">{t("admin.drivers.allDocs")}</div>
        )}
        <TextArea label={t("bookingCancel.commentLabel")} value={comment} onChange={setComment} />
        <p className="text-xs text-muted-foreground">{t("admin.drivers.approveNotActive")}</p>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button tone="primary" disabled={props.busy} onClick={() => props.onSubmit(comment)}>{t("common.confirm")}</Button>
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
  minLength?: number;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const t = useT();
  const [reason, setReason] = useState("");
  const min = props.minLength ?? 1;
  return (
    <ModalShell title={props.title} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        {props.warning && <div className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm font-medium text-warning">{props.warning}</div>}
        {props.suggestions && (
          <div className="flex flex-wrap gap-2">
            {props.suggestions.map((suggestion) => (
              <button key={suggestion} type="button" onClick={() => setReason(suggestion)} className="el-press rounded-full border border-border px-3 py-1 text-xs font-semibold text-secondary-foreground hover:bg-slate-50">
                {suggestion}
              </button>
            ))}
          </div>
        )}
        <TextArea label={min >= 3 ? t("admin.common.reasonMin3") : `${t("common.reason")} *`} value={reason} onChange={setReason} placeholder={t("admin.common.reasonRequired")} />
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button tone={props.tone ?? "danger"} disabled={props.busy || reason.trim().length < min} onClick={() => props.onSubmit(reason.trim())}>{props.submitLabel}</Button>
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
  const t = useT();
  const url = document.file_url;
  const title = t("admin.drivers.docTitle", { name: driverDocumentLabel(document.document_type) });
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-foreground/70 p-4">
      <section role="dialog" aria-modal="true" aria-label={title} className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-[12px] border border-border bg-card shadow-2xl">
        <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h3 className="text-base font-bold text-foreground">{title}</h3>
            <p className="text-xs text-muted-foreground">{document.created_at ? t("admin.drivers.uploadedAt", { date: formatDateTime(document.created_at) }) : t("docState.missing")}</p>
          </div>
          <div className="flex items-center gap-2">
            {url && <a href={url} target="_blank" rel="noreferrer" className="rounded-[10px] border border-border px-3 py-2 text-sm font-semibold text-secondary-foreground hover:bg-slate-50">{t("admin.drivers.openNewTab")}</a>}
            <button type="button" onClick={onClose} className="el-press rounded-[10px] border border-border px-3 py-2 text-sm font-semibold text-secondary-foreground hover:bg-slate-50">
              {t("common.close")}
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-auto bg-background p-4">
          {!url ? (
            <div className="rounded-[12px] border border-border bg-card p-10 text-center text-sm text-muted-foreground">{t("docState.missing")}</div>
          ) : isImageFile(url) ? (
            <img src={url} alt={title} className="mx-auto max-h-[76vh] max-w-full rounded-[10px] bg-card object-contain shadow-sm" />
          ) : isPdfFile(url) ? (
            <iframe src={url} title={title} className="h-[76vh] w-full rounded-[10px] border border-border bg-card" />
          ) : (
            <div className="rounded-[12px] border border-border bg-card p-10 text-center">
              <FileText size={36} className="mx-auto text-slate-400" />
              <p className="mt-3 text-sm font-semibold text-secondary-foreground">{t("admin.drivers.cannotPreview")}</p>
              <a href={url} target="_blank" rel="noreferrer" className="mt-4 inline-flex rounded-[10px] bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary">{t("admin.drivers.openFile")}</a>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function DocumentCard({ document, onPreview }: { document: AdminDriverDocument; onPreview: (document: AdminDriverDocument) => void }) {
  const t = useT();
  const isImage = isImageFile(document.file_url);
  return (
    <div className="rounded-[12px] border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-bold text-foreground">{driverDocumentLabel(document.document_type)}</p>
          {document.created_at && <p className="mt-1 text-xs text-muted-foreground">{t("admin.drivers.uploadedAt", { date: formatDateTime(document.created_at) })}</p>}
        </div>
        <Badge className={driverDocumentStateClass(document.status)}>{driverDocumentStateLabel(document.status)}</Badge>
      </div>
      {isImage && document.file_url && (
        <button type="button" onClick={() => onPreview(document)} className="el-press mt-3 block w-full overflow-hidden rounded-[10px] border border-border text-left hover:border-blue-300">
          <img src={document.file_url} alt={driverDocumentLabel(document.document_type)} className="h-28 w-full object-cover" />
        </button>
      )}
      {document.file_url && (
        <button type="button" onClick={() => onPreview(document)} className="el-press mt-3 inline-flex h-9 items-center rounded-[10px] border border-border px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50">{t("admin.drivers.viewDoc")}</button>
      )}
      {document.rejection_reason && <p className="mt-2 text-sm text-destructive">{t("admin.drivers.reasonLine", { reason: document.rejection_reason })}</p>}
    </div>
  );
}

/**
 * Q94: the driver enters the car once, so this is the only place it can change afterwards.
 *
 * Every field is pre-filled with what is on record and sent only when it was actually edited - a PATCH that
 * repeats the current plate would still take the plate-uniqueness path on the server for no reason, and an
 * audit row that says "plate changed" when it did not is worse than no row.
 */
function VehicleModal(props: {
  driver: AdminDriver;
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: { full_name?: string; car_model?: string; plate_number?: string; car_color?: string }) => void;
}) {
  const t = useT();
  const [fullName, setFullName] = useState(props.driver.full_name ?? "");
  const [carModel, setCarModel] = useState(props.driver.car_model ?? "");
  const [carColor, setCarColor] = useState(props.driver.car_color ?? "");
  const [plate, setPlate] = useState(props.driver.plate_number ?? "");
  const changed = {
    ...(fullName.trim() && fullName.trim() !== (props.driver.full_name ?? "") ? { full_name: fullName.trim() } : {}),
    ...(carModel.trim() !== (props.driver.car_model ?? "") ? { car_model: carModel.trim() } : {}),
    ...(carColor.trim() !== (props.driver.car_color ?? "") ? { car_color: carColor.trim() } : {}),
    ...(plate.trim() !== (props.driver.plate_number ?? "") ? { plate_number: plate.trim() } : {}),
  };
  const nothingToSend = Object.keys(changed).length === 0;
  return (
    <ModalShell title={t("admin.drivers.vehicleTitle")} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <p className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm text-warning">{t("admin.drivers.vehicleWarn")}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label={t("admin.drivers.fullName")} value={fullName} onChange={setFullName} />
          <Input label={t("driverProfileForm.carModel")} value={carModel} onChange={setCarModel} />
          <Input label={t("driverProfileForm.carColor")} value={carColor} onChange={setCarColor} />
          <Input label={t("driverProfileForm.plateNumber")} value={plate} onChange={setPlate} />
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={props.onClose}>{t("common.cancel")}</Button>
          <Button tone="primary" disabled={props.busy || nothingToSend} onClick={() => props.onSubmit(changed)}>
            {t("common.save")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function DriverOrders({ driverId }: { driverId: number }) {
  const t = useT();
  const [orders, setOrders] = useState<AdminOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getAdminDriverOrders(driverId)
      .then((items) => { if (alive) setOrders(items); })
      .catch((err) => { if (alive) { setOrders([]); setError(adminErrorMessage(err, "admin.orders.loadFailed")); } });
    return () => { alive = false; };
  }, [driverId]);
  if (error) return <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">{error}</div>;
  if (!orders) return <div className="rounded-[12px] border border-border bg-card p-6 text-sm text-muted-foreground">{t("common.loading")}</div>;
  if (!orders.length) return <div className="rounded-[12px] border border-border bg-card p-10 text-center text-sm text-muted-foreground">{t("admin.drivers.noOrders")}</div>;
  return (
    <div className="max-w-full overflow-x-auto rounded-[12px] border border-border bg-card">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2">{t("admin.overview.colOrder")}</th>
            <th className="px-3 py-2">{t("admin.common.status")}</th>
            <th className="px-3 py-2">{t("admin.common.route")}</th>
            <th className="px-3 py-2">{t("admin.orders.finalPrice")}</th>
            <th className="px-3 py-2">{t("admin.common.created")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-muted">
          {orders.map((order) => (
            <tr key={order.id}>
              <td className="px-3 py-2 font-mono text-xs font-semibold">{order.order_number ?? `#${order.id}`}</td>
              <td className="px-3 py-2"><span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${statusToneClass(order.status)}`}>{adminOrderStatusLabel(order.status)}</span></td>
              <td className="px-3 py-2">{order.from_city?.name_uz ?? "-"} → {order.to_city?.name_uz ?? "-"}</td>
              <td className="px-3 py-2">{formatAdminMoney(order.final_price)}</td>
              <td className="px-3 py-2">{formatDateTime(order.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
  onUnblock: (reason: string) => void;
  onVehicle: (payload: { full_name?: string; car_model?: string; plate_number?: string; car_color?: string }) => void;
}) {
  const t = useT();
  const [tab, setTab] = useState<"overview" | "documents" | "routes" | "orders" | "audit">("overview");
  const [modal, setModal] = useState<"approve" | "reject" | "block" | "unblock" | "vehicle" | null>(null);
  const [previewDocument, setPreviewDocument] = useState<AdminDriverDocument | null>(null);
  const driver = props.driver;
  const uploaded = new Map((driver.documents ?? []).map((document) => [document.document_type, document]));
  const documents = requiredDriverDocuments.map((documentType) => uploaded.get(documentType) ?? { document_type: documentType, status: "missing" as const });
  const name = driverName(driver, t("admin.drivers.profileIncomplete"));
  const anyAction = canApproveDriver(driver, props.user) || canRejectDriver(driver, props.user) || canBlockDriver(driver, props.user)
    || canUnblockDriver(driver, props.user) || canEditDriverVehicle(props.user);
  return (
    <>
      {/* The scrim is decoration: it closes the drawer as a convenience, and the drawer itself carries the
          dialog semantics and a real close button. */}
      <div className="fixed inset-0 z-50 bg-foreground/30" role="presentation" onClick={props.onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={name}
        className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-3xl flex-col border-l border-border bg-slate-50 shadow-2xl"
      >
        <header className="border-b border-border bg-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-foreground">{name}</h2>
                <Badge className={getDriverVerificationBadgeClass(driver.verification_status)}>{getDriverVerificationLabel(driver.verification_status)}</Badge>
                <Badge className={getAvailabilityBadgeClass(driver.is_available, driver.verification_status)}>{getAvailabilityLabel(driver.is_available, driver.verification_status)}</Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("admin.drivers.drawerSub", { phone: driverPhone(driver), created: formatDate(driver.created_at), updated: formatDate(driver.updated_at) })}
              </p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button onClick={props.onRefresh}><RefreshCw size={15} /> {t("support.refresh")}</Button>
              <Button onClick={props.onClose}><X size={15} /> {t("common.close")}</Button>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {canApproveDriver(driver, props.user) && <Button tone="primary" disabled={props.busy} onClick={() => setModal("approve")}><BadgeCheck size={15} /> {t("common.confirm")}</Button>}
            {canRejectDriver(driver, props.user) && <Button tone="danger" disabled={props.busy} onClick={() => setModal("reject")}><X size={15} /> {t("admin.common.reject")}</Button>}
            {canBlockDriver(driver, props.user) && <Button tone="danger" disabled={props.busy} onClick={() => setModal("block")}><Ban size={15} /> {t("blockReport.block")}</Button>}
            {canUnblockDriver(driver, props.user) && <Button disabled={props.busy} onClick={() => setModal("unblock")}><Unlock size={15} /> {t("blockReport.unblock")}</Button>}
            {/* Operators may edit the vehicle as well as admins - that is what the server allows (Q94), and they
                are the ones the driver reaches first. */}
            {canEditDriverVehicle(props.user) && <Button disabled={props.busy} onClick={() => setModal("vehicle")}><Car size={15} /> {t("admin.drivers.changeVehicle")}</Button>}
            {!anyAction && <span className="rounded-[10px] bg-background px-3 py-2 text-sm font-semibold text-muted-foreground">{t("admin.drivers.noActions")}</span>}
          </div>
          <div className="mt-4 flex gap-2 overflow-x-auto border-b border-border">
            {([
              ["overview", "admin.orders.tab.overview"],
              ["documents", "driverDocs.title"],
              ["routes", "app.nav.routes"],
              ["orders", "orders.title"],
              ["audit", "admin.orders.tab.audit"],
            ] as Array<[typeof tab, MessageKey]>).map(([key, label]) => (
              <button key={key} type="button" onClick={() => setTab(key)} className={`el-press whitespace-nowrap border-b-2 px-3 py-2 text-sm font-semibold ${tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{t(label)}</button>
            ))}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {tab === "overview" && (
            <div className="grid min-w-0 gap-5">
              <section className="grid gap-3 md:grid-cols-3">
                <DetailItem label={t("admin.drivers.fullName")}>{value(driver.full_name ?? driver.user?.full_name)}</DetailItem>
                <DetailItem label={t("admin.common.phone")}>{value(driverPhone(driver))}</DetailItem>
                <DetailItem label={t("driverProfileForm.carModel")}>{value(driver.car_model)}</DetailItem>
                <DetailItem label={t("driverProfileForm.carColor")}>{value(driver.car_color)}</DetailItem>
                <DetailItem label={t("driverProfileForm.plateNumber")}>{value(driver.plate_number)}</DetailItem>
                <DetailItem label={t("admin.drivers.plateNormalized")}>{value(driver.plate_number_normalized)}</DetailItem>
                <DetailItem label={t("driverProfile.rating")}>{value(driver.rating)}</DetailItem>
                <DetailItem label={t("admin.overview.totalOrders")}>{value(driver.total_orders)}</DetailItem>
                <DetailItem label={t("admin.overview.completedOrders")}>{value(driver.completed_orders)}</DetailItem>
                <DetailItem label={t("admin.drivers.cancelledOrders")}>{value(driver.cancelled_orders)}</DetailItem>
                <DetailItem label={t("admin.drivers.disputes")}>{value(driver.dispute_count)}</DetailItem>
                <DetailItem label={t("admin.drivers.availability")}>{getAvailabilityLabel(driver.is_available, driver.verification_status)}</DetailItem>
              </section>
              <section className="grid gap-3 md:grid-cols-3">
                <DetailItem label={t("driverDocs.title")}>{t("admin.drivers.docsUploaded", { done: driver.documents_count ?? 0, total: driver.required_documents_count ?? 5 })}</DetailItem>
                <DetailItem label={t("app.nav.routes")}>{t("admin.drivers.routesCount", { active: driver.active_routes_count ?? 0, total: driver.total_routes_count ?? 0 })}</DetailItem>
                <DetailItem label={t("admin.drivers.activeOrders")}>{driver.active_orders_count ?? 0}</DetailItem>
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
                    <Badge className={route.status === "available" ? "border-success/25 bg-success/12 text-success" : route.status === "busy" ? "border-blue-200 bg-accent text-primary" : "border-border bg-slate-50 text-secondary-foreground"}>
                      {ROUTE_STATUS_KEYS[route.status] ? t(ROUTE_STATUS_KEYS[route.status]) : route.status}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{t("admin.drivers.routeMeta", { created: formatDateTime(route.created_at) })}</p>
                </div>
              )) : <div className="rounded-[12px] border border-border bg-card p-10 text-center text-sm text-muted-foreground">{t("admin.drivers.noRoutes")}</div>}
            </section>
          )}

          {tab === "orders" && <DriverOrders driverId={driver.id} />}

          {tab === "audit" && (
            <div className="rounded-[12px] border border-border bg-card p-5 text-sm text-secondary-foreground">{t("admin.drivers.auditHint")}</div>
          )}
        </div>
      </aside>

      {modal === "approve" && <ApproveModal driver={driver} busy={props.busy} onClose={() => setModal(null)} onSubmit={(comment) => { setModal(null); props.onApprove(comment); }} />}
      {modal === "reject" && <ReasonModal title={t("admin.drivers.rejectTitle")} suggestions={rejectReasons.map((key) => t(key))} busy={props.busy} submitLabel={t("admin.common.reject")} onClose={() => setModal(null)} onSubmit={(reason) => { setModal(null); props.onReject(reason); }} />}
      {modal === "vehicle" && <VehicleModal driver={driver} busy={props.busy} onClose={() => setModal(null)} onSubmit={(payload) => { setModal(null); props.onVehicle(payload); }} />}
      {modal === "block" && <ReasonModal title={t("admin.drivers.blockTitle")} warning={t("admin.drivers.blockWarn")} busy={props.busy} minLength={3} submitLabel={t("blockReport.block")} onClose={() => setModal(null)} onSubmit={(reason) => { setModal(null); props.onBlock(reason); }} />}
      {modal === "unblock" && <ReasonModal title={t("admin.drivers.unblockTitle")} warning={t("admin.drivers.unblockWarn")} busy={props.busy} minLength={3} tone="primary" submitLabel={t("blockReport.unblock")} onClose={() => setModal(null)} onSubmit={(reason) => { setModal(null); props.onUnblock(reason); }} />}
      {previewDocument && <DocumentPreviewModal document={previewDocument} onClose={() => setPreviewDocument(null)} />}
    </>
  );
}

export function AdminDriversPanel({ user, initialSearch }: DriversPanelProps) {
  const t = useT();
  const target = parseDriverTarget(initialSearch);
  const [drivers, setDrivers] = useState<AdminDriver[]>([]);
  const [selectedDriver, setSelectedDriver] = useState<AdminDriver | null>(null);
  const [cities, setCities] = useState<City[]>([]);
  const [districts, setDistricts] = useState<District[]>([]);
  const [filters, setFilters] = useState<AdminDriverFilters>({ page: 1, limit: 20, search: target.search || undefined });
  const [draftFilters, setDraftFilters] = useState<AdminDriverFilters>({ page: 1, limit: 20, search: target.search || undefined });
  const [activeTab, setActiveTab] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
      setError(adminErrorMessage(err, "admin.drivers.loadFailed"));
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
      setError(adminErrorMessage(err, "admin.drivers.detailFailed"));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadDrivers();
    void getCities({ limit: 100 }).then(setCities).catch(() => setCities([]));
    if (target.openId) void openDriver(target.openId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      ["admin.drivers.total", visibleDrivers.length, Truck, ""],
      ["app.driverVerification.new", count("new"), User, ""],
      ["admin.drivers.pending", count("pending"), ClipboardList, "text-warning"],
      ["status.approved", count("approved"), BadgeCheck, "text-success"],
      ["status.rejected", count("rejected"), X, ""],
      ["admin.common.blocked", count("blocked"), Ban, "text-destructive"],
      ["admin.drivers.available", visibleDrivers.filter((driver) => driver.verification_status === "approved" && driver.is_available).length, Car, ""],
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
    setNotice(null);
    try {
      const result = await action();
      // Unblock lifts the v1 block only; a remaining v2 eligibility block is said out loud (Q15).
      if (result && typeof result === "object" && (result as { v2_eligibility_blocked?: boolean }).v2_eligibility_blocked) {
        setNotice(t("admin.drivers.v2StillBlocked"));
      }
      if (selectedDriver) setSelectedDriver(await getAdminDriverDetail(selectedDriver.id));
      await loadDrivers();
    } catch (err) {
      setError(adminErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const anyOption = <option value="">{t("admin.common.any")}</option>;
  const allOption = <option value="">{t("admin.common.all")}</option>;

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.nav.drivers")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("admin.drivers.subtitle")}</p>
        </div>
        <Button disabled={busy} onClick={() => void loadDrivers()}><RefreshCw size={16} /> {t("support.refresh")}</Button>
      </section>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">{error}</div>}
      {notice && <div className="rounded-[12px] border border-warning/28 bg-warning/14 px-4 py-3 text-sm font-medium text-warning">{notice}</div>}

      <section className="grid gap-3 sm:grid-cols-2 md:grid-cols-4 xl:grid-cols-7">
        {summary.map(([label, count, Icon, tone]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-semibold text-muted-foreground">{t(label)}</p>
              <Icon size={16} className="shrink-0 text-slate-400" />
            </div>
            <p className={`mt-3 text-2xl font-bold ${tone || "text-foreground"}`}>{count}</p>
          </div>
        ))}
      </section>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="mb-4 flex flex-wrap gap-2">
          {driverTabs.map((tab) => (
            <button key={tab.key} type="button" onClick={() => changeTab(tab)} className={`el-press rounded-full border px-3 py-1.5 text-sm font-semibold ${activeTab === tab.key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-secondary-foreground hover:bg-slate-50"}`}>{t(tab.label)}</button>
          ))}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <Input label={t("location.search")} value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder={t("admin.drivers.searchPh")} />
          <Select label={t("admin.drivers.verification")} value={draftFilters.verification_status ?? ""} onChange={(verification_status) => setDraftFilters({ ...draftFilters, verification_status })}>
            {allOption}
            {driverTabs.filter((tab) => tab.status).map((tab) => <option key={tab.key} value={tab.status}>{t(tab.label)}</option>)}
          </Select>
          <Select label={t("admin.drivers.availability")} value={draftFilters.is_available ?? ""} onChange={(is_available) => setDraftFilters({ ...draftFilters, is_available })}>
            {allOption}
            <option value="available">{t("admin.drivers.isAvailable")}</option>
            <option value="unavailable">{t("admin.drivers.unavailable")}</option>
          </Select>
          <Select label={t("admin.drivers.region")} value={draftFilters.city_id ?? ""} onChange={(city_id) => setDraftFilters({ ...draftFilters, city_id, district_id: "" })}>
            {allOption}
            {cities.map((city) => <option key={city.id} value={city.id}>{city.name_uz}</option>)}
          </Select>
          <Select label={t("admin.drivers.district")} value={draftFilters.district_id ?? ""} onChange={(district_id) => setDraftFilters({ ...draftFilters, district_id })}>
            {allOption}
            {districts.map((district) => <option key={district.id} value={district.id}>{district.name_uz}</option>)}
          </Select>
          <Select label={t("admin.drivers.hasDocs")} value={draftFilters.has_documents ?? ""} onChange={(has_documents) => setDraftFilters({ ...draftFilters, has_documents })}>
            {anyOption}
            <option value="yes">{t("admin.drivers.docsComplete")}</option>
            <option value="no">{t("admin.drivers.docsMissing")}</option>
          </Select>
          <Select label={t("admin.drivers.hasActiveRoute")} value={draftFilters.has_active_route ?? ""} onChange={(has_active_route) => setDraftFilters({ ...draftFilters, has_active_route })}>
            {anyOption}
            <option value="yes">{t("admin.common.yes")}</option>
            <option value="no">{t("common.none")}</option>
          </Select>
          <Input label={t("admin.common.fromDate")} value={draftFilters.created_from ?? ""} onChange={(created_from) => setDraftFilters({ ...draftFilters, created_from })} type="date" />
          <Input label={t("admin.common.toDate")} value={draftFilters.created_to ?? ""} onChange={(created_to) => setDraftFilters({ ...draftFilters, created_to })} type="date" />
          <Select label={t("admin.common.limit")} value={String(draftFilters.limit ?? 20)} onChange={(limit) => setDraftFilters({ ...draftFilters, limit: Number(limit), page: 1 })}>
            {[10, 20, 50, 100].map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button onClick={clearFilters}>{t("admin.common.clearFilters")}</Button>
          <Button tone="primary" disabled={busy} onClick={applyFilters}>{t("admin.common.applyFilters")}</Button>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[1000px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                {([
                  "admin.common.driver",
                  "admin.common.phone",
                  "admin.drivers.colTransport",
                  "admin.drivers.colPlate",
                  "admin.drivers.colCheck",
                  "admin.drivers.availability",
                  "driverDocs.title",
                  "app.nav.routes",
                ] as MessageKey[]).map((key) => (
                  <th key={key} className="px-4 py-3 font-semibold">{t(key)}</th>
                ))}
                <th className="px-4 py-3"><span className="sr-only">{t("admin.common.view")}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {busy && !drivers.length ? Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={9} className="px-4 py-3"><div className="h-8 animate-pulse rounded bg-background" /></td></tr>
              )) : visibleDrivers.length ? visibleDrivers.map((driver) => (
                <tr key={driver.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <p className="font-bold text-foreground">{driverName(driver, t("admin.drivers.profileIncomplete"))}</p>
                    <p className="text-xs text-muted-foreground">{t("admin.drivers.driverNo", { id: driver.id })}</p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-semibold text-secondary-foreground">{driverPhone(driver)}</p>
                    {driver.user?.is_phone_verified && <p className="text-xs text-success">{t("status.approved")}</p>}
                  </td>
                  <td className="px-4 py-3">{[driver.car_model, driver.car_color].filter(Boolean).join(" · ") || "-"}</td>
                  <td className="px-4 py-3 font-mono font-semibold text-secondary-foreground">{value(driver.plate_number)}</td>
                  <td className="px-4 py-3"><Badge className={getDriverVerificationBadgeClass(driver.verification_status)}>{getDriverVerificationLabel(driver.verification_status)}</Badge></td>
                  <td className="px-4 py-3">{getAvailabilityLabel(driver.is_available, driver.verification_status)}</td>
                  <td className="px-4 py-3">{t("admin.drivers.docsUploaded", { done: driver.documents_count ?? 0, total: driver.required_documents_count ?? 5 })}</td>
                  <td className="px-4 py-3">{t("admin.drivers.routesCount", { active: driver.active_routes_count ?? 0, total: driver.total_routes_count ?? 0 })}</td>
                  <td className="px-4 py-3">
                    <Button onClick={() => void openDriver(driver.id)}><Eye size={15} /> {t("admin.common.view")}</Button>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={9} className="px-4 py-14 text-center">
                    <Truck size={32} className="mx-auto text-slate-300" />
                    <p className="mt-3 font-semibold text-secondary-foreground">{t("admin.drivers.empty")}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{t("admin.common.emptyHint")}</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm text-secondary-foreground">
          <span>{t("admin.common.pageOf", { page: filters.page ?? 1, pages: totalPages || 1, total })}</span>
          <div className="flex gap-2">
            <Button disabled={busy || (filters.page ?? 1) <= 1} onClick={() => setPage(Math.max(1, (filters.page ?? 1) - 1))}><ChevronLeft size={15} /> {t("admin.common.prev")}</Button>
            <Button disabled={busy || (filters.page ?? 1) >= (totalPages || 1)} onClick={() => setPage((filters.page ?? 1) + 1)}>{t("admin.common.next")} <ChevronRight size={15} /></Button>
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
          onApprove={(comment) => void mutate(() => approveDriver(selectedDriver.id, { comment: comment.trim() || null }))}
          onReject={(reason) => void mutate(() => rejectDriver(selectedDriver.id, { reason }))}
          onBlock={(reason) => void mutate(() => blockDriver(selectedDriver.id, { reason }))}
          onUnblock={(reason) => void mutate(() => unblockDriver(selectedDriver.id, { reason }))}
          onVehicle={(payload) => void mutate(() => updateDriverVehicle(selectedDriver.id, payload))}
        />
      )}
    </div>
  );
}
