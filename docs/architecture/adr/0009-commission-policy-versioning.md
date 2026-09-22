# ADR-0009: Komissiya policy versiyalash va admin boshqaruvi

**Holat:** Accepted (Q1, Q2, Q16, Q17, Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §9.2, §9.4, §9.5, §14.2, §24 • **AC:** AC19, AC20, AC25, AC43 • **Qarorlar:** K5, Q1, Q2 • **BR:** D3, D4, D10, D13
**Kontrakt:** `money.validate_policy_terms`, `initial_commission_status`, `balance_check_required`, `validate_reversal`, `hold_adjustment_minor`; `EventType.COMMISSION_POLICY_CREATED`

## Kontekst
v1: `system_settings.driver_commission_rate` (default 0.15, `app/services/system_settings_service.py:10-11`), darhol ta’sir qiladi, PATCH `admin, super_admin` (`app/api/v1/admin_settings.py:24`). Klientlarda qattiq 10%/15%.

## Qaror
1. **`commission_policies` (A3, `0036`; FK `service_corridors` sababli geo katalogdan keyin)**, o‘zgarmas qatorlar: `kind`, `scope_corridor_id?`, `scope_service_type?`, `scope_key`, `fee_bps`, `effective_from`, `effective_to?`, `campaign_name?`, `reason`, `created_by`, `version`.
   - **Q1:** `standard` → `fee_bps` 1..10000 (0 taqiq), muddatsiz bo‘lishi mumkin; `campaign` → `effective_to` majburiy (muddatli), `fee_bps` 0..10000. DB CHECK + `validate_policy_terms`.
   - `EXCLUDE USING gist (scope_key =, kind =, tstzrange &&)` → `COMMISSION_POLICY_OVERLAP`; `effective_from < now` → `COMMISSION_POLICY_RETROACTIVE`; `effective_to` bir marta, kelajakka.
2. **Resolve:** faol `campaign` → aks holda `standard`; har kind ichida corridor+service > corridor > service > global. Global standard har doim bor.
3. **Fee quote (AC43, D13):** proposal versiyasida `fee_policy_id`, `fee_bps`, `commission_minor`; quote muddati = versiya `expires_at`. Versiya muddati o‘tsa accept `409 PROPOSAL_EXPIRED` (alohida quote xatosi yo‘q). Counter yangi quote oladi.
4. **Bron snapshot va holat (D3):** `bookings.fee_policy_id, fee_bps, commission_minor, commission_status`. `commission_status = exempt` **faqat** `fee_bps = 0` snapshot’idan (faol 0 bps kampaniya); DB CHECK `(fee_bps = 0) = (commission_status = 'exempt')`. `wallet_required` hech qachon exempt yoki 0 fee bermaydi.
5. **`wallet_required` (Q1):** production’da `true` (ADR-0008). Non-prod’da `false` → accept balans tekshiruvini o‘tkazib yuboradi, lekin hold real summada yaratiladi; `wallet_accounts.posted − held ≥ 0` CHECK’ini buzmaslik uchun non-prod seed wallet’larda `test_overdraft_allowed = true` (CHECK: `posted − held ≥ 0 OR test_overdraft_allowed`). **Production invariantlari DB darajasida (BR N1):** A3 muhit markerini (masalan bir qatorli `platform_environment` jadvali, deploy yozadi) va trigger’larni loyihalaydi — production markerida `wallet_accounts.test_overdraft_allowed = true` va `wallet_required=false` flag qatori DB tomonidan rad etiladi. Readiness bunday ma’lumot buzilishi uchun 503 **qaytarmaydi**: `checks.production_invariants: fail` + alert; pul buyruqlari (hold, capture, release, reversal, top-up, adjustment) invariant tekshiruvi o‘tmaguncha `503 PRODUCTION_INVARIANTS_FAILED` bilan rad etiladi. Reconciliation ham xatoni qayd etadi.
6. **Amendment (D10):** yangi commission = `commission_minor(new_total, booking.fee_bps)` (snapshot bps saqlanadi); bitta mavjud hold `adjust_hold` bilan o‘zgaradi (`UNIQUE(booking_id, charge_kind)`), musbat delta balans tekshiruvi bilan; event `wallet.hold.adjusted`.
7. **Reversal (D4):** bir capture uchun bir nechta qisman reversal; har biri alohida ledger tranzaksiyasi `reversal_of → capture tx` (unique emas); wallet lock ostida `SUM(reversals) ≤ captured` (`REVERSAL_EXCEEDS_CAPTURED`).
8. **Q2 — boshqaruv:** yaratish va tugatish faqat `super_admin` (`finance.commission_policy_manage`); `admin`, `operator` — faqat o‘qish (`finance.commission_policy_view`). Admin paneli (A9, mobile-app) shu qoidada.
9. **v1 adapteri (A3):** `GET /api/v1/admin/settings` — o‘zgarishsiz (operator/admin/super_admin), global standard’dan. `PATCH /api/v1/admin/settings/driver-commission` — **faqat super_admin** (admin → v1 `403 FORBIDDEN`, tasdiqlangan xulq o‘zgarishi); yangi global standard versiya `effective_from=now`, oldingisi `effective_to=now`; `0` → v1 `400 VALIDATION_ERROR`. Javob shakli o‘zgarmaydi. Legacy buyurtma snapshot’lari o‘zgarmaydi.
10. **Seed:** global standard joriy `system_settings` qiymatidan (`legacy_rate_to_bps`, aniq).
11. **Audit va event:** `audit_logs` + `commission.policy.created` / `commission.policy.ended`.
12. **Klient:** stavka hard-code emas; `fee_quote` va `GET /api/v2/commission/quote`.

## Hal qilingan bandlar
- **Q19:** faol kampaniya standard’dan ustun, keyin eng aniq scope (2-band tartibi).
- **Q16:** komissiya holati va fee maydonlari mijozga API’da ham, event’larda ham ko‘rsatilmaydi (`events.payload_for_audience`, N2).
- **Q19:** amendment bron fee snapshot’ini (bps) saqlaydi (6-band).
- **Q17:** `finalize_fee` — `finance.fee_finalize` (finance roli, ulanguncha super_admin); katta tuzatish/reversal ikkinchi, boshqa xodim tasdig‘i bilan (`finance.adjustment_approve`).

## Wave 1.5 qarorlari (14.09.2026)
- **Q28 — seed stavka go-live gate:** qo‘llaniladigan yagona global standard policy migratsiya seed’i bo‘lsa (`created_by IS NULL`), production’da v2 quote va hold `503 COMMISSION_POLICY_UNCONFIRMED` bilan bloklanadi — super_admin stavkani tasdiqlaguncha (yangi versiya yaratish) yoki yangisini yaratguncha. Non-prod’da ogohlantirish. Go-live checklist bandi (A10a runbook).
- **Q29:** 0036 noto‘g‘ri/aniq bo‘lmagan legacy stavkada migratsiyani qattiq yiqitadi (o‘zgarmaydi); A10a deploy oldi tekshiruv skripti `system_settings.driver_commission_rate`ni `legacy_rate_to_bps` bilan oldindan tekshiradi.
- **Q30:** chegaradan pastga bo‘lingan kichik tuzatishlar (bir wallet, qisqa oynada bir nechta adjustment yig‘indisi chegaradan oshsa) moliya hisobotida belgilanadi; pilotda qat’iy kunlik limit yo‘q.
- **Q31:** o‘chirilgan haydovchining qolgan prepaid balansi — dalilli finance **debit adjustment** (ikki xodim qoidasi amal qiladi) orqali qaytariladi; akkaunt o‘chirish/moliya runbook’ida (A10a/A3). v1 o‘chirish balans bor paytda rad etiladi (N4), shuning uchun qaytarish o‘chirishdan oldin bajariladi.
- **W17/W18:** adjustment rad etish va ro‘yxat endpointlari (API_V2_CONTRACT §9).

## Wave 2.1 qarorlari (15.09.2026)
- **Q60 — snapshot muzlatish:** bron snapshot’ida faqat `quantity`, `unit_price_minor`, `total_minor`, `commission_minor` va o‘rin/resurs ustunlari o‘zgaradi — **faqat shu tranzaksiyada qabul qilingan amendment** bilan (D10 `adjust_hold`); `fee_policy_id`, `fee_bps` va qolgan snapshot ustunlari DB’da muzlatiladi (A4, `20260915_0056`, `CONSTRAINT = 'booking_snapshot_frozen'` → `409 INTEGRITY_CONFLICT`). 4- va 6-bandlarni kuchaytiradi.
- **Q66 — nizo moduli yo‘q:** A12 `set_blocking_dispute_probe` ro‘yxatdan o‘tmagan bo‘lsa xizmat **yakunlanadi** (`503` emas), komissiya `held` qoladi (capture yo‘q), bron `finance_review` navbatiga tushadi (`enums.AdminBookingQueue.FINANCE_REVIEW`, sabab `CommissionReviewReason.DISPUTE_MODULE_UNAVAILABLE`), staff event `commission.finance_review_required`. Finance `finalize_fee` (`finance.fee_finalize`) bilan capture/release qiladi. Hold muddati o‘tishi baribir avtomatik capture/release qilmaydi (48 soat eskalatsiya saqlanadi).
- **Q69/Q70/Q71 (A3, `20260915_0055`):** top-up va adjustment’ni faqat faol `finance`/`super_admin` xodimi tasdiqlaydi — DB’da majburiy va Q48 gate tekshiruvi (`approver_guard_enforced`); gate o‘tmaguncha production’da top-up tasdiqlash va kredit adjustment’lar ham rad (`503 PRODUCTION_INVARIANTS_FAILED`); gate app roli hech bir DB ob’ektining egasi emasligini tekshiradi (`app_role_owns_no_objects`).

## Muqobillar
`system_settings`da qolish; accept paytidagi policy (AC43 ga zid); policy qatorini UPDATE qilish.

## Oqibatlar
- `btree_gist` (`0030`). Test-overdraft ustuni production invariant tekshiruvini talab qiladi (A3 + A10a).
