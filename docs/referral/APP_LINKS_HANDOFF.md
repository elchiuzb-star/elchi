# Android App Links `/r/<kod>` — Android dasturchi topshirig‘i (5-bosqich, Q107)

**Kimga:** `android-app/` egasi (Android dasturchi; ism bu hujjatda ko‘rsatilmaydi).
**Holat:** topshiriq tayyor; **haqiqiy qurilmada tekshirilmagan.** `android-app/` va `frontend/` muzlatilgan — bu repoda
ular o‘zgartirilmagan va bu hujjat ularni o‘zgartirishga ruxsat emas; o‘zgarish Android egasining o‘z jarayonida.
Infra qismi: `INFRA_HANDOFF.md`.

## Repoda tayyor (dalil)
| Qism | Joy | Holat |
|---|---|---|
| Kodni qo‘lda kiritish | `mobile-app` → Profil → «Bonuslar va taklif kodi» / «Kredit va taklif kodi» | lokal testlar ✅ |
| Web’da `/r/<kod>` → kod login orqali saqlanadi, birinchisi yutadi, attribution almashtirilmaydi | `mobile-app/src/main.tsx`, `src/app/promo.ts` | lokal testlar ✅ |
| Haydovchi QR (qurilmada, faqat `share_url`) | `mobile-app/.../PromoScreens.tsx` `ReferralQr`, ADR-0024 | lokal testlar ✅, skrinshot |
| Tushuntirish sahifasi | `landing/r.html` + rewrite | deploy qilinmagan |

## Vazifalar
1. **applicationId’ni tarqatiladigan build’dan tasdiqlang.** `android-app/app.json` dagi `"package": "uz.elchi.app"` —
   faqat repo’dagi dalil, **yakuniy tasdiq emas**. Play’ga yuklanadigan AAB/APK dan tekshiring:
   `aapt2 dump badging <app.aab|apk> | grep package` yoki `bundletool dump manifest --bundle=<app.aab> | grep package`.
2. **Imzo sertifikati SHA-256.** Play App Signing ishlatilsa — Play Console → *Setup → App integrity → App signing key
   certificate* dagi SHA-256 (upload key emas). O‘zi imzolasa — release keystore:
   `keytool -list -v -keystore <release.jks> -alias <alias>`. **Debug keystore fingerprint’i production
   `assetlinks.json` ga yozilmaydi.** Upload va app signing kalitlari farq qilsa, ikkalasi kerak bo‘lsa ro‘yxatga
   qo‘shiladi — faqat haqiqiy tarqatish kaliti(lari).
3. **Intent filter** (Expo `app.json` → `android.intentFilters` yoki native manifest):
   `action VIEW`, `category DEFAULT` + `BROWSABLE`, `autoVerify: true`, `scheme: https`, `host: <HOST>`,
   `pathPrefix: /r/`. Ilova `/r/<kod>` ni o‘qiydi (8 belgi, alifbo `23456789ABCDEFGHJKMNPQRSTUVWXYZ`), foydalanuvchiga
   ko‘rsatadi va **uning tasdig‘i bilan** `POST /api/v2/referrals/attribution` (bitta harakat uchun bitta
   `Idempotency-Key`) chaqiradi. Kod login jarayonida yo‘qolmasin; mavjud attribution’ni almashtirmaydi (server birinchisini
   saqlaydi, Q106/Q117). Ro‘yxatdan o‘tishning o‘zi mukofot deb ko‘rsatilmaydi.
4. **`assetlinks.json`** qiymatlarini infra’ga bering (fayl `https://<HOST>/.well-known/assetlinks.json`):
```json
[{
  "relation": ["delegate_permission/common.handle_all_urls"],
  "target": {
    "namespace": "android_app",
    "package_name": "<1-banddagi tasdiqlangan applicationId>",
    "sha256_cert_fingerprints": ["<2-banddagi tarqatish kaliti SHA-256>"]
  }
}]
```
5. **Qurilmada tekshiruv** (haqiqiy Android qurilma, tarqatiladigan build bilan):
   - `adb shell pm get-app-links <applicationId>` → `<HOST>: verified`;
   - `adb shell pm verify-app-links --re-verify <applicationId>` (kerak bo‘lsa);
   - `adb shell am start -a android.intent.action.VIEW -d "https://<HOST>/r/AB2CD3EF"` → ilova ochiladi, kod
     ko‘rsatiladi, tasdiqlashsiz yuborilmaydi;
   - ilova o‘rnatilmagan qurilmada havola → `r.html` sahifasi;
   - login’siz ochilgan havola → login’dan keyin ham kod saqlangan.
   Natijalar (buyruq chiqishi, skrinshot/video) hisobotga ilova qilinadi.

## «Tayyor» deyish sharti
1–5 bandlar dalil bilan + `INFRA_HANDOFF.md` §9. Ungacha hech bir hisobot App Links yoki havolani «ishlayapti» deb
yozmaydi; QR yaratilgani bunga dalil emas (AGENTS.md §7: real qurilma sinovlari Android dasturchiga tegishli).
