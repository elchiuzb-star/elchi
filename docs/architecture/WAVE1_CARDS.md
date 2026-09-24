# WAVE1_CARDS — wave 0.5 va wave 1 topshiriq kartalari

**Muallif:** A0a • **Sana:** 13.09.2026 (wave 1: Q12–Q19, N1–N5 bilan) • **Holat:** Accepted (ADR’lar Q19)
Majburiy o‘qish: [`AGENTS.md`](../../AGENTS.md), [`BASELINE_AUDIT.md`](BASELINE_AUDIT.md), ADR 0001–0018, [`STATE_MACHINES.md`](STATE_MACHINES.md), [`API_V2_CONTRACT.md`](API_V2_CONTRACT.md), [`DATA_MODEL.md`](DATA_MODEL.md), `app/contracts/`.

## Umumiy qoidalar
- **Integrator fayllari (so‘rov orqali):** `app/api/v2/__init__.py`, `app/modules/__init__.py`, `alembic/env.py`, `app/main.py` (hozir H0), `app/contracts/**`, `docs/architecture/**`.
- **Boshqa agentlar egaligi:** H0 — upload/file kodi, `app/main.py`, `app/utils/file_*`, `app/api/v1/files.py`, `.env*.example`; A0b — `docker-compose.test.yml`, `tests/pg/conftest.py`, `tests/pg/harness.py`, `tests/pg/test_*` (infra), `scripts/test-pg.*`, `pyproject.toml`, `requirements-dev.txt`, `BASELINE_TESTS.md`.
- **PG test infra (A0b):** `docker-compose.test.yml` (`postgis/postgis:16-3.5` digest pin, `127.0.0.1:45432` — Q76, avval 55432, DB/user `elchi_test`; Redis `127.0.0.1:36379`), `scripts/test-pg.sh|ps1`. Guard: faqat localhost va DB nomida `test` tokeni. Modul agentlari faqat o‘z `tests/pg/<module>/**` va `tests/modules/<module>/**` papkalarida.
- **Migratsiya:** integrator 0030–0041 stub fayllarini yaratgan (`alembic/versions/20260913_00NN_<module>_<slug>.py`, zanjir `20260803_0029 → … → 20260913_0041`). Egasi faqat o‘z faylidagi `upgrade()`ni to‘ldiradi; revision id, fayl nomi, `down_revision` o‘zgarmaydi; yangi migratsiya fayli yaratilmaydi; `upgrade` idempotent; bitta head. Tartib: 0033 flags (A2) → 0034 geo katalog (A2) → 0035 route versions (A2) → 0036 commission policies (A3) — FK sababli o‘zgartirilgan (DATA_MODEL §5). **Wave 1.5:** forward-migration stub’lari `20260914_0042_platform_wallet_hardening.py` (A3), `20260914_0043_geo_hardening.py` (A2), `20260914_0044_identity_marketplace_hardening.py` (A1) yaratilgan; egasi faqat o‘z `upgrade()`ni to‘ldiradi. Wave 1 migratsiyalari (0030–0041) endi o‘zgartirilmaydi — tuzatish faqat 0042–0044 da. **Wave 1.6:** stub’lar `20260914_0045_trips_detour_seconds.py` (A1), `20260914_0046_geo_stop_evidence_price_bands.py` (A2), `20260914_0047_wallet_balance_guard_withdraw.py` (A3); **A4 (wave 2) raqamlari 0048 dan boshlanadi.**
- **Router:** `app/modules/<name>/api.py`; ulash — integrator.
- **Lock tartibi:** ADR-0017 / `STATE_MACHINES.md` §0.2; lock helper’lar shu tartibda chaqiriladi.
- **Birliklar:** `*_g`, `*_ml`, `*_cm`, `*_m` integer.
- **Commit/push/deploy yo‘q.**

### Umumiy DoD (har karta)
1. AGENTS.md §8 bandlari.
2. PG testlari `ELCHI_TEST_PG_REQUIRED=1` bilan ishga tushirilgan (skip “o‘tdi” hisoblanmaydi); buyruq va natija hisobotda.
3. Migratsiya: toza `elchi_test`da `alembic upgrade head`, **ikkinchi `upgrade head` no-op**, bitta head. Downgrade talab qilinmaydi.
4. `py -m pytest tests/contracts -q` va to‘liq suite `--collect-only` xatosiz.
5. OpenAPI’da endpointlar `response_model` bilan; event payload’lar allowlist’dan o‘tadi.
6. BR checklist javoblari.

---

## H1 — v1 hardening (wave 0.5, H0 yakunlagandan keyin)

**Maqsad:** v1 race va invariant buzilishlarini yopish, tasdiqlangan v1 xulq o‘zgarishlarini (Q8, Q10) qo‘llash, javob shaklini saqlash.
**Spec:** §15, §17.5, §17.8, §18.1 M4, §21.2; `BASELINE_AUDIT.md` §2.4, §6 (V1–V9).

**Boshlash sharti:** H0 quyidagi fayllardagi ishini topshirgan (H0 diff’i: `order_service.py`, `driver_order_service.py`, `admin_order_service.py`, `account_deletion_service.py`, `driver_service.py`, `admin_driver_service.py`, `app/core/config.py`).

**Fayl egaligi:**
- `app/services/order_service.py` — `cancel_order`, `publish_order`, `update_order`, `get_owned_order` (lock varianti), `select_driver_for_order` (review izolyatsiyasi)
- `app/services/driver_order_service.py` — `create_bid`, `update_bid`, feed/visibility (review izolyatsiyasi)
- `app/services/matching_service.py` — review izolyatsiyasi
- `app/services/admin_order_service.py` — V9
- `app/api/v1/admin_orders.py` — Q10 rol cheklovi
- `app/services/account_deletion_service.py` — V8
- `app/services/admin_driver_service.py` — `block_driver` lock (AC41 v1 tomoni)
- `tests/pg/test_v1_order_races.py` (yangi; H1 implementatsiyasida `tests/pg/v1/` papkasi o‘rniga shu fayl); mavjud `tests/test_*.py` — faqat o‘zgargan xulq uchun, A0b bilan kelishib
- **Egalikdan tashqari:** `app/services/system_settings_service.py`, `app/api/v1/admin_settings.py` (A3); `app/core/config.py` (H0 — faqat o‘qish)

**Talablar:**
1. **V1–V7 lock’lar:** order `FOR UPDATE` bilan status qayta tekshiruvi; lock tartibi order → bids (`id ASC`); mijoz bekor qilganda active bid’lar `closed`; `update_bid` bid va order’ni lock qiladi, `active` bo‘lmasa rad etadi va statusni qayta yozmaydi.
2. **V8:** `disputed` in-flight to‘plamiga (akkaunt o‘chirilmaydi). **N4:** v2 blocking tekshiruvlari wave 3 ga qoldirilmaydi — `wallet.service.blocking_state_for_user` (A3, wave 1) va booking ekvivalenti (A4, wave 2) paydo bo‘lishi bilan H1 (yoki integrator) ularni v1 o‘chirishga read-only ulaydi (ADR-0006 D5); funksiya yo‘q bo‘lsa import qilinmaydi, ulash integratsiya o‘tishida.
3. **V9 (tasdiqlangan):** `disputed` `MANUAL_TARGET_STATUSES`dan chiqariladi — faqat dispute endpointi orqali.
4. **Q10:** `PATCH /api/v1/admin/orders/{id}/status`, `POST …/assign-driver`, `POST …/cancel` — `admin`, `super_admin`; operator → v1 `403 FORBIDDEN`. `GET` ro‘yxat/tafsilot operator uchun qoladi.
5. **Q8 review akkauntlari:** `settings.review_login_phones` ro‘yxatidagi akkauntlar (runtime, migratsiyasiz) real foydalanuvchilarga yetmaydi: ularning buyurtmalari real driver feed/matching/offer’larida yo‘q; review driver faqat review buyurtmalarini ko‘radi va taklif beradi; real mijoz review driverni tanlay olmaydi; SMS/xabarnoma real foydalanuvchiga ketmaydi; admin ro‘yxatida belgilanadi. Pul oqimi yo‘q (v1’da real undirish yo‘q; v2 wallet cheklovi — A3 ga eslatma).
6. **AC41 v1:** `block_driver` driver user’ini lock qiladi; `select_driver_for_order` driver user’ini order’dan keyin, lekin bid’dan oldin emas — tartib: order → bids → driver user (v1 ichki tartib, hujjatlanadi).
7. **Q12:** nizo `open`/`under_review` bo‘lsa `PATCH /api/v1/admin/orders/{id}/status` → v1 `409` (xato shakli v1 envelope).
8. **Q13:** buyurtma statusini tiklaydigan yoki o‘zgartiradigan nizo `resolved/rejected` qarori (`PATCH /api/v1/admin/disputes/{id}`) — `admin`, `super_admin`; operator faqat `under_review`ga o‘tkazish va izoh (resolution matnisiz status o‘zgarishi yo‘q) — `403` aks holda.
9. **Q14:** majburiy `confirmed` → `paid_manual` xulqi o‘zgarmaydi (hujjatlanadi).
10. **Q18:** `BID_NOT_ACTIVE` 409 saqlanadi.
11. Javob shakli, HTTP status va xato kodlari o‘zgarmaydi, Q10/Q12/Q13/V9/V8 bundan mustasno (tasdiqlangan).

**Testlar:** PG (`tests/pg/test_v1_order_races.py`, `ELCHI_TEST_PG_REQUIRED=1`): (a) `cancel_order` vs `select_driver_for_order`; (b) `update_bid` vs `select_driver_for_order`; (c) `create_bid` vs `select_driver_for_order`; (d) parallel `publish_order`; (e) `block_driver` vs `select_driver_for_order`. Har biri avval qizil (tuzatishsiz), keyin yashil — dalil hisobotda. API: operator 403 (Q10), `disputed` override rad (V9), `disputed` bilan akkaunt o‘chirish rad (V8), review izolyatsiyasi. Mavjud SQLite testlari o‘tadi (o‘zgargan xulq bundan mustasno, izohlanadi).

**Doiradan tashqari:** v2 kodi, upload (H0), commission/settings (A3), OTP uzunligi (Q8), v1 status modelini o‘zgartirish.

**BR checklist:**
- [ ] v1 JSON shakli bir xil; faqat Q10, V8, V9 xulqi o‘zgargan.
- [ ] Mijoz bekor qilgan buyurtmada active bid yo‘q; yopilgan bid qayta `active` bo‘lmaydi.
- [ ] Race’lar PG’da isbotlangan (SQLite emas).
- [ ] Operator status majburlay/tayinlay/bekor qila olmaydi (Q10).
- [ ] Nizo yozuvisiz `disputed` yo‘q (V9).
- [ ] Ochiq nizoda qo‘lda status 409 (Q12); status o‘zgartiradigan nizo qarori admin+ (Q13).
- [ ] `paid_manual` va `BID_NOT_ACTIVE` xulqi o‘zgarmagan (Q14, Q18).
- [ ] v2 blocking tekshiruvlari mavjud funksiyalar bilan ulangan yoki integratsiya o‘tishiga qayd etilgan (N4).
- [ ] Review akkauntlari real foydalanuvchi va pulga yetmaydi (Q8).
- [ ] H0 va A3 fayllariga tegilmagan.

---

## A1 — Identity, marketplace va trips

**Maqsad:** capability va eligibility (D16), staff/marketplace ajratish (Q3), vehicle, trip (sig‘im, overlap), listing, proposal thread/versiya — accept’siz.
**Spec:** §5.1–5.4, §7, §8.1, §11, §12, §13, §16, §21 A1.

**Fayl egaligi:**
- `app/modules/identity/**` — `get_capabilities` (`STAFF_ROLE_CAPABILITIES`, `NEW_BUSINESS_CAPABILITIES`, `OBLIGATION_CAPABILITIES`), `ensure_driver_eligible`, `lock_user_eligibility`, `activate_role` (`role_combination_allowed`), `block_driver_eligibility`/`unblock`; `api.py`: I1–I3, I5
- `app/modules/trips/**` — vehicles, trips, occurrences, segment resources; `lock_trip`, `check_capacity`, `reserve`, `release`; `api.py`: T1–T8 (T3 ham)
- `app/modules/marketplace/**` (saved searches’dan tashqari) — `lock_listing`, `lock_thread`, listing va proposal buyruqlari; `api.py`: L1–L8, P1–P7
- `tests/modules/{identity,trips,marketplace}/**`, `tests/pg/{identity,trips,marketplace}/**`
- Migratsiyalar: `20260913_0032_identity_roles_eligibility.py`, `20260913_0037_trips_vehicles.py`, `20260913_0038_trips_trips_segments.py`, `20260913_0039_marketplace_listings.py`, `20260913_0040_marketplace_proposals.py`

**Kontraktlar:** `enums` (statuslar, Capability xaritalari, `ALLOWED_PRICE_BASIS`, `LISTING_AUTHOR_ROLE`, `role_combination_allowed`), `money.total_minor`, `timeutil`, `ids`, `errors` (`QUANTITY_MISMATCH` va b.), `dto`, `state_machines.LISTING/PROPOSAL_VERSION/TRIP`, `events` (A3 `enqueue_event`), `idempotency` (A3 servisi). A2 `evaluate_route_match`, `is_flag_enabled`; A3 `quote_fee`.

**Talablar:**
- Server `total_minor`; `price_basis` jadvali.
- **D9:** passenger request’ga proposal `quantity == seat_count`; parcel `quantity == 1`; trip_offer’da `quantity ≤` qolgan o‘rin; counter’da ham.
- Overlap exclusion (driver, vehicle); `completed/cancelled` trip overlap’dan chiqadi.
- Resurslar ml/g birliklarida; `[pickup, dropoff)`.
- Proposal TTL, 3 tuzatish, self-dealing taqiq, immutable versiya, fee quote snapshot (muddati = versiya TTL).
- **D16:** eligibility bloki `driver_eligibility_blocks` orqali, faqat NEW_BUSINESS capability’larni oladi; faol trip’da `trip.operate`, `tracking.publish` qoladi; `users.status` o‘zgarmaydi.
- **Q3:** staff+marketplace roli birikmasi servis va DB trigger bilan rad.
- **Q17:** `finance` roli `user_roles` CHECK’ida va staff to‘plamida (`Role.FINANCE`, `STAFF_ROLES`); staff boshqaruvi orqali beriladi; capability xaritasi kontraktdan.
- `users.role`, v1 auth o‘zgarmaydi.

**AC:** AC01, AC05 (submit), AC10, AC11, AC12 (domen), AC13, AC41 (eligibility lock), AC43 (quote snapshot).

**Testlar:** PG — AC13 parallel trip, AC10/AC11 `reserve` va CHECK, oxirgi o‘ringa parallel `reserve`, `user_roles` backfill idempotentligi va Q3 trigger, proposal partial unique, immutable trigger, eligibility block vs parallel listing publish. UT — total, price basis, D9, TTL, revision limiti, capability hisobi (blocked driver faol trip bilan / trip’siz).

**Doiradan tashqari:** accept/booking (A4), trip actions (A4), feed (A5), geo (A2), wallet (A3), UI, v1 servislari.

**BR checklist:**
- [ ] 2 × 20 000 000 = 40 000 000 (AC01).
- [ ] Request bo‘linmaydi; `QUANTITY_MISMATCH` (D9, §5.3(6)).
- [ ] Taklif sig‘im/balans band qilmaydi (§5.3).
- [ ] O‘z listing’iga taklif 403 (AC05).
- [ ] Versiya immutable; eski revision counter 409.
- [ ] Overlap DB darajasida (AC13).
- [ ] Bloklangan driver yangi listing/trip/proposal qila olmaydi, faol trip’da tracking/proof davom etadi (D16).
- [ ] Staff va marketplace roli bitta akkauntda emas (Q3).
- [ ] Birliklar g/ml/cm (D14).

---

## A2 — Geo katalog, routing adapteri va feature flag yadrosi

**Maqsad:** PostGIS katalog, route version, `evaluate_route_match`, ETA oynasi, kumulyativ detour, flag baholash (Q1, Q5).
**Spec:** §6.1–6.5, §10.2, §10.8, §17.7, §20.3, §21 A2.

**Fayl egaligi:**
- `app/modules/geo/**` (`routing/` provayder protokoli, fake provider, bitta hosted adapter; `api.py`: G1–G11, F1–F4)
- `tests/modules/geo/**`, `tests/pg/geo/**`, `tests/fixtures/geo/**`, `scripts/seed_geo_fixtures.py` (faqat dev/test)
- Migratsiyalar: `20260913_0033_geo_feature_flags.py`, `20260913_0034_geo_catalog.py`, `20260913_0035_geo_route_versions.py` (geo katalog va route versions A3 commission policy’dan va A1 trips/listings’dan oldin tayyor bo‘lishi kerak)

**Kontraktlar:** `enums` (`MatchType`, `FeatureFlagKey`, `FlagScopeType`, `PRODUCTION_FLAG_DEFAULTS`, `FLAGS_LOCKED_IN_PRODUCTION`, `FLAGS_REQUIRING_APPROVAL_REFERENCE`), `timeutil.windows_intersect`, `ids`, `errors`, `dto`.

**Talablar:**
- `ST_DWithin(geography, geography, m)`; pickup va dropoff tekshiruvi; bekat tartibi; teskari yo‘nalish rad; ETA oraliq bekat bo‘yicha; kumulyativ detour; router tranzaksiyadan tashqarida; uzilishda `ROUTING_UNAVAILABLE`.
- `cities.type=region` avtomatik shahar emas.
- **Flag’lar (Q5):** production defaults — barcha yangi xizmatlar o‘chiq; `passenger_enabled`/`card_payments_enabled`ni production’da yoqish super_admin + `approval_reference`; boshqa flag’lar `ops.feature_flag_manage` (admin+).
- **Q1:** production’da `wallet_required` faqat `true` (`FLAG_LOCKED_IN_ENVIRONMENT`); `is_flag_enabled` production’da har doim `true` qaytaradi.
- Legacy yozuv kill-switch yaratilmaydi (Q4).
- Append-only tarix, audit.

**AC:** AC14, AC15, AC16, AC17 (hisob), AC35, AC38 (yadro).

**Testlar:** PG (PostGIS `elchi_test`) — AC14/AC16 fixture, geography masofa, GiST, flag unique, tarix trigger, `APPROVAL_REFERENCE_REQUIRED`, `FLAG_LOCKED_IN_ENVIRONMENT`. UT — ETA, detour, match_type, provider uzilishi, scope ustunligi.

**Doiradan tashqari:** feed (A5), trip (A1), accept (A4), UI (A8), rollout UI (A13), production seed.

**BR checklist:**
- [ ] Chiroqchi hard-code yo‘q; pickup va dropoff ikkalasi tekshirilgan.
- [ ] Teskari yo‘nalish chiqmaydi (AC16); ETA oraliq bekat (AC15); detour yig‘indisi (AC17).
- [ ] Router uzilsa soxta moslik yo‘q (AC35).
- [ ] Production’da yangi xizmatlar o‘chiq; passenger super_admin + approval (Q5).
- [ ] `wallet_required=false` production’da mumkin emas (Q1).
- [ ] Flag o‘zgarishi ochiq bron snapshot’iga ta’sir qilmaydi.

---

## A3 — Platform (idempotency/outbox), wallet/ledger, komissiya policy

**Maqsad:** idempotency (savepoint naqshi) va outbox yozuvi; prepaid komissiya balansi, hold (bitta, adjust), capture/release, bir nechta qisman reversal, top-up, immutable ledger, reconciliation; versiyalangan policy (Q1, Q2) va v1 settings adapteri.
**Spec:** §9.1–9.5, §13, §14.2, §15, §18.2, §21 A3.

**Fayl egaligi:**
- `app/modules/platform/**` — `acquire_idempotency`, `run_idempotent` (savepoint: `begin_nested`, domen 4xx replay), `enqueue_event` (`EventEnvelope`)
- `app/modules/wallet/**` — `lock_wallet`, `get_wallet`, `hold_fee`, `adjust_hold` (D10), `capture_fee`, `release_fee`, `reverse_fee` (D4), `quote_fee`, `resolve_policy`, `create_policy`/`end_policy` (super_admin), top-up, adjustment, `reconcile`, `production_invariants_status()` (A10a readiness chaqiradi — natija `ok|fail`, 503 bermaydi), `require_production_invariants()` (pul buyruqlari oldidan, buzilganda `503 PRODUCTION_INVARIANTS_FAILED`), **`blocking_state_for_user(user_id)`** (N4: `{wallet_posted_minor, active_holds_minor, pending_topups}` — read-only, v1 akkaunt o‘chirish uchun); `api.py`: W1–W16
- `app/services/system_settings_service.py` va `app/api/v1/admin_settings.py` — faqat v1 adapteri (Q2: PATCH super_admin, javob shakli o‘zgarmaydi)
- `tests/modules/{platform,wallet}/**`, `tests/pg/{platform,wallet}/**`
- Migratsiyalar: `20260913_0031_platform_idempotency_outbox.py`, `20260913_0036_wallet_commission_policies.py` (FK `service_corridors` — A2 0034), `20260913_0041_wallet_ledger.py`

**Kontraktlar:** `money` (`commission_minor`, `validate_policy_terms`, `initial_commission_status`, `balance_check_required`, `validate_reversal`, `hold_adjustment_minor`, legacy konvertatsiya), `enums`, `idempotency`, `events` (allowlist), `errors` (`REVERSAL_EXCEEDS_CAPTURED` va b.), `ids`, `dto`, `state_machines.COMMISSION/TOPUP`, `crypto` (kerak bo‘lsa).

**Talablar:**
- `available = posted − held`; production’da manfiy available yo‘q; non-prod `test_overdraft_allowed` faqat seed (Q1).
- **N1 — DB darajasidagi invariantlar:** A3 `platform_environment` muhit markerini (deploy yozadi) va trigger’larni loyihalaydi: production markerida `test_overdraft_allowed=true` wallet va `wallet_required=false` flag qatori DB’da rad. Readiness uchun faqat holat qaytaradi (503 emas); pul buyruqlari invariant buzilganda rad etiladi + alert.
- **Q16:** komissiya holati/fee mijozga API’da ham, event’larda ham yo‘q — `enqueue_event` payload’ni `EVENT_PAYLOAD_ALLOWLIST`dan o‘tkazadi, auditoriya filtrini A7 `payload_for_audience` bilan qo‘llaydi.
- `exempt` faqat 0 bps snapshot’dan; `wallet_required` fee’ni nolga tushirmaydi.
- Policy: standard > 0 bps; kampaniya muddatli; overlap exclusion; orqaga sana taqiq; resolve tartibi; yaratish/tugatish faqat super_admin, operator/admin o‘qish (Q2).
- Hold: `UNIQUE(booking_id, charge_kind)`; amendment `adjust_hold` (D10).
- Capture va release bitta tranzaksiyada; takror capture no-op.
- Reversal: bir nechta qisman, wallet lock ostida yig‘indi ≤ captured (D4).
- Ledger immutable, balans deferred trigger; top-up reference unique.
- **Q17:** top-up tasdiqlash `finance.topup_approve`, `finalize_fee` `finance.fee_finalize`, chegaradan katta top-up/tuzatish ikkinchi, **boshqa** xodimning `finance.adjustment_approve` tasdig‘i (W16, `SECOND_APPROVER_REQUIRED`); `finance` roli ulanguncha super_admin (kontrakt xaritasi shunday).
- Idempotency: ADR-0005 savepoint naqshi; domen 4xx replay domen o‘zgarishisiz.
- Legacy `system_fee` ledger’ga tushmaydi.
- v1 adapter: GET o‘zgarishsiz; PATCH super_admin (admin → 403), 0% → 400.

**AC:** AC08/AC09 (kutubxona), AC19, AC20, AC23, AC24, AC25, AC43, AC33 (outbox yozuvi).

**Testlar (asosan PG, `ELCHI_TEST_PG_REQUIRED=1`):** parallel hold’lar (AC19); parallel capture (AC20); parallel approve bir reference (AC23); balanslanmagan posting rollback, immutable trigger (AC25); ikki qisman reversal + ortig‘i rad (D4); amendment `adjust_hold` parallel accept bilan (D10); policy overlap, standard 0 bps rad, muddatsiz kampaniya rad; idempotency: parallel bir kalit, farqli body 409, **domen 4xx replay domen yozuvisiz** (D8); outbox rollback’da yo‘qoladi; production invariant tekshiruvi. UT/SQLite: resolve tartibi, konvertatsiya, v1 adapter javob shakli va rollari.

**Doiradan tashqari:** booking/accept orkestratsiyasi (A4), outbox dispatch (A7), karta/yechish, UI (A9), legacy view (A10b).

**BR checklist:**
- [ ] 100 000 → hold 60 000 → available 40 000; 50 000 rad (AC19).
- [ ] 0% faqat muddatli kampaniya; `wallet_required` fee’ni nolga tushirmaydi (Q1).
- [ ] Policy’ni faqat super_admin o‘zgartiradi; v1 PATCH ham (Q2).
- [ ] Skrinshot pul emas (AC24); reference ikkinchi kredit bermaydi (AC23).
- [ ] Capture takrori bitta debit (AC20); bitta hold (D10).
- [ ] Reversal yig‘indisi ≤ captured, bir nechta qisman mumkin (D4).
- [ ] Ledger yozuvi o‘zgarmaydi (AC25).
- [ ] Domen 4xx replay domen o‘zgarishisiz (D8).
- [ ] Legacy fee qarz qilinmaydi (§18.2).

---

## A10a — DevOps: PostGIS/Redis/worker compose, Postgres migratsiya rejasi, UZ hosting runbook

**Maqsad:** host-agnostic pilot topologiyasi va xavfsiz ko‘chirish rejasi; production’ga hech narsa qo‘llanmaydi.
**Spec:** §1, §17.7, §19.1–19.2, §21 A10; ADR-0011, 0012, 0013, 0018.

**Fayl egaligi:**
- `docker-compose.prod.yml` (H0 o‘zgarishlari topshirilgach), `Dockerfile`, `Caddyfile`, `scripts/deploy.sh`, `scripts/backup.sh`, `scripts/server_bootstrap.sh`, `scripts/restore_drill.sh` (yangi)
- `app/worker/__init__.py`, `app/worker/__main__.py` — skelet (wave 3’dan A7)
- `app/api/health_probes.py` — `/health/live`, `/health/ready`; ulash integrator orqali. **Readiness semantikasi (BR N1):** 503 **faqat** DB yetib bo‘lmasa yoki DB migration head kod head’iga mos kelmasa; Redis yo‘q → 200 `degraded`; `wallet.production_invariants_status()` (A3) `fail` bo‘lsa → `checks.production_invariants: "fail"` + alert, 503 emas
- `docs/ops/**`: `UZ_HOSTING_RUNBOOK.md`, `POSTGRES_POSTGIS_MIGRATION.md`, `BACKUP_RESTORE.md`, `EXTERNAL_DATA_FLOWS.md`, `SECRET_ROTATION.md`
- Migratsiya: `20260913_0030_platform_extensions.py` — integrator tanasini yozgan: **`CREATE EXTENSION IF NOT EXISTS postgis;`** va **`CREATE EXTENSION IF NOT EXISTS btree_gist;`** (PostgreSQL bo‘lmasa no-op), downgrade extension’ni o‘chirmaydi. A10a egasi sifatida ko‘rib chiqadi va prod image shartini (ADR-0013) ta’minlaydi
- `tests/pg/ops/**` (A0b infra ustida)

**Talablar:**
- Compose: `api`, `worker` (bir image), `db` (PostGIS’li Debian, PG 16; A0b test image `postgis/postgis:16-3.5` bilan bir xil major/minor tavsiya, prod tag/digest A10a tekshirib pin qiladi), `redis` (tashqariga yopiq), `caddy`; migratsiya bir martalik job.
- Test Redis `127.0.0.1:36379` va test PG `127.0.0.1:45432` (Q76) — A0b’niki; prod compose ular bilan port to‘qnashmaydi va ularni ishlatmaydi.
- Postgres ko‘chirish: logical dump/restore, collation hujjatlangan, `amcheck`, qator soni; eski volume rollback uchun; `0030` image almashmaguncha prod’ga chiqmaydi.
- Prod `SHOW timezone` tekshiruv buyrug‘i (ADR-0004; bajarish foydalanuvchi ruxsati bilan).
- Backup: kundalik + WAL/PITR varianti, off-box, O‘zbekiston ichida; restore drill; RPO/RTO faqat drill bilan.
- UZ hosting runbook, tashqi ma’lumot oqimlari, secret rotatsiyasi barcha subkey’larga ta’siri (ADR-0018).
- Rollback: flag + forward-fix + restore; downgrade emas.
- `redis` Python client — aniq versiya bilan, A0b bilan kelishib.

**AC:** AC34 (infra), AC40 (runbook + drill skripti).

**Testlar:** PG (`ELCHI_TEST_PG_REQUIRED=1`): `0030` toza `elchi_test`da va takror no-op; `/health/ready` DB yo‘q → 503, migration head nomuvofiq → 503, Redis yo‘q → 200 `degraded`, invariant buzilishi → `production_invariants: fail` va 503 emas (N1). `docker compose config` lokal; smoke bajarilgan/bajarilmagani aniq.

**Doiradan tashqari:** production’ga ulanish/deploy, hosting xaridi, legacy view (A10b), outbox consumer’lari (A7), upload (H0), test infra fayllari (A0b).

**BR checklist:**
- [ ] DB/Redis internetga yopiq; secret’lar git/image’da yo‘q.
- [ ] API va worker bir image; migratsiya bir martalik job.
- [ ] Redis o‘chishi bron/pulni yo‘qotmaydi; readiness degradatsiyani ko‘rsatadi (AC34).
- [ ] `0030` `IF NOT EXISTS` bilan, takror no-op.
- [ ] Collation xavfi dump/restore bilan yopilgan (ADR-0013).
- [ ] Backup O‘zbekistonda, boshqa nosozlik domenida; RPO/RTO drill bilan (K3, §19.2).
- [ ] Rollback downgrade emas (§18.3).
- [ ] Readiness 503 faqat DB/migration head uchun; invariant buzilishi `fail` + alert (N1).

---

## Keyingi wave’lar uchun qayd etilgan topshiriqlar (kartalar keyin to‘ldiriladi)
| Egasi | Wave | Band |
|---|---|---|
| A4 | 2 | **N4:** `bookings.service.blocking_state_for_user(user_id)` (faol v2 bronlar, ochiq nizolar soni) — read-only; v1 akkaunt o‘chirishga ulash H1/integrator. **N5:** proof kod tekshiruvi `crypto.build_keyring` + `verify_proof_code`. **N3:** `reject_no_show` trip terminal bo‘lsa bir buyruqda bekor + `fault_side=driver` (`reject_no_show_outcome`). **Q19:** listing reopen oynasi va mijozga xabar; pending no-show review davomida faqat operator bekor qiladi |
| A4 / A12 | 2 / 3 | **Q15:** v1 `block_driver` faol v2 trip’li haydovchi uchun v2 eligibility bloki sifatida (faol trip, GPS, support davom); to‘liq favqulodda blok faqat super_admin |
| A7 | 3 | **N2:** har yetkazishda `events.payload_for_audience` (`EVENT_AUDIENCES`, `CLIENT_REDACTED_PAYLOAD_KEYS`, `commission` machine mijozga yo‘q); `GET /api/v2/events` ham |
| A12 | 3 | Staff MFA rejasi (Q8); v2 `DELETE /me` A3/A4 blocking state bilan |
| A9 / A13 | 4 | **Q14:** majburiy `paid_manual` buyurtmalar moliyaviy hisobotda “tasdiqlanmagan”; **Q17:** finance roli UI (top-up navbati, W16 ikkinchi tasdiq) |
| A8 | 4 | **Q16:** mijoz UI’sida komissiya holati yo‘q |

---

## Wave 1 yakuni: integratsiya (o‘tishlar 1+2, 14.09.2026)

### Integrator bajargan ishlar
- `/api/v2`: `app/api/v2/router.py` (identity, geo, trips, marketplace, wallet — qo‘shimcha prefikssiz), `app/api/v2/__init__.py` (yengil, `api_router` lazy), `app/main.py` include + `/health/live`, `/health/ready`.
- **Yagona v2 DomainError handler:** A1 ning `identity/web.py` umumiy plumbing’i mexanik ravishda `app/api/v2/web.py`ga ko‘chirildi; `identity/web.py` — barcha nomlarni qayta eksport qiluvchi shim. `app.main` handler’ni faqat `/api/v2` yo‘llariga qo‘llaydi; boshqa joyda `DomainError` → v1 uslubidagi `500 SERVER_ERROR` (v1 xato ishlovi o‘zgarmagan).
- Modellar: `app/modules/__init__.py::import_models` (barcha wave 1 modullari), `alembic/env.py` va `app.main` chaqiradi.
- Portlar: A1 adapterlari (`trips.adapters.GeoServiceAdapter`, `marketplace.adapters.default_marketplace_ports` → `FlagServiceAdapter`, `WalletFeeAdapter`) `configure_v2_ports()` orqali ulandi.
- Legacy `User.public_id` e’lon qilindi; A1 metadata patch’i olib tashlandi; ORM drift testi o‘tadi.
- N4: v1 akkaunt o‘chirish `wallet.service.blocking_state_for_user`ni H1 lock’laridan keyin chaqiradi (`409 WALLET_BALANCE_EXISTS`, `details=as_details()`).
- Sozlamalar: `settings.redis_url`; `.env.example` / `.env.production.example` (Redis, PITR, domen, data residency, `ELCHI_GEO_*`).

### Kartalardan chetlanishlar (qayd)
| # | Egasi | Chetlanish | Baho |
|---|---|---|---|
| W1 | A2 | Geo sozlamalari `app/modules/geo/config.py`da (`ELCHI_GEO_*`), `app/core/config.py`da emas | Qabul; env namunalarga qo‘shildi |
| W2 | A2 | `app/modules/geo/adapters.py` A1 adapterlari bilan bir xil portlarni amalga oshiradi; fee adapteri yo‘q | A1 adapterlari tanlandi; A2 fayli ishlatilmaydi — keyingi A2 o‘tishida olib tashlash yoki qoldirish |
| W3 | A3 | Wallet router o‘z envelope va idempotent helper’larini ishlatadi (umumiy `app/api/v2/web.py` emas) | Mos; konflikt yo‘q; keyin unifikatsiya ixtiyoriy |
| W4 | A3 | Qo‘shimcha `ledger_adjustment_requests` jadvali, W8 → `202`, W16 | DATA_MODEL §6.2, API W8/W16 ga yozildi |
| W5 | A3 | W9 cheklovlari: `legacy_calculated_fee` → 503 (wave 5), `corridor_id` filtri → 400 (wave 2) | API W9 ga yozildi |
| W6 | A3 | Ikki xodim chegarasi servis konstantasi `LARGE_AMOUNT_THRESHOLD_MINOR` | Qaror: pilotda kontrakt konstantasi `TWO_PERSON_APPROVAL_THRESHOLD_MINOR` (teng ekani test bilan tekshiriladi) |
| W7 | A1 | `publish/resume` — egasi `users` `FOR UPDATE`, `submit/counter` — `FOR SHARE` | §0.2 dan qat’iyroq, tartibga mos (STATE_MACHINES §0.2 qaydi) |
| W8 | A1 | Material listing tahriri **barcha** ochiq takliflarni expire qiladi | §5.4 matnidan qat’iyroq — BR/foydalanuvchi uchun nomuvofiqlik (STATE_MACHINES §1 qaydi) |
| W9 | A1 | Boshqaning listing’ini bekor qilish `ops.booking_command` (operator+) | API L7 ga qaror sifatida yozildi; spec §16 ga zid emas |
| W10 | A1 | v2 handler header bo‘lmasa `request_id` qaytarmaydi | ADR-0005 ga qayd; request-id middleware keyin |
| W11 | Koordinator | DATA_MODEL §5 0034–0036 tartibi eski deb xabar qilindi | Tekshirildi: reyestr allaqachon to‘g‘ri edi; faqat 0031/0041 mazmuni yangilandi |

### Keyingi ishlar (egalarga)
| Egasi | Band |
|---|---|
| A3 | `wallet.service` da policy by-id getter (A1 `WalletFeeAdapter.policy_refs` hozir `CommissionPolicy`ni bevosita o‘qiydi); `LARGE_AMOUNT_THRESHOLD_MINOR`ni kontraktdan import qilish |
| A1 (keyingi o‘tish) yoki A4 | `ProposalCreate.parcel {weight_g, length_cm, width_cm, height_cm, volume_ml?}` (API P1 qo‘shimchasi) va accept’da cargo tekshiruvi; `proposal.rejected` eventini `reject`da chiqarish (kontraktda qo‘shildi) |
| A2 | `geo/adapters.py` taqdiri (W2) |
| A4 | N4 booking blocking state’ni v1 o‘chirishga qo‘shish (wallet qismi ulangan) |
| A10a / A13 | Request-id middleware (ADR-0005) |
| BR / foydalanuvchi | ~~W8 qarori~~ — **Q20 bilan hal qilindi** |

---

## Wave 1.5 — BR tuzatishlari (Q20–Q39, 14.09.2026)
Migratsiyalar: A3 `20260914_0042`, A2 `20260914_0043`, A1 `20260914_0044` (stub’lar tayyor). Wave 1 migratsiyalari o‘zgarmaydi. A4 raqamlari 0048 dan (wave 1.6 dan keyin).

| Egasi | Tuzatish / qaror | Manba |
|---|---|---|
| A1 | Listing tahriri faqat yo‘nalish/oyna/miqdor/`price_basis` o‘zgarsa takliflarni expire qiladi | Q20 |
| A1 | Eligible bo‘lmagan haydovchi trip_offer’iga mijoz taklifi `DRIVER_NOT_ELIGIBLE` | Q21 |
| A1 | Faol driver wallet ko‘rish/top-up capability’si tasdiqdan oldin va blokda | Q22 |
| A1 | Operator listing cancel: `ops.booking_command` + audit; `draft` emas | Q23 |
| A1 | `users` lock’lari `FOR NO KEY UPDATE` / `FOR SHARE`; `run_with_db_retry` | ADR-0017 §10, §5 |
| A1 | 0044: `proposal_versions` talab ustunlari, yakuniy versiya immutability, `lift_reason`, ixtiyoriy `users.role` Q3 trigger | BR |
| A2 | Hosted router production’da o‘chiq; geometriya saqlash provider shartlariga bog‘liq | Q24 |
| A2 | Bir leg’da ikki detour rad; `DetourQuote` snapshot; detour soniyada | Q25, kontrakt |
| A2 | Ziddiyatli flag qatorlari → o‘chiq | Q26 |
| A2 | Koridor `pilot`ga: bekatlarda meeting note/foto dalil | Q27 |
| A2 | 0043: passenger/card flag approval DB guard, production’da `fixture` route rad; production aniqlash `platform.service.is_production(db)` | BR |
| A3 | Seed stavka go-live gate (`COMMISSION_POLICY_UNCONFIRMED`) | Q28 |
| A3 | Kichik tuzatish bo‘linishi hisobotda belgilanadi | Q30 |
| A3 | O‘chirilgan haydovchi balansini debit adjustment bilan qaytarish (runbook) | Q31 |
| A3 | W17 reject, W18 list; `ledger_adjustment_requests` lock ro‘yxatida | BR |
| A3 | 0042: `platform_environment` TRUNCATE guard, fail-closed marker, ixtiyoriy running balance; `0041` docstring’idagi “A4 in 0042” eslatmasini yangilash | BR |
| A10a | Pre-deploy legacy stavka tekshiruvi | Q29 |
| A10a | Readiness `migrations: ahead` → 200 `degraded`; orqada/noma’lum → 503 | Q32 |
| A10a | Caddy: `/health/ready` monitoring IP’lariga | Q33 |
| A10a | PostGIS image Debian bookworm/trixie, PG ≥ 16.15, digest pin (prod+test, test compose A0b bilan) | Q34 |
| A10a | Production WAL/PITR yo‘q, kundalik shifrlangan dump, RPO ≤ 24 soat | Q35 |
| A10a | Migration/owner va NOSUPERUSER app DB rollari (texnik oyna) | Q36 |
| A10a | Go-live checklist: Q28 stavka tasdig‘i; o‘chirish/moliya runbook’i: Q31 | Q28, Q31 |
| H1 | Faol nizoda v1 admin cancel bloklangan (resolve-then-cancel ish tartibi hujjati) | Q37 |
| H1 | v1 operator nizoda faqat izohli `under_review`; resolve/reject admin+ | Q38 |
| H1 | Review allowlist’dan telefon olib tashlash tartibi (buyurtmalar avval yopiladi) | Q39 |
| A0a (bajarildi) | `ELCHI_ENVIRONMENT` allowlist validatsiyasi (`app/core/config.py`) | BR |
| A4 (wave 2) | Release kontrakti: `booking_allocations.active` true→false o‘tishida `release` | ADR-0017 §11 |

---

## Wave 1.5 yakuni: integratsiya (15.09.2026)

### Qarorlar va qaydlar
- **W17:** so‘rovchi o‘z `pending` adjustment so‘rovini faqat **withdraw** qiladi (`withdrawn` yoki `rejected` + `reason=withdrawn_by_requester`); **reject** — `finance.adjustment_approve` va so‘rovchidan boshqa xodim. Hozirgi A3 kodi reject uchun `finance.adjustment_approve` talab qiladi (qarorga mos); withdraw endpoint/holati — A3 keyingi ishi.
- **BookingWindow/TimelineChange** kontraktga ko‘tarilmaydi (geo `OccurrenceTiming`ga bog‘langan); A4 `app.modules.geo.types`dan foydalanadi. `DetourQuote` kontrakti geo’da subclass bilan kengaytirilgan (`stop_id`, `arrive_offset_s`, `provider`, `provider_version`) — mos.
- **Q24 implementatsiyasi (A2):** production’da routing provayderi umuman yo‘q; yoqish — ADR + kod.
- **Koridor ≥ 2 faol bekat (A2):** `pilot`/`active` uchun implementatsiya qoidasi (§6.6 ga mos), foydalanuvchi o‘zgartirishi mumkin.
- **A1 `app/api/v2/web.py` o‘zgarishi** (`run_command`/`run_versioned` → `run_with_db_retry`, har urinishda commit) ko‘rib chiqildi va qabul qilindi.
- **Lock rejimi:** `trips`, `listings`, `proposal_threads` ham `FOR NO KEY UPDATE` (ADR-0017 §12); v1 tartibi `orders → users → driver_profiles → wallet`, refresh `FOR KEY SHARE` (§13).
- **A10a wiring (integrator, bajarildi):** `alembic/env.py` — `ELCHI_MIGRATION_DATABASE_URL` (Q36 migrator roli) bo‘lsa shu, aks holda `settings.database_url` (online va offline); PostgreSQL’da `pg_advisory_lock(0x656C6368696D6967)` configure’dan oldin, `finally`da unlock (BR #21). `app/main.py` — `RequestIdMiddleware` oxirgi (eng tashqi) middleware; `app/api/deps.py::get_current_user` → `bind_actor_id(user.id)` (v2 `current_user_id`/`optional_user_id` shu dependency orqali). `app/core/config.py` — `previous_secret_keys`, `proof_code_key`, `cursor_signing_key`, `proof_code_keyring()`, `cursor_signing_secret()` (v2 cursor’lari ulangan; ADR-0018).
- **A10a implementatsiyasi (hujjatlandi):** Q34 lokal `docker/postgis/Dockerfile`, test stack prod bilan bir xil image/initdb; prod image registry digest’i yo‘q (launch gate G4); Q36 og‘ishi — extension’lar superuser egaligida, `elchi_owner` migratsiya qiladi (ADR-0013); Q32 cheklovi — eskiroq image’ga rollback `unknown`/503; readiness `database: busy`, `migrations: ahead`; `requirements-dev.txt` ajratildi. UZ launch gate foydalanuvchi harakatlari — COVERAGE_MATRIX §6.
- **Q39 tartibi (H1):** telefonni review allowlist’dan olib tashlashdan oldin `python scripts/check_review_account_orders.py` ishga tushiriladi (ochiq buyurtma/bid bo‘lsa exit 1); ularni yopib, exit 0 bo‘lguncha qayta ishga tushirish; shundan keyingina `ELCHI_REVIEW_LOGIN_PHONES`dan telefon olib tashlanadi.

### Kesishgan keyingi ishlar
| Egasi | Band |
|---|---|
| A3 | Marker guard: passenger/card flag qatorlari `approval_reference`siz yoqilgan bo‘lsa production’ga o‘tishni rad etish |
| A3 | Read-only idempotency lookup funksiyasi |
| A3 | W17 withdraw (so‘rovchi) holati/endpointi |
| A3 | `0041` docstring’idagi “A4 in 0042” eslatmasini yangilash |
| A4 | `hold_fee`ga `fee_policy_id` uzatish; `finalize_fee`da `finance.fee_finalize`; `geo.service.set_active_booking_counter` ro‘yxatdan o‘tkazish; accept’da `validate_detour_quotes` + `verify_existing_windows` + `apply_insertions` (seq_map) va trip versiyasini oshirish |
| A1 | Detour oqimlarida `TripRouteContext.route_version_public_id` uzatish; `…_0045` `trips.detour_used_s` migratsiyasi (A2 so‘rovi) |
| A3 | `wallet/api.py` cursor kaliti → `app.core.config.cursor_signing_secret()` |
| A4 | Proof kodlar `app.core.config.proof_code_keyring()` + `verify_proof_code` bilan |
| A1 + A10a | JWT keyring (`kid`, previous master’lar `refresh_token_expire_days` davomida), `otp_hash` previous master’lar — ADR-0018 ochiq bandi, v1 xulqi sababli alohida karta |

---

## Wave 1.6 (14.09.2026, Q40–Q51 tasdiqlangan)

Migratsiyalar: A1 `20260914_0045`, A2 `20260914_0046`, A3 `20260914_0047`; A4 — `…_0048` dan. Kontraktlar (A0a): `app/contracts/contact_filter.py` (`scan`, `mask`, `CONTACT_FILTER_VERSION`), `ErrorCode.PRICE_OUT_OF_BAND` (400), `WarningCode.CONTACT_INFO_MASKED` + `dto.ApiWarning`/`Envelope.warnings`, event’lar `trust.contact_filter.hit` / `trust.contact_strike.recorded` (faqat staff, matnsiz), API §7 P9 + R1/R2 qoidalari, §8 telefon ochilishi.

| Egasi | Wave 1.6 ishi | Manba |
|---|---|---|
| A1 | P9 `GET /listings/{id}/offers` + `OpenOfferViewDTO` (anonim yorliq `listing_offer_labels`, faqat joriy versiyalar); accept’dan oldingi DTO’larda kontakt yo‘q (`ProposalThreadDTO`, `ListingPublicDTO.owner_display_name`, `TripPublicDTO` → `vehicle_class`+`seat_capacity`); listing/proposal/parcel matnlarida `contact_filter.scan` + `warnings` + `trust.contact_filter.hit`; `PRICE_OUT_OF_BAND` tekshiruvi (A2 band’i); `trips.detour_used_s`, `listings.terms_version` (0045); detour oqimlarida `route_version_public_id` | Q40–Q43, BR |
| A2 | `corridor_price_bands` konfiguratsiyasi + audit + admin API (0046); Q47 uzluksiz bekat guard’lari; Q46 (detour yo‘qligi) geo javoblari/hujjatda | Q42, Q46, Q47 |
| A3 | `pg_trigger_depth` balans guard’i, `pg_temp` search_path, backfill lock tuzatishi, adjustment `withdrawn` + reject faqat boshqa xodim (0047); marker guard (passenger/card flag approval’siz production’ga o‘tish rad) | Q48, Q49 |
| H1 | Wave 1.5 qayta ko‘rib chiqish topilmalari | BR |
| A10a | Q50 lineage dizayni (A0a bilan), Q51 UZ private registry + digest; `SECRET_ROTATION.md:65` ga Q39 buyurtma yopish tekshiruvi (BR H1 N-E) | Q50, Q51 |
| A4 (wave 2) | BookingDTO `contact` bloki va telefon ochilish/yashirish qoidalari (Q44), parcel qabul qiluvchi telefoni pickup’dan keyin; accept’da `listing_terms_version` va narx diapazoni snapshot’i | Q44 |
| A7 (wave 3) | Chat + tezkor javoblar + filtr; raqobatchi driver auditoriyasi (ADR-0019 §9) | Q43, Q44 |
| A12 (wave 3) | Ogohlantirish → strike → operator navbati, aylanib o‘tish signallari, profil/reyting matni filtri, rasmlar tanlab tekshiruvi | Q45 |
| A0a | Q50 reyestr raqami; kontrakt yangilanishlari | Q50 |

### Wave 1.6 yakuniy integratsiya — 1-qism (A1, A3, H1, A10a tugatdi; A2 ishlamoqda)
- **Kontrakt (additiv):** `enums.VehicleClass` (car|minivan|minibus) + `vehicle_class_for_seat_capacity` (A1 `trips.rules.vehicle_class` bilan bir xil, test bilan); `enums.LedgerAdjustmentStatus` + `LEDGER_ADJUSTMENT_TERMINAL`. Kontrakt testi `tests/contracts/test_wave16_r2_dtos.py`: `ListingOfferDTO`, `TripPublicDTO`, `ListingPublicDTO`, `ProposalPartyDTO` accept’dan oldin identifikatsiya maydonisiz.
- **API:** P9 `ListingOfferDTO` (A1 shakli, modul egaligida), ataylab qoldirilgan identifikatsiya maydonlari ro‘yxati, parcel sender/receiver maydonlari filtrdan tashqarida (qaror, Q43 ga mos), W17a withdraw, W18 `withdrawn`, `pending_age_seconds`, A3 servis qaydlari.
- **ADR-0017 §13** (H1 v1 lock rejimlari), **ADR-0016** (extension egaligi, `--update-extensions`, deploy’dan keyin db-roles), **COVERAGE §6** (A10a gate’lari).
- **Ochiq band (part 2):** A1 `warnings` DTO maydoni → `Envelope.warnings` (`web.py` runner o‘zgarishi).

### Wave 1.6 yakuniy integratsiya — 2-qism: bajarildi
- **Envelope.warnings:** `app/api/v2/web.py` — `to_api_warnings`, `split_handler_result`; `run_command` handler’i DTO yoki `(dto, warnings)` qaytaradi, ogohlantirishlar idempotency yozuvi bilan saqlanadi va replay’da qaytadi (PG test `tests/pg/test_v2_envelope_warnings.py`). A1 marketplace handler’lari (`create/patch/cancel listing`, `submit/counter proposal`) `Envelope.warnings` orqali; `ListingDTO.warnings`, `ProposalThreadDTO.warnings`, `TextWarningDTO` olib tashlandi. Geo/wallet handler’lari o‘zgarmagan (oddiy DTO).
- **`stop_photo` upload turi:** `app/utils/file_validation.py` (`ALLOWED_UPLOAD_TYPES`, `IMAGE_ONLY_TYPES`, `STOP_PHOTO_UPLOAD_TYPE`); `app/api/v1/files.py` — faqat `ops.corridor_manage`li staff, boshqalarga v1 `403 FORBIDDEN`; mavjud turlar o‘zgarmagan. Testlar `tests/test_files_stop_photo.py` (admin yuklab `resolve_attachment` va geo `_resolve_meeting_photo` bilan biriktiradi; client/driver/operator 403). A2 PG testi “upload turi yo‘q” o‘rniga “fayl yo‘q → `invalid_file_reference`”ga yangilandi.
- **Worker:** `app.worker.every`, `register_default_tasks` — `routing_cache_cleanup_task` soatiga bir marta; faqat uzoq ishlaydigan `python -m app.worker`da (`--once` smoke tekshiruvi vazifasiz qoladi). A7 keyinroq scheduling egasi.
- **Hujjatlar:** API G12–G14 + A2 DTO’lari, Q46/Q47, `meeting_photo_url`; DATA_MODEL 0046 yakuniy trigger’lari; STATE_MACHINES Q47 sabablari.
- **Ochiq:** narx band’ini operator ham tahrirlay oladimi (foydalanuvchi qarori; hozir admin+). `vehicle_class` geo javoblarida yo‘q (tekshirildi).

### Wave 1.6 yakuniy integratsiya — 2-qism rejasi (tarix)
1. `app/api/v2/web.py`: `run_command`/`run_versioned` handler natijasini `(dto, warnings)` sifatida qabul qilib `Envelope.warnings`ga yozish (`envelope_body(..., warnings=)` tayyor); idempotent replay ogohlantirishlarni ham qaytarishi; A1 `TextWarningDTO` → `ApiWarning` moslash (A1 bilan kelishib, DTO maydoni deprecated).
2. A2 hisoboti bo‘yicha kontrakt/hujjat: `corridor_price_bands` admin API (endpoint jadvali), Q46 geo javoblari, Q47 guard xatolari, 0046 yakuniy ustunlari DATA_MODEL’da; A2 migratsiya sarlavhalaridagi “(STUB)” (0043, 0046).
3. `vehicle_class` A2 geo/matching javoblarida ishlatilsa — `enums.VehicleClass`ga moslash.
4. Tekshiruv: `tests/contracts`, to‘liq suite (PG bilan), `scripts/test-pg.ps1`, `alembic heads` + toza DB’da ikki marta upgrade, drift testi (geometry), v1 OpenAPI 93 o‘zgarmagan + v2 soni.

---

## WAVE 2 — A4 booking orkestratori (yagona nazorat ro‘yxati, 15.09.2026)

**Maqsad:** proposal accept → booking, sig‘im/pul/holat o‘zgartiradigan yagona tranzaksiyalar (accept, cancel, amend, no-show, custody, trip completion). AGENTS §4: pul/o‘rin/holat o‘zgarishi faqat A4 orkestratorida. Spec §5.3, §7, §9, §16; AC02–AC09, AC13 (qayta tekshiruv), AC17, AC20–AC22, AC26, AC41–AC43.

**Egalik:** `app/modules/bookings/**`, `tests/pg/bookings/**`, `tests/modules/bookings/**`; migratsiyalar `20260915_0048` (bookings core), `0049` (proofs), `0050` (no-show/custody), `0051` (cash/amendments) — stub’lar tayyor, faqat `upgrade()`ni to‘ldiradi. API: §7 P8, §8 B1–B13 (API_V2_CONTRACT). Boshqa modul jadvaliga yozmaydi — faqat ularning `service.py` funksiyalari.

### 1. Accept (P8) — tekshiruvlar va tartib
1. **Lock tartibi (ADR-0017):** `users → trips → listings → proposal_threads → bookings → booking bolalari → wallet_accounts → wallet_holds`; har guruhda id o‘sish tartibida. Rejim: `FOR NO KEY UPDATE` (`with_for_update(key_share=True)`); `FOR UPDATE` faqat unique ustun o‘zgarsa. Bola id bilan kelgan buyruq avval lock’siz o‘qib ota id’larini topadi, lock oladi va qayta tekshiradi. Butun buyruq `run_command` → `run_with_db_retry` ichida (≤3).
2. **Q21 eligibility** — `users` lock’i ostida qayta tekshiruv (`identity_service.get_capabilities`, `DRIVER_NOT_ELIGIBLE`).
3. **Q54 versiya:** `proposal_versions.listing_terms_version == listings.terms_version` (`listings.version` emas); body `expected_listing_version` = `expected_listing_terms_version` alias → aks holda `409 PROPOSAL_CHANGED`. Proposal versiya joriy va `expires_at > now` (`PROPOSAL_EXPIRED`, AC43 — fee quote u bilan tugaydi).
4. **Trip solishtirish:** xom `trip.version` emas — `route_version_id` + occurrence `seq` + `planned_arrival_at` snapshot’i mos; trip `status = planned`, `booking_cutoff_at > now` (`BOOKING_CUTOFF_PASSED`, `ROUTE_CHANGED`).
5. **Rezerv:** `marketplace_service.version_demand(version)` (o‘rin, bagaj `_ml`, cargo `_g`/`_ml`, parcel o‘lchamlari) → trips resurs rezervi (`CAPACITY_UNAVAILABLE`, `CARGO_LIMIT_EXCEEDED`, AC07/AC10/AC12). Q53: band accept’da **tekshirilmaydi**.
6. **Detour (AC17, Q25):** `geo.matching.validate_detour_quotes` (409 `ROUTE_CHANGED` reason bilan), `verify_existing_windows` (409 `TIME_WINDOW_CONFLICT`), `apply_insertions` (seq remap — `TimelineChange.seq_map` bilan allocation/occurrence’larni qayta raqamlash), `trips.detour_used_s` yangilash (`DETOUR_LIMIT_EXCEEDED`), tugash vaqti uzaysa **AC13 overlap qayta tekshiruvi** (`SCHEDULE_CONFLICT`), keyin trip versiyasini oshirish. Q46: production’da provayder yo‘q → quote’lar bo‘lmaydi; `TripRouteContext.route_version_public_id` har doim uzatiladi.
7. **Pul:** snapshot `fee_policy_id`, `fee_bps`, `commission_minor` (`money.commission_minor`). 0 bps → `initial_commission_status = exempt`, **`hold_fee` chaqirilmaydi**. Aks holda `wallet_service.hold_fee(..., fee_policy_id=...)` (production’da majburiy; Q28 → `503 COMMISSION_POLICY_UNCONFIRMED`; `INSUFFICIENT_COMMISSION_BALANCE`, AC19). Q48/Q56: gate o‘tmagan production’da v2 flag’lari o‘chiq.
8. **Release kontrakti:** `booking_allocations.active` true→false faqat trip lock ostida va `trips.release` faqat shu o‘tishda (cancel, `confirm_no_show`, trip-terminal `reject_no_show`, amendment) — ikki marta release yo‘q.
9. Thread `accepted`, raqobatchi versiyalar/thread’lar expire (A1 funksiyalari), outbox `booking.accepted` + audience’lar.
10. **Deferred trigger xatolari** (balans, ledger balans, Q47, Q55) COMMIT’da chiqadi → `run_command` 500 envelope (domen 4xx emas) — testda kutilgan.

### 2. Keyingi buyruqlar
- **Proof kodlar:** `app.core.config.proof_code_keyring()` + `crypto.derive_proof_code`/`verify_proof_code` (48 soat oldingi kalit, N5); `booking_proofs` (hash), urinishlar → `PROOF_ATTEMPTS_EXCEEDED`.
- **Q7 no-show:** driver faqat xabar beradi (`awaiting_pickup` + pending review); `confirm_no_show`/`reject_no_show` — operator (`OPERATOR_COMMAND_CAPABILITY`); pending review davomida faqat operator bekor qiladi (Q19, `NO_SHOW_REVIEW_PENDING`).
- **AC22 custody:** parcel custody’da oddiy cancel yo‘q (`CUSTODY_REQUIRES_RETURN_FLOW`), `custody_cases`.
- **AC42 trip completion:** `booking_blocks_trip_completion` (state_machines) → `TRIP_HAS_UNRESOLVED_BOOKINGS` `details.bookings[]`; ochiq nizo xizmat yakunini to‘xtatmaydi, faqat capture kechiktiriladi.
- **Cash receipts** (`cash_receipts`) va **amendments** (D9/D10: fee snapshot bps saqlanadi, `adjust_hold`, `hold_adjustment_minor`).
- **Komissiya:** `wallet_service.capture_fee`/`release_fee`; operator B13 `finalize_fee` buyrug‘i (`OperatorBookingCommand.FINALIZE_FEE`) → `finance.fee_finalize` (Q17) tekshiruvidan keyin shu funksiyalarni chaqiradi (alohida `finalize_fee` servis funksiyasi yo‘q); `reverse_fee(..., actor_capabilities)` — HTTP orqali reversal faqat adjustment so‘rovlari (W8/W16).
- **`geo_service.set_active_booking_counter`** ro‘yxatdan o‘tkazish (koridor yopish/qaytarish faol bronlarni ko‘radi; `bookings` bor, hook yo‘q → 503).
- **Stops-change guard (A1 N6):** A4 read funksiyasi (masalan `bookings.service.trip_has_active_allocations(trip_id)`); A1 trip marshruti/bekat tahririda keyin chaqiradi.
- **N4 (v1 akkaunt o‘chirish):** A4 read-only `blocking_bookings_for_user(user_id)`; H1/integrator keyin ulaydi.
- **Q15 (v1 `block_driver`):** A4 funksiyasi faol v2 trip’li driver uchun faqat yangi biznesni bloklash natijasini beradi; ulash keyin.

### 3. DTO va event’lar
- **Q44 telefon ochilishi** (API §8 `BookingDTO.contact`): accept → start oralig‘ida telefonlar `null`; start (passenger `onboard`, parcel `picked_up`) — ochiladi; terminaldan 24 soat keyin yashiriladi; parcel qabul qiluvchi telefoni driverga faqat `picked_up`dan keyin; jo‘natuvchi telefoni driverga hech qachon. `TripManifestDTO.contact_phone` shu qoidada.
- **Q16:** `commission_status` va fee maydonlari mijozga hech qachon (DTO va event); `events.payload_for_audience`, `EVENT_PAYLOAD_ALLOWLIST`.
- Kontakt filtri (Q43) booking erkin matnlarida (cancel izohi, amendment izohi) — `(dto, warnings)` qaytarish.

### 4. Testlar (PG, `ELCHI_TEST_PG_REQUIRED=1`, boshqa PG ishga tushirishlar bilan ustma-ust emas)
Concurrency (bir o‘rin uchun parallel accept, AC07), idempotent accept replay (AC06), Q54 terms_version, detour + AC13 qayta tekshiruv, release bir marta, exempt branch, Q28 503, deferred trigger → 500, Q7/AC22/AC42 oqimlari, Q44 DTO ko‘rinishi vaqt bo‘yicha, lock tartibi (deadlock yo‘q) — AC02–AC09, AC17, AC20–AC22, AC26, AC41–AC43.

---

## Wave 1.7 (15.09.2026) — kichik tuzatishlar

| Egasi | Ish | Manba |
|---|---|---|
| A1 | Q53 (segment/koridor band tartibi, counter narxi o‘zgarmasa tekshiruv yo‘q, accept’da yo‘q), `PRICE_OUT_OF_BAND` details `scope` bilan; Q54 `ListingDTO.terms_version` ochish; stops-change guard hook’i uchun joy (A4 read funksiyasi tayyor bo‘lgach) | Q53, Q54 |
| A2 | `20260915_0053` Q56 flag enable guard + DB trigger (A3 gate funksiyasini chaqiradi); `PRICE_OUT_OF_BAND` details shakliga moslash; 0043 sarlavhasidagi “(STUB)” | Q56 |
| A3 | `20260915_0052` Q55 ledger manba bog‘lanishlari + orphan reconciliation; Q56 gate funksiyasi (platform/wallet) va `production_invariants`ga qo‘shish; `wallet/api.py` cursor → `cursor_signing_secret()` | Q55, Q56 |
| H1 | Akkaunt o‘chirish ↔ v2 top-up tasdiqlash deadlock tahlilini PG concurrency testi bilan tasdiqlash | ADR-0017 §13 |
| A10a | Q57 readiness eslatmasi; Q58 `ELCHI_POSTGIS_IMAGE` tests/pg + restore drill; deploy `--v1-only` Q56 bilan; `POSTGRES_POSTGIS_MIGRATION.md` 21/28 qatorlari | Q56–Q58 |
| A0a | Q50 lineage reyestr raqami (dizayndan keyin); A4 kartasi yangilanishi | Q50 |

**Wave 1.7 holati: yetkazildi (15.09.2026)** — dalil va follow-up’lar COVERAGE_MATRIX “Wave 1.7 natijasi”da. Integratsiya: `WarningCode.CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR`, `PRICE_OUT_OF_BAND` `scope` (kontrakt), API G15/Q56/notices/gate CLI, DATA_MODEL 0052/0053, ADR-0017 §13, AGENTS §6 (Q55, Q56).

### Keyingi integratsiya o‘tishi — bookings (A4 hisobotidan keyin)
1. `app/api/v2/router.py`ga bookings router(lar)ini ulash; `configure_v2_ports()`da bookings portlari; `app/modules/__init__.py::WIRED_MODEL_MODULES`ga `bookings`.
2. `geo_service.set_active_booking_counter(...)` ro‘yxatdan o‘tkazish (ilova start’ida yoki `configure_v2_ports`).
3. v1 akkaunt o‘chirish: `account_deletion_service.py` A4 kiritish nuqtasiga `bookings.service.blocking_state_for_user(db, user.id, lock=True)` (lock tartibi `orders → users → driver_profiles → bookings → wallet_accounts`); Q15 `block_driver` funksiyasi; A1 stops-change guard’i (A4 read funksiyasi).
4. A4 hisobotidan kerak: aniq funksiya nomlari/signaturalari (yuqoridagi 2–3), yangi jadvallar (`test_models` ro‘yxati avtomatik, DATA_MODEL’da hujjatlash), yangi `ErrorCode`/`EventType`/DTO so‘rovlari, kontraktdan og‘ishlar, `no_show_reviews` PG-only server default’ining SQLite `create_all` bilan mosligi (SQLite suite xatosi), A3 PG testlari uchun bookings factory, migratsiya 0048–0051 yakuniy ro‘yxati, PG/unit test sonlari.
5. Tekshiruv (yolg‘iz): contracts, to‘liq suite (PG), `-m pg`, alembic heads + ikki marta upgrade, drift testi, v1 OpenAPI 93 o‘zgarmagan + v2 soni.

### Wave 2 integratsiyasi (bookings) — bajarildi
- `app/modules/__init__.py`: `app.modules.bookings.models` `WIRED_MODEL_MODULES`da (alembic metadata va drift testi ko‘radi).
- `app/api/v2/router.py`: `bookings_router` ulandi; `configure_v2_ports()` → `bookings.service.register_geo_hooks()` (`set_active_booking_counter` = `count_active_bookings_on_corridor`).
- `app/api/v2/web.py`: `run_command(..., after_command=callable(replayed))` — savepoint rollback’idan keyin, commit’dan oldin, retry ichida yon ta’sir. A4 B4 proof runner’i (`_run_action_command`) nusxa o‘rniga shu hook’dan foydalanadi (bookings `api.py` minimal tahrir). A1 filtr moslik yozuvi (`marketplace/api.py::_recording_hits`) **alohida commit** qiladi (5xx rollback’dan ham omon qolishi kerak) — hook’ga mos emas, o‘z joyida qoldi (hujjatlangan farq).
- Mounted accept replay testi: `tests/pg/bookings/test_mounted_accept_integration.py` (`app.main`, `expected_listing_terms_version` alias bilan).
- Kontrakt: `EventType.BOOKING_CONFIRMATION_OVERDUE`, `WALLET_HOLD_ESCALATION_DUE` (staff); A4 ishlatgan barcha `ErrorCode` kontraktda bor (tekshirildi).
- H1 `account_deletion_service.py`ni parallel ulaydi (integrator tegmadi).

## Wave 2.1 (15.09.2026, Q59–Q73)

**Maqsad:** wave 2 BR blocker’larini (1–7) va medium topilmalarni pilot flag’laridan oldin yopish; A1, A3, A4, A2, A10a, H1 **parallel** ishlaydi, integrator fayllariga tegmaydi. Majburiy o‘qish: `AGENTS.md` §3 “Wave 2.1 tasdiqlari”, STATE_MACHINES §11, API_V2_CONTRACT “Wave 2.1 — o‘zgarishlar”, DATA_MODEL §5 (0054–0057), ADR-0008/0009/0018/0020 wave 2.1 bo‘limlari.
(Avvalgi “Wave 2.1 follow-up kartalari” jadvali shu kartalar bilan almashtirildi; rejadagi `0054` detour snapshot Q62 sababli bekor.)

### Umumiy qoidalar (har karta)
- **Integrator fayllari (tegilmaydi, so‘rov A0a orqali):** `app/contracts/**`, `app/api/v2/**` (`web.py`, `router.py`, `__init__.py`), `app/main.py`, `app/modules/__init__.py`, `alembic/env.py`, `docs/architecture/**`, `tests/contracts/**`, `tests/test_v2_db_error_envelope.py`, `tests/test_v2_warnings_and_worker_schedule.py`, migratsiya stub’larining revision id/fayl nomi/`down_revision`. A0b: `tests/pg/conftest.py`, `tests/pg/harness.py`, `docker-compose.test.yml`, `scripts/test-pg.*`, `pyproject.toml`.
- **Migratsiya:** faqat o‘z stub’ingizning `upgrade()`ini to‘ldiring; idempotent; bitta head (`20260915_0057`). Yangi migratsiya fayli yaratilmaydi. Guard trigger’lar `RAISE EXCEPTION ... USING ERRCODE = '<sqlstate>', CONSTRAINT = '<qoida nomi>'` — nom `app/contracts/db_errors.py::CONSTRAINT_RULES`da bo‘lishi shart (yangi nom kerak bo‘lsa A0a’ga so‘rov). Servisdan qochgan DB xatosi endi `web.py` orqali v2 envelope (`INTEGRITY_CONFLICT` va h.k.) — “deferred trigger → generic 500” kutadigan testlarni moslang.
- **Modul chegarasi:** boshqa modul jadvaliga faqat uning `service.py` funksiyasi orqali; import sikli bo‘lsa funksiya ichida lazy import. Domen funksiyasi commit qilmaydi. Lock tartibi ADR-0017, har v2 buyruq `run_with_db_retry` ichida.
- **Parallel kelishuv (A1 ↔ A4):** A1 birinchi navbatda imzolari quyida berilgan public funksiyalarni chiqaradi (DB o‘zgarishisiz) va A0a’ga xabar beradi; A4 shu imzolarga qarab yozadi va oxirida importlarni almashtiradi.
- **Q72 va test fixture’lari:** `feature_flag_values`ga to‘g‘ridan-to‘g‘ri flag yoqadigan PG fixture’lar bor (`tests/pg/bookings/conftest.py` — A4; `tests/pg/geo/*` — A2; `tests/pg/wallet/test_production_invariants.py`, `test_wave16_hardening.py`, `test_wave17_source_links_gate.py` — A3). A2 **avval** `geo.service.mark_flag_change_source(session)` helper’ini (faqat `SET LOCAL`, `enums.FLAG_CHANGE_SOURCE_SETTING`/`FLAG_CHANGE_SOURCE_ADMIN_API`) chiqaradi va xabar beradi; A3/A4 o‘z fixture’larida flag yoqishdan oldin shuni (yoki `set_flag_value`) chaqiradi; A2 0057 guard’ini **eng oxirida** yoqadi.
- **PG testlar:** `ELCHI_TEST_PG_REQUIRED=1`; Docker Desktop yoqilmagan bo‘lishi mumkin — avval ishga tushiring. PG suite’lar **boshqa agentlarning PG ishga tushirishlari bilan ustma-ust emas** (bitta `elchi_test`): ommaviy soxta ulanish/lock xatolari chiqsa kuting va yolg‘iz qayta ishga tushiring. Faqat o‘z papkangiz (`tests/pg/<modul>/**`) + zarur smoke. Yakuniy to‘liq tekshiruvni integrator keyin ketma-ket bajaradi.
- **Hisobot (AGENTS §8):** buyruqlar va natijalar (“mavjud” ≠ “o‘tdi”), migratsiya idempotentligi (ikkinchi `upgrade head` no-op), kontraktdan og‘ishlar, A0a’ga so‘rovlar, ochiq cheklovlar. `py -m pytest tests/contracts -q` va `py -m pytest --collect-only -q` xatosiz.

---

### A4 — Bookings (Q59–Q66, BR blocker 1–5)
**Egalik:** `app/modules/bookings/**`, `tests/pg/bookings/**`, `tests/modules/bookings/**`; migratsiya `alembic/versions/20260915_0056_bookings_snapshot_freeze.py`.

**Kontrakt nomlari:** `state_machines.service_start_allowed`, `TRIP_STATUSES_ALLOWING_SERVICE_START`, `booking_blocks_trip_cancel`, `PASSENGER_BLOCKS_TRIP_CANCEL`, `PARCEL_BLOCKS_TRIP_CANCEL`, `TRIP_CANCEL_REFUSED_WITH_PENDING_NO_SHOW_REVIEW`, `DELIVERED_OPERATOR_QUEUE_AFTER`, `PASSENGER_BOOKING`/`PARCEL_BOOKING` `complete_with_evidence`; `proofs.reissue_decision`, `ReissueDecision.error_details`, `REISSUABLE_PROOF_KINDS`, `PROOF_REISSUE_*`; `disclosure.mask_plate_number`, `full_plate_visible`, `full_plate_visible_from`; `dto.BookingVehicleDisclosureDTO`; `detour.DETOUR_INSERTION_ENABLED`, `DETOUR_NOT_AVAILABLE_REASON`; `enums.OperatorBookingCommand.REISSUE_PROOF_CODE`, `AdminBookingQueue`, `CommissionReviewReason`; `EventType.BOOKING_PROOF_CODE_REISSUED`, `COMMISSION_FINANCE_REVIEW_REQUIRED`; `ErrorCode.TRIP_NOT_STARTED`, `PROOF_REISSUE_LIMITED`, `VEHICLE_NOT_ELIGIBLE`, `NO_SHOW_REVIEW_PENDING`, `TRIP_HAS_UNRESOLVED_BOOKINGS`, `ROUTE_MISMATCH`, `INTEGRITY_CONFLICT`; `WarningCode.DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY`; `db_errors.CONSTRAINT_RULES["booking_snapshot_frozen"]`.

**Talablar:**
1. **Q61 (blocker 1):** accept’da trip lock’idan keyin `trips.service.assert_vehicle_eligible_for_new_booking(session, vehicle_id)` (A1) → `409 VEHICLE_NOT_ELIGIBLE`; mavjud bronlarning keyingi amallari mashina holatini tekshirmaydi.
2. **Q60 (blocker 2):** 0056 freeze trigger (`booking_snapshot_frozen`): `quantity`, `unit_price_minor`, `total_minor`, `commission_minor`, resurs ustunlari faqat shu tranzaksiyada `accepted` bo‘lgan amendment bilan; `fee_policy_id`, `fee_bps`, narx asosi, oyna/occurrence, `terms_snapshot` va boshqalar muzlatilgan. Servis amendment accept yo‘lini moslaydi.
3. **Proof reissue (blocker 3):** B5a `POST /bookings/{id}/codes/{kind}/reissue` (kod egasi, driver 403, `reissue_decision` → `429 PROOF_REISSUE_LIMITED`) va B13 `reissue_proof_code` (sabab majburiy, limitsiz); `code_rotation + 1`, eski kod yaroqsiz, `failed_attempts` reset; qabul qilingan proof → `409 INVALID_STATE_TRANSITION`; audit qatori (kodsiz) + `booking.proof_code.reissued`. Reissue tarixi uchun 0056 ustunlar yoki append-only jadval.
4. **Blocker 4:** `board`/`pick_up` faqat `service_start_allowed(trip.status)` → aks holda `409 TRIP_NOT_STARTED` (kod tekshiruvidan **oldin**, urinish hisoblanmaydi). Trip `cancel` har holatdan `booking_blocks_trip_cancel` bo‘yicha rad (`TRIP_HAS_UNRESOLVED_BOOKINGS`, `details.bookings[]`).
5. **Blocker 5 (Q19/Q7):** trip `cancel` pending no-show review’ni **yopmaydi**; pending review bo‘lsa trip cancel `409 NO_SHOW_REVIEW_PENDING` (`details.bookings[]`); `trip_action` ichidagi avtomatik `reject_no_show` olib tashlanadi.
6. **Q62:** versiyada detour quote bo‘lsa accept barcha muhitlarda `409 ROUTE_MISMATCH reason=detour_not_available`.
7. **Q64:** `BookingVehicleDTO` → `BookingVehicleDisclosureDTO` (yoki undan meros); `plate_number` = `full_plate_visible(trip_status, pickup_at=booking.pickup_window_start, now)`, `plate_number_visible_from`; `cancelled`/`no_show` (xizmat boshlanmagan) bronlarda to‘liq raqam yo‘q; `views.PLATE_VISIBLE_STATUSES` qoidasi olib tashlanadi. Staff to‘liq raqam — audit.
8. **Q65:** `deliver` `_complete` chaqirmaydi (bron `delivered`, capture yo‘q); jo‘natuvchi (`client` tomoni) B4 `complete`; `DELIVERED_OPERATOR_QUEUE_AFTER` dan keyin `awaiting_confirmation` navbati (delivered ham), operator `complete_with_evidence`; B5 delivery kodida `DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY` warning.
9. **Q66:** `blocking_dispute_open` probe yo‘q bo‘lsa 503 o‘rniga: xizmat yakunlanadi, capture yo‘q, `finance_review_reason = dispute_module_unavailable`, `commission.finance_review_required` event, B12 `finance_review` navbati; finance `finalize_fee` bilan yopadi. (Integrator talqini — hisobotda ko‘rsatilgan ochiq savol: probe yo‘q = pilotda har yakunlangan bron finance navbatiga.) **Q74 bilan tasdiqlandi (16.09.2026, A4 yetkazdi):** probe yo‘q → `dispute_state = unavailable` (jadval bor-yo‘qligidan qat’i nazar) → `held` + `finance_review`; probe bor → `clear` capture, `open` kechiktirish (finance navbatisiz).
10. **Medium:** B12/B1 staff javoblarida telefon ko‘rsatilganda `audit_logs` qatori (`booking_contacts_viewed`, bron id’lari, telefon qiymatisiz); amendment muddati: `expire_due_amendments(session, *, now=None, limit=200) -> int`; signal funksiyalari `emit_confirmation_overdue_signals(session, *, now=None, limit=200) -> int` (passenger `arrived` + parcel `delivered`, dedup) va `emit_hold_escalation_signals(session, *, now=None, limit=200) -> int` — commit qilmaydi (A10a worker chaqiradi); `deliver`da versiya bir marta oshadi.
11. **Q59:** `bridges.py` olib tashlanadi — A1 funksiyalari (A1 kartasi 1-band) chiqqach importlar almashtiriladi; `_delegate` yo‘li qolmaydi. Q72 fixture moslashuvi (umumiy qoidalar).

**PG testlar (`tests/pg/bookings/`):** vehicle `rejected/blocked` → accept 409, mavjud bron `board` davom etadi (Q61); snapshot ustunini to‘g‘ridan-to‘g‘ri UPDATE → DB rad, amendment bilan o‘tadi (Q60); 5 xato → reissue → yangi kod o‘tadi, eski kod rad, limit 429, driver 403 (BR 3); `planned` trip’da `board`/`pick_up` → `TRIP_NOT_STARTED` va urinish yozilmagan (BR 4); onboard/picked_up bilan trip cancel har holatda rad (BR 4); pending review bilan trip cancel → 409, review `pending` qoladi, operator qaroridan keyin cancel o‘tadi (Q19, Q7, BR 5); detour quote’li accept 409 (Q62); plate ko‘rinishi vaqt bo‘yicha (Q64); deliver → `delivered`, sender `complete` → capture bir marta (AC20, Q65), 24 soatdan keyin navbat; probe yo‘q → completed + held + navbat (Q66); trip cancel/interrupt/resume, T10 manifest, B12 navbatlari (hammasi), HTTP cash acknowledge (AC26); admin telefon audit qatori.
**DoD:** umumiy DoD + `bridges.py` yo‘q; `rg "bridges" app/modules/bookings` bo‘sh; AC20 capture takrori bitta (Q74: pilotda capture B13 `finalize_fee` orqali; A4 Q74 PG: `tests/pg/bookings` 65 o‘tdi).

---

### A1 — Marketplace, trips, identity (Q59, Q61, Q63, Q67, Q68, BR blocker 7)
**Egalik:** `app/modules/marketplace/**`, `app/modules/trips/**`, `app/modules/identity/**`, `tests/{modules,pg}/{marketplace,trips,identity}/**`; migratsiya `alembic/versions/20260915_0054_marketplace_trips_hardening.py`.

**Kontrakt nomlari:** `enums.ParcelType`, `Amenity`, `PARCEL_TYPE_VALUES`, `AMENITY_VALUES`; `ErrorCode.TRIP_STOPS_LOCKED`, `VEHICLE_NOT_ELIGIBLE`, `PRICE_OUT_OF_BAND`, `VALIDATION_ERROR`; `db_errors.CONSTRAINT_RULES["trip_stops_locked"]`; `disclosure.mask_plate_number` (ixtiyoriy: `trips.rules.mask_plate` bilan teng, kontrakt testi bor).

**Talablar:**
1. **Q59 — public funksiyalar (birinchi navbatda, imzolar `bridges.py` docstring’laridagidek):** `marketplace.service.accept_version(session, *, listing, thread, version, now) -> None`; `close_open_threads(session, *, listing, reason, now) -> int`; `fulfil_listing(session, *, listing, now) -> None`; `reopen_listing(session, *, listing, now) -> None` (`listing.published` event bilan); `cancel_listing_for_booking(session, *, listing, actor_user_id, reason_code, now) -> None`; `trips.service.transition_trip(session, *, trip, target, command, reason, now) -> str` (oldingi holat). Hammasi `assert_transition`, `version+1`, commit yo‘q.
2. **Q61:** `trips.service.assert_vehicle_eligible_for_new_booking(session, vehicle_id: int) -> None` — `verification_status == approved` bo‘lmasa `409 VEHICLE_NOT_ELIGIBLE` (`details.reason`), o‘qish (lock’siz, trip lock ostida chaqiriladi).
3. **Q63:** `patch_trip` `stops` o‘zgarishi `bookings.service.trip_has_allocations(session, trip_id)` bo‘lsa `409 TRIP_STOPS_LOCKED` (lazy import); DB 0054 trigger (`trip_stops_locked`).
4. **Q67:** counter’da band narx **yoki** pickup/dropoff bekati o‘zgarsa qayta tekshiriladi.
5. **Q68:** `amenities`, `parcel_type`, `accepted_parcel_types` — pydantic’da enum (`400 VALIDATION_ERROR`), erkin matn filtri bu maydonlardan olib tashlanadi; 0054 CHECK’lari (`NOT VALID` → tozalash hisobi → `VALIDATE`); testlardagi eski qiymatlar (`"konditsioner"`) moslanadi.
6. **Blocker 7:** P9 `list_listing_offers` va proposal ro‘yxatlari expire bo‘lgan thread’lar ko‘p bo‘lsa ham `limit`gacha to‘ldiradi yoki `next_cursor` qaytaradi (keyset SQL filtri, Python’da tashlab yuborish emas).
7. `ProposalThreadDTO.booking_id` ← `bookings.service.booking_public_id_for_proposal_version`; trip-offer parcel takliflarida qabul qiluvchi kontakti (ism/telefon) proposal’da saqlanadi, DTO’da Q43/Q44 bo‘yicha faqat egasi/staff’ga.
8. Capacity counter trigger (0054): `trip_segment_resources.*_used` faqat allocation o‘zgarishi bilan birga.

**PG testlar:** allocation (released ham) bor trip’da stops PATCH → servis 409 va to‘g‘ridan-to‘g‘ri SQL → DB rad (Q63); vehicle rad etilgan → funksiya 409 (Q61); counter faqat bekat o‘zgarganda band tekshiruvi (Q67); noto‘g‘ri enum → 400, DB CHECK (Q68); 30 ta expire + 5 ta ochiq thread bilan P9 sahifalash hammasini qaytaradi (BR 7); public funksiyalar holat mashinasi/versiya testlari; counter trigger manfiy holati.
**DoD:** umumiy DoD + A4 importlari uchun funksiyalar ro‘yxati hisobotda.

---

### A3 — Wallet, platform gate (Q69–Q71, FK’lar)
**Egalik:** `app/modules/wallet/**`, `app/modules/platform/**`, `tests/{modules,pg}/{wallet,platform}/**`, `app/services/system_settings_service.py`, `app/api/v1/admin_settings.py` (faqat kerak bo‘lsa); migratsiya `alembic/versions/20260915_0055_wallet_booking_fk_approver_guard.py`.

**Kontrakt nomlari:** `enums.Role.FINANCE`, `Role.SUPER_ADMIN`, `Capability.FINANCE_TOPUP_APPROVE`, `FINANCE_ADJUSTMENT_APPROVE`; `ErrorCode.PRODUCTION_INVARIANTS_FAILED`, `FORBIDDEN`, `SECOND_APPROVER_REQUIRED`; `db_errors.CONSTRAINT_RULES["approver_not_finance_staff"]`, `["q48_gate_money_refused"]`; `EventType.TOPUP_APPROVED`.

**Talablar:**
1. **FK’lar:** bookings factory (`tests/pg/bookings/conftest.py` fixture’larini import/`pytest_plugins` orqali yoki o‘z `tests/pg/wallet/booking_factory.py`; A4 fayllari tahrirlanmaydi) bilan wallet PG testlaridagi o‘ylab topilgan `booking_id`larni almashtirish (`test_wallet_money.py`, `test_production_invariants.py`, `test_wave16_hardening.py`, keyin qolganlari), so‘ng 0055 FK’lari (`NOT VALID` + `VALIDATE`) va ORM `ForeignKey(..., name=...)`.
2. **Q69:** approver (`topup_requests.first_approver_id/second_approver_id`, `ledger_adjustment_requests.approved_by/rejected_by`) — faol `users` + faol `user_roles` `finance`/`super_admin`; servis + DB trigger (`approver_not_finance_staff`); `q48_gate_checks()`ga `approver_guard_enforced`.
3. **Q70:** production’da `q48_gate_status` o‘tmasa top-up tasdiqlash (birinchi va ikkinchi) va kredit adjustment (yaratish/tasdiqlash) `503 PRODUCTION_INVARIANTS_FAILED`; DB backstop (`q48_gate_money_refused`). Debit adjustment (Q31 qaytarish) bloklanmaydi — hisobotda tasdiqlang.
4. **Q71:** `app_role_owns_no_objects` gate tekshiruvi (jadval, sequence, funksiya, tur, schema).
5. Amendment `adjust_hold` (delta > 0) production’da Q48 gate tekshiruvi (`hold_fee` bilan bir xil).
6. Q72 fixture moslashuvi (umumiy qoidalar).

**PG testlar:** operator/admin/driver/revoked finance approver → DB rad (to‘g‘ridan-to‘g‘ri SQL ham) va servis 403 (Q69); gate yiqilgan production markerida top-up approve va kredit adjustment 503, debit o‘tadi (Q70); app roli ob’ekt egasi bo‘lsa gate `fail` (Q71); FK: mavjud bo‘lmagan `booking_id` rad, factory bilan barcha wallet testlari yashil; `adjust_hold` gate (AC19, D10).
**DoD:** umumiy DoD + `scripts/db_roles.expected-guarded-tables.txt` yangilanishi kerak bo‘lsa A10a’ga so‘rov.

---

### A2 — Geo, feature flag’lar (Q72, worker/readiness ma’lumotlari)
**Egalik:** `app/modules/geo/**`, `tests/{modules,pg}/geo/**`, `tests/fixtures/geo/**`, `scripts/seed_geo_fixtures.py`; migratsiya `alembic/versions/20260915_0057_geo_flag_enable_source_guard.py`.

**Kontrakt nomlari:** `enums.V2_SERVICE_FLAGS`, `FLAG_CHANGE_SOURCE_SETTING`, `FLAG_CHANGE_SOURCE_ADMIN_API`, `FeatureFlagKey`; `db_errors.CONSTRAINT_RULES["flag_enable_source_refused"]`; `ErrorCode.PRODUCTION_INVARIANTS_FAILED`.

**Talablar:**
1. **Birinchi navbatda:** `geo.service.mark_flag_change_source(session) -> None` (`SET LOCAL`) — xabar bering (A3/A4 fixture’lari).
2. **Q72:** `set_flag_value` yozishdan oldin marker qo‘yadi; 0057 trigger: v2 xizmat flag’ini yoqish markersiz rad (barcha muhitlar), o‘chirish ruxsat; migratsiya flag yoqmaydi. `geo.service.V2_SERVICE_FLAGS` kontrakt `enums.V2_SERVICE_FLAGS` bilan teng (kontrakt testi).
3. **Worker/readiness:** `geo.service.readiness_notices(session) -> list[str]` (faqat ma’lumot, Q57 uslubi: masalan `q47_violations_present`, `routing_provider_disabled`) — A10a readiness’ga qo‘shadi; geo rejali ishlari `app.modules.geo.jobs`da (mavjud `routing_cache_cleanup_task` naqshi, `run_locked`).
4. O‘z PG fixture’larini marker bilan moslash.

**PG testlar:** psql uslubidagi `UPDATE feature_flag_values SET enabled=true` markersiz → rad, marker bilan → o‘tadi, `enabled=false` markersiz → o‘tadi (Q72); `set_flag_value` o‘tadi va 0053 gate’i bilan birga ishlaydi (Q56); `readiness_notices` holatlari.
**DoD:** umumiy DoD + 0057 guard’i boshqa agentlar fixture’lari moslangach yoqilgani hisobotda.

---

### A10a — Worker, readiness, ops (Q57 uslubi, Q65 navbati, Q73)
**Egalik:** `app/worker/**`, `app/api/health_probes.py`, `docker-compose.prod.yml`, `Dockerfile`, `Caddyfile`, `scripts/**` (A0b `scripts/test-pg.*` va A2 `scripts/seed_geo_fixtures.py`dan tashqari), `docs/ops/**`, `tests/pg/ops/**`, yangi `tests/test_worker_*.py`.

**Kontrakt nomlari:** `state_machines.DELIVERED_OPERATOR_QUEUE_AFTER`; `EventType.BOOKING_CONFIRMATION_OVERDUE`, `WALLET_HOLD_ESCALATION_DUE`, `LISTING_EXPIRED`, `PROPOSAL_EXPIRED`.

**Talablar:**
1. `register_default_tasks`ga advisory lock (`run_locked`) bilan vazifalar: `marketplace.service.expire_due_listings` va `expire_due_proposals` (mavjud, `(session, *, now=None, limit=200) -> int`), `bookings.service.expire_due_amendments`, `emit_confirmation_overdue_signals` (Q65 delivered 24 soat ham), `emit_hold_escalation_signals` (A4 chiqaradi). Vazifa wrapper’i sessiya ochadi, batch’larda chaqiradi, commit qiladi, xatoda rollback; funksiya hali yo‘q bo‘lsa vazifa ro‘yxatdan o‘tmaydi (log), import xatosi worker’ni yiqitmaydi. Intervallar konfiguratsiyada (default: expiry 1 daqiqa, signal 5 daqiqa).
2. Readiness: `geo.service.readiness_notices` (A2) natijalari `notices`ga — faqat ma’lumot, hech qachon 503 emas (Q57).
3. **Q73:** registry tayyor bo‘lgach `restore_drill` faqat digest bilan pin qilingan `ELCHI_POSTGIS_IMAGE` (`@sha256:`) — tag bilan rad; hujjat (`docs/ops/BACKUP_RESTORE.md`).
4. Q72 operatsion qaydi: psql bilan flag yoqish ishlamaydi — runbook’da F3 tartibi.

**Testlar:** worker vazifalari ro‘yxati va lock (ikki worker bir vaqtda — bittasi ishlaydi), vazifa xatosi keyingisini to‘xtatmaydi; readiness notices 200; restore drill digest’siz rad (unit/shell test). PG testlari `tests/pg/ops/`da, yolg‘iz.
**DoD:** umumiy DoD + `docker compose config` natijasi.

---

### H1 — v1 `block_driver` (Q15)
**Egalik:** `app/services/admin_driver_service.py`, `app/api/v1/admin_drivers.py` (yoki `block_driver` endpointi joylashgan v1 fayl), shu xulqqa oid `tests/test_admin_driver*.py` va yangi `tests/pg/test_v1_block_driver_v2.py`. Boshqa v1 fayllar faqat zarur bo‘lsa va hisobotda sanab.

**Kontrakt/servis nomlari:** `bookings.service.driver_v2_obligations(session, driver_user_id) -> DriverV2Obligations` (`has_active_v2_business`), `identity.service.block_driver_eligibility(...)` (mavjud imzoni o‘qing), `enums.Role.SUPER_ADMIN`.

**Talablar:**
1. v1 `block_driver`: driver’da faol v2 trip/bron bo‘lsa v1 `users.status`ni o‘zgartirmaydi — faqat v2 eligibility bloki (`driver_eligibility_blocks`), faol trip, GPS, proof, support davom etadi; v2 biznesi yo‘q bo‘lsa v1 xulqi o‘zgarmaydi.
2. To‘liq favqulodda blok (hisob to‘xtatish) faol v2 biznesi bor driver uchun — faqat `super_admin` (aniq parametr/endpoint; admin → v1 `403 FORBIDDEN`).
3. v1 javob shakli `{success, data, message}` o‘zgarmaydi; javobda qo‘llangan blok turi additiv maydon bo‘lsa — hisobotda. Lock tartibi v1: `orders → users → driver_profiles → …` (ADR-0017 §13).

**Testlar:** PG — faol v2 trip’li driver: admin `block_driver` → eligibility bloki, `users.status` o‘zgarmagan, driver `board`/tracking davom etadi (D16); super_admin favqulodda blok → to‘liq; v2 biznessiz driver — eski xulq; `block_driver` vs parallel accept (AC41). SQLite v1 testlari o‘tadi.
**DoD:** umumiy DoD + v1 OpenAPI (93 yo‘l) o‘zgarmagan.

---

### A12 (wave 3, eslatma)
`bookings.service.set_blocking_dispute_probe(probe)` va `set_payment_dispute_opener(opener)` (AC26) ro‘yxatdan o‘tkaziladi; shundan keyin Q66 finance navbati faqat haqiqiy nizo holatlarida.

---

## Wave 2.1 yakuni: integratsiya (15.09.2026)

### Yetkazilgan ishlar (agent hisobotlari + integrator tekshiruvi)
| Egasi | Yetkazildi | Migratsiya |
|---|---|---|
| A1 | Q59 public funksiyalar (`accept_version`, `close_open_threads`, `fulfil_listing`, `reopen_listing`, `cancel_listing_for_booking`, `trips.service.transition_trip`); Q61 vehicle read funksiyasi; Q63 servis + DB guard; deferred segment hisoblagich trigger’i; Q67; Q68 enum + CHECK (tozalash bilan); P9 sahifalash (BR 7); `ProposalParcel.receiver` / `ProposalVersionDTO.receiver` (faqat mijoz tomoni) | `20260915_0054` |
| A3 | wallet→bookings FK’lari (bookings factory bilan); Q69 approver guard (`wallet_user_is_finance_approver`); Q70 gate (debit adjustment va commission reversal ozod); Q71; gate check’lari 7 ta; `adjust_hold` gate’i; W8/W16/W17 `403 reason=approver_not_finance_staff` | `20260915_0055` |
| A4 | `bridges.py` olib tashlandi (Q59); Q60 freeze trigger + amendment marker; Q61; Q62; proof reissue (B5a, B13 `proof_kind`, `booking_proof_reissues`); `TRIP_NOT_STARTED`; trip cancel guard’lari (Q19/Q7); Q64; Q65; Q66 (`dispute_state`); admin telefon audit; `expire_due_amendments`, signal funksiyalari; B12 `finance_review` | `20260915_0056` |
| A2 | Q72 `mark_flag_change_source` + 0057 guard; `readiness_notices`; `geo_invariant_scan_task` | `20260915_0057` |
| A10a | Worker: 5 ta servis vazifasi + 2 ta geo vazifasi (`run_locked`), readiness notices, Q73 digest-only restore drill | — |
| H1 | Q15 v1 `block_driver`: default faqat v2 eligibility bloki, `emergency` faqat super_admin; additiv javob maydonlari | — |

### Integrator tahrirlari (yakuniy o‘tish)
- `tests/test_v2_warnings_and_worker_schedule.py::test_register_default_tasks_is_idempotent_and_hourly` — qattiq “1 vazifa” o‘rniga: ikkinchi chaqiruvda soni o‘zgarmaydi, routing cleanup bitta va 3600 s.
- Hujjatlar: DATA_MODEL §5 0054–0057 yakuniy mazmuni; API_V2_CONTRACT “Wave 2.1 yakuniy implementatsiyasi”; `docs/API_GUIDE.md` v1 `block_driver` (Q15); COVERAGE_MATRIX AC13/AC17 deferred (Q62), Q59–Q73 qatorlari, “Wave 2.1 natijasi”.
- `db_errors.CONSTRAINT_RULES`ga yangi nom qo‘shilmadi: A1 hisoblagich trigger’i nomsiz `check_violation` ko‘taradi → SQLSTATE bo‘yicha `409 INTEGRITY_CONFLICT` (yetarli).

### Kartalardan chetlanishlar
| # | Egasi | Chetlanish | Baho |
|---|---|---|---|
| W21-1 | H1 | `app/schemas/admin_driver.py` (kartadan tashqari) tahrirlandi — `AdminDriverBlock.emergency` | Qabul: v1 additiv schema maydoni, OpenAPI’da yagona farq; egalik keyingi kartada qayd |
| W21-2 | A3 | Approver “effektiv rollari” = legacy `users.role` **yoki** faol `user_roles` (kartada faqat `user_roles`) | Qabul: `identity.capabilities.effective_roles` bilan mos (super_admin ko‘pincha faqat `users.role`da) |
| W21-3 | A4 | Q66: finance navbati faqat probe yo‘q **va** `disputes_v2` jadvali bor bo‘lsa; jadval yo‘q → odatdagi capture (kartada: probe yo‘q → har doim navbat) | **Ochiq savol** (pastda); hal qilinmadi |
| W21-4 | A1 | Trip-offer parcel `receiver` ixtiyoriy (kartada majburiy deb aytilmagan, lekin jo‘natma uchun kutilgan) | Qabul pilot uchun; accept/deliver’da qabul qiluvchi kontakti yo‘qligi — follow-up |
| W21-5 | A3 | Q70 dan commission reversal ham ozod (kartada faqat debit adjustment) | Qabul (mavjud capture bo‘yicha majburiyat); foydalanuvchi tasdig‘i ro‘yxatida |

### Ochiq foydalanuvchi savollari (hal qilinmagan)
1. **Q66 ziddiyati:** integrator kartasi — “A12 probe yo‘q → har yakunlangan bron `finance_review`”; A4 implementatsiyasi — “probe yo‘q **va** `disputes_v2` jadvali mavjud → `finance_review`; jadval yo‘q → odatdagi capture” (`bookings.service.dispute_state`). Pilotda `disputes_v2` yo‘q, demak amalda capture avtomatik. Qaysi biri to‘g‘ri?
2. **Q68 enum qiymatlari** (integrator ro‘yxati): `ParcelType` documents/box/bag/electronics/clothing/other; `Amenity` air_conditioning/phone_charger/no_smoking/pets_allowed/large_trunk/wifi — tasdiq/kengaytirish.
3. **Proof reissue limitlari** (2 daqiqa oraliq, 24 soatda 3 marta self-service; operator limitsiz).
4. **Trip cancel + pending no-show review:** hozir har qanday actor uchun rad (operator avval review’ni hal qiladi) — muqobil: operator trip cancel’i review’ni ochiq qoldiradi.
5. **Q70 istisnolari:** debit adjustment va commission reversal gate’dan ozod.
6. **Q64 pickup vaqti** = `pickup_window_start`; terminal holatdan keyin to‘liq plate yashirilmaydi.
7. **Q65:** qabul qiluvchi ilovada tasdiqlay olmaydi; capture sender tasdig‘i yoki operatorgacha kechikadi.
8. **`TRIP_NOT_STARTED`** trip `interrupted` holatida ham.

### BR tuzatish raundi (15.09.2026, yakuniy tekshiruvdan keyin) — yopildi
| Band | Egasi | Tuzatish |
|---|---|---|
| M1 | A4 | 0056 `bookings_snapshot_freeze()` resurs ustunlarini (`seats`, `baggage_ml`, `cargo_weight_g`, `cargo_volume_ml`) ham muzlatadi; yagona istisno — passenger `seats` = qabul qilingan amendment `new_quantity` |
| M2 | A1 | Staff L2 listing ko‘rinishida telefonlar bilan audit `listing_contacts_viewed` (`marketplace.service.record_staff_listing_contact_view`), `booking_contacts_viewed` bilan juft |
| L1 | A2 | `set_flag_value` Q72 markerini faqat yozuv atrofida qo‘yadi va `try/finally`da tiklaydi (tranzaksiyaning boshqa yozuvlariga oqmaydi) |
| L2 | H1 | v1 emergency blok super_admin tekshiruvi identity effektiv rollari bilan (`users.role` + faol `user_roles`) |
| L3 | A4 | `accept_amendment` miqdor oshganda driver va vehicle eligibility’sini qayta tekshiradi (Q61 ruhi: oshirish — yangi biznes; orkestrator talqini, foydalanuvchi tasdig‘i kutilmoqda) |
| L4 | A10a | `scripts/q68_cleanup_impact.py` + deploy oldidan (pre-migration) ma’lumot; `docs/ops/POSTGRES_POSTGIS_MIGRATION.md` §5.4 |
| L5 | A4 | B13 `reissue_proof_code` HTTP testi |
| Guard sinfi | A10a | `scripts/db_roles.expected-guarded-tables.txt` endi sinflarga ega: `read-only` va `app-marker` (`bookings`, `booking_amendments`, `feature_flag_values` — `app-marker`). **Oldi olingan production buzilishi:** yiqilgan testni faqat ro‘yxatga nom qo‘shib tuzatish db-roles skriptini bu jadvallarni app roli uchun “read-only” deb yuritishiga olib kelardi — deploy’dan keyin app bronlarni yangilay olmas va flag’larni yoqa olmas edi (v2 to‘xtaydi). Sinf ajratilishi buni oldini oldi |

### Follow-up’lar (wave 3 va infra)
| Egasi | Band |
|---|---|
| ~~**A0b**~~ | **Bajarildi (Q76, 16.09.2026):** test stack porti `127.0.0.1:45432` (`docker-compose.test.yml`, `tests/pg/conftest.py` `DEFAULT_PG_URL`, `scripts/test-pg.*`, BASELINE_TESTS); avvalgi `55432` Windows excluded TCP diapazonida (55401–55800) edi. Migratsiya smoke 7 o‘tdi (A0b hisoboti) |
| A12 | `set_blocking_dispute_probe`, `set_payment_dispute_opener`; `disputes_v2` bilan Q66 xulqi qayta ko‘riladi |
| A7 | Chatda `contact_filter.scan(..., mask_proof_codes=True)`; delivery kodini qabul qiluvchiga havola/SMS (Q65, A13 bilan) |
| A1 | Trip-offer parcel `receiver` majburiyligi (W21-4); AC13/AC17 insertion — pilotdan keyin (Q62) |
| H1 / A0a | `app/schemas/admin_driver.py` egaligi kartaga yoziladi |
| A10a | Worker vazifalarini production’da ishga tushirish smoke’i; Q73 registry digest tayyor bo‘lgach drill |
| A0a | Q50 lineage (G12); COVERAGE AC13/AC17 pilotdan keyin qayta ochiladi |
| **H1 / A12** | (a) v1 admin endpoint dependency `get_current_admin_driver_mutation_user` faqat legacy `users.role`ni tekshiradi — staff auth identity effektiv rollariga (`users.role` + faol `user_roles`) o‘tkazilsin (L4 bilan izchillik) |
| **A10a + A4** | (b) append-only jadvallar uchun grant’lar (app roliga `UPDATE`/`DELETE` revoke): `booking_proof_reissues`, `booking_status_history`, `booking_proof_attempts`, `feature_flag_changes`, `corridor_price_band_changes` — avval ular ustida `SELECT … FOR UPDATE` yo‘qligini tasdiqlash |
| **A10a** | (c) `db_roles` detektori helper funksiyalar ichidagi `current_setting()`ni ko‘rmaydi (marker helper orqali o‘qilsa `app-marker` sinfi aniqlanmaydi) |

### Tekshiruv natijalari (integrator, ketma-ket)
PG: vaqtinchalik `elchi-final-pg` (`elchi-postgis:16.15-3.5.3-trixie`, test compose bilan bir xil env/initdb, `127.0.0.1:45440`), `ELCHI_TEST_PG_URL=postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45440/elchi_test`; Redis `elchi-test-redis-1` (36379). Tugagach konteyner o‘chirildi; eski `elchi-a3-postgis` olib tashlandi.

| # | Buyruq | Natija |
|---|---|---|
| 1 | `py -m alembic heads` | `20260915_0057 (head)` — bitta |
| 2 | toza DB’da `alembic upgrade head` (1-marta) | exit 0, 55 ta migratsiya qo‘llandi |
| 3 | `alembic upgrade head` (2-marta) | exit 0, 0 ta migratsiya (no-op); `current` = `20260915_0057` |
| 4 | `py -m pytest tests/contracts -q` | 326 o‘tdi, 0 xato |
| 5 | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q` (to‘liq) | **1627 test: 1626 o‘tdi, 1 failure, 0 error, 0 skip** (548 s). Taqsimot: contracts 326, `tests/modules` 258, `tests/pg` 581, v1/boshqa 462 |
| 6 | `py -m pytest -m pg --collect-only` | 443 `pg` markerli test (53 fayl) — hammasi 5-banddagi ishga tushirishda qatnashgan |
| 7 | ORM/geometry drift + migratsiya smoke (`tests/pg/test_migrations_smoke.py`, `tests/pg/geo/test_geo_schema_drift.py`) | 9 o‘tdi |
| 8 | OpenAPI | v1 **93** operatsiya (oldingi snapshot bilan teng; yagona farq additiv `AdminDriverBlock.emergency`); v2 **87**; prefikssiz 2 (`/health/live`, `/health/ready`) |
| 9 | `rg bridges app/modules/bookings` | bo‘sh (exit 1) |

**Failure (modul egaligida, integrator tuzatmadi):** `tests/pg/ops/test_db_roles.py::test_detected_guarded_tables_match_the_committed_expected_list` — aniqlangan guard’li jadvallar `['booking_amendments', 'bookings', 'feature_flag_values', 'ledger_account_balances']`, `scripts/db_roles.expected-guarded-tables.txt`da faqat `ledger_account_balances`. Sabab: 0056 (A4 — `bookings`, `booking_amendments` trigger’lari) va 0057 (A2 — `feature_flag_values`) yangi guard’lar qo‘shdi, ro‘yxat yangilanmagan. Egasi: **A10a** (fayl), A4/A2 bilan kelishib (qaysi guard’lar Q36 app-role tekshiruviga kiradi). → **BR tuzatish raundida yopildi** (guard sinflari).

**Qayta tekshiruv (BR tuzatish raundidan keyin, 15.09.2026, yangi `elchi-final-pg` 45440, tugagach o‘chirildi):**
| # | Buyruq | Natija |
|---|---|---|
| 1 | `py -m alembic heads` | `20260915_0057 (head)` — bitta |
| 2 | toza DB `alembic upgrade head` ×2 | 1-marta 55 migratsiya, 2-marta 0 (no-op); `current` = `20260915_0057` |
| 3 | `py -m pytest tests/contracts -q` | 326 o‘tdi |
| 4 | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q` | **1639 test: 1639 o‘tdi, 0 failure, 0 error, 0 skip** (476 s) |
| 5 | OpenAPI | v1 93 — oldingi tekshiruvdagi operatsiyalar ro‘yxati bilan aynan bir xil (`AdminDriverBlock`: `reason`, `emergency`); v2 87; prefikssiz 2 |

---

## Wave 3 (16.09.2026) — A5, A6, A7, A12 parallel

**Maqsad:** lenta va saqlangan qidiruv (A5), haydovchi telefoni GPS’i va kuzatuv oynasi (A6), chat + outbox/push yetkazish (A7), nizolar, Q45 signallari, support/SOS, v2 akkaunt o‘chirish (A12). To‘rt agent **parallel** ishlaydi va integrator fayllariga tegmaydi. Majburiy o‘qish: `AGENTS.md` §3 (Q1–Q76), spec §6.6, §8, §9.5, §10, §11, §15–§17, §22; STATE_MACHINES §8, §9, §11, **§12**; API_V2_CONTRACT §6, §10, §11, §12 va ulardagi “Wave 3” bloklari; DATA_MODEL §1.5, §1.8–§1.10, §5 (0058–0061); ADR-0012, 0017, 0018, 0019, 0020.

### Umumiy qoidalar (har karta)
- **Integrator fayllari (tegilmaydi, so‘rov A0a orqali):** `app/contracts/**`, `app/api/v2/**`, `app/main.py`, `app/modules/__init__.py` (model ulash), `alembic/env.py`, `app/core/config.py`, `docs/architecture/**`, `tests/contracts/**`, migratsiya stub’larining revision id / fayl nomi / `down_revision`. **A0b:** `tests/pg/conftest.py`, `tests/pg/harness.py`, `docker-compose.test.yml`, `scripts/test-pg.*`, `pyproject.toml`. **A10a:** `app/worker/**` (worker vazifalarini keyin ulaydi), `scripts/**`, `docs/ops/**`. **A4:** `app/modules/bookings/**` — wave 3 agentlari tahrirlamaydi; kerakli o‘zgarish — pastdagi follow-up. **A1:** `app/modules/{identity,trips}/**`, `app/modules/marketplace/**` (`feed/` sub-paketidan tashqari).
- **Modul sozlamalari:** `app/modules/<modul>/config.py` (`ELCHI_<MODUL>_*`, W1 precedenti); env namunalariga qo‘shish — integrator orqali.
- **Migratsiya:** faqat o‘z stub’ingizning `upgrade()`i (`20260916_0058…0061`); idempotent; bitta head (`20260916_0061`); FK faqat 0057 gacha bo‘lgan jadvallarga (wave 3 modullari orasida FK yo‘q). Guard trigger nomlari faqat `db_errors.CONSTRAINT_RULES`dagilar: `tracking_session_superseded`, `tracking_session_closed`, `chat_message_immutable`, `dispute_terminal_frozen`, `uq_disputes_v2_booking_type_active`, `saved_search_limit`, `append_only_violation` (yangi nom kerak bo‘lsa — A0a). Yangi jadvallar ORM modellari integratsiyada `WIRED_MODEL_MODULES`ga qo‘shiladi; o‘z PG testlaringizda modellarni bevosita import qiling (geo drift testi naqshi — faqat o‘z jadvallaringiz).
- **Router:** `app/modules/<modul>/api.py` (`response_model` bilan); `app/api/v2/router.py`ga ulash — integrator. HTTP testlari: `FastAPI()` + o‘z router’ingiz + `app.api.v2.web.domain_error_handler`/`db_error_handler` (yoki `app.main` — ulangandan keyin).
- **Modul chegarasi:** boshqa modul jadvaliga yozuv faqat uning `service.py` funksiyasi orqali; o‘qish uchun ORM so‘rovi mumkin (yozuvsiz). Domen funksiyasi commit qilmaydi. Lock tartibi ADR-0017, har v2 buyruq `run_with_db_retry` ichida. **Tashqi API (push/SMS/xarita) DB tranzaksiyasi ichida chaqirilmaydi.**
- **Parallel kelishuv:** quyida “Eksport” qilingan funksiyalar imzosi qat’iy. Egasi **birinchi navbatda** imzoli funksiyani (kerak bo‘lsa bo‘sh/nol natija bilan, DB o‘zgarishisiz) chiqaradi va A0a’ga xabar beradi; iste’molchi funksiya yo‘q bo‘lsa (`ImportError`/`AttributeError`) lazy import bilan xavfsiz degradatsiya qiladi (soxta ma’lumot emas) va oxirida haqiqiy chaqiruvni tekshiradi.
- **Outbox consumer’lari:** `communications.EventConsumer` protokoli; modul `consumers.py`da `CONSUMERS: tuple[EventConsumer, ...]` va ixtiyoriy `RELEVANCE_CHECKS: dict[EventType, Callable[[Session, DispatchedEvent], bool]]`; A7 dispatcher ularni `CONSUMER_MODULES` orqali lazy yuklaydi. Consumer commit qilmaydi, tashqi API chaqirmaydi, faqat o‘z jadvallariga yozadi.
- **Worker vazifalari:** ServiceJob shakli `fn(session, *, now=None, limit=200) -> int` (commit’siz) yoki o‘z sessiyasi va `run_locked`ga ega argumentsiz task (`geo.jobs` naqshi). A10a keyinroq `app/worker`ga ulaydi — hisobotda aniq ro‘yxat.
- **Maxfiylik:** event payload faqat allowlist (koordinata, telefon, ism, matn, kod yo‘q); har yetkazishda `events.payload_for_audience`; accept’dan oldin DTO’da kontakt yo‘q (Q43); telefon faqat A4 `BookingDTO.contact` qoidasi bilan (Q44); erkin matn — `contact_filter.scan` + ogohlantirish + moslik yozuvi (R2-b: alohida commit).
- **PG testlar — shaxsiy konteyner (majburiy):** umumiy stack (`45432`) ishlatilmaydi. Har agent o‘z portida (quyidagi jadval) test compose bilan bir xil image va env’li konteyner ko‘taradi, `ELCHI_TEST_PG_URL` va `ELCHI_TEST_PG_REQUIRED=1` bilan faqat o‘z papkalarini (+ `tests/pg/test_migrations_smoke.py`) ishga tushiradi va tugagach konteynerni o‘chiradi. Docker Desktop yoqilmagan bo‘lsa avval yoqing. To‘liq yakuniy tekshiruvni integrator ketma-ket bajaradi.

| Agent | Konteyner | Port |
|---|---|---|
| A6 | `elchi-w3-a6-pg` | `127.0.0.1:45441` |
| A7 | `elchi-w3-a7-pg` | `127.0.0.1:45442` |
| A12 | `elchi-w3-a12-pg` | `127.0.0.1:45443` |
| A5 | `elchi-w3-a5-pg` | `127.0.0.1:45444` |
| (zaxira: integrator/qayta ishga tushirish) | — | 45445–45449 |

```powershell
# <NAME>, <PORT> — jadvaldan. Image docker-compose.test.yml bilan bir xil (yo'q bo'lsa: docker compose -f docker-compose.test.yml build postgis)
docker run -d --name <NAME> -p 127.0.0.1:<PORT>:5432 -e POSTGRES_USER=elchi_test -e POSTGRES_PASSWORD=elchi_test -e POSTGRES_DB=elchi_test -e "POSTGRES_INITDB_ARGS=--encoding=UTF8 --lc-collate=C --lc-ctype=C.UTF-8 --data-checksums" -e TZ=UTC --tmpfs /var/lib/postgresql/data:rw,size=1g --shm-size 256m elchi-postgis:16.15-3.5.3-trixie postgres -c timezone=UTC -c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=300 -c lock_timeout=30s
$env:ELCHI_TEST_PG_URL = "postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:<PORT>/elchi_test"; $env:ELCHI_TEST_PG_REQUIRED = "1"
py -m pytest tests/pg/<modul> tests/pg/test_migrations_smoke.py -q
docker rm -f <NAME>
```
- **Hisobot (AGENTS §8):** buyruqlar va natijalar (“mavjud” ≠ “o‘tdi”), migratsiya idempotentligi (ikkinchi `upgrade head` no-op), eksport qilingan funksiyalar va worker vazifalari ro‘yxati, kontraktdan og‘ishlar, A0a’ga so‘rovlar, ochiq cheklovlar. `py -m pytest tests/contracts -q` va `py -m pytest --collect-only -q` xatosiz.

---

### A6 — Tracking backend (spec §10.3–§10.7, AC27 backend, AC28–AC31, AC44; Q44, D16)
**Egalik:** `app/modules/tracking/**` (`models.py`, `service.py`, `schemas.py`, `api.py`, `rules.py`, `jobs.py`, `ws.py`), `tests/pg/tracking/**`, `tests/modules/tracking/**`; migratsiya `alembic/versions/20260916_0058_tracking_sessions_points.py`. PG: `elchi-w3-a6-pg`, `45441`.

**Kontrakt nomlari:** `tracking.*` (`MAX_POINTS_PER_BATCH`, `MAX_POINT_AGE`, `MAX_FUTURE_SKEW`, `MAX_ACCURACY_M`, `MAX_SPEED_MPS_INPUT`, `MAX_PLAUSIBLE_SPEED_MPS`, `LOW_ACCURACY_THRESHOLD_M`, `freshness_at`, `freshness_for_age`, `is_low_accuracy`, `point_rejection`, `is_implausible_speed`, `is_trusted_for_live`, `tracking_window`, `TrackingWindow`, `RECOMMENDED_INTERVAL_SECONDS`, `WS_PUSH_INTERVAL_SECONDS`, `TRACKING_GRANT_MIN_TTL`/`MAX_TTL`, `RAW_POINT_RETENTION`, `POINT_RECEIPT_RETENTION`, `SIMPLIFIED_TRACK_RETENTION`, `TRACKING_TOKEN_BYTES`, `TRACKING_SUBJECT_LABEL_KEY`); `dto.TrackingPointIn`, `PointsBatchIn`, `PointsBatchAck`, `PointRejectionDTO`, `TrackingLastPointDTO`, `TrackingWindowDTO`, `BookingTrackingDTO`, `PublicTrackingDTO`; `enums.TrackingSessionStatus`, `TrackingFreshness`, `ClientPlatform`, `TrackingWindowReason`, `TrackingQualityFlag`, `TrackingPointRejectReason`, `TrackingGrantScope`, `Capability.TRACKING_PUBLISH`, `OPS_VIEW`, `FeatureFlagKey.TRACKING_ENABLED`; `state_machines.TRACKING_SESSION`; `ErrorCode.TRACKING_SESSION_SUPERSEDED`, `TRACKING_SESSION_CLOSED`, `TRACKING_BATCH_TOO_LARGE`, `TRACKING_WINDOW_NOT_OPEN`, `FEATURE_DISABLED`; `EventType.TRACKING_STALE`, `TRACKING_WINDOW_OPENED`; `crypto.new_secret_token`, `secret_token_hash`; `ids.PublicIdPrefix.TRACKING_SESSION`, `TRACKING_GRANT`.

**Chaqiriladigan servislar (mavjud imzolarni o‘qing):** `identity.service.get_capabilities(session, user_id)`; `trips.service.get_trip`, `get_trip_by_public_id`, `lock_trip(session, trip_id, share=True)`; `bookings.service.get_booking_for_viewer(session, booking_public_id, viewer_user_id) -> (Booking, side)`, `get_booking_by_public_id` (faqat o‘qish: `service_type`, `service_status`, `trip_id`, `pickup_window_start`, `arrived_at_pickup_at`, `client_user_id`); `geo.service.is_flag_enabled`; `platform.service.enqueue_event`, `run_with_db_retry`, `is_production`; `app.api.v2.web.run_command`.

**Eksport (imzo qat’iy):**
- `tracking.service.booking_live_state(session, booking_id: int, *, now: datetime | None = None) -> BookingLiveState` — `BookingLiveState(window: TrackingWindow, freshness: TrackingFreshness, last_captured_at: datetime | None, driver_arrived_at: datetime | None)`; faqat o‘qish (A12 SOS staff ko‘rinishi, A7 kerak bo‘lsa).
- `tracking.service.trip_tracking_summary(session, trip_id: int, *, now: datetime | None = None) -> TripTrackingSummary` — `(active_session: bool, freshness: TrackingFreshness, last_captured_at: datetime | None)` (K9, operator navbati).
- `tracking.service.close_sessions_for_trip(session, trip_id: int, *, now: datetime | None = None) -> int` — A4 follow-up (trip terminal) uchun; commit’siz.
- **Worker:** `tracking.jobs.emit_stale_signals(session, *, now=None, limit=200) -> int` (`tracking.stale`, dedup sessiya + epizod), `tracking.jobs.emit_window_opened_signals(session, *, now=None, limit=200) -> int` (`tracking.window_opened`, bron bo‘yicha dedup), `tracking.jobs.retention_task()` (argumentsiz, o‘z sessiyasi, `run_locked`: partition yaratish funksiyasi + muddati o‘tgan nuqta/receipt/soddalashtirilgan iz).

**Talablar:**
1. **K1:** trip driveri, `tracking.publish` (eligibility blokida ham, D16), trip `boarding|in_progress|interrupted`; lock `trips` `FOR SHARE` → oldingi `active` sessiya → `TRACKING_SESSION.assert_transition(..., "supersede")` → yangi `active` (partial unique, AC29). `tracking_enabled` o‘chiq → `403 FEATURE_DISABLED` faqat trip’da avval sessiya bo‘lmagan bo‘lsa (AC38).
2. **K2:** sessiya egasi; `len(points) > MAX_POINTS_PER_BATCH` → `400 TRACKING_BATCH_TOO_LARGE`; `superseded` → `409 TRACKING_SESSION_SUPERSEDED`; `closed` yoki trip terminal → `409 TRACKING_SESSION_CLOSED` (DB guard ham). Har nuqta: `point_rejection`; receipt `(session_id, seq)` `ON CONFLICT` → `duplicate_seqs`, hash farqi → `payload_conflict`; `quality_flags` (`is_low_accuracy`, `is_mock`, `is_implausible_speed`, `captured_at < last_captured_at` → `out_of_order`); live ustunlar faqat `is_trusted_for_live` va `captured_at > last_captured_at` bo‘lsa (AC28). ACK commit’dan keyin; Idempotency-Key yo‘q (seq dedup).
3. **K4:** ishtirokchi — `tracking_window` yopiq → `403 TRACKING_WINDOW_NOT_OPEN details {reason, opens_at?}`; ochiq → `BookingTrackingDTO` (freshness `freshness_at(last_captured_at, now)`, sessiya yo‘q → `no_data`); boshqa bron/trip ma’lumoti yo‘q. Staff `ops.view` → 200 + `audit_logs.action = "tracking_viewed"` (qiymatlarsiz).
4. **K5–K7:** bron egasi `recipient_link` grant; token `crypto.new_secret_token` (`TRACKING_TOKEN_BYTES`), bazada `secret_token_hash`, URL faqat yaratishda; TTL chegaralari; K6 revoke; K7 oyna yopiq/revoked/expired/noma’lum → `404`; `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, analytics yo‘q.
5. **K8 WS:** REST bilan bir xil auth/scope; `WS_PUSH_INTERVAL_SECONDS`da oyna/grant qayta tekshiriladi va snapshot yuboriladi; oyna yopilsa `4403`, auth xato `4401`, noma’lum `4404` (AC31). Bir nechta uvicorn worker’da to‘g‘ri (xotiradagi fan-out’ga tayanmaydi). Redis yo‘q → PG (AC34).
6. **K9** `GET /admin/trips/{trip_id}/tracking` (`ops.view`, audit) → `TripTrackingAdminDTO`.
7. **Soxta GPS yo‘q (§6.6, §10.4–§10.5):** nuqta sintez/interpolyatsiya qilib saqlanmaydi; freshness faqat saqlangan ishonchli nuqtadan; DTO’da “GPS faol” yo‘q; mock nuqta hech qachon live emas. GPS’dan avtomatik “keldim” yaratilmaydi — “Keldim” faqat A4 `arrive_at_pickup` (A6 `driver_arrived_at`ni o‘qiydi).
8. **Partition/retention (Q36, Q71):** partition’lar owner roliga tegishli `SECURITY DEFINER` funksiya orqali (`search_path = pg_catalog, public, pg_temp`), app roli ob’ekt egasi bo‘lmaydi; `scripts/db_roles.expected-guarded-tables.txt` o‘zgarishi kerak bo‘lsa — A10a’ga so‘rov.

**PG testlar (`tests/pg/tracking/`):** AC28 (eski nuqta yangisidan keyin — marker orqaga ketmaydi); AC29 (ikki sessiya — eskisi 409); dublikat seq — bitta qator, `payload_conflict`; AC27 (5 daqiqa uzilish → `lost`, keyin batch → `fresh`, tartib saqlanadi); AC30 (begona user / boshqa bron / noto‘g‘ri token → 403/404, telefon yo‘q); AC31 (bron terminal → K4 403, WS yopiladi); AC44 (2 kun oldingi bron → 403 `opens_at`); parcel pickup’gacha yopiq; eligibility bloklangan driver sessiya ochadi va nuqta yuboradi (D16); flag o‘chiq + mavjud sessiya → davom (AC38); grant jadvalida faqat hash; partition funksiyasi app roli bilan ishlaydi; `trip_finished`da K2 409.
**DoD:** umumiy DoD + eksport/worker ro‘yxati hisobotda; AC27 dala qismi va AC32 “o‘tdi” deb yozilmaydi (Android dasturchi).

---

### A7 — Communications: chat, outbox dispatch, in-app/push (spec §6.6, §15, §16; ADR-0012, ADR-0019 §9, ADR-0020; AC33, AC34; N2/Q16, Q43–Q45, Q65)
**Egalik:** `app/modules/communications/**` (`models.py`, `service.py`, `schemas.py`, `api.py`, `dispatch.py`, `recipients.py`, `providers.py`, `jobs.py`), **yangi fayl** `app/modules/platform/outbox_dispatch.py` (outbox/consumer_receipts dispatch primitivlari — ADR-0012: jadval A3, dispatch A7; platform’ning boshqa fayllari A3), `tests/pg/communications/**`, `tests/modules/communications/**`; migratsiya `alembic/versions/20260916_0059_communications_chat_notifications.py`. PG: `elchi-w3-a7-pg`, `45442`.

**Kontrakt nomlari:** `communications.*` (`CHAT_TEXT_MAX_LENGTH`, `CHAT_MASK_PROOF_CODES`, `CHAT_MAX_MESSAGES_PER_MINUTE`, `CHAT_WRITABLE_AFTER_TERMINAL`, `CHAT_ATTACHMENTS_ENABLED`, `chat_writable`, `ChatActivitySummary`, `OUTBOX_RETRY_SCHEDULE`, `OUTBOX_MAX_ATTEMPTS`, `OUTBOX_BATCH_LIMIT`, `outbox_retry_delay`, `NOTIFICATION_DELIVERY_LEASE`, `NOTIFICATION_DEDUP_WINDOW`, `PUSH_PAYLOAD_KEYS`, `DispatchedEvent`, `EventConsumer`); `events.EVENT_AUDIENCES`, `payload_for_audience`, `EventAudience` (+ `COMPETING_DRIVER`), `COMPETING_DRIVER_EVENT_TYPES`, `COMPETING_DRIVER_PAYLOAD_KEYS`; `dto.ChatMessageCreate`, `ChatMessageDTO`, `EventDTO`; `contact_filter.scan(..., mask_proof_codes=True)`; `enums.ChatThreadKind`, `ChatModerationStatus`, `QuickReplyCode`, `NotificationChannel`, `NotificationDeliveryStatus`, `ClientPlatform`, `Capability.OPS_VIEW`, `OPS_TRUST_REVIEW`, `OPS_BOOKING_COMMAND`, `EventType.CHAT_MESSAGE_CREATED`; `ErrorCode.CHAT_CLOSED`, `RATE_LIMITED`, `INVALID_CURSOR`; `WarningCode.CONTACT_INFO_MASKED`; `ids.PublicIdPrefix.CHAT_THREAD`, `CHAT_MESSAGE`, `DEVICE`, `EVENT`, `NOTIFICATION`; `db_errors.CONSTRAINT_RULES["chat_message_immutable"]`.

**Chaqiriladigan servislar:** `marketplace.service.get_thread_for_party(session, thread_public_id, user_id)`, `get_listing` (recipient: listing egasi), `ContactFilterHit` + `record_contact_filter_hits(session, hits)` (`subject_type="chat_message"`, `marketplace/api.py::_recording_hits` naqshi — buyruqdan keyin alohida commit); `bookings.service.get_booking_for_viewer`, `get_booking_by_public_id` (o‘qish: tomonlar, `service_terminal_at`, `accepted_proposal_version_id`); `identity.service.get_capabilities`, `resolve_user_id`, `user_public_id`; `platform.service.enqueue_event`, `run_with_db_retry`; `app.api.v2.web.run_command`, `to_api_warnings`.

**Eksport (imzo qat’iy):**
- `communications.service.chat_activity_for_booking(session, booking_id: int) -> ChatActivitySummary` — bron chat’i + qabul qilingan proposal thread chat’i; faqat sanoq/vaqt (A12 iste’molchi). **Birinchi navbatda chiqariladi.**
- `communications.dispatch.CONSUMER_MODULES: tuple[str, ...] = ("app.modules.trust_support.consumers", "app.modules.marketplace.feed.consumers")` — har modulning `CONSUMERS` va `RELEVANCE_CHECKS`i lazy yuklanadi; import xatosi log, dispatcher to‘xtamaydi.
- **Worker:** `communications.service.dispatch_outbox(session, *, now=None, limit=200) -> int` (ServiceJob: `FOR UPDATE SKIP LOCKED`, consumer’lar + `consumer_receipts`, recipient/auditoriya bo‘yicha `notification_deliveries`, `dispatched_at` yoki backoff/dead-letter — faqat DB), `communications.jobs.push_delivery_task()` (argumentsiz, o‘z sessiyalari, `run_locked`: lease’li claim → commit → provayder DB’dan tashqarida → natija tx).

**Talablar:**
1. **Chat N6/N7:** faqat tomonlar (boshqalar `404`); `chat_writable` → `409 CHAT_CLOSED`; `scan(text, mask_proof_codes=True)` — faqat `masked_text` saqlanadi, `Envelope.warnings`; tezkor javob shartni o‘zgartirmaydi; attachment → `400 reason=chat_attachments_not_available`; chastota → `429`; `chat.message.created` (matnsiz); DTO’da `author_side`, user id/ism/telefon yo‘q (Q43/Q44). N10 staff o‘qish + audit `chat_viewed`; N11 hide (`ops.trust_review`, sabab, audit).
2. **Dispatcher (ADR-0012, AC33):** `outbox_dispatch.py`da claim/mark funksiyalari; commit’dan keyin crash → event keyin yuboriladi; takror event → bitta ta’sir (`consumer_receipts`, `UNIQUE(event_id, user_id, channel)`); `outbox_retry_delay`, 10 urinish → dead-letter; N8 ro‘yxat, N9 retry (audit, sabab).
3. **Recipient va auditoriya:** `aggregate_type` bo‘yicha — `booking` → mijoz (`client`) + driver (`driver`); `listing` → egasi (request → client, trip_offer → driver); `proposal_thread` → ikki tomon + shu listing’da ochiq thread’i bor boshqa driverlar (`competing_driver`); `trip` → driver + faol bron mijozlari; `wallet`/`topup` → driver; `user` → o‘sha user (auditoriya ruxsat bersa); `chat_thread` → boshqa tomon; `saved_search` → egasi; faqat-staff event’lar per-user yetkazilmaydi (staff N1’da outbox’dan `STAFF` nusxa). Har nusxa `payload_for_audience`; `None` → `skipped`. Mijozga `wallet.*`/`commission.*` hech qachon (N2, Q16).
4. **In-app inbox:** `notification_deliveries (channel=in_app)`; N4/N5 `NotificationDTO {id (ntf_), type (=event_type), title_key, body_key, params (audience nusxasi), is_read, created_at, link}`; legacy `notifications` jadvaliga yozilmaydi (v1 o‘zgarmaydi). N1 — cursor, faqat auditoriya nusxasi.
5. **Push:** N2/N3 `device_tokens` (`ClientPlatform`); `providers.PushProvider` protokoli + fake provider; payload faqat `PUSH_PAYLOAD_KEYS`; `NOTIFICATION_DEDUP_WINDOW`; `RELEVANCE_CHECKS` (bekor/muddati o‘tgan listing → `skipped`, §6.6); push xatosi bron/pulga ta’sir qilmaydi (AC34). **Real provayder va xom token saqlash — U3 qarorigacha ulanmaydi** (yangi dependency taqiq).

**PG testlar (`tests/pg/communications/`):** AC33 (commit’dan keyin dispatcher yiqilishi → keyingi ishga tushishda yuboriladi, dublikat yo‘q); ikki dispatcher parallel (`SKIP LOCKED`) → har event bir marta; wallet event mijozga yetkazilmaydi, mijoz booking nusxasida komissiya kalitlari yo‘q; competitor nusxasida faqat `listing_id`; chatda telefon va 6 xonali kod maskalangan, DB’da ham maskalangan; moslik yozuvi keyingi 4xx’dan omon qoladi; accept’dan keyin proposal chat 409, bron chat terminal + 24 soatda 409; rate limit; 10 urinishdan keyin dead-letter, N9 retry; relevance check `skipped`; provayder xatosi → `failed` + backoff, bron o‘zgarmaydi; `chat_message_immutable` to‘g‘ridan-to‘g‘ri SQL bilan rad.
**DoD:** umumiy DoD + consumer/relevance protokoli A5/A12 bilan integratsion test (ular yetkazgan modul bo‘lmasa — fake consumer bilan, hisobotda).

---

### A12 — Trust & support (spec §8.2 ma’lumoti, §9.5, §11, §16, §17.1–§17.3, §17.5, §17.8; AC26, AC36 ma’lumoti; Q7, Q8, Q43, Q45, Q66/Q74)
**Egalik:** `app/modules/trust_support/**` (`models.py`, `service.py`, `schemas.py`, `api.py`, `rules.py`, `consumers.py`, `config.py`), `tests/pg/trust_support/**`, `tests/modules/trust_support/**`; migratsiya `alembic/versions/20260916_0060_trust_support_disputes_strikes.py`. **Wave 3 da qo‘shimcha (H1 faol emas):** `app/services/account_deletion_service.py` — faqat trust blocking tekshiruvini qo‘shish (v1 javob shakli o‘zgarmaydi, `details` additiv) va shu xulq testi; **faqat U5 tasdig‘idan keyin:** `app/api/v1/admin_drivers.py` (uchta auth dependency) + yangi `tests/test_v1_staff_effective_roles.py`. PG: `elchi-w3-a12-pg`, `45443`.

**Kontrakt nomlari:** `trust.*` (`BLOCKING_DISPUTE_TYPES`, `DISPUTE_ESCALATE_AFTER`, `DISPUTE_DESCRIPTION_MAX_LENGTH`, `BlockingDisputeProbe`, `PaymentDisputeOpener`, `CONTACT_FILTER_STRIKE_WINDOW`, `CONTACT_FILTER_FREE_HITS`, `STRIKE_REVIEW_WINDOW`, `STRIKES_FOR_REVIEW`, `QUICK_CANCEL_AFTER_CHAT_WINDOW`, `REPEATED_PAIR_CANCEL_WINDOW`, `REPEATED_PAIR_CANCEL_THRESHOLD`, `TRUST_REVIEW_EVIDENCE_KEYS`, `hit_is_strike`, `strikes_need_review`, `is_quick_cancel_after_chat`, `is_repeated_pair_cancellation`, `SUPPORT_MESSAGE_MAX_LENGTH`, `SUPPORT_PROMISES_RESPONSE_TIME`, `RATING_PRIOR`, `RATING_PRIOR_WEIGHT`, `RATING_PUBLISH_AFTER`, `ReputationSummary`); `state_machines.DISPUTE`, `TRUST_REVIEW`, `SUPPORT_TICKET`; `enums.DisputeType`, `DisputeStatus`, `DisputeResolutionCode`, `TrustSignalType`, `TrustReviewStatus`, `TrustReviewDecision`, `SupportTicketKind`, `SupportTicketStatus`, `ReputationLabel`, `Capability.OPS_DISPUTE_RESOLVE`, `OPS_TRUST_REVIEW`, `OPS_VIEW`, `FINANCE_ADJUSTMENT`; `EventType.DISPUTE_OPENED`, `DISPUTE_RESOLVED`, `CONTACT_FILTER_HIT`, `CONTACT_STRIKE_RECORDED`, `TRUST_REVIEW_OPENED`, `TRUST_WARNING_ISSUED`, `SUPPORT_TICKET_OPENED`, `SUPPORT_SOS_RAISED`, `SUPPORT_TICKET_STATUS_CHANGED`, `RATING_PUBLISHED`, `BOOKING_CANCELLED`; `communications.DispatchedEvent`, `EventConsumer`, `ChatActivitySummary`; `ErrorCode.DISPUTE_ALREADY_OPEN`, `RATING_NOT_ALLOWED`, `RATING_ALREADY_EXISTS`, `ACCOUNT_DELETION_BLOCKED`; `ids.PublicIdPrefix.DISPUTE`, `RATING`, `SUPPORT_TICKET`, `TRUST_REVIEW`; `db_errors` `uq_disputes_v2_booking_type_active`, `dispute_terminal_frozen`, `append_only_violation`; `contact_filter.scan`.

**Chaqiriladigan servislar:** `bookings.service.set_blocking_dispute_probe`, `set_payment_dispute_opener`, `lock_booking(session, booking_id)`, `get_booking_for_viewer`, `get_booking_by_public_id`, `blocking_state_for_user(session, user_id, lock=True)`; `wallet.service.blocking_state_for_user(session, user_id, lock=True)`; `communications.service.chat_activity_for_booking(session, booking_id) -> ChatActivitySummary` (A7 parallel — lazy; yo‘q bo‘lsa `quick_cancel_after_chat` signali chiqarilmaydi, log); `identity.service.get_capabilities`, `user_public_id`, `resolve_user_id`; `marketplace.service.ContactFilterHit` + `record_contact_filter_hits` (`subject_type = rating | support_ticket | dispute`); `tracking.service.booking_live_state` (SOS staff DTO, lazy); `app.services.account_deletion_service.delete_own_account` (I4 qayta ishlatish); `platform.service.enqueue_event`, `run_with_db_retry`. Bekor qilishlar sanog‘i — `app.modules.bookings.models.Booking` bo‘yicha faqat o‘qish so‘rovi.

**Eksport (imzo qat’iy):**
- `trust_support.service.reputation_summaries(session, user_ids: Sequence[int], *, service_type: ServiceType) -> dict[int, ReputationSummary]` — A5 iste’molchi; **birinchi navbatda** (reyting jadvallari tayyor bo‘lguncha nol summary, `new_verified`).
- `trust_support.service.register_booking_hooks() -> None` — idempotent; integrator `configure_v2_ports()`da chaqiradi. Ichida: `blocking_dispute_open(session, booking_id: int) -> bool` (probe) va `open_payment_dispute(session, booking, receipt, actor_user_id: int, comment: str) -> int` (opener).
- `trust_support.service.blocking_state_for_user(session, user_id: int, *, lock: bool = False) -> TrustBlockingState` — `(open_disputes: int, open_sos_tickets: int)`, `blocks_deletion`, `as_details()`.
- `trust_support.consumers.CONSUMERS` — `contact_filter_strikes` (`trust.contact_filter.hit`), `cancellation_signals` (`booking.cancelled`).
- **Worker:** `trust_support.service.emit_dispute_escalations(session, *, now=None, limit=200) -> int` (48 soat), `publish_due_ratings(session, *, now=None, limit=200) -> int` (7 kun), `refresh_reputation_snapshots(session, *, now=None, limit=200) -> int`.

**Talablar:**
1. **Nizolar S3–S8:** ochish — ishtirokchi (bloklangan driver ham) yoki O; `bookings.service.lock_booking` → insert; `DISPUTE_ALREADY_OPEN`; bron/trip holati o‘zgarmaydi, tiklash yo‘q; S8 `ops.dispute_resolve` (+ moliyaviy qarorda `finance.adjustment`), pul/xizmat buyruqlari alohida (B13, W8). v1 nizolar (Q12, Q13, Q37, Q38) o‘zgarmaydi.
2. **Hook’lar (AC26, AC20; Q74 ni almashtiradi):** `register_booking_hooks`; PG testida ro‘yxatdan o‘tgach **ikkala** yo‘l: `clear` → yakunlash tranzaksiyasida capture (bitta, AC20) va `finance_review`ga tushmaydi; `open` (`service|payment|commission|delivery`) → capture kechiktiriladi, `held`, finance navbatiga tushmaydi; `no_show|safety|other` bloklamaydi; B8 contest → `payment` nizo, `cash_receipts.dispute_id`, xizmat holati o‘zgarmaydi. Teardown’da `set_blocking_dispute_probe(None)`, `set_payment_dispute_opener(None)` (boshqa suite’lar Q74 fallback’ida qoladi).
3. **Q45:** strike consumer (marketplace, chat, reyting, support mosliklari), `contact_strikes` (`UNIQUE(source_event_id)` — takror event bitta strike), review item (partial unique), `TRUST_REVIEW` buyruqlari S18–S20; bekor qilish consumer’i — quick-cancel-after-chat (A7 summary) va juftlik takrori; evidence faqat `TRUST_REVIEW_EVIDENCE_KEYS`; avtomatik ban/jarima yo‘q.
4. **Support/SOS S13–S17:** `config.py` (`ELCHI_SUPPORT_PHONE`, `ELCHI_SUPPORT_HOURS_TEXT`; yo‘q → `available=false`; qiymatlar — U7); 24/7/javob vaqti va’dasi yo‘q; SOS event koordinatasiz, faqat staff; xabar kontakt filtridan.
5. **Reyting S1/S2 (§17.2, AC36):** yakunlangan bron, bir muallif–subyekt, 7 kun/ikkala tomon qoidasi, izoh filtrdan, `reputation_snapshots`; legacy baholar ko‘chirilmaydi (Q4); sun’iy reyting yo‘q.
6. **I4 v2 `DELETE /me` (§17.8, N4):** bookings + wallet + trust blocking (lock tartibi v1 o‘chirish bilan bir xil: `users → driver_profiles → bookings → wallet_accounts`) → `409 ACCOUNT_DELETION_BLOCKED details`; aks holda v1 servisini qayta ishlatish. v1 `DELETE /api/v1/auth/me` ham trust tekshiruvini oladi (shakl o‘zgarmaydi).
7. **Staff MFA rejasi (Q8, §17.5):** kod/jadval yo‘q; hisobotda ADR-0021 loyihasi (tahdid modeli, TOTP/WebAuthn variantlari — kutubxona tanlovisiz, ro‘yxatdan o‘tish va tiklash, staff sessiya muddati, rollout gate) — A0a ADR sifatida yozadi.
8. **v1 staff auth (wave 2.1 follow-up a) — U5 tasdig‘igacha boshlanmaydi.** Tasdiqlansa: `get_current_admin_driver_{view,mutation}_user`, `get_current_admin_driver_vehicle_editor` staff rollarini `identity.service.get_capabilities(...).roles` (legacy `users.role` + faol `user_roles`) bo‘yicha tekshiradi; faqat staff rollari (marketplace rol tekshiruvlari o‘zgarmaydi); javob kodi/matni/shakli bir xil; v1 OpenAPI 93.

**PG testlar (`tests/pg/trust_support/`):** parallel bir xil turdagi nizo → bitta (AC26); nizo ochish vs `complete` poygasi (lock tartibi, deadlock yo‘q); hook’lar bilan clear→capture va open→delay (yuqorida); takror hit event → bitta strike, 3 strike → bitta review; quick-cancel va juftlik signallari; review buyruqlari versiya bilan; SOS event faqat staff; ochiq nizo bilan v2 va v1 akkaunt o‘chirish 409; reyting nashr qoidasi va 1×5.0 vs 200 baho (`adjusted_rating`); `dispute_evidence`/`contact_strikes` UPDATE → DB rad.
**DoD:** umumiy DoD + v1 OpenAPI 93 o‘zgarmagan; A12 hook’lari ro‘yxatdan o‘tganda A4 `tests/pg/bookings` teardown bilan yashil qolishi (bookings PG suite’ini o‘z konteyneringizda bir marta ishga tushiring).

---

### A5 — Lenta, matching, saved searches (spec §6.4, §6.6, §8.1–§8.4; AC18, AC35, AC36 ranking; Q21, Q40, Q43, Q46)
**Egalik:** `app/modules/marketplace/feed/**` (yangi sub-paket: `models.py`, `service.py`, `rules.py`, `schemas.py`, `api.py`, `consumers.py`), `tests/pg/marketplace/feed/**`, `tests/modules/marketplace/feed/**` (A1 fayllari va `tests/*/marketplace/` ichidagi mavjud fayllar tahrirlanmaydi); migratsiya `alembic/versions/20260916_0061_marketplace_saved_searches.py`. PG: `elchi-w3-a5-pg`, `45444`.

**Kontrakt nomlari:** `feed.*` (`RANKING_VERSION`, `CLIENT_SCORE_WEIGHTS`, `DRIVER_SCORE_WEIGHTS`, `MATCH_TYPE_SCORE`, `NEUTRAL_PRICE_SCORE`, `NEUTRAL_FIT_SCORE`, `RELIABILITY_WEIGHTS`, `EXPERIENCE_LOG_BASE_TRIPS`, `SAVED_SEARCH_MAX_PER_USER`, `SAVED_SEARCH_MAX_WINDOW_DAYS`, `FEED_DEFAULT_LIMIT`, `FEED_MAX_LIMIT`); `trust.ReputationSummary`, `COMPLETION_PRIOR`, `ON_TIME_PRIOR`; `enums.FeedSide`, `FeedSort`, `MatchGroup`, `MatchType`, `MatchReason`, `ReputationLabel`, `ServiceType`, `ListingKind`, `ListingStatus`, `PriceBasis`, `EventType.LISTING_PUBLISHED`, `SAVED_SEARCH_MATCHED`; `communications.DispatchedEvent`, `EventConsumer`; `ErrorCode.SAVED_SEARCH_LIMIT_REACHED`, `INVALID_CURSOR`, `ROUTING_UNAVAILABLE`, `NOT_FOUND`; `ids.PublicIdPrefix.SAVED_SEARCH`; `db_errors.CONSTRAINT_RULES["saved_search_limit"]`; cursor — `app.api.v2.web.encode_page_cursor`/`decode_*`.

**Chaqiriladigan servislar:** `marketplace.views.listing_public_dto(session, listing)`; `marketplace.service.get_listing_by_public_id`, `get_listing`; `marketplace.models.Listing` va detallar — faqat o‘qish so‘rovi; `geo.matching.evaluate_route_match` va `geo.service.is_flag_enabled` (mavjud imzolar); narx L/U — A2 band o‘qish funksiyasi (`app/modules/geo/pricing.py`) mavjud bo‘lsa, aks holda `NEUTRAL_PRICE_SCORE`; `trips.service.get_trip`; `identity.service.get_capabilities` (Q21, ko‘ruvchi capability’si); `trust_support.service.reputation_summaries` (A12 parallel — lazy; yo‘q bo‘lsa `ReputationSummary(user_id, service_type)` nol — soxta reyting emas); `platform.service.enqueue_event(..., dedup_key=f"saved_search:{svs}:{listing}")`, `run_with_db_retry`; `app.api.v2.web.run_command`.

**Eksport (imzo qat’iy):**
- `marketplace.feed.consumers.CONSUMERS` — `saved_search_matcher` (`listing.published`).
- `marketplace.feed.consumers.RELEVANCE_CHECKS = {EventType.SAVED_SEARCH_MATCHED: saved_search_match_still_relevant}`; `marketplace.feed.service.saved_search_match_still_relevant(session, event: DispatchedEvent) -> bool` (listing hali `published` va muddati o‘tmagan, qidiruv o‘chirilmagan, `notify=true`).
- **Worker:** `marketplace.feed.service.expire_saved_searches(session, *, now=None, limit=200) -> int` (oyna tugagan qidiruvlar `notify=false`).

**Talablar:**
1. **M1 lenta:** ikki tomon (`FeedSide`), §6.6 filtrlari; default — tanlangan yo‘nalish (mamlakat bo‘ylab aralash lenta yo‘q); guruhlar `exact`/`on_route` (+ production’dan tashqarida ruxsat etilgan `detour`) va alohida `alternative` (§6.4, Q46: production’da detour yo‘q); ranking §8.2 (mijoz) / §8.4 (driver), `meta.ranking_version = RANKING_VERSION`; `FeedSort`; router ishlamasa soxta moslik yo‘q (AC35, `ROUTING_UNAVAILABLE` degradatsiya belgisi). Narx solishtirish bir xil miqdor/xizmat uchun **jami narx** bo‘yicha (per_seat va total aralashmaydi); driver lentasida arzonlik mukofotlanmaydi (§8.4 Y).
2. **Ko‘rinish:** `FeedItemDTO.listing` = `listing_public_dto` (Q43); Q21 eligible bo‘lmagan driver `trip_offer`lari yashirin; AC18 kelajak safarli oflayn driver qoladi; bloklangan tomonlar (S9 wave 4) — hozircha yo‘q; P9 ko‘rinish qoidasi bilan bir xil (Q40). `ready_to_accept` — listing ochiq + sig‘im + driver eligible; mijozga balans holati ochilmaydi (Q16) — balans tekshiruvi wave 3 da kiritilmaydi (cheklov hisobotda).
3. **AC36:** 1 × 5.0 ko‘r-ko‘rona birinchi emas (`ReputationSummary.adjusted_rating`), baholar soni ko‘rinadi, yangi driverga sun’iy reyting yo‘q.
4. **M2** listing egasi uchun matches (`MatchGroup`), boshqaga `404`.
5. **M3–M5:** `SAVED_SEARCH_MAX_PER_USER` (servis `users` `FOR NO KEY UPDATE` + DB guard) → `409 SAVED_SEARCH_LIMIT_REACHED details {limit}`; oyna ≤ `SAVED_SEARCH_MAX_WINDOW_DAYS`; Idem Y; soft delete; boshqaning qidiruvi `404`.
6. **Consumer:** `listing.published` → mos `notify=true` qidiruvlar (xizmat, tomon, bekat/region, vaqt oynasi kesishuvi, miqdor), o‘z listing’i emas; `saved_search_notifications` unique → bir listing uchun bitta `saved_search.matched`; takror event → yangi event yo‘q.

**PG testlar (`tests/pg/marketplace/feed/`):** AC18; AC36 tartibi (1 vs 200 baho); jami narx bo‘yicha solishtirish (2 × 200 000 vs total); driver skori arzonni mukofotlamaydi; Q21 yashirish; teskari yo‘nalish lentada yo‘q (AC16, A2 matching orqali); cursor barqarorligi va boshqa query cursor’i `INVALID_CURSOR`; parallel saved search yaratish → limitdan oshmaydi; takror `listing.published` → bitta `saved_search.matched`; bekor qilingan listing → relevance `false`. UT: §8.3 misoli (81.67 / 88.00 / 70.50).
**DoD:** umumiy DoD + ranking UT §8.3 bilan.

---

### Wave 3 davomida bajarilmaydigan (pending) va follow-up’lar
| Egasi | Band | Holat |
|---|---|---|
| **A4** (Q74 tugadi; wave 3 kichik karta kerak — orkestrator) | (1) `arrive_at_pickup` shu tranzaksiyada `booking.driver_arrived {service_type, trip_id, arrived_at}` event’i (Q44 “Keldim”); (2) trip `complete`/`cancel`da `tracking.service.close_sessions_for_trip` (A6 eksporti, lazy); (3) nizo hal bo‘lgach kechiktirilgan capture’ni qayta baholash (U8) | rejalashtirilmagan |
| **A10a + A4** | Wave 2.1 follow-up (b): append-only jadvallar grant’lari (`booking_proof_reissues`, `booking_status_history`, `booking_proof_attempts`, `feature_flag_changes`, `corridor_price_band_changes`) — wave 3 da **rejalashtirilmagan**; wave 3 append-only jadvallari (`dispute_evidence`, `contact_strikes`, `tracking_point_receipts`) shu ro‘yxatga qo‘shiladi | pending |
| **A10a** | (c) `db_roles` detektori helper ichidagi `current_setting()`ni ko‘rmaydi — pending; wave 3 worker vazifalarini ulash (A6/A7/A12/A5 hisobotlaridagi ro‘yxat), tracking partition funksiyasi uchun `expected-guarded-tables` | pending |
| **A1 / foydalanuvchi** | W21-4: trip-offer parcel `receiver` majburiyligi — foydalanuvchi qarori kutilmoqda; P9 `rating_bucket`/`completed_bookings` — A12 `reputation_summaries` va bucket chegaralari qaroridan keyin | pending |
| **H0** | Chat rasm upload turi (`chat_photo`, private) — `CHAT_ATTACHMENTS_ENABLED` yoqilishidan oldin | pending |
| **A0a** | Integratsiya: routerlar (tracking, communications, trust_support, marketplace.feed), `WIRED_MODEL_MODULES`, `configure_v2_ports()` → `trust_support.service.register_booking_hooks()`, ADR-0021 (MFA) matni, env namunalari (`ELCHI_SUPPORT_*`), `cash_receipts.dispute_id` FK qarori | wave 3 yakunida |

### Foydalanuvchi qarorlari kutilayotgan savollar (U1–U8)
- **U1** Parcel jo‘natuvchisi pickup’gacha haydovchi jonli joylashuvini ko‘radimi? Q44 “tracking oynasida jonli joylashuv” (accept → start) deydi; spec §10.6 va STATE_MACHINES grant qoidasi parcel uchun oynani pickup’dan ochadi. Kontrakt hozir konservativ: pickup’dan (`PARCEL_NOT_PICKED_UP`).
- **U2** (integrator qarori, e’tiroz bo‘lsa) v2 in-app inbox legacy `notifications`da emas, `notification_deliveries`da — v1 Android ro‘yxati o‘zgarmasligi uchun.
- **U3** Push provayderi (Web Push VAPID / FCM / Expo push) va xom token/subscription saqlash usuli (shifrlash kalit/kutubxona yoki cheklangan ochiq ustun) — yangi dependency, ADR kerak; ungacha faqat in-app.
- **U4** Pilot default’lari: strike (7 kunda 1 bepul moslik; 30 kunda 3 strike → review), quick-cancel 1 soat, juftlik 30 kunda 2 bekor, chat 20 xabar/daq, bron chat terminaldan 24 soat, saved search 10 ta / 60 kun oyna, push dedup 10 daq, tracking grant TTL 15 daq–24 soat.
- **U5** v1 staff auth identity effektiv rollariga o‘tkazilsinmi (v1 xulqi o‘zgarishi, AGENTS §2)? Doira: faqat `admin_drivers.py` dependency’lari (BR follow-up a) yoki barcha v1 staff yo‘llari (`deps.require_roles` staff rollari). Marketplace rol tekshiruvlari har holda o‘zgarmaydi.
- **U6** Reyting S1/S2 wave 3 da (COVERAGE: W3, AC36) — integrator A12 doirasiga kiritdi; S9–S12 (bloklash/shikoyat/fraud) wave 4 ga. Tasdiq; P9 `rating_bucket` chegaralari.
- **U7** Real support telefoni va ish vaqti matni (§16; 24/7 va’da qilinmaydi).
- **U8** Nizo hal bo‘lgach kechiktirilgan capture: A4 avtomatik qayta baholash job’i yoki finance qo‘lda `finalize_fee` (pilot)?

---

## Wave 3 yakuni: integratsiya (16.09.2026) — PG to‘liq tekshiruvi hali bajarilmagan

### Yetkazilgan ishlar (agent hisobotlari)
| Egasi | Yetkazildi | Migratsiya |
|---|---|---|
| A6 | Tracking K1–K9 (WS `/ws`), sessiya/nuqta/receipt/grant, DEFAULT + kunlik partition’lar va 3 ta SECURITY DEFINER funksiya, `booking_live_state`, `trip_tracking_summary`, `close_sessions_for_trip`, worker funksiyalari | `20260916_0058` |
| A7 | Chat N6–N7, N10–N11; outbox dispatcher (`platform/outbox_dispatch.py`), recipients/auditoriya, in-app inbox N1/N4/N5, device tokens (hash), fake push provider, `chat_activity_for_booking` | `20260916_0059` |
| A12 | `disputes_v2` + hook’lar (`register_booking_hooks`), Q45 strike/review consumer’lari, review navbati, support/SOS, reyting va reputatsiya, v2 `DELETE /me`, v1 o‘chirishga trust tekshiruvi | `20260916_0060` |
| A5 | Lenta M1/M2 (ranking §8.2/§8.4), saved searches M3–M5 + limit guard, `listing.published` consumer, relevance check | `20260916_0061` |
| A4 (kichik karta) | `booking.driver_arrived`, trip terminalda tracking yopish, nizo yopilganda `mark_finance_review_after_dispute` | — |

### Integrator tahrirlari
- `app/modules/__init__.py::WIRED_MODEL_MODULES` += tracking, communications, trust_support, marketplace.feed modellari.
- `app/api/v2/router.py`: 4 router ulandi; `configure_v2_ports()` → `trust_support.service.register_booking_hooks()` (**Q74 fallback ishlayotgan ilovada tugaydi**; hook yo‘q jarayonda Q74 amal qiladi).
- Kontrakt: A7 DTO’lari va A5 `FeedPageMeta`/`FeedMatchDTO`/`FeedReputationDTO`/`TripAvailabilitySummaryDTO` `dto.py`ga (modul nusxalari bilan tenglik testi `tests/contracts/test_wave3_integration.py`); `EventType.DISPUTE_ESCALATION_DUE` (staff); `events.CLIENT_HIDDEN_DISPUTE_TYPES = {commission}`; `feed.MATCH_SCOPE_CONFIRMED_STOPS`.
- **A0b fayli (A0b bo‘sh):** `tests/pg/test_migrations_smoke.py::_compare_with_postgis_types` — `c.relkind IN ('r', 'p')` (partition’langan `tracking_points`).
- **H1 testlari (H1 bo‘sh):** `tests/test_admin_driver_verification.py::test_stage_15_does_not_add_forbidden_fields` va `tests/test_notifications.py::test_stage_16_does_not_add_external_notification_or_tracking_fields` — 1-bosqich “chat/tracking jadvali yo‘q” tekshiruvi faqat legacy v1 modellariga (`app.models.*`) qaratildi. Sabab: chat va tracking — 2-bosqich doirasi (spec §10, §16, ADR-0012/0020), v2 modellari bir jarayonda `Base.metadata`ni bo‘lishadi; maqsad (v1 modellari/javoblariga bunday maydon qo‘shilmasin) saqlandi.
- Hujjatlar: DATA_MODEL §7 (haqiqiy jadvallar), §5 `…_0062` wave 3.1 rezervi (A13 → 0063, A10b → 0064/0065); API_V2_CONTRACT §12a; ADR-0021 (staff MFA, **Proposed**).

### Kartalardan chetlanishlar
| # | Egasi | Chetlanish | Baho |
|---|---|---|---|
| W3-1 | A12 | Qo‘shimcha `contact_filter_hits` jadvali (Q45 oyna sanog‘i) | Qabul; DATA_MODEL §7.3 |
| W3-2 | A6 | K1 ko‘rinmas/boshqaning trip’i → `404`; sessiya yaratishda trip bo‘yicha advisory lock | Qabul (ADR-0005 ko‘rinmaslik qoidasi) |
| W3-3 | A6 | K4 staff javobida oyna yopiq bo‘lsa ham `last_point` | **Ochiq savol** (§10.6 “operatsion vazifa doirasi”) |
| W3-4 | A7 | Relevance va recipient qoidalari implementatsiyasi (competitor, staff-only per-user yetkazilmaydi) | Kartaga mos; BR ko‘rib chiqsin |
| W3-5 | A12 | Commission nizosi event’i umuman chiqarilmaydi; eskalatsiya event’i yo‘q | Kontrakt endi `CLIENT_HIDDEN_DISPUTE_TYPES` va `DISPUTE_ESCALATION_DUE`ni beradi → A12 follow-up |
| W3-6 | A4 | `CommissionReviewReason.DISPUTE_RESOLVED` so‘rovi | Wave 3.1 (DB CHECK forward migration, `…_0062` rezervi); hozir mavjud sabab |

### Follow-up’lar
| Egasi | Band |
|---|---|
| **A10a** | Barcha wave 3 worker vazifalarini ulash (A6 `emit_stale_signals`, `emit_window_opened_signals`, `retention_task`; A7 `dispatch_outbox`, `push_delivery_task`; A12 `emit_dispute_escalations`, `publish_due_ratings`, `refresh_reputation_snapshots`; A5 `expire_saved_searches`); A6 SECURITY DEFINER funksiyalariga app roli `EXECUTE` grant’i; append-only grant’lar (wave 2.1 (b) ro‘yxati + `tracking_point_receipts`, `dispute_evidence`, `contact_filter_hits`, `contact_strikes`); `chat_messages` uchun expected-guarded-tables tekshiruvi; (c) detektor cheklovi |
| **A7** | `communications/schemas.py` DTO’larini `app.contracts.dto`dan import qilish (nusxani olib tashlash) |
| **A5** | `feed/schemas.py` `FeedPageMeta`/`FeedMatchDTO`/`FeedReputationDTO`/`TripAvailabilitySummaryDTO` — kontraktdan import |
| **A12** | `dispute.escalation_due` event’ini chiqarish; commission nizosi event’ini `CLIENT_HIDDEN_DISPUTE_TYPES` qoidasi bilan driver/staff’ga chiqarish |
| **A4** | Wave 3.1: `DISPUTE_RESOLVED` sababi + `…_0062` migratsiyasi (integrator stub’idan keyin) |
| **A4 / A12 (wave 3.1)** | A4 `bookings.service.resolve_contested_cash_receipt(...)` (`contested → acknowledged / unpaid`) qo‘shdi; A12 uni S8 `resolve` (payment nizosi) ichida chaqiradi. STATE_MACHINES §6/§8 buni **nizo qarori** orqali talab qiladi, alohida HTTP yo‘lni emas — shuning uchun B13 `resolve_paid`/`resolve_unpaid` `OperatorBookingCommand`ga **qo‘shilmadi**. Operatorga nizosiz HTTP buyruq kerak bo‘lsa: enum + `OPERATOR_COMMAND_CAPABILITY` (`ops.dispute_resolve`) + A4 wiring |
| **Test izolyatsiyasi (integrator, bajarildi)** | `configure_v2_ports()` A12 hook’larini modul-global holatda ro‘yxatdan o‘tkazadi — ilovani ishga tushirgan test ularni keyingi testlarga “oqizardi” (A4: 7 ta bookings testi `captured` oldi). Yangi `tests/conftest.py` autouse fixture har testdan keyin `set_blocking_dispute_probe(None)` va `set_payment_dispute_opener(None)` qiladi (bookings servisi yuklangan bo‘lsagina). **Qoida:** hook kerak bo‘lgan test ularni o‘zi (test yoki fixture ichida) ro‘yxatdan o‘tkazadi; A4 `tests/pg/bookings/conftest.py::bw` reset’i qoladi. To‘liq PG ishga tushirishda wallet, ops, v1 o‘chirish va mounted integratsiya suite’lari shu jihatdan kuzatiladi |
| **H0** | `.env.example`/`.env.production.example`: `ELCHI_TRACKING_PUBLIC_URL_TEMPLATE`, `ELCHI_SUPPORT_PHONE`, `ELCHI_SUPPORT_HOURS_TEXT`; chat va nizo dalili uchun private upload turi |
| **BR / foydalanuvchi** | A6 GPS retention: ochiq nizo bo‘lsa ham xom nuqtalar 7 kundan keyin o‘chadi (§10.7 dalil nusxasi yo‘q); W3-3; U1–U8; W21-4 (trip-offer parcel `receiver`) |
| **A0a** | ADR-0021 foydalanuvchi qaroridan keyin Accepted; to‘liq PG tekshiruvi (orkestrator ruxsatidan keyin) |

### Wave 3 yakuniy tekshiruv (integrator, ketma-ket, 16.09.2026)
PG: vaqtinchalik `elchi-final-pg` (`elchi-postgis:16.15-3.5.3-trixie`, test compose bilan bir xil env/initdb, `127.0.0.1:45440`), `ELCHI_TEST_PG_REQUIRED=1`; umumiy stack (45432) ishlatilmadi; tugagach konteyner o‘chirildi.

| # | Buyruq | Natija |
|---|---|---|
| 1 | `py -m alembic heads` | `20260916_0061 (head)` — bitta |
| 2 | toza DB `alembic upgrade head` ×2 | 1-marta 59 migratsiya, 2-marta 0 (no-op); `current` = `20260916_0061` |
| 3 | `py -m pytest tests/contracts -q` | 390 o‘tdi |
| 4 | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q` | **1865 test: 1865 o‘tdi, 0 failure, 0 error, 0 skip** (612 s). Taqsimot: `tests/pg` 706, contracts 390, `tests/modules` 307, v1/boshqa 462 |
| 5 | `py -m pytest -m pg --collect-only` | 565 `pg` markerli test (70 fayl) — 4-banddagi ishga tushirishda qatnashgan |
| 6 | Drift/migratsiya smoke | umumiy ORM + geometry drift, geo/communications/tracking/trust_support/feed schema drift, idempotent upgrade testlari — hammasi o‘tdi |
| 7 | OpenAPI | v1 **93** (wave 3 da v1 router/schema fayllari o‘zgarmagan); v2 **131**; prefikssiz 2; takroriy operationId, method+path to‘qnashuvi, soyalangan yo‘l yo‘q; WebSocket `/api/v2/ws` |
| 8 | `py -c "import app.main"` | ok |

### Wave 3 BR tuzatish raundi (16.09.2026) — yopildi
| Band | Egasi | Holat / xulq |
|---|---|---|
| L10 | A6 | **Bajarildi:** grant `valid_from` = kuzatuv oynasi ochilish vaqti; oyna ochilishidan > 24 soat oldin grant so‘rovi → `400 VALIDATION_ERROR` `details {reason: "grant_too_early", issuable_from}` |
| L1 | A7 | **Bajarildi:** trip tracking event’lari (`tracking.stale`, `tracking.window_opened`) mijozga faqat uning bronining kuzatuv oynasi ochiq bo‘lganda yetkaziladi |
| L2, L9 | A5 | **Bajarildi.** L2: `POST /saved-searches` `side=requests` uchun `proposal.submit_as_driver` shart (mijoz → 403 `CAPABILITY_REQUIRED`, bloklangan driver → `DRIVER_NOT_ELIGIBLE`); `listing.published` consumer capability’si yo‘q egani o‘tkazib yuboradi, `saved_search.matched` relevance check push oldidan qayta tekshiradi. L9: lenta offer `ready_to_accept` `trips.service.assert_vehicle_eligible_for_new_booking` o‘tishini ham talab qiladi (tasdiqlanmagan mashina — offer ko‘rinadi, `ready_to_accept=false`). Testlar: `test_l2_requests_saved_search_needs_driver_capability_at_create_and_notify`, `test_l9_unapproved_vehicle_offer_is_not_ready_to_accept` |
| M2 | A4 | **Bajarildi:** ro‘yxatdan o‘tgan probe ochiq bloklovchi nizo ko‘rsatsa B13 `finalize_fee` (capture ham, release ham) → `409 INVALID_STATE_TRANSITION` `details.reason = "blocking_dispute_open"`; probe yo‘q (Q74) yo‘li o‘zgarmagan |
| Cash resolve | A12 + A4 | **Bajarildi:** `payment` nizosi `resolve` → `bookings.service.resolve_contested_cash_receipt`: `paid_confirmed` → `acknowledged`, `unpaid_confirmed` → `unpaid`; boshqa `resolution_code` va `reject` → `contested` qoladi. **Kontrakt bo‘shlig‘i (follow-up):** `DisputeCommand`da aniq naqd natija maydoni yo‘q |
| M3 | A12 | **Bajarildi:** SOS hech qachon `429` emas — takroriy bosish shu bron (yoki bronsiz) uchun ochiq hal qilinmagan SOS ticket’ni qaytaradi (201), `support_tickets.press_count` + `last_pressed_at` (0060), staff qayta xabardor qilinadi; oddiy support ticket’lar soatiga 5 limitda |
| L4 | A12 | **Bajarildi:** commission nizosi event’lari chiqariladi (mijoz nusxasi `payload_for_audience` bilan tashlanadi); `dispute.escalation_due` har nizoga bir marta |
| L6 | H1 (A12 orqali) | **Bajarildi:** `account_deletion_service.schedule_upload_removal_after_commit` — fayllar faqat root `after_commit`da o‘chiriladi, rollback’da bekor (v1 va v2 `DELETE /me`) |
| L7 | A12 | **Bajarildi:** faqat `proof_code` kategoriyali mosliklar strike/review sanog‘iga kirmaydi (orkestrator default’i — foydalanuvchi tasdig‘i kutilmoqda) |
| L8 | A12 | **Bajarildi:** juftlik bekor qilish signalining subyekti — bekor qilgan tomon |
| ADR-0021 | A12 / A0a | Staff MFA rejasi A12 rejasi bilan moslashtirildi (tahdid modeli, TOTP + WebAuthn, SMS rad, ikkinchi super_admin tasdig‘i, 10 tiklash kodi, token ≤15 daq / refresh ≤8 soat, 5 daq step-up, 3 jadval, 3 bosqichli rollout) — holat **Proposed** |

---

## Wave 3.1 (16.09.2026) — 3-to‘lqin follow-up’lari

Doira: 3-to‘lqin yakunidagi follow-up jadvali (A10a, A4/A0a, A7, A5, H0) + foydalanuvchi qarori kutilayotgan
uchta band (M1, U5, W21-4 parcel receiver). Muzlatilgan `android-app/` va `frontend/` tegilmagan.

### Yetkazilgan ishlar
| Egasi | Yetkazildi | Migratsiya |
|---|---|---|
| A10a | Wave 3 worker vazifalari ulandi: `SERVICE_JOBS` += `tracking.emit_stale_signals`, `tracking.emit_window_opened_signals`, `trust_support.emit_dispute_escalations`, `publish_due_ratings`, `refresh_reputation_snapshots`, `marketplace.expire_saved_searches`, `communications.dispatch_outbox` (oxirgi — shu raundda yozilgan event’lar shu raundda jo‘naydi); `LOCKED_MODULE_TASKS` += `tracking.retention`, `communications.push_delivery`. Har biriga interval env o‘zgaruvchisi | — |
| A10a | Grant sinflari to‘ldirildi (`scripts/db_roles.py`): append-only (wave 2.1 (b) ro‘yxati + `dispute_evidence`, `contact_filter_hits`, `contact_strikes`, `tracking_points` **va partition’lari**), yangi **no-update** sinfi (`tracking_point_receipts` — retention o‘chiradi, hech kim yangilamaydi), no-delete (`chat_messages`, `tracking_sessions`, `tracking_grants`, `disputes_v2`, `ratings_v2`, `support_tickets`, `trust_review_items`), A6 SECURITY DEFINER funksiyalariga aniq `EXECUTE`, 0063 ACL helper’iga `REVOKE` (owner-only) | — |
| A10a | Guard detektori (c) yopildi: `GUARDED_TABLES_SQL` endi funksiya **chaqiruvlari** bo‘ylab rekursiv yuradi (`\m<nom>\s*\(` — satr ichidagi nom chaqiruv hisoblanmaydi). Aniqlangan to‘plam o‘zgarmadi (4 jadval); `chat_messages` tekshirildi — sessiya holatini o‘qimaydi, shuning uchun ro‘yxatga kirmaydi (izoh faylda) | — |
| A4 | `CommissionReviewReason.DISPUTE_RESOLVED`; `mark_finance_review_after_dispute` shu sababni yozadi (Q74 yo‘li o‘zgarmadi) | `20260916_0062` |
| A4 + A12 | `DisputeCommand.cash_outcome` (`enums.CashResolutionOutcome`): naqd natija nizo qarorining o‘z maydoni. Zid `resolution_code` → 400; `contested` kvitansiyali payment nizosini natijasiz yopib bo‘lmaydi; audit qatorida `cash_outcome`, `start_review`da operator izohi | — |
| A12 + A4 | v2 nizo qarori **admin+** (`ops.dispute_decide`); operator `start_review` va izoh bilan qoladi. `resolve_contested_cash_receipt` ham shu capability’ni talab qiladi | — |
| A6 + A12 | **M1(a):** nizo ochilganda safar xom GPS’i hold ostiga olinadi, retention nuqtalarni `tracking_evidence_points`ga ko‘chiradi, nusxalanmagan hold’li partition **tashlanmaydi**; nizo yopilgach hold bo‘shatiladi va 30 kundan keyin nusxa o‘chadi | `20260916_0063` |
| A6/A10a | Yangi kunlik partition ota jadval ACL’ini meros oladi (`tracking_points_apply_parent_acl`) — append-only sinfini partition nomi bilan aylanib o‘tib bo‘lmaydi | `20260916_0063` |
| A7 / A5 | `communications/schemas.py` va `feed/schemas.py` DTO nusxalari olib tashlandi — kontrakt sinflari re-eksport qilinadi | — |
| H0 | `.env.example` va `app.env.example`: `ELCHI_TRACKING_PUBLIC_URL_TEMPLATE`, `ELCHI_SUPPORT_PHONE`, `ELCHI_SUPPORT_HOURS_TEXT` + worker interval o‘zgaruvchilari. Yangi private upload turlari: `dispute_evidence` (S6 fayllari `resolve_attachment` bilan **yuklovchiga bog‘lanadi** — boshqaning faylini dalil sifatida ilib bo‘lmaydi) va `chat_photo` (`CHAT_ATTACHMENTS_ENABLED` yoqilgunicha 403) | — |
| A1 | **W21-4:** trip-offer parcel taklifida mijoz `receiver`ni berishi majburiy (counter oldingi qabul qiluvchini saqlaydi); `pick_up` qabul qiluvchisiz rad — oxirgi himoya | — |
| H1 | **U5:** `admin_drivers.py` dependency’lari effektiv staff rollarini (`users.role` + faol `user_roles`) ishlatadi; Q3 saqlanadi (marketplace akkaunt staff bo‘lmaydi), status kodlari va matnlar o‘zgarmagan | — |

### Qo‘llangan qarorlar — **tasdiqlangan (16.09.2026)**
Foydalanuvchi tasdig‘idan keyin AGENTS.md §3 ga **Q77–Q86** sifatida yozildi: M1 → (a) dalil nusxasi (Q77);
v2 nizo qarori admin+ va `cash_outcome` maydoni (Q78); W21-4 parcel receiver (Q79); U5 faqat `admin_drivers.py`
(Q80); U1 pickup’dan keyin (Q81); U3 faqat in-app (Q82); U4 pilot sonlari (Q83); U8 finance qo‘lda (Q84);
L7 faqat mask (Q85); W3-3 xodim oxirgi nuqtasi (Q86).

### Ochiq qolgan bandlar
| Band | Holat |
|---|---|
| U6 `rating_bucket` chegaralari | Wave 3.1 da **o‘zgarmadi**: `ListingOfferDTO.rating_bucket` `null` (sun’iy reyting yo‘q). Chegaralar foydalanuvchi qarori |
| U7 real support telefoni/ish vaqti | Env o‘zgaruvchilari tayyor, qiymat yo‘q → S13 `available=false`. Passenger yoqilishidan oldin majburiy |
| U3 push provayderi | Faqat ilova ichida; `push_delivery` vazifasi ulandi, provayder o‘chiq bo‘lsa DB’ga tegmaydi |
| ADR-0021 (staff MFA) | **Proposed** — foydalanuvchi javobi kutilmoqda (kutubxona, step-up ro‘yxati, bitta super_admin holati) |
| Dalil fayllarini ko‘rsatish | `dispute_evidence` fayllari saqlanadi va yuklovchiga bog‘lanadi; ularni imzolangan havola bilan ko‘rsatish hali yo‘q (keyingi wave) |

---

## Wave 4 kartalari (16.09.2026) — A13, A8, A9

Wave 4 spec §12, §16, §19.3, §20 va API_V2_CONTRACT §13 ga tayanadi. Muzlatilgan `android-app/` va `frontend/`
tegilmaydi; stage-2 klienti — `mobile-app/` (ADR-0010).

### A13 — Operations va growth (backend) · **wave 4a**
**Egalik:** `app/modules/operations/**`, `tests/pg/operations/**`, `tests/modules/operations/**`;
migratsiya `alembic/versions/20260916_0064_operations_share_links_kpi.py`; `scripts/export_openapi.py`.

**Talablar (API_V2_CONTRACT §13):**
1. **O1–O3 share link (§20.2):** e’lon egasi ochiq listing uchun havola yaratadi (`ShareLinkCreate {channel, ttl_hours}`);
   token `crypto.new_secret_token`, bazada faqat SHA-256 (ADR-0018), URL va matn bir marta qaytariladi. `DELETE` — revoke.
   Ommaviy sahifa (`GET /public/listings/{token}`) **PII’siz**: yo‘nalish nomlari, sana/oyna, jami narx, ochiqlik holati,
   CTA. Muddati o‘tgan/revoke qilingan/yopilgan listing → `404` (token mavjudligi oshkor qilinmaydi).
2. **O4 ops navbatlari (§16):** mavjud modul navbatlarini (A4 bookings, A12 nizo/ticket/review) **servis funksiyalari orqali**
   yig‘adi; yangi jadval yo‘q. `OpsQueueItemDTO {queue, item_type, item_id, corridor, age_minutes, summary}` — summary’da
   telefon/ism yo‘q.
3. **O5 KPI (§20.4):** `kpi_daily` — worker kunlik hisoblaydi; endpoint faqat shu jadvalni o‘qiydi. Har metrika
   **son + maxraj** bilan (kichik n’da foiz yolg‘iz ko‘rsatilmaydi). Faqat bizda **haqiqatan o‘lchanadigan** metrikalar
   yoziladi; o‘lchanmaydigani (masalan `search_with_match_rate` — qidiruv jurnali yo‘q) **umuman chiqmaydi**, nol emas.
4. **O6 SLO (§19.3):** tracking freshness saqlangan nuqtalardan hisoblanadi va **barcha safarlar** bo‘yicha beriladi
   (oflayn safarlar yashirilmaydi). API p95 kechikishi ilova ichida o‘lchanmaydi → maydon `null` va `measured: false`.
5. **O7 operator nomidan e’lon (§20.2):** A1 `create_listing(..., created_by_operator_id, consent_reference)` ustida yupqa
   qatlam; `consent_reference` majburiy, audit qatori yoziladi.
6. **OpenAPI eksporti (ADR-0010 §4):** `scripts/export_openapi.py` faqat v2 sxemasini yozadi (A8 `npm run gen:api` uchun).

**Qabul:** token bazada ochiq saqlanmaydi; ommaviy sahifada ism/telefon/aniq manzil yo‘q; KPI’da o‘lchanmagan metrika
yo‘q; SLO’da o‘lchanmagan qiymat `null`; O7 auditda haqiqiy ega va rozilik havolasi bilan; `alembic heads` bitta.

### A8 — Mijoz UI va umumiy API klient · **wave 4b (doira tasdiqlanishi kerak)**
`mobile-app/` ichida v2 ekranlari: generated tiplar (`openapi-typescript`), e’lon/taklif/bron, tracking viewer,
recipient share sahifasi, chat, yordam. Chegara: qo‘lda DTO yo‘q, mijozga komissiya/balans maydonlari chiqmaydi (Q16).

### A9 — Haydovchi UI va operator paneli · **wave 4b (doira tasdiqlanishi kerak)**
Haydovchi jadvali/trip manifest/proof, wallet va hold ko‘rinishi; operator navbatlari, nizo va moliya ekranlari.
Chegara: “istalgan statusga o‘tkaz” tugmasi yo‘q; hisoblangan komissiya real kirim sifatida ko‘rsatilmaydi.

### Wave 4a yakuni — A13 yetkazildi (16.09.2026)
| Band | Holat |
|---|---|
| Migratsiya `20260916_0064` | `share_links` (+ `share_links_guard`), `kpi_daily` (`UNIQUE NULLS NOT DISTINCT`); `alembic heads` = bitta |
| O1–O3 share link | Token faqat javobda, bazada SHA-256; listingda ko‘pi bilan 5 faol havola; `paused` listing ham ulashiladi, lekin sahifa “yopiq” deydi; noma’lum/bekor/muddati o‘tgan token → 404; ochilish hisoblagichi (ko‘ruvchi haqida hech narsa yozilmaydi) |
| O4 navbatlar | `OpsQueue` 8 ta navbat — A4 va A12 servis funksiyalari orqali; yangi jadval yo‘q; `ops.view` shart |
| O5 KPI | 6 ta o‘lchanadigan metrika sanoq juftida; `denominator = 0` → `value: null`; `< 30` → `small_sample`; o‘lchanmaydigan 4 metrika `missing_metrics`da nomlanadi |
| O6 SLO | `tracking_freshness` (barcha safarlar, `sample_size` bilan); kechikish ko‘rsatkichlari `measured: false` |
| O7 nomidan e’lon | `consent_reference` majburiy; ega o‘zgarmaydi; audit qatori |
| Worker | `operations.refresh_kpi_daily` (soatiga; oxirgi 3 tugagan kun), `operations.expire_share_links` |
| OpenAPI eksport | `scripts/export_openapi.py` (`--check` CI uchun); `mobile-app/src/api/generated/openapi-v2.json` commit qilindi (138 v2 operatsiyasi) |
| Kontrakt | `EmptyDTO` endi kontraktda (tracking va feed nusxalari olib tashlandi); yangi `contracts/operations.py` |

### Wave 4b — A8 mijoz ekranlari (16.09.2026, foydalanuvchi qarori: avval mijoz, admin panel ichida, o‘rnatishga ruxsat)
| Band | Holat |
|---|---|
| Tip generatsiyasi | `openapi-typescript` **o‘rnatildi va lockfile’da pin qilindi** (ADR-0010 §3, faqat tiplar, runtime kod yo‘q); `npm run gen:api`; `openapi-v2.json` va `v2.ts` commit qilindi |
| Typed HTTP | `src/api/v2/http.ts` — v1 envelope/refresh qatlamini qayta ishlatadi, `Idempotency-Key`, `warnings`/`meta`; bazaviy URL `/api/v1` → `/api/v2` (yoki `VITE_API_V2_BASE_URL`) |
| API modullari | `marketplace.api.ts` (koridor/bekat, e’lon, taklif, accept, feed), `bookings.api.ts` (bron, kodlar, tracking, chat, share link, support, ommaviy sahifa) — barcha tiplar `Schemas[...]` dan |
| Utillar | `v2Format.ts` (minor → so‘m, `Asia/Tashkent`, AC01 narx yozuvi, freshness), `v2Errors.ts` (v2 xato kodlari o‘zbekcha, offline holati alohida) |
| Ekranlar (`/v2`) | So‘rovlarim ro‘yxati; yangi so‘rov (yo‘lovchi/pochta, pochta uchun jo‘natuvchi+qabul qiluvchi majburiy — W21-4); e’lon tafsiloti va haydovchi takliflari (accept `proposal_version_id` + `terms_version` bilan, AC04); bron tafsiloti (holat, narx, kodlar, kuzatuv, chat, bekor qilish); yordam |
| Ommaviy sahifa | `/e/<token>` — autentifikatsiyasiz, PII’siz (O3) |
| Halollik | Mijozga komissiya/balans ko‘rsatilmaydi (Q16); GPS bo‘lmasa marker chizilmaydi, “signal yo‘q” deyiladi (AC27/AC32); reytingsiz haydovchi “yangi” (AC36); kod faqat yuzma-yuz ogohlantirishi (Q65); telefon faqat server ruxsat berganda (Q44); davlat raqami maskalangan holda (Q64) |
| Tekshiruv | `npm run lint` (tsc) va `npm run build` o‘tdi; `tests/test_mobile_v2_client_contract.py` — commit qilingan sxema ilova bilan bir xil, klientning har yo‘li real v2 yo‘li, klient qatlamida qo‘lda DTO yo‘q |
| **Brauzerda qo‘lda sinov (16.09.2026)** | Chromium (Playwright), demo backend + seed (sintetik koridor, tasdiqlangan mashina, safar, pul solingan hamyon). Oqim: OTP bilan kirish → `/v2` → yo‘lovchi so‘rovi (2 × 200 000 = **400 000 so‘m**) → e’lon qilish → ulashish havolasi → `/e/<token>` ommaviy sahifa → haydovchi taklifi (anonim “Haydovchi #1”, “Yangi haydovchi (baho yo‘q)”) → qabul qilish → bron ekrani (maskalangan raqam `01****AA`, “Telefon: xizmat boshlanganda ochiladi”, chiqish kodi + yuzma-yuz ogohlantirish, kuzatuv oynasi yopiq izohi, chat) → bronlar va yordam bo‘limlari. Yakuniy o‘tish: **xatosiz** (konsol xatosi, 4xx va PII sizishi yo‘q) |
| Sinov topgan va tuzatilgan kamchiliklar | (1) sahifa yangilanganda ekran yo‘qolardi → ekran endi URL’da (`/v2/listing/<id>`, brauzer “Orqaga” tugmasi ishlaydi); (2) taklif “qabul qilish” tugmasi chiqmasdi (`state` qiymati `open`, `active` emas); (3) kuzatuv oynasi ochilmaganda **qizil xato** ko‘rsatilardi → endi “Oyna yopiq, … dan ko‘rinadi”; (4) kod yorlig‘i `boarding_code` xom ko‘rinardi → “Chiqish kodi”; (5) chat `contact.chat_thread_id` bo‘sh bo‘lgani uchun yopiq qolardi → bron faol bo‘lsa ochiq (backend follow-up: A4/A7 shu maydonni to‘ldirsin); (6) `cancellation_policy_summary` inglizcha edi va komissiyani tilga olardi → o‘zbekcha va komissiyasiz (Q16) |
| Bajarilmagan (4b qolgan qismi) | A9 operator/haydovchi ekranlari admin panel ichida; avtomatlashtirilgan UI testi repo’da yo‘q (Playwright skripti scratchpad’da); push, saqlangan qidiruv, reyting berish, nizo va amendment ekranlari hali yo‘q |

### Wave 4c — A9 operator ekranlari (admin panel ichida, 16.09.2026)
Foydalanuvchi qarori: operator ekranlari **admin panel ichida** (`mobile-app` `/admin`), mijoz ekranlaridan keyin.

| Band | Holat |
|---|---|
| Sessiya | `src/api/v2/http.ts` endi ikki auditoriyani biladi: mijoz (`elchi_access_token`) va **admin panel** (`elchi_admin_*`). Xodim v1 `staff-login` (username + parol) bilan kiradi, o‘sha JWT v2’da ishlaydi |
| API moduli | `src/api/v2/ops.api.ts` — navbatlar (O4), nizolar (S7/S8), murojaat va ishonch navbati, KPI (O5), SLO (O6), `/me/capabilities`; barcha tiplar kontraktdan |
| Ekranlar | **Operator navbatlari** (8 navbat, modul servislaridan), **Nizolar (v2)** (ro‘yxat + tafsilot + `start_review` / `resolve` / `reject`, naqd natijasi maydoni), **Murojaat va ishonch** (SOS alohida belgilanadi; avtomatik jazo yo‘q izohi), **KPI / SLO** |
| Huquq (Q78) | Tugmalar `/me/capabilities` javobiga qarab: operatorda qaror tugmalari **yo‘q**, “qaror — admin+” izohi bor; admin/super_admin’da bor. Server baribir tekshiradi — panel faqat aks ettiradi |
| Halollik | KPI sanoq juftlari bilan, kichik namuna belgilanadi, o‘lchanmaydigan metrikalar nomi bilan ko‘rsatiladi; SLO’da o‘lchanmaydigan ko‘rsatkich “o‘lchanmaydi” deydi, kechikish maqsadi **soniyada**, freshness foizda |
| **Brauzerda qo‘lda sinov** | Ikki sessiya (operator va admin) bilan to‘liq o‘tdi: operator — qaror tugmalari yo‘q; admin — nizoni hal qildi; navbatlar, murojaatlar, KPI/SLO ekranlari yuklandi. Yakuniy ishga tushirish **xatosiz** |
| Sinov topgan va tuzatilgan | SLO kechikish maqsadi foiz sifatida (“maqsad 100.0%”) ko‘rsatilardi → endi soniyada (`1.00 s`) |
| Ma’lum, tuzatilmagan | v1 admin panelidagi audit jurnali operator uchun 403 qaytaradi (eski v1 xulqi, A9 doirasidan tashqarida); v2 navbat elementidan bevosita bron/nizo kartasiga o‘tish yo‘q; haydovchi ekranlari (A9 ikkinchi qismi) hali yo‘q |

### Wave 4d — A9 haydovchi ekranlari va 4-to‘lqin qoldiqlari (16.09.2026)
Foydalanuvchi topshirig‘i: “keyingi qadam boshlansin va ochiq qolgan 4-to‘lqin qoldiqlari to‘liq bajarilsin”.

| Band | Holat |
|---|---|
| API modullari | `src/api/v2/driver.api.ts` (safarlar, manifest, sig‘im, safar/bron buyruqlari, lenta, taklif, hamyon, amendment qarori) va `src/api/v2/client-extras.api.ts` (xabarlar, saqlangan qidiruv, reyting, nizo) — barcha tiplar `Schemas[...]` dan, qo‘lda DTO yo‘q |
| Haydovchi ekranlari | **Safarlarim** → safar tafsiloti (segment bo‘yicha bo‘sh joy, manifest, safar buyruqlari, bron buyruqlari kod bilan), **So‘rovlar** lentasi (koridor + ikki bekat + sana oralig‘i majburiy) va taklif yuborish, **Takliflarim**, **Balans** (ishlatish mumkin / ushlab turilgan / tasdiq kutayotgan to‘ldirish alohida, W2 so‘rovi) |
| Mijoz qoldiqlari (A8) | Xabarlar (ilova ichida; push yoqilmagani ochiq aytiladi — Q82), saqlangan qidiruvlar (M3), reyting kartasi, nizo kartasi va “Nizolarim”, amendment kartasi, **xizmatni tasdiqlash** (`arrived`/`delivered` → mijoz yakunlaydi, `ACTION_SIDES`) |
| Kontrakt qo‘shimchasi (additiv) | **B9r `GET /bookings/{id}/amendments`** (`app/modules/bookings/{service,api}.py`, ishtirokchilar uchun, migratsiyasiz). Sababi: qarshi tomon javob berishi kerak bo‘lgan o‘zgartirish so‘rovini topadigan yo‘l umuman yo‘q edi — B10/B11 faqat id bilan ishlaydi. v2 operatsiyalari 138 → **139**, v1 **93** (o‘zgarmadi). Test: `tests/pg/bookings/test_lifecycle_pg.py::test_booking_amendments_are_listed_for_participants_only` |
| Amendment ekrani | Bron ekranida bitta karta: ochiq so‘rov holati (“Javob kutilmoqda”), muallif uchun **qaytarib olish**, qarshi tomon uchun **qabul qilish / rad etish**; komissiya farqi faqat server yuborganda (mijoz nusxasida yo‘q — Q16). Haydovchi bronni **manifestdan** ochadi (`/v2/trip/<id>` → “Ochish” → `/v2/booking/<id>`) |
| Admin panel | Navbat elementidan nizo kartasiga bevosita o‘tish (drill-down) qo‘shildi; operator sessiyasida v1 audit jurnali endi so‘ralmaydi (`canReadAuditLogs`, 403 yo‘q) |
| Halollik | Brauzerdan GPS yuborilmaydi — ekran jonli joylashuv haydovchi telefonidan kelishini aytadi (§10.5, ADR-0010 §1); to‘ldirish **so‘rovi** balansdan alohida, “hali balansga qo‘shilmagan”; komissiya “ushlab turiladi”, daromad emas (§9.2); taklif o‘rin band qilmaydi (§5.3); reyting darhol e’lon qilinmasligi aytiladi (§17.2) |
| **Brauzerda qo‘lda sinov (16.09.2026)** | To‘rtta ssenariy, hammasi **xatosiz**: (1) mijoz qoldiqlari + haydovchi lentasi/taklifi/hamyoni; (2) to‘liq xizmat oqimi — `Kutishga o‘tkazish` → `Chiqishni boshlash` → **noto‘g‘ri kod rad etildi** (“Kod noto‘g‘ri”) → to‘g‘ri kod bilan chiqdi → `Yo‘lga chiqish` → `Tushdi` → `Safarni yakunlash`; (3) mijoz xizmatni tasdiqladi va baho qoldirdi; (4) operator/admin paneli regressiyasiz |
| Sinov topgan va tuzatilgan | (0) mijoz so‘rovidan tug‘ilgan bronda o‘rin sonini o‘zgartirish **imkonsiz** (D9, `QUANTITY_MISMATCH`) — endi forma o‘rniga sabab yoziladi, tugma o‘chiq; haydovchi ekrani endi kodlarni so‘ramaydi (`driver_cannot_see_codes` 403 yo‘q); haydovchiga mijozning “bekor qilish” kartasi ko‘rsatilmaydi (`reason_code` mijoznikidir); (1) safar buyrug‘i `start` deb yuborilardi — kontraktda `depart` (400 qaytarardi); (2) haydovchiga `Yakunlash` tugmasi ko‘rsatilardi, lekin `complete` faqat mijoznikidir (403) → tugma olib tashlandi, o‘rniga “Yo‘lovchi safarni tasdiqlashi kutilmoqda” izohi; (3) mijozda xizmatni yakunlash imkoni **umuman yo‘q edi** → bron ekraniga tasdiqlash kartasi qo‘shildi (shusiz reyting ham ochilmasdi); (4) manifestda bron **ikki marta** (chiqish va tushish bekatlarida) chiqib, ikkala joyda ham bir xil tugmalarni berardi → har buyruq o‘z bekatiga bog‘landi; (5) yo‘lovchi broniga pochta buyrug‘i (`Yukni oldim`) taklif qilinardi → xizmat turiga qarab filtr; (6) manifestda holat xom inglizcha (`confirmed`) ko‘rinardi → o‘zbekcha yorliq; (7) `useAsync.reload()` ekranni spinnerga qaytarib, ostidagi kartalar holatini yo‘qotardi (baho yuborilgani ko‘rinmasdi) → yangilashda mavjud ma’lumot ekranda qoladi |
| Ma’lum, tuzatilmagan | Haydovchi “kelmadi” (no-show) xabari ekranda yo‘q — u aloqa urinishlari va dalil talab qiladi (Q7), Android ilovasi/operator navbatida qoladi; amendment faqat **miqdor**ni o‘zgartiradi (oyna, bekat, birlik narx — kontraktda bor, ekranda yo‘q); ochiq amendment haqida xabarnoma yuborilmaydi (event yo‘q) — qarshi tomon bronni ochganda ko‘radi; `contact.chat_thread_id` hali to‘ldirilmaydi (A4/A7 follow-up); avtomatlashtirilgan UI testlari repo’da emas (Playwright skriptlari scratchpad’da) |

---

## Wave 5 (17.09.2026) — A10b (legacy o‘tish) va A11 (acceptance)

Doira: W5 ning ikki egasi — **A10b** (legacy read-only proyeksiya va Q9 timestamp konvertatsiyasi) va **A11**
(AC01–AC44 dalil matritsasi, restore mashqi, SLO). Yo‘l-yo‘lakay yopilgan bandlar: **Q50 launch gate**
(revision lineage) va 4-to‘lqindan qolgan backend bo‘shliqlari (`chat_thread_id`, amendment xabarnomasi,
nizo dalili havolasi). Muzlatilgan `android-app/` va `frontend/` tegilmagan.

### Kartalar

#### A10b — Legacy o‘tish (wave 5)
**Egalik:** `alembic/versions/20260916_0065_*.py`, `…_0066_*.py`; `app/utils/legacy_time.py`;
`app/models/{order,dispute,driver_document,order_offer}.py` (faqat vaqt ustunlari tipi);
`app/modules/operations/{service,api,schemas}.py` O8 qismi; `app/contracts/dto.py` `LegacyOrderViewDTO`;
`scripts/legacy_timestamp_audit.py`; `tests/pg/ops/test_legacy_projection.py`,
`tests/pg/ops/test_legacy_timestamps.py`, `tests/test_v1_v2_isolation_ac39.py`.

**Talablar:** Q4/AC37 (jadval yo‘q, faqat view; qayta qurish dublikat bermaydi; eski fee undirilmaydi),
ADR-0006 §4 (mutatsiya → `409 LEGACY_OBJECT_READ_ONLY`), O8 (`ops.view`, PII yo‘q), Q9 (naive → `timestamptz`
faqat isbotlangan qoida bilan), AGENTS §2 (v1 javob shakli o‘zgarmaydi), AC39 (v1 klient v2 obyektini
ko‘rmaydi va o‘zgartira olmaydi).

#### A11 — Acceptance va dalil (wave 5)
**Egalik:** `scripts/ac_coverage.py`; `COVERAGE_MATRIX.md` §6; restore mashqi dalili; SLO o‘lchovi.
**Talablar:** har AC uchun aniq test/protsedura va bitta ishga tushirishdagi natija; “test bor” ≠ “test o‘tdi”;
dala (Android) AC’lari hech qachon “o‘tdi” deb yozilmaydi.

### Yetkazilgan ishlar

| Egasi | Yetkazildi | Migratsiya |
|---|---|---|
| A10b | **0065 legacy proyeksiya:** `legacy_parcel_orders_v`, `legacy_order_status_history_v`, `legacy_ratings_v`, `legacy_disputes_v`. Jadval ham, backfill ham yo‘q. Har view’da `INSTEAD OF` trigger (`legacy_object_read_only` → 409) **har rol uchun**; ikkinchi qatlam — `db_roles.py` `DEFAULT_READ_ONLY_VIEWS` (app roli DML’ni yo‘qotadi). Pul minor birlikda, `legacy_calculated_fee_minor` — hisoblangan, undirilmagan (§18.2). `unknown_time`/`unknown_dimensions` doimiy TRUE (v1 bunday maydonlarni umuman saqlamagan) | `20260916_0065` |
| A10b | **O8** `GET /api/v2/admin/legacy-orders[/{legacy_order_number}]` (`ops.view`, cursor, `status` filtri) — faqat view’dan o‘qiydi; noma’lum raqam → 404; javobda telefon/ism/manzil yo‘q. Kontrakt: `LegacyOrderViewDTO` | — |
| A10b | **0066 Q9:** 11 ta naive ustun → `timestamptz`. Migratsiya avval **dalil** talab qiladi (har qiymat o‘z qatorining `created_at`/`updated_at` oynasida UTC sifatida o‘qilishi); mos kelmasa **to‘xtaydi** va hech nimani o‘zgartirmaydi. `SET LOCAL TimeZone='UTC'` + `USING`siz `ALTER` — jadval qayta yozilmaydi (filenode testi). 0065 view’lari `pg_get_viewdef`/`pg_get_triggerdef` bilan aynan tiklanadi | `20260916_0066` |
| A10b | **v1 moslik:** `app/utils/legacy_time.py::v1_naive` — 19 ta v1 serializatsiya nuqtasi (orders, disputes, driver_documents) offsetsiz ISO satrni saqlaydi; `created_at`/`updated_at` avvalgidek offset bilan qoladi | — |
| A10b | **AC39:** `tests/test_v1_v2_isolation_ac39.py` — v1 kodi v2 model/repository import qilmaydi va SQL’da v2 jadvalini nomlamaydi (AST tekshiruvi); v2 public id v1 yo‘liga tushmaydi (v1 envelope 400), noma’lum id → 404 | — |
| A0a/A10a | **Q50 launch gate yopildi:** `alembic_revision_lineage` (`0067`) + `alembic/env.py` yozuvchisi + readiness’dagi `classify_with_lineage`. Eski image (DB revisiyasini bilmaydigan script graph) endi `ahead` (200 `degraded`) qaytaradi, 503 emas; DB o‘z head’ini yozmagan yoki boshqa shoxda bo‘lsa — avvalgidek 503. App roli jadvalni faqat o‘qiydi | `20260916_0067` |
| A4/A7 | **W4 qoldig‘i:** `BookingDTO.contact.chat_thread_id` — A7 read-only lookup (`communications.service.register_booking_hooks`, integrator `configure_v2_ports`da ulaydi); chat ochilmagan bo‘lsa `null` qoladi (bronni ochish thread yaratmaydi) | — |
| A4 | **W4 qoldig‘i:** `booking.amendment_requested` / `booking.amendment_decided` event’lari (allowlist payload, komissiyasiz — N2/Q16). Qarshi tomon endi ochiq o‘zgartirish so‘rovidan xabardor bo‘ladi | — |
| A12/H0 | **Wave 3.1 ochiq bandi yopildi:** `DisputeEvidenceDTO.file_urls` — nizo dalili fayllari uchun qisqa muddatli imzolangan havolalar (faqat javob allaqachon avtorizatsiya qilingan tomonga; `app/utils/file_access.py` qoidasi) | — |
| A9 (integrator) | **Admin panelda “Legacy (v1) arxiv” ekrani** (`mobile-app` `/admin`): O8 ro‘yxati, holat filtri, yo‘nalish, yakuniy narx, “hisoblangan komissiya (undirilmagan)”, `unknown_*` bayroqlari izohli matn bilan. Tugma **umuman yo‘q** — v1 obyekti v1 da yakunlanadi | — |
| A10a | **Restore mashqi tuzatildi:** `scripts/restore_drill.sh` biznes tekshiruvi `bookings.status` (mavjud emas) o‘rniga `service_status`/`commission_status`ni o‘qiydi, legacy qator v2 jadvaliga tushmaganini (Q4), proyeksiya qatorlari sonini va lineage yozuvlarini tekshiradi | — |

### Q9 dalili (0066 nima uchun UTC deb hisoblaydi)

| Savol | Javob | Manba |
|---|---|---|
| Qaysi ustunlar naive? | 11 ta: `orders` (7), `disputes.resolved_at`, `driver_documents.reviewed_at`, `order_offers.shown_at`/`responded_at` | `information_schema.columns` (head 0064) |
| Ularni kim yozgan? | Faqat v1 servislari, **hammasi** `datetime.now(timezone.utc)` bilan (aware UTC). Git tarixida bu ustunlarga `utcnow()` yozilgan versiya yo‘q (`utcnow` faqat `auth_service`da, u yerdagi ustunlar `timestamptz`) | `app/services/*.py`, `git log -S` |
| Sessiya mintaqasi qanday edi? | `docker-compose.prod.yml`: `TZ: UTC`, `timezone=UTC`, `log_timezone=UTC`; 1-bosqich `postgres:16-alpine` ham konteynerda UTC; ilova `create_engine`da mintaqa o‘rnatmaydi | prod/test compose, `app/db/session.py` |
| Bu taxmin qatorlar bilan tasdiqlanganmi? | Ha: har qiymat o‘z qatorining `created_at`/`updated_at` (timestamptz) oynasi ichida UTC sifatida o‘qilishi kerak (±1 soat). +5 soatli (Asia/Tashkent) talqin bu oynadan chiqadi va **rad etiladi** | `scripts/legacy_timestamp_audit.py`, `0066` ichidagi guard |
| Aralash semantika bo‘lsa nima bo‘ladi? | Migratsiya to‘xtaydi (faqat sonlar chiqadi), schema o‘zgarmaydi, alembic head oldingi revisiyada qoladi — forward fix va qaror kerak | `test_0066_refuses_a_column_whose_data_contradicts_utc` |
| Lock/ish vaqti? | Jadval **qayta yozilmaydi** (PG ≥ 12 + `SET LOCAL TimeZone='UTC'`): `pg_relation_filenode` konvertatsiyadan oldin va keyin bir xil; ACCESS EXCLUSIVE oynasi metadata yangilanishi bilan cheklanadi | `test_conversion_did_not_rewrite_the_tables` |

**v1 moslik matritsasi (AGENTS §2):**

| v1 xulqi | 0066 dan oldin | 0066 dan keyin |
|---|---|---|
| `GET /api/v1/client/orders/{id}` → `published_at` | `"2026-09-10T04:30:15"` | **bir xil** (`v1_naive`) |
| Admin buyurtma tafsiloti (7 ta vaqt maydoni) | offsetsiz | **bir xil** |
| Nizo `resolved_at`, hujjat `reviewed_at` | offsetsiz | **bir xil** |
| `created_at`/`updated_at` (avvaldan `timestamptz`) | offset bilan | **bir xil** |
| v1 kodida shu ustunlar bo‘yicha solishtirish/arifmetika | yo‘q (faqat yozish va serializatsiya) | yo‘q — aware/naive `TypeError` xavfi yo‘q |
| `order_offers.shown_at`/`responded_at` | v1 javoblarida umuman chiqmaydi | chiqmaydi |

### Tekshiruvlar (buyruq va natija)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `py -m alembic heads` | `20260916_0067 (head)` — bitta |
| 2 | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest tests/pg/test_migrations_smoke.py tests/pg/ops/test_legacy_projection.py tests/test_v1_v2_isolation_ac39.py -q` | 15 o‘tdi (migratsiya smoke 7, proyeksiya 5, AC39 3; toza DB’da `upgrade head` ×2, ikkinchisi no-op; bitta head) |
| 3 | `… tests/pg/ops/test_legacy_timestamps.py -q` | 6 o‘tdi (tip, instant, filenode, view tiklanishi, v1 wire, guard) |
| 4 | `… tests/pg/ops/test_revision_lineage.py -q` | 5 o‘tdi (Q50) |
| 5 | `… tests/pg/ops/test_wave5_followups.py -q` | 3 o‘tdi (chat_thread_id, amendment event) |
| 6 | `py -m pytest tests/contracts tests/modules -q` | 697 o‘tdi |
| 7 | `py scripts/export_openapi.py` (+ `--check`) · `npm run gen:api` · `npm run lint` · `npm run build` | v2 **141** operatsiya (139 → +2: O8 ro‘yxat va tafsilot), sxema commit qilingan nusxa bilan bir xil; `tsc --noEmit` va vite build xatosiz; `tests/test_mobile_v2_client_contract.py` **62 o‘tdi** (yangi `/admin/legacy-orders` yo‘li ham real v2 yo‘li ekani tekshirildi) |
| 8 | `bash scripts/restore_drill.sh --dump <sintetik> --expect-head 20260916_0067` | **DRILL PASSED** (pastdagi jadval) |

### Restore mashqi (AC40) — dev rehearsal, launch dalili **emas**

Sintetik dataset: `scripts/seed_admin_required_data.py` + `scripts/seed_demo_marketplace_data.py`
(14 shahar, 176 tuman, 10 mijoz, 10 tasdiqlangan haydovchi, 30 v1 buyurtma, baholar, status tarixi);
dump 669 672 bayt, `pg_dump -Fc`.

| Tekshiruv | Natija |
|---|---|
| `alembic_version` | `20260916_0067` (kutilgan) |
| `pg_amcheck --heapallindexed` | toza |
| Ledger balansi (debit = kredit, valyuta bo‘yicha) | ok (0 tranzaksiya — sintetik datasetda v2 pul oqimi yo‘q) |
| Legacy qator v2 `bookings`da | **yo‘q** (Q4/AC37) |
| Legacy proyeksiya | 30 qator = `orders` soni |
| Revision lineage | 67 qirra (Q50) |
| v1 buyurtmalar holati bo‘yicha | accepted 5, bidding 5, cancelled 1, confirmed 4, delivered 3, disputed 1, in_transit 3, picked_up 3, published 5 |
| O‘lchangan davomiylik | decrypt 0.0 s · DB start 2.6 s · `pg_restore` 3.3 s · analyze 0.7 s · verify+amcheck 6.6 s · **jami 13.3 s** |

**Bu raqam nima emas:** 669 KB sintetik dump, bitta ishchi noutbuk, shifrlanmagan fayl, **registry digest bilan
pin qilinmagan** dev image (skript buni o‘zi ogohlantiradi). Shuning uchun: RTO ≤ 2 soat **tasdiqlanmagan**,
Q34/Q51/Q73 image gate’i **ochiq**, manifest berilmagani uchun qator soni/summa manbaga qarshi solishtirilmagan,
uploads arxivi bo‘lmagani uchun attachment havolalari tekshirilmagan, Q35 (shifrlangan kundalik dump → decrypt →
restore) yo‘li bu mashqda bajarilmagan. Rasmiy AC40 mashqi — deploy hostida `scripts/backup.sh --local-only`
bilan olingan manifest+uploads va registry digestli image bilan.

### 4-to‘lqin qoldiqlarining tasnifi (wave 5 tekshiruvi)

| Band | Tekshiruv natijasi | Amal |
|---|---|---|
| Haydovchi “kelmadi” (no-show) ekrani yo‘q | **Backend to‘liq ishlaydi:** `report_no_show` → pending review → `no_show_review` operator navbati → `confirm_no_show`/`reject_no_show` (Q7). PG testlari: `tests/pg/bookings/test_wave21_pg.py` (navbat, operator 403/ruxsat), `test_lifecycle_pg.py` (oyna qoidalari) | UI bo‘shlig‘i (A9/Android) sifatida ochiq qoladi; operator navbati fallback ekanligi hujjatlashtirildi |
| Amendment ekrani faqat miqdorni o‘zgartiradi | **Wave 4d qaydi noaniq edi:** kontrakt ham pilotda faqat `quantity` va `unit_price_minor`ni qabul qiladi (`bookings.service._amendment_terms` → boshqa maydon `VALIDATION_ERROR` `pilot_amends_quantity_and_unit_price_only`); request listing’dan tug‘ilgan bronda miqdor D9 bo‘yicha qulflangan (`QUANTITY_MISMATCH`) | Hujjat tuzatildi; oyna/bekat o‘zgartirish — kelajak qaror, kontraktda yo‘q |
| Ochiq amendment haqida xabarnoma yo‘q | **Yopildi:** `booking.amendment_requested` / `booking.amendment_decided` (allowlist payload, komissiyasiz) | — |
| `contact.chat_thread_id` to‘ldirilmaydi | **Yopildi:** A7 read-only lookup; chat ochilmagan bo‘lsa `null` | — |
| v1 admin audit jurnali operatorga 403 | **Ataylab shunday:** `AUDIT_LOG_ROLES = {admin, super_admin}` (v1 xulqi, Q10/Q13 bilan bir chiziqda); `tests/test_admin_audit_logs.py` operator uchun 403 ni allaqachon tekshiradi | O‘zgartirilmadi — qulaylik uchun operatorga admin huquqi berilmaydi |
| Nizo dalili fayllarini ko‘rsatish | **Yopildi:** `DisputeEvidenceDTO.file_urls` — imzolangan, qisqa muddatli havolalar; javob allaqachon avtorizatsiya qilingan tomonga beriladi | — |
| Avtomatlashtirilgan UI testlari repo’da yo‘q | **Ochiq:** brauzer testi uchun yangi dependency (Playwright) va brauzer yuklab olish kerak — AGENTS §2 bo‘yicha bu pin bilan va qaror asosida kiritiladi; bu wave’da kiritilmadi | Foydalanuvchi qarori: `@playwright/test` ni `mobile-app` devDependency sifatida pin qilib qo‘shish va `mobile-app/e2e/` ga seed+cleanup bilan minimal ssenariy yozish |

### Yakuniy to‘liq regressiya (17.09.2026)

| Band | Qiymat |
|---|---|
| Buyruq | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q -p no:cacheprovider --junitxml=final_junit.xml` |
| Muhit | PostgreSQL 16.15 + PostGIS 3.5.3 (`elchi-postgis:16.15-3.5.3-trixie`, digest `sha256:35bf2116…`), Redis 7.4.11, Python 3.14.3, `docker-compose.test.yml` stack (127.0.0.1:45432) |
| Kod holati | commit `4f468c3` + commit qilinmagan wave 5 diff’i (`git diff HEAD` sha256 `e10f95be…`), `alembic heads` = `20260916_0067` |
| Oyna | 2026-09-16T20:32Z … 20:50Z (1061.6 s) |
| Natija | **1976 test: 1976 o‘tdi, 0 failure, 0 error, 0 skip** (exit 0) |
| Taqsimot | `tests/pg` 743 · `tests/contracts` 390 · `tests/modules` 315 · v1/boshqa 528 |
| Wave 5 fayllari | proyeksiya 5 · timestamp 6 · lineage 5 · follow-up 3 · AC39 3 · migratsiya smoke 7 · readiness 19 · db_roles 10 · mobil klient kontrakti 61 |

**Baseline haqida halol qayd:** wave 4 dan keyingi baseline run (19:49Z–20:09Z) **ifloslangan** — men u ishlayotgan
paytda 0065/0066 fayllarini qo‘shdim, shuning uchun sessiya shabloni `0064` da qolgan holda kod head’i o‘zgardi va
16 ta test (`test_health_probes_pg.py` 13, `test_migrations_smoke.py` 3) aynan shu farqni qayd etdi
(`assert '20260916_0064' == '20260916_0065'`). Hech bir failure kodning oldingi holatidagi nuqsonni ko‘rsatmagan;
yuqoridagi yakuniy run — o‘zgarishlar kiritilgandan keyingi to‘liq va toza dalil. Xulosa: test ishlayotganda
repo tahrirlanmaydi.

**Yakuniy run’dan keyingi o‘zgarishlar (halollik qaydi):** to‘liq regressiyadan keyin faqat (a) `scripts/ac_coverage.py`
(hech bir test unga tegmaydi) va (b) `mobile-app` admin paneli o‘zgardi. Ular alohida qayta tekshirildi:
`npm run lint` + `npm run build` xatosiz, `tests/test_mobile_v2_client_contract.py` **62 o‘tdi**,
`py scripts/export_openapi.py --check` — sxema yangi (141 operatsiya), `alembic heads` = `20260916_0067`.

### Wave 5 dan keyin ochiq qolgan bandlar

| Band | Holat | Kimda |
|---|---|---|
| AC40 rasmiy mashqi (manifest + uploads + digest pinlangan image) | NOT_RUN | A10a/ops (registry paydo bo‘lgach) |
| §19.3 yuklama profili (50 tracker, 200 viewer, 20 accept, 100 000 e’lon) | NOT_RUN — harness tayyor (`scripts/load_profile.py`) | A11/A13, staging kerak |
| U6 `rating_bucket`, ADR-0021 (MFA), U3 push provayderi, U7 support raqami | BLOCKED | Foydalanuvchi qarori |
| Q34/Q51/Q73 registry digest, Q35 shifrlangan dump mashqi, §9.4 fiskal, K7/Q24 huquqiy | BLOCKED | Ops / huquq / buxgalteriya |
| Avtomatlashtirilgan UI (E2E) testlari | Ochiq — yangi dependency qarori kerak | Foydalanuvchi + A8/A9 |
| Android dala sinovlari (AC27 dala qismi, AC32), 6 xonali OTP (Q8) | Doiradan tashqari | Android dasturchi |

---

## Wave 6 (17.09.2026) — spetsifikatsiya auditi va topilgan bo‘shliqlar

Foydalanuvchi topshirig‘i: “`ELCHI_PRODUCTION_ARCHITECTURE.md` ni boshidan oxirigacha o‘qi, wave’larda
bajarilgan ishlar faylda aytilgani kabi amalga oshirilganini tekshir, qolib ketgan ishlarni yangi to‘lqinga
qo‘shib davom ettir. Deploy va production keyinroq.”

### Audit natijasi (spec bo‘limi → holat)

| Bo‘lim | Holat | Izoh |
|---|---|---|
| §5.1–5.3 e’lon turlari, majburiy maydonlar, kelishuv protokoli | ✅ mos | `ListingCreate` + passenger/parcel detallari spec ro‘yxatini to‘liq qoplaydi |
| §5.4 dublikat tekshiruvi | ✅ mos | mavjud e’lon id’si bilan `DUPLICATE_LISTING` |
| §5.4 e’lon rate-limit | ❌ yo‘q edi → ✅ **wave 6** | `LISTING_PUBLISH_RATE_LIMIT` (soatiga 10), resume limitga kirmaydi |
| §5.2 pilot limitlari | ❌ yo‘q edi → ✅ **wave 6** | og‘irlik/o‘lcham/hajm chegarasi; taqiqlangan jo‘natmalar **ro‘yxati** biznes qarori (ochiq) |
| §6.1–6.5 matching, `exact/on_route/detour/alternative` | ✅ mos | `MatchType` to‘liq, `ST_DWithin` metrda |
| §6.6 lenta filtrlari | ✅ mos | xizmat, sana, yo‘nalish, o‘rin, jami narx, qulayliklar, alternativlar opt-in |
| §7 segment sig‘imi, exclusion constraint | ✅ mos | — |
| §8.1 “taraflar bir-birini bloklamagan” | ❌ **jadval ham yo‘q edi** → ✅ **wave 6** | `user_blocks` + feed/proposal filtri |
| §8.2/§8.4 ball formulalari | ✅ mos | vaznlar kontraktda, `ranking_version` bilan |
| §9 pul, ledger, hold | ✅ mos | — |
| §10.3–10.7 tracking | ✅ mos | stale chegaralari, batch limiti, partition, retention |
| §10.8 xarita kvotasi hisobi | ❌ yo‘q edi → ✅ **wave 6** | `provider_usage_daily`, 70 %/85 % chegaralari, `estimated=true` |
| §11 holat mashinalari | ✅ mos | sakkizta enum spec bilan bir xil |
| §12 modullar, OpenAPI→TS | ✅ mos | — |
| §13 jadvallar | ✅ mos (bitta ataylab chetlanish) | `legacy_links` o‘rniga read-only view (Q4) |
| §14 API ro‘yxati | ✅ 28/28 endpoint mavjud | tekshirildi: OpenAPI yo‘llari bilan solishtirildi |
| §15 atomar accept, outbox | ✅ mos | — |
| §16 operator navbatlari | ⚠️ qisman edi → ✅ **wave 6** | javobsiz e’lonlar, eskirgan GPS, tasdiqlanmagan haydovchi qo‘shildi |
| §17.2 baho, §17.4 hujjatlar, §17.8 o‘chirish | ✅ mos | — |
| §17.3 takror akkaunt / soxta safar signallari | ❌ yo‘q edi → ✅ **wave 6** | `abuse_reports`, `fraud_signals`, `device_account_links` |
| §17.6 “revoke qilingan sessiya real-time kanalda yopiladi” | ❌ 60 daqiqagacha ochiq edi → ✅ **wave 6** | access token `sid` claim + v2/WS tekshiruvi |
| §19.2 strukturali log (duration, booking_id), API p95, 5xx, outbox lag | ❌ yo‘q edi → ✅ **wave 6** | access log + `app/ops/metrics.py` + SLO ko‘rsatkichlari |
| §19.3 yuklama profili | ⏳ ochiq | harness bor (`scripts/load_profile.py`), profil bo‘yicha run staging talab qiladi |
| §20.4 KPI’lar | ⚠️ 4 tasi “o‘lchanmaydi” edi → ✅ 2 tasi yopildi | `search_with_match_rate`, `time_to_first_valid_offer`; qolgan 2 tasi halol “o‘lchanmaydi” |
| §22 AC01–AC44 | ✅ 42 PASS (wave 5 matritsasi) | AC32 dala, AC40 mashq |

### Yetkazilgan ishlar

| Egasi | Yetkazildi | Migratsiya |
|---|---|---|
| A12 | **S9–S12:** `user_blocks` (§8.1 — jim va ikki tomonlama; lentada yashiradi, yangi muzokarani `404` qiladi, mavjud bronga tegmaydi), `abuse_reports` (kontakt filtri + kunlik limit; o‘zi hech nimani o‘zgartirmaydi), `fraud_signals` + `scan_fraud_signals` worker vazifasi (`shared_device_accounts`, `self_dealing_device`, `repeated_pair_bookings`) — **avtomatik hukm yo‘q**, faqat operator navbati | `20260917_0068` |
| A7 | `device_account_links`: qurilma qaysi akkauntlarga tegishli bo‘lganining append-only tarixi (`device_tokens` faqat oxirgi egani saqlaydi); xom token saqlanmaydi, `device_account_groups` servis funksiyasi orqali o‘qiladi | `20260917_0068` |
| A10a/A13 | **§19.2 kuzatuv:** har so‘rovga bitta strukturali access log qatori (route shabloni, status, `duration_ms`, `booking_id`; query string yo‘q) va jarayon ichidagi kechikish reyestri (`app/ops/metrics.py`, cheklangan xotira). SLO endi `feed_p95_seconds`/`booking_accept_p95_seconds` ni **o‘lchaydi** (namuna < 20 bo‘lsa `null`), `server_error_rate` va `outbox_oldest_pending_seconds` qo‘shildi | — |
| A5/A13 | **§20.4:** `feed_search_events` (foydalanuvchisiz, bekatsiz, filtrsiz hisoblagich) → `search_with_match_rate`; `time_to_first_valid_offer` mavjud qatorlardan hisoblanadi (numerator = soniyalar yig‘indisi, denominator = taklif olgan e’lonlar soni). `missing_metrics` 4 → 2 ga qisqardi va nolga aylanmadi | `20260917_0069` |
| A2/A13 | **§10.8:** `provider_usage_daily` + `record_provider_usage` (routing adapteri chaqiruvida, cache’dan kelgan javob hisoblanmaydi) + `GET /admin/metrics/provider-quota` (70 % `warn`, 85 % `restrict`, `estimated=true`). GPS qabul qilish bu sondan mustaqil | `20260917_0069` |
| A13 | **§16:** uchta yangi operator navbati — `unanswered_listing` (jo‘nashga 24 soat qolgan, taklifsiz e’lonlar), `stale_tracking` (faol safarda 2 daqiqadan beri nuqta yo‘q), `ineligible_driver_trip` (12 soat ichida jo‘naydigan, haydovchisi eligible bo‘lmagan safar). Yangi jadval yo‘q; matn operatsion tilda (“aloqa uzilgan bo‘lishi mumkin”), ayblov emas | — |
| A1 | **§5.2/§5.4:** pochta uchun pilot limitlari (50 kg, 150 sm, 0.5 m³) va e’lon chiqarish rate-limiti (soatiga 10); `resume` limitga kirmaydi | — |
| H1/A6 | **§17.6:** access token endi login sessiyasiga bog‘langan (`sid`); v2 endpointlari va tracking WebSocket’i bekor qilingan sessiyani darhol rad etadi (avval 60 daqiqagacha ochiq qolardi). **v1 xulqi ataylab o‘zgarmadi** — bu v1 kontrakt o‘zgarishi bo‘lardi va alohida qaror talab qiladi | — |
| A5 | `purge_search_events` worker vazifasi: §20.4 hisoblagichlari 90 kundan keyin o‘chadi (§17.7) | — |

### Tekshiruvlar (wave 6)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `… pytest tests/pg/trust_support/test_blocks_reports_fraud_pg.py -q` | 8 o‘tdi |
| 2 | `… pytest tests/pg/ops/test_request_metrics_pg.py -q` | 5 o‘tdi |
| 3 | `… pytest tests/pg/ops/test_kpi_quota_wave6_pg.py -q` | 4 o‘tdi |
| 4 | `… pytest tests/pg/ops/test_operational_queues_pg.py -q` | 4 o‘tdi |
| 5 | `… pytest tests/pg/ops/test_session_revocation_pg.py -q` | 5 o‘tdi |
| 6 | `… pytest tests/pg/marketplace/test_listing_limits_wave6_pg.py -q` | 4 o‘tdi |
| 7 | `py -m pytest tests/contracts tests/modules tests/test_mobile_v2_client_contract.py -q` | 767 o‘tdi |
| 8 | `py scripts/export_openapi.py` + `npm run gen:api` + `npm run lint` | v2 **151** operatsiya (141 → +10), `tsc` xatosiz |
| 9 | ORM drift (trust, communications, feed) | 21 o‘tdi (jadval kommentariyalari va BIGINT/INTEGER tiplari modelda e’lon qilindi) |

### Wave 6 dan keyin ochiq qolgan bandlar

| Band | Sabab |
|---|---|
| Taqiqlangan jo‘natmalar **ro‘yxati** (§5.2) | Biznes/huquqiy qaror — kod ro‘yxatni o‘ylab topmaydi; mexanizm (limit va rad javobi) tayyor |
| §19.3 yuklama profili | Staging muhiti va 100 000 e’lonli fixture kerak; harness `scripts/load_profile.py` tayyor |
| `booked_seat_km_ratio`, `net_commission_per_corridor` | Segment masofasi hisobi va moliya hisoboti kerak — halol “o‘lchanmaydi” ro‘yxatida qoldi |
| §17.6 v1 tomoni | v1 access token logoutdan keyin ham amal qiladi; o‘zgartirish v1 xulq qarori (AGENTS §2) |
| Deploy/production gate’lari (Q48, Q36, Q34/Q51, AC40 rasmiy mashqi) | Foydalanuvchi qaroriga ko‘ra **keyinga qoldirildi** |

### Wave 6 yakuniy regressiya (17.09.2026)

| Band | Qiymat |
|---|---|
| Buyruq | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q -p no:cacheprovider --junitxml=…` |
| Kod holati | commit `4f468c3` + commit qilinmagan diff (tracked sha256 `3a4d0c9d…`, untracked 449 fayl sha256 `c6d3baac…`), `alembic heads` = `20260917_0069` |
| Oyna | 2026-09-16T22:20Z … 22:34Z (856.2 s) |
| Natija | **2007 test: 2007 o‘tdi, 0 failure, 0 error, 0 skip** (exit 0) |
| Taqsimot | `tests/pg` 773 · `tests/contracts` 390 · `tests/modules` 315 · v1/boshqa 529 |
| AC01–AC44 | **42 PASS**, AC32 `FIELD` (Android), AC40 `PROCEDURE` (restore mashqi) — o‘zgarmadi |

**O‘zgargan xulqni aks ettirish uchun yangilangan uchta test** (AGENTS §7: o‘zgargan xulq hujjatlashtiriladi):
`tests/pg/operations/test_operations_pg.py` (KPI `missing_metrics` 4 → 2; SLO kechikishi endi o‘lchanadi, namuna
kichik bo‘lsa `null` qoladi), `tests/test_worker_jobs.py` (ikkita yangi worker vazifasi). Yana bir tuzatish:
`tests/conftest.py` har testdan keyin `app.ops.metrics.REGISTRY` ni tozalaydi — jarayon-global reyestr
boshqa testning SLO javobiga oqib ketgan edi (birinchi to‘liq run’da aynan shu bitta failure chiqdi).

## Wave 7 (17.09.2026) — ochiq bandlarni yopish va qaror loyihalari

Foydalanuvchi topshirig‘i: qolgan texnik ishlarni **mavjud qarorlar doirasida oxiriga yetkazish**; qaror
talab qiladigan bandlarni esa faqat tavsiya emas, **ko‘rib chiqishga tayyor holatga** keltirish. Deploy,
production yozuvlari, commit/push — yo‘q. `android-app/` va `frontend/` tegilmadi.

### Bajarilgan ishlar

| # | Ish | Nima o‘zgardi |
|---|---|---|
| 1 | **§5.2 taqiqlangan jo‘natmalar — mexanizm** | `0070`: `parcel_policy_versions` (bir vaqtda faqat bitta `active`, partial unique index) + `parcel_policy_items` (`prohibited` bandi **huquqiy asos va manba havolasisiz** DB darajasida rad etiladi). `marketplace.service`: `active_parcel_policy`, `assert_parcel_policy_ready`, yaratish/tasdiqlash (`platform.policy_manage`, **muallif o‘zini tasdiqlay olmaydi**). `GET /parcel-policy` (autentifikatsiyasiz) + 3 ta admin endpointi |
| 2 | **Gate xulqi** | Tasdiqlangan ro‘yxat bo‘lmasa production’da `service_type='parcel'` uchun **yangi** e’lon (`publish`) va **yangi** bron (`accept_proposal`) `503 PARCEL_POLICY_UNCONFIRMED`. Mavjud bronlar, tracking, proof, support davom etadi (D16). Yo‘lovchi oqimi tegilmaydi. Bo‘sh ro‘yxat “hamma narsa mumkin” deb talqin qilinmaydi — `ParcelPolicyDTO.approved=false` + `notice` |
| 3 | **Ro‘yxat loyihasi** | `docs/ops/PARCEL_PROHIBITED_ITEMS_DRAFT.md` — 13 band, har biri toifa (taqiqlangan / ruxsatnoma talab qiladigan / biznes qarori bilan qabul qilinmaydi), foydalanuvchi tilidagi izoh, huquqiy yoki biznes asosi, manba va tekshirilgan sana bilan; **TASDIQLANMAGAN** deb belgilangan. `scripts/seed_parcel_policy_draft.py` faqat **draft** yaratadi |
| 4 | **§20.4 oxirgi ikki KPI** | `0071` (metrika CHECK 8 → 11) + `booked_seat_km_ratio` (band qilingan / taklif qilingan o‘rin-km), hamrohi `seat_km_route_coverage`, va `net_commission_per_corridor` (ledger `commission_revenue` bo‘yicha capture − reversal). `missing_metrics` endi **bo‘sh** |
| 5 | **Q87 majburlash** | Production’da `passenger_enabled`ni yoqish `ELCHI_SUPPORT_PHONE` bo‘sh bo‘lsa rad etiladi (`support_contact_not_configured`). Soxta raqam qo‘shilmadi; S13 `available=false` bo‘lib qoldi |
| 6 | **Qaror loyihalari** | `docs/architecture/decisions-pending/`: `U6-rating-bucket.md`, `ADR-0021-mfa-decision-draft.md` (ADR **Proposed** bo‘lib qoldi), `v1-logout-access-token.md` (v1 xulqi **o‘zgartirilmadi**), `U3-push-provider.md` |
| 7 | **§19.3 harness** | `docs/ops/LOAD_PROFILE_RUNBOOK.md` — fixture, env, warm-up, o‘lchash oynasi, natija formati, “o‘lchanmaydi” ro‘yxati |

### Seat-km va komissiya metrikalarining aniq ta’rifi

| Band | Qaror |
|---|---|
| Masofa manbai | `route_version_stops.cumulative_distance_m` ning maksimumi (tasdiqlangan marshrut versiyasi). **To‘g‘ri chiziqli masofa hech qachon yo‘l masofasi o‘rniga qo‘yilmaydi**; tashqi routing yoqilmadi |
| Hisoblash vaqti | `planned_start_at` kuni bo‘yicha (kunlik KPI), `trips.status <> 'cancelled'` |
| Masofasi yo‘q safar | Ikkala tomondan ham (surat va maxraj) chiqariladi va `seat_km_route_coverage` da alohida ko‘rsatiladi — nol deb hisoblanmaydi |
| O‘rin sig‘imi | Trip’ning e’lon qilingan o‘rin soni; band qilingan tomonda `bookings.seats > 0` |
| Bekor/no-show | `service_status IN ('cancelled','no_show')` **suratdan** chiqadi, maxraj (taklif qilingan sig‘im) o‘zgarmaydi |
| Komissiya qatorlari | `ledger_entries` → `ledger_transactions` → `ledger_accounts.code='commission_revenue'`, `currency='UZS'`; `credit − debit` (ya’ni capture − reversal) |
| Kirmaydi | Hold, top-up, pending daromad, legacy `system_fee`. Natija **nisbat emas, summa** va **sof foyda emas** (operatsion xarajatlar ayirilmagan) |
| Davr | Reversal o‘zi tushgan kunga yoziladi — ilgarigi kun qayta yozilmaydi |

### Tekshiruvlar (wave 7)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `… pytest tests/pg/marketplace/test_parcel_policy_pg.py -q` | 6 o‘tdi |
| 2 | `… pytest tests/pg/ops/test_kpi_seatkm_commission_pg.py -q` | 5 o‘tdi (seat-km manba qatorlari bilan, komissiya ledger bilan solishtirildi) |
| 3 | `… pytest tests/pg/ops/test_push_support_hardening_pg.py -q` | 4 o‘tdi |
| 4 | `py -m pytest tests/contracts tests/modules tests/test_mobile_v2_client_contract.py -q` | **767 o‘tdi**, 0 failure |
| 5 | `py scripts/export_openapi.py` + `npm run gen:api` + `npm run lint` | v2 **155** operatsiya (151 → +4), `tsc` xatosiz |
| 6 | `py scripts/load_profile.py … --scenario health` (lokal smoke) | 4266 so‘rov, 100 % `200`, p95 0.037 s — **harness tekshiruvi**, §19.3 natijasi emas |

### Wave 7 yakuniy regressiya (17.09.2026)

**Birinchi to‘liq run 6 ta failure bilan tugadi** — hammasi wave 7 o‘zgarishlarining haqiqiy oqibati, flake emas:

| Failure | Sabab | Tuzatish |
|---|---|---|
| `test_orm_metadata_matches_migrated_schema` | `uq_parcel_policy_versions_active` migratsiyada bor, ORM modelida e’lon qilinmagan | Migratsiya indeksni ifoda (`(status)`) o‘rniga oddiy ustun bo‘yicha quradi; model `postgresql_where`/`sqlite_where` bilan e’lon qiladi (repo konvensiyasi) |
| `test_operations_pg::…missing_metrics…`, `test_kpi_quota_wave6_pg::…search_with_match_rate…` | Ikkala test hamon “bu ikki KPI o‘lchanmaydi” deb kutar edi | `missing_metrics == []` ga yangilandi **va** qo‘shimcha tekshiruv qo‘shildi: o‘lchab bo‘lmaydigan kun hamon `denominator 0` / `value None` beradi, komissiya esa nisbat emas — ya’ni “ro‘yxat bo‘shadi” jimgina “hammasi nol” ga aylanmaydi |
| 3 × geo flag testi (`test_geo_api_pg`, `test_geo_flags_pg`, `test_geo_q48_gate_q47_pg`) | Yangi Q87 guard’i ularni **to‘g‘ri** rad etdi: production’da support telefoni yo‘q edi | `geo_pg_helpers.set_support_phone(monkeypatch)` qo‘shildi; Q5/Q48 haqidagi bu uch test Q87 shartini endi ochiq e’lon qiladi (sintetik raqam). Guard’ning rad etish yo‘li `test_push_support_hardening_pg.py` da qoplangan |

Uchinchi qator ayni paytda Q87 guard’ining **haqiqatan xulqni o‘zgartirgani**ning dalili: ilgari production’da
support raqamisiz `passenger_enabled`ni yoqish mumkin edi, endi mumkin emas.

| Band | Qiymat |
|---|---|
| Buyruq | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q -p no:cacheprovider --junitxml=…` |
| Kod holati | commit `4f468c3` + commit qilinmagan diff (tracked sha256 `3a4d0c9d30d1151e`, untracked 461 fayl sha256 `f02bb24c20c7d5dd`) |
| Migratsiya | `alembic heads` = `20260917_0071` (bitta head) |
| Muhit | Windows 11, Python 3.14, PG test stack `elchi-test-postgis-1` (127.0.0.1:45432), `elchi-test-redis-1`; boshqa sinov parallel ishlamadi |
| Oyna | 2026-09-16T23:44Z … 23:57Z (762.7 s) |
| Natija | **2022 test: 2022 o‘tdi, 0 failure, 0 error, 0 skip** (exit 0) |
| AC01–AC44 | **42 PASS**, AC32 `FIELD`, AC40 `PROCEDURE` — wave 6 dan o‘zgarmadi |

**O‘zgargan xulqni aks ettirish uchun yangilangan testlar** (AGENTS §7): yuqoridagi jadvaldagi 6 ta test.
Wave 6 ning 2007 tasidan 2022 ga o‘sish — wave 7 ning 15 ta yangi testi (parcel policy 6, seat-km/komissiya 5,
push/support 4).

### Wave 7 dan keyin ochiq qolgan bandlar

| Band | Sabab |
|---|---|
| Taqiqlangan jo‘natmalar **ro‘yxatining tasdig‘i** | Huquqiy/biznes qarori — mexanizm tayyor, 13 bandli loyiha ko‘rib chiqishni kutmoqda |
| U6 `rating_bucket`, ADR-0021 MFA, §17.6 v1 tomoni, U3 push provayderi | Foydalanuvchi qarori — har biri uchun variantlar, ta’sir va test rejasi yozildi |
| §19.3 yuklama profili | Staging muhiti va 100 000 e’lonli sintetik fixture seed’i kerak (NOT_RUN) |
| Deploy/production gate’lari (Q48, Q36, Q28, Q34/Q51/Q73, rasmiy AC40, Q35 shifrlangan dump) | Foydalanuvchi qaroriga ko‘ra **keyinga qoldirildi** — holati o‘zgartirilmadi |

## Wave 8 (17.09.2026) — tasdiqlangan beshta qarorni implementatsiya qilish

Foydalanuvchi 17.09.2026 da wave 7 hisobotini qabul qildi va qaror jadvalidagi **beshta bandni ham tavsiya
bo‘yicha** tasdiqladi. Wave 8 — o‘sha qarorlarni kodga aylantirish. Deploy, production yozuvi, commit/push —
yo‘q; `android-app/` va `frontend/` tegilmadi.

### Bajarilgan ishlar

| # | Qaror | Nima yozildi |
|---|---|---|
| 1 | **§5.2 ro‘yxati** (matn tasdiqlandi) | Hujjat holati “tasdiqlanmagan loyiha” dan “matn tasdiqlandi, production’da faollashtirilmagan” ga o‘zgardi va **ikki bosqich ataylab ajratildi**. `seed_parcel_policy_draft.py` ga `--confirm-as-user-id` qo‘shildi: **faqat production emas** bazada ishlaydi va muallif o‘zini tasdiqlay olmaydi. 2 yangi PG test: 13 band DB qoidalaridan o‘tadi; tasdiqlangach production’da pochta e’loni yana ochiladi |
| 2 | **U6 = A-variant** | `RatingBucket` enum, `RATING_BUCKET_MIN_COUNT=3`, `good ≥ 4.0` / `mixed ≥ 3.0` / `low < 3.0`; `ReputationSummary.rating_bucket`; `ListingOfferDTO.rating_bucket` + yangi `rating_count` to‘ldiriladi (`views.listing_offer_dtos`). Bucket **hech qachon** `adjusted_rating` dan olinmaydi (unda 4.5 prior bor) |
| 3 | **ADR-0021 = pyotp + 2 super_admin** | ADR **Accepted**. `pyotp==2.10.0` pin; `0074` (3 jadval, `activated_by <> user_id` CHECK, append-only trigger); `app/core/secret_box.py` (AES-256-GCM); `identity/mfa.py` (enroll, activate, verify, step-up, recovery); step-up 7 ta capability’da; staff access token 15 daqiqa |
| 4 | **§17.6 v1 = A-variant** | `0072` (`refresh_sessions.revoked_reason`) + `get_current_user` `sid` tekshiruvi; `session_revoked(..., include_rotated=False)` v1 uchun |
| 5 | **U3 = FCM** | **ADR-0022** yozildi; `communications/fcm.py` adapteri; `0073` (`device_tokens.token_cipher`, AES-256-GCM, AAD = qurilma public id); `cryptography==49.0.0` pin. **Yoqilmadi** |

### Ikkita aniqlashtirish (qaror matnida yo‘q edi, lekin zarur bo‘ldi)

1. **§17.6 rotation ≠ logout.** Qat’iy implementatsiyada token yangilangan zahoti eski access token o‘lardi va
   muzlatilgan Android klientining allaqachon yo‘lda bo‘lgan so‘rovlari `401` olardi — bu mavjud testda
   darhol ko‘rindi. Qaror *logout* haqida edi, shuning uchun `revoked_reason` qo‘shildi: `logout`/`admin_revoke`
   → v1 darhol rad etadi, `rotated` → eski token o‘z muddatini yashaydi. v2/WS qat’iy qoldi.
2. **MFA enforcement o‘zi yoqilmaydi.** Dastlab `audit_only` ikkinchi `super_admin` paydo bo‘lishi bilan
   tugar edi — natijada 4 ta mavjud wallet testi `step_up_required` bilan yiqildi, ya’ni amalda moliya
   buyruqlari xodim qo‘shilgan kuni ogohlantirishsiz to‘xtar edi. `settings.staff_mfa_mode`
   (`audit_only` **standart** → `enforce_privileged` → `enforce_all`) qo‘shildi; bitta super_admin bo‘lsa
   enforcement baribir qo‘llanmaydi.

### Tekshiruvlar (wave 8)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `py -m pytest tests/test_v1_session_revocation.py -q` | 7 o‘tdi |
| 2 | `py -m pytest tests/contracts/test_rating_bucket_u6.py -q` | 12 o‘tdi |
| 3 | `py -m pytest tests/contracts/test_fcm_adapter_adr0022.py -q` | 13 o‘tdi (hech biri tarmoqqa chiqmaydi) |
| 4 | `… pytest tests/pg/identity/test_staff_mfa_pg.py -q` | 13 o‘tdi |
| 5 | `… pytest tests/pg/marketplace/test_parcel_policy_pg.py -q` | 8 o‘tdi |
| 6 | `… pytest tests/pg/marketplace/test_marketplace_wave16_pg.py -q` | 15 o‘tdi |
| 7 | `py scripts/export_openapi.py` + `npm run gen:api` + `npm run lint` | 155 operatsiya (o‘zgarmadi — MFA endpointlari bu wave’da qo‘shilmadi), `tsc` xatosiz |

### Wave 8 dan keyin ochiq qolgan bandlar

| Band | Sabab |
|---|---|
| §5.2 ro‘yxati uchun **yurist xulosasi** | Tashqi band; matn tasdiqlangan, production’da faollashtirish ikki `super_admin` orqali |
| MFA enforcement’ni yoqish | Production’da ≥ 2 `super_admin` va omillar ro‘yxatdan o‘tishi kerak; keyin `staff_mfa_mode=enforce_privileged` |
| Staff login oqimiga MFA bosqichi + admin UI | A8/A9 kartasi; servis qatlami tayyor |
| Push yoqish (FCM) | K3 huquqiy xulosasi, Firebase credential, klientda xom token ro‘yxati |
| §19.3 yuklama profili | Staging va 100 000 e’lonli fixture kerak (NOT_RUN) |
| Deploy/production gate’lari (Q48, Q36, Q28, Q34/Q51/Q73, AC40, Q35) | Foydalanuvchi qaroriga ko‘ra keyinga qoldirilgan — holati o‘zgartirilmadi |

## Wave 9 (17.09.2026) — wave 8 regressiyasi va staff MFA yuzasi

Wave 8 kod jihatidan yakunlangan edi, lekin **yakuniy to‘liq regressiya ishga tushirilmagan** edi (faqat 7 ta
nuqtali tekshiruv bor edi). Wave 9 avval shu regressiyani oxirigacha olib boradi, so‘ng wave 8 dan keyin ochiq
qolgan yagona **kod** ishini — staff MFA endpointlari va admin UI (A8/A9 kartasi) — bajaradi. Qolgan ochiq
bandlar tashqi qaror, staging yoki foydalanuvchi qarori bilan keyinga qoldirilgan; ularning holati o‘zgarmadi.
Deploy, production yozuvi, commit/push — yo‘q; `android-app/` va `frontend/` tegilmadi.

### 1. Wave 8 regressiyasi: ikkita haqiqiy nuqson (flake emas)

| Failure | Sabab | Tuzatish |
|---|---|---|
| `tests/modules/wallet/test_v1_settings_adapter.py` (4 error) | `staff_mfa_events.detail` ustuni modelda `server_default=text("'{}'::jsonb")` bilan e’lon qilingan edi; SQLite bu sintaksisni tushunmaydi va **jadval yaratilmasdi** | Repo konvensiyasi bo‘yicha portativ `text("'{}'")` (`bookings/models.py:319` bilan bir xil); migratsiya jsonb ga o‘zi cast qiladi |
| `test_communications_models_match_migrated_schema`, `test_orm_metadata_matches_migrated_schema` | `0073` `device_tokens.token_cipher` uchun `COMMENT ON COLUMN` yozadi, ORM modeli esa izohni e’lon qilmagan → schema drift | Model ustuniga `comment=` qo‘shildi (`0072` da shu to‘g‘ri bajarilgan edi) |

### 2. Staff MFA yuzasi (I6–I11, ADR-0021)

Wave 8 servis qatlamini va majburlashni yozgan edi, lekin **birorta endpoint yo‘q edi**: xodim omil ulay ham,
uni isbotlay ham olmasdi. Ya’ni `staff_mfa_mode=enforce_privileged` ga o‘tish amalda barcha pul buyruqlarini
qulflash degani bo‘lar edi — “tayyor” deb hisoblab bo‘lmaydigan holat.

| # | Ish | Nima yozildi |
|---|---|---|
| 1 | **Endpointlar** | `GET /me/mfa`, `POST /me/mfa/enroll` (201), `POST /me/mfa/step-up`, `POST /me/mfa/recovery`, `POST /admin/staff/{user_id}/mfa/activate`, `POST /admin/staff/{user_id}/mfa/reset`. Migratsiya **kerak emas** — wave 8 jadvallari yetarli |
| 2 | **Q3 chegarasi** | MFA yuzasi faqat staff akkauntida; marketplace akkaunti `403 FORBIDDEN` (`staff_only`) |
| 3 | **`mfa.reset()`** | Yo‘qolgan telefon: **boshqa** super_admin omilni va ishlatilmagan tiklash kodlarini bekor qiladi, `factor_reset` audit qatori bilan (DB CHECK `actor <> subject`). Hech qanday huquq bermaydi |
| 4 | **Kod taxmin qilishga qarshi** | 15 daqiqada 5 xato kod → `429 RATE_LIMITED`; login/step-up, faollashtirish va tiklash yo‘llarining **hammasida** (aks holda hujumchi sanalmaydigan yo‘lni tanlardi) |
| 5 | **Savepoint tuzatish** | Xato kod domen 4xx bo‘lgani uchun `run_idempotent` savepoint’i servis yozgan `verify_failed` qatorini qaytarardi — hisoblagich hech qachon o‘smasdi va taxmin qilish bepul bo‘lardi. Urinish endi `run_command(after_command=…)` ichida qayta yoziladi (BR D8 naqshi, §11 dagi proof kodi bilan bir xil) |
| 6 | **`audit_only` qatorlari sanalmaydi** | `require_step_up` audit rejimida “omil yo‘q” qatorini yozadi; ularni sanash xodimni audit rejimidan chiqolmaydigan qilib qo‘yardi |
| 7 | **Ikkinchi qurilma** | `mfa.state()` endi eng oxirgi qatorni emas, **faol** omilni qidiradi: yangi telefonga ulanish eski omilni o‘chirmaydi. Ilgari enrollment ekranini ochishning o‘zi pul buyruqlarini to‘xtatardi (enforcement yoqilganda) |
| 8 | **Tiklash kodi semantikasi DTO’da** | `StaffMfaRecoveryDTO` faqat `enrollment_allowed` qaytaradi; step-up yoki tasdiq maydoni yo‘q (Q17/Q49) |
| 9 | **Admin UI** | `mobile-app/src/app/AdminSecurityPanel.tsx` + `api/v2/mfa.api.ts`, admin panelning “Xavfsizlik (MFA)” bo‘limi. Sir va 10 tiklash kodi **bir marta** ko‘rsatiladi va shu ogohlantirish bilan; ekran “himoyalangansiz” demaydi — `audit_only` yoki bitta super_admin sababini ochiq yozadi |

### 3. Tekshiruvlar (wave 9)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q` (wave 8 holati, tuzatishlardan oldin) | **2071 test: 2069 o‘tdi, 2 failure** (yuqoridagi schema drift) |
| 2 | `… pytest tests/pg/communications/test_communications_schema_pg.py tests/pg/test_migrations_smoke.py -q` | 10 o‘tdi (drift yopildi) |
| 3 | `… pytest tests/pg/identity/test_staff_mfa_api_pg.py -q` | **9 o‘tdi** (yangi) |
| 4 | `… pytest tests/pg/identity tests/pg/wallet -q` | 136 o‘tdi (wave 8 ning 13 MFA testi va step-up majburlashi buzilmadi) |
| 5 | `py -m pytest tests/contracts tests/modules tests/test_mobile_v2_client_contract.py tests/test_integration_wiring.py -q` | 813 o‘tdi |
| 6 | `py scripts/export_openapi.py` + `npm run gen:api` + `npm run lint` | v2 **161** operatsiya (155 → +6), `tsc` xatosiz |

### 4. Wave 9 yakuniy regressiya (17.09.2026)

| Band | Qiymat |
|---|---|
| Buyruq | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q -p no:cacheprovider --junitxml=…` |
| Kod holati | commit `4f468c3` + commit qilinmagan diff (tracked sha256 `98791a0d5338b5db`, untracked 476 fayl sha256 `00e00b496806437a`) |
| Migratsiya | `alembic heads` = `20260917_0074` (bitta head) — wave 9 da **yangi migratsiya yo‘q** |
| Muhit | Windows 11, Python 3.14, PG test stack `elchi-test-postgis-1` (127.0.0.1:45432), `elchi-test-redis-1`; boshqa sinov parallel ishlamadi |
| Oyna | 2026-09-17T12:51Z … 13:11Z (1206.1 s) |
| Natija | **2095 test: 2095 o‘tdi, 0 failure, 0 error, 0 skip** (exit 0) |
| AC01–AC44 | **42 PASS**, AC32 `FIELD`, AC40 `PROCEDURE` — wave 7 dan o‘zgarmadi (`py scripts/ac_coverage.py --junit …`) |

O‘sish (junit XML’lar solishtirildi): wave 7 = 2022 → wave 8 holati = 2071 (wave 8 ning 49 ta testi, ular
shu wave’gacha **to‘liq run’da hech qachon ishlamagan edi**) → wave 9 = 2095. Wave 9 ning +24 tasi:
`tests/pg/identity/test_staff_mfa_api_pg.py` 9, `tests/contracts/test_staff_mfa_api_wave9.py` 9 va
`tests/test_mobile_v2_client_contract.py` da +6 (u generatsiya qilingan operatsiyalar bo‘yicha parametrlangan,
6 yangi endpoint = 6 yangi holat).

**O‘zgargan xulqni aks ettirish uchun yangilangan test yo‘q** (AGENTS §7): wave 9 ning ikkala tuzatishi ham
mavjud testlarni **yashil** qildi, kutilgan natijani o‘zgartirmadi.

### 5. Wave 9 dan keyin ochiq qolgan bandlar

| Band | Sabab |
|---|---|
| MFA enforcement’ni yoqish (`enforce_privileged`) | Production’da ≥ 2 faol `super_admin` va ikkalasining omili kerak — ekran endi bor, qadamlar go-live checklistda |
| Login ekranining o‘zida MFA bosqichi | Hozir step-up buyruq vaqtida so‘raladi (5 daqiqalik oyna). Login oqimiga majburiy bosqich — `enforce_all` bilan birga keladigan qaror |
| §5.2 ro‘yxati uchun yurist xulosasi | Tashqi band; matn tasdiqlangan, production’da faollashtirish ikki `super_admin` orqali |
| Push yoqish (FCM) | K3 huquqiy xulosasi, Firebase credential, klientda xom token ro‘yxati |
| §19.3 yuklama profili | Staging va 100 000 e’lonli fixture kerak (NOT_RUN) |
| Deploy/production gate’lari (Q48, Q36, Q28, Q34/Q51/Q73, AC40, Q35) | Foydalanuvchi qaroriga ko‘ra keyinga qoldirilgan — holati o‘zgarmadi |
| WebAuthn (ADR-0021) | 2-bosqichdan keyingi alohida qaror |

## Wave 10 (17.09.2026) — tuman yo'nalish birligi sifatida va yo'ldagi tumanlar tavsiyasi

**Foydalanuvchi topshirig'i:** yo'nalish tanlashda Toshkent shahridan tashqari barcha viloyatlarga tuman
qo'shilsin; matching esa spetsifikatsiya bo'yicha ishlasin — Toshkent → Qarshi tanlagan haydovchiga Qarshigacha
bo'lgan tumanlarning e'lonlari ham tavsiya sifatida ko'rinsin.

**Tanlangan qarorlar (17.09.2026, uchta savol):** (1) doira — **v2 (mobile-app)**, v1 xulqi va javob shakli
tegilmaydi; (2) tuman ro'yxati — **legacy `districts` jadvalidan ko'chiriladi** (o'ylab topilmaydi);
(3) “yo'ldagi tuman” — **faqat tasdiqlangan marshrut bekatlari** asosida (spec §6.1/§6.5).

### Avvaldan mavjud bo'lgani (qayta yozilmadi)

Oraliq segment mosligi allaqachon bor edi: [`feed/rules.py::stop_segment_match`](../../app/modules/marketplace/feed/rules.py)
tasdiqlangan marshrut tartibida `origin ≤ pickup < dropoff ≤ destination` shartini tekshirib `on_route` beradi.
Ya'ni yetishmayotgan narsa matching emas — **tuman tanlov birligi sifatida yo'q edi**: `GET /districts` yo'q,
`FeedQuery`/`SavedSearch` faqat bekat yoki viloyatni bilardi, klient esa bekatni shunchaki nomi bo'yicha
tanlardi va qaysi tumanlar qamrab olinishini ko'rsatmasdi.

### Bajarilgan ishlar

| # | Ish | Nima yozildi |
|---|---|---|
| 1 | **`regions.requires_district`** (migratsiya `0075`) | Qoida **ma'lumotda**, kodda joy nomi qattiq yozilmaydi: standart `true`, `UZ-TK` (Toshkent shahri) uchun `false`. Migratsiya uni **faqat ustun yaratilganda** qo'yadi — operator keyin tuzatsa, qayta ishga tushirish uni bekor qilmaydi. Yangi bazada qoida katalog fixture'i bilan keladi (`tests/fixtures/geo/corridor_fixture.json`) |
| 2 | **G16 `GET /districts`** | `?region_id&q&limit` — pikerning ikkinchi qadami. `DistrictDTO.stops_count = 0` ochiq aytadi: joyni qidiruvda nomlash mumkin, lekin **hali tasdiqlangan bekat xizmat qilmaydi** — olib ketish va'da qilinmaydi |
| 3 | **G17 `GET /corridors/{id}/districts`** | “Toshkent → Qarshi” aslida qaysi tumanlarni qamrab oladi. Tartib — koridorning **tasdiqlangan marshrut versiyalari** bo'yicha (bir nechta marshrut bo'lsa, tuman eng erta pozitsiyasida turadi). Bekati bor, lekin tasdiqlangan marshrut yetib bormagan tuman ham ro'yxatda, ammo `on_confirmed_route=false` bilan va oxirida — spec §6.1 aynan shu xulosani taqiqlaydi (“hamma Toshkent→Qarshi yo'li Chiroqchidan o'tadi” deb qabul qilinmaydi) |
| 4 | **Feed va saqlangan qidiruvda tuman uchi** | `FeedQuery` va `SavedSearchCreate/DTO` ga `origin_district_id` / `destination_district_id`; har uchida aniq bitta havola (servisda `VALIDATION_ERROR`, DB'da `num_nonnulls(stop, region, district) = 1` CHECK). Tuman uchi o'sha tumandagi **faol bekatlarga** yoyiladi — moslik, sig'im va narx band'i baribir bekat va marshrut tartibi bo'yicha |
| 5 | **Legacy katalogdan import** | `scripts/import_legacy_districts.py`: legacy `cities`/`districts` → `geo_districts`, `legacy_city_mappings` orqali (mos region topilmasa yoki ikki xil mos kelsa — **hisobot va o'tkazib yuborish**, hech qachon taxmin emas). `--apply`siz faqat hisobot; har qator `legacy_district_id` bilan manbasiga bog'lanadi, shuning uchun qayta ishga tushirish dublikat yaratmaydi. Region yaratmaydi, Toshkent shahrini chetlab o'tadi |
| 6 | **Klient: yo'nalish pikeri** | `mobile-app/src/app/v2/DirectionPicker.tsx` — viloyat → (tuman) → bekat. Tuman qadami `requires_district` bo'yicha ko'rsatiladi; e'lon yaratishda oxiri **bekat** bo'lishi shart (`allowWholeDistrict={false}`), haydovchi lentasida esa “butun tuman bo'ylab” tanlash mumkin. `CreateListingScreen` va `DriverOffersScreen` shu komponentga o'tkazildi |
| 7 | **Klient: “Yo'lingizdagi tumanlar”** | Haydovchi koridorni tanlagach G17 ro'yxati chiplar sifatida chiqadi; bosilsa lenta o'sha tuman bo'yicha filtrlanadi. Tasdiqlanmagan tumanlar `*` bilan va “tasdiqlangan marshrut undan o'tishi hali tekshirilmagan” izohi bilan ko'rsatiladi — ekran hech narsani “yo'lingizda” deb noto'g'ri atamaydi |

### Nima ataylab qilinmadi

| Band | Sabab |
|---|---|
| To'liq O'zbekiston tuman ro'yxatini yozish | Qaror: legacy jadvaldan ko'chirish. Ma'muriy ma'lumotni xotiradan yozish tekshirilmagan bo'lardi (AGENTS §9) |
| Tuman qo'shniligi bo'yicha tavsiya | Spec §6.1/§6.5 to'g'ridan-to'g'ri taqiqlaydi; qaror ham “tasdiqlangan marshrut” variantini tanladi |
| v1 (Android) matching | v1 xulq o'zgarishi alohida tasdiqlangan qaror talab qiladi (AGENTS §2); katalog ham tegilmadi |
| Tuman yaratish/tahrirlash admin API'si | Bu wave doirasidan tashqari; hozir tuman import skripti yoki bevosita katalog orqali keladi — ochiq band |

### Tekshiruvlar (wave 10)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `… pytest tests/pg/geo/test_geo_districts_pg.py -q` | 7 o'tdi (G16/G17, `requires_district`, `stops_count=0`, ommaviy bo'lmagan koridor 404) |
| 2 | `… pytest tests/pg/marketplace/feed/test_feed_districts_pg.py -q` | 7 o'tdi — **foydalanuvchi ssenariysi**: Toshkent→Qarshi haydovchi Chiroqchi→Qarshi so'rovini `on_route` + `intermediate_segment` sifatida ko'radi; teskari yo'nalish va marshrutdan tashqari tuman hech narsa bermaydi |
| 3 | `… pytest tests/pg/geo/test_import_legacy_districts_pg.py -q` | 4 o'tdi (dry-run yozmaydi, Toshkent shahri chetda, region yaratilmaydi, qayta ishga tushirish no-op) |
| 4 | `… pytest tests/pg/geo tests/pg/marketplace tests/pg/test_migrations_smoke.py -q` | 196 test, 1 failure → geo OpenAPI sanog'i 19 → **21** ga yangilandi (G16/G17), qayta run yashil |
| 5 | `py -m pytest tests/contracts tests/modules tests/test_mobile_v2_client_contract.py tests/test_integration_wiring.py -q` | 816 o'tdi |
| 6 | `py scripts/export_openapi.py` + `npm run gen:api` + `npm run lint` | v2 **163** operatsiya (161 → +2), `tsc` xatosiz |

### Wave 10 yakuniy regressiya (17.09.2026)

| Band | Qiymat |
|---|---|
| Buyruq | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q -p no:cacheprovider --junitxml=…` |
| Kod holati | commit `4f468c3` + commit qilinmagan diff (tracked sha256 `98791a0d5338b5db`, untracked 482 fayl sha256 `468abfe326215ee6`) |
| Migratsiya | `alembic heads` = `20260917_0075` (bitta head); `0075` additiv va idempotent |
| Muhit | Windows 11, Python 3.14, PG test stack `elchi-test-postgis-1` (127.0.0.1:45432), `elchi-test-redis-1`; boshqa sinov parallel ishlamadi |
| Oyna | 2026-09-17T13:51Z … 14:06Z (911.7 s) |
| Natija | **2116 test: 2116 o‘tdi, 0 failure, 0 error, 0 skip** (exit 0) |
| AC01–AC44 | **42 PASS**, AC32 `FIELD`, AC40 `PROCEDURE` — o‘zgarmadi |

O‘sish 2095 → 2116 (+21): tuman endpointlari 7, tuman bo‘yicha lenta ssenariysi 7, legacy import 4 va
`tests/test_mobile_v2_client_contract.py` da +3 (u generatsiya qilingan operatsiyalar bo‘yicha parametrlangan).

**O‘zgargan xulqni aks ettirish uchun yangilangan test** (AGENTS §7): `tests/pg/geo/test_geo_api_pg.py` dagi
geo OpenAPI operatsiyalari sanog‘i 19 → 21 (G16 va G17 qo‘shilgani uchun). Boshqa hech bir mavjud testning
kutilgan natijasi o‘zgartirilmadi.

### Katalog yuklash (17.09.2026, foydalanuvchi topshirig‘i “tuman katalogini yukla”)

v2 katalogda **viloyatlar ham yo‘q edi** (faqat sintetik fixture), shuning uchun import skriptiga
`--create-regions` qo‘shildi: legacy `cities.region` qiymatlaridan viloyat yaratadi, nomni legacy matnidan
oladi, kodni esa ISO 3166-2:UZ jadvalidan (`REGION_CODES`). Jadvalda yo‘q nom — **hisobotga chiqadi va
o‘tkazib yuboriladi**, hech qachon taxmin bilan kodlanmaydi. Legacy katalog ikki xil yozilishini
(`Qashqadaryo` va `Qashqadaryo viloyati`, uch xil apostrof) bitta normalizator hal qiladi; Toshkent **shahri**
va **viloyati** hech qachon bir qatorga qo‘shilmaydi.

**Yuklash mashqi** (lokal, `elchi_test_catalog` bazasi — test stack ichida, tmpfs; production’ga ulanilmadi):

| Qadam | Buyruq | Natija |
|---|---|---|
| 1 | `py -m alembic upgrade head` | `20260917_0075` gacha o‘tdi |
| 2 | `py -m app.modules.platform.environment set development --by …` | marker `development` |
| 3 | `py scripts/seed_admin_required_data.py` | legacy katalog: 14 shahar/viloyat, **176 tuman** |
| 4 | `py scripts/import_legacy_districts.py --create-regions` | hisobot: 14 viloyat, **164 tuman** yaratilishi kerak; `Toshkent shahri` — SKIP (tuman ishlatmaydi) |
| 5 | `… --create-regions --apply` | **14 viloyat, 164 tuman, 13 `unverified` shahar→viloyat moslashuvi** |
| 6 | Shu buyruqni qayta ishga tushirish | `created 0 districts and 0 mappings` — idempotent |

Bazadagi yakuniy holat: `UZ-TK` (Toshkent shahri) — `requires_district = false`, **0 tuman**; qolgan 13
viloyatda 8–16 tadan tuman (`UZ-QR` 16, `UZ-FA`/`UZ-TO` 15, `UZ-AN`/`UZ-SA`/`UZ-QA`/`UZ-SU` 14, …);
`legacy_district_id` bo‘sh bo‘lgan tuman **0** (har biri manbasiga bog‘langan); `corridor_stops` — **0**,
shuning uchun har tuman `stops_count = 0` bilan chiqadi va klient “bekat yo‘q” deb ochiq yozadi.

**Bu mashq production yuklash emas:** baza tmpfs’da va sinov tugagach yo‘qoladi. Production’da shu ikki
buyruqni operator ishga tushiradi (go-live checklist 12-band), so‘ng `legacy_city_mappings` ni tasdiqlaydi va
tumanlarga tekshirilgan bekat biriktiradi.

### Wave 10 dan keyin ochiq qolgan bandlar

| Band | Sabab |
|---|---|
| Haqiqiy tuman katalogini **production’da** yuklash | Lokal mashq bajarildi (yuqoriga qarang); production’da operator ishga tushiradi — go-live checklist 12-band |
| `legacy_city_mappings` ni tasdiqlash | Import ularni `unverified` qoldiradi: nom bo‘yicha moslik — taklif, operator tasdig‘i emas |
| Tumanlarga tekshirilgan bekat biriktirish (Q27) | Hozir har tuman `stops_count = 0`; bekatsiz tuman qidiruvda bor, lekin taklif bermaydi |
| Tuman uchun admin API (qo'shish/tahrirlash) | Yangi bekat uchun tuman yo'q bo'lsa, hozir faqat import yoki katalog orqali qo'shiladi |
| Tuman chegaralari (`geo_districts.boundary`) | Bo'sh; “nuqta qaysi tumanda” savoli hozir bekat orqali javob beriladi |
| Oldingi wave'lardan qolgan bandlar | MFA enforcement, §5.2 yurist xulosasi, FCM, §19.3, deploy gate'lari — o'zgarmadi |

## Wave 11 (17.09.2026) — spetsifikatsiya bo'yicha QA auditi va topilgan nuqsonlar

Foydalanuvchi topshirig'i: `ELCHI_PRODUCTION_ARCHITECTURE.md` ning **barcha** talablarini haqiqiy repository,
ishlayotgan interfeys, API va baza bilan solishtirish; kamchiliklarni «aniqlandi → tuzatildi → tekshirildi →
dalil» tartibida yopish. Deploy, commit/push — yo'q; `android-app/` va `frontend/` tegilmadi.

### Usul

Hujjat to'liq o'qildi (977 satr, v1.0; repo'da **yagona** nusxa, `ELCHI_PRODUCTION_ARCHITTECTURE` nomli fayl
yo'q). Talablar `QA_REQUIREMENTS_MATRIX.md` ga ajratildi. **SC01–SC18 hujjatda yo'q** — majburiy stsenariylar
faqat AC01–AC44. Ular takrorlanmadi: avtomatik `COVERAGE_MATRIX.md` manbadir.

Tekshiruv **mock bilan emas**, jonli tizimda: doimiy dev bazasi (`docker-compose.dev.yml`) + `uvicorn :8001`;
har qadam HTTP orqali bajarilib, natija bazadan o'qib tasdiqlandi (`scripts/qa_probe.py`, 30 tekshiruv).

### Topilgan va tuzatilgan nuqsonlar

| ID | Jiddiylik | Nuqson | Tuzatish |
|---|---|---|---|
| **F-01** | **P0** | Routing provayderi o'chiq bo'lsa (Q24/Q46 — production konfiguratsiyasi) haydovchi **umuman safar yarata olmasdi**: `POST /trips` `route_version_id` talab qiladi, uni olishning yagona yo'li `POST /routes/preview` edi va u `503` qaytaradi. Safar yo'q → `trip_offer` yo'q → marketplace'ning taklif tomoni yopiq | **G18 `GET /corridors/{id}/routes`** (tasdiqlangan marshrutlar katalogi, provayder kerak emas) + klientda `DriverPlanScreens.tsx` (avtomobil va safar yaratish) |
| **F-03** | P1 | Qarshi taklif backendda bor, **klientda yo'q** edi — ikki tomonlama kelishuvning yarmi ishlamasdi | `counterProposal`/`withdrawProposal` + `ListingDetailScreen` da forma (`price_revisions_left` ko'rsatiladi) |
| **F-02** | P2 | Hamyonda `posted_balance_minor` ko'rsatilmasdi — `available = posted − held` munosabati yo'qolardi (§9.1/§9.3) | «Kiritilgan (jami)» qatori qo'shildi |
| **F-06** | P1 | Dev backend tmpfs test bazasida ishlayotgan edi; `.env` v1 revizyali bazaga ko'rsatardi | `docker-compose.dev.yml` (doimiy PostGIS) + `.env` + `RUNNING.md` |

Batafsil: [`QA_FINDINGS.md`](QA_FINDINGS.md).

### Nuqson topilmagan, lekin dalil bilan tasdiqlangan bandlar

Server narxni o'zi hisoblaydi; o'z taklifini qabul qilish `403`; eskirgan taklif `409`; balanssiz bron
`409` va bron yaratilmaydi; idempotent replay bitta bron/bitta hold; segment allocation'lari (2 o'rin → 3 qator);
komissiya `1500 bps` bo'yicha; pending top-up pul emas; `service/cash/commission` statuslari mustaqil;
flag o'chiq bo'lsa `403 FEATURE_DISABLED`; OTP `429`; logout'dan keyin `401`.

### Yangi fayllar

`docs/architecture/QA_REQUIREMENTS_MATRIX.md`, `QA_FINDINGS.md`, `QA_VERIFICATION_REPORT.md`,
`scripts/qa_probe.py`, `tests/pg/geo/test_geo_routes_catalogue_pg.py`,
`mobile-app/src/app/v2/DriverPlanScreens.tsx`, `docker-compose.dev.yml`.

### Tekshiruvlar (wave 11)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `py scripts/qa_probe.py` (jonli API + DB) | **30 tekshiruv, 0 failure** |
| 2 | `… pytest tests/pg/geo/test_geo_routes_catalogue_pg.py -q` | 4 o'tdi (F-01 regressiyasi) |
| 3 | `py scripts/export_openapi.py` + `npm run gen:api` + `npm run lint` | **164** operatsiya (+1: G18), `tsc` xatosiz |
| 4 | To'liq PostgreSQL regressiyasi | **2128 test, 0 failure** (17.09 15:51–16:05 UTC, exit 0) |

### Wave 11 dan keyin ochiq qolgan bandlar

O'zgarmadi: AC32 (dala GPS), AC40 (restore mashqi), §19.3 (yuklama), §5.2 (yurist xulosasi), MFA enforcement,
FCM, deploy gate'lari. Yangi qo'shildi: **F-05** — v2 klient 150 yo'ldan 68 tasini chaqiradi (M2 matches, naqd
kvitansiya, admin koridor/moliya ekranlari yo'q); ruscha lokalizatsiya va a11y auditi bajarilmagan.

## Wave 12 (17.09.2026) — v1 `mobile-app` ekranlari 2-bosqich dvigatelida

Foydalanuvchi qarori: **«v1 ekranlarining o'zi v2 ga o'tsin»** va «qo'shimchalar, funksiyalar shu frontend
dizayni bo'yicha amalga oshirilishi shart» (manba: `github.com/elchiuzb-star/elchi`, `mobile-app` UX/UI —
repo'dagi `git HEAD` bilan bayt-ma-bayt bir xil ekani tekshirildi).

Shu sababli **alohida v2 ilovasi qurilmadi**. `mobile-app/src/app/ConnectedApp.tsx` — o'sha v1 ekranlar; faqat
ular ortidagi katalog va buyruqlar 2-bosqich API'siga ulandi. Dizayn primitivlariga tegilmadi:
`PrimaryButton`, `SecondaryButton`, `Field`, `TopBar`, `BottomNav`, `EmptyState`, `OrderCard`,
`LocationPointRow`, `RouteSummaryRow`, `StatusBadge`, `ClientMapCanvas`, splash/onboarding/rol/telefon/OTP va
profil ekranlari o'zgarmagan. Yorliqlar saqlandi: «Yuk yuborish», «Yo'nalishni ko'rish», «Saqlash»,
«Buyurtmani e'lon qilish», tablar «Bosh sahifa / Yo'nalishlar / Moslar / Buyurtmalar / Profil».

### Mijoz tomoni

| Ekran (o'zgarmagan) | Avval (v1) | Endi (v2) |
|---|---|---|
| `client-location-selector` «Qayerdan?/Qayerga?» | `cities` jadvali | `GET /regions` (`RegionSelector`) |
| `client-district-selector` «Tumanni tanlang» | `districts` jadvali | `GET /districts?region_id` (`GeoDistrictSelector`), har qatorda faol bekatlar soni |
| `client-stop-selector` «Bekatni tanlang» (yangi qadam) | — | koridor bekatlari; tuman yoki (Toshkent shahri uchun) hudud bo'yicha |
| `client-home` | tavsiya narx | «Yo'nalishdagi tumanlar» — G17, `on_confirmed_route=true` bo'lganlari, yurish tartibida |
| `client-route-summary` | «Xarita holati» matni | tasdiqlangan marshrut xaritasi (G18 polyline + bekatlar) + jo'nash oynasi va narx |
| `client-order-address` | 2 telefon | + jo'natuvchi/qabul qiluvchi ismi (server publish uchun talab qiladi) |
| `client-order-parcel` (yangi) | — | Q68 enum bo'yicha tur, og'irlik, o'lchamlar |
| `client-order-review` → e'lon | `POST /api/v1/orders` | `POST /listings` + `/publish`, `Idempotency-Key` har urinishda |
| `client-success` | — | server maskalagan aloqa ma'lumotlari haqida ogohlantirish (Q43) ko'rsatiladi |
| `client-orders` | v1 buyurtmalar | v2 bronlar + v2 e'lonlar, ostida «Eski buyurtmalar» (v1, faqat o'qish/bekor qilish) |
| `client-listing-bids` «Haydovchi takliflari» | v1 bid'lar | `GET /listings/{id}/proposals`, «Haydovchi #1» (Q40), accept `expected_listing_terms_version` bilan |
| `client-booking-detail` (yangi) | — | bron holati, **topshirish/yetkazish kodlari** (B5, faqat mijozda) va «Yetkazilganini tasdiqlash» |

### Haydovchi tomoni

| Ekran (o'zgarmagan) | Avval (v1) | Endi (v2) |
|---|---|---|
| `driver-profile-form` | v1 profil | + o'rin/yuk sig'imi; saqlashda `POST /vehicles` (bir marta, raqam bo'yicha) |
| `driver-routes` «Yo'nalishlarim» | saqlangan yo'nalishlar | `GET /me/trips`; kartada T9 amali: «Chiqishni boshlash» → «Yo'lga chiqdim» → «Safarni yakunlash» |
| `driver-add-route` «Yo'nalish qo'shish» | shahar/tuman | avtomobil + koridor + **tasdiqlangan marshrut** + vaqt + o'rin + yuk sig'imi → `POST /trips` |
| `driver-feed` «Mos buyurtmalar» | v1 lenta | `GET /feed?side=requests`; ikki uchi mijozdagi bir xil selektor bilan tanlanadi — **tuman tanlansa yo'ldagi barcha bekatlar** so'roviga aylanadi |
| `driver-bid` «Narx taklif qiling» | v1 bid | `POST /listings/{id}/proposals`; olib ketish oynasi safar shu bekatga yetib kelish vaqtidan olinadi, mijoz oynasi bilan kesishmasa tugma yopiq |
| `driver-orders` «Buyurtmalar tarixi» | v1 buyurtmalar | `GET /me/bookings?role=driver` |
| `driver-order-detail` | v1 status | `confirmed → arrive_at_pickup → pick_up (kod) → start_transit → deliver (kod)`; kodlarni mijoz aytadi, haydovchi ko'ra olmaydi (403) |
| `driver-income` | «Sof daromad», «15% ulush» | **«Komissiya balansi»**: available/held/pending ajratilgan, to'ldirish so'rovi va uning holati |

### Ataylab o'zgartirilgan yagona yorliq

«Sof daromad» → «Komissiya balansi». Sabab: 2-bosqichda yo'lkira mijozdan **naqd** olinadi, ilova uni
bilmaydi; hamyonda faqat platforma komissiyasi turadi (§9.1–9.3). Eski yorliqni saqlash «hisoblangan
komissiyani tushgan pul deb ko'rsatish» taqiqiga zid bo'lardi (AGENTS §9).

### Jonli tekshiruv (mock emas)

Yangi skript **`scripts/qa_probe_ui_journey.py`** — ekranlar chaqiradigan aynan shu ketma-ketlikni jonli
stack'da bajaradi (PostGIS `127.0.0.1:45433`, `uvicorn :8000`, Vite `:5173`); production markerli bazada ishlashdan
bosh tortadi:

    QA_BASE=http://127.0.0.1:8000 py scripts/qa_probe_ui_journey.py
    -> 22 tekshiruv, 0 failure (17.09.2026)

| # | Qadam | Natija |
|---|---|---|
| 1 | `/regions` | 14 hudud; `UZ-TK.requires_district = false` |
| 2 | `/districts?region_id=UZ-QA` | 17 tuman, 3 tasida faol bekat |
| 3 | `/corridors/{id}/districts` | `Toshkent - Samarqand - Kattaqo'rg'on - Chiroqchi - Qarshi` (yurish tartibida), `Kitob` — `on_confirmed_route=false` |
| 4 | `/corridors/{id}/routes` | `confirmed`, 512 463 m (provayder o'chiq bo'lsa ham) |
| 5 | E'lon yaratish | izohdagi telefon **maskalandi**, `CONTACT_INFO_MASKED` ogohlantirishi qaytdi (Q43) |
| 6 | `/publish` | `parcel_enabled` koridor uchun yoqilgach `published` (avval `403 FEATURE_DISABLED` — Q5 to'g'ri ishlayapti) |
| 7 | Haydovchi: hujjatlar → tasdiq → avtomobil → tasdiq → safar | `planned`, 4 bekat |
| 8 | Tuman bo'yicha lenta | e'lon `exact` sifatida ko'rindi; `meta.degraded=[ROUTING_UNAVAILABLE]`, `match_scope=confirmed_stops` (Q46) |
| 9 | Taklif | mijozda **`Haydovchi #1`** — ism/raqam yo'q (Q40) |
| 10 | Balans | pending to'ldirish pul emas (`available=0`); moliya tasdiqlagach `available=50 000 so'm` |
| 11 | Accept | bron `confirmed`, komissiya **36 000 so'm hold** (240 000 × 1500 bps), available 14 000 |
| 12 | Kodlar | mijozda `pickup_code`/`delivery_code`; **haydovchi so'rasa `403`** (B5) |
| 13 | Safar + bron amallari | `boarding → in_progress`; `arrive_at_pickup → pick_up(kod) → start_transit → deliver(kod)` |
| 14 | Mijoz `complete` | `completed`; hold **capture** qilindi (posted 50 000 → 14 000, held 0) |
| 15 | `npm run lint` (tsc) / `npm run build` | xatosiz / `✓ built` |
| 16 | `py scripts/qa_probe_ui_journey.py` | **22 tekshiruv, 0 failure** |

Backend kodi bu wave'da o'zgarmadi (faqat dev bazasida koridor flag'i yoqildi), shuning uchun PG regressiyasi
qayta yurgizilmadi — oxirgi natija wave 11 dagi **2128 test, 0 failure**.

### Ochiq qolgan bandlar (wave 12)

- **Posilka rasmi**: `client-order-photo` saqlanib qoldi va havola `parcel.photo_file_id` ga yoziladi, lekin
  `marketplace/views.py` uni imzolangan havolaga aylantirmaydi — haydovchi rasmni hali ko'ra olmaydi
  (ADR-0021 dan keyin ochiq turgan «dalil fayllarini imzolangan havola bilan ko'rsatish» bandi).
- **v1 buyurtmani tahrirlash** olib tashlandi (yaratish oqimi v2 ga o'tgani uchun); eski buyurtmalarni ko'rish,
  bekor qilish, nizo ochish va yetkazilganini tasdiqlash o'z joyida qoldi.
- Yo'lovchi (passenger) e'loni klientda hali yo'q — «Yuk yuborish» oqimi faqat `parcel` yaratadi (Q7/K7 bo'yicha
  passenger production'da baribir o'chiq).
- Qarshi taklif (counter), naqd kvitansiya, tracking va chat ekranlari hali `v2/` ostidagi alohida
  komponentlarda; ular referens dizayniga hali ko'chirilmagan.
- F-05 (v2 klient API qamrovi), AC32, AC40, §19.3, §5.2, MFA enforcement, FCM — o'zgarmadi.

## Wave 13 (17–18.09.2026) — wave 12 dan qolgan ochiq ishlarni yopish

Doira: posilka rasmi uchun imzolangan havola, hamyon terminologiyasi, v1 tahrirlashni butunlay olib tashlash,
`MarketplaceSection.tsx` ostidagi ulanmagan ekranlarni (qarshi taklif, chat, kuzatuv, naqd qayd) referens
dizayniga ko'chirish va Q7 bo'yicha yo'lovchi oqimini yopiq saqlash. Har bandda contract, migratsiya ehtiyoji,
flag, ruxsat va invariant test tekshirildi.

### A. Posilka rasmi — imzolangan havola

**Ildiz sabab.** `parcel.photo_file_id` klient yuborgan qiymatni **tekshirmasdan** bazaga yozardi. Klient esa
`POST /api/v1/files/upload` qaytargan **imzolangan URL**ni yuborardi. Natijada: (1) muddati o'tadigan credential
bazada saqlanardi, (2) egalik tekshirilmasdi — boshqa odamning faylini biriktirish mumkin edi, (3) haqiqatan
rasm kerak bo'lgan yagona tomon — tayinlangan haydovchi — uni umuman ololmasdi, chunki haydovchi
`ListingDTO` ni hech qachon o'qimaydi.

**Tuzatish.**

| Qatlam | O'zgarish |
|---|---|
| Kontrakt | `app/contracts/dto.py`: `MediaRefDTO` (`file_id`, `url`, `expires_at`, `content_type`) |
| Yozish | `marketplace/service.py`: `_resolve_cargo_photo()` — `file_access.resolve_attachment` orqali yuklovchiga bog'lanadi, `cargo_photo` turi va rasm kengaytmasi tekshiriladi, bazaga **kanonik kalit** yoziladi |
| O'qish (egasi/xodim) | `ParcelDetails.photo`; `listing_dto(..., viewer_user_id=...)` — `viewer_user_id` berilmasa rasm ham, kalit ham qaytmaydi |
| O'qish (haydovchi) | `BookingClientDTO.parcel_photo` — bron ikki tomon o'rtasida bo'lgani uchun aynan «tayinlangan haydovchi» qoidasi (Q6) |
| Xodim auditi | `_contact_fields` ga `parcel.photo` qo'shildi — xodim rasmni ochsa telefon ko'rgani kabi audit qatori yoziladi (BR M2) |
| Klient | `ParcelPhoto` komponenti: loading, placeholder, `onError` → «Qayta yuklash», `expires_at` bo'yicha avtomatik refetch, to'liq ekran |

Bucket ochiq qilinmadi: havola `app/utils/file_access.py` dagi mavjud HMAC imzosi bilan minted, `GET
/api/v1/files/{key}` `exp`/`sig` ni tekshiradi. **Kalitning o'zi hech narsa ochmaydi.**

Migratsiya **kerak emas**: ustun turi o'zgarmadi. Eski qatorlarda imzolangan URL qolishi mumkin —
`normalize_storage_key` uni ham kalitga keltiradi, shuning uchun o'qish ishlaydi; keyingi tahrirda kanonik
shaklga yoziladi (expand → migrate → switch, majburiy backfill yo'q).

**Yo'l-yo'lakay topilgan nuqson.** `POST /api/v2/admin/listings/on-behalf` `listing_dto(..., viewer_user_id=...)`
ni chaqirardi, lekin `listing_dto` da bunday parametr **yo'q edi** — endpoint `TypeError` bilan 500 berardi.
Mavjud test servisni to'g'ridan-to'g'ri chaqirgani uchun buni ko'rmagan. Endi parametr bor va HTTP orqali test
qo'shildi.

### B. «Sof daromad» → «Komissiya balansi»

Eski yorliq qaytarilmadi. Qo'shimcha auditda topilgan va tuzatilgan joylar:

| Joy | Avval | Endi |
|---|---|---|
| `driver-income` | «Band qilingan» / «Tasdiqlanmagan» | **Komissiya balansi** + «Ushlab qolingan komissiya», «Qaytarilgan komissiya», «To'ldirishlar», «Tasdiqlanmagan so'rov» |
| `driver-income` izohi | — | «ELCHI komissiyalarini to'lash uchun balans. Yo'lkira bu yerda hisoblanmaydi.» |
| Bron ekranlari | — | «Yo'lkira: N so'm — haydovchiga naqd to'lanadi» (balansga qo'shilmaydi) |
| `AdminOverviewPanel` | «Tizim foydasi», «Haydovchilar daromadi» | «Hisoblangan tizim ulushi», «Haydovchilarga qoladigan summa» + bo'lim boshida ogohlantirish |
| Haydovchi profili | «Daromad va mos buyurtmalar oynasiga qaytish» | «Balans va mos buyurtmalar…» |

«Qaytarilgan komissiya» va «To'ldirishlar» `GET /wallet/transactions` dagi `kind` bo'yicha hisoblanadi
(`reversal` / `topup`), ya'ni wallet faqat `hold/capture/release/reverse` semantikasida qoladi. Legacy
`orders.system_fee` dan hech qanday qarzdorlik yaratilmaydi (yangi kod ham yozilmadi).

### C. v1 tahrirlashni to'liq olib tashlash

- Klientdan: «Buyurtmani tahrirlash» CTA (wave 12), `client-order-route` ekrani, `editingOrderId` holati,
  `isEditing` shoxlari.
- API modulidan: `createClientOrder`, `updateClientOrder`, `publishClientOrder` — o'chirildi, chunki yangi
  buyurtma v2 e'loni.
- v1 da qoladi: ko'rish, bekor qilish, nizo, yetkazilganini tasdiqlash, takliflarni ko'rish.

**Backend bloki kerak emasligi tekshirildi:** v1 buyurtma endpointlari `order_id: int` qabul qiladi va faqat
`orders` jadvaliga tegadi; v2 agregatlari boshqa jadvallarda va `public_id` bilan adreslanadi. Yangi
`tests/pg/test_v1_v2_object_isolation.py` buni to'rt tomondan isbotlaydi: v2 bron id si bilan chaqirilgan v1
mutatsiyalari `JSONResponse` (404) qaytaradi va v2 qatorlarining `version`/`updated_at` i o'zgarmaydi; ikki
dvigatel jadvallari orasida FK yo'q; `/admin/legacy-orders` faqat `GET`; v1 modullari v2 ga faqat
`service`/`views` orqali murojaat qiladi (ADR-0006).

> v1 buyurtma **yaratish** bloklanmadi: Q4 bo'yicha muzlatilgan Android v1 bozori 2-bosqichda parallel ishlaydi
> va cutover bu bosqichga kirmaydi. Bloklash tasdiqlangan qarorni buzardi.

### D. Ulanmagan ekranlarni ko'chirish

`MarketplaceSection.tsx` **o'chirildi**, u bilan birga faqat undan chaqiriladigan sakkiz fayl. Qolgan
`app/v2/` da faqat haqiqatan mount qilinadigan narsa bor: `PublicSharePage` (`/e/{token}`), `RouteMap`, va
ular ishlatadigan `ui.tsx` / `useAsync.ts`.

| Ekran | Qayerga ko'chdi | Nima qo'shildi |
|---|---|---|
| Qarshi taklif | `client-listing-bids` (mijoz) + yangi `driver-proposals` (haydovchi) | `expected_revision` bilan konflikt boshqaruvi, `price_revisions_left`, yopilgan taklifda tugma yo'q, `counterPending` bilan ikki marta yuborishdan himoya, optimistik UI **yo'q** |
| Chat | `booking-chat` | haqiqiy `booking_id`, `limit` bilan «Oldingi xabarlar», yuborish holati, muvaffaqiyatsizlikda matnni qaytarib «Qayta urinish», vaqt belgisi, server maskalagan matn va ogohlantirish |
| Kuzatuv | `booking-tracking` | **«Holat kuzatuvi»** (lifecycle) va **«Jonli joylashuv»** aniq ajratilgan; jonli qism `tracking_enabled` flag va `window.is_open` ostida; ma'lumot yo'q bo'lsa sabab yoziladi, soxta marker yo'q |
| Naqd qayd | ikkala bron ekranida `CashAcknowledgement` | «Naqd to'lov qaydi»; «ELCHI qabul qildi» degan ma'no yo'q; qayd → tasdiq/e'tiroz; e'tiroz operator navbatiga |

Shu bilan birga ikkita **funksional bo'shliq** yopildi: v2 broni yakunlangach mijoz haydovchini **baholay**
olmasdi (`booking-rating` → `POST /bookings/{id}/ratings`) va v2 broni bo'yicha **nizo** ocholmasdi
(`booking-dispute` → `POST /bookings/{id}/disputes`, ochiq nizolar bron ekranida ko'rinadi). Ikkalasi ham v1
ekranlarining aynan o'sha shakli — yulduzlar va «Muammo turi» selekti — bilan chizildi.

Naqd qaydni qayta o'qish uchun backendda bo'shliq bor edi: `POST /bookings/{id}/cash-receipts` javobdan
boshqa hech qayerda ko'rinmasdi, shuning uchun sahifa yangilangach ikkinchi tomon tasdiqlay olmasdi. Endi
`BookingClientDTO.cash_receipt` (oxirgi qayd) qo'shildi.

### E. Reference designga muvofiqlik

Yangi ekranlar o'sha primitivlar bilan: `TopBar`, `Field`, `PrimaryButton`, `EmptyState`, `rounded-[14px]`
kartalar, `#1B4FD8` / `#EEF2FF` / `#E5E7EB`. Har birida loading, xato, bo'sh va yopiq holat matni bor.
Navigatsiya — ekran holati (`Screen` union), typed; URL yo'q.

**Xato holatlari.** `utils/errors.ts` faqat v1 kodlarini bilardi, shuning uchun yangi oqimlardagi har bir rad
javobi «Xatolik yuz berdi» deb ko'rinardi. Endi v2 kodlari xaritaga qo'shildi — foydalanuvchi o'zi tuzata
oladigan holatlar aniq yoziladi (balans yetmasa, taklif o'zgargan bo'lsa, yuk sig'masa, safar boshlanmagan
bo'lsa va h.k.). `tests/contracts/test_client_error_messages.py` kalitlarning haqiqiy `ErrorCode` ekanini va
foydalanuvchi uchraydigan kodlarda matn borligini qo'riqlaydi.

Ikkita dead import to'plami ham tozalandi (`Pencil`, `Trash2`, `Search`, v1 driver route/feed chaqiruvlari).

### F. Q7 — yo'lovchi e'loni

Klientda yo'lovchi oqimi **umuman yo'q**: `service_type: "passenger"` bilan e'lon yaratadigan bitta ham joy
qolmadi (`CreateListingScreen` o'chirildi). `tests/contracts/test_client_has_no_passenger_flow.py` buni
qo'riqlaydi va bir vaqtning o'zida deep-link yo'qligini isbotlaydi: `main.tsx` da faqat `/admin` va `/e/`
manzillari bor, qolgani React holati.

Xizmat flag'lari **koridor doirasida** o'qiladi (`GET /feature-flags/effective?corridor_id=…`). Bu wave'da
topilgan xato: klient flag'ni davlat doirasida o'qirdi, u yerda pilot xizmat o'chiq bo'lgani uchun ochiq
koridor ham yopiq ko'rinardi.

### G. OTP ekrani (F-11, P0)

Foydalanuvchi xabari bo'yicha tekshirildi: ekran «5 xonali kod» deb yozardi, tugma esa **6** belgi talab
qilardi, server esa 5 xonali kod yuboradi — natijada v2 klientda OTP orqali kirish **umuman ishlamasdi**.
Raqam endi bitta manbadan (`VITE_OTP_LENGTH`, default 5) olinadi va yorliq, placeholder, kiritishni kesish va
tugma sharti shundan kelib chiqadi. Test kodi ko'rsatkichi faqat dev build'da. Batafsil: `QA_FINDINGS.md` F-11.

### Tekshiruvlar (wave 13)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `py -m pytest tests/contracts -q` | o'tdi (yangi passenger/deep-link va xato-xaritasi qo'riqchilari bilan) |
| 2 | `py -m pytest tests/pg/marketplace/test_parcel_photo_access_pg.py -q` | **6 test, 0 failure** |
| 3 | `py -m pytest tests/pg/test_v1_v2_object_isolation.py -q` | **4 test, 0 failure** |
| 4 | `py scripts/export_openapi.py` + `npm run gen:api` | 164 operatsiya, tiplar sinxron |
| 5 | `npm run lint` (tsc) / `npm run build` | xatosiz / `✓ built` |
| 6 | `py scripts/qa_probe_ui_journey.py` (jonli stack) | **44 tekshiruv, 0 failure** |
| 7 | `py -m pytest tests/test_mobile_v2_client_contract.py -q` | o'tdi — guard ikkita yangi naqd-qayd yo'lini ham ko'radi |
| 8 | To'liq regressiya (`pytest tests/`, toza yugurish) | **2147 test, 0 failure** (18.09, exit 0) |
| 9 | F-11 dan keyin: `pytest tests/contracts tests/test_auth.py -q` | o'tdi (OTP qo'riqchisi bilan) |
| 10 | Jonli OTP: `request-otp` → `12345` (5 xona), `verify-otp` → `200`; 4 xona bilan → `400 OTP_INVALID` | tasdiqlandi |

Probe endi quyidagilarni ham dalil bilan yopadi (baholash va nizo qadamlari ham): egasi imzolangan havola oladi va bazada kalit turadi;
tayinlangan haydovchi havola oladi va u ochiladi; **imzosiz** o'sha yo'l `403`; begona foydalanuvchi bronni
`404` ko'radi; qarshi taklif joriy versiyaga aylanadi, eskirgan revizyaga `409`, muallif o'z versiyasini qabul
qila olmaydi; chatdagi telefon maskalanadi; kuzatuv oynasi yopiq bo'lsa sabab qaytadi; naqd qayd balansni
o'zgartirmaydi va ikkinchi tomon uni tasdiqlaydi; yakunlangan bron baholanadi va baho izohidagi telefon ham
maskalanadi; nizo ochiladi va `/me/disputes` da ko'rinadi.

**Regressiya davomida ushlangan ikki narsa.** (1) `tests/test_mobile_v2_client_contract.py` `decideCashReceipt`
yo'li `${decision}` shabloni bilan qurilganini ushladi — server `acknowledge`/`contest` ni alohida route
sifatida beradi; ikkala yo'l to'liq yozib chiqildi (yo'lni o'zgaruvchiga olish testdan yashirardi, shuning uchun
unday qilinmadi). (2) `tests/pg/test_v1_order_races.py` dagi bitta poyga testi bir marta yiqildi: `assert_waited`
majburiy kesishuv **yuz bermaganini** aytadi (kech worker lock'ni erta worker commit boshlashidan 0.7 s oldin
olgan) — ya'ni tajriba o'tkazilmagan, invariant buzilmagan. Sabab: o'sha yugurish paytida bir vaqtda `vite
build` va probe ishlayotgan edi. Izolyatsiyada 4/4 o'tdi va birinchi to'liq yugurishda ham o'tgan.

### Wave 13 dan keyin ochiq qolgan bandlar

- **Saqlangan qidiruv** (`/me/saved-searches`) uchun ekran yo'q — `SavedSearchesScreen` `MarketplaceSection`
  bilan birga o'chirildi. API klienti (`client-extras.api.ts`) joyida; UI alohida karta bilan qaytarilishi kerak.
- **Nizolar ro'yxati** alohida ekran sifatida yo'q: ochiq nizo bron ekranida ko'rinadi, lekin barcha nizolar
  ro'yxati va dalil yuklash (`addDisputeEvidence`) ulanmagan.
- **Amendment (B9)** klientda yo'q.
- **Frontend test runner yo'q**: `mobile-app` da faqat `tsc --noEmit` va `vite build`. Vitest kabi kutubxona
  qo'shish ADR/karta talab qiladi (AGENTS §2), shuning uchun frontend dalili — tip tekshiruvi, build va jonli
  probe.
- Dev bazada fixture koridorida `passenger_enabled` yoqilgan (seed'dan). Production'da bu Q48 gate bilan
  bloklangan (`tests/pg/geo/test_geo_q48_gate_q47_pg.py`), klientda esa oqim yo'q.
- AC32, AC40, §19.3, §5.2, MFA enforcement, FCM, deploy gate'lari — o'zgarmadi.

## Wave 14 (18.09.2026) — Q88/Q89: xaritadan nuqta va yo'lovchi rejimi

Foydalanuvchi qarori (Q88): mijoz yo'nalish uchini **bekat ro'yxatidan emas, xaritadan** belgilaydi. Bu spec
§6.1/§6.2 dan chekinish; xavotir bildirilgan va qaror tasdiqlangan. Q89: yo'lovchi xizmati klientda quriladi
va `passenger_enabled` flag ortida turadi (K7).

Sabab ma'lumotda: katalogda **170 tumandan atigi 6 tasida** faol bekat bor, ya'ni bekatga majburlash mijozni
amalda bloklaydi.

### Chekinish qanday chegaralangan

Nuqta «xaritaning istalgan joyi» bo'lib qolmasligi uchun beshta chegara kodda va DB'da:

| Chegara | Qayerda |
|---|---|
| Uch = bekat **yoki** nuqta, ikkalasi emas | `CHECK num_nonnulls(stop_id, point) = 1` — `listings`, `proposal_versions`, `bookings` |
| Nuqta tasdiqlangan yo'lga proyeksiya bo'ladi | `geo.project_point_on_route` (`ST_LineLocatePoint` + geography masofasi) |
| Radius — **koridor konfiguratsiyasi** | `service_corridors.max_point_offset_m` (0077), default 3000 m, `CHECK 100..25000` |
| Pickup dropoff'dan oldin | `origin.fraction < destination.fraction`, aks holda `ROUTE_MISMATCH` |
| Sig'im baribir segment bo'yicha | `booking_allocations` o'zgarmadi; proyeksiya segmentni beradi |
| Nuqtali uch `exact` olmaydi | `feed._point_listing_match` → eng ko'pi `on_route` |

### Migratsiyalar

* **0076** `marketplace_point_endpoints` — uch stolga `*_point` (geometry Point 4326), `*_district_id`,
  `*_address`, `*_route_offset_m`; bekat FK'lari nullable; XOR va «nuqta bo'lsa tuman bo'lsin» CHECK'lari;
  `listings` nuqtalariga GiST indeks.
* **0077** `geo_corridor_point_radius` — `service_corridors.max_point_offset_m`. **Sizning tavsiyangiz bo'yicha
  radius global konstanta emas**: Toshkent ichida 3 km yo'ldan juda uzoq, uzoq magistralda esa tor. Kod
  konstantasi faqat qator o'qib bo'lmaganda ishlaydigan fallback.

Ikkalasi ham additiv, idempotent; `alembic heads` bitta (`20260918_0077`).

### Zanjir

| # | Qadam | Nima bo'ldi |
|---|---|---|
| 1 | `ListingCreate` | `origin_point`/`destination_point` (`PointEndInput`), stop id'lar ixtiyoriy, XOR validator; trip-offer faqat bekat bilan |
| 2 | `create_listing` | Nuqtalardan **koridor topiladi**: har nomzodning tasdiqlangan yo'llariga proyeksiya, radius koridornikidan, eng kichik og'ish yutadi |
| 3 | Tartib | `origin.fraction >= destination.fraction` → `ROUTE_MISMATCH` |
| 4 | Taklif | Nuqtali e'londa haydovchi joyni **o'zgartira olmaydi** (`listing_ends_are_points`); nuqta taklifga meros bo'ladi |
| 5 | Accept → bron | Nuqta, manzil va og'ish **snapshot** qilinadi; pul qayta hisoblanmaydi |
| 6 | Occurrence | Proyeksiya segmentni beradi; ETA **safarning o'z jadvalidan** interpolyatsiya qilinadi |
| 7 | Feed/DTO | Nuqtali e'lon tuman bekatlari orqali topiladi, `on_route`; DTO'da `origin_point`/`pickup.point` |
| 10 | Preview | **`GET /directions/preview`** — koridor, yo'l polyline'i, masofa/vaqt, radius, har uchning og'ishi, yo'ldagi tumanlar |

### Klient

* **Ikki rejim** bosh sahifada: «Yuk yuborish» / «Yo'lovchi». Flag o'chiq bo'lsa **tugma umuman yo'q**.
* Oqim: `Qayerdan?` → hudud → tuman → **xarita** → `Qayerga?` → … → preview → tasdiqlash.
* `MapPointPicker`: markazda turgan pin (xarita siljiydi, nishon emas), qidiruv, reverse-geocode qilingan
  manzil, tanlangan joy tasdig'i, radiusni odam tilida tushuntirish, oldingi nuqtani qayta tahrirlash.
* Holatlar: «Yo'nalish tekshirilmoqda...», koridor + masofa + tumanlar, va rad javobida
  **«Bu ikki nuqta hozircha ELCHI yo'nalishiga mos kelmaydi»** + nima qilish kerakligi.
* UI hech qayerda nuqtali uchni «aniq mos» demaydi.

### Tekshiruvlar (wave 14)

| # | Buyruq | Natija |
|---|---|---|
| 1 | `pytest tests/pg/marketplace/test_point_endpoints_pg.py` | **11 test, 0 failure** |
| 2 | `pytest tests/pg/marketplace tests/pg/bookings tests/pg/trips` | o'tdi — bekat yo'llari buzilmagan |
| 3 | `pytest tests/contracts` | o'tdi |
| 4 | `py scripts/qa_probe_ui_journey.py` | **54 tekshiruv, 0 failure** (22 → 44 → 54) |
| 5 | `npm run lint` / `npm run build` | xatosiz / `✓ built` |
| 6 | `export_openapi` + `gen:api` | **165** operatsiya (+1: `/directions/preview`) |
| 7 | To'liq regressiya (`pytest tests/`) | **2162 test, 0 failure** (18.09, exit 0) |

**Regressiya davomida ushlangan nuqson.** `modify_comment` drift: 0076/0077 `COMMENT ON COLUMN` qo'yadi, ORM
modellarida esa `comment=` yo'q edi — `test_orm_metadata_matches_migrated_schema` va geo drift testi buni
ushladi (bu wave 8 dagi `device_tokens.token_cipher` bilan bir xil nuqson turi). Beshta ustunga izoh
qo'shildi: `listings`/`proposal_versions`/`bookings` ning `*_point` ustunlari va
`service_corridors.max_point_offset_m`. Undan keyin ikkinchi drift chiqdi — 0076 yaratgan qisman indekslar
(`ix_<table>_<end>_district`, `listings` nuqtalaridagi GiST) ORM'da yo'q edi; ular ham qo'shildi.

**Diagnostika izohi:** bu drift testi yakka yugurganda **yolg'on «o'tdi»** beradi, chunki `import app.models`
v2 modul modellarini yuklamaydi va `Base.metadata` to'liq bo'lmaydi. Tekshirish uchun uni marketplace yoki
bookings to'plami bilan birga yurgizish kerak.

Jonli dalil: bekat ustidagi nuqta → 0 m; yo'ldan ~1 km → 715 m va to'g'ri segment; Nukus → `ROUTE_MISMATCH`;
teskari yo'nalish → `ROUTE_MISMATCH`; bekat **va** nuqta birga → `VALIDATION_ERROR`; koridor radiusi 20 km ga
kengaytirilsa o'sha rad etilgan joy qabul qilinadi.

### Wave 14 dan keyin ochiq qolgan bandlar

- **Narx bandi (Q42)** nuqtali uchga qo'llanmaydi: band bekat juftligi bo'yicha sozlanadi, nuqtada juftlik yo'q.
  Kodda ochiq yozilgan; band'ni segment yoki koridor darajasiga chiqarish alohida qaror.
- **Tuman chegaralari yo'q** (170 dan 0): nuqta tanlangan tuman ichida ekani tekshirilmaydi; tuman — advisory
  metadata. Chegaralar kiritilsa, tekshiruvni yoqish alohida qaror bo'ladi.
- **Haydovchi tomoni** nuqtali e'lonni lentada ko'radi va taklif yubora oladi, lekin haydovchining o'z safari
  hamon bekatlar bo'yicha rejalashtiriladi (Q88 faqat mijoz uchini o'zgartirdi).
- Reverse-geocode Google'ga bog'liq: kalit bo'lmasa piker koordinata ko'rsatadi va qidiruv orqali ishlaydi.
- Wave 13 dan qolganlar (saqlangan qidiruv UI, amendment, frontend test runner) o'zgarmadi.

## Wave 15 (18.09.2026) — arxitektura konsolidatsiyasi: Q88 nuqta modelini butun marketplace'ga ulash

Bu wave yangi funksiya qo'shmaydi. U ikkita ishni yopadi: (a) Q90–Q93 qarorlarining yarim qolgan qismini
(kod o'zgargan, test/hujjat/`enforced` yo'li yopilmagan edi), (b) Q88 nuqta modeli `stop_id` kutayotgan eski
chaqiruv joylariga ulanmaganini.

**Nega bu P0 edi.** Klient bugun mijozga aynan **nuqtali** e'lon yaratadi (xaritadan joy). Nuqtali e'londa:
qarshi taklif `KeyError` bilan 500 berardi, Q40 raqobat ro'yxati 404 qaytarardi, M2 matches bo'sh sahifa
berardi, saqlangan qidiruv hech qachon uyg'onmasdi, narx referensi esa umuman qidirilmasdi. Ulardan uchtasi
**xatosiz** «hech narsa yo'q» qaytarardi — ya'ni marketplace halqasi jimgina uzilgan edi.

### Bajarilgan ishlar

| # | Ish | Fayl |
|---|---|---|
| 1 | `counter_proposal` nuqtali tarmoq (`_place_listing_ends_on_trip` + `_validate_point_segment`) | `marketplace/service.py` |
| 2 | `list_listing_offers` koridorni listing'dan oladi (`_assert_listing_corridor_open`) | `marketplace/service.py` |
| 3 | `listing_end_candidates` — **yagona** manba: uch = bekat yoki tuman bekatlari | `marketplace/feed/service.py` |
| 4 | M2 `listing_matches` ikkala tarmoqda shu manbadan foydalanadi | `marketplace/feed/service.py` |
| 5 | `_search_matches` nuqta-ongli | `marketplace/feed/service.py` |
| 6 | `resolve_price_band` / `select_price_band` / `_Reads.band` `stop_id = None` qabul qiladi → koridor referensi | `geo/pricing.py`, `geo/service.py`, `feed/service.py` |
| 7 | `submit_proposal` nuqtali e'lon uchun narx referensini **o'tkazib yubormaydi** (wave 14 dagi guard olib tashlandi) | `marketplace/service.py` |
| 8 | `enforced` admin API'da: `PriceBandUpsert`, `PriceBandDTO`, `set_price_band`, audit yozuvi | `geo/schemas.py`, `geo/service.py`, `geo/api.py` |
| 9 | `WarningCode.PRICE_OUTSIDE_REFERENCE` (xato kodi bilan **bir xil yozilmaydi**) + o'zbekcha matn | `contracts/errors.py`, `v2Errors.ts` |
| 10 | Kontrakt hujjatlari Q90 ga keltirildi; ADR-0019 ning narx qismi superseded deb belgilandi | `API_V2_CONTRACT.md`, `STATE_MACHINES.md`, `DATA_MODEL.md`, `adr/0019` |
| 11 | Eskirgan band testlari `enforced=true` stsenariysiga ko'chirildi | `test_geo_pricing.py`, `test_marketplace_r2_band_pg.py`, `wave17`, `wave21` |
| 12 | **Frontend test runner**: vitest 5.0.1 + jsdom + testing-library, `npm test` | `vite.config.ts`, `src/test/setup.ts` |
| 13 | Auksion qoidalari sof modulga (`auction.ts`) chiqarildi va testlandi (AC05 shu yerda) | `src/app/auction.ts` |
| 14 | **Amendment (B9)** klientda: taklif, qabul, rad, qaytarib olish (Q60: faqat miqdor va birlik narxi) | `ConnectedApp.tsx` |
| 15 | **Saqlangan qidiruv** ekrani qaytarildi (M3) | `ConnectedApp.tsx` |
| 16 | Detour halolligi: `meta.match_scope = confirmed_stops` bo'lsa lentada ogohlantirish; `on_route` matni «yo'l yo'nalishida» | `ConnectedApp.tsx` |
| 17 | Xarita **Yandex Maps JS API v3** ga ko'chirildi; geokodlash o'z backendimiz orqali | `components/maps/*`, `geo.api.ts` |
| 18 | O'lik `google_maps_service.py` va `ELCHI_GOOGLE_MAPS_*` o'chirildi; E2/E4 data-flow qatorlari tuzatildi | `app/services/`, `app/core/config.py`, `EXTERNAL_DATA_FLOWS.md` |

### Exit criteria (foydalanuvchi muzlatgan ro'yxat)

| # | Shart | Holat | Dalil |
|---|---|---|---|
| 1 | Nuqtali e'lon primary feed'da | ✅ (wave 14 dan) | `_evaluate_request_by_stops` → `_point_listing_match` |
| 2 | Nuqtali e'lon M2 matches'da | ✅ | `test_the_owner_of_a_point_request_is_shown_matching_trip_offers`, `..._among_the_matches_for_their_trip_offer` |
| 3 | Saqlangan qidiruv nuqtali e'lonni yo'qotmaydi | ✅ | `test_a_saved_search_fires_for_a_point_listing` |
| 4 | passenger request ↔ driver trip_offer ikki tomonlama | ✅ | `ALLOWED_PRICE_BASIS` kontrakt testi + klientda ikkala kirish nuqtasi |
| 5 | Qarshi taklif har ikki yo'nalishda | ✅ | `test_the_client_can_counter_a_driver_offer_on_a_point_listing`; `auction.test.ts` |
| 6 | Accept'dan boshqa hech narsa booking yaratmaydi | ✅ | `Booking(` yagona joyda (`bookings/service.py`), audit |
| 7 | Q90–Q93 kodda emas, **enforced va testlangan** | ✅ | `enforced` API'da; `test_only_an_enforced_band_refuses...`; `test_an_enforced_reference_still_refuses_on_a_point_listing` |
| 8 | Amendment B9 klientda | ✅ | `booking-amendment` ekrani |
| 9 | O'lik marketplace ekranlari ulangan yoki flag ostida yopiq | ⚠️ qisman | Saqlangan qidiruv ulandi; **nizolar ro'yxati + dalil yuklash hali yo'q** |
| 10 | Frontend test runner | ✅ | `npm test` — 25 test |
| 11 | Q42 referensi nuqtali e'lon uchun ham ranking'da, hard fare emas | ✅ | `test_a_point_listing_resolves_the_corridor_reference_not_nothing` |
| 12 | Detour o'chiq bo'lsa UI va'da bermaydi | ✅ | `CONFIRMED_STOPS_NOTE` ikkala lentada |
| 13 | Regression + PG testlar qayta yugurilgan | ✅ | quyida |

### Ochiq qolgan (wave 16 ga)

- **Nizolar ro'yxati va dalil yuklash** (`addDisputeEvidence`) klientda hali yo'q — ochiq nizo faqat bron
  ekranida ko'rinadi.
- Ruscha lokalizatsiya, a11y auditi, F-05 ning qolgan ekranlari.
- `app/v2/ui.tsx` — hali o'lik uchinchi dizayn nusxasi.
- `frontend/` (muzlatilgan) hamon Google Maps yuklaydi — E4 qatorida yozilgan.

## Wave 16 (19.09.2026) — wave 15 dan qolgan ochiq bandlar

Wave 15 ning exit criteria ro'yxatidan qolgan bandlar va QA §7 dagi ochiqlar.

| # | Ish | Holat | Dalil |
|---|---|---|---|
| 1 | Ikkinchi *jonli* dizayn tizimi (`app/v2/ui.tsx`) birlashtirildi va o'chirildi | ✅ | `PublicSharePage`, `RouteMap` endi `app/ui/mobile.tsx` dan |
| 2 | **M2 matches ekrani** (F-05 ning birinchi bo'shlig'i) — mijoz va haydovchi tomonida | ✅ | `listing-matches` ekrani; `listingMatches()` API |
| 3 | **Admin narx referensi paneli** — `enforced` endi UI'dan yoqiladi (Q90 operatsion bo'ldi) | ✅ | `AdminPriceBandsPanel.tsx`; `PUT` v2 klientga qo'shildi |
| 4 | **A11y auditi va tuzatishlar** | ✅ | 7 ta nomsiz tugma, 5 ta nomsiz input, 4 ta modal scrim; `PhoneField` o'z nomini oladi |
| 5 | A11y regressiya testi | ✅ | `src/test/accessibility.test.ts` — 4 qoida manba bo'yicha |
| 6 | **Ruscha lokalizatsiya: poydevor + lug'at** | ⚠️ qisman | pastda |
| 7 | OpenAPI sxemasi va klient tiplari qayta generatsiya qilindi (`enforced` qo'shilgani uchun) | ✅ | 165 operatsiya |

### Lokalizatsiya: nima bajarildi, nima qolgan

**Bajarildi.** `src/i18n/` — kalit bo'yicha ikki tilli lug'at, `translate`/`translateDynamic`, `useT`/`useLocale`
(`useSyncExternalStore`), `localStorage` da saqlanadi. Lug'at parity testi (`messages.test.ts`) bo'sh tarjimani,
ruscha slotda qolgan o'zbekcha matnni va mos kelmaydigan `{placeholder}` larni ushlaydi.

**To'liq ko'chirilgan qatlam — *lug'at*:** barcha xato kodlari (v1 + v2), ogohlantirishlar, bron/e'lon/safar
holatlari, moslik turlari, proof kodlari, nizo turi/holati/qarori, kuzatuv holatlari. Bular endi konstanta emas,
render paytida so'raladi — konstanta til o'zgarishini hech qachon kuzata olmaydi.

`tests/contracts/test_client_error_messages.py` yangi joyga moslandi va **kuchaytirildi**: foydalanuvchi
tuzatishi mumkin bo'lgan rad javoblari endi rus tilida ham bo'lishi shart.

**Qolgan — *ekran matni*:** `ConnectedApp.tsx` va admin panellaridagi sarlavha, tugma va izoh matnlari hamon
o'zbekcha literal (~210 + ~280 satr).

**24.09.2026 yangilanishi:** mijoz/haydovchi ekran matni lug'atga ko'chirildi — `py scripts/i18n_coverage.py`: 1431 dan 1420 (99.2%); qolgan 11 tasi server qiymatlari, brend va matn bo'lmagan satrlar. Shart bajarilgani uchun UZ/RU almashtirgich Sozlamalar ekranida ochildi. Admin panellari o'zbekcha qoladi.

**Til almashtirgich UI'ga ataylab qo'yilmadi.** *(24.09.2026 gacha)* Hozir qo'yilsa, ekranning bir qismi ruscha (holatlar, xatolar),
qolgani o'zbekcha bo'lib chiqadi — bu bitta halol tildan yomonroq. Almashtirgich ekran matni ko'chirilgandan
keyin qo'yiladi; shu vaqtgacha tilni devtools orqali qo'yib tarjimalarni ko'rib chiqish mumkin.

### Yo'l-yo'lakay tuzatilgan nuqsonlar

- `CodeField` va `PhoneField` yorlig'i input bilan bog'lanmagan edi (komponent testi ushladi).
- `PhoneField` `label`siz ishlatilganda (auth ekranida aynan shunday) inputning nomi umuman yo'q edi.
- `v2` klientda `PUT` metodi qo'llab-quvvatlanmagan edi — G13 narx referensi upsert'i shuni talab qiladi.

### Hodisa: ConnectedApp.tsx da ma'lumot yo'qolishi

Lug'at ko'chirishdagi avtomatlashtirilgan tahrir regex'i juda ko'p narsani o'chirdi: yorliq xaritalari bilan
birga ular orasidagi 13 ta deklaratsiya ham ketdi (`DirectionEnd`, `directionEndLabel`, `soumToMinor`,
`CASH_RECORDABLE`, `PASSENGER_PROGRESS`, `PARCEL_TYPES`, `OTP_LENGTH` va boshqalar). Bu kod commit qilinmagan
edi, shuning uchun `git show HEAD` yordam bermadi.

**Tiklash:** oxirgi muvaffaqiyatli production bundle'i (`dist/assets/index-*.js` — barcha o'zgarishlardan keyin,
buzilgan tahrirdan oldin qurilgan) dan aniq xulq olindi va o'qiladigan manba sifatida qayta yozildi. `tsc`
barcha yo'qolgan nomlarni ko'rsatdi va tiklashdan keyin toza; to'liq test to'plami o'tdi.

**Xulosa:** katta faylga regex bilan «comment + deklaratsiya» o'chiradigan tahrir qilinmaydi. Aniq satr
(exact-string) almashtirish yoki kichik, tekshiriladigan bo'laklar ishlatiladi.

## Wave 15 yakuni (19.09.2026) — dev muhiti tiklandi va auksion yadrosi real stackda tasdiqlandi

Wave 15 yopilishidan oldingi oxirgi blok: dev muhitida marketplace'ning **taklif tomoni** konfiguratsiya
sababli yopiq edi, va auksion yadrosi hech qachon uchidan-uchiga real API bilan tekshirilmagan edi.

### 1. Dev fixture

`driver_listing_enabled` har joyda `false` (`PRODUCTION_FLAG_DEFAULTS`) va geo fixture unga qator
yaratmasdi → koridor default'ga tushardi → haydovchi `trip_offer` e'lon qila olmasdi (`FEATURE_DISABLED`).
Q92 ikkala tomonda kirish nuqtasini talab qiladi; dev'da taklif tomoni yo'q edi.

* `tests/fixtures/geo/loader.py::enable_dev_service_flags` — `set_flag_value` **orqali** (raw INSERT emas), ya'ni
  capability tekshiruvi, Q72 yozuv markeri, versiya trigger'i va audit qatori o'z kuchida qoladi.
* Idempotent **yozmaslik** ma'nosida: kerakli qiymatdagi flagga umuman tegilmaydi (versiya oshmaydi, history
  va audit qatori qo'shilmaydi). Boshqa qiymatdagisi joriy versiyasi orqali to'g'rilanadi.
* Production markeri ostida `RuntimeError` bilan rad etadi; production default'lari **o'zgarmadi**.
* `scripts/seed_geo_fixtures.py` flaglarni **har yugurishda** ta'minlaydi (koridor allaqachon bor bo'lsa ham),
  `--no-flags` bilan o'chiriladi.

Testlar: `tests/pg/geo/test_dev_fixture_flags_pg.py` — **6 test, 0 failure**.

### 2. Ikki tomonlama auksion smoke (real API)

Yangi `scripts/qa_probe_auction.py` — **18 tekshiruv, 0 failure** jonli stackda:

| Yo'nalish | Ketma-ketlik | Natija |
|---|---|---|
| A | passenger request 300k → driver 350k → client counter 320k → **driver accept** | bron jami **320 000** |
| B | driver trip_offer 200k → client 160k → **driver counter 180k** → client accept | bron jami **180 000** |

Qo'shimcha isbotlar: superseded versiyani qabul qilib bo'lmaydi (`PROPOSAL_CHANGED`); muallif o'z versiyasini
qabul qila olmaydi (`NOT_PROPOSAL_RECIPIENT`, AC05); flag o'chiq holatda **aynan o'sha qoralama**
`FEATURE_DISABLED`, yoqilganda 200; komissiya `available` dan ushlanadi va `posted` tegilmaydi; bir xil
Idempotency-Key bir xil bronni qaytaradi va ikkinchi marta ushlamaydi (AC08); bekor qilish hold'ni qaytaradi.

### 3. PG wallet

Docker tiklangandan keyin to'liq qayta yugurildi: **90 passed, 0 failed, 0 error**. Oldingi yugurishdagi 12 ta
ERROR setup'da ulanish taymauti edi (Docker Desktop o'chgan) — PASS deb hisoblanmadi va qayta yugurildi.

`tests/pg/bookings + marketplace + geo`: **309 passed**.

### 4. Klient qamrovi

`docs/architecture/CLIENT_COVERAGE_AUDIT.md` — 152 yo'ldan 82 chaqiriladi (avval 68/150). 11 ta foydalanuvchi
yuzasidagi bo'shliq CORE-P0/P1 bo'yicha tasniflandi; 8 tasi ataylab ulanmagan; admin uchun **19 yo'llik**
production-operability qismi ajratildi.

## Wave 17 (19.09.2026) — katalog v1 bilan tenglashtirildi: xarita qayerda ochiladi

> **Tuzatilgan — Wave 17.1 ga qarang.** Bu kartadagi «v1 koordinatalari aniq» farazi noto‘g‘ri edi: v1
> `districts.center_lat/lng` qiymatlari generatsiya qilingan panjara nuqtalari. 0079/0080 import qilgan
> qiymatlar (jumladan quyidagi `Urgut = 39.7342, 67.0397` va `UZ-TK = 41.2911, 69.2597`) **0081** bilan
> tekshirilgan qiymatlarga almashtirildi.

Foydalanuvchi topilmasi: «hududlar va yo'nalishlar v1 bo'yicha olinsin; hudud tanlansa xarita o'sha joyda
ochilsin; viloyat tumanlari aniqligi v1 da aniq ko'rsatilgan».

### Tekshirilgan farq

| | v1 | v2 (oldin) |
|---|---|---|
| Tumanlar | **176** | **170** (164 legacy'ga bog'langan, 6 fixture) |
| Koordinata | `center_lat/lng` — **176/176** | markaz ustuni **umuman yo'q**; `boundary` — **170 dan 0** |

Natija: `MapPointPicker` doim Toshkentda ochilardi. Urgutni tanlagan odam xaritani butun mamlakat bo'ylab
surishi kerak edi. v1 `MapAddressPicker` esa `district.center_lat/lng` ga markazlashadi.

### Chegara (nima o'zgarmadi)

Spec §2 **tuman markazi bo'yicha matching'ni ataylab rad etgan** (46-qator: «shahar va tumanlar aynan teng
bo'lishi» → rad; 55-qator: «tuman markazidan 75 km» → rad) va Q88 uni marshrutga proyeksiya bilan
almashtirgan. Shuning uchun qo'shilgan koordinatalar **faqat xarita kamerasi** uchun: matching, sig'im va narx
kodi ularni o'qimaydi. Buni `tests/pg/geo/test_district_map_centre_pg.py` manba bo'yicha qo'riqlaydi — yetti
faylda `center_lat` qidiradi va topsa yiqiladi.

### Bajarilgani

| # | Ish |
|---|---|
| 1 | **0079** `geo_districts.center_lat/center_lng` + `CHECK` (ikkalasi birga, O'zbekiston chegarasida); v1 `districts` dan `legacy_district_id` orqali backfill — **164/170** (qolgan 6 tasi fixture) |
| 2 | **0080** `regions.center_lat/center_lng` + bir xil `CHECK`; backfill **hosila** — viloyat tumanlari markazlarining o'rtachasi, `legacy_city_mappings` orqali, mapping bo'lmaganda nom bo'yicha. **14/14** |
| 3 | `DistrictDTO` va `RegionDTO` markazni tashiydi; ORM izohlari migratsiya izohi bilan **aynan** bir xil (drift testi buni ushlagan edi) |
| 4 | Klient: **tuman → viloyat → mamlakat** tartibida tushadi (`mapCentreFor`); markaz bo'lmasa mamlakat ko'rinishi — «bilmayman» ni yashirmaydi |
| 5 | Zoom ham mos: belgilangan nuqta 16, tuman/viloyat markazi 12, mamlakat 6 |

### Foydalanuvchi qarori (19.09.2026)

**Toshkent shahri bitta birlik bo'lib qoladi** — 12 tuman (Chilonzor, Yunusobod, ...) v2 katalogiga
qaytarilmadi. Sabab: matching tasdiqlangan bekatlar bo'yicha ishlaydi, shuning uchun tumanga bo'lish bekatsiz
tumanlarda lentani bo'shatib qo'yardi. Aniqlikni Q88 xarita nuqtasining o'zi beradi. Shu qaror **0080** ni
zaruriy qildi: tuman yo'q joyda viloyat markazi javob beradi (UZ-TK = 41.2911, 69.2597).

### Tekshiruvlar

| Buyruq | Natija |
|---|---|
| `pytest tests/pg/geo` | **95 passed** |
| `pytest tests/contracts tests/modules tests/test_mobile_v2_client_contract.py` | **837 passed** |
| `npm run lint` / `npm test` / `npm run build` | xatosiz / **35 passed** / `✓ built` |
| `qa_probe_ui_journey.py` (jonli) | **54 checks, 0 failures** |
| `qa_probe_auction.py` (jonli) | **18 checks, 0 failures** |
| Jonli API | `UZ-TK center=(41.2911, 69.2597)`, `Urgut center=(39.7342, 67.0397)` |

### Ochiq qolgani

- **6 fixture tumani** (`Qarshi (fixture)` va h.k.) haqiqiy `Qarshi` yonida turadi — dev katalogi chalkash.
  Production'da yo'q (164), lekin dev/QA uchun filtrlash yoki nomlashni ajratish kerak.
- Tuman **chegaralari** (poligon) hamon 170 dan 0 tasida. Markaz kamerani hal qildi; chegara esa «nuqta shu
  tumandami?» savoliga kerak bo'ladi va bu alohida qaror (wave 14 dan beri ochiq).

---

## Wave 17.1 (19.09.2026) — v1 koordinatalari haqiqiy emas edi: tuzatish

### Topilma

Wave 17 «v1 tumanlar aniqligi v2 ga ko'chirilsin» degan topshiriqni v1 `districts.center_lat/center_lng` ni
ko'chirish bilan bajardi. **O'sha ustun surveyed markaz emas ekan.** Qaysi skript bazani to'ldirgani hal
qiladi:

| Manba | Nima yozadi |
|---|---|
| `scripts/seed_districts.py` → `DISTRICT_CENTERS` | **111 ta qo'lda tekshirilgan** koordinata (Urgut 39.4022/67.2431, Mo'ynoq 43.7683/59.0214, Qarshi 38.8606/65.7890) — haqiqiy joylar |
| `scripts/seed_admin_required_data.py` → `district_center()` | shahar markazi atrofida **5 ustunli, 0.08° qadamli panjara** — joy emas, katak |

Dev bazada **176/176 qator panjara nuqtasi** (o'lchab tasdiqlandi: har bir qator `city_center + k·0.08`
kataklariga 1 m aniqlikda tushadi). Ya'ni 0079 **164 ta o'ylab topilgan koordinatani** v2 ga ko'chirgan, 0080
esa viloyat markazlarini o'sha panjaraning o'rtachasidan hisoblagan.

Amaliy og'irligi: Mo'ynoq panjara nuqtasi haqiqiy Mo'ynoqdan **~250 km**. Xarita o'sha yerda ochilib, ustiga
«Mo'ynoq» deb yozilsa — bu taxminiy ko'rsatma emas, yolg'on ma'lumot; odam pin'ni o'sha yerga tashlaydi.
AGENTS.md §9 aynan shuni taqiqlaydi. Mamlakat ko'rinishida ochilish bundan **yaxshiroq** edi.

### Tuzatish — **0081** (forward-fix, downgrade emas)

| # | Qadam |
|---|---|
| 1 | Panjara ekani **isbotlangan** har bir tuman markazini tozalaydi: generator mantiqi (`display_order` + o'sha 14 shahar markazi) qayta hisoblanadi va 1 m aniqlikda mos kelsagina `NULL` qilinadi — qo'lda tuzatilgan qator tegilmaydi |
| 2 | Faqat qo'lda tekshirilgan jadvaldan to'ldiradi (normallashtirilgan nom + viloyat kodi bo'yicha): **170 tumandan 99 tasi**. Qolgan **65 ta haqiqiy tuman `NULL` qoladi** — taxmin yozilmadi |
| 3 | Viloyat markazlari haqiqiy ma'muriy markazga qo'yildi (`CITY_SEEDS` — bular haqiqiy; panjara ulardan *hosila* edi). 0080 o'rtachasi 1–3 km xato berardi |

Toza bazada zanjir baribir to'g'ri tugaydi: 0079 panjarani import qiladi → 0080 o'rtachalaydi → 0081 tozalab,
tekshirilgan qiymatni qo'yadi. Production'da `districts` `seed_districts.py` bilan to'ldirilgan bo'lsa,
qiymatlar panjaraga tushmaydi va **saqlanib qoladi** (1-qadam ularga tegmaydi, 2-qadam faqat bo'shni to'ldiradi).

### Klient

`mapCentreFor` endi markazning **qanchalik aniq ekanini** ham qaytaradi (`scope: district | region`), va zoom
shunga qarab tanlanadi: belgilangan nuqta **16**, tuman markazi **12**, viloyat markazi **9**, markaz yo'q →
mamlakat **6**. Sabab: viloyat markazi odam tanlagan tumandan 100 km narida bo'lishi mumkin; unga yaqin
zoom qilish «xarita shahringizni topdi» degan yolg'on taassurot beradi.

### Tekshiruvlar

| Buyruq | Natija |
|---|---|
| `pytest tests/pg/geo` | **100 passed** (95 → +5) |
| `pytest tests/contracts tests/modules tests/test_mobile_v2_client_contract.py` | **837 passed** |
| `npm run lint` / `npm test` / `npm run build` | xatosiz / **35 passed** / `✓ built` |
| Jonli API `/api/v2/districts?q=Urgut` | `39.4022, 67.2431` (haqiqiy Urgut; oldin `39.7342, 67.0397` — katak) |
| Jonli API `/api/v2/districts?q=Kegeyli` | `null, null` (tekshirilgan qiymat yo'q → viloyatga qaytadi) |
| Jonli API `/api/v2/regions` | 14/14 haqiqiy ma'muriy markaz; `UZ-TK = 41.3111, 69.2797` |

Yangi qo'riqchi `tests/pg/geo/test_verified_map_centres_pg.py`:

- tekshirilgan jadvalda **birorta panjara nuqtasi yo'q** (panjaraning markaziy katagi istisno — u shahar
  markazining o'zi, ya'ni Qarshi'ning haqiqiy koordinatasi bilan bir xil bo'lishi to'g'ri);
- anker qiymatlar (Urgut, Mo'ynoq, Kattaqo'rg'on) — agar kimdir jadvalni yana v1 bazasidan qayta yaratsa, test
  yiqiladi;
- jadval qamramagan tuman `null` qaytaradi;
- migratsiya **ikki marta** ishlaganda drift bermaydi.

### Ochiq qolgani (o'zgarmadi)

- **65 ta haqiqiy tuman** markazsiz. To'ldirish uchun tekshirilgan tashqi manba kerak (OSM/statistika
  qo'mitasi) — bu dependency va litsenziya qarori, taxmin bilan yozish emas.
- **6 fixture tumani** hamon haqiqiy tuman yonida turadi (endi ajratish oson: fixture'da markaz `null`).
- Tuman **chegaralari** (poligon) 170 dan 0 tasida — wave 14 dan beri ochiq alohida qaror.

---

## Wave 18 (19.09.2026) — muzlatilgan `frontend/` UX/UI si `mobile-app/` ga ko'chirildi

Foydalanuvchi topshirig'i: «frontend muzlatilgan bo'lsa, undagi barcha UX/UI qismlarini hozirgi frontendga
o'tkaz. barchasini».

`frontend/` **o'qildi, tahrirlanmadi** (AGENTS.md §2). Hamma o'zgarish `mobile-app/` da.

### Nega kerak edi

| | `frontend/` (muzlatilgan, dizayn shu yerda ishlangan) | `mobile-app/` (oldin) |
|---|---|---|
| Palitra | Elchi tizimi: `#2258E6` royal blue, `--feruza` azure, status uchun ajratilgan yashil/sariq/qizil | **stock shadcn** (generic oklch kulranglar), ustiga ko'k primary bo'yalgan |
| Dark mode | To'liq ishlangan midnight-blue | shadcn defaulti — `primary` **oq**; ustiga hech narsa `.dark` klassini qo'ya olmasdi → **umuman o'lik** |
| Neytral shkala | `slate/gray/zinc` → foreground↔background aralashmasiga qayta yo'naltirilgan (mavzuga ergashadi) | Tailwind'ning qotib qolgan shkalasi |
| Rang manbasi | tokenlar | **2379 ta qattiq hex** 28 faylda |
| Tipografika | Inter + `.font-display` (tighter tracking), `.font-mono` = tabular figures | yo'q |
| Harakat | `screen-in`, `anim-rise/sheet/pulse/stamp/grow/fade`, `stagger-1..5` | faqat `el-*` grammatikasi |
| Imzo shakllar | karvon ipi (`ThreadSpine`/`RouteThread`/`JourneySpine`), muhr logotipi, `IconTile` 5 ton, status nuqtasi | yo'q |

Eng og'iri **2379 ta hex** edi: token o'zgartirish ularga ta'sir qilmaydi, shuning uchun dark mode
printsipial ravishda ishlay olmasdi.

### Bajarilgani

| # | Ish |
|---|---|
| 1 | **Tokenlar** — `styles/theme.css` to'liq Elchi tizimiga almashtirildi: palitra, haqiqiy dark mavzu, `--feruza`, status tokenlari, uch soya, 14px radius, mavzuga ergashuvchi `slate/gray/zinc` va `blue` shkalasi |
| 2 | **Tipografika** — Inter, `.font-display`, `.font-mono` = tabular figures, `svg.lucide` bitta chiziq qalinligi, `.scrollbar-hide` |
| 3 | **Harakat** — `styles/motion.css` ga frozen choreography qo'shildi (`anim-stamp`, `anim-grow`, `anim-pulse`, `stagger-*`, `elchi-thread-draw`); mavjud `el-*` qoidalarining qattiq ranglari ham tokenga o'tdi |
| 4 | **Rang migratsiyasi** — 28 faylda **2379 + 22** literal tokenga ko'chirildi; `bg-white` → `bg-card`, `text-white` → `text-primary-foreground`, `COLORS` obyekti `var(--…)` ga qayta yo'naltirildi |
| 5 | **Xarita istisnosi** — `cssColor()` (`maps/yandex.ts`): WebGL stylesheet'ni o'qimaydi, shuning uchun `MapLine` tokenni **hisoblab** oladi; marker DOM elementi esa to'g'ridan-to'g'ri `var()` ishlatadi |
| 6 | **Primitivlar** — `ThreadSpine`, `RouteThread`, `JourneySpine`, `SectionLabel`, `ElchiLogo`, `AppearancePicker` qo'shildi; `IconTile` 5 tonga, `StatusBadge` yetakchi nuqtali holatga kengaytirildi (rang-only emas) |
| 7 | **Mavzu almashuvi** — `ui/theme.ts`: light/dark/system, `localStorage`, `matchMedia` ga tirik obuna, `startTheme()` birinchi render'dan oldin (oq chaqnash yo'q). Mijoz profili, haydovchi profili va admin profilida **Ko'rinish** bo'limi |
| 8 | **Imzo shakllar joylashtirildi** — splash frozen kompozitsiyasiga o'tdi (muhr `anim-stamp`, kichik harfli wordmark, o'zini chizadigan ip); bosh sahifa va haydovchi lentasidagi **ikki uch** endi karvon ipi bilan bog'langan (origin — halqa, destination — muhr olmosi); onboarding'da wordmark |
| 9 | **O'lik kod** — `app/App.tsx` dagi 1748 qator prototip olib tashlandi. U hech qayerdan chaqirilmasdi (yagona tirik qatori `export default ConnectedApp`), lekin dizayn tizimi uni «reference» deb ko'rsatib turardi — ikkita qarama-qarshi javob aynan drift demakdir. Tarixda: `git show cbf2875:mobile-app/src/app/App.tsx` |
| 10 | **Qo'riqchi test** — `ui/theme.test.ts`: mavzu store'i + **manba bo'yicha** tekshiruv: birorta komponentda hex literal yoki noshaffof `bg-white`/`text-white` qolmasin |

### Ataylab qilinmagani

- **Til almashuvi** (`uz/ru/en`) frozen SettingsPanel'da bor, lekin **ochilmadi**: ekran matnlarining ~458
  tasi hali ko'chirilmagan, shuning uchun tugma yarim tarjima qilingan UI ko'rsatardi. Lug'at qatlami tayyor
  (`i18n/`), matn ko'chirilgach ochiladi.
- **Splash avtomatik o'tishi** (frozen'da 2200 ms) olinmadi — «Boshlash» tugmasi qoldi.
- `frontend/` ning o'ziga **tegilmadi**.

### Qo'riqchi istisnolari (hujjatlangan)

- `bg-black/45` — bu **scrim**, sirt emas; past alpha'da ikkala mavzuda to'g'ri (frozen ham shunday).
- `YandexMap.tsx` dagi bitta `#2258E6` — `cssColor()` ning fallback'i: document bo'lmasa resolver'ga
  qaytadigan qiymat kerak.

### Tekshiruvlar

| Buyruq | Natija |
|---|---|
| `npm run lint` (`tsc --noEmit`) | xatosiz |
| `npm test` | **42 passed** (35 → +7) |
| `npm run build` | `✓ built` |
| Qurilgan CSS | `.dark` bloki to'liq; `slate-400` → `color-mix(--foreground 42%, --background)`; 121 ta `color-mix`; `anim-stamp`, `elchi-pulse`, `font-display`, `tabular-nums`, `shell-canvas` bor |
| `qa_probe_ui_journey.py` (jonli) | **54 checks, 0 failures** |
| `qa_probe_auction.py` (jonli) | **18 checks, 0 failures** |
| `GET /` va `/admin` (dev server) | 200 / 200 |

---

## Wave 18.1 (19.09.2026) — ikonka to'plami, auth oqimi va qolgan UX `frontend/` dan

Wave 18 tokenlar, harakat grammatikasi va primitivlarni ko'chirgan edi. Bu qadam **qolganini** oladi:
ikonkalar, login, OTP, rol tanlash va safar chizig'i.

### Ikonka to'plami — Lucide → Phosphor

`frontend/` har bir ikonkani **`@phosphor-icons/react`** dan oladi va ularni Figma eksportidagi nomlarga
alias qiladi (`House as Home`, `CaretRight as ChevronRight`, `PaperPlaneTilt as Send`). `mobile-app/` esa
Lucide'da edi — ikki mahsulot bir narsani **ikki xil qo'l** bilan chizardi: Lucide'ning ochiq, yumaloq
geometriyasi va Phosphor'ning yopiq, teng qalinlikdagi geometriyasi. Yonma-yon qo'yilsa bitta ilovaga
o'xshamaydi.

| Ish | |
|---|---|
| Dependency | `@phosphor-icons/react` **2.1.10** — `frontend/` dagi **aynan o'sha** versiya, `--save-exact` bilan pin qilindi (AGENTS.md §2: taxmin yo'q) |
| Alias moduli | `app/ui/icons.ts` — **105 ta** nom. Frozen mijozning 72 ta aliasi + bu klientda bor 33 tasi (`// (this client)` deb belgilangan) |
| Tekshiruv | Har bir nom paket eksportiga solishtirildi: **105/105 mavjud**, yetishmagani yo'q |
| Migratsiya | **24 fayl** — faqat import manbasi o'zgardi, chaqiruv joylariga tegilmadi |
| Tozalash | `lucide-react` olib tashlandi; `svg.lucide { stroke-width }` qoidasi o'chirildi (Phosphor stroke emas, **weight** ishlatadi va `regular` defaultda) |
| Muhr | Splash va `ElchiLogo` dagi `Send` endi `weight="fill"` — frozen dizaynda muhr shunday |

`Loader2` → `CircleNotch` (ochiq halqa); `animate-spin` chaqiruv joyida qoladi — ikkala kutubxona ham o'zi
aylanmaydi.

### Auth oqimi — rol, login, OTP

| Ekran | Nima ko'chdi |
|---|---|
| **Rol** | Orqaga chipi, `ElchiLogo`, display sarlavha, `--shadow-card` li kartalar, 56px ikonka plitasi, chevron, pastda `Elchi · UZ · yil`. **Bir tegishda tanlaydi va o'tadi** — frozen'dagidek; «Davom etish» qadami olib tashlandi, chunki rol — shu ekranning yagona savoli |
| **Login** | Qaysi rol bilan kirilayotgani ekranda qoladi (chip), display sarlavha, `Enter` bilan yuborish, CTA'da **qog'oz samolyot** ikonkasi va so'rov davomida **spinner** |
| **OTP** | Markazlashgan sarlavha, raqam tabular figures bilan, **segmentli kod maydoni**, karetka pulsatsiyasi, xato holati, **59 soniyalik qayta yuborish sanog'i**, CTA'da o'ng strelka |

**Segmentli kod maydoni** (`CodeField` qayta yozildi): bitta shaffof input butun qator ustida yotadi va
barcha bosishlarni, paste'ni va platformaning SMS autofill'ini oladi; ostidagi doiralar — shu inputning
qiymati chizilgani. Har raqam uchun alohida input qilish aynan `autocomplete="one-time-code"` ni buzadi va
backspace'ni chalkashtiradi.

Frozen'da grid `grid-cols-5` qilib qotirilgan — kod 4 xonali bo'lsa bo'sh katak qoladi. Bu yerda grid
`length` dan hisoblanadi (Q8: bugun 4/5, Android v2 bilan 6).

### Safar chizig'i

`StatusTimeline` bir xil doiralar ustuni edi — u posilka **qayerdaligi** haqida hech narsa demasdi. Endi
`JourneySpine`: bosqichma-bosqich marjon, joriy bosqich — pulsatsiyalanuvchi azure halqa, oxirgisi — muhr
olmosi. Bu bosh sahifadagi karvon ipi bilan **bir xil chizma**, ya'ni yo'nalish va uning borishi bitta g'oya.

### Qo'shimcha primitiv o'zgarishlari

- `PrimaryButton` — `icon`, `iconAfter`, `busy` (spinner + `aria-busy`). Sekin tarmoqda tugma «hech narsa
  qilmadi» ko'rinmasligi uchun.
- `PhoneField` — `Enter` bilan yuborish.

### Tekshiruvlar

| Buyruq | Natija |
|---|---|
| Ikonka nomlari paket eksportiga nisbatan | **105/105**, yetishmagani yo'q |
| `npm run lint` (`tsc --noEmit`) | xatosiz |
| `npm test` | **45 passed** (42 → +3) |
| `npm run build` | `✓ built` |
| `qa_probe_ui_journey.py` / `qa_probe_auction.py` (jonli) | **54 checks 0 failures** / **18 checks 0 failures** |
| `GET /` va `/admin` | 200 / 200 |
| `git status frontend/ android-app/` | **0 fayl** |

Yangi qo'riqchi `ui/icons.test.ts`: ikonka kutubxonasiga **faqat** `ui/icons` orqali kirilsin (ikki
kutubxona bir vaqtda ishlashi build xatosi bermaydi va bitta ekran skrinshotida ko'rinmaydi — shuning uchun
mexanik tekshiriladi), aliaslar ishlasin va birorta nom `undefined` ga ishora qilmasin.

---

## Wave 18.2 (19.09.2026) — `frontend/` ning qolgan ekranlari ko'chirildi

Wave 18 dizayn tizimini, 18.1 ikonka to'plami va auth oqimini ko'chirgan edi. Bu qadam **ekran ro'yxatini
oxirigacha** yopadi: `frontend/src/app/App.tsx` dagi har bir ekran `mobile-app/` da bormi yoki yo'qmi — har
biri tekshirildi.

### Auditning natijasi

`mobile-app/` da **50 ta ekran** bor va u ko'p jihatdan `frontend/` ning **ustki to'plami** (v2 marketplace
butunlay qo'shimcha: takliflar, e'lonlar, kuzatuv, chat, amendment, nizolar, saqlangan qidiruvlar). Haqiqiy
bo'shliq **beshta** edi:

| Bo'shliq | Holati |
|---|---|
| Yordam ekrani + FAQ (`ClientSupportScreen`, `FaqItem`) | **yo'q edi** → qo'shildi |
| Sozlamalar paneli (`SettingsPanel`) | qisman (faqat profil ichida mavzu) → alohida ekran |
| Maxfiylik siyosati (`PrivacyPolicy`, 212 qator) | **umuman yo'q edi** → ko'chirildi, `/privacy` da |
| Daromad diagrammasi (`recharts` BarChart) | **yo'q edi** → qo'shildi (kutubxonasiz) |
| Haydovchida bildirishnomalar | **yo'q edi** → qo'shildi |

### Yordam ekrani — frozen shakl, lekin rost

Frozen mijozda `SUPPORT_PHONE = "+998712000000"` **qattiq yozilgan** va «Har kuni 09:00 – 21:00» deb
va'da qilingan, ustiga «Qo'ng'iroq» tugmasi bor.

Bu Q87 ga to'g'ridan-to'g'ri zid: pilotda javob beradigan liniya **yo'q**, `ELCHI_SUPPORT_PHONE` bo'sh
qoladi, S13 `available=false` qaytaradi va ilova **na raqam, na ish vaqti** ko'rsatishi kerak (AGENTS.md §9:
«24/7 operator … va'da qilinmaydi»). Backend buni allaqachon to'g'ri bajaradi
(`trust_support/config.py::support_contacts` — hatto `hours_text` javob vaqtini va'da qilsa, uni ham
tashlab yuboradi).

Shuning uchun ekranning **shakli** ko'chirildi, **manbasi** esa o'zgartirildi: raqam va ish vaqti faqat
server `available: true` desa ko'rsatiladi; aks holda ishlaydigan narsa taklif qilinadi — **ilova ichidagi
murojaat** (S14 `POST /support/tickets`) va o'z murojaatlari ro'yxati. FAQ javoblari ham v2 ga moslandi
(narxni **tomonlar kelishadi**, ELCHI belgilamaydi — Q90).

Yangi API: `supportContacts`, `createSupportTicket`, `mySupportTickets`.

### Sozlamalar

Alohida ekran: ko'rinish (light/dark/system), Yordam, Maxfiylik siyosati, Chiqish, versiya. Har ikki
profildan kiriladi.

**Ataylab ko'chirilmagani va sababi:**

- **Bildirishnoma tugmachalari** — frozen panelda ular komponent state'ida turadi, ya'ni sozlamaga o'xshaydi
  lekin keyingi ochilishda unutiladi; ustiga push provayderi hali yo'q (Q82) va yagona kanal — ilova ichidagi
  inbox, uni o'chirish mahsulotni jimlatadi. Hech narsani eslab qolmaydigan va hech narsani boshqarmaydigan
  tugmacha — tugmacha yo'qligidan yomonroq.
- **Til tanlash** — lug'at qatlami tarjima qilingan, ekran matnlari yo'q; rus tilini tanlash yarim ruscha
  ilova beradi.

### Maxfiylik siyosati

`frontend/src/pages/PrivacyPolicy.tsx` to'liq ko'chirildi, ranglari tokenlarga o'tkazildi, `/privacy` ga
ulandi (sessiyasiz ochiladi — store listing ham, sozlamalar ham shu havolaga ishora qiladi).

**Diqqat:** matnda `[YURIDIK SHAXS NOMI]` kabi to'ldirilmagan joylar bor va faylning o'zida yozilgan
ogohlantirish saqlanib qoldi: e'lon qilishdan oldin real yuridik shaxs ma'lumotlari kiritilishi va matn
O'zR ZRU-547 bo'yicha yurist ko'rigidan o'tishi shart. Bu holicha qoldirildi — men uni «tayyor» deb
ko'rsatmadim.

### Diagramma — kutubxonasiz va rost ma'lumotdan

Frozen mijoz haydovchining **daromadini** `recharts` bilan chizadi. Stage 2 da buni chizib bo'lmaydi:
yo'lkira mijoz va haydovchi o'rtasida **naqd** o'tadi va ELCHI ledgeriga umuman kirmaydi. «Daromad»
diagrammasi o'ylab topilgan pul bo'lardi (AGENTS.md §9).

Shuning uchun diagramma **ushlangan komissiyani** ko'rsatadi — bu platforma haqiqatan yozib olgan yagona
summa (`commission_capture`, `occurred_at` bo'yicha 7 kun / 6 oy). Bar ustida shu yozilgan: «Yo'lkira
mijozdan sizga naqd o'tadi va bu yerda ko'rinmaydi.»

`recharts` **qo'shilmadi**: bitta 140px diagramma uchun ~300 KB. O'sha chizma dizayn tizimida CSS bilan
(`BarChart`) — bir xil ko'rinish, nol bayt.

### Haydovchida bildirishnomalar

Bu shunchaki kosmetik emas edi: push provayderi yo'q (Q82), ya'ni **inbox yagona yetkazish kanali**, va
haydovchida u umuman ochilmasdi — mijoz javob berganini haydovchi hech qachon ko'rmasdi.

- Inbox ikkala tomon uchun ishlaydigan qilindi (`driver-notifications`, bir xil tana, rolga qarab nav).
- Haydovchi bosh sahifasida **qo'ng'iroqcha** va o'qilmaganlar soni (frozen mijozdagidek). Nav panelida
  allaqachon 5 ta tab bor — oltinchisi shu enda o'qib bo'lmas edi.
- Mijoz nav panelidagi qo'ng'iroqchada o'qilmaganlik nuqtasi.

### Tekshiruvlar

| Buyruq | Natija |
|---|---|
| `npm run lint` (`tsc --noEmit`) | xatosiz |
| `npm test` | **45 passed** |
| `npm run build` | `✓ built` (868 kB — `recharts` qo'shilganda ~1.2 MB bo'lardi) |
| `GET /`, `/admin`, `/privacy` | 200 / 200 / 200 |
| `GET /api/v2/support/contacts` (sessiyasiz) | 401 — kutilgan |
| `qa_probe_ui_journey.py` / `qa_probe_auction.py` | **54 checks 0 failures** / **18 checks 0 failures** |
| `git status frontend/ android-app/` | **0 fayl** |

---

## Wave 19 (20.09.2026) — yo'nalish uchi: bekat ro'yxati emas, xarita (Q88 oqimi to'g'rilandi)

Foydalanuvchi topilmasi (ikki skrinshot): «Toshkent shahri» tanlanganda **«Bekatni tanlang»** ochilib, ichida
bitta `Toshkent bekati (fixture)` turadi; Qashqadaryo tumanlari ro'yxatida esa har bir haqiqiy tuman yonida
`(fixture)` dublikati va ostida `Bekat yo'q` yozuvi. Talab: tuman tanlansa **xarita o'sha tumanda ochilsin**,
foydalanuvchi o'zi nuqta belgilasin.

### Ildiz sabab

Ikkalasi ham **Q88 gacha bo'lgan «avval bekat» modelining qoldig'i** edi. Q88 uni almashtirgan: mijoz uchni
xaritada ixtiyoriy nuqta sifatida belgilaydi, nuqta tasdiqlangan marshrutga proyeksiya qilinadi, bekat uchi
esa **qoladi lekin majburiy emas** (u `exact` moslik beradi).

Katalogda **170 tumandan atigi 6 tasida** faol bekat bor — ya'ni «avval bekat» oqimi amalda hammani bloklardi,
`Bekat yo'q` yozuvi esa ularga «bu tuman ishlamaydi» deb turardi, bu Q88 dan keyin **noto'g'ri**.

### Bajarilgani

| # | Ish |
|---|---|
| 1 | **Tumansiz viloyat → xarita.** `requires_district = false` (Toshkent shahri) endi bekat ro'yxatiga emas, to'g'ridan-to'g'ri nuqta tanlashga olib boradi. Kamera viloyat markazida ochiladi (0080: UZ-TK = 41.3111/69.2597) |
| 2 | **Bekat tanlash xaritaga ko'chdi.** Tumanda tasdiqlangan bekat bo'lsa, xarita ostida yorliq (chip) sifatida taklif qilinadi; bosilsa `exact` moslikli bekat uchi tanlanadi. Majburiy qadam emas |
| 3 | **`client-stop-selector` ekrani va `StopSelector` komponenti o'chirildi** — endi hech qayerdan ochilmaydi (o'lik UI qoldirilmadi) |
| 4 | **Tuman qatori soddalashtirildi:** faqat nom va `>`. `Bekat yo'q` / `N ta bekat` yozuvi va ikki rangli ikonka olib tashlandi; qator 74px → 58px |
| 5 | **Xato tuzatildi:** haydovchi xaritadan nuqta belgilaganda mijoz bosh sahifasiga tushib ketardi (`markPoint` `directionOwner` ni hisobga olmasdi) |

### `(fixture)` dublikatlari

Fixture koridori o'z tumanlarini yaratardi (`Qarshi (fixture)`), chunki u katalog importidan oldin yozilgan.
Natijada dev bazada **ikkita `Qarshi`** turardi: biri koridor bekatlarini tashiydi, ikkinchisi yo'q, va
ekranda qaysi biri ekanini ajratib bo'lmasdi.

- **Loader** (`tests/fixtures/geo/loader.py`) endi bekatlarni **haqiqiy** tuman qatoriga osadi; nom bo'yicha
  (case-insensitive) topadi, topilmasa yaratadi.
- **0082 migratsiyasi** mavjud bazalarda xuddi shuni qiladi — lekin **yozuvni hech qachon qayta yozmaydi.**
  `geo_districts` ga **10 ta ustun** ishora qiladi va ulardan ikkitasi muzlatilgan snapshot: `bookings` va
  `proposal_versions` kelishuv qaysi tumanda tuzilganini yozib qo'ygan, bron snapshot'i esa trigger bilan
  himoyalangan (Q60). Shuning uchun:
  1. `corridor_stops` haqiqiy tumanga ko'chadi — fixture aynan shuni noto'g'ri ulagan edi;
  2. hali biror joydan ishora qilinayotgan fixture qatori **o'chirilmaydi, deaktivatsiya qilinadi**
     (`list_districts` `is_active` bo'yicha filtrlaydi) — bironta FK joyidan qimirlamaydi;
  3. hech kim ishora qilmaydigan qator o'chiriladi.

  Faqat nomi `(fixture)` bilan tugaydigan va o'sha viloyatda haqiqiy nomdoshi bor qatorlar ko'riladi —
  demak production (unda bunday qator yo'q) umuman tegilmaydi.

Toshkent shahri uchun bitta qator qonuniy ravishda qoladi: viloyatda tuman **umuman yo'q** (wave 10 — shahar
o'zi yo'nalish birligi), bekat esa tumansiz mavjud bo'la olmaydi. U `Toshkent shahri` deb nomlandi va hech
qachon ko'rinmaydi, chunki `requires_district = false`.

**Dev baza natijasi:** 170 → 166 tuman qatori (4 tasi o'chirildi), 1 tasi deaktiv, 165 faol; 5 bekat haqiqiy
tumanlarga ko'chdi. Jonli API: Qashqadaryoda 14 ta tuman, `(fixture)` qatori **yo'q**.

### Tekshiruvlar

| Buyruq | Natija |
|---|---|
| `alembic upgrade head` → `downgrade -1` → `upgrade head` | toza, `20260920_0082` (bitta head) |
| `pytest tests/pg/geo` | **100 passed** |
| `npm run lint` / `npm test` / `npm run build` | xatosiz / **45 passed** / `✓ built` |
| Jonli `/api/v2/districts?region_id=UZ-QA` | 14 tuman, fixture qatorlari yo'q |
| Jonli `/api/v2/stops/search` | 6 bekat, hammasi haqiqiy tumanlarda |
| `qa_probe_ui_journey.py` / `qa_probe_auction.py` | **54 checks 0 failures** / **18 checks 0 failures** |

`tests/pg/geo/test_geo_districts_pg.py` yangilandi: u fixture dublikat nomlarini kutardi, ya'ni men olib
tashlagan xulqni qotirib qo'ygan edi.

---

## Wave 19.1 (20.09.2026) — «Kasbi tanlandi, Kitob chiqdi»: uchta alohida nuqson

Foydalanuvchi skrinshoti: sarlavhada **Kasbi, Qashqadaryo viloyati**, «Tanlangan joy» esa **Kitob**,
koordinata `38.86060, 65.78900`. Bir ekranda uchta har xil nuqson ustma-ust tushgan.

### 1. Kasbining markazi katalogda yo'q

`38.8606, 65.7890` — bu **Qashqadaryo viloyatining markazi** (Qarshi). Kasbida `center_lat/lng` yo'q
(wave 17.1 da to'ldirilmagan 65 tumandan biri; Qashqadaryoda 14 tumandan 7 tasi shunday), shuning uchun
kamera viloyat markaziga tushgan — ya'ni **boshqa tumanga**. Ekran esa buni «tanlangan joy» deb taqdim
etgan: Kasbini tanlab, tasdiqlab, pin Qarshida qolardi.

**Tuzatish:** kamera pozitsiyasi viloyat darajasida bo'lsa, u **javob emas, ko'rinish** deb hisoblanadi.
Pin qo'yilmaguncha (xaritani surish yoki qidiruv) «Shu joyni tanlash» **o'chiq** turadi, karta «Joy
belgilanmagan» deb yozadi va sabab ochiq aytiladi: bu tumanning markazi katalogda hali yo'q.

### 2. «Kitob» degan nom qayerdan kelgan

`/geo/reverse-geocode` Yandex kaliti yo'qligida `nearest_district()` ga tushadi, u esa **v1 `districts`**
jadvalini skanerlaydi — wave 17.1 fosh qilgan **generatsiya qilingan 0.08° panjara** o'sha yerda qolgan.
Qarshining koordinatasiga eng yaqin panjara katagi «Kitob» deb nomlangan ekan.

**Tuzatish:** server `provider: "local"` qaytarsa, mijoz uni **manzil deb hisoblamaydi** va koordinatani
ko'rsatadi. Noto'g'ri joy nomi joy nomi yo'qligidan yomonroq. v1 ma'lumotiga tegilmadi — u backward
compatible va uning qiymatlarini o'zgartirish tasdiqlangan qaror talab qiladi (Q2/Q10).

### 3. Xarita umuman yuklanmayapti

`mobile-app/.env` fayli **mavjud emas**, ya'ni `VITE_YANDEX_MAPS_API_KEY` bo'sh va xarita matnli zaxiraga
tushadi. Foydalanuvchi `.env.example` dagi namuna kalitni sinashni tanladi:

```
GET https://api-maps.yandex.ru/v3/?apikey=113dbff8-...
{"statusCode":403,"error":"Forbidden","message":"Invalid api key"}
```

Namuna kalit **yaroqsiz**. Xarita haqiqiy kalitsiz ishlamaydi.

Zaxira matni ham yolg'on gapirayotgan edi: «joyni tuman markazidan tasdiqlashingiz mumkin» — kamera viloyat
markazida turganda bu noto'g'ri. Endi u shartli: markaz haqiqatan o'sha tumanniki bo'lsagina shunday deydi.

### Kalit kelganda: `scripts/geocode_missing_district_centres.py`

65 ta markazni **xotiradan yozish** — wave 17.1 fosh qilgan nuqsonning aynan o'zi. Geokoder esa manba.
Skript har bir tumanni nomi bo'yicha so'raydi va javobni uch tekshiruvdan o'tkazadi: O'zbekiston chegarasida
bo'lishi, o'z viloyat markazidan `--max-km` dan uzoq bo'lmasligi, va Yandex qaytargan nom so'ralgan tumanga
o'xshashi. O'tmagani **NULL qoladi**. Default'da **hech narsa yozmaydi** — avval jadval ko'riladi, keyin
`--apply`.

### Ochiq qolgani

- **Yandex JavaScript API kaliti** — xarita uchun majburiy, foydalanuvchida.
- **`ELCHI_YANDEX_GEOCODER_API_KEY`** — manzil nomlari va yuqoridagi skript uchun.
- 65 ta tuman markazi — kalit kelgach skript bilan to'ldiriladi.

### Tekshiruvlar

| Buyruq | Natija |
|---|---|
| `npm run lint` / `npm test` / `npm run build` | xatosiz / **45 passed** / `✓ built` |
| `qa_probe_ui_journey.py` | **54 checks, 0 failures** |
| Yandex v3 namuna kalit bilan | **403 Invalid api key** |
| Skript kalitsiz | to'xtaydi, hech narsa yozmaydi |
