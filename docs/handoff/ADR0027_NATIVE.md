# ADR-0027 — Android/iOS uchun topshiriq (handoff)

**Kim uchun:** `android-app/` va `ios-app/` dasturchisi. **Sana:** 06.10.2026. **Holat:** backend va `mobile-app` (web)
tayyor; native ilovalar **o'zgartirilmagan** (foydalanuvchi qarori, Q156).

## Hozir nima ishlaydi va nima buzilmaydi
- Barcha mavjud endpointlar o'zgarmagan: native ilova `POST /trips` + `GET /feed?side=requests` bilan avvalgidek
  ishlaydi. Yangi maydonlar additiv (`ignoreUnknownKeys` / `Codable` ularni e'tiborsiz qoldiradi).
- `scripts/gen_native_api.py --check` endi **stale** deydi (OpenAPI'ga yangi endpoint va maydonlar qo'shildi). Uni
  qayta generatsiya qilish — sizning ishingiz (`python scripts/gen_native_api.py`), agentlar native fayllarga tegmaydi.

## Yangi oqim (web klientda bor, native'da qilish tavsiya etiladi)
Haydovchi faqat **yo'nalish** qo'shadi; safar, bekat, vaqt va koridorni server o'zi bajaradi.

1. **Yo'nalish qo'shish** — `POST /api/v2/driver-directions`
   `{origin: {region_id, district_id?}, destination: {region_id, district_id?}}` (mashina bitta bo'lsa `vehicle_id`
   shart emas; sig'im mashinadan). `409 ROUTE_MISMATCH` = «bu yo'nalishda hali ELCHI yo'li yo'q».
2. **Yo'nalishlarim** — `GET /api/v2/me/driver-directions`; to'xtatish/arxiv — `PATCH /driver-directions/{id}`
   `{expected_version, status: paused|active|archived}`.
3. **Mos so'rovlar** — `GET /api/v2/driver-directions/{id}/requests?service_type&date_from&date_to`.
   Har element: `fit` — `fits_trip` (safaringizga mos), `no_trip` (birinchi taklif safarni rejalashtiradi),
   `time_differs` (mashina `pickup_eta` da yetadi — mijoz boshqa vaqt so'ragan); `match_type` — `exact` / `on_route`.
4. **Taklif** — `POST /api/v2/driver-directions/{id}/offers` `{listing_id, unit_price_minor, message?}`.
   Javobda `trip_created` / `trip_retimed` — haydovchiga «Safar 06:20 da jo'nashga rejalashtirildi» deb ayting.
   `409 TIME_WINDOW_CONFLICT` + `details.eta` → «Mashina 22:30 da yetadi. Shu vaqtni taklif qilasizmi?» →
   xuddi shu so'rov `pickup_at = details.eta` bilan (vaqt taklifi).
5. **Mijoz tomoni** — `ProposalVersionDTO.outside_request_window = true` bo'lsa kartada: «Haydovchi HH:MM da olishni
   taklif qilmoqda (siz HH:MM–HH:MM so'ragansiz)». Qabul qilish yoki narxni counter qilish — rozilik.
6. **Yo'lda bron** — safar `boarding`/`in_progress` bo'lsa ham mos so'rovlar chiqadi va taklif ishlaydi (mashina
   o'tib ketmagan nuqtalar). `409 BOOKING_CUTOFF_PASSED` + `details.reason = pickup_passed` → «Bu joydan o'tib ketdingiz».

## Xato kodlari (tarjima kerak)
`ROUTE_CHANGED` web lug'atida ham yo'q edi — `mobile-app/src/i18n/messages.ts` ga qo'shildi; native satrlar
`scripts/gen_native_strings.mjs` bilan shu lug'atdan olinadi.
