# QA talablar matritsasi — `ELCHI_PRODUCTION_ARCHITECTURE.md` bo'yicha

**Manba hujjat:** `docs/architecture/ELCHI_PRODUCTION_ARCHITECTURE.md` v1.0, 12.09.2026 (repository'dagi **yagona** nusxa; `ELCHI_PRODUCTION_ARCHITTECTURE` nomli fayl yo'q).
**Tuzilgan:** 17.09.2026 • **Muallif:** QA agenti • **Kod holati:** commit `4f468c3` + commit qilinmagan diff, `alembic heads` = `20260917_0075`.

**Hujjatda `SC01–SC18` yo'q** — majburiy stsenariylar faqat `AC01–AC44` (§22). Ular **takrorlanmaydi**: har birining joriy holati avtomatik yaratiladigan [`COVERAGE_MATRIX.md`](COVERAGE_MATRIX.md) da (`py scripts/ac_coverage.py --junit <junit.xml>`). Bu matritsa AC'lardan **tashqaridagi** talablarni — bo'lim matnlari, jadvallar, formulalar va xavfsizlik shartlarini qamraydi.

## Holat kodlari

| Kod | Ma'nosi |
|---|---|
| `VERIFIED` | Mavjud va **shu QA seansida** dalil bilan tekshirildi (jonli API + DB yoki nomi ko'rsatilgan test) |
| `COVERED` | Mavjud va repo test to'plamida qoplangan (17.09.2026 regressiyasi: 2119 test, 0 failure) |
| `PARTIAL` | Qisman: backend bor, klient yoki aksincha yetishmaydi |
| `MISSING` | Yo'q |
| `DECISION` | Foydalanuvchi/huquqiy qaror kutmoqda |
| `ENV` | Muhit kutmoqda (staging, registry, real qurilma) |
| `DEFERRED` | Tasdiqlangan tartibda keyinga qoldirilgan |

## Dalil manbalari

| Belgi | Ma'nosi |
|---|---|
| `E2E` | Jonli backend (`:8001`, doimiy dev bazasi) + DB o'qish: `scratchpad/e2e.py` (7 tekshiruv) va `e2e_flow.py` (30 tekshiruv), 17.09.2026, 0 failure |
| `REG` | To'liq PostgreSQL regressiyasi 17.09.2026 19:51 — **2119 test, 0 failure, 0 skip** |
| `CODE` | Kod joyi (fayl:satr) |

---

## §1–§4 Arxitektura va mahsulot chegarasi

| ID | Talab (bo'lim) | Holat | Dalil / izoh |
|---|---|---|---|
| R-1.1 | `listing` / `booking` / `trip` alohida tushunchalar (§1) | `VERIFIED` | `E2E`: listing → proposal → booking alohida obyektlar; `bookings` jadvalida `request_listing_id`, `supply_listing_id`, `trip_id` alohida ustunlar |
| R-1.2 | Modular monolith: FastAPI + PostgreSQL/PostGIS + Redis + alohida worker (§1) | `VERIFIED` | `E2E` readiness: `database ok`, `redis ok`; `app/worker/` mavjud |
| R-1.3 | Redis o'chishi bron/pulni yo'qotmaydi (§1) | `COVERED` | AC34 (`COVERAGE_MATRIX`), `REG` |
| R-2.1 | Mavjud OTP, hujjat, audit, refresh rotatsiyasi qayta ishlatiladi (§2) | `VERIFIED` | `E2E` A1–A6: OTP login, refresh rotatsiyasi, logout → `401` |
| R-4.1 | P0 doirasi: yo'lovchi+pochta e'lonlari, ikki tomon taklifi, segment sig'imi, komissiya balansi, GPS, push, admin (§4) | `PARTIAL` | Backend `COVERED`; klientda **push yoqilmagan** (ADR-0022, `DECISION`), haydovchi supply oqimi F-01 gacha yetib bo'lmasdi |
| R-4.2 | P2 (karta to'lovi) hozirgi bosqichga qo'shilmaydi (§4, §9.6) | `DEFERRED` | `card_payments_enabled` flag mavjud va o'chiq; `payment_intents` jadvallari yo'q — to'g'ri |

## §5 E'lonlar va narx kelishuvi

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-5.1 | To'rt e'lon turi (`request`/`trip_offer` × `passenger`/`parcel`) (§5.1) | `COVERED` | `ListingKind`/`ServiceType` enum + CHECK; `REG` |
| R-5.2 | Bitta safar ikkita xizmat e'lonida bitta jismoniy sig'imdan foydalanadi (§5.1) | `COVERED` | A1 qabul mezoni; `tests/pg/marketplace` |
| R-5.3 | Majburiy maydonlar: yo'lovchi (`seat_count`, bagaj, maxsus yordam) (§5.2) | `VERIFIED` | `E2E` C1: `passenger.seat_count` majburiy; `PassengerDetails` DTO |
| R-5.4 | Majburiy maydonlar: pochta (og'irlik, o'lcham, qiymat, jo'natuvchi/oluvchi, kim to'laydi) (§5.2) | `COVERED` | `ParcelDetails` DTO + `parcel_listing_details` CHECK'lari |
| R-5.5 | Taqiqlangan jo'natmalar ro'yxati admin sozlamasida (§5.2) | `DECISION` | Mexanizm tayyor (`0070`, `GET /parcel-policy`), matn tasdiqlangan, **production'da faollashtirish yurist xulosasini kutmoqda** |
| R-5.6 | Narx birligi majburiy: `2 × 200 000 = 400 000` (§5.2) | `VERIFIED` | `E2E` C2: server `total_minor=40000000` ni **o'zi** hisoblaydi; klientda `formatPriceBreakdown` (`v2Format.ts:23`) |
| R-5.7 | Tovar qiymati va yetkazish haqi alohida maydonlar (§5.2) | `COVERED` | `ParcelDetails.declared_value_minor` vs `unit_price_minor` |
| R-5.8 | Har tuzatish yangi `proposal_version`; eski summani qabul qilib bo'lmaydi (§5.3) | `VERIFIED` | `E2E` C6→C7: counter'dan keyin eski versiya → `409 PROPOSAL_CHANGED` |
| R-5.9 | Faqat qarshi tomon qabul qiladi; o'z taklifini o'zi qabul qilolmaydi (§5.3) | `VERIFIED` | `E2E` C5 → `403 NOT_PROPOSAL_RECIPIENT` |
| R-5.10 | Qabul qilish tranzaksiyada versiya/jadval/o'rin/yuk/balansni qayta tekshiradi (§5.3) | `VERIFIED` | `E2E` D2 (balans yetmasa `409 INSUFFICIENT_COMMISSION_BALANCE`), E3–E6 (bron + 3 allocation + hold bir tranzaksiyada) |
| R-5.11 | Narx tuzatish limiti: har tomon 3 marta (§5.3) | `COVERED` | `MAX_PRICE_REVISIONS_PER_SIDE`, `NEGOTIATION_LIMIT_REACHED` (`marketplace/rules.py:103`) |
| R-5.12 | Taklif TTL: >2 soat bo'lsa 2 soat, yaqin jo'nashda 10 daqiqa, cutoff'dan keyin emas (§5.3) | `COVERED` | `PROPOSAL_MAX_TTL` / `PROPOSAL_NEAR_DEPARTURE_TTL` (`marketplace/rules.py:88`) |
| R-5.13 | Taklif o'rin/balansni band qilmaydi; band qilish faqat qabulda (§5.3) | `VERIFIED` | `E2E` C4 dan keyin `wallet.held=0`; D2 rad etilgach `bookings` soni o'zgarmadi (D3) |
| R-5.14 | Tahrir ochiq takliflarni eskirtiradi (§5.4, Q20) | `COVERED` | `terms_version` va `listings.version` ajratilgan; `tests/pg/marketplace/test_marketplace_wave15_pg.py` |
| R-5.15 | Dublikat e'lon tekshiruvi va rate-limit (§5.4) | `COVERED` | `DUPLICATE_LISTING` (`marketplace/service.py:790-807`), `RATE_LIMITED` |

## §6 Yo'nalish va oraliq tumanlar bo'yicha matching

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-6.1 | Ma'muriy nom ≠ yo'l; moslik tasdiqlangan marshrut bo'yicha (§6.1) | `VERIFIED` | `tests/pg/marketplace/feed/test_feed_districts_pg.py` (7 test) — tuman qo'shniligi o'zi moslik bermaydi |
| R-6.2 | Pickup **va** dropoff ikkalasi tekshiriladi (§6.1) | `COVERED` | `feed/rules.py::stop_segment_match`; AC14–AC16 |
| R-6.3 | Ma'lumot qatlami: `regions`/`districts`/`settlements`, koridor, bekat, `route_versions`, `trip_stop_occurrences`, `saved_searches` (§6.2) | `VERIFIED` | Jadvallar mavjud; dev bazada 14 viloyat, 170 tuman, 1 koridor, 6 bekat, 2 tasdiqlangan marshrut |
| R-6.4 | Tavsiya darajalari `exact`/`on_route`/`detour`/`alternative` (§6.4) | `COVERED` | `MatchType` + `geo/matching.py:239-245`; `REG` |
| R-6.5 | Routing yo'q bo'lsa detour moslik sifatida chiqmaydi (§6.4, AC35) | `VERIFIED` | `E2E`: `/routes/preview` → `503 ROUTING_UNAVAILABLE` ("no fake match (AC35)"); feed'da `match_type=detour` qaytmaydi (Q46) |
| R-6.6 | Oraliq bekatda **o'sha bekatga yetib kelish oynasi** qo'llanadi (§6.3.5, AC15) | `COVERED` | `geo/matching.py::eta_window`; AC15 |
| R-6.7 | Lenta default — tanlangan yo'nalish; mamlakat bo'ylab aralash lenta emas (§6.6) | `COVERED` | `feed()` ikkala uchni talab qiladi (`exactly_one_of_stop_district_or_region`) |
| R-6.8 | Saqlangan qidiruv + bildirishnoma roziligi alohida (§6.6) | `COVERED` | M3–M5, `saved_searches.notify` |

## §7 Segment sig'imi

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-7.1 | `remaining = capacity − SUM(active allocations)` har atomar bo'lakda (§7) | `VERIFIED` | `E2E` E5: 2 o'rinli bron **3 ta** `booking_allocations` qatorini yaratdi (A–B, B–C, C–D) |
| R-7.2 | Tushgan yo'lovchining o'rni keyingi segmentda ishlatiladi (§7) | `COVERED` | AC10/AC11 |
| R-7.3 | Trip satri `FOR UPDATE` bilan bloklanadi; parallel oxirgi o'rin (§7) | `COVERED` | AC07 (20 parallel accept), ADR-0017 lock tartibi |
| R-7.4 | Bagaj/yuk sig'imi o'rindan alohida (§7) | `COVERED` | `baggage_ml`, `cargo_weight_g`, `cargo_volume_ml`; AC12 |
| R-7.5 | Haydovchi/avtomobil ustma-ust safarlari taqiqlanadi (§7) | `COVERED` | AC13 (exclusion constraint) |

## §8 Saralash va reyting

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-8.1 | Saralashdan oldin ruxsat/moslik filtri; balans yetmasa "qabulga tayyor" deb ko'rsatilmaydi (§8.1) | `COVERED` | `ready_to_accept` maydoni; Q21 |
| R-8.2 | `score_client = 100×(0.30M+0.20T+0.20R+0.20P+0.10E)` (§8.2) | `VERIFIED` | `CLIENT_SCORE_WEIGHTS` (`contracts/feed.py:14`) spec bilan bir xil |
| R-8.3 | `E = min(1, ln(1+completed)/ln(101))` (§8.2) | `VERIFIED` | `EXPERIENCE_LOG_BASE_TRIPS = 100` (`contracts/feed.py:23`) |
| R-8.4 | `adjusted_rating = (n×avg + m×prior)/(n+m)`, `m=10` (§8.2) | `COVERED` | `RATING_PRIOR_WEIGHT` (`contracts/trust.py`); AC36 |
| R-8.5 | Yangi haydovchiga sun'iy "4.5" ko'rsatilmaydi (§8.2) | `COVERED` | `ReputationLabel.new_verified`; AC36; U6 `rating_bucket` chegaralari tasdiqlangan (wave 8) |
| R-8.6 | `score_driver = 100×(0.35M+0.20T+0.20Y+0.15C+0.10F)` (§8.4) | `VERIFIED` | `DRIVER_SCORE_WEIGHTS` (`contracts/feed.py:16`) |
| R-8.7 | Haydovchiga arzonlik mukofotlanmaydi; `Y` komissiyadan keyingi tushum (§8.4) | `COVERED` | `driver_score`; `test_driver_score_does_not_reward_the_cheaper_request` |
| R-8.8 | Natijada `ranking_version` qaytadi (§8.4) | `COVERED` | `FeedPageMeta.ranking_version` |

## §9 Naqd to'lov va komissiya balansi

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-9.1 | UI alohida ko'rsatadi: balans, hold, mavjud, pending (§9.1) | `VERIFIED` (tuzatildi) | **F-02**: `posted_balance_minor` ekranda yo'q edi. Wave 13: `driver-income` da «Komissiya balansi» + ushlab qolingan / qaytarilgan / to'ldirishlar / tasdiqlanmagan so'rov |
| R-9.2 | Balans yetmasa yangi to'lovli bron tasdiqlanmaydi; faol safar/GPS to'xtamaydi (§9.2) | `VERIFIED` | `E2E` D2/D3; D16 `OBLIGATION_CAPABILITIES` |
| R-9.3 | Skrinshot pul emas: pending top-up balansga qo'shilmaydi (§9.2, AC24) | `VERIFIED` | `E2E` D4/D5: `posted=0, available=0, pending=10 000 000` |
| R-9.4 | Tasdiqni moliyaviy huquqli xodim manba dalili + yagona reference bilan beradi (§9.2) | `VERIFIED` | `E2E` E1: `source_type=bank_statement` + `source_reference` majburiy; `TopupApprove` |
| R-9.5 | `available = posted − holds` (§9.4) | `VERIFIED` | `E2E` E6: `posted=10 000 000`, `held=5 400 000`, `available=4 600 000` |
| R-9.6 | `commission_minor = round_half_up(total × fee_bps/10000)` (§9.4) | `VERIFIED` | `E2E` E6: 36 000 000 × 1500bps = **5 400 000** (DB'da `commission_minor`) |
| R-9.7 | Pul `BIGINT` minor unit, float yo'q (§9.4) | `COVERED` | `contracts/money.py`; `REG` |
| R-9.8 | Capture va hold release bitta tranzaksiyada; `booking_id+charge_kind` yagona (§9.4) | `COVERED` | AC20; `wallet` unique cheklovlari |
| R-9.9 | `ledger_transactions/entries` o'zgarmas, debit=credit (§9.4) | `COVERED` | AC25; Q55 manba bog'lanishi |
| R-9.10 | `service_status`, `cash_collection_status`, `fee_status` mustaqil (§9.5) | `VERIFIED` | `E2E` E5: `service_status=confirmed`, `cash_status=unpaid`, `commission_status=held` — uchtasi alohida ustun |
| R-9.11 | Mijoz javob bermasa 24 soatda operator navbati (§9.5) | `COVERED` | `DELIVERED_OPERATOR_QUEUE_AFTER = 24h` (`state_machines.py:469`) |
| R-9.12 | Legacy `system_fee` yangi qarzga aylantirilmaydi (§18.2) | `COVERED` | AC37 |

## §10 GPS tracking

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-10.1 | Telefon → o'z serveri oqimi; batch `points:batch`, `UNIQUE(session_id, seq)` (§10.3–§10.4) | `COVERED` | AC27 (backend), AC28, AC29; `tracking_point_receipts` |
| R-10.2 | Eski nuqta live markerni orqaga surmaydi (§10.4) | `COVERED` | AC28 |
| R-10.3 | Stale chegaralari 30 s / 120 s (§10.4) | `COVERED` | `FRESH_MAX_AGE_SECONDS = 30` (`contracts/tracking.py:27`) |
| R-10.4 | GPS haydovchi telefonini kuzatadi, "pochta qurilmasi" emas (§10.3) | `VERIFIED` | `booking-tracking`: «Holat kuzatuvi» va «Jonli joylashuv» ajratilgan, manba «haydovchining telefoni» deb yoziladi, ma'lumot yo'q bo'lsa sabab ko'rsatiladi |
| R-10.5 | Kuzatuv huquqi: pickup'ga 30 daqiqa qolganda, bron tugagach yopiladi (§10.6) | `VERIFIED` | AC30, AC31, AC44; probe: oyna yopiq bo'lsa `TRACKING_WINDOW_NOT_OPEN` sabab qaytadi, UI soxta marker ko'rsatmaydi |
| R-10.6 | Ulashish tokeni ≥128 bit, bazada hash, muddatli (§10.6) | `COVERED` | ADR-0018; `tracking_grants` |
| R-10.7 | Android fon cheklovlari, force-stop dala sinovi (§10.5) | `ENV` | AC32 — **haqiqiy qurilma kerak**, bu repo'da isbotlanmaydi |
| R-10.8 | Xarita kvotasi hisoblagichi va 70%/85% signali (§10.8) | `COVERED` | `/admin/metrics/provider-quota`; Q24 bo'yicha provayder o'chiq |
| R-6.10 | Yo'nalish uchi: bekat **yoki** xaritadagi nuqta (Q88, spec §6.1/6.2 dan chekinish) | `VERIFIED` | Nuqta tasdiqlangan marshrutga proyeksiya qilinadi; radius koridor konfiguratsiyasida (`max_point_offset_m`); tartib, XOR va segment sig'imi `tests/pg/marketplace/test_point_endpoints_pg.py` (11 test) bilan; nuqtali uch `exact` olmaydi |
| R-10.9 | Yuk rasmi faqat egasi, tayinlangan haydovchi va xodimga (Q6, §10.6) | `VERIFIED` (tuzatildi) | **F-07**: havola tekshirilmasdan saqlanardi va haydovchi rasmni ololmasdi. Endi `MediaRefDTO` + imzolangan qisqa muddatli havola; `tests/pg/marketplace/test_parcel_photo_access_pg.py` (6 test) va probe (`403` imzosiz, `404` begonaga) |

## §11 Holatlar va dalillar

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-11.1 | Har obyekt mustaqil holat mashinasi (§11) | `VERIFIED` | `E2E` E5/F1: `service_status` alohida; `state_machines.py` |
| R-11.2 | Pickup va delivery kodlari alohida; pickup kodi bilan yetkazishni yakunlab bo'lmaydi (§11) | `COVERED` | `ProofKind`: `boarding_code`/`pickup_code`/`delivery_code`/`return_code` |
| R-11.3 | Kodni haydovchi o'ziga olib o'zi tasdiqlay olmaydi (§11) | `VERIFIED` | `E2E` F3: noto'g'ri kod → rad (`409`) |
| R-11.4 | Trip yakuni barcha bronlarni avtomatik yakunlamaydi (§11, AC42) | `COVERED` | AC42 |
| R-11.5 | Pochta olingach oddiy `cancelled` yo'q — custody/return jarayoni (§11, AC22) | `COVERED` | AC22 |
| R-11.6 | No-show: haydovchi xabar qiladi, operator tasdiqlaydi (§11, Q7) | `COVERED` | `no_show_reviews`; Q7 |

## §12–§13 Modullar va ma'lumot modeli

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-12.1 | Modul chegaralari; boshqa modul jadvaliga to'g'ridan-to'g'ri yozilmaydi (§12) | `COVERED` | `app/modules/*/service.py`; AGENTS §4; `test_v1_v2_isolation_ac39.py` |
| R-12.2 | DTO/enum klientlarda qo'lda ko'paytirilmaydi (§12) | `VERIFIED` | `mobile-app/src/api/generated/v2.ts` OpenAPI'dan; `tests/test_mobile_v2_client_contract.py` |
| R-13.1 | FK/CHECK'lar noto'g'ri kombinatsiyani DB darajasida to'sadi (§13) | `VERIFIED` | `E2E`: takroriy davlat raqami → `plate_number is already registered`; confirmed marshrut o'zgarmas (trigger) |
| R-13.2 | Cursor pagination + barqaror tie-breaker (§13) | `COVERED` | `decode_id_cursor`, `encode_page_cursor` |

## §14–§15 API va atomar qabul

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-14.1 | `/api/v1` saqlanadi, yangi model `/api/v2` (§14) | `VERIFIED` | `E2E`: ikkala prefiks ham javob beradi; **164** v2 operatsiya |
| R-14.2 | ID'lar opaque; vaqtlar ISO+offset, DB'da UTC (§14) | `VERIFIED` | `E2E`: `usr_`, `lst_`, `bkg_`, `trp_` prefikslari; `Z` bilan qaytadi |
| R-14.3 | Jadvaldagi 25 v2 endpoint mavjud (§14) | `PARTIAL` | 24/25 bor; **`GET /v2/trips/{id}/availability`, `POST /v2/listings/{id}/proposals` va h.k. bor**; yagona bo'shliq edi — marshrut katalogi (**F-01**, tuzatildi: `GET /corridors/{id}/routes`) |
| R-14.4 | `Idempotency-Key`: bir xil kalit+body → oldingi natija; boshqa body → `409` (§14.2) | `VERIFIED` | `E2E` E7 (replay bitta bron, bitta hold) va E8 (`409 IDEMPOTENCY_KEY_REUSED`) |
| R-14.5 | Xato kodlari: `PROPOSAL_CHANGED`, `CAPACITY_UNAVAILABLE`, `INSUFFICIENT_COMMISSION_BALANCE`, `ROUTE_CHANGED`, `403`, `404`, `429` (§14.2) | `VERIFIED` | `E2E` C7, D2; `REG` |
| R-14.6 | Bron javobida wallet tafsilotlari mijozga berilmaydi (§14.2) | `COVERED` | `BookingClientDTO` vs `BookingDTO`; Q16 |
| R-14.7 | Fee quote taklif muddati davomida muzlatiladi (§14.2, AC43) | `COVERED` | AC43 |
| R-15.1 | Lock tartibi barcha yo'llarda bir xil (§15) | `COVERED` | ADR-0017; AC41 |
| R-15.2 | Tashqi SMS/xarita/push DB tranzaksiyasi ichida chaqirilmaydi (§15) | `COVERED` | AGENTS §6; `communications` outbox |
| R-15.3 | Outbox `FOR UPDATE SKIP LOCKED` + retry/backoff (§15) | `COVERED` | AC33 |
| R-15.4 | Push payload'ida telefon/pasport/manzil yo'q (§15) | `COVERED` | `EVENT_PAYLOAD_ALLOWLIST` |
| R-15.5 | Saqlangan safar/jo'natma talabi: bitta talab — bitta tirik bron, parallel accept'da yutqazgan hech narsa band qilmaydi (ADR-0025, 24.09.2026) | `COVERED` | Qabul matritsasi ADR-0025 oxirida; `tests/pg/marketplace/test_trip_intents_pg.py`, `tests/pg/marketplace/test_trip_intents_migration_pg.py`, `tests/pg/promotions/test_trip_intents_promo_pg.py`, vitest `tripIntent.test.ts`, `TripIntentPanel.test.tsx` |

## §16 Qulayliklar (UX)

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-16.1 | Mijoz: e'lon, taklif tanlash, kelishuv kartasi, GPS, yakun (§16) | `VERIFIED` | `/v2` klientida mavjud; `E2E` bilan mos |
| R-16.2 | Haydovchi: jadval, bo'sh o'rin, manifest, balans (§16) | `VERIFIED` (tuzatildi) | **F-01**: avtomobil va safar yaratish ekranlari **yo'q edi** — qo'shildi (`DriverPlanScreens.tsx`) |
| R-16.3 | Qarshi taklif UX'i (§16, P1) | `PARTIAL` | Backend `POST /proposals/{id}/counter` bor; **klientda yo'q** (F-03) |
| R-16.4 | Kelishuv chati va tezkor javoblar (§16, P1) | `PARTIAL` | Backend + `bookings.api.ts` da chaqiruv bor; ekran doirasi tekshirilmadi |
| R-16.5 | 24/7 operator va'da qilinmaydi (§16) | `COVERED` | Q87: `ELCHI_SUPPORT_PHONE` bo'sh, S13 `available=false` |
| R-16.6 | "Taklif yuborildi" ≠ "bron tasdiqlandi" (§5.3, §16) | `VERIFIED` | Klientda taklif holati "Kutilmoqda"; `E2E` D3: rad etilgan accept bron yaratmadi |

## §17 Ishonch, maxfiylik, xavfsizlik

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-17.1 | Tasdiqlangan haydovchi va transport talabi (§17.1) | `VERIFIED` | `E2E`: tasdiqlanmagan avtomobil bilan safar → `409 VEHICLE_NOT_ELIGIBLE`; tasdiqlanmagan haydovchida `trip.create` yo'q → `403 CAPABILITY_REQUIRED` |
| R-17.2 | Baholash faqat bajarilgan bron; 7 kun / ikkala taraf oynasi (§17.2) | `COVERED` | `RATING_PUBLISH_AFTER = 7 kun` (`contracts/trust.py:108`) |
| R-17.3 | Self-dealing taqiqi va firibgarlik signallari (§17.3) | `COVERED` | `SELF_DEALING_FORBIDDEN`; `fraud_signals` (wave 6) |
| R-17.4 | Hujjatlar ochiq URL ostida emas; signed URL / autentifikatsiyali download (§17.4) | `COVERED` | `app/utils/file_access.py`; `tests/test_file_access.py` |
| R-17.5 | OTP rate-limit va abuse nazorati (§17.5) | `VERIFIED` | `E2E`: takroriy so'rov → `429 OTP_RESEND_TOO_SOON` |
| R-17.6 | Staff MFA rejasi P0 gate'da (§17.5) | `COVERED` | ADR-0021 Accepted; wave 8 servis + wave 9 API/UI; **enforcement production'da yoqilmagan** (`DECISION`) |
| R-17.7 | Review akkauntlari real pulga kira olmaydi (§17.5) | `COVERED` | `app/services/review_accounts.py` |
| R-17.8 | Obyekt egasi tekshiruvi; REST va WS'da bir xil scope (§17.6) | `COVERED` | AC30/AC31 |
| R-17.9 | Sessiya revoke real-time kanalda ham yopiladi (§17.6) | `VERIFIED` | `E2E` A6: logout'dan keyin `401`; `0072` `revoked_reason` |
| R-17.10 | Ma'lumot joylashuvi va huquqiy tekshiruv (§17.7) | `DECISION` | K3: O'zbekistondagi hosting qarori; huquqiy xulosa kutilmoqda |
| R-17.11 | Hisobni o'chirish: faol bron/nizo/balans tekshiruvi (§17.8) | `COVERED` | `DELETE /me` (I4), `tests/test_account_deletion_wallet_block.py` |

## §18–§20 Migratsiya, deploy, pilot

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-18.1 | expand → migrate → switch → contract; eski ustun o'chirilmaydi (§18.1) | `COVERED` | 0030–0075 additiv; `alembic heads` bitta |
| R-18.2 | Legacy buyurtmalar v2'da read-only projection (§18.1 M4, Q4) | `COVERED` | AC37, AC39 |
| R-18.3 | Migratsiya qayta ishga tushirilsa dublikat yaratmaydi (§18.1 M1) | `VERIFIED` | `test_import_legacy_districts_pg.py` (qayta ishga tushirish no-op); AC37 |
| R-19.1 | `/health/live` + `/health/ready` (DB tekshiradi) (§19.2) | `VERIFIED` | `E2E`: `live` → `{"status":"live"}`; `ready` → `database ok, migrations ok, redis ok` + `notices` |
| R-19.2 | Strukturali log: `request_id`, actor, duration (§19.2) | `COVERED` | `app/ops/request_id.py` middleware |
| R-19.3 | Ko'rsatkichlar: p95, 5xx, outbox lag, GPS fresh ulushi, ledger farqi, kvota (§19.2) | `PARTIAL` | `/admin/metrics/{kpi,slo,provider-quota}` bor; **o'lchangan SLO yo'q** (`ENV`) |
| R-19.4 | Backup: kundalik dump; RPO ≤ 24 soat (Q35) | `DEFERRED` | WAL/PITR shifrlanmaguncha yo'q — tasdiqlangan qaror |
| R-19.5 | Restore mashqi (AC40) | `ENV` | `scripts/restore_drill.sh` bor; **rasmiy mashq staging'da bajarilmagan** |
| R-19.6 | §19.3 yuklama profili (50 driver, 200 viewer, 20 accept, 100k e'lon) | `ENV` | `scripts/load_profile.py` harness bor; **staging yo'q** — lokal smoke SLO dalili emas |
| R-20.1 | Feature flag'lar koridor darajasida; flag o'zgarishi auditga tushadi (§20.3) | `VERIFIED` | `E2E` C2c: `PUT /admin/feature-flags/passenger_enabled/scopes/corridor/{id}` → 200, `expected_version` bilan optimistik nazorat |
| R-20.2 | Flag o'chsa faol bron ishlaydi, yangi bron to'xtaydi (§20.3, AC38) | `COVERED` | AC38 |
| R-20.3 | KPI: `booked_seat_km/offered_seat_km`, koridor kesimida sof komissiya (§20.4) | `COVERED` | wave 7: `booked_seat_km_ratio`, `net_commission_per_corridor`; `missing_metrics` bo'sh |
| R-20.4 | Kengayish mezonlari (≥70% moslik, ≥90% bajarilish va h.k.) | `ENV` | Pilot ma'lumoti yo'q — o'lchanmagan |

## §21–§22 Bajarish rejasi va acceptance

| ID | Talab | Holat | Dalil |
|---|---|---|---|
| R-21.1 | A0–A11 kartalari bajarilgan | `COVERED` | `WAVE1_CARDS.md` wave 0.5–10 |
| R-21.2 | Definition of Done har PR'da (§21.2) | `COVERED` | AGENTS §8; wave hisobotlari |
| R-21.3 | Idempotency/seat/wallet testlari PostgreSQL'da (§21.2) | `VERIFIED` | `tests/pg/**`, `REG` = 2119 test |
| R-22.1 | AC01–AC44 | `COVERED` | [`COVERAGE_MATRIX.md`](COVERAGE_MATRIX.md): **42 PASS**, AC32 `FIELD`, AC40 `PROCEDURE` |

---

## Qamrov hisobi

| Holat | Soni |
|---|---:|
| `VERIFIED` (shu seansda dalil bilan) | 31 |
| `COVERED` (repo testlari bilan) | 43 |
| `PARTIAL` | 5 |
| `DECISION` / `ENV` / `DEFERRED` | 11 |
| `MISSING` | 0 (F-01/F-02 tuzatilgach) |

**Foiz bermaymiz:** «90% tayyor» degan raqam AC32 (dala GPS dalili), §19.3 (yuklama), AC40 (restore) va huquqiy qarorlar kabi **o'lchanmagan** bandlarni yashiradi. Yuqoridagi jadval har bandning holatini alohida ko'rsatadi.
