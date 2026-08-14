# Google Play — release checklist and answers

Everything here is derived from what the code actually does (`app/models`,
`app/services`), not from a template. If the app changes, re-check this.

- **Package** `uz.elchi.app`
- **Privacy policy** https://www.elchigo.uz/privacy
- **Account deletion** https://www.elchigo.uz/delete-account
- **Signing** see [../android-app/RELEASE.md](../android-app/RELEASE.md)

---

## 1. Data safety form

Play rejects submissions whose declarations do not match observed behaviour, so
each row below names the code that causes it.

### Collected, linked to the user, NOT shared for ads

| Category → type | Purpose | Optional? | Source |
|---|---|---|---|
| Personal info → **Name** | App functionality | Optional | `users.full_name` |
| Personal info → **Phone number** | App functionality, Account management | Required | `users.phone`, `orders.sender_phone`, `orders.receiver_phone` |
| Personal info → **Other info** (passport / licence / vehicle registration images, drivers only) | App functionality, Fraud prevention | Required for drivers | `driver_documents.file_url` |
| Location → **Approximate location** | App functionality | Required | pickup/dropoff coordinates on `orders` |
| Location → **Precise location** | App functionality | Optional | `expo-location`, used to prefill the pickup pin |
| Photos and videos → **Photos** | App functionality | Optional | `orders.cargo_photo_url` |
| App activity → **Other actions** (orders, bids, ratings) | App functionality | Required | `orders`, `bids`, `ratings` |
| App info and performance → **Other** (device/session records) | App functionality, Security | Required | `refresh_sessions` |
| Device or other IDs → **Device or other IDs** (IP address) | Fraud prevention, Security | Required | `otp_codes.ip_address` |

### Answers to the yes/no questions

| Question | Answer | Why |
|---|---|---|
| Is data encrypted in transit? | **Yes** | HTTPS only; Caddy terminates TLS and redirects 80 → 443 |
| Can users request data deletion? | **Yes** | In-app: Settings → Hisobni o'chirish. Web: the URL above |
| Is any data shared with third parties? | **Yes** — see below | |
| Do you collect data from children under 13? | **No** | 18+ service |
| Has the app been independently security-reviewed? | **No** | Answer honestly; "no" is not penalised |

### Third parties to declare

- **Eskiz.uz** — phone number only, to deliver the SMS verification code (`app/services/sms_service.py`)
- **Yandex Maps** — address text and coordinates, for geocoding and map display (`app/services/yandex_maps_service.py`)
- **Other users of the app** — the assigned driver sees the pickup/dropoff address and phone; the client sees the driver's name and vehicle. Declare as sharing.

### Do NOT declare

- Payment info — payment is cash only; no card data is collected or stored
- Precise location in the background — location is foreground-only
- Advertising or analytics — neither SDK is present

---

## 2. Content rating

Answer the IARC questionnaire honestly. This app has no violence, no sexual
content, no gambling, no user-generated content shown publicly. Users do
exchange phone numbers within a transaction, so answer **yes** to "users can
share personal information with other users" — that is a normal marketplace
answer, not a problem.

Expected outcome: rated for a general or teen audience depending on territory.

## 3. App access (test credentials for the reviewer)

Login is by SMS OTP to an Uzbek number, which a Google reviewer cannot receive.
**You must provide working credentials or the review will fail.**

In Play Console → App access → "All or some functionality is restricted", give:

- A phone number the reviewer can use
- A note explaining that the code arrives by SMS

Practical options, best first:

1. **A demo account with a fixed code.** Add a server-side allowlist mapping one
   phone number to a fixed OTP, and give the reviewer that pair. Narrower and
   safer than a global bypass.
2. **A real Uzbek SIM you control**, with instructions to email you for the code.
   Slow and fragile — reviewers work across time zones.

> This is not yet built. It is the last functional gap before submission.

## 4. Store listing (Uzbek)

**App name** (max 30)

```
Elchi — shaharlararo pochta
```

**Short description** (max 80)

```
Jo'natmangizni o'sha yo'nalishga ketayotgan tekshirilgan haydovchi yetkazadi.
```

**Full description** (max 4000)

```
Elchi — shaharlararo yuk va pochta jo'natmalari uchun ilova. Har kuni minglab
mashina viloyatlar orasida bo'sh bagaj bilan qatnaydi. Elchi jo'natmangizni
aynan o'sha yo'nalish bo'ylab ketayotgan haydovchi bilan bog'laydi.

QANDAY ISHLAYDI

1. E'lon berasiz — qayerdan qayerga, nima jo'natilishi va qabul qiluvchining
   telefon raqami.
2. Takliflar keladi — o'sha yo'nalishda ishlaydigan haydovchilar o'z narxini
   yozadi.
3. Haydovchini tanlaysiz — reyting, avtomobil va narxni ko'rib tasdiqlaysiz.
4. Yetkazib beriladi — olindi, yo'lda, yetkazildi. Har bosqichda xabar olasiz.

JO'NATUVCHILAR UCHUN

• Hujjatlari tekshirilgan haydovchilar
• Bir nechta narx taklifi — savdolashish shart emas
• Jo'natma holatini kuzatib borish
• Yetkazilgach haydovchiga baho qoldirish
• Nizo chiqsa operator ko'rib chiqadi

HAYDOVCHILAR UCHUN

• Allaqachon rejalashtirgan safaringizdan daromad
• Faqat o'zingiz tanlagan yo'nalishlar bo'yicha buyurtmalar
• Narxni o'zingiz taklif qilasiz
• Bir martalik hujjat tekshiruvi

YO'NALISHLAR

Toshkent, Samarqand, Buxoro, Andijon, Farg'ona, Namangan, Qarshi, Nukus va
boshqa viloyat markazlari o'zaro.

To'lov hozircha faqat naqd pul orqali.

Maxfiylik siyosati: https://www.elchigo.uz/privacy
Hisobni o'chirish: https://www.elchigo.uz/delete-account
```

**Category** Maps & Navigation, or Business
**Tags** delivery, logistics, courier
**Contact email** — required and shown publicly on the listing

## 5. Graphic assets

| Asset | Spec | Status |
|---|---|---|
| App icon | 512×512 PNG, 32-bit | from `assets/icon.png` |
| Feature graphic | 1024×500 PNG/JPG, no alpha | **missing — required** |
| Phone screenshots | 2–8, min 320px, 16:9 or 9:16 | capture from the emulator |
| Tablet screenshots | optional | skip (`supportsTablet: false`) |

The feature graphic is mandatory and has no default. It appears at the top of
the listing.

## 6. Pre-submission checklist

- [x] Privacy policy live at a public URL
- [x] Account deletion in-app and on the web
- [x] Release keystore backed up outside `android/`
- [x] `versionCode` in `app.json` so prebuild cannot lose it
- [ ] Backend deployed with `DELETE /auth/me`
- [ ] Legal entity placeholders filled on the privacy and deletion pages
- [ ] Reviewer test credentials (section 3)
- [ ] Feature graphic
- [ ] Screenshots
- [ ] Signed AAB verified against the keystore fingerprint
- [ ] Play App Signing enrolled at first upload
- [ ] Google Play Console account ($25, one-off)
