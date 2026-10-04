/**
 * The staff panel shell (`/admin`): password sign-in, role-gated navigation in the design's seven groups, and a
 * header with the signed-in person, a global search, refresh and sign-out.
 *
 * Visibility is the intersection of two things (DESIGN-ADMIN-DIFF §2): what the design shows each role (`HIDE`
 * in elchi-admin.js) and what the rules let that role read (AGENTS Q2/Q10/Q17/Q69, the v1 guards and
 * ADMIN-BACKEND-CONTRACT §1.2). A panel a role cannot read is not in its menu at all - a menu entry that only
 * ever answers "403" is a broken promise, not a feature. Buttons inside a panel stay gated by the panel itself
 * (capabilities from the server), so hiding a panel here never replaces a server check.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Archive,
  BarChart3,
  Bell,
  Building2,
  Car,
  Check,
  ChevronsLeft,
  CircleDollarSign,
  ChevronsRight,
  ClipboardList,
  Eye,
  EyeOff,
  FileClock,
  Headphones,
  Flag,
  Inbox,
  LifeBuoy,
  Loader2,
  LogOut,
  Percent,
  RefreshCw,
  Scale,
  Search,
  Shield,
  ShieldCheck,
  SlidersHorizontal,
  Tag,
  Truck,
  UserPlus,
  UserRound,
  UsersRound,
  WalletCards,
  X,
} from "./ui/icons";

import {
  CODE_SEARCH_MIN_LENGTH,
  SEARCH_MIN_LENGTH,
  getAdminMe,
  listAdminDisputes,
  searchAdminBookings,
  searchAdminTrips,
  searchAdminUsers,
  staffLogin,
  type AdminBookingSearchHit,
  type AdminRecord,
  type AdminTripSearchHit,
  type AdminUserSearchHit,
} from "../api/admin.api";
import { capabilities as loadCapabilities } from "../api/v2/ops.api";
import { LOCALES, translate, translateDynamic, type MessageKey } from "../i18n";
import { useLocale, useT } from "../i18n/react";
import { ApiError } from "../types/api";
import { isStaffRole, type AuthUser, type StaffRole } from "../types/auth";
import {
  clearAdminAuthStorage,
  getAdminAccessToken,
  getStoredAdminUser,
  saveAdminTokens,
  saveAdminUser,
} from "../auth/adminTokenStorage";
import {
  adminDisputeReasonLabel,
  adminDisputeStatusClass,
  adminDisputeStatusLabel,
  adminErrorMessage,
  adminRoleLabel,
} from "../utils/adminUserLabels";
import { formatDateTime } from "../utils/v2Format";
import { AdminOrdersPanel } from "./AdminOrdersPanel";
import { AdminDriversPanel } from "./AdminDriversPanel";
import { AdminCitiesPanel } from "./AdminCitiesPanel";
import { AdminTariffsPanel } from "./AdminTariffsPanel";
import { AdminOverviewPanel } from "./AdminOverviewPanel";
import { AdminUsersPanel } from "./AdminUsersPanel";
import { AdminNotificationsPanel } from "./AdminNotificationsPanel";
import { AdminProfilePanel } from "./AdminProfilePanel";
import { AdminClientsPanel } from "./AdminClientsPanel";
import { AdminAuditLogsPanel } from "./AdminAuditLogsPanel";
import {
  AdminDisputesV2Panel,
  AdminLegacyOrdersPanel,
  AdminMetricsPanel,
  AdminOpsQueuesPanel,
  AdminSupportPanel,
} from "./AdminOpsPanel";
import { AdminSecurityPanel } from "./AdminSecurityPanel";
import { AdminPriceBandsPanel } from "./AdminPriceBandsPanel";
import { AdminPromoPanel } from "./AdminPromoPanel";
import { AdminVehiclesPanel } from "./AdminVehiclesPanel";
import { AdminFinancePanel } from "./AdminFinancePanel";
import { AdminPlatformPanel } from "./AdminPlatformPanel";
import { AdminTrustPanel } from "./AdminTrustPanel";
import { AdminSupportThreadsPanel } from "./AdminSupportThreadsPanel";

export type Section =
  | "overview"
  // Bozor (v2)
  | "opsQueues" | "trustOps" | "vehicles" | "priceBands" | "disputesV2"
  // Ishonch
  | "support" | "supportThreads"
  // Moliya
  | "finance" | "promotions"
  // Katalog va sozlamalar
  | "platform" | "cities" | "tariffs"
  // Legacy (v1)
  | "orders" | "drivers" | "clients" | "disputes" | "legacyOrders"
  // Tizim
  | "metrics" | "users" | "security" | "notifications" | "audit" | "profile";

type NavIcon = typeof Activity;
type NavItem = { id: Section; icon: NavIcon; label: MessageKey };
type NavGroup = { id: string; label: MessageKey | null; items: NavItem[] };

/** The design's sidebar, in its order (elchi-admin.js `add(...)` calls), with its groups and icons. */
export const NAV_GROUPS: NavGroup[] = [
  { id: "home", label: null, items: [{ id: "overview", icon: Activity, label: "app.nav.home" }] },
  {
    id: "market",
    label: "admin.nav.group.market",
    items: [
      { id: "opsQueues", icon: Inbox, label: "admin.nav.opsQueues" },
      { id: "trustOps", icon: Scale, label: "admin.nav.trustOps" },
      { id: "vehicles", icon: Car, label: "admin.nav.vehicles" },
      { id: "priceBands", icon: CircleDollarSign, label: "admin.nav.priceBands" },
      { id: "disputesV2", icon: Flag, label: "admin.nav.disputesV2" },
    ],
  },
  {
    id: "trust",
    label: "admin.nav.group.trust",
    items: [
      { id: "support", icon: LifeBuoy, label: "admin.nav.support" },
      { id: "supportThreads", icon: Headphones, label: "admin.nav.supportThreads" },
    ],
  },
  {
    id: "finance",
    label: "admin.nav.group.finance",
    items: [
      { id: "finance", icon: WalletCards, label: "admin.nav.finance" },
      { id: "promotions", icon: Percent, label: "admin.nav.promotions" },
    ],
  },
  {
    id: "catalog",
    label: "admin.nav.group.catalog",
    items: [
      { id: "platform", icon: SlidersHorizontal, label: "admin.nav.platform" },
      { id: "cities", icon: Building2, label: "admin.nav.cities" },
      { id: "tariffs", icon: Tag, label: "admin.nav.tariffs" },
    ],
  },
  {
    id: "legacy",
    label: "admin.nav.group.legacy",
    items: [
      { id: "orders", icon: ClipboardList, label: "admin.nav.orders" },
      { id: "drivers", icon: Truck, label: "admin.nav.drivers" },
      { id: "clients", icon: UsersRound, label: "admin.nav.clients" },
      { id: "disputes", icon: AlertTriangle, label: "admin.nav.disputesV1" },
      { id: "legacyOrders", icon: Archive, label: "admin.nav.legacyOrders" },
    ],
  },
  {
    id: "system",
    label: "admin.nav.group.system",
    items: [
      { id: "metrics", icon: BarChart3, label: "admin.nav.metrics" },
      { id: "users", icon: UserPlus, label: "admin.nav.users" },
      { id: "security", icon: ShieldCheck, label: "admin.nav.security" },
      { id: "notifications", icon: Bell, label: "notifications.title" },
      { id: "audit", icon: FileClock, label: "admin.nav.audit" },
      { id: "profile", icon: UserRound, label: "admin.nav.profile" },
    ],
  },
];

export const ALL_SECTIONS: Section[] = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.id));

/**
 * What each role does NOT see (DESIGN-ADMIN-DIFF §2: design `HIDE` AND the rules).
 *
 * - operator: design hides Moliya, Xodimlar, Audit jurnali; audit is admin+ on the server (`AUDIT_LOG_ROLES`).
 * - finance: design hides the v1 catalogue/legacy and the trust panels; Xodimlar and Audit jurnali stay closed to
 *   finance on the server (ADMIN-BACKEND-CONTRACT §1.2: v1 staff list and audit log 403), so they are hidden too.
 * - admin, super_admin: everything; what they may *do* inside a panel is gated there (Q2, Q10, Q69, Q78...).
 */
export const ROLE_HIDDEN: Record<StaffRole, readonly Section[]> = {
  operator: ["finance", "users", "audit"],
  admin: [],
  super_admin: [],
  finance: [
    "orders", "drivers", "clients", "cities", "tariffs", "disputes",
    "vehicles", "priceBands", "disputesV2", "supportThreads", "support", "platform",
    "users", "audit",
  ],
};

export function canSeeSection(role: string, section: Section): boolean {
  if (!isStaffRole(role)) return false;
  return !ROLE_HIDDEN[role].includes(section);
}

export function visibleNavGroups(role: string): NavGroup[] {
  return NAV_GROUPS.map((group) => ({ ...group, items: group.items.filter((item) => canSeeSection(role, item.id)) }))
    .filter((group) => group.items.length > 0);
}

export function sectionLabelKey(section: Section): MessageKey {
  for (const group of NAV_GROUPS) {
    const item = group.items.find((candidate) => candidate.id === section);
    if (item) return item.label;
  }
  return "app.nav.home";
}

function groupOf(section: Section): NavGroup | undefined {
  return NAV_GROUPS.find((group) => group.items.some((item) => item.id === section));
}

function sectionFromHash(): Section | null {
  if (typeof window === "undefined") return null;
  const value = window.location.hash.replace(/^#\/?/, "");
  return (ALL_SECTIONS as string[]).includes(value) ? (value as Section) : null;
}

/** Phone-width screen (below the md breakpoint). Safe where there is no window (tests, prerender). */
function isNarrowScreen(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(max-width: 767px)").matches;
}

function Button(props: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "primary" | "danger" | "neutral";
  type?: "button" | "submit";
  title?: string;
}) {
  const tone = props.tone ?? "primary";
  const className =
    tone === "danger"
      ? "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/25"
      : tone === "neutral"
        ? "border-border bg-card text-secondary-foreground hover:bg-slate-50"
        : "border-primary bg-primary text-primary-foreground hover:bg-primary";
  return (
    <button
      type={props.type ?? "button"}
      onClick={props.onClick}
      disabled={props.disabled}
      title={props.title}
      className={`el-press inline-flex h-10 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold transition ${className} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

/** uz / ru switch. The admin had none; staff in Russian-speaking regions read the same panel. */
function LanguageSwitch({ dark = false }: { dark?: boolean }) {
  const [locale, setLocale] = useLocale();
  const t = useT();
  return (
    <div role="group" aria-label={t("admin.shell.language")} className={`inline-flex h-10 overflow-hidden rounded-[10px] border ${dark ? "border-background/25" : "border-border"}`}>
      {LOCALES.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={locale === option.value}
          onClick={() => setLocale(option.value)}
          className={`px-2.5 text-xs font-bold uppercase ${locale === option.value ? "bg-primary text-primary-foreground" : dark ? "text-background/75 hover:bg-background/10" : "bg-card text-secondary-foreground hover:bg-slate-50"}`}
        >
          {option.value}
        </button>
      ))}
    </div>
  );
}

// --- Sign-in --------------------------------------------------------------------------------------------------------

/** One generic sentence for every credential failure, so the screen never says which half was wrong. */
export function staffLoginErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "INVALID_CREDENTIALS" || error.code === "VALIDATION_ERROR" || error.status === 422) {
      return translate("admin.login.invalid");
    }
    if (error.code === "USER_BLOCKED" || error.code === "USER_INACTIVE") return translate("admin.login.blocked");
    if (error.code === "RATE_LIMITED") return translate("error.RATE_LIMITED");
  }
  return adminErrorMessage(error, "admin.login.failed");
}

export function AdminLogin({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!username.trim() || !password) {
      setError(t("admin.login.fillBoth"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await staffLogin({ username, password });
      if (!isStaffRole(result.user.role)) {
        // The server only signs in staff here; a marketplace account must never land in this panel (Q3).
        setError(t("admin.login.invalid"));
        return;
      }
      saveAdminTokens(result.access_token, result.refresh_token, result.user);
      setPassword("");
      onLogin(result.user);
    } catch (err) {
      setError(staffLoginErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10 font-['Inter',sans-serif] sm:px-6">
      <section className="grid w-full max-w-5xl overflow-hidden rounded-[16px] border border-border bg-card shadow-xl md:grid-cols-[1fr_420px]">
        <div className="bg-foreground p-8 text-background sm:p-10">
          <div className="flex items-center justify-between gap-3">
            <div className="inline-flex h-11 w-11 items-center justify-center rounded-[12px] bg-primary"><Shield size={22} /></div>
            <LanguageSwitch dark />
          </div>
          <h1 className="mt-8 text-3xl font-bold">Elchi Admin</h1>
          <p className="mt-3 max-w-lg text-sm leading-6 text-background/75">{t("admin.login.tagline")}</p>
          <div className="mt-10 grid gap-3 text-sm text-background/75">
            <p className="flex items-center gap-2"><Check size={16} className="text-success" />{t("admin.login.point1")}</p>
            <p className="flex items-center gap-2"><Check size={16} className="text-success" />{t("admin.login.point2")}</p>
            <p className="flex items-center gap-2"><Check size={16} className="text-success" />{t("admin.login.point3")}</p>
          </div>
        </div>
        <form className="p-6 sm:p-8" onSubmit={(event) => void submit(event)} noValidate>
          <h2 className="text-xl font-bold text-foreground">{t("admin.login.heading")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("admin.login.desc")}</p>
          <div className="mt-6 grid gap-4">
            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              {t("admin.login.username")}
              <input
                value={username}
                name="username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={64}
                onChange={(event) => setUsername(event.target.value)}
                className="h-11 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              {t("admin.login.password")}
              <span className="relative">
                <input
                  value={password}
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  maxLength={72}
                  onChange={(event) => setPassword(event.target.value)}
                  className="h-11 w-full rounded-[10px] border border-border bg-card px-3 pr-11 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={t(showPassword ? "admin.login.hidePassword" : "admin.login.showPassword")}
                  title={t(showPassword ? "admin.login.hidePassword" : "admin.login.showPassword")}
                  className="el-press absolute right-1.5 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-[8px] text-muted-foreground hover:bg-muted"
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </span>
            </label>
            {error && <p role="alert" className="rounded-[10px] bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">{error}</p>}
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 size={16} className="animate-spin" />}
              {t("admin.login.cta")}
            </Button>
          </div>
        </form>
      </section>
    </main>
  );
}

// --- Global search (ADMIN-BACKEND-CONTRACT §5.2-§5.4) --------------------------------------------------------------

type SearchState = {
  users: AdminUserSearchHit[];
  bookings: AdminBookingSearchHit[];
  trips: AdminTripSearchHit[];
  unavailable: boolean;
  error: string | null;
};

const EMPTY_SEARCH: SearchState = { users: [], bookings: [], trips: [], unavailable: false, error: null };

/** A missing route (backend not deployed yet) reads as "not available", not as a broken panel. */
function isMissingRoute(reason: unknown): boolean {
  return reason instanceof ApiError && (reason.status === 404 || reason.status === 405);
}

export function AdminGlobalSearch(props: { role: string; onOpen: (section: Section, query?: string) => void }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SearchState>(EMPTY_SEARCH);
  const counter = useRef(0);
  const trimmed = query.trim();

  useEffect(() => {
    if (trimmed.length < SEARCH_MIN_LENGTH) {
      setResult(EMPTY_SEARCH);
      setBusy(false);
      return;
    }
    const ticket = ++counter.current;
    setBusy(true);
    const handle = window.setTimeout(async () => {
      const codeLike = trimmed.length >= CODE_SEARCH_MIN_LENGTH && !/\s/.test(trimmed);
      const [users, bookings, trips] = await Promise.allSettled([
        searchAdminUsers(trimmed, { limit: 8 }),
        codeLike ? searchAdminBookings(trimmed, 5) : Promise.resolve([] as AdminBookingSearchHit[]),
        codeLike ? searchAdminTrips(trimmed, 5) : Promise.resolve([] as AdminTripSearchHit[]),
      ]);
      if (ticket !== counter.current) return;
      const settled = [users, bookings, trips];
      const rejected = settled.filter((item): item is PromiseRejectedResult => item.status === "rejected");
      // A code-shaped query is often not a valid code: a 400 from one source is "no match", not an error.
      const realErrors = rejected.filter((item) => !isMissingRoute(item.reason) && !(item.reason instanceof ApiError && item.reason.code === "VALIDATION_ERROR"));
      setResult({
        users: users.status === "fulfilled" ? users.value : [],
        bookings: bookings.status === "fulfilled" ? bookings.value : [],
        trips: trips.status === "fulfilled" ? trips.value : [],
        unavailable: rejected.length === settled.length && rejected.every((item) => isMissingRoute(item.reason)),
        error: realErrors.length === settled.length ? adminErrorMessage(realErrors[0].reason) : null,
      });
      setBusy(false);
    }, 300);
    return () => window.clearTimeout(handle);
  }, [trimmed]);

  function openUser(hit: AdminUserSearchHit) {
    const lookup = hit.phone ?? hit.full_name ?? hit.id;
    if (hit.role === "driver" && canSeeSection(props.role, "drivers")) props.onOpen("drivers", lookup);
    else if (hit.role === "client" && canSeeSection(props.role, "clients")) props.onOpen("clients", lookup);
    else if (isStaffRole(hit.role) && canSeeSection(props.role, "users")) props.onOpen("users", lookup);
    else return;
    setOpen(false);
  }

  const nothing = !busy && !result.error && !result.unavailable
    && result.users.length + result.bookings.length + result.trips.length === 0;

  return (
    <div className="relative w-full max-w-md min-w-0 flex-1">
      <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
      <input
        value={query}
        onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}
        placeholder={t("admin.search.placeholder")}
        aria-label={t("location.search")}
        className="h-10 w-full rounded-[10px] border border-border bg-card pl-9 pr-9 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
      />
      {query && (
        <button type="button" onClick={() => { setQuery(""); setOpen(false); }} aria-label={t("common.close")} className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-[8px] text-muted-foreground hover:bg-muted">
          <X size={14} />
        </button>
      )}
      {open && trimmed.length > 0 && (
        <div className="absolute left-0 right-0 top-12 z-[80] max-h-[70vh] overflow-y-auto rounded-[12px] border border-border bg-card p-2 text-sm shadow-xl">
          {trimmed.length < SEARCH_MIN_LENGTH && <p className="px-2 py-2 text-muted-foreground">{t("admin.search.minLength", { count: SEARCH_MIN_LENGTH })}</p>}
          {trimmed.length >= SEARCH_MIN_LENGTH && busy && <p className="flex items-center gap-2 px-2 py-2 text-muted-foreground"><Loader2 size={14} className="animate-spin" />{t("common.loading")}</p>}
          {!busy && result.unavailable && <p className="px-2 py-2 text-muted-foreground">{t("admin.search.unavailable")}</p>}
          {!busy && result.error && <p className="px-2 py-2 text-destructive">{result.error}</p>}
          {trimmed.length >= SEARCH_MIN_LENGTH && nothing && <p className="px-2 py-2 text-muted-foreground">{t("admin.search.empty")}</p>}
          {!busy && result.users.length > 0 && (
            <div className="grid gap-0.5">
              <p className="px-2 pt-1 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t("admin.search.people")}</p>
              {result.users.map((hit) => (
                <button key={hit.id} type="button" onClick={() => openUser(hit)} className="el-press flex items-center justify-between gap-3 rounded-[8px] px-2 py-2 text-left hover:bg-slate-50">
                  <span className="min-w-0">
                    <span className="block truncate font-semibold text-foreground">{hit.full_name || t("admin.clients.noName")}</span>
                    <span className="block truncate text-xs text-muted-foreground">{[hit.phone, hit.id].filter(Boolean).join(" · ")}</span>
                  </span>
                  <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-secondary-foreground">{adminRoleLabel(hit.role)}</span>
                </button>
              ))}
            </div>
          )}
          {!busy && result.bookings.length > 0 && (
            <div className="mt-1 grid gap-0.5">
              <p className="px-2 pt-1 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t("admin.search.bookings")}</p>
              {result.bookings.map((hit) => (
                <button key={hit.id} type="button" onClick={() => { props.onOpen("trustOps", hit.id); setOpen(false); }} className="el-press flex items-center justify-between gap-3 rounded-[8px] px-2 py-2 text-left hover:bg-slate-50">
                  <span className="min-w-0">
                    <span className="block truncate font-mono text-xs font-semibold text-foreground">{hit.id}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {[hit.client?.display_name, hit.driver?.display_name, hit.created_at ? formatDateTime(hit.created_at) : null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs font-semibold text-secondary-foreground">{translateDynamic(`status.${hit.service_status}`) ?? hit.service_status}</span>
                </button>
              ))}
            </div>
          )}
          {!busy && result.trips.length > 0 && (
            <div className="mt-1 grid gap-0.5">
              <p className="px-2 pt-1 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t("admin.search.trips")}</p>
              {result.trips.map((hit) => (
                <button key={hit.id} type="button" onClick={() => { props.onOpen("trustOps", hit.id); setOpen(false); }} className="el-press flex items-center justify-between gap-3 rounded-[8px] px-2 py-2 text-left hover:bg-slate-50">
                  <span className="min-w-0">
                    <span className="block truncate font-mono text-xs font-semibold text-foreground">{hit.id}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {[hit.driver_display_name, hit.planned_start_at ? formatDateTime(hit.planned_start_at) : null, t("admin.search.tripSeats", { count: hit.seat_capacity })].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs font-semibold text-secondary-foreground">{translateDynamic(`status.${hit.status}`) ?? hit.status}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// --- Nizolar (v1): read-only table (§19) ------------------------------------------------------------------------------

export function AdminDisputesV1Panel() {
  const t = useT();
  const [rows, setRows] = useState<AdminRecord[]>([]);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const page = await listAdminDisputes({ limit: 100 });
      setRows(page.items ?? []);
    } catch (err) {
      setRows([]);
      setError(adminErrorMessage(err, "admin.disputes1.loadFailed"));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) =>
      [row.id, row.order_number, row.order_id, row.reason, adminDisputeReasonLabel(String(row.reason ?? "")), row.status, openedBy(row)]
        .filter((value) => value !== null && value !== undefined)
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [rows, search]);

  return (
    <div className="grid min-w-0 gap-5">
      <section className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.nav.disputesV1")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("admin.disputes1.subtitle")}</p>
        </div>
        <Button tone="neutral" disabled={busy} onClick={() => void load()}><RefreshCw size={16} /> {t("support.refresh")}</Button>
      </section>
      <section className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
        <label className="grid max-w-md gap-1.5 text-sm font-medium text-secondary-foreground">
          {t("admin.disputes1.searchLabel")}
          <span className="relative">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("admin.disputes1.searchPh")}
              className="h-10 w-full rounded-[10px] border border-border bg-card pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100"
            />
          </span>
        </label>
      </section>
      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">{error}</div>}
      <div className="max-w-full min-w-0 overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                {([
                  "admin.common.id",
                  "admin.overview.colOrder",
                  "common.reason",
                  "admin.common.status",
                  "admin.disputes1.openedBy",
                  "admin.common.created",
                ] as MessageKey[]).map((key) => <th key={key} className="px-4 py-3 font-semibold">{t(key)}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-muted">
              {busy && !rows.length ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">{t("common.loading")}</td></tr>
              ) : visible.length ? visible.map((row, index) => (
                <tr key={String(row.id ?? index)} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-semibold text-secondary-foreground">{String(row.id ?? "-")}</td>
                  <td className="px-4 py-3 font-mono text-xs">{String(row.order_number ?? (row.order as AdminRecord | undefined)?.order_number ?? row.order_id ?? "-")}</td>
                  <td className="px-4 py-3">{adminDisputeReasonLabel(String(row.reason ?? ""))}</td>
                  <td className="px-4 py-3"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${adminDisputeStatusClass(String(row.status ?? ""))}`}>{adminDisputeStatusLabel(String(row.status ?? ""))}</span></td>
                  <td className="px-4 py-3">{openedBy(row)}</td>
                  <td className="px-4 py-3">{formatDateTime(String(row.created_at ?? ""))}</td>
                </tr>
              )) : (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">{t("admin.disputes1.empty")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function openedBy(row: AdminRecord): string {
  const value = row.opened_by ?? row.opened_by_user;
  if (value && typeof value === "object") {
    const user = value as AdminRecord;
    return String(user.phone ?? user.full_name ?? user.id ?? "-");
  }
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

// --- Shell ------------------------------------------------------------------------------------------------------------

function initialSection(role: string | undefined): Section {
  const fromHash = sectionFromHash();
  return fromHash && role && canSeeSection(role, fromHash) ? fromHash : "overview";
}

export default function AdminApp() {
  const t = useT();
  const [user, setUser] = useState<AuthUser | null>(() => {
    const stored = getStoredAdminUser();
    return stored && getAdminAccessToken() && isStaffRole(stored.role) ? stored : null;
  });
  const [section, setSectionState] = useState<Section>(() => initialSection(getStoredAdminUser()?.role));
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  // A 248 px menu next to a phone-width panel leaves ~140 px for the work: on narrow screens it starts folded.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => isNarrowScreen());
  const [focusDisputeId, setFocusDisputeId] = useState<string | null>(null);
  const [panelQuery, setPanelQuery] = useState<string | undefined>(undefined);
  const [caps, setCaps] = useState<string[] | null>(null);

  const setSection = useCallback((next: Section, query?: string) => {
    setPanelQuery(query);
    setSectionState(next);
    if (typeof window !== "undefined" && window.location.hash !== `#${next}`) {
      window.history.replaceState(null, "", `#${next}`);
    }
  }, []);

  const logout = useCallback(() => {
    clearAdminAuthStorage();
    setUser(null);
    setCaps(null);
  }, []);

  /** Re-reads who is signed in; a refused token ends the session instead of leaving a half-working panel. */
  const refreshMe = useCallback(async () => {
    if (!getAdminAccessToken()) return;
    try {
      const me = await getAdminMe();
      if (!isStaffRole(me.role)) {
        logout();
        return;
      }
      saveAdminUser(me);
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) logout();
    }
  }, [logout]);

  useEffect(() => {
    if (!user) return;
    void refreshMe();
    void loadCapabilities().then((dto) => setCaps(dto.capabilities as string[])).catch(() => setCaps([]));
    // Only on sign-in / first load; the header refresh calls these again explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  // A role change (or a hash typed by hand) never leaves a person on a panel their role cannot see.
  useEffect(() => {
    if (user && !canSeeSection(user.role, section)) setSection("overview");
  }, [section, setSection, user]);

  if (!user) {
    return (
      <AdminLogin
        onLogin={(nextUser) => {
          setUser(nextUser);
          setSection(initialSection(nextUser.role));
        }}
      />
    );
  }

  const groups = visibleNavGroups(user.role);
  const currentGroup = groupOf(section);

  async function refreshAll() {
    setBusy(true);
    try {
      await refreshMe();
      setRefreshNonce((value) => value + 1);
    } finally {
      setBusy(false);
    }
  }

  function navigate(next: Section, query?: string) {
    if (!user || !canSeeSection(user.role, next)) return;
    setFocusDisputeId(null);
    setSection(next, query);
    if (isNarrowScreen()) setSidebarCollapsed(true); // the chosen panel gets the width back
  }

  return (
    <main className="min-h-screen bg-background font-['Inter',sans-serif] text-foreground">
      <div className={`grid min-h-screen transition-[grid-template-columns] duration-200 ${sidebarCollapsed ? "grid-cols-[72px_minmax(0,1fr)]" : "grid-cols-[248px_minmax(0,1fr)]"}`}>
        <aside className="min-w-0 border-r border-border bg-foreground px-3 py-5 text-background">
          <div className={`flex items-center ${sidebarCollapsed ? "flex-col justify-center gap-2" : "justify-between gap-3 px-2"}`}>
            <div className={`flex min-w-0 items-center gap-3 ${sidebarCollapsed ? "justify-center" : ""}`}>
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-primary"><Shield size={20} /></div>
              {!sidebarCollapsed && (
                <div className="min-w-0">
                  <p className="font-bold">Elchi Admin</p>
                  <p className="truncate text-xs text-background/60" data-testid="sidebar-role">{adminRoleLabel(user.role)}</p>
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => setSidebarCollapsed((value) => !value)}
              className="el-press inline-flex h-9 w-9 items-center justify-center rounded-[10px] text-background/75 hover:bg-background/10 hover:text-background"
              aria-label={t(sidebarCollapsed ? "admin.shell.expandMenu" : "admin.shell.collapseMenu")}
              title={t(sidebarCollapsed ? "admin.shell.expandMenu" : "admin.shell.collapseMenu")}
            >
              {sidebarCollapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
            </button>
          </div>
          <nav className="mt-6 grid gap-1" aria-label={t("admin.shell.navigation")}>
            {groups.map((group, groupIndex) => (
              <div key={group.id} className="grid gap-1">
                {group.label && (sidebarCollapsed
                  ? groupIndex > 0 && <hr className="my-2 border-background/15" />
                  : <p className="mt-3 px-3 pb-1 text-[11px] font-bold uppercase tracking-wider text-background/60">{t(group.label)}</p>)}
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = section === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => navigate(item.id)}
                      title={t(item.label)}
                      aria-current={active ? "page" : undefined}
                      className={`el-press flex h-10 min-w-0 items-center rounded-[10px] text-sm font-semibold ${sidebarCollapsed ? "justify-center px-0" : "gap-3 px-3"} ${active ? "bg-card text-foreground" : "text-background/75 hover:bg-background/10 hover:text-background"}`}
                    >
                      <Icon size={17} />
                      {!sidebarCollapsed && <span className="truncate">{t(item.label)}</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>
        </aside>

        <section className="min-w-0 overflow-hidden">
          <header className="flex min-h-16 flex-wrap items-center gap-3 border-b border-border bg-card px-4 py-3 lg:px-6">
            <div className="min-w-0 shrink-0">
              <p className="text-xs text-muted-foreground">{currentGroup?.label ? t(currentGroup.label) : "Elchi Admin"}</p>
              <h1 className="truncate text-base font-bold">{t(sectionLabelKey(section))}</h1>
            </div>
            {(caps === null || caps.includes("ops.view")) && <AdminGlobalSearch role={user.role} onOpen={navigate} />}
            <div className="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-2">
              <p className="hidden max-w-[260px] truncate text-sm font-semibold text-secondary-foreground md:block" data-testid="header-identity">
                {user.full_name || user.username || user.phone} · {adminRoleLabel(user.role)}
              </p>
              <LanguageSwitch />
              <Button tone="neutral" disabled={busy} onClick={() => void refreshAll()} title={t("support.refresh")}>
                <RefreshCw size={16} className={busy ? "animate-spin" : ""} /> <span className="hidden sm:inline">{t("support.refresh")}</span>
              </Button>
              <Button tone="neutral" onClick={logout} title={t("nav.logout")}>
                <LogOut size={16} /> <span className="hidden sm:inline">{t("nav.logout")}</span>
              </Button>
            </div>
          </header>

          {/* `key` restarts the entrance on every section change and on a header refresh, so the panel reloads. */}
          <div key={`${section}:${refreshNonce}:${panelQuery ?? ""}`} className="el-enter min-w-0 overflow-x-hidden p-4 lg:p-6">
            {section === "overview" && <AdminOverviewPanel user={user} capabilities={caps} onNavigate={navigate} canSee={(target) => canSeeSection(user.role, target)} />}
            {section === "orders" && <AdminOrdersPanel user={user} />}
            {section === "drivers" && <AdminDriversPanel user={user} initialSearch={panelQuery} />}
            {section === "clients" && <AdminClientsPanel user={user} initialSearch={panelQuery} />}
            {section === "cities" && <AdminCitiesPanel user={user} />}
            {section === "tariffs" && <AdminTariffsPanel user={user} />}
            {section === "disputes" && <AdminDisputesV1Panel />}

            {section === "opsQueues" && (
              <AdminOpsQueuesPanel
                onOpenItem={(item) => {
                  // The queue only points at an object; each kind is opened in the section that owns it. A v2
                  // booking is never sent to the v1 orders search (§4.5): it belongs to the trust/ops bookings.
                  if (item.item_type === "dispute") {
                    setFocusDisputeId(item.item_id);
                    setSection("disputesV2");
                  } else if (item.item_type === "support_ticket" || item.item_type === "trust_review") {
                    navigate("support");
                  } else if (item.item_type === "support_thread") {
                    navigate("supportThreads");
                  } else {
                    navigate("trustOps", item.item_id);
                  }
                }}
              />
            )}
            {section === "disputesV2" && <AdminDisputesV2Panel focusId={focusDisputeId} />}
            {section === "support" && <AdminSupportPanel />}
            {section === "metrics" && <AdminMetricsPanel />}
            {section === "priceBands" && <AdminPriceBandsPanel />}
            {section === "promotions" && <AdminPromoPanel />}
            {section === "vehicles" && <AdminVehiclesPanel />}
            {section === "finance" && <AdminFinancePanel />}
            {section === "platform" && <AdminPlatformPanel />}
            {section === "trustOps" && <AdminTrustPanel />}
            {section === "supportThreads" && <AdminSupportThreadsPanel />}
            {section === "legacyOrders" && <AdminLegacyOrdersPanel />}

            {section === "audit" && <AdminAuditLogsPanel user={user} />}
            {section === "users" && <AdminUsersPanel user={user} initialSearch={panelQuery} />}
            {section === "security" && <AdminSecurityPanel />}
            {section === "notifications" && <AdminNotificationsPanel />}
            {section === "profile" && <AdminProfilePanel user={user} onUserUpdate={setUser} onLogout={logout} />}
          </div>
        </section>
      </div>
    </main>
  );
}
