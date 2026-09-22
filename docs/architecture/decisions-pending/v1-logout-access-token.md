# §17.6 v1 qismi — logout va access token: qaror loyihasi

> ## ✅ QAROR QABUL QILINDI — 17.09.2026: **A-variant**
>
> Wave 8 da implementatsiya qilindi: `get_current_user` endi `sid` bo‘yicha sessiyani tekshiradi.
>
> **Bir aniqlashtirish bilan:** qaror *logout* haqida edi, *rotation* haqida emas. Qat’iy o‘qishda token
> yangilangach eski access token darhol o‘lardi va muzlatilgan Android klientining allaqachon yo‘lda bo‘lgan
> so‘rovlari 401 olardi. Shuning uchun `20260917_0072` `refresh_sessions.revoked_reason` ustunini qo‘shdi:
> `logout`/`admin_revoke` → v1 ham darhol rad etadi; `rotated` → eski access token o‘z muddatini yashab
> bo‘ladi (v2/WS avvalgidek qat’iy qoladi). 0072 dan oldingi qatorlarda sabab noma’lum → tugagan deb
> hisoblanadi (fail-closed), bu bir martalik ≤ 60 daqiqalik oyna.
>
> Testlar: `tests/test_v1_session_revocation.py` (7). Quyidagi matn qaror oldidan yozilgan tahlil.


**Holat:** ochiq (foydalanuvchi qarori). v1 xulqi **o‘zgartirilmadi**. • **Tayyorladi:** wave 7 agenti
**Sana:** 17.09.2026 • **Spec:** §17.6 (“refresh revoke qilingan sessiya real-time kanalda ham yopiladi”)
**Bog‘liq:** AGENTS §2 (v1 xulqi faqat tasdiqlangan qaror bilan o‘zgaradi), Q80 (U5 doirasi)

## 1. Hozirgi xulq (kod bilan tekshirilgan)

| Amal | Nima bo‘ladi |
|---|---|
| `POST /api/v1/auth/logout` | Faqat **refresh sessiyasi** bekor qilinadi (`refresh_sessions.is_revoked = true`) — [auth_service.py](../../../app/services/auth_service.py) |
| Amaldagi access token | **Amal qilishda davom etadi**, muddati tugaguncha — `access_token_expire_minutes = 60` |
| v1 tekshiruv | `get_current_user` faqat imzo, `type=access`, `sub` va `users.status='active'` ni tekshiradi; sessiya holatiga qaramaydi |
| v2 (wave 6 dan) | Access tokenda `sid` claim bor; v2 endpointlari va tracking WebSocket bekor qilingan sessiyani **darhol** rad etadi |
| Bloklangan akkaunt | Har ikkala yo‘lda darhol rad etiladi (`status != active`) |

Ya’ni ayni paytda: **v2 §17.6 ga mos, v1 mos emas.** v1 uchun eng yomon holat — telefon yo‘qolganda logout
bosilgan bo‘lsa ham, o‘g‘irlangan access token **60 daqiqagacha** ishlaydi.

## 2. Nega bu avtomatik o‘zgartirilmadi

v1 — muzlatilgan Android klientining kontrakti. `get_current_user` ga sessiya tekshiruvini qo‘shish javob
**kodini** o‘zgartiradi (ilgari `200` bo‘lgan so‘rov `401` bo‘ladi). AGENTS §2 bo‘yicha bu tasdiqlangan qaror
talab qiladi, shuning uchun bu yerda faqat variant va reja beriladi.

## 3. Variantlar

### A-variant (tavsiya) — v1 ham `sid` bo‘yicha tekshiriladi

- `get_current_user` (v1+v2 umumiy) `session_revoked(db, payload)` ni chaqiradi.
- **Faqat `sid` claim’i bor** tokenlar tekshiriladi. Wave 6 dan oldin chiqarilgan tokenlarda claim yo‘q —
  ular avvalgidek muddati tugaguncha ishlaydi (moslik oynasi ≤ 60 daqiqa).
- Xarajat: har autentifikatsiyalangan so‘rovga **bitta indeksli SELECT** (`refresh_sessions.jti` unique index).
  Kesh kerak emas; kerak bo‘lsa keyin Redis’ga ko‘chiriladi.
- Nosozlikda xulq: DB javob bermasa so‘rov allaqachon `500` bo‘ladi (`get_db` ham DB’ga bog‘liq) — yangi
  “fail-open” yo‘l ochilmaydi.
- Eski klient ta’siri: logout’dan keyin ilova baribir qayta login qiladi; amalda farq — logoutdan keyin eski
  token bilan yuborilgan so‘rov endi `401` oladi (ilova refresh/login oqimini boshlaydi).

### B-variant — faqat “barcha qurilmalardan chiqish”

- Yangi `POST /api/v1/auth/logout-all` (yoki admin amali): foydalanuvchining **barcha** sessiyalari bekor
  qilinadi va `users.tokens_valid_from` (yangi ustun) yangilanadi; undan oldin chiqarilgan tokenlar rad etiladi.
- Oddiy logout avvalgidek qoladi (faqat refresh).
- Ustunligi: kundalik xulq o‘zgarmaydi; “telefonim yo‘qoldi” ssenariysi yopiladi.
- Kamchiligi: oddiy logout hamon 60 daqiqalik oyna qoldiradi (§17.6 to‘liq bajarilmaydi).

### C-variant — hech nima o‘zgartirmaslik

- v1 access token TTL’ini qisqartirish (60 → masalan 15 daqiqa) bilan cheklanish.
- Ustunligi: kod o‘zgarmaydi. Kamchiligi: barcha klientlarda refresh chastotasi oshadi; §17.6 hamon bajarilmaydi.

## 4. A-variant uchun implementatsiya rejasi

| Band | Reja |
|---|---|
| O‘zgaradigan kod | `app/api/deps.py::get_current_user` (bitta tekshiruv qo‘shiladi) |
| Saqlash | Yangi jadval **kerak emas**: `refresh_sessions.jti` allaqachon unique indeksli |
| So‘rov xarajati | +1 `SELECT … WHERE jti = :sid` (indeks bo‘yicha); o‘lchov: wave 6 access log `duration_ms` bilan solishtiriladi |
| Eski klientlar | `sid` yo‘q tokenlar tegilmaydi → bir martalik ≤ 60 daqiqalik o‘tish oynasi |
| “Barcha qurilmalardan chiqish” | Alohida band: `logout-all` yoki admin amali (B-variant bilan birlashtirilishi mumkin) |
| Testlar | (1) logout → eski access token `401`; (2) `sid` siz token ishlaydi; (3) boshqa qurilma sessiyasi ta’sirlanmaydi; (4) bloklangan akkaunt avvalgidek `403`; (5) v1 javob **shakli** o‘zgarmaydi (envelope bir xil) |
| Rollback | Bitta `if` — flag bilan o‘chirib qo‘yish mumkin |

## 5. Xavfsizlik bahosi

- **A-variant** §17.6 ni to‘liq bajaradi va o‘g‘irlangan token oynasini 60 daqiqadan ~0 ga tushiradi. Xavfi:
  eski klient logout’dan keyin xato ko‘rsatishi mumkin (lekin u allaqachon logout qilgan).
- **B-variant** eng og‘ir ssenariyni (qurilma yo‘qolishi) yopadi, kundalik oynani qoldiradi.
- **C-variant** faqat oynani qisqartiradi; “bekor qilingan sessiya” tushunchasi v1’da yo‘q bo‘lib qolaveradi.

**Tavsiya: A-variant** (kerak bo‘lsa B bilan birga). Xarajati bitta indeksli o‘qish, moslik oynasi bir martalik.

## 6. Savol

**v1 access token logout’dan keyin darhol bekor qilinsinmi (A), faqat “barcha qurilmalardan chiqish” qo‘shilsinmi
(B), yoki hozircha o‘zgarmasinmi (C)?** Tasdiqlanmaguncha v1 xulqi hozirgicha qoladi.
