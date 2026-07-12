import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bell,
  Building2,
  ChevronsLeft,
  ChevronsRight,
  Check,
  ClipboardList,
  FileClock,
  LogOut,
  RefreshCw,
  Search,
  Shield,
  SlidersHorizontal,
  Truck,
  UserPlus,
  UserRound,
  UsersRound,
} from "lucide-react";

import {
  getAdminMe,
  listAdminAuditLogs,
  listAdminCities,
  listAdminDisputes,
  listAdminDrivers,
  listAdminOrders,
  listAdminTariffs,
  requestAdminOtp,
  verifyAdminOtp,
  type AdminRecord,
} from "../api/admin.api";
import { ApiError } from "../types/api";
import type { AuthUser, StaffRole } from "../types/auth";
import {
  clearAdminAuthStorage,
  getAdminAccessToken,
  getStoredAdminUser,
  saveAdminTokens,
  saveAdminUser,
} from "../auth/adminTokenStorage";
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

type Section = "overview" | "orders" | "drivers" | "clients" | "cities" | "tariffs" | "disputes" | "users" | "notifications" | "audit" | "profile";

const sectionLabels: Record<Section, string> = {
  overview: "Bosh sahifa",
  orders: "Buyurtmalar",
  drivers: "Haydovchilar",
  clients: "Mijozlar",
  cities: "Hududlar",
  tariffs: "Tariflar",
  disputes: "Nizolar",
  users: "Xodimlar",
  notifications: "Bildirishnomalar",
  audit: "Audit jurnali",
  profile: "Profil / Akkaunt",
};

const navItems: Array<{ id: Section; icon: typeof Activity }> = [
  { id: "overview", icon: Activity },
  { id: "orders", icon: ClipboardList },
  { id: "drivers", icon: Truck },
  { id: "clients", icon: UsersRound },
  { id: "cities", icon: Building2 },
  { id: "tariffs", icon: SlidersHorizontal },
  { id: "disputes", icon: AlertTriangle },
  { id: "users", icon: UserPlus },
  { id: "notifications", icon: Bell },
  { id: "audit", icon: FileClock },
  { id: "profile", icon: UserRound },
];

function valueOf(item: AdminRecord, key: string): string {
  const value = item[key];
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") {
    const nested = value as AdminRecord;
    return String(nested.name_uz ?? nested.full_name ?? nested.phone ?? nested.id ?? "-");
  }
  return String(value);
}

function itemsOf(data: unknown): AdminRecord[] {
  if (Array.isArray(data)) return data as AdminRecord[];
  if (data && typeof data === "object" && "items" in data) {
    const items = (data as { items?: unknown }).items;
    return Array.isArray(items) ? (items as AdminRecord[]) : [];
  }
  return [];
}

function formatMoney(value: unknown): string {
  const amount = typeof value === "number" ? value : typeof value === "string" ? Number(value) : null;
  if (amount === null || Number.isNaN(amount)) return "-";
  return `${new Intl.NumberFormat("uz-UZ").format(amount)} UZS`;
}

function statusTone(status: string): string {
  if (["active", "approved", "confirmed", "delivered", "resolved"].includes(status)) return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (["pending", "published", "bidding", "new", "in_transit", "picked_up"].includes(status)) return "bg-blue-50 text-blue-700 border-blue-200";
  if (["rejected", "blocked", "cancelled", "disputed"].includes(status)) return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-slate-50 text-slate-700 border-slate-200";
}

function Pill({ value }: { value: unknown }) {
  const text = String(value ?? "-");
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(text)}`}>{text}</span>;
}

function Button(props: { children: React.ReactNode; onClick?: () => void; disabled?: boolean; tone?: "primary" | "danger" | "neutral" }) {
  const tone = props.tone ?? "primary";
  const className =
    tone === "danger"
      ? "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
      : tone === "neutral"
        ? "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
        : "border-blue-600 bg-blue-600 text-white hover:bg-blue-700";
  return (
    <button
      onClick={props.onClick}
      disabled={props.disabled}
      className={`inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-semibold transition ${className} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

function Field(props: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) {
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

function SelectField<T extends string>(props: { label: string; value: T; onChange: (value: T) => void; options: Array<{ value: T; label: string }> }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-slate-700">
      {props.label}
      <select
        value={props.value}
        onChange={(event) => props.onChange(event.target.value as T)}
        className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-950 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      >
        {props.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function Card(props: { title: string; value: string | number; icon: typeof Activity; sub?: string }) {
  const Icon = props.icon;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500">{props.title}</p>
        <Icon size={18} className="text-slate-400" />
      </div>
      <p className="mt-3 text-2xl font-bold text-slate-950">{props.value}</p>
      {props.sub && <p className="mt-1 text-xs text-slate-500">{props.sub}</p>}
    </div>
  );
}

function Table(props: { rows: AdminRecord[]; columns: Array<{ key: string; label: string; render?: (row: AdminRecord) => React.ReactNode }>; empty: string }) {
  return (
    <div className="max-w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>{props.columns.map((column) => <th key={column.key} className="px-4 py-3 font-semibold">{column.label}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {props.rows.length ? props.rows.map((row, index) => (
              <tr key={String(row.id ?? index)} className="hover:bg-slate-50">
                {props.columns.map((column) => <td key={column.key} className="px-4 py-3 align-top text-slate-700">{column.render ? column.render(row) : valueOf(row, column.key)}</td>)}
              </tr>
            )) : (
              <tr>
                <td colSpan={props.columns.length} className="px-4 py-10 text-center text-slate-500">{props.empty}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AdminLogin({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const [phone, setTelefon] = useState("+998900000001");
  const [role, setRol] = useState<StaffRole>("admin");
  const [otp, setOtp] = useState("12345");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function requestOtp() {
    setBusy(true);
    setError(null);
    try {
      const result = await requestAdminOtp({ phone, role });
      setDevOtp(result.dev_otp ?? null);
      if (result.dev_otp) setOtp(result.dev_otp);
    } catch (err) {
      if (err instanceof ApiError && err.code === "OTP_RESEND_TOO_SOON") return;
      setError(err instanceof Error ? err.message : "OTP so'rovi bajarilmadi");
    } finally {
      setBusy(false);
    }
  }

  async function login() {
    setBusy(true);
    setError(null);
    try {
      const result = await verifyAdminOtp({ phone, role, otp });
      saveAdminTokens(result.access_token, result.refresh_token, result.user);
      onLogin(result.user);
    } catch (err) {
      if (err instanceof ApiError && ["OTP_USED", "OTP_EXPIRED", "OTP_INVALID"].includes(err.code)) {
        try {
          const fresh = await requestAdminOtp({ phone, role });
          if (fresh.dev_otp) {
            setDevOtp(fresh.dev_otp);
            setOtp(fresh.dev_otp);
            setError("Eski OTP endi yaroqsiz. Yangi dev OTP kiritildi, qayta kirishni bosing.");
            return;
          }
          setError("Eski OTP endi yaroqsiz. Yangi OTP so'raldi, yangi kodni kiriting.");
          return;
        } catch (refreshErr) {
          if (refreshErr instanceof ApiError && refreshErr.code === "OTP_RESEND_TOO_SOON") {
            setError("Eski OTP allaqachon ishlatilgan. Biroz kutib, OTP so'rash tugmasini bosing.");
            return;
          }
          setError(refreshErr instanceof Error ? refreshErr.message : "Yangi OTP so'rovi bajarilmadi");
          return;
        }
      }
      setError(err instanceof Error ? err.message : "Kirish amalga oshmadi");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-6 py-10 font-['Inter',sans-serif]">
      <section className="grid w-full max-w-5xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl md:grid-cols-[1fr_420px]">
        <div className="bg-slate-950 p-10 text-white">
          <div className="inline-flex h-11 w-11 items-center justify-center rounded-lg bg-blue-600"><Shield size={22} /></div>
          <h1 className="mt-8 text-3xl font-bold">Elchi Admin</h1>
          <p className="mt-3 max-w-lg text-sm leading-6 text-slate-300">
            Buyurtmalar, haydovchi tekshiruvi, tariflar, nizolar va audit jarayonlari uchun boshqaruv paneli.
          </p>
          <div className="mt-10 grid gap-3 text-sm text-slate-300">
            <p className="flex items-center gap-2"><Check size={16} className="text-emerald-400" />Jonli backend ma'lumotlari</p>
            <p className="flex items-center gap-2"><Check size={16} className="text-emerald-400" />Rolga mos xodim kirishi</p>
            <p className="flex items-center gap-2"><Check size={16} className="text-emerald-400" />Haydovchini tekshirish amallari</p>
          </div>
        </div>
        <div className="p-8">
          <h2 className="text-xl font-bold text-slate-950">Xodim sifatida kirish</h2>
          <p className="mt-1 text-sm text-slate-500">Mavjud operator, administrator yoki super administrator telefonidan foydalaning.</p>
          <div className="mt-6 grid gap-4">
            <Field label="Telefon" value={phone} onChange={setTelefon} />
            <SelectField
              label="Rol"
              value={role}
              onChange={setRol}
              options={[
                { value: "super_admin", label: "Super administrator" },
                { value: "admin", label: "Administrator" },
                { value: "operator", label: "Operator" },
              ]}
            />
            <Field label="OTP" value={otp} onChange={setOtp} />
            {devOtp && <p className="rounded-md bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700">Dev OTP: {devOtp}</p>}
            {error && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700">{error}</p>}
            <div className="grid grid-cols-2 gap-3">
              <Button tone="neutral" disabled={busy} onClick={() => void requestOtp()}>OTP so'rash</Button>
              <Button disabled={busy} onClick={() => void login()}>Kirish</Button>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

export default function AdminApp() {
  const [user, setUser] = useState<AuthUser | null>(() => getStoredAdminUser());
  const [section, setSection] = useState<Section>("overview");
  const [orders, setBuyurtmalar] = useState<AdminRecord[]>([]);
  const [drivers, setDrivers] = useState<AdminRecord[]>([]);
  const [cities, setCities] = useState<AdminRecord[]>([]);
  const [tariffs, setTariflar] = useState<AdminRecord[]>([]);
  const [disputes, setDisputes] = useState<AdminRecord[]>([]);
  const [audits, setAudits] = useState<AdminRecord[]>([]);
  const [search, setQidirish] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  async function loadAll() {
    if (!getAdminAccessToken()) return;
    setBusy(true);
    setError(null);
    try {
      const [me, orderData, driverData, cityData, tariffData, disputeData] = await Promise.all([
        getAdminMe(),
        listAdminOrders({ limit: 20 }),
        listAdminDrivers({ limit: 20 }),
        listAdminCities({ limit: 100 }),
        listAdminTariffs({ limit: 100 }),
        listAdminDisputes({ limit: 20 }).catch(() => ({ items: [] })),
      ]);
      saveAdminUser(me);
      setUser(me);
      setBuyurtmalar(itemsOf(orderData));
      setDrivers(itemsOf(driverData));
      setCities(itemsOf(cityData));
      setTariflar(itemsOf(tariffData));
      setDisputes(itemsOf(disputeData));
      if (me.role === "admin" || me.role === "super_admin") {
        const auditData = await listAdminAuditLogs({ limit: 20 }).catch(() => ({ items: [] }));
        setAudits(itemsOf(auditData));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Admin ma'lumotlarini yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const byQidirish = (row: AdminRecord) => JSON.stringify(row).toLowerCase().includes(q);
    const map: Record<Section, AdminRecord[]> = {
      overview: [],
      orders,
      drivers,
      clients: [],
      cities,
      tariffs,
      disputes,
      users: [],
      notifications: [],
      audit: audits,
      profile: [],
    };
    return q ? map[section].filter(byQidirish) : map[section];
  }, [audits, cities, disputes, drivers, orders, search, section, tariffs]);

  if (!user || !["operator", "admin", "super_admin"].includes(user.role)) {
    return <AdminLogin onLogin={(nextUser) => { setUser(nextUser); void loadAll(); }} />;
  }

  const publishedBuyurtmalar = orders.filter((order) => ["published", "bidding"].includes(valueOf(order, "status"))).length;
  const pendingDrivers = drivers.filter((driver) => ["new", "pending"].includes(valueOf(driver, "verification_status"))).length;
  const activeCities = cities.filter((city) => valueOf(city, "is_active") === "true").length;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Amal bajarilmadi");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearAdminAuthStorage();
    setUser(null);
  }

  return (
    <main className="min-h-screen bg-slate-100 font-['Inter',sans-serif] text-slate-950">
      <div className={`grid min-h-screen transition-[grid-template-columns] duration-200 ${sidebarCollapsed ? "grid-cols-[72px_minmax(0,1fr)]" : "grid-cols-[248px_minmax(0,1fr)]"}`}>
        <aside className="min-w-0 border-r border-slate-200 bg-slate-950 px-3 py-5 text-white">
          <div className={`flex items-center ${sidebarCollapsed ? "flex-col justify-center gap-2" : "justify-between gap-3 px-2"}`}>
            <div className={`flex min-w-0 items-center gap-3 ${sidebarCollapsed ? "justify-center" : ""}`}>
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600"><Shield size={20} /></div>
            {!sidebarCollapsed && <div className="min-w-0">
              <p className="font-bold">Elchi Admin</p>
              <p className="text-xs text-slate-400">{user.role}</p>
            </div>}
            </div>
            <button
              type="button"
              onClick={() => setSidebarCollapsed((value) => !value)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md text-slate-300 hover:bg-slate-900 hover:text-white"
              aria-label={sidebarCollapsed ? "Yon menyuni ochish" : "Yon menyuni yopish"}
              title={sidebarCollapsed ? "Yon menyuni ochish" : "Yon menyuni yopish"}
            >
              {sidebarCollapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
            </button>
          </div>
          <nav className="mt-7 grid gap-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = section === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setSection(item.id)}
                  title={sectionLabels[item.id]}
                  className={`flex h-10 min-w-0 items-center rounded-md text-sm font-semibold ${sidebarCollapsed ? "justify-center px-0" : "gap-3 px-3"} ${active ? "bg-white text-slate-950" : "text-slate-300 hover:bg-slate-900 hover:text-white"}`}
                >
                  <Icon size={17} />
                  {!sidebarCollapsed && <span className="truncate">{sectionLabels[item.id]}</span>}
                </button>
              );
            })}
          </nav>
        </aside>

        <section className="min-w-0 overflow-hidden">
          <header className="flex min-h-16 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 lg:px-6">
            <div className="min-w-0">
              <h1 className="text-xl font-bold">{sectionLabels[section]}</h1>
              <p className="text-xs text-slate-500">{user.full_name || user.phone}</p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
              <Button tone="neutral" disabled={busy} onClick={() => void loadAll()}><RefreshCw size={16} /> Yangilash</Button>
              <Button tone="neutral" onClick={logout}><LogOut size={16} /> Chiqish</Button>
            </div>
          </header>

          <div className="min-w-0 overflow-x-hidden p-4 lg:p-6">
            {error && <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">{error}</div>}

            {section === "overview" && (
              <AdminOverviewPanel user={user} onNavigate={setSection} />
            )}

            {section !== "overview" && section !== "orders" && section !== "drivers" && section !== "clients" && section !== "cities" && section !== "tariffs" && section !== "users" && section !== "notifications" && section !== "profile" && (
              <div className="mb-4 flex items-center gap-3">
                <div className="relative max-w-md flex-1">
                  <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input value={search} onChange={(event) => setQidirish(event.target.value)} placeholder="Joriy jadvaldan qidirish" className="h-10 w-full rounded-md border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                </div>
              </div>
            )}

            {section === "orders" && (
              <AdminOrdersPanel user={user} />
            )}

            {section === "drivers" && (
              <AdminDriversPanel user={user} />
            )}

            {section === "clients" && (
              <AdminClientsPanel user={user} />
            )}

            {section === "cities" && (
              <AdminCitiesPanel user={user} />
            )}

            {section === "tariffs" && (
              <AdminTariffsPanel user={user} />
            )}

            {section === "disputes" && (
              <Table
                rows={filteredRows}
                empty="Nizolar topilmadi"
                columns={[
                  { key: "id", label: "ID" },
                  { key: "order_number", label: "Buyurtma" },
                  { key: "reason", label: "Sabab" },
                  { key: "status", label: "Holat", render: (row) => <Pill value={row.status} /> },
                  { key: "opened_by", label: "Ochgan foydalanuvchi" },
                  { key: "created_at", label: "Yaratilgan" },
                ]}
              />
            )}

            {section === "audit" && (
              <AdminAuditLogsPanel user={user} />
            )}

            {section === "users" && (
              <AdminUsersPanel user={user} />
            )}

            {section === "notifications" && (
              <AdminNotificationsPanel />
            )}

            {section === "profile" && (
              <AdminProfilePanel user={user} onUserUpdate={setUser} onLogout={logout} />
            )}
          </div>
        </section>
      </div>
    </main>
  );
}


