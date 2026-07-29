import { useEffect, useRef, useState } from "react";
import { Animated, BackHandler, Modal, Pressable, Text, View } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Bell, Headphones, Home, LogOut, Menu, Package, Settings, User, X } from "@/components/icons";
import { useT } from "@/i18n/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { useSession } from "@/auth/SessionProvider";
import { normalizeUzPhone } from "@/utils/phone";
import { useAsync } from "@/data/useApi";
import { getNotifications } from "@/api/notifications.api";
import { createClientOrder, listClientOrders, publishClientOrder } from "@/api/client-orders.api";
import { sessionPhone } from "@/data/session";
import { EMPTY_DRAFT, type CityInfo, type LocationPoint, type OrderDraft } from "@/core/order";
import { detectCurrentPickup } from "@/data/currentLocation";
import { SettingsPanel } from "@/components/SettingsPanel";
import { ClientHomeScreen } from "./ClientHomeScreen";
import { ClientSupportScreen } from "./ClientSupportScreen";
import { CitySelectScreen } from "./CitySelectScreen";
import { DistrictSelectScreen, type PickedDistrict } from "./DistrictSelectScreen";
import { MapPickerScreen, type PickedLocation } from "./MapPickerScreen";
import { ContactsScreen } from "./ContactsScreen";
import { CargoPhotoScreen } from "./CargoPhotoScreen";
import { OrderReviewScreen } from "./OrderReviewScreen";
import { OrderSuccessScreen } from "./OrderSuccessScreen";
import { ClientOrdersScreen } from "./ClientOrdersScreen";
import { ClientOrderDetailScreen } from "./ClientOrderDetailScreen";
import { ClientBidsScreen } from "./ClientBidsScreen";
import { ConfirmDeliveryScreen } from "./ConfirmDeliveryScreen";
import { RatingScreen } from "./RatingScreen";
import { DisputeScreen } from "./DisputeScreen";
import { ClientNotificationsScreen } from "./ClientNotificationsScreen";
import { ClientProfileScreen, type ClientStats } from "./ClientProfileScreen";

type ClientTab = "home" | "orders" | "notifications" | "profile";
type ClientScreen =
  | ClientTab
  | "city-select-from" | "city-select-to"
  | "district-select-from" | "district-select-to"
  | "map-picker-from" | "map-picker-to"
  | "contacts" | "cargo-photo" | "order-review" | "order-success"
  | "c-order-detail" | "bids" | "confirm-delivery" | "rating" | "dispute"
  | "c-settings" | "c-support";

const MAIN_TABS: ClientScreen[] = ["home", "orders", "notifications", "profile"];

export function ClientApp() {
  const { t, lang, setLang } = useT();
  const { colors, themeMode, setThemeMode } = useTheme();
  const { logout } = useSession();
  const insets = useSafeAreaInsets();
  const phone = sessionPhone("client");

  const [tab, setTab] = useState<ClientTab>("home");
  const [screen, setScreen] = useState<ClientScreen>("home");
  const [menuOpen, setMenuOpen] = useState(false);
  const [draft, setDraft] = useState<OrderDraft>(EMPTY_DRAFT);
  const [selOrder, setSelOrder] = useState<number>(0);
  const [pendingCity, setPendingCity] = useState<CityInfo | null>(null);
  const [pendingDist, setPendingDist] = useState<PickedDistrict | undefined>();
  const [side, setSide] = useState<"from" | "to">("from");
  const [detectingLoc, setDetectingLoc] = useState(true);
  const detectedRef = useRef(false);

  // Pre-fill "from" with the client's current location on first load; they can
  // still tap to change it. Runs once, and never overrides a manual choice.
  useEffect(() => {
    if (detectedRef.current) return;
    detectedRef.current = true;
    let active = true;
    detectCurrentPickup()
      .then((pt) => {
        if (active && pt) {
          setDraft((d) => (d.pickup ? d : { ...d, pickup: pt, pickupAddress: pt.address }));
        }
      })
      .finally(() => {
        if (active) setDetectingLoc(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const { data: ordersData, reload: reloadOrders } = useAsync<any>(
    () => listClientOrders({ limit: 100 }),
    [screen === "home" || screen === "profile"],
  );
  const allOrders: any[] = ordersData?.items ?? [];
  const stats: ClientStats = {
    active: allOrders.filter((o) => ["published", "bidding", "accepted", "picked_up", "in_transit"].includes(o.status)).length,
    bids: allOrders.reduce((s, o) => s + (o.bids_count || 0), 0),
    completed: allOrders.filter((o) => ["delivered", "confirmed"].includes(o.status)).length,
  };

  const { data: notifData, loading: notifLoading, reload: reloadNotifs } = useAsync<any>(
    () => getNotifications({ limit: 50 }),
    [tab],
  );
  const notifs: any[] = notifData?.items ?? [];
  const unreadNotifs = notifs.filter((n) => !n.is_read).length;

  const goTo = (s: ClientScreen) => setScreen(s);
  const goTab = (tb: ClientTab) => {
    setTab(tb);
    setScreen(tb);
  };

  // Hardware back: close the drawer, else return sub-screens to their tab.
  useEffect(() => {
    const onBack = () => {
      if (menuOpen) {
        setMenuOpen(false);
        return true;
      }
      if (!MAIN_TABS.includes(screen)) {
        goTab(tab);
        return true;
      }
      return false;
    };
    const sub = BackHandler.addEventListener("hardwareBackPress", onBack);
    return () => sub.remove();
  }, [menuOpen, screen, tab]);

  function handleCity(city: CityInfo, forSide: "from" | "to") {
    setSide(forSide);
    setPendingCity(city);
    if (city.dist) goTo(forSide === "from" ? "district-select-from" : "district-select-to");
    else {
      setPendingDist(undefined);
      goTo(forSide === "from" ? "map-picker-from" : "map-picker-to");
    }
  }
  function handleDistrict(d: PickedDistrict) {
    setPendingDist(d);
    goTo(side === "from" ? "map-picker-from" : "map-picker-to");
  }
  function handleConfirmLoc(loc: PickedLocation) {
    if (!pendingCity) return;
    const pt: LocationPoint = {
      city: pendingCity,
      district: pendingDist?.name,
      districtId: pendingDist?.id ?? null,
      address: loc.address,
      lat: loc.lat,
      lng: loc.lng,
    };
    if (side === "from") setDraft((d) => ({ ...d, pickup: pt, pickupAddress: loc.address }));
    else setDraft((d) => ({ ...d, dropoff: pt, dropoffAddress: loc.address }));
    goTo("home");
  }

  async function publishOrder() {
    if (!draft.pickup || !draft.dropoff) throw new Error("VALIDATION_ERROR");
    const created: any = await createClientOrder({
      from_city_id: draft.pickup.city.id,
      to_city_id: draft.dropoff.city.id,
      from_district_id: draft.pickup.districtId ?? null,
      to_district_id: draft.dropoff.districtId ?? null,
      pickup_address: draft.pickupAddress || draft.pickup.address,
      dropoff_address: draft.dropoffAddress || draft.dropoff.address,
      pickup_lat: draft.pickup.lat ?? null,
      pickup_lng: draft.pickup.lng ?? null,
      dropoff_lat: draft.dropoff.lat ?? null,
      dropoff_lng: draft.dropoff.lng ?? null,
      sender_phone: normalizeUzPhone(draft.senderPhone),
      receiver_phone: normalizeUzPhone(draft.receiverPhone),
      cargo_type: draft.cargoType || null,
      cargo_photo_url: draft.cargoPhotoUrl ?? null,
      client_price: draft.clientPrice ? Number(draft.clientPrice) : null,
      comment: draft.comment || null,
    });
    await publishClientOrder(created.id);
    setSelOrder(created.id);
    goTo("order-success");
  }

  const isMain = MAIN_TABS.includes(screen);
  const patch = (p: Partial<OrderDraft>) => setDraft((d) => ({ ...d, ...p }));

  return (
    <SafeAreaView edges={["top", "bottom"]} className="flex-1 bg-background">
      <View className="flex-1">
        {screen === "home" && (
          <ClientHomeScreen
            onSelectFrom={() => { setSide("from"); goTo("city-select-from"); }}
            onSelectTo={() => { setSide("to"); goTo("city-select-to"); }}
            draft={draft}
            detectingFrom={detectingLoc && !draft.pickup}
            onViewRoute={() => goTo("contacts")}
            onSupport={() => goTo("c-support")}
          />
        )}
        {screen === "city-select-from" && <CitySelectScreen title={t("chooseCity")} onBack={() => goTo("home")} onSelect={(c) => handleCity(c, "from")} />}
        {screen === "city-select-to" && <CitySelectScreen title={t("chooseCity")} onBack={() => goTo("home")} onSelect={(c) => handleCity(c, "to")} />}
        {screen === "district-select-from" && pendingCity && <DistrictSelectScreen city={pendingCity} onBack={() => goTo("city-select-from")} onSelect={handleDistrict} />}
        {screen === "district-select-to" && pendingCity && <DistrictSelectScreen city={pendingCity} onBack={() => goTo("city-select-to")} onSelect={handleDistrict} />}
        {screen === "map-picker-from" && pendingCity && <MapPickerScreen city={pendingCity} district={pendingDist?.name} centerLat={pendingDist?.lat} centerLng={pendingDist?.lng} onBack={() => goTo(pendingCity.dist ? "district-select-from" : "city-select-from")} onConfirm={handleConfirmLoc} />}
        {screen === "map-picker-to" && pendingCity && <MapPickerScreen city={pendingCity} district={pendingDist?.name} centerLat={pendingDist?.lat} centerLng={pendingDist?.lng} onBack={() => goTo(pendingCity.dist ? "district-select-to" : "city-select-to")} onConfirm={handleConfirmLoc} />}
        {screen === "contacts" && <ContactsScreen draft={draft} onChange={patch} onBack={() => goTo("home")} onNext={() => goTo("cargo-photo")} />}
        {screen === "cargo-photo" && <CargoPhotoScreen draft={draft} onChange={patch} onBack={() => goTo("contacts")} onNext={() => goTo("order-review")} />}
        {screen === "order-review" && <OrderReviewScreen draft={draft} onChange={patch} onBack={() => goTo("cargo-photo")} onPublish={publishOrder} />}
        {screen === "order-success" && <OrderSuccessScreen onViewOrder={() => { setDraft(EMPTY_DRAFT); goTo("c-order-detail"); }} onHome={() => { setDraft(EMPTY_DRAFT); goTab("home"); }} />}
        {screen === "orders" && <ClientOrdersScreen onOrderDetail={(id) => { setSelOrder(id); goTo("c-order-detail"); }} onCreateOrder={() => goTab("home")} />}
        {screen === "c-order-detail" && <ClientOrderDetailScreen orderId={selOrder} onBack={() => goTab("orders")} onViewBids={() => goTo("bids")} onConfirmDelivery={() => goTo("confirm-delivery")} onRate={() => goTo("rating")} onDispute={() => goTo("dispute")} onCancelled={() => goTab("orders")} />}
        {screen === "bids" && <ClientBidsScreen orderId={selOrder} onBack={() => goTo("c-order-detail")} onSelectDriver={() => goTo("c-order-detail")} />}
        {screen === "confirm-delivery" && <ConfirmDeliveryScreen orderId={selOrder} onBack={() => goTo("c-order-detail")} onConfirm={() => goTo("rating")} />}
        {screen === "rating" && <RatingScreen orderId={selOrder} onBack={() => goTo("orders")} onSubmit={() => goTab("orders")} />}
        {screen === "dispute" && <DisputeScreen orderId={selOrder} onBack={() => goTo("c-order-detail")} />}
        {screen === "notifications" && <ClientNotificationsScreen notifs={notifs} loading={notifLoading} reload={reloadNotifs} />}
        {screen === "profile" && <ClientProfileScreen phone={phone} stats={stats} onRefresh={reloadOrders} onOrders={() => goTab("orders")} onNotifications={() => goTab("notifications")} onSettings={() => goTo("c-settings")} onLogout={logout} />}
        {screen === "c-settings" && <SettingsPanel onBack={() => goTo("profile")} themeMode={themeMode} onThemeChange={setThemeMode} lang={lang} onLangChange={setLang} onLogout={logout} notifKeys={{ a: "bidAlerts", ad: "bidAlertsDesc", b: "orderUpdates", bd: "orderUpdatesDesc" }} />}
        {screen === "c-support" && <ClientSupportScreen onBack={() => goTo("home")} />}
      </View>

      {/* Floating menu button on main screens */}
      {isMain && !menuOpen ? (
        <Pressable
          onPress={() => setMenuOpen(true)}
          accessibilityLabel={t("menu")}
          className="absolute h-11 w-11 items-center justify-center rounded-full border border-border bg-card active:opacity-80"
          // Position below the status bar via the real safe-area inset (a fixed
          // top-4 landed inside the status bar, so the OS ate the taps). High
          // elevation/zIndex gives it draw + touch priority over the native map.
          style={{ position: "absolute", top: insets.top + 8, left: 16, shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 8, elevation: 30, zIndex: 30 }}
        >
          <Menu size={20} color={colors.foreground} />
          {unreadNotifs > 0 ? (
            <View
              style={{ position: "absolute", top: 2, right: 2, width: 10, height: 10, borderRadius: 5, backgroundColor: colors.destructive, borderWidth: 2, borderColor: colors.card }}
            />
          ) : null}
        </Pressable>
      ) : null}

      <ClientDrawer
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        phone={phone}
        tab={tab}
        unread={unreadNotifs}
        onTab={(tb) => { goTab(tb); setMenuOpen(false); }}
        onSupport={() => { goTo("c-support"); setMenuOpen(false); }}
        onSettings={() => { goTo("c-settings"); setMenuOpen(false); }}
        onLogout={logout}
      />
    </SafeAreaView>
  );
}

function ClientDrawer({
  open,
  onClose,
  phone,
  tab,
  unread,
  onTab,
  onSupport,
  onSettings,
  onLogout,
}: {
  open: boolean;
  onClose: () => void;
  phone: string;
  tab: ClientTab;
  unread: number;
  onTab: (t: ClientTab) => void;
  onSupport: () => void;
  onSettings: () => void;
  onLogout: () => void;
}) {
  const { t } = useT();
  const { colors } = useTheme();
  const slide = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (open) {
      slide.setValue(0);
      Animated.timing(slide, { toValue: 1, duration: 220, useNativeDriver: true }).start();
    }
  }, [open, slide]);

  const items: { id: ClientTab; icon: typeof Home; label: string }[] = [
    { id: "home", icon: Home, label: t("home") },
    { id: "orders", icon: Package, label: t("orders") },
    { id: "notifications", icon: Bell, label: t("notifications") },
    { id: "profile", icon: User, label: t("profile") },
  ];

  return (
    <Modal visible={open} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable onPress={onClose} className="flex-1" style={{ backgroundColor: "rgba(0,0,0,0.5)" }}>
        <Animated.View
          style={{
            height: "100%",
            width: "80%",
            maxWidth: 300,
            backgroundColor: colors.background,
            borderRightWidth: 1,
            borderColor: colors.border,
            transform: [{ translateX: slide.interpolate({ inputRange: [0, 1], outputRange: [-300, 0] }) }],
          }}
        >
          <SafeAreaView edges={["top", "bottom"]} className="flex-1">
            <Pressable onPress={() => {}} className="flex-1">
              <View className="flex-row items-center justify-between border-b border-border p-5">
                <View className="min-w-0 flex-1 flex-row items-center" style={{ gap: 12 }}>
                  <View className="items-center justify-center rounded-full" style={{ width: 44, height: 44, backgroundColor: `${colors.primary}26` }}>
                    <User size={22} color={colors.primary} />
                  </View>
                  <View className="min-w-0">
                    <Text className="text-sm font-semibold text-foreground" numberOfLines={1}>{phone || "—"}</Text>
                    <Text className="text-[11px] text-muted-foreground">{t("client")}</Text>
                  </View>
                </View>
                <Pressable onPress={onClose} className="h-8 w-8 items-center justify-center rounded-full active:bg-secondary">
                  <X size={16} color={colors.mutedForeground} />
                </Pressable>
              </View>

              <View className="flex-1 p-3" style={{ gap: 4 }}>
                {items.map(({ id, icon: Icon, label }) => {
                  const active = tab === id;
                  return (
                    <Pressable
                      key={id}
                      onPress={() => onTab(id)}
                      className="flex-row items-center rounded-xl px-4 py-3"
                      style={{ gap: 12, backgroundColor: active ? colors.secondary : "transparent" }}
                    >
                      <Icon size={19} color={active ? colors.primary : colors.mutedForeground} />
                      <Text className="text-sm font-medium" style={{ color: active ? colors.foreground : colors.mutedForeground }}>
                        {label}
                      </Text>
                      {id === "notifications" && unread > 0 ? (
                        <View className="ml-auto items-center justify-center rounded-full px-1.5" style={{ minWidth: 20, height: 20, backgroundColor: colors.destructive }}>
                          <Text className="text-[10px] font-bold text-white">{unread > 9 ? "9+" : unread}</Text>
                        </View>
                      ) : null}
                    </Pressable>
                  );
                })}
                <Pressable onPress={onSupport} className="flex-row items-center rounded-xl px-4 py-3" style={{ gap: 12 }}>
                  <Headphones size={19} color={colors.mutedForeground} />
                  <Text className="text-sm font-medium text-muted-foreground">{t("helpTitle")}</Text>
                </Pressable>
                <Pressable onPress={onSettings} className="flex-row items-center rounded-xl px-4 py-3" style={{ gap: 12 }}>
                  <Settings size={19} color={colors.mutedForeground} />
                  <Text className="text-sm font-medium text-muted-foreground">{t("settings")}</Text>
                </Pressable>
              </View>

              <View className="border-t border-border p-3">
                <Pressable onPress={onLogout} className="flex-row items-center rounded-xl px-4 py-3 active:opacity-80" style={{ gap: 12 }}>
                  <LogOut size={19} color={colors.destructive} />
                  <Text className="text-sm font-medium" style={{ color: colors.destructive }}>{t("logOut")}</Text>
                </Pressable>
              </View>
            </Pressable>
          </SafeAreaView>
        </Animated.View>
      </Pressable>
    </Modal>
  );
}
