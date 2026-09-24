# Referral, bonus va rag‘bat tizimi — bajarish rejasi

**Holat:** referral moduli **lokal yakunlangan, production gate’lari yopilmagan** (24.09.2026). 0–6-bosqichlar lokal bajarildi: migratsiyalar 0084–0090, Q101–Q135, simulyator (sintetik), A6.2 hisobot, QA #1–#24 ([QA_REPORT.md](QA_REPORT.md)), go-live checklist ([GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md)), G14 budjet chegarasi. `promotions_enabled` production’da `false`; hech bir kampaniya, parametr yoki budjet tasdiqlanmagan; haqiqiy muhit, qurilma, App Links, DNS/TLS va deploy tekshirilmagan • **Yangilangan:** 24.09.2026
**Topshiriq:** [`ELCHI_REFERRAL_TASK.md`](ELCHI_REFERRAL_TASK.md) (§1–§17 havolalari shu faylga) • **ADR:** [ADR-0023](../architecture/adr/0023-promotions-referral.md) • **Qarorlar:** `AGENTS.md §3` Q101–Q119
**Ish tartibi:** har bosqich oxirida hisobot (AGENTS.md §8) → foydalanuvchi tasdig‘i → keyingi bosqich.
Commit/push/deploy yo‘q. `android-app/`, `frontend/` tahrirlanmaydi — ular uchun faqat handoff.
Barcha test summalari **sintetik**; mukofot, budjet, O, M, share qiymatlari 6-bosqich simulyatsiyasidan keyin.

---

## 1. Audit xulosasi (mavjud tizim)

| Soha | Hozir nima bor | Referral uchun ahamiyati |
|---|---|---|
| Komissiya | `contracts/money.py:82 commission_minor`; bronda `fee_policy_id`, `fee_bps`, `commission_minor`, `commission_status` snapshot, Q60 trigger bilan muzlatilgan | C shu formuladan. Bronga P/H/C_net/F_cash ustunlari qo‘shiladi → Q60 trigger’i kengaytiriladi (4-bosqich) |
| Hold/capture | `wallet/service.py`: `hold_fee` :830, `adjust_hold` :899, `capture_fee` :934, `release_fee` :976, `reverse_fee` :1000 | Real hold **C_net** bo‘yicha. Real ledger’ga yangi manba turi kerak emas |
| Ledger manbasi (Q55) | `LEDGER_SOURCE_TYPES` = topup, adjustment, wallet_hold; DB CHECK + commit trigger | Referral real ledger’ga kredit yozmaydi. Q55/Q48 **avtomatik yopilmaydi** — 4-bosqichda qayta isbot |
| Quote | Alohida obyekt yo‘q; `proposal_versions` da fee snapshot + `expires_at`; `FeeQuoteDTO` faqat driver’ga | Yagona `PromoQuote` (versiya, fingerprint) + `PassengerBonusConsent` |
| Accept | `bookings/service.py:615 accept_proposal`: lock’lar → tekshiruvlar → `reserve` → booking → `hold_fee` → outbox | Lot rezervlari lock tartibida `wallet_accounts`dan keyin (ADR-0023 §13) |
| Yakun | `_complete` :1351 capture; `_release_fee`; `cash_receipts` (`reported_paid → acknowledged/contested`) | Qualification: capture + `acknowledged` + nizo yo‘q + 48 soat |
| Flag’lar | `feature_flag_values` (geo), `FeatureFlagKey` enum + CHECK migratsiyasi | Yangi `promotions_enabled`, production `false` |
| Identity | v2’da signup yo‘q — user v1 OTP verify’da; o‘chirilgan telefon yangi user bo‘lib qaytadi | Himoyalangan telefon HMAC (Q108) |
| Qurilma | `device_tokens`, `device_account_links`, `fraud_signals` | Zaif signal sifatida qayta ishlatiladi |
| Outbox | `outbox_events.dedup_key` **unique emas** | Grant idempotentligi DB unique kalitlarga tayanadi |
| Klient versiyasi | Header yo‘q | `X-Elchi-Client-Features: promo_cash_v1` (kontraktda) |
| Web/linklar | `landing/` (Vercel), `assetlinks.json` yo‘q | Web sahifa + qo‘lda kod; App Links — handoff |
| Klientlar | `mobile-app/` — Vite React web (yagona v2 klient); `android-app/` — Expo, v1, muzlatilgan | Android foydalanuvchilari referral’dan foydalana olmaydi — ochiq cheklov |

## 2. Spec va qarorlar bilan ziddiyatlar — hal qilinishi

| # | Ziddiyat | Holat |
|---|---|---|
| 1 | Spec §9.2 faqat muddatli komissiya kampaniyasini ko‘radi | Hal: Q101 + ADR-0023 (spec o‘zgarmaydi, kengaytma) |
| 2 | Q16 — mijoz komissiyani taxmin qilishi mumkin | Hal: Q103 (bevosita oshkor qilmaslik, taxmin kafolati yo‘q) |
| 3 | AGENTS.md §4 modul ro‘yxati | Hal: `promotions` qo‘shildi (Q102) |
| 4 | Q60 snapshot muzlatish | Qaror: yangi ustunlar faqat amendment bilan (ADR-0023 §6); implementatsiya 4-bosqich |
| 5 | Q74 finance_review | Qaror: capture bo‘lmaguncha qualification kutadi (Q110); UX “tekshiruvda” |

## 3. 12 kamchilik — yechim yoki ochiq holat

| # | Kamchilik | Yechim | Holat |
|---|---|---|---|
| K1 | Haydovchi mijozsiz accept qiladi — P roziligi | `PassengerBonusConsent` + `quote_at_accept`: aynan tasdiqlangan P, aks holda `PROMO_QUOTE_STALE` (Q104). “Bron’dan keyin qo‘llash” varianti **qabul qilinmadi** | ✅ Kontrakt + test. Integratsiya — 4-bosqich |
| K2 | Haydovchi F_cash ni bilmasligi | `driver_view` (naqd olinadigan summa); `promo_new_deal_allowed` — ikkala klient `promo_cash_v1` e’lon qilmasa yangi promo bitim yo‘q | ✅ Kontrakt + test. Header o‘qish va klient UI — 4/5-bosqich |
| K3 | Cash receipt F bilan solishtiriladi | `cash_receipt_matches(F_cash, …)` | ✅ Kontrakt. `report_cash_receipt` o‘zgarishi — 4-bosqich |
| K4 | Amendment F_cash ni oshirishi | `amendment_reconfirmation` — mijoz/haydovchi qayta tasdig‘i; F_cash oshadigan holat testlangan | ✅ Kontrakt + test. Amendment oqimi — 4-bosqich |
| K5 | Ko‘p bronli trip ko‘p safar sanalishi | `milestone_progress` (distinct trip, bog‘lanmagan mijoz), `milestones_reached(min_distinct_clients)`; driver→driver kampaniyasi `min_distinct_clients` siz aktivlashmaydi | ✅ Kontrakt + test (QA #17). Qiymat — konfiguratsiya, production tasdiqlanmagan |
| K6 | O‘chirilgan telefon qayta ro‘yxatdan o‘tishi | HMAC identity kaliti, `acquisition_key(identity, family)`, moslik → faqat review (Q108) | ⚠️ Mexanizm tasdiqlangan; **saqlash muddati, huquqiy asos, maxfiylik siyosati bandi — ochiq** (production sharti) |
| K7 | Budjet manbai kamayishi | `BudgetPosition.reduce_allocation` → `shortfall`, yangi enrollment to‘xtaydi, majburiyatlar qoladi | ✅ Kontrakt + test (QA #8). Mas’ulga ko‘rsatish — 5-bosqich admin |
| K8 | O/M noma’lum, lekin sintetik oqim ishlashi kerak | `None` → `PROMO_PARAMETERS_UNSET`; `validate_activation` (M > 0 ham); testlar sintetik policy bilan | ✅ Kontrakt + test |
| K9 | Review cheksiz qolishi | `review_due_at` SLA; muddat o‘tsa eskalatsiya, avtomatik qaror yo‘q; qaror admin+ (`promo.fraud_decide`); risk qoidalari versiyalangan (Q113) | ✅ Kontrakt. SLA — konfiguratsiya (sintetik); review navbati va audit oqimi — 3-bosqich |
| K10 | Analitika bazasi yo‘q | SQL view + admin hisobot endpoint, tashqi analitika yo‘q | ✅ `GET /admin/promo/report` (operatsion, faqat o‘qiydi) |
| K11 | Link ilovani ochishi, android muzlatilgan | `/r/<kod>` web sahifa + qo‘lda kiritish; App Links handoff; host konfiguratsiyada (Q107) | ⏳ 2/5-bosqich. **Domen/deploy/sertifikat — ochiq**, tekshirilmaguncha “tayyor” emas |
| K12 | Promo rezervlari uchun lock guruhi | ADR-0023 §13 (1-bosqichda aniqlashtirildi): `wallet_accounts → promo_campaigns → promo_obligations → promo_lots → promo_redemptions → promo_budgets (faqat ledger trigger) → wallet_holds` | ✅ Promo ichki qismi PG’da isbotlandi (1-bosqich). Booking/wallet bilan birga — 4-bosqich |

## 4. Bosqichlar

### 0-bosqich — Audit va moliyaviy kontrakt ✅ (23.09.2026)
- Topshiriq saqlandi, audit, reja; ADR-0023; Q101–Q110; AGENTS.md §4 `promotions`.
- `app/contracts/promo.py`: `quote_promo`, `quote_at_accept`, `record_consent`, `client_view`/`driver_view`, `amendment_reconfirmation`, `passenger_bonus_allowed`, `lot_usable_for`, client-features qoidalari, `cash_receipt_matches`, `LotBalance`, `reversal_plan`, `restored_expiry`, `BudgetPosition`, `CampaignTerms`/`validate_activation`, attribution/qualification/milestone qoidalari, idempotentlik kalitlari.
- `enums.py` — `Promo*`, `ReferralAttributionStatus`, `FraudSignalStrength` (1-bosqichda versiyalangan `PromoRiskSignal` + `RISK_RULESET_V1` bilan almashtirildi); `errors.py` — 7 yangi kod; `state_machines.py` — 5 mashina (`PROMO_MACHINES`); `STATE_MACHINES.md` §13.
- Testlar: `tests/contracts/test_promo.py` (243 ta, sintetik).

### 1-bosqich — Kampaniya, budjet va promo ledger ✅ (23.09.2026)
- Qarorlar Q111–Q116 (AGENTS.md §3, ADR-0023). Kontrakt: marja invariantlari (`O ≥ 0`, `M > 0`, `C_net > 0`), yaxlitlash qoidasi, versiyalangan `RISK_RULESET_V1`, pochta jo‘natmasi dalili, qualification muddati, oldindan ko‘rsatiladigan shartlar, budjet uchun ikki xodim qoidasi.
- Migratsiya `20260923_0084_promotions_core`; modul `app/modules/promotions/` (models, service); flag `promotions_enabled`; capability’lar `promo.*`.
- PG testlari `tests/pg/promotions/` (1-bosqichda 33 ta). 1-bosqich oxiridagi to‘liq PG progoni (toza snapshot, `ELCHI_TEST_PG_REQUIRED=1`): 784 passed, 0 failed, 0 skipped; non-PG: 1806 passed.
- **Qilinmagan (keyingi bosqichlarga):** HTTP endpointlar (5), attribution/enrollment (2), qualification va review navbati (3), booking/wallet integratsiyasi va C_net hold (4), worker job ro‘yxatdan o‘tkazish (3), klient UI (5).

### 2-bosqich — Kod, attribution, enrollment ✅ (23.09.2026)
- Qarorlar Q117–Q119; migratsiya `20260923_0085_promotions_referral`; `promotions/referral.py` (kod, attribution, enrollment, offer), `promotions/identity.py` (Q108 HMAC, rotatsiya, o‘chirishda tozalash); v1 akkaunt o‘chirish oqimiga identity hook; `promo.*` capability’lar MFA step-up ro‘yxatida.
- 1-bosqich dalillari: migratsiya (toza baza / oldingi head’dan bosqichma-bosqich / head’da no-op / body idempotentligi — alohida testlar), haqiqiy application roli bilan DB himoyasi, eskirgan chegirma faqat joriy accept urinishini rad etadi.
- Natija (toza snapshot, `ELCHI_TEST_PG_REQUIRED=1`): PG 821 passed, 0 failed, 0 skipped (promotions — 70); non-PG 1830 passed.
- **Qilinmagan:** HTTP endpointlar va App Links (5; kontrakt ADR-0023 §16), attribution ↔ `accept_proposal` to‘liq poyga testi (4, A4.12), review navbati va `identity_needs_review` holatini ko‘rib chiqish (3), operator attribution tuzatishi (3), identity digest tozalash job’i worker’ga ulanmagan (3).

### Test muhiti (izolyatsiyalangan PG progoni)
Repo ildizidagi mahalliy `.env` dev sozlamalari (`ELCHI_GEO_*`) ikkita mavjud PG testini o‘zgartiradi (baseline’da ham takrorlangan). Toza natija uchun daraxt `.env` siz nusxalanadi va o‘sha yerda ishga tushiriladi; `.env` o‘zgartirilmaydi:
```bash
SNAP="$TMPDIR/elchi-pg"; rm -rf "$SNAP"; mkdir -p "$SNAP"
tar --exclude=__pycache__ --exclude=node_modules --exclude=docs/store-screenshots -cf - \
    app alembic alembic.ini tests scripts pyproject.toml requirements*.txt docker docker-compose.test.yml docs AGENTS.md \
    mobile-app/src mobile-app/package.json | (cd "$SNAP" && tar -xf -)
cd "$SNAP" && bash scripts/test-pg.sh -- -q --junitxml=pg-junit.xml   # ELCHI_TEST_PG_REQUIRED=1, port 45432
```
### 3-bosqich — Qualification, grant, milestone, fraud review ✅ (23.09.2026)
- Migratsiya `20260923_0086_promotions_qualification`; `promotions/qualification.py`, `promotions/jobs.py`; 7 ta worker job `SERVICE_JOBS` da; outbox `promo.reward_granted`, `promo.review_opened`, `promo.review_escalated` (faqat staff).
- Dalil **haqiqiy bron hayot siklidan** (real accept/hold, proof kodlari, cash receipt, finance capture) — testlarda; bron oqimi hali `record_booking_event` ni chaqirmaydi (4-bosqich), sweep job buni qoplaydi.
- Talqinlar T1–T3 (ADR-0023 §17) — Q-qaror emas, tasdiq kutmoqda. Attribution tuzatish yoqilmagan — `ATTRIBUTION_CORRECTION_PROPOSAL.md`.
- Natija (toza snapshot, `ELCHI_TEST_PG_REQUIRED=1`): PG 841 passed, 0 failed, 0 skipped (promotions — 90); non-PG 1830 passed.
### 4-bosqich — Redemption: quote/accept/cancel/amend/complete integratsiyasi ✅ (23.09.2026)
- Migratsiya `20260923_0087_promotions_booking`; `promotions/booking.py`; bookings orkestratori (accept, amendment, cancel/no-show, complete, `finalize_fee`, cash receipt), wallet (C_net hold, `reverse_fee` hodisasi), trust_support (nizo hodisasi), marketplace (preview + klient imkoniyati).
- Q120/Q122 kodda. T4 talqinlari (ADR-0023 §18) — Q-qaror emas, tasdiq kutmoqda.
- Ikki sessiya natijasi bitta holatga keltirildi (23.09.2026, integrator sessiya): `promo_quote`/amendment `promo` — rolga alohida obyekt; A4.4/A4.7/A4.10 uchun 3 ta qo‘shimcha PG testi; A4 bandlari testlarga bog‘landi; T4 to‘liq matni ADR §18.1.
- Natija, kod holati barmoq izi `03d6762afd6baab2` (`git ls-files -mo` sha256): izolyatsiyalangan PG (`.env`siz snapshot, `ELCHI_TEST_PG_REQUIRED=1`, `scripts/test-pg.sh`) — **875 passed, 0 failed, 0 skipped, 0 error, 154 deselected**; standart non-PG (`pytest tests -m "not pg"`, repo muhiti) — **1845 passed, 0 failed, 0 skipped, 875 deselected**. `.env`siz snapshot’dagi non-PG’da 1 failed (`test_client_otp_length`: test repo `.env` dagi `otp_length`ga tayanadi — muhit artefakti, kod xatosi emas).
- Eslatma: avvalgi `pytest tests --ignore=tests/pg` buyrug‘i `tests/pg/` ichidagi 154 ta markersiz unit testni tashlab yuborgan; ular alohida bajarildi (154 passed) va yuqoridagi standart progonga kiradi.
### 5-bosqich — Interfeys (mobile-app), admin API, web sahifa, android handoff (24.09.2026, lokal qism ✅ — pastda)
- Migratsiyalar `20260923_0088_promotions_rate_events`, `20260923_0089_promotions_t4` (Q123–Q129); QR — `qrcode-generator` 2.0.4 (ADR-0024); handoff: `INFRA_HANDOFF.md`, `APP_LINKS_HANDOFF.md`; `promotions/api.py`, `portal.py`, `schemas.py`; marketplace `promo_consent` + `promo-preview`; mobile `promo.ts`, `api/v2/promo.api.ts`, `v2/PromoScreens.tsx`, `AdminPromoPanel.tsx`; landing `r.html`; `APP_LINKS_HANDOFF.md`. ADR-0023 §19.
### 6-bosqich — Simulyator, metrikalar, yakuniy QA va go-live checklist (24.09.2026: lokal qism ✅ — A6.1–A6.3 pastda)
- `app/modules/promotions/simulation/`, `scripts/promo_simulate.py`, `docs/referral/simulation/` (`scenarios.json`, `results.json`, `REPORT.md`) — **sintetik ssenariylar**. ADR-0023 §20. Migratsiya yo‘q.

Har bosqich qamrovi va qabul mezonlari §5 da.

## 5. Keyingi bosqichlar uchun acceptance mezonlari

Har mezon tekshiriladigan: test nomi yoki buyruq natijasi hisobotda ko‘rsatiladi. “PG” — haqiqiy PostgreSQL (`scripts/test-pg.*`), SQLite emas.

### 1-bosqich — kampaniya, budjet, promo ledger (✅ bajarildi — testlar yakuniy hisobotda)
- A1.1 Migratsiya(lar) `20260923_0084…` dan, idempotent upgrade (ikki marta ishga tushirish dublikat yaratmaydi), `alembic heads` bitta, DATA_MODEL.md reyestri yangilangan.
- A1.2 `promo_campaign_versions` qatorlari o‘zgarmas (DB trigger); enrollment versiyaga FK bilan bog‘langan (QA #22, PG).
- A1.3 Parametri `NULL` versiyani `active`ga o‘tkazish DB va servisda rad (`PROMO_PARAMETERS_UNSET`), `M > 0` CHECK.
- A1.4 Promo ledger double-entry: har tranzaksiya yig‘indisi 0; bucket balanslari `BudgetPosition` bilan bir xil (reconciliation funksiyasi, PG).
- A1.5 Parallel enrollment (≥ 20 oqim) budjetdan oshmaydi (QA #7, PG, budjet qatori lock).
- A1.6 Budjet tugashi → kampaniya `paused`, oldingi grant’lar sarflanadi (QA #8, PG).
- A1.7 `promotions_enabled` flag: CHECK kengaytirilgan, production default `false`, mavjud flag’lar o‘zgarmagan (test).
- A1.8 Capability’lar: operator budjet/mukofotni o‘zgartira olmaydi (403), katta allocation ikki turli xodim, har o‘zgarish `audit_logs`da.
- A1.9 Real ledger jadvallariga promotions’dan yozuv yo‘q (grep/arxitektura testi + PG: `ledger_transactions` soni o‘zgarmaydi).

### 2-bosqich — attribution va enrollment
- A2.1 ✅ Kod PII’siz, CSPRNG, DB unique, kolliziyada qayta urinish (`promo.new_referral_code`, `test_code_is_random_unique_and_retried_on_collision`). `/r/<kod>` host — 5-bosqich (§16 kontrakt).
- A2.2 ✅ O‘z kodi (boshqa rol orqali ham) rad (QA #1); parallel ikki kod — bittasi (QA #2) — PG.
- A2.3 ✅ Birinchi attribution almashtirilmaydi (PG). ⏳ Operator tuzatishi (sabab + audit) — 3-bosqich.
- A2.4 ✅ 72 soat server vaqti bilan (PG). ⚠️ “O‘chirib qayta ochish oynani yangilamaydi” — faqat Q108 saqlash muddati tasdiqlansa ishlaydi (digest saqlanadi, identity oynasi saqlanadi — PG testi sintetik siyosat bilan); tasdiqlanmaguncha production enrollment yopiq.
- A2.5 ✅ Oila bo‘yicha bitta tirik enrollment (identity va user partial unique) — yo‘lovchi+pochta; haydovchi oilasi alohida ochiq (PG).
- A2.6 ✅ Digest mosligi akkaunt/xizmatni bloklamaydi; enrollment `identity_needs_review` (PG). Review oqimi — 3-bosqich.
- A2.7 ✅ Attribution hech narsa va’da qilmaydi, rezerv qilmaydi (PG).
- A2.8 ⏳ Kod tekshiruvi faqat `valid` (PG); HTTP DTO allowlist testi — 5-bosqich.
- A2.9 ✅ Ikkala tomon bitta tranzaksiyada yoki hech biri (QA #6, PG); pauza va versiya almashishi bilan parallel izchil (PG).
- A2.10 ✅ Bir xil idempotency kaliti boshqa mazmun bilan — `IDEMPOTENCY_KEY_REUSED`; takroriy enrollment bitta majburiyat va bitta rezerv (PG parallel).
- A2.11 ✅ Referral rad etilishi ro‘yxatdan o‘tishni buzmaydi; xato tranzaksiyadan keyin yetim attribution/enrollment/rezerv qolmaydi (PG).

### 3-bosqich — qualification va grant
- A3.1 ✅ Intake dedup (`dedup_key` unique, RETURNING); worker commit’dan oldin uzilsa qayta ishlanadi, commit’dan keyin qayta yurish yangi grant yaratmaydi (PG).
- A3.2 ✅ Risk oynasi eng oxirgi shartdan; 48 soatdan oldin/aynan/keyin (PG); grant tranzaksiyasida dalil va faollik qayta o‘qiladi.
- A3.3 ✅ Capture’siz, nizoli, taklif qiluvchi xizmat ko‘rsatgan bron grant bermaydi; referrer bronidan keyin boshqa haydovchi bilan grant (PG). 0% / C_net=0 — kontrakt testi (real 0% bron 4-bosqich).
- A3.4 ✅ Ikki bron bitta trip’da — bitta milestone qadami; ikkinchi trip — ikkinchi qadam (PG); pochta: bitta trip’dagi ikki mustaqil jo‘natma hisoblanadi, sun’iy bo‘linish → review (PG).
- A3.5 ✅ Versiyali qoidalar (kontrakt); review SLA va eskalatsiya — avtomatik qaror yo‘q (PG). Real IP/qurilma signal manbalari hali ulanmagan.
- A3.6 ✅ Va’da → grant o‘tishida budjet ikki marta sanalmaydi; reconciliation bo‘sh (PG).
- A3.7 ✅ Grant’dan keyingi refund → review → rad etilsa sarflanmagan qism reversal; real balans o‘zgarmaydi (PG).
- A3.8 ✅ 7 job ro‘yxatda, application roli bilan ishlaydi (PG); commit/crash xavfsiz.
- A3.9 ✅ `reinstate_expired_release`: asl yozuvga bog‘langan, parallel ham bitta, budjet xonasiz rad (manfiy qoldiq yo‘q) (PG).
- A3.10 ✅ Review navbati (identity, qualification_risk, party_not_active, post_grant_recheck): rollback’da yo‘qolmaydi, takrorlanmaydi, operator qaror qila olmaydi, tasdiq mukofot yaratmaydi (PG).
- A3.11 ⏸ Operator attribution tuzatishi — yoqilmagan; taklif hujjatlashtirildi (qaror kutilmoqda).

### 4-bosqich — redemption integratsiyasi (A4 orkestratori bilan)
Dalillar `tests/pg/promotions/test_promo_booking_pg.py` (bundan keyin `B::`), `tests/contracts/test_promo_booking.py` (`C::`). Har band bu sessiyada kod va test bilan qayta tekshirildi (23.09.2026); boshqa sessiya hisoboti yolg‘iz dalil sifatida olinmadi.
- A4.1 ✅ Accept: sig‘im + lot rezervlari + C_net hold bitta tranzaksiyada; xato bo‘lsa hammasi rollback — `B::test_bonus_enough_but_driver_real_balance_short_rolls_back_everything`, `B::test_synthetic_example_runs_through_the_real_flow`.
- A4.2 ✅ Ikki parallel accept bir lotni ikki marta rezerv qilmaydi — `B::test_two_parallel_accepts_cannot_spend_one_bonus`.
- A4.3 ✅ Roziliksiz/eskirgan rozilik bilan kattaroq F_cash’li bron yo‘q — `B::test_consent_needs_a_capable_client_and_its_exact_numbers`, `B::test_driver_accept_applies_exactly_the_recorded_consent_or_refuses`, `B::test_zero_percent_booking_takes_no_discount_and_a_consent_on_it_is_stale`, `B::test_promotions_switched_off_makes_a_consent_stale`.
- A4.4 ✅ Cancel → redemption released, hold bo‘shaydi — `B::test_repeated_accept_and_cancel_create_one_booking_and_one_money_result`; aybdor tomon bo‘yicha tiklash bron oqimida — `B::test_cancel_after_expiry_restores_by_fault_in_the_real_flow` (aybdorlik xaritasi — T4(g), tasdiq kutmoqda).
- A4.5 ✅ Capture → consumed bir marta; `C = C_net + P + H` (`promo_booking_finance`) — `B::test_synthetic_example_runs_through_the_real_flow`, `B::test_release_versus_capture_race_settles_the_money_once`.
- A4.6 ✅ Amendment: F_cash o‘zgarsa mijoz qayta tasdiqlaydi; xatoda eski kelishuv — `B::test_amendment_recomputes_terms_needs_the_clients_confirmation_and_keeps_the_old_agreement_on_failure`, `B::test_client_authored_amendment_carries_its_consent_to_the_drivers_accept` (faqat kichrayish — T4(c)).
- A4.7 ✅ Cash receipt F_cash bilan; boshqa summa faqat izoh bilan va contested oqimiga — `B::test_synthetic_example_runs_through_the_real_flow`, `B::test_a_cash_amount_other_than_f_cash_needs_a_note_and_goes_to_the_contested_path`.
- A4.8 ✅ Eski klient: yangi promo bitim yo‘q, cash buyruqlari `CLIENT_UPGRADE_REQUIRED`, chegirma saqlanadi — `B::test_consent_needs_a_capable_client_and_its_exact_numbers`, `B::test_counterparty_with_an_old_app_makes_a_consented_discount_stale`, `B::test_old_client_cannot_run_cash_commands_on_a_promo_booking_and_the_discount_stays`.
- A4.9 ✅ Flag o‘chiq → bron oqimi bugungidek — `B::test_promotions_switched_off_makes_a_consent_stale`, `B::test_plain_booking_is_unchanged_and_marked_plain` va mavjud bookings/wallet PG testlari (to‘liq izolyatsiyalangan progon).
- A4.10 ✅ Q55/Q48 va `ledger_*` testlari o‘zgarishsiz o‘tadi (to‘liq progon); mijoz DTO’sida C/H/stavka yo‘q — `B::test_synthetic_example_runs_through_the_real_flow`, `B::test_both_sides_see_the_money_terms_before_agreeing`, `C::test_client_promo_objects_have_no_commission_keys_and_driver_objects_match_the_driver_view`; mijoz event nusxalarida — `B::test_client_copies_of_booking_events_carry_no_commission_or_credit`.
- A4.11 ✅ (qisman aniqlashtirildi) Lock tartibi ADR-0023 §18 bo‘yicha; parallel accept, capture/release poygasi, event+sweep poygasi deadlock’siz — `B::test_two_parallel_accepts_cannot_spend_one_bonus`, `B::test_release_versus_capture_race_settles_the_money_once`, `B::test_event_and_sweep_together_grant_once`. `run_with_db_retry` (≤ 3) — mavjud HTTP runner, promo uchun alohida retry testi **yo‘q**.
- A4.12 ✅ Attribution ↔ haqiqiy `accept_proposal`: ikkala tartib (attribution birinchi / accept birinchi) bir-biriga qoplanuvchi tranzaksiyalarda — `B::test_attribution_races_the_real_first_accept`; mijozdan haydovchiga o‘tgan foydalanuvchi — `B::test_a_client_who_becomes_a_driver_keeps_an_open_driver_window`. Eslatma: test tartibni kechikish bilan belgilaydi (to‘liq tasodifiy bir vaqtlilik emas).
- A4.13 ✅ `PROMO_QUOTE_STALE` faqat joriy urinishni rad etadi (`scope=accept_attempt`, `action=requote`) — `B::test_zero_percent_booking_takes_no_discount_and_a_consent_on_it_is_stale`, `B::test_driver_accept_applies_exactly_the_recorded_consent_or_refuses`.
- Q120 (kech capture) — `B::test_late_capture_after_an_in_time_service_waits_and_grants_once_captured`, `C::test_late_platform_capture_does_not_disqualify_an_in_time_service`; Q122 — `B::test_post_grant_review_stops_new_spending_but_keeps_confirmed_discounts`, `B::test_autonomous_review_neither_commits_nor_waits_for_the_callers_work`, `B::test_reinstate_is_never_partial_and_an_unfulfilled_one_stays_escalated`, `B::test_processing_suspension_changes_no_booking_price_and_charges_once`.

### 5-bosqich — interfeys va admin
Dalillar: `tests/pg/promotions/test_promo_http_pg.py` (`H::`), `mobile-app/src/app/promo.test.ts` (`M::`), `mobile-app/src/app/v2/PromoScreens.test.tsx` (`R::`), `tests/test_mobile_v2_client_contract.py` (`K::`), UI skrinshotlari (sintetik demo baza, haqiqiy backend + vite, Chrome CDP; 390×844, 360×640, admin 1280×860).
- A5.1 ✅ v2 endpointlar `response_model` bilan; OpenAPI eksport + `npm run gen:api`; klient yo‘llari literal va served — `K::test_every_client_call_hits_a_real_v2_path`.
- A5.2 ✅ (lokal). ✅ mijoz: kod/nusxa, kodni qo‘lda kiritish, kampaniya shartlari (disclosure), bonus holatlari (mavjud/band/tekshiruvda/sarflangan/muddati tugagan — pul emas), taklif/counter oldidan preview va aniq rozilik, accept’da rozilik, bron bo‘yicha F/P/F_cash, cash qaydi F_cash bilan; ✅ haydovchi: kredit holati (real balansdan alohida), accept’dan oldin naqd/komissiya/kredit/qoladigan summa, bron breakdown — `H::test_consent_before_counter_driver_sees_terms_then_cash_and_capture`, `M::*`, `R::*`, skrinshotlar. ✅ haydovchi QR (qurilmada, faqat `share_url`; `R::draws the referral QR on the device...`), progress/milestone (`H::test_enrollment_over_http_then_a_real_service_qualifies` — `in_review` bajarilgan sanalmaydi; `promoT4.test.ts`), “nega chegirma yo‘q” (`H::test_stage5_the_preview_says_why...`, `test_q129_no_discount_reason_is_a_plain_category`), eskirgan tasdiqni yangilash (`H::test_q126_*`), haydovchi amendment tasdig‘i (`test_q125_*`, skrinshot 390_47–49). Skrinshotlar (sintetik demo baza, 390/360/1280): progress, QR, milestone, sabab, qayta tasdiq, amendment, admin juftlik va review’lar.
- A5.3 ✅ Admin API + UI: kampaniya/versiya/holat, ishlovni to‘xtatish, byudjet (ikki xodim), review (operator izoh, admin qaror), reconciliation; har qaror haqiqiy MFA step-up bilan; grant tugmasi yo‘q — `H::test_budget_and_review_decisions_need_a_real_step_up`, `H::test_a_large_budget_change_needs_a_second_different_person`, `H::test_operator_notes_a_review_and_only_an_admin_with_a_factor_decides`. Audit — mavjud servis `_audit` yozuvlari.
- A5.4 ⚠️ lokal: `landing/r.html` + rewrite; topshiriq tayyor: `INFRA_HANDOFF.md` (domen, DNS, TLS, rewrite, statik fayllar, tekshirish buyruqlari, rollback), `APP_LINKS_HANDOFF.md` (applicationId’ni tarqatiladigan build’dan, release imzo SHA-256, intent filter, assetlinks, qurilmada tekshiruv); **haqiqiy muhitda tekshirilmagan** — havola ishlayapti deb yozilmaydi. `android-app` tegilmagan.
- A5.5 ✅ HTTP himoyasi: actor sessiyadan, soxta user/role 422, begona obyekt 404, capability serverda — `H::test_actor_comes_from_the_session_and_foreign_objects_answer_404`; rate-limit — `H::test_code_check_is_rate_limited_and_says_nothing_about_owners`, `H::test_attribution_attempts_are_limited_per_user`; flag o‘chiq → yangi majburiyat yo‘q — `H::test_with_promotions_off_no_new_promo_obligation_can_be_made`; takroriy bosish/timeout — `H::test_retry_with_the_same_key_returns_the_first_booking`, `M::retries`; eskirgan rozilik/eski klient — `H::test_stale_or_hidden_consent_is_refused_and_nothing_is_sent`; HTTP enrollment → haqiqiy xizmat → grant — `H::test_enrollment_over_http_then_a_real_service_qualifies`.

### 6-bosqich — simulyator va yakuniy QA
**Simulyatsiya uchun kiritiladigan parametrlar (hammasi hozir sintetik yoki belgilanmagan — hech biri tasdiqlanmagan):**
| Parametr | Qayerda | Hozir |
|---|---|---|
| Mukofot summalari (taklif qiluvchi / taklif qilingan, har instrument) | kampaniya versiyasi | faqat sintetik testlarda |
| Kampaniya budjeti (ajratish) | `promo_budget_requests` | sintetik |
| O: `variable_cost_fixed_minor`, `variable_cost_bps` | kampaniya versiyasi | belgilanmagan (sintetik 1 000 so‘m / 0 bps) |
| M: `min_margin_minor` | kampaniya versiyasi | belgilanmagan (sintetik 1 000 so‘m) |
| `max_discount_share_bps`, `max_discount_per_booking_minor` | kampaniya versiyasi | belgilanmagan (sintetik 50 %, 15 000 so‘m) |
| `passenger_bonus_max_per_booking_minor`, `driver_credit_max_per_booking_minor` | kampaniya versiyasi | belgilanmagan |
| Juftliklar va `cost_basis` (`shared`/`additive`) — qaysi kampaniyalar birga (Q123) | `promo_campaign_combinations` | yo‘q |
| Qualification muddati, bonus amal muddati, restoration grace | kampaniya versiyasi | sintetik (30 / 60 / 7 kun) |
| Review SLA | kampaniya versiyasi | sintetik (72 soat) |
| Driver milestone bosqichlari, `min_distinct_clients` | kampaniya versiyasi | sintetik (5, 10 / 3) |
| `enrollment_limit` | kampaniya versiyasi | sintetik |
| Komissiya stavkasi (C manbai) koridor bo‘yicha | commission policy | sintetik 10 % |
| O‘rtacha F (yo‘lovchi / pochta), bron chastotasi, bekor/refund/nizo ulushi, redemption darajasi | simulyator kiritmasi | yo‘q — ma’lumot kerak |
| Rate-limit: kod tekshiruvi IP/daqiqa, attribution user/soat | `config.py` | taklif 30 / 5 — tasdiqlanmagan |
| Split-shipment oynasi, “mustaqil guruhlar” chegarasi | contract / `RISK_RULESET_V1` | sintetik 30 daqiqa / 2 |
| HMAC saqlash muddati (Q108) | `APPROVED_RETENTION` | tasdiqlanmagan |
- A6.1 ✅ Deterministik simulyator (sof modul + CLI). Mezon “dry-run endpoint/CLI” — ikkisidan biri; **CLI yetarli deb qabul qilindi, HTTP dry-run keyinga qoldirildi** (kerak bo‘lsa: faqat sof simulyator, DB’ga yozmaydi, kiritma va vaqt chegarasi bilan): maksimal majburiyat (stress marja), 100% redemption (`stress_full_redemption`, sezgirlik qatori), past narx (`low_fares`), P + H birga, refund/fraud/kechikish (`adverse`, `ops_delay_shortage`), budjet tugashi (`zero_budget`, `budget_cut`), sarflash uchun bronlar soni — `py scripts/promo_simulate.py --check`, `tests/contracts/test_promo_simulation.py`, `tests/pg/promotions/test_promo_simulation_pg.py` (simulyator shartlari = haqiqiy accept, budjet bosqichlari = `promo_budgets`).
- A6.2 ✅ Cohort langarlari aniq (enrollment → qualification; aktivlashish → D30/D60 qaytish va D60 marja; grant/`available_from` → bonus sarfi); yetilmagan kuzatuv alohida, yetilgani minimaldan kam bo‘lsa `hali_baholab_bolmaydi` (0 emas); har ko‘rsatkichda hisob kuni, maxraj, yetilgan/yetilmagan soni. Pochta: lot / egalar / qiymat ulushi alohida va ishlatilmaslik sabablari. Budjet: limit, majburiyat, ta’minlangan, kamomad. Zararsizlik simulyatsiya to‘rida, stresslar alohida va birga, 20 seed. Admin hisobot `GET /api/v2/admin/promo/report` (K10) — `tests/pg/promotions/test_promo_report_pg.py` (4), `tests/contracts/test_promo_simulation.py` (17). ADR-0023 §20.1.
- A6.3 ✅ (lokal) QA #1–#24 — [QA_REPORT.md](QA_REPORT.md): 24 band “o‘tdi” (server, lokal PG), cheklovlari bilan; bo‘shliqlar yangi testlar bilan yopildi (`tests/pg/promotions/test_promo_qa_pg.py`: #2, #4, #12, #19, #20, #24); promo retry testi va uyqusiz poyga sinxronlashuvi. Go-live — [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) (G1–G20; o‘lchash dizayni va biznes to‘xtatish chegaralari tasdiqlanmagan — Q134, Q135; Q127 qaror jadvali §E). G14 (Q132, 0090) — `tests/pg/promotions/test_promo_budget_floor_pg.py`. Qurilma, App Links, DNS/TLS, deploy — **yopilmagan**.

## 6. Hali ochiq qarorlar

| Mavzu | Kim hal qiladi | Qachon kerak |
|---|---|---|
| HMAC saqlash muddati, huquqiy asos, maxfiylik siyosati bandi (Q108) | Foydalanuvchi + huquqiy tekshiruv | Production yoqishdan oldin (2-bosqich kodi muddatni konfiguratsiyadan oladi) |
| Mukofot summalari, budjet, O, M, share, per-booking cap’lar | Foydalanuvchi, 6-bosqich simulyatsiyasidan keyin | Kampaniya aktivlashtirishdan oldin |
| Review SLA, restoration grace, bonus amal muddati, qualification muddati — production qiymatlari (hozir sintetik) | Foydalanuvchi | Aktivlashtirishdan oldin |
| Driver milestone bosqichlari va `min_distinct_clients` — production qiymatlari | Foydalanuvchi | Driver→driver kampaniyasidan oldin |
| `elchigo.uz/r/<kod>`: domen egaligi, DNS, sertifikat, deploy joyi (texnik tekshiruv) | Foydalanuvchi + texnik tekshiruv | 5-bosqich |
| Kontekst signallari uchun “mustaqil guruhlar” chegarasi (`RISK_RULESET_V1` da 2) — production qiymati | Foydalanuvchi | 3-bosqich |

**Hal qilingan (1-bosqich):** risk oynasi 48 soat (Q110, qayta ochilmaydi); ikki xodim chegarasi — mavjud `TWO_PERSON_APPROVAL_THRESHOLD_MINOR` (Q114); pochta mustaqil jo‘natmasi — alohida bron + o‘z dalillari, alohida trip shart emas (Q113).
