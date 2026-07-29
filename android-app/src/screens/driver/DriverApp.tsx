import { useEffect, useState } from "react";
import { Linking, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AlertCircle, ArrowRight, Bell, CheckCircle2, ChevronRight, FileText, Home, Inbox, LogOut,
  Navigation, Package, Pencil, Plus, Route, Settings, SealCheck, SealWarning, Send, Star,
  ToggleLeft, ToggleRight, Trash2, TrendingUp, Truck, User,
} from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { useSession } from "@/auth/SessionProvider";
import { getNotifications } from "@/api/notifications.api";
import {
  disableDriverRoute, getDriverOrderDetail, setDriverAvailability, updateDriverOrderStatus, updateDriverRouteStatus,
} from "@/api/driver.api";
import type { DriverOrderAction } from "@/types/driver";
import { useAsync } from "@/data/useApi";
import { usePullRefresh } from "@/data/usePullRefresh";
import { mapActiveOrder, useDriverData, type UiFeedOrder } from "@/data/driver";
import { getUzbekErrorMessage } from "@/utils/errors";
import { BackHeader, EmptyState, IconTile, Spinner, StatusBadge } from "@/components/primitives";
import { SettingsPanel } from "@/components/SettingsPanel";
import { cargoTypeLabel, fmt, groupNum } from "@/core/order";
import { mapsDirectionsUrl } from "@/core/maps";
import { haptics } from "@/core/haptics";
import { MapPanel } from "@/components/maps/MapPanel";
import { BidSheet } from "./BidSheet";
import { DriverAddRoute } from "./DriverAddRoute";
import { DriverEditProfile } from "./DriverEditProfile";
import { DriverDocuments } from "./DriverDocuments";
import { DriverOrderBids } from "./DriverOrderBids";
import { ClientNotificationsScreen } from "@/screens/client/ClientNotificationsScreen";

type DriverTab = "home" | "routes" | "orders" | "profile";
type DriverScreen = DriverTab | "income" | "order-detail" | "documents" | "edit-profile" | "add-route" | "settings" | "notifications";

const MAIN_TABS: DriverScreen[] = ["home", "routes", "orders", "profile"];

export function DriverApp() {
  const { t, lang, setLang } = useT();
  const { colors, themeMode, setThemeMode } = useTheme();
  const { logout } = useSession();
  const { driverData, routes, feed, activeOrder, recentEarnings, netIncome, loading, reload } = useDriverData();

  const [tab, setTab] = useState<DriverTab>("home");
  const [screen, setScreen] = useState<DriverScreen>("home");
  const [bidOrder, setBidOrder] = useState<UiFeedOrder | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [bidTick, setBidTick] = useState(0); // bump to refetch an open order detail after bidding
  const [period, setPeriod] = useState<"daily" | "monthly">("daily");
  const [orderTab, setOrderTab] = useState<"feed" | "history">("feed");
  const [busyAvail, setBusyAvail] = useState(false);
  const [busyStatus, setBusyStatus] = useState(false);
  const [actionErr, setActionErr] = useState("");
  const [routeBusy, setRouteBusy] = useState<number | null>(null);
  const [routeErr, setRouteErr] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const { data: notifData, loading: notifLoading, reload: reloadNotifs } = useAsync<any>(() => getNotifications({ limit: 50 }), [screen]);
  const notifs: any[] = notifData?.items ?? [];
  const unreadNotifs = notifs.filter((n) => !n.is_read).length;

  const goTo = (s: DriverScreen) => setScreen(s);
  const goBack = () => setScreen(tab);
  const switchTab = (t2: DriverTab) => { setTab(t2); setScreen(t2); };

  const avail = driverData.available;
  const isApproved = driverData.status === "approved";
  const activeRoute = routes.find((r) => r.status === "active") ?? null;
  const isDetail = !MAIN_TABS.includes(screen);

  const hour = new Date().getHours();
  const greetKey = hour < 12 ? "goodMorning" : hour < 18 ? "goodAfternoon" : "goodEvening";

  useEffect(() => {
    const { BackHandler } = require("react-native");
    const onBack = () => {
      if (bidOrder) { setBidOrder(null); return true; }
      if (!MAIN_TABS.includes(screen)) { goBack(); return true; }
      return false;
    };
    const sub = BackHandler.addEventListener("hardwareBackPress", onBack);
    return () => sub.remove();
  }, [screen, tab, bidOrder]);

  async function toggleAvail() {
    if (!isApproved || busyAvail) return;
    setBusyAvail(true); setActionErr("");
    try { await setDriverAvailability(!avail); haptics.selection(); await reload(); }
    catch (e) { setActionErr(getUzbekErrorMessage(e)); }
    finally { setBusyAvail(false); }
  }
  async function toggleRoute(r: { id: number; status: "active" | "inactive" }) {
    if (routeBusy) return;
    setRouteBusy(r.id); setRouteErr("");
    try { await updateDriverRouteStatus(r.id, { status: r.status === "active" ? "unavailable" : "available" }); await reload(); }
    catch (e) { setRouteErr(getUzbekErrorMessage(e)); }
    finally { setRouteBusy(null); }
  }
  async function deleteRoute(id: number) {
    if (routeBusy) return;
    setRouteBusy(id); setRouteErr("");
    try { await disableDriverRoute(id); setConfirmDelete(null); await reload(); }
    catch (e) { setRouteErr(getUzbekErrorMessage(e)); }
    finally { setRouteBusy(null); }
  }
  // The status-advance action belongs to the driver's assigned order only.
  // When browsing a feed order's detail (detailId ≠ the active order) it must
  // not show, or it would advance the wrong order.
  const viewingActiveOrder = !!activeOrder && (detailId == null || detailId === activeOrder.id);
  const nextStatus: DriverOrderAction | null = viewingActiveOrder && activeOrder
    ? (activeOrder.status === "accepted" ? "picked_up" : activeOrder.status === "picked_up" ? "in_transit" : activeOrder.status === "in_transit" ? "delivered" : null)
    : null;
  const nextStatusLabel = nextStatus === "picked_up" ? t("pickedUp") : nextStatus === "in_transit" ? t("inTransit") : nextStatus === "delivered" ? t("markDelivered") : "";
  async function advanceStatus() {
    if (!activeOrder || !nextStatus || busyStatus) return;
    setBusyStatus(true); setActionErr("");
    try { await updateDriverOrderStatus(activeOrder.id, nextStatus); haptics.success(); await reload(); goBack(); }
    catch (e) { setActionErr(getUzbekErrorMessage(e)); }
    finally { setBusyStatus(false); }
  }

  const chartData = recentEarnings.length ? recentEarnings.slice().reverse().map((e) => ({ label: e.date || e.code, amount: e.net })) : [];
  const grossIncome = Math.round(netIncome / 0.9);
  const commissionTotal = grossIncome - netIncome;

  return (
    <SafeAreaView edges={["top", "bottom"]} className="flex-1 bg-background">
      <View className="flex-1">
        {screen === "home" && (
          <DriverHome
            data={driverData} feed={feed} activeRoute={activeRoute} greetKey={greetKey} isApproved={isApproved}
            unread={unreadNotifs} onNotifs={() => goTo("notifications")} onIncome={() => goTo("income")}
            onSeeAll={() => switchTab("orders")} onAddRoute={() => switchTab("routes")}
            onOpen={(id: number) => { setDetailId(id); goTo("order-detail"); }} onRefresh={reload}
          />
        )}

        {screen === "routes" && (
          <DriverRoutes
            routes={routes} routeBusy={routeBusy} routeErr={routeErr} confirmDelete={confirmDelete}
            onAdd={() => goTo("add-route")} onToggle={toggleRoute} onDelete={deleteRoute}
            onConfirmDelete={setConfirmDelete} onRefresh={reload}
          />
        )}

        {screen === "add-route" && <DriverAddRoute onBack={goBack} onSaved={() => { reload(); goBack(); }} />}

        {screen === "orders" && (
          <DriverOrders
            feed={feed} activeOrder={activeOrder} recentEarnings={recentEarnings} orderTab={orderTab} setOrderTab={setOrderTab}
            onOpen={(id: number) => { setDetailId(id); goTo("order-detail"); }} onBid={setBidOrder} onRefresh={reload}
          />
        )}

        {screen === "order-detail" && (detailId || activeOrder) && (
          <DriverOrderDetail
            order={activeOrder} detailId={detailId} bidTick={bidTick} nextStatus={nextStatus} nextStatusLabel={nextStatusLabel}
            busyStatus={busyStatus} actionErr={actionErr} onBack={goBack} onAdvance={advanceStatus} onBid={setBidOrder}
          />
        )}

        {screen === "income" && (
          <DriverIncome netIncome={netIncome} grossIncome={grossIncome} commissionTotal={commissionTotal} chartData={chartData} recentEarnings={recentEarnings} period={period} setPeriod={setPeriod} onBack={goBack} />
        )}

        {screen === "documents" && <DriverDocuments onBack={goBack} onUploaded={reload} />}
        {screen === "edit-profile" && <DriverEditProfile data={driverData} onBack={goBack} onSaved={() => { reload(); goBack(); }} />}
        {screen === "settings" && <SettingsPanel onBack={goBack} themeMode={themeMode} onThemeChange={setThemeMode} lang={lang} onLangChange={setLang} onLogout={logout} notifKeys={{ a: "orderUpdates", ad: "orderUpdatesDesc", b: "bidAlerts", bd: "bidAlertsDesc" }} />}
        {screen === "notifications" && <ClientNotificationsScreen notifs={notifs} loading={notifLoading} reload={reloadNotifs} onBack={goBack} />}

        {screen === "profile" && (
          <DriverProfile
            data={driverData} avail={avail} isApproved={isApproved} busyAvail={busyAvail} actionErr={actionErr}
            onToggleAvail={toggleAvail}
            onEdit={() => goTo("edit-profile")} onDocs={() => goTo("documents")} onRoutes={() => switchTab("routes")}
            onOrders={() => switchTab("orders")} onIncome={() => goTo("income")} onSettings={() => goTo("settings")} onLogout={logout}
            onRefresh={reload}
          />
        )}
      </View>

      {loading && screen === "home" ? (
        <View className="absolute right-3 top-3"><Spinner size="small" /></View>
      ) : null}

      {!isDetail ? <DriverBottomNav tab={tab} screen={screen} onTab={switchTab} onAdd={() => goTo("add-route")} /> : null}

      {bidOrder ? <BidSheet order={bidOrder} onSubmitted={() => { reload(); setBidTick((n) => n + 1); }} onClose={() => setBidOrder(null)} /> : null}
    </SafeAreaView>
  );
}

/* ── Home ─────────────────────────────────────────────────────────────────── */
function DriverHome({ data, feed, activeRoute, greetKey, isApproved, unread, onNotifs, onIncome, onSeeAll, onAddRoute, onOpen, onRefresh }: any) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const refresh = usePullRefresh(onRefresh);
  return (
    <ScrollView contentContainerClassName="p-4 gap-4 pb-6" refreshControl={refresh}>
      <View className="flex-row items-center justify-between pt-1" style={{ gap: 12 }}>
        <View className="min-w-0 flex-1">
          <Text className="text-xs text-muted-foreground">{t(greetKey)}</Text>
          <View className="flex-row items-center" style={{ gap: 6 }}>
            <Text className="text-xl font-bold text-foreground" numberOfLines={1}>{String(data.name).split(" ")[0]}</Text>
            {isApproved ? <SealCheck size={20} color={colors.success} /> : <SealWarning size={20} color={colors.warning} />}
          </View>
        </View>
        <View className="flex-row items-center" style={{ gap: 8 }}>
          <Pressable onPress={onNotifs} className="h-11 w-11 items-center justify-center rounded-xl border border-border bg-card">
            <Bell size={18} color={colors.foreground} />
            {unread > 0 ? (
              <View className="absolute -right-1 -top-1 items-center justify-center rounded-full px-1" style={{ minWidth: 18, height: 18, backgroundColor: colors.destructive }}>
                <Text className="text-[9px] font-bold text-white">{unread > 9 ? "9+" : unread}</Text>
              </View>
            ) : null}
          </Pressable>
          <Pressable onPress={onIncome} className="flex-row items-center rounded-xl border border-border bg-card px-3.5 py-2.5" style={{ gap: 8 }}>
            <TrendingUp size={15} color={colors.primary} />
            <Text className="text-base font-bold text-foreground">{groupNum(data.netIncome)}</Text>
          </Pressable>
        </View>
      </View>

      {/* Active-route strip (map placeholder until phase 6) */}
      <View className="overflow-hidden rounded-2xl" style={{ height: 120, backgroundColor: "#1a2234", justifyContent: "flex-end", padding: 16 }}>
        {activeRoute ? (
          <View className="flex-row items-center" style={{ gap: 8 }}>
            <View style={{ width: 10, height: 10, borderRadius: 5, borderWidth: 2, borderColor: colors.feruza }} />
            <Text className="text-sm font-medium text-white" numberOfLines={1}>{activeRoute.from}</Text>
            <View className="flex-1 border-t border-dashed" style={{ borderColor: "rgba(255,255,255,0.3)" }} />
            <Text className="text-sm font-medium text-white" numberOfLines={1}>{activeRoute.to}</Text>
            <View style={{ width: 10, height: 10, backgroundColor: colors.primary, borderRadius: 5, borderBottomLeftRadius: 2, transform: [{ rotate: "45deg" }] }} />
          </View>
        ) : (
          <View className="flex-row items-center" style={{ gap: 6 }}>
            <Route size={13} color="rgba(255,255,255,0.8)" />
            <Text className="text-xs" style={{ color: "rgba(255,255,255,0.8)" }}>
              {lang === "ru" ? "Активный маршрут не выбран" : lang === "en" ? "No active route" : "Faol yo'nalish yo'q"}
            </Text>
          </View>
        )}
      </View>

      {/* Matching orders */}
      <View>
        <View className="mb-2 flex-row items-center justify-between px-1">
          <Text className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("matchingOrders")}</Text>
          {feed.length > 0 ? (
            <Pressable onPress={onSeeAll}><Text className="text-xs font-medium" style={{ color: colors.primary }}>{lang === "ru" ? "Все" : lang === "en" ? "See all" : "Barchasi"}</Text></Pressable>
          ) : null}
        </View>
        {feed.length === 0 ? (
          <View className="items-center rounded-2xl border border-dashed border-border p-5">
            <Text className="text-center text-xs text-muted-foreground">
              {activeRoute
                ? (lang === "ru" ? "По маршруту пока нет заказов" : lang === "en" ? "No orders on your route yet" : "Yo'nalishingiz bo'yicha hozircha buyurtma yo'q")
                : (lang === "ru" ? "Добавьте маршрут, чтобы видеть заказы" : lang === "en" ? "Add a route to see orders" : "Buyurtmalarni ko'rish uchun yo'nalish qo'shing")}
            </Text>
            {!activeRoute ? (
              <Pressable onPress={onAddRoute} className="mt-3 flex-row items-center rounded-xl bg-primary px-4 py-2" style={{ gap: 6 }}>
                <Plus size={13} color={colors.primaryForeground} />
                <Text className="text-xs font-semibold text-primary-foreground">{t("addRoute")}</Text>
              </Pressable>
            ) : null}
          </View>
        ) : (
          <View style={{ gap: 12 }}>
            {feed.slice(0, 3).map((o: UiFeedOrder) => (
              <Pressable key={o.id} onPress={() => onOpen(o.id)} className="rounded-2xl border border-border bg-card p-3.5 active:opacity-90">
                <View className="flex-row items-center" style={{ gap: 12 }}>
                  <RouteDots small />
                  <View className="min-w-0 flex-1">
                    <View className="flex-row items-center" style={{ gap: 6 }}>
                      <Text className="text-sm font-semibold text-foreground" numberOfLines={1}>{o.from}</Text>
                      <ArrowRight size={13} color={colors.primary} />
                      <Text className="text-sm font-semibold text-foreground" numberOfLines={1}>{o.to}</Text>
                    </View>
                    <Text className="mt-0.5 text-[11px] text-muted-foreground" numberOfLines={1}>
                      {o.pickup}{o.dropoff ? ` · ${o.dropoff}` : ""}
                    </Text>
                  </View>
                  <View className="items-end">
                    <Text className="text-sm font-bold text-foreground">{groupNum(o.price)}</Text>
                    <Text className="text-[9px] text-muted-foreground">so'm</Text>
                  </View>
                </View>
              </Pressable>
            ))}
          </View>
        )}
      </View>

      {/* Stats */}
      <View className="flex-row" style={{ gap: 12 }}>
        {[
          { label: t("rating"), value: String(data.rating) },
          { label: t("completed"), value: String(data.completedOrders) },
          { label: t("total"), value: String(data.totalOrders) },
        ].map(({ label, value }) => (
          <View key={label} className="flex-1 items-center rounded-2xl border border-border bg-card p-3">
            <Text className="text-xl font-bold text-foreground">{value}</Text>
            <Text className="mt-0.5 text-[10px] text-muted-foreground">{label}</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function RouteDots({ small }: { small?: boolean }) {
  const { colors } = useTheme();
  const s = small ? 8 : 10;
  return (
    <View className="items-center" style={{ gap: 4 }}>
      <View style={{ width: s, height: s, borderRadius: s / 2, borderWidth: 2, borderColor: colors.feruza, backgroundColor: colors.card }} />
      <View style={{ width: 1, height: 20, backgroundColor: colors.border }} />
      <View style={{ width: s, height: s, backgroundColor: colors.primary, borderRadius: s / 2, borderBottomLeftRadius: 2, transform: [{ rotate: "45deg" }] }} />
    </View>
  );
}

/* ── Routes ───────────────────────────────────────────────────────────────── */
function DriverRoutes({ routes, routeBusy, routeErr, confirmDelete, onAdd, onToggle, onDelete, onConfirmDelete, onRefresh }: any) {
  const { t, lang } = useT();
  const { colors } = useTheme();
  const refresh = usePullRefresh(onRefresh);
  return (
    <ScrollView contentContainerClassName="p-4 gap-4 pb-6" refreshControl={refresh}>
      <View className="flex-row items-center justify-between pt-1">
        <Text className="text-xl font-semibold text-foreground">{t("myRoutes")}</Text>
        <Pressable onPress={onAdd} className="flex-row items-center rounded-xl bg-primary px-3 py-2" style={{ gap: 6 }}>
          <Plus size={14} color={colors.primaryForeground} />
          <Text className="text-sm font-medium text-primary-foreground">{t("addRoute")}</Text>
        </Pressable>
      </View>
      {routeErr ? <Text className="px-1 text-xs" style={{ color: colors.destructive }}>{routeErr}</Text> : null}
      <Text className="-mt-1 px-1 text-[11px] text-muted-foreground">
        {lang === "ru" ? "Маршрут можно включить/выключить." : lang === "en" ? "Toggle a route on/off." : "Yo'nalishni yoqib/o'chirib qo'yish mumkin."}
      </Text>
      {routes.length === 0 ? (
        <EmptyState icon={Route} title={t("noRoutesYet")} desc={t("noRoutesDesc")} action={
          <Pressable onPress={onAdd} className="rounded-xl bg-primary px-5 py-2.5"><Text className="text-sm font-medium text-primary-foreground">{t("addFirstRoute")}</Text></Pressable>
        } />
      ) : (
        routes.map((r: any) => {
          const active = r.status === "active";
          return (
            <View key={r.id} className="rounded-2xl border border-border bg-card p-4">
              <View className="mb-3 flex-row items-center justify-between">
                <StatusBadge status={r.status} />
                <View className="flex-row items-center" style={{ gap: 8 }}>
                  <Pressable onPress={() => onToggle(r)} disabled={routeBusy === r.id} className="flex-row items-center" style={{ gap: 6, opacity: routeBusy === r.id ? 0.6 : 1 }}>
                    <Text className="text-[11px] font-medium text-muted-foreground">
                      {active ? (lang === "ru" ? "Вкл" : lang === "en" ? "On" : "Yoqilgan") : (lang === "ru" ? "Выкл" : lang === "en" ? "Off" : "O'chiq")}
                    </Text>
                    {active ? <ToggleRight size={30} color={colors.primary} /> : <ToggleLeft size={30} color={colors.mutedForeground} />}
                  </Pressable>
                  <Pressable onPress={() => onConfirmDelete(confirmDelete === r.id ? null : r.id)} className="rounded-lg p-1.5" style={{ backgroundColor: `${colors.destructive}1A` }}>
                    <Trash2 size={13} color={colors.destructive} />
                  </Pressable>
                </View>
              </View>
              <View className="flex-row items-center" style={{ gap: 12 }}>
                <RouteDots />
                <View className="flex-1">
                  <Text className="text-sm font-semibold text-foreground">{r.from}</Text>
                  {r.fromDistrict ? <Text className="text-xs text-muted-foreground">{r.fromDistrict}</Text> : null}
                  <Text className="mt-2 text-sm font-semibold text-foreground">{r.to}</Text>
                  {r.toDistrict ? <Text className="text-xs text-muted-foreground">{r.toDistrict}</Text> : null}
                </View>
              </View>
              {confirmDelete === r.id ? (
                <View className="mt-3 flex-row items-center border-t border-border pt-3" style={{ gap: 8 }}>
                  <Text className="flex-1 text-xs" style={{ color: colors.destructive }}>
                    {lang === "ru" ? "Удалить маршрут?" : lang === "en" ? "Delete this route?" : "Yo'nalish o'chirilsinmi?"}
                  </Text>
                  <Pressable onPress={() => onConfirmDelete(null)} className="rounded-lg border border-border bg-secondary px-3 py-1.5">
                    <Text className="text-xs text-foreground">{lang === "ru" ? "Нет" : lang === "en" ? "No" : "Yo'q"}</Text>
                  </Pressable>
                  <Pressable onPress={() => onDelete(r.id)} disabled={routeBusy === r.id} className="rounded-lg px-3 py-1.5" style={{ backgroundColor: colors.destructive }}>
                    <Text className="text-xs text-white">{routeBusy === r.id ? "..." : lang === "ru" ? "Удалить" : lang === "en" ? "Delete" : "O'chirish"}</Text>
                  </Pressable>
                </View>
              ) : null}
            </View>
          );
        })
      )}
    </ScrollView>
  );
}

/* ── Orders (feed / history) ──────────────────────────────────────────────── */
function DriverOrders({ feed, activeOrder, recentEarnings, orderTab, setOrderTab, onOpen, onBid, onRefresh }: any) {
  const { t } = useT();
  const { colors } = useTheme();
  const refresh = usePullRefresh(onRefresh);
  return (
    <View className="flex-1">
      <View className="p-4 pb-0 pt-5">
        <Text className="mb-4 text-xl font-semibold text-foreground">{t("orders")}</Text>
        <View className="flex-row rounded-xl bg-secondary p-1" style={{ gap: 4 }}>
          {(["feed", "history"] as const).map((tp) => (
            <Pressable key={tp} onPress={() => setOrderTab(tp)} className="flex-1 items-center rounded-lg py-2" style={{ backgroundColor: orderTab === tp ? colors.card : "transparent" }}>
              <Text className="text-xs font-medium" style={{ color: orderTab === tp ? colors.foreground : colors.mutedForeground }}>
                {tp === "feed" ? t("matchingOrders") : t("myHistory")}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>
      <ScrollView contentContainerClassName="p-4 gap-3" refreshControl={refresh}>
        {orderTab === "feed" ? (
          feed.length === 0 ? (
            <EmptyState icon={Inbox} title={t("noOrdersYet")} />
          ) : (
            feed.map((o: UiFeedOrder) => (
              <Pressable key={o.id} onPress={() => onOpen(o.id)} className="rounded-2xl border border-border bg-card p-4 active:opacity-90">
                <View className="mb-3 flex-row items-center justify-between">
                  <Text className="text-xs text-muted-foreground">{o.code}</Text>
                  <StatusBadge status={o.status} />
                </View>
                <View className="mb-3 flex-row items-center" style={{ gap: 12 }}>
                  <RouteDots />
                  <View className="flex-1">
                    <Text className="text-sm font-semibold text-foreground">{o.from}</Text>
                    <Text className="mb-1 text-[11px] text-muted-foreground">{o.pickup}</Text>
                    <Text className="text-sm font-semibold text-foreground">{o.to}</Text>
                    <Text className="text-[11px] text-muted-foreground">{o.dropoff}</Text>
                  </View>
                  <View className="items-end">
                    <Text className="text-base font-bold text-foreground">{groupNum(o.price)}</Text>
                    <Text className="text-[10px] text-muted-foreground">so'm</Text>
                  </View>
                </View>
                <View className="flex-row items-center justify-between border-t border-border pt-3">
                  <Text className="text-[11px] text-muted-foreground">{o.date}</Text>
                  {o.hasBid ? (
                    <View className="flex-row items-center" style={{ gap: 8 }}>
                      <View className="flex-row items-center" style={{ gap: 6 }}>
                        <CheckCircle2 size={12} color={colors.warning} />
                        <Text className="text-xs" style={{ color: colors.warning }}>{t("bid")}: {groupNum(o.bidPrice ?? 0)} so'm</Text>
                      </View>
                      {(o.bidUpdatesLeft ?? 0) > 0 ? (
                        <Pressable onPress={() => onBid(o)}><Text className="text-xs font-medium" style={{ color: colors.primary }}>{t("bidChangePrice")}</Text></Pressable>
                      ) : null}
                    </View>
                  ) : (
                    <Pressable onPress={() => onBid(o)} className="flex-row items-center rounded-lg border px-3 py-1.5" style={{ gap: 4, borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}26` }}>
                      <Send size={11} color={colors.primary} />
                      <Text className="text-xs font-medium" style={{ color: colors.primary }}>{t("sendBid")}</Text>
                    </Pressable>
                  )}
                </View>
              </Pressable>
            ))
          )
        ) : (
          <>
            {activeOrder ? (
              <Pressable onPress={() => onOpen(activeOrder.id)} className="rounded-2xl border p-4" style={{ borderColor: `${colors.info}4D`, backgroundColor: `${colors.info}0D` }}>
                <View className="mb-2 flex-row items-center justify-between">
                  <Text className="text-xs text-muted-foreground">{activeOrder.code}</Text>
                  <StatusBadge status={activeOrder.status} />
                </View>
                <Text className="mb-1 text-sm font-semibold text-foreground">{activeOrder.from} → {activeOrder.to}</Text>
                <View className="mt-3 flex-row items-center justify-between border-t pt-3" style={{ borderColor: `${colors.info}33` }}>
                  <View className="flex-row" style={{ gap: 16 }}>
                    <Text className="text-xs text-muted-foreground">{t("gross")}: <Text className="text-foreground">{groupNum(activeOrder.gross)}</Text></Text>
                    <Text className="text-xs text-muted-foreground">{t("net")}: <Text style={{ color: colors.success }}>{groupNum(activeOrder.net)}</Text></Text>
                  </View>
                  <ChevronRight size={14} color={colors.mutedForeground} />
                </View>
              </Pressable>
            ) : null}
            {recentEarnings.map((e: any) => (
              <View key={e.id} className="rounded-2xl border border-border bg-card p-4">
                <View className="flex-row items-center justify-between">
                  <View>
                    <Text className="text-sm font-semibold text-foreground">{e.from} → {e.to}</Text>
                    <Text className="text-[11px] text-muted-foreground">{e.code} · {e.date}</Text>
                  </View>
                  <View className="items-end">
                    <Text className="text-sm font-bold" style={{ color: colors.success }}>+{groupNum(e.net)} so'm</Text>
                    <Text className="text-[10px] text-muted-foreground">{t("net")}</Text>
                  </View>
                </View>
              </View>
            ))}
            {!activeOrder && recentEarnings.length === 0 ? <EmptyState icon={Package} title={t("noOrdersYet")} /> : null}
          </>
        )}
      </ScrollView>
    </View>
  );
}

/* ── Order detail ─────────────────────────────────────────────────────────── */
function DriverOrderDetail({ order: listOrder, detailId, bidTick, nextStatus, nextStatusLabel, busyStatus, actionErr, onBack, onAdvance, onBid }: any) {
  const { t, lang } = useT();
  const { colors } = useTheme();

  // The list payload is deliberately limited until the bid is accepted (no
  // contacts, price or coordinates). Fetch the detail endpoint so an order —
  // opened from the feed (no assigned order yet) or an assigned one — shows its
  // real data. `listOrder` may be null when opened straight from the feed.
  // bidTick forces a refetch after the driver places/updates a bid.
  const orderId = detailId ?? listOrder?.id;
  const { data: detail, reload } = useAsync<any>(() => getDriverOrderDetail(orderId), [orderId, bidTick]);
  const refresh = usePullRefresh(reload);
  const order = detail ? mapActiveOrder(detail) : listOrder;

  // Opened from the feed the detail is fetched fresh, so show a spinner until
  // it arrives instead of a blank screen.
  if (!order) {
    return (
      <View className="flex-1">
        <BackHeader onBack={onBack} title="" />
        <Spinner />
      </View>
    );
  }

  const mapUrl = mapsDirectionsUrl(order.pickupLat, order.pickupLng, order.dropoffLat, order.dropoffLng);
  const sf = [
    { key: "accepted", label: t("accepted") },
    { key: "picked_up", label: t("pickedUp") },
    { key: "in_transit", label: t("inTransit") },
    { key: "delivered", label: t("delivered") },
  ];
  const ci = sf.findIndex((s) => s.key === order.status);
  const isAssigned = ci >= 0 || order.status === "confirmed";

  // Income: real figures once the order is won; otherwise the driver's
  // potential earnings at the client's offered price, so the report is useful
  // instead of a misleading zero.
  const incGross = order.gross || order.offeredPrice;
  const incCommission = order.commission || Math.round(incGross * 0.15);
  const incNet = order.net || Math.max(incGross - incCommission, 0);

  // Bidding: on an open order the driver can place or change a bid. my_bid holds
  // the existing bid and how many price changes remain.
  const biddable = order.status === "published" || order.status === "bidding";
  const myBid = detail?.my_bid;
  const hasBid = Boolean(myBid);
  const bidUpdatesLeft = myBid?.price_updates_left ?? 3;
  function openBid() {
    onBid?.({
      id: order.id, code: order.code, from: order.from, to: order.to,
      status: order.status, price: order.offeredPrice,
      pickup: order.pickup, dropoff: order.dropoff, date: order.date,
      hasBid, bidId: myBid?.id,
      bidPrice: myBid?.price != null ? Number(myBid.price) : undefined,
      bidUpdatesLeft: myBid?.price_updates_left,
    });
  }

  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={order.code} right={<StatusBadge status={order.status} />} />
      <ScrollView contentContainerClassName="p-4 gap-4" refreshControl={refresh}>
        <View className="rounded-2xl border border-border bg-card p-4 flex-row" style={{ gap: 12 }}>
          <RouteDots />
          <View className="flex-1">
            <Text className="text-sm font-bold text-foreground">{order.from}</Text>
            <Text className="mb-3 text-xs text-muted-foreground">{order.pickup}</Text>
            <Text className="text-sm font-bold text-foreground">{order.to}</Text>
            <Text className="text-xs text-muted-foreground">{order.dropoff}</Text>
          </View>
        </View>

        {/* Offered price + cargo — what a driver needs to size up a feed order.
            For a won order the income card below carries the money detail. */}
        {!isAssigned ? (
          <View className="flex-row rounded-2xl border border-border bg-card p-4" style={{ gap: 12 }}>
            <View className="flex-1">
              <Text className="text-[11px] text-muted-foreground">{t("clientPrice")}</Text>
              <Text className="text-lg font-bold text-foreground">{order.offeredPrice ? fmt(order.offeredPrice) : "—"}</Text>
            </View>
            {order.cargoType ? (
              <View className="flex-row items-center" style={{ gap: 8 }}>
                <Package size={14} color={colors.mutedForeground} />
                <View>
                  <Text className="text-[11px] text-muted-foreground">{lang === "ru" ? "Тип отправления" : lang === "en" ? "Parcel type" : "Jo'natma turi"}</Text>
                  <Text className="text-sm font-medium text-foreground">{cargoTypeLabel(order.cargoType, lang)}</Text>
                </View>
              </View>
            ) : null}
          </View>
        ) : null}

        {mapUrl ? (
          <>
            <MapPanel pickupLat={order.pickupLat} pickupLng={order.pickupLng} dropoffLat={order.dropoffLat} dropoffLng={order.dropoffLng} />
            <Pressable onPress={() => Linking.openURL(mapUrl)} className="flex-row items-center justify-center rounded-2xl border py-3" style={{ gap: 8, borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}0D` }}>
              <Navigation size={16} color={colors.primary} />
              <Text className="text-sm font-semibold" style={{ color: colors.primary }}>{t("openInMaps")}</Text>
            </Pressable>
          </>
        ) : null}

        {/* Status progress */}
        <View className="rounded-2xl border border-border bg-card p-4">
          <Text className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">{t("statusProgress")}</Text>
          <View className="flex-row items-center">
            {sf.map((s, i) => (
              <View key={s.key} className="flex-1 flex-row items-center">
                <View style={{ width: 12, height: 12, borderRadius: 6, borderWidth: 2, backgroundColor: i <= ci ? colors.primary : colors.secondary, borderColor: i <= ci ? colors.primary : colors.border }} />
                {i < sf.length - 1 ? <View style={{ flex: 1, height: 2, backgroundColor: i < ci ? colors.primary : colors.border }} /> : null}
              </View>
            ))}
          </View>
          <View className="mt-2 flex-row justify-between">
            {sf.map((s) => <Text key={s.key} className="text-[8px] text-muted-foreground">{s.label}</Text>)}
          </View>
        </View>

        <DriverOrderBids orderId={orderId} />

        {/* Contact details — client contacts fill in once the driver wins the order. */}
        <View className="rounded-2xl border border-border bg-card p-4" style={{ gap: 12 }}>
          <Text className="text-xs uppercase tracking-wide text-muted-foreground">{t("contactDetails")}</Text>
          {order.cargoType ? (
            <View className="flex-row items-start" style={{ gap: 12 }}>
              <Package size={14} color={colors.mutedForeground} />
              <View>
                <Text className="text-[10px] text-muted-foreground">{lang === "ru" ? "Тип отправления" : lang === "en" ? "Parcel type" : "Jo'natma turi"}</Text>
                <Text className="text-sm text-foreground">{cargoTypeLabel(order.cargoType, lang)}</Text>
              </View>
            </View>
          ) : null}
          {[
            { label: t("sender"), value: order.sender },
            { label: t("receiver"), value: order.receiver },
            { label: t("comment"), value: order.comment },
          ].map(({ label, value }) => (
            <View key={label} className="flex-row items-start" style={{ gap: 12 }}>
              <FileText size={14} color={colors.mutedForeground} />
              <View>
                <Text className="text-[10px] text-muted-foreground">{label}</Text>
                <Text className="text-sm text-foreground">{value || "—"}</Text>
              </View>
            </View>
          ))}
        </View>

        {/* Income report — real once won, else potential earnings at the offered price. */}
        <View className="rounded-2xl border p-4" style={{ borderColor: `${colors.success}33`, backgroundColor: `${colors.success}0D` }}>
          <Text className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">{t("incomeReport")}</Text>
          <View style={{ gap: 8 }}>
            {[
              { label: t("grossAmount"), value: fmt(incGross), color: colors.foreground, big: false },
              { label: t("systemFee"), value: `−${fmt(incCommission)}`, color: colors.destructive, big: false },
              { label: t("netIncome"), value: fmt(incNet), color: colors.success, big: true },
            ].map(({ label, value, color, big }) => (
              <View key={label} className="flex-row items-center justify-between">
                <Text className="text-xs text-muted-foreground">{label}</Text>
                <Text style={{ color, fontSize: big ? 16 : 14, fontWeight: big ? "700" : "400" }}>{value}</Text>
              </View>
            ))}
          </View>
        </View>

        {actionErr ? (
          <View className="flex-row items-center px-1" style={{ gap: 4 }}>
            <AlertCircle size={11} color={colors.destructive} />
            <Text style={{ fontSize: 12, color: colors.destructive }}>{actionErr}</Text>
          </View>
        ) : null}
        {nextStatus ? (
          <Pressable onPress={onAdvance} disabled={busyStatus} className="w-full items-center rounded-2xl bg-primary py-3.5" style={{ opacity: busyStatus ? 0.7 : 1 }}>
            <Text className="text-sm font-semibold text-primary-foreground">{nextStatusLabel}</Text>
          </Pressable>
        ) : biddable ? (
          <Pressable
            onPress={openBid}
            disabled={hasBid && bidUpdatesLeft <= 0}
            className="w-full flex-row items-center justify-center rounded-2xl bg-primary py-3.5"
            style={{ gap: 8, opacity: hasBid && bidUpdatesLeft <= 0 ? 0.5 : 1 }}
          >
            <Send size={15} color={colors.primaryForeground} />
            <Text className="text-sm font-semibold text-primary-foreground">
              {hasBid ? (bidUpdatesLeft > 0 ? t("bidChangePrice") : t("bidNoChangesLeft")) : t("sendBid")}
            </Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </View>
  );
}

/* ── Income ───────────────────────────────────────────────────────────────── */
function DriverIncome({ netIncome, grossIncome, commissionTotal, chartData, recentEarnings, period, setPeriod, onBack }: any) {
  const { t } = useT();
  const { colors } = useTheme();
  const maxAmount = chartData.reduce((m: number, d: any) => Math.max(m, d.amount), 0) || 1;
  return (
    <View className="flex-1">
      <BackHeader onBack={onBack} title={t("income")} />
      <ScrollView contentContainerClassName="p-4 gap-4">
        <View className="rounded-2xl border p-5" style={{ borderColor: `${colors.primary}33`, backgroundColor: `${colors.primary}0D` }}>
          <Text className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">{t("netIncome")}</Text>
          <Text className="text-3xl font-bold text-foreground">{groupNum(netIncome)} so'm</Text>
          <Text className="mt-1 text-xs text-muted-foreground">{t("afterCommission")}</Text>
          <View className="mt-4 flex-row border-t pt-4" style={{ gap: 16, borderColor: `${colors.primary}1A` }}>
            <View><Text className="text-[10px] text-muted-foreground">{t("gross")}</Text><Text className="text-sm text-foreground">{fmt(grossIncome)}</Text></View>
            <View><Text className="text-[10px] text-muted-foreground">{t("commission")}</Text><Text className="text-sm" style={{ color: colors.destructive }}>−{fmt(commissionTotal)}</Text></View>
          </View>
        </View>

        <View className="rounded-2xl border border-border bg-card p-4">
          <View className="mb-4 flex-row items-center justify-between">
            <Text className="text-sm font-semibold text-foreground">{t("earningsChart")}</Text>
            <View className="flex-row rounded-lg bg-secondary p-0.5" style={{ gap: 2 }}>
              {(["daily", "monthly"] as const).map((p) => (
                <Pressable key={p} onPress={() => setPeriod(p)} className="rounded-md px-3 py-1" style={{ backgroundColor: period === p ? colors.card : "transparent" }}>
                  <Text className="text-xs font-medium" style={{ color: period === p ? colors.foreground : colors.mutedForeground }}>{p === "daily" ? t("sevenDays") : t("sixMonths")}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          {chartData.length === 0 ? (
            <View style={{ height: 140 }} className="items-center justify-center">
              <Text className="text-xs text-muted-foreground">{t("noOrdersYet")}</Text>
            </View>
          ) : (
            <View style={{ height: 140, flexDirection: "row", alignItems: "flex-end", justifyContent: "space-around", gap: 8 }}>
              {chartData.map((d: any, i: number) => (
                <View key={i} className="flex-1 items-center" style={{ gap: 4 }}>
                  <View style={{ width: "70%", height: Math.max(4, (d.amount / maxAmount) * 110), backgroundColor: colors.primary, borderTopLeftRadius: 6, borderTopRightRadius: 6 }} />
                  <Text className="text-[9px] text-muted-foreground" numberOfLines={1}>{d.label}</Text>
                </View>
              ))}
            </View>
          )}
        </View>

        <View>
          <Text className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">{t("recentEarnings")}</Text>
          <View style={{ gap: 8 }}>
            {recentEarnings.map((e: any) => (
              <View key={e.id} className="flex-row items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
                <View>
                  <Text className="text-sm font-semibold text-foreground">{e.from} → {e.to}</Text>
                  <Text className="text-[11px] text-muted-foreground">{e.code} · {e.date}</Text>
                </View>
                <Text className="text-sm font-bold" style={{ color: colors.success }}>+{groupNum(e.net)} so'm</Text>
              </View>
            ))}
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

/* ── Profile ──────────────────────────────────────────────────────────────── */
function DriverProfile({ data, avail, isApproved, busyAvail, actionErr, onToggleAvail, onEdit, onDocs, onRoutes, onOrders, onIncome, onSettings, onLogout, onRefresh }: any) {
  const { t } = useT();
  const { colors } = useTheme();
  const refresh = usePullRefresh(onRefresh);
  const links = [
    { icon: Pencil, label: t("editProfile"), action: onEdit },
    { icon: FileText, label: t("documents"), action: onDocs },
    { icon: Route, label: t("myRoutes"), action: onRoutes },
    { icon: Package, label: t("orders"), action: onOrders },
    { icon: TrendingUp, label: t("income"), action: onIncome },
    { icon: Settings, label: t("settings"), action: onSettings },
  ];
  return (
    <ScrollView contentContainerClassName="p-4 gap-4 pb-6" refreshControl={refresh}>
      <Text className="pt-1 text-[22px] font-extrabold text-foreground">{t("profile")}</Text>

      <View className="rounded-2xl bg-card p-5 border border-border">
        <View className="mb-4 flex-row items-center" style={{ gap: 16 }}>
          <View className="items-center justify-center rounded-2xl" style={{ width: 64, height: 64, backgroundColor: `${colors.primary}26` }}>
            <Truck size={28} color={colors.primary} />
          </View>
          <View className="min-w-0 flex-1">
            <Text className="text-lg font-bold text-foreground" numberOfLines={1}>{data.name}</Text>
            <Text className="text-sm text-muted-foreground">{data.phone}</Text>
            <View className="mt-1 flex-row" style={{ gap: 8 }}>
              <StatusBadge status={data.status} />
              <StatusBadge status={avail ? "active" : "inactive"} />
            </View>
          </View>
        </View>
        <View className="flex-row border-t border-border pt-4">
          {[
            { label: t("rating"), value: String(data.rating) },
            { label: t("completed"), value: String(data.completedOrders) },
            { label: t("total"), value: String(data.totalOrders) },
          ].map(({ label, value }) => (
            <View key={label} className="flex-1 items-center">
              <Text className="text-lg font-bold text-foreground">{value}</Text>
              <Text className="text-[10px] text-muted-foreground">{label}</Text>
            </View>
          ))}
        </View>
      </View>

      <View className="rounded-2xl bg-card p-4 border border-border">
        <View className="flex-row items-center justify-between">
          <View>
            <Text className="text-sm font-semibold text-foreground">{t("availability")}</Text>
            <Text className="text-xs text-muted-foreground">{avail ? t("youAreOnline") : t("youAreOffline")}</Text>
          </View>
          <Pressable onPress={onToggleAvail} style={{ opacity: !isApproved || busyAvail ? 0.4 : 1 }}>
            {avail ? <ToggleRight size={36} color={colors.primary} /> : <ToggleLeft size={36} color={colors.mutedForeground} />}
          </Pressable>
        </View>
        {actionErr ? <Text className="mt-2 text-xs" style={{ color: colors.destructive }}>{actionErr}</Text> : null}
      </View>

      <View className="rounded-2xl bg-card p-4 border border-border">
        <View className="mb-3 flex-row items-center" style={{ gap: 8 }}>
          <Truck size={16} color={colors.primary} />
          <Text className="text-sm font-semibold text-foreground">{t("vehicle")}</Text>
          <StatusBadge status={data.status} />
        </View>
        <View style={{ gap: 8 }}>
          {[
            { label: t("carModel"), value: data.car.model },
            { label: t("carColor"), value: data.car.color },
            { label: t("plateNumber"), value: data.car.plate },
          ].map(({ label, value }) => (
            <View key={label} className="flex-row justify-between">
              <Text className="text-xs text-muted-foreground">{label}</Text>
              <Text className="text-xs text-foreground">{value}</Text>
            </View>
          ))}
        </View>
      </View>

      <View className="overflow-hidden rounded-2xl border border-border bg-card">
        {links.map(({ icon: Icon, label, action }, i) => (
          <Pressable key={label} onPress={action} className="flex-row items-center px-4 py-3 active:bg-secondary" style={{ gap: 12, borderTopWidth: i > 0 ? 1 : 0, borderColor: colors.border }}>
            <IconTile icon={Icon} size={15} />
            <Text className="flex-1 text-sm text-foreground">{label}</Text>
            <ChevronRight size={16} color={colors.mutedForeground} />
          </Pressable>
        ))}
        <Pressable onPress={onLogout} className="flex-row items-center border-t border-border px-4 py-3 active:opacity-80" style={{ gap: 12 }}>
          <IconTile icon={LogOut} size={15} tone="danger" />
          <Text className="flex-1 text-sm" style={{ color: colors.destructive }}>{t("logOut")}</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

/* ── Bottom nav ───────────────────────────────────────────────────────────── */
function DriverBottomNav({ tab, screen, onTab, onAdd }: { tab: DriverTab; screen: DriverScreen; onTab: (t: DriverTab) => void; onAdd: () => void }) {
  const { colors } = useTheme();
  const left: { id: DriverTab; icon: typeof Home }[] = [{ id: "home", icon: Home }, { id: "routes", icon: Route }];
  const right: { id: DriverTab; icon: typeof Home }[] = [{ id: "orders", icon: Inbox }, { id: "profile", icon: User }];
  const NavBtn = ({ id, Icon }: { id: DriverTab; Icon: typeof Home }) => {
    const active = tab === id && screen === id;
    return (
      <Pressable onPress={() => onTab(id)} className="h-11 w-11 items-center justify-center rounded-full" style={{ backgroundColor: active ? colors.primary : "transparent" }}>
        <Icon size={21} color={active ? colors.primaryForeground : colors.mutedForeground} />
      </Pressable>
    );
  };
  return (
    <View className="px-5 pb-2 pt-3">
      <View className="flex-row items-center justify-between rounded-full border border-border bg-card px-3 py-2" style={{ shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 12, elevation: 8 }}>
        {left.map((n) => <NavBtn key={n.id} id={n.id} Icon={n.icon} />)}
        <Pressable onPress={onAdd} className="h-14 w-14 items-center justify-center rounded-full bg-primary active:opacity-90">
          <Plus size={26} color={colors.primaryForeground} />
        </Pressable>
        {right.map((n) => <NavBtn key={n.id} id={n.id} Icon={n.icon} />)}
      </View>
    </View>
  );
}
