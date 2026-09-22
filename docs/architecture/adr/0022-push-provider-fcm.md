# ADR-0022: Push provayderi — FCM

**Holat:** Accepted (foydalanuvchi qarori, 17.09.2026; U3/Q82 yopildi) • **Sana:** 17.09.2026 • **Muallif:** A7, wave 8
**Spec:** §15 (payload allowlist), §16 (push hech qachon tranzaksiya dalili emas), §17.7 • **Bog‘liq:** ADR-0012 (outbox), ADR-0018 (derived keys), Q82, Q83 (dedup 10 daqiqa), K3 (hosting/huquq), AC34

## Kontekst

Wave 3 dan beri push porti (`communications.providers.PushProvider`) bor, lekin provayder tanlanmagani uchun
`DisabledPushProvider` o‘rnatilgan: `push_delivery_task` hech nima yozmaydi va yagona kanal — ilova ichidagi
inbox. `device_tokens` faqat token’ning SHA-256 hashini saqlaydi, chunki yuboradigan joy yo‘q edi.

Nomzodlar U3 hujjatida taqqoslangan edi (FCM, Web Push/VAPID, Expo).

## Qaror

1. **Provayder — FCM (Firebase Cloud Messaging), HTTP v1 API.** Sabab: Android birlamchi klient, xabar
   uzatish uchun alohida to‘lov yo‘q, iOS va veb ham shu orqali qoplanadi, adapter ortida almashtirish oson.
2. **Xom token shifrlangan holda saqlanadi.** FCM token’ning o‘zini talab qiladi, shuning uchun uni saqlamay
   iloji yo‘q. `device_tokens.token_cipher` — AES-256-GCM (`app/core/secret_box.py`), kalit
   `crypto.derive_subkey(secret_key, "push-token")` dan, AAD sifatida qurilmaning `public_id` si ishlatiladi
   (boshqa qatorga ko‘chirilgan shifrmatn ochilmaydi). `token_hash` qidiruv kaliti bo‘lib qoladi.
   `token_key_version` kalit rotatsiyasini qator-baqator qilish imkonini beradi.
3. **Payload — faqat kalit, matn emas.** FCM so‘rovida `notification` bloki **yo‘q**: OS ko‘rsatadigan sarlavha
   real matn bo‘lishi kerak bo‘lardi. Faqat `data` yuboriladi va u `PUSH_PAYLOAD_KEYS` bilan **chiqish
   nuqtasida** tekshiriladi (`fcm.build_request` `ValueError` bilan rad etadi) — telefon, ism, manzil,
   koordinata, kod hech qachon chiqmaydi (§15).
4. **Xato tasnifi** (`fcm.classify`): `UNREGISTERED`/`INVALID_ARGUMENT`/`SENDER_ID_MISMATCH` → qurilma
   o‘chgan, qayta urinilmaydi; `UNAVAILABLE`/`INTERNAL`/`QUOTA_EXCEEDED`/429/5xx → outbox backoff bilan qayta
   uradi; 401/403 → bizning credential xato, qurilma aybdor emas va qayta urinish foydasiz.
5. **Yoqish alohida qadam.** Adapter credential va transport berilmaguncha `enabled = False` va `send`
   `fcm_not_configured` qaytaradi. Kodni import qilish hech nimani yoqmaydi.

## Yoqishdan oldin bajarilishi shart (hali ochiq)

| Band | Kim |
|---|---|
| **K3 huquqiy tekshiruv:** shaxsiy ma’lumot (qurilma tokeni + bron holati) Google serverlariga uzatilishi, foydalanuvchi roziligi matni, provayder shartlari | Foydalanuvchi + yurist |
| Firebase loyihasi va service account krediti (**agent ochmaydi**) | Ops |
| `ELCHI_PUSH_*` sozlamalari va kalit saqlash | Ops |
| Klient tomonidan token ro‘yxatdan o‘tkazish (xom token bilan) — `android-app/` muzlatilgan, shuning uchun bu `mobile-app` va keyingi Android relizi | A8 / Android dasturchi |

Shu bandlar yopilmaguncha provayder o‘rnatilmaydi va `DisabledPushProvider` amalda qoladi.

## Oqibatlar

- **Dependency:** `cryptography` endi to‘g‘ridan-to‘g‘ri ishlatiladi (ilgari `python-jose[cryptography]` orqali
  tranzitiv kelardi) va `requirements.txt` da pin qilindi. Yangi tashqi paket qo‘shilmadi.
- `app/contracts/` dependency-free bo‘lib qoladi: shifrlash yordamchisi `app/core/secret_box.py` da (AGENTS §4).
- 0073 dan oldin ro‘yxatdan o‘tgan qurilmalarda `token_cipher IS NULL` — ularga push yuborib bo‘lmaydi va bu
  **skip**, xato emas; qurilma qayta ro‘yxatdan o‘tganda to‘ladi.
- Push ishlamasligi bron yoki pulga ta’sir qilmaydi (AC34) — bu o‘zgarmadi.
- Dedup (Q83, 10 daqiqa), retry/DLQ va `notification_deliveries` allaqachon tayyor; ular qayta yozilmadi.

## Rad etilgan variantlar

- **Web Push (VAPID):** kalit o‘zimizda qolardi, lekin Android ilovasida ishlamaydi — birlamchi klient aynan u.
- **Expo Push:** Expo ekotizimiga bog‘lanish; Android klienti muzlatilgan va Expo ishlatmaydi.
- **Xom token’ni saqlamaslik:** FCM bilan texnik jihatdan imkonsiz. Shuning uchun shifrlash tanlandi.
