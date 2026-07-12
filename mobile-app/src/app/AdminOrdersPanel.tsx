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
} from "lucide-react";

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
import { ApiError } from "../types/api";
import type { AdminOrder, AdminOrderBid, AdminOrderFilters, AdminOrderRef } from "../types/admin-order";
import type { AuthUser } from "../types/auth";
import type { City, District } from "../types/city";
import type { OrderStatus } from "../types/order";
import { formatShortAdminDate, formatAdminDate } from "../utils/date";
import { formatAdminMoney } from "../utils/money";
import { manualOrderStatuses, statusLabel, statusToneClass } from "../utils/orderStatus";

type OrdersPanelProps = {
  user: AuthUser;
};

type StatusTab = {
  key: string;
  label: string;
  statuses?: OrderStatus[];
};

const statusTabs: StatusTab[] = [
  { key: "all", label: "Barchasi" },
  { key: "published", label: "E'lon qilingan", statuses: ["published"] },
  { key: "bidding", label: "Takliflar", statuses: ["bidding"] },
  { key: "accepted", label: "Qabul qilingan", statuses: ["accepted"] },
  { key: "delivery", label: "Yetkazish jarayonida", statuses: ["picked_up", "in_transit"] },
  { key: "delivered", label: "Yetkazilgan", statuses: ["delivered"] },
  { key: "confirmed", label: "Tasdiqlangan", statuses: ["confirmed"] },
  { key: "cancelled", label: "Bekor qilingan", statuses: ["cancelled"] },
  { key: "disputed", label: "Nizoli", statuses: ["disputed"] },
];

const timelineStatuses: OrderStatus[] = ["draft", "published", "bidding", "accepted", "picked_up", "in_transit", "delivered", "confirmed"];

function refName(ref?: AdminOrderRef | null): string {
  return ref?.name_uz ?? ref?.full_name ?? ref?.phone ?? "-";
}

function driverName(driver: AdminOrder["assigned_driver"]): string {
  return driver?.full_name ?? driver?.phone ?? "Biriktirilmagan";
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
  if (tone === "primary") return "border-blue-600 bg-blue-600 text-white hover:bg-blue-700";
  if (tone === "danger") return "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100";
  return "border-slate-200 bg-white text-slate-700 hover:bg-slate-50";
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
      className={`inline-flex h-10 items-center justify-center gap-2 rounded-md border px-3 text-sm font-semibold transition ${outlineButtonClass(props.tone)} disabled:cursor-not-allowed disabled:opacity-50`}
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

function DetailItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-1 text-sm font-semibold text-slate-950">{value || "-"}</div>
    </div>
  );
}

function ModalShell(props: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/40 p-4">
      <section className="w-full max-w-md rounded-lg border border-slate-200 bg-white shadow-xl">
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

function ChangeStatusModal(props: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: { status: string; reason: string }) => void;
}) {
  const [status, setStatus] = useState("published");
  const [reason, setReason] = useState("");
  const valid = reason.trim().length > 0;
  return (
    <ModalShell title="Buyurtma holatini o'zgartirish" onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <Select label="Yangi holat" value={status} onChange={setStatus}>
          {manualOrderStatuses.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}
        </Select>
        <Input label="Sabab" value={reason} onChange={setReason} placeholder="Sabab kiritish shart" />
        <div className="flex justify-end gap-2">
          <AdminButton onClick={props.onClose}>Bekor qilish</AdminButton>
          <AdminButton tone="primary" disabled={props.busy || !valid} onClick={() => props.onSubmit({ status, reason })}>Saqlash</AdminButton>
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
  const [driverId, setDriverId] = useState("");
  const [driverQuery, setDriverQuery] = useState("");
  const [driverListOpen, setDriverListOpen] = useState(false);
  const [finalPrice, setFinalPrice] = useState("");
  const [reason, setReason] = useState("");
  const valid = Number(driverId) > 0 && Number(finalPrice) > 0 && reason.trim().length > 0;
  const driverLabel = (driver: Record<string, unknown>) => {
    const user = driver.user as { phone?: string; full_name?: string } | undefined;
    return [user?.full_name, user?.phone, driver.car_model, driver.plate_number].filter(Boolean).join(" / ") || `Haydovchi #${driver.id}`;
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
    <ModalShell title="Haydovchi biriktirish" onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <label className="relative grid gap-1.5 text-sm font-medium text-slate-700">
          Haydovchi
          <input
            value={driverQuery}
            onChange={(event) => searchDrivers(event.target.value)}
            onFocus={() => setDriverListOpen(true)}
            onBlur={() => window.setTimeout(() => setDriverListOpen(false), 120)}
            placeholder="Ism, telefon yoki raqam orqali qidiring"
            className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-950 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          />
          {driverListOpen && (
            <div className="absolute left-0 right-0 top-[68px] z-[80] max-h-56 overflow-y-auto rounded-md border border-slate-200 bg-white py-1 shadow-lg">
              {visibleDrivers.length ? visibleDrivers.map((driver) => {
                const active = String(driver.id) === driverId;
                return (
                  <button
                    type="button"
                    key={String(driver.id)}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectDriver(driver)}
                    className={`block w-full px-3 py-2 text-left text-sm hover:bg-blue-50 ${active ? "bg-blue-50 text-blue-700" : "text-slate-700"}`}
                  >
                    <span className="block font-semibold">{driverLabel(driver)}</span>
                    <span className="block text-xs text-slate-500">ID {String(driver.id)}</span>
                  </button>
                );
              }) : (
                <div className="px-3 py-3 text-sm text-slate-500">Mos haydovchi topilmadi</div>
              )}
            </div>
          )}
          {selectedDriver && <span className="text-xs font-semibold text-emerald-700">Tanlandi: {driverLabel(selectedDriver)}</span>}
        </label>
        <Input label="Yakuniy narx" value={finalPrice} onChange={setFinalPrice} type="number" />
        <Input label="Sabab" value={reason} onChange={setReason} placeholder="Sabab kiritish shart" />
        <p className="text-xs text-slate-500">Ro'yxatda tasdiqlangan faol haydovchilar ko'rsatiladi. Backend yo'nalish mosligini biriktirish vaqtida tekshiradi.</p>
        <div className="flex justify-end gap-2">
          <AdminButton onClick={props.onClose}>Bekor qilish</AdminButton>
          <AdminButton tone="primary" disabled={props.busy || !valid} onClick={() => props.onSubmit({ driver_id: Number(driverId), final_price: Number(finalPrice), reason })}>Biriktirish</AdminButton>
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
  const [reason, setReason] = useState("");
  return (
    <ModalShell title="Buyurtmani bekor qilish" onClose={props.onClose}>
      <div className="grid gap-4 p-5">
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm font-medium text-amber-800">
          Bu amal mijoz va haydovchiga ta'sir qilishi mumkin. Davom etilsinmi?
        </div>
        <Input label="Sabab" value={reason} onChange={setReason} placeholder="Sabab kiritish shart" />
        <div className="flex justify-end gap-2">
          <AdminButton onClick={props.onClose}>Ortga</AdminButton>
          <AdminButton tone="danger" disabled={props.busy || !reason.trim()} onClick={() => props.onSubmit(reason)}>Buyurtmani bekor qilish</AdminButton>
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
  const [tab, setTab] = useState<"overview" | "bids" | "history" | "audit">("overview");
  const [modal, setModal] = useState<"status" | "assign" | "cancel" | null>(null);
  const order = props.order;
  const canAssign = ["published", "bidding"].includes(order.status);
  const canCancel = order.status !== "cancelled";
  return (
    <>
      <div className="fixed inset-0 z-50 bg-slate-950/30" onClick={props.onClose} />
      <aside className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-3xl flex-col border-l border-slate-200 bg-slate-50 shadow-2xl">
        <header className="border-b border-slate-200 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-slate-950">{order.order_number ?? `Order #${order.id}`}</h2>
                {statusBadge(order.status)}
                {order.dispute && <span className="inline-flex rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700">Dispute opened</span>}
              </div>
              <p className="mt-1 text-sm text-slate-500">Created {formatAdminDate(order.created_at)} · Updated {formatAdminDate(order.updated_at)}</p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <AdminButton onClick={props.onRefresh}><RefreshCw size={15} /> Yangilash</AdminButton>
              <AdminButton onClick={props.onClose}><X size={15} /> Yopish</AdminButton>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <AdminButton tone="primary" disabled={props.busy} onClick={() => setModal("status")}>Change status</AdminButton>
            <AdminButton disabled={props.busy || !canAssign} onClick={() => setModal("assign")}>Assign driver</AdminButton>
            <AdminButton tone="danger" disabled={props.busy || !canCancel} onClick={() => setModal("cancel")}>Buyurtmani bekor qilish</AdminButton>
          </div>
          <div className="mt-4 flex gap-2 border-b border-slate-200">
            {[
              ["overview", "Umumiy"],
              ["bids", "Takliflar"],
              ["history", "Holat tarixi"],
              ["audit", "Audit"],
            ].map(([key, label]) => (
              <button key={key} onClick={() => setTab(key as typeof tab)} className={`border-b-2 px-3 py-2 text-sm font-semibold ${tab === key ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-950"}`}>{label}</button>
            ))}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {tab === "overview" && (
            <div className="grid min-w-0 gap-5">
              {order.dispute && (
                <section className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
                  <p className="font-bold">Dispute opened</p>
                  <p className="mt-1">Reason: {order.dispute.reason ?? "-"}</p>
                  <p>Status: {order.dispute.status ?? "-"}</p>
                </section>
              )}
              <section className="grid gap-3 md:grid-cols-3">
                <DetailItem label="Qayerdan" value={`${refName(order.from_city)}${order.from_district ? ` / ${refName(order.from_district)}` : ""}`} />
                <DetailItem label="Qayerga" value={`${refName(order.to_city)}${order.to_district ? ` / ${refName(order.to_district)}` : ""}`} />
                <DetailItem label="Tavsiya narx" value={formatAdminMoney(order.suggested_price)} />
                <DetailItem label="Yakuniy narx" value={formatAdminMoney(order.final_price)} />
                <DetailItem label="To'lov usuli" value={order.payment_method ?? "cash"} />
                <DetailItem label="To'lov holati" value={order.payment_status ?? "-"} />
              </section>
              <section className="grid gap-3 md:grid-cols-2">
                <DetailItem label="Olib ketish manzili" value={order.pickup_address ?? "-"} />
                <DetailItem label="Yetkazish manzili" value={order.dropoff_address ?? "-"} />
                <DetailItem label="Olib ketish koordinatalari" value={order.pickup_lat && order.pickup_lng ? `${order.pickup_lat}, ${order.pickup_lng}` : "Xaritada nuqta tanlanmagan"} />
                <DetailItem label="Yetkazish koordinatalari" value={order.dropoff_lat && order.dropoff_lng ? `${order.dropoff_lat}, ${order.dropoff_lng}` : "Xaritada nuqta tanlanmagan"} />
              </section>
              {(order.pickup_lat || order.dropoff_lat) && (
                <section className="rounded-lg border border-slate-200 bg-white p-4">
                  <p className="mb-3 text-sm font-bold text-slate-950">Map preview</p>
                  <ReadOnlyOrderMap pickupLat={order.pickup_lat} pickupLng={order.pickup_lng} dropoffLat={order.dropoff_lat} dropoffLng={order.dropoff_lng} />
                </section>
              )}
              <section className="grid gap-3 md:grid-cols-3">
                <DetailItem label="Mijoz" value={`${order.client?.full_name ?? "Mijoz"} · ${order.client?.phone ?? "-"}`} />
                <DetailItem label="Yuboruvchi telefoni" value={order.sender_phone ?? "-"} />
                <DetailItem label="Qabul qiluvchi telefoni" value={order.receiver_phone ?? "-"} />
              </section>
              <section className="grid gap-3 md:grid-cols-2">
                <DetailItem label="Yuk rasmi" value={order.cargo_photo_url ? <a href={order.cargo_photo_url} target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">Open photo</a> : "-"} />
                <DetailItem label="Izoh" value={order.comment ?? "-"} />
              </section>
              <section className="rounded-lg border border-slate-200 bg-white p-4">
                <p className="text-sm font-bold text-slate-950">Assigned driver</p>
                {order.assigned_driver ? (
                  <div className="mt-3 grid gap-3 md:grid-cols-3">
                    <DetailItem label="Haydovchi" value={driverName(order.assigned_driver)} />
                    <DetailItem label="Telefon" value={order.assigned_driver.phone ?? "-"} />
                    <DetailItem label="Avtomobil" value={[order.assigned_driver.car_model, order.assigned_driver.car_color, order.assigned_driver.plate_number].filter(Boolean).join(" / ") || "-"} />
                    <DetailItem label="Reyting" value={order.assigned_driver.rating ?? "-"} />
                    <DetailItem label="Tekshiruv" value={order.assigned_driver.verification_status ?? "-"} />
                  </div>
                ) : <p className="mt-3 text-sm text-slate-500">No driver assigned</p>}
              </section>
              <section className="rounded-lg border border-slate-200 bg-white p-4">
                <p className="text-sm font-bold text-slate-950">Status timeline</p>
                <div className="mt-4 grid gap-3 md:grid-cols-4">
                  {timelineStatuses.map((item) => {
                    const active = item === order.status || Boolean(order[`${item}_at` as keyof AdminOrder]);
                    return (
                      <div key={item} className={`rounded-md border px-3 py-2 text-xs font-semibold ${active ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-50 text-slate-500"}`}>
                        {statusLabel(item)}
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>
          )}

          {tab === "bids" && (
            <section className="grid gap-3">
              {(order.bids ?? []).length ? (order.bids ?? []).map((bid: AdminOrderBid) => (
                <div key={bid.id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-bold text-slate-950">{bid.driver_name ?? `Driver #${bid.driver_id}`}</p>
                      <p className="text-sm text-slate-500">{[bid.car_model, bid.plate_number, bid.driver_phone].filter(Boolean).join(" / ") || "-"}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-bold text-slate-950">{formatAdminMoney(bid.price)}</p>
                      {statusBadge(bid.status)}
                    </div>
                  </div>
                  <p className="mt-3 text-sm text-slate-600">{bid.comment || "Izoh yo'q"}</p>
                  <p className="mt-2 text-xs text-slate-500">Rating: {bid.driver_rating ?? "-"} · Created {formatAdminDate(bid.created_at)}</p>
                </div>
              )) : <div className="rounded-lg border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">No bids yet</div>}
            </section>
          )}

          {tab === "history" && (
            <section className="grid gap-3">
              {(order.status_history ?? []).length ? (order.status_history ?? []).map((item, index) => (
                <div key={`${item.created_at}-${index}`} className="rounded-lg border border-slate-200 bg-white p-4">
                  <p className="font-semibold text-slate-950">{statusLabel(item.old_status)} → {statusLabel(item.new_status)}</p>
                  <p className="mt-1 text-sm text-slate-600">{item.reason ?? "Sabab yo'q"}</p>
                  <p className="mt-2 text-xs text-slate-500">{item.changed_by_role ?? "-"} · {formatAdminDate(item.created_at)}</p>
                </div>
              )) : <div className="rounded-lg border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">No status history</div>}
            </section>
          )}

          {tab === "audit" && (
            <div className="rounded-lg border border-slate-200 bg-white p-5 text-sm text-slate-600">
              Audit yozuvlari Audit jurnali modulida mavjud. Buyurtmaga alohida audit endpointi hali mavjud emas.
            </div>
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

  const canMutate = ["operator", "admin", "super_admin"].includes(user.role);

  async function loadOrders(nextFilters = filters) {
    setBusy(true);
    setError(null);
    try {
      const response = await getAdminOrders(nextFilters);
      setOrders(response.items ?? []);
      setTotal(response.pagination?.total ?? response.items.length);
      setTotalPages(response.pagination?.total_pages ?? 1);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "Ruxsat yo'q" : err instanceof Error ? err.message : "Buyurtmalarni yuklab bo'lmadi");
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
      const drivers = await getEligibleDriversForOrder(orderId).catch(() => []);
      setEligibleDrivers(drivers);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "Ruxsat yo'q" : err instanceof Error ? err.message : "Buyurtma tafsilotlarini yuklab bo'lmadi");
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
      ["Jami buyurtmalar", visibleOrders.length, ClipboardList],
      ["E'lon qilingan / Takliflar", count(["published", "bidding"]), Search],
      ["Qabul qilingan / Faol yetkazish", count(["accepted", "picked_up", "in_transit"]), Truck],
      ["Yetkazilgan", count(["delivered"]), MapPin],
      ["Tasdiqlangan", count(["confirmed"]), DollarSign],
      ["Bekor qilingan", count(["cancelled"]), X],
      ["Nizoli", count(["disputed"]), AlertTriangle],
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
      setError(err instanceof ApiError && err.status === 403 ? "Ruxsat yo'q" : err instanceof Error ? err.message : "Amal bajarilmadi");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-slate-950">Orders</h2>
          <p className="mt-1 text-sm text-slate-500">Manage client orders, bids, drivers, statuses, and disputes</p>
        </div>
        <AdminButton disabled={busy} onClick={() => void loadOrders()}><RefreshCw size={16} /> Yangilash</AdminButton>
      </section>

      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">{error}</div>}

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-7">
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
        <div className="mb-4 flex flex-wrap gap-2">
          {statusTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                const next = { ...filters, page: 1, status: tab.statuses?.length === 1 ? tab.statuses[0] : undefined };
                setFilters(next);
                setDraftFilters((current) => ({ ...current, status: next.status, page: 1 }));
                void loadOrders(next);
              }}
              className={`rounded-md border px-3 py-2 text-sm font-semibold ${activeTab === tab.key ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="grid gap-3 lg:grid-cols-4 xl:grid-cols-6">
          <Input label="Qidirish" value={draftFilters.search ?? ""} onChange={(search) => setDraftFilters({ ...draftFilters, search })} placeholder="Kod, telefon yoki haydovchi" />
          <Select label="Holat" value={draftFilters.status ?? ""} onChange={(status) => setDraftFilters({ ...draftFilters, status })}>
            <option value="">Barchasi</option>
            {manualOrderStatuses.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}
            <option value="draft">Draft</option>
          </Select>
          <Select label="Qayerdan" value={draftFilters.from_city_id ?? ""} onChange={(from_city_id) => setDraftFilters({ ...draftFilters, from_city_id, from_district_id: "" })}>
            <option value="">Barchasi</option>
            {cities.map((city) => <option key={city.id} value={city.id}>{city.name_uz}</option>)}
          </Select>
          <Select label="Qayerdan tuman" value={draftFilters.from_district_id ?? ""} onChange={(from_district_id) => setDraftFilters({ ...draftFilters, from_district_id })}>
            <option value="">Barchasi</option>
            {fromDistricts.map((district) => <option key={district.id} value={district.id}>{district.name_uz}</option>)}
          </Select>
          <Select label="Qayerga" value={draftFilters.to_city_id ?? ""} onChange={(to_city_id) => setDraftFilters({ ...draftFilters, to_city_id, to_district_id: "" })}>
            <option value="">Barchasi</option>
            {cities.map((city) => <option key={city.id} value={city.id}>{city.name_uz}</option>)}
          </Select>
          <Select label="Qayerga tuman" value={draftFilters.to_district_id ?? ""} onChange={(to_district_id) => setDraftFilters({ ...draftFilters, to_district_id })}>
            <option value="">Barchasi</option>
            {toDistricts.map((district) => <option key={district.id} value={district.id}>{district.name_uz}</option>)}
          </Select>
          <Input label="Biriktirilgan haydovchi" value={draftFilters.assigned_driver ?? ""} onChange={(assigned_driver) => setDraftFilters({ ...draftFilters, assigned_driver })} placeholder="Ism yoki telefon" />
          <Input label="Sanadan" value={draftFilters.created_from ?? ""} onChange={(created_from) => setDraftFilters({ ...draftFilters, created_from })} type="date" />
          <Input label="Sanagacha" value={draftFilters.created_to ?? ""} onChange={(created_to) => setDraftFilters({ ...draftFilters, created_to })} type="date" />
          <Select label="Takliflari bor" value={draftFilters.has_bids ?? ""} onChange={(has_bids) => setDraftFilters({ ...draftFilters, has_bids })}>
            <option value="">Istalgan</option>
            <option value="yes">Ha</option>
            <option value="no">Yo'q</option>
          </Select>
          <Select label="Nizosi bor" value={draftFilters.has_dispute ?? ""} onChange={(has_dispute) => setDraftFilters({ ...draftFilters, has_dispute })}>
            <option value="">Istalgan</option>
            <option value="yes">Ha</option>
            <option value="no">Yo'q</option>
          </Select>
          <Select label="Limit" value={String(draftFilters.limit ?? 20)} onChange={(limit) => setDraftFilters({ ...draftFilters, limit: Number(limit), page: 1 })}>
            {[10, 20, 50, 100].map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <AdminButton onClick={clearFilters}>Filtrlarni tozalash</AdminButton>
          <AdminButton tone="primary" disabled={busy} onClick={applyFilters}>Filtrlarni qo'llash</AdminButton>
        </div>
      </section>

      <section className="max-w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                {["Buyurtma", "Holat", "Yo'nalish", "Tumanlar", "Mijoz", "Biriktirilgan haydovchi", "Takliflar", "Tavsiya narx", "Yakuniy narx", "Created at", "Amallar"].map((label) => (
                  <th key={label} className="px-4 py-3 font-semibold">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {busy && !orders.length ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <tr key={index}>
                    <td colSpan={11} className="px-4 py-3">
                      <div className="h-8 animate-pulse rounded bg-slate-100" />
                    </td>
                  </tr>
                ))
              ) : visibleOrders.length ? visibleOrders.map((order) => (
                <tr key={order.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <p className="font-bold text-slate-950">{order.order_number ?? `#${order.id}`}</p>
                    <p className="text-xs text-slate-500">#{order.id}</p>
                  </td>
                  <td className="px-4 py-3">{statusBadge(order.status)}</td>
                  <td className="px-4 py-3 font-semibold text-slate-800">{refName(order.from_city)} → {refName(order.to_city)}</td>
                  <td className="px-4 py-3 text-slate-600">{order.from_district || order.to_district ? `${refName(order.from_district)} → ${refName(order.to_district)}` : "-"}</td>
                  <td className="px-4 py-3">
                    <p className="font-semibold text-slate-800">{order.client?.phone ?? order.client_phone ?? "-"}</p>
                    <p className="text-xs text-slate-500">{order.sender_phone ?? "-"}</p>
                  </td>
                  <td className="px-4 py-3">
                    {order.assigned_driver ? (
                      <>
                        <p className="font-semibold text-slate-800">{driverName(order.assigned_driver)}</p>
                        <p className="text-xs text-slate-500">{[order.assigned_driver.car_model, order.assigned_driver.plate_number].filter(Boolean).join(" / ")}</p>
                      </>
                    ) : <span className="text-slate-500">Not assigned</span>}
                  </td>
                  <td className="px-4 py-3">{order.bids_count ?? 0} bids</td>
                  <td className="px-4 py-3">{formatAdminMoney(order.suggested_price)}</td>
                  <td className="px-4 py-3">{formatAdminMoney(order.final_price)}</td>
                  <td className="px-4 py-3"><Calendar size={14} className="mr-1 inline text-slate-400" />{formatShortAdminDate(order.created_at)}</td>
                  <td className="px-4 py-3">
                    <AdminButton onClick={() => void openOrder(order.id)}><Eye size={15} /> Manage</AdminButton>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={11} className="px-4 py-14 text-center">
                    <ClipboardList size={32} className="mx-auto text-slate-300" />
                    <p className="mt-3 font-semibold text-slate-700">No orders found</p>
                    <p className="mt-1 text-sm text-slate-500">Try clearing filters or refreshing the list.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
          <span>Page {filters.page ?? 1} of {totalPages || 1} · {total} total</span>
          <div className="flex gap-2">
            <AdminButton disabled={busy || (filters.page ?? 1) <= 1} onClick={() => setPage(Math.max(1, (filters.page ?? 1) - 1))}><ChevronLeft size={15} /> Oldingi</AdminButton>
            <AdminButton disabled={busy || (filters.page ?? 1) >= (totalPages || 1)} onClick={() => setPage((filters.page ?? 1) + 1)}>Keyingi <ChevronRight size={15} /></AdminButton>
          </div>
        </footer>
      </section>

      {selectedOrder && (
        <OrdersDrawer
          order={selectedOrder}
          user={user}
          busy={busy || !canMutate}
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
