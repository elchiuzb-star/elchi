// Client order-creation domain: the multi-screen draft, cargo types, and the
// small formatters ported from the web app's shared helpers.
import type { ComponentType } from "react";
import type { UiCity } from "@/data/cities";
import type { Lang } from "@/i18n/i18n";
import {
  AlertCircle,
  ClipboardList,
  FileText,
  Inbox,
  Package,
  Tag,
  Zap,
} from "@/components/icons";

export type CityInfo = UiCity;

export interface LocationPoint {
  city: CityInfo;
  district?: string;
  districtId?: number | null;
  address: string;
  lat?: number | null;
  lng?: number | null;
}

export interface OrderDraft {
  pickup: LocationPoint | null;
  dropoff: LocationPoint | null;
  senderPhone: string;
  receiverPhone: string;
  pickupAddress: string;
  dropoffAddress: string;
  comment: string;
  hasPhoto: boolean;
  cargoPhotoUrl?: string | null;
  cargoType: string;
  clientPrice: string;
}

export const EMPTY_DRAFT: OrderDraft = {
  pickup: null,
  dropoff: null,
  senderPhone: "",
  receiverPhone: "",
  pickupAddress: "",
  dropoffAddress: "",
  comment: "",
  hasPhoto: false,
  cargoPhotoUrl: null,
  cargoType: "",
  clientPrice: "",
};

type IconType = ComponentType<{ size?: number; color?: string }>;

export const CARGO_TYPES: { id: string; uz: string; ru: string; en: string; icon: IconType }[] = [
  { id: "document", uz: "Hujjat", ru: "Документы", en: "Document", icon: FileText },
  { id: "parcel", uz: "Posilka", ru: "Посылка", en: "Parcel", icon: Package },
  { id: "food", uz: "Oziq-ovqat", ru: "Продукты", en: "Food", icon: Inbox },
  { id: "fragile", uz: "Mo'rt buyum", ru: "Хрупкое", en: "Fragile", icon: AlertCircle },
  { id: "electronics", uz: "Elektronika", ru: "Электроника", en: "Electronics", icon: Zap },
  { id: "clothes", uz: "Kiyim", ru: "Одежда", en: "Clothes", icon: Tag },
  { id: "other", uz: "Boshqa", ru: "Другое", en: "Other", icon: ClipboardList },
];

export function cargoTypeLabel(id: string | undefined | null, lang: Lang): string {
  const ct = CARGO_TYPES.find((c) => c.id === id);
  return ct ? (lang === "ru" ? ct.ru : lang === "en" ? ct.en : ct.uz) : "";
}

/** Group digits with spaces: 1234567 → "1 234 567" (Hermes Intl grouping is
 *  unreliable on Android, so we do it manually). */
export function groupNum(n: number): string {
  return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** Format a numeric amount as "1 234 567 so'm". */
export function fmt(n: number): string {
  return `${groupNum(n)} so'm`;
}

export const asCoord = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Local (9-digit) part of an Uzbek phone, after the fixed +998 prefix. */
export const localPhone = (v: string): string =>
  (v || "").replace(/\D/g, "").replace(/^998/, "").slice(0, 9);

export const fmtLocalPhone = (v: string): string => {
  const d = localPhone(v);
  return [d.slice(0, 2), d.slice(2, 5), d.slice(5, 7), d.slice(7, 9)].filter(Boolean).join(" ");
};
