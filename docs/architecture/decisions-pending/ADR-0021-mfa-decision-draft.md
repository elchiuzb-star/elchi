# ADR-0021 (staff MFA) — qaror loyihasi

> ## ✅ QAROR QABUL QILINDI — 17.09.2026: `pyotp==2.10.0` + “production’da ≥ 2 super_admin”
>
> [ADR-0021](../adr/0021-staff-mfa-plan.md) endi **Accepted** va wave 8 da implementatsiya qilindi
> (`app/modules/identity/mfa.py`, migratsiya `20260917_0074`, 13 test).
> Bitta aniqlashtirish bilan: enforcement **o‘zi yoqilmaydi** — `settings.staff_mfa_mode`
> (`audit_only` standart → `enforce_privileged` → `enforce_all`). Tafsilot ADR-0021 oxiridagi bo‘limda.


**Holat:** ADR-0021 hamon **Proposed**. Bu hujjat uni Accepted qilmaydi; qaror uchun aniq savollar, tekshirilgan
faktlar va implementatsiya rejasini beradi. • **Tayyorladi:** wave 7 agenti • **Sana:** 17.09.2026
**Spec:** §17.5, §17.6, §19.2 • **Bog‘liq:** ADR-0007, ADR-0018, Q3, Q8, Q17, Q49, U5/Q80

## 1. Hozirgi staff autentifikatsiyasi (tekshirilgan)

| Band | Holat |
|---|---|
| Kirish | `POST /api/v1/auth/staff-login` — **username + parol** (bcrypt), OTP emas ([auth.py](../../../app/api/v1/auth.py)) |
| Token | JWT HS256, access **60 daqiqa**, refresh sessiyasi `refresh_sessions` da (`jti`, `token_hash`, `is_revoked`) |
| Sessiya bog‘lash | Wave 6 dan access token `sid` claim bilan login sessiyasiga bog‘langan; v2 va tracking WS bekor qilingan sessiyani darhol rad etadi |
| Rollar | `users.role` + faol `user_roles` (effektiv rollar, Q80 doirasi `admin_drivers.py`) |
| Ikki kishilik tasdiq | Pulda allaqachon bor: katta adjustment/top-up ikkinchi **boshqa** xodim tasdig‘ini talab qiladi (Q17/Q49) |
| MFA | **Yo‘q** — jadval ham, kod ham yo‘q |

## 2. Kutubxona (tekshirilgan, hali qo‘shilmagan)

| Nomzod | Versiya | Litsenziya | Python | Runtime bog‘liqlik | Izoh |
|---|---|---|---|---|---|
| [`pyotp`](https://pypi.org/project/pyotp/) | **2.10.0** (14.06.2026) | MIT | ≥ 3.8 | **Yo‘q** | RFC 4226/6238; TOTP uchun yetarli |
| [`py_webauthn`](https://github.com/duo-labs/py_webauthn) | (sahifadan olinmadi) | BSD-3-Clause | ≥ 3.10 | `cryptography`, `cbor2`, `asn1crypto` (pyproject’dan tasdiqlanishi kerak) | WebAuthn uchun; 2-bosqichda |

Repoda hozircha ikkalasi ham yo‘q (`requirements.txt` da 10 ta paket). AGENTS §2: yangi dependency faqat qaror
bilan va **pin** qilingan holda kiritiladi.

**Muqobil:** TOTP’ni o‘z kodimizda yozish (HMAC-SHA1 + stdlib `hmac`/`base64` ≈ 40 satr). Yangi dependency
bermaydi, lekin sinovdan o‘tgan kutubxona o‘rniga o‘z implementatsiyamizni saqlashimiz kerak bo‘ladi.

## 3. Taklif qilinayotgan qaror (tasdiq kerak)

1. **1-bosqich: faqat TOTP** (`pyotp==2.10.0` pin bilan). WebAuthn — 2-bosqich, alohida qaror.
2. **Kimga:** effektiv rollarida `super_admin` yoki `finance` bo‘lgan har akkaunt — majburiy. `admin`/`operator`
   uchun 3-bosqichda (rollout).
3. **Ro‘yxatdan o‘tish:** birinchi kirishda majburiy; sir `crypto.derive_subkey(secret_key, "staff_mfa")` bilan
   shifrlanadi, bazada ochiq saqlanmaydi. Faollashtirish **boshqa** `super_admin` tasdig‘i bilan (Q17 ruhi).
4. **Tiklash kodlari:** 10 ta bir martalik kod, bazada faqat hash (ADR-0018 `crypto.new_secret_token`).
   **Tiklash kodi MFA’ni chetlab o‘tmaydi:** u faqat TOTP omilini qayta ro‘yxatdan o‘tkazish uchun ishlatiladi va
   moliyaviy ikki kishilik tasdiqni hech qachon almashtirmaydi.
5. **Sessiya:** staff uchun access ≤ 15 daqiqa (hozir 60), refresh ≤ 8 soat va MFA talab qiladi.
6. **Step-up (5 daqiqalik oyna):** W6/W7 (top-up tasdiqlash), W8/W16/W17 (adjustment), W13/W15/W19 (finalize/reversal),
   F3 (flag yoqish), I5 (eligibility bloki), B13 `cancel`/`finalize_fee`, S8 moliyaviy nizo qarori, telefon
   ko‘rsatadigan staff ko‘rinishlari, **va wave 7 dan**: `POST /admin/parcel-policies/{id}/confirm`.
7. **Jadvallar:** `staff_mfa_factors`, `staff_mfa_recovery_codes`, `staff_mfa_events` (append-only, sirsiz).
   Migratsiya raqami qaror qabul qilingandan keyin reyestrga kiritiladi.

## 4. Bitta `super_admin` holati (aniq tartib)

Muammo: tasdiqlovchi ham, tiklovchi ham “boshqa `super_admin`” bo‘lishi kerak, lekin pilotda bitta bo‘lishi mumkin.

**Taklif:**
1. **Launch shartiga qo‘shiladi:** production’da kamida **ikkita faol `super_admin`** bo‘lishi shart
   (go-live checklist bandi). Bu eng sodda va eng xavfsiz yechim.
2. Ikkinchi `super_admin` paydo bo‘lgunicha MFA **audit-only** rejimda ishlaydi (omil so‘raladi, jurnalga
   yoziladi, bloklamaydi) — ya’ni hech kim qulflanib qolmaydi.
3. **Break-glass** (faqat bitta super_admin qolganda): yangi omil serverda **`ELCHI_MFA_BREAK_GLASS_TOKEN`**
   (deploy vaqtida o‘rnatiladigan, bazada faqat hash) bilan ro‘yxatdan o‘tkaziladi. Har ishlatilishi
   `staff_mfa_events` ga yoziladi, barcha sessiyalar bekor qilinadi va operatorga alert ketadi.
   **Break-glass moliyaviy ikki kishilik tasdiqni chetlab o‘tmaydi** — u faqat kirishni tiklaydi.
4. **Bir xodim ikki tasdiqlovchi bo‘la olmaydi:** tasdiq/tiklashda `actor_user_id <> subject_user_id` DB CHECK
   bilan majburlanadi (Q49 dagi adjustment guard’i kabi).

## 5. Implementatsiya rejasi (qaror qabul qilingandan keyin)

| Qadam | Ish | Dalil |
|---|---|---|
| 1 | `pyotp==2.10.0` ni `requirements.txt` ga pin bilan qo‘shish | lockfile diff, import testi |
| 2 | Migratsiya: uchta jadval + `actor <> subject` CHECK + append-only guard | PG test: guard ishlaydi |
| 3 | `identity.mfa` servis funksiyalari (enroll, verify, step_up, recovery) | unit + PG testlari |
| 4 | Staff login oqimiga MFA bosqichi (audit-only flag bilan) | PG test: audit-only bloklamaydi |
| 5 | Step-up dekoratori pul va flag buyruqlariga | PG test: step-upsiz `403`, step-up bilan ruxsat |
| 6 | Staff access token TTL 15 daqiqa (faqat staff uchun) | v1 javob shakli o‘zgarmaydi (token — opaque) |
| 7 | Rollout: audit-only → finance/super_admin majburiy → barcha staff | ADR va readiness yangilanadi |

## 6. Qaror uchun savollar

1. **TOTP kutubxonasi:** `pyotp==2.10.0` (MIT, bog‘liqliksiz) qo‘shilsinmi yoki o‘z implementatsiyamiz yozilsinmi?
2. **WebAuthn** 2-bosqichda qolsinmi (`super_admin`/`finance` uchun keyin majburiy)?
3. **Step-up ro‘yxati** yuqoridagi 6-banddagi ro‘yxat bilan tasdiqlanadimi; 5 daqiqalik oyna to‘g‘rimi?
4. **Bitta super_admin:** “production’da kamida ikkita super_admin” talabi qabul qilinadimi? Break-glass tokeni
   kerakmi yoki audit-only rejim yetarlimi?
5. Rollout 3-bosqichi (barcha staff uchun majburiy) qachon — pilot ichida yoki keyin?
