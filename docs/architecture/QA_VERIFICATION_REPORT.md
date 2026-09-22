# QA verifikatsiya hisoboti — 17.09.2026

**Doira:** `ELCHI_PRODUCTION_ARCHITECTURE.md` v1.0 ↔ haqiqiy kod, ishlayotgan backend, `mobile-app` klienti, PostgreSQL.
**Talablar matritsasi:** [`QA_REQUIREMENTS_MATRIX.md`](QA_REQUIREMENTS_MATRIX.md) • **Topilmalar:** [`QA_FINDINGS.md`](QA_FINDINGS.md) • **AC01–AC44:** [`COVERAGE_MATRIX.md`](COVERAGE_MATRIX.md)

## 1. Muhit va kod holati

| Band | Qiymat |
|---|---|
| Kod | commit `4f468c3` + commit qilinmagan lokal diff (push/commit bajarilmadi) |
| Migratsiya | `alembic heads` = `20260917_0075` — bitta head |
| Test bazasi | `docker-compose.test.yml` PostgreSQL 16.15 + PostGIS 3.5.3 (`127.0.0.1:45432`), tmpfs |
| Jonli tekshiruv bazasi | `docker-compose.dev.yml` (yangi) — bir xil PostGIS image, **doimiy volume** (`127.0.0.1:45433`) |
| Jonli backend | `py -m uvicorn app.main:app --port 8001`, `.env` orqali dev bazasiga ulangan |
| Katalog | 14 viloyat, 170 tuman, 1 koridor, 6 bekat, 2 tasdiqlangan marshrut |
| Klient | `mobile-app` (Vite + React) — `tsc --noEmit` toza |
| Muhit markeri | `development` (production emas; probe production bazada ishlashdan bosh tortadi) |

## 2. Bajarilgan tekshiruvlar

| # | Buyruq | Sana / vaqt (UTC) | Natija |
|---|---|---|---|
| 1 | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q -p no:cacheprovider --junitxml=…` | 17.09 14:51 | **2119 test: 2119 o'tdi, 0 failure, 0 error, 0 skip** (exit 0, 951 s) |
| 2 | `py scripts/qa_probe.py` (jonli API + DB) | 17.09 15:2x | **30 tekshiruv, 0 failure** |
| 3 | `scratchpad/e2e.py` (auth/sessiya) | 17.09 15:1x | **7 tekshiruv, 0 failure** |
| 4 | `… pytest tests/pg/geo/test_geo_routes_catalogue_pg.py -q` | 17.09 15:21 | **4 o'tdi** (F-01 regressiyasi) |
| 5 | `… pytest tests/pg/geo/test_geo_districts_pg.py tests/pg/marketplace/feed/test_feed_districts_pg.py -q` | 17.09 | 14 o'tdi |
| 6 | `py scripts/export_openapi.py` + `npm run gen:api` + `npm run lint` | 17.09 15:3x | v2 **164** operatsiya (163 → +1: G18), `tsc` xatosiz |
| 7 | To'liq regressiya (QA tuzatishlaridan keyin) | 17.09 15:51–16:05 | **2128 test: 2128 o'tdi, 0 failure, 0 error, 0 skip** (exit 0, 861 s) |

`REG` natijasi `junit.xml` bilan saqlangan; AC matritsasi shu fayldan avtomatik yaratiladi.

## 3. Jonli oqim dalili (mock emas)

Har qadam HTTP orqali bajarildi va natija **bazadan o'qib** tasdiqlandi:

| Qadam | Natija |
|---|---|
| OTP login (mijoz va haydovchi) | Sessiya olindi; `/api/v2/me` v1 tokenini qabul qildi (ADR-0006) |
| Refresh → logout | Logout'dan keyin access token darhol `401` (§17.6) |
| Takroriy OTP so'rovi | `429 OTP_RESEND_TOO_SOON` (§17.5) |
| Avtomobil ro'yxati | `201`; takroriy davlat raqami DB darajasida rad (§13) |
| Tasdiqlanmagan avtomobil bilan safar | `409 VEHICLE_NOT_ELIGIBLE` (§17.1) |
| Safar yaratish | `201`, tasdiqlangan marshrut bo'yicha 4 bekat |
| E'lon (2 o'rin × 200 000) | Server jami summani **o'zi** hisobladi: `total_minor = 40 000 000` (AC01) |
| Xizmat flag'i o'chiq | Nashr `403 FEATURE_DISABLED` (Q5) |
| `super_admin` staff-login + flag yoqish | `200`; mavjud qator `expected_version` talab qildi (optimistik nazorat) |
| Haydovchi taklifi | `201`, `proposal_version` yaratildi |
| O'z taklifini qabul qilish | `403 NOT_PROPOSAL_RECIPIENT` (AC05) |
| Mijoz qarshi taklifi | `200`, yangi revision |
| Eskirgan versiyani qabul qilish | `409 PROPOSAL_CHANGED`, bron yaratilmadi (AC04) |
| Balanssiz qabul | `409 INSUFFICIENT_COMMISSION_BALANCE`; `bookings` soni o'zgarmadi (§9.2) |
| Top-up so'rovi | `pending`; `posted=0`, `available=0`, `pending=10 000 000` (AC24) |
| Moliya tasdig'i | `source_type=bank_statement` + `source_reference` majburiy; `posted=10 000 000` (§9.2) |
| Qabul (accept) | `201` bron; `service_status=confirmed`, `cash_status=unpaid`, `commission_status=held` — uchtasi mustaqil (§9.5) |
| Segment sig'imi | 2 o'rinli bron **3 ta** `booking_allocations` qatorini yaratdi (§7) |
| Komissiya | `36 000 000 × 1500 bps = 5 400 000`; `available = 10 000 000 − 5 400 000` (§9.3, §9.4) |
| Idempotent replay | Bir xil kalit → **bitta** bron, **bitta** hold (AC08) |
| Kalitni boshqa body bilan ishlatish | `409 IDEMPOTENCY_KEY_REUSED` (AC09) |
| Xizmat harakati | `awaiting_pickup` o'tdi; noto'g'ri boarding kod rad etildi (§11) |

## 4. Tuzatilgan nuqsonlar

| ID | Jiddiylik | Tuzatish | Regressiya testi |
|---|---|---|---|
| F-01 | **P0** | G18 `GET /corridors/{id}/routes` + haydovchi «Yangi safar»/«Avtomobil» ekranlari | `tests/pg/geo/test_geo_routes_catalogue_pg.py` (4 test), jumladan provayder `503` bo'lganda safar rejalashtirish |
| F-02 | P2 | Hamyonda «Kiritilgan (jami)» qatori | `tsc`; jonli qiymatlar bilan mos |
| F-03 | P1 | Klientda qarshi taklif (`counterProposal`/`withdrawProposal` + forma) | `tsc`; endpoint jonli tekshirildi |
| F-04 | P2 | Yo'nalish pikeri koridordan ajratildi | wave 10 testlari |
| F-06 | P1 | `docker-compose.dev.yml` (doimiy PostGIS bazasi) + `.env` + `RUNNING.md` | Konteyner restartidan keyin ma'lumot saqlanishi tekshirildi |

## 5. UX/UI baholash

| Jihat | Baho | Izoh |
|---|---|---|
| Mijoz oqimi (`/v2`) | **Ishlaydi** | E'lon → takliflar → qarshi taklif (yangi) → qabul → bron → tracking → yordam |
| Haydovchi oqimi | **Endi ishlaydi** | F-01 gacha avtomobil/safar yaratib bo'lmasdi; endi to'liq zanjir bor |
| Operator paneli | **Qisman** | 6 ta v2 bo'lim (navbatlar, nizolar, KPI/SLO, MFA); koridor/bekat/moliya ekranlari yo'q (F-05) |
| Narx aniqligi | **To'g'ri** | `2 x 200 000 = 400 000` ko'rinishida; hamyonda posted/held/available ajratilgan |
| Rostgo'ylik | **To'g'ri** | «Taklif yuborildi» ≠ «bron»; pending top-up pul emas; GPS yo'q bo'lsa soxta marker yo'q; support raqami yo'q bo'lsa va'da yo'q |
| Bo'sh holatlar | **Yaxshilandi** | Katalog bo'sh bo'lsa sabab yoziladi (`CatalogueNotice`), avval jim bo'sh selektlar edi |
| Lokalizatsiya | **Qisman** | Interfeys o'zbekcha; ruscha tarjima to'plami yo'q — ochiq band |
| Klaviatura/kontrast/fokus | **Tekshirilmagan** | Avtomatlashtirilgan a11y audit bajarilmadi (`NOT_RUN`) |
| Android klienti | **Doira tashqarisida** | `android-app/` muzlatilgan; AC32 uchun haqiqiy qurilma kerak |

## 6. Backend to'g'riligi, xavfsizlik, production tayyorligi

| Soha | Baho | Asos |
|---|---|---|
| **Biznes invariantlari** | Kuchli | 2119 test, 0 failure; jonli oqimda pul/o'rin/versiya/idempotency qoidalari tasdiqlandi |
| **Ma'lumot yaxlitligi** | Kuchli | FK/CHECK/trigger DB darajasida (takroriy raqam, o'zgarmas marshrut, append-only audit) |
| **Xavfsizlik** | Yaxshi, lekin yakunlanmagan | OTP limiti, logout revoke, obyekt egasi tekshiruvi, signed URL, Q40 anonimlik ishlaydi. **MFA enforcement yoqilmagan** (ikki `super_admin` kerak), huquqiy tekshiruvlar ochiq |
| **Kuzatuv** | Qisman | `/health/live`, `/health/ready`, `request_id`, KPI/SLO endpointlari bor; **o'lchangan SLO yo'q** (staging yo'q) |
| **Production tayyorligi** | **Tayyor emas** | Q48/Q36/Q28 gate'lari, UZ registry digesti (Q34/Q51/Q73), rasmiy AC40 restore, Q35 shifrlangan dump, §19.3 yuklama — hammasi ochiq va tasdiqlangan tartibda keyinga qoldirilgan |

## 7. Ochiq bandlar

| Band | Sabab | Mas'ul | Keyingi amal |
|---|---|---|---|
| AC32 / AC27 dala qismi | Haqiqiy Android qurilmasi | Android dasturchisi | Release build bilan yo'l sinovi; emulyator dalil emas |
| AC40 rasmiy restore | Staging muhiti | A10a | `scripts/restore_drill.sh` ni staging'da bajarish |
| §19.3 yuklama profili | Staging + 100 000 e'lonli fixture | A10a | Fixture seed + `scripts/load_profile.py` |
| §5.2 taqiqlangan ro'yxat | Yurist xulosasi | Biznes | Ikki `super_admin` bilan faollashtirish |
| MFA enforcement | ≥2 `super_admin` | Ops | `staff_mfa_mode=enforce_privileged` |
| Push (FCM) | Huquqiy xulosa + credential | Biznes / A7 | ADR-0022 bo'yicha yoqish |
| F-05 klient qamrovi | Ekran yozilmagan | A8/A9 | M2 matches, naqd kvitansiya, admin koridor/moliya ekranlari |
| Ruscha lokalizatsiya | Tarjima to'plami yo'q | A8 | uz/ru resurs fayllari |
| a11y auditi | Bajarilmagan | A8 | Klaviatura, fokus, kontrast tekshiruvi |
| Deploy gate'lari (Q48/Q36/Q28/Q34/Q51/Q73/Q35) | Foydalanuvchi qaroriga ko'ra keyinga qoldirilgan | Ops | Holati o'zgartirilmadi |

## 8. Xulosa

Backend biznes yadrosi — ikki tomonlama kelishuv, segment sig'imi, komissiya balansi va ledger, idempotency, holatlar ajratilishi — **jonli tizimda ham, testlarda ham** ishlaydi. Auditda topilgan eng jiddiy nuqson mahsulot darajasida edi: production konfiguratsiyasida (routing provayderi o'chiq) **haydovchi umuman safar yarata olmasdi**, ya'ni marketplace'ning taklif tomoni yopiq edi. U tuzatildi va regressiya testi bilan qoplandi.

**«Hammasi tayyor» degan xulosa berilmaydi:** dala GPS dalili, restore mashqi, yuklama profili, huquqiy ro'yxat va MFA enforcement o'lchanmagan yoki tashqi qarorga bog'liq. Ular yuqorida alohida ko'rsatilgan.

## 9. Yakuniy regressiya tafsiloti

| Band | Qiymat |
|---|---|
| Buyruq | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q -p no:cacheprovider --junitxml=…` |
| Kod holati | commit `4f468c3` + commit qilinmagan diff (tracked sha256 `ca70cab53ed60c55`, untracked 489 fayl sha256 `60039a08fddf7b5a`) |
| Migratsiya | `alembic heads` = `20260917_0075` (bitta head) |
| Oyna | 2026-09-17T15:51Z … 16:05Z (860.7 s) |
| Natija | **2128 test: 2128 o‘tdi, 0 failure, 0 error, 0 skip** (exit 0) |
| AC01–AC44 | 42 PASS, AC32 `FIELD`, AC40 `PROCEDURE` — o‘zgarmadi |

O‘sish 2119 → 2128 (+9): G18 marshrut katalogi testlari 4 ta va `tests/test_mobile_v2_client_contract.py` da +5
(u generatsiya qilingan operatsiyalar bo‘yicha parametrlangan). **O‘zgargan xulqni aks ettirish uchun yangilangan
test:** `tests/pg/geo/test_geo_api_pg.py` dagi geo operatsiyalari sanog‘i 21 → 22 (G18 qo‘shilgani uchun).
