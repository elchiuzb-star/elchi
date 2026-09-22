# ADR-0008: Feature flag modeli

**Holat:** Accepted (Q1, Q5, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §9.2, §17.7, §18.3, §20.1, §20.3 • **AC:** AC38 • **Qarorlar:** K7, Q1, Q4, Q5
**Kontrakt:** `FeatureFlagKey`, `FlagScopeType`, `PRODUCTION_FLAG_DEFAULTS`, `FLAGS_LOCKED_IN_PRODUCTION`, `FLAGS_REQUIRING_APPROVAL_REFERENCE` (`enums.py`), `money.balance_check_required`

## Kontekst
Joriy tizimda flag yo‘q; faqat `system_settings(key, value)`. Spec §20.3 country/region/corridor/cohort flag’larini audit bilan, ochiq bron shartini o‘zgartirmasdan talab qiladi.

## Qaror
1. **Jadvallar (A2, `0033`):** `feature_flag_values(flag_key, scope_type, scope_ref, enabled, approval_reference, reason, version, updated_by)` `UNIQUE(flag_key, scope_type, scope_ref)`; `feature_flag_changes` append-only.
2. **Baholash:** `cohort > corridor > region > country`; qator yo‘q bo‘lsa production’da `PRODUCTION_FLAG_DEFAULTS`, boshqa muhitda seed. **Q26:** bir scope darajasida bir nechta mos qator bo‘lib, qiymatlari ziddiyatli bo‘lsa (masalan ikki cohort) natija — **o‘chiq** (xavfsiz default), ogohlantirish log’i bilan. **Production aniqlash:** `platform.service.is_production(db)` (DB markeri + env), faqat env satri emas (wave 1.5). **A2 implementatsiyasi:** `is_flag_enabled`, `snapshot_flags`, `set_flag_value`, `production_flag_violations` endi `environment=` parametrini qabul qilmaydi — production holati DB markeri va env’dan olinadi (chaqiruvchi uni soxtalashtira olmaydi). DB guard’lari (0043) fail-closed: marker yo‘q/noma’lum → production. Production guard’lari (A2, 0043): production markerida passenger/card flag’ini `approval_reference`siz yoqish DB’da ham rad.
3. **Q5 — production defaults:** `passenger_enabled`, `parcel_enabled` (v2), `driver_listing_enabled`, `tracking_enabled`, `corridor_matching_enabled`, `card_payments_enabled` — **o‘chiq**, koridor bo‘yicha yoqiladi. `passenger_enabled` (va `card_payments_enabled`) ni production’da yoqish: `super_admin` + `approval_reference` (`400 APPROVAL_REFERENCE_REQUIRED`). Boshqa flag’lar: `ops.feature_flag_manage` (admin+).
4. **Q1 — `wallet_required`:** production’da doim `true` (`FLAGS_LOCKED_IN_PRODUCTION`); boshqa qiymat yozish servisda `409 FLAG_LOCKED_IN_ENVIRONMENT` va DB’da muhit markeri + trigger bilan rad (N1); buzilgan holat readiness’da `production_invariants: fail` + alert (503 emas), pul buyruqlari `503 PRODUCTION_INVARIANTS_FAILED`. Boshqa muhitda `false` **faqat** balans yetarliligi tekshiruvini o‘tkazib yuboradi: fee real policy’dan hisoblanadi, snapshot va hold qilinadi (ADR-0009). Komissiyani nolga tushirmaydi.
5. **Qo‘llash:** publish, proposal submit, accept, yangi tracking sessiyasi (yangi trip) flag’ni tekshiradi. Mavjud bron keyingi amallari flag’dan mustaqil (AC38). Accept paytidagi flag qiymatlari `bookings.terms_snapshot.flags`ga yoziladi.
6. **Legacy kill-switch yo‘q:** v1 cutover doirada emas (Q4, ADR-0006).
7. **Audit:** `feature_flag_changes` + `audit_logs`.
8. **Klient:** `GET /api/v2/feature-flags/effective?corridor_id=`; server baribir tekshiradi.

## Muqobillar
- Env o‘zgaruvchilari (scope/audit yo‘q), `system_settings` JSON (constraint yo‘q), tashqi flag servisi (K3, dependency).

## Oqibatlar
- Rollout UI — A13; yadro — A2 (wave 1).

## Q72 qarori (15.09.2026, wave 2.1)
- v2 xizmat flag’lari (`enums.V2_SERVICE_FLAGS`) **faqat ilova/admin API orqali yoqiladi** (F3). DB guard (A2, `20260915_0057`): flag’ni yoqish (INSERT `enabled=true` yoki `false → true`) tranzaksiyada `SET LOCAL elchi.flag_change_source = 'admin_api'` (`enums.FLAG_CHANGE_SOURCE_SETTING` / `FLAG_CHANGE_SOURCE_ADMIN_API`) bo‘lmasa rad (`CONSTRAINT = 'flag_enable_source_refused'`). O‘chirish har qanday manbadan mumkin (xavfsiz yo‘nalish). Barcha muhitlarda amal qiladi; Q56 gate trigger’i (0053) o‘zgarmaydi.
- **Cheklov (rostgo‘ylik):** marker — tranzaksiya sozlamasi; app roli huquqlari bilan psql’ga kirgan odam uni ham qo‘ya oladi, owner/superuser trigger’ni o‘chira oladi. Guard tasodifiy psql/migratsiya yoqishini to‘xtatadi, lekin DB huquqlari to‘liq bo‘lgan niyatli odamni emas; bunga qarshi — Q36 rollari, audit (`feature_flag_changes`) va monitoring.
- Bu band 2-qarordagi (baholash) va 3-qarordagi (kim yoqadi) qoidalarni o‘zgartirmaydi, faqat yoqish kanalini cheklaydi.
