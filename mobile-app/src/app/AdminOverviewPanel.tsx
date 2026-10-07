/**
 * Bosh sahifa (DESIGN-ADMIN-DIFF §3): v1 and v2 signals on one page.
 *
 * The money tiles are *calculated* shares of v1 orders - the fare is paid to the driver in cash and ELCHI does not
 * collect it - so no tile calls them revenue or profit (spec money-words rule, §3.3). Finance cannot read v1 at
 * all (ADMIN-BACKEND-CONTRACT §1.2), so a finance user gets the head, the note, the money queue and the quick
 * actions, and nothing that would only answer 403.
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  Bell,
  ClipboardList,
  FileClock,
  RefreshCw,
  Route,
  Truck,
} from "./ui/icons";

import {
  formatTileCount,
  getAdminOverview,
  getFinanceMoney,
  type FinanceMoneyTile,
  getV2QueueCounts,
  type AdminOverviewData,
  type V2QueueCounts,
  type V2TileId,
} from "../api/admin-overview.api";
import type { MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import type { AuthUser } from "../types/auth";
import { adminErrorMessage, adminOrderStatusLabel } from "../utils/adminUserLabels";
import { formatAdminMoney } from "../utils/money";
import { statusToneClass } from "../utils/orderStatus";
import { formatDate, formatDateTime, formatMinor } from "../utils/v2Format";
import type { Section } from "./AdminApp";
import { buildOverviewDash, millions, type DashDelta, type DashTile, type OverviewDash } from "./overviewDash";

type Tone = "warn" | "err" | "blue" | "neutral";

const TONE_TEXT: Record<Tone, string> = {
  warn: "text-warning",
  err: "text-destructive",
  blue: "text-primary",
  neutral: "text-foreground",
};

function Kpi(props: { title: string; value: string | number; tone?: Tone; onClick?: () => void; testId?: string }) {
  const Comp = props.onClick ? "button" : "div";
  return (
    <Comp
      type={props.onClick ? "button" : undefined}
      onClick={props.onClick}
      data-testid={props.testId}
      className={`rounded-[12px] border border-border bg-card p-4 text-left shadow-sm ${props.onClick ? "el-press transition hover:border-blue-200 hover:shadow-md" : ""}`}
    >
      <span className="block text-xs font-semibold text-muted-foreground">{props.title}</span>
      <span className={`mt-2 block text-2xl font-bold ${TONE_TEXT[props.tone ?? "neutral"]}`}>{props.value}</span>
    </Comp>
  );
}

function SectionHead(props: { title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-bold uppercase tracking-wide text-muted-foreground">{props.title}</h3>
      {props.action}
    </div>
  );
}

function Panel(props: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-[12px] border border-border bg-card shadow-sm">
      <div className="flex items-center justify-between gap-2 border-b border-muted px-4 py-3">
        <h2 className="text-sm font-bold text-foreground">{props.title}</h2>
        {props.action}
      </div>
      <div className="p-4">{props.children}</div>
    </section>
  );
}

function SmallButton(props: { children: ReactNode; onClick: () => void; ghost?: boolean }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className={`el-press inline-flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-xs font-semibold ${props.ghost ? "text-primary hover:bg-accent" : "border border-border bg-card text-secondary-foreground hover:bg-slate-50"}`}
    >
      {props.children}
    </button>
  );
}

const CARD = "min-w-0 rounded-[20px] border border-border bg-card px-5 py-[18px] shadow-sm";

function DeltaChip({ delta }: { delta: DashDelta }) {
  if (!delta) return null;
  const tone =
    delta.trend === "up" ? "bg-success/12 text-success" : delta.trend === "down" ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground";
  return <span className={`self-start whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>{delta.text}</span>;
}

function Legend(props: { color: string; label: string; value: ReactNode; extra?: string }) {
  return (
    <div className="flex items-center gap-2 text-[12.5px]">
      <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: props.color }} />
      <span className="min-w-0 flex-1 truncate text-secondary-foreground">{props.label}</span>
      <span className="font-semibold text-foreground">{props.value}</span>
      {props.extra !== undefined && <span className="w-10 text-right text-muted-foreground">{props.extra}</span>}
    </div>
  );
}

function pct(part: number, total: number): string {
  return total ? `${Math.round((part / total) * 100)}%` : "0%";
}

/** The v3 dashboard (§2.2): CSS bars, a conic donut, split and stacked bars, four sparkline tiles. No chart library. */
function Dashboard({ dash }: { dash: OverviewDash }) {
  const t = useT();
  const weekdays = t("admin.v3.dash.weekdays").split(",");
  const maxDay = Math.max(...dash.days.map((day) => day.amount), 0);
  const statusRows = [
    { key: "confirmed", label: t("status.approved"), value: dash.status.confirmed, color: "var(--success)" },
    { key: "inProgress", label: t("admin.v3.dash.inProgress"), value: dash.status.inProgress, color: "var(--primary)" },
    { key: "cancelled", label: t("status.cancelled"), value: dash.status.cancelled, color: "var(--muted-foreground)" },
    { key: "disputed", label: t("admin.orders.disputed"), value: dash.status.disputed, color: "var(--destructive)" },
  ];
  let angle = 0;
  const stops = statusRows
    .filter((row) => row.value > 0)
    .map((row) => {
      const from = angle;
      angle += (row.value / (dash.status.total || 1)) * 360;
      return `${row.color} ${from}deg ${angle}deg`;
    });
  const donut = stops.length ? `conic-gradient(${stops.join(", ")})` : "var(--muted)";
  const driverRows = [
    { key: "approved", label: t("status.approved"), value: dash.drivers.approved, color: "var(--success)" },
    { key: "pending", label: t("status.pending"), value: dash.drivers.pending, color: "var(--warning)" },
    { key: "rejected", label: t("status.rejected"), value: dash.drivers.rejected, color: "var(--destructive)" },
    { key: "blocked", label: t("admin.common.blocked"), value: dash.drivers.blocked, color: "var(--muted-foreground)" },
  ];
  const systemPct = `${dash.split.systemPct.toFixed(dash.split.systemPct > 0 && dash.split.systemPct < 10 ? 1 : 0)}%`;
  const tileLabel: Record<DashTile["id"], MessageKey> = {
    avgOrder: "admin.overview.avgOrder",
    deliveredToday: "admin.overview.deliveredToday",
    activeDeliveries: "admin.overview.activeDeliveries",
    todayShare: "admin.overview.todayShare",
  };

  return (
    <div className="grid min-w-0 gap-3.5" data-testid="overview-dashboard">
      <div className="grid min-w-0 gap-3.5 lg:grid-cols-3">
        <div className={`${CARD} grid gap-3.5 lg:col-span-3`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="grid gap-1">
              <span className="text-[13px] text-muted-foreground">{t("admin.v3.dash.sum7d")}</span>
              <span className="text-[30px] font-semibold leading-tight tracking-tight text-foreground" data-testid="dash-total">{formatAdminMoney(dash.total7d)}</span>
            </div>
            {dash.vsLastWeek && (
              <span className={`whitespace-nowrap rounded-full px-3 py-1.5 text-[12.5px] font-semibold ${dash.vsLastWeek.trend === "down" ? "bg-destructive/10 text-destructive" : "bg-success/12 text-success"}`}>
                {t("admin.v3.dash.vsLastWeek", { delta: dash.vsLastWeek.text })}
              </span>
            )}
          </div>
          <div className="flex h-[190px] items-end gap-2 pt-1.5 sm:gap-3">
            {dash.days.map((day, index) => {
              const top = maxDay > 0 && day.amount === maxDay;
              const height = maxDay > 0 ? Math.max((day.amount / maxDay) * 130, day.amount > 0 ? 6 : 3) : 3;
              return (
                <div key={index} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-2">
                  <span className={`whitespace-nowrap text-[11.5px] ${top ? "font-bold text-primary" : "text-muted-foreground"}`}>{millions(day.amount)}</span>
                  <span className={`w-full max-w-[46px] rounded-[12px_12px_6px_6px] ${top ? "bg-primary" : "bg-primary/25"}`} style={{ height }} />
                  <span className="text-xs text-muted-foreground">{weekdays[day.weekday] ?? ""}</span>
                </div>
              );
            })}
          </div>
          <span className="text-[11.5px] text-muted-foreground">{t("admin.v3.dash.unitCaption")}</span>
        </div>

        <div className={`${CARD} grid content-start gap-3.5`}>
          <span className="text-[13px] text-muted-foreground">{t("clientProfile.ordersTitle")}</span>
          <div className="flex flex-wrap items-center gap-4">
            <div className="relative h-[132px] w-[132px] shrink-0 rounded-full" style={{ background: donut }}>
              <div className="absolute inset-5 flex flex-col items-center justify-center rounded-full bg-card">
                <span className="text-[22px] font-semibold leading-tight">{dash.status.total}</span>
                <span className="text-[11px] lowercase text-muted-foreground">{t("common.total")}</span>
              </div>
            </div>
            <div className="grid min-w-[130px] flex-1 gap-2">
              {statusRows.map((row) => <Legend key={row.key} color={row.color} label={row.label} value={row.value} extra={pct(row.value, dash.status.total)} />)}
            </div>
          </div>
        </div>

        <div className={`${CARD} grid content-start gap-3.5`}>
          <span className="text-[13px] text-muted-foreground">{t("admin.v3.dash.split")}</span>
          <div className="grid gap-1">
            <span className="text-2xl font-semibold leading-tight">{formatAdminMoney(dash.split.system)}</span>
            <span className="text-[12.5px] text-muted-foreground">{t("admin.v3.dash.systemShareLine", { pct: systemPct })}</span>
          </div>
          <div className="flex h-3.5 overflow-hidden rounded-[7px] bg-muted">
            <span className="bg-primary" style={{ width: `${Math.min(dash.split.systemPct, 100)}%` }} />
            {dash.split.total > 0 && <span className="flex-1 bg-foreground" />}
          </div>
          <div className="grid gap-2">
            <Legend color="var(--primary)" label={t("admin.nav.group.system")} value={formatAdminMoney(dash.split.system)} />
            <Legend color="var(--foreground)" label={t("admin.v3.dash.toDrivers")} value={formatAdminMoney(dash.split.drivers)} />
          </div>
        </div>

        <div className={`${CARD} grid content-start gap-3.5`}>
          <div className="flex items-baseline justify-between">
            <span className="text-[13px] text-muted-foreground">{t("admin.nav.drivers")}</span>
            <span className="text-[22px] font-semibold">{dash.drivers.total}</span>
          </div>
          <div className="flex h-3.5 gap-0.5 overflow-hidden rounded-[7px] bg-muted">
            {driverRows.filter((row) => row.value > 0).map((row) => (
              <span key={row.key} style={{ width: `${(row.value / (dash.drivers.total || 1)) * 100}%`, background: row.color }} />
            ))}
          </div>
          <div className="grid grid-cols-2 gap-x-3.5 gap-y-2">
            {driverRows.map((row) => <Legend key={row.key} color={row.color} label={row.label} value={row.value} />)}
          </div>
        </div>
      </div>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {dash.tiles.map((tile) => {
          const max = Math.max(...tile.spark, 0);
          const value = tile.id === "deliveredToday" ? String(tile.value) : formatAdminMoney(tile.value);
          return (
            <div key={tile.id} data-testid={`dash-tile-${tile.id}`} className="flex min-w-0 items-end gap-3 rounded-[20px] border border-border bg-card px-4 py-3.5 shadow-sm">
              <div className="grid min-w-0 flex-1 gap-1">
                <span className="text-xs leading-snug text-muted-foreground">{t(tileLabel[tile.id])}</span>
                <span className="whitespace-nowrap text-lg font-semibold">{value}</span>
                {tile.count !== undefined ? (
                  <span className="self-start whitespace-nowrap rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold text-primary">{t("admin.v3.dash.countUnit", { count: tile.count })}</span>
                ) : (
                  <DeltaChip delta={tile.delta} />
                )}
              </div>
              <div className="flex h-11 w-[70px] shrink-0 items-end gap-[3px]" aria-hidden="true">
                {tile.spark.map((point, index) => (
                  <span
                    key={index}
                    className={`flex-1 rounded-[3px] ${index === tile.spark.length - 1 ? "bg-primary" : "bg-primary/30"}`}
                    style={{ height: `${max > 0 ? Math.max((point / max) * 100, 6) : 6}%` }}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const V2_TILES: Array<{ id: V2TileId; label: MessageKey; tone: Tone; target: Section }> = [
  { id: "finance_review", label: "admin.overview.qFinance", tone: "warn", target: "opsQueues" },
  { id: "no_show_review", label: "admin.overview.qNoShow", tone: "warn", target: "trustOps" },
  { id: "fraud", label: "admin.overview.qFraud", tone: "err", target: "trustOps" },
  { id: "support_threads", label: "admin.overview.qThreads", tone: "blue", target: "supportThreads" },
];

/** Money words stay exact (spec §9.2): a hold is calculated, a capture is collected commission, a top-up is a balance inflow. */
const FINANCE_TILE_LABELS: Record<FinanceMoneyTile["report"], MessageKey> = {
  calculated_commission: "admin.overview.mCalculated",
  commission_revenue: "admin.overview.mCaptured",
  cash_inflows: "admin.overview.mTopups",
  reversals: "admin.overview.mReversals",
};

export function AdminOverviewPanel({
  user,
  capabilities,
  onNavigate,
  canSee,
}: {
  user: AuthUser;
  /** `/me/capabilities`, loaded once by the shell; `null` while it is still loading. */
  capabilities?: string[] | null;
  onNavigate: (section: Section, query?: string) => void;
  /** Which sections this role can open (the shell's role matrix); buttons to hidden sections are not drawn. */
  canSee?: (section: Section) => boolean;
}) {
  const t = useT();
  const readsV1 = user.role !== "finance";
  const [data, setData] = useState<AdminOverviewData | null>(null);
  const [queues, setQueues] = useState<V2QueueCounts>({});
  const [money, setMoney] = useState<{ tiles: FinanceMoneyTile[]; from: string; to: string } | null>(null);
  const [queuesFailed, setQueuesFailed] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const visible = (section: Section) => (canSee ? canSee(section) : true);
  void capabilities;

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const [overview, v2, financeMoney] = await Promise.all([
        readsV1 ? getAdminOverview() : Promise.resolve(null),
        getV2QueueCounts(user.role),
        readsV1 ? Promise.resolve(null) : getFinanceMoney(),
      ]);
      setData(overview);
      setMoney(financeMoney);
      setQueues(v2.counts);
      setQueuesFailed(v2.failed);
    } catch (err) {
      setError(adminErrorMessage(err, "admin.overview.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.role]);

  const name = user.full_name || user.username || user.phone;
  const head = (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-2xl font-bold text-foreground">{t("admin.overview.title", { name })}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("admin.overview.subtitle")}</p>
        {data && data.warnings.length > 0 && (
          <p className="mt-1 text-xs font-semibold text-warning">
            {t("admin.overview.loadWarning", { sources: data.warnings.map((key) => t(key)).join(", ") })}
          </p>
        )}
        {queuesFailed && <p className="mt-1 text-xs font-semibold text-warning">{t("admin.overview.queuesWarning")}</p>}
      </div>
      <button
        type="button"
        onClick={() => void load()}
        disabled={busy}
        className="el-press inline-flex h-9 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50"
      >
        <RefreshCw size={16} className={busy ? "animate-spin" : ""} /> {t("support.refresh")}
      </button>
    </div>
  );

  const financeNote = (
    <div role="note" className="rounded-[12px] border border-warning/28 bg-warning/14 px-4 py-3 text-[13px] leading-5 text-warning">
      <p className="font-bold">{t("admin.overview.financeTitle")}</p>
      <p className="mt-0.5">{t("admin.overview.financeNote")}</p>
    </div>
  );

  const v2Tiles = V2_TILES.filter((tile) => queues[tile.id] !== undefined && visible(tile.target));
  const v2Section = v2Tiles.length > 0 && (
    <div className="grid gap-3">
      <SectionHead title={t("admin.overview.v2Queues")} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {v2Tiles.map((tile) => (
          <Kpi key={tile.id} testId={`v2-tile-${tile.id}`} title={t(tile.label)} value={formatTileCount(queues[tile.id])} tone={tile.tone} onClick={() => onNavigate(tile.target)} />
        ))}
      </div>
    </div>
  );

  const quickActions: Array<{ section: Section; label: MessageKey; icon: typeof Bell }> = [
    { section: "orders", label: "admin.overview.qOrders", icon: ClipboardList },
    { section: "drivers", label: "admin.overview.qDrivers", icon: Truck },
    { section: "tariffs", label: "admin.overview.qTariffs", icon: Route },
    { section: "notifications", label: "notifications.title", icon: Bell },
    { section: "audit", label: "admin.nav.audit", icon: FileClock },
  ];
  const quick = (
    <div className="grid gap-3">
      <SectionHead title={t("driverProfile.quickActions")} />
      <div className="flex flex-wrap gap-2">
        {quickActions.filter((action) => visible(action.section)).map((action) => {
          const Icon = action.icon;
          return <SmallButton key={action.section} onClick={() => onNavigate(action.section)}><Icon size={14} /> {t(action.label)}</SmallButton>;
        })}
      </div>
    </div>
  );

  if (busy && !data && !Object.keys(queues).length) {
    return (
      <div className="grid min-w-0 gap-5">
        {head}
        <div className="rounded-[12px] border border-border bg-card p-8 text-sm text-muted-foreground">{t("admin.overview.loading")}</div>
      </div>
    );
  }

  if (!readsV1) {
    return (
      <div className="grid min-w-0 gap-5">
        {head}
        {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 p-4 text-sm font-semibold text-destructive">{error}</div>}
        {financeNote}
        {v2Section}
        {money && money.tiles.length > 0 && (
          <div className="grid gap-3">
            <SectionHead title={t("admin.overview.moneyPeriod", { from: formatDate(money.from), to: formatDate(money.to) })} />
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="finance-money">
              {money.tiles.map((tile) => (
                <div key={tile.report} className="rounded-[12px] border border-border bg-card p-4 shadow-sm">
                  <p className="text-xs font-semibold text-muted-foreground">{t(FINANCE_TILE_LABELS[tile.report])}</p>
                  <p className="mt-2 text-xl font-bold text-foreground">{formatMinor(tile.amountMinor)}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{t("admin.overview.moneyNote", { count: tile.count, today: formatMinor(tile.todayMinor) })}</p>
                </div>
              ))}
            </div>
          </div>
        )}
        <p className="rounded-[12px] border border-border bg-card p-4 text-sm text-secondary-foreground">{t("admin.overview.financeOnlyHint")}</p>
        {quick}
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="grid min-w-0 gap-5">
        {head}
        <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 p-4 text-sm font-semibold text-destructive">{error}</div>
      </div>
    );
  }
  if (!data) return null;

  const ordersWithBids = data.orders.filter((order) => ["published", "bidding"].includes(order.status) && (order.bids_count ?? 0) > 0);
  const deliveredAwaiting = data.orders.filter((order) => order.status === "delivered");
  const pendingDrivers = data.drivers.filter((driver) => ["new", "pending"].includes(driver.verification_status));
  const districtIssueCities = data.cities.filter(
    (city) => city.is_active !== false && city.requires_district && (city.active_districts_count ?? city.districts_count ?? 0) === 0,
  );
  // §3.6: the tile opens Nizolar (v2), so it counts v2 disputes when the queue answered; v1 count is the fallback.
  const openDisputes = queues.disputes ? formatTileCount(queues.disputes) : String(data.stats.openDisputes);
  const go = (section: Section) => (visible(section) ? () => onNavigate(section) : undefined);

  const pending: Array<{ label: MessageKey; count: string | number; target: Section }> = [
    { label: "admin.overview.pDrivers", count: pendingDrivers.length, target: "drivers" },
    { label: "admin.overview.pBids", count: ordersWithBids.length, target: "orders" },
    { label: "admin.overview.pDelivered", count: deliveredAwaiting.length, target: "trustOps" },
    { label: "admin.overview.pDisputes", count: openDisputes, target: "disputesV2" },
    { label: "admin.overview.pDistricts", count: districtIssueCities.length, target: "cities" },
    { label: "admin.overview.pTariffs", count: data.stats.missingTariffs, target: "tariffs" },
  ];

  return (
    <div className="grid min-w-0 gap-5">
      {head}

      <Dashboard dash={buildOverviewDash(data.orders, data.drivers)} />

      {v2Section}

      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
        <Kpi title={t("admin.overview.openDisputes")} value={openDisputes} tone="err" onClick={go("disputesV2")} />
        <Kpi title={t("admin.overview.activeCities")} value={data.stats.activeCities} />
        <Kpi title={t("admin.overview.districtIssues")} value={data.stats.districtIssues} tone="warn" onClick={go("cities")} />
        <Kpi title={t("admin.overview.activeTariffs")} value={data.stats.activeTariffs} />
        <Kpi title={t("admin.overview.missingTariffs")} value={data.stats.missingTariffs} tone="warn" onClick={go("tariffs")} />
      </div>

      <div className="grid gap-3">
        <SectionHead title={t("admin.overview.pending")} />
        <div className="flex flex-wrap gap-2">
          {pending.filter((item) => visible(item.target)).map((item) => (
            <SmallButton key={item.label} onClick={() => onNavigate(item.target)}>{t(item.label, { count: item.count })}</SmallButton>
          ))}
        </div>
      </div>

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,.65fr)]">
        <Panel title={t("admin.overview.recentOrders")} action={visible("orders") ? <SmallButton ghost onClick={() => onNavigate("orders")}>{t("admin.overview.openOrders")}</SmallButton> : undefined}>
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="py-2">{t("admin.overview.colOrder")}</th>
                  <th>{t("admin.common.route")}</th>
                  <th>{t("admin.common.status")}</th>
                  <th>{t("common.price")}</th>
                  <th>{t("admin.common.created")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-muted">
                {data.orders.slice(0, 8).map((order) => (
                  <tr key={order.id}>
                    <td className="py-3 font-mono text-xs font-semibold">{order.order_number || order.code || `#${order.id}`}</td>
                    <td>{order.from_city?.name_uz || order.from_city_id} &rarr; {order.to_city?.name_uz || order.to_city_id}</td>
                    <td><span className={`rounded-full border px-2 py-1 text-xs font-semibold ${statusToneClass(order.status)}`}>{adminOrderStatusLabel(order.status)}</span></td>
                    <td>{formatAdminMoney(order.final_price ?? order.suggested_price)}</td>
                    <td>{formatDateTime(order.created_at)}</td>
                  </tr>
                ))}
                {data.orders.length === 0 && <tr><td colSpan={5} className="py-8 text-center text-muted-foreground">{t("admin.overview.noOrders")}</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title={t("admin.overview.driverQueue")} action={visible("drivers") ? <SmallButton ghost onClick={() => onNavigate("drivers")}>{t("admin.overview.review")}</SmallButton> : undefined}>
          <div className="grid divide-y divide-muted">
            {pendingDrivers.slice(0, 5).map((driver) => (
              <div key={driver.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <div className="min-w-0">
                  <div className="truncate font-semibold">{driver.full_name || driver.user?.full_name || driver.phone || driver.user?.phone || t("admin.drivers.driverNo", { id: driver.id })}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {t("admin.overview.docsCount", { plate: driver.plate_number || t("admin.overview.noPlate"), done: driver.documents_count ?? 0, total: driver.required_documents_count ?? 5 })}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="rounded-full border border-warning/28 bg-warning/14 px-2 py-0.5 text-xs font-semibold text-warning">{t("admin.overview.awaitingReview")}</span>
                  {visible("drivers") && <SmallButton onClick={() => onNavigate("drivers", `id:${driver.id}`)}>{t("admin.common.view")}</SmallButton>}
                </div>
              </div>
            ))}
            {pendingDrivers.length === 0 && <p className="text-sm text-muted-foreground">{t("admin.overview.noPendingDrivers")}</p>}
          </div>
        </Panel>
      </div>

      {quick}
      {error && <div className="rounded-[12px] border border-destructive/25 bg-destructive/10 p-3 text-sm font-semibold text-destructive"><AlertTriangle size={14} className="mr-1 inline" />{error}</div>}
    </div>
  );
}
