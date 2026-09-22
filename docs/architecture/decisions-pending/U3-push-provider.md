# U3 — push provayderi: tanlov mezonlari va qaror uchun savollar

> ## ✅ QAROR QABUL QILINDI — 17.09.2026: **FCM** → [ADR-0022](../adr/0022-push-provider-fcm.md)
>
> Wave 8 da yozildi: `app/modules/communications/fcm.py` adapteri (payload allowlist chiqish nuqtasida
> majburlanadi, xato tasnifi outbox uchun), `20260917_0073` shifrlangan xom token ustuni,
> `app/core/secret_box.py` (AES-256-GCM). Testlar: `tests/contracts/test_fcm_adapter_adr0022.py` (13).
>
> **Yoqilmadi:** akkaunt ochilmadi, credential yo‘q, `DisabledPushProvider` amalda qolmoqda va K3 huquqiy
> tekshiruvi hamon ochiq. Tafsilot ADR-0022 dagi “Yoqishdan oldin bajarilishi shart” jadvalida.


**Holat:** ochiq. Hozirgi xulq **o‘zgartirilmadi**: push provayderi yo‘q, faqat ilova ichidagi xabarlar.
**Tayyorladi:** wave 7 agenti • **Sana:** 17.09.2026 • **Spec:** §15, §16 • **Bog‘liq:** ADR-0012 (outbox), Q82

## 1. Hozirgi holat (kod bilan tekshirilgan)

| Band | Holat |
|---|---|
| Provayder | `DisabledPushProvider` — `send()` har doim `push_provider_disabled` qaytaradi, tashqi chaqiruv yo‘q |
| Worker vazifasi | `communications.jobs.push_delivery_task` provayder o‘chiq bo‘lsa **darhol 0 qaytaradi**: lock olinmaydi, DB’ga yozilmaydi |
| Kanal | Faqat `in_app` (`notification_deliveries`) |
| Token saqlash | `device_tokens` da faqat **SHA-256** hash; xom token/subscription saqlanmaydi (U3 gacha) |
| Dublikat | `notification_dedup` (foydalanuvchi + dedup kaliti + oyna), Q83 bo‘yicha 10 daqiqa |
| Qayta urinish | Outbox `attempts` + backoff, `dead_lettered_at`; `/api/v2/admin/outbox` va retry endpointi bor |
| Kafolat | Push hech qachon tranzaksiya dalili emas (§16); uning ishlamasligi bron yoki pulga ta’sir qilmaydi (AC34) |
| Test | `tests/pg/ops/test_push_support_hardening_pg.py` — o‘chiq provayder hech nima yubormaydi va yozmaydi |

## 2. Tanlov mezonlari (to‘ldirish kerak)

| Mezon | Nima aniqlanishi kerak |
|---|---|
| **Xarajat** | Yuborilgan xabar soniga to‘lovmi yoki bepulmi; pilot hajmida (kuniga ~500–2000 xabar) oylik taxmin |
| **Platformalar** | Android (asosiy klient), mobil veb (mijoz), iOS (keyin) — provayder qaysilarini qoplaydi |
| **Yetkazish xulqi** | Navbat muddati, retry, “o‘chirilgan qurilma” xatosi, dublikat kafolati (at-least-once), feedback (invalid token) |
| **Uzatiladigan ma’lumot** | Payload faqat `PUSH_PAYLOAD_KEYS` bo‘ladi (telefon, ism, manzil, koordinata, kod yo‘q — §15). Provayderga **qanday ma’lumot chiqadi** va u qayerda saqlanadi |
| **Huquqiy** | K3/§17.7: shaxsiy ma’lumot chet el serveriga uzatiladimi; foydalanuvchi roziligi matni; provayder shartlari |
| **Texnik bog‘liqlik** | Yangi dependency (pin bilan), kalit/sertifikat saqlash (`crypto.derive_subkey`), xom token saqlash zarurati va uning shifrlanishi |
| **Chiqib ketish** | Provayderdan voz kechish qanchalik oson (adapter ortida; `PushProvider` porti allaqachon bor) |

## 3. Nomzodlar (faqat ro‘yxat — hech biri tanlanmagan, akkaunt ochilmagan)

| Nomzod | Kuchli tomoni | Ochiq savol |
|---|---|---|
| FCM (Firebase Cloud Messaging) | Android’da standart; xabar uzatish uchun alohida to‘lov yo‘q (spec §16 manbasi) | Google hisobi va ma’lumot uzatish shartlari; xom token saqlash |
| Web Push (VAPID) | Mobil veb uchun serversiz-provayderli; kalit o‘zimizda | iOS/Android brauzer qoplamasi; subscription obyektini saqlash |
| Expo Push | Expo klienti bilan bir xil ekotizim | Expo hisobiga bog‘liqlik; Android klienti muzlatilgan |

## 4. Qaror qabul qilingandan keyingi ish (reja)

1. ADR yoziladi (provayder, saqlanadigan ma’lumot, kalitlar, huquqiy xulosa).
2. Dependency pin bilan qo‘shiladi; adapter `PushProvider` porti ortida yoziladi.
3. Xom token/subscription saqlash kerak bo‘lsa — migratsiya (shifrlangan ustun yoki cheklangan ochiq ustun).
4. `push_delivery_task` yoqiladi; dedup, retry va DLQ allaqachon tayyor.
5. Testlar: provayder xatosi bron/pulga ta’sir qilmasligi (AC34), dublikat xabar yo‘qligi, payload allowlist’i.

## 5. Savollar

1. Qaysi provayder (FCM / Web Push / Expo / boshqa)?
2. Xom token saqlashga ruxsat beriladimi (shifrlangan holda) yoki hash bilan chegaralanamizmi?
3. Push payload’i faqat “bron holati o‘zgardi” darajasida qolsinmi (hozirgi allowlist) — matnsiz?
4. Huquqiy tekshiruv (K3) push provayderiga ma’lumot uzatishni qamrab oladimi?
