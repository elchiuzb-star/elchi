import { useState, createContext, useContext, useEffect, useRef } from "react";
import { RouterProvider, createBrowserRouter, useNavigate, Outlet, Navigate } from "react-router";
import {
  House as Home, MapPin, Package, User, CaretRight as ChevronRight, CaretLeft as ChevronLeft,
  ToggleLeft, ToggleRight, Star, Plus, Trash as Trash2, Pencil, TrendUp as TrendingUp,
  CheckCircle as CheckCircle2, Clock, Truck, FileText, WarningCircle as AlertCircle, PaperPlaneTilt as Send, NavigationArrow as Navigation,
  Shield, Phone, Car, Path as Route, Tray as Inbox, SignOut as LogOut, Bell, Sun, Moon, Monitor,
  Gear as Settings, Globe, Info, Vibrate, ArrowRight, ArrowsClockwise as RefreshCw, X, List as Menu,
  Camera, Image, ThumbsUp, Flag, MagnifyingGlass as Search,
  CreditCard, Checks as CheckCheck, Prohibit as Ban, PencilSimple as Edit3, Eye, Crosshair as Locate, Lock, Headphones,
  SquaresFour as LayoutDashboard, Users, Tag, ShieldCheck, SealCheck, SealWarning, ClipboardText as ClipboardList, CurrencyDollar as DollarSign,
  Pulse as Activity, CaretDown as ChevronDown, SidebarSimple as PanelLeftClose, Sidebar as PanelLeft, ArrowUpRight,
  RadioButton as CircleDot, UserCheck, UserMinus as UserX, Lightning as Zap, Funnel as Filter, DownloadSimple as Download, ArrowSquareOut as ExternalLink,
} from "@phosphor-icons/react";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip } from "recharts";
import {
  sessionRequestOtp, sessionVerifyOtp, sessionLogout, isSessionActive, sessionRefreshMe, sessionPhone, sessionUser,
} from "../data/session";
import { getUzbekErrorMessage } from "../utils/errors";
import {
  setDriverAvailability, sendBid, updateBid, createDriverRoute, disableDriverRoute,
  updateDriverRouteStatus, updateDriverOrderStatus, updateDriverProfile, uploadDriverDocument,
  getDriverOrderDetail,
} from "../api/driver.api";
import { useDriverData, type UiFeedOrder, type UiDriverData } from "../data/driver";
import { useCities, useDistricts, type UiCity } from "../data/cities";
import type { DriverDocumentType, DriverOrderAction } from "../types/driver";
import {
  createClientOrder, publishClientOrder, listClientOrders, getClientOrder,
  listClientOrderBids, selectDriver, confirmClientOrder, rateClientOrder,
  openClientDispute, cancelClientOrder,
} from "../api/client-orders.api";
import { getSuggestedPrice } from "../api/cities.api";
import { uploadFile } from "../api/files.api";
import { getNotifications, markNotificationRead } from "../api/notifications.api";
import { getMe } from "../api/auth.api";
import { updateClientProfile } from "../api/client-profile.api";
import { normalizeUzPhone } from "../utils/phone";
import { useAsync } from "../data/useApi";
import { cityName as cityNameOf, toNumber as toNum, shortDate as fmtDate } from "../data/format";
import { MapView } from "../components/maps/MapView";
import { RouteMap } from "../components/maps/RouteMap";
import { LocationPicker, type PickedLocation } from "../components/maps/LocationPicker";
import {
  getAdminOverview, getAdminOrders, getAdminDrivers, getAdminClients, getAdminCities,
  getAdminTariffs, getAdminUsers, listAdminDisputes, listAdminAuditLogs, getAdminNotifications,
  mapOrderRow, mapDriverRow, mapClientRow, mapRegionRow, mapTariffRow, mapDisputeRow,
  mapStaffRow, mapAuditRow, mapNotifRow, overviewToMetrics,
} from "../data/admin";
import { approveDriver, rejectDriver, blockDriver, updateDriverVehicle } from "../api/admin-drivers.api";
import { blockAdminClient, unblockAdminClient } from "../api/admin-clients.api";
import { createTariff, activateTariff, deactivateTariff } from "../api/admin-tariffs.api";
import { activateCity, deactivateCity } from "../api/admin-cities.api";
import { createStaffUser, blockStaffUser, unblockStaffUser } from "../api/admin-users.api";
import { manualAssignDriver, manualUpdateOrderStatus, cancelAdminOrder, getAdminOrderBids } from "../api/admin-orders.api";
import { updateDriverCommission, getAdminSystemSettings } from "../api/admin-settings.api";
import { updateAdminMe } from "../api/admin.api";

// ─── Types ────────────────────────────────────────────────────────────────────

type AuthStep  = "splash" | "onboarding" | "role-select" | "phone" | "otp" | "app";
type Role      = "client" | "driver" | "admin";
type AdminSection = "dashboard"|"orders"|"drivers"|"clients"|"regions"|"tariffs"|"disputes"|"staff"|"notifications"|"audit"|"profile";
type ThemeMode = "light" | "dark" | "system";
type Lang      = "uz" | "ru" | "en";

type DriverTab    = "home" | "routes" | "orders" | "profile";
type DriverScreen = DriverTab | "income" | "order-detail" | "documents" | "edit-profile" | "add-route" | "settings" | "notifications";

type ClientTab    = "home" | "orders" | "notifications" | "profile";
type ClientScreen =
  | ClientTab
  | "city-select-from" | "city-select-to"
  | "district-select-from" | "district-select-to"
  | "map-picker-from" | "map-picker-to"
  | "contacts" | "cargo-photo" | "order-review" | "order-success"
  | "c-order-detail" | "bids" | "confirm-delivery" | "rating" | "dispute"
  | "c-settings" | "c-support";

// ─── Translations ─────────────────────────────────────────────────────────────

const T = {
  uz: {
    splashTagline:"Yetkazib berish, oson", onboardingTitle:"Elchi bilan ishlang",
    onboardingDesc:"Shaharlararo yuk tashish",
    onboardingCta:"Boshlash", roleTitle:"Kirish turi", roleDesc:"Hisob turini tanlang",
    roleDriver:"Haydovchiman", roleDriverDesc:"Buyurtmalar qabul qilish",
    roleClient:"Mijozman", roleClientDesc:"Yuk jo'natish",
    phoneTitle:"Telefon raqam", phoneDesc:"Kod yuboriladi",
    phonePlaceholder:"+998 XX XXX XX XX", phoneLabel:"Telefon raqamingiz",
    phoneCta:"Kodni yuborish", phoneError:"Noto'g'ri raqam",
    otpTitle:"Kodni kiriting", otpDesc:"Kod yuborildi",
    otpResend:"Qayta yuborish", otpResendIn:"Qayta yuborish", otpVerify:"Tasdiqlash",
    otpError:"Kod noto'g'ri", back:"Ortga", as:"Sifatida",
    // Client home
    sendParcel:"Yuk jo'natish", chooseExactAddress:"Manzillarni tanlang",
    pickupPoint:"Olib ketish joyi", dropoffPoint:"Yetkazish joyi", changeBtn:"O'zgartirish",
    selectPickup:"Olib ketish joyini tanlang", selectDropoff:"Yetkazish joyini tanlang",
    activeStat:"Faol", bidsStat:"Takliflar", completedStat:"Bajarilgan",
    viewRoute:"Yo'nalishni ko'rish", cityNotSelected:"Shaharni tanlang",
    // City/district
    chooseCity:"Shaharni tanlang", searchCity:"Shahar qidirish...",
    chooseDistrict:"Tumanni tanlang", searchDistrict:"Tuman qidirish...",
    noDistricts:"Tuman topilmadi", noResults:"Natija topilmadi",
    // Map
    confirmLocation:"Manzilni tasdiqlash", manualAddress:"Manzilni kiriting",
    // Contacts
    contactsTitle:"Aloqa ma'lumotlari", senderPhone:"Jo'natuvchi telefoni *",
    receiverPhone:"Qabul qiluvchi telefoni *", pickupAddress:"Olib ketish manzili *",
    dropoffAddress:"Yetkazish manzili *", commentOptional:"Izoh (ixtiyoriy)",
    commentPlaceholder:"Qo'shimcha ma'lumot...", nextBtn:"Davom etish",
    // Cargo
    cargoPhotoTitle:"Yuk rasmi", uploadPhoto:"Rasm yuklash",
    photoDesc:"Rasm yuklang (max 5 MB)", photoUploaded:"Rasm yuklandi",
    changePhoto:"Rasmni o'zgartirish", skipPhoto:"O'tkazib yuborish",
    // Review
    reviewTitle:"Buyurtmani tekshirish", publishOrder:"Buyurtmani e'lon qilish",
    suggestedPrice:"Tavsiya etilgan narx", editOrder:"Tahrirlash",
    yourPrice:"Sizning narxingiz", yourPriceHint:"O'z narxingizni kiriting", priceRangeHint:"Narx oralig'i", priceTooLow:"Narx juda past", priceTooHigh:"Narx juda yuqori",
    openInMaps:"Yo'lni Google Maps'da ochish",
    fromLabel:"Qayerdan", toLabel:"Qayerga",
    // Success
    orderPublished:"Buyurtma e'lon qilindi!", orderPublishedDesc:"Haydovchilar taklif yuboradi",
    viewMyOrder:"Buyurtmani ko'rish", backHome:"Bosh sahifaga",
    // Orders list
    myOrders:"Buyurtmalarim", allOrders:"Barchasi", activeOrders:"Faol",
    completedOrders:"Bajarilgan", cancelledOrders:"Bekor qilingan",
    noOrdersYet:"Buyurtmalar yo'q", noOrdersDesc:"Buyurtma yarating",
    createOrder:"Buyurtma yaratish",
    // Order detail
    orderDetail:"Buyurtma tafsiloti", statusTimeline:"Holat",
    assignedDriver:"Biriktirilgan haydovchi", bidsSection:"Takliflar",
    noBidsYet:"Takliflar yo'q", waitingBids:"Takliflar kutilmoqda…",
    viewBids:"Takliflarni ko'rish", confirmDelivery:"Yetkazishni tasdiqlash",
    cancelOrderBtn:"Buyurtmani bekor qilish", openDisputeBtn:"Shikoyat ochish",
    editOrderBtn:"Buyurtmani tahrirlash",
    // Bids
    driverOffers:"Haydovchi takliflari", selectDriver:"Haydovchini tanlash",
    noBids:"Hali takliflar yo'q",
    confirmDriverTitle:"Haydovchini tasdiqlash", confirmDriverDesc:"Buyurtmani shu haydovchi bajaradi",
    confirmSelectDriver:"Tasdiqlash",
    // Confirm delivery
    confirmDeliveryTitle:"Yetkazishni tasdiqlash", paymentNote:"To'lov turi: Naqd",
    cashNote:"Naqd to'lov", confirmBtn:"Tasdiqlash",
    // Rating
    rateDriverTitle:"Haydovchini baholang", ratingDesc:"Xizmatni baholang",
    yourRating:"Bahoingiz", addComment:"Izoh (ixtiyoriy)",
    submitRating:"Baholashni yuborish", ratingSuccess:"Rahmat!",
    ratingLabels:["","Yomon","Qoniqarli","Yaxshi","Zo'r","A'lo!"],
    // Dispute
    disputeTitle:"Shikoyat ochish", disputeReason:"Sabab *", disputeComment:"Izoh",
    disputeReasonPlaceholder:"Muammoni yozing…", submitDispute:"Yuborish",
    disputeSuccess:"Shikoyat yuborildi!", disputeSuccessDesc:"Tez orada ko'rib chiqiladi",
    disputeErrorEmpty:"Sabab kiriting",
    disputeReasons:"Yuk shikastlangan|Kech yetkazilgan|Haydovchi xulqi|Noto'g'ri manzil|Boshqa",
    // Notifications
    notifications:"Bildirishnomalar", noNotifications:"Bildirishnomalar yo'q",
    noNotifDesc:"Yangilanishlar shu yerda",
    markAllRead:"Barchasi o'qildi",
    // Profile
    clientProfile:"Profil", personalData:"Shaxsiy ma'lumotlar",
    fullNameLabel:"To'liq ism", saveProfile:"Saqlash",
    myOrdersLink:"Mening buyurtmalarim", notificationsLink:"Bildirishnomalar",
    // Shared
    home:"Asosiy", orders:"Buyurtmalar", profile:"Profil",
    goodMorning:"Xayrli tong", goodAfternoon:"Xayrli kun", goodEvening:"Xayrli kech", netIncome:"Sof daromad", activeRoute:"Faol yo'nalish",
    liveLabel:"JONLI", verifiedDriver:"Tasdiqlangan haydovchi", pendingVerification:"Tasdiqlanish kutilmoqda",
    approvedDesc:"Mos buyurtmalar chiqadi",
    notApprovedDesc:"Profil va hujjatlarni to'ldiring",
    completeProfile:"Profilni to'ldirish", uploadDocuments:"Hujjatlarni yuklash",
    availability:"Mavjudlik", visibleToClients:"Mijozlarga ko'rinasiz", currentlyOffline:"Hozir oflayn",
    rating:"Reyting", completed:"Bajarildi", total:"Jami",
    myRoutes:"Mening yo'nalishlarim", addRoute:"Yo'nalish qo'shish",
    noRoutesYet:"Yo'nalishlar yo'q", noRoutesDesc:"Yo'nalish qo'shing",
    addFirstRoute:"Birinchi yo'nalishni qo'shish", fromCity:"Qayerdan (shahar) *",
    toCity:"Qayerga (shahar) *", fromDistrict:"Qayerdan (tuman, ixtiyoriy)",
    toDistrict:"Qayerga (tuman, ixtiyoriy)", selectCity:"Shaharni tanlang",
    saveRoute:"Yo'nalishni saqlash", editRoute:"Yo'nalishni tahrirlash",
    matchingOrders:"Mos buyurtmalar", myHistory:"Mening tarixim",
    sendBid:"Taklif yuborish", bid:"Taklif", gross:"Yalpi", net:"Sof",
    bidChangePrice:"Narxni o'zgartirish", bidChangesLeft:"{n} marta o'zgartirish qoldi", bidNoChangesLeft:"O'zgartirish limiti tugadi",
    otherBids:"Boshqa haydovchilar takliflari", yourBid:"Sizning taklifingiz", bidsCountLabel:"ta taklif", lowestBid:"Eng past", noBidsForOrder:"Hozircha boshqa takliflar yo'q",
    bidSheetTitle:"Taklif yuborish", bidSheetRoute:"Yo'nalish",
    bidSheetSuggestedPrice:"Tavsiya etilgan narx", bidSheetYourPrice:"Sizning narxingiz",
    bidSheetPricePlaceholder:"Narxni kiriting", bidSheetNote:"Izoh (ixtiyoriy)",
    bidSheetNotePlaceholder:"Qo'shimcha ma'lumot...", bidSheetSubmit:"Taklif yuborish",
    bidSheetCancel:"Bekor qilish", bidSheetSuccess:"Taklif yuborildi!",
    bidSheetSuccessDesc:"Mijoz taklifni ko'radi",
    bidSheetErrorEmpty:"Narx kiriting", bidSheetErrorZero:"Narx noldan katta bo'lsin",
    bidSheetNetEst:"Taxminiy sof daromad", bidSheetCommissionNote:"Komissiya (10%)",
    statusProgress:"Holat jarayoni", contactDetails:"Aloqa ma'lumotlari",
    sender:"Jo'natuvchi", receiver:"Qabul qiluvchi", comment:"Izoh",
    incomeReport:"Daromad hisoboti", grossAmount:"Yalpi miqdor",
    systemFee:"Komissiya (10%)", viewOnMap:"Xaritada ko'rish",
    markDelivered:"Yetkazildi",
    accepted:"Qabul qilindi", pickedUp:"Olib ketildi", inTransit:"Yo'lda", delivered:"Yetkazildi",
    income:"Daromad", afterCommission:"Komissiyadan keyin",
    commission:"Komissiya", earningsChart:"Daromad grafigi", sevenDays:"7 kun",
    sixMonths:"6 oy", recentEarnings:"So'nggi daromadlar",
    youAreOnline:"Siz onlinesiz", youAreOffline:"Siz oflayn holatdasiz",
    vehicle:"Transport vositasi", editProfile:"Profilni tahrirlash",
    documents:"Hujjatlar", settings:"Sozlamalar", logOut:"Chiqish",
    fullName:"To'liq ism", carModel:"Avtomobil modeli", carColor:"Avtomobil rangi",
    plateNumber:"Davlat raqami", saveChanges:"O'zgarishlarni saqlash",
    vehicleLockedNote:"Avtomobil ma'lumotlari qulflangan. O'zgartirish uchun operatorga murojaat qiling.",
    menu:"Menyu", client:"Mijoz", support:"Qo'llab-quvvatlash", myLocation:"Mening joylashuvim",
    whereFrom:"Qayerdan?", whereTo:"Qayerga?",
    helpTitle:"Yordam", helpContactTitle:"Qo'llab-quvvatlash markazi", helpHours:"Har kuni 09:00 – 21:00",
    helpCallBtn:"Qo'ng'iroq", helpFaqTitle:"Savollar",
    faq1q:"Buyurtma qanday yarataman?", faq1a:"Manzillarni tanlang va 'Yo'nalishni ko'rish'ni bosing.",
    faq2q:"Narx qanday belgilanadi?", faq2a:"Haydovchilar taklif yuboradi, siz mosini tanlaysiz.",
    faq3q:"Buyurtmani bekor qilsam bo'ladimi?", faq3a:"Ha, haydovchi tayinlanmaguncha bekor qilinadi.",
    uploadAllDocs:"Barcha hujjatlarni yuklang",
    viewFile:"Faylni ko'rish", replace:"Almashtirish", upload:"Yuklash",
    appearance:"Ko'rinish", theme:"Mavzu", themeDesc:"Ko'rinishni tanlang",
    lightTheme:"Yorug'", darkTheme:"Qorong'u", systemTheme:"Sistema",
    alwaysLight:"Doim yorug'", alwaysDark:"Doim qorong'u", followsDevice:"Qurilmaga bog'liq",
    language:"Til", appLanguage:"Ilova tili", notifications2:"Bildirishnomalar",
    orderUpdates:"Buyurtma yangilanishlari", orderUpdatesDesc:"Holat o'zgarishlari",
    bidAlerts:"Taklif ogohlantirishlari", bidAlertsDesc:"Yangi takliflar",
    promotions:"Aktsiyalar", promotionsDesc:"Yangiliklar va takliflar",
    vibration:"Tebranish", vibrationDesc:"Ogohlantirishda tebranish",
    account:"Hisob", privacySecurity:"Maxfiylik va xavfsizlik",
    termsOfService:"Foydalanish shartlari", aboutElchi:"Elchi haqida",
    version:"Elchi · v2.4.1 · Versiya 2026.06",
    statusPublished:"E'lon qilingan", statusBidding:"Takliflar bor",
    statusAccepted:"Qabul qilindi", statusInTransit:"Yo'lda",
    statusDelivered:"Yetkazildi", statusConfirmed:"Tasdiqlandi",
    statusCancelled:"Bekor qilindi", statusActive:"Faol",
    statusInactive:"Faol emas", statusApproved:"Tasdiqlangan",
    statusPending:"Kutilmoqda", statusMissing:"Yuklanmagan", statusNew:"Yangi", statusDraft:"Qoralama",
    // ── Admin panel ──
    admDashboard:"Boshqaruv paneli", admOrders:"Buyurtmalar", admDrivers:"Haydovchilar",
    admClients:"Mijozlar", admRegions:"Hududlar", admTariffs:"Tariflar",
    admDisputes:"Nizolar", admStaff:"Xodimlar", admNotifications:"Bildirishnomalar",
    admAuditLog:"Audit jurnali", admProfile:"Profil",
    admRefresh:"Yangilash", admLogout:"Chiqish", admCollapse:"Yig'ish",
    admBrandSubtitle:"Super admin", admSuperAdmin:"Super admin",
    admLoginHeading:"Boshqaruv paneli", admLoginDesc:"Davom etish uchun raqamingizni kiriting",
    admPanelBlurb:"Buyurtmalar, haydovchilar va tariflarni bir joydan boshqaring", admOtpSentTo:"Kod yuborildi:",
    // Dashboard
    admFinancialOverview:"Moliyaviy ko'rsatkichlar", admOperations:"Operatsiyalar",
    admTotalRevenue:"Umumiy daromad", admPlatformProfit:"Platforma foydasi",
    admDriverEarnings:"Haydovchilar daromadi", admAvgOrderValue:"O'rtacha buyurtma qiymati",
    admToday:"Bugun", admTotalOrders:"Jami buyurtmalar", admActiveDeliveries:"Faol yetkazishlar",
    admPendingDrivers:"Kutilayotgan haydovchilar", admOpenDisputes:"Ochiq nizolar",
    admPublishedBidding:"E'lon qilingan/Takliflar", admApprovedDrivers:"Tasdiqlangan haydovchilar",
    admActiveTariffs:"Faol tariflar", admMissingTariffs:"Yetishmayotgan tariflar",
    admRecentOrders:"So'nggi buyurtmalar", admViewAll:"Barchasini ko'rish",
    admVerificationQueue:"Tasdiqlash navbati", admRecentActivity:"So'nggi faoliyat",
    admViewLog:"Jurnalni ko'rish", admDocsShort:"hujjat",
    // Table headers / common
    admOrder:"Buyurtma", admRoute:"Yo'nalish", admClient:"Mijoz", admStatus:"Holat",
    admPrice:"Narx", admActor:"Bajaruvchi", admRole:"Rol", admAction:"Amal",
    admEntity:"Obyekt", admTime:"Vaqt", admDriver:"Haydovchi", admPayment:"To'lov",
    admDate:"Sana", admActions:"Amallar", admPhone:"Telefon", admVehicle:"Transport",
    admAvailable:"Mavjud", admDocs:"Hujjatlar", admRoutes:"Yo'nalishlar",
    admJoined:"Qo'shildi", admVerified:"Tasdiqlangan", admLastOrder:"So'nggi buyurtma",
    admName:"Ism", admType:"Turi", admDistricts:"Tumanlar", admReqDistrict:"Tuman majburiy",
    admActive:"Faol", admId:"ID", admUzbek:"O'zbekcha", admRussian:"Ruscha",
    admSuggested:"Tavsiya etilgan", admMin:"Min", admMax:"Maks", admCurrency:"Valyuta",
    admCreated:"Yaratilgan", admReason:"Sabab", admOpenedBy:"Kim ochgan",
    admRecipient:"Qabul qiluvchi", admTitle:"Sarlavha", admMessage:"Xabar",
    admChannel:"Kanal", admRead:"O'qilgan", admLastLogin:"So'nggi kirish", admEntityId:"Obyekt ID",
    // Search placeholders
    admSearchOrders:"Buyurtma, mijoz, haydovchi izlash...",
    admSearchDrivers:"Ism, telefon, raqam izlash...",
    admSearchClients:"Ism yoki telefon bo'yicha izlash...",
    admSearchRegions:"Nom bo'yicha izlash...", admSearchTariffs:"Yo'nalish, shahar izlash...",
    admSearchAudit:"Bajaruvchi yoki amalni izlash...",
    // Tabs / statuses
    admTabAll:"Barchasi", admTabPublished:"E'lon qilingan", admTabBidding:"Takliflar",
    admTabAccepted:"Qabul qilingan", admTabInTransit:"Yo'lda", admTabDelivered:"Yetkazildi",
    admTabConfirmed:"Tasdiqlangan", admTabCancelled:"Bekor qilingan", admTabDisputed:"Nizoli",
    admTabNew:"Yangi", admTabPending:"Kutilmoqda", admTabApproved:"Tasdiqlangan",
    admTabRejected:"Rad etilgan", admTabBlocked:"Bloklangan",
    // Orders
    admAwaitingBids:"Takliflar kutilmoqda", admDisputed:"Nizoli",
    admOverview:"Umumiy", admBids:"Takliflar", admHistory:"Tarix",
    admFrom:"Qayerdan", admTo:"Qayerga", admSuggestedPrice:"Tavsiya etilgan narx",
    admView:"Ko'rish", admSelected:"Tanlangan", admNoBids:"Hali takliflar yo'q",
    admAssignDriver:"Haydovchi biriktirish", admChangeStatus:"Holatni o'zgartirish",
    admCancelOrder:"Buyurtmani bekor qilish", admDriverId:"Haydovchi ID",
    admFinalPrice:"Yakuniy narx", admReasonRequired:"Sabab *",
    admAssignReasonPh:"Biriktirish sababi...", admStatusReasonPh:"Holat o'zgarishi sababi...",
    admCancelReasonPh:"Bekor qilish sababi...", admNewStatus:"Yangi holat",
    admSelectStatus:"Holatni tanlang...", admUpdateStatus:"Holatni yangilash",
    admCancelOrderWarn:"Bu amalni ortga qaytarib bo'lmaydi. Buyurtma bekor qilinadi.",
    admOrderPrefix:"Buyurtma", admDrawerAssignDriver:"Haydovchi biriktirish",
    // Drivers
    admTotalDrivers:"Jami haydovchilar", admPendingReview:"Ko'rib chiqilmoqda",
    admApproved:"Tasdiqlangan", admAvailableNow:"Hozir mavjud",
    admOnline:"Onlayn", admOffline:"Oflayn", admApprove:"Tasdiqlash",
    admReject:"Rad etish", admBlock:"Bloklash", admApproveDriver:"Haydovchini tasdiqlash",
    admRejectDriver:"Haydovchini rad etish", admBlockDriver:"Haydovchini bloklash",
    admApproveDriverQ:"Ushbu haydovchi platformada ishlashi tasdiqlansinmi?",
    admRejectBlockWarn:"Bu ularning ishlashiga to'sqinlik qiladi.",
    admReasonIncompleteDocs:"Hujjatlar to'liq emas", admReasonFalsifiedDocs:"Soxta hujjatlar",
    admReasonPolicyViolation:"Qoidabuzarlik", admReasonOther:"Boshqa",
    admEditVehicleDetails:"Transport ma'lumotlarini tahrirlash",
    admEditVehicleDesc:"Ism va transport ma'lumotlarini yangilang.",
    admFullName:"To'liq ism", admCarModel:"Avtomobil modeli",
    admCarColor:"Avtomobil rangi", admPlateNumber:"Davlat raqami",
    admModel:"Model", admColor:"Rang", admPlate:"Raqam",
    admDocPassport:"Pasport", admDocSelfie:"Selfi", admDocLicense:"Haydovchilik guvohnomasi",
    admDocCarDoc:"Avtomobil hujjati", admDocCarPhoto:"Avtomobil rasmi",
    admUploaded:"Yuklangan", admMissing:"Yuklanmagan",
    admRating:"Reyting", admCompleted:"Bajarilgan",
    // Clients
    admTotalClients:"Jami mijozlar", admBlocked:"Bloklangan", admWithOrders:"Buyurtmalar bilan",
    admBlockClient:"Mijozni bloklash", admUnblock:"Blokdan chiqarish",
    // Regions
    admTotalRegions:"Jami hududlar", admWithDistricts:"Tumanlar bilan",
    admInactive:"Faol emas", admAddRegion:"Hudud qo'shish",
    admDeactivate:"Faolsizlantirish", admActivate:"Faollashtirish",
    // Tariffs
    admTotalTariffs:"Jami tariflar", admAvgPrice:"O'rtacha narx",
    admAddTariff:"Tarif qo'shish", admSaveTariff:"Tarifni saqlash",
    admFromCity:"Qayerdan (shahar)", admToCity:"Qayerga (shahar)",
    admSelectPh:"Tanlang...", admMinPrice:"Minimal narx", admMaxPrice:"Maksimal narx",
    // Disputes
    admTotalDisputes:"Jami nizolar", admOpen:"Ochiq", admResolved:"Hal qilingan",
    admDisputePrefix:"Nizo", admResolution:"Yechim", admUpdateStatusLbl:"Holatni yangilash",
    admResolutionNotePh:"Yechim izohi...", admUpdateDispute:"Nizoni yangilash", admReview:"Ko'rib chiqish",
    // Staff
    admTotalStaff:"Jami xodimlar", admAdmins:"Adminlar", admOperators:"Operatorlar",
    admCreateStaff:"Xodim yaratish", admCreateUser:"Foydalanuvchi yaratish",
    admRoleLbl:"Rol", admOperator:"Operator", admAdmin:"Admin",
    // Notifications
    admTotal:"Jami", admUnread:"O'qilmagan", admSystem:"Tizim",
    // Audit
    admReadOnlyAudit:"Faqat o'qish uchun audit jurnali",
    // Profile
    admPhoneVerified:"Telefon tasdiqlangan", admYes:"Ha",
    admAccountCreated:"Hisob yaratilgan", admSave:"Saqlash", admSaved:"Saqlandi",
    admRefreshProfile:"Profilni yangilash", admPlatformCommission:"Platforma komissiyasi",
    admCommissionDesc:"Haydovchi daromadidan chegirma darajasi",
    admCommissionPct:"Komissiya %", admCommissionWarn:"⚠ O'zgarishlar faqat kelgusi qabul qilingan buyurtmalarga tegishli. Mavjud buyurtmalar o'z komissiyasini saqlaydi.",
  },
  ru: {
    splashTagline:"Доставка, просто", onboardingTitle:"Работайте с Elchi",
    onboardingDesc:"Межгородские грузоперевозки",
    onboardingCta:"Начать", roleTitle:"Тип входа", roleDesc:"Выберите тип аккаунта",
    roleDriver:"Я водитель", roleDriverDesc:"Принимать заказы",
    roleClient:"Я клиент", roleClientDesc:"Отправить груз",
    phoneTitle:"Номер телефона", phoneDesc:"Придёт код",
    phonePlaceholder:"+998 XX XXX XX XX", phoneLabel:"Ваш номер телефона",
    phoneCta:"Отправить код", phoneError:"Неверный номер",
    otpTitle:"Введите код", otpDesc:"Код отправлен",
    otpResend:"Отправить снова", otpResendIn:"Отправить снова", otpVerify:"Подтвердить",
    otpError:"Неверный код", back:"Назад", as:"Как",
    sendParcel:"Отправить груз", chooseExactAddress:"Выберите адреса",
    pickupPoint:"Место получения", dropoffPoint:"Место доставки", changeBtn:"Изменить",
    selectPickup:"Выберите место получения", selectDropoff:"Выберите место доставки",
    activeStat:"Активные", bidsStat:"Предложения", completedStat:"Выполнено",
    viewRoute:"Посмотреть маршрут", cityNotSelected:"Выберите город",
    chooseCity:"Выберите город", searchCity:"Поиск города...",
    chooseDistrict:"Выберите район", searchDistrict:"Поиск района...",
    noDistricts:"Районы не найдены", noResults:"Ничего не найдено",
    confirmLocation:"Подтвердить адрес", manualAddress:"Введите адрес",
    contactsTitle:"Контактные данные", senderPhone:"Телефон отправителя *",
    receiverPhone:"Телефон получателя *", pickupAddress:"Адрес получения *",
    dropoffAddress:"Адрес доставки *", commentOptional:"Комментарий (необязательно)",
    commentPlaceholder:"Дополнительная информация...", nextBtn:"Продолжить",
    cargoPhotoTitle:"Фото груза", uploadPhoto:"Загрузить фото",
    photoDesc:"Загрузите фото (макс. 5 МБ)", photoUploaded:"Фото загружено",
    changePhoto:"Изменить фото", skipPhoto:"Пропустить",
    reviewTitle:"Проверка заказа", publishOrder:"Опубликовать заказ",
    suggestedPrice:"Рекомендуемая цена", editOrder:"Редактировать",
    yourPrice:"Ваша цена", yourPriceHint:"Укажите свою цену", priceRangeHint:"Диапазон цены", priceTooLow:"Цена слишком низкая", priceTooHigh:"Цена слишком высокая",
    openInMaps:"Открыть маршрут в Google Maps",
    fromLabel:"Откуда", toLabel:"Куда",
    orderPublished:"Заказ опубликован!", orderPublishedDesc:"Водители пришлют предложения",
    viewMyOrder:"Мой заказ", backHome:"На главную",
    myOrders:"Мои заказы", allOrders:"Все", activeOrders:"Активные",
    completedOrders:"Выполненные", cancelledOrders:"Отменённые",
    noOrdersYet:"Заказов нет", noOrdersDesc:"Создайте заказ", createOrder:"Создать заказ",
    orderDetail:"Детали заказа", statusTimeline:"Статус",
    assignedDriver:"Назначенный водитель", bidsSection:"Предложения",
    noBidsYet:"Предложений нет", waitingBids:"Ожидание предложений…",
    viewBids:"Посмотреть предложения", confirmDelivery:"Подтвердить доставку",
    cancelOrderBtn:"Отменить заказ", openDisputeBtn:"Открыть спор", editOrderBtn:"Редактировать",
    driverOffers:"Предложения водителей", selectDriver:"Выбрать водителя",
    noBids:"Предложений нет",
    confirmDriverTitle:"Подтвердить водителя", confirmDriverDesc:"Заказ выполнит этот водитель",
    confirmSelectDriver:"Подтвердить",
    confirmDeliveryTitle:"Подтвердить доставку", paymentNote:"Способ оплаты: Наличные",
    cashNote:"Оплата наличными", confirmBtn:"Подтвердить",
    rateDriverTitle:"Оцените водителя", ratingDesc:"Оцените сервис",
    yourRating:"Ваша оценка", addComment:"Комментарий (необязательно)",
    submitRating:"Отправить оценку", ratingSuccess:"Спасибо!",
    ratingLabels:["","Плохо","Удовлетворительно","Хорошо","Отлично","Превосходно!"],
    disputeTitle:"Открыть спор", disputeReason:"Причина *", disputeComment:"Комментарий",
    disputeReasonPlaceholder:"Опишите проблему…", submitDispute:"Отправить",
    disputeSuccess:"Жалоба отправлена!", disputeSuccessDesc:"Скоро рассмотрим",
    disputeErrorEmpty:"Укажите причину",
    disputeReasons:"Груз повреждён|Задержка доставки|Поведение водителя|Неверный адрес|Другое",
    notifications:"Уведомления", noNotifications:"Уведомлений нет",
    noNotifDesc:"Обновления появятся здесь",
    markAllRead:"Прочитать все",
    clientProfile:"Профиль", personalData:"Личные данные",
    fullNameLabel:"Полное имя", saveProfile:"Сохранить",
    myOrdersLink:"Мои заказы", notificationsLink:"Уведомления",
    home:"Главная", orders:"Заказы", profile:"Профиль",
    goodMorning:"Доброе утро", goodAfternoon:"Добрый день", goodEvening:"Добрый вечер", netIncome:"Чистый доход", activeRoute:"Активный маршрут",
    liveLabel:"ПРЯМОЙ", verifiedDriver:"Подтверждённый водитель", pendingVerification:"Ожидает подтверждения",
    approvedDesc:"Появятся подходящие заказы",
    notApprovedDesc:"Заполните профиль и документы",
    completeProfile:"Заполнить профиль", uploadDocuments:"Загрузить документы",
    availability:"Доступность", visibleToClients:"Вы видны клиентам", currentlyOffline:"Вы сейчас офлайн",
    rating:"Рейтинг", completed:"Выполнено", total:"Всего",
    myRoutes:"Мои маршруты", addRoute:"Добавить маршрут",
    noRoutesYet:"Маршрутов нет", noRoutesDesc:"Добавьте маршрут",
    addFirstRoute:"Добавить первый маршрут", fromCity:"Откуда (город) *",
    toCity:"Куда (город) *", fromDistrict:"Откуда (район, необязательно)",
    toDistrict:"Куда (район, необязательно)", selectCity:"Выберите город",
    saveRoute:"Сохранить маршрут", editRoute:"Редактировать маршрут",
    matchingOrders:"Подходящие заказы", myHistory:"Моя история",
    sendBid:"Отправить предложение", bid:"Предложение", gross:"Валовый", net:"Чистый",
    bidChangePrice:"Изменить цену", bidChangesLeft:"Осталось изменений: {n}", bidNoChangesLeft:"Лимит изменений исчерпан",
    otherBids:"Предложения других водителей", yourBid:"Ваше предложение", bidsCountLabel:"предл.", lowestBid:"Мин.", noBidsForOrder:"Пока других предложений нет",
    bidSheetTitle:"Отправить предложение", bidSheetRoute:"Маршрут",
    bidSheetSuggestedPrice:"Рекомендуемая цена", bidSheetYourPrice:"Ваша цена",
    bidSheetPricePlaceholder:"Введите цену", bidSheetNote:"Комментарий (необязательно)",
    bidSheetNotePlaceholder:"Дополнительная информация...", bidSheetSubmit:"Отправить предложение",
    bidSheetCancel:"Отмена", bidSheetSuccess:"Предложение отправлено!",
    bidSheetSuccessDesc:"Клиент увидит предложение",
    bidSheetErrorEmpty:"Введите цену", bidSheetErrorZero:"Цена больше нуля",
    bidSheetNetEst:"Примерный чистый доход", bidSheetCommissionNote:"Комиссия (10%)",
    statusProgress:"Статус выполнения", contactDetails:"Контактные данные",
    sender:"Отправитель", receiver:"Получатель", comment:"Комментарий",
    incomeReport:"Отчёт о доходах", grossAmount:"Валовая сумма",
    systemFee:"Комиссия (10%)", viewOnMap:"Смотреть на карте",
    markDelivered:"Доставлено",
    accepted:"Принято", pickedUp:"Забрано", inTransit:"В пути", delivered:"Доставлено",
    income:"Доходы", afterCommission:"После комиссии",
    commission:"Комиссия", earningsChart:"График доходов", sevenDays:"7 дней",
    sixMonths:"6 месяцев", recentEarnings:"Последние доходы",
    youAreOnline:"Вы онлайн", youAreOffline:"Вы офлайн",
    vehicle:"Транспортное средство", editProfile:"Редактировать профиль",
    documents:"Документы", settings:"Настройки", logOut:"Выйти",
    fullName:"Полное имя", carModel:"Модель автомобиля", carColor:"Цвет автомобиля",
    plateNumber:"Гос. номер", saveChanges:"Сохранить изменения",
    vehicleLockedNote:"Данные авто заблокированы. Обратитесь к оператору.",
    menu:"Меню", client:"Клиент", support:"Поддержка", myLocation:"Моё местоположение",
    whereFrom:"Откуда?", whereTo:"Куда?",
    helpTitle:"Помощь", helpContactTitle:"Центр поддержки", helpHours:"Ежедневно 09:00 – 21:00",
    helpCallBtn:"Позвонить", helpFaqTitle:"Вопросы",
    faq1q:"Как создать заказ?", faq1a:"Выберите адреса и нажмите «Посмотреть маршрут».",
    faq2q:"Как определяется цена?", faq2a:"Водители присылают предложения, вы выбираете подходящее.",
    faq3q:"Можно ли отменить заказ?", faq3a:"Да, пока не назначен водитель.",
    uploadAllDocs:"Загрузите все документы",
    viewFile:"Просмотреть файл", replace:"Заменить", upload:"Загрузить",
    appearance:"Внешний вид", theme:"Тема", themeDesc:"Выберите вид",
    lightTheme:"Светлая", darkTheme:"Тёмная", systemTheme:"Системная",
    alwaysLight:"Всегда светлая", alwaysDark:"Всегда тёмная", followsDevice:"По устройству",
    language:"Язык", appLanguage:"Язык приложения", notifications2:"Уведомления",
    orderUpdates:"Обновления заказов", orderUpdatesDesc:"Изменения статуса",
    bidAlerts:"Уведомления о предложениях", bidAlertsDesc:"Новые предложения",
    promotions:"Акции", promotionsDesc:"Новости и предложения",
    vibration:"Вибрация", vibrationDesc:"Вибрация уведомлений",
    account:"Аккаунт", privacySecurity:"Конфиденциальность и безопасность",
    termsOfService:"Условия использования", aboutElchi:"О Elchi",
    version:"Elchi · v2.4.1 · Сборка 2026.06",
    statusPublished:"Опубликовано", statusBidding:"Есть предложения",
    statusAccepted:"Принято", statusInTransit:"В пути",
    statusDelivered:"Доставлено", statusConfirmed:"Подтверждено",
    statusCancelled:"Отменено", statusActive:"Активен",
    statusInactive:"Неактивен", statusApproved:"Подтверждён",
    statusPending:"На проверке", statusMissing:"Не загружено", statusNew:"Новый", statusDraft:"Черновик",
    // ── Admin panel ──
    admDashboard:"Панель управления", admOrders:"Заказы", admDrivers:"Водители",
    admClients:"Клиенты", admRegions:"Регионы", admTariffs:"Тарифы",
    admDisputes:"Споры", admStaff:"Персонал", admNotifications:"Уведомления",
    admAuditLog:"Журнал аудита", admProfile:"Профиль",
    admRefresh:"Обновить", admLogout:"Выход", admCollapse:"Свернуть",
    admBrandSubtitle:"Супер-админ", admSuperAdmin:"Супер-админ",
    admLoginHeading:"Панель управления", admLoginDesc:"Введите номер для входа",
    admPanelBlurb:"Управляйте заказами, водителями и тарифами в одном месте", admOtpSentTo:"Код отправлен:",
    // Dashboard
    admFinancialOverview:"Финансовый обзор", admOperations:"Операции",
    admTotalRevenue:"Общая выручка", admPlatformProfit:"Прибыль платформы",
    admDriverEarnings:"Доход водителей", admAvgOrderValue:"Средняя стоимость заказа",
    admToday:"Сегодня", admTotalOrders:"Всего заказов", admActiveDeliveries:"Активные доставки",
    admPendingDrivers:"Водители на проверке", admOpenDisputes:"Открытые споры",
    admPublishedBidding:"Опубликовано/Торги", admApprovedDrivers:"Одобренные водители",
    admActiveTariffs:"Активные тарифы", admMissingTariffs:"Отсутствующие тарифы",
    admRecentOrders:"Последние заказы", admViewAll:"Показать все",
    admVerificationQueue:"Очередь проверки", admRecentActivity:"Последняя активность",
    admViewLog:"Смотреть журнал", admDocsShort:"док.",
    // Table headers / common
    admOrder:"Заказ", admRoute:"Маршрут", admClient:"Клиент", admStatus:"Статус",
    admPrice:"Цена", admActor:"Исполнитель", admRole:"Роль", admAction:"Действие",
    admEntity:"Объект", admTime:"Время", admDriver:"Водитель", admPayment:"Оплата",
    admDate:"Дата", admActions:"Действия", admPhone:"Телефон", admVehicle:"Транспорт",
    admAvailable:"Доступен", admDocs:"Документы", admRoutes:"Маршруты",
    admJoined:"Добавлен", admVerified:"Подтверждён", admLastOrder:"Последний заказ",
    admName:"Имя", admType:"Тип", admDistricts:"Районы", admReqDistrict:"Район обязателен",
    admActive:"Активен", admId:"ID", admUzbek:"Узбекский", admRussian:"Русский",
    admSuggested:"Рекомендуемая", admMin:"Мин", admMax:"Макс", admCurrency:"Валюта",
    admCreated:"Создан", admReason:"Причина", admOpenedBy:"Кем открыт",
    admRecipient:"Получатель", admTitle:"Заголовок", admMessage:"Сообщение",
    admChannel:"Канал", admRead:"Прочитано", admLastLogin:"Последний вход", admEntityId:"ID объекта",
    // Search placeholders
    admSearchOrders:"Поиск заказа, клиента, водителя...",
    admSearchDrivers:"Поиск по имени, телефону, номеру...",
    admSearchClients:"Поиск по имени или телефону...",
    admSearchRegions:"Поиск по названию...", admSearchTariffs:"Поиск маршрута, города...",
    admSearchAudit:"Поиск исполнителя или действия...",
    // Tabs / statuses
    admTabAll:"Все", admTabPublished:"Опубликовано", admTabBidding:"Торги",
    admTabAccepted:"Принято", admTabInTransit:"В пути", admTabDelivered:"Доставлено",
    admTabConfirmed:"Подтверждено", admTabCancelled:"Отменено", admTabDisputed:"Спорные",
    admTabNew:"Новые", admTabPending:"На проверке", admTabApproved:"Одобренные",
    admTabRejected:"Отклонённые", admTabBlocked:"Заблокированные",
    // Orders
    admAwaitingBids:"Ожидают предложений", admDisputed:"Спорные",
    admOverview:"Обзор", admBids:"Предложения", admHistory:"История",
    admFrom:"Откуда", admTo:"Куда", admSuggestedPrice:"Рекомендуемая цена",
    admView:"Просмотр", admSelected:"Выбран", admNoBids:"Предложений пока нет",
    admAssignDriver:"Назначить водителя", admChangeStatus:"Изменить статус",
    admCancelOrder:"Отменить заказ", admDriverId:"ID водителя",
    admFinalPrice:"Итоговая цена", admReasonRequired:"Причина *",
    admAssignReasonPh:"Причина назначения...", admStatusReasonPh:"Причина изменения статуса...",
    admCancelReasonPh:"Причина отмены...", admNewStatus:"Новый статус",
    admSelectStatus:"Выберите статус...", admUpdateStatus:"Обновить статус",
    admCancelOrderWarn:"Это действие необратимо. Заказ будет отменён.",
    admOrderPrefix:"Заказ", admDrawerAssignDriver:"Назначить водителя",
    // Drivers
    admTotalDrivers:"Всего водителей", admPendingReview:"На проверке",
    admApproved:"Одобрено", admAvailableNow:"Доступны сейчас",
    admOnline:"Онлайн", admOffline:"Офлайн", admApprove:"Одобрить",
    admReject:"Отклонить", admBlock:"Заблокировать", admApproveDriver:"Одобрить водителя",
    admRejectDriver:"Отклонить водителя", admBlockDriver:"Заблокировать водителя",
    admApproveDriverQ:"Одобрить этого водителя для работы на платформе?",
    admRejectBlockWarn:"Это не позволит им работать.",
    admReasonIncompleteDocs:"Неполные документы", admReasonFalsifiedDocs:"Поддельные документы",
    admReasonPolicyViolation:"Нарушение правил", admReasonOther:"Другое",
    admEditVehicleDetails:"Редактировать данные транспорта",
    admEditVehicleDesc:"Обновите имя и данные транспорта.",
    admFullName:"Полное имя", admCarModel:"Модель автомобиля",
    admCarColor:"Цвет автомобиля", admPlateNumber:"Гос. номер",
    admModel:"Модель", admColor:"Цвет", admPlate:"Номер",
    admDocPassport:"Паспорт", admDocSelfie:"Селфи", admDocLicense:"Водительское удостоверение",
    admDocCarDoc:"Документ на авто", admDocCarPhoto:"Фото авто",
    admUploaded:"Загружено", admMissing:"Отсутствует",
    admRating:"Рейтинг", admCompleted:"Выполнено",
    // Clients
    admTotalClients:"Всего клиентов", admBlocked:"Заблокировано", admWithOrders:"С заказами",
    admBlockClient:"Заблокировать клиента", admUnblock:"Разблокировать",
    // Regions
    admTotalRegions:"Всего регионов", admWithDistricts:"С районами",
    admInactive:"Неактивные", admAddRegion:"Добавить регион",
    admDeactivate:"Деактивировать", admActivate:"Активировать",
    // Tariffs
    admTotalTariffs:"Всего тарифов", admAvgPrice:"Средняя цена",
    admAddTariff:"Добавить тариф", admSaveTariff:"Сохранить тариф",
    admFromCity:"Откуда (город)", admToCity:"Куда (город)",
    admSelectPh:"Выберите...", admMinPrice:"Мин. цена", admMaxPrice:"Макс. цена",
    // Disputes
    admTotalDisputes:"Всего споров", admOpen:"Открытые", admResolved:"Решённые",
    admDisputePrefix:"Спор", admResolution:"Решение", admUpdateStatusLbl:"Обновить статус",
    admResolutionNotePh:"Заметка о решении...", admUpdateDispute:"Обновить спор", admReview:"Рассмотреть",
    // Staff
    admTotalStaff:"Всего персонала", admAdmins:"Администраторы", admOperators:"Операторы",
    admCreateStaff:"Создать сотрудника", admCreateUser:"Создать пользователя",
    admRoleLbl:"Роль", admOperator:"Оператор", admAdmin:"Администратор",
    // Notifications
    admTotal:"Всего", admUnread:"Непрочитанные", admSystem:"Системные",
    // Audit
    admReadOnlyAudit:"Журнал аудита только для чтения",
    // Profile
    admPhoneVerified:"Телефон подтверждён", admYes:"Да",
    admAccountCreated:"Аккаунт создан", admSave:"Сохранить", admSaved:"Сохранено",
    admRefreshProfile:"Обновить профиль", admPlatformCommission:"Комиссия платформы",
    admCommissionDesc:"Ставка удержания из дохода водителя",
    admCommissionPct:"Комиссия %", admCommissionWarn:"⚠ Изменения применяются только к будущим принятым заказам. Существующие заказы сохраняют исходную комиссию.",
  },
  en: {
    splashTagline:"Delivery, made easy", onboardingTitle:"Work with Elchi",
    onboardingDesc:"Intercity parcel delivery",
    onboardingCta:"Get Started", roleTitle:"Sign In As", roleDesc:"Choose your account type",
    roleDriver:"I'm a Driver", roleDriverDesc:"Accept delivery orders",
    roleClient:"I'm a Client", roleClientDesc:"Send a parcel",
    phoneTitle:"Phone Number", phoneDesc:"We'll send a code",
    phonePlaceholder:"+998 XX XXX XX XX", phoneLabel:"Your phone number",
    phoneCta:"Send Code", phoneError:"Invalid phone number",
    otpTitle:"Enter Code", otpDesc:"Code sent",
    otpResend:"Resend code", otpResendIn:"Resend in", otpVerify:"Verify",
    otpError:"Invalid code", back:"Back", as:"as",
    sendParcel:"Send Parcel", chooseExactAddress:"Choose addresses",
    pickupPoint:"Pickup Point", dropoffPoint:"Dropoff Point", changeBtn:"Change",
    selectPickup:"Select pickup location", selectDropoff:"Select dropoff location",
    activeStat:"Active", bidsStat:"Bids", completedStat:"Completed",
    viewRoute:"View Route", cityNotSelected:"Select a city",
    chooseCity:"Choose City", searchCity:"Search city...",
    chooseDistrict:"Choose District", searchDistrict:"Search district...",
    noDistricts:"No districts found", noResults:"No results found",
    confirmLocation:"Confirm Location", manualAddress:"Enter address manually",
    contactsTitle:"Contact Details", senderPhone:"Sender phone *",
    receiverPhone:"Receiver phone *", pickupAddress:"Pickup address *",
    dropoffAddress:"Dropoff address *", commentOptional:"Comment (optional)",
    commentPlaceholder:"Additional info...", nextBtn:"Continue",
    cargoPhotoTitle:"Cargo Photo", uploadPhoto:"Upload Photo",
    photoDesc:"Upload a photo (max 5 MB)", photoUploaded:"Photo uploaded",
    changePhoto:"Change photo", skipPhoto:"Skip",
    reviewTitle:"Review Order", publishOrder:"Publish Order",
    suggestedPrice:"Suggested Price", editOrder:"Edit",
    yourPrice:"Your price", yourPriceHint:"Enter your price", priceRangeHint:"Price range", priceTooLow:"Price is too low", priceTooHigh:"Price is too high",
    openInMaps:"Open route in Google Maps",
    fromLabel:"From", toLabel:"To",
    orderPublished:"Order Published!", orderPublishedDesc:"Drivers will send offers",
    viewMyOrder:"View My Order", backHome:"Back to Home",
    myOrders:"My Orders", allOrders:"All", activeOrders:"Active",
    completedOrders:"Completed", cancelledOrders:"Cancelled",
    noOrdersYet:"No orders yet", noOrdersDesc:"Create an order", createOrder:"Create Order",
    orderDetail:"Order Detail", statusTimeline:"Status",
    assignedDriver:"Assigned Driver", bidsSection:"Bids",
    noBidsYet:"No bids yet", waitingBids:"Waiting for bids…",
    viewBids:"View Bids", confirmDelivery:"Confirm Delivery",
    cancelOrderBtn:"Cancel Order", openDisputeBtn:"Open Dispute", editOrderBtn:"Edit Order",
    driverOffers:"Driver Offers", selectDriver:"Select Driver",
    noBids:"No bids yet",
    confirmDriverTitle:"Confirm Driver", confirmDriverDesc:"This driver will handle it",
    confirmSelectDriver:"Confirm",
    confirmDeliveryTitle:"Confirm Delivery", paymentNote:"Payment: Cash",
    cashNote:"Cash payment", confirmBtn:"Confirm",
    rateDriverTitle:"Rate Driver", ratingDesc:"Rate the service",
    yourRating:"Your rating", addComment:"Comment (optional)",
    submitRating:"Submit Rating", ratingSuccess:"Thank you!",
    ratingLabels:["","Poor","Fair","Good","Great","Excellent!"],
    disputeTitle:"Open Dispute", disputeReason:"Reason *", disputeComment:"Comment",
    disputeReasonPlaceholder:"Describe the problem…", submitDispute:"Submit",
    disputeSuccess:"Dispute submitted!", disputeSuccessDesc:"We'll review it soon",
    disputeErrorEmpty:"Enter a reason",
    disputeReasons:"Cargo damaged|Late delivery|Driver behavior|Wrong address|Other",
    notifications:"Notifications", noNotifications:"No notifications",
    noNotifDesc:"Updates will appear here",
    markAllRead:"Read all",
    clientProfile:"Profile", personalData:"Personal Data",
    fullNameLabel:"Full Name", saveProfile:"Save",
    myOrdersLink:"My Orders", notificationsLink:"Notifications",
    home:"Home", orders:"Orders", profile:"Profile",
    goodMorning:"Good morning", goodAfternoon:"Good afternoon", goodEvening:"Good evening", netIncome:"Net Income", activeRoute:"Active route",
    liveLabel:"LIVE", verifiedDriver:"Verified Driver", pendingVerification:"Pending Verification",
    approvedDesc:"Matching orders will appear",
    notApprovedDesc:"Complete profile and documents",
    completeProfile:"Complete Profile", uploadDocuments:"Upload Documents",
    availability:"Availability", visibleToClients:"You are visible to clients", currentlyOffline:"You are currently offline",
    rating:"Rating", completed:"Completed", total:"Total",
    myRoutes:"My Routes", addRoute:"Add Route",
    noRoutesYet:"No routes yet", noRoutesDesc:"Add a route",
    addFirstRoute:"Add First Route", fromCity:"From City *",
    toCity:"To City *", fromDistrict:"From District (optional)",
    toDistrict:"To District (optional)", selectCity:"Select city",
    saveRoute:"Save Route", editRoute:"Edit Route",
    matchingOrders:"Matching Orders", myHistory:"My History",
    sendBid:"Send Bid", bid:"Bid", gross:"Gross", net:"Net",
    bidChangePrice:"Change Price", bidChangesLeft:"{n} changes left", bidNoChangesLeft:"No changes left",
    otherBids:"Other drivers' bids", yourBid:"Your bid", bidsCountLabel:"bids", lowestBid:"Lowest", noBidsForOrder:"No other bids yet",
    bidSheetTitle:"Send Bid", bidSheetRoute:"Route",
    bidSheetSuggestedPrice:"Suggested Price", bidSheetYourPrice:"Your Price",
    bidSheetPricePlaceholder:"Enter your price", bidSheetNote:"Note (optional)",
    bidSheetNotePlaceholder:"Additional info...", bidSheetSubmit:"Send Bid",
    bidSheetCancel:"Cancel", bidSheetSuccess:"Bid Sent!",
    bidSheetSuccessDesc:"The client will see it",
    bidSheetErrorEmpty:"Enter a price", bidSheetErrorZero:"Price must be above zero",
    bidSheetNetEst:"Estimated net income", bidSheetCommissionNote:"Commission (10%)",
    statusProgress:"Status Progress", contactDetails:"Contact Details",
    sender:"Sender", receiver:"Receiver", comment:"Comment",
    incomeReport:"Income Report", grossAmount:"Gross Amount",
    systemFee:"Commission (10%)", viewOnMap:"View on Map",
    markDelivered:"Delivered",
    accepted:"Accepted", pickedUp:"Picked Up", inTransit:"In Transit", delivered:"Delivered",
    income:"Income", afterCommission:"After commission",
    commission:"Commission", earningsChart:"Earnings Chart", sevenDays:"7 days",
    sixMonths:"6 months", recentEarnings:"Recent Earnings",
    youAreOnline:"You are online", youAreOffline:"You are offline",
    vehicle:"Vehicle", editProfile:"Edit Profile",
    documents:"Documents", settings:"Settings", logOut:"Log Out",
    fullName:"Full Name", carModel:"Car Model", carColor:"Car Color",
    plateNumber:"Plate Number", saveChanges:"Save Changes",
    vehicleLockedNote:"Vehicle details are locked. Contact an operator to change them.",
    menu:"Menu", client:"Client", support:"Support", myLocation:"My location",
    whereFrom:"From where?", whereTo:"Where to?",
    helpTitle:"Help", helpContactTitle:"Support center", helpHours:"Daily 09:00 – 21:00",
    helpCallBtn:"Call", helpFaqTitle:"FAQ",
    faq1q:"How do I create an order?", faq1a:"Pick the addresses, then tap 'View route'.",
    faq2q:"How is the price set?", faq2a:"Drivers send offers and you pick the best.",
    faq3q:"Can I cancel an order?", faq3a:"Yes, until a driver is assigned.",
    uploadAllDocs:"Upload all documents",
    viewFile:"View File", replace:"Replace", upload:"Upload",
    appearance:"Appearance", theme:"Theme", themeDesc:"Choose appearance",
    lightTheme:"Light", darkTheme:"Dark", systemTheme:"System",
    alwaysLight:"Always light", alwaysDark:"Always dark", followsDevice:"Follows device",
    language:"Language", appLanguage:"App Language", notifications2:"Notifications",
    orderUpdates:"Order Updates", orderUpdatesDesc:"Status changes",
    bidAlerts:"Bid Alerts", bidAlertsDesc:"New bids",
    promotions:"Promotions", promotionsDesc:"News and offers",
    vibration:"Vibration", vibrationDesc:"Vibration on alerts",
    account:"Account", privacySecurity:"Privacy & Security",
    termsOfService:"Terms of Service", aboutElchi:"About Elchi",
    version:"Elchi · v2.4.1 · Build 2026.06",
    statusPublished:"Published", statusBidding:"Bidding",
    statusAccepted:"Accepted", statusInTransit:"In Transit",
    statusDelivered:"Delivered", statusConfirmed:"Confirmed",
    statusCancelled:"Cancelled", statusActive:"Active",
    statusInactive:"Inactive", statusApproved:"Approved",
    statusPending:"Pending", statusMissing:"Missing", statusNew:"New", statusDraft:"Draft",
    // ── Admin panel ──
    admDashboard:"Dashboard", admOrders:"Orders", admDrivers:"Drivers",
    admClients:"Clients", admRegions:"Regions", admTariffs:"Tariffs",
    admDisputes:"Disputes", admStaff:"Staff", admNotifications:"Notifications",
    admAuditLog:"Audit Log", admProfile:"Profile",
    admRefresh:"Refresh", admLogout:"Logout", admCollapse:"Collapse",
    admBrandSubtitle:"Super Admin", admSuperAdmin:"Super Admin",
    admLoginHeading:"Management Panel", admLoginDesc:"Enter your number to continue",
    admPanelBlurb:"Manage orders, drivers and tariffs in one place", admOtpSentTo:"Code sent to:",
    // Dashboard
    admFinancialOverview:"Financial Overview", admOperations:"Operations",
    admTotalRevenue:"Total Revenue", admPlatformProfit:"Platform Profit",
    admDriverEarnings:"Driver Earnings", admAvgOrderValue:"Avg Order Value",
    admToday:"Today", admTotalOrders:"Total Orders", admActiveDeliveries:"Active Deliveries",
    admPendingDrivers:"Pending Drivers", admOpenDisputes:"Open Disputes",
    admPublishedBidding:"Published/Bidding", admApprovedDrivers:"Approved Drivers",
    admActiveTariffs:"Active Tariffs", admMissingTariffs:"Missing Tariffs",
    admRecentOrders:"Recent Orders", admViewAll:"View all",
    admVerificationQueue:"Verification Queue", admRecentActivity:"Recent Activity",
    admViewLog:"View log", admDocsShort:"docs",
    // Table headers / common
    admOrder:"Order", admRoute:"Route", admClient:"Client", admStatus:"Status",
    admPrice:"Price", admActor:"Actor", admRole:"Role", admAction:"Action",
    admEntity:"Entity", admTime:"Time", admDriver:"Driver", admPayment:"Payment",
    admDate:"Date", admActions:"Actions", admPhone:"Phone", admVehicle:"Vehicle",
    admAvailable:"Available", admDocs:"Docs", admRoutes:"Routes",
    admJoined:"Joined", admVerified:"Verified", admLastOrder:"Last Order",
    admName:"Name", admType:"Type", admDistricts:"Districts", admReqDistrict:"Req. District",
    admActive:"Active", admId:"ID", admUzbek:"Uzbek", admRussian:"Russian",
    admSuggested:"Suggested", admMin:"Min", admMax:"Max", admCurrency:"Currency",
    admCreated:"Created", admReason:"Reason", admOpenedBy:"Opened By",
    admRecipient:"Recipient", admTitle:"Title", admMessage:"Message",
    admChannel:"Channel", admRead:"Read", admLastLogin:"Last Login", admEntityId:"Entity ID",
    // Search placeholders
    admSearchOrders:"Search order, client, driver...",
    admSearchDrivers:"Search name, phone, plate...",
    admSearchClients:"Search by name or phone...",
    admSearchRegions:"Search by name...", admSearchTariffs:"Search route, city...",
    admSearchAudit:"Search actor or action...",
    // Tabs / statuses
    admTabAll:"All", admTabPublished:"Published", admTabBidding:"Bidding",
    admTabAccepted:"Accepted", admTabInTransit:"In transit", admTabDelivered:"Delivered",
    admTabConfirmed:"Confirmed", admTabCancelled:"Cancelled", admTabDisputed:"Disputed",
    admTabNew:"New", admTabPending:"Pending", admTabApproved:"Approved",
    admTabRejected:"Rejected", admTabBlocked:"Blocked",
    // Orders
    admAwaitingBids:"Awaiting Bids", admDisputed:"Disputed",
    admOverview:"Overview", admBids:"Bids", admHistory:"History",
    admFrom:"From", admTo:"To", admSuggestedPrice:"Suggested Price",
    admView:"View", admSelected:"Selected", admNoBids:"No bids yet",
    admAssignDriver:"Assign Driver", admChangeStatus:"Change Status",
    admCancelOrder:"Cancel Order", admDriverId:"Driver ID",
    admFinalPrice:"Final Price", admReasonRequired:"Reason *",
    admAssignReasonPh:"Admin assignment reason...", admStatusReasonPh:"Reason for status change...",
    admCancelReasonPh:"Cancellation reason...", admNewStatus:"New Status",
    admSelectStatus:"Select status...", admUpdateStatus:"Update Status",
    admCancelOrderWarn:"This action cannot be undone. The order will be cancelled.",
    admOrderPrefix:"Order", admDrawerAssignDriver:"Assign Driver",
    // Drivers
    admTotalDrivers:"Total Drivers", admPendingReview:"Pending Review",
    admApproved:"Approved", admAvailableNow:"Available Now",
    admOnline:"Online", admOffline:"Offline", admApprove:"Approve",
    admReject:"Reject", admBlock:"Block", admApproveDriver:"Approve Driver",
    admRejectDriver:"Reject Driver", admBlockDriver:"Block Driver",
    admApproveDriverQ:"Approve this driver to start working on the platform?",
    admRejectBlockWarn:"This will prevent them from working.",
    admReasonIncompleteDocs:"Incomplete documents", admReasonFalsifiedDocs:"Falsified documents",
    admReasonPolicyViolation:"Policy violation", admReasonOther:"Other",
    admEditVehicleDetails:"Edit Vehicle Details",
    admEditVehicleDesc:"Update the name and vehicle details.",
    admFullName:"Full Name", admCarModel:"Car Model",
    admCarColor:"Car Color", admPlateNumber:"Plate Number",
    admModel:"Model", admColor:"Color", admPlate:"Plate",
    admDocPassport:"Passport", admDocSelfie:"Selfie", admDocLicense:"Driver License",
    admDocCarDoc:"Car Document", admDocCarPhoto:"Car Photo",
    admUploaded:"Uploaded", admMissing:"Missing",
    admRating:"Rating", admCompleted:"Completed",
    // Clients
    admTotalClients:"Total Clients", admBlocked:"Blocked", admWithOrders:"With Orders",
    admBlockClient:"Block Client", admUnblock:"Unblock",
    // Regions
    admTotalRegions:"Total Regions", admWithDistricts:"With Districts",
    admInactive:"Inactive", admAddRegion:"Add Region",
    admDeactivate:"Deactivate", admActivate:"Activate",
    // Tariffs
    admTotalTariffs:"Total Tariffs", admAvgPrice:"Avg Price",
    admAddTariff:"Add Tariff", admSaveTariff:"Save Tariff",
    admFromCity:"From City", admToCity:"To City",
    admSelectPh:"Select...", admMinPrice:"Min Price", admMaxPrice:"Max Price",
    // Disputes
    admTotalDisputes:"Total Disputes", admOpen:"Open", admResolved:"Resolved",
    admDisputePrefix:"Dispute", admResolution:"Resolution", admUpdateStatusLbl:"Update Status",
    admResolutionNotePh:"Resolution note...", admUpdateDispute:"Update Dispute", admReview:"Review",
    // Staff
    admTotalStaff:"Total Staff", admAdmins:"Admins", admOperators:"Operators",
    admCreateStaff:"Create Staff User", admCreateUser:"Create User",
    admRoleLbl:"Role", admOperator:"Operator", admAdmin:"Admin",
    // Notifications
    admTotal:"Total", admUnread:"Unread", admSystem:"System",
    // Audit
    admReadOnlyAudit:"Read-only audit trail",
    // Profile
    admPhoneVerified:"Phone Verified", admYes:"Yes",
    admAccountCreated:"Account Created", admSave:"Save", admSaved:"Saved",
    admRefreshProfile:"Refresh Profile", admPlatformCommission:"Platform Commission",
    admCommissionDesc:"Driver earnings deduction rate",
    admCommissionPct:"Commission %", admCommissionWarn:"⚠ Changes apply only to future accepted orders. Existing orders keep their original commission values.",
  },
} satisfies Record<Lang, Record<string, unknown>>;

type TKey = keyof typeof T.en;

// ─── i18n ─────────────────────────────────────────────────────────────────────

const LangCtx = createContext<{ lang: Lang; t: (k: TKey) => string }>({ lang:"uz", t:(k)=>String(T.uz[k]) });
function useT() { return useContext(LangCtx); }

// ─── App Context (shared across routes) ──────────────────────────────────────

interface AppCtxType {
  role: Role;      setRole:      (r: Role)      => void;
  phone: string;   setPhone:     (p: string)    => void;
  themeMode: ThemeMode; setThemeMode: (m: ThemeMode) => void;
  lang: Lang;      setLang:      (l: Lang)      => void;
  isDark: boolean;
}
const AppCtx = createContext<AppCtxType>({} as AppCtxType);
function useApp() { return useContext(AppCtx); }

// ─── Order draft types ───────────────────────────────────────────────────────

type CityInfo = UiCity;

interface LocationPoint { city: CityInfo; district?: string; districtId?: number | null; address: string; lat?: number | null; lng?: number | null }
interface OrderDraft {
  pickup: LocationPoint | null; dropoff: LocationPoint | null;
  senderPhone: string; receiverPhone: string;
  pickupAddress: string; dropoffAddress: string;
  comment: string; hasPhoto: boolean; cargoPhotoUrl?: string | null;
  cargoType: string; clientPrice: string;
}
const EMPTY_DRAFT: OrderDraft = { pickup:null, dropoff:null, senderPhone:"", receiverPhone:"", pickupAddress:"", dropoffAddress:"", comment:"", hasPhoto:false, cargoPhotoUrl:null, cargoType:"", clientPrice:"" };

const CARGO_TYPES: { id:string; uz:string; ru:string; en:string; icon:typeof Package }[] = [
  { id:"document",    uz:"Hujjat",      ru:"Документы",   en:"Document",    icon:FileText },
  { id:"parcel",      uz:"Posilka",     ru:"Посылка",     en:"Parcel",      icon:Package },
  { id:"food",        uz:"Oziq-ovqat",  ru:"Продукты",    en:"Food",        icon:Inbox },
  { id:"fragile",     uz:"Mo'rt buyum", ru:"Хрупкое",     en:"Fragile",     icon:AlertCircle },
  { id:"electronics", uz:"Elektronika", ru:"Электроника", en:"Electronics", icon:Zap },
  { id:"clothes",     uz:"Kiyim",       ru:"Одежда",      en:"Clothes",     icon:Tag },
  { id:"other",       uz:"Boshqa",      ru:"Другое",      en:"Other",       icon:ClipboardList },
];
function cargoTypeLabel(id:string|undefined|null, lang:Lang):string {
  const ct = CARGO_TYPES.find(c=>c.id===id);
  return ct ? (lang==="ru"?ct.ru:lang==="en"?ct.en:ct.uz) : "";
}

// ─── Shared Helpers ───────────────────────────────────────────────────────────

function fmt(n: number) { return n.toLocaleString("ru-RU") + " so'm"; }

// Build a Google Maps directions deep-link (A → B). Opens the native Maps/Waze app on mobile.
// If a coordinate pair is missing, that endpoint is dropped so Google uses the device location.
function mapsDirectionsUrl(pLat:unknown, pLng:unknown, dLat:unknown, dLng:unknown): string | null {
  const num = (v:unknown)=>{ const n=Number(v); return Number.isFinite(n)?n:0; };
  const hasP = num(pLat)!==0 || num(pLng)!==0;
  const hasD = num(dLat)!==0 || num(dLng)!==0;
  const dest = hasD ? `${num(dLat)},${num(dLng)}` : hasP ? `${num(pLat)},${num(pLng)}` : "";
  if(!dest) return null;
  const params = new URLSearchParams({ api:"1", destination:dest, travelmode:"driving" });
  if(hasP && hasD) params.set("origin", `${num(pLat)},${num(pLng)}`);
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

// Unified icon stroke weight — a single thin, minimalist line style everywhere.
const SUPPORT_PHONE = (import.meta.env.VITE_SUPPORT_PHONE as string | undefined) || "+998712000000";
const asCoord = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
// Local (9-digit) part of an Uzbek phone, entered after the fixed +998 prefix.
const localPhone = (v: string) => (v || "").replace(/\D/g, "").replace(/^998/, "").slice(0, 9);
const fmtLocalPhone = (v: string) => {
  const d = localPhone(v);
  return [d.slice(0, 2), d.slice(2, 5), d.slice(5, 7), d.slice(7, 9)].filter(Boolean).join(" ");
};

// Calm icon container. Replaces the multi-colour icon chips with one quiet accent
// so the whole app reads as a single, consistent visual system.
function IconTile({ icon:Icon, size=16, tone="muted", className="" }: {
  icon: typeof Home; size?:number; tone?:"muted"|"primary"|"feruza"|"success"|"danger"; className?:string;
}) {
  const tones = {
    muted:   "bg-secondary text-muted-foreground",
    primary: "bg-primary/10 text-primary",
    feruza:  "",
    success: "",
    danger:  "bg-destructive/10 text-destructive",
  } as const;
  // color-mix() values don't survive Tailwind's arbitrary-class parser — inline them.
  const mixStyle = tone==="feruza" ? { color:"var(--feruza)", background:"color-mix(in srgb, var(--feruza) 14%, transparent)" }
    : tone==="success" ? { color:"var(--success)", background:"color-mix(in srgb, var(--success) 14%, transparent)" }
    : undefined;
  return (
    <div style={mixStyle} className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${tones[tone]} ${className}`}>
      <Icon size={size}/>
    </div>
  );
}

// ─── Route thread — the app's signature ─────────────────────────────────────
// One continuous caravan spine: a hollow feruza origin node, a beaded thread,
// and a filled majolica destination node. It replaces the two stacked inputs +
// dead grey connector on Home, and reappears as a status timeline in tracking.
function ThreadSpine({ tall=false }: { tall?:boolean }) {
  return (
    <div className="flex flex-col items-center self-stretch pt-1.5" aria-hidden="true">
      <span className="w-3.5 h-3.5 rounded-full border-[3px] flex-none"
        style={{ borderColor:"var(--feruza)", background:"var(--card)", boxShadow:"0 0 0 4px color-mix(in srgb, var(--feruza) 14%, transparent)" }}/>
      <span className={`w-0.5 ${tall?"my-2":"my-1.5"} flex-1`}
        style={{ minHeight:tall?32:20, background:"repeating-linear-gradient(to bottom, var(--primary) 0 3px, transparent 3px 8px)", opacity:.65 }}/>
      <span className="w-4 h-4 flex-none" style={{ background:"var(--primary)", borderRadius:"50% 50% 50% 3px", transform:"rotate(45deg)", boxShadow:"0 0 0 4px color-mix(in srgb, var(--primary) 16%, transparent)" }}/>
    </div>
  );
}
function RouteThread({ from, to, onFrom, onTo }: {
  from:React.ReactNode|null; to:React.ReactNode|null; onFrom:()=>void; onTo:()=>void;
}) {
  const { t } = useT();
  return (
    <div className="flex gap-3">
      <ThreadSpine/>
      <div className="flex-1 flex flex-col">
        <button onClick={onFrom} className="flex items-center justify-between text-left py-2.5 active:opacity-70 transition-opacity">
          <span className="min-w-0">
            <span className="block text-[11px] text-muted-foreground">{t("whereFrom")}</span>
            <span className={`block text-[15px] truncate ${from?"text-foreground font-medium":"text-muted-foreground/70"}`}>{from ?? t("chooseCity")}</span>
          </span>
          <ChevronRight size={16} className="text-muted-foreground flex-none ml-2"/>
        </button>
        <div className="h-px bg-border"/>
        <button onClick={onTo} className="flex items-center justify-between text-left py-2.5 active:opacity-70 transition-opacity">
          <span className="min-w-0">
            <span className="block text-[11px] text-muted-foreground">{t("whereTo")}</span>
            <span className={`block text-[15px] truncate ${to?"text-foreground font-medium":"text-muted-foreground/70"}`}>{to ?? t("chooseCity")}</span>
          </span>
          <ChevronRight size={16} className="text-muted-foreground flex-none ml-2"/>
        </button>
      </div>
    </div>
  );
}

// Quiet section label — sans-serif, replaces the techy mono/wide-tracking headers.
function SectionLabel({ children, className="" }: { children:React.ReactNode; className?:string }) {
  return <p className={`text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1 ${className}`}>{children}</p>;
}

// Unified empty state — calm icon tile (matches IconTile) + title + optional
// guidance and CTA. Replaces ad-hoc faded floating icons so every "nothing here"
// moment reads the same across both apps.
function EmptyState({ icon:Icon, title, desc, action }: {
  icon: typeof Home; title:string; desc?:string; action?:React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-8 text-center">
      <div className="w-16 h-16 rounded-2xl bg-secondary flex items-center justify-center mb-4">
        <Icon size={26} className="text-muted-foreground"/>
      </div>
      <p className="text-sm font-semibold text-foreground">{title}</p>
      {desc && <p className="text-xs text-muted-foreground mt-1 max-w-[240px] leading-relaxed">{desc}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// The route thread as a status timeline — the same caravan spine, now with a
// bead per stage. Done stages fill majolica; the current stage is a pulsing
// feruza ring; the destination is the saffron-free majolica seal-diamond.
function JourneySpine({ steps, current }: { steps:{key:string;label:string; time?:string}[]; current:number }) {
  return (
    <div className="flex flex-col">
      {steps.map((s,i)=>{
        const done=i<current, now=i===current, last=i===steps.length-1;
        return (
          <div key={s.key} className="grid grid-cols-[18px_1fr] gap-3">
            <div className="relative flex justify-center">
              {!last && <span className="absolute w-0.5" style={{ top:11, bottom:-4, background: done?"var(--primary)":"repeating-linear-gradient(to bottom, color-mix(in srgb, var(--primary) 40%, transparent) 0 3px, transparent 3px 8px)" }}/>}
              {last
                ? <span className="relative z-10 w-4 h-4 mt-1 flex-none" style={{ background: done?"var(--primary)":"var(--card)", border:done?"none":"2px solid color-mix(in srgb, var(--primary) 45%, transparent)", borderRadius:"50% 50% 50% 3px", transform:"rotate(45deg)", boxShadow: done?"0 0 0 4px color-mix(in srgb, var(--primary) 16%, transparent)":"none" }}/>
                : <span className={`relative z-10 w-3.5 h-3.5 mt-1 rounded-full flex-none ${now?"anim-pulse":""}`} style={ now
                    ? { border:"2px solid var(--feruza)", background:"var(--card)" }
                    : done ? { background:"var(--primary)" } : { background:"var(--card)", border:"2px solid color-mix(in srgb, var(--primary) 45%, transparent)" } }>
                    {now && <span className="absolute inset-[3px] rounded-full" style={{background:"var(--feruza)"}}/>}
                  </span>}
            </div>
            <div className="pb-4 min-w-0">
              <p className={`text-sm leading-tight ${now?"font-semibold text-foreground":done?"text-foreground":"text-muted-foreground"}`}>{s.label}</p>
              {s.time && <p className="text-[11px] text-muted-foreground font-mono mt-0.5">{s.time}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Status is the one place green/amber/red are allowed to speak — every state
// maps to a semantic token (success / warning / danger / info) or a calm
// neutral, never a decorative hue. A tiny leading dot doubles the signal so
// meaning survives for colour-blind readers (color-not-only).
type StatusTone = "success"|"warning"|"danger"|"info"|"neutral";
function statusToneStyle(tone:StatusTone): { style:React.CSSProperties; dot:string } {
  if(tone==="neutral") return {
    style:{ background:"var(--muted)", color:"var(--muted-foreground)", borderColor:"var(--border)" },
    dot:"var(--muted-foreground)",
  };
  // "danger" maps to the --destructive token (there is no --danger var).
  const v = tone==="danger" ? "var(--destructive)" : `var(--${tone})`;
  return {
    style:{ background:`color-mix(in srgb, ${v} 14%, transparent)`, color:v, borderColor:`color-mix(in srgb, ${v} 30%, transparent)` },
    dot:v,
  };
}
function StatusBadge({ status }: { status: string }) {
  const { t } = useT();
  const map: Record<string,{label:string;tone:StatusTone}> = {
    published:  {label:t("statusPublished"),  tone:"info"},
    bidding:    {label:t("statusBidding"),    tone:"warning"},
    accepted:   {label:t("statusAccepted"),   tone:"info"},
    in_transit: {label:t("statusInTransit"),  tone:"info"},
    delivered:  {label:t("statusDelivered"),  tone:"success"},
    confirmed:  {label:t("statusConfirmed"),  tone:"success"},
    cancelled:  {label:t("statusCancelled"),  tone:"danger"},
    active:     {label:t("statusActive"),     tone:"success"},
    inactive:   {label:t("statusInactive"),   tone:"neutral"},
    approved:   {label:t("statusApproved"),   tone:"success"},
    pending:    {label:t("statusPending"),    tone:"warning"},
    missing:    {label:t("statusMissing"),    tone:"danger"},
    new:        {label:t("statusNew"),        tone:"neutral"},
    draft:      {label:t("statusDraft"),      tone:"neutral"},
  };
  const d = map[status] ?? {label:status, tone:"neutral" as StatusTone};
  const { style, dot } = statusToneStyle(d.tone);
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold border" style={style}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background:dot }}/>
      {d.label}
    </span>
  );
}

function BackHeader({ onBack, title, right }: { onBack:()=>void; title:string; right?:React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 p-4 border-b border-border flex-shrink-0">
      <button onClick={onBack} aria-label="Orqaga" className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center active:scale-95 transition-transform"><ChevronLeft size={18} className="text-foreground"/></button>
      <h1 className="font-display text-[17px] font-bold text-foreground flex-1">{title}</h1>
      {right}
    </div>
  );
}

function ElchiLogo({ size=40 }: { size?:number }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="rounded-2xl bg-primary flex items-center justify-center relative" style={{width:size,height:size}}>
        <Send size={size*0.46} className="text-[var(--primary-foreground)] relative z-10" weight="fill"/>
        <span className="absolute rounded-xl" style={{inset:size*0.16, border:"1.5px solid color-mix(in srgb, var(--primary-foreground) 40%, transparent)"}}/>
      </div>
      <span className="font-display text-[24px] font-extrabold text-foreground leading-none">elchi</span>
    </div>
  );
}

function SettingsPanel({ onBack, themeMode, onThemeChange, lang, onLangChange, onLogout, notifKeys }: {
  onBack:()=>void; themeMode:ThemeMode; onThemeChange:(m:ThemeMode)=>void;
  lang:Lang; onLangChange:(l:Lang)=>void; onLogout:()=>void;
  notifKeys: { a:string; ad:string; b:string; bd:string }
}) {
  const { t } = useT();
  const [na,setNa] = useState(true); const [nb,setNb] = useState(true);
  const [np,setNp] = useState(false); const [vib,setVib] = useState(true);
  const themeOpts = [
    {id:"light" as ThemeMode,icon:Sun,     label:t("lightTheme"),  desc:t("alwaysLight")   },
    {id:"dark"  as ThemeMode,icon:Moon,    label:t("darkTheme"),   desc:t("alwaysDark")    },
    {id:"system"as ThemeMode,icon:Monitor, label:t("systemTheme"), desc:t("followsDevice") },
  ];
  const langs = [{id:"uz" as Lang,code:"UZ",label:"O'zbek"},{id:"ru" as Lang,code:"RU",label:"Русский"},{id:"en" as Lang,code:"EN",label:"English"}];
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("settings")}/>
      <div className="flex-1 overflow-y-auto scrollbar-hide p-4 flex flex-col gap-5 pb-8">
        <section>
          <SectionLabel>{t("appearance")}</SectionLabel>
          <div className="rounded-2xl border border-border bg-card p-4">
            <div className="grid grid-cols-3 gap-2">
              {themeOpts.map(({id,icon:Icon,label,desc})=>{
                const act=themeMode===id;
                return (
                  <button key={id} onClick={()=>onThemeChange(id)}
                    className={`flex flex-col items-center gap-1.5 rounded-xl py-3 px-2 border transition-all ${act?"border-primary bg-primary/10":"border-border bg-secondary/50"}`}>
                    <Icon size={20} className={act?"text-primary":"text-muted-foreground"}/>
                    <p className={`text-xs font-semibold ${act?"text-primary":"text-foreground"}`}>{label}</p>
                    <p className="text-[9px] text-muted-foreground leading-tight text-center">{desc}</p>
                  </button>
                );
              })}
            </div>
          </div>
        </section>
        <section>
          <SectionLabel>{t("language")}</SectionLabel>
          <div className="rounded-2xl border border-border bg-card p-3 flex gap-2">
            {langs.map(({id,code,label})=>{
              const active = lang===id;
              return (
              <button key={id} onClick={()=>onLangChange(id)}
                className={`flex-1 flex flex-col items-center gap-1.5 py-2.5 rounded-xl border transition-all ${active?"border-primary bg-primary/10":"border-border bg-secondary/50"}`}>
                <span className={`text-[11px] font-bold tracking-wide rounded-md px-1.5 py-0.5 ${active?"bg-primary text-[var(--primary-foreground)]":"bg-muted text-muted-foreground"}`}>{code}</span>
                <span className={`text-[11px] font-semibold ${active?"text-primary":"text-foreground"}`}>{label}</span>
              </button>
              );
            })}
          </div>
        </section>
        <section>
          <SectionLabel>{t("notifications2")}</SectionLabel>
          <div className="rounded-2xl border border-border bg-card overflow-hidden divide-y divide-border">
            {[
              {label:t(notifKeys.a as TKey),sub:t(notifKeys.ad as TKey),val:na, set:setNa, icon:Package},
              {label:t(notifKeys.b as TKey),sub:t(notifKeys.bd as TKey),val:nb, set:setNb, icon:Bell},
              {label:t("promotions"),       sub:t("promotionsDesc"),    val:np, set:setNp, icon:TrendingUp},
              {label:t("vibration"),        sub:t("vibrationDesc"),     val:vib,set:setVib,icon:Vibrate},
            ].map(({label,sub,val,set,icon:Icon})=>(
              <div key={label} className="flex items-center gap-3 px-4 py-3.5">
                <IconTile icon={Icon} size={15}/>
                <div className="flex-1 min-w-0"><p className="text-sm font-medium text-foreground">{label}</p></div>
                <button onClick={()=>set(!val)}>{val?<ToggleRight size={34} className="text-primary"/>:<ToggleLeft size={34} className="text-muted-foreground"/>}</button>
              </div>
            ))}
          </div>
        </section>
        <section>
          <SectionLabel>{t("account")}</SectionLabel>
          <div className="rounded-2xl border border-border bg-card overflow-hidden divide-y divide-border">
            {[
              {icon:Shield,   label:t("privacySecurity")},
              {icon:FileText, label:t("termsOfService")},
              {icon:Info,     label:t("aboutElchi")},
            ].map(({icon:Icon,label})=>(
              <button key={label} className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-secondary/40 transition-colors">
                <IconTile icon={Icon} size={15}/>
                <span className="text-sm font-medium text-foreground flex-1 text-left">{label}</span>
                <ChevronRight size={16} className="text-muted-foreground"/>
              </button>
            ))}
          </div>
        </section>
        <div className="rounded-2xl border border-border bg-card overflow-hidden">
          <button onClick={onLogout} className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-destructive/5 transition-colors">
            <IconTile icon={LogOut} size={15} tone="danger"/>
            <span className="text-sm font-medium text-destructive flex-1 text-left">{t("logOut")}</span>
          </button>
        </div>
        <p className="text-center text-[10px] text-muted-foreground">{t("version")}</p>
      </div>
    </div>
  );
}

// ─── Auth Screens ─────────────────────────────────────────────────────────────

function SplashScreen({ onDone }: { onDone:()=>void }) {
  const { t } = useT();
  useEffect(()=>{ const id=setTimeout(onDone,2200); return()=>clearTimeout(id); },[onDone]);
  return (
    <div className="flex flex-col items-center justify-center h-full bg-background gap-5 relative overflow-hidden">
      {/* Envoy seal stamps in */}
      <div className="relative anim-stamp">
        <div className="w-20 h-20 rounded-[26px] bg-primary flex items-center justify-center" style={{boxShadow:"var(--shadow-pop)"}}>
          <span className="absolute rounded-[18px]" style={{inset:9, border:"1.5px solid color-mix(in srgb, var(--primary-foreground) 35%, transparent)"}}/>
          <Send size={32} weight="fill" className="text-[var(--primary-foreground)] relative"/>
        </div>
      </div>
      <div className="text-center">
        <h1 className="font-display text-[26px] font-bold text-foreground anim-rise stagger-1">elchi</h1>
        <p className="text-sm text-muted-foreground mt-1.5 anim-rise stagger-2">{t("splashTagline")}</p>
      </div>
      {/* The route thread draws itself: origin ring → beads → destination */}
      <div className="flex items-center mt-2 anim-fade stagger-2">
        <span className="w-3 h-3 rounded-full border-[2.5px] flex-none" style={{borderColor:"var(--feruza)", background:"var(--background)"}}/>
        <span className="h-0.5 w-24 mx-1 anim-grow stagger-3" style={{background:"repeating-linear-gradient(to right, var(--primary) 0 3px, transparent 3px 8px)", opacity:.7}}/>
        <span className="w-3 h-3 flex-none anim-fade stagger-5" style={{background:"var(--primary)", borderRadius:"50% 50% 50% 3px", transform:"rotate(45deg)"}}/>
      </div>
    </div>
  );
}

function OnboardingScreen({ onContinue }: { onContinue:()=>void }) {
  const { t } = useT();
  const [idx,setIdx] = useState(0);
  const slides = [
    {icon:Route,   title:t("onboardingTitle"),      desc:t("onboardingDesc")},
    {icon:MapPin,  title:"Viloyatlararo yetkazish", desc:"Toshkent, Samarqand, Buxoro, Farg'ona va boshqa shaharlar o'rtasida"},
    {icon:Shield,  title:"Ishonchli qo'llarda",     desc:"Tasdiqlangan haydovchilar, narx takliflari va yetkazuv tasdig'i"},
  ];
  const s = slides[idx];
  const last = idx===slides.length-1;
  return (
    <div className="flex flex-col h-full bg-background px-6 pt-12 pb-8">
      <div className="anim-fade"><ElchiLogo size={36}/></div>
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-6 py-8">
        <div key={idx} className="contents">
          <div className="w-24 h-24 rounded-3xl flex items-center justify-center bg-primary/10 anim-rise"><s.icon size={44} className="text-primary"/></div>
          <div className="anim-rise stagger-2">
            <h2 className="font-display text-[22px] font-bold text-foreground mb-2.5 text-balance">{s.title}</h2>
            <p className="text-sm text-muted-foreground leading-relaxed max-w-xs mx-auto">{s.desc}</p>
          </div>
        </div>
        <div className="flex gap-1.5 justify-center">
          {slides.map((_,i)=><button key={i} onClick={()=>setIdx(i)} aria-label={`${i+1}`} className={`h-1.5 rounded-full bg-primary transition-all duration-300 ${i===idx?"w-6":"w-1.5 opacity-30"}`}/>)}
        </div>
      </div>
      <button onClick={()=>{ last?onContinue():setIdx(i=>i+1); }} className="w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-4 text-base font-semibold flex items-center justify-center gap-2 active:scale-[0.99] transition-transform">
        {last?t("onboardingCta"):t("nextBtn")}<ArrowRight size={18}/>
      </button>
      {!last && <button onClick={onContinue} className="mt-3 w-full text-sm text-muted-foreground py-1">{t("onboardingCta")}</button>}
    </div>
  );
}

function RoleSelectScreen({ onSelect, onBack }: { onSelect:(r:Role)=>void; onBack:()=>void }) {
  const { t } = useT();
  const roles = [
    {id:"client" as Role, icon:Package, title:t("roleClient"), desc:t("roleClientDesc")},
    {id:"driver" as Role, icon:Truck,   title:t("roleDriver"), desc:t("roleDriverDesc")},
  ];
  return (
    <div className="flex flex-col h-full bg-background px-5 pt-10 pb-8">
      <button onClick={onBack} aria-label={t("back")} className="self-start w-9 h-9 rounded-xl bg-secondary flex items-center justify-center mb-6 active:scale-95 transition-transform"><ChevronLeft size={18} className="text-foreground"/></button>
      <div className="anim-fade"><ElchiLogo size={36}/></div>
      <div className="mt-6 mb-8 anim-rise stagger-1">
        <h2 className="font-display text-[22px] font-bold text-foreground">{t("roleTitle")}</h2>
        <p className="text-sm text-muted-foreground mt-1.5">{t("roleDesc")}</p>
      </div>
      <div className="flex flex-col gap-3 flex-1">
        {roles.map(({id,icon:Icon,title,desc},i)=>(
          <button key={id} onClick={()=>onSelect(id)}
            className={`flex items-center gap-4 rounded-2xl border border-border bg-card p-5 text-left active:scale-[0.98] hover:border-primary/40 transition-all anim-rise stagger-${i+2}`}
            style={{boxShadow:"var(--shadow-card)"}}>
            <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center flex-shrink-0"><Icon size={26} className="text-primary"/></div>
            <div className="flex-1 min-w-0"><p className="text-base font-bold text-foreground">{title}</p><p className="text-sm text-muted-foreground mt-0.5">{desc}</p></div>
            <ChevronRight size={18} className="text-muted-foreground flex-none"/>
          </button>
        ))}
      </div>
      <p className="text-center text-xs text-muted-foreground mt-4">Elchi · UZ · {new Date().getFullYear()}</p>
    </div>
  );
}

function PhoneScreen({ role, onSubmit, onBack }: { role:Role; onSubmit:(p:string)=>Promise<void>|void; onBack:()=>void }) {
  const { t } = useT();
  const [phone,setPhone] = useState("+998 ");
  const [error,setError] = useState("");
  const [loading,setLoading] = useState(false);
  function fmtPhone(raw:string) {
    const d=raw.replace(/\D/g,"").slice(0,12);
    if(d.length<=3) return `+${d}`;
    if(d.length<=5) return `+${d.slice(0,3)} ${d.slice(3)}`;
    if(d.length<=8) return `+${d.slice(0,3)} ${d.slice(3,5)} ${d.slice(5)}`;
    if(d.length<=10) return `+${d.slice(0,3)} ${d.slice(3,5)} ${d.slice(5,8)} ${d.slice(8)}`;
    return `+${d.slice(0,3)} ${d.slice(3,5)} ${d.slice(5,8)} ${d.slice(8,10)} ${d.slice(10)}`;
  }
  function handleChange(v:string) { if(!v.startsWith("+998")){setPhone("+998 ");return;} setPhone(fmtPhone(v)); if(error)setError(""); }
  async function handleSubmit() {
    const d=phone.replace(/\D/g,"");
    if(d.length<12){setError(t("phoneError"));return;}
    setLoading(true);
    try { await onSubmit(phone); }
    catch(e){ setError(getUzbekErrorMessage(e)); }
    finally { setLoading(false); }
  }
  const RoleIcon = role==="driver"?Truck:Package;
  return (
    <div className="flex flex-col h-full bg-background px-5 pt-10 pb-8">
      <button onClick={onBack} aria-label={t("back")} className="self-start w-9 h-9 rounded-xl bg-secondary flex items-center justify-center mb-6 active:scale-95 transition-transform"><ChevronLeft size={18} className="text-foreground"/></button>
      <div className="flex items-center gap-2 mb-6 anim-fade">
        <div className="w-8 h-8 rounded-xl bg-primary/15 flex items-center justify-center"><RoleIcon size={15} className="text-primary"/></div>
        <span className="text-xs font-medium text-muted-foreground">{t("as")} <span className="text-foreground font-semibold">{t(role==="driver"?"roleDriver":"roleClient")}</span></span>
      </div>
      <div className="anim-rise stagger-1">
        <h2 className="font-display text-[22px] font-bold text-foreground mb-1.5">{t("phoneTitle")}</h2>
        <p className="text-sm text-muted-foreground mb-8">{t("phoneDesc")}</p>
      </div>
      <div className="flex-1 anim-rise stagger-2">
        <label className="text-xs font-medium text-muted-foreground mb-2 block">{t("phoneLabel")}</label>
        <div className="flex items-center gap-3 bg-input-background border rounded-2xl px-4 py-4 mb-2 transition-colors"
          style={{borderColor: error?"color-mix(in srgb, var(--destructive) 50%, transparent)":"var(--border)"}}>
          <span className="flex-none text-[11px] font-bold text-primary bg-primary/10 rounded-lg px-2 py-1">UZ</span>
          <input type="tel" autoFocus className="flex-1 bg-transparent text-lg font-bold font-mono text-foreground placeholder:text-muted-foreground outline-none"
            placeholder="+998 XX XXX XX XX" value={phone} onChange={e=>handleChange(e.target.value)}/>
        </div>
        {error && <p className="text-xs flex items-center gap-1" style={{color:"var(--destructive)"}}><AlertCircle size={11}/>{error}</p>}
      </div>
      <button onClick={handleSubmit} disabled={loading} className="w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-4 text-base font-semibold flex items-center justify-center gap-2 disabled:opacity-70 active:scale-[0.99] transition-transform anim-rise stagger-3">
        {loading?<span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<><Send size={16}/>{t("phoneCta")}</>}
      </button>
    </div>
  );
}

const OTP_LENGTH = 5;

function OtpScreen({ phone, onVerify, onResend, devOtp, onBack }: { phone:string; role:Role; onVerify:(code:string)=>Promise<void>; onResend:()=>Promise<string|undefined>; devOtp?:string; onBack:()=>void }) {
  const { t } = useT();
  const [code,setCode] = useState("");
  const [error,setError] = useState("");
  const [loading,setLoading] = useState(false);
  const [resend,setResend] = useState(59);
  const [focused,setFocused] = useState(true);
  useEffect(()=>{ if(resend<=0)return; const id=setInterval(()=>setResend(s=>s-1),1000); return()=>clearInterval(id); },[resend]);
  const complete = code.length===OTP_LENGTH;
  async function verify(){
    const c=code.replace(/\D/g,"");
    if(c.length<OTP_LENGTH){setError(t("otpError"));return;}
    setLoading(true); setError("");
    try { await onVerify(c); }
    catch(e){ setError(getUzbekErrorMessage(e)); setLoading(false); }
  }
  async function resendCode(){
    setError("");
    try { await onResend(); setResend(59); }
    catch(e){ setError(getUzbekErrorMessage(e)); }
  }
  return (
    <div className="flex flex-col h-full bg-background px-6 pt-6 pb-6">
      <button onClick={onBack} aria-label={t("back")}
        className="self-start w-9 h-9 rounded-xl bg-secondary flex items-center justify-center hover:bg-secondary/80 active:scale-95 transition-all">
        <ChevronLeft size={18} className="text-foreground"/>
      </button>

      <div className="mt-6 text-center anim-rise">
        <h2 className="font-display text-[22px] font-bold text-foreground">{t("otpTitle")}</h2>
        <p className="mt-1.5 text-sm text-muted-foreground">{t("otpDesc")}</p>
        <p className="mt-1 text-sm font-mono font-semibold text-foreground break-all">{phone}</p>
      </div>

      {/* Segmented OTP input: one hidden field drives the visible boxes */}
      <div className="relative mt-8 anim-rise stagger-2">
        <input
          type="text" inputMode="numeric" autoComplete="one-time-code" autoFocus value={code}
          onChange={e=>{setCode(e.target.value.replace(/\D/g,"").slice(0,OTP_LENGTH));setError("");}}
          onKeyDown={e=>{ if(e.key==="Enter"&&complete) verify(); }}
          onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)}
          aria-label={t("otpTitle")}
          className="absolute inset-0 z-10 w-full h-full opacity-0 cursor-pointer"/>
        <div className="grid grid-cols-5 gap-2.5">
          {Array.from({length:OTP_LENGTH}).map((_,i)=>{
            const char = code[i] ?? "";
            const isCurrent = focused && i===code.length;
            const state = error
              ? "border-2 text-foreground"
              : char
              ? "border-2 border-primary bg-primary/10 text-foreground"
              : isCurrent
              ? "border-2 border-primary bg-input-background"
              : "border border-border bg-input-background";
            const errStyle = error ? { borderColor:"color-mix(in srgb, var(--destructive) 60%, transparent)", background:"color-mix(in srgb, var(--destructive) 5%, transparent)" } : undefined;
            return (
              <div key={i} style={errStyle} className={`aspect-square rounded-full flex items-center justify-center text-lg font-bold font-mono transition-all duration-150 ${state}`}>
                {char || (isCurrent ? <span className="w-0.5 h-5 rounded-full bg-primary animate-pulse"/> : "")}
              </div>
            );
          })}
        </div>
      </div>

      {error && <p className="mt-3 text-xs text-center flex items-center justify-center gap-1" style={{color:"var(--destructive)"}}><AlertCircle size={11}/>{error}</p>}

      <div className="mt-5 flex justify-center">
        {resend>0
          ?<p className="text-xs text-muted-foreground font-mono">{t("otpResendIn")} 0:{resend.toString().padStart(2,"0")}</p>
          :<button onClick={resendCode} className="flex items-center gap-1 text-xs text-primary font-medium hover:underline"><RefreshCw size={11}/>{t("otpResend")}</button>}
      </div>

      <button onClick={verify} disabled={!complete||loading}
        className="mt-7 w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-4 text-base font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed anim-rise stagger-3">
        {loading?<span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<>{t("otpVerify")}<ArrowRight size={18}/></>}
      </button>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// CLIENT APP
// ═══════════════════════════════════════════════════════════════════════════════
// CLIENT APP
// ═══════════════════════════════════════════════════════════════════════════════

type ClientStats = { active:number; bids:number; completed:number };

function ClientHomeScreen({ onSelectFrom, onSelectTo, draft, onViewRoute, onSupport }: {
  onSelectFrom:()=>void; onSelectTo:()=>void; draft:OrderDraft; onViewRoute:()=>void; onSupport:()=>void;
}) {
  const { t } = useT();
  const mapRef = useRef<google.maps.Map | null>(null);
  const [userPos,setUserPos] = useState<{lat:number;lng:number}|null>(null);
  const [locating,setLocating] = useState(false);
  function locate(){
    if(!navigator.geolocation){ return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos)=>{
        const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setUserPos(p);
        mapRef.current?.panTo(p);
        mapRef.current?.setZoom(15);
        setLocating(false);
      },
      ()=> setLocating(false),
      { enableHighAccuracy:true, timeout:8000 },
    );
  }
  return (
    <div className="flex flex-col h-full relative">
      <div className="absolute inset-0">
        <MapView
          pickupLat={draft.pickup?.lat} pickupLng={draft.pickup?.lng}
          dropoffLat={draft.dropoff?.lat} dropoffLng={draft.dropoff?.lng}
          userLat={userPos?.lat} userLng={userPos?.lng}
          onReady={(m)=>{ mapRef.current = m; }}
          height="100%"
        />
      </div>
      <div className="absolute bottom-0 left-0 right-0 z-20 bg-card rounded-t-[24px] border-t border-border anim-sheet" style={{boxShadow:"var(--shadow-sheet)"}}>
        {/* Floating support + locate controls — clean ceramic buttons over the map */}
        <div className="absolute right-4 bottom-full mb-3 flex flex-col gap-2.5 items-center">
          <button onClick={onSupport} aria-label={t("support")}
            className="w-11 h-11 rounded-full bg-card border border-border flex items-center justify-center active:scale-95 transition-transform" style={{boxShadow:"var(--shadow-pop)"}}>
            <Headphones size={19} className="text-foreground"/>
          </button>
          <button onClick={locate} aria-label={t("myLocation")} disabled={locating}
            className="w-11 h-11 rounded-full bg-card border border-border flex items-center justify-center active:scale-95 transition-transform disabled:opacity-70" style={{boxShadow:"var(--shadow-pop)"}}>
            {locating?<span className="w-4 h-4 border-2 border-border rounded-full animate-spin" style={{borderTopColor:"var(--primary)"}}/>:<Navigation size={19} className="text-primary"/>}
          </button>
        </div>
        <div className="flex justify-center pt-3 pb-1"><div className="w-10 h-1 rounded-full bg-border"/></div>
        <div className="px-5 pt-2 pb-6">
          <h2 className="font-display text-[20px] font-bold text-foreground mb-4">{t("sendParcel")}</h2>
          <RouteThread
            from={draft.pickup ? (draft.pickup.district||draft.pickup.city.uz) : null}
            to={draft.dropoff ? (draft.dropoff.district||draft.dropoff.city.uz) : null}
            onFrom={onSelectFrom} onTo={onSelectTo}/>
          <button onClick={()=>{ if(!draft.pickup) onSelectFrom(); else if(!draft.dropoff) onSelectTo(); else onViewRoute(); }}
            className="mt-5 w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-3.5 text-[15px] font-semibold flex items-center justify-center gap-2 active:scale-[0.99] transition-transform">
            {t("viewRoute")}<ArrowRight size={17}/>
          </button>
        </div>
      </div>
    </div>
  );
}

function FaqItem({ q, a }: { q:string; a:string }) {
  const [open,setOpen] = useState(false);
  return (
    <button onClick={()=>setOpen(o=>!o)} className="w-full text-left rounded-2xl border border-border bg-card p-4 transition-colors hover:bg-secondary/40">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-foreground">{q}</span>
        <ChevronDown size={16} className={`text-muted-foreground flex-shrink-0 transition-transform ${open?"rotate-180":""}`}/>
      </div>
      {open && <p className="text-xs text-muted-foreground leading-relaxed mt-2">{a}</p>}
    </button>
  );
}

function ClientSupportScreen({ onBack }: { onBack:()=>void }) {
  const { t } = useT();
  const faqs = [{q:t("faq1q"),a:t("faq1a")},{q:t("faq2q"),a:t("faq2a")},{q:t("faq3q"),a:t("faq3a")}];
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("helpTitle")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-5">
        <div className="rounded-2xl bg-primary/10 border border-primary/20 p-4 flex items-start gap-3">
          <div className="w-11 h-11 rounded-full bg-primary/15 flex items-center justify-center flex-shrink-0"><Headphones size={20} className="text-primary"/></div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">{t("helpContactTitle")}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{t("helpHours")}</p>
            <a href={`tel:${SUPPORT_PHONE}`} className="mt-3 inline-flex items-center gap-2 bg-primary text-white rounded-xl px-4 py-2.5 text-sm font-semibold active:scale-95 transition-transform">
              <Phone size={15}/>{t("helpCallBtn")}
            </a>
          </div>
        </div>
        <div>
          <SectionLabel>{t("helpFaqTitle")}</SectionLabel>
          <div className="flex flex-col gap-2 mt-2">
            {faqs.map((f,i)=><FaqItem key={i} q={f.q} a={f.a}/>)}
          </div>
        </div>
      </div>
    </div>
  );
}

function CitySelectScreen({ title, onBack, onSelect }: { title:string; onBack:()=>void; onSelect:(c:CityInfo)=>void }) {
  const { t, lang } = useT();
  const { cities, loading } = useCities();
  const [q,setQ] = useState("");
  const filtered = cities.filter(c => [c.uz,c.ru,c.en].some(n=>n.toLowerCase().includes(q.toLowerCase())));
  const name = (c:CityInfo) => lang==="ru"?c.ru:c.uz;
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={title}/>
      <div className="p-4 pb-2">
        <div className="flex items-center gap-2 bg-input-background border border-border rounded-xl px-3 py-2.5">
          <Search size={14} className="text-muted-foreground flex-shrink-0"/>
          <input autoFocus className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none" placeholder={t("searchCity")} value={q} onChange={e=>setQ(e.target.value)}/>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading
          ?<div className="flex justify-center py-16"><span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/></div>
          :filtered.length===0
          ?<EmptyState icon={Search} title={t("noResults")}/>
          :filtered.map(c=>(
            <button key={c.id} onClick={()=>onSelect(c)} className="w-full flex items-center gap-3 px-4 py-3.5 border-b border-border hover:bg-secondary/40 transition-colors">
              <MapPin size={14} className="text-primary flex-shrink-0"/>
              <div className="flex-1 text-left">
                <p className="text-sm font-medium text-foreground">{name(c)}</p>
                {c.dist && <p className="text-[10px] text-muted-foreground font-mono">Tumanlar mavjud</p>}
              </div>
              {c.dist && <ChevronRight size={14} className="text-muted-foreground"/>}
            </button>
          ))}
      </div>
    </div>
  );
}

function DistrictSelectScreen({ city, onBack, onSelect }: { city:CityInfo; onBack:()=>void; onSelect:(d:{id:number;name:string;lat:number|null;lng:number|null})=>void }) {
  const { t } = useT();
  const { districts, loading } = useDistricts(city.id);
  const [q,setQ] = useState("");
  const filtered = districts.filter(d=>d.name_uz.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("chooseDistrict")}/>
      <div className="p-4 pb-2">
        <div className="flex items-center gap-2 bg-input-background border border-border rounded-xl px-3 py-2.5">
          <Search size={14} className="text-muted-foreground flex-shrink-0"/>
          <input autoFocus className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none" placeholder={t("searchDistrict")} value={q} onChange={e=>setQ(e.target.value)}/>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading
          ?<div className="flex justify-center py-16"><span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/></div>
          :filtered.length===0
          ?<EmptyState icon={Search} title={t("noDistricts")}/>
          :filtered.map(d=>(
            <button key={d.id} onClick={()=>onSelect({id:d.id,name:d.name_uz,lat:asCoord(d.center_lat),lng:asCoord(d.center_lng)})} className="w-full flex items-center gap-3 px-4 py-3.5 border-b border-border hover:bg-secondary/40 transition-colors">
              <div className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0"/>
              <p className="text-sm font-medium text-foreground flex-1 text-left">{d.name_uz}</p>
              <ChevronRight size={14} className="text-muted-foreground"/>
            </button>
          ))}
      </div>
    </div>
  );
}

function MapPickerScreen({ city, district, centerLat, centerLng, onBack, onConfirm }: { city:CityInfo; district?:string; centerLat?:number|null; centerLng?:number|null; onBack:()=>void; onConfirm:(loc:PickedLocation)=>void }) {
  const title = district ? `${district}, ${city.uz}` : city.uz;
  const lat = centerLat ?? null;
  const lng = centerLng ?? null;
  const initialCenter = lat !== null && lng !== null ? { lat, lng } : null;
  const regionParts = [district, city.uz, city.raw.region].filter(Boolean) as string[];
  const regionQuery = [...new Set(regionParts), "Uzbekistan"].join(", ");
  return (
    <LocationPicker
      title={title}
      initialCenter={initialCenter}
      regionQuery={regionQuery}
      initialAddress={district ? `${district}, ${city.uz}` : ""}
      onBack={onBack}
      onConfirm={onConfirm}
    />
  );
}

function ContactsScreen({ draft, onChange, onBack, onNext }: { draft:OrderDraft; onChange:(d:Partial<OrderDraft>)=>void; onBack:()=>void; onNext:()=>void }) {
  const { t } = useT();
  const [errs,setErrs] = useState<Record<string,string>>({});
  function validate() {
    const e:Record<string,string>={};
    if(localPhone(draft.senderPhone).length!==9) e.senderPhone=t("phoneError");
    if(localPhone(draft.receiverPhone).length!==9) e.receiverPhone=t("phoneError");
    if(!draft.pickupAddress) e.pickupAddress="Kiriting";
    if(!draft.dropoffAddress) e.dropoffAddress="Kiriting";
    setErrs(e); return Object.keys(e).length===0;
  }
  const phoneFields = [
    {label:t("senderPhone"),   key:"senderPhone"   as const},
    {label:t("receiverPhone"), key:"receiverPhone" as const},
  ];
  const addressFields = [
    {label:t("pickupAddress"), key:"pickupAddress"  as const, ph:"Ko'cha, uy raqami", icon:Navigation},
    {label:t("dropoffAddress"),key:"dropoffAddress" as const, ph:"Ko'cha, uy raqami", icon:MapPin},
  ];
  const draftVal = draft as unknown as Record<string,string>;
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("contactsTitle")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
        {phoneFields.map(({label,key})=>(
          <div key={key}>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">{label}</label>
            <div className={`flex items-center gap-2 bg-input-background border rounded-xl px-4 py-3 transition-colors ${errs[key]?"border-red-500/50":"border-border focus-within:border-primary/60"}`}>
              <Phone size={14} className="text-muted-foreground flex-shrink-0"/>
              <span className="text-sm text-foreground font-mono select-none flex-shrink-0">+998</span>
              <input inputMode="numeric" className="flex-1 min-w-0 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none font-mono tracking-wide" placeholder="XX XXX XX XX"
                value={fmtLocalPhone(draftVal[key])}
                onChange={e=>{ onChange({[key]:localPhone(e.target.value)}); if(errs[key])setErrs(p=>({...p,[key]:""})); }}/>
            </div>
            {errs[key] && <p className="text-xs text-red-600 dark:text-red-400 mt-1 flex items-center gap-1"><AlertCircle size={10}/>{errs[key]}</p>}
          </div>
        ))}
        {addressFields.map(({label,key,ph,icon:Icon})=>(
          <div key={key}>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">{label}</label>
            <div className={`flex items-center gap-3 bg-input-background border rounded-xl px-4 py-3 transition-colors ${errs[key]?"border-red-500/50":"border-border focus-within:border-primary/60"}`}>
              <Icon size={14} className="text-muted-foreground flex-shrink-0"/>
              <input className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none font-mono" placeholder={ph}
                value={draftVal[key]}
                onChange={e=>{ onChange({[key]:e.target.value}); if(errs[key])setErrs(p=>({...p,[key]:""})); }}/>
            </div>
            {errs[key] && <p className="text-xs text-red-600 dark:text-red-400 mt-1 flex items-center gap-1"><AlertCircle size={10}/>{errs[key]}</p>}
          </div>
        ))}
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">{t("commentOptional")}</label>
          <textarea rows={2} className="w-full bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground outline-none resize-none focus:border-primary/60 transition-colors"
            placeholder={t("commentPlaceholder")} value={draft.comment} onChange={e=>onChange({comment:e.target.value})}/>
        </div>
      </div>
      <div className="p-4 border-t border-border">
        <button onClick={()=>{ if(validate()) onNext(); }} className="w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.99] transition-transform">{t("nextBtn")}<ArrowRight size={16}/></button>
      </div>
    </div>
  );
}

function CargoPhotoScreen({ draft, onChange, onBack, onNext }: { draft:OrderDraft; onChange:(d:Partial<OrderDraft>)=>void; onBack:()=>void; onNext:()=>void }) {
  const { t, lang } = useT();
  const [uploading,setUploading] = useState(false);
  const [err,setErr] = useState("");
  const typeLabel = lang==="ru"?"Тип отправления":lang==="en"?"Parcel type":"Jo'natma turi";
  const photoOptional = lang==="ru"?"необязательно":lang==="en"?"optional":"ixtiyoriy";
  async function handleUpload(file:File|undefined){
    if(!file) return;
    setUploading(true); setErr("");
    try { const res = await uploadFile(file, "cargo_photo"); onChange({hasPhoto:true, cargoPhotoUrl:res.file_url}); }
    catch(e){ setErr(getUzbekErrorMessage(e)); }
    finally { setUploading(false); }
  }
  function next(){
    if(!draft.cargoType){ setErr(lang==="ru"?"Выберите тип отправления":lang==="en"?"Select a parcel type":"Jo'natma turini tanlang"); return; }
    setErr(""); onNext();
  }
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("cargoPhotoTitle")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-5">
        <section>
          <p className="text-xs font-medium text-muted-foreground mb-2">{typeLabel} *</p>
          <div className="grid grid-cols-3 gap-2">
            {CARGO_TYPES.map(ct=>{
              const act=draft.cargoType===ct.id; const Icon=ct.icon;
              return (
                <button key={ct.id} onClick={()=>{onChange({cargoType:ct.id}); if(err)setErr("");}}
                  className={`flex flex-col items-center gap-1.5 rounded-xl py-3 px-1 border transition-all ${act?"border-primary bg-primary/10":"border-border bg-card"}`}>
                  <Icon size={18} className={act?"text-primary":"text-muted-foreground"}/>
                  <span className={`text-[11px] font-medium text-center leading-tight ${act?"text-primary":"text-foreground"}`}>{lang==="ru"?ct.ru:lang==="en"?ct.en:ct.uz}</span>
                </button>
              );
            })}
          </div>
        </section>
        <section>
          <p className="text-xs font-medium text-muted-foreground mb-2">{t("cargoPhotoTitle")} <span className="text-muted-foreground/70">· {photoOptional}</span></p>
          {draft.hasPhoto
            ?<div className="w-full rounded-2xl overflow-hidden border" style={{borderColor:"color-mix(in srgb, var(--success) 30%, transparent)", background:"color-mix(in srgb, var(--success) 6%, transparent)"}}>
              <div className="p-4 flex items-center gap-2"><CheckCircle2 size={16} weight="fill" style={{color:"var(--success)"}}/><p className="text-sm font-medium" style={{color:"var(--success)"}}>{t("photoUploaded")}</p><button onClick={()=>onChange({hasPhoto:false, cargoPhotoUrl:null})} className="ml-auto text-xs text-muted-foreground border border-border px-2.5 py-1 rounded-lg">{t("changePhoto")}</button></div>
            </div>
            :<label className="w-full border-2 border-dashed border-border bg-secondary/30 rounded-2xl p-8 flex flex-col items-center gap-3 hover:border-primary/40 transition-colors cursor-pointer">
              {uploading?<span className="w-10 h-10 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/>
                :<><div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center"><Camera size={26} className="text-primary"/></div>
                  <div className="text-center"><p className="text-sm font-semibold text-foreground">{t("uploadPhoto")}</p><p className="text-xs text-muted-foreground mt-1">{t("photoDesc")}</p></div></>}
              <input type="file" accept="image/*" className="hidden" onChange={e=>handleUpload(e.target.files?.[0])}/>
            </label>}
        </section>
        {err && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
      </div>
      <div className="p-4 border-t border-border"><button onClick={next} className="w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.99] transition-transform">{t("nextBtn")}<ArrowRight size={16}/></button></div>
    </div>
  );
}

function OrderReviewScreen({ draft, onChange, onBack, onPublish }: { draft:OrderDraft; onChange:(d:Partial<OrderDraft>)=>void; onBack:()=>void; onPublish:()=>Promise<void> }) {
  const { t, lang } = useT();
  const fromId = draft.pickup?.city.id; const toId = draft.dropoff?.city.id;
  const { data:tariff } = useAsync<any>(()=> (fromId&&toId)?getSuggestedPrice(fromId,toId):Promise.resolve(null), [fromId,toId]);
  const price = toNum(tariff?.suggested_price);
  const minPrice = toNum(tariff?.min_price); const maxPrice = toNum(tariff?.max_price);
  const [busy,setBusy] = useState(false); const [err,setErr] = useState("");

  // Prefill the client's price with the suggested price once the tariff loads (only if empty).
  useEffect(()=>{ if(price>0 && !draft.clientPrice) onChange({clientPrice:String(price)}); }, [price]);

  const clientPriceNum = toNum(draft.clientPrice);
  const priceOutOfRange = clientPriceNum>0 && ((minPrice>0 && clientPriceNum<minPrice) || (maxPrice>0 && clientPriceNum>maxPrice));
  function onPriceInput(raw:string){ onChange({clientPrice: raw.replace(/[^\d]/g,"")}); if(err)setErr(""); }

  async function go(){
    if(priceOutOfRange){ setErr(clientPriceNum<minPrice?t("priceTooLow"):t("priceTooHigh")); return; }
    setBusy(true); setErr(""); try { await onPublish(); } catch(e){ setErr(getUzbekErrorMessage(e)); setBusy(false); }
  }
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("reviewTitle")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-3">
        <div className="rounded-2xl border border-border bg-card p-4" style={{boxShadow:"var(--shadow-card)"}}>
          <div className="flex items-start gap-3">
            <div className="flex flex-col items-center pt-1">
              <span className="w-3.5 h-3.5 rounded-full border-[3px] flex-none" style={{borderColor:"var(--feruza)", background:"var(--card)"}}/>
              <span className="w-0.5 my-1 flex-1" style={{minHeight:30, background:"repeating-linear-gradient(to bottom, var(--primary) 0 3px, transparent 3px 8px)", opacity:.6}}/>
              <span className="w-4 h-4 flex-none" style={{background:"var(--primary)", borderRadius:"50% 50% 50% 3px", transform:"rotate(45deg)"}}/>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[15px] font-bold text-foreground mb-1">{draft.pickup?.city.uz}{draft.pickup?.district?` · ${draft.pickup.district}`:""}</p>
              <p className="text-xs text-muted-foreground mb-3 truncate">{draft.pickupAddress||draft.pickup?.address}</p>
              <p className="text-[15px] font-bold text-foreground mb-1">{draft.dropoff?.city.uz}{draft.dropoff?.district?` · ${draft.dropoff.district}`:""}</p>
              <p className="text-xs text-muted-foreground truncate">{draft.dropoffAddress||draft.dropoff?.address}</p>
            </div>
          </div>
        </div>
        <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">{t("suggestedPrice")}</p>
            <p className="text-sm font-bold font-mono text-foreground">{price>0?fmt(price):"—"}</p>
          </div>
          {(minPrice>0||maxPrice>0) && (
            <p className="text-[11px] text-muted-foreground">{t("priceRangeHint")}: <span className="font-mono">{minPrice>0?fmt(minPrice):"—"} – {maxPrice>0?fmt(maxPrice):"—"}</span></p>
          )}
          <div className="pt-1 border-t border-primary/15">
            <label className="text-xs font-medium text-foreground block mb-2">{t("yourPrice")}</label>
            <div className="flex items-center gap-2 rounded-xl border bg-card px-3 py-2.5" style={{borderColor: priceOutOfRange?"var(--destructive)":"var(--border)"}}>
              <input
                type="text" inputMode="numeric" value={draft.clientPrice}
                onChange={e=>onPriceInput(e.target.value)}
                placeholder={price>0?String(price):"0"}
                className="flex-1 bg-transparent text-lg font-bold font-mono text-foreground outline-none placeholder:text-muted-foreground/50 placeholder:font-normal"/>
              <span className="text-sm text-muted-foreground">so'm</span>
            </div>
          </div>
        </div>
        {draft.cargoType && (
          <div className="rounded-2xl border border-border bg-card p-4 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{lang==="ru"?"Тип отправления":lang==="en"?"Parcel type":"Jo'natma turi"}</span>
            <span className="text-sm font-medium text-foreground">{cargoTypeLabel(draft.cargoType, lang)}</span>
          </div>
        )}
        <div className="rounded-2xl border border-border bg-card p-4 flex flex-col gap-2">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{t("contactDetails")}</p>
          {[{label:t("sender"),value:draft.senderPhone},{label:t("receiver"),value:draft.receiverPhone}].map(({label,value})=>(
            <div key={label} className="flex items-center justify-between"><span className="text-xs text-muted-foreground">{label}</span><span className="text-sm font-mono text-foreground">{value}</span></div>
          ))}
          {draft.comment && <div className="pt-2 border-t border-border"><p className="text-xs text-muted-foreground">{t("comment")}</p><p className="text-sm text-foreground mt-0.5">{draft.comment}</p></div>}
        </div>
        {draft.hasPhoto && (
          <div className="rounded-2xl border border-border bg-card p-4 flex items-center gap-3">
            <Image size={16} className="text-primary"/><p className="text-sm font-medium text-foreground flex-1">{t("cargoPhotoTitle")}</p><CheckCircle2 size={16} weight="fill" style={{color:"var(--success)"}}/>
          </div>
        )}
        {err && <p className="text-xs flex items-center gap-1" style={{color:"var(--destructive)"}}><AlertCircle size={11}/>{err}</p>}
      </div>
      <div className="p-4 border-t border-border flex gap-3">
        <button onClick={onBack} className="flex-1 border border-border bg-secondary rounded-2xl py-3 text-sm font-semibold text-foreground">{t("editOrder")}</button>
        <button onClick={go} disabled={busy} className="flex-[2] flex items-center justify-center gap-2 bg-primary text-white rounded-2xl py-3 text-sm font-semibold disabled:opacity-70">
          {busy?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<><Send size={14}/>{t("publishOrder")}</>}
        </button>
      </div>
    </div>
  );
}

function OrderSuccessScreen({ onViewOrder, onHome }: { onViewOrder:()=>void; onHome:()=>void }) {
  const { t } = useT();
  return (
    <div className="flex flex-col h-full bg-background items-center justify-center px-8 text-center">
      {/* Envoy seal — the parcel is entrusted and on its way. Stamps in on mount. */}
      <div className="w-28 h-28 rounded-full grid place-items-center mb-6 relative anim-stamp"
        style={{ background:"radial-gradient(circle at 38% 32%, color-mix(in srgb, var(--primary) 18%, var(--card)), color-mix(in srgb, var(--primary) 8%, var(--card)))", border:"2px solid var(--primary)", boxShadow:"var(--shadow-pop)" }}>
        <span className="absolute rounded-full" style={{ inset:8, border:"1.5px dashed color-mix(in srgb, var(--primary) 45%, transparent)" }}/>
        <Send size={42} weight="fill" className="text-primary relative"/>
      </div>
      <h2 className="font-display text-[24px] font-extrabold text-foreground mb-2 anim-rise stagger-1">{t("orderPublished")}</h2>
      <p className="text-sm text-muted-foreground leading-relaxed mb-10 anim-rise stagger-2">{t("orderPublishedDesc")}</p>
      <div className="flex flex-col gap-3 w-full anim-rise stagger-3">
        <button onClick={onViewOrder} className="w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.99] transition-transform"><Eye size={16}/>{t("viewMyOrder")}</button>
        <button onClick={onHome} className="w-full border border-border bg-secondary rounded-2xl py-3.5 text-sm font-semibold text-foreground flex items-center justify-center gap-2 active:scale-[0.99] transition-transform"><Home size={16}/>{t("backHome")}</button>
      </div>
    </div>
  );
}

function ClientOrdersScreen({ onOrderDetail, onCreateOrder }: { onOrderDetail:(id:number)=>void; onCreateOrder:()=>void }) {
  const { t } = useT();
  const [tab,setTab] = useState<"all"|"active"|"completed"|"cancelled">("all");
  const { data, loading } = useAsync<any>(()=>listClientOrders({ limit:50 }), []);
  const orders:any[] = data?.items ?? [];
  const filtered = orders.filter(o=>{
    if(tab==="all") return true;
    if(tab==="active") return ["published","bidding","accepted","picked_up","in_transit"].includes(o.status);
    if(tab==="completed") return ["delivered","confirmed"].includes(o.status);
    return o.status==="cancelled";
  });
  const tabs = [{id:"all" as const,label:t("allOrders")},{id:"active" as const,label:t("activeOrders")},{id:"completed" as const,label:t("completedOrders")},{id:"cancelled" as const,label:t("cancelledOrders")}];
  return (
    <div className="flex flex-col h-full">
      <div className="p-4 pt-5 pb-2">
        <h1 className="font-display text-[22px] font-extrabold text-foreground mb-3 pl-16">{t("myOrders")}</h1>
        <div className="flex gap-1 bg-secondary rounded-xl p-1">
          {tabs.map(tp=>(
            <button key={tp.id} onClick={()=>setTab(tp.id)}
              className={`flex-1 py-1.5 rounded-lg text-[11px] font-medium transition-colors whitespace-nowrap ${tab===tp.id?"bg-card text-foreground":"text-muted-foreground"}`}>
              {tp.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-3">
        {loading
          ?<div className="flex justify-center py-16"><span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/></div>
          :filtered.length===0
          ?<EmptyState icon={Package} title={t("noOrdersYet")} desc={t("noOrdersDesc")} action={<button onClick={onCreateOrder} className="bg-primary text-white rounded-xl px-5 py-2.5 text-sm font-medium">{t("createOrder")}</button>}/>
          :filtered.map((o,i)=>{
            const price = toNum(o.final_price ?? o.client_price ?? o.suggested_price);
            const cancelled = o.status==="cancelled";
            const cardStyle:React.CSSProperties = cancelled
              ? { boxShadow:"var(--shadow-card)", animationDelay:`${Math.min(i*45,225)}ms`, background:"color-mix(in srgb, var(--destructive) 5%, var(--card))", borderColor:"color-mix(in srgb, var(--destructive) 28%, transparent)" }
              : { boxShadow:"var(--shadow-card)", animationDelay:`${Math.min(i*45,225)}ms` };
            return (
            <button key={o.id} onClick={()=>onOrderDetail(o.id)} style={cardStyle}
              className={`rounded-2xl border p-4 text-left active:scale-[0.99] transition-all anim-rise ${cancelled?"border-transparent":"border-border bg-card hover:border-primary/30"}`}>
              <div className="flex items-center justify-between mb-2"><span className="font-mono text-xs text-muted-foreground">{o.order_number||`#${o.id}`}</span><StatusBadge status={o.status}/></div>
              <div className="flex items-center gap-2 mb-1">
                <p className={`text-[15px] font-bold ${cancelled?"text-muted-foreground line-through":"text-foreground"}`}>{o.from_city}</p>
                <ArrowRight size={14} className="flex-none" style={{color: cancelled?"var(--destructive)":"var(--primary)"}}/>
                <p className={`text-[15px] font-bold ${cancelled?"text-muted-foreground line-through":"text-foreground"}`}>{o.to_city}</p>
              </div>
              <p className="text-xs text-muted-foreground mb-3">{o.from_district?.name_uz||""}{o.to_district?` → ${o.to_district?.name_uz||""}`:""}</p>
              <div className="flex items-center justify-between pt-3 border-t" style={{borderColor: cancelled?"color-mix(in srgb, var(--destructive) 18%, transparent)":"var(--border)"}}>
                <p className={`text-sm font-bold font-mono ${cancelled?"text-muted-foreground":"text-foreground"}`}>{price>0?fmt(price):"—"}</p>
                <div className="flex items-center gap-2">
                  {!cancelled && o.bids_count>0 && <span className="text-xs bg-primary/10 text-primary border border-primary/20 rounded-lg px-2 py-0.5 font-mono">{o.bids_count} {t("bidsStat")}</span>}
                  <span className="text-xs text-muted-foreground font-mono">{fmtDate(o.created_at)}</span>
                </div>
              </div>
            </button>
          );})}
      </div>
    </div>
  );
}

function ClientOrderDetailScreen({ orderId, onBack, onViewBids, onConfirmDelivery, onRate, onDispute, onCancelled }: {
  orderId:number; onBack:()=>void; onViewBids:()=>void; onConfirmDelivery:()=>void; onRate:()=>void; onDispute:()=>void; onCancelled:()=>void;
}) {
  const { t, lang } = useT();
  const { data:o, loading } = useAsync<any>(()=>getClientOrder(orderId), [orderId]);
  const [cancelling,setCancelling] = useState(false);
  if(loading||!o) return <div className="flex flex-col h-full"><BackHeader onBack={onBack} title={`#${orderId}`}/><div className="flex-1 flex items-center justify-center"><span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/></div></div>;
  const fromCity = cityNameOf(o.from_city, lang); const toCity = cityNameOf(o.to_city, lang);
  const price = toNum(o.final_price ?? o.client_price ?? o.suggested_price);
  const driver = o.assigned_driver;
  const sf = [{key:"published",label:t("statusPublished")},{key:"bidding",label:t("statusBidding")},{key:"accepted",label:t("statusAccepted")},{key:"in_transit",label:t("statusInTransit")},{key:"delivered",label:t("statusDelivered")}];
  const ci = sf.findIndex(s=>s.key===o.status);
  async function cancel(){ setCancelling(true); try { await cancelClientOrder(orderId,"Mijoz tomonidan bekor qilindi"); onCancelled(); } catch{ setCancelling(false); } }
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={o.order_number||`#${o.id}`} right={<StatusBadge status={o.status}/>}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
        <div className="rounded-2xl border border-border bg-card p-4" style={{boxShadow:"var(--shadow-card)"}}>
          <div className="flex items-start gap-3">
            <div className="flex flex-col items-center pt-1">
              <span className="w-3.5 h-3.5 rounded-full border-[3px] flex-none" style={{borderColor:"var(--feruza)", background:"var(--card)"}}/>
              <span className="w-0.5 my-1 flex-1" style={{minHeight:34, background:"repeating-linear-gradient(to bottom, var(--primary) 0 3px, transparent 3px 8px)", opacity:.6}}/>
              <span className="w-4 h-4 flex-none" style={{background:"var(--primary)", borderRadius:"50% 50% 50% 3px", transform:"rotate(45deg)"}}/>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[15px] font-bold text-foreground">{fromCity}</p><p className="text-xs text-muted-foreground mb-4 truncate">{o.pickup_address||""}</p>
              <p className="text-[15px] font-bold text-foreground">{toCity}</p><p className="text-xs text-muted-foreground truncate">{o.dropoff_address||""}</p>
            </div>
            <p className="text-base font-bold font-mono text-foreground whitespace-nowrap">{price>0?fmt(price):"—"}</p>
          </div>
        </div>
        {o.cargo_type && (
          <div className="rounded-2xl border border-border bg-card p-4 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{lang==="ru"?"Тип отправления":lang==="en"?"Parcel type":"Jo'natma turi"}</span>
            <span className="text-sm font-medium text-foreground">{cargoTypeLabel(o.cargo_type, lang)}</span>
          </div>
        )}
        {(toNum(o.pickup_lat)!==0 || toNum(o.dropoff_lat)!==0) && (
          <div className="rounded-2xl border border-border bg-card overflow-hidden h-44 flex-none">
            <MapView pickupLat={o.pickup_lat} pickupLng={o.pickup_lng} dropoffLat={o.dropoff_lat} dropoffLng={o.dropoff_lng} height="100%"/>
          </div>
        )}
        {!["confirmed","cancelled"].includes(o.status) && (
          <div className="rounded-2xl border border-border bg-card p-4" style={{boxShadow:"var(--shadow-card)"}}>
            <SectionLabel>{t("statusTimeline")}</SectionLabel>
            <JourneySpine steps={sf} current={ci}/>
          </div>
        )}
        {driver && (
          <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-3">{t("assignedDriver")}</p>
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-primary/15 flex items-center justify-center"><Truck size={20} className="text-primary"/></div>
              <div className="flex-1">
                <p className="text-sm font-bold text-foreground">{driver.full_name||"—"}</p>
                <p className="text-xs text-muted-foreground">{driver.car_model||""}{driver.plate_number?` · ${driver.plate_number}`:""}</p>
                <div className="flex items-center gap-1 mt-0.5"><Star size={11} weight="fill" className="text-primary"/><span className="text-xs font-mono">{toNum(driver.rating).toFixed(1)}</span></div>
              </div>
              {driver.phone && <a href={`tel:${driver.phone}`} aria-label={driver.phone} className="w-10 h-10 rounded-xl bg-primary/15 flex items-center justify-center active:scale-95 transition-transform"><Phone size={16} className="text-primary"/></a>}
            </div>
          </div>
        )}
        {["published","bidding"].includes(o.status) && (
          <div className="rounded-2xl border border-border bg-card p-4">
            <div className="flex items-center justify-between mb-2"><p className="text-sm font-semibold text-foreground">{t("bidsSection")}</p>{o.bids_count>0&&<span className="text-xs bg-primary/10 text-primary border border-primary/20 rounded-lg px-2 py-0.5 font-mono">{o.bids_count}</span>}</div>
            {!o.bids_count
              ?<p className="text-xs text-muted-foreground">{t("waitingBids")}</p>
              :<button onClick={onViewBids} className="w-full flex items-center justify-center gap-2 bg-primary/10 text-primary border border-primary/20 rounded-xl py-2.5 text-sm font-medium active:scale-[0.99] transition-transform"><Eye size={14}/>{t("viewBids")}</button>}
          </div>
        )}
        <div className="flex flex-col gap-2">
          {o.status==="delivered" && <button onClick={onConfirmDelivery} className="w-full text-white rounded-2xl py-3 text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.99] transition-transform" style={{background:"var(--success)"}}><CheckCheck size={16}/>{t("confirmDelivery")}</button>}
          {o.status==="confirmed" && <button onClick={onRate} className="w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-3 text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.99] transition-transform"><Star size={16} weight="fill"/>{t("rateDriverTitle")}</button>}
          {!["confirmed","cancelled"].includes(o.status) && <button onClick={onDispute} className="w-full border border-border text-muted-foreground rounded-2xl py-3 text-sm font-medium flex items-center justify-center gap-2 active:scale-[0.99] transition-transform"><Flag size={14}/>{t("openDisputeBtn")}</button>}
          {["published","bidding","accepted"].includes(o.status) && <button onClick={cancel} disabled={cancelling} className="w-full border rounded-2xl py-3 text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-60 active:scale-[0.99] transition-transform" style={{borderColor:"color-mix(in srgb, var(--destructive) 30%, transparent)", color:"var(--destructive)"}}><Ban size={14}/>{t("cancelOrderBtn")}</button>}
        </div>
      </div>
    </div>
  );
}

function ClientBidsScreen({ orderId, onBack, onSelectDriver }: { orderId:number; onBack:()=>void; onSelectDriver:()=>void }) {
  const { t } = useT();
  const { data, loading } = useAsync<any[]>(()=>listClientOrderBids(orderId), [orderId]);
  const bids:any[] = data ?? [];
  const [sel,setSel] = useState<any|null>(null);
  const [busy,setBusy] = useState(false);
  async function confirm(){ if(!sel) return; setBusy(true); try { await selectDriver(orderId, sel.id); setSel(null); onSelectDriver(); } catch{ setBusy(false); } }
  return (
    <div className="flex flex-col h-full relative">
      {sel && (
        <div className="absolute inset-0 z-50 flex flex-col justify-end bg-black/50 backdrop-blur-sm">
          <div className="bg-card rounded-t-[28px] border-t border-border p-5">
            <div className="flex justify-center mb-4"><div className="w-10 h-1 rounded-full bg-border"/></div>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-2xl bg-primary/15 flex items-center justify-center"><Truck size={20} className="text-primary"/></div>
              <div className="flex-1"><p className="text-base font-bold text-foreground">{sel.driver?.full_name||"—"}</p><p className="text-xs text-muted-foreground">{sel.driver?.car_model||""}{sel.driver?.plate_number?` · ${sel.driver.plate_number}`:""}</p><div className="flex items-center gap-1 mt-0.5"><Star size={10} className="text-primary fill-primary"/><span className="text-xs font-mono">{toNum(sel.driver?.rating).toFixed(1)}</span></div></div>
              <p className="text-lg font-bold font-mono text-foreground">{fmt(toNum(sel.price))}</p>
            </div>
            <h3 className="text-sm font-semibold text-foreground mb-1">{t("confirmDriverTitle")}</h3>
            <p className="text-xs text-muted-foreground mb-5">{t("confirmDriverDesc")}</p>
            <div className="flex gap-3">
              <button onClick={()=>setSel(null)} className="flex-1 border border-border bg-secondary rounded-2xl py-3 text-sm font-semibold text-foreground">{t("bidSheetCancel")}</button>
              <button onClick={confirm} disabled={busy} className="flex-[2] bg-primary text-white rounded-2xl py-3 text-sm font-semibold disabled:opacity-70">{busy?"...":t("confirmSelectDriver")}</button>
            </div>
          </div>
        </div>
      )}
      <BackHeader onBack={onBack} title={t("driverOffers")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-3">
        {loading
          ?<div className="flex justify-center py-16"><span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/></div>
          :bids.length===0
          ?<EmptyState icon={Inbox} title={t("noBids")} desc={t("waitingBids")}/>
          :bids.map((b,i)=>(
            <div key={b.id} className={`rounded-2xl border bg-card p-4 ${i===0?"border-primary/30 bg-primary/5":"border-border"}`}>
              {i===0 && <div className="flex items-center gap-1 mb-2"><Star size={10} weight="fill" className="text-primary"/><span className="text-[10px] text-primary font-semibold">Top taklif</span></div>}
              <div className="flex items-center gap-3 mb-3">
                <div className="w-11 h-11 rounded-xl bg-secondary flex items-center justify-center"><Truck size={18} className="text-muted-foreground"/></div>
                <div className="flex-1">
                  <p className="text-sm font-bold text-foreground">{b.driver?.full_name||"—"}</p><p className="text-xs text-muted-foreground">{b.driver?.car_model||""}{b.driver?.plate_number?` · ${b.driver.plate_number}`:""}</p>
                  <div className="flex items-center gap-2 mt-0.5"><div className="flex items-center gap-0.5"><Star size={10} className="text-primary fill-primary"/><span className="text-xs font-mono">{toNum(b.driver?.rating).toFixed(1)}</span></div><span className="text-xs text-muted-foreground">· {b.driver?.completed_orders||0} {t("completed")}</span></div>
                </div>
                <div className="text-right"><p className="text-lg font-bold font-mono text-foreground">{(toNum(b.price)/1000).toFixed(0)}K</p><p className="text-[10px] text-muted-foreground">so'm</p></div>
              </div>
              <button onClick={()=>setSel(b)} className={`w-full py-2.5 rounded-xl text-sm font-semibold ${i===0?"bg-primary text-white":"border border-border bg-secondary text-foreground"}`}>{t("selectDriver")}</button>
            </div>
          ))}
      </div>
    </div>
  );
}

function ConfirmDeliveryScreen({ orderId, onBack, onConfirm }: { orderId:number; onBack:()=>void; onConfirm:()=>void }) {
  const { t, lang } = useT();
  const { data:o } = useAsync<any>(()=>getClientOrder(orderId), [orderId]);
  const [loading,setLoading] = useState(false); const [err,setErr] = useState("");
  const price = toNum(o?.final_price ?? o?.client_price ?? o?.suggested_price);
  async function go(){ setLoading(true); setErr(""); try { await confirmClientOrder(orderId); onConfirm(); } catch(e){ setErr(getUzbekErrorMessage(e)); setLoading(false); } }
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("confirmDeliveryTitle")}/>
      <div className="flex-1 p-4 flex flex-col gap-4">
        <div className="rounded-2xl border border-green-500/20 bg-green-500/5 p-5 text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/15 flex items-center justify-center mx-auto mb-3"><CheckCheck size={28} className="text-green-600 dark:text-green-400"/></div>
          <p className="text-base font-bold text-foreground mb-1">{cityNameOf(o?.from_city, lang)} → {cityNameOf(o?.to_city, lang)}</p>
          <p className="text-sm text-muted-foreground">{t("statusDelivered")}</p>
        </div>
        <div className="rounded-2xl border border-border bg-card p-4">
          <div className="flex items-center gap-3 mb-3"><CreditCard size={16} className="text-primary"/><p className="text-sm font-semibold text-foreground">{t("paymentNote")}</p></div>
          <p className="text-sm text-muted-foreground">{t("cashNote")}</p>
          <div className="mt-3 pt-3 border-t border-border flex items-center justify-between"><span className="text-xs text-muted-foreground">Jami to'lov</span><span className="text-base font-bold font-mono text-foreground">{price>0?fmt(price):"—"}</span></div>
        </div>
        {err && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
      </div>
      <div className="p-4 border-t border-border">
        <button onClick={go} disabled={loading} className="w-full bg-green-500 text-white rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-70">
          {loading?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<><CheckCheck size={16}/>{t("confirmBtn")}</>}
        </button>
      </div>
    </div>
  );
}

function RatingScreen({ orderId, onBack, onSubmit }: { orderId:number; onBack:()=>void; onSubmit:()=>void }) {
  const { t } = useT();
  const labels = t("ratingLabels") as unknown as string[];
  const [stars,setStars] = useState(0); const [hover,setHover] = useState(0);
  const [comment,setComment] = useState(""); const [loading,setLoading] = useState(false); const [done,setDone] = useState(false); const [err,setErr] = useState("");
  async function go(){ if(!stars)return; setLoading(true); setErr(""); try { await rateClientOrder(orderId,{rating:stars,comment:comment||null}); setLoading(false); setDone(true); setTimeout(onSubmit,1800); } catch(e){ setErr(getUzbekErrorMessage(e)); setLoading(false); } }
  if(done) return (
    <div className="flex flex-col h-full items-center justify-center px-8 text-center">
      <div className="w-20 h-20 rounded-full bg-primary/15 flex items-center justify-center mb-4 anim-stamp"><ThumbsUp size={36} weight="fill" className="text-primary"/></div>
      <p className="font-display text-[24px] font-extrabold text-foreground mb-2 anim-rise stagger-1">{t("ratingSuccess")}</p>
      <p className="text-sm text-muted-foreground anim-rise stagger-2">Bahoingiz uchun rahmat!</p>
    </div>
  );
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("rateDriverTitle")}/>
      <div className="flex-1 p-6 flex flex-col items-center gap-6">
        <div className="w-20 h-20 rounded-2xl bg-primary/15 flex items-center justify-center"><Truck size={36} className="text-primary"/></div>
        <div>
          <p className="text-sm font-medium text-muted-foreground text-center mb-4">{t("ratingDesc")}</p>
          <div className="flex gap-3 justify-center">
            {[1,2,3,4,5].map(s=>(
              <button key={s} onMouseEnter={()=>setHover(s)} onMouseLeave={()=>setHover(0)} onClick={()=>setStars(s)}>
                <Star size={36} className={`transition-colors ${s<=(hover||stars)?"text-primary fill-primary":"text-border"}`}/>
              </button>
            ))}
          </div>
          {stars>0 && <p className="text-center text-sm font-medium text-foreground mt-3">{labels[stars]}</p>}
        </div>
        <div className="w-full">
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">{t("addComment")}</label>
          <textarea rows={3} className="w-full bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground outline-none resize-none focus:border-primary/60 transition-colors"
            placeholder="Izoh..." value={comment} onChange={e=>setComment(e.target.value)}/>
        </div>
        {err && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
      </div>
      <div className="p-4 border-t border-border">
        <button onClick={go} disabled={!stars||loading} className="w-full bg-primary text-[var(--primary-foreground)] rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-40 active:scale-[0.99] transition-transform">
          {loading?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<><Star size={14} weight="fill"/>{t("submitRating")}</>}
        </button>
      </div>
    </div>
  );
}

function DisputeScreen({ orderId, onBack }: { orderId:number; onBack:()=>void }) {
  const { t } = useT();
  const reasons = (t("disputeReasons") as unknown as string).split("|");
  const [sel,setSel] = useState(""); const [comment,setComment] = useState(""); const [err,setErr] = useState(""); const [loading,setLoading] = useState(false); const [done,setDone] = useState(false);
  async function go(){ if(!sel){setErr(t("disputeErrorEmpty"));return;} setLoading(true); setErr(""); try { await openClientDispute(orderId,{reason:sel,comment:comment||null}); setLoading(false); setDone(true); } catch(e){ setErr(getUzbekErrorMessage(e)); setLoading(false); } }
  if(done) return (
    <div className="flex flex-col h-full items-center justify-center px-8 text-center">
      <div className="w-20 h-20 rounded-full flex items-center justify-center mb-4 anim-stamp" style={{background:"color-mix(in srgb, var(--warning) 15%, transparent)"}}><Flag size={36} weight="fill" style={{color:"var(--warning)"}}/></div>
      <p className="font-display text-[24px] font-extrabold text-foreground mb-2 anim-rise stagger-1">{t("disputeSuccess")}</p>
      <p className="text-sm text-muted-foreground mb-8">{t("disputeSuccessDesc")}</p>
      <button onClick={onBack} className="bg-primary text-white rounded-2xl px-8 py-3 text-sm font-semibold">{t("back")}</button>
    </div>
  );
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("disputeTitle")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-2 block">{t("disputeReason")}</label>
          <div className="flex flex-col gap-2">
            {reasons.map((r:string)=>(
              <button key={r} onClick={()=>{setSel(r);setErr("");}} className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all ${sel===r?"border-primary bg-primary/10":"border-border bg-card"}`}>
                <div className={`w-4 h-4 rounded-full border-2 flex-shrink-0 ${sel===r?"border-primary bg-primary":"border-border"}`}/>
                <span className="text-sm font-medium text-foreground">{r}</span>
              </button>
            ))}
          </div>
          {err && <p className="text-xs text-red-600 dark:text-red-400 mt-2 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">{t("disputeComment")}</label>
          <textarea rows={4} className="w-full bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground outline-none resize-none focus:border-primary/60 transition-colors"
            placeholder={t("disputeReasonPlaceholder")} value={comment} onChange={e=>setComment(e.target.value)}/>
        </div>
      </div>
      <div className="p-4 border-t border-border">
        <button onClick={go} disabled={loading} className="w-full bg-primary text-white rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-70">
          {loading?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<><Flag size={14}/>{t("submitDispute")}</>}
        </button>
      </div>
    </div>
  );
}

function ClientNotificationsScreen({ notifs, loading, reload, onBack }: {
  notifs:any[]; loading:boolean; reload:()=>void; onBack?:()=>void;
}) {
  const { t } = useT();
  const unread = notifs.filter(n=>!n.is_read).length;
  async function readOne(id:number){ try { await markNotificationRead(id); reload(); } catch{ /* ignore */ } }
  async function readAll(){ try { await Promise.all(notifs.filter(n=>!n.is_read).map(n=>markNotificationRead(n.id))); reload(); } catch{ /* ignore */ } }
  return (
    <div className="flex flex-col h-full">
      <div className={`p-4 pt-5 pb-2 flex items-center justify-between ${onBack?"":"pl-16"}`}>
        <div className="flex items-center gap-2.5 min-w-0">
          {onBack && <button onClick={onBack} aria-label={t("back")} className="w-9 h-9 rounded-full bg-secondary flex items-center justify-center flex-shrink-0 active:scale-95 transition-transform"><ChevronLeft size={18} className="text-foreground"/></button>}
          <div className="min-w-0"><h1 className="font-display text-[22px] font-extrabold text-foreground">{t("notifications")}</h1>{unread>0&&<p className="text-xs text-muted-foreground mt-0.5">{unread} ta o'qilmagan</p>}</div>
        </div>
        {unread>0&&<button onClick={readAll} className="text-xs text-primary font-medium flex-shrink-0">{t("markAllRead")}</button>}
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading
          ?<div className="flex justify-center py-16"><span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/></div>
          :notifs.length===0
          ?<EmptyState icon={Bell} title={t("noNotifications")} desc={t("noNotifDesc")}/>
          :notifs.map(n=>(
            <button key={n.id} onClick={()=>readOne(n.id)}
              className={`w-full flex items-start gap-3 px-4 py-4 border-b border-border text-left transition-colors ${!n.is_read?"bg-primary/5":"hover:bg-secondary/40"}`}>
              <div className={`w-2.5 h-2.5 rounded-full mt-1.5 flex-shrink-0 ${!n.is_read?"bg-primary":"bg-transparent border border-border"}`}/>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-0.5">
                  <p className={`text-sm font-semibold ${!n.is_read?"text-foreground":"text-muted-foreground"}`}>{n.title||n.type}</p>
                  <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0 ml-2">{fmtDate(n.created_at)}</span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{n.message||n.body||""}</p>
                {n.order_id && <p className="text-[10px] text-primary font-mono mt-1">#{n.order_id}</p>}
              </div>
            </button>
          ))}
      </div>
    </div>
  );
}

function ClientProfileScreen({ phone, onOrders, onNotifications, onSettings, onLogout, stats }: {
  phone:string; onOrders:()=>void; onNotifications:()=>void; onSettings:()=>void; onLogout:()=>void; stats:ClientStats;
}) {
  const { t } = useT();
  const { data:me } = useAsync<any>(()=>getMe(), []);
  const [name,setName] = useState("");
  useEffect(()=>{ if(me?.full_name) setName(me.full_name); },[me]);
  const [saving,setSaving] = useState(false); const [saved,setSaved] = useState(false);
  const [saveErr,setSaveErr] = useState("");
  async function save(){ setSaving(true); setSaveErr(""); try { await updateClientProfile(name); setSaved(true); setTimeout(()=>setSaved(false),2000); } catch(e){ setSaveErr(getUzbekErrorMessage(e)); } finally { setSaving(false); } }
  return (
    <div className="flex flex-col gap-4 p-4 pb-6">
      <h1 className="font-display text-[22px] font-extrabold text-foreground pt-1 pl-16">{t("clientProfile")}</h1>
      <div className="rounded-2xl border border-border bg-card p-5" style={{boxShadow:"var(--shadow-card)"}}>
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-primary/15 flex items-center justify-center"><User size={28} className="text-primary"/></div>
          <div className="space-y-1"><h2 className="font-display text-[18px] font-bold text-foreground leading-tight">{name||"—"}</h2><p className="text-sm text-muted-foreground font-mono">{phone}</p><StatusBadge status="active"/></div>
        </div>
        <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-border">
          {[{label:t("activeStat"),value:String(stats.active)},{label:t("bidsStat"),value:String(stats.bids)},{label:t("completedStat"),value:String(stats.completed)}].map(({label,value})=>(
            <div key={label} className="text-center"><p className="text-lg font-bold font-mono text-foreground">{value}</p><p className="text-[10px] text-muted-foreground">{label}</p></div>
          ))}
        </div>
      </div>
      <div className="rounded-2xl border border-border bg-card p-4">
        <p className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wide">{t("personalData")}</p>
        <label className="text-xs text-muted-foreground mb-1.5 block">{t("fullNameLabel")}</label>
        <div className="flex gap-2">
          <input className="flex-1 bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground outline-none focus:border-primary/60 transition-colors" value={name} onChange={e=>setName(e.target.value)}/>
          <button onClick={save} disabled={saving} className="px-4 rounded-xl text-sm font-medium transition-colors disabled:opacity-60 active:scale-[0.98]"
            style={saved?{background:"color-mix(in srgb, var(--success) 15%, transparent)", color:"var(--success)", border:"1px solid color-mix(in srgb, var(--success) 25%, transparent)"}:{background:"var(--primary)", color:"var(--primary-foreground)"}}>
            {saving?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin inline-block"/>:saved?<CheckCircle2 size={16} weight="fill"/>:t("saveProfile")}
          </button>
        </div>
        {saveErr && <p className="mt-2 text-sm" style={{color:"var(--destructive)"}}>{saveErr}</p>}
      </div>
      <div className="rounded-2xl border border-border bg-card overflow-hidden">
        {[{icon:Package,label:t("myOrdersLink"),action:onOrders},{icon:Bell,label:t("notificationsLink"),action:onNotifications},{icon:Settings,label:t("settings"),action:onSettings}].map(({icon:Icon,label,action},i)=>(
          <button key={label} onClick={action} className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-secondary/50 transition-colors ${i>0?"border-t border-border":""}`}>
            <IconTile icon={Icon} size={15}/><span className="text-sm text-foreground flex-1 text-left">{label}</span><ChevronRight size={16} className="text-muted-foreground"/>
          </button>
        ))}
        <button onClick={onLogout} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-destructive/5 transition-colors border-t border-border">
          <IconTile icon={LogOut} size={15} tone="danger"/><span className="text-sm text-destructive flex-1 text-left">{t("logOut")}</span>
        </button>
      </div>
    </div>
  );
}

// ─── Client Shell ─────────────────────────────────────────────────────────────

function ClientApp({ phone, themeMode, onThemeChange, lang, onLangChange, onLogout }: {
  phone:string; themeMode:ThemeMode; onThemeChange:(m:ThemeMode)=>void;
  lang:Lang; onLangChange:(l:Lang)=>void; onLogout:()=>void;
}) {
  const { t } = useT();
  const [tab,setTab]       = useState<ClientTab>("home");
  const [screen,setScreen] = useState<ClientScreen>("home");
  const [menuOpen,setMenuOpen] = useState(false);
  const [draft,setDraft]   = useState<OrderDraft>(EMPTY_DRAFT);
  const [selOrder,setSelOrder] = useState<number>(0);
  const [pendingCity,setPendingCity]     = useState<CityInfo|null>(null);
  const [pendingDist,setPendingDist]     = useState<{id:number;name:string;lat:number|null;lng:number|null}|undefined>();
  const [side,setSide]                   = useState<"from"|"to">("from");

  const { data:ordersData } = useAsync<any>(()=>listClientOrders({ limit:100 }), [screen==="home"||screen==="profile"]);
  const allOrders:any[] = ordersData?.items ?? [];
  const stats:ClientStats = {
    active: allOrders.filter(o=>["published","bidding","accepted","picked_up","in_transit"].includes(o.status)).length,
    bids: allOrders.reduce((s,o)=>s+(o.bids_count||0),0),
    completed: allOrders.filter(o=>["delivered","confirmed"].includes(o.status)).length,
  };

  const { data:notifData, loading:notifLoading, reload:reloadNotifs } = useAsync<any>(()=>getNotifications({ limit:50 }), [tab]);
  const notifs:any[] = notifData?.items ?? [];
  const unreadNotifs = notifs.filter(n=>!n.is_read).length;

  function goTo(s:ClientScreen){ setScreen(s); }
  function goTab(tb:ClientTab){ setTab(tb); setScreen(tb); }

  function handleCity(city:CityInfo, forSide:"from"|"to"){
    setSide(forSide); setPendingCity(city);
    if(city.dist) goTo(forSide==="from"?"district-select-from":"district-select-to");
    else { setPendingDist(undefined); goTo(forSide==="from"?"map-picker-from":"map-picker-to"); }
  }
  function handleDistrict(d:{id:number;name:string;lat:number|null;lng:number|null}){ setPendingDist(d); goTo(side==="from"?"map-picker-from":"map-picker-to"); }
  function handleConfirmLoc(loc:PickedLocation){
    if(!pendingCity) return;
    const pt:LocationPoint = { city:pendingCity, district:pendingDist?.name, districtId:pendingDist?.id ?? null, address:loc.address, lat:loc.lat, lng:loc.lng };
    if(side==="from") setDraft(d=>({...d,pickup:pt,pickupAddress:loc.address})); else setDraft(d=>({...d,dropoff:pt,dropoffAddress:loc.address}));
    goTo("home");
  }

  async function publishOrder(){
    if(!draft.pickup||!draft.dropoff) throw new Error("VALIDATION_ERROR");
    const created:any = await createClientOrder({
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

  const isMain = ["home","orders","notifications","profile"].includes(screen);

  return (
    <div className="flex flex-col flex-1 min-h-0 relative">
      <div key={screen} className="flex-1 min-h-0 overflow-y-auto scrollbar-hide screen-in">
        {screen==="home" && <ClientHomeScreen onSelectFrom={()=>{setSide("from");goTo("city-select-from");}} onSelectTo={()=>{setSide("to");goTo("city-select-to");}} draft={draft} onViewRoute={()=>goTo("contacts")} onSupport={()=>goTo("c-support")}/>}
        {screen==="city-select-from" && <CitySelectScreen title={t("chooseCity")} onBack={()=>goTo("home")} onSelect={c=>handleCity(c,"from")}/>}
        {screen==="city-select-to"   && <CitySelectScreen title={t("chooseCity")} onBack={()=>goTo("home")} onSelect={c=>handleCity(c,"to")}/>}
        {screen==="district-select-from" && pendingCity && <DistrictSelectScreen city={pendingCity} onBack={()=>goTo("city-select-from")} onSelect={handleDistrict}/>}
        {screen==="district-select-to"   && pendingCity && <DistrictSelectScreen city={pendingCity} onBack={()=>goTo("city-select-to")}   onSelect={handleDistrict}/>}
        {screen==="map-picker-from" && pendingCity && <MapPickerScreen city={pendingCity} district={pendingDist?.name} centerLat={pendingDist?.lat} centerLng={pendingDist?.lng} onBack={()=>goTo(pendingCity.dist?"district-select-from":"city-select-from")} onConfirm={handleConfirmLoc}/>}
        {screen==="map-picker-to"   && pendingCity && <MapPickerScreen city={pendingCity} district={pendingDist?.name} centerLat={pendingDist?.lat} centerLng={pendingDist?.lng} onBack={()=>goTo(pendingCity.dist?"district-select-to":"city-select-to")}   onConfirm={handleConfirmLoc}/>}
        {screen==="contacts"     && <ContactsScreen     draft={draft} onChange={p=>setDraft(d=>({...d,...p}))} onBack={()=>goTo("home")}     onNext={()=>goTo("cargo-photo")}/>}
        {screen==="cargo-photo"  && <CargoPhotoScreen   draft={draft} onChange={p=>setDraft(d=>({...d,...p}))} onBack={()=>goTo("contacts")} onNext={()=>goTo("order-review")}/>}
        {screen==="order-review" && <OrderReviewScreen  draft={draft} onChange={p=>setDraft(d=>({...d,...p}))} onBack={()=>goTo("cargo-photo")} onPublish={publishOrder}/>}
        {screen==="order-success"&& <OrderSuccessScreen onViewOrder={()=>{setDraft(EMPTY_DRAFT);goTo("c-order-detail");}} onHome={()=>{setDraft(EMPTY_DRAFT);goTab("home");}}/>}
        {screen==="orders"       && <ClientOrdersScreen onOrderDetail={id=>{setSelOrder(id);goTo("c-order-detail");}} onCreateOrder={()=>goTab("home")}/>}
        {screen==="c-order-detail"&&<ClientOrderDetailScreen orderId={selOrder} onBack={()=>goTab("orders")} onViewBids={()=>goTo("bids")} onConfirmDelivery={()=>goTo("confirm-delivery")} onRate={()=>goTo("rating")} onDispute={()=>goTo("dispute")} onCancelled={()=>goTab("orders")}/>}
        {screen==="bids"          &&<ClientBidsScreen orderId={selOrder} onBack={()=>goTo("c-order-detail")} onSelectDriver={()=>goTo("c-order-detail")}/>}
        {screen==="confirm-delivery"&&<ConfirmDeliveryScreen orderId={selOrder} onBack={()=>goTo("c-order-detail")} onConfirm={()=>goTo("rating")}/>}
        {screen==="rating"        &&<RatingScreen orderId={selOrder} onBack={()=>goTo("orders")} onSubmit={()=>goTab("orders")}/>}
        {screen==="dispute"       &&<DisputeScreen orderId={selOrder} onBack={()=>goTo("c-order-detail")}/>}
        {screen==="notifications" &&<ClientNotificationsScreen notifs={notifs} loading={notifLoading} reload={reloadNotifs}/>}
        {screen==="profile"       &&<ClientProfileScreen phone={phone} stats={stats} onOrders={()=>goTab("orders")} onNotifications={()=>goTab("notifications")} onSettings={()=>goTo("c-settings")} onLogout={onLogout}/>}
        {screen==="c-settings"    &&<SettingsPanel onBack={()=>goTo("profile")} themeMode={themeMode} onThemeChange={onThemeChange} lang={lang} onLangChange={onLangChange} onLogout={onLogout} notifKeys={{a:"bidAlerts",ad:"bidAlertsDesc",b:"orderUpdates",bd:"orderUpdatesDesc"}}/>}
        {screen==="c-support"     &&<ClientSupportScreen onBack={()=>goTo("home")}/>}
      </div>
      {/* Top-left floating menu button (opens the hideable drawer) */}
      {isMain && !menuOpen && (
        <button onClick={()=>setMenuOpen(true)} aria-label={t("menu")}
          className="absolute top-4 left-4 z-30 w-11 h-11 rounded-full bg-card border border-border flex items-center justify-center active:scale-95 transition-transform" style={{boxShadow:"var(--shadow-pop)"}}>
          <Menu size={20} className="text-foreground"/>
          {unreadNotifs>0 && <span className="absolute top-0.5 right-0.5 w-2.5 h-2.5 rounded-full bg-destructive border-2 border-card"/>}
        </button>
      )}

      {/* Backdrop */}
      <div onClick={()=>setMenuOpen(false)}
        className={`absolute inset-0 z-40 bg-black/50 transition-opacity duration-300 ${menuOpen?"opacity-100":"opacity-0 pointer-events-none"}`}/>

      {/* Hideable side menu */}
      <aside className={`absolute top-0 left-0 z-50 h-full w-[80%] max-w-[300px] bg-background border-r border-border shadow-2xl flex flex-col transition-transform duration-300 ${menuOpen?"translate-x-0":"-translate-x-full"}`}>
        <div className="flex items-center justify-between p-5 border-b border-border">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-11 h-11 rounded-full bg-primary/15 flex items-center justify-center flex-shrink-0"><User size={22} className="text-primary"/></div>
            <div className="min-w-0"><p className="text-sm font-semibold text-foreground font-mono truncate">{phone||"—"}</p><p className="text-[11px] text-muted-foreground">{t("client")}</p></div>
          </div>
          <button onClick={()=>setMenuOpen(false)} aria-label="Close" className="w-8 h-8 rounded-full hover:bg-secondary flex items-center justify-center flex-shrink-0"><X size={16} className="text-muted-foreground"/></button>
        </div>
        <nav className="flex-1 overflow-y-auto p-3 flex flex-col gap-1">
          {([
            {id:"home" as ClientTab,icon:Home,label:t("home")},
            {id:"orders" as ClientTab,icon:Package,label:t("orders")},
            {id:"notifications" as ClientTab,icon:Bell,label:t("notifications")},
            {id:"profile" as ClientTab,icon:User,label:t("profile")},
          ]).map(({id,icon:Icon,label})=>{
            const active=tab===id;
            return (
              <button key={id} onClick={()=>{goTab(id);setMenuOpen(false);}}
                className={`flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-colors ${active?"bg-secondary text-foreground":"text-muted-foreground hover:bg-secondary/60"}`}>
                <Icon size={19} className={active?"text-primary":""}/>
                <span>{label}</span>
                {id==="notifications"&&unreadNotifs>0 && <span className="ml-auto min-w-5 h-5 px-1.5 rounded-full bg-destructive text-white text-[10px] font-bold flex items-center justify-center leading-none">{unreadNotifs>9?"9+":unreadNotifs}</span>}
              </button>
            );
          })}
          <button onClick={()=>{goTo("c-support");setMenuOpen(false);}} className="flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium text-muted-foreground hover:bg-secondary/60 transition-colors"><Headphones size={19}/><span>{t("helpTitle")}</span></button>
          <button onClick={()=>{goTo("c-settings");setMenuOpen(false);}} className="flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium text-muted-foreground hover:bg-secondary/60 transition-colors"><Settings size={19}/><span>{t("settings")}</span></button>
        </nav>
        <div className="p-3 border-t border-border">
          <button onClick={onLogout} className="flex items-center gap-3 w-full rounded-xl px-4 py-3 text-sm font-medium text-red-400 hover:bg-red-500/10 transition-colors"><LogOut size={19}/><span>{t("logOut")}</span></button>
        </div>
      </aside>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// DRIVER APP
// ═══════════════════════════════════════════════════════════════════════════════

type BidOrder = UiFeedOrder;
type BidState = "form"|"loading"|"success";

function BidSheet({ order, onSubmitted, onClose }: { order:BidOrder; onSubmitted:()=>void; onClose:()=>void }) {
  const { t } = useT();
  const editing = order.hasBid && order.bidId!=null;
  const updatesLeft = order.bidUpdatesLeft ?? 3;
  const exhausted = editing && updatesLeft<=0;
  const [price,setPrice] = useState(editing&&order.bidPrice?order.bidPrice.toLocaleString("ru-RU"):""); const [note,setNote] = useState(""); const [err,setErr] = useState(""); const [st,setSt] = useState<BidState>("form");
  const num = parseInt(price.replace(/\D/g,""),10)||0;
  const net = num>0?Math.round(num*0.9):0;
  function bd(e:React.MouseEvent<HTMLDivElement>){ if(e.target===e.currentTarget)onClose(); }
  function hp(raw:string){ const d=raw.replace(/\D/g,""); setPrice(d?parseInt(d,10).toLocaleString("ru-RU"):""); if(err)setErr(""); }
  async function go(){
    if(!price||num===0){setErr(num===0&&price?t("bidSheetErrorZero"):t("bidSheetErrorEmpty"));return;}
    setSt("loading");
    try {
      if(editing) await updateBid(order.bidId!, { price:num, comment:note||null });
      else await sendBid(order.id, { price:num, comment:note||null });
      setSt("success"); onSubmitted();
    }
    catch(e){ setErr(getUzbekErrorMessage(e)); setSt("form"); }
  }
  useEffect(()=>{ if(st==="success"){const id=setTimeout(onClose,2200);return()=>clearTimeout(id);} },[st,onClose]);
  return (
    <div className="absolute inset-0 z-50 flex flex-col justify-end" style={{background:"rgba(0,0,0,0.55)",backdropFilter:"blur(2px)"}} onClick={bd}>
      <div className="bg-card rounded-t-[28px] border-t border-border overflow-hidden">
        <div className="flex justify-center pt-3 pb-1"><div className="w-10 h-1 rounded-full bg-border"/></div>
        {st==="success"
          ?<div className="flex flex-col items-center py-10 px-6 gap-3">
            <div className="w-16 h-16 rounded-full bg-green-500/15 flex items-center justify-center mb-2"><CheckCircle2 size={32} className="text-green-600 dark:text-green-400"/></div>
            <p className="text-lg font-bold text-foreground">{t("bidSheetSuccess")}</p>
            <p className="text-sm text-muted-foreground text-center">{t("bidSheetSuccessDesc")}</p>
            <p className="text-xs font-mono text-muted-foreground">{order.from} → {order.to} · {num.toLocaleString("ru-RU")} so'm</p>
          </div>
          :<div className="px-5 pt-2 pb-7 flex flex-col gap-0">
            <div className="flex items-center justify-between mb-5"><h2 className="text-lg font-bold text-foreground">{editing?t("bidChangePrice"):t("bidSheetTitle")}</h2><button onClick={onClose} className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center"><X size={14} className="text-foreground"/></button></div>
            <div className="rounded-2xl border border-border bg-background p-4 mb-4">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2">{t("bidSheetRoute")}</p>
              <div className="flex items-center gap-3">
                <div className="flex flex-col items-center gap-1"><span className="w-2.5 h-2.5 rounded-full border-2 flex-none" style={{borderColor:"var(--feruza)",background:"var(--card)"}}/><span className="w-0.5 h-5" style={{background:"repeating-linear-gradient(to bottom, var(--primary) 0 3px, transparent 3px 7px)",opacity:.6}}/><span className="w-2.5 h-2.5 flex-none" style={{background:"var(--primary)",borderRadius:"50% 50% 50% 2px",transform:"rotate(45deg)"}}/></div>
                <div className="flex-1"><p className="text-sm font-semibold text-foreground">{order.from}</p><p className="text-[11px] text-muted-foreground mb-1">{order.pickup}</p><p className="text-sm font-semibold text-foreground">{order.to}</p><p className="text-[11px] text-muted-foreground">{order.dropoff}</p></div>
                <div className="text-right"><p className="text-[10px] text-muted-foreground mb-0.5">{t("bidSheetSuggestedPrice")}</p><p className="text-base font-bold font-mono text-foreground">{(order.price/1000).toFixed(0)}K</p><p className="text-[10px] text-muted-foreground">so'm</p></div>
              </div>
            </div>
            <div className="mb-3">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">{t("bidSheetYourPrice")} *</label>
              <div className={`flex items-center gap-3 bg-input-background border rounded-xl px-4 py-3 ${err?"border-red-500/50":"border-border focus-within:border-primary/60"}`}>
                <span className="text-sm text-muted-foreground font-mono flex-shrink-0">so'm</span>
                <input type="text" inputMode="numeric" autoFocus className="flex-1 bg-transparent text-sm font-bold font-mono text-foreground placeholder:text-muted-foreground outline-none" placeholder={t("bidSheetPricePlaceholder")} value={price} onChange={e=>hp(e.target.value)}/>
              </div>
              {err && <p className="text-xs text-red-600 dark:text-red-400 mt-1.5 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
              {editing && !err && <p className={`text-[11px] mt-1.5 ${exhausted?"text-red-600 dark:text-red-400":"text-muted-foreground"}`}>{exhausted?t("bidNoChangesLeft"):t("bidChangesLeft").replace("{n}",String(updatesLeft))}</p>}
            </div>
            {num>0 && <div className="rounded-xl border border-green-500/20 bg-green-500/5 px-4 py-2.5 mb-3 flex items-center justify-between"><div><p className="text-xs font-medium text-green-600 dark:text-green-400">{t("bidSheetNetEst")}</p><p className="text-[10px] text-muted-foreground">{t("bidSheetCommissionNote")}</p></div><p className="text-base font-bold font-mono text-green-600 dark:text-green-400">{net.toLocaleString("ru-RU")}</p></div>}
            <div className="mb-5">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">{t("bidSheetNote")}</label>
              <textarea rows={2} className="w-full bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground outline-none resize-none focus:border-primary/60 transition-colors" placeholder={t("bidSheetNotePlaceholder")} value={note} onChange={e=>setNote(e.target.value)}/>
            </div>
            <div className="flex gap-3">
              <button onClick={onClose} className="flex-1 border border-border bg-secondary rounded-2xl py-3 text-sm font-semibold text-foreground">{t("bidSheetCancel")}</button>
              <button onClick={go} disabled={st==="loading"||exhausted} className="flex-[2] flex items-center justify-center gap-2 bg-primary text-white rounded-2xl py-3 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed">
                {st==="loading"?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<><Send size={14}/>{editing?t("bidChangePrice"):t("bidSheetSubmit")}</>}
              </button>
            </div>
          </div>}
      </div>
    </div>
  );
}

// ── Add Route (connected) ─────────────────────────────────────────────────────
function DriverAddRoute({ onBack, onSaved }: { onBack:()=>void; onSaved:()=>void }) {
  const { t } = useT();
  const { cities } = useCities();
  const [fromCity,setFromCity] = useState<number|"">("");
  const [toCity,setToCity]     = useState<number|"">("");
  const [fromDist,setFromDist] = useState<number|"">("");
  const [toDist,setToDist]     = useState<number|"">("");
  const [err,setErr] = useState(""); const [saving,setSaving] = useState(false);
  const fromCityObj = cities.find(c=>c.id===fromCity);
  const toCityObj   = cities.find(c=>c.id===toCity);
  const { districts: fromDistricts } = useDistricts(fromCityObj?.dist ? (fromCity||null) : null);
  const { districts: toDistricts }   = useDistricts(toCityObj?.dist ? (toCity||null) : null);
  async function save(){
    if(!fromCity||!toCity){ setErr(t("phoneError")); return; }
    setSaving(true); setErr("");
    try {
      await createDriverRoute({ from_city_id:Number(fromCity), to_city_id:Number(toCity), from_district_id:fromDist?Number(fromDist):null, to_district_id:toDist?Number(toDist):null });
      onSaved();
    } catch(e){ setErr(getUzbekErrorMessage(e)); setSaving(false); }
  }
  const selCls = "w-full bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground appearance-none";
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("addRoute")}/>
      <div className="flex flex-col gap-4 p-4 flex-1 overflow-y-auto">
        <div>
          <label className="text-xs text-muted-foreground mb-1.5 block">{t("fromCity")}</label>
          <select className={selCls} value={fromCity} onChange={e=>{setFromCity(e.target.value?Number(e.target.value):"");setFromDist("");}}>
            <option value="">{t("selectCity")}</option>
            {cities.map(c=><option key={c.id} value={c.id}>{c.uz}</option>)}
          </select>
        </div>
        {fromCityObj?.dist && fromDistricts.length>0 && (
          <div>
            <label className="text-xs text-muted-foreground mb-1.5 block">{t("fromDistrict")}</label>
            <select className={selCls} value={fromDist} onChange={e=>setFromDist(e.target.value?Number(e.target.value):"")}>
              <option value="">—</option>
              {fromDistricts.map(d=><option key={d.id} value={d.id}>{d.name_uz}</option>)}
            </select>
          </div>
        )}
        <div>
          <label className="text-xs text-muted-foreground mb-1.5 block">{t("toCity")}</label>
          <select className={selCls} value={toCity} onChange={e=>{setToCity(e.target.value?Number(e.target.value):"");setToDist("");}}>
            <option value="">{t("selectCity")}</option>
            {cities.map(c=><option key={c.id} value={c.id}>{c.uz}</option>)}
          </select>
        </div>
        {toCityObj?.dist && toDistricts.length>0 && (
          <div>
            <label className="text-xs text-muted-foreground mb-1.5 block">{t("toDistrict")}</label>
            <select className={selCls} value={toDist} onChange={e=>setToDist(e.target.value?Number(e.target.value):"")}>
              <option value="">—</option>
              {toDistricts.map(d=><option key={d.id} value={d.id}>{d.name_uz}</option>)}
            </select>
          </div>
        )}
        {err && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
        <div className="mt-auto pt-4">
          <button onClick={save} disabled={saving} className="w-full bg-primary text-white rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-70">
            {saving?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:t("saveRoute")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Edit Profile (connected) ──────────────────────────────────────────────────
function DriverEditProfile({ data, onBack, onSaved }: { data:UiDriverData; onBack:()=>void; onSaved:()=>void }) {
  const { t } = useT();
  const locked = data.status==="approved"; // vehicle details locked after admin approval
  const [fullName,setFullName] = useState(data.name);
  const [model,setModel] = useState(data.car.model==="—"?"":data.car.model);
  const [color,setColor] = useState(data.car.color==="—"?"":data.car.color);
  const [plate,setPlate] = useState(data.car.plate==="—"?"":data.car.plate);
  const [err,setErr] = useState(""); const [saving,setSaving] = useState(false);
  async function save(){
    setSaving(true); setErr("");
    try {
      await updateDriverProfile(locked
        ? { full_name:fullName||null }
        : { full_name:fullName||null, car_model:model||null, car_color:color||null, plate_number:plate||null });
      onSaved();
    }
    catch(e){ setErr(getUzbekErrorMessage(e)); setSaving(false); }
  }
  const fields = [
    {label:t("fullName"),value:fullName,set:setFullName,editable:true},
    {label:t("carModel"),value:model,set:setModel,editable:!locked},
    {label:t("carColor"),value:color,set:setColor,editable:!locked},
    {label:t("plateNumber"),value:plate,set:setPlate,editable:!locked},
  ];
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("editProfile")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
        {locked && (
          <div className="flex items-start gap-2 rounded-xl border border-border bg-secondary/40 px-3 py-2.5">
            <Lock size={13} className="text-muted-foreground flex-shrink-0 mt-0.5"/>
            <p className="text-xs text-muted-foreground leading-relaxed">{t("vehicleLockedNote")}</p>
          </div>
        )}
        {fields.map(({label,value,set,editable})=>(
          <div key={label}>
            <label className="text-xs text-muted-foreground mb-1.5 block">{label}{!editable&&<Lock size={10} className="inline ml-1 -mt-0.5 text-muted-foreground"/>}</label>
            <input
              className="w-full bg-input-background border border-border rounded-xl px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground font-mono outline-none disabled:opacity-60 disabled:cursor-not-allowed"
              value={value} disabled={!editable} onChange={e=>set(e.target.value)}/>
          </div>
        ))}
        {err && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
        <button className="w-full bg-primary text-white rounded-2xl py-3.5 text-sm font-semibold mt-2 flex items-center justify-center gap-2 disabled:opacity-70" onClick={save} disabled={saving}>
          {saving?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:t("saveChanges")}
        </button>
      </div>
    </div>
  );
}

// ── Documents (connected upload) ──────────────────────────────────────────────
const DRIVER_DOC_DEFS: { type:DriverDocumentType; label:string }[] = [
  { type:"passport",     label:"Passport" },
  { type:"selfie",       label:"Selfie" },
  { type:"license",      label:"Driver License" },
  { type:"car_document", label:"Car Document" },
  { type:"car_photo",    label:"Car Photo" },
];
function DriverDocuments({ data, onBack, onUploaded }: { data:UiDriverData; onBack:()=>void; onUploaded:()=>void }) {
  const { t } = useT();
  const [busy,setBusy] = useState<DriverDocumentType|null>(null);
  const [err,setErr] = useState("");
  const baseStatus = data.status==="approved"?"approved":data.status==="pending"?"pending":"missing";
  async function upload(type:DriverDocumentType, file:File|undefined){
    if(!file) return;
    setBusy(type); setErr("");
    try { await uploadDriverDocument(type, file); onUploaded(); }
    catch(e){ setErr(getUzbekErrorMessage(e)); }
    finally { setBusy(null); }
  }
  return (
    <div className="flex flex-col h-full">
      <BackHeader onBack={onBack} title={t("documents")}/>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-3">
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-2"><AlertCircle size={14}/>{t("uploadAllDocs")}</div>
        {err && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertCircle size={11}/>{err}</p>}
        {DRIVER_DOC_DEFS.map(doc=>(
          <div key={doc.type} className="rounded-2xl border border-border bg-card p-4">
            <div className="flex items-center justify-between mb-3"><div className="flex items-center gap-2">{baseStatus==="approved"?<CheckCircle2 size={16} className="text-green-600 dark:text-green-400"/>:baseStatus==="pending"?<Clock size={16} className="text-amber-600 dark:text-amber-400"/>:<AlertCircle size={16} className="text-red-600 dark:text-red-400"/>}<p className="text-sm font-semibold text-foreground">{doc.label}</p></div><StatusBadge status={baseStatus}/></div>
            <label className="w-full border border-dashed border-primary/30 bg-primary/5 text-primary rounded-xl py-2.5 text-xs font-medium flex items-center justify-center gap-1.5 cursor-pointer">
              {busy===doc.type?<span className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/>:<><Plus size={12}/>{t("upload")} {doc.label}</>}
              <input type="file" accept="image/*,application/pdf" className="hidden" onChange={e=>upload(doc.type, e.target.files?.[0])}/>
            </label>
          </div>
        ))}
      </div>
    </div>
  );
}

// Shows all active bids on an order to a driver who has placed a bid, so they can
// see how their offer compares with the competition. Hidden until the driver bids.
function DriverOrderBids({ orderId }: { orderId:number }) {
  const { t } = useT();
  const { data:o } = useAsync<any>(()=>getDriverOrderDetail(orderId), [orderId]);
  const bids:any[] = Array.isArray(o?.bids) ? o.bids : [];
  const myBid = o?.my_bid;
  if(!myBid) return null;
  const lowest = bids.length ? Math.min(...bids.map(b=>toNum(b.price))) : 0;
  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">{t("otherBids")}</p>
        <span className="text-[11px] text-muted-foreground font-mono">{bids.length} {t("bidsCountLabel")}</span>
      </div>
      {bids.length===0
        ? <p className="text-xs text-muted-foreground">{t("noBidsForOrder")}</p>
        : <div className="flex flex-col gap-2">
            {bids.map((b:any)=>{
              const mine = Boolean(b.is_mine);
              const price = toNum(b.price);
              const isLowest = price===lowest;
              return (
                <div key={b.id} className={`flex items-center gap-3 rounded-xl border p-3 ${mine?"border-primary bg-primary/5":"border-border bg-secondary/30"}`}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${mine?"bg-primary/15":"bg-secondary"}`}>
                    <Truck size={14} className={mine?"text-primary":"text-muted-foreground"}/>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <p className="text-sm font-medium text-foreground truncate">{mine?t("yourBid"):(b.driver?.full_name||"—")}</p>
                      {isLowest && <span className="text-[9px] bg-green-500/15 text-green-600 dark:text-green-400 px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide">{t("lowestBid")}</span>}
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground mt-0.5">
                      {b.driver?.car_model && <span className="truncate">{b.driver.car_model}</span>}
                      {toNum(b.driver?.rating)>0 && <span className="flex items-center gap-0.5"><Star size={9} className="text-amber-500 fill-amber-500"/>{toNum(b.driver.rating).toFixed(1)}</span>}
                    </div>
                  </div>
                  <p className={`text-sm font-bold font-mono ${mine?"text-primary":"text-foreground"}`}>{fmt(price)}</p>
                </div>
              );
            })}
          </div>}
    </div>
  );
}

function DriverApp({ themeMode, onThemeChange, lang, onLangChange, onLogout }: {
  themeMode:ThemeMode; onThemeChange:(m:ThemeMode)=>void;
  lang:Lang; onLangChange:(l:Lang)=>void; onLogout:()=>void;
}) {
  const { t } = useT();
  const { driverData, routes, feed, activeOrder, recentEarnings, netIncome, loading, reload } = useDriverData();
  const [tab,setTab]       = useState<DriverTab>("home");
  const [screen,setScreen] = useState<DriverScreen>("home");
  const [bidOrder,setBidOrder] = useState<BidOrder|null>(null);
  const [detailId,setDetailId] = useState<number|null>(null);
  const [period,setPeriod] = useState<"daily"|"monthly">("daily");
  const [orderTab,setOrderTab] = useState<"feed"|"history">("feed");
  const [busyAvail,setBusyAvail] = useState(false);
  const [busyStatus,setBusyStatus] = useState(false);

  const { data:notifData, loading:notifLoading, reload:reloadNotifs } = useAsync<any>(()=>getNotifications({ limit:50 }), [screen]);
  const notifs:any[] = notifData?.items ?? [];
  const unreadNotifs = notifs.filter(n=>!n.is_read).length;

  function goTo(s:DriverScreen){ setScreen(s); }
  function goBack(){ setScreen(tab); }
  function switchTab(t2:DriverTab){ setTab(t2); setScreen(t2); }

  const avail = driverData.available;
  const isApproved = driverData.status==="approved";
  const activeRoute = routes.find(r=>r.status==="active") ?? null;
  const isDetail = !["home","routes","orders","profile"].includes(screen);
  const hour = new Date().getHours();
  const greetKey: TKey = hour<12 ? "goodMorning" : hour<18 ? "goodAfternoon" : "goodEvening";

  const [actionErr,setActionErr] = useState("");
  async function toggleAvail(){
    if(!isApproved||busyAvail) return;
    setBusyAvail(true); setActionErr("");
    try { await setDriverAvailability(!avail); await reload(); } catch(e){ setActionErr(getUzbekErrorMessage(e)); } finally { setBusyAvail(false); }
  }
  const [routeBusy,setRouteBusy] = useState<number|null>(null);
  const [routeErr,setRouteErr] = useState("");
  const [confirmDelete,setConfirmDelete] = useState<number|null>(null);
  async function toggleRoute(r:{id:number;status:"active"|"inactive"}){
    if(routeBusy) return;
    setRouteBusy(r.id); setRouteErr("");
    try { await updateDriverRouteStatus(r.id, { status: r.status==="active" ? "unavailable" : "available" }); await reload(); }
    catch(e){ setRouteErr(getUzbekErrorMessage(e)); }
    finally { setRouteBusy(null); }
  }
  async function deleteRoute(id:number){
    if(routeBusy) return;
    setRouteBusy(id); setRouteErr("");
    try { await disableDriverRoute(id); setConfirmDelete(null); await reload(); }
    catch(e){ setRouteErr(getUzbekErrorMessage(e)); }
    finally { setRouteBusy(null); }
  }
  const nextStatus: DriverOrderAction|null = activeOrder
    ? (activeOrder.status==="accepted"?"picked_up":activeOrder.status==="picked_up"?"in_transit":activeOrder.status==="in_transit"?"delivered":null)
    : null;
  const nextStatusLabel = nextStatus==="picked_up"?t("pickedUp"):nextStatus==="in_transit"?t("inTransit"):nextStatus==="delivered"?t("markDelivered"):"";
  async function advanceStatus(){
    if(!activeOrder||!nextStatus||busyStatus) return;
    setBusyStatus(true); setActionErr("");
    try { await updateDriverOrderStatus(activeOrder.id, nextStatus); await reload(); goBack(); } catch(e){ setActionErr(getUzbekErrorMessage(e)); } finally { setBusyStatus(false); }
  }

  const chartData = recentEarnings.length
    ? recentEarnings.slice().reverse().map(e=>({ label:e.date||e.code, amount:e.net }))
    : [];
  const grossIncome = Math.round(netIncome/0.9);
  const commissionTotal = grossIncome-netIncome;

  return (
    <>
      {bidOrder && <BidSheet order={bidOrder} onSubmitted={reload} onClose={()=>setBidOrder(null)}/>}
      <div key={screen} className="flex-1 min-h-0 overflow-y-auto scrollbar-hide screen-in">

        {/* HOME */}
        {screen==="home" && (
          <div className="flex flex-col gap-4 p-4 pb-6">
            {/* Header: greeting + name with verified badge · income amount */}
            <div className="flex items-center justify-between pt-1 gap-3">
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">{t(greetKey)}</p>
                <div className="flex items-center gap-1.5">
                  <h1 className="font-display text-xl font-bold text-foreground truncate">{driverData.name.split(" ")[0]}</h1>
                  {isApproved
                    ? <SealCheck size={20} weight="fill" style={{color:"var(--success)"}} aria-label={t("verifiedDriver")}/>
                    : <SealWarning size={20} weight="fill" style={{color:"var(--warning)"}} aria-label={t("pendingVerification")}/>}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-none">
                <button onClick={()=>goTo("notifications")} aria-label={t("notifications")} className="relative w-11 h-11 rounded-xl bg-card border border-border flex items-center justify-center hover:border-primary/40 active:scale-[0.98] transition-all">
                  <Bell size={18} className="text-foreground"/>
                  {unreadNotifs>0 && <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-destructive flex items-center justify-center"><span className="text-[9px] font-bold text-white leading-none">{unreadNotifs>9?"9+":unreadNotifs}</span></span>}
                </button>
                <button onClick={()=>goTo("income")} aria-label={t("income")} className="flex items-center gap-2 bg-card border border-border rounded-xl px-3.5 py-2.5 hover:border-primary/40 active:scale-[0.98] transition-all">
                  <TrendingUp size={15} className="text-primary"/>
                  <p className="text-base font-bold text-foreground font-mono">{(driverData.netIncome/1_000_000).toFixed(2)}M</p>
                </button>
              </div>
            </div>

            {/* Map — active route only; no-route state when none is active */}
            <div className="relative rounded-2xl overflow-hidden h-44 bg-[#1a2234]">
              <div className="absolute inset-0">
                <RouteMap fromName={activeRoute?.from} toName={activeRoute?.to} height="100%"/>
              </div>
              <div className="absolute bottom-0 left-0 right-0 p-4 pointer-events-none">
                {activeRoute
                  ? <div className="flex items-center gap-2 text-sm font-medium text-white"><span className="w-2.5 h-2.5 rounded-full border-2 flex-none" style={{borderColor:"var(--feruza)",background:"transparent"}}/><span className="drop-shadow truncate">{activeRoute.from}</span><div className="flex-1 border-t border-dashed border-white/30"/><span className="drop-shadow truncate">{activeRoute.to}</span><span className="w-2.5 h-2.5 flex-none" style={{background:"var(--primary)",borderRadius:"50% 50% 50% 2px",transform:"rotate(45deg)"}}/></div>
                  : <p className="text-xs text-white/80 drop-shadow flex items-center gap-1.5"><Route size={13}/>{lang==="ru"?"Активный маршрут не выбран":lang==="en"?"No active route":"Faol yo'nalish yo'q"}</p>}
              </div>
            </div>

            {/* Recommended orders matching the active route */}
            <section>
              <div className="flex items-center justify-between mb-2 px-1">
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">{t("matchingOrders")}</p>
                {feed.length>0 && <button onClick={()=>switchTab("orders")} className="text-xs text-primary font-medium">{lang==="ru"?"Все":lang==="en"?"See all":"Barchasi"}</button>}
              </div>
              {feed.length===0
                ? <div className="rounded-2xl border border-dashed border-border bg-card/60 p-5 text-center">
                    <p className="text-xs text-muted-foreground">{activeRoute
                      ? (lang==="ru"?"По маршруту пока нет заказов":lang==="en"?"No orders on your route yet":"Yo'nalishingiz bo'yicha hozircha buyurtma yo'q")
                      : (lang==="ru"?"Добавьте маршрут, чтобы видеть заказы":lang==="en"?"Add a route to see orders":"Buyurtmalarni ko'rish uchun yo'nalish qo'shing")}</p>
                    {!activeRoute && <button onClick={()=>switchTab("routes")} className="mt-3 inline-flex items-center gap-1.5 bg-primary text-[var(--primary-foreground)] rounded-xl px-4 py-2 text-xs font-semibold active:scale-95 transition-transform"><Plus size={13}/>{t("addRoute")}</button>}
                  </div>
                : <div className="flex flex-col gap-3">
                    {feed.slice(0,3).map((o,i)=>(
                      <button key={o.id} onClick={()=>{setDetailId(o.id);goTo("order-detail");}} style={{animationDelay:`${Math.min(i*50,150)}ms`}}
                        className="w-full rounded-2xl border border-border bg-card p-3.5 text-left hover:border-primary/30 active:scale-[0.99] transition-all anim-rise" >
                        <div className="flex items-center gap-3">
                          <div className="flex flex-col items-center gap-1"><span className="w-2 h-2 rounded-full border-2 flex-none" style={{borderColor:"var(--feruza)",background:"var(--card)"}}/><span className="w-px h-5 bg-border"/><span className="w-2 h-2 flex-none" style={{background:"var(--primary)",borderRadius:"50% 50% 50% 2px",transform:"rotate(45deg)"}}/></div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5"><p className="text-sm font-semibold text-foreground truncate">{o.from}</p><ArrowRight size={13} className="text-primary flex-none"/><p className="text-sm font-semibold text-foreground truncate">{o.to}</p></div>
                            <p className="text-[11px] text-muted-foreground truncate mt-0.5">{o.pickup}{o.dropoff?` · ${o.dropoff}`:""}</p>
                          </div>
                          <div className="text-right flex-none"><p className="text-sm font-bold font-mono text-foreground">{(o.price/1000).toFixed(0)}K</p><p className="text-[9px] text-muted-foreground">so'm</p></div>
                        </div>
                      </button>
                    ))}
                  </div>}
            </section>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-3">
              {[{label:t("rating"),value:driverData.rating.toString()},{label:t("completed"),value:driverData.completedOrders.toString()},{label:t("total"),value:driverData.totalOrders.toString()}].map(({label,value})=>(
                <div key={label} className="rounded-2xl border border-border bg-card p-3 text-center"><p className="text-xl font-bold font-mono text-foreground">{value}</p><p className="text-[10px] text-muted-foreground mt-0.5">{label}</p></div>
              ))}
            </div>
          </div>
        )}

        {/* ROUTES */}
        {screen==="routes" && (
          <div className="flex flex-col gap-4 p-4 pb-6">
            <div className="flex items-center justify-between pt-1"><h1 className="text-xl font-semibold text-foreground">{t("myRoutes")}</h1><button onClick={()=>goTo("add-route")} className="flex items-center gap-1.5 bg-primary text-white rounded-xl px-3 py-2 text-sm font-medium"><Plus size={14}/>{t("addRoute")}</button></div>
            {routeErr && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1 px-1"><AlertCircle size={11}/>{routeErr}</p>}
            <p className="text-[11px] text-muted-foreground px-1 -mt-1">{lang==="ru"?"Маршрут можно включить/выключить — не нужно создавать заново.":lang==="en"?"Toggle a route on/off — no need to recreate it.":"Yo'nalishni yoqib/o'chirib qo'yish mumkin — qayta yaratish shart emas."}</p>
            {routes.length===0
              ?<EmptyState icon={Route} title={t("noRoutesYet")} desc={t("noRoutesDesc")} action={<button onClick={()=>goTo("add-route")} className="bg-primary text-white rounded-xl px-5 py-2.5 text-sm font-medium">{t("addFirstRoute")}</button>}/>
              :routes.map(r=>{
                const active = r.status==="active";
                return (
                <div key={r.id} className="rounded-2xl border border-border bg-card p-4">
                  <div className="flex items-center justify-between mb-3">
                    <StatusBadge status={r.status}/>
                    <div className="flex items-center gap-2">
                      <button onClick={()=>toggleRoute(r)} disabled={routeBusy===r.id} title={active?(lang==="ru"?"Деактивировать":lang==="en"?"Deactivate":"Faolsizlantirish"):(lang==="ru"?"Активировать":lang==="en"?"Activate":"Faollashtirish")} className="flex items-center gap-1.5 disabled:opacity-60">
                        <span className="text-[11px] font-medium text-muted-foreground">{active?(lang==="ru"?"Вкл":lang==="en"?"On":"Yoqilgan"):(lang==="ru"?"Выкл":lang==="en"?"Off":"O'chiq")}</span>
                        {routeBusy===r.id?<span className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin"/>:active?<ToggleRight size={30} className="text-primary"/>:<ToggleLeft size={30} className="text-muted-foreground"/>}
                      </button>
                      <button onClick={()=>setConfirmDelete(confirmDelete===r.id?null:r.id)} className="p-1.5 rounded-lg bg-red-500/10"><Trash2 size={13} className="text-red-600 dark:text-red-400"/></button>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex flex-col items-center gap-1"><span className="w-2.5 h-2.5 rounded-full border-2 flex-none" style={{borderColor:"var(--feruza)",background:"var(--card)"}}/><span className="w-0.5 h-8" style={{background:"repeating-linear-gradient(to bottom, var(--primary) 0 3px, transparent 3px 7px)",opacity:.6}}/><span className="w-2.5 h-2.5 flex-none" style={{background:"var(--primary)",borderRadius:"50% 50% 50% 2px",transform:"rotate(45deg)"}}/></div>
                    <div className="flex-1"><p className="text-sm font-semibold text-foreground">{r.from}</p>{r.fromDistrict&&<p className="text-xs text-muted-foreground">{r.fromDistrict}</p>}<div className="mt-2"><p className="text-sm font-semibold text-foreground">{r.to}</p>{r.toDistrict&&<p className="text-xs text-muted-foreground">{r.toDistrict}</p>}</div></div>
                  </div>
                  {confirmDelete===r.id && (
                    <div className="mt-3 pt-3 border-t border-border flex items-center gap-2">
                      <p className="text-xs text-red-600 dark:text-red-400 flex-1">{lang==="ru"?"Удалить маршрут?":lang==="en"?"Delete this route?":"Yo'nalish o'chirilsinmi?"}</p>
                      <button onClick={()=>setConfirmDelete(null)} className="text-xs px-3 py-1.5 rounded-lg border border-border bg-secondary text-foreground">{lang==="ru"?"Нет":lang==="en"?"No":"Yo'q"}</button>
                      <button onClick={()=>deleteRoute(r.id)} disabled={routeBusy===r.id} className="text-xs px-3 py-1.5 rounded-lg bg-red-500 text-white disabled:opacity-60">{routeBusy===r.id?"...":(lang==="ru"?"Удалить":lang==="en"?"Delete":"O'chirish")}</button>
                    </div>
                  )}
                </div>
                );
              })}
          </div>
        )}

        {/* ADD ROUTE */}
        {screen==="add-route" && <DriverAddRoute onBack={goBack} onSaved={()=>{ reload(); goBack(); }}/>}

        {/* ORDERS */}
        {screen==="orders" && (
          <div className="flex flex-col h-full">
            <div className="p-4 pt-5 pb-0"><h1 className="text-xl font-semibold text-foreground mb-4">{t("orders")}</h1>
              <div className="flex gap-1 bg-secondary rounded-xl p-1">{(["feed","history"] as const).map(tp=><button key={tp} onClick={()=>setOrderTab(tp)} className={`flex-1 py-2 rounded-lg text-xs font-medium transition-colors ${orderTab===tp?"bg-card text-foreground":"text-muted-foreground"}`}>{tp==="feed"?t("matchingOrders"):t("myHistory")}</button>)}</div>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-3">
              {orderTab==="feed" ? (
                feed.length===0
                  ?<EmptyState icon={Inbox} title={t("noOrdersYet")}/>
                  :feed.map(o=>(
                  <div key={o.id} className="rounded-2xl border border-border bg-card p-4 cursor-pointer hover:border-primary/30 transition-colors" onClick={()=>{setDetailId(o.id);goTo("order-detail");}}>
                    <div className="flex items-center justify-between mb-3"><span className="font-mono text-xs text-muted-foreground">{o.code}</span><StatusBadge status={o.status}/></div>
                    <div className="flex items-center gap-3 mb-3">
                      <div className="flex flex-col items-center gap-1"><div className="w-2 h-2 rounded-full bg-primary"/><div className="w-px h-6 bg-border"/><span className="w-2 h-2 flex-none" style={{background:"var(--feruza)",borderRadius:"50% 50% 50% 2px",transform:"rotate(45deg)"}}/></div>
                      <div className="flex-1"><p className="text-sm font-semibold text-foreground">{o.from}</p><p className="text-[11px] text-muted-foreground mb-1">{o.pickup}</p><p className="text-sm font-semibold text-foreground">{o.to}</p><p className="text-[11px] text-muted-foreground">{o.dropoff}</p></div>
                      <div className="text-right"><p className="text-base font-bold font-mono text-foreground">{(o.price/1000).toFixed(0)}K</p><p className="text-[10px] text-muted-foreground">so'm</p></div>
                    </div>
                    <div className="flex items-center justify-between pt-3 border-t border-border">
                      <span className="text-[11px] text-muted-foreground font-mono">{o.date}</span>
                      {o.hasBid
                        ?<div className="flex items-center gap-2">
                          <div className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400 text-xs"><CheckCircle2 size={12}/><span className="font-mono">{t("bid")}: {((o.bidPrice??0)/1000).toFixed(0)}K</span></div>
                          {(o.bidUpdatesLeft??0)>0 && <button className="text-primary text-xs font-medium" onClick={e=>{e.stopPropagation();setBidOrder(o);}}>{t("bidChangePrice")}</button>}
                        </div>
                        :<button className="flex items-center gap-1 bg-primary/15 text-primary border border-primary/20 rounded-lg px-3 py-1.5 text-xs font-medium" onClick={e=>{e.stopPropagation();setBidOrder(o);}}><Send size={11}/>{t("sendBid")}</button>}
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex flex-col gap-3">
                  {activeOrder && (
                    <div className="rounded-2xl border border-indigo-500/30 bg-indigo-500/5 p-4 cursor-pointer" onClick={()=>{setDetailId(activeOrder.id);goTo("order-detail");}}>
                      <div className="flex items-center justify-between mb-2"><span className="font-mono text-xs text-muted-foreground">{activeOrder.code}</span><StatusBadge status={activeOrder.status}/></div>
                      <p className="text-sm font-semibold text-foreground mb-1">{activeOrder.from} → {activeOrder.to}</p>
                      <div className="flex items-center justify-between mt-3 pt-3 border-t border-indigo-500/20">
                        <div className="flex gap-4 text-xs font-mono"><span className="text-muted-foreground">{t("gross")}: <span className="text-foreground">{(activeOrder.gross/1000).toFixed(0)}K</span></span><span className="text-muted-foreground">{t("net")}: <span className="text-green-600 dark:text-green-400">{(activeOrder.net/1000).toFixed(0)}K</span></span></div>
                        <ChevronRight size={14} className="text-muted-foreground"/>
                      </div>
                    </div>
                  )}
                  {recentEarnings.map(e=><div key={e.id} className="rounded-2xl border border-border bg-card p-4"><div className="flex items-center justify-between"><div><p className="text-sm font-semibold text-foreground">{e.from} → {e.to}</p><p className="text-[11px] text-muted-foreground font-mono">{e.code} · {e.date}</p></div><div className="text-right"><p className="text-sm font-bold text-green-600 dark:text-green-400 font-mono">+{(e.net/1000).toFixed(0)}K</p><p className="text-[10px] text-muted-foreground">{t("net")}</p></div></div></div>)}
                  {!activeOrder && recentEarnings.length===0 && <EmptyState icon={Package} title={t("noOrdersYet")}/>}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ORDER DETAIL */}
        {screen==="order-detail" && activeOrder && (
          <div className="flex flex-col h-full">
            <BackHeader onBack={goBack} title={activeOrder.code} right={<StatusBadge status={activeOrder.status}/>}/>
            <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
              <div className="rounded-2xl border border-border bg-card p-4">
                <div className="flex items-center gap-3"><div className="flex flex-col items-center gap-1"><div className="w-3 h-3 rounded-full bg-primary border-2 border-primary/40"/><div className="w-px h-10 bg-border"/><span className="w-3 h-3 flex-none" style={{background:"var(--primary)",borderRadius:"50% 50% 50% 2px",transform:"rotate(45deg)"}}/></div><div className="flex-1"><div className="mb-3"><p className="text-sm font-bold text-foreground">{activeOrder.from}</p><p className="text-xs text-muted-foreground">{activeOrder.pickup}</p></div><div><p className="text-sm font-bold text-foreground">{activeOrder.to}</p><p className="text-xs text-muted-foreground">{activeOrder.dropoff}</p></div></div></div>
              </div>
              {(toNum(activeOrder.pickupLat)!==0 || toNum(activeOrder.dropoffLat)!==0) && (
                <div className="rounded-2xl border border-border bg-card overflow-hidden">
                  <div className="h-44"><MapView pickupLat={activeOrder.pickupLat} pickupLng={activeOrder.pickupLng} dropoffLat={activeOrder.dropoffLat} dropoffLng={activeOrder.dropoffLng} height="100%"/></div>
                  {(()=>{ const url=mapsDirectionsUrl(activeOrder.pickupLat,activeOrder.pickupLng,activeOrder.dropoffLat,activeOrder.dropoffLng); return url && (
                    <a href={url} target="_blank" rel="noopener noreferrer"
                      className="flex items-center justify-center gap-2 border-t border-border bg-primary/5 py-3 text-sm font-semibold text-primary active:bg-primary/10 transition-colors">
                      <Navigation size={16}/>{t("openInMaps")}
                    </a>
                  ); })()}
                </div>
              )}
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs text-muted-foreground mb-3 uppercase tracking-wide">{t("statusProgress")}</p>
                {(()=>{ const sf=[{key:"accepted",label:t("accepted")},{key:"picked_up",label:t("pickedUp")},{key:"in_transit",label:t("inTransit")},{key:"delivered",label:t("delivered")}]; const ci=sf.findIndex(s=>s.key===activeOrder.status);
                  return (<><div className="flex items-center gap-1">{sf.map((s,i)=><div key={s.key} className="flex items-center flex-1"><div className={`w-3 h-3 rounded-full border-2 flex-shrink-0 ${i<=ci?"bg-primary border-primary":"bg-secondary border-border"}`}/>{i<sf.length-1&&<div className={`flex-1 h-0.5 ${i<ci?"bg-primary":"bg-border"}`}/>}</div>)}</div><div className="flex justify-between mt-2">{sf.map(s=><p key={s.key} className="text-[8px] text-muted-foreground font-mono">{s.label}</p>)}</div></>);
                })()}
              </div>
              <DriverOrderBids orderId={detailId ?? activeOrder.id}/>
              <div className="rounded-2xl border border-border bg-card p-4 flex flex-col gap-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">{t("contactDetails")}</p>
                {activeOrder.cargoType && (
                  <div className="flex items-start gap-3"><Package size={14} className="text-muted-foreground mt-0.5"/><div><p className="text-[10px] text-muted-foreground">{lang==="ru"?"Тип отправления":lang==="en"?"Parcel type":"Jo'natma turi"}</p><p className="text-sm text-foreground">{cargoTypeLabel(activeOrder.cargoType, lang)}</p></div></div>
                )}
                {[{icon:Phone,label:t("sender"),value:activeOrder.sender},{icon:Phone,label:t("receiver"),value:activeOrder.receiver},{icon:FileText,label:t("comment"),value:activeOrder.comment}].map(({icon:Icon,label,value})=>(
                  <div key={label} className="flex items-start gap-3"><Icon size={14} className="text-muted-foreground mt-0.5"/><div><p className="text-[10px] text-muted-foreground">{label}</p><p className="text-sm text-foreground font-mono">{value||"—"}</p></div></div>
                ))}
              </div>
              <div className="rounded-2xl border border-green-500/20 bg-green-500/5 p-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-3">{t("incomeReport")}</p>
                <div className="flex flex-col gap-2">
                  {[{label:t("grossAmount"),value:fmt(activeOrder.gross),cls:"text-foreground"},{label:t("systemFee"),value:`−${fmt(activeOrder.commission)}`,cls:"text-red-600 dark:text-red-400"},{label:t("netIncome"),value:fmt(activeOrder.net),cls:"text-green-600 dark:text-green-400 text-base font-bold"}].map(({label,value,cls})=>(
                    <div key={label} className="flex items-center justify-between"><span className="text-xs text-muted-foreground">{label}</span><span className={`text-sm font-mono ${cls}`}>{value}</span></div>
                  ))}
                </div>
              </div>
              {actionErr && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1 px-1"><AlertCircle size={11}/>{actionErr}</p>}
              {nextStatus && <button onClick={advanceStatus} disabled={busyStatus} className="w-full bg-primary text-white rounded-2xl py-3.5 text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-70">{busyStatus?<span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:nextStatusLabel}</button>}
            </div>
          </div>
        )}

        {/* INCOME */}
        {screen==="income" && (
          <div className="flex flex-col h-full">
            <BackHeader onBack={goBack} title={t("income")}/>
            <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
              <div className="rounded-2xl border border-primary/20 bg-primary/5 p-5">
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">{t("netIncome")}</p>
                <p className="text-3xl font-bold font-mono text-foreground">{(netIncome/1_000_000).toFixed(2)}M so'm</p>
                <p className="text-xs text-muted-foreground mt-1">{t("afterCommission")}</p>
                <div className="flex gap-4 mt-4 pt-4 border-t border-primary/10"><div><p className="text-[10px] text-muted-foreground">{t("gross")}</p><p className="text-sm font-mono text-foreground">{fmt(grossIncome)}</p></div><div><p className="text-[10px] text-muted-foreground">{t("commission")}</p><p className="text-sm font-mono text-red-600 dark:text-red-400">−{fmt(commissionTotal)}</p></div></div>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <div className="flex items-center justify-between mb-4"><p className="text-sm font-semibold text-foreground">{t("earningsChart")}</p><div className="flex gap-1 bg-secondary rounded-lg p-0.5">{(["daily","monthly"] as const).map(p=><button key={p} onClick={()=>setPeriod(p)} className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${period===p?"bg-card text-foreground":"text-muted-foreground"}`}>{p==="daily"?t("sevenDays"):t("sixMonths")}</button>)}</div></div>
                {chartData.length===0
                  ?<div className="h-[140px] flex items-center justify-center text-xs text-muted-foreground">{t("noOrdersYet")}</div>
                  :<ResponsiveContainer width="100%" height={140}>
                    <BarChart data={chartData} barSize={24}>
                      <XAxis dataKey="label" tick={{fontSize:10,fill:"#8b949e",fontFamily:"JetBrains Mono"}} axisLine={false} tickLine={false}/>
                      <YAxis hide/>
                      <Tooltip contentStyle={{background:"#161b22",border:"1px solid rgba(255,255,255,0.08)",borderRadius:10,fontSize:11}} labelStyle={{color:"#8b949e"}} itemStyle={{color:"#f0f2f5",fontFamily:"JetBrains Mono"}} formatter={(v:number)=>[`${(v/1000).toFixed(0)}K so'm`,t("net")]}/>
                      <Bar dataKey="amount" fill="var(--primary)" radius={[6,6,0,0]}/>
                    </BarChart>
                  </ResponsiveContainer>}
              </div>
              <div><p className="text-xs text-muted-foreground uppercase tracking-wide mb-3">{t("recentEarnings")}</p><div className="flex flex-col gap-2">{recentEarnings.map(e=><div key={e.id} className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3"><div><p className="text-sm font-semibold text-foreground">{e.from} → {e.to}</p><p className="text-[11px] text-muted-foreground font-mono">{e.code} · {e.date}</p></div><p className="text-sm font-bold text-green-600 dark:text-green-400 font-mono">+{(e.net/1000).toFixed(0)}K</p></div>)}</div></div>
            </div>
          </div>
        )}

        {/* DOCUMENTS */}
        {screen==="documents" && <DriverDocuments data={driverData} onBack={goBack} onUploaded={reload}/>}

        {/* EDIT PROFILE */}
        {screen==="edit-profile" && <DriverEditProfile data={driverData} onBack={goBack} onSaved={()=>{ reload(); goBack(); }}/>}

        {/* SETTINGS */}
        {screen==="settings" && <SettingsPanel onBack={goBack} themeMode={themeMode} onThemeChange={onThemeChange} lang={lang} onLangChange={onLangChange} onLogout={onLogout} notifKeys={{a:"orderUpdates",ad:"orderUpdatesDesc",b:"bidAlerts",bd:"bidAlertsDesc"}}/>}
        {screen==="notifications" && <ClientNotificationsScreen notifs={notifs} loading={notifLoading} reload={reloadNotifs} onBack={goBack}/>}

        {/* PROFILE */}
        {screen==="profile" && (
          <div className="flex flex-col gap-4 p-4 pb-6">
            <h1 className="font-display text-[22px] font-extrabold text-foreground pt-1">{t("profile")}</h1>
            <div className="rounded-2xl bg-card p-5" style={{boxShadow:"var(--shadow-card)"}}>
              <div className="flex items-center gap-4 mb-4"><div className="w-16 h-16 rounded-2xl bg-primary/15 flex items-center justify-center"><Truck size={28} className="text-primary"/></div><div className="flex-1 min-w-0"><h2 className="text-lg font-bold text-foreground truncate">{driverData.name}</h2><p className="text-sm text-muted-foreground font-mono">{driverData.phone}</p><div className="flex gap-2 mt-1"><StatusBadge status={driverData.status}/><StatusBadge status={avail?"active":"inactive"}/></div></div></div>
              <div className="grid grid-cols-3 gap-3 pt-4 border-t border-border">{[{label:t("rating"),value:driverData.rating.toString()},{label:t("completed"),value:driverData.completedOrders.toString()},{label:t("total"),value:driverData.totalOrders.toString()}].map(({label,value})=><div key={label} className="text-center"><p className="text-lg font-bold font-mono text-foreground">{value}</p><p className="text-[10px] text-muted-foreground">{label}</p></div>)}</div>
            </div>
            <div className="rounded-2xl bg-card p-4" style={{boxShadow:"var(--shadow-card)"}}><div className="flex items-center justify-between"><div><p className="text-sm font-semibold text-foreground">{t("availability")}</p><p className="text-xs text-muted-foreground">{avail?t("youAreOnline"):t("youAreOffline")}</p></div><button onClick={toggleAvail} className={!isApproved||busyAvail?"opacity-40 cursor-not-allowed":""}>{avail?<ToggleRight size={36} className="text-primary"/>:<ToggleLeft size={36} className="text-muted-foreground"/>}</button></div>{actionErr && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1 mt-2"><AlertCircle size={11}/>{actionErr}</p>}</div>
            <div className="rounded-2xl bg-card p-4" style={{boxShadow:"var(--shadow-card)"}}>
              <div className="flex items-center gap-2 mb-3"><Truck size={16} className="text-primary"/><p className="text-sm font-semibold text-foreground">{t("vehicle")}</p><StatusBadge status={driverData.status}/></div>
              <div className="flex flex-col gap-2">{[{label:t("carModel"),value:driverData.car.model},{label:t("carColor"),value:driverData.car.color},{label:t("plateNumber"),value:driverData.car.plate}].map(({label,value})=><div key={label} className="flex justify-between"><span className="text-xs text-muted-foreground">{label}</span><span className="text-xs font-mono text-foreground">{value}</span></div>)}</div>
            </div>
            <div className="rounded-2xl bg-card overflow-hidden" style={{boxShadow:"var(--shadow-card)"}}>
              {[{icon:Pencil,label:t("editProfile"),action:()=>goTo("edit-profile")},{icon:FileText,label:t("documents"),action:()=>goTo("documents")},{icon:Route,label:t("myRoutes"),action:()=>switchTab("routes")},{icon:Package,label:t("orders"),action:()=>switchTab("orders")},{icon:TrendingUp,label:t("income"),action:()=>goTo("income")},{icon:Settings,label:t("settings"),action:()=>goTo("settings")}].map(({icon:Icon,label,action},i)=>(
                <button key={label} onClick={action} className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-secondary/50 transition-colors ${i>0?"border-t border-border":""}`}><IconTile icon={Icon} size={15}/><span className="text-sm text-foreground flex-1 text-left">{label}</span><ChevronRight size={16} className="text-muted-foreground"/></button>
              ))}
              <button onClick={onLogout} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-destructive/5 transition-colors border-t border-border"><IconTile icon={LogOut} size={15} tone="danger"/><span className="text-sm text-destructive flex-1 text-left">{t("logOut")}</span></button>
            </div>
          </div>
        )}
      </div>

      {loading && screen==="home" && <div className="absolute top-2 right-2 z-40"><span className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin inline-block"/></div>}

      {/* Driver bottom nav — floating dark pill with a raised center action */}
      {!isDetail && (
        <div className="flex-shrink-0 px-5 pt-3 pb-6">
          <div className="flex items-center justify-between rounded-full bg-card border border-border px-3 py-2" style={{boxShadow:"var(--shadow-pop)"}}>
            {([{id:"home" as DriverTab,icon:Home,label:t("home")},{id:"routes" as DriverTab,icon:Route,label:t("myRoutes")}]).map(({id,icon:Icon,label})=>{
              const active=tab===id&&screen===id;
              return <button key={id} onClick={()=>switchTab(id)} aria-label={label} className={`w-11 h-11 rounded-full flex items-center justify-center transition-colors ${active?"bg-primary":"hover:bg-secondary"}`}><Icon size={21} className={active?"text-[var(--primary-foreground)]":"text-muted-foreground"}/></button>;
            })}
            <button onClick={()=>goTo("add-route")} aria-label={t("addRoute")} className="w-14 h-14 rounded-full bg-primary flex items-center justify-center shadow-lg shadow-primary/40 active:scale-95 transition-transform"><Plus size={26} className="text-white"/></button>
            {([{id:"orders" as DriverTab,icon:Inbox,label:t("orders")},{id:"profile" as DriverTab,icon:User,label:t("profile")}]).map(({id,icon:Icon,label})=>{
              const active=tab===id&&screen===id;
              return <button key={id} onClick={()=>switchTab(id)} aria-label={label} className={`w-11 h-11 rounded-full flex items-center justify-center transition-colors ${active?"bg-primary":"hover:bg-secondary"}`}><Icon size={21} className={active?"text-[var(--primary-foreground)]":"text-muted-foreground"}/></button>;
            })}
          </div>
        </div>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ADMIN PANEL
// ═══════════════════════════════════════════════════════════════════════════════


// ── Admin Shared Components ───────────────────────────────────────────────────

function AdminStatusBadge({ status }: { status: string }) {
  const map: Record<string,string> = {
    published: "bg-blue-100 text-blue-700 border-blue-200",
    bidding:   "bg-amber-100 text-amber-700 border-amber-200",
    accepted:  "bg-blue-100 text-blue-800 border-blue-200",
    in_transit:"bg-indigo-100 text-indigo-700 border-indigo-200",
    delivered: "bg-green-100 text-green-700 border-green-200",
    confirmed: "bg-emerald-100 text-emerald-700 border-emerald-200",
    cancelled: "bg-red-100 text-red-700 border-red-200",
    disputed:  "bg-rose-100 text-rose-700 border-rose-200",
    approved:  "bg-green-100 text-green-700 border-green-200",
    pending:   "bg-amber-100 text-amber-700 border-amber-200",
    rejected:  "bg-red-100 text-red-700 border-red-200",
    blocked:   "bg-slate-100 text-slate-600 border-slate-200",
    new:       "bg-slate-100 text-slate-600 border-slate-200",
    active:    "bg-green-100 text-green-700 border-green-200",
    inactive:  "bg-slate-100 text-slate-500 border-slate-200",
    open:      "bg-rose-100 text-rose-700 border-rose-200",
    in_review: "bg-amber-100 text-amber-700 border-amber-200",
    resolved:  "bg-green-100 text-green-700 border-green-200",
    completed: "bg-emerald-100 text-emerald-700 border-emerald-200",
    super_admin:"bg-purple-100 text-purple-700 border-purple-200",
    admin:     "bg-blue-100 text-blue-700 border-blue-200",
    operator:  "bg-slate-100 text-slate-600 border-slate-200",
    system:    "bg-slate-100 text-slate-500 border-slate-200",
    push:      "bg-blue-100 text-blue-600 border-blue-200",
    email:     "bg-violet-100 text-violet-600 border-violet-200",
  };
  const cls = map[status] ?? "bg-slate-100 text-slate-600 border-slate-200";
  const label = status.replace(/_/g," ").replace(/\b\w/g, l=>l.toUpperCase());
  return <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border uppercase tracking-wide ${cls}`}>{label}</span>;
}

function AdminMetricCard({ title, value, sub, icon: Icon, color, onClick }: {
  title:string; value:string; sub?:string; icon:typeof Home; color:string; onClick?:()=>void;
}) {
  return (
    <div onClick={onClick} className={`bg-card border border-slate-200 rounded-lg p-4 flex items-start gap-3 ${onClick?"cursor-pointer hover:shadow-md hover:border-blue-200":""} transition-all`}>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${color}`}>
        <Icon size={18}/>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-0.5">{title}</p>
        <p className="text-xl font-bold text-slate-900 font-mono leading-tight">{value}</p>
        {sub && <p className="text-[11px] text-slate-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function AdminTableWrapper({ children, className="" }: { children:React.ReactNode; className?:string }) {
  return (
    <div className={`overflow-x-auto rounded-lg border border-slate-200 bg-card${className}`}>
      <table className="min-w-full text-sm">{children}</table>
    </div>
  );
}

function AdminTh({ children }: { children:React.ReactNode }) {
  return <th className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-slate-500 text-left bg-slate-50 border-b border-slate-200 whitespace-nowrap">{children}</th>;
}
function AdminTd({ children, className="", onClick }: { children:React.ReactNode; className?:string; onClick?:(e:React.MouseEvent<HTMLTableCellElement>)=>void }) {
  return <td onClick={onClick} className={`px-4 py-2.5 text-slate-700 border-b border-slate-100 whitespace-nowrap ${className}`}>{children}</td>;
}

function AdminSearchBar({ placeholder, value, onChange }: { placeholder:string; value:string; onChange:(v:string)=>void }) {
  return (
    <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
      <Search size={14} className="text-slate-400 flex-shrink-0"/>
      <input className="flex-1 bg-transparent text-sm text-slate-700 placeholder:text-slate-400 outline-none min-w-0"
        placeholder={placeholder} value={value} onChange={e=>onChange(e.target.value)}/>
    </div>
  );
}

function AdminActionBtn({ label, onClick, variant="default", icon:Icon }: {
  label:string; onClick?:()=>void; variant?:"default"|"approve"|"reject"|"block"|"danger"; icon?:typeof Eye;
}) {
  const cls = {
    default:"border-slate-200 text-slate-600 hover:bg-slate-50",
    approve:"border-green-200 text-green-700 hover:bg-green-50",
    reject: "border-orange-200 text-orange-700 hover:bg-orange-50",
    block:  "border-red-200 text-red-700 hover:bg-red-50",
    danger: "border-red-200 text-red-700 hover:bg-red-50",
  }[variant];
  return (
    <button onClick={onClick} title={label} className={`inline-flex items-center gap-1 px-2 py-1 rounded border text-[11px] font-medium transition-colors ${cls}`}>
      {Icon && <Icon size={11}/>}{label}
    </button>
  );
}

// ── Admin Drawer ──────────────────────────────────────────────────────────────

function AdminDrawer({ title, onClose, children }: { title:string; onClose:()=>void; children:React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/30 backdrop-blur-sm" onClick={onClose}/>
      <div className="w-[420px] bg-card h-full shadow-2xl flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 flex-shrink-0">
          <h2 className="text-base font-semibold text-slate-800">{title}</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors"><X size={16} className="text-slate-500"/></button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

// ── Admin Modal ───────────────────────────────────────────────────────────────

function AdminModal({ title, onClose, onSubmit, submitLabel, submitVariant="primary", error, busy, children }: {
  title:string; onClose:()=>void; onSubmit?:()=>void; submitLabel?:string; submitVariant?:"primary"|"danger"; error?:string; busy?:boolean; children:React.ReactNode;
}) {
  const { t } = useT();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose}/>
      <div className="relative bg-card rounded-xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-800">{title}</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={16} className="text-slate-500"/></button>
        </div>
        <div className="p-5 flex flex-col gap-4">{children}</div>
        {error && <p className="px-5 pb-1 -mt-1 text-sm text-red-600">{error}</p>}
        {onSubmit && (
          <div className="flex gap-3 px-5 py-4 border-t border-slate-200">
            <button onClick={onClose} className="flex-1 border border-slate-200 rounded-lg py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50">{t("bidSheetCancel")}</button>
            <button onClick={onSubmit} disabled={busy} className={`flex-[2] rounded-lg py-2.5 text-sm font-semibold text-white disabled:opacity-60 ${submitVariant==="danger"?"bg-red-600 hover:bg-red-700":"bg-primary hover:bg-blue-700"}`}>{submitLabel ?? t("submitDispute")}</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Admin Dashboard ───────────────────────────────────────────────────────────

function AdminDashboard({ onNav }: { onNav:(s:AdminSection)=>void }) {
  const { t } = useT();
  const fm = (n:number) => (n/1_000_000).toFixed(2)+"M so'm";
  const fk = (n:number) => (n/1_000).toFixed(0)+"K so'm";
  const { data:ov, loading } = useAsync<any>(()=>getAdminOverview(), []);
  const adminMetrics = overviewToMetrics(ov);
  const adminOrders = ((ov?.orders ?? []) as any[]).map(mapOrderRow);
  const adminDrivers = ((ov?.drivers ?? []) as any[]).map(mapDriverRow);
  const adminDisputes = ((ov?.disputes ?? []) as any[]).map(mapDisputeRow);
  const adminAuditLog = ((ov?.audits ?? []) as any[]).map(mapAuditRow);
  if (loading && !ov) return <div className="p-6 flex items-center justify-center h-64"><span className="w-8 h-8 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin"/></div>;
  return (
    <div className="p-6 space-y-6">
      {/* Financial metrics */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">{t("admFinancialOverview")}</p>
        <div className="grid grid-cols-4 gap-4">
          <AdminMetricCard title={t("admTotalRevenue")}    value={fm(adminMetrics.totalRevenue)}    icon={DollarSign}   color="bg-blue-50 text-blue-600"/>
          <AdminMetricCard title={t("admPlatformProfit")}  value={fm(adminMetrics.platformProfit)}  icon={TrendingUp}   color="bg-blue-50 text-blue-600" sub={`${t("admToday")}: ${fk(adminMetrics.todayProfit)}`}/>
          <AdminMetricCard title={t("admDriverEarnings")}  value={fm(adminMetrics.driverEarnings)}  icon={Truck}        color="bg-blue-50 text-blue-600"/>
          <AdminMetricCard title={t("admAvgOrderValue")}  value={fk(adminMetrics.avgOrderValue)}   icon={Activity}     color="bg-blue-50 text-blue-600"/>
        </div>
      </div>

      {/* Operations metrics */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">{t("admOperations")}</p>
        <div className="grid grid-cols-4 gap-4">
          <AdminMetricCard title={t("admTotalOrders")}      value={adminMetrics.totalOrders.toString()}      icon={Package}    color="bg-slate-100 text-slate-600" onClick={()=>onNav("orders")}/>
          <AdminMetricCard title={t("admActiveDeliveries")} value={adminMetrics.activeDeliveries.toString()} icon={Navigation} color="bg-blue-50 text-blue-600" onClick={()=>onNav("orders")}/>
          <AdminMetricCard title={t("admPendingDrivers")}   value={adminMetrics.pendingDrivers.toString()}   icon={Clock}      color="bg-amber-50 text-amber-600"   onClick={()=>onNav("drivers")}/>
          <AdminMetricCard title={t("admOpenDisputes")}     value={adminMetrics.openDisputes.toString()}     icon={Flag}       color="bg-rose-50 text-rose-600"     onClick={()=>onNav("disputes")}/>
          <AdminMetricCard title={t("admPublishedBidding")} value={adminMetrics.publishedBidding.toString()} icon={CircleDot}  color="bg-blue-50 text-blue-600"     onClick={()=>onNav("orders")}/>
          <AdminMetricCard title={t("admApprovedDrivers")}  value={adminMetrics.approvedDrivers.toString()}  icon={UserCheck}  color="bg-green-50 text-green-600"   onClick={()=>onNav("drivers")}/>
          <AdminMetricCard title={t("admActiveTariffs")}    value={adminMetrics.activeTariffs.toString()}    icon={Tag}        color="bg-blue-50 text-blue-600"     onClick={()=>onNav("tariffs")}/>
          <AdminMetricCard title={t("admMissingTariffs")}   value={adminMetrics.missingTariffs.toString()}   icon={AlertCircle}color="bg-red-50 text-red-600"       onClick={()=>onNav("tariffs")}/>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Recent orders */}
        <div className="col-span-2 bg-card border border-slate-200 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <p className="text-sm font-semibold text-slate-800">{t("admRecentOrders")}</p>
            <button onClick={()=>onNav("orders")} className="text-xs text-blue-600 hover:underline flex items-center gap-1">{t("admViewAll")} <ChevronRight size={12}/></button>
          </div>
          <AdminTableWrapper>
            <thead><tr><AdminTh>{t("admOrder")}</AdminTh><AdminTh>{t("admRoute")}</AdminTh><AdminTh>{t("admClient")}</AdminTh><AdminTh>{t("admStatus")}</AdminTh><AdminTh>{t("admPrice")}</AdminTh></tr></thead>
            <tbody>
              {adminOrders.slice(0,6).map(o=>(
                <tr key={o.id} className="hover:bg-slate-50">
                  <AdminTd><span className="font-mono text-xs text-slate-500">{o.code}</span></AdminTd>
                  <AdminTd><span className="font-medium">{o.from}</span><span className="text-slate-400 mx-1">→</span>{o.to}</AdminTd>
                  <AdminTd>{o.client}</AdminTd>
                  <AdminTd><AdminStatusBadge status={o.status}/></AdminTd>
                  <AdminTd><span className="font-mono text-xs">{(o.price/1000).toFixed(0)}K</span></AdminTd>
                </tr>
              ))}
            </tbody>
          </AdminTableWrapper>
        </div>

        {/* Right panels */}
        <div className="flex flex-col gap-4">
          {/* Driver queue */}
          <div className="bg-card border border-slate-200 rounded-lg overflow-hidden flex-1">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
              <p className="text-sm font-semibold text-slate-800">{t("admVerificationQueue")}</p>
              <button onClick={()=>onNav("drivers")} className="text-xs text-blue-600 hover:underline"><ChevronRight size={12}/></button>
            </div>
            <div className="divide-y divide-slate-100">
              {adminDrivers.filter(d=>d.status==="pending").map(d=>(
                <div key={d.id} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="w-7 h-7 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0"><Truck size={12} className="text-amber-600"/></div>
                  <div className="flex-1 min-w-0"><p className="text-xs font-medium text-slate-800 truncate">{d.name}</p><p className="text-[10px] text-slate-400 font-mono">{d.docs}/5 {t("admDocsShort")}</p></div>
                  <AdminStatusBadge status={d.status}/>
                </div>
              ))}
            </div>
          </div>

          {/* Disputes */}
          <div className="bg-card border border-slate-200 rounded-lg overflow-hidden flex-1">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
              <p className="text-sm font-semibold text-slate-800">{t("admOpenDisputes")}</p>
              <button onClick={()=>onNav("disputes")} className="text-xs text-blue-600 hover:underline"><ChevronRight size={12}/></button>
            </div>
            <div className="divide-y divide-slate-100">
              {adminDisputes.filter(d=>d.status==="open"||d.status==="in_review").map(d=>(
                <div key={d.id} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="w-7 h-7 rounded-full bg-rose-100 flex items-center justify-center flex-shrink-0"><Flag size={12} className="text-rose-600"/></div>
                  <div className="flex-1 min-w-0"><p className="text-xs font-medium text-slate-800 truncate">{d.orderId}</p><p className="text-[10px] text-slate-400">{d.reason}</p></div>
                  <AdminStatusBadge status={d.status}/>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Recent audit */}
      <div className="bg-card border border-slate-200 rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
          <p className="text-sm font-semibold text-slate-800">{t("admRecentActivity")}</p>
          <button onClick={()=>onNav("audit")} className="text-xs text-blue-600 hover:underline flex items-center gap-1">{t("admViewLog")} <ChevronRight size={12}/></button>
        </div>
        <AdminTableWrapper>
          <thead><tr><AdminTh>{t("admActor")}</AdminTh><AdminTh>{t("admRole")}</AdminTh><AdminTh>{t("admAction")}</AdminTh><AdminTh>{t("admEntity")}</AdminTh><AdminTh>{t("admTime")}</AdminTh></tr></thead>
          <tbody>
            {adminAuditLog.slice(0,5).map(l=>(
              <tr key={l.id} className="hover:bg-slate-50">
                <AdminTd><span className="font-medium">{l.actor}</span></AdminTd>
                <AdminTd><AdminStatusBadge status={l.role}/></AdminTd>
                <AdminTd><span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded">{l.action}</span></AdminTd>
                <AdminTd><span className="text-slate-500">{l.entity}</span> <span className="font-mono text-xs text-slate-400">#{l.entityId}</span></AdminTd>
                <AdminTd><span className="text-slate-400 text-xs">{l.created}</span></AdminTd>
              </tr>
            ))}
          </tbody>
        </AdminTableWrapper>
      </div>
    </div>
  );
}

// ── Admin Orders ──────────────────────────────────────────────────────────────

function AdminOrderBids({ orderId }: { orderId:number }) {
  const { t } = useT();
  const { data, loading } = useAsync<any[]>(()=>getAdminOrderBids(orderId), [orderId]);
  const bids = data ?? [];
  if(loading) return <div className="py-4 text-center"><span className="w-5 h-5 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin inline-block"/></div>;
  if(!bids.length) return <p className="text-xs text-slate-400 text-center py-4">{t("admNoBids")}</p>;
  return (
    <div className="space-y-2">
      {bids.map((b: any)=>(
        <div key={b.id} className={`flex items-center gap-3 p-3 rounded-lg border ${b.status==="accepted"?"border-green-200 bg-green-50":"border-slate-200"}`}>
          <div className="flex-1"><p className="text-sm font-medium text-slate-800">{b.driver_name||b.driver?.full_name||"—"}</p><p className="text-[11px] text-slate-400 font-mono">{b.car_model||b.plate_number||""}</p></div>
          <span className="text-sm font-bold font-mono text-slate-800">{(toNum(b.price)/1000).toFixed(0)}K</span>
          {b.status==="accepted" && <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">{t("admSelected")}</span>}
        </div>
      ))}
    </div>
  );
}

function AdminOrders() {
  const { t } = useT();
  const orderTabLabels: Record<string,TKey> = { all:"admTabAll", published:"admTabPublished", bidding:"admTabBidding", accepted:"admTabAccepted", in_transit:"admTabInTransit", delivered:"admTabDelivered", confirmed:"admTabConfirmed", cancelled:"admTabCancelled", disputed:"admTabDisputed" };
  const [tab,setTab] = useState<string>("all");
  const [search,setSearch] = useState("");
  const { data, reload } = useAsync<any>(()=>getAdminOrders({ limit:100 }), []);
  const adminOrders = ((data?.items ?? []) as any[]).map(mapOrderRow);
  const [drawer,setDrawer] = useState<ReturnType<typeof mapOrderRow>|null>(null);
  const [modal,setModal] = useState<"assign"|"status"|"cancel"|null>(null);
  const [drawerTab,setDrawerTab] = useState("overview");
  const [form,setForm] = useState<{driverId:string;price:string;status:string;reason:string}>({driverId:"",price:"",status:"",reason:""});
  const [busy,setBusy] = useState(false);
  const [err,setErr] = useState("");

  async function doAction(){
    if(!drawer) return;
    setBusy(true); setErr("");
    try {
      if(modal==="assign") await manualAssignDriver(drawer.id,{driver_id:Number(form.driverId),final_price:Number(form.price),reason:form.reason||"Admin tomonidan biriktirildi"});
      else if(modal==="status") await manualUpdateOrderStatus(drawer.id,{status:form.status,reason:form.reason||"Admin tomonidan o'zgartirildi"});
      else if(modal==="cancel") await cancelAdminOrder(drawer.id,{reason:form.reason||"Admin tomonidan bekor qilindi"});
      setModal(null); setDrawer(null); setForm({driverId:"",price:"",status:"",reason:""}); reload();
    } catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); }
  }

  const tabs = ["all","published","bidding","accepted","in_transit","delivered","confirmed","cancelled","disputed"];
  const filtered = adminOrders.filter((o: any)=>(tab==="all"||o.status===tab) && (search===""||o.code.includes(search)||o.client.toLowerCase().includes(search.toLowerCase())||o.driver.toLowerCase().includes(search.toLowerCase())));

  return (
    <div className="p-6 space-y-5">
      {drawer && (
        <AdminDrawer title={`${t("admOrderPrefix")} ${drawer.code}`} onClose={()=>setDrawer(null)}>
          {modal==="assign" && (
            <AdminModal title={t("admAssignDriver")} onClose={()=>{setModal(null);setErr("");}} onSubmit={doAction} submitLabel={busy?"...":t("admAssignDriver")} error={err} busy={busy}>
              <div><label className="text-xs font-medium text-slate-600 block mb-1.5">{t("admDriverId")}</label><input value={form.driverId} onChange={e=>setForm(f=>({...f,driverId:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder="e.g. 3"/></div>
              <div><label className="text-xs font-medium text-slate-600 block mb-1.5">{t("admFinalPrice")}</label><input value={form.price} onChange={e=>setForm(f=>({...f,price:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder="e.g. 145000"/></div>
              <div><label className="text-xs font-medium text-slate-600 block mb-1.5">{t("admReasonRequired")}</label><textarea value={form.reason} onChange={e=>setForm(f=>({...f,reason:e.target.value}))} rows={2} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none resize-none" placeholder={t("admAssignReasonPh")}/></div>
            </AdminModal>
          )}
          {modal==="status" && (
            <AdminModal title={t("admChangeStatus")} onClose={()=>{setModal(null);setErr("");}} onSubmit={doAction} submitLabel={busy?"...":t("admUpdateStatus")} error={err} busy={busy}>
              <div><label className="text-xs font-medium text-slate-600 block mb-1.5">{t("admNewStatus")}</label><select value={form.status} onChange={e=>setForm(f=>({...f,status:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none appearance-none"><option value="">{t("admSelectStatus")}</option>{tabs.slice(1).map(tb=><option key={tb} value={tb}>{t(orderTabLabels[tb])}</option>)}</select></div>
              <div><label className="text-xs font-medium text-slate-600 block mb-1.5">{t("admReasonRequired")}</label><textarea value={form.reason} onChange={e=>setForm(f=>({...f,reason:e.target.value}))} rows={2} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none resize-none" placeholder={t("admStatusReasonPh")}/></div>
            </AdminModal>
          )}
          {modal==="cancel" && (
            <AdminModal title={t("admCancelOrder")} onClose={()=>{setModal(null);setErr("");}} onSubmit={doAction} submitLabel={busy?"...":t("admCancelOrder")} submitVariant="danger" error={err} busy={busy}>
              <p className="text-sm text-slate-600">{t("admCancelOrderWarn")} <strong>{drawer.code}</strong></p>
              <div><label className="text-xs font-medium text-slate-600 block mb-1.5">{t("admReasonRequired")}</label><textarea value={form.reason} onChange={e=>setForm(f=>({...f,reason:e.target.value}))} rows={3} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none resize-none" placeholder={t("admCancelReasonPh")}/></div>
            </AdminModal>
          )}
          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <AdminStatusBadge status={drawer.status}/>
              <span className="text-xs text-slate-400">{drawer.date}</span>
            </div>
            {/* Drawer tabs */}
            <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
              {([["overview","admOverview"],["bids","admBids"],["history","admHistory"]] as [string,TKey][]).map(([tb,k])=><button key={tb} onClick={()=>setDrawerTab(tb)} className={`flex-1 py-1.5 rounded-md text-xs font-medium transition-colors ${drawerTab===tb?"bg-card text-slate-800 shadow-sm":"text-slate-500"}`}>{t(k)}</button>)}
            </div>
            {drawerTab==="overview" && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-50 rounded-lg p-3"><p className="text-[10px] text-slate-400 uppercase mb-1">{t("admFrom")}</p><p className="text-sm font-semibold text-slate-800">{drawer.from}</p></div>
                  <div className="bg-slate-50 rounded-lg p-3"><p className="text-[10px] text-slate-400 uppercase mb-1">{t("admTo")}</p><p className="text-sm font-semibold text-slate-800">{drawer.to}</p></div>
                </div>
                {[
                  {label:t("admClient"),value:drawer.client},{label:t("admDriver"),value:drawer.driver},
                  {label:t("admSuggestedPrice"),value:(drawer.price/1000).toFixed(0)+"K so'm"},
                  {label:t("admPayment"),value:drawer.payment},{label:t("admDate"),value:drawer.date},
                ].map(({label,value})=>(
                  <div key={label} className="flex items-center justify-between py-2 border-b border-slate-100">
                    <span className="text-xs text-slate-500">{label}</span>
                    <span className="text-sm font-medium text-slate-800">{value}</span>
                  </div>
                ))}
              </div>
            )}
            {drawerTab==="bids" && <AdminOrderBids orderId={drawer.id}/>}
            {drawerTab==="history" && (
              <div className="space-y-2">
                {[{status:"published",time:"Jun 25, 09:00"},{status:"bidding",time:"Jun 25, 09:10"},{status:"accepted",time:"Jun 25, 09:20"}].map((h,i)=>(
                  <div key={i} className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0"/>
                    <div className="flex-1"><p className="text-xs font-medium text-slate-700">{t(orderTabLabels[h.status])}</p></div>
                    <span className="text-[11px] text-slate-400">{h.time}</span>
                  </div>
                ))}
              </div>
            )}
            {/* Actions */}
            <div className="flex flex-col gap-2 pt-2 border-t border-slate-100">
              <button onClick={()=>setModal("assign")} className="w-full flex items-center justify-center gap-2 bg-primary text-white rounded-lg py-2.5 text-sm font-medium"><UserCheck size={14}/>{t("admAssignDriver")}</button>
              <div className="flex gap-2">
                <button onClick={()=>setModal("status")} className="flex-1 border border-slate-200 text-slate-600 rounded-lg py-2 text-xs font-medium hover:bg-slate-50">{t("admChangeStatus")}</button>
                <button onClick={()=>setModal("cancel")} className="flex-1 border border-red-200 text-red-600 rounded-lg py-2 text-xs font-medium hover:bg-red-50">{t("admCancelOrder")}</button>
              </div>
            </div>
          </div>
        </AdminDrawer>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        <AdminMetricCard title={t("admTotalOrders")}    value={adminOrders.length.toString()}  icon={Package}    color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admActiveDeliveries")} value={adminOrders.filter((o: any)=>["accepted","picked_up","in_transit"].includes(o.status)).length.toString()} icon={Navigation} color="bg-blue-50 text-blue-600"/>
        <AdminMetricCard title={t("admAwaitingBids")}   value={adminOrders.filter((o: any)=>["published","bidding"].includes(o.status)).length.toString()} icon={CircleDot}  color="bg-amber-50 text-amber-600"/>
        <AdminMetricCard title={t("admDisputed")}        value={adminOrders.filter((o: any)=>o.status==="disputed").length.toString()} icon={Flag}      color="bg-rose-50 text-rose-600"/>
      </div>

      {/* Status tabs */}
      <div className="flex gap-1 bg-slate-100 p-1 rounded-lg overflow-x-auto">
        {tabs.map(tb=><button key={tb} onClick={()=>setTab(tb)} className={`px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${tab===tb?"bg-card text-slate-800 shadow-sm":"text-slate-500 hover:text-slate-700"}`}>{t(orderTabLabels[tb])}</button>)}
      </div>

      {/* Filters */}
      <div className="flex gap-3"><AdminSearchBar placeholder={t("admSearchOrders")} value={search} onChange={setSearch}/></div>

      {/* Table */}
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admOrder")}</AdminTh><AdminTh>{t("admStatus")}</AdminTh><AdminTh>{t("admRoute")}</AdminTh><AdminTh>{t("admClient")}</AdminTh><AdminTh>{t("admDriver")}</AdminTh><AdminTh>{t("admPrice")}</AdminTh><AdminTh>{t("admPayment")}</AdminTh><AdminTh>{t("admDate")}</AdminTh><AdminTh>{t("admActions")}</AdminTh></tr></thead>
        <tbody>
          {filtered.map(o=>(
            <tr key={o.id} className="hover:bg-slate-50 cursor-pointer" onClick={()=>setDrawer(o)}>
              <AdminTd><span className="font-mono text-xs font-semibold text-blue-600">{o.code}</span></AdminTd>
              <AdminTd><AdminStatusBadge status={o.status}/></AdminTd>
              <AdminTd><span className="font-medium">{o.from}</span><span className="text-slate-400 mx-1">→</span>{o.to}</AdminTd>
              <AdminTd>{o.client}</AdminTd>
              <AdminTd><span className={o.driver==="—"?"text-slate-400":""} >{o.driver}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs font-semibold">{(o.price/1000).toFixed(0)}K</span></AdminTd>
              <AdminTd><AdminStatusBadge status={o.payment}/></AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{o.date}</span></AdminTd>
              <AdminTd onClick={e=>e.stopPropagation()}>
                <div className="flex gap-1">
                  <AdminActionBtn label={t("admView")} icon={Eye} onClick={()=>setDrawer(o)}/>
                </div>
              </AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Drivers ─────────────────────────────────────────────────────────────

function AdminDrivers() {
  const { t } = useT();
  const driverTabLabels: Record<string,TKey> = { all:"admTabAll", new:"admTabNew", pending:"admTabPending", approved:"admTabApproved", rejected:"admTabRejected", blocked:"admTabBlocked" };
  const [tab,setTab] = useState("all");
  const [search,setSearch] = useState("");
  const { data, reload } = useAsync<any>(()=>getAdminDrivers({ limit:100 }), []);
  const adminDrivers = ((data?.items ?? []) as any[]).map(mapDriverRow);
  const [drawer,setDrawer] = useState<ReturnType<typeof mapDriverRow>|null>(null);
  const [modal,setModal] = useState<"approve"|"reject"|"block"|"vehicle"|null>(null);
  const [reason,setReason] = useState(""); const [busy,setBusy] = useState(false);
  const [err,setErr] = useState("");
  const [vForm,setVForm] = useState({full_name:"",car_model:"",car_color:"",plate_number:""});

  async function doAction(){
    if(!drawer) return;
    setBusy(true); setErr("");
    try {
      if(modal==="approve") await approveDriver(drawer.id,{});
      else if(modal==="reject") await rejectDriver(drawer.id,{reason:reason||"Hujjatlar to'liq emas"});
      else if(modal==="block") await blockDriver(drawer.id,{reason:reason||"Qoidabuzarlik"});
      setModal(null); setDrawer(null); setReason(""); reload();
    } catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); }
  }

  function openVehicle(){
    if(!drawer) return;
    setVForm({
      full_name: drawer.name==="—"?"":drawer.name,
      car_model: drawer.car==="—"?"":drawer.car,
      car_color: drawer.color==="—"?"":drawer.color,
      plate_number: drawer.plate==="—"?"":drawer.plate,
    });
    setModal("vehicle");
  }
  async function saveVehicle(){
    if(!drawer) return;
    setBusy(true); setErr("");
    try {
      await updateDriverVehicle(drawer.id,{
        full_name:vForm.full_name||null,
        car_model:vForm.car_model||null,
        car_color:vForm.car_color||null,
        plate_number:vForm.plate_number||null,
      });
      setModal(null); setDrawer(null); reload();
    } catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); }
  }

  const tabs = ["all","new","pending","approved","rejected","blocked"];
  const filtered = adminDrivers.filter((d: any)=>(tab==="all"||(tab==="new"?d.orders===0&&d.status==="approved":d.status===tab))&&(search===""||d.name.toLowerCase().includes(search.toLowerCase())||d.phone.includes(search)));

  const counts = { total:adminDrivers.length, pending:adminDrivers.filter((d: any)=>d.status==="pending").length, approved:adminDrivers.filter((d: any)=>d.status==="approved").length, rejected:adminDrivers.filter((d: any)=>d.status==="rejected").length, blocked:adminDrivers.filter((d: any)=>d.status==="blocked").length, available:adminDrivers.filter((d: any)=>d.status==="approved"&&d.avail).length };

  return (
    <div className="p-6 space-y-5">
      {drawer && (
        <AdminDrawer title={drawer.name} onClose={()=>setDrawer(null)}>
          {modal==="approve" && (
            <AdminModal title={t("admApproveDriver")} onClose={()=>{setModal(null);setErr("");}} onSubmit={doAction} submitLabel={busy?"...":t("admApprove")} submitVariant="primary" error={err} busy={busy}>
              <p className="text-sm text-slate-600"><strong>{drawer.name}</strong> — {t("admApproveDriverQ")}</p>
            </AdminModal>
          )}
          {(modal==="reject"||modal==="block") && (
            <AdminModal title={modal==="reject"?t("admRejectDriver"):t("admBlockDriver")} onClose={()=>{setModal(null);setErr("");}} onSubmit={doAction} submitLabel={busy?"...":(modal==="reject"?t("admReject"):t("admBlock"))} submitVariant="danger" error={err} busy={busy}>
              <p className="text-sm text-slate-600">{modal==="reject"?t("admReject"):t("admBlock")} — <strong>{drawer.name}</strong>. {t("admRejectBlockWarn")}</p>
              <div><label className="text-xs font-medium text-slate-600 block mb-1.5">{t("admReasonRequired")}</label><div className="flex flex-col gap-2">{([["Incomplete documents","admReasonIncompleteDocs"],["Falsified documents","admReasonFalsifiedDocs"],["Policy violation","admReasonPolicyViolation"],["Other","admReasonOther"]] as [string,TKey][]).map(([r,k])=><label key={r} className="flex items-center gap-2 text-sm"><input type="radio" name="reason" checked={reason===r} onChange={()=>setReason(r)} className="text-blue-600"/>{t(k)}</label>)}</div></div>
            </AdminModal>
          )}
          {modal==="vehicle" && (
            <AdminModal title={t("admEditVehicleDetails")} onClose={()=>{setModal(null);setErr("");}} onSubmit={saveVehicle} submitLabel={busy?"...":t("admSave")} submitVariant="primary" error={err} busy={busy}>
              <p className="text-sm text-slate-600"><strong>{drawer.name}</strong> — {t("admEditVehicleDesc")}</p>
              {([
                {l:t("admFullName"),k:"full_name"},
                {l:t("admCarModel"),k:"car_model"},
                {l:t("admCarColor"),k:"car_color"},
                {l:t("admPlateNumber"),k:"plate_number"},
              ] as {l:string;k:keyof typeof vForm}[]).map(({l,k})=>(
                <div key={k}><label className="text-xs font-medium text-slate-600 block mb-1.5">{l}</label>
                  <input className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm" value={vForm[k]} onChange={e=>setVForm(f=>({...f,[k]:e.target.value}))}/></div>
              ))}
            </AdminModal>
          )}
          <div className="p-5 space-y-4">
            <div className="flex items-center gap-4">
              <div className="w-14 h-14 rounded-xl bg-blue-50 flex items-center justify-center"><Truck size={24} className="text-blue-600"/></div>
              <div>
                <p className="text-base font-bold text-slate-800">{drawer.name}</p>
                <p className="text-sm text-slate-500 font-mono">{drawer.phone}</p>
                <div className="flex gap-2 mt-1"><AdminStatusBadge status={drawer.status}/>{drawer.avail&&<AdminStatusBadge status="active"/>}</div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 py-3 border-y border-slate-100">
              {[{label:t("admRating"),value:drawer.rating||"—"},{label:t("admCompleted"),value:drawer.orders},{label:t("admRoutes"),value:drawer.routes}].map(({label,value})=>(
                <div key={label} className="text-center"><p className="text-lg font-bold font-mono text-slate-800">{value}</p><p className="text-[10px] text-slate-400 uppercase">{label}</p></div>
              ))}
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("admVehicle")}</p>
              {[{l:t("admModel"),v:drawer.car},{l:t("admColor"),v:drawer.color},{l:t("admPlate"),v:drawer.plate}].map(({l,v})=><div key={l} className="flex justify-between py-1.5 border-b border-slate-100"><span className="text-xs text-slate-500">{l}</span><span className="text-sm font-mono font-medium text-slate-700">{v}</span></div>)}
            </div>
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("admDocs")} ({drawer.docs}/5)</p>
              <div className="w-full bg-slate-100 rounded-full h-2"><div className="bg-blue-500 h-2 rounded-full transition-all" style={{width:`${(drawer.docs/5)*100}%`}}/></div>
              {([["Passport","admDocPassport"],["Selfie","admDocSelfie"],["Driver License","admDocLicense"],["Car Document","admDocCarDoc"],["Car Photo","admDocCarPhoto"]] as [string,TKey][]).map(([doc,k],i)=>(
                <div key={doc} className="flex items-center justify-between py-1.5 border-b border-slate-100">
                  <span className="text-xs text-slate-600">{t(k)}</span>
                  {i<drawer.docs?<span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">{t("admUploaded")}</span>:<span className="text-[10px] bg-red-100 text-red-600 px-1.5 py-0.5 rounded font-medium">{t("admMissing")}</span>}
                </div>
              ))}
            </div>
            <div className="flex flex-col gap-2 pt-2">
              <button onClick={openVehicle} className="w-full border border-blue-200 text-blue-700 rounded-lg py-2 text-sm font-medium hover:bg-blue-50"><Edit3 size={13} className="inline mr-1"/>{t("admEditVehicleDetails")}</button>
              <div className="flex gap-2">
                {drawer.status==="pending" && <>
                  <button onClick={()=>setModal("approve")} className="flex-1 bg-green-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-green-700"><UserCheck size={13} className="inline mr-1"/>{t("admApprove")}</button>
                  <button onClick={()=>setModal("reject")}  className="flex-1 border border-orange-200 text-orange-700 rounded-lg py-2 text-sm font-medium hover:bg-orange-50"><UserX size={13} className="inline mr-1"/>{t("admReject")}</button>
                </>}
                {drawer.status==="approved" && <button onClick={()=>setModal("block")} className="flex-1 border border-red-200 text-red-700 rounded-lg py-2 text-sm font-medium hover:bg-red-50"><Ban size={13} className="inline mr-1"/>{t("admBlock")}</button>}
              </div>
            </div>
          </div>
        </AdminDrawer>
      )}

      <div className="grid grid-cols-4 gap-4">
        <AdminMetricCard title={t("admTotalDrivers")}  value={counts.total.toString()}    icon={Truck}     color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admPendingReview")} value={counts.pending.toString()}  icon={Clock}     color="bg-amber-50 text-amber-600"/>
        <AdminMetricCard title={t("admApproved")}       value={counts.approved.toString()} icon={UserCheck} color="bg-green-50 text-green-600"/>
        <AdminMetricCard title={t("admAvailableNow")}  value={counts.available.toString()} icon={Navigation}color="bg-blue-50 text-blue-600"/>
      </div>

      <div className="flex gap-1 bg-slate-100 p-1 rounded-lg">
        {tabs.map(tb=><button key={tb} onClick={()=>setTab(tb)} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${tab===tb?"bg-card text-slate-800 shadow-sm":"text-slate-500"}`}>{t(driverTabLabels[tb])}</button>)}
      </div>

      <AdminSearchBar placeholder={t("admSearchDrivers")} value={search} onChange={setSearch}/>

      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admDriver")}</AdminTh><AdminTh>{t("admPhone")}</AdminTh><AdminTh>{t("admVehicle")}</AdminTh><AdminTh>{t("admStatus")}</AdminTh><AdminTh>{t("admAvailable")}</AdminTh><AdminTh>{t("admDocs")}</AdminTh><AdminTh>{t("admRoutes")}</AdminTh><AdminTh>{t("admOrders")}</AdminTh><AdminTh>{t("admJoined")}</AdminTh><AdminTh>{t("admActions")}</AdminTh></tr></thead>
        <tbody>
          {filtered.map(d=>(
            <tr key={d.id} className="hover:bg-slate-50">
              <AdminTd><span className="font-medium text-slate-800">{d.name}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{d.phone}</span></AdminTd>
              <AdminTd><span className="text-xs">{d.car} · <span className="font-mono">{d.plate}</span></span></AdminTd>
              <AdminTd><AdminStatusBadge status={d.status}/></AdminTd>
              <AdminTd>{d.avail?<span className="text-green-600 text-xs font-medium">{t("admOnline")}</span>:<span className="text-slate-400 text-xs">{t("admOffline")}</span>}</AdminTd>
              <AdminTd><span className={`font-mono text-xs font-semibold ${d.docs<5?"text-amber-600":"text-green-600"}`}>{d.docs}/5</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{d.routes}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{d.orders}</span></AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{d.created}</span></AdminTd>
              <AdminTd>
                <div className="flex gap-1">
                  <AdminActionBtn label={t("admView")}   icon={Eye}    onClick={()=>setDrawer(d)}/>
                  {d.status==="pending"  && <AdminActionBtn label={t("admApprove")} variant="approve" onClick={()=>{setDrawer(d);setModal("approve");}}/>}
                  {d.status==="pending"  && <AdminActionBtn label={t("admReject")}  variant="reject"  onClick={()=>{setDrawer(d);setModal("reject");}}/>}
                  {d.status==="approved" && <AdminActionBtn label={t("admBlock")}   variant="block"   onClick={()=>{setDrawer(d);setModal("block");}}/>}
                </div>
              </AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Clients ─────────────────────────────────────────────────────────────

function AdminClients() {
  const { t } = useT();
  const [search,setSearch] = useState("");
  const { data, reload } = useAsync<any>(()=>getAdminClients({ limit:100 }), []);
  const adminClients = ((data?.items ?? []) as any[]).map(mapClientRow);
  const [drawer,setDrawer] = useState<ReturnType<typeof mapClientRow>|null>(null);
  const [busy,setBusy] = useState(false);
  const [err,setErr] = useState("");
  async function toggleBlock(c:ReturnType<typeof mapClientRow>){
    setBusy(true); setErr("");
    try { if(c.status==="blocked") await unblockAdminClient(c.id,"Admin tomonidan"); else await blockAdminClient(c.id,"Admin tomonidan"); setDrawer(null); reload(); }
    catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); }
  }
  const filtered = adminClients.filter((c: any)=>search===""||c.name.toLowerCase().includes(search.toLowerCase())||c.phone.includes(search));
  return (
    <div className="p-6 space-y-5">
      {err && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 flex items-center justify-between">{err}<button onClick={()=>setErr("")} className="ml-3 text-red-400 hover:text-red-600"><X size={14}/></button></div>}
      {drawer && (
        <AdminDrawer title={drawer.name} onClose={()=>setDrawer(null)}>
          <div className="p-5 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center"><User size={22} className="text-slate-500"/></div>
              <div><p className="text-base font-bold text-slate-800">{drawer.name}</p><p className="text-sm text-slate-500 font-mono">{drawer.phone}</p><div className="flex gap-2 mt-1"><AdminStatusBadge status={drawer.status}/>{drawer.verified&&<span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium border border-blue-200">{t("admVerified")}</span>}</div></div>
            </div>
            <div className="grid grid-cols-3 gap-3 py-3 border-y border-slate-100">
              {[{l:t("admTotalOrders"),v:drawer.orders},{l:t("admActive"),v:drawer.active},{l:t("admCompleted"),v:drawer.orders-drawer.active}].map(({l,v})=><div key={l} className="text-center"><p className="text-lg font-bold font-mono text-slate-800">{v}</p><p className="text-[10px] text-slate-400 uppercase">{l}</p></div>)}
            </div>
            {[{l:t("admLastOrder"),v:drawer.last},{l:t("admJoined"),v:drawer.created}].map(({l,v})=><div key={l} className="flex justify-between py-2 border-b border-slate-100"><span className="text-xs text-slate-500">{l}</span><span className="text-sm text-slate-700">{v}</span></div>)}
            <div className="flex gap-2 pt-2">
              {drawer.status==="active"  && <button onClick={()=>toggleBlock(drawer)} disabled={busy} className="flex-1 border border-red-200 text-red-700 rounded-lg py-2 text-sm font-medium hover:bg-red-50 disabled:opacity-60"><Ban size={13} className="inline mr-1"/>{t("admBlockClient")}</button>}
              {drawer.status==="blocked" && <button onClick={()=>toggleBlock(drawer)} disabled={busy} className="flex-1 border border-green-200 text-green-700 rounded-lg py-2 text-sm font-medium hover:bg-green-50 disabled:opacity-60"><CheckCircle2 size={13} className="inline mr-1"/>{t("admUnblock")}</button>}
            </div>
          </div>
        </AdminDrawer>
      )}
      <div className="grid grid-cols-4 gap-4">
        <AdminMetricCard title={t("admTotalClients")}  value={adminClients.length.toString()}                     icon={Users}        color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admActive")}         value={adminClients.filter((c: any)=>c.status==="active").length.toString()} icon={CheckCircle2} color="bg-green-50 text-green-600"/>
        <AdminMetricCard title={t("admBlocked")}        value={adminClients.filter((c: any)=>c.status==="blocked").length.toString()}icon={Ban}         color="bg-red-50 text-red-600"/>
        <AdminMetricCard title={t("admWithOrders")}    value={adminClients.filter((c: any)=>c.orders>0).length.toString()}           icon={Package}     color="bg-blue-50 text-blue-600"/>
      </div>
      <AdminSearchBar placeholder={t("admSearchClients")} value={search} onChange={setSearch}/>
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admClient")}</AdminTh><AdminTh>{t("admPhone")}</AdminTh><AdminTh>{t("admStatus")}</AdminTh><AdminTh>{t("admVerified")}</AdminTh><AdminTh>{t("admOrders")}</AdminTh><AdminTh>{t("admActive")}</AdminTh><AdminTh>{t("admLastOrder")}</AdminTh><AdminTh>{t("admJoined")}</AdminTh><AdminTh>{t("admActions")}</AdminTh></tr></thead>
        <tbody>
          {filtered.map(c=>(
            <tr key={c.id} className="hover:bg-slate-50">
              <AdminTd><span className="font-medium">{c.name}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{c.phone}</span></AdminTd>
              <AdminTd><AdminStatusBadge status={c.status}/></AdminTd>
              <AdminTd>{c.verified?<CheckCircle2 size={14} className="text-green-500"/>:<X size={14} className="text-slate-400"/>}</AdminTd>
              <AdminTd><span className="font-mono text-xs">{c.orders}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{c.active}</span></AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{c.last}</span></AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{c.created}</span></AdminTd>
              <AdminTd>
                <div className="flex gap-1">
                  <AdminActionBtn label={t("admView")} icon={Eye} onClick={()=>setDrawer(c)}/>
                  {c.status==="active"  && <AdminActionBtn label={t("admBlock")}   variant="block" onClick={()=>toggleBlock(c)}/>}
                  {c.status==="blocked" && <AdminActionBtn label={t("admUnblock")} variant="approve" onClick={()=>toggleBlock(c)}/>}
                </div>
              </AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Regions ─────────────────────────────────────────────────────────────

function AdminRegions() {
  const { t } = useT();
  const [search,setSearch] = useState("");
  const { data, reload } = useAsync<any>(()=>getAdminCities({ limit:100 }), []);
  const adminRegions = ((data?.items ?? []) as any[]).map(mapRegionRow);
  const [busy,setBusy] = useState(false);
  const [err,setErr] = useState("");
  async function toggleActive(r:ReturnType<typeof mapRegionRow>){ setBusy(true); setErr(""); try { if(r.active) await deactivateCity(r.id); else await activateCity(r.id); reload(); } catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); } }
  const filtered = adminRegions.filter((r: any)=>search===""||r.uz.toLowerCase().includes(search.toLowerCase())||r.ru.toLowerCase().includes(search.toLowerCase()));
  return (
    <div className="p-6 space-y-5">
      {err && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 flex items-center justify-between">{err}<button onClick={()=>setErr("")} className="ml-3 text-red-400 hover:text-red-600"><X size={14}/></button></div>}
      <div className="grid grid-cols-4 gap-4">
        <AdminMetricCard title={t("admTotalRegions")}   value={adminRegions.length.toString()} icon={MapPin} color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admActive")}          value={adminRegions.filter((r: any)=>r.active).length.toString()} icon={CheckCircle2} color="bg-green-50 text-green-600"/>
        <AdminMetricCard title={t("admWithDistricts")}  value={adminRegions.filter((r: any)=>r.dist).length.toString()} icon={LayoutDashboard} color="bg-blue-50 text-blue-600"/>
        <AdminMetricCard title={t("admInactive")}        value={adminRegions.filter((r: any)=>!r.active).length.toString()} icon={Ban} color="bg-slate-100 text-slate-500"/>
      </div>
      <div className="flex gap-3 items-center justify-between">
        <AdminSearchBar placeholder={t("admSearchRegions")} value={search} onChange={setSearch}/>
        <button className="flex items-center gap-2 bg-primary text-white px-3 py-2 rounded-lg text-sm font-medium"><Plus size={14}/>{t("admAddRegion")}</button>
      </div>
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admId")}</AdminTh><AdminTh>{t("admUzbek")}</AdminTh><AdminTh>{t("admRussian")}</AdminTh><AdminTh>{t("admType")}</AdminTh><AdminTh>{t("admDistricts")}</AdminTh><AdminTh>{t("admReqDistrict")}</AdminTh><AdminTh>{t("admActive")}</AdminTh><AdminTh>{t("admActions")}</AdminTh></tr></thead>
        <tbody>
          {filtered.map(r=>(
            <tr key={r.id} className="hover:bg-slate-50">
              <AdminTd><span className="font-mono text-xs text-slate-400">{r.id}</span></AdminTd>
              <AdminTd><span className="font-medium">{r.uz}</span></AdminTd>
              <AdminTd>{r.ru}</AdminTd>
              <AdminTd><AdminStatusBadge status={r.type}/></AdminTd>
              <AdminTd><span className="font-mono text-xs">{r.districts}</span></AdminTd>
              <AdminTd>{r.dist?<CheckCircle2 size={14} className="text-green-500"/>:<X size={14} className="text-slate-300"/>}</AdminTd>
              <AdminTd>{r.active?<CheckCircle2 size={14} className="text-green-500"/>:<X size={14} className="text-red-600 dark:text-red-400"/>}</AdminTd>
              <AdminTd>
                <div className="flex gap-1">
                  <AdminActionBtn label={r.active?t("admDeactivate"):t("admActivate")} variant={r.active?"reject":"approve"} onClick={()=>toggleActive(r)}/>
                </div>
              </AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Tariffs ─────────────────────────────────────────────────────────────

function AdminTariffs() {
  const { t } = useT();
  const [search,setSearch] = useState("");
  const [modal,setModal] = useState(false);
  const { data, reload } = useAsync<any>(()=>getAdminTariffs({ limit:100 }), []);
  const adminTariffs = ((data?.items ?? []) as any[]).map(mapTariffRow);
  const { cities } = useCities();
  const [busy,setBusy] = useState(false);
  const [tf,setTf] = useState({from:"",to:"",suggested:"",min:"",max:""});
  const [err,setErr] = useState("");
  async function toggleActive(t:ReturnType<typeof mapTariffRow>){ setBusy(true); setErr(""); try { if(t.active) await deactivateTariff(t.id); else await activateTariff(t.id); reload(); } catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); } }
  async function createNew(){ if(!tf.from||!tf.to||!tf.suggested) return; setBusy(true); setErr(""); try { await createTariff({from_city_id:Number(tf.from),to_city_id:Number(tf.to),suggested_price:Number(tf.suggested),min_price:tf.min?Number(tf.min):null,max_price:tf.max?Number(tf.max):null}); setModal(false); setTf({from:"",to:"",suggested:"",min:"",max:""}); reload(); } catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); } }
  const avg = adminTariffs.length ? adminTariffs.reduce((a: number,t: any)=>a+t.suggested,0)/adminTariffs.length : 0;
  const filtered = adminTariffs.filter((t: any)=>search===""||t.from.toLowerCase().includes(search.toLowerCase())||t.to.toLowerCase().includes(search.toLowerCase()));
  return (
    <div className="p-6 space-y-5">
      {err && !modal && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 flex items-center justify-between">{err}<button onClick={()=>setErr("")} className="ml-3 text-red-400 hover:text-red-600"><X size={14}/></button></div>}
      {modal && (
        <AdminModal title={t("admAddTariff")} onClose={()=>{setModal(false);setErr("");}} onSubmit={createNew} submitLabel={busy?"...":t("admSaveTariff")} error={err} busy={busy}>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="text-xs font-medium text-slate-600 block mb-1">{t("admFromCity")}</label><select value={tf.from} onChange={e=>setTf(f=>({...f,from:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none"><option value="">{t("admSelectPh")}</option>{cities.map(c=><option key={c.id} value={c.id}>{c.uz}</option>)}</select></div>
            <div><label className="text-xs font-medium text-slate-600 block mb-1">{t("admToCity")}</label><select value={tf.to} onChange={e=>setTf(f=>({...f,to:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none"><option value="">{t("admSelectPh")}</option>{cities.map(c=><option key={c.id} value={c.id}>{c.uz}</option>)}</select></div>
          </div>
          {([{k:"suggested",l:t("admSuggestedPrice"),ph:"150000"},{k:"min",l:t("admMinPrice"),ph:"120000"},{k:"max",l:t("admMaxPrice"),ph:"200000"}] as const).map(({k,l,ph})=>(
            <div key={l}><label className="text-xs font-medium text-slate-600 block mb-1">{l}</label><input value={(tf as any)[k]} onChange={e=>setTf(f=>({...f,[k]:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder={ph}/></div>
          ))}
        </AdminModal>
      )}
      <div className="grid grid-cols-4 gap-4">
        <AdminMetricCard title={t("admTotalTariffs")} value={adminTariffs.length.toString()}                      icon={Tag} color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admActive")}        value={adminTariffs.filter((t: any)=>t.active).length.toString()}  icon={CheckCircle2} color="bg-green-50 text-green-600"/>
        <AdminMetricCard title={t("admInactive")}      value={adminTariffs.filter((t: any)=>!t.active).length.toString()} icon={Ban} color="bg-slate-100 text-slate-500"/>
        <AdminMetricCard title={t("admAvgPrice")}     value={(avg/1000).toFixed(0)+"K so'm"} icon={DollarSign} color="bg-blue-50 text-blue-600"/>
      </div>
      <div className="flex gap-3 items-center justify-between">
        <AdminSearchBar placeholder={t("admSearchTariffs")} value={search} onChange={setSearch}/>
        <button onClick={()=>setModal(true)} className="flex items-center gap-2 bg-primary text-white px-3 py-2 rounded-lg text-sm font-medium"><Plus size={14}/>{t("admAddTariff")}</button>
      </div>
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admId")}</AdminTh><AdminTh>{t("admRoute")}</AdminTh><AdminTh>{t("admSuggested")}</AdminTh><AdminTh>{t("admMin")}</AdminTh><AdminTh>{t("admMax")}</AdminTh><AdminTh>{t("admCurrency")}</AdminTh><AdminTh>{t("admActive")}</AdminTh><AdminTh>{t("admCreated")}</AdminTh><AdminTh>{t("admActions")}</AdminTh></tr></thead>
        <tbody>
          {filtered.map(tr=>(
            <tr key={tr.id} className="hover:bg-slate-50">
              <AdminTd><span className="font-mono text-xs text-slate-400">{tr.id}</span></AdminTd>
              <AdminTd><span className="font-medium">{tr.from}</span><span className="text-slate-400 mx-1">→</span>{tr.to}</AdminTd>
              <AdminTd><span className="font-mono text-sm font-semibold text-slate-800">{(tr.suggested/1000).toFixed(0)}K</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{(tr.min/1000).toFixed(0)}K</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{(tr.max/1000).toFixed(0)}K</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{tr.currency}</span></AdminTd>
              <AdminTd>{tr.active?<CheckCircle2 size={14} className="text-green-500"/>:<X size={14} className="text-red-600 dark:text-red-400"/>}</AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{tr.created}</span></AdminTd>
              <AdminTd>
                <div className="flex gap-1">
                  <AdminActionBtn label={tr.active?t("admDeactivate"):t("admActivate")} variant={tr.active?"reject":"approve"} onClick={()=>toggleActive(tr)}/>
                </div>
              </AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Disputes ────────────────────────────────────────────────────────────

function AdminDisputesSection() {
  const { t } = useT();
  const { data } = useAsync<any>(()=>listAdminDisputes({ limit:100 }), []);
  const adminDisputes = ((data?.items ?? []) as any[]).map(mapDisputeRow);
  const [drawer,setDrawer] = useState<ReturnType<typeof mapDisputeRow>|null>(null);
  return (
    <div className="p-6 space-y-5">
      {drawer && (
        <AdminDrawer title={`${t("admDisputePrefix")} — ${drawer.orderId}`} onClose={()=>setDrawer(null)}>
          <div className="p-5 space-y-4">
            <AdminStatusBadge status={drawer.status}/>
            <div className="space-y-2">
              {[{l:t("admOrder"),v:drawer.orderId},{l:t("admReason"),v:drawer.reason},{l:t("admOpenedBy"),v:drawer.openedBy},{l:t("admCreated"),v:drawer.created},{l:t("admResolution"),v:drawer.resolution||"—"}].map(({l,v})=>(
                <div key={l} className="flex justify-between py-2 border-b border-slate-100"><span className="text-xs text-slate-500">{l}</span><span className="text-sm font-medium text-slate-700">{v}</span></div>
              ))}
            </div>
            {(drawer.status==="open"||drawer.status==="in_review") && (
              <div className="space-y-2">
                <label className="text-xs font-medium text-slate-600 block">{t("admUpdateStatusLbl")}</label>
                <select className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none"><option>in_review</option><option>resolved</option><option>rejected</option></select>
                <textarea rows={3} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none resize-none" placeholder={t("admResolutionNotePh")}/>
                <button className="w-full bg-primary text-white rounded-lg py-2 text-sm font-medium">{t("admUpdateDispute")}</button>
              </div>
            )}
          </div>
        </AdminDrawer>
      )}
      <div className="grid grid-cols-3 gap-4">
        <AdminMetricCard title={t("admTotalDisputes")} value={adminDisputes.length.toString()} icon={Flag} color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admOpen")}           value={adminDisputes.filter((d: any)=>d.status==="open").length.toString()} icon={AlertCircle} color="bg-rose-50 text-rose-600"/>
        <AdminMetricCard title={t("admResolved")}       value={adminDisputes.filter((d: any)=>d.status==="resolved").length.toString()} icon={CheckCircle2} color="bg-green-50 text-green-600"/>
      </div>
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admId")}</AdminTh><AdminTh>{t("admOrder")}</AdminTh><AdminTh>{t("admReason")}</AdminTh><AdminTh>{t("admStatus")}</AdminTh><AdminTh>{t("admOpenedBy")}</AdminTh><AdminTh>{t("admCreated")}</AdminTh><AdminTh>{t("admActions")}</AdminTh></tr></thead>
        <tbody>
          {adminDisputes.map(d=>(
            <tr key={d.id} className="hover:bg-slate-50">
              <AdminTd><span className="font-mono text-xs text-slate-400">{d.id}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs font-semibold text-blue-600">{d.orderId}</span></AdminTd>
              <AdminTd>{d.reason}</AdminTd>
              <AdminTd><AdminStatusBadge status={d.status}/></AdminTd>
              <AdminTd>{d.openedBy}</AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{d.created}</span></AdminTd>
              <AdminTd><AdminActionBtn label={t("admReview")} icon={Eye} onClick={()=>setDrawer(d)}/></AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Staff ───────────────────────────────────────────────────────────────

function AdminStaffSection() {
  const { t } = useT();
  const [modal,setModal] = useState(false);
  const { data, reload } = useAsync<any>(()=>getAdminUsers({ limit:100 }), []);
  const adminStaff = ((data?.items ?? []) as any[]).map(mapStaffRow);
  const [busy,setBusy] = useState(false);
  const [sf,setSf] = useState({phone:"",name:"",role:"operator"});
  const [err,setErr] = useState("");
  async function createNew(){ if(!sf.phone) return; setBusy(true); setErr(""); try { await createStaffUser({phone:normalizeUzPhone(sf.phone),full_name:sf.name||null,role:sf.role as "operator"|"admin"}); setModal(false); setSf({phone:"",name:"",role:"operator"}); reload(); } catch(e){ setErr(getUzbekErrorMessage(e)); } finally { setBusy(false); } }
  async function toggleBlock(s:ReturnType<typeof mapStaffRow>){ setErr(""); try { if(s.status==="blocked") await unblockStaffUser(s.id,"Admin"); else await blockStaffUser(s.id,"Admin"); reload(); } catch(e){ setErr(getUzbekErrorMessage(e)); } }
  return (
    <div className="p-6 space-y-5">
      {err && !modal && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 flex items-center justify-between">{err}<button onClick={()=>setErr("")} className="ml-3 text-red-400 hover:text-red-600"><X size={14}/></button></div>}
      {modal && (
        <AdminModal title={t("admCreateStaff")} onClose={()=>{setModal(false);setErr("");}} onSubmit={createNew} submitLabel={busy?"...":t("admCreateUser")} error={err} busy={busy}>
          <div><label className="text-xs font-medium text-slate-600 block mb-1">{t("admPhone")}</label><input value={sf.phone} onChange={e=>setSf(f=>({...f,phone:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder="+998XXXXXXXXX"/></div>
          <div><label className="text-xs font-medium text-slate-600 block mb-1">{t("admFullName")}</label><input value={sf.name} onChange={e=>setSf(f=>({...f,name:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder={t("admFullName")}/></div>
          <div><label className="text-xs font-medium text-slate-600 block mb-1">{t("admRoleLbl")}</label><select value={sf.role} onChange={e=>setSf(f=>({...f,role:e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none"><option value="operator">{t("admOperator")}</option><option value="admin">{t("admAdmin")}</option></select></div>
        </AdminModal>
      )}
      <div className="grid grid-cols-4 gap-4">
        <AdminMetricCard title={t("admTotalStaff")}   value={adminStaff.length.toString()} icon={Users} color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admAdmins")}        value={adminStaff.filter((s: any)=>s.role==="admin"||s.role==="super_admin").length.toString()} icon={ShieldCheck} color="bg-purple-50 text-purple-600"/>
        <AdminMetricCard title={t("admOperators")}     value={adminStaff.filter((s: any)=>s.role==="operator").length.toString()} icon={User} color="bg-blue-50 text-blue-600"/>
        <AdminMetricCard title={t("admActive")}        value={adminStaff.filter((s: any)=>s.status==="active").length.toString()} icon={CheckCircle2} color="bg-green-50 text-green-600"/>
      </div>
      <div className="flex justify-end">
        <button onClick={()=>setModal(true)} className="flex items-center gap-2 bg-primary text-white px-3 py-2 rounded-lg text-sm font-medium"><Plus size={14}/>{t("admCreateStaff")}</button>
      </div>
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admName")}</AdminTh><AdminTh>{t("admPhone")}</AdminTh><AdminTh>{t("admRole")}</AdminTh><AdminTh>{t("admStatus")}</AdminTh><AdminTh>{t("admVerified")}</AdminTh><AdminTh>{t("admCreated")}</AdminTh><AdminTh>{t("admLastLogin")}</AdminTh><AdminTh>{t("admActions")}</AdminTh></tr></thead>
        <tbody>
          {adminStaff.map(s=>(
            <tr key={s.id} className="hover:bg-slate-50">
              <AdminTd><span className="font-medium">{s.name}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs">{s.phone}</span></AdminTd>
              <AdminTd><AdminStatusBadge status={s.role}/></AdminTd>
              <AdminTd><AdminStatusBadge status={s.status}/></AdminTd>
              <AdminTd>{s.verified?<CheckCircle2 size={14} className="text-green-500"/>:<X size={14} className="text-slate-400"/>}</AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{s.created}</span></AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{s.lastLogin}</span></AdminTd>
              <AdminTd>
                <div className="flex gap-1">
                  {s.status==="active" && s.role!=="super_admin" && <AdminActionBtn label={t("admBlock")} variant="block" onClick={()=>toggleBlock(s)}/>}
                  {s.status==="blocked" && <AdminActionBtn label={t("admUnblock")} variant="approve" onClick={()=>toggleBlock(s)}/>}
                </div>
              </AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Notifications ───────────────────────────────────────────────────────

function AdminNotificationsSection() {
  const { t } = useT();
  const { data } = useAsync<any>(()=>getAdminNotifications({ limit:100 }), []);
  const adminAdminNotifs = ((data?.items ?? []) as any[]).map(mapNotifRow);
  return (
    <div className="p-6 space-y-5">
      <div className="grid grid-cols-3 gap-4">
        <AdminMetricCard title={t("admTotal")} value={adminAdminNotifs.length.toString()} icon={Bell} color="bg-slate-100 text-slate-600"/>
        <AdminMetricCard title={t("admUnread")} value={adminAdminNotifs.filter((n: any)=>!n.read).length.toString()} icon={AlertCircle} color="bg-amber-50 text-amber-600"/>
        <AdminMetricCard title={t("admSystem")} value={adminAdminNotifs.filter((n: any)=>n.type==="system").length.toString()} icon={Zap} color="bg-blue-50 text-blue-600"/>
      </div>
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admRecipient")}</AdminTh><AdminTh>{t("admType")}</AdminTh><AdminTh>{t("admTitle")}</AdminTh><AdminTh>{t("admMessage")}</AdminTh><AdminTh>{t("admChannel")}</AdminTh><AdminTh>{t("admRead")}</AdminTh><AdminTh>{t("admDate")}</AdminTh></tr></thead>
        <tbody>
          {adminAdminNotifs.map(n=>(
            <tr key={n.id} className={`hover:bg-slate-50 ${!n.read?"bg-blue-50/30":""}`}>
              <AdminTd><span className="font-medium text-xs">{n.recipient}</span></AdminTd>
              <AdminTd><AdminStatusBadge status={n.type}/></AdminTd>
              <AdminTd><span className="font-medium text-xs">{n.title}</span></AdminTd>
              <AdminTd><span className="text-slate-500 text-xs max-w-[200px] block truncate">{n.message}</span></AdminTd>
              <AdminTd><AdminStatusBadge status={n.channel}/></AdminTd>
              <AdminTd>{n.read?<CheckCircle2 size={14} className="text-green-500"/>:<div className="w-2 h-2 rounded-full bg-blue-500"/>}</AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{n.date}</span></AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Audit Log ───────────────────────────────────────────────────────────

function AdminAuditLogSection() {
  const { t } = useT();
  const [search,setSearch] = useState("");
  const { data } = useAsync<any>(()=>listAdminAuditLogs({ limit:100 }), []);
  const adminAuditLog = ((data?.items ?? []) as any[]).map(mapAuditRow);
  const filtered = adminAuditLog.filter((l: any)=>search===""||l.actor.toLowerCase().includes(search.toLowerCase())||l.action.includes(search));
  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center gap-3 justify-between">
        <AdminSearchBar placeholder={t("admSearchAudit")} value={search} onChange={setSearch}/>
        <div className="flex items-center gap-2 text-xs text-slate-500 bg-amber-50 border border-amber-200 px-3 py-2 rounded-lg"><AlertCircle size={12} className="text-amber-500"/> {t("admReadOnlyAudit")}</div>
      </div>
      <AdminTableWrapper>
        <thead><tr><AdminTh>{t("admId")}</AdminTh><AdminTh>{t("admActor")}</AdminTh><AdminTh>{t("admRole")}</AdminTh><AdminTh>{t("admAction")}</AdminTh><AdminTh>{t("admEntity")}</AdminTh><AdminTh>{t("admEntityId")}</AdminTh><AdminTh>{t("admTime")}</AdminTh></tr></thead>
        <tbody>
          {filtered.map(l=>(
            <tr key={l.id} className="hover:bg-slate-50">
              <AdminTd><span className="font-mono text-xs text-slate-400">{l.id}</span></AdminTd>
              <AdminTd><span className="font-medium">{l.actor}</span></AdminTd>
              <AdminTd><AdminStatusBadge status={l.role}/></AdminTd>
              <AdminTd><span className="font-mono text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded">{l.action}</span></AdminTd>
              <AdminTd><span className="text-slate-600">{l.entity}</span></AdminTd>
              <AdminTd><span className="font-mono text-xs text-slate-400">#{l.entityId}</span></AdminTd>
              <AdminTd><span className="text-slate-400 text-xs">{l.created}</span></AdminTd>
            </tr>
          ))}
        </tbody>
      </AdminTableWrapper>
    </div>
  );
}

// ── Admin Profile ─────────────────────────────────────────────────────────────

function AdminProfileSection({ onLogout }: { onLogout:()=>void }) {
  const { t } = useT();
  const me = sessionUser("admin");
  const [name,setName] = useState(me?.full_name || "");
  const [commission,setCommission] = useState("10");
  const [saved,setSaved] = useState(false);
  const [commSaved,setCommSaved] = useState(false);
  const { data:settings } = useAsync<any>(()=>getAdminSystemSettings(), []);
  useEffect(()=>{ if(settings?.driver_commission_percent!==undefined) setCommission(String(settings.driver_commission_percent)); },[settings]);

  const [profileErr,setProfileErr] = useState("");
  const [commErr,setCommErr] = useState("");
  async function saveProfile(){ setProfileErr(""); try { await updateAdminMe({ full_name: name||null }); setSaved(true); setTimeout(()=>setSaved(false),2000); } catch(e){ setProfileErr(getUzbekErrorMessage(e)); } }
  async function saveComm(){ setCommErr(""); try { await updateDriverCommission(Number(commission)); setCommSaved(true); setTimeout(()=>setCommSaved(false),2000); } catch(e){ setCommErr(getUzbekErrorMessage(e)); } }

  return (
    <div className="p-6 max-w-2xl space-y-6">
      {/* Profile card */}
      <div className="bg-card border border-slate-200 rounded-lg p-6">
        <div className="flex items-center gap-4 mb-6 pb-6 border-b border-slate-100">
          <div className="w-16 h-16 rounded-xl bg-primary/10 flex items-center justify-center"><ShieldCheck size={28} className="text-primary"/></div>
          <div>
            <p className="text-lg font-bold text-slate-800">{name||"Admin"}</p>
            <p className="text-sm text-slate-500 font-mono">{sessionPhone("admin")||"—"}</p>
            <div className="flex gap-2 mt-1"><AdminStatusBadge status={me?.role||"admin"}/><AdminStatusBadge status="active"/></div>
          </div>
        </div>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500 block mb-2">{t("admFullName")}</label>
            <div className="flex gap-3">
              <input className="flex-1 border border-slate-200 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-blue-400" value={name} onChange={e=>setName(e.target.value)}/>
              <button onClick={saveProfile} className={`px-4 rounded-lg text-sm font-medium transition-colors ${saved?"bg-green-50 text-green-700 border border-green-200":"bg-primary text-white hover:bg-blue-700"}`}>
                {saved?<><CheckCircle2 size={14} className="inline mr-1"/>{t("admSaved")}</>:t("admSave")}
              </button>
            </div>
            {profileErr && <p className="mt-2 text-sm text-red-600">{profileErr}</p>}
          </div>
          <div className="grid grid-cols-2 gap-4">
            {[{l:t("admRole"),v:t("admSuperAdmin")},{l:t("admPhoneVerified"),v:t("admYes")},{l:t("admLastLogin"),v:"Jun 25, 09:00"},{l:t("admAccountCreated"),v:"Dec 1, 2024"}].map(({l,v})=>(
              <div key={l}><p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">{l}</p><p className="text-sm font-medium text-slate-700">{v}</p></div>
            ))}
          </div>
        </div>
        <div className="flex gap-3 mt-6 pt-6 border-t border-slate-100">
          <button onClick={onLogout} className="flex items-center gap-2 text-red-600 border border-red-200 px-4 py-2 rounded-lg text-sm font-medium hover:bg-red-50"><LogOut size={14}/>{t("admLogout")}</button>
          <button className="flex items-center gap-2 text-slate-600 border border-slate-200 px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-50"><RefreshCw size={14}/>{t("admRefreshProfile")}</button>
        </div>
      </div>

      {/* Commission card */}
      <div className="bg-card border border-slate-200 rounded-lg p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center"><DollarSign size={18} className="text-emerald-600"/></div>
          <div><p className="text-base font-semibold text-slate-800">{t("admPlatformCommission")}</p><p className="text-xs text-slate-500">{t("admCommissionDesc")}</p></div>
        </div>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500 block mb-2">{t("admCommissionPct")}</label>
            <div className="flex items-center border border-slate-200 rounded-lg overflow-hidden">
              <input type="number" min="0" max="50" className="flex-1 px-3 py-2.5 text-sm outline-none font-mono" value={commission} onChange={e=>setCommission(e.target.value)}/>
              <span className="px-3 py-2.5 bg-slate-50 border-l border-slate-200 text-sm text-slate-500 font-mono">%</span>
            </div>
          </div>
          <button onClick={saveComm} className={`px-5 py-2.5 rounded-lg text-sm font-medium transition-colors ${commSaved?"bg-green-50 text-green-700 border border-green-200":"bg-primary text-white hover:bg-blue-700"}`}>
            {commSaved?<><CheckCircle2 size={14} className="inline mr-1"/>{t("admSaved")}</>:t("admSave")}
          </button>
        </div>
        {commErr && <p className="mt-2 text-sm text-red-600">{commErr}</p>}
        <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-xs text-amber-700 font-medium">{t("admCommissionWarn")}</p>
        </div>
      </div>
    </div>
  );
}

// ── Admin App Shell ───────────────────────────────────────────────────────────

const ADMIN_NAV: { id:AdminSection; icon:typeof Home; labelKey:TKey }[] = [
  { id:"dashboard",     icon:LayoutDashboard, labelKey:"admDashboard"     },
  { id:"orders",        icon:Package,         labelKey:"admOrders"        },
  { id:"drivers",       icon:Truck,           labelKey:"admDrivers"       },
  { id:"clients",       icon:Users,           labelKey:"admClients"       },
  { id:"regions",       icon:MapPin,          labelKey:"admRegions"       },
  { id:"tariffs",       icon:Tag,             labelKey:"admTariffs"       },
  { id:"disputes",      icon:Flag,            labelKey:"admDisputes"      },
  { id:"staff",         icon:ShieldCheck,     labelKey:"admStaff"         },
  { id:"notifications", icon:Bell,            labelKey:"admNotifications" },
  { id:"audit",         icon:ClipboardList,   labelKey:"admAuditLog"      },
  { id:"profile",       icon:User,            labelKey:"admProfile"       },
];

function AdminApp({ onLogout }: { onLogout:()=>void }) {
  const { t } = useT();
  const { lang, setLang } = useApp();
  const [section,setSection] = useState<AdminSection>("dashboard");
  const [collapsed,setCollapsed] = useState(false);
  const [refreshKey,setRefreshKey] = useState(0);

  const current = ADMIN_NAV.find(n=>n.id===section)!;
  const { data:dispData } = useAsync<any>(()=>listAdminDisputes({ status:"open", limit:1 }), [refreshKey]);
  const { data:notifData } = useAsync<any>(()=>getAdminNotifications({ is_read:"unread", limit:1 }), [refreshKey]);
  const unreadDisputes = dispData?.pagination?.total ?? 0;
  const unreadNotifs   = notifData?.pagination?.total ?? 0;

  return (
    <div className="flex h-screen bg-slate-100 overflow-hidden" style={{fontFamily:"Inter, sans-serif"}}>
      {/* Sidebar */}
      <aside className={`flex-shrink-0 flex flex-col bg-[#0f172a] transition-all duration-200 ${collapsed?"w-16":"w-60"}`}>
        {/* Brand */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-white/10 flex-shrink-0">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center flex-shrink-0"><Truck size={16} className="text-white"/></div>
          {!collapsed && <div className="min-w-0"><p className="text-sm font-bold text-white truncate">Elchi Admin</p><p className="text-[10px] text-white/40">{t("admBrandSubtitle")}</p></div>}
        </div>

        {/* Nav items */}
        <nav className="flex-1 overflow-y-auto py-3 space-y-0.5 px-2">
          {ADMIN_NAV.map(({ id,icon:Icon,labelKey })=>{
            const active = section===id;
            const label = t(labelKey);
            const badge = id==="disputes"?unreadDisputes:id==="notifications"?unreadNotifs:0;
            return (
              <button key={id} onClick={()=>setSection(id)}
                className={`w-full flex items-center gap-3 rounded-lg transition-all ${collapsed?"justify-center px-0 py-2.5":"px-3 py-2"} ${active?"bg-primary text-white":"text-white/60 hover:bg-white/5 hover:text-white"}`}
                title={collapsed?label:undefined}>
                <div className="relative flex-shrink-0">
                  <Icon size={16}/>
                  {badge>0 && <div className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-red-500 flex items-center justify-center"><span className="text-[8px] font-bold text-white">{badge}</span></div>}
                </div>
                {!collapsed && <span className="text-sm font-medium flex-1 text-left">{label}</span>}
                {!collapsed && badge>0 && <span className="text-[10px] bg-red-500 text-white px-1.5 py-0.5 rounded-full font-bold">{badge}</span>}
              </button>
            );
          })}
        </nav>

        {/* Collapse toggle */}
        <div className="border-t border-white/10 p-3">
          <button onClick={()=>setCollapsed(c=>!c)} className="w-full flex items-center justify-center gap-2 text-white/40 hover:text-white transition-colors py-2 rounded-lg hover:bg-white/5">
            {collapsed?<PanelLeft size={16}/>:<><PanelLeftClose size={16}/>{!collapsed&&<span className="text-xs">{t("admCollapse")}</span>}</>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top header */}
        <header className="flex-shrink-0 bg-card border-b border-slate-200 flex items-center justify-between px-6 h-14">
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold text-slate-800">{t(current.labelKey)}</h1>
            <AdminStatusBadge status="super_admin"/>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center bg-slate-100 rounded-lg p-0.5">
              {([["uz","UZ"],["ru","RU"],["en","EN"]] as [Lang,string][]).map(([l,lbl])=>(
                <button key={l} onClick={()=>setLang(l)}
                  className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-colors ${lang===l?"bg-primary text-white":"text-slate-600 hover:text-slate-800"}`}>
                  {lbl}
                </button>
              ))}
            </div>
            <button onClick={()=>setRefreshKey(k=>k+1)} className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-xs text-slate-600 hover:bg-slate-50 transition-colors">
              <RefreshCw size={12}/> {t("admRefresh")}
            </button>
            <button onClick={onLogout} className="flex items-center gap-1.5 px-3 py-1.5 border border-red-200 rounded-lg text-xs text-red-600 hover:bg-red-50 transition-colors">
              <LogOut size={12}/> {t("admLogout")}
            </button>
          </div>
        </header>

        {/* Scrollable content */}
        <main className="flex-1 overflow-y-auto" key={refreshKey}>
          {section==="dashboard"     && <AdminDashboard onNav={setSection}/>}
          {section==="orders"        && <AdminOrders/>}
          {section==="drivers"       && <AdminDrivers/>}
          {section==="clients"       && <AdminClients/>}
          {section==="regions"       && <AdminRegions/>}
          {section==="tariffs"       && <AdminTariffs/>}
          {section==="disputes"      && <AdminDisputesSection/>}
          {section==="staff"         && <AdminStaffSection/>}
          {section==="notifications" && <AdminNotificationsSection/>}
          {section==="audit"         && <AdminAuditLogSection/>}
          {section==="profile"       && <AdminProfileSection onLogout={onLogout}/>}
        </main>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ROOT
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// PAGES
// ═══════════════════════════════════════════════════════════════════════════════

// ── Root Layout — shared state across all routes ──────────────────────────────

function RootLayout() {
  const [role,      setRole]      = useState<Role>("driver");
  const [phone,     setPhone]     = useState("");
  const [themeMode, setThemeMode] = useState<ThemeMode>("dark");
  const [lang,      setLang]      = useState<Lang>("uz");

  const systemDark = window.matchMedia?.("(prefers-color-scheme:dark)").matches ?? true;
  const isDark = themeMode === "dark" || (themeMode === "system" && systemDark);

  const tFn = (k: TKey): string => {
    const v = (T[lang] as Record<string, unknown>)[k as string];
    if (Array.isArray(v)) return v as unknown as string;
    return String(v ?? (T.en as Record<string, unknown>)[k as string] ?? k);
  };

  return (
    <AppCtx.Provider value={{ role, setRole, phone, setPhone, themeMode, setThemeMode, lang, setLang, isDark }}>
      <LangCtx.Provider value={{ lang, t: tFn }}>
        <Outlet />
      </LangCtx.Provider>
    </AppCtx.Provider>
  );
}

// ── / — Auth page (splash → onboarding → role-select → phone → otp) ──────────

function AuthPage() {
  const { role, setRole, phone, setPhone, isDark } = useApp();
  const navigate = useNavigate();
  const [authStep, setAuthStep] = useState<Exclude<AuthStep, "app">>("splash");
  const [devOtp, setDevOtp] = useState<string | undefined>();

  // If a valid session already exists for this role, skip straight into the app.
  useEffect(() => {
    let active = true;
    if (isSessionActive(role)) {
      sessionRefreshMe(role).then(me => { if (active && me) navigate(`/${role}`, { replace: true }); });
    }
    return () => { active = false; };
  }, [role, navigate]);

  async function requestOtpFor(p: string) {
    setPhone(p);
    const res = await sessionRequestOtp(role, p);
    setDevOtp(res.devOtp);
    setAuthStep("otp");
  }
  async function resendOtp() {
    const res = await sessionRequestOtp(role, phone);
    setDevOtp(res.devOtp);
    return res.devOtp;
  }
  async function verifyOtpFor(code: string) {
    await sessionVerifyOtp(role, phone, code);
    navigate(`/${role}`, { replace: true });
  }

  // Admin: centered card on dark background
  if (role === "admin") {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-6" style={{ fontFamily: "Inter, sans-serif" }}>
        <div className="w-full max-w-sm bg-card rounded-2xl shadow-2xl overflow-hidden">
          <div className="bg-[#0f172a] px-6 py-5 flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center"><Truck size={16} className="text-white" /></div>
            <div><p className="text-sm font-bold text-white">Elchi Admin</p><p className="text-[10px] text-white/40">Management Panel</p></div>
          </div>
          <div key={authStep} className="h-[480px] overflow-hidden dark screen-in">
            {authStep === "splash"      && <SplashScreen onDone={() => setAuthStep("role-select")} />}
            {authStep === "role-select" && <RoleSelectScreen onSelect={r => { setRole(r); setAuthStep("phone"); }} onBack={() => setAuthStep("splash")} />}
            {authStep === "phone"       && <PhoneScreen role={role} onSubmit={requestOtpFor} onBack={() => setAuthStep("role-select")} />}
            {authStep === "otp"         && <OtpScreen phone={phone} role={role} onVerify={verifyOtpFor} onResend={resendOtp} devOtp={devOtp} onBack={() => setAuthStep("phone")} />}
          </div>
        </div>
      </div>
    );
  }

  // Client / Driver: phone frame
  return (
    <div className={isDark ? "dark" : ""}>
      <div className="min-h-screen flex items-center justify-center p-4 transition-colors duration-300"
        style={{ fontFamily: "Inter, sans-serif", background: isDark ? "#060a0f" : "#e8edf5" }}>
        <div className="relative w-full max-w-[390px] h-[844px] bg-background rounded-[44px] overflow-hidden flex flex-col transition-colors duration-300"
          style={{ boxShadow: isDark ? "0 40px 80px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.05)" : "0 40px 80px rgba(0,0,0,0.2), 0 0 0 1px rgba(0,0,0,0.06)" }}>
          {/* Status bar */}
          <div className="flex items-center justify-between px-8 pt-4 pb-1 flex-shrink-0">
            <span className="text-[11px] font-semibold text-foreground font-mono">9:41</span>
            <div className="w-28 h-6 rounded-full" style={{ background: isDark ? "#000" : "#111827" }} />
            <div className="flex items-center gap-1">
              <div className="flex gap-0.5 items-end">{[3, 5, 7, 9].map((h, i) => <div key={i} className="w-1 rounded-sm bg-foreground/70" style={{ height: h }} />)}</div>
              <Bell size={10} className="text-foreground/70 ml-1" />
            </div>
          </div>
          <div key={authStep} className="flex-1 overflow-hidden screen-in">
            {authStep === "splash"      && <SplashScreen onDone={() => setAuthStep("onboarding")} />}
            {authStep === "onboarding"  && <OnboardingScreen onContinue={() => setAuthStep("role-select")} />}
            {authStep === "role-select" && <RoleSelectScreen onSelect={r => { setRole(r); setAuthStep("phone"); }} onBack={() => setAuthStep("onboarding")} />}
            {authStep === "phone"       && <PhoneScreen role={role} onSubmit={requestOtpFor} onBack={() => setAuthStep("role-select")} />}
            {authStep === "otp"         && <OtpScreen phone={phone} role={role} onVerify={verifyOtpFor} onResend={resendOtp} devOtp={devOtp} onBack={() => setAuthStep("phone")} />}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── /driver ───────────────────────────────────────────────────────────────────

function DriverPage() {
  const { themeMode, setThemeMode, lang, setLang, isDark } = useApp();
  const navigate = useNavigate();
  useEffect(() => { if (!isSessionActive("driver")) navigate("/", { replace: true }); }, [navigate]);
  const handleLogout = async () => { await sessionLogout("driver"); navigate("/", { replace: true }); };
  const tFn = (k: TKey): string => {
    const v = (T[lang] as Record<string, unknown>)[k as string];
    if (Array.isArray(v)) return v as unknown as string;
    return String(v ?? (T.en as Record<string, unknown>)[k as string] ?? k);
  };
  return (
    <LangCtx.Provider value={{ lang, t: tFn }}>
      <div className={isDark ? "dark" : ""}>
        <div className="min-h-screen flex items-center justify-center p-4 transition-colors duration-300"
          style={{ fontFamily: "Inter, sans-serif", background: isDark ? "#060a0f" : "#e8edf5" }}>
          <div className="relative w-full max-w-[390px] h-[844px] bg-background rounded-[44px] overflow-hidden flex flex-col transition-colors duration-300"
            style={{ boxShadow: isDark ? "0 40px 80px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.05)" : "0 40px 80px rgba(0,0,0,0.2), 0 0 0 1px rgba(0,0,0,0.06)" }}>
            {/* Status bar */}
            <div className="flex items-center justify-between px-8 pt-4 pb-1 flex-shrink-0">
              <span className="text-[11px] font-semibold text-foreground font-mono">9:41</span>
              <div className="w-28 h-6 rounded-full" style={{ background: isDark ? "#000" : "#111827" }} />
              <div className="flex items-center gap-1">
                <div className="flex gap-0.5 items-end">{[3, 5, 7, 9].map((h, i) => <div key={i} className="w-1 rounded-sm bg-foreground/70" style={{ height: h }} />)}</div>
                <Bell size={10} className="text-foreground/70 ml-1" />
              </div>
            </div>
            <DriverApp themeMode={themeMode} onThemeChange={setThemeMode} lang={lang} onLangChange={setLang} onLogout={handleLogout} />
          </div>
        </div>
      </div>
    </LangCtx.Provider>
  );
}

// ── /client ───────────────────────────────────────────────────────────────────

function ClientPage() {
  const { themeMode, setThemeMode, lang, setLang, isDark } = useApp();
  const navigate = useNavigate();
  useEffect(() => { if (!isSessionActive("client")) navigate("/", { replace: true }); }, [navigate]);
  const handleLogout = async () => { await sessionLogout("client"); navigate("/", { replace: true }); };
  const phone = sessionPhone("client");
  const tFn = (k: TKey): string => {
    const v = (T[lang] as Record<string, unknown>)[k as string];
    if (Array.isArray(v)) return v as unknown as string;
    return String(v ?? (T.en as Record<string, unknown>)[k as string] ?? k);
  };
  return (
    <LangCtx.Provider value={{ lang, t: tFn }}>
      <div className={isDark ? "dark" : ""}>
        <div className="min-h-screen flex items-center justify-center p-4 transition-colors duration-300"
          style={{ fontFamily: "Inter, sans-serif", background: isDark ? "#060a0f" : "#e8edf5" }}>
          <div className="relative w-full max-w-[390px] h-[844px] bg-background rounded-[44px] overflow-hidden flex flex-col transition-colors duration-300"
            style={{ boxShadow: isDark ? "0 40px 80px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.05)" : "0 40px 80px rgba(0,0,0,0.2), 0 0 0 1px rgba(0,0,0,0.06)" }}>
            {/* Status bar */}
            <div className="flex items-center justify-between px-8 pt-4 pb-1 flex-shrink-0">
              <span className="text-[11px] font-semibold text-foreground font-mono">9:41</span>
              <div className="w-28 h-6 rounded-full" style={{ background: isDark ? "#000" : "#111827" }} />
              <div className="flex items-center gap-1">
                <div className="flex gap-0.5 items-end">{[3, 5, 7, 9].map((h, i) => <div key={i} className="w-1 rounded-sm bg-foreground/70" style={{ height: h }} />)}</div>
                <Bell size={10} className="text-foreground/70 ml-1" />
              </div>
            </div>
            <ClientApp phone={phone} themeMode={themeMode} onThemeChange={setThemeMode} lang={lang} onLangChange={setLang} onLogout={handleLogout} />
          </div>
        </div>
      </div>
    </LangCtx.Provider>
  );
}

// ── /admin ────────────────────────────────────────────────────────────────────

function AdminLogin({ step, phone, onRequestOtp, onVerify, onResend, onExit }: {
  step:"phone"|"otp"; phone:string;
  onRequestOtp:(phone:string)=>Promise<void>; onVerify:(code:string)=>Promise<void>;
  onResend:()=>Promise<string|undefined>; onExit:()=>void;
}) {
  const { t } = useT();
  const [rest,setRest] = useState("");
  const [code,setCode] = useState("");
  const [err,setErr] = useState("");
  const [loading,setLoading] = useState(false);
  const [resend,setResend] = useState(0);
  const [focused,setFocused] = useState(true);
  useEffect(()=>{ setErr(""); if(step==="otp"){ setCode(""); setResend(59); } },[step]);
  useEffect(()=>{ if(resend<=0)return; const id=setInterval(()=>setResend(s=>s-1),1000); return()=>clearInterval(id); },[resend]);
  const digits = rest.replace(/\D/g,"").slice(0,9);
  const shownPhone = [digits.slice(0,2),digits.slice(2,5),digits.slice(5,7),digits.slice(7,9)].filter(Boolean).join(" ");
  const complete = code.length===OTP_LENGTH;
  async function submitPhone(){
    if(digits.length<9){ setErr(t("phoneError")); return; }
    setLoading(true); setErr("");
    try { await onRequestOtp("+998"+digits); }
    catch(e){ setErr(getUzbekErrorMessage(e)); }
    finally { setLoading(false); }
  }
  async function submitOtp(){
    if(!complete){ setErr(t("otpError")); return; }
    setLoading(true); setErr("");
    try { await onVerify(code); }
    catch(e){ setErr(getUzbekErrorMessage(e)); setLoading(false); }
  }
  async function resendCode(){ setErr(""); try { await onResend(); setResend(59); } catch(e){ setErr(getUzbekErrorMessage(e)); } }

  return (
    <div className="min-h-screen w-full bg-slate-100 flex items-center justify-center p-4" style={{ fontFamily:"Inter, sans-serif" }}>
      <div className="w-full max-w-4xl bg-white rounded-2xl shadow-[0_24px_60px_-20px_rgba(15,23,42,0.35)] overflow-hidden grid md:grid-cols-2 border border-slate-200">
        {/* Brand panel */}
        <div className="hidden md:flex flex-col justify-between p-10 bg-[#0f172a] text-white relative overflow-hidden">
          <div className="absolute -right-16 -top-16 w-64 h-64 rounded-full bg-[#1B4FD8]/20 blur-2xl pointer-events-none"/>
          <div className="relative flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[#1B4FD8] flex items-center justify-center"><Truck size={20} className="text-white"/></div>
            <div><p className="text-base font-bold leading-tight">Elchi Admin</p><p className="text-[11px] text-white/40">Management Panel</p></div>
          </div>
          <div className="relative">
            <h1 className="text-2xl font-bold leading-tight mb-3">{t("admLoginHeading")}</h1>
            <p className="text-sm text-white/50 leading-relaxed max-w-xs">{t("admPanelBlurb")}</p>
          </div>
          <p className="relative text-[11px] text-white/30">© Elchi · Management Panel</p>
        </div>

        {/* Form panel */}
        <div className="p-8 sm:p-12 flex flex-col justify-center min-h-[440px]">
          <div className="md:hidden flex items-center gap-3 mb-8">
            <div className="w-9 h-9 rounded-xl bg-[#1B4FD8] flex items-center justify-center"><Truck size={18} className="text-white"/></div>
            <div><p className="text-sm font-bold text-slate-900">Elchi Admin</p><p className="text-[10px] text-slate-400">Management Panel</p></div>
          </div>

          {step==="phone" ? (
            <>
              <h2 className="text-2xl font-bold text-slate-900 mb-1.5">{t("admLoginHeading")}</h2>
              <p className="text-sm text-slate-500 mb-8">{t("admLoginDesc")}</p>
              <label className="text-xs font-semibold text-slate-500 mb-2 block">{t("phoneLabel")}</label>
              <div className={`flex items-center gap-3 rounded-xl border bg-slate-50 px-4 h-14 transition-colors ${err?"border-red-400":"border-slate-200 focus-within:border-[#1B4FD8]"}`}>
                <span className="text-[11px] font-bold text-[#1B4FD8] bg-[#1B4FD8]/10 rounded-md px-2 py-1">UZ</span>
                <span className="text-base font-bold text-slate-900">+998</span>
                <input autoFocus type="text" inputMode="numeric" value={shownPhone}
                  onChange={e=>{ setRest(e.target.value); if(err)setErr(""); }}
                  onKeyDown={e=>{ if(e.key==="Enter") submitPhone(); }}
                  placeholder="90 123 45 67"
                  className="flex-1 bg-transparent text-base font-bold font-mono text-slate-900 placeholder:text-slate-300 outline-none"/>
              </div>
              {err && <p className="mt-2 text-xs text-red-500 flex items-center gap-1"><AlertCircle size={12}/>{err}</p>}
              <button onClick={submitPhone} disabled={loading||digits.length<9}
                className="mt-8 w-full rounded-xl bg-[#1B4FD8] text-white text-sm font-semibold flex items-center justify-center gap-2 py-4 hover:bg-[#1746c4] active:scale-[0.99] transition disabled:opacity-50 disabled:cursor-not-allowed">
                {loading?<span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<>{t("phoneCta")}<ArrowRight size={18}/></>}
              </button>
            </>
          ) : (
            <>
              <button onClick={()=>onExit()} className="self-start mb-6 w-9 h-9 rounded-full bg-slate-100 hover:bg-slate-200 flex items-center justify-center transition-colors"><ChevronLeft size={18} className="text-slate-600"/></button>
              <h2 className="text-2xl font-bold text-slate-900 mb-1.5">{t("otpTitle")}</h2>
              <p className="text-sm text-slate-500 mb-8">{t("admOtpSentTo")} <span className="font-mono font-semibold text-slate-700">+998 {shownPhone||phone}</span></p>
              <div className="relative">
                <input type="text" inputMode="numeric" autoComplete="one-time-code" autoFocus value={code}
                  onChange={e=>{ setCode(e.target.value.replace(/\D/g,"").slice(0,OTP_LENGTH)); if(err)setErr(""); }}
                  onKeyDown={e=>{ if(e.key==="Enter"&&complete) submitOtp(); }}
                  onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)}
                  className="absolute inset-0 z-10 w-full h-full opacity-0 cursor-pointer"/>
                <div className="grid grid-cols-5 gap-3">
                  {Array.from({length:OTP_LENGTH}).map((_,i)=>{
                    const char = code[i] ?? "";
                    const isCurrent = focused && i===code.length;
                    const cls = err ? "border-red-400 bg-red-50" : char ? "border-[#1B4FD8] bg-[#1B4FD8]/5" : isCurrent ? "border-[#1B4FD8] bg-white" : "border-slate-200 bg-slate-50";
                    return <div key={i} className={`aspect-square rounded-xl border-2 flex items-center justify-center text-xl font-bold font-mono text-slate-900 transition-all ${cls}`}>{char||(isCurrent?<span className="w-0.5 h-6 bg-[#1B4FD8] rounded-full animate-pulse"/>:"")}</div>;
                  })}
                </div>
              </div>
              {err && <p className="mt-3 text-xs text-red-500 flex items-center gap-1"><AlertCircle size={12}/>{err}</p>}
              <div className="mt-5 flex justify-center">
                {resend>0
                  ?<p className="text-xs text-slate-400 font-mono">{t("otpResendIn")} 0:{resend.toString().padStart(2,"0")}</p>
                  :<button onClick={resendCode} className="flex items-center gap-1 text-xs text-[#1B4FD8] font-medium hover:underline"><RefreshCw size={12}/>{t("otpResend")}</button>}
              </div>
              <button onClick={submitOtp} disabled={loading||!complete}
                className="mt-8 w-full rounded-xl bg-[#1B4FD8] text-white text-sm font-semibold flex items-center justify-center gap-2 py-4 hover:bg-[#1746c4] active:scale-[0.99] transition disabled:opacity-50 disabled:cursor-not-allowed">
                {loading?<span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"/>:<>{t("otpVerify")}<ArrowRight size={18}/></>}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function AdminPage() {
  const { lang } = useApp();
  const navigate = useNavigate();
  // Self-contained admin auth: /admin shows its own phone+OTP login (no public entry button).
  const [status, setStatus] = useState<"checking" | "login" | "authed">(isSessionActive("admin") ? "checking" : "login");
  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [phone, setPhoneState] = useState("");
  const [devOtp, setDevOtp] = useState<string | undefined>();

  // Validate any stored admin session before mounting the panel (avoids 401 loops on expired tokens).
  useEffect(() => {
    if (status !== "checking") return;
    let active = true;
    sessionRefreshMe("admin")
      .then(me => { if (active) setStatus(me ? "authed" : "login"); })
      .catch(() => { if (active) setStatus("login"); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const requestOtp = async (p: string) => { setPhoneState(p); const res = await sessionRequestOtp("admin", p); setDevOtp(res.devOtp); setStep("otp"); };
  const resendOtp = async () => { const res = await sessionRequestOtp("admin", phone); setDevOtp(res.devOtp); return res.devOtp; };
  const verifyOtp = async (code: string) => { await sessionVerifyOtp("admin", phone, code); setStatus("authed"); };
  const handleLogout = async () => { await sessionLogout("admin"); setStep("phone"); setStatus("login"); };

  const tFn = (k: TKey): string => {
    const v = (T[lang] as Record<string, unknown>)[k as string];
    if (Array.isArray(v)) return v as unknown as string;
    return String(v ?? (T.en as Record<string, unknown>)[k as string] ?? k);
  };

  return (
    <LangCtx.Provider value={{ lang, t: tFn }}>
      {status === "authed" ? (
        <AdminApp onLogout={handleLogout} />
      ) : status === "checking" ? (
        <div className="min-h-screen bg-background flex items-center justify-center">
          <span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : (
        <AdminLogin
          step={step}
          phone={phone}
          onRequestOtp={requestOtp}
          onVerify={verifyOtp}
          onResend={resendOtp}
          onExit={() => setStep("phone")}
        />
      )}
    </LangCtx.Provider>
  );
}

// ── Router ────────────────────────────────────────────────────────────────────

const router = createBrowserRouter([
  {
    path: "/",
    Component: RootLayout,
    children: [
      { index: true,       Component: AuthPage   },
      { path: "driver",    Component: DriverPage  },
      { path: "client",    Component: ClientPage  },
      { path: "admin",     Component: AdminPage   },
      { path: "*",         element: <Navigate to="/" replace /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
