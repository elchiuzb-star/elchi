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
  Banknote,
  Bell,
  CheckCircle2,
  CircleDollarSign,
  ClipboardList,
  FileClock,
  Percent,
  RefreshCw,
  Route,
  Truck,
  WalletCards,
  TrendingUp,
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

function MoneyCard(props: { title: string; value: number; note: string; icon: typeof Banknote; tone?: "blue" | "emerald" | "amber" | "slate" }) {
  const Icon = props.icon;
  const toneClass = {
    blue: "bg-accent text-primary",
    emerald: "bg-success/12 text-success",
    amber: "bg-warning/14 text-warning",
    slate: "bg-slate-50 text-secondary-foreground",
  }[props.tone ?? "slate"];
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

function percent(part: number, total: number): string {
  if (!total) return "0%";
  return `${((part / total) * 100).toFixed(1)}%`;
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
  const systemShare = percent(data.finance.systemProfit, data.finance.totalOrderAmount);
  const completedShare = percent(data.finance.completedSystemProfit, data.finance.completedOrderAmount);
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
      {financeNote}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MoneyCard title={t("admin.overview.totalAmount")} value={data.finance.totalOrderAmount} note={t("admin.overview.noteTotal", { count: data.finance.pricedOrders })} icon={CircleDollarSign} tone="blue" />
        <MoneyCard title={t("admin.overview.systemShare")} value={data.finance.systemProfit} note={t("admin.overview.noteShare", { share: systemShare })} icon={TrendingUp} tone="emerald" />
        <MoneyCard title={t("admin.overview.driverShare")} value={data.finance.driverIncome} note={t("admin.overview.noteDriver")} icon={WalletCards} tone="amber" />
        <MoneyCard title={t("admin.overview.avgOrder")} value={data.finance.averageOrderAmount} note={t("admin.overview.noteAvg", { amount: formatAdminMoney(data.finance.averageSystemProfit) })} icon={Banknote} />
        <MoneyCard title={t("admin.overview.completedOrders")} value={data.finance.completedOrderAmount} note={t("admin.overview.noteCompleted", { count: data.finance.completedOrders })} icon={CheckCircle2} tone="emerald" />
        <MoneyCard title={t("admin.overview.completedShare")} value={data.finance.completedSystemProfit} note={t("admin.overview.noteCompletedShare", { share: completedShare })} icon={Percent} tone="emerald" />
        <MoneyCard title={t("admin.overview.activeAmount")} value={data.finance.activeOrderAmount} note={t("admin.overview.noteActive", { count: data.finance.activePricedOrders })} icon={Truck} tone="blue" />
        <MoneyCard title={t("admin.overview.todayShare")} value={data.finance.todaySystemProfit} note={t("admin.overview.noteToday", { amount: formatAdminMoney(data.finance.todayOrderAmount) })} icon={FileClock} />
      </div>

      {v2Section}

      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        <Kpi title={t("admin.overview.totalOrders")} value={data.stats.totalOrders} />
        <Kpi title={t("admin.overview.inBidding")} value={data.stats.publishedOrders} />
        <Kpi title={t("admin.overview.activeDeliveries")} value={data.stats.activeDeliveries} />
        <Kpi title={t("admin.overview.deliveredToday")} value={data.stats.deliveredToday} />
        <Kpi title={t("status.approved")} value={data.stats.confirmedOrders} />
        <Kpi title={t("admin.overview.pendingDrivers")} value={data.stats.pendingDrivers} tone="warn" onClick={go("drivers")} />
        <Kpi title={t("admin.overview.approvedDrivers")} value={data.stats.approvedDrivers} />
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
