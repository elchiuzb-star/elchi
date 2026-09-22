# QA topilmalari — spetsifikatsiya auditi, 17.09.2026

**Doira:** `ELCHI_PRODUCTION_ARCHITECTURE.md` v1.0 talablari ↔ haqiqiy repository, ishlayotgan backend (`:8001`, doimiy dev bazasi), `mobile-app` klienti va PostgreSQL.
**Usul:** jonli HTTP oqimlari + har qadamdan keyin bazani o'qish (`scratchpad/e2e.py`, `e2e_flow.py`), kod tekshiruvi, mavjud test to'plami.
**Qoida:** har topilma «aniqlandi → tuzatildi → tekshirildi → dalil» tartibida yopiladi. Tuzatilmagan band ochiq deb qoladi.

| ID | Jiddiylik | Holat | Qisqacha |
|---|---|---|---|
| F-01 | **P0** | ✅ Yopildi | Routing provayderi o'chiq bo'lsa haydovchi **umuman safar yarata olmasdi** → supply tomoni ishlamasdi |
| F-02 | P2 | ✅ Yopildi | Haydovchi hamyonida kiritilgan (posted) balans ko'rsatilmasdi |
| F-03 | P1 | ✅ Yopildi | Qarshi taklif klientda yo'q edi — ikki tomonlama kelishuvning yarmi |
| F-04 | P2 | ✅ Yopildi | Yo'nalish tanlashda viloyat/tuman koridor ortida qulflangan edi (wave 10 davomida) |
| F-05 | P3 | 📋 Ochiq (hujjatlangan) | v2 klient 150 yo'ldan 68 tasini chaqiradi; qolganining tasnifi |
| F-06 | P1 | ✅ Yopildi | Dev muhiti: backend tmpfs test bazasida ishlayotgan edi; `.env` v1 revizyali bazaga ko'rsatardi |

---

## F-01 — Routing provayderi o'chiq bo'lganda supply tomoni ishlamaydi (**P0**)

**Kutilgan xulq** (§4 P0, §5.1, §5.3, §16, A1/A9 kartalari): tasdiqlangan haydovchi safar rejalashtiradi, `trip_offer` e'lon qiladi yoki mijoz so'roviga safarini biriktirib taklif beradi.

**Amaldagi xulq:** `POST /api/v2/trips` majburiy `route_version_id` so'raydi. Uni olishning **yagona** yo'li `POST /api/v2/routes/preview` (G5) edi, u esa routing provayderini talab qiladi. Provayder Q24/Q46 bo'yicha **ataylab o'chiq** (huquqiy/data-flow tekshiruvigacha) — ya'ni production aynan shu konfiguratsiyada ishlaydi.

**Takrorlash:**
```
1. Tasdiqlangan haydovchi sifatida kiring.
2. POST /api/v2/routes/preview {stop_ids, departure_at}
   -> 503 {"code":"ROUTING_UNAVAILABLE","message":"Routing/maps provider unavailable; no fake match (AC35)."}
3. Boshqa hech qanday endpoint mavjud `route_version_id` ni qaytarmaydi
   (v2 da faqat /routes/preview va /routes/{id}/confirm bor edi).
4. Demak POST /api/v2/trips hech qachon chaqirib bo'lmaydi.
```

**Ta'sir:** safar yo'q → `trip_offer` e'loni yo'q → `ProposalCreate.trip_id` bilan taklif yo'q → **marketplace'ning butun taklif tomoni** production konfiguratsiyasida yopiq. Mijoz so'rov qo'ya oladi, lekin unga hech kim javob bera olmaydi.

**Ildiz sabab:** marshrut katalogining **o'qish endpointi yo'q** edi; marshrut yaratish siyosat bo'yicha o'chirilgan provayderga bog'lab qo'yilgan. Tasdiqlangan marshrutlar bazada bor edi (`route_versions.status='confirmed'`), lekin klient ularni ko'ra olmasdi.

**Tuzatish:**
1. **G18 `GET /api/v2/corridors/{corridor_id}/routes`** — koridorning tasdiqlangan marshrut versiyalari (`app/modules/geo/service.py::list_corridor_routes`, `app/modules/geo/api.py`). Provayder kerak emas: bu marshrutlar avval haydovchi yoki operator tomonidan tasdiqlangan.
2. Klient: `listCorridorRoutes` (`mobile-app/src/api/v2/marketplace.api.ts`) + **yangi ekranlar** `DriverPlanScreens.tsx` — avtomobil ro'yxatdan o'tkazish va marshrutdan safar rejalashtirish; `MarketplaceApp` ga «Yangi safar» va «Avtomobil» tablari qo'shildi.
3. Ekran haqiqatni aytadi: yangi avtomobil «Tekshiruvda», tasdiqlangan marshrut yo'q bo'lsa «operator marshrut qo'shishi kerak».

**Tekshiruv:** `tests/pg/geo/test_geo_routes_catalogue_pg.py` — **4 test o'tdi**, jumladan `test_a_driver_can_plan_a_trip_while_the_routing_provider_refuses`: provayder `503` qaytarayotganda ham katalog haydovchiga ishlaydigan marshrut beradi. Jonli tekshiruv: `GET /corridors/{id}/routes` → 2 ta tasdiqlangan marshrut (512 km / 8.5 soat va 563 km / 9.4 soat).

---

## F-02 — Hamyon ekrani kiritilgan balansni yashirardi (P2)

**Kutilgan** (§9.1, §9.3): UI **alohida** ko'rsatadi — komissiya balansi, band qilingan, mavjud summa, tasdiq kutayotgan to'ldirish. §9.3 misoli aynan `100 000 → hold 60 000 → mavjud 40 000` munosabatiga asoslangan.

**Amaldagi:** `DriverWalletScreen` faqat `available`, `held` va `pending` ni ko'rsatardi. `posted_balance_minor` yo'q edi, shuning uchun haydovchi «mavjud 46 000» va «ushlab turilgan 54 000» ni ko'rardi, lekin **jami qancha kiritgani** ko'rinmasdi — `available = posted − held` munosabati yo'qolardi.

**Tuzatish:** `mobile-app/src/app/v2/DriverScreens.tsx` — «Kiritilgan (jami)» qatori qo'shildi, tartib `posted → held → available`.

**Tekshiruv:** `npm run lint` (tsc) toza; jonli qiymatlar `E2E` E6 bilan mos: `posted=10 000 000`, `held=5 400 000`, `available=4 600 000`.

---

## F-03 — Qarshi taklif klientda yo'q edi (P1)

**Kutilgan** (§5.3, §16, P1 «Qarshi taklif UX'i»): har ikki tomon narxni tuzata oladi; har tuzatish yangi `proposal_version` yaratadi va tomonda cheklangan tuzatish huquqi bor.

**Amaldagi:** backendda `POST /proposals/{id}/counter` va `/withdraw` ishlaydi (E2E C6 bilan tasdiqlandi), lekin `mobile-app` da ularni chaqiradigan **birorta joy yo'q edi** — mijoz faqat «Qabul qilish» yoki rad eta olardi. Ya'ni mahsulotning asosiy g'oyasi — ikki tomonlama narx kelishuvi — ilovada bir tomonlama edi.

**Tuzatish:** `marketplace.api.ts` ga `counterProposal` va `withdrawProposal`; `ListingDetailScreen` ga «Boshqa narx taklif qilish» formasi — joriy narx bilan to'ldiriladi va `price_revisions_left` ni ko'rsatadi («Yana N marta narx taklif qila olasiz, §5.3»).

**Tekshiruv:** tsc toza; endpoint jonli tekshirildi (`E2E` C6 → 200, yangi revision, eski versiya `superseded` → C7 `409 PROPOSAL_CHANGED`).

---

## F-04 — Tuman koridor ortida qulflangan edi (P2, wave 10 davomida yopilgan)

Yo'nalish pikeri viloyat/tuman selektlarini `disabled={!corridorId}` bilan yopgan edi; koridorlar esa bo'sh katalogda nolta bo'lgani uchun foydalanuvchi hech narsa ko'rmasdi. Endi yo'nalish avval tanlanadi, koridor undan kelib chiqadi, bo'sh holat sababi ochiq yoziladi (`DirectionPicker.tsx: CatalogueNotice`). Batafsil: `WAVE1_CARDS.md` «Wave 10».

---

## F-05 — v2 klient API qamrovi (P3, ochiq va hujjatlangan)

Kontraktdagi **150** v2 yo'lidan klient **68** tasini chaqiradi. Qolgan 82 ta ikkiga bo'linadi:

| Turkum | Misollar | Baho |
|---|---|---|
| **Ataylab** | `tracking/sessions*` (GPS haydovchi Android ilovasidan keladi, §10.3/§10.5), `devices/push-token` (FCM yoqilmagan, ADR-0022) | To'g'ri |
| **Ochiq bo'shliq** | `/listings/{id}/matches` (M2 reytingli ro'yxat), naqd kvitansiya oqimi (`/bookings/{id}/cash-receipts`), `/blocks`, `/me/roles`, `/commission/quote`, 46 ta admin yo'li (koridor/bekat/narx band'i, moliya, outbox) | Keyingi kartalar |

Bu **ekran yo'qligi**, xato emas: backend ishlaydi va testlar bilan qoplangan. Operator tomoni hozircha admin panelining 6 ta v2 bo'limi bilan cheklangan.

---

## F-06 — Dev muhiti noto'g'ri bazada ishlayotgan edi (P1, yopildi)

Ishlab turgan backend `docker-compose.test.yml` ning **tmpfs** bazasiga (`:45432`) ulangan edi — har restartda hamma narsa (katalog, akkauntlar) yo'qolardi. `.env` esa `20260705_0027` revizyasidagi v1 bazaga ko'rsatardi, unda 2-bosqich jadvallari umuman yo'q; lokal PostgreSQL'da **PostGIS yo'q** bo'lgani uchun uni migratsiya qilib ham bo'lmaydi.

**Tuzatish:** `docker-compose.dev.yml` — production bilan bir xil PostGIS image, **doimiy volume**, alohida portlar (PG `45433`, Redis `36380`); `.env`/`.env.example` unga yo'naltirildi; `RUNNING.md` da lokal ishga tushirish bo'limi qayta yozildi. Katalog yuklandi: 14 viloyat, 170 tuman, 1 koridor, 6 bekat, 2 tasdiqlangan marshrut.

**Tekshiruv:** konteyner `restart` qilindi — `regions=14, geo_districts=170, corridor_stops=6` joyida qoldi.

---

## F-07 — Posilka rasmi: tekshirilmagan havola bazada, haydovchida esa rasm yo'q (**P1**, wave 13)

**Aniqlandi.** `parcel.photo_file_id` klient yuborgan satrni tekshirmasdan saqlardi. Klient esa
`POST /api/v1/files/upload` qaytargan **imzolangan URL**ni yuborardi. Uch oqibat:

1. muddati o'tadigan credential (`?exp=…&sig=…`) bazada saqlanardi;
2. egalik tekshirilmasdi — boshqa foydalanuvchi yuklagan faylni biriktirish mumkin edi;
3. Q6 bo'yicha rasmni ko'rishi kerak bo'lgan **tayinlangan haydovchi** uni umuman ololmasdi: haydovchi
   `ListingDTO` ni o'qimaydi, `BookingDTO` da esa rasm maydoni yo'q edi.

**Tuzatildi.**

* `MediaRefDTO` (`app/contracts/dto.py`) — `file_id`, `url`, `expires_at`, `content_type`.
* `marketplace/service.py::_resolve_cargo_photo` — `file_access.resolve_attachment` bilan yuklovchiga
  bog'lanadi (`cargo_photo` turi, rasm kengaytmasi), bazaga **kanonik kalit** yoziladi.
* `listing_dto(..., viewer_user_id=...)` — rasm faqat egasi va xodimga; `viewer_user_id` berilmasa na havola,
  na kalit qaytadi (xavfsiz default).
* `BookingClientDTO.parcel_photo` — tayinlangan haydovchi va jo'natuvchiga.
* Xodim rasmni ochsa `listing_contacts_viewed` auditiga `parcel.photo` yoziladi (BR M2).
* Klientda `ParcelPhoto`: loading, placeholder, `onError` → «Qayta yuklash», `expires_at` bo'yicha refetch,
  to'liq ekran. Imzolangan URL endi matn sifatida **chop etilmaydi** (avval «Rasm tayyor: <URL>» ko'rsatilardi).

**Tekshirildi.** `tests/pg/marketplace/test_parcel_photo_access_pg.py` (6 test): begona yuklama, noto'g'ri
upload turi, pdf, yo'q fayl — hammasi `VALIDATION_ERROR`; saqlangan qiymatda `sig=` yo'q; egasi havola oladi,
`viewer_user_id` siz chaqiruv hech narsa bermaydi; haydovchi bronda havola oladi; imzosiz/buzilgan/eskirgan
imzo rad etiladi. Jonli probe: havola `200`, imzosiz o'sha yo'l `403`, begona foydalanuvchi bronni `404`.

**Migratsiya kerak emas** — ustun turi o'zgarmadi; eski qiymatlar `normalize_storage_key` orqali o'qiladi.

## F-08 — `POST /admin/listings/on-behalf` 500 qaytarardi (P1, wave 13)

**Aniqlandi.** Endpoint `listing_dto(session, listing, viewer_user_id=...)` ni chaqirardi, lekin `listing_dto`
bunday parametrni qabul qilmasdi → `TypeError` → 500. Mavjud test servis funksiyasini to'g'ridan-to'g'ri
chaqirgani uchun buni ko'rmagan.

**Tuzatildi.** F-07 doirasida parametr qo'shildi. **Tekshirildi.**
`tests/pg/operations/test_operations_pg.py::test_listing_on_behalf_through_http` — HTTP orqali `201`.

## F-09 — Xizmat flag'i koridor emas, davlat doirasida o'qilardi (P2, wave 13)

**Aniqlandi.** Klient `GET /feature-flags/effective` ni koridorsiz chaqirardi. Q5 bo'yicha xizmat **koridor
bo'yicha** yoqiladi, davlat doirasida esa pilot xizmat o'chiq turadi — natijada ochiq koridor ham «yopiq» deb
ko'rsatilardi.

**Tuzatildi.** Yo'nalish koridori aniqlanishi bilan `effectiveFlags(corridorId)` qayta o'qiladi; o'qib
bo'lmasa hammasi yopiq (Q26). **Tekshirildi.** Probe davlat va koridor doirasini alohida o'qiydi va farqni
ko'rsatadi.

## F-10 — Naqd qayd sahifa yangilangach yo'qolardi (P2, wave 13)

**Aniqlandi.** `POST /bookings/{id}/cash-receipts` javobidan boshqa hech qayerda qayd ko'rinmasdi
(`BookingDTO` da maydon yo'q, `GET` yo'q). Sahifa yangilangach ikkinchi tomon `receipt_id` ni bilmagani uchun
tasdiqlay yoki e'tiroz bildira olmasdi.

**Tuzatildi.** `BookingClientDTO.cash_receipt` — oxirgi qayd. **Tekshirildi.** Probe: qayd → ikkinchi tomon
o'qiydi → tasdiqlaydi; hamyon balansi o'zgarmaydi.

## F-11 — OTP ekranida tugma hech qachon ochilmasdi (**P0**, wave 13)

**Aniqlandi.** `mobile-app` ning OTP ekrani uch xil raqam bilan ishlardi:

| Joy | Qiymat |
|---|---|
| Matn va yorliq | «5 xonali kod», placeholder `12345` |
| Tasdiqlash tugmasi | `disabled={busy || otp.trim().length < 6}` — **6** ta belgi talab qilardi |
| Server (`ELCHI_OTP_LENGTH`) | **5** (`auth_service`: `len(otp) == settings.otp_length`) |

Server 5 xonali kod yuboradi, foydalanuvchi uni kiritadi, tugma esa 6 ta belgi kutgani uchun **hech qachon
ochilmaydi**. Ya'ni v2 klientda OTP orqali kirish umuman ishlamasdi. Kirish nuqtasi bo'lgani uchun P0.

**Tuzatildi.** Raqam bitta manbadan olinadi — `VITE_OTP_LENGTH` (default backend bilan bir xil, 5), v1 web
ilovasidagi naqsh bo'yicha. Yorliq, matn, placeholder, kiritishni kesish (`\D` olib tashlanadi va uzunlikka
qisqartiriladi) va tugma sharti (`otp.length !== OTP_LENGTH`) shundan kelib chiqadi. Mahalliy test kodi
ko'rsatkichi endi faqat dev build'da ko'rinadi va `VITE_DEV_OTP` dan o'qiladi — production UI da bypass kodi
chop etilmaydi.

**Tekshirildi.** `tests/contracts/test_client_otp_length.py` (3 test): klient default'i `settings.otp_length`
ga teng; ekran matnida raqam yozilmagan; tugma sharti `OTP_LENGTH` bilan solishtiriladi va bo'sh
`length < N` taqqoslash qolmagan. Jonli tekshiruv: server `12345` (5 xona) yubordi, `verify-otp` → `200`;
o'sha kodning 4 xonasi bilan → `400 OTP_INVALID`.

> **Kuzatuv (tuzatilmadi):** muzlatilgan `frontend/` da `VITE_OTP_LENGTH` default'i `4`, bu muhitdagi `5` ga
> mos emas. `frontend/` AGENTS §2 bo'yicha tegilmaydi; u deploy paytida `VITE_OTP_LENGTH` o'rnatilishiga
> tayanadi. Agar o'rnatilmasa, u yerdagi OTP maydoni kodni 4 belgiga qirqadi.

## F-12 — Bekat majburiyligi mijozni bloklardi (**P1**, wave 14, Q88)

**Aniqlandi.** Mijoz yo'nalish uchini faqat tasdiqlangan bekatdan tanlay olardi. Katalogda esa **170 tumandan
6 tasida** faol bekat bor (hammasi bitta fixture koridorida), ya'ni 164 tuman tanlab bo'lmasdi va oqim
boshlanmasdan tugardi.

**Tuzatildi (foydalanuvchi qarori Q88, spec §6.1/6.2 dan chekinish).** Uch endi bekat **yoki** xaritadagi
nuqta. Chekinish beshta chegara bilan bog'langan: nuqta tasdiqlangan marshrutga proyeksiya qilinadi
(`ST_LineLocatePoint`), koridor sozlagan radiusdan uzoq bo'lsa rad etiladi, pickup dropoff'dan oldin bo'lishi
shart, sig'im hamon segment bo'yicha taqsimlanadi va nuqtali uch hech qachon `exact` moslik olmaydi.

**Tekshirildi.** `tests/pg/marketplace/test_point_endpoints_pg.py` (11 test) va probe (54 tekshiruv):
bekat ustidagi nuqta → 0 m; ~1 km chetda → 715 m va to'g'ri segment; Nukus → `ROUTE_MISMATCH`; teskari
yo'nalish → `ROUTE_MISMATCH`; bekat va nuqta birga → `VALIDATION_ERROR` (DB'da ham `CHECK`).

## F-13 — Nuqtali e'lon lentada umuman ko'rinmasdi (P1, wave 14)

**Aniqlandi.** Feed moslikni `pickup_stop_id` bo'yicha hisoblaydi; nuqtali e'londa bekat id yo'q, shuning
uchun `stop_segment_match` har doim `None` qaytarardi — haydovchi bunday e'lonni **hech qachon ko'rmasdi**.

**Tuzatildi.** `feed._point_listing_match`: e'lon o'z tumanining tasdiqlangan bekatlari orqali topiladi va
natija `on_route` bilan cheklanadi. **Tekshirildi.** `test_a_marked_place_is_never_called_an_exact_match`.

## F-14 — ETA marshrutning taxminidan hisoblanardi (P2, wave 14)

**Aniqlandi.** Nuqtaning yetib kelish vaqti `route_version_stops.cumulative_duration_s` dan olinardi. Safar
esa o'z jadvaliga ega bo'lishi mumkin (haydovchi sekinroq yoki tezroq rejalashtirgan), va mijoz aynan **o'sha
haydovchini** kutadi.

**Tuzatildi.** ETA safarning o'z `trip_stop_occurrences` vaqtlaridan, segment ichidagi nisbat
(`segment_ratio`) bilan interpolyatsiya qilinadi. **Tekshirildi.** Testda ochildi; 11 test o'tadi.

## F-15 — 0076/0077 izohlari ORM'da yo'q edi (P2, wave 14)

**Aniqlandi.** Migratsiyalar `COMMENT ON COLUMN` qo'yadi, ORM modellarida `comment=` yo'q edi →
`modify_comment` drift (wave 8 dagi `device_tokens.token_cipher` bilan bir xil nuqson turi). To'liq
regressiyada `test_orm_metadata_matches_migrated_schema` va geo drift testi ushladi.

**Tuzatildi.** Beshta ustunga izoh qo'shildi; keyin ikkinchi drift chiqdi — 0076 yaratgan **qisman
indekslar** (`ix_<table>_<end>_district` va `listings` nuqtalaridagi GiST) ORM'da e'lon qilinmagan edi. Ular
ham `__table_args__` ga qo'shildi.

**Diagnostika izohi (keyingi safar uchun muhim).** Bu drift testi **yakka yugurganda yolg'on «o'tdi» beradi**:
u `Base.metadata` ni jonli sxema bilan solishtiradi, lekin `import app.models` v2 modul modellarini
yuklamaydi. Faqat boshqa test ularni import qilgan bo'lsa metadata to'liq bo'ladi. Shuning uchun uni tekshirish
kerak bo'lsa, marketplace/bookings to'plami bilan **birga** yurgizish lozim:
`pytest tests/pg/bookings tests/pg/test_migrations_smoke.py tests/pg/geo/test_geo_schema_drift.py`.

**Tekshirildi.** Ikkala drift testi ham to'liq metadata bilan o'tdi.

## Tekshirilgan, lekin nuqson topilmagan muhim bandlar

Bular alohida qayd etiladi, chunki ular odatda buziladigan joylar:

| Band | Natija |
|---|---|
| Klient yuborgan narxga ishonish | Server jami summani **o'zi** hisoblaydi (`E2E` C2: 2 × 200 000 → 40 000 000 tiyin) |
| O'z taklifini o'zi qabul qilish | `403 NOT_PROPOSAL_RECIPIENT` |
| Eskirgan taklifni qabul qilish | `409 PROPOSAL_CHANGED`, bron yaratilmaydi |
| Balanssiz bron | `409 INSUFFICIENT_COMMISSION_BALANCE`, `bookings` soni o'zgarmaydi |
| Idempotency | Bir xil kalit → **bitta** bron, **bitta** hold; boshqa body → `409 IDEMPOTENCY_KEY_REUSED` |
| Segment sig'imi | 2 o'rinli bron 4 bekatli marshrutda **3 ta** allocation yaratdi |
| Komissiya | `36 000 000 × 1500 bps = 5 400 000`; `available = posted − held` |
| Pending top-up | Balansga qo'shilmaydi (`posted=0`, `pending=10 000 000`) |
| Holatlar ajratilgani | `service_status=confirmed`, `cash_status=unpaid`, `commission_status=held` — uchtasi mustaqil |
| Xizmat flag'i | `passenger_enabled` o'chiq bo'lsa nashr `403 FEATURE_DISABLED`; yoqish `expected_version` bilan optimistik nazorat ostida |
| OTP abuse | Takroriy so'rov `429 OTP_RESEND_TOO_SOON` |
| Logout | Access token darhol `401` (§17.6) |
| Davlat raqami takrorlanishi | DB darajasida rad etiladi |
| Tasdiqlanmagan avtomobil | `409 VEHICLE_NOT_ELIGIBLE` |
| Q40 anonimlik | `ListingOfferDTO` da ism, telefon, davlat raqami yo'q — faqat yorliq, reyting bucket'i va avtomobil klassi |

## Ochiq qolgan, tuzatilmaydigan bandlar (sabab bilan)

| Band | Sabab | Kim / keyingi amal |
|---|---|---|
| AC32, AC27 dala qismi | Haqiqiy Android qurilmasi kerak | Android dasturchisi; emulyator dalil emas |
| AC40 rasmiy restore mashqi | Staging muhiti kerak | A10a; `scripts/restore_drill.sh` tayyor |
| §19.3 yuklama profili | Staging + 100 000 e'lonli fixture | A10a; lokal smoke SLO dalili emas |
| §5.2 taqiqlangan jo'natmalar ro'yxati | Yurist xulosasi | Mexanizm tayyor, matn tasdiqlangan |
| MFA enforcement | Production'da ≥2 `super_admin` | Go-live checklist 10-band |
| Push (FCM) | K3 huquqiy xulosasi + credential | ADR-0022 |
| Q48/Q36/Q28/Q34/Q51/Q73/Q35 | Foydalanuvchi qaroriga ko'ra keyinga qoldirilgan | Holati o'zgartirilmadi |
