import { useEffect, useMemo, useState } from "react";
import type { ElementType, ReactNode } from "react";
import {
  ArrowLeft,
  Bell,
  Camera,
  Check,
  CheckCircle,
  ChevronRight,
  FileText,
  Home,
  LocateFixed,
  Loader2,
  MapPin,
  Menu,
  Navigation,
  Package,
  Pencil,
  Search,
  Star,
  Trash2,
  Truck,
  Upload,
  User,
  X,
} from "lucide-react";

import { ClientMapCanvas } from "../components/maps/ClientMapCanvas";
import { GoogleMapPicker } from "../components/maps/GoogleMapPicker";
import { ReadOnlyOrderMap } from "../components/maps/ReadOnlyOrderMap";
import { CitySelector } from "../components/location/CitySelector";
import { DistrictSelector } from "../components/location/DistrictSelector";
import { useAuth } from "../auth/AuthContext";
import { getCities, getSuggestedPrice } from "../api/cities.api";
import { getDistricts } from "../api/districts.api";
import { uploadFile } from "../api/files.api";
import {
  cancelClientOrder,
  confirmClientOrder,
  createClientOrder,
  getClientOrder,
  listClientOrderBids,
  listClientOrders,
  openClientDispute,
  publishClientOrder,
  rateClientOrder,
  selectDriver,
  updateClientOrder,
} from "../api/client-orders.api";
import { getClientProfile, updateClientProfile } from "../api/client-profile.api";
import {
  createDriverRoute,
  disableDriverRoute,
  getDriverFeed,
  getDriverOrders,
  getDriverOrderDetail,
  getDriverProfile,
  getDriverRoutes,
  rejectOrder,
  sendBid,
  setDriverAvailability,
  submitDriverDocument,
  updateDriverOrderStatus,
  updateDriverProfile,
  updateDriverRoute,
} from "../api/driver.api";
import { getNotifications, markNotificationRead } from "../api/notifications.api";
import type { City, District } from "../types/city";
import type { Bid } from "../types/bid";
import type { ClientOrder, CreateOrderPayload, OrderStatus } from "../types/order";
import type { DriverDocumentType, DriverFeedOrder, DriverProfile, DriverRoute } from "../types/driver";
import type { NotificationItem } from "../types/notification";
import type { MobileRole } from "../types/auth";
import { formatUzs } from "../utils/money";
import { normalizeUzPhone } from "../utils/phone";
import { getUzbekErrorMessage } from "../utils/errors";
import { createGoogleMapsDirectionsUrl, createGoogleMapsSearchUrl, hasLocation } from "../utils/maps";
import { formatAddressRegion, formatAddressTitle, formatMapSelectionStatus, formatShortAddress } from "../utils/address";

type Screen =
  | "splash"
  | "onboarding"
  | "role"
  | "phone"
  | "otp"
  | "client-home"
  | "client-location-selector"
  | "client-district-selector"
  | "client-route-summary"
  | "client-order-route"
  | "client-order-address"
  | "client-order-photo"
  | "client-order-review"
  | "client-success"
  | "client-orders"
  | "client-order-detail"
  | "client-bids"
  | "client-confirm"
  | "client-rating"
  | "client-dispute"
  | "client-notifications"
  | "client-profile"
  | "driver-home"
  | "driver-profile-form"
  | "driver-documents"
  | "driver-routes"
  | "driver-add-route"
  | "driver-feed"
  | "driver-bid"
  | "driver-orders"
  | "driver-order-detail"
  | "driver-income"
  | "driver-profile";

type OrderDetail = ClientOrder & {
  from_city?: City;
  to_city?: City;
  from_district?: District | null;
  to_district?: District | null;
  pickup_address?: string;
  dropoff_address?: string;
  pickup_lat?: number | string | null;
  pickup_lng?: number | string | null;
  dropoff_lat?: number | string | null;
  dropoff_lng?: number | string | null;
  sender_phone?: string;
  receiver_phone?: string;
  comment?: string | null;
  assigned_driver?: {
    full_name?: string | null;
    phone?: string | null;
    car_model?: string | null;
    plate_number?: string | null;
    rating?: number | string | null;
  } | null;
};

type DriverOrderDetail = DriverFeedOrder & {
  pickup_address?: string;
  dropoff_address?: string;
  pickup_lat?: number | string | null;
  pickup_lng?: number | string | null;
  dropoff_lat?: number | string | null;
  dropoff_lng?: number | string | null;
  sender_phone?: string;
  receiver_phone?: string;
  final_price?: number | string | null;
  comment?: string | null;
};

type ConfirmAction =
  | { type: "select-driver"; bid: Bid }
  | { type: "confirm-delivery" }
  | { type: "cancel-order" };

const emptyOrder: CreateOrderPayload = {
  from_city_id: 0,
  to_city_id: 0,
  from_district_id: null,
  to_district_id: null,
  pickup_address: "",
  dropoff_address: "",
  pickup_lat: null,
  pickup_lng: null,
  dropoff_lat: null,
  dropoff_lng: null,
  sender_phone: "",
  receiver_phone: "",
  cargo_photo_url: "",
  comment: "",
};

const statusLabels: Record<string, string> = {
  draft: "Qoralama",
  published: "E'lon qilingan",
  bidding: "Takliflar bor",
  accepted: "Haydovchi tanlangan",
  picked_up: "Olib ketildi",
  in_transit: "Yo'lda",
  delivered: "Yetkazildi",
  confirmed: "Tasdiqlandi",
  cancelled: "Bekor qilingan",
  disputed: "Nizo ochilgan",
};

const docLabels: Record<DriverDocumentType, string> = {
  passport: "Pasport",
  selfie: "Selfi",
  license: "Haydovchilik guvohnomasi",
  car_document: "Avtomobil hujjati",
  car_photo: "Avtomobil rasmi",
};

const driverVerificationLabels: Record<string, string> = {
  new: "Yangi",
  pending: "Ko'rib chiqilmoqda",
  approved: "Tasdiqlangan",
  rejected: "Rad etilgan",
  blocked: "Bloklangan",
};

const DRIVER_EARNING_STATUSES = new Set(["delivered", "confirmed"]);
const DRIVER_NET_RATE = 0.85;

function cityName(city: unknown): string {
  if (!city) return "-";
  if (typeof city === "string") return city;
  if (typeof city === "object" && "name_uz" in city) return String((city as City).name_uz);
  return "-";
}

function districtName(district: unknown): string | null {
  if (!district) return null;
  if (typeof district === "string") return district;
  if (typeof district === "object" && "name_uz" in district) return String((district as District).name_uz);
  return null;
}

function districtCenter(district: District | null | undefined): { lat: number; lng: number } | null {
  const lat = district?.center_lat === null || district?.center_lat === undefined ? NaN : Number(district.center_lat);
  const lng = district?.center_lng === null || district?.center_lng === undefined ? NaN : Number(district.center_lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng };
}

function nullableNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function shortDate(value?: string): string {
  if (!value) return "";
  return new Date(value).toLocaleDateString("uz-UZ", { day: "2-digit", month: "short" });
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("uz-UZ", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toLocalDateTimeInputValue(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function cls(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function moneyNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function driverGrossIncome(order: DriverFeedOrder): number {
  return moneyNumber(order.gross_income ?? order.final_price);
}

function driverNetIncome(order: DriverFeedOrder): number {
  const explicitIncome = moneyNumber(order.driver_income);
  if (explicitIncome > 0) return explicitIncome;
  return Math.round(driverGrossIncome(order) * DRIVER_NET_RATE);
}

function driverSystemFee(order: DriverFeedOrder): number {
  const explicitFee = moneyNumber(order.system_fee);
  if (explicitFee > 0) return explicitFee;
  return Math.max(0, driverGrossIncome(order) - driverNetIncome(order));
}

function driverOrderBid(order: DriverFeedOrder): Bid | null {
  if (!order.my_bid || typeof order.my_bid !== "object") return null;
  return order.my_bid as Bid;
}

function driverOrderBids(order: DriverFeedOrder): Bid[] {
  return Array.isArray(order.bids) ? order.bids : [];
}

function isDriverEarningOrder(order: DriverFeedOrder): boolean {
  return DRIVER_EARNING_STATUSES.has(order.status) && driverGrossIncome(order) > 0;
}

function localDateKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function localMonthKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${date.getFullYear()}-${month}`;
}

function driverIncomeDate(order: DriverFeedOrder): Date {
  return new Date(order.confirmed_at ?? order.delivered_at ?? order.created_at ?? Date.now());
}

function buildDriverIncomeSeries(orders: DriverFeedOrder[]) {
  const today = new Date();
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() - (6 - index));
    date.setHours(0, 0, 0, 0);
    return {
      key: localDateKey(date),
      label: date.toLocaleDateString("uz-UZ", { weekday: "short" }),
      value: 0,
    };
  });
  const byKey = new Map(days.map((day) => [day.key, day]));
  orders.filter(isDriverEarningOrder).forEach((order) => {
    const key = localDateKey(driverIncomeDate(order));
    const bucket = byKey.get(key);
    if (bucket) bucket.value += driverNetIncome(order);
  });
  return days;
}

function buildDriverMonthlyIncomeSeries(orders: DriverFeedOrder[]) {
  const today = new Date();
  const months = Array.from({ length: 6 }, (_, index) => {
    const date = new Date(today.getFullYear(), today.getMonth() - (5 - index), 1);
    return {
      key: localMonthKey(date),
      label: date.toLocaleDateString("uz-UZ", { month: "short" }),
      value: 0,
    };
  });
  const byKey = new Map(months.map((month) => [month.key, month]));
  orders.filter(isDriverEarningOrder).forEach((order) => {
    const key = localMonthKey(driverIncomeDate(order));
    const bucket = byKey.get(key);
    if (bucket) bucket.value += driverNetIncome(order);
  });
  return months;
}

function PrimaryButton(props: { children: string; onClick?: () => void; disabled?: boolean; type?: "button" | "submit" }) {
  return (
    <button
      type={props.type ?? "button"}
      onClick={props.onClick}
      disabled={props.disabled}
      className="flex h-[52px] w-full items-center justify-center rounded-[14px] bg-[#1B4FD8] px-4 text-[16px] font-semibold text-white disabled:bg-[#9CA3AF]"
    >
      {props.children}
    </button>
  );
}

function SecondaryButton(props: { children: string; onClick?: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className={cls(
        "flex h-[52px] w-full items-center justify-center rounded-[14px] px-4 text-[15px] font-semibold",
        props.danger ? "bg-[#FEE2E2] text-[#DC2626]" : "bg-[#EEF2FF] text-[#1B4FD8]",
      )}
    >
      {props.children}
    </button>
  );
}

function Field(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  type?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[14px] font-medium text-[#374151]">{props.label}</span>
      {props.multiline ? (
        <textarea
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
          placeholder={props.placeholder}
          rows={3}
          className="resize-none rounded-[12px] border border-[#E5E7EB] bg-white px-4 py-3 text-[15px] text-[#111827] outline-none"
        />
      ) : (
        <input
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
          placeholder={props.placeholder}
          type={props.type ?? "text"}
          className="h-[52px] rounded-[12px] border border-[#E5E7EB] bg-white px-4 text-[15px] text-[#111827] outline-none"
        />
      )}
    </label>
  );
}

function TopBar(props: { title: string; back?: () => void; right?: ReactNode }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[#E5E7EB] bg-white px-5">
      {props.back && (
        <button onClick={props.back} className="flex h-9 w-9 items-center justify-center rounded-full bg-[#F3F4F6]">
          <ArrowLeft size={18} />
        </button>
      )}
      <h1 className="flex-1 text-[17px] font-semibold text-[#111827]">{props.title}</h1>
      {props.right}
    </header>
  );
}

function StatusBadge({ status }: { status?: string }) {
  return (
    <span className="rounded-full bg-[#EDE9FE] px-2.5 py-1 text-[12px] font-semibold text-[#6D28D9]">
      {statusLabels[status ?? ""] ?? status ?? "-"}
    </span>
  );
}

function EmptyState(props: { icon: ElementType; title: string; subtitle?: string; action?: string; onAction?: () => void }) {
  const Icon = props.icon;
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-8 py-12 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#F3F4F6]">
        <Icon size={28} color="#9CA3AF" />
      </div>
      <div>
        <p className="text-[15px] font-semibold text-[#374151]">{props.title}</p>
        {props.subtitle && <p className="mt-1.5 text-[13px] leading-5 text-[#6B7280]">{props.subtitle}</p>}
      </div>
      {props.action && <SecondaryButton onClick={props.onAction}>{props.action}</SecondaryButton>}
    </div>
  );
}

function ProfileActionRow(props: {
  icon: ElementType;
  label: string;
  description?: string;
  onClick: () => void;
  danger?: boolean;
}) {
  const Icon = props.icon;
  return (
    <button
      type="button"
      onClick={props.onClick}
      className="flex min-h-[64px] w-full items-center gap-3 rounded-[14px] bg-white px-4 py-3 text-left"
    >
      <span className={cls(
        "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
        props.danger ? "bg-[#FEE2E2] text-[#DC2626]" : "bg-[#EEF2FF] text-[#1B4FD8]",
      )}>
        <Icon size={19} />
      </span>
      <span className="min-w-0 flex-1">
        <span className={cls("block text-[15px] font-semibold", props.danger ? "text-[#DC2626]" : "text-[#111827]")}>
          {props.label}
        </span>
        {props.description && <span className="mt-0.5 block text-[12px] leading-5 text-[#6B7280]">{props.description}</span>}
      </span>
      {!props.danger && <ChevronRight size={18} color="#9CA3AF" />}
    </button>
  );
}

function StatusTimeline({ status }: { status: OrderStatus }) {
  const steps: { status: OrderStatus; label: string }[] = [
    { status: "published", label: "E'lon qilindi" },
    { status: "bidding", label: "Takliflar bor" },
    { status: "accepted", label: "Haydovchi tanlandi" },
    { status: "picked_up", label: "Olib ketildi" },
    { status: "in_transit", label: "Yo'lda" },
    { status: "delivered", label: "Yetkazildi" },
    { status: "confirmed", label: "Tasdiqlandi" },
  ];
  const index = steps.findIndex((step) => step.status === status);
  const activeIndex = index >= 0 ? index : 0;
  return (
    <div className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
      <p className="text-[13px] font-semibold text-[#111827]">Buyurtma holati</p>
      <div className="mt-3 space-y-2">
        {steps.map((step, stepIndex) => (
          <div key={step.status} className="flex items-center gap-2">
            <span className={cls("h-3 w-3 rounded-full", stepIndex <= activeIndex ? "bg-[#1B4FD8]" : "bg-[#D1D5DB]")} />
            <span className={cls("text-[13px]", stepIndex <= activeIndex ? "font-semibold text-[#111827]" : "text-[#6B7280]")}>
              {step.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DriverAuctionBids({ bids }: { bids?: Bid[] }) {
  const activeBids = bids ?? [];
  if (!activeBids.length) return null;

  return (
    <div className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[13px] font-semibold text-[#111827]">Auksion takliflari</p>
        <span className="rounded-full bg-[#EEF2FF] px-2.5 py-1 text-[12px] font-semibold text-[#1B4FD8]">
          {activeBids.length} ta
        </span>
      </div>
      <div className="mt-3 space-y-2">
        {activeBids.map((bid) => (
          <div
            key={bid.id ?? `${bid.order_id}-${bid.price}`}
            className={cls(
              "rounded-[12px] border p-3",
              bid.is_mine ? "border-[#1B4FD8] bg-[#EEF2FF]" : "border-[#E5E7EB] bg-[#F9FAFB]",
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-[14px] font-semibold text-[#111827]">
                  {bid.driver?.full_name ?? "Haydovchi"}{bid.is_mine ? " (men)" : ""}
                </p>
                <p className="mt-0.5 truncate text-[12px] text-[#6B7280]">
                  {bid.driver?.car_model ?? "-"} / {bid.driver?.plate_number ?? "-"}
                </p>
              </div>
              <p className="shrink-0 text-[15px] font-bold text-[#1B4FD8]">{formatUzs(bid.price)}</p>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <div className="rounded-[10px] bg-white px-2 py-1.5">
                <p className="text-[10px] text-[#6B7280]">Reyting</p>
                <p className="text-[12px] font-semibold text-[#111827]">{bid.driver?.rating ?? "-"}</p>
              </div>
              <div className="rounded-[10px] bg-white px-2 py-1.5">
                <p className="text-[10px] text-[#6B7280]">Yakunlangan</p>
                <p className="text-[12px] font-semibold text-[#111827]">{bid.driver?.completed_orders ?? 0} ta</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MiniIncomeChart({ data }: { data: Array<{ key: string; label: string; value: number }> }) {
  const maxValue = Math.max(...data.map((item) => item.value), 1);
  return (
    <div className="mt-4 flex h-[112px] items-end gap-2">
      {data.map((item) => {
        const height = item.value > 0 ? Math.max(10, Math.round((item.value / maxValue) * 72)) : 6;
        return (
          <div key={item.key} className="flex min-w-0 flex-1 flex-col items-center gap-2">
            <div className="flex h-[76px] w-full items-end rounded-[10px] bg-[#EEF2FF] px-1.5 pb-1.5">
              <div
                className={cls("w-full rounded-[7px]", item.value > 0 ? "bg-[#16A34A]" : "bg-[#CBD5E1]")}
                style={{ height }}
              />
            </div>
            <span className="text-[10px] font-medium text-[#6B7280]">{item.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function ConfirmSheet(props: { title: string; text: string; confirmText: string; cancelText?: string; danger?: boolean; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="absolute inset-0 z-[70] flex items-end bg-black/35">
      <div className="w-full rounded-t-[24px] bg-white p-5 shadow-[0_-8px_30px_rgba(15,23,42,0.18)]">
        <p className="text-[18px] font-bold text-[#111827]">{props.title}</p>
        <p className="mt-2 text-[14px] leading-6 text-[#6B7280]">{props.text}</p>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <button onClick={props.onCancel} className="h-[52px] rounded-[14px] bg-[#F3F4F6] text-[15px] font-semibold text-[#6B7280]">
            {props.cancelText ?? "Bekor qilish"}
          </button>
          <button
            onClick={props.onConfirm}
            className={cls("h-[52px] rounded-[14px] text-[15px] font-semibold text-white", props.danger ? "bg-[#DC2626]" : "bg-[#1B4FD8]")}
          >
            {props.confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

function CitySelect(props: { label: string; cities: City[]; value: number; onChange: (value: number) => void }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[14px] font-medium text-[#374151]">{props.label}</span>
      <select
        value={props.value || ""}
        onChange={(event) => props.onChange(Number(event.target.value))}
        className="h-[52px] rounded-[12px] border border-[#E5E7EB] bg-white px-4 text-[15px] text-[#111827] outline-none"
      >
        <option value="">Shaharni tanlang</option>
        {props.cities.map((city) => (
          <option key={city.id} value={city.id}>
            {city.name_uz}
          </option>
        ))}
      </select>
    </label>
  );
}

function LocationPointRow(props: {
  label: string;
  address: string;
  hasPoint: boolean;
  onClick: () => void;
  icon: ElementType;
}) {
  const Icon = props.icon;
  const title = formatAddressTitle(props.address);
  const region = formatAddressRegion(props.address);

  return (
    <button
      type="button"
      onClick={props.onClick}
      className="flex min-h-[92px] w-full items-center gap-3 bg-white px-4 py-4 text-left"
    >
      <span className={cls(
        "flex h-11 w-11 shrink-0 items-center justify-center rounded-full",
        props.hasPoint ? "bg-[#E0F2FE] text-[#0369A1]" : "bg-[#F3F4F6] text-[#6B7280]",
      )}>
        <Icon size={21} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[12px] font-bold uppercase tracking-wide text-[#6B7280]">{props.label}</span>
        <span className="mt-1 block break-words text-[16px] font-semibold leading-6 text-[#111827]">
          {title || "Qidirish yoki xaritadan tanlash"}
        </span>
        <span className="mt-1 block text-[12px] text-[#6B7280]">
          {region || (props.hasPoint ? "Manzil tizim tomonidan avtomatik aniqlandi" : "Joyni belgilang, manzil avtomatik yoziladi")}
        </span>
      </span>
      <span className="shrink-0 text-[13px] font-semibold text-[#1B4FD8]">
        {props.hasPoint ? "O'zgartirish" : "Tanlash"}
      </span>
    </button>
  );
}

function LocationSelectorRow(props: { city: City; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className="flex min-h-[70px] w-full items-center gap-3 border-b border-[#E5E7EB] px-5 text-left last:border-b-0"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#F3F4F6] text-[#6B7280]">
        <MapPin size={20} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[16px] font-semibold text-[#111827]">{props.city.name_uz}</span>
        <span className="mt-0.5 block truncate text-[13px] text-[#6B7280]">{props.city.region}</span>
      </span>
      <ChevronRight size={19} color="#9CA3AF" />
    </button>
  );
}

function DistrictSelectorRow(props: { district: District; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className="flex min-h-[64px] w-full items-center gap-3 border-b border-[#E5E7EB] px-5 text-left last:border-b-0"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EEF2FF] text-[#1B4FD8]">
        <MapPin size={19} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[16px] font-semibold text-[#111827]">{props.district.name_uz}</span>
        {props.district.name_ru && <span className="mt-0.5 block truncate text-[13px] text-[#6B7280]">{props.district.name_ru}</span>}
      </span>
      <ChevronRight size={19} color="#9CA3AF" />
    </button>
  );
}

function RouteSummaryRow(props: {
  label: string;
  address: string;
  city?: string;
  district?: string | null;
  onEdit: () => void;
  icon: ElementType;
}) {
  const Icon = props.icon;
  const title = formatAddressTitle(props.address);
  const region = formatAddressRegion(props.address) || props.city;

  return (
    <div className="flex gap-3 border-b border-[#E5E7EB] px-4 py-4 last:border-b-0">
      <span className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#F3F4F6] text-[#111827]">
        <Icon size={20} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold text-[#6B7280]">{props.label}</p>
        <p className="mt-1 break-words text-[16px] font-semibold leading-6 text-[#111827]">
          {title || "Manzil kiritilmagan"}
        </p>
        <p className="mt-1 text-[13px] leading-5 text-[#6B7280]">{[region, props.district].filter(Boolean).join(" / ") || "-"}</p>
      </div>
      <button
        type="button"
        onClick={props.onEdit}
        className="h-9 shrink-0 rounded-full bg-[#F3F4F6] px-3 text-[13px] font-semibold text-[#374151]"
      >
        O'zgartirish
      </button>
    </div>
  );
}

function OrderCard({ order, onClick }: { order: ClientOrder | DriverFeedOrder; onClick?: () => void }) {
  const fromDistrictLabel = districtName("from_district" in order ? order.from_district : undefined);
  const toDistrictLabel = districtName("to_district" in order ? order.to_district : undefined);
  return (
    <button onClick={onClick} className="w-full rounded-[16px] border border-[#E5E7EB] bg-white p-4 text-left">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[14px] font-semibold text-[#111827]">
          <MapPin size={14} color="#1B4FD8" />
          {[cityName(order.from_city), fromDistrictLabel].filter(Boolean).join(", ")} {"->"} {[cityName(order.to_city), toDistrictLabel].filter(Boolean).join(", ")}
        </span>
        <StatusBadge status={order.status} />
      </div>
      <div className="flex items-center justify-between text-[13px] text-[#6B7280]">
        <span>{shortDate(order.created_at)}</span>
        <span className="font-semibold text-[#111827]">{formatUzs(("final_price" in order ? order.final_price : null) ?? order.suggested_price)}</span>
      </div>
      {"bids_count" in order && (
        <p className="mt-2 text-[12px] text-[#6B7280]">{order.bids_count ?? 0} ta taklif</p>
      )}
    </button>
  );
}

function BottomNav({ role, active, go }: { role: MobileRole; active: Screen; go: (screen: Screen) => void }) {
  const tabs =
    role === "client"
      ? [
          ["client-home", Home, "Bosh sahifa"],
          ["client-orders", Package, "Buyurtmalar"],
          ["client-notifications", Bell, "Xabarlar"],
          ["client-profile", User, "Profil"],
        ]
      : [
          ["driver-home", Home, "Bosh sahifa"],
          ["driver-routes", Navigation, "Yo'nalishlar"],
          ["driver-feed", Package, "Moslar"],
          ["driver-orders", Package, "Buyurtmalar"],
          ["driver-profile", User, "Profil"],
        ];
  return (
    <nav className="flex h-[72px] shrink-0 border-t border-[#E5E7EB] bg-white">
      {tabs.map(([id, Icon, label]) => (
        <button key={id as string} onClick={() => go(id as Screen)} className="flex flex-1 flex-col items-center justify-center gap-1">
          <Icon size={22} color={active === id ? "#1B4FD8" : "#9CA3AF"} />
          <span className={cls("text-[10px] font-medium", active === id ? "text-[#1B4FD8]" : "text-[#9CA3AF]")}>{label as string}</span>
        </button>
      ))}
    </nav>
  );
}

export function ConnectedApp() {
  const auth = useAuth();
  const [screen, setScreen] = useState<Screen>("splash");
  const [selectedRole, setSelectedRole] = useState<MobileRole>("client");
  const [phone, setPhone] = useState("+998");
  const [otp, setOtp] = useState("");
  const [onboardingStep, setOnboardingStep] = useState(0);
  const [cities, setCities] = useState<City[]>([]);
  const [districts, setDistricts] = useState<District[]>([]);
  const [orderForm, setOrderForm] = useState<CreateOrderPayload>(emptyOrder);
  const [selectedFromCity, setSelectedFromCity] = useState<City | null>(null);
  const [selectedToCity, setSelectedToCity] = useState<City | null>(null);
  const [selectedFromDistrict, setSelectedFromDistrict] = useState<District | null>(null);
  const [selectedToDistrict, setSelectedToDistrict] = useState<District | null>(null);
  const [suggestedPrice, setSuggestedPrice] = useState<number | null>(null);
  const [orders, setOrders] = useState<ClientOrder[]>([]);
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null);
  const [bids, setBids] = useState<Bid[]>([]);
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
  const [rating, setRating] = useState(5);
  const [ratingComment, setRatingComment] = useState("");
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [disputeReason, setDisputeReason] = useState("Haydovchi kelmadi");
  const [disputeComment, setDisputeComment] = useState("");
  const [clientName, setClientName] = useState("");
  const [driverProfile, setDriverProfile] = useState<DriverProfile | null>(null);
  const [driverRoutes, setDriverRoutes] = useState<DriverRoute[]>([]);
  const [driverFeed, setDriverFeed] = useState<DriverFeedOrder[]>([]);
  const [driverOrder, setDriverOrder] = useState<DriverOrderDetail | null>(null);
  const [selectedFeedOrder, setSelectedFeedOrder] = useState<DriverFeedOrder | null>(null);
  const [driverForm, setDriverForm] = useState({ full_name: "", car_model: "", car_color: "", plate_number: "" });
  const [routeForm, setRouteForm] = useState({ from_city_id: 0, from_district_id: null as number | null, to_city_id: 0, to_district_id: null as number | null });
  const [editingRouteId, setEditingRouteId] = useState<number | null>(null);
  const [bidPrice, setBidPrice] = useState("");
  const [incomePeriod, setIncomePeriod] = useState<"daily" | "monthly">("daily");
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [locationSelectorMode, setLocationSelectorMode] = useState<"pickup" | "dropoff">("pickup");
  const [districtQuery, setDistrictQuery] = useState("");
  const [districtCity, setDistrictCity] = useState<City | null>(null);
  const [districtMode, setDistrictMode] = useState<"client-pickup" | "client-dropoff" | "driver-from" | "driver-to">("client-pickup");
  const [mapPicker, setMapPicker] = useState<"pickup" | "dropoff" | null>(null);
  const [readOnlyMap, setReadOnlyMap] = useState<{
    pickupLat?: number | string | null;
    pickupLng?: number | string | null;
    dropoffLat?: number | string | null;
    dropoffLng?: number | string | null;
    destinationLat?: number | string | null;
    destinationLng?: number | string | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const go = (next: Screen) => {
    setError("");
    setMessage("");
    setScreen(next);
  };

  const run = async (work: () => Promise<void>, success?: string) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
      if (success) setMessage(success);
    } catch (err) {
      setError(getUzbekErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void getCities({ limit: 100 }).then(setCities).catch(() => setCities([]));
  }, []);

  useEffect(() => {
    if (auth.isLoading) return;
    const authScreens = ["splash", "onboarding", "role", "phone", "otp"];
    if (!auth.isAuthenticated) {
      if (!authScreens.includes(screen)) {
        go("role");
      }
      return;
    }
    if (auth.user?.role && !["client", "driver"].includes(auth.user.role)) {
      void run(async () => {
        await auth.logout();
        go("role");
      }, "Bu rol mobile ilova uchun mavjud emas");
      return;
    }
    if (authScreens.includes(screen)) {
      go(auth.user?.role === "driver" ? "driver-home" : "client-home");
    }
  }, [auth.isAuthenticated, auth.isLoading, auth.user?.role, screen]);

  useEffect(() => {
    if (orderForm.from_city_id && orderForm.to_city_id && auth.isAuthenticated) {
      void getSuggestedPrice(orderForm.from_city_id, orderForm.to_city_id)
        .then((data) => setSuggestedPrice(data.suggested_price))
        .catch(() => setSuggestedPrice(null));
    }
  }, [auth.isAuthenticated, orderForm.from_city_id, orderForm.to_city_id]);

  useEffect(() => {
    if (auth.user?.role !== "client" || !auth.user.phone || orderForm.sender_phone) return;
    setOrderForm((current) => ({ ...current, sender_phone: auth.user?.phone ?? current.sender_phone }));
  }, [auth.user?.phone, auth.user?.role, orderForm.sender_phone]);

  const fromCity = useMemo(
    () => selectedFromCity ?? cities.find((city) => city.id === orderForm.from_city_id),
    [cities, orderForm.from_city_id, selectedFromCity],
  );
  const toCity = useMemo(
    () => selectedToCity ?? cities.find((city) => city.id === orderForm.to_city_id),
    [cities, orderForm.to_city_id, selectedToCity],
  );
  const fromDistrict = useMemo(
    () => selectedFromDistrict ?? districts.find((district) => district.id === orderForm.from_district_id),
    [districts, orderForm.from_district_id, selectedFromDistrict],
  );
  const toDistrict = useMemo(
    () => selectedToDistrict ?? districts.find((district) => district.id === orderForm.to_district_id),
    [districts, orderForm.to_district_id, selectedToDistrict],
  );
  const filteredDistricts = useMemo(() => {
    const query = districtQuery.trim().toLowerCase();
    if (!query) return districts;
    return districts.filter((district) =>
      [district.name_uz, district.name_ru].some((value) => String(value ?? "").toLowerCase().includes(query)),
    );
  }, [districtQuery, districts]);

  async function openDistrictSelector(city: City, mode: typeof districtMode) {
    setDistrictCity(city);
    setDistrictMode(mode);
    setDistrictQuery("");
    setDistricts([]);
    go("client-district-selector");
    try {
      setDistricts(await getDistricts(city.id, { limit: 100 }));
    } catch {
      setDistricts([]);
    }
  }

  function openLocationSelector(mode: "pickup" | "dropoff") {
    setLocationSelectorMode(mode);
    go("client-location-selector");
  }

  function selectCityForLocation(city: City) {
    if (locationSelectorMode === "pickup") {
      setOrderForm((current) => ({
        ...current,
        from_city_id: city.id,
        from_district_id: null,
        pickup_lat: null,
        pickup_lng: null,
        pickup_address: "",
      }));
      setSelectedFromCity(city);
      setSelectedFromDistrict(null);
      if (city.requires_district) {
        void openDistrictSelector(city, "client-pickup");
        return;
      }
    } else {
      setOrderForm((current) => ({
        ...current,
        to_city_id: city.id,
        to_district_id: null,
        dropoff_lat: null,
        dropoff_lng: null,
        dropoff_address: "",
      }));
      setSelectedToCity(city);
      setSelectedToDistrict(null);
      if (city.requires_district) {
        void openDistrictSelector(city, "client-dropoff");
        return;
      }
    }
    setMapPicker(locationSelectorMode);
  }

  function selectDistrict(district: District) {
    const center = districtCenter(district);
    if (!center) setError("Bu tuman uchun default koordinata topilmadi");
    const address = [district.name_uz, districtCity?.name_uz, districtCity?.region].filter(Boolean).join(", ");
    if (districtMode === "client-pickup") {
      setOrderForm((current) => ({
        ...current,
        from_district_id: district.id,
        pickup_lat: center?.lat ?? null,
        pickup_lng: center?.lng ?? null,
        pickup_address: center ? address : current.pickup_address,
      }));
      setSelectedFromDistrict(district);
      setMapPicker("pickup");
    } else if (districtMode === "client-dropoff") {
      setOrderForm((current) => ({
        ...current,
        to_district_id: district.id,
        dropoff_lat: center?.lat ?? null,
        dropoff_lng: center?.lng ?? null,
        dropoff_address: center ? address : current.dropoff_address,
      }));
      setSelectedToDistrict(district);
      setMapPicker("dropoff");
    } else if (districtMode === "driver-from") {
      setRouteForm((current) => ({ ...current, from_district_id: district.id }));
      go("driver-add-route");
    } else {
      setRouteForm((current) => ({ ...current, to_district_id: district.id }));
      go("driver-add-route");
    }
  }

  function normalizeCityText(value: string) {
    return value
      .toLowerCase()
      .replace(/[''`]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function citySearchTerms(city: City) {
    const base = [city.name_uz, city.name_ru, city.region].map((value) => normalizeCityText(String(value ?? ""))).filter(Boolean);
    const joined = base.join(" ");
    const aliasGroups = [
      ["toshkent", "tashkent", "ташкент"],
      ["jizzax", "jizzakh", "джизак", "джизакская"],
      ["samarqand", "samarkand", "самарканд"],
      ["buxoro", "bukhara", "бухара", "бухарская"],
      ["andijon", "andijan", "андижан", "андижанская"],
      ["fargona", "farg ona", "fergana", "фергана", "ферганская"],
      ["namangan", "наманган", "наманганская"],
      ["navoiy", "navoi", "навои", "навоийская"],
      ["qashqadaryo", "kashkadarya", "кашкадарья", "кашкадарьинская"],
      ["surxondaryo", "surkhandarya", "сурхандарья", "сурхандарьинская"],
      ["sirdaryo", "syrdarya", "сырдарья", "сырдарьинская"],
      ["xorazm", "khorezm", "хорезм", "хорезмская"],
      ["qoraqalpogiston", "karakalpakstan", "каракалпакстан"],
    ];
    const aliasTerms = aliasGroups
      .filter((group) => group.some((term) => joined.includes(term)))
      .flat();

    return Array.from(new Set([
      ...base,
      ...aliasTerms,
    ]));
  }

  const effectiveFromCityId = orderForm.from_city_id;
  const effectiveToCityId = orderForm.to_city_id;
  const fromDistrictReady = !fromCity?.requires_district || Boolean(orderForm.from_district_id);
  const toDistrictReady = !toCity?.requires_district || Boolean(orderForm.to_district_id);
  const routeDistrictsReady = fromDistrictReady && toDistrictReady;

  async function loadClientOrders() {
    const result = await listClientOrders({ limit: 50 });
    setOrders(result.items ?? []);
  }

  async function openClientOrder(id: number, target: Screen = "client-order-detail") {
    setSelectedOrderId(id);
    const detail = await getClientOrder(id);
    setOrderDetail(detail as OrderDetail);
    if (target === "client-bids") {
      setBids(await listClientOrderBids(id));
    }
    go(target);
  }

  function resetOrderDraft() {
    setEditingOrderId(null);
    setOrderForm(emptyOrder);
    setSelectedFromCity(null);
    setSelectedToCity(null);
    setSelectedFromDistrict(null);
    setSelectedToDistrict(null);
  }

  function beginEditOrder(order: OrderDetail) {
    const fromCityRef = order.from_city ?? null;
    const toCityRef = order.to_city ?? null;
    const fromDistrictRef = order.from_district ?? null;
    const toDistrictRef = order.to_district ?? null;
    const fromCityId = fromCityRef?.id ?? 0;
    const toCityId = toCityRef?.id ?? 0;

    setEditingOrderId(order.id);
    setSelectedFromCity(cities.find((city) => city.id === fromCityId) ?? fromCityRef);
    setSelectedToCity(cities.find((city) => city.id === toCityId) ?? toCityRef);
    setSelectedFromDistrict(fromDistrictRef);
    setSelectedToDistrict(toDistrictRef);
    setOrderForm({
      from_city_id: fromCityId,
      to_city_id: toCityId,
      from_district_id: fromDistrictRef?.id ?? null,
      to_district_id: toDistrictRef?.id ?? null,
      pickup_address: order.pickup_address ?? "",
      dropoff_address: order.dropoff_address ?? "",
      pickup_lat: nullableNumber(order.pickup_lat),
      pickup_lng: nullableNumber(order.pickup_lng),
      dropoff_lat: nullableNumber(order.dropoff_lat),
      dropoff_lng: nullableNumber(order.dropoff_lng),
      sender_phone: order.sender_phone ?? auth.user?.phone ?? "",
      receiver_phone: order.receiver_phone ?? "",
      cargo_photo_url: order.cargo_photo_url ?? "",
      comment: order.comment ?? "",
    });
    go("client-route-summary");
  }

  async function loadDriverProfile() {
    const profile = await getDriverProfile();
    setDriverProfile(profile);
    setDriverForm({
      full_name: profile.full_name ?? profile.user?.full_name ?? "",
      car_model: profile.car_model ?? "",
      car_color: profile.car_color ?? "",
      plate_number: profile.plate_number ?? "",
    });
  }

  async function loadDriverRoutes() {
    setDriverRoutes(await getDriverRoutes());
  }

  async function loadDriverFeed() {
    const data = await getDriverFeed({ limit: 50 });
    setDriverFeed(data.items ?? []);
  }

  async function loadDriverOrders() {
    const data = await getDriverOrders({ limit: 50 });
    setDriverFeed(data.items ?? []);
  }

  function startEditDriverRoute(route: DriverRoute) {
    const fromCityRef = typeof route.from_city === "object" && route.from_city && "id" in route.from_city ? route.from_city as City : null;
    const toCityRef = typeof route.to_city === "object" && route.to_city && "id" in route.to_city ? route.to_city as City : null;
    const fromDistrictRef = typeof route.from_district === "object" && route.from_district && "id" in route.from_district ? route.from_district as District : null;
    const toDistrictRef = typeof route.to_district === "object" && route.to_district && "id" in route.to_district ? route.to_district as District : null;
    setEditingRouteId(route.id);
    setRouteForm({
      from_city_id: fromCityRef?.id ?? 0,
      from_district_id: route.from_district_id ?? fromDistrictRef?.id ?? null,
      to_city_id: toCityRef?.id ?? 0,
      to_district_id: route.to_district_id ?? toDistrictRef?.id ?? null,
    });
    setDistricts([fromDistrictRef, toDistrictRef].filter(Boolean) as District[]);
    go("driver-add-route");
  }

  async function loadNotifications() {
    const data = await getNotifications({ limit: 50 });
    setNotifications(data.items ?? []);
  }

  async function runConfirmAction(action: ConfirmAction) {
    if (action.type === "select-driver") {
      if (!selectedOrderId || !(action.bid.id ?? action.bid.bid_id)) return;
      await selectDriver(selectedOrderId, Number(action.bid.id ?? action.bid.bid_id));
      setConfirmAction(null);
      await openClientOrder(selectedOrderId);
      return;
    }
    if (action.type === "confirm-delivery" && orderDetail) {
      await confirmClientOrder(orderDetail.id);
      setConfirmAction(null);
      go("client-rating");
      return;
    }
    if (action.type === "cancel-order" && orderDetail) {
      await cancelClientOrder(orderDetail.id, "Mijoz bekor qildi");
      setConfirmAction(null);
      await loadClientOrders();
      go("client-orders");
    }
  }

  useEffect(() => {
    if (!auth.isAuthenticated) return;
    if (screen === "client-home" || screen === "client-orders") void run(loadClientOrders);
    if (screen === "client-notifications") void run(loadNotifications);
    if (screen === "client-profile") {
      void run(async () => {
        const profile = await getClientProfile();
        setClientName(profile.full_name ?? "");
        await loadClientOrders();
      });
    }
    if (screen === "driver-home" || screen === "driver-profile" || screen === "driver-income") {
      void run(async () => {
        await loadDriverProfile();
        if (screen === "driver-home" || screen === "driver-income") {
          try {
            await loadDriverOrders();
          } catch {
            setDriverFeed([]);
          }
        }
        if (screen === "driver-profile") await loadDriverRoutes();
      });
    }
    if (screen === "driver-routes") void run(loadDriverRoutes);
    if (screen === "driver-feed") void run(loadDriverFeed);
    if (screen === "driver-orders") void run(loadDriverOrders);
  }, [screen, auth.isAuthenticated]);

  const content = (() => {
    if (auth.isLoading) {
      return <EmptyState icon={Loader2} title="Yuklanmoqda..." />;
    }

    if (screen === "splash") {
      return (
        <main className="flex flex-1 flex-col items-center justify-between bg-[#1B4FD8] px-5 py-12 text-white">
          <div />
          <div className="flex flex-col items-center gap-6 text-center">
            <div className="flex h-24 w-24 items-center justify-center rounded-[28px] bg-white/15">
              <Truck size={46} />
            </div>
            <div>
              <h1 className="text-[38px] font-bold">Elchi</h1>
              <p className="mt-2 text-[16px] leading-6 text-white/75">Shaharlararo posilka yetkazish xizmati</p>
            </div>
          </div>
          <PrimaryButton onClick={() => go("onboarding")}>Boshlash</PrimaryButton>
        </main>
      );
    }

    if (screen === "onboarding") {
      const steps = [
        ["Posilkangizni shahardan shaharga yuboring", "Yo'nalishni tanlang, manzillarni kiriting va haydovchilardan taklif oling.", MapPin],
        ["Haydovchilar narx taklif qiladi", "Sizga mos narx va haydovchini o'zingiz tanlaysiz.", FileText],
        ["Yetkazildi - tasdiqlang va baholang", "Posilka yetib borgach, buyurtmani tasdiqlang va haydovchiga baho bering.", CheckCircle],
      ] as const;
      const [title, subtitle, Icon] = steps[onboardingStep];
      return (
        <main className="flex flex-1 flex-col bg-white px-8 py-8">
          <div className="flex flex-1 flex-col items-center justify-center text-center">
            <div className="mb-10 flex h-32 w-32 items-center justify-center rounded-[36px] bg-[#EEF2FF]">
              <Icon size={60} color="#1B4FD8" />
            </div>
            <h2 className="text-[22px] font-bold leading-[30px] text-[#111827]">{title}</h2>
            <p className="mt-3 text-[15px] leading-6 text-[#6B7280]">{subtitle}</p>
          </div>
          <div className="space-y-3">
            <PrimaryButton onClick={() => (onboardingStep < 2 ? setOnboardingStep(onboardingStep + 1) : go("role"))}>
              {onboardingStep < 2 ? "Keyingisi" : "Boshlash"}
            </PrimaryButton>
            {onboardingStep < 2 && <SecondaryButton onClick={() => go("role")}>O'tkazib yuborish</SecondaryButton>}
          </div>
        </main>
      );
    }

    if (screen === "role") {
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA] px-5 py-8">
          <h1 className="text-[26px] font-bold text-[#111827]">Elchiga xush kelibsiz</h1>
          <p className="mt-2 text-[15px] text-[#6B7280]">Davom etish uchun rolingizni tanlang</p>
          <div className="mt-8 space-y-3">
            {[
              ["client", User, "Men mijozman"],
              ["driver", Truck, "Men haydovchiman"],
            ].map(([role, Icon, label]) => (
              <button
                key={role as string}
                onClick={() => setSelectedRole(role as MobileRole)}
                className={cls(
                  "flex w-full items-center gap-4 rounded-[16px] border bg-white p-4 text-left",
                  selectedRole === role ? "border-[#1B4FD8]" : "border-[#E5E7EB]",
                )}
              >
                <Icon size={28} color="#1B4FD8" />
                <span className="flex-1 text-[16px] font-semibold text-[#111827]">{label as string}</span>
                {selectedRole === role && <Check size={18} color="#1B4FD8" />}
              </button>
            ))}
          </div>
          <div className="mt-auto">
            <PrimaryButton onClick={() => go("phone")}>Davom etish</PrimaryButton>
          </div>
        </main>
      );
    }

    if (screen === "phone") {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Telefon raqami" back={() => go("role")} />
          <section className="flex flex-1 flex-col gap-5 px-5 py-6">
            <div>
              <h2 className="text-[24px] font-bold text-[#111827]">Telefon raqamingizni kiriting</h2>
              <p className="mt-2 text-[15px] text-[#6B7280]">Tasdiqlash kodi SMS orqali yuboriladi</p>
            </div>
            <Field label="Telefon raqam" value={phone} onChange={setPhone} placeholder="+998 __ ___ __ __" />
            <div className="mt-auto">
              <PrimaryButton
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await auth.requestOtp({ phone, role: selectedRole });
                    go("otp");
                  }, "Kod yuborildi")
                }
              >
                Kod olish
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "otp") {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Tasdiqlash kodi" back={() => go("phone")} />
          <section className="flex flex-1 flex-col gap-5 px-5 py-6">
            <p className="text-[15px] leading-6 text-[#6B7280]">Raqamingizga yuborilgan 5 xonali kodni kiriting</p>
            <Field label="5 xonali kod" value={otp} onChange={setOtp} placeholder="12345" />
            <p className="text-[13px] text-[#6B7280]">Mahalliy test kodi odatda: 12345</p>
            <div className="mt-auto space-y-3">
              <PrimaryButton
                disabled={busy || otp.trim().length < 6}
                onClick={() =>
                  run(async () => {
                    const user = await auth.loginWithOtp({ phone: normalizeUzPhone(phone), role: selectedRole, otp });
                    go(user.role === "driver" ? "driver-home" : "client-home");
                  })
                }
              >
                Tasdiqlash
              </PrimaryButton>
              <SecondaryButton onClick={() => run(() => auth.requestOtp({ phone, role: selectedRole }), "Kod qayta yuborildi")}>
                Kodni qayta yuborish
              </SecondaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-home") {
      return (
        <main className="relative flex flex-1 flex-col overflow-hidden bg-[#E5E7EB]">
          <ClientMapCanvas
            pickupLat={orderForm.pickup_lat}
            pickupLng={orderForm.pickup_lng}
            dropoffLat={orderForm.dropoff_lat}
            dropoffLng={orderForm.dropoff_lng}
          />
          <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between px-5 pt-4">
            <button
              type="button"
              onClick={() => go("client-orders")}
              className="pointer-events-auto flex h-11 w-11 items-center justify-center rounded-full bg-white shadow-lg"
              aria-label="Buyurtmalar"
            >
              <Menu size={20} />
            </button>
            <button
              type="button"
              className="pointer-events-auto flex h-11 w-11 items-center justify-center rounded-full bg-white text-[#1B4FD8] shadow-lg"
              aria-label="Joriy joylashuv"
            >
              <LocateFixed size={20} />
            </button>
          </div>
          <section className="absolute inset-x-0 bottom-16 z-10 rounded-t-[26px] bg-white px-5 pb-4 pt-4 shadow-[0_-10px_30px_rgba(15,23,42,0.18)]">
            <div className="mx-auto mb-4 h-1.5 w-20 rounded-full bg-[#D1D5DB]" />
            <h1 className="text-[22px] font-bold text-[#111827]">Yuk yuborish</h1>
            <p className="mt-1 text-[13px] leading-5 text-[#6B7280]">Shahar va aniq manzilni tanlang, haydovchilardan taklif oling.</p>
            <div className="mt-4 overflow-hidden rounded-[18px] border border-[#E5E7EB] bg-white">
              <LocationPointRow
                label="Olib ketish joyi"
                address={orderForm.pickup_address}
                hasPoint={hasLocation(orderForm.pickup_lat, orderForm.pickup_lng)}
                onClick={() => openLocationSelector("pickup")}
                icon={Navigation}
              />
              <div className="ml-[76px] h-px bg-[#E5E7EB]" />
              <LocationPointRow
                label="Qayerga?"
                address={orderForm.dropoff_address}
                hasPoint={hasLocation(orderForm.dropoff_lat, orderForm.dropoff_lng)}
                onClick={() => openLocationSelector("dropoff")}
                icon={MapPin}
              />
            </div>
            {Boolean(effectiveFromCityId && effectiveToCityId) && (
              <div className="mt-3 rounded-[14px] bg-[#EEF2FF] px-4 py-3">
                <p className="text-[12px] font-semibold text-[#1B4FD8]">Tavsiya etilgan narx</p>
                <p className="mt-0.5 text-[18px] font-bold text-[#111827]">
                  {suggestedPrice ? formatUzs(suggestedPrice) : "Narx haydovchi bilan kelishiladi"}
                </p>
                <p className="mt-1 text-[12px] leading-5 text-[#6B7280]">
                  Haydovchilar o'z taklifini yuboradi.
                </p>
              </div>
            )}
            <div className="mt-3 grid grid-cols-3 gap-2.5">
              {[
                ["Faol", orders.filter((o) => !["confirmed", "cancelled"].includes(o.status)).length],
                ["Takliflar", orders.reduce((sum, o) => sum + (o.bids_count ?? 0), 0)],
                ["Yakunlangan", orders.filter((o) => o.status === "confirmed").length],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-[12px] border border-[#E5E7EB] bg-[#F9FAFB] p-2.5 text-center">
                  <p className="text-[18px] font-bold text-[#111827]">{value}</p>
                  <p className="text-[11px] text-[#6B7280]">{label}</p>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <PrimaryButton
                disabled={!effectiveFromCityId || !effectiveToCityId || !routeDistrictsReady || !orderForm.pickup_address || !orderForm.dropoff_address}
                onClick={() => {
                  setOrderForm((current) => ({
                    ...current,
                    from_city_id: current.from_city_id || effectiveFromCityId,
                    to_city_id: current.to_city_id || effectiveToCityId,
                  }));
                  go("client-route-summary");
                }}
              >
                Yo'nalishni ko'rish
              </PrimaryButton>
              {orderForm.pickup_address && orderForm.dropoff_address && (!effectiveFromCityId || !effectiveToCityId) && (
                <p className="mt-2 text-center text-[12px] leading-5 text-[#DC2626]">
                  Yo'nalishni davom ettirish uchun shaharni tanlang. Manzil qatorini bosib, ro'yxatdan shaharni tanlashingiz mumkin.
                </p>
              )}
              {orderForm.pickup_address && orderForm.dropoff_address && !routeDistrictsReady && (
                <p className="mt-2 text-center text-[12px] leading-5 text-[#DC2626]">
                  Yo'nalishni davom ettirish uchun tuman tanlang.
                </p>
              )}
            </div>
          </section>
          <div className="absolute inset-x-0 bottom-0 z-20">
            <BottomNav role="client" active={screen} go={go} />
          </div>
        </main>
      );
    }

    if (screen === "client-location-selector") {
      const selectorTitle = locationSelectorMode === "pickup" ? "Qayerdan?" : "Qayerga?";
      return (
        <CitySelector
          mode={locationSelectorMode}
          title={selectorTitle}
          onSelectCity={selectCityForLocation}
          onBack={() => go("client-home")}
        />
      );
    }

    if (screen === "client-district-selector") {
      if (!districtMode.startsWith("driver") && districtCity) {
        return (
          <DistrictSelector
            mode={districtMode === "client-pickup" ? "pickup" : "dropoff"}
            city={districtCity}
            onSelectDistrict={selectDistrict}
            onBack={() => go("client-location-selector")}
          />
        );
      }
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Tumanni tanlang" back={() => {
            if (districtMode.startsWith("driver")) go("driver-add-route");
            else go("client-location-selector");
          }} />
          <section className="flex min-h-0 flex-1 flex-col">
            <div className="border-b border-[#E5E7EB] px-5 py-4">
              <p className="mb-2 text-[13px] font-semibold text-[#6B7280]">{districtCity?.name_uz}</p>
              <label className="flex h-12 items-center gap-3 rounded-[16px] border-2 border-[#38BDF8] bg-white px-4">
                <Search size={19} color="#6B7280" />
                <input
                  value={districtQuery}
                  onChange={(event) => setDistrictQuery(event.target.value)}
                  placeholder="Tuman qidirish"
                  className="min-w-0 flex-1 bg-transparent text-[15px] text-[#111827] outline-none"
                />
              </label>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {filteredDistricts.length ? (
                filteredDistricts.map((district) => (
                  <DistrictSelectorRow key={district.id} district={district} onClick={() => selectDistrict(district)} />
                ))
              ) : (
                <EmptyState icon={MapPin} title="Tumanlar topilmadi" subtitle="Boshqa nom bilan qidirib ko'ring." />
              )}
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-route-summary") {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title={editingOrderId ? "Buyurtmani tahrirlash" : "Yo'nalish"} back={() => (editingOrderId ? go("client-order-detail") : go("client-home"))} />
          <section className="flex flex-1 flex-col px-5 py-5">
            <div className="overflow-hidden rounded-[18px] border border-[#E5E7EB] bg-white">
              <RouteSummaryRow
                label="Olib ketish"
                address={orderForm.pickup_address}
                city={fromCity ? `${fromCity.name_uz}${fromCity.region ? `, ${fromCity.region}` : ""}` : undefined}
                district={fromDistrict?.name_uz}
                onEdit={() => openLocationSelector("pickup")}
                icon={Navigation}
              />
              <RouteSummaryRow
                label="Yetkazish"
                address={orderForm.dropoff_address}
                city={toCity ? `${toCity.name_uz}${toCity.region ? `, ${toCity.region}` : ""}` : undefined}
                district={toDistrict?.name_uz}
                onEdit={() => openLocationSelector("dropoff")}
                icon={MapPin}
              />
            </div>
            <div className="mt-4 rounded-[16px] bg-[#F9FAFB] p-4">
              <p className="text-[13px] font-semibold text-[#374151]">Xarita holati</p>
              <p className="mt-1 text-[13px] text-[#6B7280]">
                Olib ketish: {formatMapSelectionStatus(orderForm.pickup_lat, orderForm.pickup_lng)}
              </p>
              <p className="mt-1 text-[13px] text-[#6B7280]">
                Yetkazish: {formatMapSelectionStatus(orderForm.dropoff_lat, orderForm.dropoff_lng)}
              </p>
            </div>
            {Boolean(orderForm.from_city_id && orderForm.to_city_id) && (
              <div className="mt-4 rounded-[16px] bg-[#EEF2FF] p-4">
                <p className="text-[13px] font-semibold text-[#1B4FD8]">Tavsiya etilgan narx</p>
                <p className="mt-1 text-[20px] font-bold text-[#111827]">
                  {suggestedPrice ? formatUzs(suggestedPrice) : "Narx haydovchi bilan kelishiladi"}
                </p>
                <p className="mt-1 text-[13px] leading-5 text-[#6B7280]">
                  {suggestedPrice ? "Bu tavsiya narx. " : ""}Haydovchilar o'z taklifini yuboradi.
                </p>
              </div>
            )}
            <div className="mt-auto">
              <PrimaryButton disabled={!orderForm.pickup_address || !orderForm.dropoff_address} onClick={() => go("client-order-address")}>
                Saqlash
              </PrimaryButton>
              {editingOrderId && (
                <button type="button" onClick={() => { resetOrderDraft(); go("client-order-detail"); }} className="mt-3 h-10 w-full text-[14px] font-semibold text-[#6B7280]">
                  Tahrirlashni bekor qilish
                </button>
              )}
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-order-route") {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Yo'nalishni tanlang" back={() => go("client-home")} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <CitySelect cities={cities} label="Qayerdan" value={orderForm.from_city_id} onChange={(v) => setOrderForm({ ...orderForm, from_city_id: v })} />
            <CitySelect cities={cities} label="Qayerga" value={orderForm.to_city_id} onChange={(v) => setOrderForm({ ...orderForm, to_city_id: v })} />
            <div className="rounded-[16px] bg-[#EEF2FF] p-4">
              <p className="text-[13px] font-semibold text-[#1B4FD8]">Tavsiya etilgan narx</p>
              <p className="mt-1 text-[22px] font-bold text-[#111827]">{formatUzs(suggestedPrice)}</p>
            </div>
            <div className="rounded-[16px] border border-[#DBEAFE] bg-white p-4">
              <div className="flex items-start gap-3">
                <MapPin className="mt-0.5 shrink-0" size={20} color="#1B4FD8" />
                <div>
                  <p className="text-[15px] font-semibold text-[#111827]">Xarita keyingi bosqichda</p>
                  <p className="mt-1 text-[13px] leading-5 text-[#6B7280]">
                    Shaharlarni tanlagandan keyin olib ketish va yetkazish joyini xaritadan belgilaysiz.
                  </p>
                </div>
              </div>
            </div>
            <div className="mt-auto">
              <PrimaryButton disabled={!orderForm.from_city_id || !orderForm.to_city_id} onClick={() => go("client-order-address")}>
                Davom etish
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-order-address") {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Aloqa ma'lumotlari" back={() => go("client-route-summary")} />
          <section className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <div className="rounded-[18px] bg-[#F9FAFB] p-4">
              <p className="text-[13px] font-semibold text-[#6B7280]">Yo'nalish</p>
              <p className="mt-1 text-[15px] font-semibold text-[#111827]">{formatShortAddress(orderForm.pickup_address)}</p>
              <p className="mt-1 text-[15px] font-semibold text-[#111827]">{formatShortAddress(orderForm.dropoff_address)}</p>
            </div>
            <Field label="Yuboruvchi telefon raqami" value={orderForm.sender_phone} placeholder="+998 __ ___ __ __" onChange={(v) => setOrderForm({ ...orderForm, sender_phone: v })} />
            <Field label="Qabul qiluvchi telefon raqami" value={orderForm.receiver_phone} placeholder="+998 __ ___ __ __" onChange={(v) => setOrderForm({ ...orderForm, receiver_phone: v })} />
            <Field label="Izoh" value={orderForm.comment ?? ""} multiline onChange={(v) => setOrderForm({ ...orderForm, comment: v })} />
            <PrimaryButton
              disabled={!orderForm.sender_phone || !orderForm.receiver_phone}
              onClick={() => go("client-order-photo")}
            >
              Davom etish
            </PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "client-order-photo") {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Posilka rasmi" back={() => go("client-order-address")} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <label className="flex cursor-pointer flex-col items-center justify-center rounded-[16px] border border-dashed border-[#1B4FD8] bg-[#EEF2FF] p-8 text-center">
              <Upload size={30} color="#1B4FD8" />
              <span className="mt-3 text-[16px] font-semibold text-[#111827]">Rasm yuklash</span>
              <span className="mt-1 text-[13px] text-[#6B7280]">Posilkani haydovchi ko'rishi uchun bitta rasm yuklang</span>
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  void run(async () => {
                    const uploaded = await uploadFile(file, "cargo_photo");
                    setOrderForm((current) => ({ ...current, cargo_photo_url: uploaded.file_url }));
                  }, "Rasm yuklandi");
                }}
              />
            </label>
            {orderForm.cargo_photo_url && <p className="text-[13px] text-[#16A34A]">Rasm tayyor: {orderForm.cargo_photo_url}</p>}
            {!orderForm.cargo_photo_url && <p className="text-[13px] text-[#DC2626]">Posilka rasmini yuklang</p>}
            <div className="mt-auto">
              <PrimaryButton disabled={!orderForm.cargo_photo_url} onClick={() => go("client-order-review")}>
                Buyurtmani ko'rib chiqish
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-order-review") {
      const isEditing = editingOrderId !== null;
      const canPublish = Boolean(
        orderForm.from_city_id
        && orderForm.to_city_id
        && routeDistrictsReady
        && orderForm.pickup_address
        && orderForm.dropoff_address
        && orderForm.sender_phone
        && orderForm.receiver_phone
        && orderForm.cargo_photo_url,
      );

      return (
        <main className="relative flex min-h-0 flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title={isEditing ? "O'zgarishlarni tekshiring" : "Buyurtmani tekshiring"} back={() => go("client-order-photo")} />
          <section className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            {[
              ["Yo'nalish", `${fromCity?.name_uz ?? "-"} -> ${toCity?.name_uz ?? "-"}`],
              ["Olib ketish tumani", fromDistrict?.name_uz ?? (fromCity?.requires_district ? "-" : "Talab qilinmaydi")],
              ["Olib ketish", orderForm.pickup_address],
              ["Olib ketish xaritasi", hasLocation(orderForm.pickup_lat, orderForm.pickup_lng) ? "Xaritada belgilangan" : "Xaritada belgilanmagan"],
              ["Yetkazish tumani", toDistrict?.name_uz ?? (toCity?.requires_district ? "-" : "Talab qilinmaydi")],
              ["Yetkazish", orderForm.dropoff_address],
              ["Yetkazish xaritasi", hasLocation(orderForm.dropoff_lat, orderForm.dropoff_lng) ? "Xaritada belgilangan" : "Xaritada belgilanmagan"],
              ["Telefonlar", `${orderForm.sender_phone} / ${orderForm.receiver_phone}`],
              ["Posilka rasmi", orderForm.cargo_photo_url ? "Yuklangan" : "Yuklanmagan"],
              ["Tavsiya narx", formatUzs(suggestedPrice)],
              ["Izoh", orderForm.comment || "-"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <p className="text-[12px] text-[#6B7280]">{label}</p>
                <p className="mt-1 text-[15px] font-semibold text-[#111827]">{value}</p>
              </div>
            ))}
          </section>
          <div className="absolute inset-x-0 bottom-0 z-20 border-t border-[#E5E7EB] bg-white px-5 py-4 shadow-[0_-8px_20px_rgba(15,23,42,0.08)]">
            {!canPublish && (
              <p className="mb-2 text-center text-[12px] leading-5 text-[#DC2626]">
                E'lon qilish uchun yo'nalish, telefonlar va posilka rasmi to'liq bo'lishi kerak.
              </p>
            )}
            <PrimaryButton
              disabled={busy || !canPublish}
              onClick={() =>
                run(async () => {
                  if (editingOrderId !== null) {
                    const updated = await updateClientOrder(editingOrderId, orderForm);
                    setOrderDetail(updated as OrderDetail);
                    setSelectedOrderId(updated.id);
                    resetOrderDraft();
                    await loadClientOrders();
                    go("client-order-detail");
                    return;
                  }
                  const created = await createClientOrder(orderForm);
                  const published = await publishClientOrder(created.id);
                  setSelectedOrderId(published.id ?? created.id);
                  resetOrderDraft();
                  await loadClientOrders();
                  go("client-success");
                })
              }
            >
              {isEditing ? "O'zgarishlarni saqlash" : "Buyurtmani e'lon qilish"}
            </PrimaryButton>
            <button type="button" onClick={() => go("client-order-address")} className="mt-3 h-10 w-full text-[14px] font-semibold text-[#1B4FD8]">
              Tahrirlash
            </button>
          </div>
        </main>
      );
    }

    if (screen === "client-success") {
      return (
        <main className="flex flex-1 flex-col items-center justify-center bg-white px-6 text-center">
          <CheckCircle size={72} color="#16A34A" />
          <h1 className="mt-5 text-[24px] font-bold text-[#111827]">Buyurtma e'lon qilindi</h1>
          <p className="mt-2 text-[15px] leading-6 text-[#6B7280]">Haydovchilardan takliflar kutilmoqda</p>
          <p className="mt-1 text-[14px] leading-6 text-[#6B7280]">Taklif kelganda sizga xabar beramiz</p>
          <div className="mt-8 w-full">
            <PrimaryButton onClick={() => go("client-orders")}>Buyurtmalarimga o'tish</PrimaryButton>
          </div>
        </main>
      );
    }

    if (screen === "client-orders") {
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <section className="flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <h1 className="text-[24px] font-bold text-[#111827]">Buyurtmalar</h1>
            {orders.length ? orders.map((order) => <OrderCard key={order.id} order={order} onClick={() => void run(() => openClientOrder(order.id))} />) : <EmptyState icon={Package} title="Hozircha buyurtmalar yo'q" />}
          </section>
          <BottomNav role="client" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "client-order-detail" && orderDetail) {
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title="Buyurtma tafsilotlari" back={() => go("client-orders")} />
          <section className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <OrderCard order={orderDetail} />
            {[
              ["Olib ketish", orderDetail.pickup_address],
              ["Yetkazish", orderDetail.dropoff_address],
              ["Yuboruvchi", orderDetail.sender_phone],
              ["Qabul qiluvchi", orderDetail.receiver_phone],
              ["Izoh", orderDetail.comment || "-"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <p className="text-[12px] text-[#6B7280]">{label}</p>
                <p className="mt-1 text-[14px] font-medium text-[#111827]">{value}</p>
              </div>
            ))}
            {orderDetail.assigned_driver && (
              <div className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <p className="text-[12px] text-[#6B7280]">Haydovchi</p>
                <p className="mt-1 text-[15px] font-semibold text-[#111827]">{orderDetail.assigned_driver.full_name ?? "Haydovchi"}</p>
                <p className="text-[13px] text-[#6B7280]">{orderDetail.assigned_driver.car_model} / {orderDetail.assigned_driver.plate_number}</p>
              </div>
            )}
            {(hasLocation(orderDetail.pickup_lat, orderDetail.pickup_lng) || hasLocation(orderDetail.dropoff_lat, orderDetail.dropoff_lng)) && (
              <div className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <p className="text-[12px] text-[#6B7280]">Xarita nuqtalari</p>
                <p className="mt-1 text-[14px] font-medium text-[#111827]">
                  {hasLocation(orderDetail.pickup_lat, orderDetail.pickup_lng) ? "Olib ketish joyi belgilangan" : "Olib ketish joyi belgilanmagan"}
                </p>
                <p className="mt-1 text-[14px] font-medium text-[#111827]">
                  {hasLocation(orderDetail.dropoff_lat, orderDetail.dropoff_lng) ? "Yetkazish joyi belgilangan" : "Yetkazish joyi belgilanmagan"}
                </p>
                <button
                  type="button"
                  onClick={() => setReadOnlyMap({
                    pickupLat: orderDetail.pickup_lat,
                    pickupLng: orderDetail.pickup_lng,
                    dropoffLat: orderDetail.dropoff_lat,
                    dropoffLng: orderDetail.dropoff_lng,
                    destinationLat: orderDetail.dropoff_lat,
                    destinationLng: orderDetail.dropoff_lng,
                  })}
                  className="mt-3 h-10 w-full rounded-[10px] bg-[#EEF2FF] text-[14px] font-semibold text-[#1B4FD8]"
                >
                  Xaritada ko'rish
                </button>
              </div>
            )}
            <StatusTimeline status={orderDetail.status} />
            {["published", "bidding"].includes(orderDetail.status) && (orderDetail.bids_count ?? 0) === 0 && (
              <EmptyState icon={Package} title="Hozircha takliflar yo'q" subtitle="Haydovchilar taklif yuborishi bilan shu yerda ko'rasiz" />
            )}
            {orderDetail.status === "delivered" && <PrimaryButton onClick={() => setConfirmAction({ type: "confirm-delivery" })}>Yetkazilganini tasdiqlash</PrimaryButton>}
            {["draft", "published", "bidding"].includes(orderDetail.status) && (
              <SecondaryButton onClick={() => beginEditOrder(orderDetail)}>
                Buyurtmani tahrirlash
              </SecondaryButton>
            )}
            {["published", "bidding"].includes(orderDetail.status) && <PrimaryButton onClick={() => void run(() => openClientOrder(orderDetail.id, "client-bids"))}>Takliflarni ko'rish</PrimaryButton>}
            {["draft", "published", "bidding", "accepted"].includes(orderDetail.status) && (
              <SecondaryButton danger onClick={() => setConfirmAction({ type: "cancel-order" })}>
                Buyurtmani bekor qilish
              </SecondaryButton>
            )}
            {["picked_up", "in_transit", "delivered", "disputed"].includes(orderDetail.status) && (
              <SecondaryButton onClick={() => go("client-dispute")}>Muammo haqida xabar berish</SecondaryButton>
            )}
          </section>
        </main>
      );
    }

    if (screen === "client-bids") {
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title="Haydovchi takliflari" back={() => go("client-order-detail")} />
          <section className="flex-1 space-y-3 overflow-y-auto px-5 py-5">
            {bids.length ? bids.map((bid) => (
              <div key={bid.id ?? bid.bid_id} className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[16px] font-semibold text-[#111827]">{bid.driver?.full_name ?? "Haydovchi"}</p>
                    <p className="text-[13px] text-[#6B7280]">{bid.driver?.car_model ?? "-"} / {bid.driver?.plate_number ?? "-"}</p>
                    <p className="mt-1 text-[13px] text-[#6B7280]">Reyting: {bid.driver?.rating ?? "-"}</p>
                  </div>
                  <p className="text-[17px] font-bold text-[#1B4FD8]">{formatUzs(bid.price)}</p>
                </div>
                <div className="mt-4">
                  <PrimaryButton
                    onClick={() => setConfirmAction({ type: "select-driver", bid })}
                  >
                    Shu haydovchini tanlash
                  </PrimaryButton>
                </div>
              </div>
            )) : <EmptyState icon={Package} title="Hozircha takliflar yo'q" subtitle="Haydovchilar taklif yuborishi bilan shu yerda ko'rasiz" />}
          </section>
        </main>
      );
    }

    if (screen === "client-confirm" && orderDetail) {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Buyurtmani tasdiqlang" back={() => go("client-order-detail")} />
          <section className="flex flex-1 flex-col justify-center gap-5 px-5 text-center">
            <CheckCircle className="mx-auto" size={72} color="#16A34A" />
            <p className="text-[16px] leading-6 text-[#374151]">Posilka yetib kelgan bo'lsa, buyurtmani tasdiqlang.</p>
            <PrimaryButton onClick={() => run(async () => { await confirmClientOrder(orderDetail.id); go("client-rating"); }, "Buyurtma tasdiqlandi")}>Tasdiqlash</PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "client-rating" && selectedOrderId) {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Haydovchini baholang" back={() => go("client-orders")} />
          <section className="flex flex-1 flex-col gap-5 px-5 py-6">
            <p className="text-center text-[14px] text-[#6B7280]">1 dan 5 gacha baho bering</p>
            <div className="flex justify-center gap-2">
              {[1, 2, 3, 4, 5].map((value) => (
                <button key={value} onClick={() => setRating(value)}>
                  <Star fill={value <= rating ? "#F59E0B" : "none"} color="#F59E0B" size={34} />
                </button>
              ))}
            </div>
            <Field label="Izoh qoldiring" value={ratingComment} multiline onChange={setRatingComment} />
            <div className="mt-auto">
              <PrimaryButton onClick={() => run(async () => { await rateClientOrder(selectedOrderId, { rating, comment: ratingComment || null }); go("client-orders"); }, "Baho yuborildi")}>Bahoni yuborish</PrimaryButton>
              <button type="button" onClick={() => go("client-orders")} className="mt-3 h-10 w-full text-[14px] font-semibold text-[#6B7280]">
                Keyinroq
              </button>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-dispute" && orderDetail) {
      const reasons = ["Haydovchi kelmadi", "Posilka kechikdi", "Narx bo'yicha kelishmovchilik", "Boshqa muammo"];
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Muammo haqida xabar berish" back={() => go("client-order-detail")} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <label className="flex flex-col gap-1.5">
              <span className="text-[14px] font-medium text-[#374151]">Muammo turi</span>
              <select
                value={disputeReason}
                onChange={(event) => setDisputeReason(event.target.value)}
                className="h-[52px] rounded-[12px] border border-[#E5E7EB] bg-white px-4 text-[15px] text-[#111827] outline-none"
              >
                {reasons.map((reason) => <option key={reason} value={reason}>{reason}</option>)}
              </select>
            </label>
            <Field label="Izoh" value={disputeComment} multiline onChange={setDisputeComment} />
            <div className="mt-auto">
              <PrimaryButton
                onClick={() => run(async () => {
                  await openClientDispute(orderDetail.id, { reason: disputeReason, comment: disputeComment || null });
                  setDisputeComment("");
                  await openClientOrder(orderDetail.id);
                }, "Nizo ochildi. Operatorlar muammoni ko'rib chiqadi")}
              >
                Yuborish
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-notifications") {
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <section className="flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <h1 className="text-[24px] font-bold text-[#111827]">Bildirishnomalar</h1>
            {notifications.length ? notifications.map((item) => (
              <button
                key={item.id}
                onClick={() => run(async () => {
                  await markNotificationRead(item.id).catch(() => undefined);
                  await loadNotifications();
                  const orderId = item.order_id ?? (item.entity_type === "order" ? item.entity_id : undefined);
                  if (orderId) await openClientOrder(orderId, item.type === "new_bid" ? "client-bids" : "client-order-detail");
                })}
                className={cls("w-full rounded-[14px] border bg-white p-4 text-left", item.is_read ? "border-[#E5E7EB]" : "border-[#BFDBFE]")}
              >
                <p className="text-[15px] font-semibold text-[#111827]">{item.title}</p>
                <p className="mt-1 text-[13px] text-[#6B7280]">{item.message ?? item.body}</p>
              </button>
            )) : <EmptyState icon={Bell} title="Hozircha bildirishnomalar yo'q" />}
          </section>
          <BottomNav role="client" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "client-profile") {
      const activeOrders = orders.filter((order) => !["confirmed", "cancelled"].includes(order.status)).length;
      const completedOrders = orders.filter((order) => order.status === "confirmed").length;
      const totalBids = orders.reduce((sum, order) => sum + (order.bids_count ?? 0), 0);
      const latestOrder = orders[0];
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title="Profil" back={() => go("client-home")} />
          <section className="flex-1 space-y-4 overflow-y-auto px-5 pb-24 pt-5">
            <div className="rounded-[18px] border border-[#E5E7EB] bg-white p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-[#EEF2FF] text-[#1B4FD8]">
                  <User size={28} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[18px] font-bold text-[#111827]">{clientName || auth.user?.full_name || "Mijoz"}</p>
                  <p className="mt-0.5 text-[13px] text-[#6B7280]">{auth.user?.phone}</p>
                  <span className="mt-2 inline-flex rounded-full bg-[#ECFDF5] px-2.5 py-1 text-[11px] font-semibold text-[#15803D]">
                    Mijoz akkaunti
                  </span>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                ["Jami", orders.length],
                ["Faol", activeOrders],
                ["Taklif", totalBids],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-[12px] border border-[#E5E7EB] bg-white p-3 text-center">
                  <p className="text-[20px] font-bold text-[#111827]">{value}</p>
                  <p className="text-[11px] text-[#6B7280]">{label}</p>
                </div>
              ))}
            </div>
            <div className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
              <p className="text-[13px] font-semibold text-[#6B7280]">Buyurtmalar holati</p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div className="rounded-[12px] bg-[#F9FAFB] p-3">
                  <p className="text-[17px] font-bold text-[#111827]">{completedOrders}</p>
                  <p className="text-[12px] text-[#6B7280]">Yakunlangan</p>
                </div>
                <div className="rounded-[12px] bg-[#F9FAFB] p-3">
                  <p className="text-[17px] font-bold text-[#111827]">{latestOrder ? statusLabels[latestOrder.status] : "-"}</p>
                  <p className="text-[12px] text-[#6B7280]">So'nggi buyurtma</p>
                </div>
              </div>
            </div>
            <div className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
              <p className="text-[13px] font-semibold text-[#6B7280]">Shaxsiy ma'lumotlar</p>
              <div className="mt-3 space-y-3">
                <Field label="Ism familiya" value={clientName} onChange={setClientName} placeholder="Masalan: Ali Valiyev" />
                <PrimaryButton onClick={() => run(async () => { await updateClientProfile(clientName); await auth.refreshMe(); }, "Profil yangilandi")}>Saqlash</PrimaryButton>
              </div>
            </div>
            <div className="space-y-2">
              <p className="px-1 text-[13px] font-semibold text-[#6B7280]">Tezkor amallar</p>
              <ProfileActionRow icon={Package} label="Buyurtmalarim" description="Yaratilgan buyurtmalar va holatlarni ko'rish" onClick={() => go("client-orders")} />
              <ProfileActionRow icon={Bell} label="Bildirishnomalar" description="Takliflar va buyurtma yangiliklari" onClick={() => go("client-notifications")} />
              <ProfileActionRow icon={Home} label="Bosh sahifa" description="Yangi buyurtma yaratish oynasiga qaytish" onClick={() => go("client-home")} />
              <ProfileActionRow danger icon={X} label="Chiqish" description="Akkauntdan xavfsiz chiqish" onClick={() => run(async () => { await auth.logout(); go("role"); })} />
            </div>
          </section>
          <BottomNav role="client" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-home") {
      const approved = driverProfile?.verification_status === "approved";
      const showOnboardingActions = Boolean(driverProfile && !approved);
      const earningOrders = driverFeed.filter(isDriverEarningOrder);
      const netIncome = earningOrders.reduce((sum, order) => sum + driverNetIncome(order), 0);
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <section className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <div className="flex items-start justify-between gap-3">
              <h1 className="min-w-0 flex-1 text-[24px] font-bold text-[#111827]">{approved ? "Bosh sahifa" : "Profilni to'ldiring"}</h1>
              <button
                type="button"
                onClick={() => go("driver-income")}
                className="shrink-0 rounded-[14px] border border-[#DDE7FF] bg-white px-3 py-2 text-right shadow-sm"
                aria-label="Sof daromad"
              >
                <span className="block text-[10px] font-semibold text-[#6B7280]">Sof daromad</span>
                <span className="mt-0.5 flex items-center justify-end gap-1 text-[13px] font-bold text-[#111827]">
                  {formatUzs(netIncome)}
                  <ChevronRight size={14} color="#9CA3AF" />
                </span>
              </button>
            </div>
            <div className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
              <p className="text-[15px] font-semibold text-[#111827]">Tasdiqlash holati: {driverProfile?.verification_status ?? "new"}</p>
              <p className="mt-2 text-[14px] leading-6 text-[#6B7280]">{approved ? "Faol bo'lsangiz, yo'nalishingizga mos buyurtmalar ko'rinadi" : "Buyurtmalarni ko'rish uchun avval profil va hujjatlaringizni yuboring."}</p>
            </div>
            <div className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[15px] font-semibold text-[#111827]">Faollik holati</p>
                  <p className="text-[13px] text-[#6B7280]">{approved ? "Faolman" : "Tasdiqlanmaguncha faol bo'la olmaysiz"}</p>
                </div>
                <button
                  disabled={!approved || busy}
                  onClick={() => run(async () => { await setDriverAvailability(!driverProfile?.is_available); await loadDriverProfile(); }, "Faollik yangilandi")}
                  className={cls("h-8 w-14 rounded-full p-1", driverProfile?.is_available ? "bg-[#1B4FD8]" : "bg-[#D1D5DB]", !approved && "opacity-60")}
                >
                  <span className={cls("block h-6 w-6 rounded-full bg-white transition", driverProfile?.is_available && "translate-x-6")} />
                </button>
              </div>
            </div>
            {showOnboardingActions && (
              <>
                <PrimaryButton onClick={() => go("driver-profile-form")}>Profilni to'ldirish</PrimaryButton>
                <SecondaryButton onClick={() => go("driver-documents")}>Hujjatlarni yuklash</SecondaryButton>
              </>
            )}
            {approved && <SecondaryButton onClick={() => go("driver-feed")}>Mos buyurtmalarni ko'rish</SecondaryButton>}
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-profile-form") {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Haydovchi profili" back={() => go("driver-home")} />
          <section className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <Field label="Ism familiya" value={driverForm.full_name} onChange={(v) => setDriverForm({ ...driverForm, full_name: v })} />
            <Field label="Avtomobil modeli" value={driverForm.car_model} placeholder="Masalan: Cobalt" onChange={(v) => setDriverForm({ ...driverForm, car_model: v })} />
            <Field label="Avtomobil rangi" value={driverForm.car_color} placeholder="Masalan: Oq" onChange={(v) => setDriverForm({ ...driverForm, car_color: v })} />
            <Field label="Davlat raqami" value={driverForm.plate_number} placeholder="Masalan: 01 A 123 AA" onChange={(v) => setDriverForm({ ...driverForm, plate_number: v })} />
            <PrimaryButton onClick={() => run(async () => { await updateDriverProfile(driverForm); await loadDriverProfile(); go("driver-home"); }, "Profil saqlandi")}>Saqlash</PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "driver-documents") {
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title="Hujjatlar" back={() => go("driver-home")} />
          <section className="flex-1 space-y-3 overflow-y-auto px-5 py-5">
            {(Object.keys(docLabels) as DriverDocumentType[]).map((type) => (
              <label key={type} className="flex cursor-pointer items-center gap-3 rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <Camera size={24} color="#1B4FD8" />
                <span className="flex-1 text-[15px] font-semibold text-[#111827]">{docLabels[type]}</span>
                <span className="text-[13px] text-[#1B4FD8]">Yuklash</span>
                <input
                  type="file"
                  accept="image/*,.pdf"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    void run(async () => {
                      const uploaded = await uploadFile(file, type);
                      await submitDriverDocument({ document_type: type, file_url: uploaded.file_url, mime_type: uploaded.mime_type ?? file.type, size_bytes: uploaded.size_bytes ?? file.size });
                      await loadDriverProfile();
                    }, "Hujjat ko'rib chiqishga yuborildi");
                  }}
                />
              </label>
            ))}
          </section>
        </main>
      );
    }

    if (screen === "driver-routes") {
      const visibleRoutes = driverRoutes.filter((route) => route.status !== "unavailable");
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <section className="flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="flex items-center justify-between">
              <h1 className="text-[24px] font-bold text-[#111827]">Yo'nalishlarim</h1>
              <button
                onClick={() => {
                  setEditingRouteId(null);
                  setRouteForm({ from_city_id: 0, from_district_id: null, to_city_id: 0, to_district_id: null });
                  go("driver-add-route");
                }}
                className="flex h-10 w-10 items-center justify-center rounded-full bg-[#1B4FD8] text-white"
              >
                +
              </button>
            </div>
            {visibleRoutes.length ? visibleRoutes.map((route) => (
              <div key={route.id} className="relative rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <div className="absolute right-3 top-3 flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => startEditDriverRoute(route)}
                    aria-label="Yo'nalishni tahrirlash"
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-[#EEF2FF] text-[#1B4FD8]"
                  >
                    <Pencil size={15} />
                  </button>
                  <button
                    type="button"
                    onClick={() => run(async () => { await disableDriverRoute(route.id); await loadDriverRoutes(); }, "Yo'nalish o'chirildi")}
                    aria-label="Yo'nalishni o'chirish"
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-[#FEE2E2] text-[#DC2626]"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
                <p className="pr-20 text-[15px] font-semibold leading-6 text-[#111827]">
                  {[cityName(route.from_city), districtName(route.from_district)].filter(Boolean).join(", ")} {"->"} {[cityName(route.to_city), districtName(route.to_district)].filter(Boolean).join(", ")}
                </p>
                <p className="mt-1 text-[13px] text-[#16A34A]">Status: Faol</p>
              </div>
            )) : <EmptyState icon={Navigation} title="Hozircha yo'nalish qo'shilmagan" action="Yo'nalish qo'shish" onAction={() => go("driver-add-route")} />}
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-add-route") {
      const isEditingRoute = editingRouteId !== null;
      const routeFromCity = cities.find((city) => city.id === routeForm.from_city_id);
      const routeToCity = cities.find((city) => city.id === routeForm.to_city_id);
      const routeFromDistrict = districts.find((district) => district.id === routeForm.from_district_id);
      const routeToDistrict = districts.find((district) => district.id === routeForm.to_district_id);
      const routeReady = Boolean(
        routeForm.from_city_id
        && routeForm.to_city_id
        && (!routeFromCity?.requires_district || routeForm.from_district_id)
        && (!routeToCity?.requires_district || routeForm.to_district_id),
      );
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title={isEditingRoute ? "Yo'nalishni tahrirlash" : "Yo'nalish qo'shish"} back={() => { setEditingRouteId(null); go("driver-routes"); }} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <CitySelect label="Qayerdan" cities={cities} value={routeForm.from_city_id} onChange={(v) => setRouteForm({ ...routeForm, from_city_id: v, from_district_id: null })} />
            {routeFromCity?.requires_district && (
              <button
                type="button"
                onClick={() => void openDistrictSelector(routeFromCity, "driver-from")}
                className="flex h-[52px] items-center justify-between rounded-[12px] border border-[#E5E7EB] bg-white px-4 text-left"
              >
                <span className="text-[15px] font-medium text-[#111827]">{routeFromDistrict?.name_uz ?? "Qayerdan tumani"}</span>
                <ChevronRight size={18} color="#9CA3AF" />
              </button>
            )}
            <CitySelect label="Qayerga" cities={cities} value={routeForm.to_city_id} onChange={(v) => setRouteForm({ ...routeForm, to_city_id: v, to_district_id: null })} />
            {routeToCity?.requires_district && (
              <button
                type="button"
                onClick={() => void openDistrictSelector(routeToCity, "driver-to")}
                className="flex h-[52px] items-center justify-between rounded-[12px] border border-[#E5E7EB] bg-white px-4 text-left"
              >
                <span className="text-[15px] font-medium text-[#111827]">{routeToDistrict?.name_uz ?? "Qayerga tumani"}</span>
                <ChevronRight size={18} color="#9CA3AF" />
              </button>
            )}
            <div className="mt-auto">
              <PrimaryButton
                disabled={!routeReady}
                onClick={() => run(async () => {
                  if (editingRouteId !== null) {
                    await updateDriverRoute(editingRouteId, routeForm);
                    setEditingRouteId(null);
                    await loadDriverRoutes();
                    go("driver-routes");
                    return;
                  }
                  await createDriverRoute(routeForm);
                  await loadDriverRoutes();
                  go("driver-routes");
                }, isEditingRoute ? "Yo'nalish yangilandi" : "Yo'nalish qo'shildi")}
              >
                {isEditingRoute ? "O'zgarishlarni saqlash" : "Saqlash"}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "driver-feed" || screen === "driver-orders") {
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <section className="flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <h1 className="text-[24px] font-bold text-[#111827]">{screen === "driver-feed" ? "Mos buyurtmalar" : "Buyurtmalar tarixi"}</h1>
            {driverFeed.length ? driverFeed.map((order) => {
              const myBid = driverOrderBid(order);
              return (
                <div key={order.id} className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
                  <OrderCard order={order} onClick={() => run(async () => { setDriverOrder(await getDriverOrderDetail(order.id) as DriverOrderDetail); go("driver-order-detail"); })} />
                  {myBid && (
                    <div className="mt-3 rounded-[12px] bg-[#EEF2FF] p-3">
                      <p className="text-[12px] font-semibold text-[#1B4FD8]">Mening taklifim</p>
                      <div className="mt-1 flex items-center justify-between gap-2">
                        <p className="text-[15px] font-bold text-[#111827]">{formatUzs(myBid.price)}</p>
                        <StatusBadge status={myBid.status} />
                      </div>
                    </div>
                  )}
                  {driverOrderBids(order).length > 0 && (
                    <div className="mt-3">
                      <DriverAuctionBids bids={driverOrderBids(order)} />
                    </div>
                  )}
                  {screen === "driver-orders" && isDriverEarningOrder(order) && (
                    <div className="mt-3 grid grid-cols-3 gap-2">
                      {[
                        ["Brutto", driverGrossIncome(order)],
                        ["15% ulush", driverSystemFee(order)],
                        ["Sof", driverNetIncome(order)],
                      ].map(([label, value]) => (
                        <div key={label as string} className="rounded-[12px] bg-[#F9FAFB] p-2.5 text-center">
                          <p className="text-[12px] font-bold text-[#111827]">{formatUzs(value as number)}</p>
                          <p className="text-[10px] text-[#6B7280]">{label}</p>
                        </div>
                      ))}
                    </div>
                  )}
                  {screen === "driver-feed" && (
                    myBid ? (
                      <div className="mt-3">
                        <button onClick={() => run(async () => { await rejectOrder(order.id, "Mos emas"); await loadDriverFeed(); }, "Rad etildi")} className="h-10 w-full rounded-[10px] bg-[#F3F4F6] text-[14px] font-semibold text-[#6B7280]">Mos emas deb belgilash</button>
                      </div>
                    ) : (
                      <div className="mt-3 flex gap-2">
                        <button onClick={() => run(async () => { await rejectOrder(order.id, "Mos emas"); await loadDriverFeed(); }, "Rad etildi")} className="h-10 flex-1 rounded-[10px] bg-[#F3F4F6] text-[14px] font-semibold text-[#6B7280]">Rad etish</button>
                        <button onClick={() => { setSelectedFeedOrder(order); setBidPrice(""); go("driver-bid"); }} className="h-10 flex-1 rounded-[10px] bg-[#1B4FD8] text-[14px] font-semibold text-white">Taklif yuborish</button>
                      </div>
                    )
                  )}
                </div>
              );
            }) : <EmptyState icon={Package} title={screen === "driver-feed" ? "Hozircha mos buyurtmalar yo'q" : "Buyurtmalar tarixi bo'sh"} />}
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-bid" && selectedFeedOrder) {
      return (
        <main className="flex flex-1 flex-col bg-white">
          <TopBar title="Narx taklif qiling" back={() => go("driver-feed")} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <div className="rounded-[14px] bg-[#F7F8FA] p-4">
              <p className="font-semibold text-[#111827]">{cityName(selectedFeedOrder.from_city)} {"->"} {cityName(selectedFeedOrder.to_city)}</p>
              <p className="text-[13px] text-[#6B7280]">Tavsiya narx: {formatUzs(selectedFeedOrder.suggested_price)}</p>
            </div>
            <DriverAuctionBids bids={driverOrderBids(selectedFeedOrder)} />
            <Field label="Taklif narxi" type="number" value={bidPrice} onChange={setBidPrice} placeholder="Masalan: 55000" />
            <div className="mt-auto">
              <PrimaryButton disabled={!Number(bidPrice) || Number(bidPrice) <= 0} onClick={() => run(async () => { await sendBid(selectedFeedOrder.id, { price: Number(bidPrice) }); await loadDriverFeed(); go("driver-feed"); }, "Taklif yuborildi")}>Taklif yuborish</PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "driver-order-detail" && driverOrder) {
      const nextAction =
        driverOrder.status === "accepted" ? ["picked_up", "Olib ketildi deb belgilash"] :
        driverOrder.status === "picked_up" ? ["in_transit", "Yo'lga chiqdi deb belgilash"] :
        driverOrder.status === "in_transit" ? ["delivered", "Yetkazildi deb belgilash"] : null;
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title="Buyurtma tafsilotlari" back={() => go("driver-orders")} />
          <section className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <OrderCard order={driverOrder} />
            {[
              ["Olib ketish manzili", driverOrder.pickup_address ?? driverOrder.pickup_area],
              ["Yetkazish manzili", driverOrder.dropoff_address ?? driverOrder.dropoff_area],
              ["Yuboruvchi telefon", driverOrder.sender_phone ?? "Tanlangandan keyin ko'rinadi"],
              ["Qabul qiluvchi telefon", driverOrder.receiver_phone ?? "Tanlangandan keyin ko'rinadi"],
              ["Izoh", driverOrder.comment || "-"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <p className="text-[12px] text-[#6B7280]">{label}</p>
                <p className="mt-1 text-[14px] font-medium text-[#111827]">{value}</p>
              </div>
            ))}
            <DriverAuctionBids bids={driverOrderBids(driverOrder)} />
            {isDriverEarningOrder(driverOrder) && (
              <div className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <p className="text-[13px] font-semibold text-[#111827]">Daromad hisoboti</p>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  {[
                    ["Brutto", driverGrossIncome(driverOrder)],
                    ["15% ulush", driverSystemFee(driverOrder)],
                    ["Sof", driverNetIncome(driverOrder)],
                  ].map(([label, value]) => (
                    <div key={label as string} className="rounded-[12px] bg-[#F9FAFB] p-2.5 text-center">
                      <p className="text-[12px] font-bold text-[#111827]">{formatUzs(value as number)}</p>
                      <p className="text-[10px] text-[#6B7280]">{label}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {(hasLocation(driverOrder.pickup_lat, driverOrder.pickup_lng) || hasLocation(driverOrder.dropoff_lat, driverOrder.dropoff_lng)) && (
              <div className="rounded-[14px] border border-[#E5E7EB] bg-white p-4">
                <p className="text-[12px] text-[#6B7280]">Xarita nuqtalari</p>
                <p className="mt-1 text-[14px] font-medium text-[#111827]">Olib ketish va yetkazish joylari belgilangan</p>
                <button
                  type="button"
                  onClick={() => setReadOnlyMap({
                    pickupLat: driverOrder.pickup_lat,
                    pickupLng: driverOrder.pickup_lng,
                    dropoffLat: driverOrder.dropoff_lat,
                    dropoffLng: driverOrder.dropoff_lng,
                    destinationLat: driverOrder.dropoff_lat,
                    destinationLng: driverOrder.dropoff_lng,
                  })}
                  className="mt-3 h-10 w-full rounded-[10px] bg-[#EEF2FF] text-[14px] font-semibold text-[#1B4FD8]"
                >
                  Xaritada ko'rish
                </button>
              </div>
            )}
            {nextAction && <PrimaryButton onClick={() => run(async () => { await updateDriverOrderStatus(driverOrder.id, nextAction[0] as "picked_up" | "in_transit" | "delivered"); setDriverOrder(await getDriverOrderDetail(driverOrder.id) as DriverOrderDetail); }, "Status yangilandi")}>{nextAction[1]}</PrimaryButton>}
          </section>
        </main>
      );
    }

    if (screen === "driver-income") {
      const earningOrders = driverFeed.filter(isDriverEarningOrder);
      const grossIncome = earningOrders.reduce((sum, order) => sum + driverGrossIncome(order), 0);
      const netIncome = earningOrders.reduce((sum, order) => sum + driverNetIncome(order), 0);
      const systemFee = earningOrders.reduce((sum, order) => sum + driverSystemFee(order), 0);
      const incomeSeries = incomePeriod === "daily" ? buildDriverIncomeSeries(driverFeed) : buildDriverMonthlyIncomeSeries(driverFeed);
      const recentEarningOrders = earningOrders.slice(0, 5);
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title="Daromad" back={() => go("driver-home")} />
          <section className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 pb-24 pt-5">
            <div className="rounded-[18px] border border-[#E5E7EB] bg-white p-4">
              <p className="text-[13px] font-semibold text-[#6B7280]">Sof daromad</p>
              <p className="mt-1 text-[30px] font-bold text-[#111827]">{formatUzs(netIncome)}</p>
              <p className="mt-1 text-[12px] leading-5 text-[#6B7280]">15% tizim ulushi ayirilgandan keyingi summa</p>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-[12px] bg-[#F9FAFB] p-3">
                  <p className="text-[15px] font-bold text-[#111827]">{formatUzs(grossIncome)}</p>
                  <p className="text-[11px] text-[#6B7280]">Brutto</p>
                </div>
                <div className="rounded-[12px] bg-[#F9FAFB] p-3">
                  <p className="text-[15px] font-bold text-[#111827]">{formatUzs(systemFee)}</p>
                  <p className="text-[11px] text-[#6B7280]">Tizim ulushi</p>
                </div>
              </div>
            </div>
            <div className="rounded-[18px] border border-[#E5E7EB] bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[15px] font-semibold text-[#111827]">Grafik</p>
                  <p className="mt-0.5 text-[12px] text-[#6B7280]">{incomePeriod === "daily" ? "Oxirgi 7 kun" : "Oxirgi 6 oy"}</p>
                </div>
                <div className="grid grid-cols-2 rounded-[12px] bg-[#F3F4F6] p-1">
                  {[
                    ["daily", "Kun"],
                    ["monthly", "Oy"],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setIncomePeriod(value as "daily" | "monthly")}
                      className={cls(
                        "h-8 rounded-[9px] px-3 text-[12px] font-semibold",
                        incomePeriod === value ? "bg-white text-[#1B4FD8] shadow-sm" : "text-[#6B7280]",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <MiniIncomeChart data={incomeSeries} />
            </div>
            <div className="space-y-2">
              <p className="px-1 text-[13px] font-semibold text-[#6B7280]">So'nggi daromadlar</p>
              {recentEarningOrders.length ? recentEarningOrders.map((order) => (
                <button
                  key={order.id}
                  type="button"
                  onClick={() => run(async () => { setDriverOrder(await getDriverOrderDetail(order.id) as DriverOrderDetail); go("driver-order-detail"); })}
                  className="flex w-full items-center justify-between gap-3 rounded-[14px] border border-[#E5E7EB] bg-white p-4 text-left"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold text-[#111827]">
                      {cityName(order.from_city)} {"->"} {cityName(order.to_city)}
                    </span>
                    <span className="mt-0.5 block text-[12px] text-[#6B7280]">{shortDate(order.confirmed_at ?? order.delivered_at ?? order.created_at)}</span>
                  </span>
                  <span className="shrink-0 text-[14px] font-bold text-[#16A34A]">{formatUzs(driverNetIncome(order))}</span>
                </button>
              )) : (
                <EmptyState icon={Package} title="Daromad hali yo'q" subtitle="Yetkazilgan buyurtmalar shu yerda ko'rinadi." />
              )}
            </div>
          </section>
          <BottomNav role="driver" active="driver-home" go={go} />
        </main>
      );
    }

    if (screen === "driver-profile") {
      const vehicleInfo = [driverProfile?.car_model, driverProfile?.car_color, driverProfile?.plate_number].filter(Boolean).join(" / ") || "Avtomobil ma'lumoti kiritilmagan";
      const verificationLabel = driverVerificationLabels[driverProfile?.verification_status ?? "new"] ?? driverProfile?.verification_status ?? "Yangi";
      return (
        <main className="flex flex-1 flex-col bg-[#F7F8FA]">
          <TopBar title="Profil" back={() => go("driver-home")} />
          <section className="flex-1 space-y-4 overflow-y-auto px-5 pb-24 pt-5">
            <div className="rounded-[18px] border border-[#E5E7EB] bg-white p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-[#EEF2FF] text-[#1B4FD8]">
                  <Truck size={28} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[18px] font-bold text-[#111827]">{driverProfile?.full_name ?? driverProfile?.user?.full_name ?? "Haydovchi"}</p>
                  <p className="mt-0.5 text-[13px] text-[#6B7280]">{driverProfile?.user?.phone ?? auth.user?.phone}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <span className={cls(
                      "rounded-full px-2.5 py-1 text-[11px] font-semibold",
                      driverProfile?.verification_status === "approved" ? "bg-[#ECFDF5] text-[#15803D]" : "bg-[#FEF3C7] text-[#92400E]",
                    )}>
                      {verificationLabel}
                    </span>
                    <span className={cls(
                      "rounded-full px-2.5 py-1 text-[11px] font-semibold",
                      driverProfile?.is_available ? "bg-[#EEF2FF] text-[#1B4FD8]" : "bg-[#F3F4F6] text-[#6B7280]",
                    )}>
                      {driverProfile?.is_available ? "Faol" : "Faol emas"}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                ["Reyting", driverProfile?.rating ? Number(driverProfile.rating).toFixed(1) : "-"],
                ["Bajarilgan", driverProfile?.completed_orders ?? 0],
                ["Jami", driverProfile?.total_orders ?? 0],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-[12px] border border-[#E5E7EB] bg-white p-3 text-center">
                  <p className="text-[20px] font-bold text-[#111827]">{value}</p>
                  <p className="text-[11px] text-[#6B7280]">{label}</p>
                </div>
              ))}
            </div>
            <div className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[15px] font-semibold text-[#111827]">Faollik holati</p>
                  <p className="mt-1 text-[13px] text-[#6B7280]">
                    {driverProfile?.verification_status === "approved" ? (driverProfile?.is_available ? "Buyurtma qabul qilishga tayyor" : "Vaqtincha faol emas") : "Avval admin tasdiqlashi kerak"}
                  </p>
                </div>
                <button
                  disabled={driverProfile?.verification_status !== "approved" || busy}
                  onClick={() => run(async () => { await setDriverAvailability(!driverProfile?.is_available); await loadDriverProfile(); }, "Faollik yangilandi")}
                  className={cls("h-8 w-14 rounded-full p-1", driverProfile?.is_available ? "bg-[#1B4FD8]" : "bg-[#D1D5DB]", driverProfile?.verification_status !== "approved" && "opacity-60")}
                >
                  <span className={cls("block h-6 w-6 rounded-full bg-white transition", driverProfile?.is_available && "translate-x-6")} />
                </button>
              </div>
            </div>
            <div className="rounded-[16px] border border-[#E5E7EB] bg-white p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#F3F4F6] text-[#374151]">
                  <Truck size={19} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-[#6B7280]">Avtomobil</p>
                  <p className="mt-1 break-words text-[15px] font-semibold text-[#111827]">{vehicleInfo}</p>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2">
                {[
                  ["Holat", verificationLabel],
                  ["Yo'nalish", driverRoutes.length],
                  ["Nizo", driverProfile?.dispute_count ?? 0],
                ].map(([label, value]) => (
                  <div key={label as string} className="rounded-[12px] bg-[#F9FAFB] p-2.5 text-center">
                    <p className="break-words text-[13px] font-bold text-[#111827]">{value}</p>
                    <p className="text-[11px] text-[#6B7280]">{label}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <p className="px-1 text-[13px] font-semibold text-[#6B7280]">Tezkor amallar</p>
              <ProfileActionRow icon={User} label="Profilni tahrirlash" description="Ism, avtomobil va davlat raqamini yangilash" onClick={() => go("driver-profile-form")} />
              <ProfileActionRow icon={FileText} label="Hujjatlar" description="Pasport, guvohnoma va avtomobil hujjatlari" onClick={() => go("driver-documents")} />
              <ProfileActionRow icon={Navigation} label="Yo'nalishlarim" description="Qaysi yo'nalishlarda ishlashingizni boshqarish" onClick={() => go("driver-routes")} />
              <ProfileActionRow icon={Package} label="Buyurtmalarim" description="Qabul qilingan buyurtmalar tarixi" onClick={() => go("driver-orders")} />
              <ProfileActionRow icon={Home} label="Bosh sahifa" description="Daromad va mos buyurtmalar oynasiga qaytish" onClick={() => go("driver-home")} />
              <ProfileActionRow danger icon={X} label="Chiqish" description="Akkauntdan xavfsiz chiqish" onClick={() => run(async () => { await auth.logout(); go("role"); })} />
            </div>
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    return <EmptyState icon={Package} title="Ma'lumot topilmadi" action="Orqaga" onAction={() => go(auth.user?.role === "driver" ? "driver-home" : "client-home")} />;
  })();

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0B1120] p-4 font-[Inter]">
      <div className="relative flex h-[844px] w-[390px] max-w-full flex-col overflow-hidden rounded-[36px] border-[7px] border-[#2C3347] bg-[#F7F8FA] shadow-2xl">
        <div className="flex h-11 shrink-0 items-center justify-between bg-white px-6 text-[13px] font-semibold text-[#111827]">
          <span>9:41</span>
          <span>LTE 100%</span>
        </div>
        {(message || error || busy) && (
          <div className={cls("px-5 py-2 text-[13px] font-medium", error ? "bg-[#FEE2E2] text-[#DC2626]" : "bg-[#DCFCE7] text-[#15803D]")}>
            {busy ? "Yuklanmoqda..." : error || message}
          </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col">{content}</div>
        {mapPicker && (mapPicker === "pickup" ? fromCity : toCity) && (
          <GoogleMapPicker
            mode={mapPicker}
            city={(mapPicker === "pickup" ? fromCity : toCity)!}
            district={mapPicker === "pickup" ? fromDistrict : toDistrict}
            initialLat={mapPicker === "pickup" ? Number(orderForm.pickup_lat) || null : Number(orderForm.dropoff_lat) || null}
            initialLng={mapPicker === "pickup" ? Number(orderForm.pickup_lng) || null : Number(orderForm.dropoff_lng) || null}
            initialAddress={mapPicker === "pickup" ? orderForm.pickup_address : orderForm.dropoff_address}
            onBack={() => setMapPicker(null)}
            onConfirm={(location) => {
              const isPickup = mapPicker === "pickup";
              const willHavePickup = isPickup ? Boolean(location.address) : Boolean(orderForm.pickup_address);
              const willHaveDropoff = isPickup ? Boolean(orderForm.dropoff_address) : Boolean(location.address);
              const willHaveCities = Boolean(orderForm.from_city_id && orderForm.to_city_id);
              if (mapPicker === "pickup") {
                setOrderForm((current) => ({
                  ...current,
                  from_district_id: fromDistrict?.id ?? null,
                  pickup_lat: location.lat,
                  pickup_lng: location.lng,
                  pickup_address: location.address || current.pickup_address,
                }));
              } else {
                setOrderForm((current) => ({
                  ...current,
                  to_district_id: toDistrict?.id ?? null,
                  dropoff_lat: location.lat,
                  dropoff_lng: location.lng,
                  dropoff_address: location.address || current.dropoff_address,
                }));
              }
              setMapPicker(null);
              go(willHavePickup && willHaveDropoff && willHaveCities ? "client-route-summary" : "client-home");
            }}
          />
        )}
        {readOnlyMap && (
          <div className="absolute inset-0 z-50 flex flex-col bg-white">
            <TopBar title="Xarita nuqtalari" back={() => setReadOnlyMap(null)} />
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              <ReadOnlyOrderMap
                pickupLat={readOnlyMap.pickupLat}
                pickupLng={readOnlyMap.pickupLng}
                dropoffLat={readOnlyMap.dropoffLat}
                dropoffLng={readOnlyMap.dropoffLng}
              />
              {hasLocation(readOnlyMap.pickupLat, readOnlyMap.pickupLng) && (
                <a
                  href={createGoogleMapsSearchUrl(Number(readOnlyMap.pickupLat), Number(readOnlyMap.pickupLng))}
                  target="_blank"
                  rel="noreferrer"
                  className="flex h-[48px] items-center justify-center rounded-[12px] bg-[#EEF2FF] text-[14px] font-semibold text-[#1B4FD8]"
                >
                  Olib ketish joyini Google Maps'da ochish
                </a>
              )}
              {hasLocation(readOnlyMap.destinationLat, readOnlyMap.destinationLng) && (
                <a
                  href={createGoogleMapsDirectionsUrl(Number(readOnlyMap.destinationLat), Number(readOnlyMap.destinationLng))}
                  target="_blank"
                  rel="noreferrer"
                  className="flex h-[48px] items-center justify-center rounded-[12px] bg-[#1B4FD8] text-[14px] font-semibold text-white"
                >
                  Google Maps'da ochish
                </a>
              )}
            </div>
          </div>
        )}
        {confirmAction && (
          <ConfirmSheet
            title={
              confirmAction.type === "select-driver"
                ? "Haydovchini tanlaysizmi?"
                : confirmAction.type === "confirm-delivery"
                  ? "Posilka yetib keldimi?"
                  : "Buyurtmani bekor qilasizmi?"
            }
            text={
              confirmAction.type === "select-driver"
                ? "Tanlaganingizdan keyin boshqa takliflar yopiladi."
                : confirmAction.type === "confirm-delivery"
                  ? "Tasdiqlaganingizdan keyin buyurtma yakunlanadi."
                  : orderDetail?.status === "accepted"
                    ? "Haydovchi tanlangan. Buyurtmani bekor qilmoqchimisiz?"
                    : "Bu amalni ortga qaytarib bo'lmaydi."
            }
            confirmText={confirmAction.type === "select-driver" ? "Tanlash" : confirmAction.type === "confirm-delivery" ? "Tasdiqlash" : "Bekor qilish"}
            cancelText={confirmAction.type === "cancel-order" ? "Ortga" : "Bekor qilish"}
            danger={confirmAction.type === "cancel-order"}
            onCancel={() => setConfirmAction(null)}
            onConfirm={() => run(async () => runConfirmAction(confirmAction), confirmAction.type === "cancel-order" ? "Buyurtma bekor qilindi" : undefined)}
          />
        )}
        <div className="flex h-[34px] shrink-0 items-center justify-center bg-white">
          <div className="h-1.5 w-32 rounded-full bg-[#D1D5DB]" />
        </div>
      </div>
    </div>
  );
}
