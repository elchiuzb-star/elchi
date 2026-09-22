# BASELINE_AUDIT — joriy tizim va 2-bosqich spetsifikatsiyasi

**Muallif:** A0a • **Sana:** 13.09.2026 • **Holat:** wave 0 hisobot, foydalanuvchi tasdig‘ini kutadi
**Asos:** `HEAD` = `4f468c3` (branch `main`). Barcha `fayl:qator` havolalari shu commit bo‘yicha; ishchi daraxtda H0/A0b parallel o‘zgartirayotgan fayllar (`app/main.py`, `app/services/*`, `docker-compose.prod.yml` va boshqalar) qator raqamlari keyin surilishi mumkin.
**Test/build natijalari:** A0b yuritadi → [`BASELINE_TESTS.md`](BASELINE_TESTS.md). Bu hujjat faqat kod o‘qish va quyidagi buyruqlar natijasiga tayanadi:

- `py -m pytest --collect-only -q` (HEAD holatida, A0b/H0 o‘zgarishlaridan oldin): 23 modul, 321 test yig‘ildi, collection xatosiz. Testlar **ishga tushirilmadi** — natija A0b hujjatida.
- `py -m alembic heads` → `20260803_0029 (head)`; `py -m alembic branches` → branchpoint `20260618_0014` (`20260620_0015`, `ac62a9c9e9e2`) va `20260620_0015` (`20260622_0016`, `20260622_0020`).
- Lokal Python 3.14.3; Docker image `python:3.12-slim` (`Dockerfile:1`). 3.12 runtime lokal yo‘q — farq xavf sifatida qayd etildi.

Belgilar: **[KOD]** — kodda tekshirildi; **[TAXMIN]** — kod asosida xulosa, runtime’da tekshirilmagan; **[H0]** — H0 hozir tuzatmoqda.

---

## 1. Spetsifikatsiya §2 jadvali bo‘yicha tekshiruv

| §2 dagi da’vo | Kod haqiqati | Dalil |
|---|---|---|
| FastAPI, SQLAlchemy, Alembic, PostgreSQL | To‘g‘ri. PostGIS yo‘q | `requirements.txt:1-11`; `docker-compose.prod.yml:12` |
| `orders` mijozga tegishli pochta buyurtmasi | To‘g‘ri; `listings/trips/bookings` yo‘q | `app/models/order.py:11-57` |
| `bids` faqat haydovchidan | To‘g‘ri; bitta driver — bitta bid, narx 3 marta tahrir | `app/models/bid.py:13-23`; `app/services/driver_order_service.py:475-527` |
| Shahar/tuman aynan tengligi | To‘g‘ri | `app/services/matching_service.py` (route equality), `app/services/driver_order_service.py:232-247` |
| Matching `is_available=true` | To‘g‘ri | `app/services/matching_service.py:22` |
| Komissiya 15% | To‘g‘ri, `system_settings` orqali o‘zgaradi; real undirish yo‘q | `app/services/system_settings_service.py:10-11,46-68` |
| Xarita bor, GPS tracking yo‘q | To‘g‘ri; tracking kodi yo‘q | `grep -i "redis\|websocket\|outbox\|fcm\|postgis" app requirements.txt` → faqat `app/contracts/` (wave 0) |
| Xabarnoma faqat `in_app` | To‘g‘ri | `app/services/notification_service.py:14` |
| Bitta `users.role` | To‘g‘ri | `app/models/user.py:23` |
| Bitta buyurtmaga bitta baho | To‘g‘ri | `app/models/rating.py:15` (`order_id unique`) |
| Nizo buyurtma statusini almashtiradi | To‘g‘ri va qaytaradi | `app/services/dispute_service.py:208-217,354-359` |
| Admin istalgan statusga o‘tkazadi | To‘g‘ri; **operator ham** | `app/services/admin_order_service.py:19-20,250-283`; `app/api/v1/admin_orders.py:23,40` |
| Geo tekshiruv 75 km | To‘g‘ri | `app/services/geo_service.py:15,93` |
| Moliyaviy ko‘rsatkichlar frontendda | To‘g‘ri, uchala klientda | `mobile-app/src/api/admin-overview.api.ts:56`, `frontend/src/api/admin-overview.api.ts:56`, `android-app/src/api/admin-overview.api.ts:56` |

---

## 2. Majburiy topilmalar (joriy holat)

### 2.1 Statuslar oddiy string, DB CHECK yo‘q [KOD]
`orders.status` (`order.py:44`), `bids.status` (`bid.py:22`), `disputes.status` (`dispute.py:18`), `driver_documents.status` (`driver_document.py:21`), `driver_profiles.verification_status` (`driver_profile.py:24`), `order_offers.status` (`order_offer.py:19`), `users.status/role` (`user.py:23-24`) — `String(32)`. Modellar va migratsiyalardagi barcha CHECK’lar ro‘yxati: narx musbatligi, shaharlar farqi, rating 1..5, tarif chegaralari (`bid.py:14`, `order.py:15`, `rating.py:11`, `route_tariff.py:13-21`, `20260613_0003_cities_route_tariffs.py:36-51`). Status qiymati faqat Python to‘plamlarida (`admin_order_service.py:19`, `dispute_service.py:27-33`, `order_service.py:23-25`). Spec §13: “Faqat Python’da tekshiruv bilan cheklanilmaydi”.

### 2.2 Admin/operator ixtiyoriy status override [KOD]
`MANUAL_TARGET_STATUSES = ORDER_STATUSES - {"draft"}` (`admin_order_service.py:20`). `validate_manual_status_transition` faqat `cancelled`dan chiqish va `confirmed`dan chiqishni cheklaydi (`:250-263`) — masalan `published → delivered` yoki `bidding → confirmed` ruxsat. Oqibatlar:
- `confirmed`ga o‘tkazish `payment_status="paid_manual"` yozadi (`:279-280`) — naqd pul dalilisiz.
- `disputed`ga o‘tkazish `disputes` yozuvisiz status beradi (`:277`).
- Haydovchi tayinlanmagan buyurtma `picked_up`ga o‘tishi mumkin (tekshiruv yo‘q).
- Ruxsat `operator, admin, super_admin` (`app/api/v1/admin_orders.py:23,40`).
Spec §2, §21 A9 chegarasi: “istalgan status”ni to‘g‘ridan-to‘g‘ri yozadigan admin tugmasi yo‘q.

### 2.3 Nizo `previous_order_status`ni tiklaydi [KOD]
Ochilganda `previous_order_status=order.status`, `order.status="disputed"` (`dispute_service.py:208-217`); `resolved/rejected`da `order.status = previous_order_status` (`:354-359`, `RESTORABLE_STATUSES` `:33`). Nizo davomida xizmat oqimi to‘xtaydi; hal bo‘lganda ko‘r-ko‘rona tiklanadi. Spec §11: “ko‘r-ko‘rona `previous_status`ga tiklanmaydi”.

### 2.4 Lock’siz v1 amallar va bekor qilishda bid’lar yopilmaydi [KOD]
| Amal | Lock | Dalil |
|---|---|---|
| Mijoz `cancel_order` | Yo‘q (`db.get`) | `order_service.py:568-603`, `get_owned_order` `:433-446` |
| Mijoz `publish_order` | Yo‘q | `order_service.py:499-528` |
| Mijoz `update_order` | Yo‘q | `order_service.py:318` |
| Driver `create_bid` | Yo‘q (order ham, bid ham) | `driver_order_service.py:396-473` |
| Driver `update_bid` | Yo‘q; `bid.status="active"` qayta yoziladi | `driver_order_service.py:475-527`, `:499` |
| `select_driver_for_order` | Bor: order, bid, boshqa bid’lar `FOR UPDATE` | `order_service.py:610,626,659` |
| Admin `cancel_order_manually` | Bor + `close_active_bids` | `admin_order_service.py:406-425` |

Mijoz bekor qilganda `bids` yopilmaydi (`order_service.py:581-599` da `Bid` o‘zgarmaydi), admin bekor qilishda yopiladi (`admin_order_service.py:406-410`). Race stsenariylari [TAXMIN, PG testida isbotlanishi kerak]:
1. `cancel_order` statusni o‘qiydi (`bidding`) → parallel `select_driver` commit (`accepted`, komissiya, driver xabari) → `cancel_order` `cancelled` yozadi: bekor buyurtmada qabul qilingan bid.
2. `update_bid` bid’ni `active` deb o‘qiydi → `select_driver` boshqa bid’ni tanlab uni `closed` qiladi → `update_bid` `status="active"` va yangi narx yozadi: yopilgan bid qayta tiriladi; tanlangan bid bo‘lsa `final_price` va `bid.price` ajraladi.
3. `create_bid` `select_driver` snapshot’idan keyin kiritiladi → `accepted` buyurtmada `active` bid qoladi.

### 2.5 Idempotency, Redis, worker, WebSocket, push, outbox, tracking yo‘q [KOD]
`app/` va `requirements.txt` bo‘yicha grep natijasi bo‘sh (faqat wave 0 `app/contracts/`). Compose’da faqat `db`, `api`, `caddy` (`docker-compose.prod.yml:11,29,42`). Uvicorn `--workers 2` (`Dockerfile:39`) — kelajak WebSocket fan-out’i jarayonlararo kanal (Redis) talab qiladi.

### 2.6 Buyurtmada vazn/o‘lcham/vaqt oynasi yo‘q [KOD]
`orders`da faqat `cargo_type` (`order.py:34`) va `comment`; og‘irlik, o‘lcham, pickup/dropoff oynasi yo‘q. `20260626_0023_add_order_pickup_available_at.py` — bo‘sh (“retired”) migratsiya: ustun qo‘shilmagan.

### 2.7 Naive timestamp ustunlari [KOD]
`orders.published_at…cancelled_at` (`order.py:51-57`; migratsiya `20260613_0002_database_models.py:148-149`, `20260613_0005_client_order_lifecycle_fields.py:22-26`), `disputes.resolved_at` (`dispute.py:22`; `20260615_0008_dispute_fields.py:22`), `driver_documents.reviewed_at` (`driver_document.py:24`; `20260615_0009...:22`), `order_offers.shown_at/responded_at` (`order_offer.py:21-22`; `20260613_0006...:21`) — `timestamp without time zone`. Servislar esa aware UTC yozadi (masalan `order_service.py:511`). [TAXMIN] PostgreSQL aware qiymatni sessiya `TimeZone` bo‘yicha naive’ga aylantiradi; prod sessiyasi UTC ekanini A10a tekshirishi shart. [TAXMIN] v1 JSON’da bu maydonlar offset’siz chiqadi; JS `new Date("…T…")` offset’siz qiymatni lokal vaqt deb o‘qiydi.

### 2.8 Pul `Numeric(12,2)`/`Decimal`, JSON’da float [KOD]
`order.py:36-41`, `bid.py:20`, `route_tariff.py:38-40`; stavka `Numeric(5,4)` (`order.py:39`); yaxlitlash `system_settings_service.py:12-25,46-55`. Routerlar `dict` qaytaradi (`response_model=None`, masalan `app/api/v1/admin_settings.py:13,21`) — FastAPI `jsonable_encoder` `Decimal("60000.00")` ni `60000.0` float qiladi (lokal tekshirildi). Spec §9.4: BIGINT minor, float yo‘q.

### 2.9 Komissiya: backend 15%, klientlarda qattiq 10%/15% [KOD]
- Backend default `Decimal("0.15")` (`system_settings_service.py:11`).
- `mobile-app`: “15% ulush” yorliqlari `src/app/ConnectedApp.tsx:2257,2336,2387`; `src/api/admin-overview.api.ts:56` `DEFAULT_SYSTEM_FEE_RATE = 0.15`; admin input default `"15"` `src/app/AdminProfilePanel.tsx:18`.
- `frontend` (muzlatilgan): “Komissiya (10%)” `src/app/App.tsx:192,196,433,437,674,678`.
- `android-app` (muzlatilgan): `src/screens/driver/BidSheet.tsx:35` `num * 0.85 // 15%`.
- v1 PATCH `/admin/settings/driver-commission` ruxsati `admin, super_admin` (`app/api/v1/admin_settings.py:24`).
K5: policy admin paneldan versiyalanadi; stage-2 klient (`mobile-app`) qattiq stavkadan tozalanadi (A8/A9).

### 2.10 Bitta `users.role`, unique phone, rolga bog‘langan OTP [KOD]
`users.phone` unique (`user.py:13`), `users.role` (`user.py:23`); OTP yozuvida `role` (`otp_code.py:15`); boshqa rol bilan so‘rov `ROLE_MISMATCH` (`auth_service.py:219-235,393-398`); JWT `role` claim (`auth_service.py:503`); v1 ruxsat DB’dagi `users.role` bo‘yicha (`app/api/deps.py:46-55`). Bir telefon bilan mijoz va haydovchi bo‘lish imkoni yo‘q.

### 2.11 Alembic: bitta head, tarixiy branch’lar [KOD]
Head `20260803_0029`. Tarix: `ac62a9c9e9e2` (avtogeneratsiya, `20260618_0014`dan) indekslarni o‘chiradi (`ac62a9c9e9e2_first_migration.py:23-33`); `0016` merge (`20260622_0016...:12`); `0020` `0015`dan alohida branch; `0022` merge (`20260625_0022...:15`). Fayllar 27 ta (0017–0019 yo‘q). Prod indekslari migratsiya tarixiga mosligini A10a schema-diff bilan tekshiradi.

### 2.12 Testlar faqat SQLite [KOD]
HEAD’dagi 23 modulning 20 tasi `sqlite+pysqlite:///:memory:` + `StaticPool` ishlatadi (masalan `tests/test_select_driver_transaction.py:19-23`); qolgan 3 tasi DB’siz (`test_api_docs_collection.py`, `test_health.py`, `test_models.py`). SQLite `FOR UPDATE`ni e’tiborsiz qoldiradi — `select_driver_for_order` lock testi race’ni isbotlamaydi. Spec §21.2: idempotency/seat/wallet testlari PostgreSQL’da. PG infra — A0b.

### 2.13 Ommaviy upload’lar [KOD][H0]
`app.mount("/uploads", StaticFiles(...))` (`app/main.py:59-63`, `config.py:58,61`), volume `docker-compose.prod.yml:38`. Pasport/selfie/hujjat URL’i autentifikatsiyasiz. H0 tuzatmoqda — ADR-0015.

### 2.14 Prod compose: `postgres:16-alpine`, Redis/worker yo‘q [KOD]
`docker-compose.prod.yml:12`. PostGIS alpine image’da yo‘q; PostGIS image’lari Debian (glibc). Alpine (musl) → glibc o‘tishida matn collation farqi indekslarni buzishi mumkin — ADR-0013. Migratsiya deploy’da bir martalik job (`scripts/deploy.sh:27`) — spec §19.1 ga mos.

### 2.15 Hetzner (Germaniya) va O‘zbekiston qonuni [KOD][K3]
`docs/SERVER_MIGRATION.md:7-10` o‘zi ogohlantiradi: yangi host Hetzner Germaniya, shaxsiy ma’lumot mamlakatdan chiqadi. K3: stage-2 production launch gate — O‘zbekistondagi hosting (ADR-0011). Backup ham shu serverda: `scripts/backup.sh:1-4,20-21,33-34` (kundalik `pg_dump`, 14 kun, off-box nusxa yo‘q) → amalda RPO ≈ 24 soat, server yo‘qolsa backup ham yo‘qoladi.

### 2.16 `mobile-app` eskirgan, tiplar qo‘lda ko‘paytirilgan [KOD]
- `mobile-app/src/types/*.ts` 13 faylning 11 tasi `frontend/src/types`dagi bilan bayt-bayt bir xil; `driver.ts`, `order.ts` farq qiladi.
- Backend `cargo_type`, `client_price`ni qabul qiladi (`app/schemas/order.py:44-46`), `mobile-app/src` da bu maydonlar umuman yo‘q (grep bo‘sh).
- Klient logikasi bitta 2 668 qatorli `src/app/ConnectedApp.tsx`da.
- HEAD’da ikki lockfile bor edi (`package-lock.json`, `pnpm-lock.yaml`). **Hal qilindi (Q11):** A0b `pnpm-lock.yaml` va `pnpm-workspace.yaml`ni olib tashladi; ishchi daraxtda faqat `package-lock.json` qoldi (tekshirildi). `npm audit`, build va lint natijalari — A0b hisobotida.
- v1 routerlarning ko‘pi `response_model=None` → OpenAPI javob sxemasiz; v1 dan TS generatsiya qilib bo‘lmaydi (ADR-0010).

### 2.17 1-bosqich hujjatlari 2-bosqichga zid [KOD]
`MASTER_PROMPT.md` va `codex_backend_development_plan_v10.md` “time matching/capacity/weight/OTP proof/GPS/chat yo‘q” va “operator barcha statuslarga aralasha oladi” deydi. K1 bo‘yicha `docs/archive/stage1/`ga ko‘chirildi; taqqoslash: [`STAGE1_ARCHIVE_COMPARISON.md`](STAGE1_ARCHIVE_COMPARISON.md). Kod allaqachon ularni buzgan (`cargo_type` — `20260630_0025`).

---

## 3. `PROJECT_OVERVIEW.md` bilan tafovutlar

| # | Overview | Kod | Dalil |
|---|---|---|---|
| D1 | “Barcha modellar … timezone-aware” (§3) | 10 ta naive ustun | §2.7 |
| D2 | Komissiyani faqat `super_admin` o‘zgartiradi (§2, §5.8, §6) | `admin` ham | `app/api/v1/admin_settings.py:24` |
| D3 | Operator buyurtmani faqat ko‘radi; `PATCH status`, assign, cancel — admin+ (§2, §6) | Operator ham bajaradi | `app/api/v1/admin_orders.py:23,40,96-137` |
| D4 | “Rol tekshiruvi har endpointda `require_roles(...)`” (§8) | `admin_orders` alohida dependency | `app/api/v1/admin_orders.py:26-42` |
| D5 | `payment_status` = `unpaid`/`paid` (§3.9) | `paid_manual` | `order_service.py:737`, `admin_order_service.py:280` |
| D6 | “Faol buyurtma bo‘lsa akkaunt o‘chmaydi” (§5.13) | `disputed` ro‘yxatda yo‘q | `account_deletion_service.py:43-50,75` (H0 hozir shu faylni o‘zgartirmoqda) |
| D7 | “24 ta test moduli” (§1, §10) | 23 | `git ls-tree HEAD tests/` |
| D8 | “Migratsiyalar 29 ta” (§9) | 27 fayl; 0017–0019 yo‘q; 0023 bo‘sh | `alembic/versions/` |
| D9 | “21 ta router fayli” (§1) | 20 router + `__init__.py` | `app/api/v1/` |
| D10 | “Uchala klient bir xil API qatlami va tiplarga ega” (§7) | `mobile-app` tiplari farqli va eskirgan | §2.16 |
| D11 | `Referrer-Policy` xavfsizlik header’i (§8) | API `no-referrer` (`app/main.py:70`), Caddy `strict-origin-when-cross-origin` (`Caddyfile:14`); qaysi biri yakuniy ekani tekshirilmagan [TAXMIN] | |
| D12 | JSON pul maydonlari haqida yozilmagan | float bo‘lib chiqadi | §2.8 |
| D13 | Admin `PATCH status` “sabab majburiy” | To‘g‘ri, lekin invariant yo‘q (`disputed` yozuvsiz, `paid_manual`) | §2.2 |

---

## 4. Ro‘yxatda bo‘lmagan qo‘shimcha topilmalar

| # | Topilma | Dalil | Taklif |
|---|---|---|---|
| X1 | `update_bid` yopilgan/qabul qilingan bid’ni `active`ga qaytarishi mumkin | `driver_order_service.py:479-499` | v1 hardening (§6) |
| X2 | `disputed` buyurtmali foydalanuvchi akkauntini o‘chira oladi | `account_deletion_service.py:43-50` | v1 hardening; A12 v2 qoidasi |
| X3 | OTP 4 xonali; spec §17.5 6 xonaga bosqichli o‘tish | `config.py:22`; Eskiz shabloni `config.py:54-56` | Qaror Q8: hozircha 4 xona; 6 xona Android v2 klienti bilan |
| X4 | Admin status override `disputed`ni nizo yozuvisiz, `confirmed`ni naqd dalilisiz qo‘yadi | `admin_order_service.py:277-280` | v1 hardening |
| X5 | Health faqat `/api/v1/health`, readiness DB’ni tekshirmaydi | `app/api/v1/health.py:8-10` | A10a: `/health/live`, `/health/ready` |
| X6 | Backup bir serverda, kundalik | `scripts/backup.sh` | A10a runbook (RPO/RTO) |
| X7 | `pytest` runtime `requirements.txt`da | `requirements.txt:9` | A0b (`requirements-dev.txt`) |
| X8 | Lokal Python 3.14, image 3.12 | `Dockerfile:1`; `app/__pycache__/*.cpython-314.pyc` | A0b: 3.12’da test |
| X9 | `audit_logs.entity_id` `Integer` (int4) | `app/models/audit_log.py:15` | v2 BIGINT id’lar uchun kuzatiladi (DATA_MODEL) |
| X10 | `ac62a9c9e9e2` avtogeneratsiya indekslarni o‘chiradi; qaysi indekslar prod’da borligi noma’lum | `ac62a9c9e9e2_first_migration.py:23-33` | A10a schema-diff |

---

## 5. Mavjud production uchun xavflar

| # | Xavf | Ta’sir | Kim/qachon |
|---|---|---|---|
| R1 | Pasport/selfie public URL | Shaxsiy hujjat sizishi | H0, hozir |
| R2 | Shaxsiy ma’lumot Germaniyada (K3) | Huquqiy | Foydalanuvchi + A10a runbook; stage-2 launch gate |
| R3 | v1 race’lar (§2.4, X1) | Bekor buyurtmada qabul qilingan bid; noto‘g‘ri `final_price` | v1 hardening kartasi (WAVE1_CARDS) |
| R4 | PostGIS migratsiyasi image almashmasdan deploy qilinsa `alembic upgrade head` yiqiladi (`scripts/deploy.sh:27`) | Deploy to‘xtaydi | A10a: image avval, migratsiya 0030 keyin (ADR-0013, ADR-0016) |
| R5 | Postgres volume’ini alpine→Debian image’ga to‘g‘ridan-to‘g‘ri ulash | Unique indekslar (phone, username) buzilishi, dublikat | A10a: dump/restore (ADR-0013) |
| R6 | Naive timestamp konvertatsiyasi | Vaqt siljishi; v1 JSON formati o‘zgaradi | A10b, prod `TimeZone` tekshiruvidan keyin (ADR-0004) |
| R7 | Backup off-box emas | Server yo‘qolsa hammasi yo‘qoladi | A10a |
| R8 | v1 kontraktini buzish (`{success,data,message}`, JWT `role`, OTP `role`) | Muzlatilgan `android-app`/`frontend` ishlamay qoladi | Barcha agentlar; ADR-0006/0007 |
| R9 | Komissiya manbasini policy jadvaliga ko‘chirish v1 yangi buyurtmalar fee’sini o‘zgartirishi | Moliyaviy snapshot farqi | A3 (ADR-0009): seed = joriy qiymat |
| R10 | Parallel agentlar bir faylni o‘zgartirishi | Yo‘qolgan o‘zgarish | Fayl egaligi (AGENTS.md) |

---

## 6. v1’da tuzatiladigan bug nomzodlari (xulqni muzlatib, lock qo‘shish)

Maqsad: v1 javob shakli va holat oqimini **o‘zgartirmasdan** race va invariant buzilishini yopish. Har biri avval PostgreSQL’da qizil (failing) concurrency testi bilan isbotlanadi.

| # | Nomzod | Tuzatish yo‘nalishi | Dalil |
|---|---|---|---|
| V1 | Mijoz `cancel_order` lock’siz | `SELECT … FOR UPDATE` bilan order; status qayta tekshiriladi | `order_service.py:568-603` |
| V2 | Mijoz bekor qilganda active bid’lar ochiq qoladi | Shu tranzaksiyada bid’larni `closed` (admin xulqi bilan bir xil) | `order_service.py:581-599` vs `admin_order_service.py:406-410` |
| V3 | `publish_order` lock’siz | Order lock; ikkinchi publish `ORDER_INVALID_STATUS` | `order_service.py:499-528` |
| V4 | `update_order` lock’siz | Order lock | `order_service.py:318` |
| V5 | `create_bid` order’ni lock qilmaydi | Order `FOR UPDATE`, status qayta tekshiruv | `driver_order_service.py:396-473` |
| V6 | `update_bid` bid/order lock’siz, `status="active"` qayta yozadi | Bid va order lock; `active` bo‘lmasa rad; statusni qayta yozmaslik | `driver_order_service.py:475-527` |
| V7 | Lock tartibi | Hamma v1 yo‘llarda: order → bids (id bo‘yicha) | spec §15 |
| V8 | Akkaunt o‘chirish `disputed`ni o‘tkazib yuboradi | `disputed`ni in-flight to‘plamiga qo‘shish (H0 ishidan keyin) | `account_deletion_service.py:43-50` |
| V9 | Admin override `disputed`ni nizosiz qo‘yadi | `disputed`ni `MANUAL_TARGET_STATUSES`dan chiqarish (faqat dispute endpoint) — **xulq o‘zgarishi**, BR va foydalanuvchi tasdig‘i kerak | `admin_order_service.py:19-20` |

V1–V8 javob shaklini o‘zgartirmaydi. **V9 tasdiqlandi (Q10, 13.09.2026)** — muzlatilgan `frontend` admin panelida `disputed`ni qo‘lda tanlash endi rad javobini oladi. Egasi: H1 (`WAVE1_CARDS.md`).

---

## 7. Wave 0.5 qarorlari (13.09.2026) va ushbu audit bandlariga ta’siri

| Qaror | Audit bandi | Natija |
|---|---|---|
| Q1 0% faqat muddatli kampaniya; `wallet_required` production’da `true` | §2.9 | ADR-0009, `app/contracts/money.py` |
| Q2 Commission policy — faqat super_admin; v1 PATCH ham | §2.9, D2 | A3 v1 adapteri; `admin_settings.py:24` xulqi o‘zgaradi |
| Q3 Staff va marketplace akkauntlari alohida | §2.10 | ADR-0007 |
| Q4 Legacy faqat read-only view; v1/v2 bozorlari parallel; cutover yo‘q | R8 | ADR-0006, DATA_MODEL §1.12 |
| Q5 Yangi xizmatlar production’da o‘chiq; passenger super_admin + approval | R2 | ADR-0008, ADR-0014 |
| Q6 Cargo rasmi faqat egasi va tayinlangan haydovchiga | §2.13 | H0; ADR-0015 |
| Q7 No-show faqat operator tasdig‘i bilan | — | STATE_MACHINES §4 |
| Q8 OTP 4 xona; review akkauntlari izolyatsiyasi H1; staff MFA A12 | X3 | WAVE1_CARDS H1, COVERAGE_MATRIX |
| Q9 Naive timestamp konvertatsiyasi wave 5 | §2.7, R6 | ADR-0004 |
| Q10 v1 operator override/assign/cancel yo‘q; nizosiz `disputed` yo‘q | §2.2, D3, V9, X4 | H1 |
| Q11 mobile-app npm | §2.16 | Bajarildi (A0b) |
| Q12 Ochiq nizoda v1 qo‘lda status o‘zgartirish 409 | §2.2, §2.3 | H1 |
| Q13 Status o‘zgartiradigan nizo qarori admin+; operator faqat ko‘rib chiqadi | §2.3 | H1 |
| Q14 Majburiy `confirmed` → `paid_manual` o‘zgarmaydi; hisobotda “tasdiqlanmagan” | §2.2, D5 | A9/A13 |
| Q15 v1 `block_driver` faol v2 trip’ni to‘xtatmaydi; to‘liq blok super_admin | §2.10 | A4/A12 |
| Q16 Komissiya holati mijozdan yashirin (event’larda ham) | §2.9 | Kontrakt (`events.py`), A7 |
| Q17 `finance` staff roli | §2.9, D2 | Kontrakt (`enums.py`), A1, A3 |
| Q18 v1 `BID_NOT_ACTIVE` 409 saqlanadi | `order_service.py` (HEAD, select_driver) | O‘zgarishsiz |
| Q19 Barcha ADR’lar qabul qilindi | — | `docs/architecture/adr/` |
| Q37 Faol nizoda v1 admin cancel bloklangan (resolve-then-cancel) | §2.2, §2.3 | H1 |
| Q38 v1 operator nizoda faqat izohli `under_review` | §2.3 | H1 |
| Q39 Review allowlist’dan olib tashlash tartibi | X3, Q8 | H1 (procedure doc) |
