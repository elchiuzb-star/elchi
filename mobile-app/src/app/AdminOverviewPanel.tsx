import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  Banknote,
  Bell,
  Building2,
  CheckCircle2,
  CircleDollarSign,
  ClipboardList,
  FileClock,
  MapPinned,
  Percent,
  RefreshCw,
  Route,
  ShieldCheck,
  TrendingUp,
  Truck,
  UserCheck,
  WalletCards,
} from "./ui/icons";

import { getAdminOverview, type AdminOverviewData } from "../api/admin-overview.api";
import type { AuthUser } from "../types/auth";
import { formatAdminDate, formatShortAdminDate } from "../utils/date";
import { statusLabel, statusToneClass } from "../utils/orderStatus";
import { formatAdminMoney } from "../utils/money";

type AdminSection =
  | "overview"
  | "orders"
  | "drivers"
  | "cities"
  | "tariffs"
  | "disputes"
  | "audit"
  | "users"
  | "notifications"
  | "profile";

function Card(props: { title: string; value: number; note: string; icon: typeof ClipboardList; onClick?: () => void }) {
  const Icon = props.icon;
  const Comp = props.onClick ? "button" : "div";
  return (
    <Comp
      onClick={props.onClick}
      className="rounded-[12px] border border-border bg-card p-4 text-left shadow-sm transition hover:border-blue-200 hover:shadow-md"
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-muted-foreground">{props.title}</span>
        <Icon size={18} className="text-slate-400" />
      </div>
      <div className="mt-3 text-2xl font-bold text-foreground">{props.value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{props.note}</div>
    </Comp>
  );
}

function MoneyCard(props: { title: string; value: number; note: string; icon: typeof Banknote; tone?: "blue" | "emerald" | "amber" | "slate" }) {
  const Icon = props.icon;
  const tone = props.tone ?? "slate";
  const toneClass = {
    blue: "bg-accent text-primary",
    emerald: "bg-success/12 text-success",
    amber: "bg-warning/14 text-warning",
    slate: "bg-slate-50 text-secondary-foreground",
  }[tone];
  return (
    <div className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-muted-foreground">{props.title}</p>
          <p className="mt-3 text-xl font-bold text-foreground">{formatAdminMoney(props.value)}</p>
        </div>
        <span className={`flex h-9 w-9 items-center justify-center rounded-[10px] ${toneClass}`}><Icon size={18} /></span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{props.note}</p>
    </div>
  );
}

function Panel(props: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-[12px] border border-border bg-card shadow-sm">
      <div className="flex items-center justify-between border-b border-muted px-4 py-3">
        <h2 className="text-sm font-bold text-foreground">{props.title}</h2>
        {props.action}
      </div>
      <div className="p-4">{props.children}</div>
    </section>
  );
}

function SmallButton(props: { children: ReactNode; onClick: () => void }) {
  return (
    <button onClick={props.onClick} className="el-press rounded-[10px] border border-border bg-card px-3 py-1.5 text-xs font-semibold text-secondary-foreground hover:bg-slate-50">
      {props.children}
    </button>
  );
}

function percent(part: number, total: number): string {
  if (!total) return "0%";
  return `${((part / total) * 100).toFixed(1)}%`;
}

export function AdminOverviewPanel({ user, onNavigate }: { user: AuthUser; onNavigate: (section: AdminSection) => void }) {
  const [data, setData] = useState<AdminOverviewData | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setData(await getAdminOverview());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bosh sahifani yuklab bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (busy && !data) {
    return <div className="rounded-[12px] border border-border bg-card p-8 text-sm text-muted-foreground">Bosh sahifa yuklanmoqda...</div>;
  }
  if (error && !data) {
    return <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 p-4 text-sm font-semibold text-destructive">{error}</div>;
  }
  if (!data) return null;

  const ordersWithTakliflar = data.orders.filter((order) => ["published", "bidding"].includes(order.status) && (order.bids_count ?? 0) > 0);
  const deliveredAwaiting = data.orders.filter((order) => order.status === "delivered");
  const pendingDrivers = data.drivers.filter((driver) => ["new", "pending"].includes(driver.verification_status));
  const openDisputes = data.disputes.filter((dispute) => !["resolved", "closed", "cancelled"].includes(String(dispute.status ?? "")));
  const districtIssueCities = data.cities.filter(
    (city) => city.is_active !== false && city.requires_district && (city.active_districts_count ?? city.districts_count ?? 0) === 0,
  );
  const systemProfitShare = percent(data.finance.systemProfit, data.finance.totalOrderAmount);
  const completedProfitShare = percent(data.finance.completedSystemProfit, data.finance.completedOrderAmount);

  return (
    <div className="grid min-w-0 gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">{user.full_name || user.phone} uchun operatsiyalar holati</p>
          {data.warnings.length > 0 && <p className="mt-1 text-xs font-semibold text-warning">{data.warnings.join(". ")}</p>}
        </div>
        <button
          onClick={() => void load()}
          disabled={busy}
          className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={16} /> Yangilash
        </button>
      </div>

      <Panel title="Moliyaviy hisobot">
        <p className="mb-4 rounded-[12px] bg-warning/14 px-3 py-2 text-[13px] leading-5 text-warning">
          Bu bo'lim v1 buyurtmalari bo'yicha <strong>hisoblangan</strong> summalarni ko'rsatadi. Yo'lkira
          haydovchiga naqd to'lanadi va ELCHI uni inkassatsiya qilmaydi, shuning uchun bu sonlar tushum yoki sof
          foyda emas.
        </p>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MoneyCard
            title="Jami buyurtma summasi"
            value={data.finance.totalOrderAmount}
            note={`${data.finance.pricedOrders} ta narxi tasdiqlangan buyurtma bo'yicha`}
            icon={CircleDollarSign}
            tone="blue"
          />
          <MoneyCard
            title="Hisoblangan tizim ulushi"
            value={data.finance.systemProfit}
            note={`Hisoblangan, inkassatsiya qilingan pul emas. Buyurtma summasidan ulush: ${systemProfitShare}`}
            icon={TrendingUp}
            tone="emerald"
          />
          <MoneyCard
            title="Haydovchilarga qoladigan summa"
            value={data.finance.driverIncome}
            note="Hisob-kitob: kelishilgan summadan tizim ulushi ayirilgan. Naqd to'lov ELCHI orqali o'tmaydi."
            icon={WalletCards}
            tone="amber"
          />
          <MoneyCard
            title="O'rtacha buyurtma"
            value={data.finance.averageOrderAmount}
            note={`Har bir buyurtmadan o'rtacha hisoblangan ulush: ${formatAdminMoney(data.finance.averageSystemProfit)}`}
            icon={Banknote}
          />
          <MoneyCard
            title="Yakunlangan buyurtmalar"
            value={data.finance.completedOrderAmount}
            note={`${data.finance.completedOrders} ta yetkazilgan/tasdiqlangan buyurtma`}
            icon={CheckCircle2}
            tone="emerald"
          />
          <MoneyCard
            title="Yakunlanganlardan hisoblangan ulush"
            value={data.finance.completedSystemProfit}
            note={`Hisoblangan ulush, tushum emas. Yakunlangan buyurtmalar bo'yicha: ${completedProfitShare}`}
            icon={Percent}
            tone="emerald"
          />
          <MoneyCard
            title="Faol yetkazmalar summasi"
            value={data.finance.activeOrderAmount}
            note={`${data.finance.activePricedOrders} ta qabul qilingan yoki yo'ldagi buyurtma`}
            icon={Truck}
            tone="blue"
          />
          <MoneyCard
            title="Bugungi tizim foydasi"
            value={data.finance.todaySystemProfit}
            note={`Bugungi narxi bor buyurtmalar summasi: ${formatAdminMoney(data.finance.todayOrderAmount)}`}
            icon={FileClock}
          />
        </div>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title="Jami buyurtmalar" value={data.stats.totalOrders} note="Yuklangan so'nggi admin buyurtmalari" icon={ClipboardList} onClick={() => onNavigate("orders")} />
        <Card title="E'lon/taklif jarayonida" value={data.stats.publishedOrders} note="Mos haydovchilarga ko'rinadi" icon={Route} onClick={() => onNavigate("orders")} />
        <Card title="Faol yetkazmalar" value={data.stats.activeDeliveries} note="Qabul qilingan, olib ketilgan yoki yo'lda" icon={Truck} onClick={() => onNavigate("orders")} />
        <Card title="Bugun yetkazilgan" value={data.stats.deliveredToday} note="Mijoz tasdig'i kutilmoqda" icon={CheckCircle2} onClick={() => onNavigate("orders")} />
        <Card title="Tasdiqlangan" value={data.stats.confirmedOrders} note="Yakunlangan buyurtma yozuvlari" icon={ShieldCheck} onClick={() => onNavigate("orders")} />
        <Card title="Kutilayotgan haydovchilar" value={data.stats.pendingDrivers} note="Tekshiruv talab qilinadi" icon={UserCheck} onClick={() => onNavigate("drivers")} />
        <Card title="Tasdiqlangan haydovchilar" value={data.stats.approvedDrivers} note="Buyurtma olishga tayyor" icon={Truck} onClick={() => onNavigate("drivers")} />
        <Card title="Ochiq nizolar" value={data.stats.openDisputes} note="Admin e'tibori kerak" icon={AlertTriangle} onClick={() => onNavigate("disputes")} />
        <Card title="Faol hududlar" value={data.stats.activeCities} note="Shahar/viloyat katalogi" icon={Building2} onClick={() => onNavigate("cities")} />
        <Card title="Tuman muammolari" value={data.stats.districtIssues} note="Tuman talab qilinadi, lekin yo'q" icon={MapPinned} onClick={() => onNavigate("cities")} />
        <Card title="Faol tariflar" value={data.stats.activeTariffs} note="Yo'nalish narxlari" icon={Route} onClick={() => onNavigate("tariffs")} />
        <Card title="Yetishmayotgan tariflar" value={data.stats.missingTariffs} note="Tarifsiz faol hudud juftliklari" icon={AlertTriangle} onClick={() => onNavigate("tariffs")} />
      </div>

      <Panel title="Kutilayotgan amallar">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[
            ["Tekshiruv kutayotgan haydovchilar", pendingDrivers.length, "drivers"],
            ["Taklifli buyurtmalar", ordersWithTakliflar.length, "orders"],
            ["Tasdiq kutayotgan yetkazmalar", deliveredAwaiting.length, "orders"],
            ["Ochiq nizolar", openDisputes.length, "disputes"],
            ["Tuman talab qiladigan hududlar", districtIssueCities.length, "cities"],
            ["Faol tarifsiz yo'nalishlar", data.stats.missingTariffs, "tariffs"],
          ].map(([label, count, target]) => (
            <button key={label} onClick={() => onNavigate(target as AdminSection)} className="el-press rounded-[10px] border border-border p-3 text-left hover:bg-slate-50">
              <div className="text-xl font-bold text-foreground">{count}</div>
              <div className="text-sm font-semibold text-secondary-foreground">{label}</div>
            </button>
          ))}
        </div>
      </Panel>

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,.65fr)]">
        <Panel title="So'nggi buyurtmalar" action={<SmallButton onClick={() => onNavigate("orders")}>Buyurtmalarni ochish</SmallButton>}>
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="py-2">Buyurtma</th>
                  <th>Yo'nalish</th>
                  <th>Holat</th>
                  <th>Narx</th>
                  <th>Yaratilgan</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-muted">
                {data.orders.slice(0, 8).map((order) => (
                  <tr key={order.id}>
                    <td className="py-3 font-semibold">{order.order_number || order.code || `#${order.id}`}</td>
                    <td>{order.from_city?.name_uz || order.from_city_id} &rarr; {order.to_city?.name_uz || order.to_city_id}</td>
                    <td><span className={`rounded-full border px-2 py-1 text-xs font-semibold ${statusToneClass(order.status)}`}>{statusLabel(order.status)}</span></td>
                    <td>{formatAdminMoney(order.final_price ?? order.suggested_price)}</td>
                    <td>{formatShortAdminDate(order.created_at)}</td>
                  </tr>
                ))}
                {data.orders.length === 0 && <tr><td colSpan={5} className="py-8 text-center text-muted-foreground">Buyurtmalar yuklanmadi</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Haydovchilarni tekshirish navbati" action={<SmallButton onClick={() => onNavigate("drivers")}>Ko'rib chiqish</SmallButton>}>
          <div className="grid gap-3">
            {pendingDrivers.slice(0, 5).map((driver) => (
              <div key={driver.id} className="rounded-[10px] border border-border p-3">
                <div className="font-semibold">{driver.full_name || driver.user?.full_name || driver.phone || driver.user?.phone || `Haydovchi #${driver.id}`}</div>
                <div className="mt-1 text-xs text-muted-foreground">{driver.plate_number || "Raqam belgisi yo'q"} · {driver.documents_count ?? 0}/{driver.required_documents_count ?? 0} hujjat</div>
              </div>
            ))}
            {pendingDrivers.length === 0 && <p className="text-sm text-muted-foreground">Tekshiruv kutayotgan haydovchilar yo'q.</p>}
          </div>
        </Panel>
      </div>

      <div className="grid min-w-0 gap-5 xl:grid-cols-3">
        <Panel title="Nizolar navbati" action={<SmallButton onClick={() => onNavigate("disputes")}>Nizolarni ochish</SmallButton>}>
          <div className="grid gap-2 text-sm">
            {openDisputes.slice(0, 5).map((dispute) => (
              <div key={String(dispute.id)} className="rounded-[10px] border border-border p-3">
                <div className="font-semibold">{String(dispute.reason ?? "Nizo")}</div>
                <div className="text-xs text-muted-foreground">{formatAdminDate(String(dispute.created_at ?? ""))}</div>
              </div>
            ))}
            {openDisputes.length === 0 && <p className="text-muted-foreground">Ochiq nizolar yo'q.</p>}
          </div>
        </Panel>

        <Panel title="Hudud va tariflar holati" action={<SmallButton onClick={() => onNavigate("cities")}>Hududlarni ochish</SmallButton>}>
          <div className="grid gap-2 text-sm text-secondary-foreground">
            <p>{data.districts.length} ta tuman yuklandi: {data.stats.activeCities} ta faol hudud.</p>
            <p>{districtIssueCities.length} ta faol hududga hali tuman kerak.</p>
            <p>{data.stats.missingTariffs} ta faol hudud juftligida faol tarif yo'q.</p>
          </div>
        </Panel>

        <Panel title="So'nggi faollik" action={<SmallButton onClick={() => onNavigate("audit")}>Audit jurnalini ochish</SmallButton>}>
          <div className="grid gap-2 text-sm">
            {data.audits.slice(0, 5).map((audit) => (
              <div key={String(audit.id)} className="rounded-[10px] border border-border p-3">
                <div className="font-semibold">{String(audit.action ?? "faollik")}</div>
                <div className="text-xs text-muted-foreground">{formatAdminDate(String(audit.created_at ?? ""))}</div>
              </div>
            ))}
            {data.audits.length === 0 && <p className="text-muted-foreground">Audit faolligi yuklanmadi.</p>}
          </div>
        </Panel>
      </div>

      <Panel title="Tezkor amallar">
        <div className="flex flex-wrap gap-2">
          <SmallButton onClick={() => onNavigate("orders")}><ClipboardList size={14} /> Buyurtmalarni boshqarish</SmallButton>
          <SmallButton onClick={() => onNavigate("drivers")}><Truck size={14} /> Haydovchilarni ko'rish</SmallButton>
          <SmallButton onClick={() => onNavigate("tariffs")}><Route size={14} /> Tariflarni tekshirish</SmallButton>
          <SmallButton onClick={() => onNavigate("notifications")}><Bell size={14} /> Bildirishnomalar</SmallButton>
          <SmallButton onClick={() => onNavigate("audit")}><FileClock size={14} /> Audit jurnali</SmallButton>
        </div>
      </Panel>
    </div>
  );
}





