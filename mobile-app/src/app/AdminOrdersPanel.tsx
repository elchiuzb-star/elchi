import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Calendar,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  DollarSign,
  Eye,
  MapPin,
  RefreshCw,
  Search,
  Truck,
  User,
  X,
} from "./ui/icons";

import {
  cancelAdminOrder,
  getAdminOrderDetail,
  getAdminOrders,
  getEligibleDriversForOrder,
  manualAssignDriver,
  manualUpdateOrderStatus,
} from "../api/admin-orders.api";
import { getCities } from "../api/cities.api";
import { getDistricts } from "../api/districts.api";
import { ReadOnlyOrderMap } from "../components/maps/ReadOnlyOrderMap";
import type { MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import type { AdminOrder, AdminOrderBid, AdminOrderFilters, AdminOrderRef } from "../types/admin-order";
import type { AuthUser } from "../types/auth";
import type { City, District } from "../types/city";
import type { OrderStatus } from "../types/order";
import {
  adminBidStatusLabel,
  adminDisputeReasonLabel,
  adminDisputeStatusLabel,
  adminErrorMessage,
  adminOrderStatusLabel as statusLabel,
  adminPaymentLabel,
  adminRoleLabel,
} from "../utils/adminUserLabels";
import { getDriverVerificationLabel } from "../utils/driverStatus";
import { formatAdminMoney } from "../utils/money";
import { manualOrderStatuses, statusToneClass } from "../utils/orderStatus";
import { formatDateTime } from "../utils/v2Format";

type OrdersPanelProps = {
  user: AuthUser;
};

type StatusTab = {
  key: string;
  label: MessageKey;
  statuses?: OrderStatus[];
};

const statusTabs: StatusTab[] = [
  { key: "all", label: "admin.common.all" },
  { key: "published", label: "status.published", statuses: ["published"] },
  { key: "bidding", label: "admin.orders.bids", statuses: ["bidding"] },
  { key: "accepted", label: "admin.orders.accepted", statuses: ["accepted"] },
  { key: "delivery", label: "admin.orders.inTransit", statuses: ["picked_up", "in_transit"] },
  { key: "delivered", label: "admin.orders.delivered", statuses: ["delivered"] },
  { key: "confirmed", label: "status.approved", statuses: ["confirmed"] },
  { key: "cancelled", label: "status.cancelled", statuses: ["cancelled"] },
  { key: "disputed", label: "admin.orders.disputed", statuses: ["disputed"] },
];

/** Q10: force status, assign and cancel through the admin order endpoints are admin+ (`ADMIN_ORDER_MUTATION_ROLES`). */
export function canMutateOrders(role: string): boolean {
  return role === "admin" || role === "super_admin";
}

const timelineStatuses: OrderStatus[] = ["draft", "published", "bidding", "accepted", "picked_up", "in_transit", "delivered", "confirmed"];

function refName(ref?: AdminOrderRef | null): string {
  return ref?.name_uz ?? ref?.full_name ?? ref?.phone ?? "-";
}

function driverName(driver: AdminOrder["assigned_driver"], notAssigned: string): string {
  return driver?.full_name ?? driver?.phone ?? notAssigned;
}

function point(lat?: number | string | null, lng?: number | string | null): string | null {
  return lat && lng ? `${lat}, ${lng}` : null;
}

function textForSearch(order: AdminOrder): string {
  return [
    order.order_number,
    order.client?.phone,
    order.sender_phone,
    order.receiver_phone,
    order.assigned_driver?.full_name,
    order.assigned_driver?.phone,
    order.assigned_driver?.plate_number,
    refName(order.from_city),
    refName(order.to_city),
    refName(order.from_district),
    refName(order.to_district),
  ].filter(Boolean).join(" ").toLowerCase();
}

function statusBadge(status?: string | null) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusToneClass(status)}`}>{statusLabel(status)}</span>;
}

function outlineButtonClass(tone: "neutral" | "primary" | "danger" = "neutral") {
  if (tone === "primary") return "border-primary bg-primary text-primary-foreground hover:bg-primary";
  if (tone === "danger") return "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/25";
  return "border-border bg-card text-secondary-foreground hover:bg-slate-50";
}

function AdminButton(props: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "neutral" | "primary" | "danger";
  type?: "button" | "submit";
}) {
  return (
    <button
      type={props.type ?? "button"}
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold transition ${outlineButtonClass(props.tone)} disabled:cursor-not-allowed disabled:opacity-50`}
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

function DetailItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-[12px] border border-border bg-card p-3">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-1 text-sm font-semibold text-foreground">{value || "-"}</div>
    </div>
  );
}

function ModalShell(props: { title: string; children: React.ReactNode; onClose: () => void }) {
  const t = useT();
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-foreground/40 p-4">
      <section className="w-full max-w-md rounded-[12px] border border-border bg-card shadow-xl">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-base font-bold text-foreground">{props.title}</h3>
          <button onClick={props.onClose} className="el-press rounded-[10px] p-1 text-muted-foreground hover:bg-muted" aria-label={t("common.close")}>
            <X size={18} />
          </button>
        </header>
        {props.children}
      </section>
    </div>
  );
}

function ChangeStatusModal(props: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: { status: string; reason: string }) => void;
}) {
  const t = useT();
  const [status, setStatus] = useState("published");
  const [reason, setReason] = useState("");
  const valid = reason.trim().length > 0;
  return (
    <ModalShell title={t("admin.orders.statusModal")} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <Select label={t("admin.orders.newStatus")} value={status} onChange={setStatus}>
          {manualOrderStatuses.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}
        </Select>
        <TextArea label={`${t("common.reason")} *`} value={reason} onChange={setReason} placeholder={t("admin.common.reasonRequired")} />
        <div className="flex justify-end gap-2">
          <AdminButton onClick={props.onClose}>{t("common.cancel")}</AdminButton>
          <AdminButton tone="primary" disabled={props.busy || !valid} onClick={() => props.onSubmit({ status, reason })}>{t("common.save")}</AdminButton>
        </div>
      </div>
    </ModalShell>
  );
}

function AssignDriverModal(props: {
  busy: boolean;
  drivers: Array<Record<string, unknown>>;
  onSearch: (value: string) => void;
  onClose: () => void;
  onSubmit: (payload: { driver_id: number; final_price: number; reason: string }) => void;
}) {
  const t = useT();
  const [driverId, setDriverId] = useState("");
  const [driverQuery, setDriverQuery] = useState("");
  const [driverListOpen, setDriverListOpen] = useState(false);
  const [finalPrice, setFinalPrice] = useState("");
  const [reason, setReason] = useState("");
  const valid = Number(driverId) > 0 && Number(finalPrice) > 0 && reason.trim().length > 0;
  const driverLabel = (driver: Record<string, unknown>) => {
    const user = driver.user as { phone?: string; full_name?: string } | undefined;
    return [user?.full_name, user?.phone, driver.car_model, driver.plate_number].filter(Boolean).join(" / ") || t("admin.drivers.driverNo", { id: String(driver.id) });
  };
  const selectedDriver = props.drivers.find((driver) => String(driver.id) === driverId);
  const localDrivers = props.drivers.filter((driver) => driverLabel(driver).toLowerCase().includes(driverQuery.trim().toLowerCase()));
  const visibleDrivers = driverQuery.trim() ? localDrivers : props.drivers;

  function searchDrivers(value: string) {
    setDriverQuery(value);
    setDriverId("");
    setDriverListOpen(true);
    props.onSearch(value);
  }

  function selectDriver(driver: Record<string, unknown>) {
    setDriverId(String(driver.id));
    setDriverQuery(driverLabel(driver));
    setDriverListOpen(false);
  }

  return (
    <ModalShell title={t("admin.orders.assign")} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <label className="relative grid gap-1.5 text-sm font-medium text-secondary-foreground">
          {t("admin.common.driver")}
          <input
            value={driverQuery}
            onChange={(event) => searchDrivers(event.target.value)}
            onFocus={() => setDriverListOpen(true)}
            onBlur={() => window.setTimeout(() => setDriverListOpen(false), 120)}
            placeholder={t("admin.orders.driverSearch")}
            className="h-10 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
          />
          {driverListOpen && (
            <div className="absolute left-0 right-0 top-[68px] z-[80] max-h-56 overflow-y-auto rounded-[10px] border border-border bg-card py-1 shadow-lg">
              {visibleDrivers.length ? visibleDrivers.map((driver) => {
                const active = String(driver.id) === driverId;
                return (
                  <button
                    type="button"
                    key={String(driver.id)}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectDriver(driver)}
                    className={`el-press block w-full px-3 py-2 text-left text-sm hover:bg-accent ${active ? "bg-accent text-primary" : "text-secondary-foreground"}`}
                  >
                    <span className="block font-semibold">{driverLabel(driver)}</span>
                    <span className="block text-xs text-muted-foreground">ID {String(driver.id)}</span>
                  </button>
                );
              }) : (
                <div className="px-3 py-3 text-sm text-muted-foreground">{t("admin.orders.noEligibleDriver")}</div>
              )}
            </div>
          )}
          {selectedDriver && <span className="text-xs font-semibold text-success">{t("admin.orders.selected", { name: driverLabel(selectedDriver) })}</span>}
        </label>
        <Input label={t("admin.orders.finalPrice")} value={finalPrice} onChange={setFinalPrice} type="number" />
        <Input label={`${t("common.reason")} *`} value={reason} onChange={setReason} placeholder={t("admin.common.reasonRequired")} />
        <p className="text-xs text-muted-foreground">{t("admin.orders.assignHint")}</p>
        <div className="flex justify-end gap-2">
          <AdminButton onClick={props.onClose}>{t("common.cancel")}</AdminButton>
          <AdminButton tone="primary" disabled={props.busy || !valid} onClick={() => props.onSubmit({ driver_id: Number(driverId), final_price: Number(finalPrice), reason })}>{t("admin.orders.assignCta")}</AdminButton>
        </div>
      </div>
    </ModalShell>
  );
}

function CancelOrderModal(props: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const t = useT();
  const [reason, setReason] = useState("");
  return (
    <ModalShell title={t("orders.cancel")} onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <div className="rounded-[10px] border border-warning/28 bg-warning/14 p-3 text-sm font-medium text-warning">
          {t("admin.orders.cancelWarn")}
        </div>
        <TextArea label={`${t("common.reason")} *`} value={reason} onChange={setReason} placeholder={t("admin.common.reasonRequired")} />
        <div className="flex justify-end gap-2">
          <AdminButton onClick={props.onClose}>{t("confirmDialog.back")}</AdminButton>
          <AdminButton tone="danger" disabled={props.busy || !reason.trim()} onClick={() => props.onSubmit(reason)}>{t("orders.cancel")}</AdminButton>
        </div>
      </div>
    </ModalShell>
  );
}

function OrdersDrawer(props: {
  order: AdminOrder;
  user: AuthUser;
  busy: boolean;
  drivers: Array<Record<string, unknown>>;
  onClose: () => void;
  onRefresh: () => void;
  onSearchDrivers: (value: string) => void;
  onStatus: (payload: { status: string; reason: string }) => void;
  onAssign: (payload: { driver_id: number; final_price: number; reason: string }) => void;
  onCancel: (reason: string) => void;
}) {
  const t = useT();
  const [tab, setTab] = useState<"overview" | "bids" | "history" | "audit">("overview");
  const [modal, setModal] = useState<"status" | "assign" | "cancel" | null>(null);
  const order = props.order;
  const canMutate = canMutateOrders(props.user.role);
  const canAssign = ["published", "bidding"].includes(order.status);
  const canCancel = order.status !== "cancelled";
  const pickupPoint = point(order.pickup_lat, order.pickup_lng);
  const dropoffPoint = point(order.dropoff_lat, order.dropoff_lng);
  const currentIndex = timelineStatuses.indexOf(order.status);
  return (
    <>
      {/* The scrim is decoration: it closes the drawer as a convenience, and the drawer itself carries the
          dialog semantics and a real close button. Marking it presentational keeps a screen reader from
          announcing a clickable region with no name. */}
      <div className="fixed inset-0 z-50 bg-foreground/30" role="presentation" onClick={props.onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={order.order_number ?? `#${order.id}`}
        className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-3xl flex-col border-l border-border bg-slate-50 shadow-2xl"
      >
        <header className="border-b border-border bg-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-mono text-xl font-bold text-foreground">{order.order_number ?? `#${order.id}`}</h2>
                {statusBadge(order.status)}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("admin.orders.drawerSub", { status: statusLabel(order.status), created: formatDateTime(order.created_at), updated: formatDateTime(order.updated_at) })}
              </p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <AdminButton onClick={props.onRefresh}><RefreshCw size={15} /> {t("support.refresh")}</AdminButton>
              <AdminButton onClick={props.onClose}><X size={15} /> {t("common.close")}</AdminButton>
            </div>
          </div>
          {canMutate ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <AdminButton tone="primary" disabled={props.busy} onClick={() => setModal("status")}>{t("admin.orders.changeStatus")}</AdminButton>
              <AdminButton disabled={props.busy || !canAssign} onClick={() => setModal("assign")}>{t("admin.orders.assign")}</AdminButton>
              <AdminButton tone="danger" disabled={props.busy || !canCancel} onClick={() => setModal("cancel")}>{t("orders.cancel")}</AdminButton>
            </div>
          ) : (
            <p className="mt-4 rounded-[10px] bg-background px-3 py-2 text-sm font-semibold text-muted-foreground" data-testid="orders-readonly">{t("admin.orders.readOnly")}</p>
          )}
          <div className="mt-4 flex gap-2 overflow-x-auto border-b border-border">
            {([
              ["overview", "admin.orders.tab.overview"],
              ["bids", "admin.orders.bids"],
              ["history", "admin.orders.tab.history"],
              ["audit", "admin.orders.tab.audit"],
            ] as Array<[typeof tab, MessageKey]>).map(([key, label]) => (
              <button key={key} type="button" onClick={() => setTab(key)} className={`el-press whitespace-nowrap border-b-2 px-3 py-2 text-sm font-semibold ${tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{t(label)}</button>
            ))}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {tab === "overview" && (
            <div className="grid min-w-0 gap-5">
              {order.dispute && (
                <section className="rounded-[12px] border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">
                  <p className="font-bold">{t("status.disputed")}</p>
                  <p className="mt-1">{t("admin.orders.disputeLine", { reason: adminDisputeReasonLabel(order.dispute.reason), status: adminDisputeStatusLabel(order.dispute.status) })}</p>
                </section>
              )}
              <section className="grid gap-3 md:grid-cols-3">
                <DetailItem label={t("admin.common.from")} value={`${refName(order.from_city)}${order.from_district ? ` / ${refName(order.from_district)}` : ""}`} />
                <DetailItem label={t("admin.common.to")} value={`${refName(order.to_city)}${order.to_district ? ` / ${refName(order.to_district)}` : ""}`} />
                <DetailItem label={t("admin.orders.suggested")} value={formatAdminMoney(order.suggested_price)} />
                <DetailItem label={t("admin.orders.finalPrice")} value={formatAdminMoney(order.final_price)} />
                <DetailItem label={t("admin.orders.paymentMethod")} value={adminPaymentLabel(order.payment_method ?? "cash")} />
                <DetailItem label={t("admin.orders.paymentStatus")} value={adminPaymentLabel(order.payment_status)} />
                <DetailItem label={t("admin.orders.pickup")} value={[order.pickup_address, pickupPoint].filter(Boolean).join(" · ") || t("admin.orders.noPoint")} />
                <DetailItem label={t("admin.orders.dropoff")} value={[order.dropoff_address, dropoffPoint].filter(Boolean).join(" · ") || t("admin.orders.noPoint")} />
                <DetailItem label={t("admin.common.client")} value={[order.client?.full_name, order.client?.phone].filter(Boolean).join(" · ") || "-"} />
                <DetailItem label={t("admin.orders.senderPhone")} value={order.sender_phone ?? "-"} />
                <DetailItem label={t("admin.orders.receiverPhone")} value={order.receiver_phone ?? "-"} />
                <DetailItem label={t("listingOwner.commentLabel")} value={order.comment ?? "-"} />
                <DetailItem label={t("admin.orders.cargoPhoto")} value={order.cargo_photo_url ? <a href={order.cargo_photo_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">{t("admin.orders.openPhoto")}</a> : "-"} />
              </section>
              {(pickupPoint || dropoffPoint) && (
                <section className="relative overflow-hidden rounded-[12px] border border-border bg-card">
                  <ReadOnlyOrderMap pickupLat={order.pickup_lat} pickupLng={order.pickup_lng} dropoffLat={order.dropoff_lat} dropoffLng={order.dropoff_lng} />
                  <span className="pointer-events-none absolute left-3 top-3 z-[500] rounded-full bg-card/95 px-3 py-1 text-xs font-semibold text-foreground shadow-sm">{t("admin.orders.mapReadOnly")}</span>
                </section>
              )}
              <section className="rounded-[12px] border border-border bg-card p-4">
                <p className="text-sm font-bold text-foreground">{t("admin.orders.assignedTitle")}</p>
                {order.assigned_driver ? (
                  <div className="mt-3 grid gap-3 md:grid-cols-4">
                    <DetailItem label={t("admin.common.driver")} value={driverName(order.assigned_driver, t("admin.orders.notAssigned"))} />
                    <DetailItem label={t("admin.common.phone")} value={order.assigned_driver.phone ?? "-"} />
                    <DetailItem label={t("driverProfile.vehicle")} value={[order.assigned_driver.car_model, order.assigned_driver.car_color, order.assigned_driver.plate_number].filter(Boolean).join(" · ") || "-"} />
                    <DetailItem label={t("driverProfile.rating")} value={order.assigned_driver.rating ?? "-"} />
                    <DetailItem label={t("admin.drivers.colCheck")} value={getDriverVerificationLabel(order.assigned_driver.verification_status)} />
                  </div>
                ) : <p className="mt-3 text-sm text-muted-foreground">{t("admin.orders.notAssigned")}</p>}
              </section>
              <section className="rounded-[12px] border border-border bg-card p-4">
                <p className="text-sm font-bold text-foreground">{t("admin.orders.tab.history")}</p>
                <div className="mt-3 flex flex-wrap gap-2" data-testid="status-timeline">
                  {[...timelineStatuses, ...(order.status === "cancelled" || order.status === "disputed" ? [order.status] : [])].map((item, index) => {
                    const current = item === order.status;
                    const reached = current || (currentIndex >= 0 && index < currentIndex) || Boolean(order[`${item}_at` as keyof AdminOrder]);
                    return (
                      <span
                        key={item}
                        aria-current={current ? "step" : undefined}
                        className={`rounded-full border px-3 py-1 text-xs font-semibold ${current ? "border-primary bg-primary text-primary-foreground" : reached ? "border-blue-200 bg-accent text-primary" : "border-border bg-card text-muted-foreground"}`}
                      >
                        {statusLabel(item)}
                      </span>
                    );
                  })}
                </div>
              </section>
            </div>
          )}

          {tab === "bids" && (
            <section className="grid gap-3">
              {(order.bids ?? []).length ? (order.bids ?? []).map((bid: AdminOrderBid) => (
                <div key={bid.id} className="rounded-[12px] border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-bold text-foreground">{bid.driver_name ?? t("admin.drivers.driverNo", { id: String(bid.driver_id ?? "-") })}</p>
                      <p className="text-sm text-muted-foreground">{[bid.car_model, bid.plate_number, bid.driver_phone].filter(Boolean).join(" · ") || "-"}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-bold text-foreground">{formatAdminMoney(bid.price)}</p>
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusToneClass(bid.status)}`}>{adminBidStatusLabel(bid.status)}</span>
                    </div>
                  </div>
                  <p className="mt-3 text-sm text-secondary-foreground">{bid.comment || t("admin.orders.noComment")}</p>
                  <p className="mt-2 text-xs text-muted-foreground">{t("admin.orders.bidMeta", { rating: String(bid.driver_rating ?? "-"), created: formatDateTime(bid.created_at) })}</p>
                </div>
              )) : <div className="rounded-[12px] border border-border bg-card p-10 text-center text-sm text-muted-foreground">{t("admin.orders.noBids")}</div>}
            </section>
          )}

          {tab === "history" && (
            <section className="grid gap-3">
              {(order.status_history ?? []).length ? (order.status_history ?? []).map((item, index) => (
                <div key={`${item.created_at}-${index}`} className="rounded-[12px] border border-border bg-card p-4">
                  <p className="font-semibold text-foreground">{statusLabel(item.old_status)} → {statusLabel(item.new_status)}</p>
                  <p className="mt-1 text-sm text-secondary-foreground">{item.reason ?? t("admin.orders.noReason")}</p>
                  <p className="mt-2 text-xs text-muted-foreground">{adminRoleLabel(item.changed_by_role)} · {formatDateTime(item.created_at)}</p>
                </div>
              )) : <div className="rounded-[12px] border border-border bg-card p-10 text-center text-sm text-muted-foreground">{t("admin.orders.noHistory")}</div>}
            </section>
          )}

          {tab === "audit" && (
            <div className="rounded-[12px] border border-border bg-card p-5 text-sm text-secondary-foreground">{t("admin.orders.auditHint")}</div>
          )}
        </div>
      </aside>

      {modal === "status" && <ChangeStatusModal busy={props.busy} onClose={() => setModal(null)} onSubmit={(payload) => { setModal(null); props.onStatus(payload); }} />}
      {modal === "assign" && <AssignDriverModal busy={props.busy} drivers={props.drivers} onSearch={props.onSearchDrivers} onClose={() => setModal(null)} onSubmit={(payload) => { setModal(null); props.onAssign(payload); }} />}
      {modal === "cancel" && <CancelOrderModal busy={props.busy} onClose={() => setModal(null)} onSubmit={(reason) => { setModal(null); props.onCancel(reason); }} />}
    </>
  );
}

export function AdminOrdersPanel({ user }: OrdersPanelProps) {
  const t = useT();
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [selectedOrder, setSelectedOrder] = useState<AdminOrder | null>(null);
  const [cities, setCities] = useState<City[]>([]);
  const [fromDistricts, setFromDistricts] = useState<District[]>([]);
  const [toDistricts, setToDistricts] = useState<District[]>([]);
  const [eligibleDrivers, setEligibleDrivers] = useState<Array<Record<string, unknown>>>([]);
  const [filters, setFilters] = useState<AdminOrderFilters>({ page: 1, limit: 20 });
  const [draftFilters, setDraftFilters] = useState<AdminOrderFilters>({ page: 1, limit: 20 });
  const [activeTab, setActiveTab] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const canMutate = canMutateOrders(user.role);

  async function loadOrders(nextFilters = filters) {
    setBusy(true);
    setError(null);
    try {
      const response = await getAdminOrders(nextFilters);
      setOrders(response.items ?? []);
      setTotal(response.pagination?.total ?? response.items.length);
      setTotalPages(response.pagination?.total_pages ?? 1);
    } catch (err) {
      setError(adminErrorMessage(err, "admin.orders.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function openOrder(orderId: number) {
    setBusy(true);
    setError(null);
    try {
      const detail = await getAdminOrderDetail(orderId);
      setSelectedOrder(detail);
      // The eligible-drivers list is only for the assign action (admin+); an operator never asks for it.
      setEligibleDrivers(canMutate ? await getEligibleDriversForOrder(orderId).catch(() => []) : []);
    } catch (err) {
      setError(adminErrorMessage(err, "admin.orders.detailFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function refreshSelected() {
    if (!selectedOrder) return;
    await openOrder(selectedOrder.id);
    await loadOrders();
  }

  useEffect(() => {
    void loadOrders();
    void getCities({ limit: 100 }).then(setCities).catch(() => setCities([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const cityId = Number(draftFilters.from_city_id);
    if (!cityId) {
      setFromDistricts([]);
      return;
    }
    void getDistricts(cityId, { limit: 100 }).then(setFromDistricts).catch(() => setFromDistricts([]));
  }, [draftFilters.from_city_id]);

  useEffect(() => {
    const cityId = Number(draftFilters.to_city_id);
    if (!cityId) {
      setToDistricts([]);
      return;
    }
    void getDistricts(cityId, { limit: 100 }).then(setToDistricts).catch(() => setToDistricts([]));
  }, [draftFilters.to_city_id]);

  const visibleOrders = useMemo(() => {
    const q = (filters.search ?? "").trim().toLowerCase();
    const tab = statusTabs.find((item) => item.key === activeTab);
    return orders.filter((order) => {
      if (tab?.statuses && !tab.statuses.includes(order.status)) return false;
      if (q && !textForSearch(order).includes(q)) return false;
      if (filters.from_district_id && String(order.from_district?.id ?? "") !== String(filters.from_district_id)) return false;
      if (filters.to_district_id && String(order.to_district?.id ?? "") !== String(filters.to_district_id)) return false;
      if (filters.assigned_driver && !textForSearch(order).includes(filters.assigned_driver.toLowerCase())) return false;
      if (filters.has_bids === "yes" && !(Number(order.bids_count ?? 0) > 0)) return false;
      if (filters.has_bids === "no" && Number(order.bids_count ?? 0) > 0) return false;
      if (filters.has_dispute === "yes" && order.status !== "disputed" && !order.dispute) return false;
      if (filters.has_dispute === "no" && (order.status === "disputed" || order.dispute)) return false;
      return true;
    });
  }, [activeTab, filters, orders]);

  const summary = useMemo(() => {
    const count = (statuses: string[]) => visibleOrders.filter((order) => statuses.includes(order.status)).length;
    return [
      ["admin.overview.totalOrders", visibleOrders.length, ClipboardList, ""],
      ["admin.orders.kpiPublished", count(["published", "bidding"]), Search, ""],
      ["admin.orders.kpiActive", count(["accepted", "picked_up", "in_transit"]), Truck, ""],
      ["admin.orders.delivered", count(["delivered"]), MapPin, ""],
      ["status.approved", count(["confirmed"]), DollarSign, ""],
      ["status.cancelled", count(["cancelled"]), X, ""],
      ["admin.orders.disputed", count(["disputed"]), AlertTriangle, "text-destructive"],
    ] as const;
  }, [visibleOrders]);

  function applyFilters() {
    const tab = statusTabs.find((item) => item.key === activeTab);
    const next = {
      ...draftFilters,
      page: 1,
      status: tab?.statuses?.length === 1 ? tab.statuses[0] : draftFilters.status,
    };
    setFilters(next);
    void loadOrders(next);
  }

  function clearFilters() {
    const next = { page: 1, limit: filters.limit ?? 20 };
    setActiveTab("all");
    setDraftFilters(next);
    setFilters(next);
    void loadOrders(next);
  }

  function setPage(page: number) {
    const next = { ...filters, page };
    setFilters(next);
    setDraftFilters((current) => ({ ...current, page }));
    void loadOrders(next);
  }

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refreshSelected();
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
          <h2 className="text-2xl font-bold text-foreground">{t("orders.title")}</h2>
        </div>
        <AdminButton disabled={busy} onClick={() => void loadOrders()}><RefreshCw size={16} /> {t("support.refresh")}</AdminButton>
      </section>

      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">{error}</div>}

      <section className="grid gap-3 sm:grid-cols-2 md:grid-cols-4 xl:grid-cols-7">
        {summary.map(([label, value, Icon, tone]) => (
          <div key={label} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-semibold text-muted-foreground">{t(label)}</p>
              <Icon size={16} className="shrink-0 text-slate-400" />
            </div>
            <p className={`mt-3 text-2xl font-bold ${tone || "text-foreground"}`}>{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <div className="mb-4 flex flex-wrap gap-2">
          {statusTabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => {
                setActiveTab(tab.key);
                const next = { ...filters, page: 1, status: tab.statuses?.length === 1 ? tab.statuses[0] : undefined };
                setFilters(next);
                setDraftFilters((current) => ({ ...current, status: next.status, page: 1 }));
                void loadOrders(next);
              }}
              className={`el-press rounded-full border px-3 py-1.5 text-sm font-semibold ${activeTab === tab.key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-secondary-foreground hover:bg-slate-50"}`}
            >
              {t(tab.label)}
            </button>
          ))}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <Input label={t("location.search")} value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder={t("admin.orders.searchPh")} />
          <Select label={t("admin.common.status")} value={draftFilters.status ?? ""} onChange={(status) => setDraftFilters({ ...draftFilters, status })}>
            {allOption}
            {manualOrderStatuses.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}
            <option value="draft">{statusLabel("draft")}</option>
          </Select>
          <Select label={t("admin.common.from")} value={draftFilters.from_city_id ?? ""} onChange={(from_city_id) => setDraftFilters({ ...draftFilters, from_city_id, from_district_id: "" })}>
            {allOption}
            {cities.map((city) => <option key={city.id} value={city.id}>{city.name_uz}</option>)}
          </Select>
          <Select label={t("admin.orders.fromDistrict")} value={draftFilters.from_district_id ?? ""} onChange={(from_district_id) => setDraftFilters({ ...draftFilters, from_district_id })}>
            {allOption}
            {fromDistricts.map((district) => <option key={district.id} value={district.id}>{district.name_uz}</option>)}
          </Select>
          <Select label={t("admin.common.to")} value={draftFilters.to_city_id ?? ""} onChange={(to_city_id) => setDraftFilters({ ...draftFilters, to_city_id, to_district_id: "" })}>
            {allOption}
            {cities.map((city) => <option key={city.id} value={city.id}>{city.name_uz}</option>)}
          </Select>
          <Select label={t("admin.orders.toDistrict")} value={draftFilters.to_district_id ?? ""} onChange={(to_district_id) => setDraftFilters({ ...draftFilters, to_district_id })}>
            {allOption}
            {toDistricts.map((district) => <option key={district.id} value={district.id}>{district.name_uz}</option>)}
          </Select>
          <Input label={t("admin.orders.assignedDriver")} value={draftFilters.assigned_driver ?? ""} onChange={(assigned_driver) => setDraftFilters({ ...draftFilters, assigned_driver })} placeholder={t("admin.orders.namePhone")} />
          <Input label={t("admin.common.fromDate")} value={draftFilters.created_from ?? ""} onChange={(created_from) => setDraftFilters({ ...draftFilters, created_from })} type="date" />
          <Input label={t("admin.common.toDate")} value={draftFilters.created_to ?? ""} onChange={(created_to) => setDraftFilters({ ...draftFilters, created_to })} type="date" />
          <Select label={t("admin.orders.hasBids")} value={draftFilters.has_bids ?? ""} onChange={(has_bids) => setDraftFilters({ ...draftFilters, has_bids })}>
            {anyOption}
            <option value="yes">{t("admin.common.yes")}</option>
            <option value="no">{t("common.none")}</option>
          </Select>
          <Select label={t("admin.orders.hasDispute")} value={draftFilters.has_dispute ?? ""} onChange={(has_dispute) => setDraftFilters({ ...draftFilters, has_dispute })}>
            {anyOption}
            <option value="yes">{t("admin.common.yes")}</option>
            <option value="no">{t("common.none")}</option>
          </Select>
          <Select label={t("admin.common.limit")} value={String(draftFilters.limit ?? 20)} onChange={(limit) => setDraftFilters({ ...draftFilters, limit: Number(limit), page: 1 })}>
            {[10, 20, 50, 100].map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <AdminButton onClick={clearFilters}>{t("admin.common.clearFilters")}</AdminButton>
          <AdminButton tone="primary" disabled={busy} onClick={applyFilters}>{t("admin.common.applyFilters")}</AdminButton>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[1000px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                {([
                  "admin.overview.colOrder",
                  "admin.common.status",
                  "admin.common.route",
                  "admin.common.client",
                  "admin.common.driver",
                  "admin.orders.bids",
                  "admin.orders.finalPrice",
                  "admin.common.created",
                ] as MessageKey[]).map((key) => (
                  <th key={key} className="px-4 py-3 font-semibold">{t(key)}</th>
                ))}
                <th className="px-4 py-3"><span className="sr-only">{t("admin.orders.manage")}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {busy && !orders.length ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <tr key={index}>
                    <td colSpan={9} className="px-4 py-3">
                      <div className="h-8 animate-pulse rounded bg-background" />
                    </td>
                  </tr>
                ))
              ) : visibleOrders.length ? visibleOrders.map((order) => (
                <tr key={order.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <p className="font-mono font-bold text-foreground">{order.order_number ?? `#${order.id}`}</p>
                    <p className="text-xs text-muted-foreground">#{order.id}</p>
                  </td>
                  <td className="px-4 py-3">{statusBadge(order.status)}</td>
                  <td className="px-4 py-3 font-semibold text-secondary-foreground">
                    {refName(order.from_city)} → {refName(order.to_city)}
                    {(order.from_district || order.to_district) && <p className="text-xs font-normal text-muted-foreground">{refName(order.from_district)} → {refName(order.to_district)}</p>}
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-semibold text-secondary-foreground">{order.client?.phone ?? order.client_phone ?? "-"}</p>
                    {order.sender_phone && <p className="text-xs text-muted-foreground">{t("admin.orders.senderLine", { phone: order.sender_phone })}</p>}
                  </td>
                  <td className="px-4 py-3">
                    {order.assigned_driver ? (
                      <>
                        <p className="font-semibold text-secondary-foreground">{driverName(order.assigned_driver, t("admin.orders.notAssigned"))}</p>
                        <p className="text-xs text-muted-foreground">{[order.assigned_driver.car_model, order.assigned_driver.plate_number].filter(Boolean).join(" · ")}</p>
                      </>
                    ) : <span className="text-muted-foreground">{t("admin.orders.notAssigned")}</span>}
                  </td>
                  <td className="px-4 py-3">{t("admin.orders.bidsCount", { count: order.bids_count ?? 0 })}</td>
                  <td className="px-4 py-3">{formatAdminMoney(order.final_price)}</td>
                  <td className="whitespace-nowrap px-4 py-3"><Calendar size={14} className="mr-1 inline text-slate-400" />{formatDateTime(order.created_at)}</td>
                  <td className="px-4 py-3">
                    <AdminButton onClick={() => void openOrder(order.id)}><Eye size={15} /> {t("admin.orders.manage")}</AdminButton>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={9} className="px-4 py-14 text-center">
                    <ClipboardList size={32} className="mx-auto text-slate-300" />
                    <p className="mt-3 font-semibold text-secondary-foreground">{t("admin.orders.empty")}</p>
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
            <AdminButton disabled={busy || (filters.page ?? 1) <= 1} onClick={() => setPage(Math.max(1, (filters.page ?? 1) - 1))}><ChevronLeft size={15} /> {t("admin.common.prev")}</AdminButton>
            <AdminButton disabled={busy || (filters.page ?? 1) >= (totalPages || 1)} onClick={() => setPage((filters.page ?? 1) + 1)}>{t("admin.common.next")} <ChevronRight size={15} /></AdminButton>
          </div>
        </footer>
      </section>

      {selectedOrder && (
        <OrdersDrawer
          order={selectedOrder}
          user={user}
          busy={busy}
          drivers={eligibleDrivers}
          onClose={() => setSelectedOrder(null)}
          onRefresh={() => void refreshSelected()}
          onSearchDrivers={(search) => {
            if (!selectedOrder) return;
            void getEligibleDriversForOrder(selectedOrder.id, { search }).then(setEligibleDrivers).catch(() => setEligibleDrivers([]));
          }}
          onStatus={(payload) => void mutate(() => manualUpdateOrderStatus(selectedOrder.id, payload))}
          onAssign={(payload) => void mutate(() => manualAssignDriver(selectedOrder.id, payload))}
          onCancel={(reason) => void mutate(() => cancelAdminOrder(selectedOrder.id, { reason }))}
        />
      )}
    </div>
  );
}
