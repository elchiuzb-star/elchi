# ADR-0021: Staff akkauntlari uchun MFA rejasi

**Holat:** **Accepted** (foydalanuvchi qarori, 17.09.2026; wave 8 da implementatsiya qilindi) • **Sana:** 16.09.2026 • **Muallif:** A12 rejasi, A0a tahriri
**Spec:** §17.5 (staff uchun MFA rejasini P0 gate’da ko‘rib chiqish), §17.6, §19.2 • **Bog‘liq:** ADR-0007 (rollar, capability), ADR-0018 (derived keys), Q3 (staff va marketplace akkauntlari alohida), Q17 (finance roli)

## Kontekst — tahdid modeli
Staff akkaunti egallanishi (parol yoki token oqishi, phishing) quyidagilarga yo‘l ochadi: pul buyruqlari (top-up tasdiqlash, adjustment, `finalize_fee`), eligibility bloklari, kontakt ma’lumotini ko‘rish, v2 xizmat flag’larini yoqish. Eng yuqori xavfli rollar — `finance` va `super_admin`. Hozir kirish — telefon + 4 xonali OTP (Q8) va JWT. Wave 3 da kod yoki jadval yo‘q — faqat reja.

## Qaror (tasdiqlangan)
1. **Kimga:** effektiv rollarida (`users.role` + faol `user_roles`) staff roli bor har akkaunt. Marketplace akkauntlariga majburiy emas.
2. **Omillar (kutubxona tanlovisiz — alohida dependency qarori, AGENTS §2):**
   - TOTP (RFC 6238) — sir bazada faqat `crypto.derive_subkey(secret_key, purpose)` bilan shifrlangan holda;
   - WebAuthn/FIDO2 — `super_admin` va `finance` uchun tavsiya etiladi;
   - SMS OTP staff uchun **rad etilgan** (SIM almashtirish xavfi).
3. **Ro‘yxatdan o‘tish:** birinchi kirishda majburiy; omil **boshqa `super_admin` tasdig‘i** bilan faollashadi. 10 ta bir martalik tiklash kodi, bazada faqat hash.
4. **Omil yo‘qolganda tiklash:** boshqa `super_admin` + audit qatori + foydalanuvchining barcha sessiyalari bekor qilinadi (o‘zi o‘ziga reset yo‘q, Q17 ikki xodim ruhi).
5. **Staff sessiyasi:** access token ≤ 15 daqiqa; refresh ≤ 8 soat va MFA talab qiladi; pul va kontakt ko‘rish buyruqlari oldidan **5 daqiqalik step-up** (masalan W6/W7, W8/W16/W17, W13/W15/W19, F3 flag yoqish, I5, B13 `cancel`/`finalize_fee`, S8 moliyaviy qaror, telefon ko‘rsatadigan staff ko‘rinishlari).
6. **Rejalashtirilgan jadvallar:** `staff_mfa_factors`, `staff_mfa_recovery_codes` (hash), `staff_mfa_events` (append-only: enrollment, tasdiq, muvaffaqiyatsiz urinish, reset, step-up — sir qiymatlarisiz). Migratsiya raqami qabul qilingandan keyin reyestrga kiritiladi.
7. **Rollout gate:** (1) audit-only rejim (omil so‘raladi va jurnalga yoziladi, bloklamaydi) → (2) `finance` va `super_admin` uchun majburiy → (3) barcha staff uchun majburiy. Production launch gate’iga qo‘shiladi (Q8; COVERAGE §6).

## Oqibatlar
- v1 web admin endpointlari ham shu staff auth qatlamidan o‘tishi kerak — U5 (v1 staff effektiv rollari) qarori bilan bog‘liq.
- Qisqa access token va step-up admin UI (A9) oqimlarini o‘zgartiradi.
- Ikkinchi `super_admin` talabi pilotda kamida ikkita faol `super_admin` bo‘lishini talab qiladi.

## Ochiq savollar (foydalanuvchi)
- TOTP/WebAuthn kutubxonasi yoki o‘z implementatsiyasi; WebAuthn qachon majburiy.
- Step-up ro‘yxati va 5 daqiqalik oyna; operatorlar uchun pilotda majburiymi (rollout 3-bosqich muddati).
- Faqat bitta `super_admin` bo‘lgan davrda enrollment tasdig‘i qanday bajariladi.


## Wave 8 implementatsiyasi (17.09.2026)

Tasdiqlangan qaror bo‘yicha yozilgan kod (`tests/pg/identity/test_staff_mfa_pg.py` — 13 test):

| Band | Qanday bajarildi |
|---|---|
| Kutubxona | `pyotp==2.10.0` (MIT, runtime bog‘liqliksiz — o‘rnatilgandan keyin tekshirildi) `requirements.txt` da pin qilindi |
| Jadvallar | `20260917_0074`: `staff_mfa_factors`, `staff_mfa_recovery_codes`, `staff_mfa_events` |
| Sir | TOTP siri **shifrlangan** (`app/core/secret_box.py`, AES-256-GCM, kalit `derive_subkey(secret_key, "staff-mfa")`); AAD — omilning `public_id` si, shuning uchun shifrmatnni boshqa qatorga ko‘chirish ish bermaydi |
| Ikki kishilik nazorat | `activate()` da `actor <> subject`, **va** DB CHECK `ck_staff_mfa_factors_two_person` — xom SQL bilan ham o‘zini tasdiqlab bo‘lmaydi (test bor) |
| Tiklash | 10 ta bir martalik kod, bazada faqat SHA-256. Kod **faqat** qayta ro‘yxatdan o‘tish huquqini qaytaradi: step-up bermaydi, moliyaviy ikkinchi tasdiqlovchi bo‘lmaydi, va ishlatilganda faol omil bekor qilinadi |
| Replay | Ishlatilgan TOTP qadami `last_counter` da saqlanadi — bir xil kod o‘z 30 soniyasi ichida ham ikkinchi marta o‘tmaydi |
| Audit | `staff_mfa_events` append-only (trigger UPDATE/DELETE ni rad etadi); hech bir qatorda sir, kod yoki tiklash kodi yo‘q (test bor) |
| Step-up | `STEP_UP_CAPABILITIES` (7 ta pul/flag/siyosat capability’si), 5 daqiqalik oyna; `wallet/api._require`, `geo/api.require_capability` va `identity.require_capability(session=…)` orqali majburlanadi |
| Sessiya | Staff access token **15 daqiqa** (`staff_access_token_expire_minutes`); marketplace tokenlari 60 daqiqada qoldi — muzlatilgan Android klientining refresh ritmi o‘zgarmasin |

**Rollout (muhim aniqlashtirish):** enforcement o‘zi yoqilmaydi. `settings.staff_mfa_mode` uch bosqich:
`audit_only` (**standart**) → `enforce_privileged` → `enforce_all`. Ikkinchi `super_admin` paydo bo‘lishi
enforcement’ni yoqmaydi — aks holda xodim qo‘shilgan kuni moliya buyruqlari ogohlantirishsiz to‘xtar edi.
Bundan qat’i nazar, faol `super_admin` bitta bo‘lsa enforcement **hech qachon** qo‘llanmaydi (yagona
operatorni qulflab qo‘yish MFA olib tashlaydigan xavfdan yomonroq).

**Hali ochiq (wave 8 holati):** WebAuthn (2-bosqich, alohida qaror); staff login oqimiga MFA bosqichini ulash
va admin UI (A8/A9); production’da kamida ikkita `super_admin` — go-live checklist bandi.

## Wave 9 implementatsiyasi (17.09.2026) — API va admin UI

Wave 8 da servis qatlami va majburlash bor edi, lekin **hech bir endpoint yo‘q edi**: xodim omil ulay ham,
uni isbotlay ham olmasdi, ya’ni `enforce_privileged` ga o‘tish amalda akkauntlarni qulflash degani bo‘lar edi.
Wave 9 shu bo‘shliqni yopadi (kontrakt §13a, I6–I11):

| Band | Qanday bajarildi |
|---|---|
| Endpointlar | `GET /me/mfa`, `POST /me/mfa/enroll`, `POST /me/mfa/step-up`, `POST /me/mfa/recovery`, `POST /admin/staff/{user_id}/mfa/activate`, `POST /admin/staff/{user_id}/mfa/reset` |
| Q3 | MFA yuzasi faqat staff akkauntida: marketplace akkaunti `403 FORBIDDEN` (`details.reason="staff_only"`) |
| Reset | Yangi `mfa.reset()` — **boshqa** super_admin (`staff.mfa_approve`) omilni va ishlatilmagan tiklash kodlarini bekor qiladi; `factor_reset` audit qatori (DB CHECK `actor <> subject`). Hech qanday huquq bermaydi |
| Kodni topishga urinish | 15 daqiqada 5 xato kod → `429 RATE_LIMITED` (`reason="too_many_failed_codes"`), barcha kod qabul qiladigan yo‘llarda (login/step-up, faollashtirish, tiklash). `audit_only` rejimida yozilgan “omil yo‘q” qatorlari **sanalmaydi** — aks holda xodim audit rejimidan chiqolmay qolardi |
| Savepoint | Xato kod domen 4xx bo‘lgani uchun handler yozuvlari savepoint bilan qaytariladi (ADR-0005/BR D8); shuning uchun urinish `run_command(after_command=…)` ichida qayta yoziladi — aks holda hisoblagich hech qachon o‘smas va taxmin qilish bepul bo‘lar edi |
| Ikkinchi qurilma | `mfa.state()` endi **faol** omilni qidiradi (eng oxirgi qatorni emas): yangi telefonga ulanish eski omilni o‘chirmaydi va pul buyruqlarini to‘xtatmaydi |
| Admin UI | `mobile-app/src/app/AdminSecurityPanel.tsx` (“Xavfsizlik (MFA)” bo‘limi): holat, ulash (sir va tiklash kodlari **bir marta**), step-up, tiklash kodi, va `staff.mfa_approve` bo‘lsa boshqa xodimni faollashtirish/bekor qilish. Ekran “himoyalangan” demaydi — `audit_only` yoki bitta super_admin sababini ochiq yozadi |

**Hali ochiq:** WebAuthn; login ekranining o‘zida majburiy MFA bosqichi (hozir step-up buyruq vaqtida
so‘raladi); production’da ≥ 2 `super_admin` va `staff_mfa_mode=enforce_privileged` — go-live checklist.
